# Backend database schema

The SQLAlchemy schema lives in `backend/app/models/entities.py`; Alembic migrations `082c83387a35` and `6fc7d5c29b43` establish the initial schema and enrollment feature context. PostgreSQL through `DATABASE_URL` is the supported shared/production database. SQLite is used by isolated tests and can support a single-user local smoke run. Migrations, rather than startup-time table creation, own schema changes.

## Entities and relationships

- `users`: normalized unique email, Argon2 password hash, role (`student` or `coordinator`), active state, creation time.
- `students`: one profile per student-role user; no student name or demographics are required for the support workflow.
- `enrollments`: student/module/presentation association, unique per student and course presentation; stores Phase 2 registration day, prior-attempt count, and studied credits when known.
- `assessment_schedule`: enrollment-scoped assessment key (string form of OULAD `id_assessment`), relative scheduled day, and optional weight; keys are unique within an enrollment.
- `academic_records`: enrollment-scoped scores and typed academic event details; score constrained to 0–100.
- Assessment score records store `assessment_key` and `submitted_day` in dedicated columns. A database uniqueness constraint permits only one score per assessment per enrollment.
- `engagement_records`: weekly enrollment-scoped click and active-day totals plus distinct source site IDs and activity types; one row per enrollment/week.
- `predictions`: persisted model/version/feature-version, support score, threshold, review band, observed signals, requester, and timestamp. Score/threshold constrained to [0,1].
- `behavioral_clusters`: versioned, enrollment-scoped cluster assignments and observed input values.
- `interventions`: coordinator-authored, enrollment-scoped support actions with status and optional due date.
- `study_plans`: generated or local-fallback plans, source prediction, status, and creator.
- `motivational_messages`: supportive content related to an enrollment and optional plan; source distinguishes LLM from fallback.

UUID primary keys are used for application entities. Foreign keys cascade when a student/enrollment is removed; audit authors are protected with `RESTRICT`. JSON columns hold small schema-validated snapshots, not raw OULAD CSV rows. Indexes support enrollment history and student lookup. Role, workflow status, and enrollment feature ranges have database check constraints as well as Pydantic validation.

## Local PostgreSQL setup

1. Copy `.env.example` to `.env`; replace the database password, JWT secret, and coordinator invite code with distinct random secrets. Keep `.env` out of source control.
2. Start the database with `docker compose up -d db` (or provide a PostgreSQL 16+ service yourself). `DATABASE_URL` must use the same credentials. Percent-encode reserved URL characters in passwords.
3. Install `backend/requirements-lock.txt`, then run `python -m alembic -c backend/alembic.ini upgrade head` from the project root.
4. Start the API with `python -m uvicorn backend.app.main:app --reload`.

The API readiness endpoint performs `SELECT 1`; it returns healthy only when the configured database is reachable. No table creation is performed at application startup.
