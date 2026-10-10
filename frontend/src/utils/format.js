export function formatDate(value, options = { dateStyle: 'medium' }) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

export function formatScore(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Not recorded';
  return `${Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1)} / 100`;
}

export function formatClicks(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

export function titleCase(value = '') {
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function latestPrediction(predictions = []) {
  return [...predictions].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] || null;
}

export function sortByDateDescending(items = [], key = 'created_at') {
  return [...items].sort((a, b) => new Date(b[key] || 0) - new Date(a[key] || 0));
}
