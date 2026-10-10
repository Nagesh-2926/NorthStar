import os
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

TEST_SECRET = "test-only-signing-key-64-bytes-minimum-not-production"
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", TEST_SECRET)
os.environ.setdefault("COORDINATOR_INVITE_CODE", "test-coordinator-invite")

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.main import create_app
from backend.app.models import Student


@pytest.fixture
def app(tmp_path):
    config = Settings(_env_file=None, database_url="sqlite://", jwt_secret_key=TEST_SECRET,
        coordinator_invite_code="test-coordinator-invite", llm_provider="disabled",
        application_enrollment_registry_path=tmp_path / "application_enrollment_registry.json")
    application = create_app(config)
    Base.metadata.create_all(application.state.engine)
    yield application
    Base.metadata.drop_all(application.state.engine)
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def register(client, email, role="student", invite_code=None):
    body = {"email": email, "password": "SecurePass1234", "role": role}
    if invite_code is not None:
        body["invite_code"] = invite_code
    response = client.post("/api/auth/register", json=body)
    assert response.status_code == 201, response.text
    user = response.json()
    if role == "student":
        db = client.app.state.session_factory()
        try:
            student = db.scalar(select(Student).where(Student.user_id == UUID(user["id"])))
            student.access_approved = True
            db.commit()
        finally:
            db.close()
    return user


def login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": "SecurePass1234"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_enrollment(client, headers, student_id, module="AAA", presentation="2013B"):
    response = client.post(f"/api/students/{student_id}/enrollments", headers=headers,
        json={"code_module": module, "code_presentation": presentation,
              "registration_day": -20, "num_of_prev_attempts": 0, "studied_credits": 60})
    assert response.status_code == 201, response.text
    return response.json()


def ingest_model_sources(client, headers, student_id, enrollment_id):
    schedule = client.put(f"/api/enrollments/{enrollment_id}/assessment-schedule",
        headers=headers, json={"assessments":[
            {"assessment_key":"a1", "scheduled_day":28, "weight":50},
            {"assessment_key":"a2", "scheduled_day":35, "weight":50},
            {"assessment_key":"late", "scheduled_day":70, "weight":20}]})
    assert schedule.status_code == 200, schedule.text
    for assessment_key, score, submitted_day in (("a1", 82, 20), ("a2", 62, 45), ("late", 99, 40)):
        response = client.post(f"/api/students/{student_id}/performance?enrollment_id={enrollment_id}",
            headers=headers, json={"record_type":"assessment_score", "score":score,
                "assessment_key":assessment_key, "submitted_day":submitted_day})
        assert response.status_code == 201, response.text
    for week, clicks, days, site_ids, types in (
        (0, 100, 3, [101, 102], ["resource", "forum"]),
        (1, 75, 4, [102, 103], ["forum", "quiz"]),
        (2, 0, 0, [], []),
        (3, 0, 0, [], []),
        (4, 0, 0, [], []),
        (5, 0, 0, [], []),
        (6, 0, 0, [], []),
        (7, 0, 0, [], []),
    ):
        response = client.post(f"/api/students/{student_id}/engagement?enrollment_id={enrollment_id}",
            headers=headers, json={"week_index":week, "clicks":clicks, "active_days":days,
                "active_site_ids":site_ids, "activity_types":types})
        assert response.status_code == 201, response.text
