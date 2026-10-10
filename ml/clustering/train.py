"""Unsupervised behavioral segmentation, profiled from observed feature values."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from ml.features.build_dataset import FEATURE_VERSION, split_by_presentation, split_diagnostics
from ml.clustering.features import ENGAGEMENT
from ml.version import MODEL_VERSION

ROOT = Path(__file__).resolve().parents[2]
def train_clusters(data: pd.DataFrame) -> dict:
    train, _, _ = split_by_presentation(data)
    x = train[ENGAGEMENT].copy()
    pre = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                    ("scale", StandardScaler())])
    z = pre.fit_transform(x)
    candidates = []
    for k in range(2, 7):
        model = KMeans(n_clusters=k, n_init=20, random_state=42)
        labels = model.fit_predict(z)
        candidates.append((silhouette_score(z, labels, sample_size=min(len(z), 5000), random_state=42), k, model))
    silhouette, k, model = max(candidates, key=lambda t: t[0])
    labels = model.predict(z)
    all_labels = model.predict(pre.transform(data[ENGAGEMENT]))
    prof = train[ENGAGEMENT].assign(cluster=labels).groupby("cluster")[ENGAGEMENT].median()
    sizes = pd.Series(labels).value_counts().sort_index()
    report = {"feature_version": FEATURE_VERSION, "features": ENGAGEMENT,
        "selection": "maximum train-cohort silhouette over k=2..6; silhouette sampled up to 5,000 train rows",
        "fit_periods": ["2013B", "2013J"], "student_independence": split_diagnostics(data),
        "training_rows": int(len(train)),
        "candidates": [{"k": int(kk), "silhouette": float(ss)} for ss, kk, _ in candidates],
        "selected_k": int(k), "selected_silhouette": float(silhouette),
        "profiles": [{"cluster_id": int(cid), "size": int(sizes[cid]),
            "median_feature_values": {key: (None if pd.isna(val) else float(val)) for key, val in row.items()},
            "interpretation": "Review observed medians against the cohort; no normative label assigned."}
            for cid, row in prof.iterrows()]}
    out = ROOT / "ml/saved_models"
    joblib.dump({"preprocessor": pre, "model": model, "features": ENGAGEMENT,
                 "feature_version": FEATURE_VERSION, "model_version": MODEL_VERSION}, out / "kmeans.joblib")
    pd.DataFrame({"code_module": data.code_module, "code_presentation": data.code_presentation,
                  "id_student": data.id_student, "cluster_id": all_labels}).to_csv(
                  ROOT / "data/processed/behavioral_clusters.csv.gz", index=False, compression="gzip")
    (ROOT / "data/processed/clustering_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
