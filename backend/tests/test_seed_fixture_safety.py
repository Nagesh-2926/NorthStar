"""Seeder safety checks that run without Docker or any database.

Every subprocess and engine call is replaced by a fake; an unexpected call fails the test.
"""
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from ml.fixtures import coordinator_upload as fixture
from scripts import seed_synthetic_upload_fixture as seed

pytestmark = pytest.mark.skipif(not (fixture.FIXTURE_DIR / fixture.MAPPING_CSV).is_file(),
                                reason="Coordinator upload fixture has not been generated")

FIXTURE_URL = "postgresql+psycopg://tester:secret@127.0.0.1:5433/student_support_fixture"
IDENTIFIER = "7694699641731592226"
CONTROLDATA = (f"pg_control version number:            1300\n"
               f"Catalog version number:               202307071\n"
               f"Database system identifier:           {IDENTIFIER}\n"
               f"Database cluster state:               in production\n")


def isolated(_port):
    return seed.ALLOWED_CONTAINER


def _forbidden(*_args, **_kwargs):
    raise AssertionError("unexpected subprocess or engine call")


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(seed.subprocess, "run", _forbidden)
    monkeypatch.setattr(seed, "build_engine", _forbidden)
    monkeypatch.setattr(seed, "ROOT", tmp_path)  # no root .env
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in seed.REDIRECTING_LIBPQ_ENV:
        monkeypatch.delenv(name, raising=False)


def fake_docker(monkeypatch, events, controldata=CONTROLDATA, failure=None):
    def run(argv, **_kwargs):
        if argv[:2] == ["docker", "ps"]:
            events.append("docker ps")
            return subprocess.CompletedProcess(argv, 0, stdout=f"{seed.ALLOWED_CONTAINER}\n", stderr="")
        if "pg_controldata" in argv:
            events.append(argv)
            if failure is not None:
                raise failure
            return subprocess.CompletedProcess(argv, 0, stdout=controldata, stderr="")
        raise AssertionError(f"unexpected subprocess: {argv[:2]}")
    monkeypatch.setattr(seed.subprocess, "run", run)


def test_cluster_identifier_reads_the_control_file_without_any_database_client(monkeypatch):
    events = []
    fake_docker(monkeypatch, events)
    assert seed.docker_cluster_identifier() == IDENTIFIER
    (argv,) = events
    assert argv == ["docker", "exec", "-u", "postgres", "-e", "LC_ALL=C", seed.ALLOWED_CONTAINER, "pg_controldata"]
    assert not {"psql", "-d", "inspect", seed.APPLICATION_DATABASE, seed.ALLOWED_DATABASE} & set(argv)


@pytest.mark.parametrize("controldata, failure", [
    ("Catalog version number: 202307071\n", None),
    ("Database system identifier: not-a-number\n", None),
    ("Database system identifier: 0\n", None),
    ("Database system identifier: 18446744073709551616\n", None),
    ("Database system identifier: １２３\n", None),
    (CONTROLDATA + f"Database system identifier: {IDENTIFIER}\n", None),
    ("", None),
    (CONTROLDATA, subprocess.CalledProcessError(1, "docker")),
    (CONTROLDATA, subprocess.TimeoutExpired("docker", 30)),
    (CONTROLDATA, OSError("docker not found")),
])
def test_unreadable_cluster_identity_fails_closed(monkeypatch, controldata, failure):
    fake_docker(monkeypatch, [], controldata=controldata, failure=failure)
    assert seed.docker_cluster_identifier() is None


def test_main_refuses_before_building_an_engine_when_identity_is_unreadable(monkeypatch):
    events = []
    fake_docker(monkeypatch, events, failure=subprocess.CalledProcessError(1, "docker"))
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    with pytest.raises(SystemExit, match="cluster identity"):
        seed.main([])
    assert events[0] == "docker ps" and "pg_controldata" in events[1]  # build_engine would have raised


class FakeEngine:
    def dispose(self):
        pass


class FakeSession:
    """Records statements; any write method fails the test."""

    def __init__(self, log, execute_error=None):
        self.log = log
        self.execute_error = execute_error

    def __call__(self, _engine):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement):
        if self.execute_error is not None:
            raise self.execute_error
        self.log.append(("execute", str(statement)))

    def scalars(self, statement):
        self.log.append(("scalars", str(statement).split()[0]))
        return []

    def rollback(self):
        self.log.append(("rollback",))

    def add(self, *_args):
        raise AssertionError("dry run must not add")

    flush = delete = commit = add


