# Coordinator upload test fixture (test-only)

These files test coordinator CSV validation and import in an **isolated development/test database only**. They are never training data. Do not upload them to a production installation.

| File | Purpose |
|---|---|
| `coordinator_upload_valid.test.csv` | 23 rows expected to be accepted once matching synthetic enrollments are seeded: 21 with the full eight-week sequence and 2 aggregate-only rows (all weekly fields blank, so no sequence forecast runs). |
| `coordinator_upload_rejections.test.csv` | 14 rows, each expected to be rejected for one documented reason. |
| `synthetic_enrollment_mapping.test-only.csv` | Test-only mapping from each synthetic number to its fixture row, case, expected outcome/field, seed values, and historical `source_record_id`. Never upload it. |
| `fixture_manifest.json` | Reserved range, collision-check summary, source partition, row counts, and SHA-256 of each file. |

## Synthetic enrollment numbers

- Reserved block: `2403031590000`–`2403031599999` (prefix `24030315`, sequential 5-digit suffix from `90000`). This fixture uses `2403031590000`–`2403031590035`.
- These numbers are **synthetic test identifiers**. They are not institution-issued, do not identify real students, and are not real active enrollments.
- The originally requested start `2403031500000`+ was not used: `…00001`–`…28785` were issued to OULAD learners by the retired legacy registry, and `…28786`–`…28793` belong to legacy and current application accounts. The generator fails if any synthetic number was already issued, repeats within the fixture, falls outside the block, or if the application allocator's high-water mark reaches the block.
- Enrollment numbers and `source_record_id` values are never model features.

## Source rows

Rows come unchanged from the student-disjoint held-out test partition (2014J after purging students seen in training or validation) of `data/processed/student_training_dataset.csv`, ordered by `source_record_id`. Missing observations stay blank, and no assessment or VLE values are invented. Rejection rows corrupt or withhold exactly one value, as documented below.

## Rejection cases

| Case | Expected field | Seeded? | What is wrong |
|---|---|---|---|
| `unknown_enrollment` | `enrollment_number` | no | Well-formed reserved number with no application enrollment |
| `module_presentation_mismatch` | `enrollment_number` | yes | Row says `2014B`; the seeded enrollment is `2014J` |
| `registration_metadata_mismatch` | `enrollment_features` | yes | `studied_credits` is 30 higher than the seeded enrollment |
| `inactive_enrollment` | `enrollment_number` | yes (inactive) | Enrollment exists but is inactive |
| `missing_enrollment_number` | `enrollment_number` | no | Blank |
| `malformed_enrollment_number` | `enrollment_number` | no | Only four digits after the prefix |
| `missing_code_module` | `features` | no | Required categorical blank |
| `malformed_numeric` | `early_vle_clicks` | no | Text value |
| `out_of_range_numeric` | `features` | no | `early_assessment_mean` = 150 |
| `non_integer_count` | `features` | no | `early_vle_active_days` = 3.5 |
| `partial_weekly_sequence` | `weekly_sequence` | no | Week 8 blank |
| `weekly_aggregate_mismatch` | `weekly_sequence` | no | Week 1 clicks +1 |
| `duplicate_enrollment_number_a`/`_b` | `enrollment_number` | yes (once) | Same number on two rows; both rejected |

## Regenerate

```powershell
.\.venv\Scripts\python.exe -m ml.fixtures.coordinator_upload
# Optional: add numbers read from the target test DB as extra collision sources
.\.venv\Scripts\python.exe -m ml.fixtures.coordinator_upload --known-ids-file known_ids.txt
```

## Verify the isolated fixture target before any connection

The only permitted fixture target is `student_support_fixture` at `127.0.0.1:5433`, belonging to the cluster in `northstar-local-db-1`. Port `5432` and the active application's `student_support` database on every port are prohibited. Docker port publication and a container-local cluster identifier do not establish the connected database's identity.

The following helpers require separately approved operations. Their presence in this README does not authorize a database connection or a write.

1. Approve the exact identity-only, read-only connection to `127.0.0.1:5433/student_support_fixture`. Then run this helper from an interactive local terminal:

   ```powershell
   .\scripts\verify_fixture_identity.ps1
   ```

   Enter fixture-specific credentials only at its masked local prompt. Never paste credentials into chat, command arguments, shell assignments/history, logs, or files. Do not reuse the root `.env` application credentials. The helper checks the guarded target and container metadata, reads the container-local identifier using `pg_controldata` without connecting to `POSTGRES_DB`, and compares the connected database name, cluster identifier, and Alembic revision inside a read-only transaction. A missing identity, mismatch, forbidden override, or unavailable privilege stops the operation. Success must be supported by the actual helper output; a previous report is insufficient.

2. After identity verification succeeds, obtain separate approval for the read-only fixture dry-run before running:

   ```powershell
   .\scripts\fixture_dry_run.ps1
   ```

   This operation checks the fixture mappings and reserved-number conflicts and reports planned counts. It does not seed records, import CSV rows, or enable write arguments. A successful dry-run is not proof that an import has occurred.

Both helpers preserve pre-existing environment values, reject conflicting application or libpq override variables, and remove a temporary fixture credential variable that they create in their own process. They fail if the seeder differs from the reviewed source. Keep the root `.env` unchanged. If a secure interactive terminal or fixture credentials are unavailable, stop the dependent operation and continue database-independent checks.

## Seed and import only after separate write approval

The exact approval-gated commands, expected counts, backup, verified fixture backend (`scripts/fixture_backend.py`, port 8002) and rollback are in [the fixture PostgreSQL runbook](../../../docs/fixture-postgres-runbook.md).

`scripts/seed_synthetic_upload_fixture.py` creates one inactive-login synthetic account per seeded number (`synthetic-upload-fixture-<number>@example.com`, unusable password hash, `access_approved=false`) with an enrollment that matches the mapping. There are 27 distinct seeded-number definitions. The mapping has 37 rows and 36 distinct numbers because the two duplicate rejection rows intentionally share one number.

Before any seed or CSV import write, require all of the following:

- Independently verified fixture database identity, guarded exact target, and fixture-specific credentials.
- A backup and rollback plan appropriate to the isolated fixture database, with evidence supporting its integrity.
- Separate explicit approval for the exact fixture write operation, including the intended target and affected records.
- Separate approval for application startup or live integration tests when needed for the API workflow.

No database creation, database drop, migration, fixture removal, or application database write is authorized by this workflow. If source/configuration or a dry-run shows that such an operation is required, stop and seek approval for that exact operation. Do not touch the active application database to populate the demo.

The seeder refuses the application target as written in `.env`, as rewritten to port 5433 by `scripts/with_isolated_db.py`, or as set in `DATABASE_URL`. It also refuses incorrect hosts, ports, database names, malformed URLs, query parameters, fragments, and all nine guarded libpq override variables. It obtains container identity before creating an engine and verifies the connected database and expected Alembic revision before fixture operations. Its default path is read-only; write functions and commits require explicit write authorization. Existing reserved numbers or marker accounts block seeding rather than being overwritten.

Seeding does not upload the CSV. With a separately approved backend targeting the verified fixture database, `POST /api/imports/validate` reports validation-only results without writing records. `POST /api/imports` performs the separately approved import and returns the actual import receipt. Report confirmed import counts only from that response. The valid fixture expects 23 eligible rows with 21 complete weekly sequences and 2 aggregate-only rows; missing sequence forecasts remain absent rather than becoming zero. The rejection fixture expects 14 rejected rows with the documented reasons above. Database-independent tests can verify these expectations with mocks; they do not establish a live import result.
