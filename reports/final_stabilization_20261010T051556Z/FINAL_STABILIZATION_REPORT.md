# NorthStar Final Stabilization Report

| | |
|---|---|
| Pass ID | `final_stabilization_20261010T051556Z` |
| Builds on | `reports/full_project_audit_20261010T044740Z/` (called "the audit") |
| Companion files | `TEST_RESULTS.md`, `MODIFIED_FILES.md`, `live_http_results.json`, `db_snapshot_{before,after_live,final}.json`, `baseline_hashes.sha256`, `protected_subset.sha256`, `scripts/` |

**Evidence labels**

| Label | Meaning |
|---|---|
| **[Verified]** | Executed in this pass and its output checked |
| **[Fixed]** | Changed in this pass |
| **[Owner]** | Decision or action reserved for the project owner |
| **[Not run]** | Not performed; the reason is given |

---

## 1. Summary

| Question | Answer |
|---|---|
| Is the login/API connectivity issue still fixed? | **Yes [Verified].** `allow_private_network=True` is present in `backend/app/main.py`. Live PNA preflights from both allowed origins return 200 with the correct `Access-Control-Allow-Origin`. An unlisted origin is still rejected (400, no allow-origin). The frontend serves `VITE_API_BASE_URL=http://127.0.0.1:8001/api`. |
| Is the intended stack running? | **Yes [Verified].** One NorthStar backend on 8001 (launched via `npm run backend` → `scripts/with_isolated_db.py`), DB connection to 127.0.0.1:5433 only; one Vite dev server on 5173; `/health` → `{"status":"ok"}`. |
| Fixed in this pass | (1) The live E2E expectation for `/students/me` is now pinned by a backend test, and the live suite was replaced by a non-destructive one (24/24). (2) The README no longer steers this machine to the legacy database. (3) The frontend bundle warning, resolved with a localized vendor chunk split. |
| Tests | Backend + ML **158 passed**; frontend **33 passed**; build succeeds with **no warnings**; live HTTP **24/24**; launcher, seed-guard, schema, contract and ML checks all pass (`TEST_RESULTS.md`) |
| Not verified | Real-browser login and UI workflows (no browser automation available, and no owner credentials). See §6 for the manual checklist. |
| Safety | No database writes (5433 snapshots identical before and after); no access to 5432; `.env` byte-identical to its pre-session state; all 188 protected files unchanged; no migrations, retraining or artifact changes |

---

## 2. Current state verified before editing (Phase 1) [Verified]

| Item | Finding |
|---|---|
| Port 8001 | Exactly **one** NorthStar backend. Process chain: `cmd` (npm) → `with_isolated_db` launcher → venv redirector `python.exe` → uvicorn reloader → worker. The worker holds the only DB connection, to **127.0.0.1:5433**. The apparently duplicate `python.exe` entries are the Windows venv redirector stub plus the real interpreter, not separate servers. |
| Port 5173 | One Vite dev server (`npm run frontend`). HTTP 200. |
| Containers (no connection to 5432) | `northstar-local-db-1` 127.0.0.1:5433 healthy; `student-db-1` 127.0.0.1:5432 healthy (inspected only via `docker ps` / `docker inspect`) |
| Earlier fixes present | CORS `allow_private_network=True` (`main.py:36`); import forecast uses `forecast_result["model_version"]` (`imports.py:256`); JSONB variant (`entities.py:223`); `package.json` targets via launcher |
| Effective frontend API URL | `http://127.0.0.1:8001/api`; Axios joins it with `/auth/login`, so `/api` is neither duplicated nor missing |

---

## 3. Login path (Phase 2) [Verified]

| Step | Evidence |
|---|---|
| Frontend request | `authApi.login` → `POST /auth/login` on base `http://127.0.0.1:8001/api` (served `import.meta.env`) |
| CORS preflight with PNA | 200 from `http://127.0.0.1:5173` and `http://localhost:5173` for login, register, and `GET /api/students` with `Authorization`; no `allow-credentials` |
| Unapproved origin | Preflight 400 with no allow-origin; actual request carries no allow-origin, so the browser blocks it |
| Route registration | `POST /api/auth/login`, `POST /api/auth/register`, `GET /api/auth/me` present in the live OpenAPI |
| Authentication errors | Missing fields → 422; unknown account → 401 `"Invalid email or password"` (with allow-origin, so the UI can display it); malformed token → 401 |
| Protected routes without a token | 401 on `/auth/me`, `/students`, `/students/me`, `/analytics/overview`, `/predictions`, `/interventions`, `/imports/template`, `/access-requests` |
| Registration reachable | Invalid body → 422; coordinator with wrong invite → 403. Both are rejected before any write; the DB snapshot is unchanged. |
| Health | 200 `{"status":"ok"}`, no configuration disclosed |
| Root cause still reproducible in isolation | `repro_cors_pna.py`: without the flag, PNA → 400 "Disallowed CORS private-network"; with it → 200 |