def test_dry_run_reads_identity_first_then_only_reads_and_rolls_back(monkeypatch, capsys):
    events, log = [], []
    fake_docker(monkeypatch, events)
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    monkeypatch.setattr(seed, "build_engine", lambda _url: events.append("engine") or FakeEngine())
    monkeypatch.setattr(seed, "Session", FakeSession(log))
    monkeypatch.setattr(seed, "verify_connected_database",
                        lambda _session, expected: log.append(("verify", expected)))

    seed.main([])

    assert events[1][-1] == "pg_controldata" and events[2] == "engine"
    assert log[0] == ("execute", "SET TRANSACTION READ ONLY")
    assert log[1] == ("verify", IDENTIFIER)
    assert {entry[0] for entry in log[2:-1]} == {"scalars"}
    assert all(entry[1] == "SELECT" for entry in log[2:-1])
    assert log[-1] == ("rollback",)
    assert "dry-run (read-only, nothing written)" in capsys.readouterr().out


def test_driver_errors_are_reported_without_user_or_server_details(monkeypatch):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    monkeypatch.setattr(seed, "build_engine", lambda _url: FakeEngine())
    driver_error = OperationalError(
        "SET TRANSACTION READ ONLY", {},
        Exception('connection to server at "127.0.0.1", port 5433 failed: '
                  'password authentication failed for user "tester" (secret)'))
    monkeypatch.setattr(seed, "Session", FakeSession([], execute_error=driver_error))
    with pytest.raises(SystemExit) as error:
        seed.main([])
    message = str(error.value)
    assert message == "Refusing to run: database error (OperationalError)."
    assert error.value.__cause__ is None and error.value.__suppress_context__


CREDENTIAL_FRAGMENTS = ("tester", "secret", "Secr3t", "Fragment", "Zq9")


