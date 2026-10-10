"""Small model-loading/prediction boundary suitable for a future FastAPI service."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Mapping, Any, Sequence
import joblib
import pandas as pd
from ml.features.build_dataset import FEATURES, NUMERIC_FEATURES, FEATURE_VERSION
from ml.clustering.features import ENGAGEMENT
from ml.timeseries.features import SEQUENCE_FEATURES, SEQUENCE_LENGTH

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "ml/saved_models"
RANGES = {"registration_day": (-322, 49), "num_of_prev_attempts": (0, 6),
    "studied_credits": (30, 655), "early_assessment_mean": (0, 100),
    "early_assessment_count": (0, 4), "early_on_time_rate": (0, 1),
    "early_assessment_coverage": (0, 1), "early_vle_clicks": (0, 9481),
    "early_vle_active_days": (0, 56), "early_vle_active_weeks": (0, 8),
    "early_vle_active_sites": (0, 267), "early_vle_activity_types": (0, 14)}
INTEGER_FEATURES = {"registration_day", "num_of_prev_attempts", "studied_credits",
    "early_assessment_count", "early_vle_clicks", "early_vle_active_days",
    "early_vle_active_weeks", "early_vle_active_sites", "early_vle_activity_types"}


def validate_features(features: Mapping[str, Any]) -> dict:
    missing = sorted(set(FEATURES) - set(features))
    extra = sorted(set(features) - set(FEATURES))
    if missing or extra:
        raise ValueError(f"Feature keys mismatch; missing={missing}, extra={extra}")
    clean = dict(features)
    for name, (lo, hi) in RANGES.items():
        value = clean[name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric or null")
        if not (lo <= value <= hi):
            raise ValueError(f"{name} must be between {lo} and {hi}")
        if name in INTEGER_FEATURES and not float(value).is_integer():
            raise ValueError(f"{name} must be an integer")
    for name in ["code_module", "code_presentation"]:
        if not isinstance(clean[name], str) or not clean[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    return clean


def validate_cluster_features(features: Mapping[str, Any]) -> dict:
    from ml.clustering.features import ENGAGEMENT
    missing = sorted(set(ENGAGEMENT) - set(features))
    extra = sorted(set(features) - set(ENGAGEMENT))
    if missing or extra:
        raise ValueError(f"Cluster feature keys mismatch; missing={missing}, extra={extra}")
    clean = dict(features)
    for name in ENGAGEMENT:
        value = clean[name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric or null")
        lo, hi = RANGES[name]
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        if name in INTEGER_FEATURES and not float(value).is_integer():
            raise ValueError(f"{name} must be an integer")
    return clean


def load_model(model_name: str | None = None) -> dict:
    registry = json.loads((MODEL_DIR / "registry.json").read_text(encoding="utf-8"))
    if model_name is None:
        chosen = next((m for m in registry["models"] if m["selected"]), None)
        if chosen is None:
            raise RuntimeError("No selected supervised model is registered")
        model_name = chosen["name"]
    entry = next((m for m in registry["models"] if m["name"] == model_name), None)
    if entry is None:
        raise ValueError(f"Unknown model: {model_name}")
    artifact = joblib.load(ROOT / entry["path"])
    if artifact["feature_version"] != FEATURE_VERSION or artifact["features"] != FEATURES:
        raise RuntimeError("Model feature contract does not match this inference service")
    return {**artifact, "name": model_name, "version": entry["version"]}


def predict(features: Mapping[str, Any], model: dict | None = None) -> dict:
    clean = validate_features(features)
    loaded = model or load_model()
    row = pd.DataFrame([{name: clean[name] for name in FEATURES}], columns=FEATURES)
    score = float(loaded["pipeline"].predict_proba(row)[0][1])
    observed = {name: clean[name] for name in NUMERIC_FEATURES if clean[name] is not None}
    return {"model": loaded["name"], "model_version": loaded["version"],
        "feature_version": FEATURE_VERSION, "support_priority_score": score,
        "threshold": float(loaded["threshold"]),
        "priority_band": "review_for_support" if score >= loaded["threshold"] else "no_flag_from_model",
        "observed_signals": observed,
        "interpretation": "This is a statistical decision-support signal, not a prediction of an individual student's intent or destiny. A coordinator reviews context before deciding whether to offer support."}


def model_feature_importance(model: dict | None = None, top_n: int = 10) -> dict:
    """Return cohort-level tree importances; never present them as individual causes."""
    loaded = model or load_model()
    pipe = loaded["pipeline"]
    estimator = pipe.named_steps["model"]
    if not hasattr(estimator, "feature_importances_"):
        raise ValueError("This model does not expose tree feature importances")
    names = pipe.named_steps["preprocess"].get_feature_names_out()
    values = estimator.feature_importances_
    ranked = sorted(zip(names, values), key=lambda item: float(item[1]), reverse=True)[:top_n]
    return {"model": loaded["name"], "importance_type": "tree split importance",
        "features": [{"feature": str(name), "importance": float(value)} for name, value in ranked],
        "interpretation": "These cohort-level importances describe model associations, not individual reasons or causal effects."}


def predict_weekly_sequence(sequence, network=None, preprocessing=None) -> dict:
    """Score one ordered 8x2 days-0–55 sequence with the saved LSTM and scaler."""
    import numpy as np
    import tensorflow as tf
    artifact = preprocessing or joblib.load(MODEL_DIR / "lstm_preprocessing.joblib")
    values = np.asarray(sequence, dtype="float32")
    if values.shape != (SEQUENCE_LENGTH, len(SEQUENCE_FEATURES)) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"sequence must have shape {SEQUENCE_LENGTH}x{len(SEQUENCE_FEATURES)} and contain finite, nonnegative weekly values")
    scaled = artifact["scaler"].transform(values).reshape(1, SEQUENCE_LENGTH, len(SEQUENCE_FEATURES)).astype("float32")
    net = network or tf.keras.models.load_model(MODEL_DIR / "lstm_weekly.keras")
    score = float(net.predict(scaled, verbose=0).ravel()[0])
    return {"model": "lstm_weekly", "feature_version": artifact["feature_version"],
        "support_priority_score": score, "threshold": float(artifact["threshold"]),
        "priority_band": "review_for_support" if score >= artifact["threshold"] else "no_flag_from_model",
        "interpretation": "A statistical signal for human review; weekly VLE activity is not attendance or proof of learning."}


def assign_behavioral_clusters(features: Sequence[Mapping[str, Any]], bundle=None) -> list[dict]:
    """Assign cohort-relative clusters in one pass using the persisted K-Means model."""
    loaded = bundle or joblib.load(MODEL_DIR / "kmeans.joblib")
    clean_features = [validate_cluster_features(values) for values in features]
    if not clean_features:
        return []
    matrix = pd.DataFrame(
        [{name: clean[name] for name in ENGAGEMENT} for clean in clean_features],
        columns=ENGAGEMENT,
    )
    cluster_ids = loaded["model"].predict(loaded["preprocessor"].transform(matrix))
    return [
        {"cluster_id": int(cluster_id), "features": clean,
         "interpretation": "Cluster IDs are cohort-relative groupings, not student labels or diagnoses. Review observed values and context."}
        for cluster_id, clean in zip(cluster_ids, clean_features, strict=True)
    ]


def assign_behavioral_cluster(features: Mapping[str, Any], bundle=None) -> dict:
    """Assign one enrollment to a cohort-relative cluster."""
    return assign_behavioral_clusters([features], bundle)[0]
