"""Train, compare, select, and serialize early-support classifiers."""
from __future__ import annotations
import json, platform
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, precision_score, recall_score, f1_score,
                             fbeta_score, roc_auc_score, confusion_matrix)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from ml.features.build_dataset import (FEATURES, NUMERIC_FEATURES, CATEGORICAL_FEATURES,
    TARGET, FEATURE_VERSION, PREDICTION_DAY, build_student_features, split_by_presentation,
    split_diagnostics)
from ml.features.canonical import write_canonical_training_dataset, write_coordinator_upload_template
from ml.data.source_manifest import create_source_manifest
from ml.version import MODEL_VERSION

ROOT = Path(__file__).resolve().parents[2]
RAW_CANDIDATES = [ROOT / "data/raw/oulad", ROOT / "data/raw/raw/oulad"]
MODEL_DIR = ROOT / "ml/saved_models"
PROCESSED = ROOT / "data/processed"
UPLOAD_TEMPLATE = ROOT / "data/templates/student_upload_template.csv"
CANONICAL_TRAINING_DATASET = PROCESSED / "student_training_dataset.csv"


def write_processed_student_dataset(
    data: pd.DataFrame,
    sequences: pd.DataFrame,
) -> int:
    """Write every historical student-course row using an OULAD-only identity."""
    count = write_canonical_training_dataset(data, sequences, CANONICAL_TRAINING_DATASET)
    write_coordinator_upload_template(UPLOAD_TEMPLATE)
    return count


def make_preprocessor() -> ColumnTransformer:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler())])
    categorical = Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                             ("encode", OneHotEncoder(handle_unknown="ignore"))])
    return ColumnTransformer([("numeric", numeric, NUMERIC_FEATURES),
                              ("categorical", categorical, CATEGORICAL_FEATURES)])


def metrics(y, probabilities, threshold: float) -> dict:
    pred = (np.asarray(probabilities) >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"threshold": round(float(threshold), 6), "accuracy": float(accuracy_score(y, pred)),
            "precision": float(precision_score(y, pred, zero_division=0)),
            "recall": float(recall_score(y, pred, zero_division=0)),
            "f1": float(f1_score(y, pred, zero_division=0)),
            "f2": float(fbeta_score(y, pred, beta=2, zero_division=0)),
            "roc_auc": float(roc_auc_score(y, probabilities)),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}}


def select_threshold(y, probabilities) -> tuple[float, dict]:
    # Threshold selection is limited to the validation presentations. F2 weights missed
    # support opportunities (false negatives) more heavily while retaining reported precision.
    candidates = np.unique(np.r_[np.linspace(0.05, 0.95, 91), probabilities])
    scored = [(fbeta_score(y, probabilities >= t, beta=2, zero_division=0), float(t)) for t in candidates]
    score, threshold = max(scored, key=lambda x: (x[0], x[1]))
    return threshold, {"selection_metric": "validation F2", "validation_f2": float(score)}


def model_specs(pos_weight: float) -> dict:
    return {
        "logistic_regression": LogisticRegression(max_iter=1500, class_weight="balanced", random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=350, min_samples_leaf=3,
            class_weight="balanced_subsample", n_jobs=-1, random_state=42),
        "xgboost": XGBClassifier(n_estimators=400, max_depth=4, learning_rate=0.04,
            subsample=0.85, colsample_bytree=0.85, reg_lambda=2.0, min_child_weight=3,
            objective="binary:logistic", eval_metric="logloss", scale_pos_weight=pos_weight,
            n_jobs=-1, random_state=42)
    }


