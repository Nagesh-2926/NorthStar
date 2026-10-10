r"""Run the reviewed independent suite without database or application access.

Usage: .\.venv\Scripts\python.exe -B scripts/run_safe_tests.py
This deliberately excludes the existing loopback socket and child-process tests.
It never reads or changes application/fixture credentials.
"""
from __future__ import annotations

import importlib.abc
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST_PATHS = [
    "backend/tests/test_seed_fixture_safety.py",
    "tests/test_fixture_readonly_helpers.py",
    "tests/test_fixture_backend_launcher.py",
    "tests/test_with_isolated_db.py",
    "tests/test_csv_import_unit.py",
    "tests/test_features.py",
    "tests/test_identity_registry.py",
    "tests/test_upload_fixture.py",
    "tests/test_inference.py",
    "tests/test_canonical_integrity.py",
    "tests/test_sqlite_runner_guards.py",
]
EXCLUDED = "not test_busy_port_blocks_the_command and not test_child_receives_rewritten_url_only"


def forbidden(*_args, **_kwargs):
    raise AssertionError("Safe suite forbids real engines, connections, application startup, and subprocesses")


class NoApplicationStartup(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "backend.app.main":
            raise AssertionError("Safe suite forbids importing the application entry point")
        return None


def protect_artifact_writes() -> None:
    """Permit temporary test files while rejecting writes to persistent artifacts."""
    protected = [path.resolve() for path in (
        ROOT / ".env", ROOT / "student_support.db", ROOT / "ml/saved_models", ROOT / "data/processed",
        ROOT / "data/test_fixtures/coordinator_upload")]

    def is_protected(value) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        candidate = Path(os.fsdecode(value)).resolve()
        return any(candidate == path or path in candidate.parents for path in protected)

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and is_protected(path):
                raise AssertionError("Safe suite forbids persistent artifact writes")
        elif event in {"os.remove", "os.rmdir", "os.mkdir"} and is_protected(args[0]):
            raise AssertionError("Safe suite forbids persistent artifact mutations")
        elif event == "os.rename" and any(is_protected(path) for path in args[:2]):
            raise AssertionError("Safe suite forbids persistent artifact moves")

    sys.addaudithook(audit)


def main() -> int:
    if sys.argv[1:] not in ([], ["--collect-only"]):
        print("Safe suite accepts only the optional --collect-only flag.")
        return 2
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    # Disable unrelated installed pytest plugins in this runner process only.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    sys.meta_path.insert(0, NoApplicationStartup())
    protect_artifact_writes()

    for name in ("create_connection", "getaddrinfo"):
        setattr(socket, name, forbidden)
    for name in ("connect", "connect_ex", "bind", "listen", "sendto"):
        setattr(socket.socket, name, forbidden)
    class ForbiddenPopen(subprocess.Popen):
        __init__ = forbidden

    subprocess.Popen = ForbiddenPopen
    for name in ("run", "call", "check_call", "check_output"):
        setattr(subprocess, name, forbidden)

    import sqlite3
    import sqlalchemy
    import psycopg
    import fastapi

    sqlite3.connect = forbidden
    sqlite3.dbapi2.connect = forbidden
    sqlalchemy.create_engine = forbidden
    sqlalchemy.engine.create_engine = forbidden
    sqlalchemy.engine.create.create_engine = forbidden
    sqlalchemy.engine.Engine.connect = forbidden
    sqlalchemy.engine.Engine.raw_connection = forbidden
    psycopg.connect = forbidden
    psycopg.Connection.connect = forbidden
    psycopg.AsyncConnection.connect = forbidden
    fastapi.FastAPI = forbidden

    import pytest

    class Inventory:
        selected = 0
        deselected = 0

        def pytest_collection_finish(self, session):
            self.selected = len(session.items)

        def pytest_deselected(self, items):
            self.deselected += len(items)

    inventory = Inventory()
    args = ["--noconftest", "-q", "-k", EXCLUDED, *TEST_PATHS]
    if sys.argv[1:]:
        args.append("--collect-only")
    result = int(pytest.main(args, plugins=[inventory]))
    print(f"safe_suite_selected={inventory.selected}; deselected={inventory.deselected}; exit_code={result}")
    print("Guards: application startup, real engines, SQLite/PostgreSQL connects, Python sockets, subprocesses, persistent artifact writes.")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
