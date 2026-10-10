from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from backend.app.models import Enrollment, Student


def get_student_detail(db: Session, student_id: UUID) -> Student | None:
    return db.scalar(select(Student).where(Student.id == student_id).options(
        selectinload(Student.user), selectinload(Student.enrollments)))


def get_enrollment_for_student(db: Session, student_id: UUID, enrollment_id: UUID) -> Enrollment:
    enrollment = db.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.student_id != student_id:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return enrollment
