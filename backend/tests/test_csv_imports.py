import csv
import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.models import (
    BehavioralCluster,
    DatasetImport,
    Enrollment,
    ImportedFeatureSnapshot,
    Prediction,
    Student,
    User,
)
from backend.app.ml.model_manager import ModelUnavailable
from backend.app.services.csv_import import (
    CSVImportValidationError,
    parse_inference_csv,
    parse_inference_csv_report,
)
from ml.features.build_dataset import NUMERIC_FEATURES
from backend.tests.conftest import create_enrollment, login, register

def make_csv(rows=None, headers=None):
    if headers is None:
        headers = [
            "enrollment_number", *NUMERIC_FEATURES,
            "code_module", "code_presentation",
            *[column for week in range(1, 9)
              for column in (f"week_{week}_clicks", f"week_{week}_active_days")],
        ]
        for row in rows or [{}]:
            headers.extend(name for name in row if name not in headers)
    values = {
        "enrollment_number": "2403031500001",
        "code_module": "AAA",
        "code_presentation": "2013B",
        "registration_day": "0",
        "num_of_prev_attempts": "0",
        "studied_credits": "60",
        "early_assessment_mean": "70",
        "early_assessment_count": "2",
        "early_on_time_rate": "0.5",
        "early_assessment_coverage": "0.5",
        "early_vle_clicks": "36",
        "early_vle_active_days": "3",
        "early_vle_active_weeks": "3",
        "early_vle_active_sites": "4",
        "early_vle_activity_types": "3",
        **{f"week_{week}_clicks": "12" if week <= 3 else "0"
           for week in range(1, 9)},
        **{f"week_{week}_active_days": "1" if week <= 3 else "0"
           for week in range(1, 9)},
    }
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows or [values]:
        writer.writerow({**values, **row})
    return output.getvalue().encode("utf-8")


def seed_test_enrollments(app, rows):
    """Create only test-database enrollments corresponding to the supplied CSV rows."""
    session = app.state.session_factory()
    enrollment_ids = {}
    try:
        for index, row in enumerate(rows):
            features = row["features"]
            user = User(email=f"csv-import-test-{index:03d}@example.com",
                        password_hash="test-only-not-a-login", role="student", is_active=True)
            student = Student(user=user, enrollment_number=row["enrollment_number"],
                              access_approved=True)
            enrollment = Enrollment(
                student=student,
                code_module=features["code_module"],
                code_presentation=features["code_presentation"],
                registration_day=features["registration_day"],
                num_of_prev_attempts=features["num_of_prev_attempts"],
                studied_credits=features["studied_credits"],
                is_active=True,
            )
            session.add(user)
            session.flush()
            enrollment_ids[row["enrollment_number"]] = enrollment.id
        session.commit()
    finally:
        session.close()
    return enrollment_ids


def test_parse_valid_complete_csv_keeps_weekly_sequence():
    parsed = parse_inference_csv(make_csv())

    assert len(parsed) == 1
    assert parsed[0]["enrollment_number"] == "2403031500001"
    assert parsed[0]["features"]["early_vle_clicks"] == 36
    assert parsed[0]["weekly_sequence"] == [
        [12.0, 1.0], [12.0, 1.0], [12.0, 1.0], [0.0, 0.0],
        [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0],
    ]


