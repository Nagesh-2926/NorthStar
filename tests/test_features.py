import pandas as pd
import pytest
from backend.app.services.csv_import import CSVImportValidationError, parse_inference_csv
from ml.features.build_dataset import (FEATURES, TARGET, build_student_features,
    historical_source_record_id, split_by_presentation)
from ml.features.canonical import CANONICAL_COLUMNS, write_canonical_training_dataset


def write_csv(root, name, rows):
    pd.DataFrame(rows).to_csv(root / name, index=False)


@pytest.fixture
def oulad_mini(tmp_path):
    write_csv(tmp_path, "studentInfo.csv", [
        {"code_module":"AAA","code_presentation":"2013B","id_student":1,"gender":"F","region":"R",
         "highest_education":"H","imd_band":"x","age_band":"0-35","num_of_prev_attempts":0,
         "studied_credits":60,"disability":"N","final_result":"Pass"},
        {"code_module":"AAA","code_presentation":"2013B","id_student":2,"gender":"M","region":"R",
         "highest_education":"H","imd_band":"x","age_band":"0-35","num_of_prev_attempts":1,
         "studied_credits":60,"disability":"N","final_result":"Fail"},
        {"code_module":"AAA","code_presentation":"2013B","id_student":3,"gender":"F","region":"R",
         "highest_education":"H","imd_band":"x","age_band":"0-35","num_of_prev_attempts":0,
         "studied_credits":60,"disability":"N","final_result":"Withdrawn"},
        {"code_module":"AAA","code_presentation":"2013B","id_student":4,"gender":"M","region":"R",
         "highest_education":"H","imd_band":"x","age_band":"0-35","num_of_prev_attempts":0,
         "studied_credits":60,"disability":"N","final_result":"Withdrawn"},
        {"code_module":"BBB","code_presentation":"2013B","id_student":5,"gender":"F","region":"R",
         "highest_education":"H","imd_band":"x","age_band":"0-35","num_of_prev_attempts":0,
         "studied_credits":60,"disability":"N","final_result":"Pass"}])
    write_csv(tmp_path, "studentRegistration.csv", [
        {"code_module":"AAA","code_presentation":"2013B","id_student":1,"date_registration":-10,"date_unregistration":None},
        {"code_module":"AAA","code_presentation":"2013B","id_student":2,"date_registration":70,"date_unregistration":100},
        {"code_module":"AAA","code_presentation":"2013B","id_student":3,"date_registration":-12,"date_unregistration":35},
        {"code_module":"AAA","code_presentation":"2013B","id_student":4,"date_registration":-8,"date_unregistration":None},
        {"code_module":"BBB","code_presentation":"2013B","id_student":5,"date_registration":-8,"date_unregistration":None}])
    write_csv(tmp_path, "courses.csv", [
        {"code_module":"AAA","code_presentation":"2013B","module_presentation_length":240},
        {"code_module":"BBB","code_presentation":"2013B","module_presentation_length":240}])
    write_csv(tmp_path, "assessments.csv", [
        {"code_module":"AAA","code_presentation":"2013B","id_assessment":10,"assessment_type":"TMA","date":30,"weight":50},
        {"code_module":"AAA","code_presentation":"2013B","id_assessment":11,"assessment_type":"TMA","date":80,"weight":50}])
    write_csv(tmp_path, "studentAssessment.csv", [
        {"id_assessment":10,"id_student":1,"date_submitted":29,"is_banked":0,"score":88},
        {"id_assessment":11,"id_student":1,"date_submitted":80,"is_banked":0,"score":0},
        ])
    write_csv(tmp_path, "vle.csv", [{"id_site":100,"code_module":"AAA","code_presentation":"2013B",
        "activity_type":"oucontent","week_from":0,"week_to":1}, {"id_site":101,"code_module":"AAA",
        "code_presentation":"2013B","activity_type":"forumng","week_from":0,"week_to":1}])
    write_csv(tmp_path, "studentVle.csv", [
        {"code_module":"AAA","code_presentation":"2013B","id_student":1,"id_site":100,"date":5,"sum_click":3},
        {"code_module":"AAA","code_presentation":"2013B","id_student":1,"id_site":101,"date":60,"sum_click":99},
        {"code_module":"AAA","code_presentation":"2013B","id_student":2,"id_site":100,"date":15,"sum_click":2}])
    return tmp_path


