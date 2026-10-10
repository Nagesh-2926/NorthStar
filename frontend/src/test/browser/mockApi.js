// Test-only UI responses. This module never imports backend code or a transport.
import validCsv from './fixtures/coordinator_upload_valid.test.csv?raw';
import rejectedCsv from './fixtures/coordinator_upload_rejections.test.csv?raw';
import mappingCsv from './fixtures/synthetic_enrollment_mapping.test-only.csv?raw';
import { AxiosError } from 'axios';

function columns(line) {
  const values = [];
  let value = '', quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') { value += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { values.push(value); value = ''; }
    else value += char;
  }
  return [...values, value];
}

function rows(csv) {
  const [header, ...lines] = csv.trim().split(/\r?\n/);
  const keys = columns(header);
  return lines.map((line) => Object.fromEntries(columns(line).map((value, index) => [keys[index], value])));
}

const validRows = rows(validCsv);
const mapping = rows(mappingCsv);
const rejectionMapping = mapping.filter((row) => row.fixture_file === 'coordinator_upload_rejections.test.csv');
const rejectionRows = rows(rejectedCsv);
const validMapping = mapping.filter((row) => row.fixture_file === 'coordinator_upload_valid.test.csv');
const timestamp = '2026-10-10T00:00:00Z';

export const demoFixtures = {
  valid: { name: 'coordinator_upload_valid.test.csv', text: validCsv },
  rejections: { name: 'coordinator_upload_rejections.test.csv', text: rejectedCsv },
};

export const validValidation = {
  valid: true, total_rows: validRows.length, valid_rows: validRows.length, invalid_rows: 0,
  forecast_rows: validRows.filter((row) => Array.from({ length: 8 }, (_, index) => index + 1)
    .every((week) => row[`week_${week}_clicks`] !== '' && row[`week_${week}_active_days`] !== '')).length,
  errors: [], duplicate_rows: [], unknown_enrollment_numbers: [], inactive_enrollment_numbers: [],
};

export const rejectionValidation = {
  valid: false, total_rows: rejectionRows.length, valid_rows: 0, invalid_rows: rejectionRows.length, forecast_rows: 0,
  errors: rejectionMapping.map((row) => ({ row: Number(row.fixture_row), field: row.expected_field,
    enrollment_number: rejectionRows[Number(row.fixture_row) - 2].enrollment_number,
    message: row.description })),
  duplicate_rows: rejectionMapping.filter((row) => row.case_id.startsWith('duplicate_')).map((row) => Number(row.fixture_row)),
  unknown_enrollment_numbers: [rejectionMapping.find((row) => row.case_id === 'unknown_enrollment').synthetic_enrollment_number],
  inactive_enrollment_numbers: [rejectionMapping.find((row) => row.case_id === 'inactive_enrollment').synthetic_enrollment_number],
};

export const mockImportResult = {
  import_id: 'mock-import-fixture', already_imported: false, total_rows: validRows.length,
  valid_rows: validRows.length, invalid_rows: 0, errors: [],
  records: validMapping.map((row, index) => ({ source_row: Number(row.fixture_row),
    enrollment_id: `mock-enrollment-${row.synthetic_enrollment_number}`,
    prediction_id: `mock-prediction-${index}`, cluster_record_id: `mock-cluster-${index}`,
    cluster_id: index % 4,
    forecast_id: row.case_id === 'valid_with_weekly_sequence' ? `mock-forecast-${index}` : null,
  })),
  note: 'Mock response only. No rows were saved and no models ran.',
};

const profiles = validMapping.map((row) => ({
  id: `mock-student-${row.synthetic_enrollment_number}`, enrollment_number: row.synthetic_enrollment_number,
  user_id: `mock-user-${row.synthetic_enrollment_number}`, access_approved: true, created_at: timestamp,
  user: { id: `mock-user-${row.synthetic_enrollment_number}`,
    email: `synthetic-upload-fixture-${row.synthetic_enrollment_number}@example.com`, role: 'student', is_active: true },
  enrollments: [{ id: `mock-enrollment-${row.synthetic_enrollment_number}`, code_module: row.seed_code_module,
    code_presentation: row.seed_code_presentation, is_active: true, registration_day: Number(row.seed_registration_day),
    num_of_prev_attempts: Number(row.seed_num_of_prev_attempts), studied_credits: Number(row.seed_studied_credits) }],
}));

export const demoStudent = profiles.find((profile) => profile.enrollment_number === '2403031590021');

function modelOutput(profile) {
  // Intentional zero for UI verification; this is a stub, never model inference.
  return { id: `mock-zero-output-${profile.id}`, enrollment_id: profile.enrollments[0].id,
    model_name: 'random_forest', model_version: 'mock-only', feature_version: 'mock-only',
    support_priority_score: 0, threshold: 0.4, priority_band: 'no_flag_from_model',
    observed_signals: {}, created_at: timestamp };
}