def test_openapi_excludes_removed_synthetic_demo_routes(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/imports/validate" in paths
    assert not any(path.startswith("/api/demo/imports") for path in paths)


def test_parse_valid_aggregate_without_weekly_sequence_does_not_invent_weeks():
    parsed = parse_inference_csv(make_csv(headers=[
        "enrollment_number", *NUMERIC_FEATURES,
        "code_module", "code_presentation",
    ]))

    assert parsed[0]["weekly_sequence"] is None


def test_parse_rejects_duplicate_enrollment_numbers():
    with pytest.raises(CSVImportValidationError, match="CSV validation failed") as error:
        parse_inference_csv(make_csv(rows=[{}, {"week_1_clicks": "0"}]))

    assert any(item["field"] == "enrollment_number" and "Duplicate" in item["message"]
               for item in error.value.errors)


@pytest.mark.parametrize(
    ("change", "expected_field"),
    [
        ({"enrollment_number": "123"}, "enrollment_number"),
        ({"early_assessment_mean": "101"}, "features"),
        ({"week_1_clicks": "11"}, "weekly_sequence"),
        ({"early_support_label": "1"}, "header"),
    ],
)
def test_parse_rejects_bad_identity_ranges_sequence_and_training_labels(change, expected_field):
    with pytest.raises(CSVImportValidationError) as error:
        parse_inference_csv(make_csv(rows=[change]))

    assert any(item["field"] == expected_field for item in error.value.errors)


def test_parse_allows_weekly_sequence_to_be_entirely_absent():
    headers = [
        "enrollment_number", *NUMERIC_FEATURES,
        "code_module", "code_presentation",
    ]
    parsed = parse_inference_csv(make_csv(headers=headers))

    assert parsed[0]["weekly_sequence"] is None


def test_batch_parser_keeps_valid_rows_and_reports_bad_rows_and_all_duplicates():
    content = make_csv(rows=[
        {},
        {"enrollment_number": "2403031500002", "early_assessment_mean": "not-a-number"},
        {"enrollment_number": "2403031500003"},
        {"enrollment_number": "2403031500003"},
    ])
    rows, errors, total = parse_inference_csv_report(content)

    assert total == 4
    assert [row["enrollment_number"] for row in rows] == ["2403031500001"]
    assert {item["row"] for item in errors if "Duplicate" in item["message"]} == {4, 5}
    assert any(item["row"] == 3 and item["field"] == "early_assessment_mean" for item in errors)


def test_batch_parser_reports_missing_headers_and_training_labels_for_every_data_row():
    headers = ["registration_day", "early_support_label"]
    rows, errors, total = parse_inference_csv_report(
        b"registration_day,early_support_label\n-20,1\n-10,0\n"
    )

    assert rows == []
    assert total == 2
    assert {item["field"] for item in errors} >= {"enrollment_number", "header", "early_support_label"}


def test_batch_parser_reports_malformed_csv_at_its_source_row_without_losing_prior_rows():
    content = make_csv(rows=[{"enrollment_number": "2403031500001"}]) + b'"unterminated\n'

    rows, errors, total = parse_inference_csv_report(content)

    assert len(rows) == 1
    assert total == 2
    assert any(item["row"] == 3 and item["field"] == "csv" for item in errors)


def test_batch_parser_handles_the_five_thousand_row_limit():
    rows = [
        {"enrollment_number": f"24030315{number:05d}"}
        for number in range(1, 5001)
    ]

    parsed, errors, total = parse_inference_csv_report(make_csv(rows=rows))

    assert errors == []
    assert total == 5000
    assert len(parsed) == 5000
    assert parsed[0]["row"] == 2
    assert parsed[-1]["row"] == 5001


def test_batch_parser_rejects_files_over_the_five_thousand_row_limit():
    rows = [
        {"enrollment_number": f"24030315{number:05d}"}
        for number in range(1, 5002)
    ]

    parsed, errors, total = parse_inference_csv_report(make_csv(rows=rows))

    assert parsed == []
    assert total == 5001
    assert errors == [{
        "row": 5002,
        "field": "file",
        "message": "Upload exceeds the 5,000-row limit.",
    }]


def test_form_field_and_multipart_content_type_match_fastapi_contract(client):
    coordinator = register(client, "csv.form.contract@example.com", "coordinator", "test-coordinator-invite")
    headers = login(client, coordinator["email"])

    response = client.post(
        "/api/imports/validate",
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        data={"file": "enrollment_number"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [{
        "loc": ["body", "file"],
        "msg": "Value error, Expected UploadFile, received: <class 'str'>",
        "type": "value_error",
    }]


def test_coordinator_import_persists_real_api_records_and_is_idempotent(client, app):
    student_user = register(client, "csv.student@example.com")
    coordinator_user = register(
        client, "csv.coordinator@example.com", "coordinator", "test-coordinator-invite"
    )
    student_headers = login(client, student_user["email"])
    coordinator_headers = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student_headers).json()
    enrollment = create_enrollment(client, coordinator_headers, profile["id"])
    session = app.state.session_factory()
    try:
        student = session.get(Student, UUID(profile["id"]))
        student.enrollment_number = "2403031500001"
        session.commit()
    finally:
        session.close()

    calls = {"supervised": 0, "cluster": 0, "sequence": 0}

    def predict(features):
        calls["supervised"] += 1
        return {
            "model": "test-model",
            "model_version": "test",
            "feature_version": "test-features",
            "support_priority_score": 0.25,
            "threshold": 0.2,
            "priority_band": "review_for_support",
            "observed_signals": {"early_vle_clicks": features["early_vle_clicks"]},
        }

    def cluster_many(features_list):
        calls["cluster"] += len(features_list)
        return [{
            "cluster_id": index % 2,
            "model_version": "test",
            "feature_version": "test-features",
            "features": features,
        } for index, features in enumerate(features_list)]

    def predict_sequence(sequence):
        calls["sequence"] += 1
        # ModelManager.predict_sequence returns the LSTM's registry version.
        return {
            "model_version": "registry-lstm-version",
            "support_priority_score": 0.3,
            "threshold": 0.2,
            "priority_band": "review_for_support",
            "feature_version": "test-features",
        }

    app.state.model_manager.predict = predict
    app.state.model_manager.cluster_many = cluster_many
    app.state.model_manager.predict_sequence = predict_sequence
    content = make_csv(rows=[{"registration_day": "-20"}])

    assert client.get("/api/imports/template").status_code == 401
    template = client.get("/api/imports/template", headers=coordinator_headers)
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("text/csv")
    assert "early_support_label" not in template.text
    validation = client.post(
        "/api/imports/validate",
        headers=coordinator_headers,
        files={"file": ("source.csv", content, "text/csv")},
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["forecast_rows"] == 1

    response = client.post(
        "/api/imports",
        headers=coordinator_headers,
        files={"file": ("source.csv", content, "text/csv")},
    )

    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["already_imported"] is False
    assert imported["records"][0]["enrollment_id"] == enrollment["id"]
    assert imported["records"][0]["cluster_id"] == 0
    assert imported["records"][0]["forecast_id"]

    replay = client.post(
        "/api/imports",
        headers=coordinator_headers,
        files={"file": ("source.csv", content, "text/csv")},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_imported"] is True
    assert replay.json()["records"] == imported["records"]
    assert calls == {"supervised": 1, "cluster": 1, "sequence": 1}

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(DatasetImport)) == 1
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(Prediction)) == 2
        assert session.scalar(select(func.count()).select_from(BehavioralCluster)) == 1
        forecast = session.get(Prediction, UUID(imported["records"][0]["forecast_id"]))
        # Imported LSTM forecasts must carry the version of the model that scored them.
        assert (forecast.model_name, forecast.model_version) == ("lstm_weekly", "registry-lstm-version")
    finally:
        session.close()


def test_multi_student_import_runs_each_valid_row_and_skips_unknown_rows(client, app):
    coordinator = register(client, "csv.multi.coordinator@example.com", "coordinator", "test-coordinator-invite")
    headers = login(client, coordinator["email"])
    student_ids = []
    enrollment_numbers = ["2403031500101", "2403031500102"]
    for index, number in enumerate(enrollment_numbers):
        student = register(client, f"csv.multi.student{index}@example.com")
        student_headers = login(client, student["email"])
        profile = client.get("/api/students/me", headers=student_headers).json()
        created = create_enrollment(client, headers, profile["id"])
        session = app.state.session_factory()
        try:
            record = session.get(Student, UUID(profile["id"]))
            record.enrollment_number = number
            session.commit()
        finally:
            session.close()
        student_ids.append((profile["id"], created["id"], student_headers))

    calls = {"predict": 0, "cluster": 0}

    def prediction(features):
        calls["predict"] += 1
        return {"model": "test-model", "model_version": "test", "feature_version": "test",
                "support_priority_score": 0.4, "threshold": 0.2,
                "priority_band": "review_for_support",
                "observed_signals": {"early_vle_clicks": features["early_vle_clicks"]}}

    def clustering(features_list):
        calls["cluster"] += len(features_list)
        return [{"cluster_id": index, "model_version": "test",
                 "feature_version": "test", "features": features}
                for index, features in enumerate(features_list)]

    app.state.model_manager.predict = prediction
    app.state.model_manager.cluster_many = clustering
    app.state.model_manager.predict_sequence = lambda _sequence: None
    content = make_csv(rows=[
        {"enrollment_number": enrollment_numbers[0], "registration_day": "-20"},
        {"enrollment_number": "2403031599999", "registration_day": "-20"},
        {"enrollment_number": enrollment_numbers[1], "registration_day": "-20",
         "early_vle_clicks": "99",
         **{f"week_{week}_{measure}": "" for week in range(1, 9)
            for measure in ("clicks", "active_days")}},
    ])

    validation = client.post("/api/imports/validate", headers=headers,
        files={"file": ("multi.csv", content, "text/csv")})
    assert validation.status_code == 200, validation.text
    assert (validation.json()["total_rows"], validation.json()["valid_rows"],
            validation.json()["invalid_rows"]) == (3, 2, 1)
    assert validation.json()["unmatched_rows"] == [3]
    assert validation.json()["unknown_rows"] == [3]
    assert validation.json()["unknown_enrollment_numbers"] == ["2403031599999"]

    response = client.post("/api/imports", headers=headers,
        files={"file": ("multi.csv", content, "text/csv")})
    assert response.status_code == 201, response.text
    imported = response.json()
    assert (imported["total_rows"], imported["valid_rows"], imported["invalid_rows"]) == (3, 2, 1)
    assert len(imported["records"]) == 2
    assert {record["source_row"] for record in imported["records"]} == {2, 4}
    assert {record["cluster_id"] for record in imported["records"]} == {0, 1}
    assert calls == {"predict": 2, "cluster": 2}

    records_by_enrollment = {
        record["enrollment_id"]: record for record in imported["records"]
    }
    for student_id, enrollment_id, student_headers in student_ids:
        prediction_record = records_by_enrollment[enrollment_id]
        own_predictions = client.get(
            f"/api/predictions/{student_id}?enrollment_id={enrollment_id}",
            headers=student_headers,
        )
        assert own_predictions.status_code == 200, own_predictions.text
        assert [item["id"] for item in own_predictions.json()] == [
            prediction_record["prediction_id"]
        ]
        assert own_predictions.json()[0]["observed_signals"]["early_vle_clicks"] == (
            36 if enrollment_id == student_ids[0][1] else 99
        )

        plan = client.post(
            f"/api/students/{student_id}/study-plan",
            headers=student_headers,
            json={"enrollment_id": enrollment_id},
        )
        assert plan.status_code == 201, plan.text
        assert plan.json()["study_plan"]["source_prediction_id"] == (
            prediction_record["prediction_id"]
        )
        own_plans = client.get(
            f"/api/students/{student_id}/study-plan?enrollment_id={enrollment_id}",
            headers=student_headers,
        )
        assert own_plans.status_code == 200
        assert [item["id"] for item in own_plans.json()] == [
            plan.json()["study_plan"]["id"]
        ]

        other_student_id = next(
            item[0] for item in student_ids if item[0] != student_id
        )
        assert client.get(
            f"/api/predictions/{other_student_id}",
            headers=student_headers,
        ).status_code == 404
        assert client.get(
            f"/api/students/{other_student_id}/study-plan",
            headers=student_headers,
        ).status_code == 404

    assert client.get("/api/analytics/overview", headers=headers).json()[
        "risk_distribution"
    ]["review_for_support"] == 2
    analytics = client.get("/api/analytics/overview", headers=headers).json()
    assert analytics["predictions"] == 2
    assert analytics["imports_total"] == 1
    assert analytics["latest_import"]["valid_rows"] == 2
    assert analytics["latest_import"]["invalid_rows"] == 1
    monitoring = client.get(
        "/api/analytics/monitoring/students?limit=10",
        headers=headers,
    )
    assert monitoring.status_code == 200, monitoring.text
    assert monitoring.json()["total"] == 2
    assert {
        item["latest_prediction"]["enrollment_id"]
        for item in monitoring.json()["items"]
    } == {enrollment_id for _student_id, enrollment_id, _headers in student_ids}

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(Student)) == 2
        assert session.scalar(select(func.count()).select_from(Enrollment)) == 2
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(Prediction)) == 2
    finally:
        session.close()


