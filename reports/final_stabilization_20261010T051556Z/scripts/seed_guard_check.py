"""Exercise the synthetic-seed tool's target guard without connecting to any database.

Calls scripts.seed_synthetic_upload_fixture.verify_target directly. verify_target never opens a
database connection; its only external call is a read-only `docker ps --filter publish=<port>`.
Nothing is seeded and no SQL is executed. Credentials in the URLs below are dummies.
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.getcwd())
from scripts.seed_synthetic_upload_fixture import (UnsafeTargetError, _env_file_target,  # noqa: E402
                                                   docker_container_for_port, verify_target)

ISO = "postgresql+psycopg://dummy:dummy@127.0.0.1:5433/student_support"
cases = [
    ("no target given", None, None, True, {}),
    ("legacy port 5432", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/student_support", None, False, {}),
    ("default port (implicit 5432)", "postgresql+psycopg://dummy:dummy@127.0.0.1/student_support", None, False, {}),
    ("wrong database name on 5433", "postgresql+psycopg://dummy:dummy@127.0.0.1:5433/other", None, False, {}),
    ("query-parameter redirect", ISO + "?host=127.0.0.1&port=5432", None, False, {}),
    ("libpq PGPORT override", ISO, None, False, {"PGPORT": "5432"}),
    ("write without --confirm-target", ISO, None, True, {}),
]
failures = 0
env_host, env_port = _env_file_target()
print(f"root .env app target (host:port only): {env_host}:{env_port}")
print(f"container publishing 5433: {docker_container_for_port(5433)}")
for name, url, confirmation, require, environ in cases:
    try:
        verify_target(url, confirmation, require_confirmation=require, environ=environ)
        print(f"FAIL {name}: guard ACCEPTED")
        failures += 1
    except UnsafeTargetError as exc:
        print(f"PASS {name}: refused ({exc})")
# Dry-run acceptance (no writes requested) of the verified isolated target.
try:
    verify_target(ISO, None, require_confirmation=False, environ={})
    print("PASS isolated 5433 target accepted for a dry run (connection not attempted here)")
except UnsafeTargetError as exc:
    print(f"FAIL isolated target unexpectedly refused: {exc}")
    failures += 1
sys.exit(1 if failures else 0)
