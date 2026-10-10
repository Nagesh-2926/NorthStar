import { useState } from 'react';
import { Check, ShieldX, UserRoundCheck } from 'lucide-react';
import { accessRequestsApi } from '../api/services';
import { useResource } from '../hooks/useResource';
import { Card, PageHeader } from '../components/Primitives';
import { EmptyState, ErrorState, LoadingState, SuccessNotice } from '../components/States';

function messageFrom(error) {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error?.message || 'The request failed.';
}

export function CoordinatorAccessRequestsPage() {
  const resource = useResource(() => accessRequestsApi.pending(), []);
  const [busyId, setBusyId] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  async function review(requestId, status) {
    setBusyId(requestId);
    setError('');
    setNotice('');
    try {
      await accessRequestsApi.review(requestId, status);
      setNotice(status === 'approved' ? 'Student access approved.' : 'Request rejected.');
      await resource.retry();
    } catch (requestError) {
      setError(messageFrom(requestError));
    } finally {
      setBusyId('');
    }
  }

  if (resource.loading) return <LoadingState label="Loading access requests" />;
  if (resource.error) return <ErrorState error={resource.error} onRetry={resource.retry} />;

  return <>
    <PageHeader eyebrow="COORDINATOR WORKSPACE" title="Student access requests"
      description="Verify enrollment through your institution's approved process before granting a student access to their own account records." />
    {notice && <SuccessNotice>{notice}</SuccessNotice>}
    {error && <div className="form-alert" role="alert">{error}</div>}
    {resource.data.length ? <div className="access-request-list">{resource.data.map((request) => (
      <Card key={request.id}>
        <div className="access-request-heading"><UserRoundCheck size={18} aria-hidden="true" /><strong>{request.student_email}</strong></div>
        <dl className="access-request-details">
          <div><dt>Application enrollment number</dt><dd>{request.enrollment_number}</dd></div>
          <div><dt>Account courses</dt><dd>{request.courses.length ? request.courses.join(', ') : 'No course enrollment yet'}</dd></div>
          <div><dt>Requested</dt><dd>{new Date(request.created_at).toLocaleString()}</dd></div>
        </dl>
        <p className="microcopy">Do not approve based on the number alone. OULAD-derived research identities are not proof of real-world identity.</p>
        <div className="import-actions">
          <button className="button button-primary" disabled={Boolean(busyId)}
            onClick={() => review(request.id, 'approved')} type="button">
            <Check size={16} aria-hidden="true" />{busyId === request.id ? 'Saving…' : 'Approve'}
          </button>
          <button className="button button-secondary" disabled={Boolean(busyId)}
            onClick={() => review(request.id, 'rejected')} type="button">
            <ShieldX size={16} aria-hidden="true" />Reject
          </button>
        </div>
      </Card>
    ))}</div> : <Card><EmptyState title="No pending access requests"
      description="New student requests will appear here for review." /></Card>}
  </>;
}
