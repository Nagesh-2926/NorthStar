from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from backend.app.core.dependencies import get_authorized_student, get_current_user, require_roles
from backend.app.db.dependencies import get_db
from backend.app.models import (AcademicRecord, EngagementRecord, Enrollment, Student, User)
from backend.app.models import ScheduledAssessment
from backend.app.repositories.students import get_enrollment_for_student, get_student_detail
from backend.app.schemas.common import (AcademicRecordCreate, AcademicRecordRead,
    AssessmentScheduleBatch, EngagementRecordCreate, EngagementRecordRead, EnrollmentCreate, EnrollmentRead,
    ScheduledAssessmentRead,
    StudentDetail)
from ml.identity_registry import allocate_application_enrollment_number

router = APIRouter(prefix="/students", tags=["students"])
enrollment_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("/me", response_model=StudentDetail)
def my_student_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "student":
        raise HTTPException(status_code=404, detail="Student profile not found")
    student = get_student_detail(db, user.student.id) if user.student else None
    if student is None:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return student


@router.get("", response_model=list[StudentDetail])
def list_students(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                  _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    return list(db.scalars(select(Student).options(selectinload(Student.user),
        selectinload(Student.enrollments)).order_by(Student.created_at).offset(offset).limit(limit)))


@router.post("/{student_id}/enrollment-number", response_model=StudentDetail)
def assign_enrollment_number(student_id: UUID, request: Request,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    if student.enrollment_number is None:
        student.enrollment_number = allocate_application_enrollment_number(
            student.id, request.app.state.settings.application_enrollment_registry_path
        )
        db.commit()
        db.refresh(student)
    return get_student_detail(db, student.id)


@router.get("/{student_id}", response_model=StudentDetail)
def read_student(student_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    authorized = get_authorized_student(student_id, user, db)
    return get_student_detail(db, authorized.id)


@router.post("/{student_id}/enrollments", response_model=EnrollmentRead, status_code=status.HTTP_201_CREATED)
def create_enrollment(student_id: UUID, body: EnrollmentCreate,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = Enrollment(student_id=student.id, code_module=body.code_module.upper(),
        code_presentation=body.code_presentation.upper(), registration_day=body.registration_day,
        num_of_prev_attempts=body.num_of_prev_attempts, studied_credits=body.studied_credits)
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Enrollment already exists") from exc
    db.refresh(enrollment)
    return enrollment


@enrollment_router.put("/{enrollment_id}/assessment-schedule", status_code=status.HTTP_200_OK)
def replace_assessment_schedule(enrollment_id: UUID, body: AssessmentScheduleBatch,
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    enrollment = db.get(Enrollment, enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.query(ScheduledAssessment).filter(
        ScheduledAssessment.enrollment_id == enrollment_id).delete(synchronize_session=False)
    db.add_all([ScheduledAssessment(enrollment_id=enrollment_id,
        assessment_key=item.assessment_key, scheduled_day=item.scheduled_day, weight=item.weight)
        for item in body.assessments])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Assessment schedule conflicts with existing data") from exc
    return {"enrollment_id": enrollment_id, "assessment_count": len(body.assessments)}


@enrollment_router.get("/{enrollment_id}/assessment-schedule",
                       response_model=list[ScheduledAssessmentRead])
def read_assessment_schedule(enrollment_id: UUID,
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    if db.get(Enrollment, enrollment_id) is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return list(db.scalars(select(ScheduledAssessment).where(
        ScheduledAssessment.enrollment_id == enrollment_id).order_by(ScheduledAssessment.assessment_key)))


@router.get("/{student_id}/performance", response_model=list[AcademicRecordRead])
def student_performance(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(AcademicRecord).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(AcademicRecord.enrollment_id == enrollment_id)
    return list(db.scalars(query.order_by(AcademicRecord.occurred_on.desc().nullslast(),
                                          AcademicRecord.recorded_at.desc())))


@router.post("/{student_id}/performance", response_model=AcademicRecordRead,
             status_code=status.HTTP_201_CREATED)
def add_performance_record(student_id: UUID, enrollment_id: UUID, body: AcademicRecordCreate,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, enrollment_id)
    record = AcademicRecord(enrollment_id=enrollment.id, record_type=body.record_type,
        score=body.score, occurred_on=body.occurred_on, assessment_key=body.assessment_key,
        submitted_day=body.submitted_day, details=body.details)
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if body.record_type == "assessment_score":
            raise HTTPException(status_code=409, detail="Assessment score already exists") from exc
        raise HTTPException(status_code=409, detail="Academic record conflicts with existing data") from exc
    db.refresh(record)
    return record


@router.get("/{student_id}/engagement", response_model=list[EngagementRecordRead])
def student_engagement(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(EngagementRecord).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(EngagementRecord.enrollment_id == enrollment_id)
    return list(db.scalars(query.order_by(EngagementRecord.week_index)))


@router.post("/{student_id}/engagement", response_model=EngagementRecordRead,
             status_code=status.HTTP_201_CREATED)
def add_engagement_record(student_id: UUID, enrollment_id: UUID, body: EngagementRecordCreate,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    get_enrollment_for_student(db, student.id, enrollment_id)
    existing = db.scalar(select(EngagementRecord).where(
        EngagementRecord.enrollment_id == enrollment_id, EngagementRecord.week_index == body.week_index))
    if existing:
        existing.clicks = body.clicks
        existing.active_days = body.active_days
        existing.metrics = {**body.metrics, "active_site_ids": body.active_site_ids,
                            "activity_types": body.activity_types}
        db.commit(); db.refresh(existing)
        return existing
    record = EngagementRecord(enrollment_id=enrollment_id, week_index=body.week_index,
        clicks=body.clicks, active_days=body.active_days,
        metrics={**body.metrics, "active_site_ids": body.active_site_ids,
                 "activity_types": body.activity_types})
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409,
            detail="Engagement record conflicts with an existing week") from exc
    db.refresh(record)
    return record
