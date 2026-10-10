# NorthStar local demo verification — 10 October 2026

This report distinguishes isolated test evidence from the unverified PostgreSQL
demo. No live fixture seed, CSV import, application migration, or application
database cleanup is authorized by this work.

## What changed

Fixture safety:

- `scripts/seed_synthetic_upload_fixture.py`: exact fixture host, psycopg driver,
  canonical port and explicit independent credentials; raw query/fragment,
  whitespace, quote and placeholder rejection; protected application targets;
  sanitized argument/preparation/driver/cleanup errors; one control-file identity
  before engine creation; schema-qualified connected identity/database checks;
  exactly one expected Alembic revision; read-only default and explicit write guard.
- `scripts/with_isolated_db.py`: validate local application URL before port rewriting
  or displaying target metadata; reject redirecting/malformed URLs and database-port
  HTTP probes; sanitize command-launch errors. This wrapper is an application
  launcher, not a permitted fixture-credential source.
- New `scripts/check_fixture_target.py`: reuse the seeder's preflight checks without
  opening a database connection or displaying untrusted URL parts.
- New `scripts/verify_fixture_identity.py` and `.ps1`: the separately approved minimal
  read-only fixture identity operation described below.
- New `scripts/fixture_readonly.ps1` and `scripts/fixture_dry_run.ps1`: local masked
  credential entry, pinned reviewed seeder hash, process-override checks, isolated
  Python invocation, single attempt and cleanup of only a newly created fixture
  variable. Existing variables are not overwritten or cleared.
- New `scripts/run_safe_tests.py`: independent test runner that blocks real engines,
  database/network connections, application startup, subprocesses and writes to
  persistent application/fixture/model artifacts.
- New `scripts/run_sqlite_tests.py`: the separately approved backend integration
  runner, allowing only in-memory SQLite or files below a freshly verified
  temporary directory, with network/PostgreSQL and persistent artifact writes
  blocked. In-process ASGI tests start no HTTP server.

Backend behavior:

- `backend/app/services/csv_import.py`: reuse validated integer-valued weekly
  numbers, including decimal/exponent spellings; reject malformed headers,
  incomplete weekly columns and invalid/nonfinite/fractional observations; count
  rejected rows toward the file limit.
- `backend/app/api/routes/imports.py`: explicitly label validation as no-write.
- `backend/app/main.py`, `backend/app/llm/service.py`,
  `backend/app/api/routes/study_plans.py`: avoid exception-payload logging and keep
  absent support observations separate from observed zero values.

Frontend behavior:

- `frontend/src/auth/AuthContext.jsx`: injectable transient token storage for the
  isolated mock harness; production storage remains the default.
- `frontend/src/components/Primitives.jsx`: keep technical enrollment references in
  diagnostic details.
- `frontend/src/pages/CoordinatorImportsPage.jsx`: require supported validation and
  import evidence; separate validation-only, saved, previously saved and rejected
  results; preserve missing forecasts.
- `frontend/src/pages/CoordinatorPages.jsx`, `StudentPages.jsx`: clearer empty and
  error states, structured assistant error handling and diagnostic-only UUIDs.
- `frontend/src/styles.css`: styles for diagnostic details.
- New `frontend/mock-demo.html` and `frontend/src/test/browser/`: actual React
  routes/services with an in-memory Axios adapter. Unknown requests fail locally;
  saved browser authentication is untouched. The three copied CSVs are checked
  byte-for-byte against the original fixtures. The harness is excluded from the
  production build.

Regression coverage:

- `backend/tests/test_seed_fixture_safety.py`
- `tests/test_fixture_readonly_helpers.py` (new)
- `tests/test_with_isolated_db.py`
- `tests/test_csv_import_unit.py` (new)
- `tests/test_sqlite_runner_guards.py` (new)
- `frontend/src/test/setup.js`, `frontend/src/test/AppFlows.test.jsx`
- `frontend/src/test/browser/mockApi.test.js` (new)
- `data/test_fixtures/coordinator_upload/README.md`: safe local prompt instructions
  and explicit connection/write/backup boundaries; fixture provenance preserved.

