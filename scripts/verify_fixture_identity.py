"""Minimal read-only fixture identity check; run only after connection approval.

Credentials come only from NORTHSTAR_TEST_DATABASE_URL, never command arguments.
No fixture records are loaded, seeded, imported, migrated, or removed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_synthetic_upload_fixture as seed

EXPECTED_CLUSTER_IDENTIFIER = "7694699641731592226"


def main() -> int:
    engine = None
    outcome = 1
    try:
        target = seed.verify_target(os.environ.get(seed.DATABASE_URL_ENV), None,
                                    require_confirmation=False)
        identifier = seed.docker_cluster_identifier()
        if identifier != EXPECTED_CLUSTER_IDENTIFIER:
            print("identity check: STOP -- container identity is unavailable or unexpected; no connection made")
            return 1
        # Supply the read-only default in the startup packet, before any SQL.
        engine = create_engine(target, poolclass=NullPool, use_native_hstore=False,
            connect_args={"options": "-c default_transaction_read_only=on", "connect_timeout": 5})
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            seed.verify_connected_database(session, identifier)
            if session.scalar(text("SHOW transaction_read_only")) != "on":
                raise seed.UnsafeTargetError("The verification transaction is not read-only.")
            session.rollback()
        outcome = 0
    except seed.UnsafeTargetError as exc:
        print(f"identity check: FAIL -- {exc}")
    except Exception:
        print("identity check: FAIL -- verification unavailable; details withheld")
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                print("identity check: FAIL -- connection cleanup failed; details withheld")
                outcome = 1
    if outcome:
        return outcome
    print(f"target={seed.CONFIRMATION}")
    print(f"cluster_identifier={EXPECTED_CLUSTER_IDENTIFIER} matches_container=true")
    print(f"alembic_revision={seed.EXPECTED_ALEMBIC_HEAD} transaction_read_only=on")
    print("identity check: VERIFIED; fixture writes were not attempted")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("identity check: STOP -- command arguments are not accepted")
        raise SystemExit(1)
    raise SystemExit(main())