def test_inactive_and_unknown_enrollments_are_reported_and_never_imported(client, app):
    coordinator = register(client, "csv.inactive.coordinator@example.com", "coordinator", "test-coordinator-invite")
    headers = login(client, coordinator["email"])
    numbers = ["2403031500201", "2403031500202", "2403031500203"]
    for index, number in enumerate(numbers):
        student = register(client, f"csv.inactive.student{index}@example.com")
        profile = client.get("/api/students/me", headers=login(client, student["email"])).json()
        create_enrollment(client, headers, profile["id"])
        session = app.state.session_factory()
        try:
            record = session.get(Student, UUID(profile["id"]))
            record.enrollment_number = number
            if index == 1:
                record.enrollments[0].is_active = False
            if index == 2:
                session.get(User, UUID(student["id"])).is_active = False
            session.commit()
        finally:
            session.close()

    calls = {"predict": 0, "cluster": 0}
    app.state.model_manager.predict = lambda features: calls.__setitem__(
        "predict", calls["predict"] + 1
    ) or {"model": "test", "model_version": "test", "feature_version": "test",
          "support_priority_score": 0.2, "threshold": 0.5,
          "priority_band": "no_flag_from_model", "observed_signals": {}}
    app.state.model_manager.cluster_many = lambda feature_rows: (
        calls.__setitem__("cluster", calls["cluster"] + len(feature_rows)) or [
            {"cluster_id": index, "model_version": "test", "feature_version": "test",
             "features": features}
            for index, features in enumerate(feature_rows)
        ]
    )
    app.state.model_manager.predict_sequence = lambda _sequence: None
    content = make_csv(rows=[
        {"enrollment_number": numbers[0], "registration_day": "-20"},
        {"enrollment_number": numbers[1], "registration_day": "-20"},
        {"enrollment_number": numbers[2], "registration_day": "-20"},
        {"enrollment_number": "2403031599999", "registration_day": "-20"},
    ])

    validation = client.post("/api/imports/validate", headers=headers,
        files={"file": ("states.csv", content, "text/csv")})

    assert validation.status_code == 200, validation.text
    report = validation.json()
    assert (report["total_rows"], report["valid_rows"], report["invalid_rows"]) == (4, 1, 3)
    assert report["inactive_rows"] == [3, 4]
    assert report["unknown_rows"] == [5]
    assert report["inactive_enrollment_numbers"] == numbers[1:]
    assert report["unknown_enrollment_numbers"] == ["2403031599999"]

    response = client.post("/api/imports", headers=headers,
        files={"file": ("states.csv", content, "text/csv")})

    assert response.status_code == 201, response.text
    assert (response.json()["valid_rows"], response.json()["invalid_rows"]) == (1, 3)
    assert len(response.json()["records"]) == 1
    assert calls == {"predict": 1, "cluster": 1}

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(Student)) == 3
        assert session.scalar(select(func.count()).select_from(Enrollment)) == 3
    finally:
        session.close()


