"""Guards of scripts/reset_app_user_password.py, exercised without any database connection."""
import pytest

from scripts import reset_app_user_password as reset
from scripts.verify_fixture_identity import EXPECTED_CLUSTER_IDENTIFIER

LEGACY = "postgresql+psycopg://app_user:Secret1234567@127.0.0.1:5432/student_support"


def _env_file(tmp_path, url):
    path = tmp_path / ".env"
    path.write_text(f"DATABASE_URL={url}\n", encoding="utf-8")
    return path


def test_legacy_env_url_is_rewritten_to_the_isolated_port(tmp_path):
    url = reset.target_url(environ={}, env_file=_env_file(tmp_path, LEGACY))
    assert url.endswith("@127.0.0.1:5433/student_support") and ":5432" not in url


@pytest.mark.parametrize("name", ["DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGSERVICE"])
def test_environment_overrides_are_refused(tmp_path, name):
    with pytest.raises(reset.UnsafeTarget, match=name):
        reset.target_url(environ={name: "x"}, env_file=_env_file(tmp_path, LEGACY))


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:p@127.0.0.1:5432/student_support_fixture",
    "postgresql+psycopg://u:p@db.example.com:5432/student_support",
    "postgresql+psycopg://u:p@127.0.0.1/student_support",
])
def test_unexpected_targets_are_refused_without_echoing_credentials(tmp_path, url):
    with pytest.raises(reset.UnsafeTarget) as caught:
        reset.target_url(environ={}, env_file=_env_file(tmp_path, url))
    assert "u:p" not in str(caught.value)


def test_container_must_publish_the_isolated_port_with_the_pinned_identity():
    with pytest.raises(reset.UnsafeTarget):
        reset.verify_container(lambda port: "student-db-1", lambda name: EXPECTED_CLUSTER_IDENTIFIER)
    with pytest.raises(reset.UnsafeTarget):
        reset.verify_container(lambda port: "northstar-local-db-1", lambda name: "1")
    assert reset.verify_container(lambda port: "northstar-local-db-1",
                                  lambda name: EXPECTED_CLUSTER_IDENTIFIER) == EXPECTED_CLUSTER_IDENTIFIER


class FakeSession:
    def __init__(self, identifier, database, head):
        self.answers = iter([identifier, database, head])
        self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

    def scalar(self, _statement):
        return next(self.answers)


@pytest.mark.parametrize("identifier,database,head", [
    ("1", "student_support", reset.seed.EXPECTED_ALEMBIC_HEAD),
    (EXPECTED_CLUSTER_IDENTIFIER, "student_support_fixture", reset.seed.EXPECTED_ALEMBIC_HEAD),
    (EXPECTED_CLUSTER_IDENTIFIER, "student_support", "082c83387a35"),
])
def test_connected_database_must_match_cluster_name_and_head(identifier, database, head):
    with pytest.raises(reset.UnsafeTarget):
        reset.verify_connected(FakeSession(identifier, database, head), EXPECTED_CLUSTER_IDENTIFIER)


def test_verified_connection_passes():
    session = FakeSession(EXPECTED_CLUSTER_IDENTIFIER, "student_support", reset.seed.EXPECTED_ALEMBIC_HEAD)
    reset.verify_connected(session, EXPECTED_CLUSTER_IDENTIFIER)


@pytest.mark.parametrize("password,confirmation", [
    ("Short1a", "Short1a"), ("alllowercase123", "alllowercase123"),
    ("ValidPassword123", "ValidPassword124"),
])
def test_weak_or_mismatched_passwords_are_rejected(password, confirmation):
    with pytest.raises(ValueError):
        reset.check_new_password(password, confirmation)


def test_apply_requires_the_exact_target_confirmation(monkeypatch):
    monkeypatch.setattr(reset, "target_url", lambda: pytest.fail("must not resolve a target"))
    with pytest.raises(SystemExit):
        reset.main(["--email", "a@example.com", "--apply"])
    with pytest.raises(SystemExit):
        reset.main(["--email", "a@example.com", "--apply", "--confirm-target", "student_support@127.0.0.1:5432"])
