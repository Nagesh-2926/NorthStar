# Historical OULAD identity boundary

OULAD source learners are not application students. The source provides anonymized `id_student` values, not verified live enrollment numbers. Therefore historical OULAD rows must not be inserted into the application's `Student` or `Enrollment` tables, assigned synthetic `enrollment_number` values, or used to infer a link to a real student.

The former database importer at `scripts/import_oulad.py` is now a refusal-only safety guard. It does not connect to a database. Running it exits with a message directing the operator to the canonical file exporter. This prevents a future setup command from re-creating the old identity conflation. Previously imported database rows, if any, are left untouched; this change performs no database migration or record cleanup.

To build historical ML features without database writes or model training:

```powershell
.\.venv\Scripts\python.exe -m ml.features.export_canonical
```

The exporter verifies the seven-file source manifest, applies the versioned day-56 feature contract, writes the historical canonical training table, and writes the derived weekly sequence artifacts. Original CSVs remain unchanged. The supervised, grade-score, clustering, and LSTM model pipelines continue to use historical source data and their own evaluation protocols. Runtime inference and Coordinator CSV uploads continue to use the shared feature names and require real application enrollment identity where applicable.

If a future requirement needs a source-to-application identity link, do not guess from IDs or feature values. Add an explicitly reviewed mapping table with uniqueness constraints, an application enrollment foreign key, provenance/evidence, verifier, and verification timestamp. There is no active historical-to-live mapping table or automatic mapping.
