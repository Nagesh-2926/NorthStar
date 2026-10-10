import axios from 'axios';

export const TOKEN_KEY = 'student-support-access-token';
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = window.localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = 'Bearer ' + token;
    config.__northstarAccessToken = token;
  }
  return config;
});

function isAuthenticationEntryRequest(config) {
  const path = (config?.url || '').split('?')[0];
  return path.endsWith('/auth/login') || path.endsWith('/auth/register');
}

function isCurrentUserRequest(config) {
  return (config?.url || '').split('?')[0].endsWith('/auth/me');
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !isAuthenticationEntryRequest(error.config)) {
      const requestToken = error.config?.__northstarAccessToken;
      if (requestToken && window.localStorage.getItem(TOKEN_KEY) === requestToken) {
        window.localStorage.removeItem(TOKEN_KEY);
        window.dispatchEvent(new Event('auth:expired'));
      }
    }
    return Promise.reject(error);
  },
);

function apiDetailMessage(detail) {
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return '';
  return detail.map((item) => {
    const message = item?.msg || item?.message;
    if (!message) return '';
    const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
    return location ? location + ': ' + message : message;
  }).filter(Boolean).join('; ');
}

export function friendlyError(error) {
  if (!error?.response) {
    return 'The API at ' + API_BASE_URL + ' could not be reached. Check VITE_API_BASE_URL and confirm that this backend is running.';
  }
  const status = error.response.status;
  const detail = apiDetailMessage(error.response.data?.detail);
  if (status === 401) {
    if (isAuthenticationEntryRequest(error.config)) return detail || 'Invalid email or password.';
    if (isCurrentUserRequest(error.config)) {
      return 'The API at ' + API_BASE_URL + ' rejected the saved login. It may belong to another backend; sign in again using this API.';
    }
    return 'Your session has expired. Please sign in again.';
  }
  if (status === 403) return detail || 'Your account does not have permission to do that.';
  if (status === 404) return detail || 'This record is not available for your account.';
  if (status === 409) return detail || 'This action conflicts with an existing record.';
  if (status === 422) return detail || 'Some information needs to be corrected. Review the fields and try again.';
  if (status >= 500) return detail || 'The service had a problem. Please try again in a moment.';
  return detail || 'Something went wrong. Please try again.';
}

export default api;
