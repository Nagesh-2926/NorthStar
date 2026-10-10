import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.features.build_dataset import (FEATURES, KEYS, NUMERIC_FEATURES, TARGET,
    build_student_features, split_by_presentation)
from ml.features.canonical import CANONICAL_COLUMNS, CANONICAL_ID_COLUMNS
from tests.test_features import oulad_mini, write_csv  # noqa: F401  (fixture reuse)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data/processed/student_training_dataset.csv"
IDENTIFIER_TOKENS = ("id", "enrollment", "source", "hash", "sha", "record")


@pytest.fixture(scope="module")
def canonical():
    if not CANONICAL.is_file():
        pytest.skip("Canonical dataset has not been generated")
    return pd.read_csv(CANONICAL).rename(columns={"source_student_id": "id_student"})


def test_many_activity_and_assessment_rows_do_not_multiply_student_course_rows(oulad_mini):
    # Same student/site/day repeated, several sites, and a second assessment: aggregates
    # must change but the student-course grain must not.
    vle = pd.read_csv(oulad_mini / "studentVle.csv")
    extra = pd.DataFrame([
        {"code_module": "AAA", "code_presentation": "2013B", "id_student": 1, "id_site": 100, "date": 5, "sum_click": 4},
        {"code_module": "AAA", "code_presentation": "2013B", "id_student": 1, "id_site": 101, "date": 5, "sum_click": 1},
        {"code_module": "AAA", "code_presentation": "2013B", "id_student": 1, "id_site": 101, "date": 9, "sum_click": 2},
    ])
    pd.concat([vle, extra]).to_csv(oulad_mini / "studentVle.csv", index=False)
    assessments = pd.read_csv(oulad_mini / "assessments.csv")
    pd.concat([assessments, pd.DataFrame([{"code_module": "AAA", "code_presentation": "2013B",
        "id_assessment": 12, "assessment_type": "CMA", "date": 40, "weight": 0}])]).to_csv(
        oulad_mini / "assessments.csv", index=False)
    scores = pd.read_csv(oulad_mini / "studentAssessment.csv")
    pd.concat([scores, pd.DataFrame([{"id_assessment": 12, "id_student": 1, "date_submitted": 41,
        "is_banked": 0, "score": 60}])]).to_csv(oulad_mini / "studentAssessment.csv", index=False)

    data, sequences = build_student_features(oulad_mini, chunk_size=2)
    assert not data.duplicated(KEYS).any()
    assert len(data) == 3
    one = data.set_index("id_student").loc[1]
    assert one["early_vle_clicks"] == 3 + 4 + 1 + 2
    assert one["early_vle_active_days"] == 2
    assert one["early_vle_active_sites"] == 2
    assert one["early_vle_activity_types"] == 2
    assert one["early_vle_active_weeks"] == 2
    assert one["early_assessment_count"] == 2
    assert one["early_assessment_mean"] == pytest.approx(74)
    assert one["early_on_time_rate"] == pytest.approx(0.5)
    assert one["early_assessment_coverage"] == pytest.approx(1.0)
    assert not sequences.duplicated(KEYS).any()


def test_feature_build_is_deterministic_across_chunk_sizes(oulad_mini):
    first, first_seq = build_student_features(oulad_mini, chunk_size=1)
    second, second_seq = build_student_features(oulad_mini, chunk_size=1000)
    order = lambda frame: frame.sort_values(KEYS).reset_index(drop=True)
    pd.testing.assert_frame_equal(order(first), order(second), check_like=False)
    pd.testing.assert_frame_equal(order(first_seq), order(second_seq))


def test_predictive_features_exclude_identifiers_labels_and_outcome_timing():
    lowered = [name.lower() for name in FEATURES]
    assert TARGET not in FEATURES
    assert not {"id_student", "source_record_id", "source_student_id", "enrollment_number",
                "final_result", "date_unregistration"} & set(FEATURES)
    for name in lowered:
        assert not any(name == token or name.startswith(f"{token}_") or name.endswith(f"_{token}")
                       for token in IDENTIFIER_TOKENS), name


def test_canonical_dataset_schema_grain_and_identity_separation(canonical):
    raw = pd.read_csv(CANONICAL, nrows=0)
    assert list(raw.columns) == CANONICAL_COLUMNS
    assert "enrollment_number" not in raw.columns
    assert not canonical.duplicated(KEYS).any()
    assert not canonical["source_record_id"].duplicated().any()
    assert canonical["source_record_id"].str.startswith("oulad:student-course:v1:").all()
    assert set(CANONICAL_ID_COLUMNS).isdisjoint(FEATURES)
    assert canonical[TARGET].isin([0, 1]).all()


