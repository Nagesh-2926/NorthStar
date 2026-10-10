from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.models import Enrollment, Student, User
from backend.tests.conftest import login, register
from ml.fixtures import coordinator_upload as fixture
from scripts import seed_synthetic_upload_fixture as seed

DIR = fixture.FIXTURE_DIR
SAFE_URL = "postgresql+psycopg://tester:secret@127.0.0.1:5433/student_support_fixture"
# The real layout: .env names the app database on 5432, and with_isolated_db moves it to 5433.
APP_URL_IN_ENV = "postgresql+psycopg://u:p@127.0.0.1:5432/student_support"
APP_URL_AT_RUNTIME = "postgresql+psycopg://u:p@127.0.0.1:5433/student_support"

pytestmark = pytest.mark.skipif(not (DIR / fixture.MAPPING_CSV).is_file(),
                                reason="Coordinator upload fixture has not been generated")


def isolated(_port):
    return seed.ALLOWED_CONTAINER


def coordinator(client):
    register(client, "fixture-coordinator@example.com", "coordinator", "test-coordinator-invite")
    return login(client, "fixture-coordinator@example.com")


def seed_app(app):
    session = app.state.session_factory()
    try:
        count = seed.seed_records(session, seed.load_seed_records())
        session.commit()
        return count
    finally:
        session.close()


def validate(client, headers, name):
    response = client.post("/api/imports/validate", headers=headers,
        files={"file": (name, (DIR / name).read_bytes(), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def cases():
    import csv
    with (DIR / fixture.MAPPING_CSV).open(encoding="utf-8", newline="") as stream:
        return {row["case_id"]: row for row in csv.DictReader(stream)
                if row["fixture_file"] == fixture.REJECTIONS_CSV}


def test_synthetic_numbers_are_rejected_when_no_matching_records_exist(client):
    headers = coordinator(client)
    body = validate(client, headers, fixture.VALID_CSV)
    assert body["valid"] is False
    assert body["valid_rows"] == 0
    assert len(body["unknown_rows"]) == body["total_rows"] == 23


def test_valid_fixture_is_accepted_only_after_isolated_seeding(app, client):
    headers = coordinator(client)
    assert seed_app(app) == 27
    body = validate(client, headers, fixture.VALID_CSV)
    assert body["valid"] is True, body["errors"]
    assert body["valid_rows"] == 23
    assert body["forecast_rows"] == 21
    assert body["errors"] == []


def test_rejection_fixture_rows_fail_for_their_documented_reason(app, client):
    headers = coordinator(client)
    seed_app(app)
    body = validate(client, headers, fixture.REJECTIONS_CSV)
    by_case = cases()
    row = lambda case: int(by_case[case]["fixture_row"])
    assert body["valid_rows"] == 0
    assert body["invalid_rows"] == body["total_rows"] == len(fixture.REJECTION_CASES)
    assert row("unknown_enrollment") in body["unknown_rows"]
    assert row("inactive_enrollment") in body["inactive_rows"]
    assert row("module_presentation_mismatch") in body["unmatched_rows"]
    assert row("module_presentation_mismatch") not in body["unknown_rows"]
    assert set(body["duplicate_rows"]) == {row("duplicate_enrollment_number_a"),
                                           row("duplicate_enrollment_number_b")}
    errors = {}
    for error in body["errors"]:
        errors.setdefault(error["row"], set()).add(error["field"])
    for case, mapping in by_case.items():
        assert mapping["expected_field"] in errors[row(case)], case


def test_valid_fixture_imports_through_saved_models_in_the_test_database(app, client):
    headers = coordinator(client)
    seed_app(app)
    response = client.post("/api/imports", headers=headers,
        files={"file": (fixture.VALID_CSV, (DIR / fixture.VALID_CSV).read_bytes(), "text/csv")})
    assert response.status_code == 201, response.text
    records = response.json()["records"]
    assert len(records) == 23
    assert sum(record["forecast_id"] is not None for record in records) == 21


def test_seeded_records_are_marked_synthetic_and_cannot_sign_in(app, client):
    seed_app(app)
    session = app.state.session_factory()
    try:
        users = session.scalars(select(User).where(User.email.like(f"{fixture.SYNTHETIC_EMAIL_PREFIX}%"))).all()
        assert len(users) == 27
        assert all(user.password_hash == seed.UNUSABLE_PASSWORD_HASH for user in users)
        numbers = session.scalars(select(Student.enrollment_number)).all()
        assert all(fixture.is_reserved_synthetic(number) for number in numbers)
        assert session.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.is_active.is_(False))) == 1
    finally:
        session.close()
    response = client.post("/api/auth/login", json={"email": users[0].email, "password": "SecurePass1234"})
    assert response.status_code == 401


def test_seeding_never_overwrites_existing_numbers(app):
    seed_app(app)
    session = app.state.session_factory()
    try:
        with pytest.raises(seed.SeedConflictError):
            seed.seed_records(session, seed.load_seed_records())
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Student)) == 27
    finally:
        session.close()


