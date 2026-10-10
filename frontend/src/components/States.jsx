import { AlertCircle, CheckCircle2, Inbox, LoaderCircle } from 'lucide-react';
import { friendlyError } from '../api/client';

export function LoadingState({ label = 'Loading data', fullPage = false }) {
  return (
    <div className={`state state-loading${fullPage ? ' state-full' : ''}`} role="status" aria-live="polite">
      <LoaderCircle size={22} aria-hidden="true" className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, title = 'We could not load this information' }) {
  return (
    <div className="state state-error" role="alert">
      <AlertCircle size={22} aria-hidden="true" />
      <div><strong>{title}</strong><p>{friendlyError(error)}</p></div>
      {onRetry && <button className="button button-secondary button-small" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function EmptyState({ title = 'Nothing to show yet', description = 'New records will appear here when they are available.', action }) {
  return (
    <div className="state state-empty">
      <span className="empty-icon"><Inbox size={22} aria-hidden="true" /></span>
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function SuccessNotice({ children }) {
  return <div className="notice notice-success" role="status"><CheckCircle2 size={18} aria-hidden="true" />{children}</div>;
}
