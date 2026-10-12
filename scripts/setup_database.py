"""Apply the project's Alembic migrations to DATABASE_URL from the environment or .env."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    # Settings reads DATABASE_URL from the environment or root .env and validates the
    # required backend configuration without printing credential-bearing values.
    from backend.app.core.config import Settings

    settings = Settings()
    url = make_url(settings.database_url)
    if not url.drivername.startswith("postgresql"):
        print("DATABASE_URL must point to PostgreSQL for this setup command.", file=sys.stderr)
        return 2
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")

    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    command = [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"]
    try:
        return subprocess.call(command, cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("Could not start Alembic; check the Python environment.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
