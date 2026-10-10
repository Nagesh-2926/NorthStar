import { useState } from 'react';
import { AlertTriangle, Download, FileSpreadsheet, Info, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';
import { importsApi } from '../api/services';
import { Card, PageHeader, SectionHeading } from '../components/Primitives';
import { SuccessNotice } from '../components/States';

const RECORD_PREVIEW_LIMIT = 25;

function apiError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  const errors = Array.isArray(detail) ? detail : detail?.errors;
  if (Array.isArray(errors)) {
    const messages = errors.map((item) => {
      const field = typeof item?.field === 'string' ? item.field
        : Array.isArray(item?.loc) && typeof item.loc.at(-1) === 'string' ? item.loc.at(-1) : 'request';
      const message = typeof item?.message === 'string' ? item.message
        : typeof item?.msg === 'string' ? item.msg : 'Invalid value';
      return `${Number.isInteger(item?.row) ? `Row ${item.row} · ` : ''}${field}: ${message}`;
    });
    if (typeof detail.message === 'string') messages.unshift(detail.message);
    if (messages.length) return messages.join('\n');
  }
  if (typeof detail?.message === 'string') return detail.message;
  return typeof error?.message === 'string' ? error.message : 'The request failed. Please try again.';
}

const isCount = (value) => Number.isInteger(value) && value >= 0;
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

function hasValidationCounts(response) {
  return response && [response.total_rows, response.valid_rows, response.invalid_rows, response.forecast_rows].every(isCount)
    && response.valid_rows + response.invalid_rows === response.total_rows
    && response.forecast_rows <= response.valid_rows;
}

const isIdentifier = (value) => typeof value === 'string' && value.length > 0 && !/\s/.test(value);

function hasConfirmedImport(result) {
  if (!result || !isIdentifier(result.import_id) || !Array.isArray(result.records) || !result.records.length
    || ![result.total_rows, result.valid_rows, result.invalid_rows].every(isCount)
    || result.valid_rows !== result.records.length
    || result.valid_rows + result.invalid_rows !== result.total_rows
    || (result.row_count !== undefined && result.row_count !== result.total_rows)
    || (result.already_imported !== undefined && typeof result.already_imported !== 'boolean')) return false;
  const rows = new Set(), enrollments = new Set(), predictions = new Set(), clusters = new Set();
  for (const record of result.records) {
    if (!record || typeof record !== 'object' || Array.isArray(record)
      || !Number.isInteger(record.source_row) || record.source_row < 2 || record.source_row > result.total_rows + 1
      || ![record.enrollment_id, record.prediction_id, record.cluster_record_id].every(isIdentifier)
      || !isCount(record.cluster_id)
      || (record.forecast_id !== null && !isIdentifier(record.forecast_id))
      || rows.has(record.source_row) || enrollments.has(record.enrollment_id)
      || predictions.has(record.prediction_id) || clusters.has(record.cluster_record_id)) return false;
    rows.add(record.source_row); enrollments.add(record.enrollment_id);
    predictions.add(record.prediction_id); clusters.add(record.cluster_record_id);
    if (record.forecast_id !== null) {
      if (predictions.has(record.forecast_id)) return false;
      predictions.add(record.forecast_id);
    }
  }
  return true;
}

function WarningNotice({ children }) {
  return <div className="notice notice-warning" role="status"><AlertTriangle size={18} aria-hidden="true" /><div>{children}</div></div>;
}

function InfoNotice({ children }) {
  return <div className="notice notice-info" role="status"><Info size={18} aria-hidden="true" /><div>{children}</div></div>;
}

function SummaryCounts({ items }) {
  const shown = items.filter((item) => isCount(item.value));
  if (!shown.length) return null;
  return <dl className="import-summary">{shown.map((item) => <div key={item.label} className={item.tone ? `import-summary-${item.tone}` : undefined}>
    <dt>{item.label}</dt><dd>{item.value.toLocaleString()}</dd>{item.note && <span>{item.note}</span>}
  </div>)}</dl>;
}

