from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrations_create_and_revert_the_current_schema(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("JWT_SECRET_KEY", "migration-test-secret-only-0123456789-abcdefghijkl")
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    names = set(inspect(engine).get_table_names())
    assert {"users", "students", "enrollments", "assessment_schedule", "predictions",
            "study_plans", "dataset_imports", "imported_feature_snapshots",
            "student_access_requests", "alembic_version"} <= names
    student_columns = {column["name"] for column in inspect(engine).get_columns("students")}
    assert {"enrollment_number", "access_approved"} <= student_columns
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "token_version" in user_columns
    enrollment_columns = {column["name"] for column in inspect(engine).get_columns("enrollments")}
    assert {"registration_day", "num_of_prev_attempts", "studied_credits"} <= enrollment_columns
    academic_columns = {column["name"] for column in inspect(engine).get_columns("academic_records")}
    assert {"assessment_key", "submitted_day"} <= academic_columns
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert "users" not in inspect(engine).get_table_names()
    engine.dispose()


def test_grade_prediction_signals_use_jsonb_on_postgresql_like_its_migration():
    # Migration a58f9d632e10 creates this column as JSONB on PostgreSQL; the ORM must match,
    # otherwise `alembic check` reports drift and autogenerate emits a spurious type change.
    from sqlalchemy.dialects import postgresql
    from backend.app.models.entities import GradePrediction
    column_type = GradePrediction.__table__.c.observed_signals.type
    assert column_type.compile(dialect=postgresql.dialect()) == "JSONB"
