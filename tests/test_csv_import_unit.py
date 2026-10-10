"""CSV parser and route-function checks with no application, engine, or database."""
import ast
import csv
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import joblib
import pytest
import sqlalchemy
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from backend.app.api.routes import imports, study_plans
from backend.app.llm.service import StudyPlanService
from backend.app.models import ImportedFeatureSnapshot, Prediction
from backend.app.schemas.llm import StudySupportContext, SupportAssistantQuestion
from backend.app.services import csv_import


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "data/test_fixtures/coordinator_upload"


class MemoryUpload:
    """Mock async upload I/O without an event loop, threads, or sockets."""
    def __init__(self, file, filename=None):
        self.file = file
        self.filename = filename

    async def read(self, size):
        return self.file.read(size)


def run_immediate(coroutine):
    """Drive a route whose mocked I/O completes without suspending."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    raise AssertionError("Mocked route must complete without an external I/O wait")


@pytest.fixture(autouse=True)
def forbid_runtime_access(monkeypatch):
    """Fail if any tested path tries to open a database or load real ML artifacts."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("These tests permit only in-memory mocks")

    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(sqlalchemy.engine.Engine, "connect", forbidden)
    monkeypatch.setattr(joblib, "load", forbidden)


def csv_content(rows=None, headers=None):
    with (FIXTURE_DIR / "coordinator_upload_valid.test.csv").open(
            encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        original_headers = reader.fieldnames
        fixture_rows = list(reader)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers or original_headers,
                            extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows or fixture_rows[:1])
    return output.getvalue().encode("utf-8")


