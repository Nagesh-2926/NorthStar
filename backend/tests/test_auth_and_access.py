from backend.tests.conftest import login, register, create_enrollment
from datetime import datetime, timedelta, timezone
from uuid import UUID
import jwt
from backend.tests.conftest import TEST_SECRET
from sqlalchemy import select
from backend.app.core.security import verify_password
from backend.app.models.entities import User


def test_register_login_jwt_and_role_protection(client):
    student = register(client, "student.one@example.com")
    assert "password_hash" not in student
    token = login(client, "student.one@example.com")
    me = client.get("/api/auth/me", headers=token)
    assert me.status_code == 200
    assert me.json()["id"] == student["id"]
    assert me.json()["role"] == "student"
    with client.app.state.session_factory() as db:
        stored_user = db.scalar(select(User).where(User.email == student["email"]))
        assert stored_user.password_hash != "SecurePass1234"
        assert verify_password("SecurePass1234", stored_user.password_hash)
    duplicate = client.post("/api/auth/register", json={"email": student["email"],
        "password": "SecurePass1234", "role": "student"})
    assert duplicate.status_code == 409
    assert client.get("/api/students").status_code == 401
    assert client.get("/api/students", headers={"Authorization": "Bearer invalid-token"}).status_code == 401
    assert client.get("/api/students", headers=token).status_code == 403
    wrong_password = client.post("/api/auth/login", json={"email": "student.one@example.com",
        "password": "wrong"})
    assert wrong_password.status_code == 401
    assert wrong_password.json()["detail"] == "Invalid email or password"
    assert client.get("/health").json() == {"status": "ok"}


