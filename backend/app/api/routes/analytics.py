from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Literal
from fastapi import APIRouter, Depends
from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session
from backend.app.core.dependencies import require_roles
from backend.app.db.dependencies import get_db
from backend.app.models import (AcademicRecord, BehavioralCluster, DatasetImport, Enrollment,
    EngagementRecord, ImportedFeatureSnapshot, Intervention, Prediction, Student, User)
from backend.app.schemas.common import (AnalyticsOverview, ClusterProfile, MonitoringStudent,
    MonitoringStudentsPage, LatestPredictionSummary, RiskTrendPoint)

router = APIRouter(prefix="/analytics", tags=["coordinator analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def overview(_user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    ranked = select(Prediction.enrollment_id, Prediction.priority_band,
        func.row_number().over(partition_by=Prediction.enrollment_id,
            order_by=(Prediction.created_at.desc(), Prediction.id.desc())).label("rank")).subquery()
    latest_rows = select(ranked).where(ranked.c.rank == 1).subquery()
    review_count = db.scalar(select(func.count()).select_from(latest_rows).where(
        latest_rows.c.priority_band == "review_for_support")) or 0
    no_flag_count = db.scalar(select(func.count()).select_from(latest_rows).where(
        latest_rows.c.priority_band == "no_flag_from_model")) or 0
    latest_count = db.scalar(select(func.count()).select_from(latest_rows)) or 0
    enrollment_count = db.scalar(select(func.count()).select_from(Enrollment)) or 0
    forecast_ranked = select(Prediction.enrollment_id, Prediction.priority_band,
        func.row_number().over(partition_by=Prediction.enrollment_id,
            order_by=(Prediction.created_at.desc(), Prediction.id.desc())).label("rank"))\
        .where(Prediction.model_name == "lstm_weekly").subquery()
    latest_forecasts = select(forecast_ranked).where(forecast_ranked.c.rank == 1).subquery()
    forecast_review = db.scalar(select(func.count()).select_from(latest_forecasts).where(
        latest_forecasts.c.priority_band == "review_for_support")) or 0
    forecast_no_flag = db.scalar(select(func.count()).select_from(latest_forecasts).where(
        latest_forecasts.c.priority_band == "no_flag_from_model")) or 0
    performance_bands = case(
        (AcademicRecord.score < 20, "0-19"),
        (AcademicRecord.score < 40, "20-39"),
        (AcademicRecord.score < 60, "40-59"),
        (AcademicRecord.score < 80, "60-79"),
        else_="80-100",
    ).label("score_band")
    performance_rows = db.execute(select(performance_bands, func.count(AcademicRecord.id))
        .where(AcademicRecord.score.is_not(None)).group_by(performance_bands)).all()
    performance_distribution = {f"{lower}-{lower + 19 if lower < 80 else 100}": 0
                                for lower in (0, 20, 40, 60, 80)}
    performance_distribution.update({band: count for band, count in performance_rows})
    score_count, mean_score = db.execute(select(func.count(AcademicRecord.id),
        func.avg(AcademicRecord.score)).where(AcademicRecord.score.is_not(None))).one()
    status_rows = db.execute(select(Intervention.status, func.count(Intervention.id))
        .group_by(Intervention.status)).all()
    status_counts = {name: count for name, count in status_rows}
    imports_total = db.scalar(select(func.count()).select_from(DatasetImport)) or 0
    latest_import_row = db.scalar(select(DatasetImport).order_by(
        DatasetImport.created_at.desc()).limit(1))
    latest_import = None
    if latest_import_row is not None:
        imported_rows = db.scalar(select(func.count()).select_from(ImportedFeatureSnapshot)
            .where(ImportedFeatureSnapshot.dataset_import_id == latest_import_row.id)) or 0
        latest_import = {
            "filename": latest_import_row.original_filename,
            "total_rows": latest_import_row.row_count,
            "valid_rows": imported_rows,
            "invalid_rows": max(0, latest_import_row.row_count - imported_rows),
            "created_at": latest_import_row.created_at,
        }
    return AnalyticsOverview(students=db.scalar(select(func.count()).select_from(Student)) or 0,
        enrollments=enrollment_count,
        predictions=db.scalar(select(func.count()).select_from(Prediction)) or 0,
        review_for_support=review_count,
        interventions_open=db.scalar(select(func.count()).select_from(Intervention).where(
            Intervention.status.in_(["open", "in_progress"]))) or 0,
        risk_distribution={"review_for_support": review_count, "no_flag_from_model": no_flag_count,
            "unscored": max(enrollment_count - latest_count, 0)},
        outcome_forecast_distribution={
            "review_for_support": forecast_review,
            "no_flag_from_model": forecast_no_flag,
            "not_generated": max(enrollment_count - forecast_review - forecast_no_flag, 0),
        },
        performance_distribution=performance_distribution,
        recorded_score_count=score_count,
        mean_recorded_score=float(mean_score) if mean_score is not None else None,
        intervention_status_counts={status: status_counts.get(status, 0) for status in
            ("open", "in_progress", "completed", "cancelled")},
        imports_total=imports_total, latest_import=latest_import)


@router.get("/risk-trends", response_model=list[RiskTrendPoint])
def risk_trends(days: int = 30, _user: User = Depends(require_roles("coordinator")),
                db: Session = Depends(get_db)):
    days = min(max(days, 1), 365)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(db.scalars(select(Prediction).where(Prediction.created_at >= cutoff)
                           .order_by(Prediction.created_at)))
    grouped: dict[date, list[float]] = {}
    for row in rows:
        grouped.setdefault(row.created_at.date(), []).append(row.support_priority_score)
    return [RiskTrendPoint(date=day, count=len(scores), mean_score=sum(scores) / len(scores))
            for day, scores in sorted(grouped.items())]


@router.get("/engagement")
def engagement_analytics(_user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    rows = db.execute(select(EngagementRecord.week_index,
        func.count(EngagementRecord.id).label("records"),
        func.avg(EngagementRecord.clicks).label("mean_clicks"),
        func.avg(EngagementRecord.active_days).label("mean_active_days"))
        .group_by(EngagementRecord.week_index).order_by(EngagementRecord.week_index)).all()
    return {"weeks": [{"week_index": row.week_index, "records": row.records,
        "mean_clicks": float(row.mean_clicks or 0), "mean_active_days": float(row.mean_active_days or 0)}
        for row in rows]}


@router.get("/monitoring/students", response_model=MonitoringStudentsPage)
def monitoring_students(search: str | None = None,
    risk_filter: Literal["review_for_support", "no_flag_from_model", "unscored"] | None = None,
    sort_by: Literal["created_at", "email", "support_score"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc", offset: int = 0, limit: int = 25,
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    """Return a paginated coordinator roster with each student's latest prediction summary."""
    offset = max(offset, 0)
    limit = min(max(limit, 1), 100)
    latest = select(Enrollment.student_id.label("student_id"),
        Prediction.id.label("prediction_id"), Prediction.enrollment_id.label("enrollment_id"),
        Prediction.model_name.label("model_name"), Prediction.model_version.label("model_version"),
        Prediction.feature_version.label("feature_version"),
        Prediction.support_priority_score.label("support_priority_score"),
        Prediction.threshold.label("threshold"), Prediction.priority_band.label("priority_band"),
        Prediction.created_at.label("prediction_created_at"),
        func.row_number().over(partition_by=Enrollment.student_id,
            order_by=(Prediction.created_at.desc(), Prediction.id.desc())).label("row_num"))\
        .join(Prediction, Prediction.enrollment_id == Enrollment.id).subquery()
    latest_join = and_(latest.c.student_id == Student.id, latest.c.row_num == 1)
    filters = []
    if search and search.strip():
        term = search.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        filters.append(or_(User.email.ilike(pattern, escape="\\"),
            cast(Student.id, String).ilike(pattern, escape="\\")))
    if risk_filter == "unscored":
        filters.append(latest.c.prediction_id.is_(None))
    elif risk_filter is not None:
        filters.append(latest.c.priority_band == risk_filter)

    source = select(Student.id).join(User, User.id == Student.user_id).outerjoin(
        latest, latest_join).where(*filters).subquery()
    total = db.scalar(select(func.count()).select_from(source)) or 0

    order_columns = {"created_at": Student.created_at, "email": User.email,
                     "support_score": latest.c.support_priority_score}
    order_column = order_columns[sort_by]
    ordered = order_column.desc().nulls_last() if sort_order == "desc" else order_column.asc().nulls_last()
    rows = db.execute(select(Student.id.label("student_id"), User.email, Student.created_at,
        latest.c.prediction_id, latest.c.enrollment_id, latest.c.model_name,
        latest.c.model_version, latest.c.feature_version, latest.c.support_priority_score,
        latest.c.threshold, latest.c.priority_band,
        latest.c.prediction_created_at).join(User, User.id == Student.user_id)
        .outerjoin(latest, latest_join).where(*filters)
        .order_by(ordered, Student.id).offset(offset).limit(limit)).all()
    if not rows:
        return MonitoringStudentsPage(items=[], total=total, offset=offset, limit=limit)
    student_ids = [row.student_id for row in rows]
    enrollment_counts = dict(db.execute(select(Enrollment.student_id, func.count(Enrollment.id))
        .where(Enrollment.student_id.in_(student_ids)).group_by(Enrollment.student_id)).all())
    items = []
    for row in rows:
        prediction = None
        if row.prediction_id is not None:
            prediction = LatestPredictionSummary(id=row.prediction_id,
                enrollment_id=row.enrollment_id, model_name=row.model_name,
                model_version=row.model_version, feature_version=row.feature_version,
                support_priority_score=row.support_priority_score, threshold=row.threshold,
                priority_band=row.priority_band, created_at=row.prediction_created_at)
        items.append(MonitoringStudent(student_id=row.student_id, email=row.email,
            created_at=row.created_at, enrollment_count=enrollment_counts.get(row.student_id, 0),
            latest_prediction=prediction))
    return MonitoringStudentsPage(items=items, total=total, offset=offset, limit=limit)


@router.get("/clusters", response_model=list[ClusterProfile])
def cluster_profiles(_user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    """Summarize the latest persisted cluster assignment for every enrollment."""
    from ml.clustering.features import ENGAGEMENT

    latest = select(BehavioralCluster.id.label("id"), BehavioralCluster.enrollment_id.label("enrollment_id"),
        Enrollment.student_id.label("student_id"), BehavioralCluster.cluster_id.label("cluster_id"),
        BehavioralCluster.model_version.label("model_version"),
        BehavioralCluster.feature_version.label("feature_version"),
        BehavioralCluster.observed_signals.label("observed_signals"),
        func.row_number().over(partition_by=BehavioralCluster.enrollment_id,
            order_by=(BehavioralCluster.assigned_at.desc(), BehavioralCluster.id.desc())).label("row_num"))\
        .join(Enrollment, Enrollment.id == BehavioralCluster.enrollment_id).subquery()
    rows = db.execute(select(latest).where(latest.c.row_num == 1)).mappings().all()
    groups: dict[int, list] = {}
    for row in rows:
        groups.setdefault(row["cluster_id"], []).append(row)
    result = []
    for cluster_id, group in sorted(groups.items()):
        medians = {}
        for feature in ENGAGEMENT:
            values = [float(row["observed_signals"][feature]) for row in group
                      if row["observed_signals"].get(feature) is not None]
            medians[feature] = float(median(values)) if values else None
        result.append(ClusterProfile(cluster_id=cluster_id,
            student_count=len({row["student_id"] for row in group}), enrollment_count=len(group),
            model_version=group[0]["model_version"], feature_version=group[0]["feature_version"],
            median_features=medians))
    return result
