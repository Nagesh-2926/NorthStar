from uuid import UUID

from sqlalchemy import select

from backend.app.models import Student
from backend.tests.conftest import login, register


def test_new_student_needs_coordinator_approval_before_record_access(client, app):
    registration = client.post("/api/auth/register", json={
        "email": "verify.student@example.com",
        "password": "SecurePass1234",
        "role": "student",
    })
    assert registration.status_code == 201, registration.text
    student_headers = login(client, "verify.student@example.com")
    profile = client.get("/api/students/me", headers=student_headers)
    assert profile.status_code == 200
    profile = profile.json()
    assert profile["enrollment_number"].startswith("24030315")
    assert profile["access_approved"] is False
    assert client.get(
        f"/api/students/{profile['id']}/performance",
        headers=student_headers,
    ).status_code == 403

    wrong_number = client.post("/api/access-requests", headers=student_headers,
                               json={"enrollment_number": "2403031599999"})
    assert wrong_number.status_code == 422
    request_response = client.post(
        "/api/access-requests", headers=student_headers,
        json={"enrollment_number": profile["enrollment_number"]},
    )
    assert request_response.status_code == 201, request_response.text
    request = request_response.json()
    assert request["status"] == "pending"
    assert client.get("/api/access-requests/me", headers=student_headers).json()["request"]["id"] == request["id"]

    coordinator = register(client, "verify.coordinator@example.com",
                           "coordinator", "test-coordinator-invite")
    coordinator_headers = login(client, coordinator["email"])
    queue = client.get("/api/access-requests", headers=coordinator_headers)
    assert queue.status_code == 200, queue.text
    assert [row["id"] for row in queue.json()] == [request["id"]]
    approved = client.patch(
        f"/api/access-requests/{request['id']}",
        headers=coordinator_headers, json={"status": "approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert client.get(
        f"/api/students/{profile['id']}/performance",
        headers=student_headers,
    ).status_code == 200
    assert client.patch(
        f"/api/access-requests/{request['id']}",
        headers=coordinator_headers, json={"status": "rejected"},
    ).status_code == 409

    db = app.state.session_factory()
    try:
        student = db.get(Student, UUID(profile["id"]))
        assert student.access_approved is True
    finally:
        db.close()


def test_rejected_student_request_can_be_resubmitted(client):
    student = register(client, "rejected.student@example.com")
    student_headers = login(client, student["email"])
    profile = client.get("/api/students/me", headers=student_headers).json()
    db = client.app.state.session_factory()
    try:
        record = db.scalar(select(Student).where(Student.id == UUID(profile["id"])))
        record.access_approved = False
        db.commit()
    finally:
        db.close()
    pending = client.post(
        "/api/access-requests", headers=student_headers,
        json={"enrollment_number": profile["enrollment_number"]},
    ).json()
    coordinator = register(client, "reject.coordinator@example.com",
                           "coordinator", "test-coordinator-invite")
    coordinator_headers = login(client, coordinator["email"])
    rejected = client.patch(
        f"/api/access-requests/{pending['id']}",
        headers=coordinator_headers, json={"status": "rejected"},
    )
    assert rejected.status_code == 200, rejected.text
    resubmitted = client.post(
        "/api/access-requests", headers=student_headers,
        json={"enrollment_number": profile["enrollment_number"]},
    )
    assert resubmitted.status_code == 201
    assert resubmitted.json()["id"] == pending["id"]
    assert resubmitted.json()["status"] == "pending"
