"""Preview or atomically update transferred student placeholder emails."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import Settings
from backend.app.db.session import build_engine
from backend.app.models import Student, User

EMAIL_PREFIX = "24030315"
EMAIL_DOMAIN = "@paruluniversity.ac.in"
PLACEHOLDER_PATTERN = "transfer-disabled-%@example.invalid"
MAX_SEQUENCE = 100_000


class EmailMigrationError(RuntimeError):
    """Raised when a safe, complete email mapping cannot be produced."""


class EmailConflictError(EmailMigrationError):
    """Raised when a proposed email already belongs to another account."""


@dataclass(frozen=True)
class EmailAssignment:
    user: User
    student_id: UUID
    source_email: str
    enrollment_number: str | None
    target_email: str


def plan_email_updates(db: Session) -> list[EmailAssignment]:
    orphaned_count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == "student",
            func.lower(User.email).like(PLACEHOLDER_PATTERN),
            ~select(Student.id).where(Student.user_id == User.id).exists(),
        )
    ) or 0
    if orphaned_count:
        raise EmailMigrationError(
            f"Found {orphaned_count} placeholder student accounts without a Student profile."
        )

    rows = db.execute(
        select(User, Student.id, Student.enrollment_number)
        .join(Student, Student.user_id == User.id)
        .where(
            User.role == "student",
            func.lower(User.email).like(PLACEHOLDER_PATTERN),
        )
        .order_by(Student.enrollment_number.asc().nulls_last(), Student.id.asc())
    ).all()
    if len(rows) > MAX_SEQUENCE:
        raise EmailMigrationError(
            "The five-digit university email sequence cannot represent all eligible accounts."
        )

    assignments = [
        EmailAssignment(
            user=user,
            student_id=student_id,
            source_email=user.email,
            enrollment_number=enrollment_number,
            target_email=f"{EMAIL_PREFIX}{index:05d}{EMAIL_DOMAIN}",
        )
        for index, (user, student_id, enrollment_number) in enumerate(rows)
    ]
    target_emails = [item.target_email.lower() for item in assignments]
    if len(target_emails) != len(set(target_emails)):
        raise EmailMigrationError("The generated email mapping contains duplicate addresses.")

    if target_emails:
        conflicts = db.execute(
            select(User.id, User.email)
            .where(func.lower(User.email).in_(target_emails))
            .order_by(func.lower(User.email), User.id)
        ).all()
        if conflicts:
            details = ", ".join(
                f"{email} (user {user_id})" for user_id, email in conflicts
            )
            raise EmailConflictError(
                f"Generated university email address conflict(s): {details}"
            )

    return assignments


def apply_email_updates(db: Session, assignments: list[EmailAssignment]) -> int:
    for assignment in assignments:
        assignment.user.email = assignment.target_email
    db.flush()

    remaining_placeholders = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == "student",
            func.lower(User.email).like(PLACEHOLDER_PATTERN),
        )
    ) or 0
    expected_addresses = {item.target_email.lower() for item in assignments}
    stored_addresses = {
        email.lower()
        for email in db.scalars(
            select(User.email).where(func.lower(User.email).in_(expected_addresses))
        )
    } if expected_addresses else set()
    if remaining_placeholders or stored_addresses != expected_addresses:
        raise EmailMigrationError(
            "Post-update verification failed; the database transaction must be rolled back."
        )
    return len(assignments)


def _print_preview(assignments: list[EmailAssignment], apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")
    print(f"Student placeholder accounts: {len(assignments)}")
    print("Generated addresses do not verify mailbox ownership or activate accounts.")
    if not assignments:
        print("No remaining student placeholder accounts; no changes are needed.")
        return
    print(f"First mapping: {assignments[0].source_email} -> {assignments[0].target_email}")
    print(f"Last mapping: {assignments[-1].source_email} -> {assignments[-1].target_email}")
    print("Ordering: enrollment number ascending (missing numbers last), then Student UUID.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the conflict-checked mapping in one database transaction",
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("Transferred account updates require the configured PostgreSQL database.")

    engine = build_engine(settings.database_url)
    try:
        with Session(engine) as db, db.begin():
            assignments = plan_email_updates(db)
            _print_preview(assignments, args.apply)
            if args.apply:
                updated = apply_email_updates(db, assignments)
                print(f"Updated and verified student email addresses: {updated}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
