"""persist coordinator CSV imports and aggregate source snapshots

Revision ID: 23ba7783d120
Revises: 9a1d7e04b62f
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa


revision = "23ba7783d120"
down_revision = "9a1d7e04b62f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_dataset_import_sha256"),
    )
    op.create_index("ix_dataset_imports_uploaded_by_user_id", "dataset_imports",
                    ["uploaded_by_user_id"], unique=False)
    op.create_table(
        "imported_feature_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_import_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("weekly_sequence", sa.JSON(), nullable=True),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("forecast_prediction_id", sa.Uuid(), nullable=True),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_import_id"], ["dataset_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["forecast_prediction_id"], ["predictions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cluster_id"], ["behavioral_clusters.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_import_id", "source_row", name="uq_import_snapshot_source_row"),
        sa.UniqueConstraint("prediction_id"),
        sa.UniqueConstraint("forecast_prediction_id"),
        sa.UniqueConstraint("cluster_id"),
    )
    op.create_index("ix_imported_feature_snapshots_dataset_import_id",
                    "imported_feature_snapshots", ["dataset_import_id"], unique=False)
    op.create_index("ix_imported_feature_snapshots_enrollment_id",
                    "imported_feature_snapshots", ["enrollment_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_imported_feature_snapshots_enrollment_id",
                  table_name="imported_feature_snapshots")
    op.drop_index("ix_imported_feature_snapshots_dataset_import_id",
                  table_name="imported_feature_snapshots")
    op.drop_table("imported_feature_snapshots")
    op.drop_index("ix_dataset_imports_uploaded_by_user_id", table_name="dataset_imports")
    op.drop_table("dataset_imports")
