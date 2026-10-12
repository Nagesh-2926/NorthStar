"""Apply pending schema migrations, then start the local FastAPI server."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.with_isolated_db import port_in_use

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if port_in_use(8001):
        print("Port 8001 is already in use; stop the existing backend first.", file=sys.stderr)
        return 3
    migration = subprocess.call([sys.executable, "-m", "scripts.setup_database"], cwd=ROOT)
    if migration != 0:
        return migration
    try:
        return subprocess.call(
            [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--reload",
             "--host", "127.0.0.1", "--port", "8001"],
            cwd=ROOT,
        )
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("Could not start Uvicorn; check the Python environment.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