Existing-account login and the rendered UI response were **not** verified ([Not run]: no credentials and no browser automation). See §6.

---

## 4. Database configuration (Phase 3)

### 4.1 How each command chooses its database [Verified]

| Command | Target resolution | Verified behaviour |
|---|---|---|
| `npm run backend` | `with_isolated_db` copies `DATABASE_URL` (shell env, else `.env`) and replaces **only the port** with 5433 | Child receives `127.0.0.1:5433/student_support`. Even with a shell `DATABASE_URL` forced to 5432, the child gets 5433. `--db-port 5432` → refused. |
| `npm run dev` | Opens `npm run backend` in a new window, plus `npm run frontend` | Same as above |
| `npm run migrate` | Same launcher, then `alembic upgrade head` | **Not executed** (no migrations in this task). The same launcher path was run with read-only `alembic current` → `127.0.0.1:5433`, `1d7c8f2a6b91 (head)`. |
| `npm run db` | `docker start northstar-local-db-1` | Run against the already-running container: same container ID, same `StartedAt`, identical volume list. It never creates a container or volume. |
| Second `npm run backend` | `--require-free-port 8001` | Refused ("Port 8001 is already in use…"); listener count stayed at 1 |
| Seed tool | `NORTHSTAR_TEST_DATABASE_URL` or `--database-url` only; never `.env` | `verify_target` (no DB connection) refused 7 of 7 unsafe targets: none, 5432, default port, wrong DB name, query-parameter redirect, `PGPORT` override, write without `--confirm-target`. The verified 5433 target is accepted for a dry run. The seed-fixture backend tests also pass. |
| VS Code tasks (`.vscode/tasks.json`) | `.env` directly (5432 on this machine) | Unchanged. The README now warns about this (§5). |

### 4.2 The configuration conflict [Owner]

- **`.env`** sets `DATABASE_URL` to `127.0.0.1:5432` (`student-db-1`).
- **The launcher** makes the running app use **5433**.
- **The seed tool** treats 5433 as the isolated *test* database. Its guard refuses any target equal to the `.env` database (5432 here), so it **will** seed synthetic accounts into 5433, which is the database the app now serves. `data/test_fixtures/coordinator_upload/README.md` expects the fixture to be imported through the app against 5433, so this is consistent with the tool's design. It is not a code defect.
- **5433 holds** 28 students, 27 enrollments, 44 predictions and 1 import.

**Decision required:** is 5433 a test-only database (synthetic seeding acceptable), or does it hold data that must stay free of synthetic accounts?

- If test-only: no change needed.
- If it holds protected data: the seed guard should also refuse the launcher's effective target, or a separate test database is needed.
- Changing `.env` to 5433 would make the seed guard refuse 5433 (4 seed-guard tests fail, as observed earlier in the session).

Per the brief, neither side was changed.

---

## 5. Remaining audit items (Phase 4)

| Item | Result |
|---|---|
| **A. Historical LSTM labels** | [Verified, read-only, 5433] 21 rows `lstm_weekly / 1.2.0 / oulad-early-risk-v1` and 23 rows `xgboost / 1.2.0`. The real `ModelManager.predict_sequence` reports **1.1.0** (threshold 0.193651). The import regression test passes, so new imports store the scoring result's version. **Historical rows not changed.** A correction is a data change to persisted provenance that other records reference (`imported_feature_snapshots.forecast_prediction_id`); it needs approval, a backup, and a decision between rewriting the label or annotating the rows as historical. [Owner] |
| **B. Audit test account** | [Verified, read-only] Exists: coordinator, active, `token_version` 1. **Correction to the audit report:** emails are lowercased on registration (`auth.py:26`), so it is stored as `audit-e2e-coordinator-20261010t045341z@example.com`. Not changed; cleanup is left to the owner. [Owner] |
| **C. `/students/me` expectation** | [Fixed] The implementation returns 404 to non-students (`students.py:23-24`), consistent with the project's non-disclosure convention (`get_authorized_student`, `dependencies.py:48-50`, which "hides cross-account resource existence") and the existing security test asserting 404 for denied reads. Behaviour unchanged. New backend test `test_student_profile_endpoint_is_not_found_for_coordinators` pins it (SQLite). The previous live script (`e2e_api.py`, which creates an account) is **superseded** by `scripts/live_http_readonly.py`, which creates nothing: **24/24 passed**, DB counts identical before and after. |
| **D. Real-browser verification** | [Not run] No browser automation is available in this environment, and no owner credentials. Checklist in §6. |
| **E. Bundle warning** | [Fixed] Measured per package (scratch build): chart.js 170 kB, react-dom 127 kB, app 107 kB, axios 50 kB, react-router 38 kB, all in one 543 kB chunk. `frontend/vite.config.js` now puts React and the charting libraries into separate long-cached vendor chunks (index 176 kB, vendor-react 181 kB, vendor-charts 185 kB), with **no warning**. Same 1,666 modules and the same code at startup. Total download is **not** reduced. Smoke test of the built output (temporary `vite preview` on 4173): all referenced assets 200, vendor chunks preloaded, API base baked in, SPA route 200. Lazy-loading chart pages to reduce initial load is recommended as a separate task. |
| **F. Lint / types / deprecations** | [Verified] There is no ESLint, TypeScript, or Python linter or type checker (no scripts, no tools in `.venv`, no config). Third-party warnings persist: Keras `DeprecationWarning` (NumPy ≥ 1.25 scalar conversion; 43 occurrences) and `StarletteDeprecationWarning` (TestClient with `httpx`). Nothing was installed, upgraded, or suppressed. |

