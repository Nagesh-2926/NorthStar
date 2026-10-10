import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.dependencies import get_authorized_student, get_current_user
from backend.app.db.dependencies import get_db
from backend.app.models import (AcademicRecord, BehavioralCluster, EngagementRecord,
    DatasetImport, Enrollment, ImportedFeatureSnapshot, Intervention, MotivationalMessage,
    Prediction, ScheduledAssessment, StudyPlan, User)
from backend.app.repositories.students import get_enrollment_for_student
from backend.app.schemas.common import (MotivationalMessageRead, StudyPlanCreate,
    StudyPlanRead, StudyPlanResult)
from backend.app.schemas.llm import (StudyPlanProgressUpdate, StudySupportContext,
    SupportAssistantAnswer, SupportAssistantQuestion)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["study plans"])


def _build_support_context(db: Session, enrollment: Enrollment,
                           prediction: Prediction) -> StudySupportContext:
    snapshot = db.scalar(
        select(ImportedFeatureSnapshot)
        .join(DatasetImport, DatasetImport.id == ImportedFeatureSnapshot.dataset_import_id)
        .where(ImportedFeatureSnapshot.enrollment_id == enrollment.id)
        .order_by(DatasetImport.created_at.desc(), ImportedFeatureSnapshot.source_row.desc())
        .limit(1)
    )
    imported_features = snapshot.features if snapshot is not None else {}
    engagement = list(db.scalars(select(EngagementRecord).where(
        EngagementRecord.enrollment_id == enrollment.id, EngagementRecord.week_index < 8)
        .order_by(EngagementRecord.week_index.desc()).limit(8)))
    academic = list(db.scalars(select(AcademicRecord).where(
        AcademicRecord.enrollment_id == enrollment.id, AcademicRecord.score.is_not(None))
        .order_by(AcademicRecord.occurred_on.desc().nullslast(),
                  AcademicRecord.recorded_at.desc()).limit(8)))
    cluster = db.scalar(select(BehavioralCluster).where(
        BehavioralCluster.enrollment_id == enrollment.id)
        .order_by(BehavioralCluster.assigned_at.desc()).limit(1))
    interventions = list(db.scalars(select(Intervention).where(
        Intervention.enrollment_id == enrollment.id)
        .order_by(Intervention.created_at.desc()).limit(20)))
    scheduled = list(db.scalars(select(ScheduledAssessment).where(
        ScheduledAssessment.enrollment_id == enrollment.id)
        .order_by(ScheduledAssessment.scheduled_day, ScheduledAssessment.assessment_key).limit(20)))

    recent_scores = [float(record.score) for record in academic if record.score is not None]
    if imported_features.get("early_assessment_mean") is not None:
        recent_scores.insert(0, float(imported_features["early_assessment_mean"]))
    active_weeks = imported_features.get("early_vle_active_weeks")
    if active_weeks is None and engagement:
        active_weeks = min(8, sum(1 for row in engagement if row.clicks > 0))
    assessment_count = imported_features.get("early_assessment_count")
    if assessment_count is None and academic:
        assessment_count = min(4, len(academic))
    return StudySupportContext(
        priority_band=prediction.priority_band,
        recent_performance=recent_scores[:8],
        active_weeks=int(active_weeks) if active_weeks is not None else None,
        assessment_count=int(assessment_count) if assessment_count is not None else None,
        cluster_id=cluster.cluster_id if cluster else None,
        early_assessment_mean=imported_features.get("early_assessment_mean"),
        early_on_time_rate=imported_features.get("early_on_time_rate"),
        early_vle_clicks=imported_features.get("early_vle_clicks"),
        recent_intervention_statuses=[item.status for item in interventions],
        scheduled_assessment_keys=[item.assessment_key for item in scheduled],
    )


def _assistant_context(db: Session, enrollment: Enrollment, prediction: Prediction,
                       context: StudySupportContext) -> dict:
    academic = list(db.scalars(select(AcademicRecord).where(
        AcademicRecord.enrollment_id == enrollment.id)
        .order_by(AcademicRecord.recorded_at.desc()).limit(20)))
    engagement = list(db.scalars(select(EngagementRecord).where(
        EngagementRecord.enrollment_id == enrollment.id)
        .order_by(EngagementRecord.week_index.desc()).limit(8)))
    interventions = list(db.scalars(select(Intervention).where(
        Intervention.enrollment_id == enrollment.id)
        .order_by(Intervention.created_at.desc()).limit(20)))
    plan = db.scalar(select(StudyPlan).where(
        StudyPlan.enrollment_id == enrollment.id)
        .order_by(StudyPlan.created_at.desc()).limit(1))
    schedule = list(db.scalars(select(ScheduledAssessment).where(
        ScheduledAssessment.enrollment_id == enrollment.id)
        .order_by(ScheduledAssessment.scheduled_day, ScheduledAssessment.assessment_key).limit(20)))
    return {
        "course": {"module": enrollment.code_module, "presentation": enrollment.code_presentation},
        "support_review": {
            "category": prediction.priority_band,
            "score": prediction.support_priority_score,
            "threshold": prediction.threshold,
            "model": prediction.model_name,
            "recorded_at": prediction.created_at.isoformat(),
        },
        "observed_feature_summary": context.model_dump(),
        "academic_records": [{
            "record_type": record.record_type,
            "score": record.score,
            "assessment_key": record.assessment_key,
            "submitted_day": record.submitted_day,
        } for record in academic],
        "weekly_engagement_records": [{
            "week_index": record.week_index,
            "clicks": record.clicks,
            "active_days": record.active_days,
        } for record in engagement],
        "student_visible_interventions": [{
            "status": item.status,
            "due_date": item.due_date.isoformat() if item.due_date else None,
        } for item in interventions],
        "latest_study_plan": plan.content if plan else None,
        "recorded_assessment_schedule": [{
            "assessment_key": item.assessment_key,
            "course_relative_day": item.scheduled_day,
        } for item in schedule],
        "course_content_available": False,
        "forecast_target": "end-of-course Fail/Withdrawn outcome; not a dropout-specific forecast",
    }


