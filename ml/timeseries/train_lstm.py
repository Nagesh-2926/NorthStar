"""Chronological LSTM and flattened logistic baseline for early weekly VLE signals."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from ml.features.build_dataset import KEYS, TARGET, split_by_presentation, split_diagnostics
from ml.timeseries.features import SEQUENCE_FEATURES, SEQUENCE_LENGTH, SEQUENCE_FEATURE_VERSION
from ml.supervised.train import metrics, select_threshold

ROOT = Path(__file__).resolve().parents[2]
def train_lstm(data: pd.DataFrame, sequences: pd.DataFrame) -> dict:
    try:
        import tensorflow as tf
    except ImportError as exc:
        raise RuntimeError("TensorFlow is required for the LSTM. Install ml/requirements.txt") from exc
    tf.keras.utils.set_random_seed(42)
    tf.config.experimental.enable_op_determinism()
    seq_map = {tuple(r[k] for k in KEYS): np.column_stack([
        np.asarray(r[name], dtype="float32") for name in SEQUENCE_FEATURES])
        for _, r in sequences.iterrows()}
    seq = np.stack([seq_map.get(tuple(r[k] for k in KEYS), np.zeros((SEQUENCE_LENGTH, len(SEQUENCE_FEATURES)), dtype="float32"))
                    for _, r in data.iterrows()])
    tr, va, te = split_by_presentation(data)
    idx = {key: i for i, key in enumerate(map(tuple, data[KEYS].itertuples(index=False, name=None)))}
    inds = {name: np.asarray([idx[tuple(row)] for row in part[KEYS].itertuples(index=False, name=None)])
            for name, part in (("train", tr), ("validation", va), ("test", te))}
    y = data[TARGET].to_numpy(dtype="int32")
    scaler = StandardScaler().fit(seq[inds["train"]].reshape(-1, seq.shape[-1]))
    x = scaler.transform(seq.reshape(-1, seq.shape[-1])).reshape(seq.shape).astype("float32")
    model = tf.keras.Sequential([tf.keras.layers.Input(shape=(SEQUENCE_LENGTH, len(SEQUENCE_FEATURES))),
        tf.keras.layers.LSTM(24, dropout=0.15), tf.keras.layers.Dense(12, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid")])
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=[tf.keras.metrics.AUC(name="auc")])
    history = model.fit(x[inds["train"]], y[inds["train"]], validation_data=(x[inds["validation"]], y[inds["validation"]]),
        epochs=25, batch_size=128, callbacks=[tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=4, restore_best_weights=True)], verbose=0)
    vp = model.predict(x[inds["validation"]], verbose=0).ravel()
    threshold, _ = select_threshold(y[inds["validation"]], vp)
    tp = model.predict(x[inds["test"]], verbose=0).ravel()

    # Baseline uses precisely the same weekly inputs flattened in chronological order.
    flat_scaler = StandardScaler().fit(seq[inds["train"]].reshape(len(inds["train"]), -1))
    flat = flat_scaler.transform(seq.reshape(len(seq), -1))
    baseline = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
    baseline.fit(flat[inds["train"]], y[inds["train"]])
    bvp = baseline.predict_proba(flat[inds["validation"]])[:, 1]
    bthreshold, _ = select_threshold(y[inds["validation"]], bvp)
    btp = baseline.predict_proba(flat[inds["test"]])[:, 1]
    report = {"feature_version": SEQUENCE_FEATURE_VERSION, "sequence_length_weeks": SEQUENCE_LENGTH,
        "prediction_horizon": "OULAD end-of-course Fail/Withdrawn outcome; inputs only presentation days 0-55",
        "weekly_inputs": SEQUENCE_FEATURES, "split": {"train": ["2013B", "2013J"],
        "validation": ["2014B"], "test": ["2014J"]}, "best_epoch": int(np.argmin(history.history["val_loss"]) + 1),
        "student_independence": split_diagnostics(data),
        "epochs_run": len(history.history["loss"]), "lstm_threshold_from_validation_f2": threshold,
        "lstm_test": metrics(y[inds["test"]], tp, threshold),
        "logistic_sequence_baseline_threshold": bthreshold,
        "logistic_sequence_baseline_test": metrics(y[inds["test"]], btp, bthreshold),
        "limitations": ["Only eight early weeks are available at the chosen cutoff.",
            "OULAD is historical and observational; activity is not attendance or learning quality.",
            "One later presentation is held out, so performance uncertainty is substantial."]}
    out = ROOT / "ml/saved_models"
    model.save(out / "lstm_weekly.keras")
    joblib.dump({"scaler": scaler, "features": SEQUENCE_FEATURES, "sequence_length": SEQUENCE_LENGTH,
                 "feature_version": SEQUENCE_FEATURE_VERSION, "threshold": threshold},
                 out / "lstm_preprocessing.joblib")
    joblib.dump({"scaler": flat_scaler, "model": baseline, "sequence_length": SEQUENCE_LENGTH,
                 "features": SEQUENCE_FEATURES}, out / "weekly_logistic_baseline.joblib")
    (ROOT / "data/processed/lstm_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
