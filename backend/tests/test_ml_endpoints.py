from backend.tests.conftest import login, register, create_enrollment, ingest_model_sources
import pandas as pd
import pytest
from uuid import UUID
from backend.app.models import Enrollment
from backend.app.services.feature_assembly import (build_student_features as assemble_inference_features,
    build_weekly_sequence)
from ml.features.build_dataset import FEATURES, build_student_features as build_oulad_features


def test_oulad_training_features_match_backend_inference_contract(client, tmp_path):
    # This synthetic fixture compares transformations only. Source IDs are never
    # looked up as application enrollment numbers or stored against test accounts.
    raw = tmp_path / "oulad"
    raw.mkdir()
    source_rows = {
        "studentInfo.csv": [{
            "code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
            "gender": "F", "region": "R", "highest_education": "H", "imd_band": "x",
            "age_band": "0-35", "num_of_prev_attempts": 0, "studied_credits": 60,
            "disability": "N", "final_result": "Fail",
        }, {
            "code_module": "AAA", "code_presentation": "2013B", "id_student": 23456,
            "gender": "M", "region": "R", "highest_education": "H", "imd_band": "x",
            "age_band": "0-35", "num_of_prev_attempts": 1, "studied_credits": 60,
            "disability": "N", "final_result": "Pass",
        }],
        "studentRegistration.csv": [{
            "code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
            "date_registration": -20, "date_unregistration": None,
        }, {
            "code_module": "AAA", "code_presentation": "2013B", "id_student": 23456,
            "date_registration": 80, "date_unregistration": None,
        }],
        "courses.csv": [{
            "code_module": "AAA", "code_presentation": "2013B", "module_presentation_length": 240,
        }],
        "assessments.csv": [
            {"code_module": "AAA", "code_presentation": "2013B", "id_assessment": 10,
             "assessment_type": "TMA", "date": 28, "weight": 40},
            {"code_module": "AAA", "code_presentation": "2013B", "id_assessment": 11,
             "assessment_type": "TMA", "date": 35, "weight": 40},
            {"code_module": "AAA", "code_presentation": "2013B", "id_assessment": 12,
             "assessment_type": "Exam", "date": 70, "weight": 20},
        ],
        "studentAssessment.csv": [
            {"id_assessment": 10, "id_student": 12345, "date_submitted": 20, "is_banked": 0, "score": 82},
            {"id_assessment": 11, "id_student": 12345, "date_submitted": 45, "is_banked": 0, "score": 62},
            {"id_assessment": 12, "id_student": 12345, "date_submitted": 40, "is_banked": 0, "score": 99},
        ],
        "vle.csv": [
            {"id_site": 101, "code_module": "AAA", "code_presentation": "2013B",
             "activity_type": "resource", "week_from": 0, "week_to": 1},
            {"id_site": 102, "code_module": "AAA", "code_presentation": "2013B",
             "activity_type": "forumng", "week_from": 0, "week_to": 1},
            {"id_site": 103, "code_module": "AAA", "code_presentation": "2013B",
             "activity_type": "quiz", "week_from": 0, "week_to": 1},
        ],
        "studentVle.csv": [
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 101, "date": 1, "sum_click": 40},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 102, "date": 2, "sum_click": 30},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 103, "date": 3, "sum_click": 30},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 101, "date": 8, "sum_click": 15},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 102, "date": 9, "sum_click": 20},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 103, "date": 10, "sum_click": 25},
            {"code_module": "AAA", "code_presentation": "2013B", "id_student": 12345,
             "id_site": 101, "date": 11, "sum_click": 15},
        ],
    }
    for filename, rows in source_rows.items():
        pd.DataFrame(rows).to_csv(raw / filename, index=False)
    training, sequences = build_oulad_features(raw, chunk_size=2)

    profile, enrollment, _student, coordinator = setup_accounts(client)
    second_user = register(client, "ml.student.second@example.com")
    second_headers = login(client, second_user["email"])
    second_profile = client.get("/api/students/me", headers=second_headers).json()
    response = client.post(f"/api/students/{second_profile['id']}/enrollments", headers=coordinator,
        json={"code_module": "AAA", "code_presentation": "2013B", "registration_day": None,
            "num_of_prev_attempts": 1, "studied_credits": 60})
    assert response.status_code == 201, response.text
    second_enrollment = response.json()
    app_enrollments = [(profile, enrollment), (second_profile, second_enrollment)]
    for _profile, app_enrollment in app_enrollments:
        schedule = client.put(f"/api/enrollments/{app_enrollment['id']}/assessment-schedule",
            headers=coordinator, json={"assessments": [
                {"assessment_key": "10", "scheduled_day": 28, "weight": 40},
                {"assessment_key": "11", "scheduled_day": 35, "weight": 40},
                {"assessment_key": "12", "scheduled_day": 70, "weight": 20},
            ]})
        assert schedule.status_code == 200, schedule.text
    for key, score, day in (("10", 82, 20), ("11", 62, 45), ("12", 99, 40)):
        response = client.post(
            f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
            headers=coordinator, json={"record_type": "assessment_score", "score": score,
                "assessment_key": key, "submitted_day": day})
        assert response.status_code == 201, response.text
    weekly = [
        (100, 3), (75, 4), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0),
    ]
    for profile_row, app_enrollment in app_enrollments:
        activity = weekly if profile_row["id"] == profile["id"] else [(0, 0)] * 8
        for week, (clicks, days) in enumerate(activity):
            response = client.post(
                f"/api/students/{profile_row['id']}/engagement?enrollment_id={app_enrollment['id']}",
                headers=coordinator, json={"week_index": week, "clicks": clicks, "active_days": days,
                    "active_site_ids": [101, 102, 103] if clicks else [],
                    "activity_types": ["resource", "forumng", "quiz"] if clicks else []})
            assert response.status_code == 201, response.text

    training_rows = training.set_index("id_student")
    with client.app.state.session_factory() as db:
        for source_student_id, app_enrollment in zip((12345, 23456), (enrollment, second_enrollment), strict=True):
            enrollment_record = db.get(Enrollment, UUID(app_enrollment["id"]))
            inference = assemble_inference_features(db, enrollment_record)
            inference_sequence = build_weekly_sequence(db, enrollment_record)
            training_row = training_rows.loc[source_student_id]
            assert list(inference) == FEATURES
            for feature in FEATURES:
                expected = training_row[feature]
                actual = inference[feature]
                if pd.isna(expected):
                    assert actual is None, (source_student_id, feature)
                elif feature in {"code_module", "code_presentation"}:
                    assert actual == expected, (source_student_id, feature)
                else:
                    assert actual == pytest.approx(float(expected)), (source_student_id, feature)

            sequence_match = sequences.loc[sequences.id_student.eq(source_student_id)]
            expected_sequence = [[0.0, 0.0]] * 8
            if not sequence_match.empty:
                sequence_row = sequence_match.iloc[0]
                expected_sequence = [[float(clicks), float(days)] for clicks, days in zip(
                    sequence_row["weekly_clicks"], sequence_row["weekly_active_days"], strict=True)]
            assert inference_sequence == expected_sequence