def test_password_change_verifies_current_password_and_revokes_existing_tokens(client):
    account = register(client, "password.change@example.com")
    old_token = login(client, account["email"])
    response = client.post("/api/auth/change-password", headers=old_token, json={
        "current_password": "SecurePass1234",
        "new_password": "AnotherSecure5678",
        "confirm_password": "AnotherSecure5678",
    })
    assert response.status_code == 200
    assert response.json()["message"] == "Password updated. Sign in again with your new password."
    assert client.get("/api/auth/me", headers=old_token).status_code == 401

    assert client.post("/api/auth/login", json={"email": account["email"],
        "password": "SecurePass1234"}).status_code == 401
    replacement = client.post("/api/auth/login", json={"email": account["email"],
        "password": "AnotherSecure5678"})
    assert replacement.status_code == 200
    new_token = {"Authorization": f"Bearer {replacement.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_token).status_code == 200
    with client.app.state.session_factory() as db:
        stored_user = db.scalar(select(User).where(User.id == UUID(account["id"])))
        assert stored_user.token_version == 1
        assert stored_user.password_hash != "AnotherSecure5678"
        assert verify_password("AnotherSecure5678", stored_user.password_hash)


def test_password_change_rejects_wrong_current_password_and_invalid_confirmation(client):
    account = register(client, "password.reject@example.com")
    token = login(client, account["email"])
    wrong_current = client.post("/api/auth/change-password", headers=token, json={
        "current_password": "IncorrectPass123",
        "new_password": "AnotherSecure5678",
        "confirm_password": "AnotherSecure5678",
    })
    assert wrong_current.status_code == 400
    assert wrong_current.json()["detail"] == "Current password is incorrect"
    mismatch = client.post("/api/auth/change-password", headers=token, json={
        "current_password": "SecurePass1234",
        "new_password": "AnotherSecure5678",
        "confirm_password": "DifferentSecure9876",
    })
    assert mismatch.status_code == 422
    weak = client.post("/api/auth/change-password", headers=token, json={
        "current_password": "SecurePass1234",
        "new_password": "weakpasswordonly",
        "confirm_password": "weakpasswordonly",
    })
    assert weak.status_code == 422
    assert client.get("/api/auth/me", headers=token).status_code == 200
    with client.app.state.session_factory() as db:
        stored_user = db.scalar(select(User).where(User.id == UUID(account["id"])))
        assert stored_user.token_version == 0
        assert verify_password("SecurePass1234", stored_user.password_hash)


def test_password_change_requires_authentication(client):
    response = client.post("/api/auth/change-password", json={
        "current_password": "SecurePass1234",
        "new_password": "AnotherSecure5678",
        "confirm_password": "AnotherSecure5678",
    })
    assert response.status_code == 401


def test_coordinator_can_change_only_the_authenticated_accounts_password(client):
    account = register(client, "password.coordinator@example.com", "coordinator",
                       "test-coordinator-invite")
    token = login(client, account["email"])
    response = client.post("/api/auth/change-password", headers=token, json={
        "current_password": "SecurePass1234",
        "new_password": "CoordinatorSecure5678",
        "confirm_password": "CoordinatorSecure5678",
        "target_user_id": "00000000-0000-0000-0000-000000000001",
    })
    assert response.status_code == 422
    changed = client.post("/api/auth/change-password", headers=token, json={
        "current_password": "SecurePass1234",
        "new_password": "CoordinatorSecure5678",
        "confirm_password": "CoordinatorSecure5678",
    })
    assert changed.status_code == 200
    assert client.post("/api/auth/login", json={"email": account["email"],
        "password": "CoordinatorSecure5678"}).status_code == 200


def test_password_change_route_is_registered_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/api/auth/change-password"]["post"]["security"] == [{"HTTPBearer": []}]


def test_coordinator_signup_is_invite_only(client):
    denied = client.post("/api/auth/register", json={"email":"coord.no@example.com",
        "password":"SecurePass1234","role":"coordinator"})
    assert denied.status_code == 403
    wrong_invite = client.post("/api/auth/register", json={"email":"coord.wrong@example.com",
        "password":"SecurePass1234","role":"coordinator","invite_code":"wrong-invite"})
    assert wrong_invite.status_code == 403
    assert wrong_invite.json()["detail"] == "Coordinator registration is invite-only"
    coordinator = register(client, "coord.yes@example.com", "coordinator", "test-coordinator-invite")
    assert coordinator["role"] == "coordinator"


def test_student_cannot_read_or_mutate_another_students_resources(client):
    first = register(client, "student.a@example.com")
    second = register(client, "student.b@example.com")
    coord = register(client, "coord.access@example.com", "coordinator", "test-coordinator-invite")
    student_a = login(client, first["email"])
    student_b = login(client, second["email"])
    coord_token = login(client, coord["email"])
    profile_a = client.get("/api/students/me", headers=student_a).json()
    profile_b = client.get("/api/students/me", headers=student_b).json()
    assert client.get(f"/api/students/{profile_b['id']}", headers=student_a).status_code == 404
    enrollment = create_enrollment(client, coord_token, profile_a["id"])
    response = client.get(f"/api/students/{profile_a['id']}/engagement?enrollment_id={enrollment['id']}",
                          headers=student_b)
    assert response.status_code == 404
    forbidden = client.post(f"/api/students/{profile_b['id']}/enrollments", headers=student_a,
                            json={"code_module":"BBB","code_presentation":"2014J"})
    assert forbidden.status_code == 403


def test_student_profile_endpoint_is_not_found_for_coordinators(client):
    # Like other reads (get_authorized_student), /students/me answers 404 rather than 403 to
    # non-students, so it does not disclose whether a student profile exists.
    coord = register(client, "coord.me@example.com", "coordinator", "test-coordinator-invite")
    response = client.get("/api/students/me", headers=login(client, coord["email"]))
    assert response.status_code == 404
    assert response.json()["detail"] == "Student profile not found"
    assert client.get("/api/students/me").status_code == 401


def test_expired_and_wrong_type_tokens_are_rejected(client):
    student = register(client, "expired.student@example.com")
    now = datetime.now(timezone.utc)
    for claims in (
        {"sub": student["id"], "role": "student", "iat": now - timedelta(minutes=2),
         "exp": now - timedelta(minutes=1), "type": "access"},
        {"sub": student["id"], "role": "student", "iat": now,
         "exp": now + timedelta(minutes=5), "type": "refresh"},
    ):
        token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


def test_cors_allows_local_origin_without_cookie_credentials(client):
    response = client.options("/api/auth/login", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_accepts_browser_private_network_preflight_from_allowed_origin(client):
    # Chrome adds Access-Control-Request-Private-Network to local preflights; rejecting it
    # surfaced in the UI as "The API ... could not be reached".
    response = client.options("/api/auth/login", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
        "Access-Control-Request-Private-Network": "true",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_cors_private_network_preflight_from_unlisted_origin_is_rejected(client):
    response = client.options("/api/auth/login", headers={
        "Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
        "Access-Control-Request-Private-Network": "true",
    })
    # Starlette may still echo allow-private-network, but without an allowed origin and with
    # a 400 status the browser refuses the preflight, so unlisted origins stay blocked.
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers

