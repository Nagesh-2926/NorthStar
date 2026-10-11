r"""Reset one existing user's password in the isolated application database only.

    .\.venv\Scripts\python.exe -B -m scripts.reset_app_user_password --email someone@example.com
    .\.venv\Scripts\python.exe -B -m scripts.reset_app_user_password --email someone@example.com `
        --apply --confirm-target student_support@127.0.0.1:5433

Without --apply it only verifies the target and reports whether the account exists (read-only
transaction). The target is always the root .env DATABASE_URL rewritten to port 5433, exactly
as scripts.with_isolated_db does; the legacy port 5432 is never contacted. Before any write the
open connection must prove it reached northstar-local-db-1 (pg_control system identifier),
database student_support, at the expected Alembic head, inside the same transaction as the
UPDATE. Accounts are never created; the new password is read only from a masked prompt,
and token_version is incremented so existing sessions are revoked. Credentials are never printed.
"""
from __future__ import annotations

import argparse
import os
import sys
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_synthetic_upload_fixture as seed
from scripts.verify_fixture_identity import EXPECTED_CLUSTER_IDENTIFIER
from scripts.with_isolated_db import ISOLATED_PORT, with_port

TARGET_DATABASE = seed.APPLICATION_DATABASE
CONFIRMATION = f"{TARGET_DATABASE}@127.0.0.1:{ISOLATED_PORT}"


class UnsafeTarget(RuntimeError):
    """Fixed, reviewed messages only; never URL parts or credentials."""


def target_url(environ=os.environ, env_file: Path = ROOT / ".env") -> str:
    """Return the root .env DATABASE_URL rewritten to the isolated port, or refuse."""
    redirecting = sorted(name for name in (*seed.REDIRECTING_LIBPQ_ENV, "DATABASE_URL") if environ.get(name))
    if redirecting:
        raise UnsafeTarget(f"Unset these environment overrides first: {', '.join(redirecting)}.")
    source = dotenv_values(env_file).get("DATABASE_URL")
    if not source:
        raise UnsafeTarget("DATABASE_URL is missing from the root .env.")
    try:
        url = with_port(source, ISOLATED_PORT)
    except ValueError:
        raise UnsafeTarget("DATABASE_URL could not be validated; details withheld.") from None
    if not url.endswith(f"@127.0.0.1:{ISOLATED_PORT}/{TARGET_DATABASE}"):
        raise UnsafeTarget(f"Rewritten target is not {CONFIRMATION}.")
    return url


def verify_container(container_lookup=seed.docker_container_for_port,
                     identifier_lookup=seed.docker_cluster_identifier) -> str:
    """Before connecting: port 5433 must be published by the isolated container, with the pinned identity."""
    if container_lookup(ISOLATED_PORT) != seed.ALLOWED_CONTAINER:
        raise UnsafeTarget(f"Port {ISOLATED_PORT} is not verifiably published by {seed.ALLOWED_CONTAINER}.")
    identifier = identifier_lookup(seed.ALLOWED_CONTAINER)
    if identifier != EXPECTED_CLUSTER_IDENTIFIER:
        raise UnsafeTarget(f"{seed.ALLOWED_CONTAINER} identity is unavailable or unexpected.")
    return identifier


def verify_connected(session: Session, identifier: str) -> None:
    """Prove the open transaction reached the isolated cluster's application database at the expected head."""
    if session.bind.dialect.name != "postgresql":
        raise UnsafeTarget("Connected database is not PostgreSQL.")
    if str(session.scalar(text("select system_identifier from pg_catalog.pg_control_system()"))) != identifier:
        raise UnsafeTarget(f"The connection did not reach the {seed.ALLOWED_CONTAINER} cluster.")
    if session.scalar(text("select pg_catalog.current_database()")) != TARGET_DATABASE:
        raise UnsafeTarget(f"Connected database is not {TARGET_DATABASE}.")
    version = session.scalar(text("select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) "
                                  "else null end from public.alembic_version"))
    if version != seed.EXPECTED_ALEMBIC_HEAD:
        raise UnsafeTarget(f"Database migration is not the expected head {seed.EXPECTED_ALEMBIC_HEAD}.")


def find_user(session: Session, email: str):
    return session.execute(text("select id, role, is_active from users where email = :email"),
                           {"email": email}).one_or_none()


def check_new_password(password: str, confirmation: str) -> None:
    """Same rules as the application's PasswordChangeRequest."""
    if password != confirmation:
        raise ValueError("Password entries did not match.")
    if not 12 <= len(password) <= 128:
        raise ValueError("Passwords must be between 12 and 128 characters.")
    if (not any(c.islower() for c in password) or not any(c.isupper() for c in password)
            or not any(c.isdigit() for c in password)):
        raise ValueError("Passwords must include uppercase, lowercase, and numeric characters.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--apply", action="store_true", help="Write the new password (default: verify only).")
    parser.add_argument("--confirm-target", default=None)
    args = parser.parse_args(argv)
    email = args.email.strip().lower()
    if args.apply and args.confirm_target != CONFIRMATION:
        parser.error(f"--apply requires --confirm-target {CONFIRMATION}")

    try:
        url = target_url()
        identifier = verify_container()
    except UnsafeTarget as exc:
        print(f"reset: STOP -- {exc} No connection made.")
        return 1

    engine = create_engine(url, poolclass=NullPool, connect_args={
        "connect_timeout": 5, **({} if args.apply else {"options": "-c default_transaction_read_only=on"})})
    try:
        with Session(engine) as session, session.begin():
            if not args.apply:
                session.execute(text("SET TRANSACTION READ ONLY"))
            verify_connected(session, identifier)
            row = find_user(session, email)
            print(f"reset: target VERIFIED -- {CONFIRMATION}, cluster {identifier}, head {seed.EXPECTED_ALEMBIC_HEAD}")
            if row is None:
                print("reset: STOP -- no account with that email exists here; nothing changed. "
                      "Create accounts through the application, not this script.")
                return 1
            print(f"reset: account found -- role={row.role} is_active={row.is_active}")
            if not args.apply:
                print("reset: verify-only run; nothing changed.")
                return 0
            from backend.app.core.security import hash_password
            password = getpass("New password: ")
            check_new_password(password, getpass("Confirm new password: "))
            new_hash = hash_password(password)
            del password
            # Re-verified inside this same transaction immediately before the write.
            verify_connected(session, identifier)
            updated = session.execute(text(
                "update users set password_hash = :hash, token_version = token_version + 1 "
                "where id = :id and email = :email"), {"hash": new_hash, "id": row.id, "email": email}).rowcount
            if updated != 1:
                raise UnsafeTarget("Expected exactly one row to change; rolled back.")
        print("reset: password updated and existing sessions revoked. The password was not stored or printed.")
        return 0
    except (UnsafeTarget, ValueError) as exc:
        print(f"reset: STOP -- {exc} Nothing changed.")
        return 1
    except Exception:
        print("reset: FAIL -- database operation failed; details withheld. Nothing changed.")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
