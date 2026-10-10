import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMockDemoApi, demoStudent, mockImportResult, rejectionValidation, validValidation } from './mockApi';

describe('test-only browser mock adapter', () => {
  it('uses byte-identical copies of the existing repository fixtures inside Vite\'s allowed root', () => {
    const directory = dirname(fileURLToPath(import.meta.url));
    for (const name of ['coordinator_upload_valid.test.csv', 'coordinator_upload_rejections.test.csv', 'synthetic_enrollment_mapping.test-only.csv']) {
      const original = readFileSync(resolve(directory, '../../../../data/test_fixtures/coordinator_upload', name));
      const served = readFileSync(resolve(directory, 'fixtures', name));
      expect(served.equals(original)).toBe(true);
    }
  });
  it('reflects the checked-in fixture counts and forecast availability', () => {
    expect(validValidation).toMatchObject({ total_rows: 23, valid_rows: 23, invalid_rows: 0, forecast_rows: 21 });
    expect(rejectionValidation).toMatchObject({ total_rows: 14, valid_rows: 0, invalid_rows: 14, forecast_rows: 0 });
    expect(rejectionValidation.errors).toHaveLength(14);
    expect(rejectionValidation.duplicate_rows).toEqual([14, 15]);
    expect(mockImportResult.records).toHaveLength(23);
    expect(mockImportResult.records.filter((record) => record.forecast_id)).toHaveLength(21);
    expect(mockImportResult.records.filter((record) => !record.forecast_id)).toHaveLength(2);
  });

  it('fails unhandled routes locally with no network fallback', async () => {
    const mock = createMockDemoApi();
    await expect(mock.adapter({ method: 'get', url: '/unhandled' })).rejects.toMatchObject({ response: { status: 501 } });
    expect(mock.calls).toEqual([{ method: 'GET', path: '/unhandled' }]);
  });

  it('uses an existing synthetic fixture profile, zero stub score, and no fabricated detailed records', async () => {
    const mock = createMockDemoApi({ role: 'student' });
    expect(demoStudent.enrollment_number).toBe('2403031590021');
    const profile = await mock.adapter({ method: 'get', url: '/students/me' });
    expect(profile.data).toBe(demoStudent);
    const prediction = await mock.adapter({ method: 'get', url: `/predictions/${demoStudent.id}` });
    expect(prediction.data[0].support_priority_score).toBe(0);
    expect(prediction.data[0].model_version).toBe('mock-only');
    const records = await mock.adapter({ method: 'get', url: `/students/${demoStudent.id}/performance` });
    expect(records.data).toEqual([]);
  });

  it('distinguishes empty data from a failed overview', async () => {
    const empty = createMockDemoApi({ scenario: 'empty' });
    expect((await empty.adapter({ method: 'get', url: '/analytics/overview' })).data.students).toBe(0);
    const failed = createMockDemoApi({ scenario: 'error' });
    await expect(failed.adapter({ method: 'get', url: '/analytics/overview' })).rejects.toMatchObject({ response: { status: 503 } });
  });
});
