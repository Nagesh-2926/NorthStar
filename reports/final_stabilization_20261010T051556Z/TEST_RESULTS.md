# Test Results: `final_stabilization_20261010T051556Z`

Each row was executed in this pass and its output inspected. "Launcher" means `.venv\Scripts\python.exe -m scripts.with_isolated_db -- …`, which gives the child process `DATABASE_URL` pointed at 127.0.0.1:5433 and leaves `.env` untouched.

## Passed

| # | Check | Command / method | Result |
|---|---|---|---|
| 1 | Process and port inventory | `netstat -ano`, `Get-CimInstance Win32_Process` | 1 backend chain on 8001 (DB → 5433), 1 Vite on 5173 |
| 2 | Container state | `docker ps`, `docker inspect` (no DB connection to 5432) | Both healthy; ports 5433 and 5432 as expected |
| 3 | Earlier fixes present | `grep` in `main.py`, `imports.py`, `entities.py`, `package.json` | All present |
| 4 | DB snapshot before (read-only) | Launcher + `scripts/db_readonly_snapshot.py` | `transaction_read_only = on`; head `1d7c8f2a6b91`; users 30 (2 coordinator, 28 student); 21 LSTM rows labelled 1.2.0; marker account present |
| 5 | Auth test module, including the new `/students/me` test | `pytest backend/tests/test_auth_and_access.py` | **13 passed** |
| 6 | Live non-destructive HTTP suite | `scripts/live_http_readonly.py` | **24 passed, 0 failed** |
| 7 | No writes from the live suite | Snapshot before vs after | Identical |
| 8 | `npm run db` is a no-op on the existing container | `docker inspect` before and after | Same ID, same `StartedAt`, same volumes |
| 9 | Duplicate backend refused | Second `npm run backend` | Refused; listeners on 8001 stayed at 1 |
| 10 | `npm run migrate` target (without migrating) | Launcher + `alembic current` | `127.0.0.1:5433`, `1d7c8f2a6b91 (head)` |
| 11 | Launcher refuses legacy port | `--db-port 5432` | `refusing port 5432` |
| 12 | Launcher overrides a 5432 shell URL | `DATABASE_URL=…:5432… launcher` | Child port 5433 |
| 13 | Seed-tool guard (no DB connection) | `scripts/seed_guard_check.py` | 7 of 7 unsafe targets refused; isolated target accepted for a dry run |
| 14 | Bundle composition (scratch, measurement only) | `measure_bundle.mjs` via the Vite API | chart.js 170.2 kB, react-dom 127.4 kB, app 107.3 kB, axios 50.2 kB, react-router 37.9 kB |
| 15 | Production build after the vendor split | `npx vite build --outDir <scratch>` | 1,666 modules; index 176.43 kB, vendor-react 181.10 kB, vendor-charts 184.64 kB; **no size warning** |
| 16 | Built output smoke test | Temporary `vite preview` on 4173 | All assets 200; vendor chunks modulepreloaded; API base `http://127.0.0.1:8001/api` baked in; SPA route 200; preview stopped |
| 17 | **Full backend + ML suite** | `pytest -q backend/tests tests` | **158 passed**, 0 failed, 45 warnings (third-party) |
| 18 | Targeted regressions (CORS, import version, JSONB, launcher, seed fixture, canonical integrity) | `pytest` on those modules/tests | **81 passed** |
| 19 | **Frontend tests** | `npx vitest run` | **33 passed** (2 files) |
| 20 | Route contract | `full_project_audit_…/scripts/contract_check.py` | 43 calls, 0 missing |
| 21 | CORS PNA root-cause reproduction | `full_project_audit_…/scripts/repro_cors_pna.py` | Without flag + PNA → 400; with flag → 200 |
| 22 | Schema drift vs 5433 (compare-only) | Launcher + `alembic check` | "No new upgrade operations detected." |
| 23 | Real LSTM version | `ModelManager.predict_sequence` on saved artifacts | `1.1.0`, threshold 0.193651 |
| 24 | Vite dev server after the config change | `curl :5173`, served `client.js` | 200; `VITE_API_BASE_URL` correct |
| 25 | Hash integrity | `sha256sum -c` (228-file baseline; 188 protected) | 3 intended changes; protected files all unchanged |
| 26 | `.env` | Hash vs pre-session snapshot | Byte-identical |
| 27 | DB snapshot final | Read-only snapshot | Identical to before |
| 28 | Final health and processes | `curl /health`, `netstat` | `{"status":"ok"}`; 1 backend, 1 Vite; DB connection to 5433 only |

## Failed and then resolved during this pass

| Check | What happened | Resolution |
|---|---|---|
| Marker-account lookup (first snapshot) | Returned empty: the query used the mixed-case email from the audit report, but the app stores emails lowercased | Query uses `lower(%s)`; account found. The report text is corrected in §5B. |
| First bundle measurement | A Vite config file in the scratch directory could not resolve the `vite` package | Used the Vite build API by absolute path instead (`measure_bundle.mjs`); no project file added |

There are no failed checks left open.

## Not run

| Check | Reason |
|---|---|
| Real-browser login, UI rendering, console and network inspection | No browser automation available; no owner credentials |
| Authenticated live workflows (coordinator dashboard data via login) | Would require credentials or creating accounts (forbidden in this pass). Covered by the SQLite backend suite. |
| `npm run migrate` / `alembic upgrade` | Migrations prohibited in this task; already at head |
| Any connection to 5432 | Prohibited |
| `npm audit` | Network call to the npm registry; outside this pass's scope |
| Lint / typecheck | No tooling configured; installing it is prohibited in this pass |
