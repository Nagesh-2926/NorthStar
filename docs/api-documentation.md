# Backend API

The FastAPI OpenAPI schema is served at `/openapi.json`; interactive Swagger UI is at `/docs` and ReDoc at `/redoc`. All business routes are under `/api`. JSON errors use `{"detail": ...}`. Request validation returns 422 locations/messages without echoing submitted values; unexpected errors return a generic 500 message while details stay in server logs.

## Authentication and authorization

Send `Authorization: Bearer <access_token>` to protected routes. `POST /api/auth/register` creates students by default and allocates an application enrollment number. New student record routes remain blocked until a coordinator approves the student's access request; `/api/students/me` and `/api/access-requests/me` remain available to submit/check a request. The student must provide their own assigned number; it is not an access credential. A coordinator account can be registered only with the server-side `COORDINATOR_INVITE_CODE`; public role selection without that invite is denied. `POST /api/auth/login` returns a short-lived HS256 JWT; `GET /api/auth/me` returns the current public account. Student access is checked in the backend against the authenticated account. Cross-student IDs return 404 to avoid confirming another profile exists. Coordinators are required for monitoring, mutation, inference, intervention, and aggregate analytics operations.

### Authentication routes

| Method | Path | Access | Request / result |
|---|---|---|---|
| POST | `/api/auth/register` | Public; coordinator invite required for that role | `{email,password,role? ,invite_code?}` → public user, 201; duplicate → 409 |
| POST | `/api/auth/login` | Public | `{email,password}` → `{access_token,token_type,expires_in}`; invalid credentials → 401 |
| GET | `/api/auth/me` | Authenticated | Public account profile |
| GET | `/api/access-requests/me` | Student | Own enrollment number, access status, and request status |
| POST | `/api/access-requests` | Student | Submit/re-submit `{enrollment_number}` matching this account's assigned number |
| GET | `/api/access-requests` | Coordinator | List pending requests with the student's account email and courses |
| PATCH | `/api/access-requests/{request_id}` | Coordinator | `{status:"approved"|"rejected"}`; approved status unlocks only the requester's account |

Passwords require at least 12 characters including uppercase, lowercase, and a digit; they are stored only as Argon2 hashes.

