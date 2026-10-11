# Repository Cleanup Report

- **Audit date:** 2026-10-11
- **Scope:** `D:\AIML_BOOTCAMP\project\NorthStar`. All tracked, untracked, and ignored files outside `.git`, `.venv`, and `frontend/node_modules`.
- **Rollback:** Git is present (`main`, one commit `2bb118a`, remote `origin` = GitHub). There are no local remote-tracking refs, so it could not be confirmed whether `2bb118a` has been pushed. Every tracked file can be restored with `git checkout -- <path>`. Ignored files (caches, data, backups) have no git rollback.
- **Constraints observed:** No PostgreSQL connection. The backend `/health` endpoint was not called. `.env` was not modified. No packages were installed. No recursive force deletes were used.

## Final status

**SAFE CLEANUP COMPLETE — REVIEW LIST REMAINS**

## 1. What was audited

| Area | Contents | Size | Classification |
|---|---|---|---|
| `backend/` | FastAPI app, 7 Alembic migrations, 13 test modules | small | A, keep |
| `frontend/src`, `index.html`, `mock-demo.html` | React/Vite app plus the browser mock demo | small | A, keep |
| `frontend/dist` | Vite build output (ignored) | 589 KB | C, keep (see 5) |
| `ml/` code + `ml/saved_models/` | Pipelines; 9 model artifacts + `registry.json` | 107 MB | A/C, keep |
| `data/raw/oulad` | OULAD source CSVs (ignored) | 443 MB | C, keep |
| `data/processed`, `data/templates`, `data/test_fixtures` | Training data, registries, upload template, fixtures | 14 MB | A/C, keep |
| `database/demo_database.dump` | Demo DB dump | 21 MB | C, keep |
| `backups/db/` | Pre-cleanup DB dump + checksum (ignored) | 61 KB | C, keep |
| `student_support.db` | Root SQLite file (ignored) | 180 KB | C, keep |
| `scripts/` | Isolation wrapper, safety and fixture tools, test runners | small | A/C, keep |
| `tests/`, `backend/tests/` | Safety, regression, integration tests | small | A, keep |
| `docs/` | 17 docs | small | A, keep |
| `reports/` | 7 historical audit/verification folders | 2.9 MB | Owner review (see 4) |
| Root `_*.py` (21 files) | Ad-hoc debug and diagnostic scripts | 80 KB | **B, quarantined (see 3)** |
| `__pycache__/`, `.pytest_cache/` | Python bytecode and test cache | ~1.7 MB | **Removed (see 2)** |

## 2. Removed: cache files only

| Removed | Evidence it is safe |
|---|---|
| All `*.pyc` files under 21 project `__pycache__/` directories whose `.py` source exists, then the emptied directories (removed one at a time with `rmdir`) | Gitignored (`__pycache__/`, `*.py[cod]`). Python regenerates them on import. No script, test, or hash manifest under `reports/` references bytecode. |
| `.pytest_cache/` (5 files) | Gitignored. Pytest regenerates it, and it was recreated by the verification run below. |

`.venv/`, `frontend/node_modules/`, and `frontend/dist/` were **not** touched.

**Deliberately kept:** 5 orphaned bytecode files whose source no longer exists anywhere, on disk or in git:

- `scripts/__pycache__/reset_demo_credentials.cpython-313.pyc`
- `scripts/__pycache__/provision_local_demo.cpython-313.pyc`
- `backend/app/api/routes/__pycache__/demo_imports.cpython-313.pyc`
- `backend/app/services/__pycache__/csv_demo.cpython-313.pyc`
- `backend/tests/__pycache__/test_csv_demo.cpython-313-pytest-8.4.2.pyc`

Python never imports these, so they are dead at runtime. They are, however, the only remaining trace of that code. Delete them once you confirm the code is not wanted.

**Space recovered:** about 1.7 MB.

## 3. Moved to quarantine (owner-approved, 2026-10-11)

