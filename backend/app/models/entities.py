from datetime import date, datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
    Index, Integer, JSON, String, UniqueConstraint, Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('student', 'coordinator')", name="ck_users_role"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="student")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    student: Mapped["Student | None"] = relationship(back_populates="user", uselist=False,
        cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, nullable=False)
    enrollment_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    access_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="student")
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student",
        cascade="all, delete-orphan", passive_deletes=True)


class StudentAccessRequest(Base):
    __tablename__ = "student_access_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')",
                        name="ck_student_access_request_status"),
        UniqueConstraint("student_id", name="uq_student_access_request_student"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetImport(Base):
    __tablename__ = "dataset_imports"
    __table_args__ = (UniqueConstraint("sha256", name="uq_dataset_import_sha256"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ImportedFeatureSnapshot(Base):
    __tablename__ = "imported_feature_snapshots"
    __table_args__ = (UniqueConstraint("dataset_import_id", "source_row",
                        name="uq_import_snapshot_source_row"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_import_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("dataset_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    weekly_sequence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prediction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("predictions.id", ondelete="RESTRICT"), nullable=False, unique=True)
    forecast_prediction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("predictions.id", ondelete="RESTRICT"), nullable=True, unique=True)
    cluster_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("behavioral_clusters.id", ondelete="RESTRICT"), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "code_module", "code_presentation",
                        name="uq_enrollment_student_module_presentation"),
        CheckConstraint("registration_day IS NULL OR (registration_day >= -322 AND registration_day <= 49)",
                        name="ck_enrollment_registration_day"),
        CheckConstraint("num_of_prev_attempts IS NULL OR (num_of_prev_attempts >= 0 AND num_of_prev_attempts <= 6)",
                        name="ck_enrollment_previous_attempts"),
        CheckConstraint("studied_credits IS NULL OR (studied_credits >= 30 AND studied_credits <= 655)",
                        name="ck_enrollment_studied_credits"))

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True)
    code_module: Mapped[str] = mapped_column(String(8), nullable=False)
    code_presentation: Mapped[str] = mapped_column(String(8), nullable=False)
    registration_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_of_prev_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    studied_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    student: Mapped[Student] = relationship(back_populates="enrollments")
    academic_records: Mapped[list["AcademicRecord"]] = relationship(back_populates="enrollment",
        cascade="all, delete-orphan", passive_deletes=True)
    engagement_records: Mapped[list["EngagementRecord"]] = relationship(back_populates="enrollment",
        cascade="all, delete-orphan", passive_deletes=True)
    assessment_schedule: Mapped[list["ScheduledAssessment"]] = relationship(back_populates="enrollment",
        cascade="all, delete-orphan", passive_deletes=True)


class ScheduledAssessment(Base):
    __tablename__ = "assessment_schedule"
    __table_args__ = (UniqueConstraint("enrollment_id", "assessment_key", name="uq_assessment_enrollment_key"),
        CheckConstraint("scheduled_day IS NULL OR (scheduled_day >= -365 AND scheduled_day <= 500)",
                        name="ck_assessment_scheduled_day"),
        CheckConstraint("weight IS NULL OR (weight >= 0 AND weight <= 100)", name="ck_assessment_weight"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    enrollment: Mapped[Enrollment] = relationship(back_populates="assessment_schedule")


class AcademicRecord(Base):
    __tablename__ = "academic_records"
    __table_args__ = (CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)",
                                      name="ck_academic_score_range"),
                      CheckConstraint("record_type != 'assessment_score' OR "
                          "(assessment_key IS NOT NULL AND submitted_day IS NOT NULL AND "
                          "submitted_day >= 0 AND submitted_day <= 608)",
                          name="ck_academic_assessment_source"),
                      UniqueConstraint("enrollment_id", "assessment_key",
                          name="uq_academic_enrollment_assessment"),
                      Index("ix_academic_enrollment_recorded", "enrollment_id", "recorded_at"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(48), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessment_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    enrollment: Mapped[Enrollment] = relationship(back_populates="academic_records")


class EngagementRecord(Base):
    __tablename__ = "engagement_records"
    __table_args__ = (CheckConstraint("week_index >= 0 AND week_index <= 60", name="ck_engagement_week_range"),
        CheckConstraint("clicks >= 0 AND clicks <= 9481 AND active_days >= 0 AND active_days <= 7",
                        name="ck_engagement_counts"),
        UniqueConstraint("enrollment_id", "week_index", name="uq_engagement_week"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    week_index: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    enrollment: Mapped[Enrollment] = relationship(back_populates="engagement_records")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (CheckConstraint("support_priority_score >= 0 AND support_priority_score <= 1",
                                      name="ck_prediction_score_range"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_prediction_threshold_range"),
        Index("ix_prediction_enrollment_created", "enrollment_id", "created_at"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    support_priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    priority_band: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class GradePrediction(Base):
    __tablename__ = "grade_predictions"
    __table_args__ = (
        CheckConstraint("predicted_score >= 0 AND predicted_score <= 100",
                        name="ck_grade_prediction_score_range"),
        Index("ix_grade_prediction_enrollment_created", "enrollment_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    target_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction_day: Mapped[int] = mapped_column(Integer, nullable=False, default=56)
    predicted_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Matches migration a58f9d632e10, which creates JSONB on PostgreSQL.
    observed_signals: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"),
                                                   nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class BehavioralCluster(Base):
    __tablename__ = "behavioral_clusters"
    __table_args__ = (Index("ix_cluster_enrollment_assigned", "enrollment_id", "assigned_at"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Intervention(Base):
    __tablename__ = "interventions"
    __table_args__ = (CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')",
                                      name="ck_intervention_status"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    notes: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
        default=utc_now, onupdate=utc_now)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    __table_args__ = (CheckConstraint("status IN ('draft', 'active', 'completed')", name="ck_study_plan_status"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source_prediction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("predictions.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    generated_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class MotivationalMessage(Base):
    __tablename__ = "motivational_messages"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    study_plan_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True),
        ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=True)
    content: Mapped[str] = mapped_column(String(1200), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="fallback")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
