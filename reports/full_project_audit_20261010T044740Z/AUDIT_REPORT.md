# NorthStar Full-Project Audit and Repair

| | |
|---|---|
| Audit ID | `full_project_audit_20261010T044740Z` |
| Date (UTC) | 2026-10-10 |
| Scope | FastAPI backend, React/Vite frontend, PostgreSQL / Alembic, local infrastructure scripts, ML serving integration (protected) |
| Companion files | `TEST_RESULTS.md` (every command and result), `MODIFIED_FILES.md`, `e2e_api_results.json`, `baseline_hashes.sha256`, `scripts/` (re-runnable checks) |

**Evidence labels**

| Label | Meaning |
|---|---|
| **[Verified]** | Executed and checked in this audit |
| **[Observed]** | Read from source, logs, or configuration |
| **[Not verified]** | Could not be executed; the reason is stated |

---

## 1. Executive summary

**The visible error.** The login page reported "The API at http://127.0.0.1:8001/api could not be reached". The backend was in fact running. There were two causes.

1. **Root cause (P1): CORS private-network preflight rejected.**
   - Chrome adds `Access-Control-Request-Private-Network: true` to the CORS preflight for `POST /api/auth/login` and `/register`.
   - The backend's `CORSMiddleware` did not set `allow_private_network`, so Starlette answered `400 Disallowed CORS private-network`.
   - Axios received no usable response and showed the generic "could not be reached" message.
   - Reproduced in isolation, and in the backend log (§3.1).
   - Fixed with one argument; two regression tests added.
2. **Contributing cause (P1): several backends sharing port 8001.**
   - Three uvicorn processes were listening on 127.0.0.1:8001 at once. Windows let them share the port.
   - Some had been started from `.env`, which points at the legacy 5432 database.
   - Requests landed on an arbitrary process.
   - Fixed by a launcher that refuses to start when the port is busy.

**Other defects fixed**

| ID | Defect | Fix |
|---|---|---|
| P0 | Local scripts (`npm run backend/dev/migrate/db`) and the README Docker command target the **legacy** 5432 database, or would create a new empty container | `.env` was left untouched. Scripts now go through `scripts/with_isolated_db.py`, which targets 5433 and refuses 5432. `db` starts the existing `northstar-local-db-1`. |
| P2 | CSV-import LSTM forecasts were stored with a hard-coded `model_version` ("1.2.0") instead of the version of the model that scored them (registry `lstm_weekly` = 1.1.0) | Uses the scoring result's version; regression test added |
| P3 | ORM/migration drift: `grade_predictions.observed_signals` is JSONB in PostgreSQL but JSON in the model, so `alembic check` failed | Model now matches the migration; `alembic check` is clean |

**Verification [Verified]**
- 157 backend/ML tests pass, and 33 frontend tests pass.
- The production build succeeds.
- `alembic check` against 5433 reports no drift.
- 46 live HTTP checks were run with the browser's origin: 45 passed. The one "failure" was an incorrect expectation in my script (§4.4).
- The frontend↔backend route contract matches for all 43 calls.

**Not verified**
- A real-browser click-through, because no browser automation was available.
- Login with a *pre-existing* account, because no credentials were available.
- Student login and prediction creation on the live database. I avoided these to protect real records and `data/processed/application_enrollment_registry.json`. Both are covered by the SQLite test suite instead.

**Preserved**
- `.env` is byte-identical to its state before this session.
- All 125 protected files (models, registry, processed and raw data, docs, migrations, frontend source and dist, earlier reports) are unchanged from the audit baseline.
- No database was reset, recreated, or migrated during this audit.
- The only database write was one clearly marked coordinator test account on 5433.

**Disclosure.** Before this audit, at your explicit request earlier in the session:
- an additive migration was applied to **5432**;
- the backend ran against 5432 for a period.

Details are in §8.

---

## 2. Baseline (Phase 1)

