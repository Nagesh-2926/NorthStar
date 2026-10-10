import json
import logging
from pathlib import Path
from threading import RLock
import joblib
from ml.features.build_dataset import FEATURE_VERSION, FEATURES
from ml.version import MODEL_VERSION
from ml.inference.prediction_service import (predict as predict_supervised,
    predict_weekly_sequence, assign_behavioral_cluster, assign_behavioral_clusters)

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


class ModelManager:
    """Thread-safe lazy cache. Training is never imported or called from API requests."""
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self._lock = RLock()
        self._supervised: dict | None = None
        self._grade_score: dict | None = None
        self._cluster: dict | None = None
        self._lstm_network = None
        self._lstm_preprocessing: dict | None = None

    def _load_supervised(self) -> dict:
        if self._supervised is not None:
            return self._supervised
        with self._lock:
            if self._supervised is None:
                try:
                    registry = json.loads((self.model_dir / "registry.json").read_text(encoding="utf-8"))
                    selected = next(item for item in registry["models"]
                                    if item["selected"] and item["name"] in {"logistic_regression", "random_forest", "xgboost"})
                    artifact = joblib.load(self.model_dir / Path(selected["path"]).name)
                    if artifact.get("feature_version") != FEATURE_VERSION or artifact.get("features") != FEATURES:
                        raise ValueError("Saved supervised model uses a different feature contract")
                    self._supervised = {**artifact, "name": selected["name"],
                                        "version": selected["version"]}
                except Exception as exc:
                    logger.exception("Could not load selected supervised model")
                    raise ModelUnavailable("Supervised model is unavailable") from exc
        return self._supervised

    def predict(self, feature_values: dict) -> dict:
        return predict_supervised(feature_values, self._load_supervised())

    def _load_grade_score(self) -> dict:
        if self._grade_score is not None:
            return self._grade_score
        with self._lock:
            if self._grade_score is None:
                try:
                    artifact = joblib.load(self.model_dir / "grade_score.joblib")
                    if (artifact.get("feature_version") != FEATURE_VERSION or
                            artifact.get("features") != FEATURES or
                            artifact.get("target_name") != "final_exam_score"):
                        raise ValueError("Saved grade model uses a different feature or target contract")
                    self._grade_score = artifact
                except Exception as exc:
                    logger.exception("Could not load final-exam score model")
                    raise ModelUnavailable("Final-exam score model is unavailable") from exc
        return self._grade_score

    def predict_grade_score(self, feature_values: dict) -> dict:
        import pandas as pd
        from ml.inference.prediction_service import validate_features

        artifact = self._load_grade_score()
        clean = validate_features(feature_values)
        if clean["code_module"] not in artifact["supported_modules"]:
            raise ValueError("Numeric exam score prediction is supported only for CCC and DDD in the trained data")
        frame = pd.DataFrame([{name: clean[name] for name in artifact["features"]}])
        score = float(artifact["pipeline"].predict(frame)[0])
        score = min(100.0, max(0.0, score))
        used = {name: clean[name] for name in artifact["features"]}
        return {"model": artifact["model_name"], "model_version": artifact["model_version"],
                "feature_version": artifact["feature_version"], "target_name": artifact["target_name"],
                "prediction_day": artifact["prediction_day"], "predicted_score": round(score, 2),
                "observed_signals": used}

    def _load_cluster(self) -> dict:
        if self._cluster is not None:
            return self._cluster
        with self._lock:
            if self._cluster is None:
                try:
                    artifact = joblib.load(self.model_dir / "kmeans.joblib")
                    from ml.clustering.features import ENGAGEMENT
                    if artifact.get("feature_version") != FEATURE_VERSION:
                        raise ValueError("Saved cluster model uses a different feature contract")
                    if artifact.get("features") != ENGAGEMENT:
                        raise ValueError("Saved cluster model feature ordering differs")
                    self._cluster = artifact
                except Exception as exc:
                    logger.exception("Could not load behavioral cluster model")
                    raise ModelUnavailable("Behavioral cluster model is unavailable") from exc
        return self._cluster

    def cluster(self, feature_values: dict) -> dict:
        artifact = self._load_cluster()
        result = assign_behavioral_cluster(feature_values, artifact)
        return {**result, "model_version": artifact.get("model_version", MODEL_VERSION),
                "feature_version": FEATURE_VERSION}

    def cluster_many(self, feature_values: list[dict]) -> list[dict]:
        artifact = self._load_cluster()
        results = assign_behavioral_clusters(feature_values, artifact)
        return [{**result, "model_version": artifact.get("model_version", MODEL_VERSION),
                 "feature_version": FEATURE_VERSION}
                for result in results]

    def _load_lstm(self):
        if self._lstm_network is not None and self._lstm_preprocessing is not None:
            return self._lstm_network, self._lstm_preprocessing
        with self._lock:
            if self._lstm_network is None:
                try:
                    import tensorflow as tf
                    preprocessing = joblib.load(self.model_dir / "lstm_preprocessing.joblib")
                    network = tf.keras.models.load_model(self.model_dir / "lstm_weekly.keras")
                    from ml.timeseries.features import (SEQUENCE_FEATURES, SEQUENCE_LENGTH,
                        SEQUENCE_FEATURE_VERSION, LEGACY_SEQUENCE_FEATURE_VERSIONS)
                    if preprocessing.get("feature_version") not in ({SEQUENCE_FEATURE_VERSION} |
                            LEGACY_SEQUENCE_FEATURE_VERSIONS):
                        raise ValueError("Saved LSTM uses a different weekly sequence contract")
                    if (preprocessing.get("features") != SEQUENCE_FEATURES or
                            preprocessing.get("sequence_length") != SEQUENCE_LENGTH):
                        raise ValueError("Saved LSTM sequence shape or feature order differs")
                    self._lstm_preprocessing = preprocessing
                    self._lstm_network = network
                except Exception as exc:
                    logger.exception("Could not load weekly LSTM")
                    raise ModelUnavailable("Weekly sequence model is unavailable") from exc
        return self._lstm_network, self._lstm_preprocessing

    def predict_sequence(self, sequence: list[list[float]]) -> dict:
        network, preprocessing = self._load_lstm()
        result = predict_weekly_sequence(sequence, network, preprocessing)
        registry = json.loads((self.model_dir / "registry.json").read_text(encoding="utf-8"))
        entry = next((item for item in registry["models"] if item["name"] == "lstm_weekly"), None)
        if entry is None:
            raise ModelUnavailable("Weekly sequence model is not registered")
        result["model_version"] = entry["version"]
        return result
