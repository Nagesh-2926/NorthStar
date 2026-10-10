from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeneratedStudySupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=120)
    priorities: list[str] = Field(default_factory=list, max_length=4)
    actions: list[str] = Field(min_length=1, max_length=6)
    schedule: list[str] = Field(default_factory=list, max_length=7)
    goals: list[str] = Field(default_factory=list, max_length=6)
    motivational_message: str = Field(min_length=5, max_length=500)

    @field_validator("actions")
    @classmethod
    def validate_action_lengths(cls, actions: list[str]) -> list[str]:
        if any(not action.strip() or len(action) > 280 for action in actions):
            raise ValueError("Each action must contain 1 to 280 characters")
        return actions

    @field_validator("priorities", "schedule", "goals")
    @classmethod
    def validate_plan_entries(cls, entries: list[str]) -> list[str]:
        if any(not entry.strip() or len(entry) > 280 for entry in entries):
            raise ValueError("Plan entries must contain 1 to 280 characters")
        return entries


class StudySupportContext(BaseModel):
    """Minimal, pseudonymous fields permitted in an external generation request."""
    model_config = ConfigDict(extra="forbid")
    priority_band: str = Field(pattern=r"^(review_for_support|no_flag_from_model)$")
    recent_performance: list[float] = Field(default_factory=list, max_length=8)
    active_weeks: int | None = Field(default=None, ge=0, le=8)
    assessment_count: int | None = Field(default=None, ge=0, le=4)
    cluster_id: int | None = Field(default=None, ge=0, le=20)
    early_assessment_mean: float | None = Field(default=None, ge=0, le=100)
    early_on_time_rate: float | None = Field(default=None, ge=0, le=1)
    early_vle_clicks: int | None = Field(default=None, ge=0, le=9481)
    recent_intervention_statuses: list[str] = Field(default_factory=list, max_length=20)
    scheduled_assessment_keys: list[str] = Field(default_factory=list, max_length=20)


class StudyPlanProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed_goal_indices: list[int] = Field(max_length=6)

    @model_validator(mode="after")
    def validate_goal_indices(self):
        if any(index < 0 for index in self.completed_goal_indices):
            raise ValueError("Completed goal indices must be nonnegative")
        if len(set(self.completed_goal_indices)) != len(self.completed_goal_indices):
            raise ValueError("Completed goal indices must be unique")
        return self


class SupportAssistantQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_id: UUID
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class SupportAssistantAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    source: Literal["llm"]
