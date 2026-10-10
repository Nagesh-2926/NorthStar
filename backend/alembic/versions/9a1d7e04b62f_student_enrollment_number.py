"""add stable application enrollment numbers to student identities

Revision ID: 9a1d7e04b62f
Revises: 6fc7d5c29b43
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa


revision = "9a1d7e04b62f"
down_revision = "6fc7d5c29b43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("enrollment_number", sa.String(length=32), nullable=True))
    op.create_index(
        "ix_students_enrollment_number",
        "students",
        ["enrollment_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_students_enrollment_number", table_name="students")
    op.drop_column("students", "enrollment_number")