def test_canonical_weekly_sequences_reconcile_with_aggregates(canonical):
    clicks = canonical[[f"week_{week}_clicks" for week in range(1, 9)]]
    days = canonical[[f"week_{week}_active_days" for week in range(1, 9)]]
    assert (clicks.sum(axis=1) == canonical["early_vle_clicks"]).all()
    assert (days.sum(axis=1) == canonical["early_vle_active_days"]).all()
    assert ((clicks > 0).sum(axis=1) == canonical["early_vle_active_weeks"]).all()
    assert days.le(7).all().all() and days.ge(0).all().all()


def test_canonical_dataset_matches_the_source_snapshot_the_models_were_trained_on():
    manifest = json.loads((ROOT / "data/processed/source_manifest.json").read_text(encoding="utf-8"))
    evaluation = json.loads((ROOT / "data/processed/supervised_evaluation.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 7
    assert evaluation["dataset_version"] == manifest["snapshot_sha256"]


def test_split_is_student_disjoint_and_test_never_feeds_saved_preprocessing(canonical):
    train, validation, test = split_by_presentation(canonical)
    groups = [set(part.id_student) for part in (train, validation, test)]
    assert not (groups[0] & groups[1]) and not (groups[0] & groups[2]) and not (groups[1] & groups[2])
    evaluation = json.loads((ROOT / "data/processed/supervised_evaluation.json").read_text(encoding="utf-8"))
    assert evaluation["counts"] == {"train": len(train), "validation": len(validation), "test": len(test)}

    # The registered model is refit on train + validation after selection; its fitted
    # median imputer must match those rows and not any statistic that includes test rows.
    artifact = joblib.load(ROOT / "ml/saved_models/xgboost.joblib")
    imputer = (artifact["pipeline"].named_steps["preprocess"]
               .named_transformers_["numeric"].named_steps["impute"])
    fit_rows = pd.concat([train, validation])[NUMERIC_FEATURES]
    np.testing.assert_allclose(imputer.statistics_, fit_rows.median().to_numpy())
    with_test = pd.concat([train, validation, test])[NUMERIC_FEATURES].median().to_numpy()
    assert not np.allclose(imputer.statistics_, with_test)


def _close(actual, recorded):
    keys = ["accuracy", "precision", "recall", "f1", "f2", "roc_auc"]
    return (all(abs(actual[key] - recorded[key]) < 1e-9 for key in keys)
            and actual["confusion_matrix"] == recorded["confusion_matrix"])


@pytest.mark.parametrize("name", ["logistic_regression", "random_forest", "xgboost"])
def test_saved_supervised_artifacts_reproduce_the_recorded_test_metrics(canonical, name):
    from ml.supervised.train import metrics
    evaluation = json.loads((ROOT / "data/processed/supervised_evaluation.json").read_text(encoding="utf-8"))
    artifact = joblib.load(ROOT / f"ml/saved_models/{name}.joblib")
    _, _, test = split_by_presentation(canonical)
    pipeline = artifact["pipeline"]
    assert list(pipeline.classes_) == [0, 1]  # predict_proba[:, 1] is the support label
    assert artifact["features"] == FEATURES
    scores = pipeline.predict_proba(test[FEATURES])[:, 1]
    assert _close(metrics(test[TARGET].astype(int), scores, artifact["threshold"]), evaluation["test_results"][name])
    assert artifact["threshold"] == pytest.approx(evaluation["validation_results"][name]["validation"]["threshold"], abs=1e-6)


def test_saved_kmeans_reproduces_the_recorded_cluster_assignments(canonical):
    bundle = joblib.load(ROOT / "ml/saved_models/kmeans.joblib")
    recorded = pd.read_csv(ROOT / "data/processed/behavioral_clusters.csv.gz")
    labels = bundle["model"].predict(bundle["preprocessor"].transform(canonical[bundle["features"]]))
    merged = canonical[KEYS].assign(label=labels).merge(recorded, on=KEYS, validate="one_to_one")
    assert len(merged) == len(canonical)
    assert (merged["label"] == merged["cluster_id"]).all()


def test_every_training_row_passes_inference_validation(canonical):
    from ml.inference.prediction_service import validate_features
    for row in canonical[FEATURES].to_dict("records"):
        validate_features({key: None if isinstance(value, float) and np.isnan(value) else value
                           for key, value in row.items()})


def _numbers(text):
    """Numbers in prose/table text, ignoring bold markers and thousands separators."""
    import re
    return {float(token.replace(",", "")) for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)}


def _report(name):
    return json.loads((ROOT / "data/processed" / name).read_text(encoding="utf-8"))


def _paragraph(doc, marker):
    return next(block for block in doc.split("\n\n") if marker in block)


def test_documented_supervised_table_matches_the_recorded_evaluation():
    evaluation = _report("supervised_evaluation.json")
    doc = (ROOT / "docs/model-evaluation.md").read_text(encoding="utf-8")
    labels = {"logistic_regression": "Logistic Regression", "random_forest": "Random Forest", "xgboost": "XGBoost"}
    for name, label in labels.items():
        result = evaluation["test_results"][name]
        row = next(line for line in doc.splitlines() if line.startswith(f"| {label} |"))
        expected = {round(result["threshold"], 4)} | {round(result[key], 3) for key in
                    ("accuracy", "precision", "recall", "f1", "f2", "roc_auc")}
        expected |= {float(value) for value in result["confusion_matrix"].values()}
        assert expected <= _numbers(row), (label, sorted(expected - _numbers(row)))
    selected = evaluation["selected_model"]
    selection = _paragraph(doc, "was selected because")
    assert labels[selected] in selection
    assert round(evaluation["validation_results"][selected]["validation"]["f2"], 3) in _numbers(selection)
    matrix = evaluation["test_results"][selected]["confusion_matrix"]
    assert {float(matrix["fp"]), float(matrix["fn"])} <= _numbers(selection)


def test_documented_lstm_grade_cluster_and_cohort_figures_match_reports():
    doc = (ROOT / "docs/model-evaluation.md").read_text(encoding="utf-8")
    supervised, lstm = _report("supervised_evaluation.json"), _report("lstm_evaluation.json")
    grade, clusters = _report("grade_score_evaluation.json"), _report("clustering_evaluation.json")
    lstm_text = _paragraph(doc, "The LSTM consumes")
    for key, threshold in (("lstm_test", "lstm_threshold_from_validation_f2"),
                           ("logistic_sequence_baseline_test", "logistic_sequence_baseline_threshold")):
        result = lstm[key]
        expected = {round(result["roc_auc"], 3), round(result["f2"], 3), round(lstm[threshold], 4),
                    float(result["confusion_matrix"]["fn"]), float(result["confusion_matrix"]["fp"])}
        assert expected <= _numbers(lstm_text), (key, sorted(expected - _numbers(lstm_text)))
    selected = supervised["test_results"][supervised["selected_model"]]
    assert {round(selected["roc_auc"], 3), round(selected["f2"], 3)} <= _numbers(lstm_text)

    grade_text = _paragraph(doc, "Held-out MAE")
    expected = {round(grade[part][metric], 3) for part in ("test", "validation", "training_mean_baseline_test")
                for metric in ("mae", "rmse", "r2")}
    assert expected <= _numbers(grade_text), sorted(expected - _numbers(grade_text))
    assert float(grade["source_rows"]) in _numbers(_paragraph(doc, "submitted exam scores"))

    cluster_text = _paragraph(doc, "K-Means selected")
    assert {float(clusters["selected_k"]), round(clusters["selected_silhouette"], 3)} <= _numbers(cluster_text)
    for profile in clusters["profiles"]:
        medians = profile["median_feature_values"]
        assert {medians["early_vle_clicks"], medians["early_vle_active_days"],
                medians["early_vle_active_weeks"]} <= _numbers(cluster_text)

    cohort = supervised["cohort_eligibility"]
    protocol = _paragraph(doc, "The target is end-of-course")
    assert {float(cohort[key]) for key in ("eligible_rows", "source_rows", "excluded_withdrawn_before_prediction_day",
            "excluded_withdrawn_unknown_timing")} <= _numbers(protocol)
    split = _paragraph(doc, "The split follows")
    independence = supervised["student_independence"]
    assert {float(value) for part in ("rows", "unique_students") for value in independence[part].values()} <= _numbers(split)
    balance = _paragraph(doc, "After eligibility filtering")
    assert {float(value) for part in ("all", "train") for value in supervised["class_distribution"][part].values()} <= _numbers(balance)


def test_readme_headline_metrics_match_reports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    supervised, lstm = _report("supervised_evaluation.json"), _report("lstm_evaluation.json")
    headline = _paragraph(readme, "day-56 eligibility leaves")
    chosen = supervised["selected_model"]
    result = supervised["test_results"][chosen]
    expected = {float(supervised["cohort_eligibility"]["eligible_rows"]),
                round(supervised["validation_results"][chosen]["validation"]["f2"], 3),
                round(result["f2"], 3), round(result["recall"], 3), round(result["roc_auc"], 3),
                float(result["confusion_matrix"]["fn"]), float(result["confusion_matrix"]["fp"]),
                round(supervised["test_results"]["random_forest"]["roc_auc"], 3),
                round(lstm["lstm_test"]["roc_auc"], 3), round(lstm["lstm_test"]["f2"], 3),
                round(lstm["logistic_sequence_baseline_test"]["roc_auc"], 3),
                round(lstm["logistic_sequence_baseline_test"]["f2"], 3)}
    assert expected <= _numbers(headline), sorted(expected - _numbers(headline))
