from backend.app.core.config import Settings
from backend.app.services import email_notifications
from backend.tests.conftest import create_enrollment, login, register


def _settings(**overrides):
    return Settings(_env_file=None, database_url="sqlite://",
        jwt_secret_key="test-only-signing-key-64-bytes-minimum-not-production", **overrides)


def test_smtp_notification_uses_configured_provider_without_real_network(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def starttls(self):
            captured["starttls"] = True

        def login(self, username, password):
            captured["login"] = (username, password)

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(email_notifications.smtplib, "SMTP", FakeSMTP)
    service = email_notifications.EmailNotificationService(_settings(
        smtp_host="smtp.example.test", smtp_username="mailer", smtp_password="test-secret",
        smtp_from_email="northstar@example.test"))
    sent = service.send("student@example.test", "Study plan ready", "Sign in to view it.",
        event="study_plan_created")

    assert sent is True
    assert captured["connection"] == ("smtp.example.test", 587, 8.0)
    assert captured["starttls"] is True
    assert captured["login"] == ("mailer", "test-secret")
    assert captured["message"]["To"] == "student@example.test"


def test_smtp_disabled_and_failure_are_graceful(monkeypatch):
    def should_not_connect(*_args, **_kwargs):
        raise AssertionError("SMTP must stay disabled without host and sender")

    monkeypatch.setattr(email_notifications.smtplib, "SMTP", should_not_connect)
    disabled = email_notifications.EmailNotificationService(_settings())
    assert disabled.send("student@example.test", "Subject", "Body", event="test") is False

    class BrokenSMTP:
        def __init__(self, *_args, **_kwargs):
            raise OSError("mock SMTP unavailable")

    monkeypatch.setattr(email_notifications.smtplib, "SMTP", BrokenSMTP)
    enabled = email_notifications.EmailNotificationService(_settings(
        smtp_host="smtp.example.test", smtp_from_email="northstar@example.test"))
    assert enabled.send("student@example.test", "Subject", "Body", event="test") is False


def test_saved_intervention_dispatches_optional_student_notification(client):
    student_user = register(client, "notify.student@example.com")
    coordinator_user = register(client, "notify.coordinator@example.com", "coordinator",
        "test-coordinator-invite")
    student_headers = login(client, student_user["email"])
    coordinator_headers = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student_headers).json()
    enrollment = create_enrollment(client, coordinator_headers, profile["id"])

    calls = []
    client.app.state.email_notifications.send = lambda *args, **kwargs: calls.append((args, kwargs)) or False
    response = client.post("/api/interventions", headers=coordinator_headers, json={
        "enrollment_id": enrollment["id"], "title": "Check in", "notes": "Review upcoming work"})
    assert response.status_code == 201, response.text
    assert len(calls) == 1
    assert calls[0][0][0] == student_user["email"]
    assert calls[0][1]["event"] == "intervention_created"
