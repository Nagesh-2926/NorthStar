from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.dependencies import get_authorized_student, get_current_user, require_roles
from backend.app.db.dependencies import get_db
from backend.app.ml.model_manager import ModelUnavailable
from backend.app.models import BehavioralCluster, Enrollment, User
from backend.app.repositories.students import get_enrollment_for_student
from backend.app.schemas.common import ClusterCreate, ClusterRead
from backend.app.services.feature_assembly import InsufficientHistoricalData, build_engagement_features

router = APIRouter(prefix="/clusters", tags=["behavioral clusters"])
student_router = APIRouter(tags=["behavioral clusters"])


@router.get("", response_model=list[ClusterRead])
def list_clusters(_user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    return list(db.scalars(select(BehavioralCluster).order_by(BehavioralCluster.assigned_at.desc()).limit(500)))


@router.post("/{student_id}", response_model=ClusterRead, status_code=status.HTTP_201_CREATED)
def assign_cluster(student_id: UUID, body: ClusterCreate, request: Request,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    try:
        features = build_engagement_features(db, enrollment)
        result = request.app.state.model_manager.cluster(features)
    except InsufficientHistoricalData as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="Cluster service is temporarily unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Cluster features do not match the active feature contract") from exc
    record = BehavioralCluster(enrollment_id=enrollment.id, requested_by_user_id=user.id,
        cluster_id=result["cluster_id"], model_version=result["model_version"],
        feature_version=result["feature_version"], observed_signals=result["features"])
    db.add(record); db.commit(); db.refresh(record)
    return record


@student_router.get("/students/{student_id}/cluster", response_model=ClusterRead)
def student_cluster(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(BehavioralCluster).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(BehavioralCluster.enrollment_id == enrollment_id)
    record = db.scalar(query.order_by(BehavioralCluster.assigned_at.desc()).limit(1))
    if record is None:
        raise HTTPException(status_code=404, detail="Cluster assignment not found")
    return record
