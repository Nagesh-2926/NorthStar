"""Developer launchers (VS Code tasks, npm scripts) must not reach the legacy database.

The root .env DATABASE_URL targets the legacy port 5432; only scripts.with_isolated_db
rewrites it to the isolated port, so every database-using launcher must go through it.
"""
import json
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_ENTRY_POINTS = {"uvicorn", "alembic"}
WRAPPER = ["-m", "scripts.with_isolated_db"]
REDIRECTING_ENV = {"DATABASE_URL", "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE"}


def _tasks():
    return json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))["tasks"]


def _npm_commands():
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    return {name: shlex.split(command.replace("\\", "/")) for name, command in scripts.items()}


def _assert_wrapped(argv: list[str], label: str):
    """argv[0] is the interpreter; DB entry points may only appear after the wrapper's '--'."""
    uses_db = [i for i, token in enumerate(argv) if token in DB_ENTRY_POINTS]
    if not uses_db:
        return
    assert argv[1:3] == WRAPPER, f"{label} starts {argv[uses_db[0]]} without scripts.with_isolated_db"
    separator = argv.index("--")
    assert separator < min(uses_db), f"{label} runs a database entry point outside the wrapper"
    wrapper_options = argv[3:separator]
    assert "--db-port" not in wrapper_options, f"{label} overrides the isolated database port"


@pytest.mark.parametrize("task", _tasks(), ids=lambda task: task["label"])
def test_vscode_task_cannot_bypass_the_isolated_database_wrapper(task):
    argv = [task["command"], *task.get("args", [])]
    _assert_wrapped(argv, task["label"])
    assert not any("5432" in token for token in argv), f"{task['label']} names the legacy port"
    env = task.get("options", {}).get("env", {})
    assert not REDIRECTING_ENV & set(env), f"{task['label']} sets a database-redirecting variable"


def test_database_tasks_are_all_wrapped():
    labels = {task["label"] for task in _tasks()
              if DB_ENTRY_POINTS & set(task.get("args", []))}
    assert labels == {"Backend: Start FastAPI", "Backend: Apply migrations"}
    for task in _tasks():
        if task["label"] in labels:
            assert task["args"][:2] == WRAPPER


def test_pytest_task_stays_unwrapped_so_tests_default_to_sqlite():
    # backend/tests/conftest.py only setdefault()s DATABASE_URL=sqlite://; wrapping pytest
    # would inject the isolated PostgreSQL URL and point tests at the application database.
    for task in _tasks():
        if "pytest" in task.get("args", []):
            assert "scripts.with_isolated_db" not in task["args"]


@pytest.mark.parametrize("name", ["backend", "migrate"])
def test_npm_database_scripts_use_the_wrapper(name):
    _assert_wrapped(_npm_commands()[name], f"npm run {name}")
