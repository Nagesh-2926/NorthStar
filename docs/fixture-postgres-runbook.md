# Fixture PostgreSQL runbook — seed, import, verify, roll back

Test-only procedure for proving the coordinator upload end to end against the isolated
fixture database. Nothing here is authorized by being written down: each step marked
**approval** needs explicit approval of that exact operation before it runs.

## Target

| Item | Value | How it is established |
|---|---|---|
| Database | `student_support_fixture` | `verify_target` (exact name) and `current_database()` in a read-only transaction |
| Address | `127.0.0.1:5433` | exact authority check; 5432 and `student_support` refused on every port |
| Container | `northstar-local-db-1` (`5432/tcp -> 127.0.0.1:5433`) | `docker ps --filter publish=5433` must return exactly this name |
| Cluster identifier | `7694699641731592226` | `pg_controldata` in the container (no connection), then `pg_control_system()` on the connection |
| Alembic revision | `1d7c8f2a6b91` (sole row) | `public.alembic_version` |
| Reviewed seeder SHA-256 | `8CC0215A…81B4F26` | `fixture_readonly.ps1` and `fixture_backend.py` refuse a changed seeder |

The application database `student_support` lives in the same container (same cluster
identifier), so the cluster check alone never proves isolation; the database-name check does.
The application backend on 8001 and `npm run backend` always target `student_support` and are
never used here.

## Operations

| Step | Operation | Writes | Status |
|---|---|---|---|
| 0 | Dedicated fixture login (only if none exists) | cluster role catalog, fixture grants | **approval** |
| 1 | Identity check | none | approved; needs your masked prompt |
| 2 | Seeder dry run | none | **approval** |
| 3 | Pre-seed backup | backup file only | **approval** |
| 4 | Seed 27 synthetic accounts | fixture DB | **approval** |
| 5 | Fixture backend on 8002 + frontend on 5174 | none at start | **approval** |
| 6 | Register one fixture coordinator | fixture DB | **approval** |
| 7 | Validate and import the fixture CSVs | fixture DB | **approval** |
| 8 | Verification queries | none | with step 7 |
| 9 | Rollback | fixture DB | only if needed; **approval** |

Run every command from `D:\AIML_BOOTCAMP\project\NorthStar` in an interactive PowerShell
terminal with no `DATABASE_URL` or `PG*` variables set. Enter credentials only at hidden
prompts — never in chat, arguments, files or `.env`.

### 0. Dedicated fixture login (only if you have none)

The helpers refuse the application's credentials. If no separate fixture login exists, a
cluster administrator creates one, connected to the fixture database only:

```powershell
docker exec -it northstar-local-db-1 psql -U <cluster-admin-role> -d student_support_fixture
```

```sql
CREATE ROLE northstar_fixture LOGIN;
\password northstar_fixture
GRANT CONNECT ON DATABASE student_support_fixture TO northstar_fixture;
GRANT USAGE ON SCHEMA public TO northstar_fixture;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO northstar_fixture;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO northstar_fixture;
GRANT EXECUTE ON FUNCTION pg_control_system() TO northstar_fixture;
```

The table and sequence grants apply only to `student_support_fixture`, the database this
session is connected to. The function grant lets the identity check read the cluster identifier;
it exposes no table data. Roles are cluster-wide: PostgreSQL's default `PUBLIC` connect
privilege lets this role open a session on `student_support`, but it has no table privileges
there and PostgreSQL 16 grants no `CREATE` on `public`; it is never used against that database.
Do not revoke anything on `student_support` as part of this procedure.

The fixture URL is then `postgresql+psycopg://northstar_fixture:<password>@127.0.0.1:5433/student_support_fixture`
(percent-encode `@ : / ? #` in the password).

### 1. Identity check

```powershell
.\scripts\verify_fixture_identity.ps1
```

Success is only: `identity check: VERIFIED; fixture writes were not attempted`, exit code 0,
and `temporary fixture variable removed from this process: True`.

### 2. Dry run

```powershell
.\scripts\fixture_dry_run.ps1
```

Read-only: no write argument is accepted or passed; the seeder sets `SET TRANSACTION READ ONLY`
before any query, issues only SELECTs and rolls back. Expected:

```
target=student_support_fixture@127.0.0.1:5433 container=northstar-local-db-1 action=seed mode=dry-run (read-only, nothing written)
synthetic_accounts=27 inactive_enrollments=1
numbers=2403031590000..2403031590035
```

`Refusing to run: N synthetic numbers or marker emails already exist` means the fixture was
already seeded — stop; do not seed again.

### 3. Pre-seed backup

Inside the container, `127.0.0.1:5432` is that container's own server (published to the host as
5433); the legacy `student-db-1` is a different container and is unreachable there. `pg_dump`
asks for the fixture password at its own hidden prompt (`-W`).

```powershell
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$name = "student_support_fixture_pre_seed_$stamp.dump"
docker exec -it northstar-local-db-1 pg_dump -h 127.0.0.1 -p 5432 -U northstar_fixture -W -d student_support_fixture -Fc -f "/tmp/$name"
docker exec northstar-local-db-1 pg_restore --list "/tmp/$name" | Select-String 'dbname:|TOC Entries'
docker cp "northstar-local-db-1:/tmp/$name" "backups\db\$name"
docker exec northstar-local-db-1 rm "/tmp/$name"
(Get-FileHash "backups\db\$name" -Algorithm SHA256).Hash | Out-File -Encoding ascii "backups\db\$name.sha256"
```

Integrity evidence: `pg_restore --list` shows `dbname: student_support_fixture` and a nonzero
TOC count, the copied file is nonzero, and its SHA-256 is recorded. `backups/` is gitignored.