@router.get("/students/{student_id}/study-plan", response_model=list[StudyPlanRead])
def list_study_plans(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(StudyPlan).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(StudyPlan.enrollment_id == enrollment_id)
    return list(db.scalars(query.order_by(StudyPlan.created_at.desc()).limit(100)))


@router.post("/students/{student_id}/study-plan", response_model=StudyPlanResult,
             status_code=status.HTTP_201_CREATED)
def create_study_plan(student_id: UUID, body: StudyPlanCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    prediction = db.scalar(select(Prediction).where(Prediction.enrollment_id == enrollment.id)
                           .order_by(Prediction.created_at.desc()).limit(1))
    if prediction is None:
        raise HTTPException(status_code=409, detail="Create a reviewed prediction before generating a study plan")
    context = _build_support_context(db, enrollment, prediction)
    generated, used_llm = request.app.state.study_plan_service.create(context)
    plan = StudyPlan(enrollment_id=enrollment.id, created_by_user_id=user.id,
        source_prediction_id=prediction.id,
        content={"title": generated.title, "priorities": generated.priorities,
                 "actions": generated.actions, "schedule": generated.schedule,
                 "goals": generated.goals, "completed_goal_indices": []}, status="draft",
        generated_by_llm=used_llm)
    db.add(plan); db.flush()
    message = MotivationalMessage(enrollment_id=enrollment.id, study_plan_id=plan.id,
        content=generated.motivational_message, source="llm" if used_llm else "fallback")
    db.add(message); db.commit(); db.refresh(plan); db.refresh(message)
    request.app.state.email_notifications.send(
        student.user.email,
        "Your study plan is ready",
        f"A study plan is ready for your {enrollment.code_module} course. "
        "Sign in to review the suggested priorities and track your goals.",
        event="study_plan_created",
    )
    return StudyPlanResult(study_plan=plan, motivational_message=message, generated_by_llm=used_llm)


@router.put("/students/{student_id}/study-plan/{plan_id}/progress",
            response_model=StudyPlanRead)
def update_study_plan_progress(student_id: UUID, plan_id: UUID,
    body: StudyPlanProgressUpdate, user: User = Depends(get_current_user),
    db: Session = Depends(get_db)):
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only the student can update personal study-plan progress")
    student = get_authorized_student(student_id, user, db)
    plan = db.scalar(select(StudyPlan).join(Enrollment).where(
        StudyPlan.id == plan_id, Enrollment.student_id == student.id))
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found")
    goals = plan.content.get("goals", [])
    if any(index >= len(goals) for index in body.completed_goal_indices):
        raise HTTPException(status_code=422, detail="A completed goal does not exist in this plan")
    plan.content = {**plan.content,
                    "completed_goal_indices": sorted(body.completed_goal_indices)}
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/students/{student_id}/motivational-messages", response_model=list[MotivationalMessageRead])
def list_motivational_messages(student_id: UUID, user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(MotivationalMessage).join(Enrollment).where(Enrollment.student_id == student.id)
    return list(db.scalars(query.order_by(MotivationalMessage.created_at.desc()).limit(100)))


@router.post("/students/me/support-assistant", response_model=SupportAssistantAnswer)
def ask_support_assistant(body: SupportAssistantQuestion, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "student" or user.student is None:
        raise HTTPException(status_code=403, detail="The support assistant is available to student accounts")
    student = get_authorized_student(user.student.id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    prediction = db.scalar(select(Prediction).where(
        Prediction.enrollment_id == enrollment.id)
        .order_by(Prediction.created_at.desc()).limit(1))
    if prediction is None:
        raise HTTPException(status_code=409, detail="A coordinator must record a support review before using the assistant")
    context = _build_support_context(db, enrollment, prediction)
    grounded_context = _assistant_context(db, enrollment, prediction, context)
    try:
        answer = request.app.state.study_plan_service.answer_question(body.question, grounded_context)
    except Exception as exc:
        logger.warning("Grounded student support assistant failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503,
            detail="The student support assistant is unavailable; no answer was generated.") from exc
    return SupportAssistantAnswer(answer=answer, source="llm")
