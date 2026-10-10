from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserRole(str, Enum):
    STUDENT = "student"
    COORDINATOR = "coordinator"


class UserCreate(StrictSchema):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: UserRole = UserRole.STUDENT
    invite_code: str | None = Field(default=None, max_length=256)

    @field_validator("password")
    @classmethod
    def password_has_mixed_classes(cls, value: str) -> str:
        if not any(c.islower() for c in value) or not any(c.isupper() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value


class LoginRequest(StrictSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(StrictSchema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_has_mixed_classes(cls, value: str) -> str:
        if not any(c.islower() for c in value) or not any(c.isupper() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Password must include uppercase, lowercase, and numeric characters")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class EnrollmentCreate(StrictSchema):
    code_module: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9_-]+$")
    code_presentation: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9_-]+$")
    registration_day: int | None = Field(default=None, ge=-322, le=49)
    num_of_prev_attempts: int | None = Field(default=None, ge=0, le=6)
    studied_credits: int | None = Field(default=None, ge=30, le=655)


class EnrollmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code_module: str
    code_presentation: str
    registration_day: int | None
    num_of_prev_attempts: int | None
    studied_credits: int | None
    is_active: bool
    created_at: datetime


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    enrollment_number: str | None
    access_approved: bool
    created_at: datetime


class StudentDetail(StudentRead):
    user: UserRead
    enrollments: list[EnrollmentRead]


class StudentAccessRequestCreate(StrictSchema):
    enrollment_number: str = Field(pattern=r"^24030315[0-9]{5,}$", max_length=32)


class StudentAccessRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    student_id: UUID
    enrollment_number: str
    status: Literal["pending", "approved", "rejected"]
    reviewed_by_user_id: UUID | None
    created_at: datetime
    reviewed_at: datetime | None


class StudentAccessRequestStatus(BaseModel):
    access_approved: bool
    enrollment_number: str | None
    request: StudentAccessRequestRead | None


class CoordinatorAccessRequestRead(StudentAccessRequestRead):
    student_email: EmailStr
    courses: list[str]


class AccessRequestDecision(StrictSchema):
    status: Literal["approved", "rejected"]


class AcademicRecordCreate(StrictSchema):
    record_type: str = Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")
    score: float | None = Field(default=None, ge=0, le=100)
    occurred_on: datetime | None = None
    assessment_key: str | None = Field(default=None, min_length=1, max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$")
    submitted_day: int | None = Field(default=None, ge=0, le=608)
    details: dict[str, Any] = Field(default_factory=dict, max_length=40)

    @field_validator("submitted_day", mode="before")
    @classmethod
    def submitted_day_is_an_integer(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError("submitted_day must be an integer course-relative day")
        return value

    @model_validator(mode="after")
    def assessment_scores_have_source_dates(self):
        if self.record_type == "assessment_score":
            if self.assessment_key is None or self.submitted_day is None:
                raise ValueError("assessment_score requires assessment_key and submitted_day")
        elif self.assessment_key is not None or self.submitted_day is not None:
            raise ValueError("assessment source fields are only valid for assessment_score records")
        return self


class AcademicRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    record_type: str
    score: float | None
    occurred_on: datetime | None
    assessment_key: str | None
    submitted_day: int | None
    details: dict[str, Any]
    recorded_at: datetime


class EngagementRecordCreate(StrictSchema):
    week_index: int = Field(ge=0, le=60)
    clicks: int = Field(ge=0, le=9481)
    active_days: int = Field(ge=0, le=7)
    active_site_ids: list[int] = Field(max_length=267)
    activity_types: list[str] = Field(max_length=14)
    metrics: dict[str, Any] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def unique_source_dimensions(self):
        if len(set(self.active_site_ids)) != len(self.active_site_ids) or any(site < 0 for site in self.active_site_ids):
            raise ValueError("active_site_ids must contain unique nonnegative IDs")
        if (len(set(self.activity_types)) != len(self.activity_types) or
                any(not value.strip() or len(value) > 32 for value in self.activity_types)):
            raise ValueError("activity_types must contain unique nonempty values of at most 32 characters")
        return self


class EngagementRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    week_index: int
    clicks: int
    active_days: int
    metrics: dict[str, Any]
    recorded_at: datetime


class PredictionCreate(StrictSchema):
    enrollment_id: UUID


class SequencePredictionCreate(StrictSchema):
    enrollment_id: UUID


class PredictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    model_name: str
    model_version: str
    feature_version: str
    support_priority_score: float
    threshold: float
    priority_band: str
    observed_signals: dict[str, Any]
    created_at: datetime


class GradePredictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    model_name: str
    model_version: str
    feature_version: str
    target_name: str
    prediction_day: int
    predicted_score: float
    observed_signals: dict[str, Any]
    created_at: datetime


class ClusterCreate(StrictSchema):
    enrollment_id: UUID


class ScheduledAssessmentInput(StrictSchema):
    assessment_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scheduled_day: int | None = Field(default=None, ge=-365, le=500)
    weight: float | None = Field(default=None, ge=0, le=100)


class ScheduledAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    assessment_key: str
    scheduled_day: int | None
    weight: float | None
    created_at: datetime


class AssessmentScheduleBatch(StrictSchema):
    assessments: list[ScheduledAssessmentInput] = Field(min_length=1, max_length=206)

    @model_validator(mode="after")
    def assessment_keys_are_unique(self):
        keys = [item.assessment_key for item in self.assessments]
        if len(keys) != len(set(keys)):
            raise ValueError("Assessment keys must be unique in a schedule batch")
        return self


class ClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    cluster_id: int
    model_version: str
    feature_version: str
    observed_signals: dict[str, Any]
    assigned_at: datetime


class InterventionStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InterventionCreate(StrictSchema):
    enrollment_id: UUID
    title: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=4000)
    due_date: date | None = None


class InterventionUpdate(StrictSchema):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    status: InterventionStatus | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied")
        if any(getattr(self, name) is None for name in ("title", "notes", "status")
               if name in self.model_fields_set):
            raise ValueError("title, notes, and status cannot be null")
        return self


class InterventionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    created_by_user_id: UUID
    title: str
    notes: str
    status: InterventionStatus
    due_date: date | None
    created_at: datetime
    updated_at: datetime


class StudyPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    enrollment_id: UUID
    source_prediction_id: UUID | None
    content: dict[str, Any]
    status: str
    generated_by_llm: bool
    created_at: datetime


class StudyPlanCreate(StrictSchema):
    enrollment_id: UUID


class MotivationalMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    content: str
    source: str
    created_at: datetime


class StudyPlanResult(BaseModel):
    study_plan: StudyPlanRead
    motivational_message: MotivationalMessageRead
    generated_by_llm: bool


class LatestImportSummary(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created_at: datetime


class AnalyticsOverview(BaseModel):
    students: int
    enrollments: int
    predictions: int
    review_for_support: int
    interventions_open: int
    risk_distribution: dict[str, int]
    outcome_forecast_distribution: dict[str, int]
    performance_distribution: dict[str, int]
    recorded_score_count: int
    mean_recorded_score: float | None
    intervention_status_counts: dict[str, int]
    imports_total: int
    latest_import: LatestImportSummary | None


class RiskTrendPoint(BaseModel):
    date: date
    count: int
    mean_score: float


class LatestPredictionSummary(BaseModel):
    id: UUID
    enrollment_id: UUID
    model_name: str
    model_version: str
    feature_version: str
    support_priority_score: float
    threshold: float
    priority_band: str
    created_at: datetime


class MonitoringStudent(BaseModel):
    student_id: UUID
    email: str
    created_at: datetime
    enrollment_count: int
    latest_prediction: LatestPredictionSummary | None


class MonitoringStudentsPage(BaseModel):
    items: list[MonitoringStudent]
    total: int
    offset: int
    limit: int


class ClusterProfile(BaseModel):
    cluster_id: int
    student_count: int
    enrollment_count: int
    model_version: str
    feature_version: str
    median_features: dict[str, float | None]
