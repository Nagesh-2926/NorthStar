import { afterEach, describe, expect, it, vi } from 'vitest';
import { AxiosError } from 'axios';
import api, { friendlyError, TOKEN_KEY } from './client';
import { authApi, importsApi } from './services';

const originalAdapter = api.defaults.adapter;
const originalBaseURL = api.defaults.baseURL;

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  api.defaults.baseURL = originalBaseURL;
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('authentication API configuration and errors', () => {
  it.each([
    ['registration', () => authApi.register({ email: 'student@example.edu', password: 'SecurePass1234', role: 'student' }), '/auth/register'],
    ['login', () => authApi.login({ email: 'student@example.edu', password: 'SecurePass1234' }), '/auth/login'],
  ])('sends %s through the configured API client', async (_operation, request, expectedPath) => {
    let requestConfig;
    api.defaults.adapter = vi.fn(async (config) => {
      requestConfig = config;
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
    });

    await request();

    expect(requestConfig.url).toBe(expectedPath);
    expect(requestConfig.baseURL).toBe(originalBaseURL);
  });

  it('sends password changes only to the authenticated password-change endpoint', async () => {
    let requestConfig;
    api.defaults.adapter = vi.fn(async (config) => {
      requestConfig = config;
      return { data: { message: 'Password updated.' }, status: 200,
        statusText: 'OK', headers: {}, config };
    });
    window.localStorage.setItem(TOKEN_KEY, 'current-user-token');

    await authApi.changePassword({ current_password: 'old', new_password: 'NewPassword1234',
      confirm_password: 'NewPassword1234' });

    expect(requestConfig.url).toBe('/auth/change-password');
    expect(requestConfig.method).toBe('post');
    expect(requestConfig.headers.Authorization).toBe('Bearer current-user-token');
  });

  it('does not clear or expire the saved token after invalid login credentials', async () => {
    api.defaults.baseURL = 'http://127.0.0.1:8001/api';
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    const dispatchEvent = vi.spyOn(window, 'dispatchEvent');
    api.defaults.adapter = vi.fn(async (config) => {
      const response = { data: { detail: 'Invalid email or password' }, status: 401,
        statusText: 'Unauthorized', headers: {}, config };
      throw new AxiosError('Request failed', 'ERR_BAD_REQUEST', config, null, response);
    });

    let error;
    try {
      await authApi.login({ email: 'demo@example.edu', password: 'wrong-password' });
    } catch (requestError) {
      error = requestError;
    }

    expect(error).toBeDefined();
    expect(friendlyError(error)).toBe('Invalid email or password');
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('existing-token');
    expect(dispatchEvent.mock.calls.some(([event]) => event.type === 'auth:expired')).toBe(false);
  });

  it('keeps server and connection errors distinct from session expiry', () => {
    expect(friendlyError({ response: { status: 503, data: { detail: 'Backend unavailable' } } }))
      .toBe('Backend unavailable');
    expect(friendlyError({ config: { url: '/auth/register' },
      response: { status: 403, data: { detail: 'Coordinator registration is invite-only' } } }))
      .toBe('Coordinator registration is invite-only');
    expect(friendlyError({ message: 'Network Error' })).toContain('VITE_API_BASE_URL');
    expect(friendlyError({ message: 'Network Error' })).not.toContain('session has expired');
  });

  it('identifies a saved token rejected by another backend separately from expiration', () => {
    const message = friendlyError({
      config: { url: '/auth/me' },
      response: { status: 401, data: { detail: 'Authentication required' } },
    });
    expect(message).toContain('API at');
    expect(message).toContain('another backend');
    expect(message).not.toContain('session has expired');
    expect(friendlyError({ config: { url: '/students' }, response: { status: 401, data: {} } }))
      .toBe('Your session has expired. Please sign in again.');
  });
});

describe('CSV imports API', () => {
  it.each([
    ['validation', importsApi.validate],
    ['import', importsApi.create],
  ])('sends %s uploads as multipart FormData', async (_operation, send) => {
    let requestConfig;
    const adapter = vi.fn(async (config) => {
      requestConfig = config;
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
    });
    api.defaults.adapter = adapter;

    await send(new File(['enrollment_number\n2403031528786'], 'student_upload.csv', { type: 'text/csv' }));

    expect(adapter).toHaveBeenCalledOnce();
    expect(requestConfig.data).toBeInstanceOf(FormData);
    expect(requestConfig.data.get('file')).toBeInstanceOf(File);
    expect(requestConfig.headers.getContentType()).toBe(false);
  });

});