def test_remove_deletes_only_marked_synthetic_accounts(app, client):
    register(client, "real-student@example.com")
    seed_app(app)
    session = app.state.session_factory()
    try:
        assert seed.remove_records(session, seed.load_seed_records()) == 27
        session.commit()
        assert session.scalars(select(User.email).where(User.role == "student")).all() == ["real-student@example.com"]
    finally:
        session.close()


@pytest.mark.parametrize("url, message", [
    (None, "root .env is never used"),
    ("sqlite:///seed.db", "Only the isolated PostgreSQL"),
    ("postgresql+psycopg://u:p@127.0.0.1:5432/student_support", "student-db-1"),
    ("postgresql+psycopg://u:p@127.0.0.1/student_support", "default 5432"),
    ("postgresql+psycopg://u:p@db.example.org:5433/student_support_fixture", "unverified target"),
    ("postgresql+psycopg://u:p@127.0.0.1:5433/other_db", "unverified target"),
    ("postgresql+psycopg://u:p@127.0.0.1:5433/student_support", "active application database"),
    ("postgresql+psycopg://u:p@localhost:5433/student_support", "active application database"),
    ("postgresql+psycopg://u:p@127.0.0.1:5434/student_support_fixture", "unverified target"),
])
def test_seed_refuses_unverified_or_production_targets(url, message):
    with pytest.raises(seed.UnsafeTargetError, match=message):
        seed.verify_target(url, seed.CONFIRMATION, require_confirmation=True, container_lookup=isolated)


@pytest.mark.parametrize("query", ["?port=5432", "?host=10.0.0.9", "?dbname=other", "?service=prod",
                                   "?hostaddr=127.0.0.1", "?options=-c%20search_path%3Dx"])
def test_seed_refuses_url_query_parameters_that_could_redirect_libpq(query):
    # SQLAlchemy forwards query parameters to psycopg.connect, where e.g. port=5432
    # overrides the URL's :5433 and would reach student-db-1.
    with pytest.raises(seed.UnsafeTargetError, match="query parameters"):
        seed.verify_target(SAFE_URL + query, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={})


@pytest.mark.parametrize("variable", seed.REDIRECTING_LIBPQ_ENV)
def test_seed_refuses_while_libpq_environment_overrides_are_set(variable):
    with pytest.raises(seed.UnsafeTargetError, match=variable):
        seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={variable: "x"})


class FakePostgresSession:
    """Stand-in for a connected session; returns canned server answers."""

    def __init__(self, identifier, database=seed.ALLOWED_DATABASE, head=seed.EXPECTED_ALEMBIC_HEAD):
        self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()
        self.answers = {"pg_control_system": identifier, "current_database": database, "alembic_version": head}

    def scalar(self, statement):
        sql = str(statement)
        return next(value for key, value in self.answers.items() if key in sql)