@pytest.mark.parametrize("url, message", [
    (FIXTURE_URL + "?", "query parameters"),
    (FIXTURE_URL + "?host", "query parameters"),
    (FIXTURE_URL + "?host=", "query parameters"),
    (FIXTURE_URL + "?port=5432", "query parameters"),
    ("postgresql+psycopg://tester:se?cret@127.0.0.1:5433/student_support_fixture", "query parameters"),
    (FIXTURE_URL + "#Zq9", "fragments"),
    ("postgresql+psycopg://tester:se#cret@127.0.0.1:5433/student_support_fixture", "fragments"),
    (" " + FIXTURE_URL, "whitespace or quotes"),
    (FIXTURE_URL + " ", "whitespace or quotes"),
    (FIXTURE_URL + "\n", "whitespace or quotes"),
    (FIXTURE_URL + "\t", "whitespace or quotes"),
    (f'"{FIXTURE_URL}"', "whitespace or quotes"),
    (f"'{FIXTURE_URL}'", "whitespace or quotes"),
    ("postgresql+psycopg://<fixture_user>:secret@127.0.0.1:5433/student_support_fixture", "placeholder angle brackets"),
    ("postgresql+psycopg://tester:<fixture_password>@127.0.0.1:5433/student_support_fixture", "placeholder angle brackets"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5432/student_support_fixture", "student-db-1"),
    ("postgresql+psycopg://tester:secret@127.0.0.1/student_support_fixture", "default 5432"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5433/student_support", "active application database"),
    ("postgresql+psycopg://tester:secret@localhost:5433/student_support", "active application database"),
    ("postgresql+psycopg://tester:secret@10.0.0.9:5433/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@localhost:5433/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5434/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5433/other", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:54x3/student_support_fixture", "could not be parsed"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:+5433/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:05433/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:0/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:65536/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:/student_support_fixture", "could not be parsed"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5433/student_support_fixture/", "unverified target"),
    ("postgresql+psycopg://tester:secret@127.0.0.1:5433/student_support_fixture%20", "unverified target"),
    ("postgresql+psycopg://127.0.0.1:5433/student_support_fixture", "Explicit fixture username"),
    ("postgresql+psycopg://tester@127.0.0.1:5433/student_support_fixture", "Explicit fixture username"),
    ("postgresql+psycopg://tester:@127.0.0.1:5433/student_support_fixture", "Explicit fixture username"),
    ("postgresql+psycopg://:secret@127.0.0.1:5433/student_support_fixture", "Explicit fixture username"),
    ("postgresql+psycopg2://tester:secret@127.0.0.1:5433/student_support_fixture", "Only the isolated PostgreSQL"),
    ("postgresql+unknown://tester:secret@127.0.0.1:5433/student_support_fixture", "Only the isolated PostgreSQL"),
    ("not a url at all", "whitespace or quotes"),
    ("tester:secret@127.0.0.1:5433/student_support_fixture", "could not be parsed"),
    ("postgresql+psycopg://tester:Secr3t@Fragment@127.0.0.1:5433/student_support_fixture", "unverified target"),
])
def test_bad_targets_are_refused_without_echoing_credentials(url, message):
    with pytest.raises(seed.UnsafeTargetError, match=message) as error:
        seed.verify_target(url, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={})
    assert not any(fragment in str(error.value) for fragment in CREDENTIAL_FRAGMENTS)
    assert error.value.__cause__ is None


def test_percent_encoded_credentials_are_accepted():
    url = "postgresql+psycopg://tester:p%40ss%3Fx%23y%20z@127.0.0.1:5433/student_support_fixture"
    assert seed.verify_target(url, None, require_confirmation=False,
                              container_lookup=isolated, environ={}) == url


@pytest.mark.parametrize("variable", seed.REDIRECTING_LIBPQ_ENV)
def test_each_libpq_override_still_refuses(variable):
    with pytest.raises(seed.UnsafeTargetError, match=variable):
        seed.verify_target(FIXTURE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={variable: "x"})


@pytest.mark.parametrize("line", [
    "DATABASE_URL=postgresql+psycopg://app:other@127.0.0.1:5433/student_support_fixture",
    "export DATABASE_URL='postgresql+psycopg://app:other@127.0.0.1:5432/student_support_fixture'",
    'database_url="postgresql+psycopg://app:other@localhost:5432/student_support_fixture"',
])
def test_root_env_and_its_runtime_port_rewrite_remain_protected(tmp_path, line):
    (tmp_path / ".env").write_text(line + "\n", encoding="utf-8")
    with pytest.raises(seed.UnsafeTargetError, match="root .env"):
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ={})


@pytest.mark.parametrize("source", ["environment", "root .env"])
def test_application_credentials_cannot_be_reused_for_the_fixture(tmp_path, source):
    app_url = "postgresql+psycopg://tester:secret@127.0.0.1:5432/student_support"
    environ = {}
    if source == "environment":
        environ["DATABASE_URL"] = app_url
    else:
        (tmp_path / ".env").write_text(f"DATABASE_URL={app_url}\n", encoding="utf-8")
    with pytest.raises(seed.UnsafeTargetError, match="credentials must differ") as error:
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ=environ)
    assert "tester" not in str(error.value) and "secret" not in str(error.value)


def test_percent_encoding_does_not_disguise_application_credential_reuse():
    app_url = "postgresql+psycopg://test%65r:secr%65t@127.0.0.1:5432/student_support"
    with pytest.raises(seed.UnsafeTargetError, match="credentials must differ"):
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ={"DATABASE_URL": app_url})


def test_application_configuration_is_read_once_for_each_target_check(monkeypatch):
    reads = []
    monkeypatch.setattr(seed, "_env_file_url", lambda: reads.append("read") or None)
    seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                       container_lookup=isolated, environ={})
    assert reads == ["read"]


def test_unreadable_application_configuration_is_sanitized(monkeypatch):
    def fail():
        raise OSError("tester secret credential URL")
    monkeypatch.setattr(seed, "_env_file_url", fail)
    with pytest.raises(seed.UnsafeTargetError, match="could not be read") as error:
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ={})
    assert "tester" not in str(error.value) and "secret" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


@pytest.mark.parametrize("app_url", [
    "postgresql+psycopg://app:other@127.0.0.1:5432/student_support?dbname=student_support_fixture",
    "postgresql+psycopg://app:other@127.0.0.1:5432/student_support?",
    "postgresql+psycopg://app:other@127.0.0.1:5432/student_support#secret",
    "postgresql+psycopg://app:other@127.0.0.1:malformed/student_support",
])
def test_unprovable_application_configuration_fails_closed(app_url):
    with pytest.raises(seed.UnsafeTargetError, match="application DATABASE_URL could not be parsed") as error:
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ={"DATABASE_URL": app_url})
    assert not any(part in str(error.value) for part in ("other", "malformed", "secret"))


