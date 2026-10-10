"""Start a separate test backend that targets only the verified isolated fixture database.

Test-only. Run from an interactive local terminal after the fixture seed was approved:

    .\\.venv\\Scripts\\python.exe -B scripts\\fixture_backend.py

The fixture URL comes from a pre-existing NORTHSTAR_TEST_DATABASE_URL or a masked prompt,
never from arguments or the root .env. Before uvicorn starts, the seeder's target guard runs,
the container cluster identity is read without a connection, and a read-only transaction proves
the URL reaches student_support_fixture at the expected revision. Only the child receives the URL
as DATABASE_URL; the parent shell and .env are unchanged. The API listens on 127.0.0.1:8002 and
never on the application's 8001. Student enrollment-number allocation is redirected to a
fixture-only registry so the application's registry file is never written.
"""
from __future__ import annotations

import getpass
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_synthetic_upload_fixture as seed
from scripts import verify_fixture_identity as verify

FIXTURE_API_PORT = 8002
FIXTURE_FRONTEND_ORIGIN = "http://127.0.0.1:5174"
REVIEWED_SEEDER_SHA256 = "8cc0215adcff86380a629634e7df990c50e7c82146877bd6f5ddef1ea81b4f26"
FIXTURE_REGISTRY_PATH = (Path(tempfile.gettempdir()) / "northstar-fixture-backend"
                         / "application_enrollment_registry.json")


def seeder_is_reviewed(path: Path = Path(seed.__file__)) -> bool:
    return hashlib.sha256(path.read_bytes()).hexdigest() == REVIEWED_SEEDER_SHA256


def interactive_console() -> bool:
    """True only for a real terminal; Windows reports the NUL device as a tty."""
    if sys.stdin is None or not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError):
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def verified_fixture_url(raw: str | None) -> str:
    """Return the URL only after target, container, and connected-database identity agree."""
    target = seed.verify_target(raw, None, require_confirmation=False)
    identifier = seed.docker_cluster_identifier()
    if identifier != verify.EXPECTED_CLUSTER_IDENTIFIER:
        raise seed.UnsafeTargetError("Container identity is unavailable or unexpected; no connection made.")
    engine = create_engine(target, poolclass=NullPool, use_native_hstore=False,
        connect_args={"options": "-c default_transaction_read_only=on", "connect_timeout": 5})
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            seed.verify_connected_database(session, identifier)
            session.rollback()
    finally:
        engine.dispose()
    return target


def child_environment(database_url: str, environ=os.environ) -> dict[str, str]:
    blocked = {seed.DATABASE_URL_ENV, "DATABASE_URL", *seed.REDIRECTING_LIBPQ_ENV}
    env = {name: value for name, value in environ.items() if name.upper() not in blocked}
    env.update({
        "DATABASE_URL": database_url,
        "CORS_ORIGINS": FIXTURE_FRONTEND_ORIGIN,
        "APPLICATION_ENROLLMENT_REGISTRY_PATH": str(FIXTURE_REGISTRY_PATH),
    })
    return env


def main() -> int:
    try:
        if not seeder_is_reviewed():
            raise seed.UnsafeTargetError("The seeder differs from the reviewed source.")
        if not port_is_free(FIXTURE_API_PORT):
            raise seed.UnsafeTargetError(f"Port {FIXTURE_API_PORT} is already in use.")
        raw = os.environ.get(seed.DATABASE_URL_ENV)
        if not raw:
            if not interactive_console():
                raise seed.UnsafeTargetError("An interactive terminal is required for the masked prompt.")
            raw = getpass.getpass(f"Fixture URL for {seed.CONFIRMATION} (input hidden): ")
        database_url = verified_fixture_url(raw)
    except seed.UnsafeTargetError as exc:
        print(f"fixture backend: STOP -- {exc}")
        return 1
    except Exception:
        print("fixture backend: STOP -- verification unavailable; details withheld")
        return 1
    FIXTURE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"fixture backend: identity VERIFIED target={seed.CONFIRMATION} "
          f"revision={seed.EXPECTED_ALEMBIC_HEAD}")
    print(f"fixture backend: http://127.0.0.1:{FIXTURE_API_PORT} (CORS {FIXTURE_FRONTEND_ORIGIN}); Ctrl+C stops it")
    try:
        return subprocess.run(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app",
             "--host", "127.0.0.1", "--port", str(FIXTURE_API_PORT)],
            cwd=ROOT, env=child_environment(database_url), check=False).returncode
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("fixture backend: STOP -- backend launch failed; details withheld")
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("fixture backend: STOP -- command arguments are not accepted")
        raise SystemExit(1)
    raise SystemExit(main())