def test_connected_database_must_be_the_isolated_containers_cluster():
    seed.verify_connected_database(FakePostgresSession("7694699641731592226"), "7694699641731592226")
    with pytest.raises(seed.UnsafeTargetError, match="did not reach"):
        seed.verify_connected_database(FakePostgresSession("1111"), "7694699641731592226")
    with pytest.raises(seed.UnsafeTargetError, match="cluster identity"):
        seed.verify_connected_database(FakePostgresSession("7694699641731592226"), None)
    with pytest.raises(seed.UnsafeTargetError, match="database name"):
        seed.verify_connected_database(FakePostgresSession("1", database="other"), "1")
    with pytest.raises(seed.UnsafeTargetError, match="expected head"):
        seed.verify_connected_database(FakePostgresSession("1", head="a58f9d632e10"), "1")
    with pytest.raises(seed.UnsafeTargetError, match="active application database"):
        seed.verify_connected_database(FakePostgresSession("1", database="student_support"), "1")


def test_connected_database_check_rejects_non_postgres(app):
    session = app.state.session_factory()
    try:
        with pytest.raises(seed.UnsafeTargetError, match="not PostgreSQL"):
            seed.verify_connected_database(session, "1")
    finally:
        session.close()


@pytest.mark.parametrize("container", [None, "student-db-1", "some-other-db"])
def test_seed_refuses_when_port_is_not_published_by_the_isolated_container(container):
    with pytest.raises(seed.UnsafeTargetError, match="not verifiably published"):
        seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=lambda _port: container)


def test_seed_writes_require_explicit_confirmation_but_dry_run_does_not():
    with pytest.raises(seed.UnsafeTargetError, match="--confirm-target"):
        seed.verify_target(SAFE_URL, None, require_confirmation=True, container_lookup=isolated)
    with pytest.raises(seed.UnsafeTargetError, match="--confirm-target"):
        seed.verify_target(SAFE_URL, "yes", require_confirmation=True, container_lookup=isolated)
    assert seed.verify_target(SAFE_URL, None, require_confirmation=False, container_lookup=isolated) == SAFE_URL
    assert seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                              container_lookup=isolated) == SAFE_URL


def test_seed_cli_refuses_without_an_explicit_test_database(monkeypatch):
    monkeypatch.delenv(seed.DATABASE_URL_ENV, raising=False)
    with pytest.raises(SystemExit, match="Refusing to run"):
        seed.main(["--apply", "--confirm-target", seed.CONFIRMATION])


def test_seed_refuses_mapping_numbers_outside_the_reserved_block(tmp_path):
    source = (DIR / fixture.MAPPING_CSV).read_text(encoding="utf-8")
    first = fixture.synthetic_number(0)
    tampered = tmp_path / "mapping.csv"
    tampered.write_text(source.replace(first, "2403031500001", 1), encoding="utf-8")
    with pytest.raises(seed.SeedConflictError, match="outside the reserved"):
        seed.load_seed_records(tampered)


def test_refusal_messages_never_echo_url_parts_that_may_hold_a_password():
    leaky = "postgresql+psycopg://tester:Secr3t@Fragment@127.0.0.1:5433/student_support"
    with pytest.raises(seed.UnsafeTargetError) as error:
        seed.verify_target(leaky, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={})
    assert "Fragment" not in str(error.value) and "Secr3t" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("line", [
    'DATABASE_URL="postgresql+psycopg://u:p@127.0.0.1:5433/student_support_fixture"',
    "export DATABASE_URL='postgresql+psycopg://u:p@127.0.0.1:5433/student_support_fixture'",
    "database_url = postgresql+psycopg://u:p@127.0.0.1:5433/student_support_fixture",
    "DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/x\nDATABASE_URL=postgresql+psycopg://u:p@localhost:5433/student_support_fixture",
    # On 5432 in .env, but with_isolated_db would run the app against it on 5433.
    "DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/student_support_fixture",
])
def test_root_env_pointing_at_the_seed_target_is_detected_in_any_dotenv_form(tmp_path, monkeypatch, line):
    (tmp_path / ".env").write_text(line + "\n", encoding="utf-8")
    monkeypatch.setattr(seed, "ROOT", tmp_path)
    with pytest.raises(seed.UnsafeTargetError, match="root .env"):
        seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={})