def fixture_rows():
    with (FIXTURE_DIR / "coordinator_upload_valid.test.csv").open(
            encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize("format_value", [lambda value: f"{value}.0",
                                         lambda value: f"{value}e0"])
def test_integer_weekly_values_keep_the_validated_numeric_representation(format_value):
    row = fixture_rows()[0]
    for column in csv_import.WEEKLY_COLUMNS:
        row[column] = format_value(row[column])
    content = csv_content([row])
    strict = csv_import.parse_inference_csv(content)
    parsed, errors, total = csv_import.parse_inference_csv_report(content)
    assert parsed == strict
    assert total == 1 and errors == []
    assert sum(week[0] for week in parsed[0]["weekly_sequence"]) == parsed[0]["features"]["early_vle_clicks"]


@pytest.mark.parametrize("field", ["week_1_clicks", "week_1_active_days"])
@pytest.mark.parametrize("value", ["not-a-number", "NaN", "Infinity", "1.5", "-1", "9482"])
def test_invalid_weekly_values_return_field_errors_instead_of_server_errors(field, value):
    row = fixture_rows()[0]
    row[field] = value
    content = csv_content([row])
    with pytest.raises(csv_import.CSVImportValidationError) as error:
        csv_import.parse_inference_csv(content)
    assert any(item["field"] == field for item in error.value.errors)
    parsed, errors, total = csv_import.parse_inference_csv_report(content)
    assert parsed == [] and total == 1
    assert any(item["field"] == field for item in errors)


def test_malformed_header_has_the_same_safe_error_in_both_parsers():
    content = b'"unterminated-header\n'
    with pytest.raises(csv_import.CSVImportValidationError) as error:
        csv_import.parse_inference_csv(content)
    parsed, errors, total = csv_import.parse_inference_csv_report(content)
    assert parsed == [] and total == 0
    assert error.value.errors == errors == [
        {"row": 1, "field": "header", "message": "Malformed CSV header."}]


def test_partial_weekly_header_is_rejected_even_when_the_present_column_is_blank():
    row = fixture_rows()[0]
    row["week_1_clicks"] = ""
    headers = ["enrollment_number", *csv_import.FEATURES, "week_1_clicks"]
    content = csv_content([row], headers)
    with pytest.raises(csv_import.CSVImportValidationError) as error:
        csv_import.parse_inference_csv(content)
    parsed, errors, total = csv_import.parse_inference_csv_report(content)
    assert parsed == [] and total == 1
    assert error.value.errors == errors
    assert errors[0]["row"] == 1 and errors[0]["field"] == "weekly_sequence"


def test_strict_row_limit_counts_rejected_rows_too(monkeypatch):
    monkeypatch.setattr(csv_import, "MAX_ROWS", 2)
    rows = [dict(fixture_rows()[0], enrollment_number="invalid") for _ in range(3)]
    with pytest.raises(csv_import.CSVImportValidationError) as error:
        csv_import.parse_inference_csv(csv_content(rows))
    assert any(item["field"] == "file" and item["row"] == 4 for item in error.value.errors)


class ReadOnlyEnrollmentMock:
    """Only query results exist: no engine, sessions, or write methods."""
    def __init__(self, records):
        self.records = records

    def execute(self, _statement):
        return SimpleNamespace(all=lambda: self.records)


def mapped_enrollments():
    records = {}
    with (FIXTURE_DIR / "synthetic_enrollment_mapping.test-only.csv").open(
            encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["seed_enrollment"] != "true":
                continue
            number = row["synthetic_enrollment_number"]
            records[number] = (number, True, SimpleNamespace(
                id=uuid4(), is_active=row["seed_enrollment_active"] == "true",
                code_module=row["seed_code_module"],
                code_presentation=row["seed_code_presentation"],
                registration_day=int(row["seed_registration_day"]) if row["seed_registration_day"] else None,
                num_of_prev_attempts=int(row["seed_num_of_prev_attempts"]) if row["seed_num_of_prev_attempts"] else None,
                studied_credits=int(row["seed_studied_credits"]) if row["seed_studied_credits"] else None,
            ))
    return list(records.values())


@pytest.mark.parametrize("filename,valid,invalid,forecasts", [
    ("coordinator_upload_valid.test.csv", 23, 0, 21),
    ("coordinator_upload_rejections.test.csv", 0, 14, 0),
])
def test_fixture_validation_matches_mapping_without_writes(filename, valid, invalid, forecasts):
    upload = MemoryUpload(filename=filename, file=io.BytesIO((FIXTURE_DIR / filename).read_bytes()))
    response = run_immediate(imports.validate_upload(
        file=upload, _user=SimpleNamespace(), db=ReadOnlyEnrollmentMock(mapped_enrollments())))
    assert response["total_rows"] == valid + invalid
    assert (response["valid_rows"], response["invalid_rows"], response["forecast_rows"]) == (valid, invalid, forecasts)
    assert response["valid"] is bool(valid and not invalid)
    assert "no records were written" in response["note"]
    with (FIXTURE_DIR / "synthetic_enrollment_mapping.test-only.csv").open(
            encoding="utf-8", newline="") as stream:
        cases = [row for row in csv.DictReader(stream) if row["fixture_file"] == filename]
    for case in cases:
        if case["expected_outcome"] == "reject":
            assert any(error["row"] == int(case["fixture_row"]) and
                       error["field"] == case["expected_field"] for error in response["errors"]), case["case_id"]


def test_unknown_fixture_numbers_are_invalid_without_mapping():
    upload = MemoryUpload(file=io.BytesIO((FIXTURE_DIR / "coordinator_upload_valid.test.csv").read_bytes()))
    response = run_immediate(imports.validate_upload(
        file=upload, _user=SimpleNamespace(), db=ReadOnlyEnrollmentMock([])))
    assert response["valid_rows"] == 0 and response["invalid_rows"] == 23
    assert len(response["unknown_rows"]) == 23


def test_invalid_fixture_import_stops_before_inference_or_writes():
    upload = MemoryUpload(file=io.BytesIO((FIXTURE_DIR / "coordinator_upload_rejections.test.csv").read_bytes()))
    with pytest.raises(HTTPException) as error:
        run_immediate(imports.import_upload(request=None, file=upload,
            user=SimpleNamespace(), db=ReadOnlyEnrollmentMock(mapped_enrollments())))
    assert error.value.status_code == 422
    assert error.value.detail["valid_rows"] == 0 and error.value.detail["invalid_rows"] == 14


class ImportWriteMock(ReadOnlyEnrollmentMock):
    """A recording mock; add/commit never persist anything."""
    def __init__(self):
        super().__init__(mapped_enrollments())
        self.added = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def scalar(self, _statement):
        return None

    def add(self, record):
        record.id = uuid4()
        self.added.append(record)

    def add_all(self, records):
        for record in records:
            self.add(record)

    def flush(self):
        pass

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


class InferenceMock:
    def __init__(self):
        self.sequence_calls = []

    def predict(self, features):
        return {"model": "mock", "model_version": "mock", "feature_version": "mock",
                "support_priority_score": 0.0, "threshold": 0.5,
                "priority_band": "no_flag_from_model", "observed_signals": features}

    def predict_sequence(self, sequence):
        self.sequence_calls.append(sequence)
        return self.predict({"weekly_sequence": sequence})

    def cluster_many(self, features):
        return [{"cluster_id": 0, "model_version": "mock", "feature_version": "mock",
                 "features": row} for row in features]


def test_mock_import_receipt_counts_only_valid_rows_and_preserves_missing_forecast():
    source = fixture_rows()
    invalid = dict(source[1], early_vle_clicks="invalid")
    upload = MemoryUpload(filename="demo.csv", file=io.BytesIO(csv_content([source[0], source[-1], invalid])))
    db = ImportWriteMock()
    model = InferenceMock()
    response = run_immediate(imports.import_upload(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_manager=model))),
        file=upload, user=SimpleNamespace(id=uuid4()), db=db))
    assert response["total_rows"] == 3
    assert response["valid_rows"] == len(response["records"]) == 2
    assert response["invalid_rows"] == 1
    assert response["already_imported"] is False
    assert response["records"][0]["forecast_id"] is not None
    assert response["records"][1]["forecast_id"] is None
    assert len(model.sequence_calls) == 1
    assert db.commit_calls == 1 and db.rollback_calls == 0
    snapshots = [record for record in db.added if isinstance(record, ImportedFeatureSnapshot)]
    assert snapshots[1].weekly_sequence is None
    assert all(record.support_priority_score == 0.0 for record in db.added if isinstance(record, Prediction))


