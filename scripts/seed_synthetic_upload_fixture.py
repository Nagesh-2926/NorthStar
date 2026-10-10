"""Seed (or remove) synthetic enrollments for the coordinator-upload test fixture.

Test-only. Records are created only in the dedicated `student_support_fixture`
database published on 127.0.0.1:5433 by the `northstar-local-db-1` container, and
only with the reserved synthetic numbers in the fixture mapping. The application's
own `student_support` database runs in the same container (the backend reaches it
through scripts/with_isolated_db.py, which rewrites the root .env port to 5433), so
the script always refuses `student_support` and any target equal to the application
database as configured in .env, as rewritten by that wrapper, or as set in
DATABASE_URL. It never reads the root .env as its target, refuses port 5432
(`student-db-1`) or any unverified target, never overwrites an existing
student/enrollment, and defaults to a dry run.

Synthetic accounts use the email marker `synthetic-upload-fixture-<number>@example.com`
and an unusable password hash, so they cannot sign in. They are test fixtures, not
real or institution-issued enrollments.

    # Supply the process-only fixture URL through the reviewed secure local prompt.
    # Never place credentials in command arguments or shell history.
    python -m scripts.seed_synthetic_upload_fixture                       # dry run
    python -m scripts.seed_synthetic_upload_fixture --apply \
        --confirm-target student_support_fixture@127.0.0.1:5433           # create
    python -m scripts.seed_synthetic_upload_fixture --remove --apply \
        --confirm-target student_support_fixture@127.0.0.1:5433           # remove
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.session import build_engine
from backend.app.models import (AcademicRecord, BehavioralCluster, EngagementRecord, Enrollment,
    GradePrediction, ImportedFeatureSnapshot, Intervention, MotivationalMessage, Prediction,
    ScheduledAssessment, Student, StudyPlan, User)
from ml.fixtures.coordinator_upload import (
    FIXTURE_DIR,
    MAPPING_CSV,
    SYNTHETIC_EMAIL_DOMAIN,
    SYNTHETIC_EMAIL_PREFIX,
    SYNTHETIC_FIRST,
    SYNTHETIC_LAST,
    is_reserved_synthetic,
)
from scripts.with_isolated_db import ISOLATED_PORT as APP_RUNTIME_PORT

DATABASE_URL_ENV = "NORTHSTAR_TEST_DATABASE_URL"
ALLOWED_HOSTS = {"127.0.0.1"}
ALLOWED_PORT = 5433
ALLOWED_DATABASE = "student_support_fixture"
# The live application database; it shares the container and port with the fixture database.
APPLICATION_DATABASE = "student_support"
ALLOWED_CONTAINER = "northstar-local-db-1"
PROTECTED_CONTAINER = "student-db-1"
PROTECTED_PORT = 5432
CONFIRMATION = f"{ALLOWED_DATABASE}@127.0.0.1:{ALLOWED_PORT}"
UNUSABLE_PASSWORD_HASH = "!synthetic-upload-fixture:no-login"
EXPECTED_ALEMBIC_HEAD = "1d7c8f2a6b91"
# libpq reads these when the conninfo does not set them; any of them could redirect
# or reinterpret the connection, so the seed refuses to run while they are set.
REDIRECTING_LIBPQ_ENV = ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE",
                         "PGSERVICEFILE", "PGSYSCONFDIR", "PGOPTIONS", "PGTARGETSESSIONATTRS")


class UnsafeTargetError(RuntimeError):
    """The requested database is not the verified isolated test database."""


class SeedConflictError(RuntimeError):
    """A synthetic number or marker email already exists; nothing is overwritten."""


class _SecretSafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse's default error includes unrecognized or invalid caller input.
        self.exit(2, "Refusing to run: invalid command arguments; details withheld.\n")


@dataclass(frozen=True)
class SeedRecord:
    enrollment_number: str
    code_module: str
    code_presentation: str
    registration_day: int | None
    num_of_prev_attempts: int | None
    studied_credits: int | None
    enrollment_active: bool

    @property
    def email(self) -> str:
        return f"{SYNTHETIC_EMAIL_PREFIX}{self.enrollment_number}{SYNTHETIC_EMAIL_DOMAIN}"


def _env_file_url() -> str | None:
    from dotenv import dotenv_values

    env_path = ROOT / ".env"
    if not env_path.is_file():
        return None
    # Parse like the app does (python-dotenv, case-insensitive keys, last value wins).
    values = {key.lower(): value for key, value in dotenv_values(env_path).items()}
    return values.get("database_url") or None


def _env_file_target() -> tuple[str | None, int | None]:
    """Host/port of the root .env DATABASE_URL, read without exposing credentials."""
    raw = _env_file_url()
    if not raw:
        return None, None
    try:
        url = make_url(raw)
    except Exception:
        # Fail closed: an unreadable app target cannot be proven different.
        return "unparseable", ALLOWED_PORT
    return url.host, url.port


def _same_host(host: str | None) -> str | None:
    # An application's localhost target must still protect the exact loopback fixture URL.
    return "127.0.0.1" if host in {"127.0.0.1", "localhost"} else host


def _application_urls(environ):
    """Read application URLs only for refusal checks, never as fixture credentials."""
    try:
        raw_urls = (_env_file_url(), environ.get("DATABASE_URL"))
    except Exception:
        raise UnsafeTargetError("The application DATABASE_URL could not be read; refusing to seed.") from None
    for raw in raw_urls:
        if not raw:
            continue
        try:
            # A query may override the application's parsed host, port, or database.
            if any(char.isspace() or char in "\"'?#<>" for char in raw):
                raise ValueError
            url = make_url(raw)
            if url.query:
                raise ValueError
        except Exception:
            raise UnsafeTargetError("The application DATABASE_URL could not be parsed; refusing to seed.") from None
        yield url


def application_targets(environ=os.environ) -> set[tuple[str | None, int, str | None]]:
    """(host, port, database) the application may be using, read without exposing credentials.

    Covers the root .env URL as written, the same URL after scripts/with_isolated_db.py swaps
    its port to APP_RUNTIME_PORT (how the backend is launched), and any DATABASE_URL in the
    environment (set by that wrapper in child processes). An unreadable URL fails closed.
    """
    return _application_targets(_application_urls(environ))


def _application_targets(urls) -> set[tuple[str | None, int, str | None]]:
    targets = set()
    for url in urls:
        if not url.drivername.startswith("postgresql"):
            continue
        host = _same_host(url.host)
        targets.add((host, url.port or PROTECTED_PORT, url.database))
        targets.add((host, APP_RUNTIME_PORT, url.database))
    return targets


def docker_container_for_port(port: int) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"publish={port}", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names[0] if len(names) == 1 else None


def docker_cluster_identifier(container: str = ALLOWED_CONTAINER) -> str | None:
    """Read the cluster system identifier from the container's pg_control file.

    pg_controldata reads $PGDATA/global/pg_control and opens no database connection, so this
    can never reach the application database (the container's POSTGRES_DB is student_support).
    Any failure returns None, which callers treat as a refusal.
    """
    try:
        result = subprocess.run(
            ["docker", "exec", "-u", "postgres", "-e", "LC_ALL=C", container, "pg_controldata"],
            capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    identifiers = []
    for line in result.stdout.splitlines():
        label, _, value = line.partition(":")
        if label.strip() == "Database system identifier":
            value = value.strip()
            if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > 2**64 - 1:
                return None
            identifiers.append(value)
    return identifiers[0] if len(identifiers) == 1 else None


def verify_target(database_url: str | None, confirmation: str | None, *,
                  require_confirmation: bool, container_lookup=docker_container_for_port,
                  environ=os.environ) -> str:
    """Return the URL only if it is the verified isolated test database."""
    if not database_url:
        raise UnsafeTargetError(f"Set {DATABASE_URL_ENV} through the reviewed secure local prompt; "
                                "the root .env is never used as a seed target.")
    # Checked on the raw string: the parser silently drops an empty or valueless query
    # ("?", "?host") and folds a fragment into the database name.
    if any(char.isspace() or char in "\"'<>" for char in database_url):
        raise UnsafeTargetError("The database URL must not contain whitespace or quotes, or placeholder angle brackets.")
    if "?" in database_url:
        raise UnsafeTargetError("Database URL query parameters are not allowed for the seed target "
                                "(percent-encode '?' in credentials).")
    if "#" in database_url:
        raise UnsafeTargetError("Database URL fragments are not allowed for the seed target "
                                "(percent-encode '#' in credentials).")
    try:
        url = make_url(database_url)
    except Exception:
        raise UnsafeTargetError("The database URL could not be parsed.") from None
    if url.drivername != "postgresql+psycopg":
        raise UnsafeTargetError("Only the isolated PostgreSQL test database is supported.")
    if url.query:
        # Query parameters are forwarded to libpq and can override host, port, or dbname.
        raise UnsafeTargetError("Database URL query parameters are not allowed for the seed target.")
    redirecting = sorted(name for name in REDIRECTING_LIBPQ_ENV if environ.get(name))
    if redirecting:
        raise UnsafeTargetError(f"Unset libpq environment overrides before seeding: {', '.join(redirecting)}.")
    if url.port == PROTECTED_PORT or url.port is None:
        raise UnsafeTargetError(f"Refusing port {url.port or 'default 5432'}: it is {PROTECTED_CONTAINER}, not the isolated test database.")
    if url.database == APPLICATION_DATABASE:
        raise UnsafeTargetError(f"Refusing the active application database {APPLICATION_DATABASE}; seed only {ALLOWED_DATABASE}.")
    if url.host not in ALLOWED_HOSTS or url.port != ALLOWED_PORT or url.database != ALLOWED_DATABASE:
        # Never echo URL parts: an unencoded '@' in a password would spill into host.
        raise UnsafeTargetError(f"Refusing unverified target; only {CONFIRMATION} is allowed.")
    # Parsing converts ports such as '+5433' and '05433' to 5433. Require the exact
    # authority that will be sent to psycopg, including an explicit canonical port.
    authority = database_url.partition("://")[2].partition("/")[0].rpartition("@")[2]
    if authority != f"127.0.0.1:{ALLOWED_PORT}":
        raise UnsafeTargetError(f"Refusing unverified target; only {CONFIRMATION} is allowed.")
    if not url.username or not url.password:
        raise UnsafeTargetError("Explicit fixture username and password are required; credential fallbacks are prohibited.")
    app_urls = list(_application_urls(environ))
    if (_same_host(url.host), url.port, url.database) in _application_targets(app_urls):
        raise UnsafeTargetError("Refusing a target that matches the application database "
                                "(root .env, its with_isolated_db port rewrite, or DATABASE_URL).")
    if any(app_url.drivername.startswith("postgresql") and
           (url.username, url.password) == (app_url.username, app_url.password)
           for app_url in app_urls):
        raise UnsafeTargetError("Fixture credentials must differ from application DATABASE_URL credentials.")
    container = container_lookup(url.port)
    if container == PROTECTED_CONTAINER or container != ALLOWED_CONTAINER:
        raise UnsafeTargetError(f"Port {ALLOWED_PORT} is not verifiably published by {ALLOWED_CONTAINER}.")
    if require_confirmation and confirmation != CONFIRMATION:
        raise UnsafeTargetError(f"Writes require --confirm-target {CONFIRMATION}.")
    return database_url


def verify_connected_database(session: Session, expected_cluster_identifier: str | None) -> None:
    """Prove the open connection reached the isolated container's own cluster."""
    if session.bind.dialect.name != "postgresql":
        raise UnsafeTargetError("Connected database is not PostgreSQL.")
    if not expected_cluster_identifier:
        raise UnsafeTargetError(f"Could not read the cluster identity of {ALLOWED_CONTAINER}.")
    connected = str(session.scalar(text("select system_identifier from pg_catalog.pg_control_system()")))
    if connected != expected_cluster_identifier:
        raise UnsafeTargetError(f"The connection did not reach the {ALLOWED_CONTAINER} cluster.")
    database = session.scalar(text("select pg_catalog.current_database()"))
    if database == APPLICATION_DATABASE:
        raise UnsafeTargetError("The connection reached the active application database; refusing.")
    if database != ALLOWED_DATABASE:
        raise UnsafeTargetError("Connected database name does not match the isolated test database.")
    version = session.scalar(text("select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num) else null end "
                                  "from public.alembic_version"))
    if version != EXPECTED_ALEMBIC_HEAD:
        raise UnsafeTargetError(f"Database migration is not the expected head {EXPECTED_ALEMBIC_HEAD}.")


def _optional_int(value: str) -> int | None:
    return int(value) if value.strip() else None


def load_seed_records(mapping_path: Path = FIXTURE_DIR / MAPPING_CSV) -> list[SeedRecord]:
    with mapping_path.open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["seed_enrollment"] == "true"]
    records = []
    for row in rows:
        number = row["synthetic_enrollment_number"]
        if not is_reserved_synthetic(number):
            raise SeedConflictError("Mapping contains a number outside the reserved synthetic block.")
        records.append(SeedRecord(
            enrollment_number=number,
            code_module=row["seed_code_module"],
            code_presentation=row["seed_code_presentation"],
            registration_day=_optional_int(row["seed_registration_day"]),
            num_of_prev_attempts=_optional_int(row["seed_num_of_prev_attempts"]),
            studied_credits=_optional_int(row["seed_studied_credits"]),
            enrollment_active=row["seed_enrollment_active"] == "true",
        ))
    numbers = [record.enrollment_number for record in records]
    if len(numbers) != len(set(numbers)):
        raise SeedConflictError("Mapping seeds the same synthetic number more than once")
    return records