def setup_accounts(client):
    student_user = register(client, "ml.student@example.com")
    coordinator_user = register(client, "ml.coord@example.com", "coordinator", "test-coordinator-invite")
    student_headers = login(client, student_user["email"])
    coordinator_headers = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student_headers).json()
    enrollment = create_enrollment(client, coordinator_headers, profile["id"])
    return profile, enrollment, student_headers, coordinator_headers


def test_supervised_prediction_is_persisted_and_student_can_only_read_self(client):
    profile, enrollment, student, coordinator = setup_accounts(client)
    ingest_model_sources(client, coordinator, profile["id"], enrollment["id"])
    body = {"enrollment_id": enrollment["id"]}
    forbidden = client.post(f"/api/predictions/{profile['id']}", headers=student, json=body)
    assert forbidden.status_code == 403
    response = client.post(f"/api/predictions/{profile['id']}", headers=coordinator, json=body)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["model_name"] in {"logistic_regression", "random_forest", "xgboost"}
    assert payload["model_version"] == "1.2.0"
    assert 0 <= payload["support_priority_score"] <= 1
    assert payload["observed_signals"]["early_assessment_mean"] == 72
    assert payload["observed_signals"]["early_assessment_count"] == 2
    assert payload["observed_signals"]["early_on_time_rate"] == 0.5
    assert payload["observed_signals"]["early_assessment_coverage"] == 1
    assert payload["observed_signals"]["early_vle_clicks"] == 175
    assert payload["observed_signals"]["early_vle_active_sites"] == 3
    assert payload["observed_signals"]["early_vle_activity_types"] == 3
    own = client.get(f"/api/predictions/{profile['id']}", headers=student)
    assert own.status_code == 200 and len(own.json()) == 1
    assert client.get("/api/predictions", headers=student).status_code == 403


def test_cluster_and_lstm_are_served_through_api(client):
    profile, enrollment, student, coordinator = setup_accounts(client)
    ingest_model_sources(client, coordinator, profile["id"], enrollment["id"])
    cluster = client.post(f"/api/clusters/{profile['id']}", headers=coordinator,
        json={"enrollment_id":enrollment["id"]})
    assert cluster.status_code == 201, cluster.text
    read_cluster = client.get(f"/api/students/{profile['id']}/cluster", headers=student)
    assert read_cluster.status_code == 200
    assert read_cluster.json()["cluster_id"] in (0, 1)
    assert read_cluster.json()["model_version"] == "1.2.0"
    profiles = client.get("/api/analytics/clusters", headers=coordinator)
    assert profiles.status_code == 200
    current_profile = next(row for row in profiles.json() if row["cluster_id"] == cluster.json()["cluster_id"])
    assert current_profile["student_count"] == 1 and current_profile["enrollment_count"] == 1
    assert current_profile["median_features"]["early_vle_clicks"] == 175

    lstm = client.post(f"/api/predictions/{profile['id']}/sequence", headers=coordinator,
        json={"enrollment_id":enrollment["id"]})
    assert lstm.status_code == 201, lstm.text
    assert lstm.json()["model_name"] == "lstm_weekly"
    assert lstm.json()["model_version"] == "1.1.0"
    assert lstm.json()["observed_signals"]["weekly_sequence"][:2] == [[100.0, 3.0], [75.0, 4.0]]


