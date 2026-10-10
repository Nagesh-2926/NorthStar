# Mocked browser verification

With the existing frontend Vite server serving `127.0.0.1:5173`, open
`/mock-demo.html`. This is a separate development/test HTML entry; `npm run build`
includes only the normal `index.html`, so the harness is excluded from production.

The real React routes and API services run against an explicit in-memory Axios
adapter installed before the app renders. Unhandled routes fail locally; there
is no HTTP transport fallback. The harness does not read or modify the saved
browser login, `.env`, any database, or model artifacts. The top banner remains
visible to identify every screenshot as mocked verification.

Use the fixture selection buttons to load the two unchanged existing CSV files.
The three files in `fixtures/` are byte-identical copies checked against the
repository originals by the frontend tests. Copies keep Vite's default filesystem
boundary intact instead of exposing the parent project directory.
The CSV validation responses mirror the mapping's expected outcomes: 23 valid
rows, 21 weekly forecasts and 2 aggregate-only rows, or 14 rejected rows with
their documented reasons. Import responses and group/model outputs are clearly
stubbed UI responses, and do not prove backend validation, inference, or writes.
The product UI confirms a response only when totals match complete saved records
with unique source rows and record identifiers; malformed responses show an
unconfirmed state without saved counts.
Student profiles use the existing reserved synthetic fixture identities. Detailed
academic and activity records remain empty. The student view displays a stored
zero stub model score alongside missing forecast data.

Routes:

- `/mock-demo.html`: coordinator import and validation UI.
- `/mock-demo.html?role=student`: zero model score and missing forecast.
- `/mock-demo.html?path=/coordinator/dashboard&scenario=empty`: empty overview.
- `/mock-demo.html?path=/coordinator/dashboard&scenario=error`: failed overview.
- `/mock-demo.html?path=/login`: mocked authentication flow.

Navigation inside the app uses a memory router. Refresh returns to the path in
the URL query. The harness's stub API may reject actions outside these checks;
it never delegates such actions to the real API.