There is no `.git` metadata in this project copy. A prior-user-change diff cannot
be established; edits above preserve the current source and avoid unrelated
refactoring. Root `.env`, original fixture CSVs, model artifacts, thresholds and
risk-scoring behavior were not edited by this task.

## Reproducible independent checks

From the project directory:

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_safe_tests.py
npm --prefix frontend test
npm --prefix frontend run build
```

The Python runner uses `--noconftest` because the backend's normal conftest imports
`main.py`, which constructs an application during collection. It excludes the two
legacy socket/child-process wrapper tests; those were reviewed and passed in a
separate wrapper run. It never starts a server or connects to PostgreSQL.

Saved-artifact checks load and score the existing models without training or
changing artifacts. A Keras/NumPy scalar-conversion deprecation warning remains.

The user separately approved this SQLite integration command:

```powershell
.\.venv\Scripts\python.exe -B .\scripts\run_sqlite_tests.py
```

It creates only temporary test data. Its socket-free test event loop supports
ASGI memory transport without allowing outbound networking. Temporary test files
are retained for review, not deleted automatically or reused as a test root.

## Configuration diagnosis

Before verification, the agent's tool process had no `DATABASE_URL`, fixture URL,
or prohibited libpq override. This does not establish the earlier terminal's
environment. `with_isolated_db.py` passes a rewritten application URL only to its
spawned child; it cannot change the parent shell. Backend settings read `.env`
without exporting `DATABASE_URL` into PowerShell. The earlier variable's actual
origin remains unknown. No original-shell or persistent setting was cleared.
The reviewed fixture helpers refuse a conflict and never obtain their target or
credentials from the application's configuration.

## Mock demo

The existing Vite frontend is listening on `127.0.0.1:5173`. Open:

`http://127.0.0.1:5173/mock-demo.html`

The banner identifies the page as mocked. Use the existing valid/rejection fixture
buttons, then the real validation/import controls. Mock import responses are UI
stubs and do not establish saved PostgreSQL records or live model inference.
Student, empty-overview and error-overview links cover zero scores, missing
forecasts and unavailable/empty results. Desktop/mobile screenshots were not
verified: Windows browser automation refused to proceed because it could not
determine the browser URL sufficiently to enforce policy. No bypass was attempted.

Fixture audit: 23 valid CSV rows, 14 rejection CSV rows, 37 mapping rows, 36 distinct
synthetic numbers and 27 seed definitions. The duplicate identity is intentional.
All three manifest hashes match. The valid fixture defines 21 complete weekly
sequences and two aggregate-only rows. These are expected/tested counts, not a
claim about a live PostgreSQL import.

## Approved read-only identity operation

The user approved one fixture identity verification and isolated SQLite integration
tests. PostgreSQL credentials are unavailable to the agent, so this requires a
user-run local terminal prompt:

```powershell
.\scripts\verify_fixture_identity.ps1
```

Enter the independent fixture URL only at its masked prompt. Do not use root `.env`
credentials, a command-line credential argument, a file, or chat. The supported
target is exactly `127.0.0.1:5433/student_support_fixture`.

Preflight requires the pinned reviewed seeder SHA256:

`8CC0215ADCFF86380A629634E7DF990C50E7C82146877BD6F5DDEF1EA81B4F26`

It refuses nonempty `DATABASE_URL` and all nine prohibited libpq overrides. It
does not clear them. An original-shell conflict must be reviewed locally or a clean
terminal used; no persistent setting is changed. Docker must report exactly
`northstar-local-db-1` publishing 5433. Its control-file identifier must be the
independently re-read value `7694699641731592226`, before any engine is created.

The database connection sends `default_transaction_read_only=on` at startup. The
explicit statements are:

```sql
SET TRANSACTION READ ONLY;
select system_identifier from pg_catalog.pg_control_system();
select pg_catalog.current_database();
select case when pg_catalog.count(*) = 1 then pg_catalog.min(version_num)
            else null end from public.alembic_version;
SHOW transaction_read_only;
```