def find_conflicts(session: Session, records: list[SeedRecord]) -> list[str]:
    """Existing reserved-block numbers (seeded or not) and marker emails block seeding."""
    emails = {record.email for record in records}
    existing_numbers = set(session.scalars(select(Student.enrollment_number).where(
        Student.enrollment_number.between(str(SYNTHETIC_FIRST), str(SYNTHETIC_LAST)),
        func.length(Student.enrollment_number) == 13)))
    existing_emails = set(session.scalars(select(User.email).where(func.lower(User.email).in_(emails))))
    return sorted(existing_numbers | existing_emails)


def seed_records(session: Session, records: list[SeedRecord]) -> int:
    """Insert synthetic users/students/enrollments; refuse if anything already exists."""
    conflicts = find_conflicts(session, records)
    if conflicts:
        raise SeedConflictError(f"{len(conflicts)} synthetic numbers or marker emails already exist; nothing was changed.")
    for record in records:
        user = User(email=record.email, password_hash=UNUSABLE_PASSWORD_HASH, role="student", is_active=True)
        student = Student(user=user, enrollment_number=record.enrollment_number, access_approved=False)
        session.add(Enrollment(
            student=student, code_module=record.code_module, code_presentation=record.code_presentation,
            registration_day=record.registration_day, num_of_prev_attempts=record.num_of_prev_attempts,
            studied_credits=record.studied_credits, is_active=record.enrollment_active))
    session.flush()
    return len(records)


