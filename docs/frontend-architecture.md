# Frontend architecture (Phase 4)

The client is a JavaScript React single-page application built with Vite. It calls the FastAPI REST API only; it has no database connection, model-file access, or direct LLM provider integration. The API base URL comes from `VITE_API_BASE_URL` (default: `http://127.0.0.1:8001/api`). The backend's `CORS_ORIGINS` setting must allow the frontend origin.

## Route map

| Route | Role | Purpose |
|---|---|---|
| `/login`, `/register` | Public | Sign-in and student registration |
| `/student/dashboard` | Student | Academic, engagement, review, and study-plan overview |
| `/student/performance` | Student | Recorded academic results and history |
| `/student/engagement` | Student | Weekly VLE activity summaries |
| `/student/predictions` | Student | Saved support-review history and observed inputs |
| `/student/interventions` | Student | Support actions recorded for the selected enrollment |
| `/student/study-plan` | Student | Optional study recommendations and create action |
| `/student/motivation` | Student | Supportive message history |
| `/student/profile` | Student | Account and course enrollment information |
| `/coordinator/dashboard` | Coordinator | Aggregate student, review, cluster, and intervention views |
| `/coordinator/students` | Coordinator | Searchable, filterable, sortable, paginated roster |
| `/coordinator/students/:studentId` | Coordinator | Student records, reviews, cluster, and support actions |
| `/coordinator/clusters` | Coordinator | Persisted cluster profiles with median feature summaries |
| `/coordinator/interventions` | Coordinator | Support-action status and history |

The route guards use the role returned by `GET /api/auth/me`, and the backend enforces authorization independently on every protected endpoint. Coordinator access is never granted from a client-selected role. Registration defaults to student; coordinator creation remains subject to the backend invite rule.

## API and session handling

`src/api/client.js` owns the Axios instance, API base URL, bearer header, and expired-session handling. `src/api/services.js` maps page operations to API routes. Components consume those service functions through `useResource`, which exposes loading, retryable error, and loaded states. A 401 clears the local token and returns the user to sign-in; 403, 404, 422, 500, and network errors receive distinct user-facing guidance.

The current backend issues bearer JWTs, which the client keeps in `localStorage` for page refreshes. This is an explicit compatibility choice with the existing API; it increases exposure to script injection compared with an HttpOnly-cookie session. Keep tokens short-lived, avoid third-party scripts, and revisit cookie-based sessions with CSRF protection before a public production deployment.

## Data display and responsible use

Charts use values returned by the API: academic records, weekly VLE activity, saved prediction history, aggregate risk-review counts, daily saved-score averages, intervention status counts, and backend-derived cluster statistics. Empty API results render explicit empty states; the interface contains no demo or randomly generated dashboard values.

The UI calls model output a support-review signal. It shows saved model/feature versions and observed numeric signals without describing them as causes. Scores are not labeled calibrated probabilities. Cluster descriptions use the backend's persisted cluster medians; cluster identifiers are presented without assigning invented behavioral names. Coordinators remain responsible for decisions, and student text makes clear that VLE clicks are not attendance or proof of learning.

## Main frontend modules

- `src/auth/`: current-user context and authentication/role route guards.
- `src/api/`: centralized Axios client and typed-by-convention service wrappers.
- `src/hooks/useResource.js`: request lifecycle, retry, and page loading state.
- `src/components/`: shared application shell, forms, tables, charts, cards, and state views.
- `src/pages/`: student, coordinator, registration, and login pages.
- `src/test/AppFlows.test.jsx`: mocked API integration tests for primary portal flows.

`VITE_API_BASE_URL` is public frontend configuration and must not contain secrets. LLM credentials and database settings belong only in the backend environment.
