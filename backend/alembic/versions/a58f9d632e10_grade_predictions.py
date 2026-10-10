"""store numeric final-exam score predictions separately from risk scores

Revision ID: a58f9d632e10
Revises: 4c2f981d0e73
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a58f9d632e10"
down_revision = "4c2f981d0e73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "grade_predictions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("enrollment_id", uuid_type,
                  sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", uuid_type,
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("target_name", sa.String(length=64), nullable=False),
        sa.Column("prediction_day", sa.Integer(), nullable=False, server_default="56"),
        sa.Column("predicted_score", sa.Float(), nullable=False),
        sa.Column("observed_signals", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("predicted_score >= 0 AND predicted_score <= 100",
                           name="ck_grade_prediction_score_range"),
    )
    op.create_index("ix_grade_prediction_enrollment_created", "grade_predictions",
                    ["enrollment_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_grade_prediction_enrollment_created", table_name="grade_predictions")
    op.drop_table("grade_predictions")
