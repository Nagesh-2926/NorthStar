r"""Run the approved backend suite against memory or freshly isolated SQLite only.

Usage: .\.venv\Scripts\python.exe -B scripts/run_sqlite_tests.py
No HTTP server, PostgreSQL connection, network socket, or ML training is allowed.
The temporary test directory is retained for review, never reused as basetemp.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = [
    "test_access_requests.py", "test_auth_and_access.py", "test_csv_imports.py",
    "test_email_notifications.py", "test_grade_score_training.py", "test_migrations.py",
    "test_ml_endpoints.py", "test_oulad_import.py", "test_records_llm_analytics.py",
    "test_seed_fixture_safety.py", "test_student_self_support.py", "test_synthetic_upload_fixture.py",
    "test_transfer_student_emails.py",
]


def deny_external(*_args, **_kwargs):
    raise AssertionError("SQLite suite forbids PostgreSQL, network sockets, subprocesses, and ML training")


def sqlite_authorizer(action, _first, second, _database, _source):
    """Reject additional database attachment and SQL extension loading before execution."""
    import sqlite3
    if (action == sqlite3.SQLITE_ATTACH or
            (action == sqlite3.SQLITE_FUNCTION and isinstance(second, str)
             and second.lower() == "load_extension")):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class MemorySelector(selectors.BaseSelector):
    """Poll thread callbacks without registering any operating-system I/O."""
    def register(self, *_args, **_kwargs):
        raise AssertionError("Test event loop does not permit file-descriptor I/O")

    def unregister(self, *_args, **_kwargs):
        raise AssertionError("Test event loop does not permit file-descriptor I/O")

    def select(self, timeout=None):
        if timeout is None or timeout > 0:
            time.sleep(min(timeout, 0.002) if timeout is not None else 0.002)
        return []

    def get_map(self):
        return {}

    def close(self):
        pass


class MemoryEventLoop(asyncio.SelectorEventLoop):
    """TestClient uses ASGI memory transport; thread wakeups need no socketpair."""
    def __init__(self):
        super().__init__(selector=MemorySelector())

    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass


class MemoryEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return MemoryEventLoop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--focus", help="Select reviewed test names with a pytest -k expression")
    options = parser.parse_args()
    existing = os.environ.get("DATABASE_URL")
    if existing is not None and existing not in {"sqlite://", "sqlite:///:memory:"}:
        print("STOP: pre-existing DATABASE_URL conflicts with isolated SQLite tests; left unchanged.")
        return 2

    temp_parent = Path(tempfile.gettempdir()).resolve()
    test_root = Path(tempfile.mkdtemp(prefix="northstar-sqlite-tests-")).resolve()
    if (test_root.parent != temp_parent or not test_root.name.startswith("northstar-sqlite-tests-")
            or any(test_root.iterdir())):
        print("STOP: fresh temporary directory could not be verified.")
        return 2
    basetemp = test_root / "pytest"
    assert not basetemp.exists() and basetemp.resolve().parent == test_root
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    # Dummy values exist only in this runner process and its in-memory test app.
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ["JWT_SECRET_KEY"] = "test-only-signing-key-64-bytes-minimum-not-production"
    os.environ["COORDINATOR_INVITE_CODE"] = "test-coordinator-invite"
    os.environ["LLM_PROVIDER"] = "disabled"
    os.environ["SMTP_HOST"] = ""
    os.environ["SMTP_FROM_EMAIL"] = ""
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    from scripts.run_safe_tests import protect_artifact_writes
    protect_artifact_writes()
    asyncio.set_event_loop_policy(MemoryEventLoopPolicy())

    for name in ("create_connection", "getaddrinfo", "socketpair"):
        setattr(socket, name, deny_external)
    for name in ("connect", "connect_ex", "bind", "listen", "sendto"):
        setattr(socket.socket, name, deny_external)
    class ForbiddenPopen(subprocess.Popen):
        __init__ = deny_external
    subprocess.Popen = ForbiddenPopen
    for name in ("run", "call", "check_call", "check_output"):
        setattr(subprocess, name, deny_external)

    import sqlite3
    import _sqlite3
    import sqlalchemy
    import psycopg
    import joblib
    from sqlalchemy.engine import make_url

    native_connect = sqlite3.connect
    native_create_engine = sqlalchemy.create_engine
    native_engine_connect = sqlalchemy.engine.Engine.connect
    native_raw_connection = sqlalchemy.engine.Engine.raw_connection
    targets = set()
    connection_count = 0
    write_attempts = 0

    def sqlite_target(database):
        if database == ":memory:":
            return ":memory:"
        if not isinstance(database, (str, os.PathLike)):
            raise AssertionError("SQLite database target is not an approved path")
        text = os.fspath(database)
        if text.startswith("file:"):
            raise AssertionError("SQLite URI targets are not approved")
        candidate = Path(text).resolve()
        if test_root not in candidate.parents:
            raise AssertionError("SQLite file target is outside the fresh temporary test directory")
        return str(candidate)

    def check_engine_target(url):
        try:
            parsed = make_url(url)
        except Exception:
            raise AssertionError("Engine URL could not be validated; details withheld") from None
        if (parsed.drivername not in {"sqlite", "sqlite+pysqlite"} or parsed.host is not None
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.query):
            raise AssertionError("Only guarded SQLite engine URLs are approved")
        sqlite_target(parsed.database or ":memory:")

    def trace(statement):
        nonlocal write_attempts
        if statement.lstrip().split(" ", 1)[0].upper() in {
                "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}:
            # Count statements without retaining SQL, submitted records, or hashes.
            write_attempts += 1

    def sqlite_connect(database, *args, **kwargs):
        nonlocal connection_count
        if kwargs.get("uri") or (len(args) >= 7 and args[6]):
            raise AssertionError("SQLite URI connection mode is not approved")
        target = sqlite_target(database)
        connection = native_connect(database, *args, **kwargs)
        connection.set_authorizer(sqlite_authorizer)
        connection.set_trace_callback(trace)
        targets.add(target)
        connection_count += 1
        return connection

    def create_engine(url, *args, **kwargs):
        check_engine_target(url)
        return native_create_engine(url, *args, **kwargs)

    def engine_connect(engine, *args, **kwargs):
        check_engine_target(engine.url)
        return native_engine_connect(engine, *args, **kwargs)

    def raw_connection(engine, *args, **kwargs):
        check_engine_target(engine.url)
        return native_raw_connection(engine, *args, **kwargs)

    def audit(event, args):
        if event == "sqlite3.connect":
            sqlite_target(args[0])
        elif event in {"socket.connect", "socket.bind", "socket.sendto"}:
            deny_external()
        elif event in {"sqlite3.load_extension", "sqlite3.enable_load_extension"}:
            deny_external()

    sys.addaudithook(audit)
    sqlite3.connect = sqlite_connect
    sqlite3.dbapi2.connect = sqlite_connect
    _sqlite3.connect = sqlite_connect
    sqlalchemy.create_engine = create_engine
    sqlalchemy.engine.create_engine = create_engine
    sqlalchemy.engine.create.create_engine = create_engine
    sqlalchemy.engine.Engine.connect = engine_connect
    sqlalchemy.engine.Engine.raw_connection = raw_connection
    psycopg.connect = deny_external
    psycopg.Connection.connect = deny_external
    psycopg.AsyncConnection.connect = deny_external
    joblib.dump = deny_external

    import pytest

    class Inventory:
        selected = 0
        def pytest_collection_finish(self, session):
            self.selected = len(session.items)

    inventory = Inventory()
    args = ["-q", "-p", "no:cacheprovider", "--basetemp", str(basetemp),
            *[str(ROOT / "backend/tests" / filename) for filename in TEST_FILES]]
    if options.collect_only:
        args.append("--collect-only")
    if options.focus:
        args.extend(["-k", options.focus])
    print(f"sqlite_test_root={test_root}")
    result = int(pytest.main(args, plugins=[inventory]))
    print(f"sqlite_suite_selected={inventory.selected}; exit_code={result}")
    print(f"sqlite_connections={connection_count}; sqlite_write_statement_attempts={write_attempts}")
    print(f"sqlite_targets={sorted(targets)}")
    print("Guards: fresh-temp/memory SQLite only; PostgreSQL, all sockets, subprocesses, persistent artifact writes blocked.")
    print("Temporary test files retained for review; runner process credentials expire with this process.")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