def test_100_row_import_runs_models_persists_and_replays_in_test_database(client, app):
    assert app.state.engine.url.get_backend_name() == "sqlite"
    coordinator = register(client, "csv.batch100.coordinator@example.com", "coordinator",
                           "test-coordinator-invite")
    headers = login(client, coordinator["email"])
    numbers = [f"240303151{index:04d}" for index in range(100)]
    content = make_csv(rows=[{"enrollment_number": number} for number in numbers])
    parsed = parse_inference_csv(content)
    enrollment_ids = seed_test_enrollments(app, parsed)
    calls = {"supervised": 0, "sequence": 0, "cluster": 0}

    def predict(features):
        calls["supervised"] += 1
        return {"model": "isolated-test-model", "model_version": "test",
                "feature_version": "test-fixture", "support_priority_score": 0.35,
                "threshold": 0.2, "priority_band": "review_for_support",
                "observed_signals": {"early_vle_clicks": features["early_vle_clicks"]}}

    def predict_sequence(_sequence):
        calls["sequence"] += 1
        return {"model_version": "test", "support_priority_score": 0.3, "threshold": 0.2,
                "priority_band": "review_for_support", "feature_version": "test-fixture"}

    def cluster_many(features_list):
        calls["cluster"] += len(features_list)
        return [{"cluster_id": index % 5, "model_version": "test",
                 "feature_version": "test-fixture", "features": features}
                for index, features in enumerate(features_list)]

    app.state.model_manager.predict = predict
    app.state.model_manager.predict_sequence = predict_sequence
    app.state.model_manager.cluster_many = cluster_many

    validation = client.post("/api/imports/validate", headers=headers,
        files={"file": ("batch.csv", content, "text/csv")})
    assert validation.status_code == 200, validation.text
    assert (validation.json()["total_rows"], validation.json()["valid_rows"],
            validation.json()["invalid_rows"], validation.json()["forecast_rows"]) == (100, 100, 0, 100)

    response = client.post("/api/imports", headers=headers,
        files={"file": ("batch.csv", content, "text/csv")})
    assert response.status_code == 201, response.text
    imported = response.json()
    assert (imported["total_rows"], imported["valid_rows"], imported["invalid_rows"]) == (100, 100, 0)
    assert len(imported["records"]) == 100
    assert calls == {"supervised": 100, "sequence": 100, "cluster": 100}

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(DatasetImport)) == 1
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 100
        assert session.scalar(select(func.count()).select_from(Prediction)) == 200
        assert session.scalar(select(func.count()).select_from(BehavioralCluster)) == 100
        snapshots = list(session.scalars(select(ImportedFeatureSnapshot).order_by(
            ImportedFeatureSnapshot.source_row)))
        assert [item.source_row for item in snapshots] == list(range(2, 102))
        assert {item.enrollment_id for item in snapshots} == set(enrollment_ids.values())
        assert all(item.forecast_prediction_id is not None for item in snapshots)
    finally:
        session.close()

    analytics = client.get("/api/analytics/overview", headers=headers)
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["imports_total"] == 1
    assert analytics.json()["latest_import"]["valid_rows"] == 100
    assert analytics.json()["latest_import"]["invalid_rows"] == 0

    replay = client.post("/api/imports", headers=headers,
        files={"file": ("batch.csv", content, "text/csv")})
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_imported"] is True
    assert replay.json()["records"] == imported["records"]
    assert calls == {"supervised": 100, "sequence": 100, "cluster": 100}


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("unavailable", 503), ("contract", 422)],
)
def test_inference_errors_do_not_persist_import_records(client, app, failure, expected_status):
    coordinator = register(client, f"csv.inference-{failure}@example.com", "coordinator",
                           "test-coordinator-invite")
    headers = login(client, coordinator["email"])
    content = make_csv()
    parsed = parse_inference_csv(content)
    seed_test_enrollments(app, parsed)

    def fail_inference(_features):
        if failure == "unavailable":
            raise ModelUnavailable("isolated test failure")
        raise ValueError("isolated feature contract failure")

    app.state.model_manager.predict = fail_inference
    response = client.post("/api/imports", headers=headers,
        files={"file": ("isolated.csv", content, "text/csv")})
    assert response.status_code == expected_status

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(DatasetImport)) == 0
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
        assert session.scalar(select(func.count()).select_from(BehavioralCluster)) == 0
    finally:
        session.close()