def test_unexpected_api_error_does_not_log_exception_payload(caplog):
    # Compile only the existing handler function. Importing main would create the
    # application, which these independent checks intentionally never do.
    tree = ast.parse((ROOT / "backend/app/main.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "unexpected_error_handler")
    function.decorator_list = []
    namespace = {"Request": object, "JSONResponse": JSONResponse,
                 "logger": logging.getLogger("test.safe_api_errors")}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "api_error_handler", "exec"), namespace)
    sentinel = "credential-and-submitted-record-sentinel"
    with caplog.at_level(logging.ERROR):
        response = run_immediate(namespace["unexpected_error_handler"](
            SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/imports")), RuntimeError(sentinel)))
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "An unexpected server error occurred"}
    assert sentinel not in caplog.text
    assert "RuntimeError" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("imported_features,engagement,academic,expected_weeks,expected_count,expected_scores", [
    ({}, [], [], None, None, []),
    ({"early_vle_active_weeks": 0, "early_assessment_count": 0, "early_assessment_mean": 0},
     [], [], 0, 0, [0.0]),
    ({}, [SimpleNamespace(clicks=0)], [SimpleNamespace(score=0)], 0, 1, [0.0]),
])
def test_study_context_preserves_absent_observations_and_real_zeros(
        imported_features, engagement, academic, expected_weeks, expected_count, expected_scores):
    scalar_results = iter([SimpleNamespace(features=imported_features), None])
    list_results = iter([engagement, academic, [], []])
    db = SimpleNamespace(scalar=lambda _statement: next(scalar_results),
                         scalars=lambda _statement: next(list_results))
    context = study_plans._build_support_context(
        db, SimpleNamespace(id=uuid4()), SimpleNamespace(priority_band="no_flag_from_model"))
    assert context.active_weeks == expected_weeks
    assert context.assessment_count == expected_count
    assert context.recent_performance == expected_scores


def test_llm_fallback_never_logs_provider_exception_content(caplog):
    sentinel = "provider-credential-and-raw-content-sentinel"

    class FailingProvider:
        def generate(self, *_args):
            raise RuntimeError(sentinel)

    with caplog.at_level(logging.WARNING):
        result, used_llm = StudyPlanService(FailingProvider()).create(
            StudySupportContext(priority_band="no_flag_from_model"))
    assert result.actions and used_llm is False
    assert sentinel not in caplog.text
    assert "RuntimeError" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_assistant_failure_returns_safe_error_and_logs_only_exception_type(monkeypatch, caplog):
    sentinel = "assistant-credential-and-record-sentinel"
    student = SimpleNamespace(id=uuid4())
    enrollment = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(study_plans, "get_authorized_student", lambda *_args: student)
    monkeypatch.setattr(study_plans, "get_enrollment_for_student", lambda *_args: enrollment)
    monkeypatch.setattr(study_plans, "_build_support_context", lambda *_args: None)
    monkeypatch.setattr(study_plans, "_assistant_context", lambda *_args: {})

    def failed_answer(*_args):
        raise RuntimeError(sentinel)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        study_plan_service=SimpleNamespace(answer_question=failed_answer))))
    with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as error:
        study_plans.ask_support_assistant(
            SupportAssistantQuestion(enrollment_id=enrollment.id, question="What is recorded?"),
            request, SimpleNamespace(role="student", student=student),
            SimpleNamespace(scalar=lambda _statement: SimpleNamespace()))
    assert error.value.status_code == 503
    assert sentinel not in str(error.value.detail) and sentinel not in caplog.text
    assert "RuntimeError" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
