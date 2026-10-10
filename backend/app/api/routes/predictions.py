from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.dependencies import get_authorized_student, get_current_user, require_roles
from backend.app.db.dependencies import get_db
from backend.app.ml.model_manager import ModelUnavailable
from backend.app.models import Enrollment, GradePrediction, Prediction, User
from backend.app.repositories.students import get_enrollment_for_student
from backend.app.schemas.common import (GradePredictionRead, PredictionCreate, PredictionRead,
    SequencePredictionCreate)
from backend.app.services.feature_assembly import (
    InsufficientHistoricalData,
    build_student_features,
    build_weekly_sequence,
)

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("/{student_id}/grade-score", response_model=GradePredictionRead,
             status_code=status.HTTP_201_CREATED)
def create_grade_score_prediction(student_id: UUID, body: PredictionCreate, request: Request,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    if enrollment.code_module not in {"CCC", "DDD"}:
        raise HTTPException(status_code=409,
            detail="Numeric final-exam score prediction is supported only for CCC and DDD in the trained data.")
    try:
        features = build_student_features(db, enrollment)
        result = request.app.state.model_manager.predict_grade_score(features)
    except InsufficientHistoricalData as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="Numeric score prediction service is unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Prediction features do not match the grade model contract") from exc
    record = GradePrediction(enrollment_id=enrollment.id, requested_by_user_id=user.id,
        model_name=result["model"], model_version=result["model_version"],
        feature_version=result["feature_version"], target_name=result["target_name"],
        prediction_day=result["prediction_day"], predicted_score=result["predicted_score"],
        observed_signals=result["observed_signals"])
    db.add(record); db.commit(); db.refresh(record)
    return record


@router.get("/{student_id}/grade-score", response_model=list[GradePredictionRead])
def list_grade_score_predictions(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(GradePrediction).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(GradePrediction.enrollment_id == enrollment_id)
    return list(db.scalars(query.order_by(GradePrediction.created_at.desc()).limit(200)))


@router.get("", response_model=list[PredictionRead])
def list_all_predictions(request: Request, limit: int = 200,
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    limit = min(max(limit, 1), 500)
    return list(db.scalars(select(Prediction).order_by(Prediction.created_at.desc()).limit(limit)))


@router.post("/{student_id}", response_model=PredictionRead, status_code=status.HTTP_201_CREATED)
def create_prediction(student_id: UUID, body: PredictionCreate, request: Request,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    try:
        features = build_student_features(db, enrollment)
        result = request.app.state.model_manager.predict(features)
    except InsufficientHistoricalData as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="Prediction service is temporarily unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Prediction features do not match the active feature contract") from exc
    record = Prediction(enrollment_id=enrollment.id, requested_by_user_id=user.id,
        model_name=result["model"], model_version=result["model_version"],
        feature_version=result["feature_version"], support_priority_score=result["support_priority_score"],
        threshold=result["threshold"], priority_band=result["priority_band"],
        observed_signals=result["observed_signals"])
    db.add(record); db.commit(); db.refresh(record)
    return record


@router.post("/{student_id}/sequence", response_model=PredictionRead,
             status_code=status.HTTP_201_CREATED)
def create_sequence_prediction(student_id: UUID, body: SequencePredictionCreate, request: Request,
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    enrollment = get_enrollment_for_student(db, student.id, body.enrollment_id)
    try:
        sequence = build_weekly_sequence(db, enrollment)
        result = request.app.state.model_manager.predict_sequence(sequence)
    except InsufficientHistoricalData as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="Sequence prediction service is temporarily unavailable") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Enrollment records do not match the active sequence contract") from exc
    record = Prediction(enrollment_id=enrollment.id, requested_by_user_id=user.id,
        model_name="lstm_weekly", model_version=result["model_version"], feature_version=result["feature_version"],
        support_priority_score=result["support_priority_score"], threshold=result["threshold"],
        priority_band=result["priority_band"], observed_signals={"weekly_sequence": sequence})
    db.add(record); db.commit(); db.refresh(record)
    return record


@router.get("/{student_id}", response_model=list[PredictionRead])
def list_student_predictions(student_id: UUID, enrollment_id: UUID | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    student = get_authorized_student(student_id, user, db)
    query = select(Prediction).join(Enrollment).where(Enrollment.student_id == student.id)
    if enrollment_id:
        get_enrollment_for_student(db, student.id, enrollment_id)
        query = query.where(Prediction.enrollment_id == enrollment_id)
    return list(db.scalars(query.order_by(Prediction.created_at.desc()).limit(200)))
