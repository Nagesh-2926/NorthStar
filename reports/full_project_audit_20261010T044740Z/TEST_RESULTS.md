# Test and Check Results: `full_project_audit_20261010T044740Z`

Every entry below was executed during this audit, and its output was checked. Commands run from the project root unless noted. "5433" means `DATABASE_URL` was set for that process only; `.env` was never edited.

## Baseline and environment

| # | Command / check | Result |
|---|---|---|
| 1 | `git status` | Not a Git repository. The SHA-256 baseline of 218 files was recorded instead. |
| 2 | `netstat -ano` (8001, 5173, 5432, 5433) | 8001: 1 uvicorn (connected to 5432); 5173: Vite; 5432 and 5433: Docker |
| 3 | `docker ps -a` | `northstar-local-db-1` (5433) healthy; `student-db-1` (5432) healthy |
| 4 | `.env` key names only (no values) | Keys match `.env.example` (SMTP keys absent, so the optional SMTP feature is disabled) |
| 5 | Read-only 5433 query (counts, alembic version) | Head `1d7c8f2a6b91`; 1 coordinator, 28 students, 27 enrollments, 44 predictions |

## Diagnosis

| # | Command / check | Result |
|---|---|---|
| 6 | `create_app()` with `DATABASE_URL=sqlite://` → OpenAPI routes | Starts; 37 operations under `/api` plus `/health` |
| 7 | `scripts/contract_check.py` | 43 frontend calls; **0 missing** on the backend |
| 8 | `scripts/repro_cors_pna.py` | No flag + PNA header → **400 "Disallowed CORS private-network"**; with flag → 200 |
| 9 | uvicorn access log from before the fix | Browser `OPTIONS /api/auth/login` and `/register` → 400 |
| 10 | Vite-served `/src/api/client.js` | `VITE_API_BASE_URL = http://127.0.0.1:8001/api` |

## Backend / ML tests

| # | Command | Result |
|---|---|---|
| 11 | `pytest -q backend/tests tests` (initial) | **150 passed**, 45 warnings (third-party deprecations only) |
| 12 | `pytest backend/tests/test_auth_and_access.py -k cors` (new tests, first run) | 2 passed, 1 failed: my over-strict header assertion, corrected (§3.3 of the report) |
| 13 | Same, after correction | **3 passed** |
| 14 | New import version assertion **before** the fix | **Failed as expected**: `('lstm_weekly', '1.2.0') != (..., 'registry-lstm-version')` |
| 15 | `pytest backend/tests/test_csv_imports.py backend/tests/test_ml_endpoints.py` after the fix | **31 passed** |
| 16 | Real `ModelManager.predict_sequence` on saved artifacts | `model_version '1.1.0'`, threshold 0.193651, score in [0, 1] |
| 17 | New JSONB test **before** the fix | **Failed as expected**: `'JSON' == 'JSONB'` |
| 18 | `pytest backend/tests/test_migrations.py` after the fix | **2 passed** |
| 19 | `pytest tests/test_with_isolated_db.py` (first run) | 5 passed, 1 failed: the connect-only port probe missed a full listen queue. Probe hardened (bind check). |
| 20 | Same, after fix | **6 passed** |
| 21 | **Final** `pytest -q backend/tests tests` | **157 passed**, 0 failed, 45 warnings (Keras/NumPy and Starlette TestClient deprecations) |

## Database / migrations (5433, read-only)

| # | Command | Result |
|---|---|---|
| 22 | `alembic current` / `alembic heads` (5433) | `1d7c8f2a6b91 (head)` / `1d7c8f2a6b91 (head)` |
| 23 | `alembic check` (5433), before the fix | **FAILED**: `modify_type grade_predictions.observed_signals JSONB → JSON` |
| 24 | `alembic check` (5433), after the fix | **"No new upgrade operations detected."** |
| 25 | `docker compose up -d --dry-run db` | Would create **new** `northstar-db-1` and volume `northstar_student-postgres` (dry run; volume list confirms nothing was created) |
| 26 | `with_isolated_db` → child `DATABASE_URL` | `127.0.0.1:5433/student_support` (credentials not printed) |
| 27 | Final read-only counts (5433) | Unchanged except +1 coordinator (the audit marker account) |

## Frontend

| # | Command | Result |
|---|---|---|
| 28 | `npx vite build --outDir <scratch>` | **Built** (1,666 modules). Warning: 543 kB chunk. `frontend/dist` not touched. |
| 29 | `npx vitest run` (twice) | **33 passed** (2 files) |
| 30 | Lint / typecheck | **Skipped**: not configured |

## Live end-to-end (HTTP, Origin `http://127.0.0.1:5173`, backend → 5433)

| # | Check | Result |
|---|---|---|
| 31 | `scripts/e2e_api.py` (46 checks, details in `e2e_api_results.json`) | **45 passed, 1 "failed"** (expected 403, got 404 on `/students/me` for a coordinator; 404 is intended, so it was a script expectation error) |
| 32 | After restart via `npm run backend`: health, PNA preflight, 401 unauthenticated, 401 bad login, frontend 200 | All as expected; one listener on 8001; DB connection to 5433 only |
| 33 | Second `npm run backend` while running | Refused: "Port 8001 is already in use" |

## Integrity

| # | Check | Result |
|---|---|---|
| 34 | `sha256sum -c baseline_hashes.sha256` | 212 of 218 unchanged. The 6 changed files are all intended (see `MODIFIED_FILES.md`); 2 new files. |
| 35 | 125 protected files (`.env`, `ml/saved_models/*`, `data/processed/*`, `data/raw/oulad/*`, `data/templates/*`, `frontend/src/*`, `frontend/dist/*`, `docs/*`, `README.md`, `docker-compose.yml`, `backend/alembic/versions/*`, `database/*`, `student_support.db`, earlier reports) | **All unchanged** |
| 36 | `.env` hash vs the first-audit pre-session snapshot | **Identical** |

## Not executed (with reason)

| Check | Reason |
|---|---|
| Real-browser UI walkthrough, console, accessibility, responsive layout | No browser automation available in this environment |
| Login with a pre-existing account | No credentials available |
| Student self-registration on the live DB | Writes `data/processed/application_enrollment_registry.json` (protected data file). Covered by the SQLite suite. |
| Creating predictions, imports, interventions, or study plans on the live DB | Would modify real student records. Covered by the SQLite suite. |
| `alembic upgrade` | Not needed (already at head); migrations were out of scope unless necessary |
| Any check against 5432 | Prohibited by the brief |