export function createMockDemoApi({ role = 'coordinator', scenario = 'records' } = {}) {
  const calls = [];
  const pending = [];
  let currentRole = role;
  let imported = false;
  let nextSupportId = 0;
  const support = [];
  const account = () => currentRole === 'student' ? demoStudent.user
    : { id: 'mock-coordinator', email: 'mock-coordinator@example.com', role: 'coordinator', is_active: true };

  function reject(config, status, detail) {
    const response = { data: { detail }, status, statusText: 'Mock response', headers: {}, config };
    throw new AxiosError('Mock request rejected', 'ERR_BAD_REQUEST', config, null, response);
  }

  async function adapter(config) {
    const path = config.url.split('?')[0];
    const method = config.method.toUpperCase();
    // Retain route/method only, never credentials or authorization headers.
    calls.push({ method, path });
    const payload = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
    const respond = (data) => ({ data, status: 200, statusText: 'Mock response', headers: {}, config });
    if (path === '/auth/me') return respond(account());
    if (path === '/auth/login' || path === '/auth/register') {
      currentRole = payload?.role || (payload?.email?.includes('coordinator') ? 'coordinator' : 'student');
      return respond(path.endsWith('login') ? { access_token: 'mock-memory-token', token_type: 'bearer' } : account());
    }
    if (path === '/auth/change-password') return respond({ message: 'Mock password response; nothing changed.' });
    if (path === '/imports/template') return respond(new Blob([validCsv.split(/\r?\n/)[0] + '\n'], { type: 'text/csv' }));
    if (path === '/imports/validate' || path === '/imports') {
      const file = payload?.get?.('file');
      const content = file && await file.text();
      if (content !== validCsv && content !== rejectedCsv) reject(config, 422, 'The mock harness accepts only the two unchanged existing fixture files.');
      if (path.endsWith('validate')) return respond(content === validCsv ? validValidation : rejectionValidation);
      if (content !== validCsv) reject(config, 422, 'No valid rows in the rejection fixture.');
      const result = { ...mockImportResult, already_imported: imported };
      imported = true;
      return respond(result);
    }
    if (path === '/analytics/overview') {
      if (scenario === 'error') reject(config, 503, 'Mock unavailable service. No backend was contacted.');
      const count = scenario === 'empty' ? 0 : profiles.length;
      return respond({ students: count, enrollments: count, predictions: count,
        review_for_support: 0, interventions_open: support.length, risk_distribution: { review_for_support: 0,
          no_flag_from_model: count, unscored: 0 }, outcome_forecast_distribution: { review_for_support: 0,
          no_flag_from_model: 0, not_generated: count },
        performance_distribution: { '0-19': 0, '20-39': 0, '40-59': 0, '60-79': 0, '80-100': 0 },
        recorded_score_count: 0, mean_recorded_score: null, imports_total: imported ? 1 : 0,
        latest_import: imported ? { filename: demoFixtures.valid.name, total_rows: validRows.length,
          valid_rows: validRows.length, invalid_rows: 0, created_at: timestamp } : null,
        intervention_status_counts: { open: support.length, in_progress: 0, completed: 0, cancelled: 0 } });
    }
    if (path === '/analytics/risk-trends') return respond([]);
    if (path === '/analytics/engagement') return respond({ weeks: [] });
    if (path === '/analytics/clusters' || path === '/clusters') return respond([]);
    if (path === '/analytics/monitoring/students' || path === '/students') {
      const selected = scenario === 'empty' || config.params?.risk_filter === 'review_for_support' ? []
        : profiles.filter((profile) => !config.params?.search || profile.user.email.includes(config.params.search));
      const offset = Number(config.params?.offset || 0), limit = Number(config.params?.limit || 25);
      return respond({ items: selected.slice(offset, offset + limit).map((profile) => ({ student_id: profile.id,
        email: profile.user.email, created_at: timestamp, enrollment_count: 1, latest_prediction: modelOutput(profile) })),
      total: selected.length, offset, limit });
    }
    if (path === '/students/me') return respond(demoStudent);
    if (path === '/access-requests' && method === 'GET') return respond(pending);
    if (path === '/access-requests/me') return respond({ access_approved: true, enrollment_number: demoStudent.enrollment_number, request: null });
    if (path === '/interventions') {
      if (method === 'GET') return respond(support);
      if (method === 'POST') {
        const item = { ...payload, id: `mock-support-${++nextSupportId}`, status: 'open', created_at: timestamp };
        support.push(item); return respond(item);
      }
    }
    if (path.startsWith('/interventions/') && method === 'PUT') {
      const item = support.find((row) => row.id === path.split('/').at(-1));
      if (!item) reject(config, 404, 'Mock support record not found.');
      Object.assign(item, payload); return respond(item);
    }
    const studentMatch = path.match(/^\/students\/([^/]+)(?:\/(.*))?$/);
    if (studentMatch) {
      const profile = profiles.find((item) => item.id === studentMatch[1]);
      if (!profile) reject(config, 404, 'Mock student not found.');
      if (!studentMatch[2]) return respond(profile);
      if (['performance', 'engagement', 'study-plan', 'motivational-messages'].includes(studentMatch[2]) && method === 'GET') return respond([]);
      if (studentMatch[2] === 'cluster') reject(config, 404, 'No mock cluster assignment.');
    }
    if (path === '/predictions') return respond(scenario === 'empty' ? [] : profiles.slice(0, 8).map(modelOutput));
    const predictionMatch = path.match(/^\/predictions\/([^/]+)(?:\/(.*))?$/);
    if (predictionMatch) {
      const profile = profiles.find((item) => item.id === predictionMatch[1]);
      if (!profile) reject(config, 404, 'Mock student not found.');
      if (predictionMatch[2] === 'grade-score' && method === 'GET') return respond([]);
      if (!predictionMatch[2]) return respond(method === 'GET' ? [modelOutput(profile)] : modelOutput(profile));
      if (predictionMatch[2] === 'sequence') reject(config, 422, 'A complete eight-week observed history is required. No records are fabricated in the mock.');
    }
    if (/^\/enrollments\/[^/]+\/assessment-schedule$/.test(path) && method === 'GET') return respond([]);
    // An unimplemented route is a local failure. There is deliberately no transport fallback.
    reject(config, 501, `No mock response for ${method} ${path}. No backend was contacted.`);
  }
  return { adapter, calls };
}