def test_features_respect_cutoff_and_use_unregistration_only_for_cohort_eligibility(oulad_mini):
    data, seq = build_student_features(oulad_mini, chunk_size=1)
    one = data.set_index("id_student").loc[1]
    two = data.set_index("id_student").loc[2]
    assert one["early_assessment_mean"] == 88
    assert one["early_assessment_count"] == 1
    assert one["early_vle_clicks"] == 3
    assert one["early_vle_activity_types"] == 1
    assert two["early_vle_clicks"] == 2
    assert two["early_assessment_count"] == 0
    assert two["early_assessment_coverage"] == 0
    assert pd.isna(two["early_on_time_rate"])
    five = data.set_index("id_student").loc[5]
    assert five["early_assessment_count"] == 0
    assert pd.isna(five["early_assessment_coverage"])  # no scheduled assessments in this presentation
    assert pd.isna(two["registration_day"])  # positive registration after prediction cutoff
    assert two[TARGET] == 1
    assert set(data.id_student) == {1, 2, 5}  # withdrawals already known at the cutoff are not future labels
    assert list(data.loc[:, FEATURES].columns) == FEATURES
    assert "date_unregistration" not in data.columns
    assert set(seq.id_student) == {1, 2}
    assert data.attrs["cohort_exclusions"]["excluded_withdrawn_before_prediction_day"] == 1
    assert data.attrs["cohort_exclusions"]["excluded_withdrawn_unknown_timing"] == 1
    assert seq.loc[seq.id_student.eq(1), "weekly_clicks"].iloc[0][0] == 3


def test_feature_order_is_explicit():
    assert len(FEATURES) == len(set(FEATURES))
    assert "id_student" not in FEATURES


def test_historical_record_id_is_stable_course_scoped_and_not_a_live_enrollment_number():
    record_id = historical_source_record_id("AAA", "2013B", 12345)
    assert record_id == historical_source_record_id("AAA", "2013B", 12345)
    assert record_id != historical_source_record_id("BBB", "2013B", 12345)
    assert record_id.startswith("oulad:student-course:v1:")
    assert not record_id.isdigit()


def test_duplicate_historical_student_course_identity_is_rejected(oulad_mini):
    path = oulad_mini / "studentInfo.csv"
    info = pd.read_csv(path)
    info = pd.concat([info, info.iloc[[0]]], ignore_index=True)
    info.to_csv(path, index=False)

    with pytest.raises(ValueError, match="duplicate student-course identities"):
        build_student_features(oulad_mini, chunk_size=1)


def test_canonical_training_export_preserves_history_without_live_enrollment_ids(oulad_mini, tmp_path):
    data, sequences = build_student_features(oulad_mini, chunk_size=1)
    path = tmp_path / "student_training_dataset.csv"
    count = write_canonical_training_dataset(data, sequences, path)

    canonical = pd.read_csv(path)
    assert count == 3
    assert canonical.columns.tolist() == CANONICAL_COLUMNS
    assert "enrollment_number" not in canonical.columns
    assert canonical["source_system"].eq("OULAD").all()
    assert canonical["source_record_id"].str.startswith("oulad:student-course:v1:").all()
    assert canonical["source_record_id"].is_unique
    assert canonical["source_student_id"].tolist() == [1, 2, 5]
    assert canonical.loc[0, "week_1_clicks"] == 3
    assert canonical.loc[0, "week_1_active_days"] == 1
    assert canonical.loc[1, "week_3_clicks"] == 2
    assert canonical.loc[1, "week_3_active_days"] == 1
    for _, row in canonical.iterrows():
        clicks = [row[f"week_{week}_clicks"] for week in range(1, 9)]
        active_days = [row[f"week_{week}_active_days"] for week in range(1, 9)]
        assert sum(clicks) == row["early_vle_clicks"]
        assert sum(active_days) == row["early_vle_active_days"]
        assert sum(value > 0 for value in clicks) == row["early_vle_active_weeks"]

    with pytest.raises(CSVImportValidationError) as error:
        parse_inference_csv(path.read_bytes())
    assert any(item["field"] == "enrollment_number" for item in error.value.errors)
    assert any(item["field"] == "header" for item in error.value.errors)
    assert any(item["field"] == "early_support_label" for item in error.value.errors)


def test_canonical_export_rejects_weekly_aggregate_mismatch(oulad_mini, tmp_path):
    data, sequences = build_student_features(oulad_mini, chunk_size=1)
    corrupted = sequences.copy(deep=True)
    corrupted.at[corrupted.index[0], "weekly_clicks"] = [4, 0, 0, 0, 0, 0, 0, 0]

    with pytest.raises(ValueError, match="do not reconcile"):
        write_canonical_training_dataset(data, corrupted, tmp_path / "invalid.csv")


def test_presentation_splits_purge_repeat_students_from_later_folds():
    data = pd.DataFrame([
        {"code_presentation": "2013B", "id_student": 1},
        {"code_presentation": "2013J", "id_student": 2},
        {"code_presentation": "2014B", "id_student": 1},
        {"code_presentation": "2014B", "id_student": 3},
        {"code_presentation": "2014J", "id_student": 2},
        {"code_presentation": "2014J", "id_student": 3},
        {"code_presentation": "2014J", "id_student": 4},
    ])
    train, validation, test = split_by_presentation(data)
    student_sets = [set(part.id_student) for part in (train, validation, test)]
    assert student_sets == [{1, 2}, {3}, {4}]
    assert not (student_sets[0] & student_sets[1])
    assert not (student_sets[0] & student_sets[2])
    assert not (student_sets[1] & student_sets[2])