### Students and records

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/students/me` | Student | Own profile and enrollments |
| GET | `/api/students` | Coordinator | Paginated roster (`offset`, `limit`, max 200) |
| GET | `/api/students/{student_id}` | Own student or coordinator | Profile and enrollments |
| POST | `/api/students/{student_id}/enrollment-number` | Coordinator | Idempotently assign a stable application ID to a legacy account missing one |
| POST | `/api/students/{student_id}/enrollments` | Coordinator | Add an enrollment; optional `registration_day`, `num_of_prev_attempts`, and `studied_credits` populate source context |
| GET | `/api/enrollments/{enrollment_id}/assessment-schedule` | Coordinator | Read the scheduled assessments before editing them |
| PUT | `/api/enrollments/{enrollment_id}/assessment-schedule` | Coordinator | Replace schedule entries containing `assessment_key`, relative `scheduled_day`, and optional weight |
| GET | `/api/students/{student_id}/performance` | Own student or coordinator | Academic records; optional `enrollment_id` |
| POST | `/api/students/{student_id}/performance?enrollment_id=...` | Coordinator | Add a typed academic record, score 0–100 |
| GET | `/api/students/{student_id}/engagement` | Own student or coordinator | Weekly engagement records; optional `enrollment_id` |
| POST | `/api/students/{student_id}/engagement?enrollment_id=...` | Coordinator | Add/update an enrollment week (0-60), including totals and distinct `active_site_ids`/`activity_types` arrays |

Assessment schedule keys are the string form of OULAD `assessments.id_assessment`; schedule days come from `assessments.date`. For `assessment_score` records, top-level `assessment_key` identifies that schedule row and `submitted_day` stores `studentAssessment.date_submitted`; the schema enforces one score per assessment per enrollment. Weekly engagement inputs represent OULAD `studentVle.sum_click`, distinct `date` values, `id_site` values, and distinct `vle.activity_type` values. The API stores aggregates and small metadata only, not raw CSV rows.

### Prediction and clusters

Prediction and cluster requests are coordinator-only and carry only `enrollment_id`. The backend assembles `oulad-early-risk-v2` features from the enrollment's registration context, assessment schedule/scores, and weekly VLE aggregates. It applies the same day 0-55 cutoff and definitions as Phase 2, validates the feature ranges and ordering, then calls cached serialized models; it never trains during an API request. Weeks 0-7 must each have an explicit record before supervised, LSTM, or clustering inference. An observed week with no platform activity is represented by an explicit zero-valued record. Missing history returns 409 with an "Insufficient historical data" detail and does not persist a result. Client-supplied feature dictionaries and LSTM sequences are rejected as extra fields.

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/predictions/{student_id}` | Coordinator | Supervised inference and persisted prediction |
| POST | `/api/predictions/{student_id}/sequence` | Coordinator | LSTM inference from eight explicitly recorded, database-derived ordered weeks of `[weekly_clicks, weekly_active_days]`; missing week history returns 409 |
| POST | `/api/predictions/{student_id}/grade-score` | Coordinator | Persisted numeric final-exam score estimate; trained target exists only for CCC and DDD, using day-56 features |
| GET | `/api/predictions/{student_id}` | Own student or coordinator | Prediction history; optional `enrollment_id` |
| GET | `/api/predictions/{student_id}/grade-score` | Own student or coordinator | Numeric final-exam score history; optional `enrollment_id` |
| GET | `/api/predictions` | Coordinator | Recent persisted predictions |
| POST | `/api/clusters/{student_id}` | Coordinator | K-Means assignment from the nine database-derived engagement features; persisted |
| GET | `/api/clusters` | Coordinator | Recent cluster assignments |
| GET | `/api/students/{student_id}/cluster` | Own student or coordinator | Latest cluster, optional `enrollment_id` |

### Coordinator CSV imports

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/api/imports/template` | Coordinator | Download the header-only inference template |
| POST | `/api/imports/validate` | Coordinator | Validate multipart `file` without persisting results |
| POST | `/api/imports` | Coordinator | Validate, call saved supervised/cluster models and optional complete-week LSTM, and atomically persist outputs and source snapshots |

The CSV API accepts at most 20 MB and 5,000 rows in one upload. Both operations use multipart field `file`; browser clients must leave the content type unset so the browser supplies the multipart boundary. Validation reports total, valid, and invalid rows plus row-level errors. Valid rows must match an active application enrollment and course; duplicate/unknown/inactive identities, outcome labels, malformed numeric values, and incomplete weekly sequences are rejected without creating or modifying students or enrollments. Import runs supervised inference for each valid row and batch-assigns each row with the saved K-Means model. Exact byte-for-byte replays return existing record IDs without re-running inference. Aggregate CSV features are stored as snapshots and are never converted into fabricated assessment or day-level engagement rows. See [CSV import details](csv-import.md).

Example supervised request (features are assembled on the server):

```json
{"enrollment_id":"a4b21f59-60f3-4be3-89c3-cd4f2592a719"}
```

Responses include `support_priority_score`, threshold, review band, model/feature version, observed numeric signals, and a human-review interpretation. They are not deterministic judgments. Missing model artifacts return 503; source values outside the feature contract return 422; enrollment mismatch returns 404.

### Interventions, study plans, and analytics

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/api/interventions` | Coordinator | Create an enrollment-linked support action |
| GET | `/api/interventions` | Student sees own; coordinator sees all | List actions |
| PUT | `/api/interventions/{id}` | Coordinator | Update status/title/notes/due date |
| GET | `/api/students/{student_id}/study-plan` | Own student or coordinator | List plans; optional `enrollment_id` |
| POST | `/api/students/{student_id}/study-plan` | Own student or coordinator | Generate from the latest saved prediction and minimal context; local fallback if LLM unavailable |
| PUT | `/api/students/{student_id}/study-plan/{plan_id}/progress` | Plan owner (student) only | Save completed goal indices; goal indices must exist in the plan |
| GET | `/api/students/{student_id}/motivational-messages` | Own student or coordinator | List generated/fallback messages |
| POST | `/api/students/me/support-assistant` | Student | Ask a question grounded in that student's own stored records and approved context; unavailable provider returns 503 |
| GET | `/api/analytics/overview` | Coordinator | Population totals, review/outcome-signal counts, recorded-score bands, intervention statuses, and latest import summary |
| GET | `/api/analytics/risk-trends?days=30` | Coordinator | Daily prediction counts and mean scores (1–365 days) |
| GET | `/api/analytics/engagement` | Coordinator | Weekly mean recorded clicks/active days |
| GET | `/api/analytics/monitoring/students` | Coordinator | Paginated/searchable roster with each student's latest model review; supports `risk_filter`, `sort_by`, and `sort_order` |
| GET | `/api/analytics/clusters` | Coordinator | Latest enrollment cluster profiles with observed medians and distinct student/enrollment counts |