### 4. Seed

```powershell
$s = Read-Host 'Fixture URL (hidden)' -AsSecureString
$env:NORTHSTAR_TEST_DATABASE_URL = [Net.NetworkCredential]::new('', $s).Password; Remove-Variable s
.\.venv\Scripts\python.exe -B -I scripts\seed_synthetic_upload_fixture.py --apply --confirm-target student_support_fixture@127.0.0.1:5433
Remove-Item Env:\NORTHSTAR_TEST_DATABASE_URL
```

The seeder repeats the target guard, container identity, connected-database and revision
checks before writing. Expected: `action=seed mode=APPLIED`, `synthetic_accounts=27
inactive_enrollments=1`. It creates 27 users (`synthetic-upload-fixture-<number>@example.com`,
unusable password, active, `access_approved=false`), 27 students and 27 enrollments
(`2403031590026` inactive) in one transaction.

### 5. Fixture backend and frontend

Terminal A:

```powershell
.\.venv\Scripts\python.exe -B scripts\fixture_backend.py
```

It prompts for the fixture URL (hidden), refuses unless the seeder is the reviewed source,
port 8002 is free, the target guard passes, the container identifier matches and a read-only
connection reaches `student_support_fixture` at `1d7c8f2a6b91`. Only then does it start uvicorn
on `127.0.0.1:8002` with that URL as the child's `DATABASE_URL`, CORS limited to
`http://127.0.0.1:5174`, and student number allocation redirected to a fixture-only registry in
`%TEMP%\northstar-fixture-backend` so `data/processed/application_enrollment_registry.json` is
never written. Other settings (JWT secret, invite code) are read from `.env` unchanged.
`http://127.0.0.1:8002/health` is safe to call: it queries the fixture database.

Terminal B:

```powershell
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8002/api'
npm --prefix frontend run dev -- --host=127.0.0.1 --port=5174 --strictPort
```

Process environment overrides `frontend/.env.local`, so this frontend talks only to 8002.

### 6. Fixture coordinator

Open `http://127.0.0.1:5174/register`, choose Coordinator, use a fixture-only address such as
`fixture-coordinator@example.com`, and enter the `COORDINATOR_INVITE_CODE` from your backend
environment. Do not register students on the fixture backend. Creates 1 user.

### 7. Validate and import

At `http://127.0.0.1:5174/coordinator/imports`:

| File (from `data/test_fixtures/coordinator_upload/`) | Action | Expected actual result |
|---|---|---|
| `coordinator_upload_valid.test.csv` | Validate | 23 valid, 0 rejected; 21 rows with weekly sequences |
| same | Import and analyze | receipt: 23 imported, 0 rejected, 21 forecasts saved, 2 not generated |
| `coordinator_upload_rejections.test.csv` | Validate | 0 valid, 14 rejected (unknown …023, module mismatch …024, metadata mismatch …025, inactive …026, rows 6–13 field errors, duplicates rows 14–15) |
| same | Import and analyze | HTTP 422 "nothing was imported"; no records written |
| valid file again (optional) | Import and analyze | "already imported"; no new records |

Report counts only from the actual receipt.

### 8. Verification queries (read-only)

```powershell
docker exec -it -e PGOPTIONS='-c default_transaction_read_only=on' northstar-local-db-1 psql -h 127.0.0.1 -p 5432 -U northstar_fixture -W -d student_support_fixture
```

```sql
select current_database(), (select system_identifier from pg_control_system());  -- student_support_fixture | 7694699641731592226
select count(*) from users where email like 'synthetic-upload-fixture-%@example.com';   -- 27
select count(*) from enrollments e join students s on s.id = e.student_id
  join users u on u.id = s.user_id
  where u.email like 'synthetic-upload-fixture-%' and not e.is_active;                 -- 1
select count(*) from users where role = 'coordinator';                                 -- 1
select count(*) from dataset_imports;                                                  -- 1
select count(*) from imported_feature_snapshots;                                       -- 23
select count(*) filter (where model_name = 'lstm_weekly') as forecasts,
       count(*) filter (where model_name <> 'lstm_weekly') as supervised from predictions; -- 21 | 23
select count(*) from behavioral_clusters;                                              -- 23
```

### 9. Rollback

Stop both fixture terminals (Ctrl+C). Before any import, `seed_synthetic_upload_fixture.py
--remove --apply --confirm-target …` removes only marked synthetic accounts (it refuses once
imports reference them). After an import, restore the step-3 backup into the fixture database
as its owner:

```powershell
docker cp "backups\db\<name>.dump" northstar-local-db-1:/tmp/restore.dump
docker exec -it northstar-local-db-1 pg_restore -U <fixture-database-owner> -d student_support_fixture --clean --if-exists --single-transaction /tmp/restore.dump
docker exec northstar-local-db-1 rm /tmp/restore.dump
```

Then rerun step 1 and the step-8 counts (expect 0 synthetic users, 0 imports). Delete
`%TEMP%\northstar-fixture-backend` if it exists.

## Why the active database is excluded

- Every connecting helper refuses `student_support`, port 5432, any URL equal to the root `.env`
  target or its 5433 rewrite, `DATABASE_URL`, libpq overrides, and the application's credentials.
- Every connection re-checks `current_database()` = `student_support_fixture` before work.
- The fixture backend is a separate process on 8002 whose only database URL is the verified one;
  the 8001 backend, its `/health`, and `npm run backend` are not used.
- `pg_dump`, `pg_restore` and `psql` above name `-d student_support_fixture` explicitly.
- Backups and verification only read; rollback restores only into the fixture database.
