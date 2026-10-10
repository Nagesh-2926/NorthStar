"""Secret-safe fixture preflight. This module never opens a database connection."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seed_synthetic_upload_fixture as seed


def main() -> int:
    try:
        seed.verify_target(os.environ.get(seed.DATABASE_URL_ENV), None,
                           require_confirmation=False)
    except seed.UnsafeTargetError as exc:
        # UnsafeTargetError contains fixed, reviewed messages rather than URL parts.
        print(f"target check: FAIL -- {exc}")
        return 1
    except Exception:
        print("target check: FAIL -- validation unavailable; details withheld")
        return 1
    print(f"target check: PASS -- {seed.CONFIRMATION}; explicit fixture credentials present")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print("target check: FAIL -- supply credentials only through the secure local prompt")
        raise SystemExit(1)
    raise SystemExit(main())
