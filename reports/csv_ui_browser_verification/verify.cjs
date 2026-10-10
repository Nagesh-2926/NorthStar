const { chromium } = require('C:/Users/vvvsn/AppData/Local/Temp/northstar-browser-verification/node_modules/playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const output = __dirname;
const fixture = path.resolve(__dirname, '../../data/test_fixtures/coordinator_upload/coordinator_upload_valid.test.csv');
const base = 'http://127.0.0.1:5173';
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const record = (n, forecast = false) => ({ source_row: n + 2, cluster_id: n % 4,
  enrollment_id: uuid(n + 100), prediction_id: uuid(n + 200),
  cluster_record_id: uuid(n + 300), forecast_id: forecast ? uuid(n + 400) : null });
const validation = { valid: true, total_rows: 3, valid_rows: 3, invalid_rows: 0, forecast_rows: 1, errors: [] };
const confirmed = { import_id: uuid(1), already_imported: false, total_rows: 3, valid_rows: 3,
  invalid_rows: 0, errors: [], records: [record(0, true), record(1), record(2)] };
const issue = { row: 5, enrollment_number: '2403031599999', field: 'enrollment_number',
  message: 'This enrollment number is not associated with an application student.' };
const report = { browser: 'Headless Chromium, standalone Playwright (browser plugin had no connected session)',
  url: `${base}/coordinator/imports`, widths: [1440, 375, 390], fixture, checks: [], requests: [],
  runtimeErrors: [], screenshots: [], failures: [] };

async function run() {
  const browser = await chromium.launch({ headless: true,
    executablePath: 'C:/Users/vvvsn/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe' });
  report.version = browser.version();
  try {
    for (const width of report.widths) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' });
      const page = await context.newPage();
      page.setDefaultTimeout(10000);
      let state = { validation, result: confirmed };
      let release = null;
      page.on('pageerror', error => report.runtimeErrors.push({ width, message: error.message }));
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
        if (/\/auth\/login$/.test(url.pathname)) {
          report.requests.push({ width, method: request.method(), path: url.pathname, action: 'mocked' });
          return json({ access_token: 'browser-verification-mock-token', token_type: 'bearer' });
        }
        if (/\/auth\/me$/.test(url.pathname)) {
          report.requests.push({ width, method: request.method(), path: url.pathname, action: 'mocked' });
          return json({ id: uuid(99), email: 'coordinator@example.edu', role: 'coordinator', is_active: true });
        }
        if (request.method() === 'POST' && /\/imports(?:\/validate)?$/.test(url.pathname)) {
          const validating = url.pathname.endsWith('/validate');
          report.requests.push({ width, method: request.method(), path: url.pathname, action: 'mocked' });
          if (state.hold === (validating ? 'validate' : 'import')) await new Promise(resolve => { release = resolve; });
          if (state.networkError) return route.abort('failed');
          if (state.error) return json({ detail: state.error }, state.status || 422);
          return json(validating ? state.validation : state.result);
        }
        // Only frontend assets reach the local Vite server. Every API request and
        // every non-local request is intercepted; there is no backend fallback.
        if (url.origin === base && !url.pathname.startsWith('/api/')) return route.continue();
        report.requests.push({ width, method: request.method(), path: url.pathname, action: 'blocked' });
        return route.abort('blockedbyclient');
      });
      async function check(name, screenshot = true) {
        await page.evaluate(() => { window.scrollTo(0, 0); });
        await page.waitForFunction(() => window.scrollY === 0);
        await page.evaluate(() => document.fonts.ready);
        const geometry = await page.evaluate(() => {
          const bounds = el => { const r = el.getBoundingClientRect(); return { x: r.x, right: r.right, width: r.width }; };
          const controls = [...document.querySelectorAll('main button, main input, main summary')]
            .filter(el => el.getClientRects().length).map(el => ({ text: el.textContent || el.id,
              ...bounds(el), client: el.clientWidth, scroll: el.scrollWidth }));
          const wrappers = [...document.querySelectorAll('main .table-wrap')].map(el => ({ ...bounds(el),
            client: el.clientWidth, scroll: el.scrollWidth, overflow: getComputedStyle(el).overflowX }));
          const clipped = controls.filter(el => el.x < -1 || el.right > innerWidth + 1 || el.scroll > el.client + 2);
          return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth, controls, wrappers, clipped };
        });
        const passed = geometry.documentWidth <= width && geometry.clipped.length === 0 &&
          geometry.wrappers.every(w => w.scroll <= w.client + 1);
        report.checks.push({ width, name, passed, geometry });
        if (!passed) report.failures.push({ width, name, geometry });
        if (screenshot) {
          const filename = `${width}-${name}.png`;
          await page.screenshot({ path: path.join(output, filename), fullPage: true });
          report.screenshots.push(filename);
        }
        console.log(`${width} ${name}: ${passed ? 'PASS' : 'FAIL'} document=${geometry.documentWidth}, clipped=${geometry.clipped.length}`);
      }
      async function reset(next = {}) {
        state = { validation, result: confirmed, ...next };
        await page.goto(`${base}/coordinator/imports`);
        await page.getByLabel('CSV file', { exact: true }).waitFor();
        await page.getByLabel('CSV file', { exact: true }).setInputFiles(fixture);
      }
      async function validate() {
        await page.getByRole('button', { name: 'Validate file', exact: true }).click();
        await page.getByRole('heading', { name: 'File check', exact: true }).waitFor();
      }
      async function importMock() {
        await page.getByRole('button', { name: 'Import and analyze', exact: true }).click();
        await page.getByRole('heading', { name: 'Import results', exact: true }).waitFor();
      }
      // Sign in through the normal UI using wholly mocked credentials/responses.
      await page.goto(`${base}/coordinator/imports`);
      await page.getByLabel('Email address', { exact: true }).fill('coordinator@example.edu');
      await page.getByLabel('Password', { exact: true }).fill('MockBrowserPassword123');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.waitForURL('**/coordinator/**');
      await page.goto(`${base}/coordinator/imports`);
      await page.getByLabel('CSV file', { exact: true }).waitFor();
      assert(await page.getByRole('button', { name: 'Validate file', exact: true }).isDisabled());
      assert(await page.getByRole('button', { name: 'Import and analyze', exact: true }).isDisabled());
      await check('initial');
      await page.getByLabel('CSV file', { exact: true }).setInputFiles(fixture);
      await validate();
      assert(await page.getByText('Validation only. Nothing has been saved and no models have run yet.').isVisible());
      assert(await page.getByText(/2 valid rows have no complete eight-week/).isVisible());
      assert.equal(await page.getByRole('heading', { name: 'Import results', exact: true }).count(), 0);
      assert(!await page.getByRole('button', { name: 'Import and analyze', exact: true }).isDisabled());
      await check('validation-only');
      await importMock();
      assert(await page.getByText(/Import saved and analyzed: 3 of 3/).isVisible());
      assert(await page.getByText('Weekly forecast not generated for 2 rows.', { exact: true }).isVisible());
      const resultTable = page.locator('.import-results-table');
      assert.equal(await resultTable.locator('tbody tr').count(), 3);
      assert.equal(await page.getByText(uuid(200), { exact: true }).count(), 0);
      assert(await resultTable.getByText('Cluster 0', { exact: true }).isVisible());
      assert(await resultTable.getByText('Forecast saved', { exact: true }).isVisible());
      await check('confirmed');
      await page.getByText('Technical details', { exact: true }).click();
      await page.getByText(uuid(200), { exact: true }).waitFor();
      for (const id of [uuid(1), uuid(100), uuid(200), uuid(300), uuid(400)])
        assert(await page.getByText(id, { exact: true }).isVisible());
      await check('technical-expanded');
      await page.getByText('Technical details', { exact: true }).click();
      await page.getByText(uuid(200), { exact: true }).waitFor({ state: 'detached' });
      await check('technical-collapsed', false);

      await reset({ result: { ...confirmed, records: [record(0), record(1), record(2)] } });
      await validate(); await importMock();
      assert(await page.getByText(/None of the imported rows included/).isVisible());
      assert.equal(await page.locator('.import-results-table').getByText('Forecast saved', { exact: true }).count(), 0);
      await check('all-forecasts-missing');

      await reset({ validation: { ...validation, forecast_rows: 3 },
        result: { ...confirmed, records: [record(0, true), record(1, true), record(2, true)] } });
      await validate();
      assert.equal(await page.getByText(/no complete eight-week/).count(), 0);
      await importMock();
      assert.equal(await page.getByText(/Weekly forecast not generated for/).count(), 0);
      assert.equal(await page.locator('.import-results-table').getByText('Forecast saved', { exact: true }).count(), 3);
      await check('all-forecasts-saved');

      await reset({ validation: { ...validation, valid: false, total_rows: 4, invalid_rows: 1,
        unknown_enrollment_numbers: [issue.enrollment_number], errors: [issue] },
        result: { ...confirmed, total_rows: 4, invalid_rows: 1, errors: [issue] } });
      await validate();
      await check('validation-rejected');
      await importMock();
      assert(await page.getByText(/Import saved with rejected rows: 3 of 4/).isVisible());
      await check('partial-import');

      await reset({ result: { ...confirmed, already_imported: true } });
      await validate(); await importMock();
      assert(await page.getByText(/Previously saved results are shown below; models were not rerun/).isVisible());
      assert.equal(await page.getByText(/Import saved and analyzed/).count(), 0);
      await check('already-imported');

      await reset({ result: { import_id: uuid(1), total_rows: 3, invalid_rows: 0, errors: [] } });
      await validate(); await importMock();
      assert(await page.getByText(/this import cannot be confirmed/).isVisible());
      assert.equal(await page.getByText(/Import saved/).count(), 0);
      await check('unconfirmed-response');

      await reset({ validation: { valid: false, total_rows: 1, valid_rows: 0, invalid_rows: 1,
        forecast_rows: 0, errors: [issue] } });
      await validate();
      assert(await page.getByRole('button', { name: 'Import and analyze', exact: true }).isDisabled());
      await check('all-rejected');

      await reset({ hold: 'validate' });
      await page.getByRole('button', { name: 'Validate file', exact: true }).click();
      await page.getByRole('button', { name: 'Validating…', exact: true }).waitFor();
      assert(await page.getByRole('button', { name: 'Validating…', exact: true }).isDisabled());
      assert(await page.getByRole('button', { name: 'Import and analyze', exact: true }).isDisabled());
      assert(await page.getByLabel('CSV file', { exact: true }).isDisabled());
      await check('validation-loading');
      release(); release = null;
      await page.getByRole('heading', { name: 'File check', exact: true }).waitFor();
      state.hold = 'import';
      await page.getByRole('button', { name: 'Import and analyze', exact: true }).click();
      await page.getByRole('button', { name: 'Running models…', exact: true }).waitFor();
      assert(await page.getByRole('button', { name: 'Running models…', exact: true }).isDisabled());
      assert(await page.getByRole('button', { name: 'Validate file', exact: true }).isDisabled());
      assert(await page.getByLabel('CSV file', { exact: true }).isDisabled());
      await check('import-loading');
      release(); release = null;
      await page.getByRole('heading', { name: 'Import results', exact: true }).waitFor();

      await reset({ error: [{ loc: ['body', 'file'], msg: 'Field required' }] });
      await page.getByRole('button', { name: 'Validate file', exact: true }).click();
      await page.getByRole('alert').waitFor();
      assert(await page.getByLabel('CSV file', { exact: true }).isEnabled());
      assert.equal(await page.getByRole('alert').innerText(), 'file: Field required');
      await check('validation-error');
      state = { validation, result: confirmed };
      await validate();
      assert.equal(await page.getByRole('alert').count(), 0);
      state.error = { message: 'Import service unavailable. Please try again.', errors: [issue] };
      state.status = 503;
      await page.getByRole('button', { name: 'Import and analyze', exact: true }).click();
      await page.getByRole('alert').waitFor();
      assert(await page.getByRole('button', { name: 'Import and analyze', exact: true }).isEnabled());
      assert(await page.getByLabel('CSV file', { exact: true }).isEnabled());
      assert.equal(await page.getByRole('heading', { name: 'Import results', exact: true }).count(), 0);
      await check('import-error');

      await reset({ networkError: true });
      await page.getByRole('button', { name: 'Validate file', exact: true }).click();
      await page.getByRole('alert').waitFor();
      await check('network-error');

      await reset();
      await page.getByLabel('CSV file', { exact: true }).setInputFiles({
        name: 'NorthStar_coordinator_verified_feature_snapshot_2026_10_10_active_enrollments_aggregate_and_weekly.csv',
        mimeType: 'text/csv', buffer: fs.readFileSync(fixture),
      });
      await validate(); await importMock();
      await check('long-filename');

      await reset({ hold: 'validate' });
      await page.getByRole('button', { name: 'Validate file', exact: true }).click();
      await page.getByRole('button', { name: 'Validating…', exact: true }).waitFor();
      const pickerDisabled = await page.getByLabel('CSV file', { exact: true }).isDisabled();
      if (!pickerDisabled) {
        await page.getByLabel('CSV file', { exact: true }).setInputFiles({
          name: 'replacement.csv', mimeType: 'text/csv', buffer: Buffer.from('enrollment_number\n2403031599999'),
        });
        release(); release = null;
        await page.getByRole('heading', { name: 'File check', exact: true }).waitFor();
        const stale = await page.getByText(/Selected: replacement.csv/).isVisible();
        report.selectionRace = [...(report.selectionRace || []), { width, staleValidationShown: stale }];
        await check('replaced-file-during-validation');
        assert(!stale, 'Validation for a previous file appeared under the replacement filename');
      } else {
        report.selectionRace = [...(report.selectionRace || []), { width, pickerDisabled: true }];
        release(); release = null;
        await page.getByRole('heading', { name: 'File check', exact: true }).waitFor();
        assert(await page.getByText(/Selected: coordinator_upload_valid.test.csv/).isVisible());
        await check('file-selection-locked', false);
      }

      const many = Array.from({ length: 28 }, (_, i) => record(i, i % 2 === 0));
      await reset({ result: { ...confirmed, total_rows: 28, valid_rows: 28, records: many } });
      await validate(); await importMock();
      assert.equal(await page.locator('.import-results-table tbody tr').count(), 25);
      await page.getByRole('button', { name: 'Show all 28', exact: true }).click();
      assert.equal(await page.locator('.import-results-table tbody tr').count(), 28);
      await check('show-all', false);
      await page.getByRole('button', { name: 'Show first 25', exact: true }).click();
      assert.equal(await page.locator('.import-results-table tbody tr').count(), 25);
      await check('preview-restored', false);
      await context.close();
    }
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  }
  assert.equal(report.runtimeErrors.length, 0, 'Unexpected frontend runtime errors');
  assert.equal(report.failures.length, 0, 'Responsive geometry failures; see results.json');
}
run().catch(error => { report.error = error.stack; fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); console.error(error); process.exitCode = 1; });