def test_wrapper_redirect_from_env_5432_to_runtime_5433_never_exposes_the_application_database(tmp_path, monkeypatch):
    # .env says 5432; with_isolated_db sends the running app to 5433/student_support.
    (tmp_path / ".env").write_text(f"DATABASE_URL={APP_URL_IN_ENV}\n", encoding="utf-8")
    monkeypatch.setattr(seed, "ROOT", tmp_path)
    assert (("127.0.0.1", seed.APP_RUNTIME_PORT, "student_support")
            in seed.application_targets({}))
    for confirmation, required in [(seed.CONFIRMATION, True), (None, False), ("student_support@127.0.0.1:5433", True)]:
        with pytest.raises(seed.UnsafeTargetError, match="active application database"):
            seed.verify_target(APP_URL_AT_RUNTIME, confirmation, require_confirmation=required,
                               container_lookup=isolated, environ={})
    # The wrapper also exports the rewritten URL to child processes.
    with pytest.raises(seed.UnsafeTargetError, match="active application database"):
        seed.verify_target(APP_URL_AT_RUNTIME, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={"DATABASE_URL": APP_URL_AT_RUNTIME})


def test_fixture_database_is_allowed_only_with_explicit_confirmation_under_the_real_layout(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"DATABASE_URL={APP_URL_IN_ENV}\n", encoding="utf-8")
    monkeypatch.setattr(seed, "ROOT", tmp_path)
    assert seed.CONFIRMATION == "student_support_fixture@127.0.0.1:5433"
    for confirmation in [None, "yes", "student_support@127.0.0.1:5433"]:
        with pytest.raises(seed.UnsafeTargetError, match="--confirm-target"):
            seed.verify_target(SAFE_URL, confirmation, require_confirmation=True,
                               container_lookup=isolated, environ={"DATABASE_URL": APP_URL_AT_RUNTIME})
    assert seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True, container_lookup=isolated,
                              environ={"DATABASE_URL": APP_URL_AT_RUNTIME}) == SAFE_URL


def test_seed_refuses_when_the_environment_points_the_app_at_the_fixture_database(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "ROOT", tmp_path)  # no .env
    with pytest.raises(seed.UnsafeTargetError, match="application database"):
        seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={"DATABASE_URL": SAFE_URL})


def test_unparseable_application_url_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(seed, "ROOT", tmp_path)
    with pytest.raises(seed.UnsafeTargetError, match="could not be parsed"):
        seed.verify_target(SAFE_URL, seed.CONFIRMATION, require_confirmation=True,
                           container_lookup=isolated, environ={"DATABASE_URL": "postgresql+psycopg://u:p@[::1"})


def test_any_existing_reserved_number_blocks_seeding_even_if_unseeded(app):
    # 2403031590023 is the unseeded unknown_enrollment case; if it exists the fixture is invalid.
    unknown = next(row for row in cases().values() if row["case_id"] == "unknown_enrollment")
    session = app.state.session_factory()
    try:
        session.add(Student(user=User(email="other@example.com", password_hash="x", role="student"),
                            enrollment_number=unknown["synthetic_enrollment_number"]))
        session.commit()
        records = seed.load_seed_records()
        assert unknown["synthetic_enrollment_number"] in seed.find_conflicts(session, records)
        with pytest.raises(seed.SeedConflictError):
            seed.seed_records(session, records)
    finally:
        session.rollback()
        session.close()


def test_remove_refuses_when_coordinator_work_references_synthetic_enrollments(app, client):
    headers = coordinator(client)
    seed_app(app)
    response = client.post("/api/imports", headers=headers,
        files={"file": (fixture.VALID_CSV, (DIR / fixture.VALID_CSV).read_bytes(), "text/csv")})
    assert response.status_code == 201, response.text
    session = app.state.session_factory()
    try:
        with pytest.raises(seed.SeedConflictError, match="predictions=44"):
            seed.remove_records(session, seed.load_seed_records())
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Student)) == 27
    finally:
        session.close()
