"""Read-only calibration and decision-threshold audit for the NorthStar early-risk model.

Writes ONLY into the directory containing this script. Never saves models, never touches the
database, never writes into ml/, data/, docs/ or backend/. Run from the project root:

    set PYTHONDONTWRITEBYTECODE=1
    .venv\\Scripts\\python.exe reports\\calibration_audit_20261010T012653Z\\audit_calibration.py

Stages
  0  load canonical data + split exactly as tests/test_canonical_integrity.py does
  1  baseline: deployed artifact reproduces recorded test metrics (gate)
  2  reconstruct the never-saved train-only XGBoost used for threshold selection (gate:
     must reproduce the recorded validation metrics); verify the refit reproduces the
     deployed artifact (label-free comparison of scores)
  3  validation-only calibration assessment + CV-fitted calibrators (within validation)
  4  validation-only threshold analysis, nested CV honest estimate, bootstrap stability
  5  refit-transfer simulation (train/validation only) + code_presentation sensitivity
  -- validation results are FROZEN to disk here --
  6  post-freeze descriptive check of deployed raw scores on test (no fitting/selection)
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import brentq  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import log_loss, roc_auc_score  # noqa: E402
from sklearn.model_selection import RepeatedStratifiedKFold  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from ml.features.build_dataset import FEATURES, TARGET, split_by_presentation  # noqa: E402
from ml.supervised.train import (make_preprocessor, metrics as project_metrics,  # noqa: E402
                                 model_specs, select_threshold)

SEED = 20261010
N_BOOT = 1000
EPS = 1e-15
RESULTS: dict = {"meta": {
    "run_utc": datetime.now(timezone.utc).isoformat(),
    "python": platform.python_version(),
    "numpy": np.__version__, "pandas": pd.__version__,
    "sklearn": __import__("sklearn").__version__, "xgboost": __import__("xgboost").__version__,
    "seed": SEED, "bootstrap_resamples": N_BOOT,
}}


def out(name: str) -> Path:
    path = OUT / name
    assert path.parent == OUT, "audit must only write into its own directory"
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- metrics helpers
def op_metrics(y, p, t) -> dict:
    y = np.asarray(y).astype(int)
    pred = (np.asarray(p) >= t).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    f2 = 5 * prec * rec / (4 * prec + rec) if prec + rec else 0.0
    return {"threshold": float(t), "flagged": tp + fp, "flag_rate": (tp + fp) / len(y),
            "precision": prec, "recall": rec, "f1": f1, "f2": f2, "specificity": spec,
            "fpr": 1 - spec, "fnr": 1 - rec, "accuracy": (tp + tn) / len(y),
            "tn": tn, "fp": fp, "fn": fn, "tp": tp,
            "alerts_per_true_positive": (tp + fp) / tp if tp else float("inf")}


def candidate_thresholds(p):
    return np.unique(np.r_[np.linspace(0.05, 0.95, 91), p])


def f2_curve(y, p, cands):
    """Vectorised F2 for every candidate threshold (flag = p >= t)."""
    y = np.asarray(y).astype(int); p = np.asarray(p)
    order = np.argsort(p); ps = p[order]; ys = y[order]
    pos_total = ys.sum()
    # number of rows with p >= t  and positives among them
    idx = np.searchsorted(ps, cands, side="left")
    pos_below = np.r_[0, np.cumsum(ys)][idx]
    tp = pos_total - pos_below
    flagged = len(p) - idx
    fp = flagged - tp; fn = pos_total - tp
    denom = 5 * tp + 4 * fn + fp
    return np.where(denom > 0, 5 * tp / np.maximum(denom, 1), 0.0)


def fast_select_threshold(y, p):
    cands = candidate_thresholds(p)
    f2 = f2_curve(y, p, cands)
    best = f2.max()
    t = cands[np.flatnonzero(f2 == best).max()]  # same tie-break as train.select_threshold
    return float(t), float(best)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    ph = k / n; d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d; h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (float(c - h), float(c + h))


def reliability_table(y, p, strategy: str, n_bins: int = 10) -> pd.DataFrame:
    y = np.asarray(y).astype(int); p = np.asarray(p)
    if strategy == "uniform":
        edges = np.linspace(0, 1, n_bins + 1)
    else:  # quantile, equal-count
        edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
        edges[0], edges[-1] = 0.0, 1.0
    b = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    rows = []
    for i in range(len(edges) - 1):
        m = b == i; n = int(m.sum()); k = int(y[m].sum())
        lo, hi = wilson(k, n)
        rows.append({"bin": i, "lower": edges[i], "upper": edges[i + 1], "n": n, "positives": k,
                     "mean_predicted": float(p[m].mean()) if n else float("nan"),
                     "observed_rate": k / n if n else float("nan"),
                     "observed_ci95_low": lo, "observed_ci95_high": hi,
                     "gap_pred_minus_obs": float(p[m].mean() - k / n) if n else float("nan"),
                     "obs_within_ci": bool(lo <= p[m].mean() <= hi) if n else None})
    return pd.DataFrame(rows)


def ece(y, p, strategy="uniform", n_bins=10) -> float:
    t = reliability_table(y, p, strategy, n_bins)
    t = t[t.n > 0]
    return float((t.n * (t.mean_predicted - t.observed_rate).abs()).sum() / t.n.sum())


def cal_slope_intercept(y, p) -> dict:
    x = logit(p).reshape(-1, 1)
    lr = LogisticRegression(penalty=None, max_iter=1000).fit(x, y)
    # calibration-in-the-large: alpha such that mean(sigmoid(logit p + alpha)) == prevalence
    lp = logit(p); prev = float(np.mean(y))
    citl = brentq(lambda a: np.mean(1 / (1 + np.exp(-(lp + a)))) - prev, -10, 10)
    return {"calibration_slope": float(lr.coef_[0][0]), "calibration_intercept": float(lr.intercept_[0]),
            "calibration_in_the_large_logit_shift": float(citl)}


def prob_metrics(y, p) -> dict:
    y = np.asarray(y).astype(int); p = np.asarray(p)
    prev = float(y.mean())
    brier = float(np.mean((p - y) ** 2)); brier_ref = prev * (1 - prev)
    return {"n": int(len(y)), "positives": int(y.sum()), "prevalence": prev,
            "mean_predicted": float(p.mean()), "brier": brier,
            "brier_prevalence_baseline": brier_ref, "brier_skill_score": 1 - brier / brier_ref,
            "log_loss": float(log_loss(y, np.clip(p, EPS, 1 - EPS), labels=[0, 1])),
            "log_loss_prevalence_baseline": float(-(prev * np.log(prev) + (1 - prev) * np.log(1 - prev))),
            "roc_auc": float(roc_auc_score(y, p)),
            "ece_uniform10": ece(y, p, "uniform"), "ece_quantile10": ece(y, p, "quantile"),
            **cal_slope_intercept(y, p)}


def bootstrap_ci(y, p, fn, n=N_BOOT, seed=SEED) -> dict:
    rng = np.random.default_rng(seed); y = np.asarray(y); p = np.asarray(p)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        vals.append(fn(y[i], p[i]))
    vals = pd.DataFrame(vals)
    return {c: [float(vals[c].quantile(0.025)), float(vals[c].quantile(0.975))] for c in vals}


def fit_xgb(X, y, pos_weight):
    pipe = Pipeline([("preprocess", make_preprocessor()), ("model", model_specs(pos_weight)["xgboost"])])
    return pipe.fit(X, y)


# --------------------------------------------------------------------------- SVG
def reliability_svg(series: list[tuple[str, str, pd.DataFrame]], title: str, path: Path):
    W, H, M = 520, 520, 60; S = W - 2 * M
    X = lambda v: M + v * S; Y = lambda v: H - M - v * S
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H + 30 * len(series)}" '
             f'font-family="sans-serif" font-size="12"><rect width="100%" height="100%" fill="white"/>',
             f'<text x="{W/2}" y="24" text-anchor="middle" font-size="14">{title}</text>',
             f'<rect x="{M}" y="{M}" width="{S}" height="{S}" fill="none" stroke="#999"/>',
             f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="#bbb" stroke-dasharray="4 4"/>']
    for v in np.linspace(0, 1, 6):
        parts += [f'<text x="{X(v)}" y="{H - M + 16}" text-anchor="middle">{v:.1f}</text>',
                  f'<text x="{M - 8}" y="{Y(v) + 4}" text-anchor="end">{v:.1f}</text>']
    parts += [f'<text x="{W/2}" y="{H - 18}" text-anchor="middle">Mean predicted score in bin</text>',
              f'<text x="16" y="{H/2}" text-anchor="middle" transform="rotate(-90 16 {H/2})">Observed positive rate (95% Wilson CI)</text>']
    for k, (label, colour, t) in enumerate(series):
        t = t[t.n > 0]
        pts = " ".join(f"{X(r.mean_predicted):.1f},{Y(r.observed_rate):.1f}" for r in t.itertuples())
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.5"/>')
        for r in t.itertuples():
            parts.append(f'<line x1="{X(r.mean_predicted):.1f}" y1="{Y(r.observed_ci95_low):.1f}" '
                         f'x2="{X(r.mean_predicted):.1f}" y2="{Y(r.observed_ci95_high):.1f}" stroke="{colour}"/>')
            parts.append(f'<circle cx="{X(r.mean_predicted):.1f}" cy="{Y(r.observed_rate):.1f}" '
                         f'r="{2 + 6 * np.sqrt(r.n / t.n.max()):.1f}" fill="{colour}" fill-opacity="0.6"/>')
        ly = H + 10 + 26 * k
        parts += [f'<rect x="{M}" y="{ly}" width="14" height="14" fill="{colour}"/>',
                  f'<text x="{M + 20}" y="{ly + 12}">{label}</text>']
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


# =========================================================================== stage 0
canonical_path = ROOT / "data/processed/student_training_dataset.csv"
canonical = pd.read_csv(canonical_path).rename(columns={"source_student_id": "id_student"})
train, valid, test = split_by_presentation(canonical)
X_tr, y_tr = train[FEATURES], train[TARGET].astype(int)
X_va, y_va = valid[FEATURES], valid[TARGET].astype(int)
X_te = test[FEATURES]
evaluation = json.loads((ROOT / "data/processed/supervised_evaluation.json").read_text(encoding="utf-8"))
registry = json.loads((ROOT / "ml/saved_models/registry.json").read_text(encoding="utf-8"))
RESULTS["data"] = {
    "canonical_rows": int(len(canonical)), "canonical_sha256": sha256(canonical_path),
    "partitions": {name: {"rows": int(len(df)), "presentations": sorted(df.code_presentation.unique()),
                          "positives": int(df[TARGET].sum()), "prevalence": float(df[TARGET].mean())}
                   for name, df in (("train", train), ("validation", valid))},
    "test_rows_only": int(len(test)), "test_presentations": sorted(test.code_presentation.unique()),
    "recorded_counts": evaluation["counts"],
}
assert RESULTS["data"]["canonical_rows"] == 26447
assert evaluation["counts"] == {"train": len(train), "validation": len(valid), "test": len(test)}
pos_weight = float((len(y_tr) - y_tr.sum()) / max(1, y_tr.sum()))
RESULTS["data"]["train_pos_weight"] = pos_weight

# =========================================================================== stage 1
artifact_path = ROOT / "ml/saved_models/xgboost.joblib"
artifact = joblib.load(artifact_path)
deployed = artifact["pipeline"]
selected = next(m for m in registry["models"] if m["selected"])
assert selected["name"] == "xgboost" and evaluation["selected_model"] == "xgboost"
assert list(deployed.classes_) == [0, 1]
thr = float(artifact["threshold"])
deployed_test_scores = deployed.predict_proba(X_te)[:, 1]
repro_test = project_metrics(test[TARGET].astype(int), deployed_test_scores, thr)
rec_test = evaluation["test_results"]["xgboost"]
keys = ["accuracy", "precision", "recall", "f1", "f2", "roc_auc"]
baseline_ok = (all(abs(repro_test[k] - rec_test[k]) < 1e-9 for k in keys)
               and repro_test["confusion_matrix"] == rec_test["confusion_matrix"])
RESULTS["baseline"] = {
    "artifact_sha256": sha256(artifact_path), "artifact_keys": sorted(artifact.keys()),
    "artifact_threshold_exact": thr, "evaluation_selected_threshold": evaluation["selected_threshold"],
    "registry_threshold_rounded": selected["metrics"]["threshold"],
    "classes": [int(c) for c in deployed.classes_],
    "recorded_test": rec_test, "reproduced_test": repro_test, "reproduced_exactly": baseline_ok,
}
if not baseline_ok:
    out("results.json").write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
    raise SystemExit("BASELINE MISMATCH - stopping before calibration analysis")

# =========================================================================== stage 2
stage1 = fit_xgb(X_tr, y_tr, pos_weight)           # never persisted
val_p = stage1.predict_proba(X_va)[:, 1]
t_proj, chosen = select_threshold(y_va.to_numpy(), val_p)
rec_val = evaluation["validation_results"]["xgboost"]["validation"]
repro_val = project_metrics(y_va, val_p, t_proj)
t_fast, f2_fast = fast_select_threshold(y_va.to_numpy(), val_p)
stage1_ok = (abs(t_proj - thr) < 1e-12 and repro_val["confusion_matrix"] == rec_val["confusion_matrix"]
             and all(abs(repro_val[k] - rec_val[k]) < 1e-9 for k in keys))
refit = fit_xgb(pd.concat([X_tr, X_va]), pd.concat([y_tr, y_va]), pos_weight)  # never persisted
refit_te = refit.predict_proba(X_te)[:, 1]          # label-free comparison only
RESULTS["reconstruction"] = {
    "stage1_threshold": t_proj, "matches_artifact_threshold": bool(abs(t_proj - thr) < 1e-12),
    "recorded_validation": rec_val, "reproduced_validation": repro_val,
    "stage1_reproduced_exactly": stage1_ok,
    "fast_selector_agrees": bool(abs(t_fast - t_proj) < 1e-12 and abs(f2_fast - chosen["validation_f2"]) < 1e-12),
    "refit_reproduces_deployed_scores_max_abs_diff": float(np.max(np.abs(refit_te - deployed_test_scores))),
}
if not stage1_ok:
    out("results.json").write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
    raise SystemExit("STAGE-1 RECONSTRUCTION MISMATCH - stopping")

# in-sample illustration: deployed model scored on its own validation training rows
dep_val = deployed.predict_proba(X_va)[:, 1]
RESULTS["in_sample_warning"] = {
    "note": "Deployed model was fit on train+validation; these validation numbers are in-sample and NOT valid for calibration or threshold assessment.",
    "deployed_on_validation_in_sample": {**{k: v for k, v in prob_metrics(y_va, dep_val).items()},
                                         "at_current_threshold": op_metrics(y_va, dep_val, thr)},
}

# orientation checks (validation, out-of-sample stage-1 scores)
dec = pd.qcut(val_p, 10, labels=False, duplicates="drop")
dec_rates = pd.Series(y_va.to_numpy()).groupby(dec).mean()
RESULTS["orientation"] = {
    "roc_auc_validation": float(roc_auc_score(y_va, val_p)),
    "mean_score_positives": float(val_p[y_va.to_numpy() == 1].mean()),
    "mean_score_negatives": float(val_p[y_va.to_numpy() == 0].mean()),
    "decile_event_rates_low_to_high": [float(v) for v in dec_rates],
    "decile_rates_monotone_nondecreasing": bool(np.all(np.diff(dec_rates.to_numpy()) >= 0)),
}

# =========================================================================== stage 3
yv = y_va.to_numpy()
raw_metrics = prob_metrics(yv, val_p)
raw_ci = bootstrap_ci(yv, val_p, lambda y, p: {
    "brier": float(np.mean((p - y) ** 2)), "log_loss": float(log_loss(y, np.clip(p, EPS, 1 - EPS), labels=[0, 1])),
    "ece_uniform10": ece(y, p, "uniform"), "ece_quantile10": ece(y, p, "quantile"),
    "roc_auc": float(roc_auc_score(y, p)), "mean_pred_minus_prev": float(p.mean() - y.mean())})
rel_u = reliability_table(yv, val_p, "uniform"); rel_q = reliability_table(yv, val_p, "quantile")
rel_u.to_csv(out("validation_reliability_uniform10_raw.csv"), index=False)
rel_q.to_csv(out("validation_reliability_quantile10_raw.csv"), index=False)

# zero-parameter correction: undo the scale_pos_weight odds inflation (no fitting)
def undo_weight(p, w=pos_weight):
    return p / (p + w * (1 - p))

# CV calibrators within validation (repeated stratified 5-fold, out-of-fold pooled)
rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=SEED)
per_repeat = {"platt": [], "isotonic": []}
oof_first = {}
splits = list(rskf.split(val_p.reshape(-1, 1), yv))
for r in range(20):
    oof = {"platt": np.zeros_like(val_p), "isotonic": np.zeros_like(val_p)}
    for tr_i, te_i in splits[r * 5:(r + 1) * 5]:
        pl = LogisticRegression(penalty=None, max_iter=1000).fit(logit(val_p[tr_i]).reshape(-1, 1), yv[tr_i])
        oof["platt"][te_i] = pl.predict_proba(logit(val_p[te_i]).reshape(-1, 1))[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(val_p[tr_i], yv[tr_i])
        oof["isotonic"][te_i] = iso.predict(val_p[te_i])
    for k in oof:
        m = prob_metrics(yv, oof[k]); per_repeat[k].append(m)
    if r == 0:
        oof_first = oof
cal_summary = {"raw": raw_metrics, "raw_bootstrap_ci95": raw_ci,
               "weight_undo_zero_param": prob_metrics(yv, undo_weight(val_p))}
for k, rows in per_repeat.items():
    df = pd.DataFrame(rows)
    cal_summary[f"{k}_cv_oof"] = {c: {"mean": float(df[c].mean()), "sd_across_repeats": float(df[c].std())}
                                 for c in df.columns if df[c].dtype.kind == "f"}
# full-validation Platt fit, for interpretation of the current cutoff only (not deployed)
platt_full = LogisticRegression(penalty=None, max_iter=1000).fit(logit(val_p).reshape(-1, 1), yv)
cal_summary["platt_full_validation_params"] = {"a_slope": float(platt_full.coef_[0][0]),
                                                "b_intercept": float(platt_full.intercept_[0])}
cal_summary["current_threshold_on_platt_scale"] = float(
    platt_full.predict_proba(logit(np.array([thr])).reshape(-1, 1))[0, 1])
cal_summary["current_threshold_on_weight_undo_scale"] = float(undo_weight(np.array([thr]))[0])
iso_full = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(val_p, yv)
cal_summary["current_threshold_on_isotonic_scale"] = float(iso_full.predict([thr])[0])
cal_summary["isotonic_distinct_output_levels_full_fit"] = int(len(np.unique(iso_full.predict(val_p))))
RESULTS["calibration_validation"] = cal_summary
reliability_table(yv, oof_first["platt"], "uniform").to_csv(out("validation_reliability_uniform10_platt_oof.csv"), index=False)
reliability_table(yv, oof_first["isotonic"], "uniform").to_csv(out("validation_reliability_uniform10_isotonic_oof.csv"), index=False)
reliability_table(yv, undo_weight(val_p), "uniform").to_csv(out("validation_reliability_uniform10_weight_undo.csv"), index=False)
reliability_svg([("Raw stage-1 XGBoost scores", "#d62728", rel_u),
                 ("Platt, 5-fold OOF (repeat 1)", "#1f77b4", reliability_table(yv, oof_first["platt"], "uniform")),
                 ("Isotonic, 5-fold OOF (repeat 1)", "#2ca02c", reliability_table(yv, oof_first["isotonic"], "uniform"))],
                f"Validation 2014B reliability (n={len(yv)}, 10 equal-width bins)", out("reliability_validation.svg"))

# per-module calibration-in-the-large (validation)
mods = []
for mod, g in valid.assign(p=val_p).groupby("code_module"):
    yy = g[TARGET].to_numpy()
    lo, hi = wilson(int(yy.sum()), len(yy))
    mods.append({"code_module": mod, "n": len(g), "observed_rate": float(yy.mean()), "obs_ci95": [lo, hi],
                 "mean_raw_score": float(g.p.mean()), "mean_platt_oof": float(oof_first["platt"][valid.index.get_indexer(g.index)].mean()),
                 "auc": float(roc_auc_score(yy, g.p)) if 0 < yy.sum() < len(yy) else None})
RESULTS["calibration_validation_by_module"] = mods

# =========================================================================== stage 4
grid = sorted(set(np.round(np.arange(0.05, 0.951, 0.05), 2).tolist()) | {thr})
grid_rows = [op_metrics(yv, val_p, t) for t in grid]
pd.DataFrame(grid_rows).to_csv(out("validation_threshold_grid.csv"), index=False)

cands = candidate_thresholds(val_p)
def best_where(cond_fn, key):
    rows = [op_metrics(yv, val_p, t) for t in cands]
    ok = [r for r in rows if cond_fn(r)]
    return max(ok, key=key) if ok else None
allrows = pd.DataFrame([op_metrics(yv, val_p, t) for t in cands])
def pick(df, sort_col, asc=False):
    return df.sort_values([sort_col, "threshold"], ascending=[asc, False]).iloc[0].to_dict() if len(df) else None
scen = {
    "current_F2_max (deployed)": op_metrics(yv, val_p, thr),
    "F1_max": pick(allrows, "f1"),
    "Youden_J_max": pick(allrows.assign(j=allrows.recall + allrows.specificity - 1), "j"),
    "recall>=0.95_highest_threshold": pick(allrows[allrows.recall >= 0.95], "threshold"),
    "recall>=0.90_highest_threshold": pick(allrows[allrows.recall >= 0.90], "threshold"),
    "recall>=0.80_highest_threshold": pick(allrows[allrows.recall >= 0.80], "threshold"),
    "alerts<=50%_of_cohort_max_recall": pick(allrows[allrows.flag_rate <= 0.50], "recall"),
    "alerts<=40%_of_cohort_max_recall": pick(allrows[allrows.flag_rate <= 0.40], "recall"),
    "alerts<=30%_of_cohort_max_recall": pick(allrows[allrows.flag_rate <= 0.30], "recall"),
    "default_0.5": op_metrics(yv, val_p, 0.5),
}
for v in scen.values():
    if v:
        v.pop("j", None)
RESULTS["threshold_scenarios_validation"] = scen
pd.DataFrame([{"scenario": k, **v} for k, v in scen.items() if v]).to_csv(out("validation_threshold_scenarios.csv"), index=False)

f2c = f2_curve(yv, val_p, cands)
near = cands[f2c >= f2c.max() - 0.005]
RESULTS["threshold_f2_flatness"] = {"f2_max": float(f2c.max()), "thresholds_within_0.005_of_max": [float(near.min()), float(near.max())],
                                    "flag_rate_range_within_0.005": [float((val_p >= near.max()).mean()), float((val_p >= near.min()).mean())]}

# bootstrap CIs at the current threshold
RESULTS["current_threshold_bootstrap_ci95"] = bootstrap_ci(yv, val_p, lambda y, p: {
    k: op_metrics(y, p, thr)[k] for k in ("precision", "recall", "f2", "specificity", "flag_rate")})

# bootstrap stability of the F2-optimal threshold itself
rng = np.random.default_rng(SEED)
boot_t = []
for _ in range(N_BOOT):
    i = rng.integers(0, len(yv), len(yv))
    boot_t.append(fast_select_threshold(yv[i], val_p[i])[0])
boot_t = np.array(boot_t)
RESULTS["f2_threshold_bootstrap"] = {"median": float(np.median(boot_t)), "ci95": [float(np.quantile(boot_t, .025)), float(np.quantile(boot_t, .975))],
                                     "iqr": [float(np.quantile(boot_t, .25)), float(np.quantile(boot_t, .75))],
                                     "flag_rate_at_ci_bounds": [float((val_p >= np.quantile(boot_t, .975)).mean()), float((val_p >= np.quantile(boot_t, .025)).mean())]}

# nested CV: choose F2 threshold on 4/5 of validation, evaluate on held-out 1/5
nest = []
for tr_i, te_i in splits:
    t_i, _ = fast_select_threshold(yv[tr_i], val_p[tr_i])
    m = op_metrics(yv[te_i], val_p[te_i], t_i); m["chosen"] = t_i; nest.append(m)
nest = pd.DataFrame(nest)
RESULTS["nested_threshold_selection"] = {c: {"mean": float(nest[c].mean()), "sd": float(nest[c].std())}
                                         for c in ("chosen", "f2", "recall", "precision", "flag_rate")}
RESULTS["nested_threshold_selection"]["in_sample_selected_f2"] = chosen["validation_f2"]

# Phase 5: same thresholds on calibrated scale; ranking/alert invariance
platt_cal = platt_full.predict_proba(logit(val_p).reshape(-1, 1))[:, 1]
iso_cal = iso_full.predict(val_p)
RESULTS["combined_strategy"] = {
    "platt_is_monotone_so_alerts_identical_at_mapped_threshold": bool(
        ((val_p >= thr) == (platt_cal >= cal_summary["current_threshold_on_platt_scale"])).all()),
    "auc_raw": float(roc_auc_score(yv, val_p)), "auc_platt_full": float(roc_auc_score(yv, platt_cal)),
    "auc_isotonic_full_in_sample": float(roc_auc_score(yv, iso_cal)),
    "platt_oof_f2_threshold": fast_select_threshold(yv, oof_first["platt"]),
    "isotonic_oof_f2_threshold": fast_select_threshold(yv, oof_first["isotonic"]),
    "platt_oof_at_f2_threshold": op_metrics(yv, oof_first["platt"], fast_select_threshold(yv, oof_first["platt"])[0]),
    "isotonic_oof_at_f2_threshold": op_metrics(yv, oof_first["isotonic"], fast_select_threshold(yv, oof_first["isotonic"])[0]),
    "raw_at_0.5": op_metrics(yv, val_p, 0.5), "platt_oof_at_0.5": op_metrics(yv, oof_first["platt"], 0.5),
}

# =========================================================================== stage 5
def transfer_sim(label, A_mask):
    XA, yA = X_tr[A_mask], y_tr[A_mask]
    wA = float((len(yA) - yA.sum()) / max(1, yA.sum()))
    mA = fit_xgb(XA, yA, wA); pA = mA.predict_proba(X_va)[:, 1]
    tA, _ = fast_select_threshold(yv, pA)
    mB = fit_xgb(X_tr, y_tr, wA)  # mirrors train.py: refit reuses stage-1 pos_weight
    pB = mB.predict_proba(X_va)[:, 1]
    tB, _ = fast_select_threshold(yv, pB)
    return {"scenario": label, "A_rows": int(A_mask.sum()), "B_rows": int(len(X_tr)), "pos_weight_used": wA,
            "A_threshold": tA, "A_at_A_threshold": op_metrics(yv, pA, tA),
            "B_at_A_threshold_transferred": op_metrics(yv, pB, tA), "B_own_f2_threshold": tB,
            "B_at_own_threshold": op_metrics(yv, pB, tB),
            "A_mean_score": float(pA.mean()), "B_mean_score": float(pB.mean())}

sims = [transfer_sim("A=2013B only -> B=2013B+2013J", (train.code_presentation == "2013B").to_numpy()),
        transfer_sim("A=2013J only -> B=2013B+2013J", (train.code_presentation == "2013J").to_numpy())]
rs = np.random.default_rng(SEED)
for s in range(5):
    sims.append(transfer_sim(f"A=random 67% of train (seed {s}) -> B=full train", rs.random(len(X_tr)) < 0.67))
RESULTS["refit_transfer_simulation_validation"] = sims

# code_presentation is a model feature; live/held-out cohorts are always an unseen category
sens = {}
for val in ["2014B (actual, unseen by stage-1)", "2013B", "2013J"]:
    Xm = X_va.copy()
    if not val.startswith("2014B"):
        Xm["code_presentation"] = val
    pp = stage1.predict_proba(Xm)[:, 1]
    sens[val] = {"mean_score": float(pp.mean()), "flag_rate_at_current": float((pp >= thr).mean()),
                 "roc_auc": float(roc_auc_score(yv, pp)), "brier": float(np.mean((pp - yv) ** 2))}
names = deployed.named_steps["preprocess"].get_feature_names_out()
imp = deployed.named_steps["model"].feature_importances_
RESULTS["code_presentation_sensitivity_stage1_validation"] = sens
RESULTS["deployed_code_presentation_importance"] = {str(n): float(v) for n, v in zip(names, imp) if "code_presentation" in n}
RESULTS["deployed_code_presentation_importance_rank"] = {str(n): int(r + 1) for r, n in enumerate(names[np.argsort(-imp)]) if "code_presentation" in n}

# label-free: does the refit shift the score distribution at the reused cutoff? (test features only, no labels)
s1_te = stage1.predict_proba(X_te)[:, 1]
RESULTS["refit_shift_label_free_test_features"] = {
    "note": "Uses 2014J features only, no labels; nothing is fitted or selected from it.",
    "stage1_flag_rate_at_current": float((s1_te >= thr).mean()),
    "deployed_flag_rate_at_current": float((deployed_test_scores >= thr).mean()),
    "stage1_mean_score": float(s1_te.mean()), "deployed_mean_score": float(deployed_test_scores.mean()),
    "deployed_threshold_matching_stage1_flag_rate": float(np.quantile(deployed_test_scores, 1 - (s1_te >= thr).mean())),
    "spearman_stage1_vs_deployed": float(pd.Series(s1_te).corr(pd.Series(deployed_test_scores), method="spearman")),
}

# =========================================================================== FREEZE
frozen = out("results_validation_frozen.json")
frozen.write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
frozen_hash = sha256(frozen)

# =========================================================================== stage 6 (post-freeze, descriptive only)
y_te = test[TARGET].astype(int).to_numpy()
RESULTS["post_freeze_test_descriptive"] = {
    "frozen_validation_results_sha256": frozen_hash,
    "note": "Deployed raw scores only. No calibrator or threshold is fitted, selected or compared on test.",
    "deployed_raw": prob_metrics(y_te, deployed_test_scores),
}
rel_te = reliability_table(y_te, deployed_test_scores, "uniform")
rel_te.to_csv(out("test_reliability_uniform10_deployed_raw_POSTFREEZE.csv"), index=False)
reliability_svg([("Deployed XGBoost raw scores (post-freeze, descriptive)", "#d62728", rel_te)],
                f"Test 2014J reliability (n={len(y_te)}, 10 equal-width bins)", out("reliability_test_postfreeze.svg"))
out("results.json").write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
print(json.dumps({"baseline_reproduced": baseline_ok, "stage1_reproduced": stage1_ok,
                  "frozen_sha256": frozen_hash}, indent=2))