def removal_targets(session: Session, records: list[SeedRecord]) -> list[User]:
    """Accounts carrying both the synthetic marker email and a mapped number."""
    numbers = {record.enrollment_number for record in records}
    targets = session.execute(
        select(User, Student).join(Student, Student.user_id == User.id)
        .where(Student.enrollment_number.in_(numbers), User.email.like(f"{SYNTHETIC_EMAIL_PREFIX}%{SYNTHETIC_EMAIL_DOMAIN}"))
    ).all()
    for user, student in targets:
        if user.email != f"{SYNTHETIC_EMAIL_PREFIX}{student.enrollment_number}{SYNTHETIC_EMAIL_DOMAIN}":
            raise SeedConflictError("A marker email does not match its enrollment number; nothing was removed.")
    return [user for user, _ in targets]


# Rows the seed never creates. If any reference a synthetic enrollment, removal would
# cascade-delete coordinator work (imports, predictions, plans), so it is refused.
DEPENDENT_MODELS = (Prediction, GradePrediction, BehavioralCluster, ImportedFeatureSnapshot,
                    Intervention, StudyPlan, MotivationalMessage, AcademicRecord,
                    EngagementRecord, ScheduledAssessment)


def dependent_records(session: Session, users: list[User]) -> dict[str, int]:
    if not users:
        return {}
    enrollment_ids = select(Enrollment.id).join(Student, Student.id == Enrollment.student_id).where(
        Student.user_id.in_([user.id for user in users]))
    counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model).where(
        model.enrollment_id.in_(enrollment_ids))) for model in DEPENDENT_MODELS}
    return {name: count for name, count in counts.items() if count}


