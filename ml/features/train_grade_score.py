"""Train the bounded OULAD final-exam score regressor (no API-time training)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.features.build_dataset import FEATURES, NUMERIC_FEATURES, FEATURE_VERSION

TARGET = "final_exam_score"
GRADE_MODEL_VERSION = "oulad-final-exam-v2"
SUPPORTED_MODULES = ["CCC", "DDD"]


def student_disjoint_splits(data: pd.DataFrame):
    train = data[data.code_presentation.isin(["2013B", "2013J"])].copy()
    validation = data[data.code_presentation.eq("2014B")].copy()
    validation = validation[~validation.id_student.isin(set(train.id_student))]
    test = data[data.code_presentation.eq("2014J")].copy()
    test = test[~test.id_student.isin(set(train.id_student) | set(validation.id_student))]
    if any(part.empty for part in (train, validation, test)):
        raise ValueError("Final-exam data must have nonempty 2013B/2013J, 2014B, and 2014J folds")
    if (set(train.id_student) & set(validation.id_student) or
            set(train.id_student) & set(test.id_student) or
            set(validation.id_student) & set(test.id_student)):
        raise ValueError("Student IDs overlap between grade evaluation folds")
    return train, validation, test


def _metrics(actual, predicted) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 6),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted))), 6),
        "r2": round(float(r2_score(actual, predicted)), 6),
    }


def build_training_data(raw_dir: Path, feature_path: Path) -> pd.DataFrame:
    features = pd.read_csv(feature_path)
    assessments = pd.read_csv(raw_dir / "assessments.csv")
    exams = assessments[assessments.assessment_type.eq("Exam")]
    # OULAD's graded end-of-course Exam assessment is consistently present for CCC/DDD.
    # Other modules have no submitted Exam scores in this source release.
    exams = exams[exams.code_module.isin(SUPPORTED_MODULES)][
        ["code_module", "code_presentation", "id_assessment"]]
    scores = pd.read_csv(raw_dir / "studentAssessment.csv")
    scores = scores.merge(exams, on="id_assessment", how="inner", validate="many_to_one")
    if scores.duplicated(["code_module", "code_presentation", "id_student"]).any():
        raise ValueError("Expected one final-exam score per student-course")
    scores = scores.rename(columns={"score": TARGET})
    data = features.merge(scores[["code_module", "code_presentation", "id_student", TARGET]],
        on=["code_module", "code_presentation", "id_student"], how="inner", validate="one_to_one")
    data = data[data.code_module.isin(SUPPORTED_MODULES)].copy()
    data[TARGET] = pd.to_numeric(data[TARGET], errors="raise")
    if data.empty or not data[TARGET].between(0, 100).all():
        raise ValueError("Final-exam scores must be present and within 0-100")
    return data


def make_model():
    preprocessing = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), NUMERIC_FEATURES),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), ["code_module", "code_presentation"]),
    ])
    return make_pipeline(preprocessing, RandomForestRegressor(
        n_estimators=120, min_samples_leaf=5, max_features=0.9, n_jobs=2, random_state=42))


def train_and_evaluate(raw_dir: Path, feature_path: Path, model_path: Path,
                       evaluation_path: Path) -> dict:
    data = build_training_data(raw_dir, feature_path)
    train, validation, test = student_disjoint_splits(data)
    model = make_model()
    model.fit(train[FEATURES], train[TARGET])
    validation_metrics = _metrics(validation[TARGET], model.predict(validation[FEATURES]))
    test_pred = model.predict(test[FEATURES])
    test_metrics = _metrics(test[TARGET], test_pred)
    baseline_metrics = _metrics(test[TARGET], np.full(len(test), train[TARGET].mean()))

    # Only after the held-out result is computed, fit the deployable pipeline on train+validation.
    final = make_model()
    fit_rows = pd.concat([train, validation], ignore_index=True)
    final.fit(fit_rows[FEATURES], fit_rows[TARGET])
    model_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "pipeline": final,
        "features": FEATURES,
        "feature_version": FEATURE_VERSION,
        "model_name": "random_forest_final_exam_regressor",
        "model_version": GRADE_MODEL_VERSION,
        "target_name": TARGET,
        "prediction_day": 56,
        "supported_modules": SUPPORTED_MODULES,
    }
    joblib.dump(artifact, model_path)
    evaluation = {
        "target": TARGET,
        "label_definition": "Observed score (0-100) for the OULAD assessment_type=Exam, among students who submitted it.",
        "prediction_horizon": "Features available through course-relative day 55; target is the later end-of-course exam score.",
        "supported_modules": SUPPORTED_MODULES,
        "source_rows": int(len(data)),
        "module_rows": {str(k): int(v) for k, v in data.code_module.value_counts().items()},
        "presentation_rows": {str(k): int(v) for k, v in data.code_presentation.value_counts().items()},
        "split": {
            "train_presentations": ["2013B", "2013J"], "validation_presentation": "2014B",
            "test_presentation": "2014J", "student_disjoint": True,
            "rows": {"train": int(len(train)), "validation": int(len(validation)), "test": int(len(test))},
            "unique_students": {"train": int(train.id_student.nunique()),
                "validation": int(validation.id_student.nunique()), "test": int(test.id_student.nunique())},
        },
        "model": "RandomForestRegressor(n_estimators=120,min_samples_leaf=5,max_features=0.9,random_state=42)",
        "validation": validation_metrics,
        "test": test_metrics,
        "training_mean_baseline_test": baseline_metrics,
        "limitations": [
            "Prediction population is limited to students who eventually submitted an exam; non-submitters have no numeric target.",
            "Only CCC and DDD have observed exam scores in this OULAD source release.",
            "2014J is one historical held-out presentation and is not external validation.",
            "The score is an exam assessment score, not an overall course grade or a guaranteed outcome.",
        ],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    return evaluation


if __name__ == "__main__":
    result = train_and_evaluate(ROOT / "data" / "raw" / "oulad",
        ROOT / "data" / "processed" / "oulad_early_features.csv.gz",
        ROOT / "ml" / "saved_models" / "grade_score.joblib",
        ROOT / "data" / "processed" / "grade_score_evaluation.json")
    print(json.dumps(result, indent=2))