The 21 root `_*.py` debug scripts listed in 4a were moved to `D:\AIML_BOOTCAMP\project\_quarantine\NorthStar_20261011\`, outside the repository. Their checksums before the move are recorded in `MANIFEST.sha256` in that folder, and `sha256sum -c` confirmed all 21 files are intact after the move. In git, they appear as unstaged deletions. They have not been committed yet.

To restore them, run `git checkout -- <file>` or copy them back from the quarantine folder.

## 4. Proposed for removal: awaiting owner approval

### 4a. Root debug and diagnostic scripts (21 files, 80 KB). Risk: low. Owner approved quarantine on 2026-10-11; done, see section 3

These files are tracked in git, so they are reproducible with `git checkout`.

```text
_check_ids.py  _debug_asgi.py  _debug_asgi2.py  _debug_email.py  _debug_http.py
_debug_login.py  _debug_login2.py  _debug_pw.py  _debug_routes.py  _debug_routes2.py
_debug_verify.py  _diag.py  _diag2.py  _diag3.py  _diag_db.py  _fix_and_test.py
_query_db.py  _test_api.py  _test_direct.py  _test_fixes.py  _test_login.py
```

- **Purpose:** One-off debugging of a 401 login error and a 404 cluster lookup, written 2026-10-10 between 21:33 and 22:54.
- **Reference evidence:** A repo-wide search for each filename stem across source, configuration, scripts, tests, docs, `package.json`, and `.vscode/tasks.json` found no references. (The `_diag` stem matches only unrelated substrings.) None of them is collected by pytest, because the leading underscore does not match `test_*.py` or `*_test.py`.
- **Why they are a liability, not just clutter:**
  - 7 of them connect directly to the PostgreSQL instance on port 5432. That is the legacy database the project treats as off-limits.
  - 2 of them (`_debug_pw.py`, `_fix_and_test.py`) **write** to it with password and user updates.
  - 9 of them contain a hard-coded database password. Those files are committed in `2bb118a`, so deleting them does not remove the password from git history. **Rotate that credential**, and if the commit has been pushed, treat it as exposed.
  - Before this audit, `_test_fixes.py` also reset a user's password on port 5432 when login failed. That fallback was removed on 2026-10-11, and the script now only calls the HTTP API.
- **Quarantine:** completed. See section 3.

### 4b. `reports/` historical folders (2.9 MB). Risk: medium. Recommended action: keep, or archive outside the repo

Several folders hold `baseline_hashes.sha256` and `protected_subset.sha256` manifests that later reports cite as evidence. `docs/demo-stabilization.md` and the final stabilization report rely on that audit trail. No runtime code depends on these folders, but removing them breaks the audit trail. The decision is the owner's.

### 4c. Configuration issue found (fixed 2026-10-11, see section 9)

`.vscode/tasks.json` starts the backend ("Backend: Start FastAPI") and runs migrations ("Backend: Apply migrations") **without** `scripts/with_isolated_db.py`. Those tasks therefore read `.env` directly, which targets port 5432. `npm run backend` and `npm run migrate` use the wrapper correctly. Fixing the tasks changes developer behavior, so it is outside the scope of a file cleanup. It is recommended as a follow-up.

## 5. Intentionally preserved (Classes A and C)

- `.env`, `frontend/.env.local`, `.env.example` (contents not inspected or reported).
- `ml/saved_models/*`: loaded by `backend/app/ml/model_manager.py` and `ml/inference/prediction_service.py`.
- `backend/alembic/versions/*`: discovered by Alembic and exercised by `test_migrations.py`.
- `data/raw/oulad/*`, `data/processed/*`, `data/templates/student_upload_template.csv` (served by `routes/imports.py`), and the registries plus `.lock` files (`ml/identity_registry.py`).
- `data/test_fixtures/coordinator_upload/*` and `frontend/src/test/browser/fixtures/*`: byte-identical by design (SHA-256 matched). `frontend/src/test/browser/README.md` documents that the browser copies are checked against the source fixtures. They are **not** a removable duplicate.
- `frontend/mock-demo.html`, `frontend/src/test/browser/*`: referenced by `docs/demo-stabilization.md` and `mockApi.test.js`.
- `frontend/dist/`: reproducible, but listed in `reports/final_stabilization_20261010T051556Z/protected_subset.sha256` and in `docs/production-deployment.md`.
- `student_support.db`: on the protected-write list in `scripts/run_safe_tests.py`.
- `database/demo_database.dump`, `backups/db/*`: recovery artifacts.
- All safety files named in the cleanup brief, plus `scripts/fixture_readonly.ps1`, `check_fixture_target.py`, `verify_fixture_identity.py`, `run_safe_tests.py`, `run_sqlite_tests.py`, and `with_isolated_db.py`. Each is referenced by docs, other scripts, or tests.

## 6. Already deleted before the audit

`Northstar_Student_Performance_Demo.zip` (tracked) was already deleted in the working tree. This audit did not touch it. Restore it with `git checkout -- Northstar_Student_Performance_Demo.zip` if the deletion was unintended.

## 7. Verification actually performed

| Check | Result |
|---|---|
| SHA-256 of 87 protected files (`.env`, `frontend/.env.local`, `student_support.db`, `ml/saved_models`, `data/`, `database/`, `backups/`, migrations, `scripts/`, `docs/`, `frontend/dist`, browser fixtures), before and after | All unchanged |
| SHA-256 of all 324 tracked files, before and after | Unchanged, except `_test_fixes.py` (intentional edit) and the pre-existing zip deletion |
| `.\.venv\Scripts\python.exe -B .\scripts\run_safe_tests.py` | **235 passed, 2 deselected (by runner design), exit 0**. One NumPy deprecation warning from Keras. |
| `git status` after cleanup | Same as before the audit, apart from the `_test_fixes.py` edit |

The safe suite was run again after the quarantine move: **235 passed, 2 deselected, exit 0**.

**Not run, and why:**

- `scripts/run_sqlite_tests.py`: the cleanup did not affect test helpers or the import workflow.
- Frontend tests and build: no frontend file was touched.
- `backend.app.main` import check: the safe suite forbids it, and nothing outside the deleted caches changed.

## 8. Remaining uncertainty

- Whether commit `2bb118a` (which contains the hard-coded DB password) has been pushed to GitHub.
- Whether the code behind the 5 orphaned `.pyc` files (for example `reset_demo_credentials.py`) is wanted.
- Whether the owner wants `reports/` kept in the repository.

## 9. Follow-up, 2026-10-11

### 9a. Credential exposure (not rotated; awaiting approval; history cleaned, see section 10)

- **What leaked:** the PostgreSQL role `student_app` password. It equals both `POSTGRES_PASSWORD` and the `DATABASE_URL` password in `.env`, confirmed by a boolean comparison that never printed the value. It is committed in 8 of the quarantined scripts in `2bb118a`. No other `.env` secret (JWT key, invite code, Gemini key) appears in any committed file or inside the committed ZIP.
- **Exposure:** `origin` (`github.com/Nagesh-2926/NorthStar`) is **public but empty**, so `2bb118a` has not been pushed. The password still exists in the local `.git` objects and in the quarantine folder.
- **What depends on it:**
  - The `student_app` role on both `northstar-local-db-1` (5433, the app database) and `student-db-1` (5432, legacy). `with_isolated_db` changes only the port, so both containers use the same credential.
  - The backend (`npm run backend`) and migrations (`npm run migrate`), which reach it through `.env` and the wrapper.
  - `docker-compose.yml`, which reads `POSTGRES_PASSWORD` only when a container is first created.
  - The fixture tools `seed_synthetic_upload_fixture.py` and `check_fixture_target.py`, which compare against the app credentials to make sure fixture credentials differ.
- **Rotation plan (each step needs approval):**
  1. Stop the backend on port 8001.
  2. Confirm that `docker port northstar-local-db-1 5432/tcp` reports `127.0.0.1:5433`. Then run `docker exec -it northstar-local-db-1 sh -c 'psql -U "$POSTGRES_USER" -d student_support'` and use `\password student_app`. This uses a masked prompt, and the password never appears on a command line or in a log.
  3. Update `.env`: `POSTGRES_PASSWORD` and the password part of `DATABASE_URL` must match. Percent-encode `@`, `:`, `/`, `?`, and `#`. The new password must differ from the fixture role's password.
  4. `student-db-1` (5432) still accepts the leaked password. Touching it is outside the standing rules. Decide separately whether to rotate it, retire it, or leave it stopped.
  5. Restart with `npm run backend`. Check with `python -B -m scripts.reset_app_user_password --email <existing user>`, which is read-only.
- **History remediation before the first push:**
  1. Back up the current history outside the repo: `git bundle create ..\NorthStar_pre_rewrite.bundle --all`. Also copy the ZIP out of `HEAD`; it holds the only source copies of `provision_local_demo.py` and `reset_demo_credentials.py`.
  2. Rewrite the single commit so it no longer contains `_*.py` or the ZIP. The ZIP is 140 MB, which is over GitHub's 100 MB file limit, so a push would be rejected anyway. Expire the reflog and run gc.
  3. Rotate the password anyway, because copies of it remain on this machine.
- **If the commit had been pushed:** rotate first, then rewrite history (`git filter-repo`), force-push, ask GitHub Support to purge cached views, and treat any forks or clones as compromised.

### 9b. `.vscode/tasks.json` (fixed)

- **Change:** "Backend: Start FastAPI" now runs through `scripts.with_isolated_db --require-free-port 8001`, and "Backend: Apply migrations" runs through `scripts.with_isolated_db`. Both are identical to `npm run backend` and `npm run migrate`.
- **Left unwrapped on purpose:**
  - "Tests": `backend/tests/conftest.py` only uses `setdefault` to set `DATABASE_URL=sqlite://`, so wrapping the task would point the tests at the app database.
  - "ML: Retrain": `ml/` has no database access.
- **Proof:**
  - `tests/test_launcher_db_safety.py` checks every task and the npm `backend` and `migrate` scripts. It passes (9 passed), and it fails both original tasks when run against the `HEAD` version of the file.
  - A live run of the wrapper hands its child process `DATABASE_URL` port 5433.
  - `--db-port 5432` is refused.

### 9c. Coordinator 401: root cause (read-only investigation)

The backend on port 8001 was started through `with_isolated_db` (confirmed from its process tree), so it uses 5433.

A read-only query against `northstar-local-db-1`, with the port mapping verified first, showed that **`demo.coordinator@demo.example.com` does not exist in `student_support` on 5433**, and no `demo.*` account does. The 401 is the "unknown email" case, not a wrong password.

The scratch scripts that set `SecurePass1234` (`_debug_pw.py`, `_fix_and_test.py`) wrote to the legacy 5432 database. The original demo accounts were created by `scripts/provision_local_demo.py`, which uses the app's API and needs the invite code; its source survives only inside the ZIP in `HEAD`.

The app database has two coordinator accounts: the owner's account, and an audit end-to-end test account.

### 9d. Reset procedure: `scripts/reset_app_user_password.py` (new)

- **Target:** the root `.env` URL rewritten to 5433. The script refuses `DATABASE_URL` and `PG*` overrides.
- **Before connecting:** checks that port 5433 is published by `northstar-local-db-1` and that the container's cluster identifier is the pinned value.
- **After connecting:** checks the cluster identifier, `current_database() = student_support`, and Alembic head `1d7c8f2a6b91`.
- **Default mode:** verify only, in a read-only transaction.
- **Writing:** requires `--apply --confirm-target student_support@127.0.0.1:5433` and a masked password prompt. The identity checks run again inside the same transaction as the write. The script updates exactly one existing row and increments `token_version`. It never creates accounts.
- **Backup first:** `docker exec northstar-local-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d student_support -t users -Fc' > backups\db\users_<timestamp>.dump`
- **Tests:** `tests/test_reset_app_user_password.py` (18 passed, no database used).
- **Live verify-only run:** target verified, account not found, nothing changed (exit 1).

### 9e. Verification (actual results)

| Check | Result |
|---|---|
| New tests: launcher safety and reset guards | 27 passed |
| `scripts/run_safe_tests.py` | 235 passed, 2 deselected, exit 0 |
| `reports/` (105 tracked files) | Checksums unchanged |
| Quarantine `MANIFEST.sha256` | 21 of 21 intact |
| SQLite and frontend suites | Not run: no backend or frontend code changed |

## 10. GitHub push fix and history cleanup, 2026-10-11

### Why GitHub rejected the push

The only commit (`2bb118a`) contained two blobs over GitHub's 100 MiB limit for regular Git files:

- `Northstar_Student_Performance_Demo.zip`: 139.90 MiB
- `ml/saved_models/random_forest.joblib`: 101.26 MiB

The same commit also held the live `student_app` database password in 8 debug scripts. The remote is still empty (0 branches, size 0, `git ls-remote` exit 2), so nothing was ever published.

### What was rewritten

`2bb118a` was replaced by `accc163`. The new commit has the same author, dates, message, and all 316 other files byte-identical. It drops only these 10 paths:

- the ZIP
- `random_forest.joblib`
- `_check_ids.py`, `_debug_pw.py`, `_diag.py`, `_diag2.py`, `_diag3.py`, `_fix_and_test.py`, `_query_db.py`, `_test_fixes.py`

The rewrite used `git read-tree`, `git rm --cached`, `git commit-tree`, and `git update-ref` (`git filter-repo` is not installed). It was rehearsed first in a throwaway clone.

The old commit is still in the local reflog. It is never pushed, because a push sends only reachable objects. Purging it with `git reflog expire` and `git gc --prune=now` is a separate, approval-gated step.

### Local copies and recovery

Recovery folder: `D:\AIML_BOOTCAMP\project\_recovery\NorthStar_20261011\`. `MANIFEST.sha256` there covers 20 files.

- `NorthStar_history_pre_rewrite.bundle`: the full pre-rewrite history. `git bundle verify` exits 0. **It contains the leaked password**, so do not upload or sync it.
- `Northstar_Student_Performance_Demo.zip`: identical to the old Git blob, and every member's CRC checks out.
- `demo_zip_sources/`: `provision_local_demo.py`, `reset_demo_credentials.py`, and `TRANSFER_README.md`. The two scripts compile to bytecode identical to the orphaned `.pyc` files.
- `model/random_forest.joblib`: identical to the old Git blob (`f1d5915…`).
- `orphaned_bytecode/`: all 5 orphaned `.pyc` files. Three of them (`csv_demo`, `demo_imports`, `test_csv_demo`) have no source anywhere else.
- `uncommitted_work/`: the pre-rewrite index, the diff, the status, and the new and changed files.

The 21 quarantined scripts are still in `_quarantine\NorthStar_20261011\` and pass their own manifest check.

### Runtime dependency no longer in Git

`ml/saved_models/random_forest.joblib` stays in the working directory and is now listed in `.gitignore`.

- **App runtime:** does not need it. `registry.json` marks it `"selected": false`, and `model_manager` loads only the selected model.
- **Tests:** `tests/test_inference.py` and `tests/test_canonical_integrity.py` do load it. A fresh clone must restore it by copying `model\random_forest.joblib` from the recovery folder into `ml\saved_models\`, then confirming `git hash-object` reports `f1d59157f2734764680e694dd1ed655c3702270d`. Alternatively, run `python -m ml.supervised.train`, but that retrains every supervised model and changes `registry.json`.
- There is no download URL.

The ZIP is ignored as well. Its only copies are the recovery folder and the bundle.

### Database password rotation: dependency-aware procedure (not executed)

Facts, from read-only checks on 5433:

- `student_app` is the only login role, and it is a superuser.
- `pg_hba` trusts connections over the container's local socket and requires SCRAM for host connections.
- `log_statement=none`.
- One backend session is open.

The steps:

1. **Shared credential:** `student-db-1` (5432) has the same role and password. Rotating on 5433 does not rotate 5432, and after rotation `.env` will no longer match 5432. That is intended, because nothing should use 5432. The leaked password stays valid there until the owner decides separately to rotate or retire that container. Do not test either password against 5432.
2. **Stop the backend** (port 8001), any `npm run migrate`, and any fixture tool. Existing sessions keep working after an `ALTER ROLE`, but new connections fail until `.env` is updated.
3. **Check the target:** `docker port northstar-local-db-1 5432/tcp` must print `127.0.0.1:5433`.
4. **Change the password:** run `docker exec -it northstar-local-db-1 psql -U student_app -d student_support`, then `\password student_app`. The prompt is masked, and psql sends only a SCRAM verifier, so the plaintext never reaches the server or the shell history.
5. **Update `.env`:** set the new value in both `POSTGRES_PASSWORD` and the password part of `DATABASE_URL`, using percent-encoding where needed.
6. **Container configuration:** `docker inspect` will still show the old value in `POSTGRES_PASSWORD`. Postgres reads it only on first initialization, and the data volume keeps the new password.
   - Changing `.env` changes the Compose config hash, so a later `docker compose up` **recreates** the container.
   - The `.env` value `POSTGRES_PORT=5432` would then publish the app database on **5432**.
   - Only use `npm run db` (`docker start`). Any recreate must run with `POSTGRES_PORT=5433` set in that shell and `-p northstar-local`.
7. **Restart and verify:** run `npm run backend`. Then run `python -B -m scripts.reset_app_user_password --email <existing coordinator>`, which only verifies and connects with the new credential.
8. **Migrations and fixture tools:** `npm run migrate` and `npm run backend` read `.env` through the wrapper, so they pick up the change automatically. The fixture tools require fixture credentials that differ from the app credentials. Because no separate fixture login role exists on this cluster, they stay blocked until one is created, before and after rotation.
9. **After rotation:** the copies of the old password in the bundle, the quarantine, and the reflog are dead credentials. Delete them only with approval.