| Item | Finding |
|---|---|
| Version control | **No Git repository** (`git status` → "not a git repository"). Changes are tracked with a SHA-256 snapshot of 218 files (`baseline_hashes.sha256`) taken before any edit in this audit. |
| Pre-existing session changes | `backend/app/main.py` (CORS fix) and the new root `package.json` were made earlier in this session, before the baseline. They are reported here as part of this repair. |
| Backend | `uvicorn backend.app.main:app --host 127.0.0.1 --port 8001` (README, `.vscode/tasks.json`). Routes are under `/api`; `GET /health` checks the database with `SELECT 1`. |
| Frontend | Vite on 127.0.0.1:5173. `frontend/.env.local` sets `VITE_API_BASE_URL=http://127.0.0.1:8001/api`, with fallback `'/api'` (`frontend/src/api/client.js`). |
| Settings | pydantic-settings reads `.env`; real environment variables override it (`backend/app/core/config.py`). Alembic prefers `$DATABASE_URL` (`backend/alembic/env.py:18`). |
| `.env` target [Observed, redacted] | `DATABASE_URL` → `127.0.0.1:5432/student_support` (legacy `student-db-1`); `POSTGRES_PORT=5432` |
| Containers [Verified] | `northstar-local-db-1` → 127.0.0.1:5433 (compose project `northstar-local`); `student-db-1` → 127.0.0.1:5432 (compose project `student`, created from `D:\AIML_BOOTCAMP\project\student`) |
| Running services at start | Vite on 5173 (one process); uvicorn on 8001 (one process, connected to 5432) |
| Test inventory | `backend/tests` (12 modules, SQLite in memory), `tests` (ML / feature / inference / integrity), `frontend/src/**/*.test.*` (Vitest). No lint or typecheck scripts are configured. |

---

## 3. Login API error: diagnosis (Phase 2)

### 3.1 Evidence

