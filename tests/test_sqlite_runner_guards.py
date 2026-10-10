"""Authorizer checks use direct callbacks; no SQLite connection or attachment."""
import sqlite3

import pytest

from scripts.run_sqlite_tests import sqlite_authorizer


@pytest.mark.parametrize("target", [":memory:", "unused-test-copy.db", "student_support.db"])
def test_authorizer_rejects_attach_action_including_vacuum_into(target):
    # SQLite uses SQLITE_ATTACH for ATTACH and VACUUM INTO. Even extra temporary
    # destinations are forbidden: every permitted database starts in the wrapper.
    assert sqlite_authorizer(sqlite3.SQLITE_ATTACH, target, None, "main", None) == sqlite3.SQLITE_DENY


@pytest.mark.parametrize("name", ["load_extension", "LOAD_EXTENSION"])
def test_authorizer_rejects_sql_extension_loading(name):
    assert sqlite_authorizer(sqlite3.SQLITE_FUNCTION, None, name, None, None) == sqlite3.SQLITE_DENY


@pytest.mark.parametrize("action,first,second", [
    (sqlite3.SQLITE_READ, "sqlite_master", "name"),
    (sqlite3.SQLITE_FUNCTION, None, "abs"),
    (sqlite3.SQLITE_SELECT, None, None),
])
def test_authorizer_allows_normal_queries(action, first, second):
    assert sqlite_authorizer(action, first, second, "main", None) == sqlite3.SQLITE_OK