function RowIssues({ errors, caption }) {
  if (errors === undefined || (Array.isArray(errors) && !errors.length)) return null;
  if (!Array.isArray(errors)) return <p className="form-alert" role="status">The server did not return readable row issues.</p>;
  return <div className="import-issues">
    <h3>{caption} <span>({errors.length})</span></h3>
    <div className="table-wrap">
      <table>
        <thead><tr><th scope="col">Source row</th><th scope="col">Enrollment</th><th scope="col">Field</th><th scope="col">Issue</th></tr></thead>
        <tbody>{errors.map((item, index) => <tr key={index}>
          <td data-label="Source row">{Number.isInteger(item?.row) ? item.row : '—'}</td>
          <td data-label="Enrollment">{typeof item?.enrollment_number === 'string' ? item.enrollment_number : '—'}</td>
          <td data-label="Field"><code className="id-mono">{typeof item?.field === 'string' ? item.field : 'request'}</code></td>
          <td data-label="Issue">{typeof item?.message === 'string' ? item.message : 'No readable validation detail was returned.'}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}

function ForecastStatus({ record }) {
  return record.forecast_id
    ? <span className="status-badge status-positive"><span className="status-dot" aria-hidden="true" />Forecast saved</span>
    : <span className="status-badge status-attention"><span className="status-dot" aria-hidden="true" />Not generated · no weekly sequence</span>;
}

function TechnicalDetails({ result, records }) {
  // Rendered only while open so large imports do not mount thousands of hidden rows.
  const [open, setOpen] = useState(false);
  return <details className="import-technical" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Technical details</summary>
    {open && <div className="import-technical-body">
      <p className="microcopy">Saved record identifiers for debugging. They are not needed for routine review.</p>
      {result.import_id && <p className="import-technical-id">Import ID <code className="id-mono">{result.import_id}</code></p>}
      {records.length > 0 && <div className="table-wrap">
        <table className="import-technical-table">
          <thead><tr><th scope="col">Source row</th><th scope="col">Prediction ID</th><th scope="col">Forecast ID</th><th scope="col">Cluster record ID</th><th scope="col">Enrollment ID</th></tr></thead>
          <tbody>{records.map((record) => <tr key={record.source_row}>
            <td data-label="Source row">{record.source_row}</td>
            <td data-label="Prediction ID"><code className="id-mono">{record.prediction_id || '—'}</code></td>
            <td data-label="Forecast ID"><code className="id-mono">{record.forecast_id || 'Not generated'}</code></td>
            <td data-label="Cluster record ID"><code className="id-mono">{record.cluster_record_id || '—'}</code></td>
            <td data-label="Enrollment ID"><code className="id-mono">{record.enrollment_id || '—'}</code></td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>}
  </details>;
}

function ValidationResults({ validation }) {
  const { total_rows: total, valid_rows: valid, invalid_rows: invalid, forecast_rows: forecastRows } = validation;
  const missingSequences = isCount(valid) && isCount(forecastRows) ? Math.max(0, valid - forecastRows) : null;
  const summary = <>Checked {plural(total, 'row')}: {valid} valid and {invalid} rejected. {plural(forecastRows, 'valid row')} {forecastRows === 1 ? 'has a complete weekly sequence' : 'have complete weekly sequences'} for forecast inference.</>;
  return <section className="import-stage" aria-labelledby="import-validation-heading">
    <SectionHeading title={<span id="import-validation-heading">File check</span>}
      detail="Validation only. Nothing has been saved and no models have run yet." />
    {validation.valid && total > 0
      ? <SuccessNotice>{summary}</SuccessNotice>
      : valid > 0
        ? <WarningNotice>{summary}</WarningNotice>
        : <div className="form-alert" role="status" style={{ whiteSpace: 'pre-wrap' }}>{summary}</div>}
    {missingSequences > 0 && <WarningNotice>
      {plural(missingSequences, 'valid row')} {missingSequences === 1 ? 'has' : 'have'} no complete eight-week weekly sequence. A weekly forecast will not be generated for {missingSequences === 1 ? 'it' : 'them'}.
    </WarningNotice>}
    {validation.duplicate_rows?.length > 0 && <p className="microcopy">Duplicate rows rejected: {validation.duplicate_rows.join(', ')}.</p>}
    {validation.inactive_enrollment_numbers?.length > 0 && <p className="microcopy">Inactive enrollments: {validation.inactive_enrollment_numbers.join(', ')}.</p>}
    {validation.unknown_enrollment_numbers?.length > 0 && <p className="microcopy">Unknown enrollments: {validation.unknown_enrollment_numbers.join(', ')}.</p>}
    <RowIssues errors={validation.errors} caption="Rows that will be rejected" />
    {valid > 0 && <p className="microcopy"><Info size={14} aria-hidden="true" /><span>Select <strong>Import and analyze</strong> to save the {plural(valid, 'valid row')} and run the models.</span></p>}
  </section>;
}

function ImportResults({ result }) {
  const [showAll, setShowAll] = useState(false);
  const confirmed = hasConfirmedImport(result);
  const records = confirmed ? result.records : [];
  const skipped = records.filter((record) => !record.forecast_id);
  const forecastsSaved = records.length - skipped.length;
  const visible = showAll ? records : records.slice(0, RECORD_PREVIEW_LIMIT);
  const alreadyImported = result.already_imported === true;
  const rejected = isCount(result.invalid_rows) ? result.invalid_rows : null;
  const ofTotal = isCount(result.total_rows) ? ` of ${result.total_rows}` : '';
  // "1 of 2 rows" agrees with the file total when it is known, otherwise with the imported count.
  const importedRows = `${records.length}${ofTotal} ${(ofTotal ? result.total_rows : records.length) === 1 ? 'row' : 'rows'} imported`;

  return <section className="import-stage" aria-labelledby="import-results-heading">
    <SectionHeading title={<span id="import-results-heading">Import results</span>}
      detail="Rows saved by the server and the model outputs recorded for each." />
    {!confirmed
      ? <div className="form-alert" role="status">The server response did not include complete saved records and consistent counts, so this import cannot be confirmed. Check the server result before retrying.</div>
      : alreadyImported
      ? <InfoNotice>This exact file was already imported. Previously saved results are shown below; models were not rerun. {importedRows}; {rejected ?? '—'} rejected.</InfoNotice>
      : rejected === 0
        ? <SuccessNotice>Import saved and analyzed: {importedRows}; {rejected} rejected.</SuccessNotice>
        : <WarningNotice>Import saved with {rejected === 1 ? 'a rejected row' : 'rejected rows'}: {importedRows}; {rejected} rejected and not imported.</WarningNotice>}
    {confirmed && <SummaryCounts items={[
      { label: alreadyImported ? 'Rows previously imported' : 'Rows imported', value: records.length, note: ofTotal ? `${ofTotal.trim()} in file` : null },
      { label: 'Rows rejected', value: rejected, tone: rejected > 0 ? 'attention' : null, note: 'Not imported' },
      { label: 'Forecasts saved', value: forecastsSaved },
      { label: 'Forecasts not generated', value: skipped.length, tone: skipped.length > 0 ? 'attention' : null, note: 'Weekly sequence absent' },
    ]} />}
    {confirmed && skipped.length > 0 && <WarningNotice>
      <strong>Weekly forecast not generated for {plural(skipped.length, 'row')}.</strong>{' '}
      {skipped.length === records.length ? 'None of the imported rows included' : 'The affected rows did not include'} a complete eight-week weekly sequence, so no forecast was produced for {skipped.length === 1 ? 'that row' : 'them'}. Their other saved outputs are listed below.
    </WarningNotice>}
    <RowIssues errors={result.errors} caption="Rejected rows" />
    {confirmed && <>
      <div className="table-wrap import-results-table">
        <table>
          <caption className="sr-only">Imported rows with engagement group and forecast status</caption>
          <thead><tr><th scope="col">Source row</th><th scope="col">Engagement group</th><th scope="col">Forecast status</th></tr></thead>
          <tbody>{visible.map((record) => <tr key={record.source_row}>
            <td data-label="Source row"><strong className="import-row-label">Source row {record.source_row}</strong></td>
            <td data-label="Engagement group">{Number.isInteger(record.cluster_id) ? `Cluster ${record.cluster_id}` : '—'}</td>
            <td data-label="Forecast status"><ForecastStatus record={record} /></td>
          </tr>)}</tbody>
        </table>
      </div>
      {records.length > RECORD_PREVIEW_LIMIT && <div className="import-results-more">
        <span className="microcopy">Showing {visible.length} of {records.length} imported rows.</span>
        <button className="button button-secondary button-small" type="button" onClick={() => setShowAll((value) => !value)}>
          {showAll ? `Show first ${RECORD_PREVIEW_LIMIT}` : `Show all ${records.length}`}
        </button>
      </div>}
    </>}
    {typeof result.note === 'string' && result.note && <p className="microcopy"><Info size={14} aria-hidden="true" />{result.note}</p>}
    {confirmed && <TechnicalDetails result={result} records={records} />}
  </section>;
}

export function CoordinatorImportsPage() {
  const [file, setFile] = useState(null);
  const [validatedFile, setValidatedFile] = useState(null);
  const [validation, setValidation] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  async function downloadTemplate() {
    setError('');
    try {
      const response = await importsApi.template();
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'student_upload_template.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(apiError(requestError));
    }
  }

  async function validate() {
    if (!file) return;
    setBusy('validate');
    setError('');
    setResult(null);
    setValidation(null);
    setValidatedFile(null);
    try {
      const response = await importsApi.validate(file);
      if (!hasValidationCounts(response)) {
        throw new Error('The server response did not include consistent validation counts. Validate the file again before importing.');
      }
      setValidation(response);
      if (response.valid_rows > 0) setValidatedFile(file);
    } catch (requestError) {
      setError(apiError(requestError));
    } finally {
      setBusy('');
    }
  }

  async function importFile() {
    if (!file || file !== validatedFile) return;
    setBusy('import');
    setError('');
    try {
      const response = await importsApi.create(file);
      setResult(response && typeof response === 'object' && !Array.isArray(response) ? response : {});
      setValidation(null);
      setValidatedFile(null);
    } catch (requestError) {
      setError(apiError(requestError));
    } finally {
      setBusy('');
    }
  }

  return <>
    <PageHeader eyebrow="COORDINATOR WORKSPACE" title="CSV review and import"
      description="Validate a multi-student feature file and run the saved models for every valid active enrollment. Imports preserve aggregate source snapshots; they never fabricate detailed records." />
    <Card>
      <SectionHeading title="Prepare a file" detail="Use the current feature contract and only enrollment numbers already assigned to an active student course." />
      <div className="import-actions">
        <button className="button button-secondary" onClick={downloadTemplate} type="button">
          <Download size={16} aria-hidden="true" /> Download template
        </button>
        <span className="microcopy"><FileSpreadsheet size={15} aria-hidden="true" /> The template contains headers only; supply verified source observations. Up to 5,000 rows per file.</span>
      </div>
      <label className="import-file-label" htmlFor="coordinator-csv">
        <span>CSV file</span>
        <input id="coordinator-csv" type="file" accept=".csv,text/csv" disabled={Boolean(busy)}
          onChange={(event) => {
            setFile(event.target.files?.[0] || null);
            setValidatedFile(null);
            setValidation(null);
            setResult(null);
            setError('');
          }} />
      </label>
      {file && <p className="microcopy import-selected-file">Selected: {file.name} · {(file.size / 1024).toFixed(1)} KB</p>}
      <div className="import-actions">
        <button className="button button-secondary" disabled={!file || Boolean(busy)}
          onClick={validate} type="button">{busy === 'validate' ? 'Validating…' : 'Validate file'}</button>
        <button className="button button-primary" disabled={!file || validatedFile !== file || Boolean(busy)}
          onClick={importFile} type="button"><Upload size={16} aria-hidden="true" />{busy === 'import' ? 'Running models…' : 'Import and analyze'}</button>
      </div>
      {error && <div className="form-alert" role="alert" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
      <div aria-live="polite">
        {validation && <ValidationResults validation={validation} />}
        {result && <ImportResults result={result} />}
      </div>
    </Card>
    <Card className="human-review-card">
      <h2>How the import is handled</h2>
      <p>Every row is checked against an active application's enrollment number, module, and presentation. Valid rows receive supervised inference, and all eligible rows are assigned individually in one saved K-Means batch; invalid rows are reported with CSV line numbers and skipped. A sequence forecast runs only when all eight weekly observations are supplied consistently.</p>
      <p>Open <Link to="/coordinator/clusters">Engagement groups</Link> to review cohort-level descriptions and observed medians for the saved assignments.</p>
      <p>Uploaded aggregates are saved in a separate, attributable snapshot table. They do not create assessment-level grades, daily activity, attendance, outcomes, study plans, messages, or interventions.</p>
      <p>Model results are decision-support signals only. A coordinator must consider context and make any support decision.</p>
    </Card>
  </>;
}
