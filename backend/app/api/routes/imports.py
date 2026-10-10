"""Coordinator CSV template, validation, and inference import endpoints."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.dependencies import require_roles
from backend.app.db.dependencies import get_db
from backend.app.ml.model_manager import ModelUnavailable
from backend.app.models import (BehavioralCluster, DatasetImport, Enrollment,
    ImportedFeatureSnapshot, Prediction, Student, User)
from backend.app.services.csv_import import (
    MAX_UPLOAD_BYTES,
    parse_inference_csv_report,
)
from ml.clustering.features import ENGAGEMENT

router = APIRouter(prefix="/imports", tags=["coordinator CSV imports"])
TEMPLATE_PATH = Path(__file__).resolve().parents[4] / "data" / "templates" / "student_upload_template.csv"


def _match_enrollments(rows: list[dict[str, Any]], db: Session) -> tuple[
        dict[int, Enrollment], list[dict[str, Any]], dict[str, list[Any]]]:
    keys = {(row["enrollment_number"], row["features"]["code_module"],
             row["features"]["code_presentation"]) for row in rows}
    found = db.execute(
        select(Student.enrollment_number, User.is_active, Enrollment)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .join(User, User.id == Student.user_id)
        .where(
            Student.enrollment_number.in_({key[0] for key in keys}),
            User.role == "student",
        )
    ).all()
    by_key = {}
    all_numbers = set()
    inactive_keys = set()
    for number, user_is_active, enrollment in found:
        key = (number, enrollment.code_module, enrollment.code_presentation)
        all_numbers.add(number)
        if enrollment.is_active and user_is_active:
            by_key[key] = enrollment
        else:
            inactive_keys.add(key)

    categorized = {
        "unmatched_rows": [],
        "inactive_rows": [],
        "unknown_rows": [],
        "unmatched_enrollment_numbers": [],
        "inactive_enrollment_numbers": [],
        "unknown_enrollment_numbers": [],
    }
    identity_errors = []
    matched_rows = []
    for row in rows:
        key = (row["enrollment_number"], row["features"]["code_module"],
               row["features"]["code_presentation"])
        if key in by_key:
            matched_rows.append(row)
            continue
        number = row["enrollment_number"]
        categorized["unmatched_rows"].append(row["row"])
        if key in inactive_keys:
            field = "inactive_rows"
            message = "The matching student-course enrollment is inactive or the student account is disabled."
        elif number in all_numbers:
            field = "unmatched_rows"
            message = "This enrollment number has no active enrollment for the supplied module and presentation."
        else:
            field = "unknown_rows"
            message = "This enrollment number is not associated with an application student."
        if field != "unmatched_rows":
            categorized[field].append(row["row"])
        categorized[field.replace("_rows", "_enrollment_numbers")].append(number)
        identity_errors.append({"row": row["row"], "field": "enrollment_number",
                                "enrollment_number": number, "message": message})

    inconsistent = []
    base_fields = ("registration_day", "num_of_prev_attempts", "studied_credits")
    for row in matched_rows:
        key = (row["enrollment_number"], row["features"]["code_module"],
               row["features"]["code_presentation"])
        enrollment = by_key[key]
        if any(row["features"][name] != getattr(enrollment, name) for name in base_fields):
            inconsistent.append({
                "row": row["row"],
                "field": "enrollment_features",
                "message": "Registration day, prior attempts, and studied credits must match the stored enrollment.",
            })
    invalid_numbers = {item["row"] for item in inconsistent}
    matched = {
        row["row"]: by_key[(row["enrollment_number"], row["features"]["code_module"],
                            row["features"]["code_presentation"])]
        for row in matched_rows if row["row"] not in invalid_numbers
    }
    for values in categorized.values():
        values[:] = sorted(set(values))
    return matched, identity_errors + inconsistent, categorized


def _existing_import_response(dataset_import: DatasetImport, db: Session,
                              errors: list[dict[str, Any]],
                              categorized: dict[str, list[Any]]) -> JSONResponse:
    snapshots = list(db.scalars(
        select(ImportedFeatureSnapshot)
        .where(ImportedFeatureSnapshot.dataset_import_id == dataset_import.id)
        .order_by(ImportedFeatureSnapshot.source_row)
    ))
    return JSONResponse(status_code=200, content={
        "import_id": str(dataset_import.id),
        "already_imported": True,
        "total_rows": dataset_import.row_count,
        "row_count": dataset_import.row_count,
        "valid_rows": len(snapshots),
        "invalid_rows": max(0, dataset_import.row_count - len(snapshots)),
        "errors": errors,
        **categorized,
        "records": [{
            "source_row": item.source_row,
            "enrollment_id": str(item.enrollment_id),
            "prediction_id": str(item.prediction_id),
            "cluster_record_id": str(item.cluster_id),
            "cluster_id": db.get(BehavioralCluster, item.cluster_id).cluster_id,
            "forecast_id": str(item.forecast_prediction_id) if item.forecast_prediction_id else None,
        } for item in snapshots],
        "note": "This exact file was already imported; existing generated records were returned without rerunning models.",
    })


@router.get("/template", response_class=FileResponse)
def download_template(_user: User = Depends(require_roles("coordinator"))):
    if not TEMPLATE_PATH.is_file():
        raise HTTPException(status_code=503, detail="CSV template is not available")
    return FileResponse(TEMPLATE_PATH, media_type="text/csv",
                        filename="student_upload_template.csv")


@router.post("/validate")
async def validate_upload(file: UploadFile = File(...),
    _user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20 MB upload limit.")
    rows, errors, total_rows = parse_inference_csv_report(content)
    enrollments, identity_errors, categorized = _match_enrollments(rows, db) if rows else ({}, [], {
        "unmatched_rows": [], "inactive_rows": [], "unknown_rows": [],
        "unmatched_enrollment_numbers": [], "inactive_enrollment_numbers": [],
        "unknown_enrollment_numbers": [],
    })
    errors.extend(identity_errors)
    valid_count = len(enrollments)
    return {"valid": valid_count > 0 and valid_count == total_rows, "total_rows": total_rows,
            "row_count": total_rows, "valid_rows": valid_count,
            "invalid_rows": max(0, total_rows - valid_count), "errors": errors,
            **categorized,
            "duplicate_rows": sorted({item["row"] for item in errors if item["field"] == "enrollment_number" and "Duplicate" in item["message"]}),
            "forecast_rows": sum(row["weekly_sequence"] is not None for row in rows if row["row"] in enrollments),
            "note": "Validation only; no records were written. Eligible rows would be stored as aggregate snapshots, without creating assessment or daily engagement records."}


@router.post("", status_code=status.HTTP_201_CREATED)
async def import_upload(request: Request, file: UploadFile = File(...),
    user: User = Depends(require_roles("coordinator")), db: Session = Depends(get_db)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20 MB upload limit.")
    rows, validation_errors, total_rows = parse_inference_csv_report(content)
    enrollments, identity_errors, categorized = _match_enrollments(rows, db) if rows else ({}, [], {
        "unmatched_rows": [], "inactive_rows": [], "unknown_rows": [],
        "unmatched_enrollment_numbers": [], "inactive_enrollment_numbers": [],
        "unknown_enrollment_numbers": [],
    })
    validation_errors.extend(identity_errors)
    import_rows = [row for row in rows if row["row"] in enrollments]
    if not import_rows:
        raise HTTPException(status_code=422, detail={
            "total_rows": total_rows, "valid_rows": 0, "invalid_rows": total_rows,
            "errors": validation_errors, **categorized,
            "message": "No valid active enrollment rows were found; nothing was imported.",
        })
    digest = hashlib.sha256(content).hexdigest()
    previous_import = db.scalar(select(DatasetImport).where(DatasetImport.sha256 == digest))
    if previous_import is not None:
        return _existing_import_response(previous_import, db, validation_errors, categorized)

    model_outputs: list[dict[str, Any]] = []
    try:
        for row in import_rows:
            prediction = request.app.state.model_manager.predict(row["features"])
            forecast = (request.app.state.model_manager.predict_sequence(row["weekly_sequence"])
                        if row["weekly_sequence"] is not None else None)
            model_outputs.append({"prediction": prediction, "forecast": forecast})
        cluster_features = [
            {name: row["features"][name] for name in ENGAGEMENT}
            for row in import_rows
        ]
        clusters = request.app.state.model_manager.cluster_many(cluster_features)
        for output, cluster in zip(model_outputs, clusters, strict=True):
            output["cluster"] = cluster
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="One or more required inference models are unavailable; no records were imported.") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Uploaded features do not match the active model contract.") from exc

    safe_filename = Path(file.filename or "upload.csv").name[:255] or "upload.csv"
    dataset_import = DatasetImport(
        uploaded_by_user_id=user.id,
        original_filename=safe_filename,
        sha256=digest,
        row_count=total_rows,
    )
    try:
        db.add(dataset_import)
        db.flush()
        generated: list[dict[str, Any]] = []
        for row, output in zip(import_rows, model_outputs, strict=True):
            enrollment = enrollments[row["row"]]
            prediction_result = output["prediction"]
            prediction = Prediction(
                enrollment_id=enrollment.id,
                requested_by_user_id=user.id,
                model_name=prediction_result["model"],
                model_version=prediction_result["model_version"],
                feature_version=prediction_result["feature_version"],
                support_priority_score=prediction_result["support_priority_score"],
                threshold=prediction_result["threshold"],
                priority_band=prediction_result["priority_band"],
                observed_signals=prediction_result["observed_signals"],
            )
            cluster_result = output["cluster"]
            cluster = BehavioralCluster(
                enrollment_id=enrollment.id,
                requested_by_user_id=user.id,
                cluster_id=cluster_result["cluster_id"],
                model_version=cluster_result["model_version"],
                feature_version=cluster_result["feature_version"],
                observed_signals=cluster_result["features"],
            )
            db.add_all([prediction, cluster])
            db.flush()
            forecast_record = None
            if output["forecast"] is not None:
                forecast_result = output["forecast"]
                forecast_record = Prediction(
                    enrollment_id=enrollment.id,
                    requested_by_user_id=user.id,
                    model_name="lstm_weekly",
                    model_version=forecast_result["model_version"],
                    feature_version=forecast_result["feature_version"],
                    support_priority_score=forecast_result["support_priority_score"],
                    threshold=forecast_result["threshold"],
                    priority_band=forecast_result["priority_band"],
                    observed_signals={"weekly_sequence": row["weekly_sequence"]},
                )
                db.add(forecast_record)
                db.flush()
            db.add(ImportedFeatureSnapshot(
                dataset_import_id=dataset_import.id,
                enrollment_id=enrollment.id,
                source_row=row["row"],
                features=row["features"],
                weekly_sequence=row["weekly_sequence"],
                prediction_id=prediction.id,
                forecast_prediction_id=forecast_record.id if forecast_record else None,
                cluster_id=cluster.id,
            ))
            generated.append({
                "source_row": row["row"],
                "enrollment_id": str(enrollment.id),
                "prediction_id": str(prediction.id),
                "cluster_record_id": str(cluster.id),
                "cluster_id": cluster.cluster_id,
                "forecast_id": str(forecast_record.id) if forecast_record else None,
            })
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        previous_import = db.scalar(select(DatasetImport).where(DatasetImport.sha256 == digest))
        if previous_import is not None:
            return _existing_import_response(previous_import, db, validation_errors, categorized)
        raise exc
    except Exception:
        db.rollback()
        raise

    return {
        "import_id": str(dataset_import.id),
        "already_imported": False,
        "total_rows": total_rows,
        "row_count": total_rows,
        "valid_rows": len(import_rows),
        "invalid_rows": max(0, total_rows - len(import_rows)),
        "errors": validation_errors,
        **categorized,
        "duplicate_rows": sorted({item["row"] for item in validation_errors if item["field"] == "enrollment_number" and "Duplicate" in item["message"]}),
        "records": generated,
        "note": "Imported features are retained as aggregate snapshots. No assessment, day-level activity, attendance, or outcome records were fabricated.",
    }
