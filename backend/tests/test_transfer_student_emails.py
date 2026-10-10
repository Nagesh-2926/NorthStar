from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.models import (
    AcademicRecord,
    Enrollment,
    Intervention,
    Prediction,
    Student,
    User,
)
from scripts.transfer_student_emails import (
    EmailConflictError,
    apply_email_updates,
    plan_email_updates,
)


@pytest.fixture
def email_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transfer-emails.db'}")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def add_student(session, email, enrollment_number):
    user = User(
        email=email,
        password_hash="unchanged-test-hash",
        role="student",
        is_active=False,
    )
    student = Student(
        user=user,
        enrollment_number=enrollment_number,
        access_approved=False,
    )
    session.add_all([user, student])
    session.flush()
    return user, student


def test_sequence_is_unique_and_uses_stable_student_order(email_db):
    with Session(email_db) as session:
        add_student(
            session,
            "transfer-disabled-b@example.invalid",
            "2403031500002",
        )
        add_student(
            session,
            "transfer-disabled-a@example.invalid",
            "2403031500001",
        )
        add_student(session, "transfer-disabled-null@example.invalid", None)
        session.commit()

        assignments = plan_email_updates(session)

        assert [item.target_email for item in assignments] == [
            "2403031500000@paruluniversity.ac.in",
            "2403031500001@paruluniversity.ac.in",
            "2403031500002@paruluniversity.ac.in",
        ]
        assert assignments[0].source_email == "transfer-disabled-a@example.invalid"
        assert assignments[-1].source_email == "transfer-disabled-null@example.invalid"
        assert len({item.target_email for item in assignments}) == len(assignments)


def test_conflict_aborts_before_any_email_is_changed(email_db):
    with Session(email_db) as session:
        student_user, _ = add_student(
            session,
            "transfer-disabled-a@example.invalid",
            "2403031500001",
        )
        legitimate_user = User(
            email="2403031500000@paruluniversity.ac.in",
            password_hash="unchanged-test-hash",
            role="coordinator",
            is_active=True,
        )
        session.add(legitimate_user)
        session.commit()

        with pytest.raises(EmailConflictError, match="2403031500000@paruluniversity.ac.in"):
            plan_email_updates(session)

        session.rollback()
        assert session.get(User, student_user.id).email == (
            "transfer-disabled-a@example.invalid"
        )
        assert session.get(User, legitimate_user.id).email == (
            "2403031500000@paruluniversity.ac.in"
        )


def test_apply_is_retry_safe_and_preserves_related_records(email_db):
    coordinator = User(
        email="transfer-disabled-coordinator@example.invalid",
        password_hash="unchanged-test-hash",
        role="coordinator",
        is_active=True,
    )
    with Session(email_db) as session:
        user, student = add_student(
            session,
            "transfer-disabled-a@example.invalid",
            "2403031500001",
        )
        enrollment = Enrollment(
            student_id=student.id,
            code_module="AAA",
            code_presentation="2013J",
        )
        session.add_all([coordinator, enrollment])
        session.flush()
        academic = AcademicRecord(
            enrollment_id=enrollment.id,
            record_type="final_grade",
            score=82,
        )
        prediction = Prediction(
            enrollment_id=enrollment.id,
            requested_by_user_id=coordinator.id,
            model_name="test-model",
            model_version="1",
            feature_version="1",
            support_priority_score=0.2,
            threshold=0.5,
            priority_band="no_flag_from_model",
            observed_signals={},
        )
        intervention = Intervention(
            enrollment_id=enrollment.id,
            created_by_user_id=coordinator.id,
            title="Check in",
            notes="Test record",
        )
        session.add_all([academic, prediction, intervention])
        session.commit()

        original_ids = {
            "user": user.id,
            "student": student.id,
            "enrollment": enrollment.id,
            "academic": academic.id,
            "prediction": prediction.id,
            "intervention": intervention.id,
        }
        assignments = plan_email_updates(session)
        updated = apply_email_updates(session, assignments)
        session.commit()

        assert updated == 1
        assert session.get(User, user.id).email == "2403031500000@paruluniversity.ac.in"
        assert session.get(User, user.id).password_hash == "unchanged-test-hash"
        assert session.get(User, user.id).is_active is False
        assert session.get(User, coordinator.id).email == (
            "transfer-disabled-coordinator@example.invalid"
        )
        assert session.get(Student, student.id).user_id == original_ids["user"]
        assert session.get(Enrollment, enrollment.id).student_id == original_ids["student"]
        assert session.get(AcademicRecord, academic.id).enrollment_id == original_ids["enrollment"]
        assert session.get(Prediction, prediction.id).enrollment_id == original_ids["enrollment"]
        assert session.get(Intervention, intervention.id).enrollment_id == original_ids["enrollment"]
        assert session.scalar(select(func.count()).select_from(Student)) == 1
        assert session.scalar(select(func.count()).select_from(Enrollment)) == 1
        assert session.scalar(select(func.count()).select_from(AcademicRecord)) == 1
        assert session.scalar(select(func.count()).select_from(Prediction)) == 1
        assert session.scalar(select(func.count()).select_from(Intervention)) == 1

        assert plan_email_updates(session) == []
