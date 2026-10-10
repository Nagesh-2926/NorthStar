# OULAD identity boundary and processed dataset schema

## Separate identity domains

OULAD is a historical research dataset. Its `id_student` value identifies an anonymized source learner; it is not an application account or `enrollment_number`. One OULAD row in the canonical dataset represents one student-course-presentation record, keyed by:

`(code_module, code_presentation, id_student)`

`source_record_id` is a stable historical key generated as `oulad:student-course:v1:<sha256>`, where the digest is computed from the canonical JSON tuple `("OULAD", 1, code_module, code_presentation, id_student)`. The original source key remains available in `source_student_id`, `code_module`, and `code_presentation`. This value is explicitly namespaced and cannot match the application's enrollment-number format.

`data/processed/student_training_dataset.csv` is the canonical, derived OULAD training export. It has one row for every eligible student-course record and contains the source identity columns, the ordered model feature contract, the training-only `early_support_label`, and eight weekly click/day pairs. It contains no `enrollment_number`, login identity, or demographic field. OULAD records are not imported into live `Student` or `Enrollment` tables. The legacy `scripts/import_oulad.py` command now refuses to write and points to the file-only exporter.

The application continues to assign `enrollment_number` to real application accounts. New assignments are stored in `data/processed/application_enrollment_registry.json`, an application-account-only registry. The old `enrollment_mapping_registry.json` is preserved and read only as a compatibility source: an exact prior `application-account:<student UUID>` mapping is retained, and its highest assigned value is used as a collision-avoidance high-water mark. Historical OULAD digest entries are never returned as application identities. No database migration is required; the `students.enrollment_number` field and coordinator validation stay unchanged.

If a verified historical-to-live link is ever required, it must be explicit and auditable. A future mapping table must have a unique `(source_system, source_record_id)` key, a unique application enrollment foreign key, mapping method, evidence/provenance, verifier, and verification timestamp. No such link is currently inferred or created.

## Canonical source joins

The seven raw CSVs are read-only. The feature builder uses these documented keys:

| Source | Join key / relationship |
|---|---|
| `studentInfo.csv` | One source learner-course row per `(code_module, code_presentation, id_student)`; supplies prior attempts, studied credits, final result, and the source student-course population. Demographic fields are excluded. |
| `studentRegistration.csv` | One-to-one on `(code_module, code_presentation, id_student)`; supplies `date_registration` and withdrawal timing. |
| `courses.csv` | One row per `(code_module, code_presentation)`; validates course-presentation keys for assessments. |
| `assessments.csv` | `id_assessment` identifies the assessment and joins to `courses.csv` by `(code_module, code_presentation)`. |
| `studentAssessment.csv` | Joins to `assessments.csv` by `id_assessment`; the assessment contributes the module, presentation, and scheduled day, while `id_student` completes the student-course key. |
| `vle.csv` | One site metadata row per `(code_module, code_presentation, id_site)`. |
| `studentVle.csv` | Joins to the learner by `(code_module, code_presentation, id_student)` and to site metadata by `(code_module, code_presentation, id_site)`. It is streamed in chunks. |

The source builder rejects duplicate student-course, course-presentation, assessment, or VLE site keys and rejects unmatched assessment/course/site references in the feature window. The current source snapshot has 32,593 `studentInfo` and `studentRegistration` rows, 22 courses, 206 assessments, 173,912 assessment submissions, 6,364 VLE site metadata rows, and 10,655,280 student-VLE rows. All checked join keys resolve in this snapshot.

## Feature and sequence contract

The shared feature names and order come from `ml/features/build_dataset.py` and are used by training, model artifacts, backend inference assembly, and the coordinator CSV parser. Prediction inputs observe only course-relative days 0-55 (prediction day 56). Fitted imputers, categorical encoding, and scaling are stored inside the supervised model pipeline and fitted on training partitions only.

Feature order:

`registration_day`, `num_of_prev_attempts`, `studied_credits`, `early_assessment_mean`, `early_assessment_count`, `early_on_time_rate`, `early_assessment_coverage`, `early_vle_clicks`, `early_vle_active_days`, `early_vle_active_weeks`, `early_vle_active_sites`, `early_vle_activity_types`, `code_module`, `code_presentation`.

- `registration_day` is the course-relative `date_registration`, censored to missing at or after day 56.
- Assessment mean/count/on-time rate use scored submissions with scheduled and submitted days both in 0-55. Coverage is eligible scored assessments divided by assessments scheduled in 0-55; it is zero when assessments are scheduled but no valid score exists, and missing only when none are scheduled. The count is zero if no eligible score exists.
- VLE clicks sum `sum_click`; active days count distinct dates; active weeks count weeks 0-7 with positive click totals; sites and activity types count distinct mapped source values, all restricted to dates 0-55. Missing VLE aggregates are zero.
- `early_support_label` is training-only: Fail or Withdrawn outcomes that are still future outcomes on day 56. Withdrawals before day 56 and withdrawals with unknown timing are excluded from the cohort.
- Weekly fields are `week_1_clicks`, `week_1_active_days` through week 8. Each week is a distinct seven-day interval within days 0-55. Canonical OULAD export and training use eight zero-valued windows when the complete source log has no rows for a learner-week, matching the current LSTM training semantics. Click totals, active-day totals, and the count of positive-click weeks must reconcile with the three aggregate VLE features.

Coordinator uploads have a separate, header-only `data/templates/student_upload_template.csv`. It uses `enrollment_number` plus the same feature order and optional all-or-none weekly columns. The production parser requires that ID to resolve to an active application enrollment with the same module and presentation; OULAD source keys are never accepted or converted. If weekly columns are supplied, all 16 must be present and aggregate weekly clicks, active days, and positive-click weeks must equal the aggregate features. A missing coordinator observation is not filled with zero.

## Rebuild

Rebuild only the historical canonical data and weekly features, without model training or database writes:

```powershell
.\.venv\Scripts\python.exe -m ml.features.export_canonical
```

The full model training command uses the same feature builder and canonical writer, then trains and evaluates candidate models. It must be run only when retraining is intended; it is not needed when only source identities or export metadata change.
