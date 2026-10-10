# Coordinator CSV results browser verification

Verified on 10 October 2026 at `http://127.0.0.1:5173/coordinator/imports` using standalone Playwright with headless Chromium 149.0.7827.55. The browser plugin reported no connected session, so verification used the locally installed Chromium executable. This is browser rendering and interaction verification, rather than a source-only review. Mobile checks use resized Chromium viewports; physical-device and other-browser behavior was not tested.

The final run passed **63 checks** across **1440 × 900**, **375 × 900**, and **390 × 900** viewports, with **51 screenshots** and no frontend runtime exceptions. Screenshots were visually inspected for the table, technical details, warnings, validation, loading, and error presentation. The complete measurements and request log are in [results.json](results.json).

All authentication, validation, and import responses were mocked in an isolated browser context. The existing `data/test_fixtures/coordinator_upload/coordinator_upload_valid.test.csv` supplied the selected file; mock response counts intentionally vary to exercise UI states. Import-button interactions were intercepted and fulfilled locally. Unknown APIs and external requests were blocked. Only frontend assets reached Vite. No real CSV import, backend/database/model change, or environment-file change occurred.

## Confirmed frontend defects and fixes

1. **Long selected filenames caused mobile horizontal overflow.** Selecting the fixture with the filename `NorthStar_coordinator_verified_feature_snapshot_2026_10_10_active_enrollments_aggregate_and_weekly.csv` widened the document to **491px** at both 375px and 390px. The selected-file paragraph now uses normal block layout and wraps long text anywhere. After the fix, the document width equals the requested viewport width. [Before, 375px](375-before-long-filename.png) · [After, 375px](375-long-filename.png) · [Before, 390px](390-before-long-filename.png) · [After, 390px](390-long-filename.png).

2. **Changing files during pending validation displayed stale results under the replacement filename.** With the mocked validation response held pending, choosing `replacement.csv` and then releasing the original response reproduced the mismatch at all three widths. The file picker now stays disabled while validation or import is pending and becomes available after success or failure. A regression test verifies that attempted replacement preserves the original file during both operations, and that selecting a new file after completion clears the previous results and disables import until revalidation. [Before](375-before-stale-validation.png) · [Validation loading after the fix](375-validation-loading.png) · [Import loading after the fix](390-import-loading.png).

The frontend changes are limited to `CoordinatorImportsPage.jsx`, one scoped CSS rule in `styles.css`, and the regression test in `AppFlows.test.jsx`. [changes.diff](changes.diff) contains the exact diff against the pre-verification files.

## Final findings

| Check | Desktop 1440px | Mobile 375px | Mobile 390px | Observed behavior |
| --- | --- | --- | --- | --- |
| Results readability and responsiveness | Pass | Pass | Pass | Three-column desktop table; mobile rows become labeled cards. Source row, engagement group, and forecast status remain visible. |
| Technical details expand/collapse | Pass | Pass | Pass | UUIDs are absent while collapsed, appear when expanded, and are removed after collapse. Full import, prediction, forecast, cluster-record, and enrollment IDs are visible. |
| Missing-forecast warning | Pass | Pass | Pass | Amber warning and per-row badges explain absent eight-week sequences. Mixed and entirely missing forecasts are covered. The warning is absent when every forecast is saved. |
| Validation versus confirmed import | Pass | Pass | Pass | Validation explicitly says nothing has been saved and no models have run. Saved, partially rejected, previously imported, all-rejected, and unconfirmed-response states remain distinct. |
| Loading | Pass | Pass | Pass | “Validating…” and “Running models…” appear during held responses. Action buttons and file selection are disabled while pending. |
| Errors and recovery | Pass | Pass | Pass | Multipart 422 details, structured service errors, and network failure appear as alerts. Controls recover, validation can be retried, and failed imports do not display confirmed results. |
| Overflow and controls | Pass | Pass | Pass | Document width equals viewport width, result/technical tables do not overflow their containers, and main-page controls stay within the viewport without horizontal clipping. Long filenames are included. |
| Large-result controls | Pass | Pass | Pass | A 28-row mock initially shows 25 rows; Show all and Show first 25 work and remain within the viewport. |

## Screenshots

| State | Desktop | 375px | 390px |
| --- | --- | --- | --- |
| Confirmed results and warning | [View](1440-confirmed.png) | [View](375-confirmed.png) | [View](390-confirmed.png) |
| Technical details expanded | [View](1440-technical-expanded.png) | [View](375-technical-expanded.png) | [View](390-technical-expanded.png) |
| Validation only | [View](1440-validation-only.png) | [View](375-validation-only.png) | [View](390-validation-only.png) |
| Partial import with rejected rows | [View](1440-partial-import.png) | [View](375-partial-import.png) | [View](390-partial-import.png) |
| Validation loading | [View](1440-validation-loading.png) | [View](375-validation-loading.png) | [View](390-validation-loading.png) |
| Import loading | [View](1440-import-loading.png) | [View](375-import-loading.png) | [View](390-import-loading.png) |
| Validation error | [View](1440-validation-error.png) | [View](375-validation-error.png) | [View](390-validation-error.png) |
| Import error | [View](1440-import-error.png) | [View](375-import-error.png) | [View](390-import-error.png) |

## Validation after the fixes

- `node reports/csv_ui_browser_verification/verify.cjs`: **63/63 browser state/layout checks passed**; zero runtime exceptions.
- `npm.cmd --prefix frontend test`: **39 tests passed in 2 files**, including the new pending-request file-selection regression test.
- `npm.cmd --prefix frontend run build`: **passed**, 1,666 modules transformed.

The runner uses `playwright-core` installed in the task-specific system temporary directory, leaving repository dependencies and lockfiles unchanged. [verify.cjs](verify.cjs) preserves the mock setup and browser checks. [before-fix-results.json](before-fix-results.json) records the original overflow and stale-selection reproductions; its geometry checks do not independently classify the semantic stale-selection defect, which is recorded in `selectionRace`.
