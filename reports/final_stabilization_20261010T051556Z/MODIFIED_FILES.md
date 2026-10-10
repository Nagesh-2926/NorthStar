# Modified Files: `final_stabilization_20261010T051556Z`

These were determined by SHA-256 comparison against `baseline_hashes.sha256` (228 files, taken before any edit in this pass).

## Changed project files (3)

| File | Change | Reason |
|---|---|---|
| `backend/tests/test_auth_and_access.py` | +1 test `test_student_profile_endpoint_is_not_found_for_coordinators` | Pins the intended 404 (non-disclosure) for non-students on `/api/students/me`, which the earlier live script misread as a failure. No application behaviour changed. |
| `README.md` | Added a callout at the top of "Install and run" pointing this machine's setup to `npm run db` / `migrate` / `dev`, and explaining the risk of the generic `.env`-based commands. Added one sentence noting that VS Code tasks use `.env` directly. | The generic commands would use the legacy `.env` database, and `docker compose up -d db` would create a new empty container. The generic fresh-machine instructions were kept. |
| `frontend/vite.config.js` | `build.rollupOptions.output.manualChunks` splits `vendor-react` (react, react-dom, react-router-dom) and `vendor-charts` (chart.js, react-chartjs-2) | Resolves the >500 kB chunk warning with a localized change. Behaviour and loaded code are unchanged. |

## New files (report directory only)

| File | Purpose |
|---|---|
| `FINAL_STABILIZATION_REPORT.md`, `TEST_RESULTS.md`, `MODIFIED_FILES.md` | Deliverables |
| `baseline_hashes.sha256`, `protected_subset.sha256` | Integrity baselines |
| `db_snapshot_before.json`, `db_snapshot_after_live.json`, `db_snapshot_final.json` | Read-only 5433 snapshots (counts and labels only) |
| `live_http_results.json` | Results of the non-destructive live suite |
| `scripts/live_http_readonly.py` | Live HTTP checks that create no accounts and need no credentials |
| `scripts/db_readonly_snapshot.py` | Read-only 5433 snapshot; refuses any other target |
| `scripts/seed_guard_check.py` | Exercises the seed-tool guard without connecting to a database |

## Not modified

- `.env`, and all of `backend/app/**`, `backend/alembic/**`, `scripts/*`, `package.json`, `.vscode/*`
- ML artifacts, registry, thresholds, feature contract
- `data/**`, `frontend/src/**`, `frontend/dist/**`, `docs/*`, `docker-compose.yml`
- All earlier reports
- Both databases: no writes, no migrations, and no connection to 5432
- No user, including the audit account, was created, changed, or removed
