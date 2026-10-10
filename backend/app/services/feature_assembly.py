"""Assemble the Phase 2 feature contract from coordinator-ingested records."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AcademicRecord, EngagementRecord, Enrollment, ScheduledAssessment
from ml.clustering.features import ENGAGEMENT
from ml.timeseries.features import SEQUENCE_LENGTH
from ml.features.build_dataset import FEATURES
from ml.inference.prediction_service import validate_cluster_features, validate_features

PREDICTION_DAY = 56
SEQUENCE_WEEKS = SEQUENCE_LENGTH


class InsufficientHistoricalData(ValueError):
    """Raised when the eight-week Phase 2 input window is not fully observed."""


def _observed_early_activity(db: Session, enrollment: Enrollment) -> list[EngagementRecord]:
    activity = list(db.scalars(select(EngagementRecord).where(
        EngagementRecord.enrollment_id == enrollment.id,
        EngagementRecord.week_index >= 0, EngagementRecord.week_index < SEQUENCE_WEEKS)))
    observed_weeks = {row.week_index for row in activity}
    missing_weeks = sorted(set(range(SEQUENCE_WEEKS)) - observed_weeks)
    if missing_weeks:
        raise InsufficientHistoricalData(
            f"Insufficient historical data: weekly records are missing for "
            f"{len(missing_weeks)} of {SEQUENCE_WEEKS} required weeks. "
            "Record all weeks 0-7, using zero values only when a week was observed with no activity."
        )
    return activity


def build_student_features(db: Session, enrollment: Enrollment) -> dict:
    """Build supervised features with the same day-56 rules as Phase 2 training."""
    scheduled = list(db.scalars(select(ScheduledAssessment).where(
        ScheduledAssessment.enrollment_id == enrollment.id)))
    early_schedule = {row.assessment_key: row.scheduled_day for row in scheduled
                      if row.scheduled_day is not None and 0 <= row.scheduled_day < PREDICTION_DAY}
    performance = list(db.scalars(select(AcademicRecord).where(
        AcademicRecord.enrollment_id == enrollment.id,
        AcademicRecord.record_type == "assessment_score")))
    eligible: list[tuple[float, int]] = []
    for record in performance:
        assessment_key = record.assessment_key
        submitted_day = record.submitted_day
        if (record.score is None or assessment_key not in early_schedule or
                isinstance(submitted_day, bool) or not isinstance(submitted_day, int) or
                not 0 <= submitted_day < PREDICTION_DAY):
            continue
        eligible.append((float(record.score), int(submitted_day <= early_schedule[assessment_key])))

    activity = _observed_early_activity(db, enrollment)
    early_clicks = sum(row.clicks for row in activity)
    early_active_days = sum(row.active_days for row in activity)
    active_weeks = sum(row.clicks > 0 for row in activity)
    sites: set[int] = set()
    activity_types: set[str] = set()
    for row in activity:
        metrics = row.metrics or {}
        sites.update(metrics.get("active_site_ids", []))
        activity_types.update(metrics.get("activity_types", []))

    count = len(eligible)
    scheduled_count = len(early_schedule)
    values = {
        "registration_day": enrollment.registration_day,
        "num_of_prev_attempts": enrollment.num_of_prev_attempts,
        "studied_credits": enrollment.studied_credits,
        "early_assessment_mean": sum(score for score, _ in eligible) / count if count else None,
        "early_assessment_count": count,
        "early_on_time_rate": sum(on_time for _, on_time in eligible) / count if count else None,
        "early_assessment_coverage": count / scheduled_count if scheduled_count else None,
        "early_vle_clicks": early_clicks,
        "early_vle_active_days": early_active_days,
        "early_vle_active_weeks": active_weeks,
        "early_vle_active_sites": len(sites),
        "early_vle_activity_types": len(activity_types),
        "code_module": enrollment.code_module,
        "code_presentation": enrollment.code_presentation,
    }
    # Keep ordering and validation bound to the same versioned contract as training.
    clean = validate_features(values)
    return {name: clean[name] for name in FEATURES}


def build_engagement_features(db: Session, enrollment: Enrollment) -> dict:
    full = build_student_features(db, enrollment)
    features = {name: full[name] for name in ENGAGEMENT}
    return validate_cluster_features(features)


def build_weekly_sequence(db: Session, enrollment: Enrollment) -> list[list[float]]:
    records = _observed_early_activity(db, enrollment)
    by_week = {record.week_index: record for record in records}
    weeks = [[float(by_week[week].clicks), float(by_week[week].active_days)]
             for week in range(SEQUENCE_WEEKS)]
    if sum(week[0] for week in weeks) > 9481 or sum(week[1] for week in weeks) > 56:
        raise ValueError("Weekly activity totals exceed the Phase 2 day-56 feature contract")
    return weeks