def test_persistence_constraint_failure_rolls_back_entire_import(client, app):
    coordinator = register(client, "csv.rollback.coordinator@example.com", "coordinator",
                           "test-coordinator-invite")
    headers = login(client, coordinator["email"])
    content = make_csv()
    parsed = parse_inference_csv(content)
    seed_test_enrollments(app, parsed)
    app.state.model_manager.predict = lambda _features: {
        "model": "isolated-test-model", "model_version": "test",
        "feature_version": "test-fixture", "support_priority_score": 1.5,
        "threshold": 0.2, "priority_band": "review_for_support", "observed_signals": {},
    }
    app.state.model_manager.predict_sequence = lambda _sequence: {
        "model_version": "test", "support_priority_score": 0.3, "threshold": 0.2,
        "priority_band": "review_for_support", "feature_version": "test-fixture",
    }
    app.state.model_manager.cluster_many = lambda feature_rows: [
        {"cluster_id": 0, "model_version": "test", "feature_version": "test-fixture",
         "features": features} for features in feature_rows
    ]

    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.post("/api/imports", headers=headers,
            files={"file": ("rollback.csv", content, "text/csv")})
    assert response.status_code == 500

    session = app.state.session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(DatasetImport)) == 0
        assert session.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
        assert session.scalar(select(func.count()).select_from(BehavioralCluster)) == 0
    finally:
        session.close()
