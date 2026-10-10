"""Read-only follow-up: saved XGBoost artifact scored on validation 2014B.

Question: is the saved model's validation evidence unbiased? The saved pipeline is refit on
train + validation (ml/supervised/train.py:104-113), so validation scores from it are expected to be
in-sample. This script (1) checks that structurally, (2) reports calibration and threshold metrics
for the saved artifact on validation, labelled IN-SAMPLE, and (3) puts them beside the
out-of-sample scores of the train-only stage-1 model (rebuilt in memory, never saved, gated on
exact reproduction of the recorded validation metrics).

Test labels are never read. Writes only into this script's directory. Run from the project root:
    $env:PYTHONDONTWRITEBYTECODE = "1"
    .venv\\Scripts\\python.exe <this dir>\\audit_saved_artifact_validation.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import log_loss, roc_auc_score  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from ml.features.build_dataset import FEATURES, NUMERIC_FEATURES, TARGET, split_by_presentation  # noqa: E402
from ml.supervised.train import make_preprocessor, metrics as project_metrics, model_specs  # noqa: E402

EPS = 1e-15
SEED = 20261010
R: dict = {}


def out(name):
    p = OUT / name
    assert p.parent == OUT
    return p


def op(y, p, t):
    y = np.asarray(y).astype(int); f = np.asarray(p) >= t
    tp = int((f & (y == 1)).sum()); fp = int((f & (y == 0)).sum())
    fn = int((~f & (y == 1)).sum()); tn = int((~f & (y == 0)).sum())
    P = tp / (tp + fp) if tp + fp else 0.0; Rc = tp / (tp + fn) if tp + fn else 0.0
    S = tn / (tn + fp) if tn + fp else 0.0
    return {"threshold": float(t), "flagged": tp + fp, "flag_rate": (tp + fp) / len(y),
            "precision": P, "recall": Rc, "f1": 2 * P * Rc / (P + Rc) if P + Rc else 0.0,
            "f2": 5 * P * Rc / (4 * P + Rc) if P + Rc else 0.0, "specificity": S,
            "fpr": 1 - S, "fnr": 1 - Rc, "tn": tn, "fp": fp, "fn": fn, "tp": tp}


def wilson(k, n, z=1.96):
    ph = k / n; d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d; h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def reliability(y, p, n_bins=10):
    y = np.asarray(y).astype(int); p = np.asarray(p)
    b = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    rows = []
    for i in range(n_bins):
        m = b == i; n = int(m.sum())
        if not n:
            rows.append({"bin": f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}", "n": 0}); continue
        k = int(y[m].sum()); lo, hi = wilson(k, n)
        rows.append({"bin": f"{i/n_bins:.1f}-{(i+1)/n_bins:.1f}", "n": n, "positives": k,
                     "mean_predicted": float(p[m].mean()), "observed_rate": k / n,
                     "ci95_low": lo, "ci95_high": hi, "gap": float(p[m].mean() - k / n),
                     "pred_inside_ci": bool(lo <= p[m].mean() <= hi)})
    return pd.DataFrame(rows)


def prob(y, p):
    y = np.asarray(y).astype(int); p = np.asarray(p, dtype=float)
    t = reliability(y, p); t = t[t.n > 0]
    prev = y.mean()
    return {"n": int(len(y)), "prevalence": float(prev), "mean_predicted": float(p.mean()),
            "brier": float(np.mean((p - y) ** 2)), "brier_prevalence_baseline": float(prev * (1 - prev)),
            "log_loss": float(log_loss(y, np.clip(p, EPS, 1 - EPS), labels=[0, 1])),
            "log_loss_prevalence_baseline": float(-(prev * np.log(prev) + (1 - prev) * np.log(1 - prev))),
            "roc_auc": float(roc_auc_score(y, p)),
            "ece_uniform10": float((t.n * t.gap.abs()).sum() / t.n.sum())}


def boot(y, p, fn, n=1000):
    rng = np.random.default_rng(SEED); y = np.asarray(y); p = np.asarray(p); v = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y)); v.append(fn(y[i], p[i]))
    v = pd.DataFrame(v)
    return {c: [float(v[c].quantile(.025)), float(v[c].quantile(.975))] for c in v}


def svg(series, title, path):
    W = H = 520; M = 60; S = W - 2 * M
    X = lambda v: M + v * S; Y = lambda v: H - M - v * S
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H + 28 * len(series)}" font-family="sans-serif" font-size="12">',
         '<rect width="100%" height="100%" fill="white"/>',
         f'<text x="{W/2}" y="24" text-anchor="middle" font-size="14">{title}</text>',
         f'<rect x="{M}" y="{M}" width="{S}" height="{S}" fill="none" stroke="#999"/>',
         f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="#bbb" stroke-dasharray="4 4"/>',
         f'<text x="{W/2}" y="{H-18}" text-anchor="middle">Mean score in bin</text>',
         f'<text x="16" y="{H/2}" text-anchor="middle" transform="rotate(-90 16 {H/2})">Observed positive rate (95% Wilson CI)</text>']
    for v in np.linspace(0, 1, 6):
        s += [f'<text x="{X(v)}" y="{H-M+16}" text-anchor="middle">{v:.1f}</text>',
              f'<text x="{M-8}" y="{Y(v)+4}" text-anchor="end">{v:.1f}</text>']
    for k, (lab, col, t) in enumerate(series):
        t = t[t.n > 0]
        s.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.5" points="' +
                 " ".join(f"{X(r.mean_predicted):.1f},{Y(r.observed_rate):.1f}" for r in t.itertuples()) + '"/>')
        for r in t.itertuples():
            s.append(f'<line x1="{X(r.mean_predicted):.1f}" y1="{Y(r.ci95_low):.1f}" x2="{X(r.mean_predicted):.1f}" y2="{Y(r.ci95_high):.1f}" stroke="{col}"/>')
            s.append(f'<circle cx="{X(r.mean_predicted):.1f}" cy="{Y(r.observed_rate):.1f}" r="{2+6*np.sqrt(r.n/t.n.max()):.1f}" fill="{col}" fill-opacity="0.6"/>')
        y0 = H + 8 + 26 * k
        s += [f'<rect x="{M}" y="{y0}" width="14" height="14" fill="{col}"/>', f'<text x="{M+20}" y="{y0+12}">{lab}</text>']
    path.write_text("\n".join(s + ["</svg>"]), encoding="utf-8")


# ---------------------------------------------------------------- data (validation labels only)
canon = pd.read_csv(ROOT / "data/processed/student_training_dataset.csv").rename(columns={"source_student_id": "id_student"})
train, valid, _test_unused = split_by_presentation(canon)
del _test_unused  # test rows/labels are not used anywhere in this script
Xtr, ytr = train[FEATURES], train[TARGET].astype(int)
Xva, yva = valid[FEATURES], valid[TARGET].astype(int).to_numpy()
ev = json.loads((ROOT / "data/processed/supervised_evaluation.json").read_text(encoding="utf-8"))
art = joblib.load(ROOT / "ml/saved_models/xgboost.joblib")
saved, thr = art["pipeline"], float(art["threshold"])
R["data"] = {"validation_rows": int(len(yva)), "validation_positives": int(yva.sum()),
             "validation_prevalence": float(yva.mean()), "threshold": thr}

# ---------------------------------------------------------------- 1. was the saved model trained on 2014B?
pre = saved.named_steps["preprocess"]
imp = pre.named_transformers_["numeric"].named_steps["impute"].statistics_
enc = pre.named_transformers_["categorical"].named_steps["encode"]
pres_idx = list(enc.feature_names_in_).index("code_presentation") if hasattr(enc, "feature_names_in_") else 1
cats = [str(c) for c in enc.categories_[1]]
R["saved_model_training_membership"] = {
    "onehot_code_presentation_categories": cats,
    "has_seen_2014B_category": "2014B" in cats,
    "imputer_medians_equal_train_plus_validation": bool(np.allclose(imp, pd.concat([train, valid])[NUMERIC_FEATURES].median().to_numpy())),
    "imputer_medians_equal_train_only": bool(np.allclose(imp, train[NUMERIC_FEATURES].median().to_numpy())),
    "xgb_booster_rounds": int(saved.named_steps["model"].get_booster().num_boosted_rounds()),
}
in_sample = R["saved_model_training_membership"]["has_seen_2014B_category"] and R["saved_model_training_membership"]["imputer_medians_equal_train_plus_validation"]
R["saved_model_validation_is_in_sample"] = bool(in_sample)

# ---------------------------------------------------------------- 2. stage-1 out-of-sample reference (gate)
pw = float((len(ytr) - ytr.sum()) / ytr.sum())
stage1 = Pipeline([("preprocess", make_preprocessor()), ("model", model_specs(pw)["xgboost"])]).fit(Xtr, ytr)
p_oos = stage1.predict_proba(Xva)[:, 1].astype(float)
rec = ev["validation_results"]["xgboost"]["validation"]
rep = project_metrics(yva, p_oos, thr)
gate = rep["confusion_matrix"] == rec["confusion_matrix"] and abs(rep["roc_auc"] - rec["roc_auc"]) < 1e-9
R["stage1_reproduces_recorded_validation"] = bool(gate)
if not gate:
    out("results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
    raise SystemExit("stage-1 reconstruction mismatch; stopping")

# ---------------------------------------------------------------- 3. saved artifact on validation
p_saved = saved.predict_proba(Xva)[:, 1].astype(float)
R["probability_metrics"] = {"saved_artifact_IN_SAMPLE": prob(yva, p_saved), "stage1_OUT_OF_SAMPLE": prob(yva, p_oos)}
bfn = lambda y, p: {"brier": float(np.mean((p - y) ** 2)), "log_loss": float(log_loss(y, np.clip(p, EPS, 1 - EPS), labels=[0, 1])),
                    "roc_auc": float(roc_auc_score(y, p))}
R["bootstrap_ci95"] = {"saved_artifact_IN_SAMPLE": boot(yva, p_saved, bfn), "stage1_OUT_OF_SAMPLE": boot(yva, p_oos, bfn)}
rs, ro = reliability(yva, p_saved), reliability(yva, p_oos)
rs.to_csv(out("reliability_validation_saved_artifact_IN_SAMPLE.csv"), index=False)
ro.to_csv(out("reliability_validation_stage1_OUT_OF_SAMPLE.csv"), index=False)
svg([("Saved artifact (trained on these rows: IN-SAMPLE)", "#d62728", rs),
     ("Train-only stage-1 model (out-of-sample)", "#1f77b4", ro)],
    f"Validation 2014B reliability, n={len(yva)}, 10 equal-width bins", out("reliability_validation.svg"))

grid = sorted(set(np.round(np.arange(0.05, 0.951, 0.05), 2).tolist()) | {thr})
rows = []
for t in grid:
    rows.append({"scores": "saved_artifact_IN_SAMPLE", **op(yva, p_saved, t)})
    rows.append({"scores": "stage1_OUT_OF_SAMPLE", **op(yva, p_oos, t)})
pd.DataFrame(rows).to_csv(out("validation_threshold_grid.csv"), index=False)
R["at_current_threshold"] = {"saved_artifact_IN_SAMPLE": op(yva, p_saved, thr), "stage1_OUT_OF_SAMPLE": op(yva, p_oos, thr)}
R["at_current_threshold_bootstrap_ci95"] = {
    k: boot(yva, p, lambda y, q: {m: op(y, q, thr)[m] for m in ("precision", "recall", "f2", "flag_rate")})
    for k, p in (("saved_artifact_IN_SAMPLE", p_saved), ("stage1_OUT_OF_SAMPLE", p_oos))}
R["score_agreement"] = {"spearman": float(pd.Series(p_saved).corr(pd.Series(p_oos), method="spearman")),
                        "mean_abs_diff": float(np.mean(np.abs(p_saved - p_oos)))}
out("results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
print(json.dumps({"in_sample": R["saved_model_validation_is_in_sample"], "gate": gate}, indent=2))