Study-plan generation sends a pseudonymous priority band, recent scores, coarse activity counts, observed early-feature summaries, intervention statuses, and scheduled assessment keys. It excludes names, email, student ID, demographics, and free-text records. LLM outputs are schema-checked and filtered for unsafe language; provider errors or unsafe output use a local supportive plan. Students can mark only goals in their own saved plan as complete.

The support assistant is separate from plan generation: it receives the authenticated student's own stored prediction summary, academic and weekly engagement records, intervention status and due dates, saved plan, scheduled assessment keys, and approved course metadata. Free-text intervention titles and notes are excluded from the provider prompt. It receives no other student's data or unstored course content. It must say when information is not recorded; provider/configuration errors are surfaced as 503 rather than fabricated with a local answer. Student accounts cannot use the coordinator's population analytics.

The supervised model is an end-of-course Fail/Withdrawn support classifier, not a calibrated probability and not a numeric grade model. The weekly LSTM has the same Fail/Withdrawn target, so it is not dropout-specific; it requires eight explicitly stored weeks and otherwise has no forecast. The coordinator overview's weekly-outcome counts describe saved model review bands, not confirmed student outcomes. Score bands summarize recorded scores only.

Set server-side `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, and optionally `GEMINI_MODEL` to use Google's GenerateContent REST API. The API key is sent in the `x-goog-api-key` header. Alternatively, configure the generic adapter with `LLM_PROVIDER=http_json`, `LLM_ENDPOINT`, and `LLM_API_KEY`; it sends a bearer-authenticated JSON POST with `system_prompt`, `user_prompt`, and `response_format`, and expects a JSON response with a string `content` or `output` field containing the generated JSON. The default `disabled` provider is fully functional for local study-plan fallback; assistant questions require a configured provider.

SMTP notifications are optional and require `SMTP_HOST` plus `SMTP_FROM_EMAIL`; credentials can be provided with `SMTP_USERNAME` and `SMTP_PASSWORD`. They are sent after intervention creation/status updates and study-plan creation. Sending errors do not undo saved records. Tests mock SMTP; delivery must be verified in the deployment environment.

## Status codes

- 400: malformed business operation (reserved for future domain checks)
- 401: missing, expired, or invalid bearer token; invalid login
- 403: authenticated role lacks permission or coordinator invite is invalid
- 404: resource absent or outside a student's ownership scope
- 409: duplicate account/enrollment, a study-plan prerequisite is missing, or early weekly history is incomplete for model scoring
- 422: schema, value, or feature-contract validation failure
- 500: unexpected server error with internal detail logged only
- 503: required ML artifact/service unavailable; study-plan LLM failures are handled locally instead