def test_application_environment_fixture_target_is_protected():
    with pytest.raises(seed.UnsafeTargetError, match="matches the application database"):
        seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                           container_lookup=isolated, environ={"DATABASE_URL": FIXTURE_URL})


def test_distinct_fixture_credentials_are_allowed_under_the_real_application_layout(tmp_path):
    app_url = "postgresql+psycopg://app:other@127.0.0.1:5432/student_support"
    (tmp_path / ".env").write_text(f"DATABASE_URL={app_url}\n", encoding="utf-8")
    assert seed.verify_target(FIXTURE_URL, None, require_confirmation=False,
                              container_lookup=isolated, environ={"DATABASE_URL": app_url}) == FIXTURE_URL


class ConnectedSession:
    """Canned identity answers only; an unexpected SQL statement fails immediately."""

    def __init__(self, identifier=IDENTIFIER, database=seed.ALLOWED_DATABASE,
                 head=seed.EXPECTED_ALEMBIC_HEAD, dialect="postgresql"):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.answers = {
            "select system_identifier from pg_catalog.pg_control_system()": identifier,
            "select pg_catalog.current_database()": database,
            "select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) else null end from public.alembic_version": head,
        }
        self.log = []

    def scalar(self, statement):
        sql = str(statement)
        self.log.append(sql)
        return self.answers[sql]


@pytest.mark.parametrize("kwargs, expected, message, queries", [
    ({"dialect": "sqlite"}, IDENTIFIER, "not PostgreSQL", 0),
    ({}, None, "cluster identity", 0),
    ({"identifier": "other"}, IDENTIFIER, "did not reach", 1),
    ({"database": seed.APPLICATION_DATABASE}, IDENTIFIER, "active application database", 2),
    ({"database": "wrong-db"}, IDENTIFIER, "database name", 2),
    ({"head": "secret-credential-url"}, IDENTIFIER, "expected head", 3),
    ({"head": None}, IDENTIFIER, "expected head", 3),
])
def test_connected_identity_database_and_migration_fail_before_fixture_queries(kwargs, expected, message, queries):
    session = ConnectedSession(**kwargs)
    with pytest.raises(seed.UnsafeTargetError, match=message) as error:
        seed.verify_connected_database(session, expected)
    assert len(session.log) == queries
    assert "secret-credential-url" not in str(error.value)


def test_connected_identity_database_and_migration_must_all_match():
    session = ConnectedSession()
    seed.verify_connected_database(session, IDENTIFIER)
    assert session.log == [
        "select system_identifier from pg_catalog.pg_control_system()",
        "select pg_catalog.current_database()",
        "select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) else null end from public.alembic_version",
    ]


@pytest.mark.parametrize("remove", [False, True])
def test_default_modes_do_not_call_any_write_function(monkeypatch, remove):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    log = []
    monkeypatch.setattr(seed, "build_engine", lambda _url: FakeEngine())
    monkeypatch.setattr(seed, "Session", FakeSession(log))
    monkeypatch.setattr(seed, "verify_connected_database", lambda *_args: log.append(("verify",)))
    monkeypatch.setattr(seed, "seed_records", _forbidden)
    monkeypatch.setattr(seed, "remove_records", _forbidden)
    monkeypatch.setattr(seed, "removal_targets", lambda *_args: log.append(("removal_targets",)) or [])
    monkeypatch.setattr(seed, "dependent_records", lambda *_args: log.append(("dependent_records",)) or {})
    seed.main(["--remove"] if remove else [])
    assert log[0] == ("execute", "SET TRANSACTION READ ONLY")
    assert log[1] == ("verify",)
    assert log[-1] == ("rollback",)


@pytest.mark.parametrize("argv", [["--apply"], ["--apply", "--remove"],
                                 ["--apply", "--confirm-target", "yes"]])
def test_writes_without_exact_confirmation_refuse_before_engine_or_identity(monkeypatch, argv):
    events = []
    fake_docker(monkeypatch, events)
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    with pytest.raises(SystemExit, match="Writes require"):
        seed.main(argv)
    assert events == ["docker ps"]