SQLAlchemy also performs read-only dialect initialization queries. The verification
requires the matching cluster, `student_support_fixture`, sole revision
`1d7c8f2a6b91`, and read-only `on`, then rolls back. No fixture records are loaded or
modified. Connection/permission failures stop with sanitized output; there is no
retry against another target.

On actual success, output identifies the fixture target, matching identifier,
revision and read-only setting, followed by `identity check: VERIFIED` and exit 0.
A failed check is not proof of database identity. Send only redacted results and
exit code, never credentials. Temporary credential removal is reported only if
this helper created the variable; it makes no secure-memory-erasure claim.

## Remaining live boundaries

Until successful PostgreSQL verification is observed, the fixture's connected
cluster identity and revision remain unverified. The seeder dry-run requires its
own approved connection. Fixture writes require verified independent credentials,
a fixture-specific backup/rollback plan and approval of the exact seed/import
operation. No database creation/drop, fixture migration, application-database
access, cleanup or writes are approved.

The existing backend on 8001 has not been contacted. Starting/reconfiguring a live
fixture backend also requires approval of the exact target and lifecycle action;
do not start a second backend or change ports to evade this boundary.

## Verification evidence

| Check | Observed result | Exit code |
|---|---|---|
| Final guarded independent Python suite | 222 passed; 2 legacy socket/child checks deselected | 0 |
| Separate wrapper suite | 21 passed, including those 2 reviewed checks | 0 |
| Approved SQLite backend integration | 223 passed, including 106 overlapping mocked safety checks | 0 |
| Final strengthened SQLite runner smoke | 3 passed: in-memory auth/health and temporary migration/email fixtures | 0 |
| Final frontend mocked tests | 94 passed in 3 files | 0 |
| Final frontend production build | 1,666 modules; mock entry excluded | 0 |
| Final Python AST and PowerShell parsing | 83 Python sources and 3 PowerShell helpers parsed | 0 |

Counts above overlap and should not be added as a single test total. Backend
dependencies emitted 44 deprecation warnings; tests did not fail.

The full SQLite run used 56 guarded connections and counted 3,865 schema/write
statement attempts. This is an attempt count, not a committed row count. Targets
were `:memory:` plus `migration.db` and three `transfer-emails.db` files below:

`C:\Users\vvvsn\AppData\Local\Temp\northstar-sqlite-tests-0g_qy5zx`

After that run, the runner was strengthened to reject every SQL attachment
(`ATTACH`/`VACUUM INTO`) and extension load, wrap the native SQLite alias, and
protect the root application SQLite file against ordinary artifact writes.
Eight callback-only checks passed inside the final 222-test independent suite;
the final three-test SQLite smoke passed with six connections and 222 counted
schema/write statement attempts in a separate fresh temporary directory. The
reviewed full suite contained no attachment, native bypass or model fitting.

The saved-model API integration asserted 23 actual import receipts and 21
forecasts in in-memory SQLite and verified all 14 rejection cases. Authentication,
roles, student/coordinator access, support, analytics, constraints, rollback and
isolated SQLite migration behavior passed. No PostgreSQL result follows from
these tests.

No PostgreSQL server, port 5432, active `student_support` database, or existing
backend HTTP endpoint was accessed by the executed verification commands.
Approved SQLite test schema/records were created, changed and removed. No fixture
PostgreSQL seed/import/write was attempted. The agent created no fixture credential
variable; local-prompt cleanup awaits the user's actual result. Existing user
processes were not globally monitored, and no claim is made that unrelated
database activity or records remained unchanged.

PostgreSQL identity verification is approved but still awaits the user-entered
local prompt result. Fixture-specific backup, seed/import write approval and live
backend lifecycle approval remain outstanding. Visual desktop/mobile checks
remain unverified because browser automation stopped under its URL policy.

Current supported status: **READY FOR MOCKED DEMO ONLY**. No PostgreSQL success
is inferred from Docker names, port publication, source migrations, mocks or
SQLite results.
