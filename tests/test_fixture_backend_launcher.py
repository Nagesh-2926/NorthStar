"""Mock-only fixture backend launcher checks: no Docker, database, socket, or uvicorn process."""
import pytest

from scripts import fixture_backend as launcher
from scripts import seed_synthetic_upload_fixture as seed
from scripts import verify_fixture_identity as verify


PASSWORD = "unit-only-secret"
FIXTURE_URL = f"postgresql+psycopg://fixture_tester:{PASSWORD}@127.0.0.1:5433/student_support_fixture"


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected external operation")


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    monkeypatch.setattr(seed.subprocess, "run", forbidden)
    monkeypatch.setattr(launcher.subprocess, "run", forbidden)
    monkeypatch.setattr(launcher, "create_engine", forbidden)
    monkeypatch.setattr(launcher, "port_is_free", lambda _port: True)
    monkeypatch.setattr(launcher.getpass, "getpass", forbidden)
    monkeypatch.setattr(seed, "_env_file_url", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv(seed.DATABASE_URL_ENV, raising=False)
    for name in seed.REDIRECTING_LIBPQ_ENV:
        monkeypatch.delenv(name, raising=False)


def trusted_container(monkeypatch, identifier=verify.EXPECTED_CLUSTER_IDENTIFIER):
    original = seed.verify_target
    def target(raw, confirmation, *, require_confirmation):
        return original(raw, confirmation, require_confirmation=require_confirmation,
                        container_lookup=lambda _port: seed.ALLOWED_CONTAINER)
    monkeypatch.setattr(seed, "verify_target", target)
    monkeypatch.setattr(seed, "docker_cluster_identifier", lambda: identifier)


class FakeEngine:
    disposed = False

    def dispose(self):
        FakeEngine.disposed = True


class FakeSession:
    statements = []

    def __init__(self, _engine):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement):
        FakeSession.statements.append(str(statement))

    def rollback(self):
        FakeSession.statements.append("ROLLBACK")


def test_reviewed_seeder_hash_matches_the_pinned_value():
    assert launcher.seeder_is_reviewed()


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://fixture_tester:x@127.0.0.1:5433/student_support",
    "postgresql+psycopg://fixture_tester:x@127.0.0.1:5432/student_support_fixture",
    "postgresql+psycopg://fixture_tester:x@127.0.0.1:8001/student_support_fixture",
])
def test_application_or_unverified_targets_are_refused_before_any_connection(monkeypatch, url):
    trusted_container(monkeypatch)
    with pytest.raises(seed.UnsafeTargetError):
        launcher.verified_fixture_url(url)


def test_unexpected_cluster_identity_stops_before_engine_creation(monkeypatch):
    trusted_container(monkeypatch, identifier="1234567890")
    with pytest.raises(seed.UnsafeTargetError, match="no connection made"):
        launcher.verified_fixture_url(FIXTURE_URL)


def test_connected_identity_is_checked_read_only_before_the_url_is_returned(monkeypatch):
    trusted_container(monkeypatch)
    checked = []
    engine_kwargs = {}
    def fake_engine(url, **kwargs):
        engine_kwargs.update(kwargs)
        return FakeEngine()
    monkeypatch.setattr(launcher, "create_engine", fake_engine)
    monkeypatch.setattr(launcher, "Session", FakeSession)
    monkeypatch.setattr(seed, "verify_connected_database", lambda _s, ident: checked.append(ident))
    FakeSession.statements = []
    assert launcher.verified_fixture_url(FIXTURE_URL) == FIXTURE_URL
    assert engine_kwargs["connect_args"]["options"] == "-c default_transaction_read_only=on"
    assert FakeSession.statements == ["SET TRANSACTION READ ONLY", "ROLLBACK"]
    assert checked == [verify.EXPECTED_CLUSTER_IDENTIFIER]
    assert FakeEngine.disposed


def test_failed_connected_identity_is_refused(monkeypatch):
    trusted_container(monkeypatch)
    monkeypatch.setattr(launcher, "create_engine", lambda *_a, **_k: FakeEngine())
    monkeypatch.setattr(launcher, "Session", FakeSession)
    def wrong_database(_session, _identifier):
        raise seed.UnsafeTargetError("The connection reached the active application database; refusing.")
    monkeypatch.setattr(seed, "verify_connected_database", wrong_database)
    with pytest.raises(seed.UnsafeTargetError):
        launcher.verified_fixture_url(FIXTURE_URL)


def test_child_environment_carries_only_the_fixture_target():
    parent = {"NORTHSTAR_TEST_DATABASE_URL": FIXTURE_URL, "DATABASE_URL": "app-url",
              "PGHOST": "elsewhere", "PATH": "kept"}
    env = launcher.child_environment(FIXTURE_URL, parent)
    assert env["DATABASE_URL"] == FIXTURE_URL
    assert "NORTHSTAR_TEST_DATABASE_URL" not in env and "PGHOST" not in env
    assert env["PATH"] == "kept"
    assert env["CORS_ORIGINS"] == launcher.FIXTURE_FRONTEND_ORIGIN
    registry = launcher.FIXTURE_REGISTRY_PATH
    assert registry != launcher.ROOT / "data" / "processed" / "application_enrollment_registry.json"
    assert launcher.ROOT not in registry.parents
    assert parent["DATABASE_URL"] == "app-url"


def test_busy_fixture_port_stops_before_prompt_or_connection(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "port_is_free", lambda _port: False)
    assert launcher.main() == 1
    assert "8002 is already in use" in capsys.readouterr().out


def test_non_interactive_session_without_variable_refuses(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "interactive_console", lambda: False)
    assert launcher.main() == 1
    assert "interactive terminal is required" in capsys.readouterr().out


def test_null_device_stdin_is_not_an_interactive_console(monkeypatch):
    # Windows reports NUL as a tty; the hidden prompt would then block instead of refusing.
    with open(launcher.os.devnull, encoding="utf-8") as null_input:
        monkeypatch.setattr(launcher.sys, "stdin", null_input)
        assert launcher.interactive_console() is False


def test_refusal_output_never_contains_the_password(monkeypatch, capsys):
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL.replace("5433", "5432"))
    trusted_container(monkeypatch)
    assert launcher.main() == 1
    assert PASSWORD not in capsys.readouterr().out


def test_verified_launch_uses_port_8002_and_the_fixture_url_only(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    monkeypatch.setattr(launcher, "verified_fixture_url", lambda raw: raw)
    monkeypatch.setattr(launcher, "FIXTURE_REGISTRY_PATH", tmp_path / "registry" / "r.json")
    launched = {}
    def fake_run(command, *, cwd, env, check):
        launched.update(command=command, env=env)
        return type("Done", (), {"returncode": 0})()
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    assert launcher.main() == 0
    assert launched["command"][-1] == "8002" and "8001" not in launched["command"]
    assert launched["env"]["DATABASE_URL"] == FIXTURE_URL
    assert seed.DATABASE_URL_ENV not in launched["env"]
    assert PASSWORD not in capsys.readouterr().out