@pytest.mark.parametrize("remove", [False, True])
def test_explicit_apply_verifies_connected_target_before_writes_and_commit(monkeypatch, remove):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    log = []
    session = FakeSession(log)
    session.commit = lambda: log.append(("commit",))
    monkeypatch.setattr(seed, "build_engine", lambda _url: FakeEngine())
    monkeypatch.setattr(seed, "Session", session)
    monkeypatch.setattr(seed, "verify_connected_database", lambda *_args: log.append(("verify",)))
    monkeypatch.setattr(seed, "seed_records", lambda *_args: log.append(("seed",)) or 27)
    monkeypatch.setattr(seed, "remove_records", lambda *_args: log.append(("remove",)) or 27)
    argv = ["--apply", "--confirm-target", seed.CONFIRMATION]
    seed.main(argv + (["--remove"] if remove else []))
    assert log == [("verify",), ("remove" if remove else "seed",), ("commit",)]


def test_failed_connected_verification_prevents_writes_and_commit(monkeypatch):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    monkeypatch.setattr(seed, "build_engine", lambda _url: FakeEngine())
    monkeypatch.setattr(seed, "Session", FakeSession([]))
    monkeypatch.setattr(seed, "seed_records", _forbidden)
    monkeypatch.setattr(seed, "remove_records", _forbidden)
    def refuse(*_args):
        raise seed.UnsafeTargetError("Connected target refused.")
    monkeypatch.setattr(seed, "verify_connected_database", refuse)
    with pytest.raises(SystemExit, match="Connected target refused"):
        seed.main(["--apply", "--confirm-target", seed.CONFIRMATION])


@pytest.mark.parametrize("failure", [
    OperationalError(None, None, Exception("tester secret credential URL")),
    ValueError("tester secret credential URL"),
    ImportError("tester secret credential URL"),
])
def test_engine_construction_errors_are_sanitized(monkeypatch, failure):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    def fail(_url):
        raise failure
    monkeypatch.setattr(seed, "build_engine", fail)
    with pytest.raises(SystemExit) as error:
        seed.main([])
    assert "tester" not in str(error.value) and "secret" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_mapping_read_errors_are_sanitized_and_prevent_engine_creation(monkeypatch):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    def fail(_path):
        raise OSError("tester secret credential URL")
    monkeypatch.setattr(seed, "load_seed_records", fail)
    with pytest.raises(SystemExit) as error:
        seed.main([])
    assert str(error.value) == "Refusing to run: fixture preparation error (OSError)."
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_engine_cleanup_errors_are_sanitized(monkeypatch):
    fake_docker(monkeypatch, [])
    monkeypatch.setenv(seed.DATABASE_URL_ENV, FIXTURE_URL)
    class FailingDisposeEngine:
        def dispose(self):
            raise RuntimeError("tester secret credential URL")
    monkeypatch.setattr(seed, "build_engine", lambda _url: FailingDisposeEngine())
    monkeypatch.setattr(seed, "Session", FakeSession([]))
    monkeypatch.setattr(seed, "verify_connected_database", lambda *_args: None)
    with pytest.raises(SystemExit) as error:
        seed.main([])
    assert str(error.value) == "Refusing to run: database cleanup failed."
    assert error.value.__cause__ is None and error.value.__suppress_context__


@pytest.mark.parametrize("argv", [
    ["--secret-argument", "PrivateMarker"],
    ["--apply=PrivateMarker"],
    ["--remove=PrivateMarker"],
    [FIXTURE_URL],
    ["--database-url"],
    ["--mapping"],
])
def test_argument_errors_never_echo_caller_values_or_credentials(capsys, argv):
    with pytest.raises(SystemExit) as error:
        seed.main(argv)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Refusing to run: invalid command arguments; details withheld.\n"
    assert "PrivateMarker" not in captured.err and "secret" not in captured.err


def test_missing_url_refers_to_secure_prompt_without_inviting_cli_credentials():
    with pytest.raises(seed.UnsafeTargetError) as error:
        seed.verify_target(None, None, require_confirmation=False,
                           container_lookup=isolated, environ={})
    assert "secure local prompt" in str(error.value)
    assert "--database-url" not in str(error.value)
