from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user, require_roles
from backend.app.db.dependencies import get_db
from backend.app.models import Student, StudentAccessRequest, User
from backend.app.schemas.common import (
    AccessRequestDecision,
    CoordinatorAccessRequestRead,
    StudentAccessRequestCreate,
    StudentAccessRequestRead,
    StudentAccessRequestStatus,
)

router = APIRouter(prefix="/access-requests", tags=["student access requests"])


def _coordinator_view(record: StudentAccessRequest, student: Student) -> dict:
    return {
        "id": record.id,
        "student_id": student.id,
        "enrollment_number": record.enrollment_number,
        "status": record.status,
        "reviewed_by_user_id": record.reviewed_by_user_id,
        "created_at": record.created_at,
        "reviewed_at": record.reviewed_at,
        "student_email": student.user.email,
        "courses": [f"{item.code_module} · {item.code_presentation}"
                    for item in student.enrollments],
    }


@router.get("/me", response_model=StudentAccessRequestStatus)
def get_my_access_request(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    if user.role != "student" or user.student is None:
        raise HTTPException(status_code=404, detail="Student access request not found")
    record = db.scalar(select(StudentAccessRequest).where(
        StudentAccessRequest.student_id == user.student.id
    ))
    return {
        "access_approved": user.student.access_approved,
        "enrollment_number": user.student.enrollment_number,
        "request": record,
    }


@router.post("", response_model=StudentAccessRequestRead,
             status_code=status.HTTP_201_CREATED)
def create_access_request(body: StudentAccessRequestCreate,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    if user.role != "student" or user.student is None:
        raise HTTPException(status_code=404, detail="Student profile not found")
    student = user.student
    if body.enrollment_number != student.enrollment_number:
        raise HTTPException(status_code=422,
                            detail="Use the enrollment number assigned to your own account.")
    if student.access_approved:
        raise HTTPException(status_code=409, detail="Student access is already approved.")
    record = db.scalar(select(StudentAccessRequest).where(
        StudentAccessRequest.student_id == student.id
    ))
    if record is None:
        record = StudentAccessRequest(
            student_id=student.id,
            enrollment_number=body.enrollment_number,
            status="pending",
        )
        db.add(record)
    elif record.status == "pending":
        return record
    else:
        record.enrollment_number = body.enrollment_number
        record.status = "pending"
        record.reviewed_by_user_id = None
        record.reviewed_at = None
        record.created_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        record = db.scalar(select(StudentAccessRequest).where(
            StudentAccessRequest.student_id == student.id
        ))
        if record is None or record.status != "pending":
            raise HTTPException(status_code=409,
                                detail="Access request could not be submitted.") from exc
    db.refresh(record)
    return record


@router.get("", response_model=list[CoordinatorAccessRequestRead])
def list_access_requests(_user: User = Depends(require_roles("coordinator")),
                         db: Session = Depends(get_db)):
    records = list(db.scalars(
        select(StudentAccessRequest).where(StudentAccessRequest.status == "pending")
        .order_by(StudentAccessRequest.created_at)
    ))
    return [
        _coordinator_view(record, db.get(Student, record.student_id))
        for record in records
    ]


@router.patch("/{request_id}", response_model=CoordinatorAccessRequestRead)
def review_access_request(request_id: UUID, body: AccessRequestDecision,
                          user: User = Depends(require_roles("coordinator")),
                          db: Session = Depends(get_db)):
    record = db.scalar(select(StudentAccessRequest).where(
        StudentAccessRequest.id == request_id
    ).with_for_update())
    if record is None:
        raise HTTPException(status_code=404, detail="Access request not found")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="Access request has already been reviewed.")
    student = db.get(Student, record.student_id)
    if student is None or student.enrollment_number != record.enrollment_number:
        raise HTTPException(status_code=409,
                            detail="The student's assigned enrollment number has changed.")
    if not student.user.is_active:
        raise HTTPException(status_code=409, detail="Inactive student accounts cannot be approved.")

    record.status = body.status
    record.reviewed_by_user_id = user.id
    record.reviewed_at = datetime.now(timezone.utc)
    student.access_approved = body.status == "approved"
    db.commit()
    db.refresh(record)
    return _coordinator_view(record, student)
