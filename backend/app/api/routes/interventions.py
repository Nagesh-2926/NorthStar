from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.dependencies import get_current_user, require_roles
from backend.app.db.dependencies import get_db
from backend.app.models import Enrollment, Intervention, User
from backend.app.repositories.students import get_enrollment_for_student
from backend.app.schemas.common import InterventionCreate, InterventionRead, InterventionUpdate

router = APIRouter(prefix="/interventions", tags=["interventions"])


@router.post("", response_model=InterventionRead, status_code=status.HTTP_201_CREATED)
def create_intervention(body: InterventionCreate, request: Request,
                        user: User = Depends(require_roles("coordinator")),
                        db: Session = Depends(get_db)):
    enrollment = db.get(Enrollment, body.enrollment_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    record = Intervention(enrollment_id=enrollment.id, created_by_user_id=user.id,
        title=body.title.strip(), notes=body.notes, due_date=body.due_date)
    db.add(record); db.commit(); db.refresh(record)
    request.app.state.email_notifications.send(
        enrollment.student.user.email,
        "A new student support intervention is available",
        f"A coordinator created a support intervention for your {enrollment.code_module} course. "
        "Sign in to view the details and next steps.",
        event="intervention_created",
    )
    return record


@router.get("", response_model=list[InterventionRead])
def list_interventions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Intervention)
    if user.role == "student":
        if user.student is None:
            return []
        query = query.join(Enrollment).where(Enrollment.student_id == user.student.id)
    return list(db.scalars(query.order_by(Intervention.created_at.desc()).limit(500)))


@router.put("/{intervention_id}", response_model=InterventionRead)
def update_intervention(intervention_id: UUID, body: InterventionUpdate, request: Request,
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    record = db.get(Intervention, intervention_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Intervention not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(record, key, value.value if hasattr(value, "value") else value)
    db.commit(); db.refresh(record)
    if "status" in body.model_fields_set:
        enrollment = db.get(Enrollment, record.enrollment_id)
        request.app.state.email_notifications.send(
            enrollment.student.user.email,
            "Your student support intervention was updated",
            f"The status of a support intervention for your {enrollment.code_module} course "
            f"is now {record.status}. Sign in to view the details.",
            event="intervention_status_updated",
        )
    return record