def test_models_reject_incomplete_early_history_without_filling_missing_weeks(client):
    profile, enrollment, _student, coordinator = setup_accounts(client)
    body = {"enrollment_id": enrollment["id"]}
    for path in (f"/api/predictions/{profile['id']}",
                 f"/api/predictions/{profile['id']}/sequence",
                 f"/api/clusters/{profile['id']}"):
        response = client.post(path, headers=coordinator, json=body)
        assert response.status_code == 409
        assert "Insufficient historical data" in response.json()["detail"]


def test_prediction_rejects_invalid_and_mismatched_contract(client):
    profile, enrollment, _student, coordinator = setup_accounts(client)
    body = {"enrollment_id": enrollment["id"], "features":{"early_vle_clicks":999999}}
    response = client.post(f"/api/predictions/{profile['id']}", headers=coordinator, json=body)
    assert response.status_code == 422
    assert "999999" not in response.text
    malformed_sequence = client.post(f"/api/predictions/{profile['id']}/sequence", headers=coordinator,
        json={"enrollment_id": enrollment["id"], "sequence": [[1, 1]]})
    assert malformed_sequence.status_code == 422


def test_grade_score_prediction_is_distinct_persisted_and_student_scoped(client):
    student_user = register(client, "grade.student@example.com")
    other_user = register(client, "grade.other@example.com")
    coordinator_user = register(client, "grade.coord@example.com", "coordinator", "test-coordinator-invite")
    student_headers = login(client, student_user["email"])
    other_headers = login(client, other_user["email"])
    coordinator_headers = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student_headers).json()
    enrollment = create_enrollment(client, coordinator_headers, profile["id"], "DDD", "2014J")
    ingest_model_sources(client, coordinator_headers, profile["id"], enrollment["id"])

    response = client.post(f"/api/predictions/{profile['id']}/grade-score",
        headers=coordinator_headers, json={"enrollment_id": enrollment["id"]})
    assert response.status_code == 201, response.text
    prediction = response.json()
    assert prediction["target_name"] == "final_exam_score"
    assert prediction["prediction_day"] == 56
    assert 0 <= prediction["predicted_score"] <= 100
    assert prediction["model_name"] == "random_forest_final_exam_regressor"
    assert prediction["model_version"] == "oulad-final-exam-v2"
    assert "support_priority_score" not in prediction

    own = client.get(f"/api/predictions/{profile['id']}/grade-score", headers=student_headers)
    assert own.status_code == 200 and [row["id"] for row in own.json()] == [prediction["id"]]
    denied = client.get(f"/api/predictions/{profile['id']}/grade-score", headers=other_headers)
    assert denied.status_code == 404


def test_grade_score_prediction_explains_unsupported_module(client):
    profile, enrollment, _student, coordinator = setup_accounts(client)
    response = client.post(f"/api/predictions/{profile['id']}/grade-score",
        headers=coordinator, json={"enrollment_id": enrollment["id"]})
    assert response.status_code == 409
    assert "CCC and DDD" in response.json()["detail"]


def test_ingestion_rejects_out_of_contract_feature_totals(client):
    profile, enrollment, _student, coordinator = setup_accounts(client)
    response = client.post(f"/api/students/{profile['id']}/engagement?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"week_index":0,"clicks":9482,"active_days":1,
            "active_site_ids":[],"activity_types":[]})
    assert response.status_code == 422


def test_coordinator_monitoring_filters_are_paginated_and_role_protected(client):
    profile, enrollment, _student, coordinator = setup_accounts(client)
    ingest_model_sources(client, coordinator, profile["id"], enrollment["id"])
    response = client.get("/api/analytics/monitoring/students?risk_filter=unscored&limit=1",
        headers=coordinator)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["enrollment_count"] == 1
    assert response.json()["items"][0]["latest_prediction"] is None

    prediction = client.post(f"/api/predictions/{profile['id']}", headers=coordinator,
        json={"enrollment_id": enrollment["id"]})
    assert prediction.status_code == 201
    band = prediction.json()["priority_band"]
    filtered = client.get(f"/api/analytics/monitoring/students?risk_filter={band}&search=ml.student",
        headers=coordinator)
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["latest_prediction"]["priority_band"] == band
    assert client.get("/api/analytics/monitoring/students", headers={}).status_code == 401