---

## 6. Manual owner checks (browser)

Run these in Chrome with the stack running (`npm run db`, `npm run dev`) and DevTools open (Network + Console). Do not share the password.

1. Open `http://127.0.0.1:5173/login`. The page loads with no red errors in the Console.
2. Log in with your coordinator account. In Network, `OPTIONS …/api/auth/login` should be **200** and `POST …/api/auth/login` **200**. There should be no "could not be reached" banner.
3. The coordinator dashboard loads with its overview cards and charts. Both `vendor-*.js` files load in a production build; in dev mode, modules load individually.
4. **Students → open one student.** Details, predictions, engagement and study-plan sections load (requests 200).
5. Open **Clusters**, **Interventions**, **Imports** (template download) and **Access requests**.
6. Log out, then open `http://127.0.0.1:5173/coordinator/dashboard` directly. You should be redirected to login.
7. Optionally, as a student account: `/student/dashboard` loads and coordinator URLs are refused.

Record any failing request (URL and status) and the console message.

---

## 7. Integrity and safety (Phase 6) [Verified]

| Check | Result |
|---|---|
| Files changed vs this pass's baseline (228 files) | **3**: `README.md`, `backend/tests/test_auth_and_access.py`, `frontend/vite.config.js`. No new project files outside this report directory. |
| Protected subset (188 files: `.env*`, `ml/saved_models/*`, ML source, `data/**`, `frontend/src/*`, `frontend/dist/*`, `frontend/.env*`, `backend/app/**`, `backend/alembic/**`, `docs/*`, `docker-compose.yml`, `database/*`, `student_support.db`, `.vscode/*`, `scripts/*`, all earlier reports) | **All unchanged** |
| `.env` | Byte-identical to the pre-session snapshot (`reports/calibration_audit_20261010T012653Z/pre_audit_hashes.sha256`) |
| Database 5433 | Read-only sessions only (`transaction_read_only = on`). Counts, roles, prediction versions, marker account and Alembic version are identical in the before, after-live and final snapshots. No migrations. |
| Database 5432 | Never connected. Only `docker ps` and `docker inspect` metadata were read. |
| Containers and volumes | Same IDs and start times; volume list unchanged; no container or volume created |
| ML | Artifacts, registry, thresholds and feature contract unchanged (hashes); `tests/test_canonical_integrity.py` reproduces the recorded metrics |
| Processes | One backend (8001, to 5433) and one Vite (5173). The temporary preview server (4173) was stopped. |
| Credentials | None printed or stored. The DB URL is shown only as `host:port/db`. |

---

## 8. Remaining work

| # | Item | Owner action |
|---|---|---|
| 1 | Is 5433 test-only or the protected app DB? (§4.2) | Decide; then align `.env`, the seed guard, or provision a separate test DB |
| 2 | 21 historical LSTM rows labelled 1.2.0 | Approve or decline a backed-up data correction, or annotate the rows as historical |
| 3 | Audit account `audit-e2e-coordinator-20261010t045341z@example.com` | Keep, deactivate, or remove |
| 4 | Browser verification (§6) | Perform it manually |
| 5 | `.vscode/tasks.json` backend and migration tasks read `.env` directly | Approve routing them through `scripts/with_isolated_db.py`, or keep them with the README warning |
| 6 | No lint or typecheck tooling | Approve adding ESLint and/or Ruff (new dev dependencies) |
| 7 | Third-party deprecation warnings | Address during a planned dependency update |
| 8 | Initial JS download (~540 kB total) | Optional separate task: lazy-load chart-heavy routes |
| 9 | The previous audit's `scripts/e2e_api.py` creates an account each run | Use `final_stabilization_…/scripts/live_http_readonly.py` instead (the old report was left unchanged) |
