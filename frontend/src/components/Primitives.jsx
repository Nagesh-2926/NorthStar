import { ArrowUpRight, Info } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useState } from 'react';
import { formatDate, formatScore, titleCase } from '../utils/format';

export function PageHeader({ eyebrow, title, description, action }) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="page-action">{action}</div>}
    </header>
  );
}

export function SectionHeading({ title, detail, action }) {
  return <div className="section-heading"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div>{action}</div>;
}

export function Card({ children, className = '', as: Element = 'section', ...props }) {
  return <Element className={`card ${className}`.trim()} {...props}>{children}</Element>;
}

export function MetricCard({ label, value, note, icon: Icon }) {
  return (
    <Card className="metric-card">
      <div className="metric-top"><span>{label}</span>{Icon && <span className="metric-icon"><Icon size={18} aria-hidden="true" /></span>}</div>
      <strong className="metric-value">{value}</strong>
      {note && <span className="metric-note">{note}</span>}
    </Card>
  );
}

export function TechnicalReference({ label = 'Technical reference', value }) {
  const [open, setOpen] = useState(false);
  if (!value) return null;
  return <details className="technical-reference" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{label}</summary>
    {open && <code className="id-mono">{value}</code>}
  </details>;
}

const statusText = {
  open: 'Open', in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled',
  review_for_support: 'Review for support', no_flag_from_model: 'No review flag',
  llm: 'Support recommendation', fallback: 'Support recommendation', draft: 'Draft',
  active: 'Active',
};

export function StatusBadge({ status, children }) {
  const value = status || 'unknown';
  const tone = value === 'review_for_support' || value === 'open' ? 'attention'
    : value === 'completed' || value === 'no_flag_from_model' ? 'positive'
      : value === 'cancelled' ? 'muted' : 'neutral';
  return <span className={`status-badge status-${tone}`}><span className="status-dot" aria-hidden="true" />{children || statusText[value] || titleCase(value)}</span>;
}

export function RiskIndicator({ prediction, compact = false }) {
  if (!prediction) return <StatusBadge status="unscored">No prediction yet</StatusBadge>;
  const flagged = prediction.priority_band === 'review_for_support';
  return (
    <div className={`risk-indicator${compact ? ' risk-compact' : ''}`}>
      <StatusBadge status={prediction.priority_band} />
      {!compact && <div className="risk-score-row">
        <span>Support priority score</span>
        <strong>{Math.round(prediction.support_priority_score * 100)} / 100</strong>
      </div>}
      {!compact && <p className="microcopy">
        <Info size={14} aria-hidden="true" /> Model score; it is not a calibrated probability or a statement about an individual's outcome.
      </p>}
      {flagged && !compact && <p className="risk-review-copy">Recent recorded patterns suggest a support review may be helpful. A coordinator considers context before offering support.</p>}
    </div>
  );
}

export function DataTable({ columns, rows, rowKey = 'id', emptyTitle, emptyDescription }) {
  if (!rows?.length) return <div className="table-empty">{emptyTitle || 'No records found'}<span>{emptyDescription || 'Records will appear here when available.'}</span></div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={row[rowKey] ?? index}>{columns.map((column) => (
            <td key={column.key} data-label={column.label}>
              {column.render ? column.render(row) : row[column.key] ?? '—'}
            </td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function PredictionSummary({ prediction, showCourse = false }) {
  if (!prediction) return <div className="prediction-summary muted-card">No model prediction has been recorded for this enrollment.</div>;
  return (
    <div className="prediction-summary">
      <div className="prediction-summary-head"><RiskIndicator prediction={prediction} compact />{showCourse && <TechnicalReference label="Enrollment reference" value={prediction.enrollment_id} />}</div>
      <div className="prediction-meta"><span>{titleCase(prediction.model_name)} · v{prediction.model_version}</span><span>{formatDate(prediction.created_at)}</span></div>
      <div className="microcopy"><Info size={14} aria-hidden="true" />This model output supports human review; it does not explain causes or predict a student's destiny.</div>
    </div>
  );
}

export function TextLink({ to, children }) {
  return <Link className="text-link" to={to}>{children}<ArrowUpRight size={15} aria-hidden="true" /></Link>;
}

export { formatDate, formatScore, titleCase };