def remove_records(session: Session, records: list[SeedRecord]) -> int:
    users = removal_targets(session, records)
    dependents = dependent_records(session, users)
    if dependents:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(dependents.items()))
        raise SeedConflictError(f"Synthetic enrollments are referenced by other records ({detail}); nothing was removed.")
    for user in users:
        session.delete(user)
    session.flush()
    return len(users)


def main(argv: list[str] | None = None) -> None:
    parser = _SecretSafeArgumentParser(description="Test-only synthetic enrollment seeding for the upload fixture.")
    parser.add_argument("--database-url", help=f"Prefer the secure local prompt for ${DATABASE_URL_ENV}; the root .env is never used.")
    parser.add_argument("--mapping", type=Path, default=FIXTURE_DIR / MAPPING_CSV)
    parser.add_argument("--apply", action="store_true", help="Write changes; without this flag the run is a dry run.")
    parser.add_argument("--remove", action="store_true", help="Remove previously seeded synthetic fixture records.")
    parser.add_argument("--confirm-target", help=f"Must equal {CONFIRMATION} when --apply is used.")
    args = parser.parse_args(argv)

    try:
        database_url = verify_target(args.database_url or os.environ.get(DATABASE_URL_ENV),
                                     args.confirm_target, require_confirmation=args.apply)
        records = load_seed_records(args.mapping)
        # Read before any engine exists so an unverifiable cluster never gets a connection.
        expected_cluster = docker_cluster_identifier()
        if not expected_cluster:
            raise UnsafeTargetError(f"Could not read the cluster identity of {ALLOWED_CONTAINER}.")
    except (UnsafeTargetError, SeedConflictError) as exc:
        raise SystemExit(f"Refusing to run: {exc}") from None
    except Exception as exc:
        raise SystemExit(f"Refusing to run: fixture preparation error ({type(exc).__name__}).") from None

    engine = None
    try:
        engine = build_engine(database_url)
        with Session(engine) as session:
            if not args.apply:
                # Dry run issues only SELECTs inside a read-only transaction.
                session.execute(text("SET TRANSACTION READ ONLY"))
            verify_connected_database(session, expected_cluster)
            action = "remove" if args.remove else "seed"
            if not args.apply:
                if args.remove:
                    users = removal_targets(session, records)
                    dependents = dependent_records(session, users)
                    if dependents:
                        detail = ", ".join(f"{name}={count}" for name, count in sorted(dependents.items()))
                        raise SeedConflictError(f"Synthetic enrollments are referenced by other records ({detail}); nothing would be removed.")
                    count = len(users)
                else:
                    conflicts = find_conflicts(session, records)
                    if conflicts:
                        raise SeedConflictError(f"{len(conflicts)} synthetic numbers or marker emails already exist; nothing would be changed.")
                    count = len(records)
                session.rollback()
            else:
                count = remove_records(session, records) if args.remove else seed_records(session, records)
                session.commit()
    except (UnsafeTargetError, SeedConflictError) as exc:
        raise SystemExit(f"Refusing to run: {exc}") from None
    except SQLAlchemyError as exc:
        # Driver messages can name the user and server; report only the error class.
        raise SystemExit(f"Refusing to run: database error ({type(exc).__name__}).") from None
    except Exception as exc:
        raise SystemExit(f"Refusing to run: fixture operation error ({type(exc).__name__}).") from None
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                # Disposal errors can carry driver details; retain a safe failure only.
                raise SystemExit("Refusing to run: database cleanup failed.") from None
    inactive = sum(not record.enrollment_active for record in records)
    print(f"target={CONFIRMATION} container={ALLOWED_CONTAINER} action={action} mode={'APPLIED' if args.apply else 'dry-run (read-only, nothing written)'}")
    print(f"synthetic_accounts={count} inactive_enrollments={inactive if action == 'seed' else 'n/a'}")
    print(f"numbers={records[0].enrollment_number}..{records[-1].enrollment_number}" if records else "numbers=none")


if __name__ == "__main__":
    main()
