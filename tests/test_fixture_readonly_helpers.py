"""Mock-only helper checks: no application startup, Docker process, or DB connection."""
from types import SimpleNamespace

import pytest

from scripts import check_fixture_target as check
from scripts import seed_synthetic_upload_fixture as seed
from scripts import verify_fixture_identity as verify


FIXTURE_URL = "postgresql+psycopg://fixture_tester:unit-only@127.0.0.1:5433/student_support_fixture"


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected external operation")


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    monkeypatch.setattr(seed.subprocess, "run", forbidden)
    monkeypatch.setattr(seed, "build_engine", forbidden)
    monkeypatch.setattr(seed, "_env_file_url", lambda: None)
    monkeypatch.setattr(verify, "create_engine", forbidden)
    monkeypatch.setattr(verify, "Session", forbidden)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv(seed.DATABASE_URL_ENV, raising=False)
    for name in seed.REDIRECTING_LIBPQ_ENV:
        monkeypatch.delenv(name, raising=False)


def preflight(monkeypatch, identifier=verify.EXPECTED_CLUSTER_IDENTIFIER):
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    monkeypatch.setattr(seed, "docker_container_for_port", lambda _port: seed.ALLOWED_CONTAINER)
    # verify_target's default callback was bound at definition time; explicitly wrap it.
    original = seed.verify_target
    def target(raw, confirmation, *, require_confirmation):
        return original(raw, confirmation, require_confirmation=require_confirmation,
                        container_lookup=lambda _port: seed.ALLOWED_CONTAINER)
    monkeypatch.setattr(seed, "verify_target", target)
    monkeypatch.setattr(seed, "docker_cluster_identifier", lambda: identifier)


def test_checker_requires_fixture_credentials_without_connection(capsys):
    assert check.main() == 1
    assert "FAIL" in capsys.readouterr().out


def test_checker_success_runs_only_preflight(monkeypatch, capsys):
    preflight(monkeypatch)
    assert check.main() == 0
    shown = capsys.readouterr().out
    assert "PASS" in shown and "unit-only" not in shown


def test_checker_unexpected_failure_never_echoes_exception(monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RuntimeError("PrivateMarker " + FIXTURE_URL)
    monkeypatch.setattr(seed, "verify_target", broken)
    assert check.main() == 1
    assert "PrivateMarker" not in capsys.readouterr().out


@pytest.mark.parametrize("identifier", [None, "", "123"])
def test_missing_or_unexpected_container_identity_stops_before_engine(monkeypatch, capsys, identifier):
    preflight(monkeypatch, identifier)
    assert verify.main() == 1
    assert "no connection made" in capsys.readouterr().out


@pytest.mark.parametrize("url", [
    FIXTURE_URL.replace(":5433/", ":5432/"),
    FIXTURE_URL.replace("student_support_fixture", "student_support"),
    FIXTURE_URL + "?", FIXTURE_URL + "#", " " + FIXTURE_URL,
])
def test_prohibited_or_malformed_target_stops_before_identity_and_engine(monkeypatch, url):
    monkeypatch.setenv(seed.DATABASE_URL_ENV, url)
    monkeypatch.setattr(seed, "docker_cluster_identifier", forbidden)
    assert verify.main() == 1


class FakeEngine:
    def __init__(self, events):
        self.events = events
    def dispose(self):
        self.events.append("dispose")


class FakeSession:
    def __init__(self, events, *, identifier=verify.EXPECTED_CLUSTER_IDENTIFIER,
                 database=seed.ALLOWED_DATABASE, revision=seed.EXPECTED_ALEMBIC_HEAD,
                 readonly="on"):
        self.events = events
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.values = {
            "select system_identifier from pg_catalog.pg_control_system()": identifier,
            "select pg_catalog.current_database()": database,
            "select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) else null end from public.alembic_version": revision,
            "SHOW transaction_read_only": readonly,
        }
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.events.append("close")
    def execute(self, statement):
        self.events.append(str(statement))
    def scalar(self, statement):
        sql = str(statement)
        self.events.append(sql)
        return self.values[sql]
    def rollback(self):
        self.events.append("rollback")
    def commit(self):
        pytest.fail("identity verification must not commit")
    def add(self, *args):
        pytest.fail("identity verification must not write")
    def delete(self, *args):
        pytest.fail("identity verification must not write")


def connection_fakes(monkeypatch, events, **values):
    preflight(monkeypatch)
    def engine(raw, **kwargs):
        assert raw == FIXTURE_URL
        assert kwargs["connect_args"] == {
            "options": "-c default_transaction_read_only=on", "connect_timeout": 5}
        assert kwargs["use_native_hstore"] is False
        events.append("engine")
        return FakeEngine(events)
    monkeypatch.setattr(verify, "create_engine", engine)
    monkeypatch.setattr(verify, "Session", lambda _engine: FakeSession(events, **values))


def test_identity_verification_uses_readonly_startup_queries_and_rollback(monkeypatch, capsys):
    events = []
    connection_fakes(monkeypatch, events)
    assert verify.main() == 0
    assert events == ["engine", "SET TRANSACTION READ ONLY",
        "select system_identifier from pg_catalog.pg_control_system()", "select pg_catalog.current_database()",
        "select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) else null end from public.alembic_version", "SHOW transaction_read_only",
        "rollback", "close", "dispose"]
    shown = capsys.readouterr().out
    assert "VERIFIED" in shown and "unit-only" not in shown


@pytest.mark.parametrize("values", [
    {"identifier": "123"}, {"database": "student_support"},
    {"database": "another_database"}, {"revision": "PrivateMarker"}, {"readonly": "off"},
])
def test_connected_mismatch_refuses_without_writes_or_sensitive_diagnostics(monkeypatch, capsys, values):
    events = []
    connection_fakes(monkeypatch, events, **values)
    assert verify.main() == 1
    assert "dispose" in events and "rollback" not in events
    shown = capsys.readouterr().out
    assert "PrivateMarker" not in shown and "unit-only" not in shown


def test_connection_failure_is_sanitized_and_engine_disposed(monkeypatch, capsys):
    events = []
    connection_fakes(monkeypatch, events)
    def failure(*args):
        raise RuntimeError("PrivateMarker " + FIXTURE_URL)
    monkeypatch.setattr(verify, "Session", failure)
    assert verify.main() == 1
    assert events == ["engine", "dispose"]
    assert "PrivateMarker" not in capsys.readouterr().out


def test_disposal_failure_is_sanitized_and_prevents_success(monkeypatch, capsys):
    events = []
    connection_fakes(monkeypatch, events)
    def failure(*args):
        raise RuntimeError("PrivateMarker " + FIXTURE_URL)
    monkeypatch.setattr(FakeEngine, "dispose", failure)
    assert verify.main() == 1
    shown = capsys.readouterr().out
    assert "PrivateMarker" not in shown and "VERIFIED" not in shown
