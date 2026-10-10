"""add per-user token version for password-change session revocation

Revision ID: 1d7c8f2a6b91
Revises: a58f9d632e10
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "1d7c8f2a6b91"
down_revision = "a58f9d632e10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
