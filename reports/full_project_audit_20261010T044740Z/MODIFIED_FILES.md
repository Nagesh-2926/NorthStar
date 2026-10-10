# Modified Files: `full_project_audit_20261010T044740Z`

The project is not under Git. The changes below were identified by SHA-256 comparison with `baseline_hashes.sha256` (taken before any edit in this audit), plus the two session changes made just before the baseline.

## Changed during this audit

| File | Change | Reason |
|---|---|---|
| `backend/app/api/routes/imports.py` | Imported LSTM forecasts store `forecast_result["model_version"]` instead of the `MODEL_VERSION` constant; removed the unused `from ml.version import MODEL_VERSION` | P2: provenance. Forecasts were labelled "1.2.0" although the scoring LSTM is registry v1.1.0 |
| `backend/app/models/entities.py` | `GradePrediction.observed_signals` uses `JSON().with_variant(JSONB(), "postgresql")`; imported `JSONB` | P3: match migration `a58f9d632e10`; `alembic check` was failing |
| `backend/tests/test_auth_and_access.py` | +2 tests: PNA preflight accepted from an allowed origin; still rejected from an unlisted origin | Regression for the login root cause, and proof the fix does not widen CORS |
| `backend/tests/test_csv_imports.py` | `predict_sequence` fakes return `model_version` (as the real `ModelManager` does); assert the stored forecast version | Regression for the import provenance defect |
| `backend/tests/test_migrations.py` | +1 test: the column compiles to JSONB on PostgreSQL | Regression for the ORM/migration drift |
| `package.json` (root) | `db` → `docker start northstar-local-db-1`; `backend` and `migrate` run through `scripts/with_isolated_db.py`, and `backend` refuses a busy port 8001 | P0/P1: scripts targeted the legacy 5432 database via `.env`, and duplicate backends shared port 8001 |

## Added during this audit

| File | Purpose |
|---|---|
| `scripts/with_isolated_db.py` | Runs one command with `DATABASE_URL` pointed at 127.0.0.1:5433, changing only the port and never printing credentials. It refuses 5432, blocks a busy HTTP port, and does not edit `.env`. |
| `tests/test_with_isolated_db.py` | 6 unit tests: port rewrite preserves credentials, redaction, missing-port rejection, legacy-port refusal, busy-port block, child environment |
| `reports/full_project_audit_20261010T044740Z/*` | This report, test results, E2E JSON, baseline hashes, re-runnable scripts |

## Changed earlier in this session, before the audit baseline (included in this repair)

| File | Change | Reason |
|---|---|---|
| `backend/app/main.py` | `CORSMiddleware(..., allow_private_network=True)` with a comment | P1 root cause of "API could not be reached" |
| `package.json` (root) | Created (run shortcuts). Revised during this audit as above. | Convenience scripts requested by the user |

## Explicitly not modified

- `.env`: byte-identical to its pre-session state.
- Model artifacts, `registry.json`, thresholds, feature contract, calibration: unchanged.
- `data/processed/*`, `data/raw/oulad/*`, `data/templates/*`: unchanged.
- Alembic migration files and the database schema: unchanged during this audit.
- `README.md`, `docs/*`, `docker-compose.yml`, `frontend/src/*`, `frontend/dist/*`: unchanged.
- Earlier audit and design reports under `reports/`: unchanged.

## Database writes during this audit

| Database | Write |
|---|---|
| 5433 `northstar-local-db-1` | One user, `audit-e2e-coordinator-20261010T045341Z@example.com` (role coordinator). Its password was changed once (`token_version` 0 → 1) to verify session revocation. The password was generated at random and never recorded. |
| 5432 `student-db-1` | None during this audit (see the session disclosure in `AUDIT_REPORT.md` §8) |