def train_all(data: pd.DataFrame, dataset_version: str = "unknown") -> dict:
    train, valid, test = split_by_presentation(data)
    X_train, y_train = train[FEATURES], train[TARGET].astype(int)
    X_valid, y_valid = valid[FEATURES], valid[TARGET].astype(int)
    X_all, y_all = pd.concat([X_train, X_valid]), pd.concat([y_train, y_valid])
    pos_weight = float((len(y_train) - y_train.sum()) / max(1, y_train.sum()))
    results, candidates = {}, {}
    for name, estimator in model_specs(pos_weight).items():
        pipe = Pipeline([("preprocess", make_preprocessor()), ("model", estimator)])
        pipe.fit(X_train, y_train)
        valid_prob = pipe.predict_proba(X_valid)[:, 1]
        threshold, chosen = select_threshold(y_valid.to_numpy(), valid_prob)
        results[name] = {"validation": metrics(y_valid, valid_prob, threshold), **chosen}
        candidates[name] = (pipe, threshold)

    selected = max(results, key=lambda n: (results[n]["validation"]["f2"],
        results[n]["validation"]["recall"], results[n]["validation"]["roc_auc"]))
    threshold = candidates[selected][1]
    test_metrics = {}
    for name, (pipe, cutoff) in candidates.items():
        # Refit after model/threshold selection using train + validation only.
        final = Pipeline([("preprocess", make_preprocessor()), ("model", model_specs(pos_weight)[name])])
        final.fit(X_all, y_all)
        probs = final.predict_proba(test[FEATURES])[:, 1]
        test_metrics[name] = metrics(test[TARGET].astype(int), probs, cutoff)
        joblib.dump({"pipeline": final, "threshold": cutoff, "features": FEATURES,
                     "feature_version": FEATURE_VERSION, "prediction_day": PREDICTION_DAY},
                    MODEL_DIR / f"{name}.joblib")
        candidates[name] = (final, cutoff)

    split_report = split_diagnostics(data)
    report = {"dataset": "OULAD", "dataset_version": dataset_version,
        "feature_version": FEATURE_VERSION, "target": "final_result is Fail or Withdrawn on/after day 56 versus Pass or Distinction; withdrawals before day 56 or with unknown timing are excluded",
        "prediction_horizon": f"support signal by presentation day {PREDICTION_DAY} to end-of-course result",
        "split": {"train": ["2013B", "2013J"], "validation": ["2014B"], "test": ["2014J"]},
        "student_independence": split_report,
        "cohort_eligibility": data.attrs.get("cohort_exclusions", {
            "policy": "See docs/ml-pipeline.md; regenerate features with the current feature builder."
        }),
        "counts": split_report["rows"],
        "class_distribution": {"all": data[TARGET].value_counts().sort_index().to_dict(),
            "train": y_train.value_counts().sort_index().to_dict()},
        "imbalance_ratio_negative_to_positive": pos_weight,
        "imbalance_handling": "No oversampling: classes are near-balanced overall; class weights used for LR/RF and scale_pos_weight for XGBoost.",
        "selection_metric": "validation F2; recall receives greater weight because missed support cases matter",
        "selected_model": selected, "selected_threshold": threshold,
        "validation_results": results, "test_results": test_metrics,
        "training_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version()}
    (PROCESSED / "supervised_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    registry = {"registry_version": 1, "models": []}
    for name in results:
        registry["models"].append({"name": name, "version": MODEL_VERSION,
            "training_date_utc": report["training_timestamp_utc"], "dataset_version": dataset_version,
            "feature_version": FEATURE_VERSION, "metrics": test_metrics[name],
            "selected": name == selected, "path": f"ml/saved_models/{name}.joblib"})
    (MODEL_DIR / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return report


def main() -> None:
    raw = next((p for p in RAW_CANDIDATES if (p / "studentInfo.csv").is_file()), None)
    if raw is None:
        raise FileNotFoundError(f"OULAD source folder missing; checked {RAW_CANDIDATES}")
    manifest = create_source_manifest(raw, PROCESSED / "source_manifest.json")
    data, sequences = build_student_features(raw)
    data.to_csv(PROCESSED / "oulad_early_features.csv.gz", index=False, compression="gzip")
    sequences.to_json(PROCESSED / "oulad_weekly_sequences.jsonl", orient="records", lines=True)
    processed_student_rows = write_processed_student_dataset(data, sequences)
    report = train_all(data, manifest["snapshot_sha256"])
    from ml.clustering.train import train_clusters
    from ml.timeseries.train_lstm import train_lstm
    cluster_report = train_clusters(data)
    lstm_report = train_lstm(data, sequences)
    registry_path = MODEL_DIR / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["models"].extend([
        {"name": "kmeans_behavioral", "version": MODEL_VERSION, "training_date_utc": report["training_timestamp_utc"],
         "dataset_version": manifest["snapshot_sha256"], "feature_version": FEATURE_VERSION,
         "metrics": {"selected_k": cluster_report["selected_k"], "silhouette": cluster_report["selected_silhouette"]},
         "selected": False, "path": "ml/saved_models/kmeans.joblib"},
        {"name": "lstm_weekly", "version": MODEL_VERSION, "training_date_utc": report["training_timestamp_utc"],
         "dataset_version": manifest["snapshot_sha256"], "feature_version": FEATURE_VERSION,
         "metrics": lstm_report["lstm_test"], "selected": False,
         "path": "ml/saved_models/lstm_weekly.keras",
         "preprocessing_path": "ml/saved_models/lstm_preprocessing.joblib"}])
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(json.dumps({"processed_rows": len(data),
                      "canonical_student_course_rows": processed_student_rows,
                      "canonical_dataset": str(CANONICAL_TRAINING_DATASET.relative_to(ROOT)),
                      "upload_template": str(UPLOAD_TEMPLATE.relative_to(ROOT)),
                      "selected_model": report["selected_model"],
                      "test_metrics": report["test_results"][report["selected_model"]],
                      "selected_k": cluster_report["selected_k"], "lstm_test": lstm_report["lstm_test"]}, indent=2))


if __name__ == "__main__":
    main()
