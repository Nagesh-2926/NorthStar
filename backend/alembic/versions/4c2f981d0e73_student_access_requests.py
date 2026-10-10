"""add coordinator-reviewed student enrollment access requests

Revision ID: 4c2f981d0e73
Revises: 23ba7783d120
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa


revision = "4c2f981d0e73"
down_revision = "23ba7783d120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("access_approved", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    with op.batch_alter_table("students") as batch_op:
        batch_op.alter_column(
            "access_approved",
            existing_type=sa.Boolean(),
            server_default=sa.false(),
        )
    op.create_table(
        "student_access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_student_access_request_status",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", name="uq_student_access_request_student"),
    )
    op.create_index("ix_student_access_requests_student_id",
                    "student_access_requests", ["student_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_student_access_requests_student_id", table_name="student_access_requests")
    op.drop_table("student_access_requests")
    op.drop_column("students", "access_approved")