| Step | Check | Result |
|---|---|---|
| Backend process | Listening on 8001, `GET /health` | 200 `{"status":"ok"}`, so the backend was up |
| Frontend URL | `import.meta.env` served by Vite for `/src/api/client.js` | `VITE_API_BASE_URL: "http://127.0.0.1:8001/api"`. Axios joins it with `/auth/login` to give `/api/auth/login`, with no duplicated or missing `/api`. |
| Routes | OpenAPI of `create_app()` | `POST /api/auth/login`, `/register`, `GET /api/auth/me` are registered |
| Contract | `scripts/contract_check.py` | 43 of 43 frontend calls map to existing method + path |
| CORS origins | `.env CORS_ORIGINS` | Includes `http://localhost:5173` and `http://127.0.0.1:5173` |
| **Browser preflights (backend log)** | `uvicorn` access log | `OPTIONS /api/auth/register` → **400**, `OPTIONS /api/auth/login` → **400** (the browser's requests before the fix) |
| Isolated reproduction | `scripts/repro_cors_pna.py` (in-process, no server or DB) | With the project's CORS settings and no `allow_private_network`: plain preflight → 200; **preflight with `Access-Control-Request-Private-Network: true` → `400 Disallowed CORS private-network`**. With the flag set → 200. |
| Port sharing | `netstat -ano` | At one point **three** processes were LISTENING on 127.0.0.1:8001: two started by `npm run backend` from `.env` (5432) and one started on 5433 |

### 3.2 Root cause
- **Error type:** CORS rejection (HTTP 400 on the preflight). It was not a connection refusal, timeout, 5xx, or authentication failure.
- **Mechanism:** Chrome's Private Network Access header was not permitted (`backend/app/main.py`, `CORSMiddleware`). Axios surfaces a blocked preflight as a response-less error, which `friendlyError()` (`frontend/src/api/client.js`) reports as "could not be reached".
- **Why tests missed it:** the existing CORS test (`test_cors_allows_local_origin_without_cookie_credentials`) never sends the PNA header.
- **Duplicate instances:** these made the symptom intermittent and pointed some requests at the legacy database.

### 3.3 Repair
- `allow_private_network=True` on the existing `CORSMiddleware`. The origin allow-list is unchanged, and credentials are still disallowed.
- **Security check [Verified]:** a PNA preflight from an unlisted origin is still rejected (400, no `Access-Control-Allow-Origin`). Starlette echoes `access-control-allow-private-network` even on that rejected response, which is harmless because the browser blocks it on the status and the missing allow-origin.
- `scripts/with_isolated_db.py --require-free-port 8001` refuses to start a second backend.

---

## 4. Backend audit (Phase 3)

### 4.1 Results

| Area | Result |
|---|---|
| Startup / configuration | [Verified] `create_app()` starts with SQLite and with PostgreSQL 5433. Settings validate the JWT secret length, HS256, expiry range, SMTP, and LLM values. |
| DB session / health | [Verified] Health returns 503 on DB failure without leaking the URL (`main.py`). One live connection, to 5433 only. |
| Auth | [Verified live] Register (invite-only coordinator; 403 on a wrong invite; 422 on a weak password; 409 on a duplicate), login (case-insensitive email; 401 on a wrong password), `/auth/me`, password change with **token revocation** (old token → 401 via `token_version`), garbage token → 401 |
| Authorization | [Verified live] 401 without a token on protected routes; coordinator-only routes work for a coordinator; pagination limits enforced (422). `GET /students/me` returns **404** to non-students by design (`students.py:23-24`), so it does not disclose profile existence. |
| Coordinator reads (existing data) | [Verified live] students (28, matching the DB count), analytics overview / risk-trends / engagement / monitoring, predictions (44), clusters (23), cluster profiles, interventions, access requests, CSV template, per-student detail / predictions / performance / engagement / study plan / messages; unknown student → 404 |
| Imports / predictions / ML endpoints | [Verified] by the backend suite (`test_csv_imports.py`, `test_ml_endpoints.py`, `test_oulad_import.py`) on SQLite with mocked and real artifacts. Not exercised with writes on the live DB (§7). |
| Error handling | [Observed] Validation errors are sanitised; unhandled errors are logged and returned as a generic 500 |
| Migrations | [Verified] `alembic current` = `heads` = `1d7c8f2a6b91` on 5433. `alembic check` failed on JSONB/JSON drift, which is now **fixed** (clean). The SQLite upgrade/downgrade test passes. |

### 4.2 Defect: imported LSTM forecasts recorded the wrong model version (P2, fixed)

| | |
|---|---|
| **Evidence** | On 5433, the 21 `lstm_weekly` predictions (created 2026-10-09 18:17 UTC by the CSV import) have `model_version = "1.2.0"`. `ml/saved_models/registry.json` lists `lstm_weekly` as **1.1.0**, and the artifact metadata matches 1.1.0: `lstm_preprocessing.joblib` has `feature_version` `oulad-early-risk-v1` and threshold 0.193651. The registry file was last written at 09:57 UTC, before these predictions. |
| **Root cause** | `backend/app/api/routes/imports.py` stored `model_version=MODEL_VERSION` (constant `"1.2.0"` from `ml/version.py`) for forecasts. The interactive path (`predictions.py:105`) correctly uses the version returned by `ModelManager.predict_sequence`, which reads the registry. Test fakes omitted `model_version`, so the bug was invisible. |
| **Fix** | Store `forecast_result["model_version"]`; remove the now-unused import; make the test fakes match the real `predict_sequence` contract. |
| **Regression test** | `test_coordinator_import_persists_real_api_records_and_is_idempotent` asserts the stored forecast's `(model_name, model_version)`. It failed before the fix (`'1.2.0' != 'registry-lstm-version'`) and passes after. |
| **Real-path check** | [Verified] `ModelManager.predict_sequence` on the saved artifacts returns `model_version '1.1.0'`, threshold 0.193651, score in [0, 1]. |
| **Not changed** | The 21 existing rows on 5433 keep their incorrect label. Correcting them is a data change that needs approval (§9). |
| **ML scope** | No model, threshold, feature contract, or calibration was changed. Only the provenance label written at import time. |

### 4.3 Defect: ORM/migration type drift (P3, fixed)

| | |
|---|---|
| **Evidence** | `alembic check` (5433): `modify_type grade_predictions.observed_signals JSONB → JSON` |
| **Root cause** | Migration `a58f9d632e10` creates `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`, but `GradePrediction.observed_signals` in `backend/app/models/entities.py` used plain `JSON`. The next `alembic revision --autogenerate` would have emitted an unintended type change. |
| **Fix** | The model uses the same variant. No database change. |
| **Test** | `test_grade_prediction_signals_use_jsonb_on_postgresql_like_its_migration`: failed before (`'JSON' == 'JSONB'`), passes after. `alembic check` now reports "No new upgrade operations detected." |

### 4.4 Live E2E note
46 checks were run; 45 passed. The one "failure" (`/students/me` as coordinator expected 403, got 404) was a wrong expectation in the audit script: 404 is the intended behaviour (§4.1). It is not a defect.

---

## 5. Frontend audit (Phase 4)

| Area | Result |
|---|---|
| Build | [Verified] `vite build`, written to a scratch directory so `frontend/dist` was not overwritten, produces 1,666 modules. Warning: one JS chunk is 543 kB (> 500 kB), P3. |
| Tests | [Verified] Vitest: 2 files, 33 tests passed |
| Lint / types | Not configured in `frontend/package.json` (no ESLint or TypeScript), so not run |
| API URL | [Verified] Effective base `http://127.0.0.1:8001/api` |
| API contract | [Verified] 43 of 43 calls in `services.js` exist on the backend with the same method. The backend operation `POST /students/{id}/enrollment-number` has no UI caller; it is a coordinator repair endpoint, since registration assigns numbers automatically. |
| Auth state | [Observed] Token in `localStorage`. A 401 on a non-auth request clears the token and dispatches `auth:expired`, which `AuthContext` handles. Login and register 401s show field messages. `RequireAuth` / `RequireRole` guard the student and coordinator areas (`App.jsx`). |
| Logout | [Observed] Client-side only (token removal); there is no server logout endpoint. Server-side revocation exists via password change ([Verified] live). |
| Fallback base URL | [Observed] Without `frontend/.env.local`, the base falls back to `'/api'` on the Vite origin, and `vite.config.js` defines no proxy, so calls would 404. Documented in `frontend/.env.example`. P3, unchanged. |
| Browser-level UI | **[Not verified]** No browser automation was available. Page rendering, console errors, accessibility, and responsive layout could not be inspected in a real browser. |

---

## 6. Database and infrastructure audit (Phase 5)

| Item | Result |
|---|---|
| Intended NorthStar DB | `northstar-local-db-1` on 5433, healthy, schema at head, ORM in sync. Contents before and after (read-only counts): users 1 coordinator + 28 students → **2 coordinators** (+1 audit account) + 28 students; students 28, enrollments 27, predictions 44, interventions 0, imports 1, clusters 23, all unchanged. |
| Legacy DB | `student-db-1` on 5432 is running and healthy. Not connected to, stopped, or modified during this audit. |
| `.env` | Not modified (hash identical to the pre-session snapshot in `reports/calibration_audit_20261010T012653Z/pre_audit_hashes.sha256`). It still points at 5432. |
| README `docker compose up -d db` (P0, scripts fixed; README unchanged) | [Verified by `--dry-run`, nothing created] From this folder it would create a **new** container `northstar-db-1` with a new empty volume `northstar_student-postgres`, binding `POSTGRES_PORT` (5432, the legacy port). It does not start `northstar-local-db-1`. |
| Script remediation | `npm run db` → `docker start northstar-local-db-1` (never recreates). `npm run backend/dev/migrate` → `scripts/with_isolated_db.py`, which takes `DATABASE_URL` from env or `.env`, swaps only the port to 5433, refuses 5432, never prints credentials, and blocks a busy HTTP port. [Verified] The child process sees `127.0.0.1:5433/student_support`; a second `npm run backend` is refused while 8001 is busy. |
| **Design conflict, needs an owner decision** | `scripts/seed_synthetic_upload_fixture.py` and `data/test_fixtures/coordinator_upload/README.md` define 5433 as the isolated **test-seeding** database and refuse to seed any database matching `.env`. If `.env` were changed to 5433, 4 seed-guard tests fail (observed earlier in this session). The launcher avoids that by leaving `.env` unchanged, but the project still has two conflicting definitions of "the app database". |
| Migrations run during this audit | **None** (`alembic upgrade` was not executed; only `current`, `heads`, `check`) |

---

## 7. ML and data integrity (Phase 6)

| Check | Result |
|---|---|
| Artifacts and registry | [Verified] Unchanged (hashes). Selected model `xgboost` 1.2.0, threshold 0.189824 (artifact 0.18982425332069397), feature version `oulad-early-risk-v2`. LSTM 1.1.0, threshold 0.193651, feature contract `oulad-early-risk-v1` (legacy-accepted). |
| Contract / class order / reproduction | [Verified] `tests/` suite passes: feature contract, inference validation, canonical integrity (recorded metrics reproduce exactly), `classes_ == [0, 1]`, scores in [0, 1] |
| Stored predictions (5433) | [Verified live] All 44 scores and thresholds are in [0, 1]. Bands are only `review_for_support` / `no_flag_from_model`. Every band equals `score >= stored threshold`. Fields match what the frontend reads. |
| Version provenance | Defect found and fixed in the import path (§4.2). The 21 historical rows remain mislabelled. |
| Model behaviour | Not changed: no retraining, recalibration, threshold change, or feature-contract change |

---

## 8. Safety and session disclosure

Earlier in this session, **before** this audit and at your explicit request ("5432 as designed"):
1. `alembic upgrade head` was run on **`student-db-1` (5432)**, applying `1d7c8f2a6b91`, which adds `users.token_version INTEGER NOT NULL DEFAULT 0`. It was additive; no existing data was changed. It was **not reverted**, because a downgrade would be a second write to that database.
2. A backend ran against 5432 for a period, so any actions you took in the UI during that period went to 5432.
3. `.env` was temporarily edited (5432 → 5433 → 5432). The current file is byte-identical to the pre-session snapshot.

During this audit there was no connection to 5432, no `.env` edit, no migration, and no reset or recreate operation.

---

## 9. Remaining issues and next actions

| # | Item | Priority | Next action |
|---|---|---|---|
| R1 | `.env` points at 5432 while this brief defines 5433 as NorthStar's DB, and the seed tool defines 5433 as a test-only DB | P0 decision | Project owner chooses the app database and either updates `.env` or updates the seed-tool guard. The launcher makes either choice safe meanwhile. |
| R2 | 21 imported LSTM predictions on 5433 labelled `1.2.0` (should be `1.1.0`) | P2 data | With approval, a targeted `UPDATE ... WHERE model_name='lstm_weekly' AND model_version='1.2.0'` after a backup, or leave them as historical with a note |
| R3 | README `docker compose up -d db` does not match the local container layout | P2 docs | Update the README to `npm run db` / `docker start northstar-local-db-1`, or run compose with `-p northstar-local` and `POSTGRES_PORT=5433` |
| R4 | Real-browser UI verification not performed | — | Click through login → coordinator dashboard → student detail in Chrome, with DevTools open |
| R5 | Existing-account login not verified (no credentials) | — | Log in with your known coordinator account |
| R6 | Student self-registration on the live DB not exercised (it writes `data/processed/application_enrollment_registry.json`) | — | Verify on a disposable environment, or accept the SQLite test coverage |
| R7 | `uvicorn --reload` hung once after a file change on Windows (old worker never exited) | P3 | Restart manually when it happens; consider dropping `--reload` if it recurs |
| R8 | 543 kB JS chunk warning; no lint or typecheck configured | P3 | Code-split heavy pages (charts); add ESLint |
| R9 | Third-party deprecation warnings (Keras on NumPy ≥ 1.25; Starlette TestClient with httpx) | P3 | Address during a planned dependency update (no upgrade done here) |
| R10 | Audit marker account `audit-e2e-coordinator-20261010T045341Z@example.com` (coordinator) on 5433 | Info | Keep for testing, or deactivate or remove with approval |

---

## 10. Reproduction

From the project root, in Git Bash or PowerShell, with the backend running via `npm run backend`:

```bash
# Root cause, in-process (no server or DB)
.venv/Scripts/python.exe -B reports/full_project_audit_20261010T044740Z/scripts/repro_cors_pna.py
# Frontend/backend route contract (no DB)
.venv/Scripts/python.exe -B reports/full_project_audit_20261010T044740Z/scripts/contract_check.py
# Live HTTP E2E. NOTE: creates one new marked coordinator account each run
.venv/Scripts/python.exe -B reports/full_project_audit_20261010T044740Z/scripts/e2e_api.py out.json
# Schema drift against 5433 (read-only)
.venv/Scripts/python.exe -m scripts.with_isolated_db -- .venv/Scripts/python.exe -m alembic -c backend/alembic.ini check
# Tests
.venv/Scripts/python.exe -m pytest -q backend/tests tests
npm --prefix frontend test
# Integrity against this audit's baseline (expect only the files in MODIFIED_FILES.md to differ)
sha256sum -c reports/full_project_audit_20261010T044740Z/baseline_hashes.sha256 | grep -v ': OK$'
```
