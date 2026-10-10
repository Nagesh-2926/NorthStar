import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { accessRequestsApi } from '../api/services';
import { useResource } from '../hooks/useResource';
import { Card, PageHeader, StatusBadge } from '../components/Primitives';
import { ErrorState, LoadingState, SuccessNotice } from '../components/States';

function messageFrom(error) {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error?.message || 'The request failed.';
}

export function StudentAccessRequestPage() {
  const resource = useResource(() => accessRequestsApi.mine(), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);

  if (resource.loading) return <LoadingState label="Checking student access" />;
  if (resource.error) return <ErrorState error={resource.error} onRetry={resource.retry} />;
  const state = resource.data;
  const request = state.request;

  async function submit() {
    if (!state.enrollment_number) return;
    setBusy(true);
    setError('');
    try {
      const created = await accessRequestsApi.create(state.enrollment_number);
      setSubmitted(true);
      resource.setData({ ...state, request: created });
    } catch (requestError) {
      setError(messageFrom(requestError));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <PageHeader eyebrow="STUDENT PORTAL" title="Coordinator verification"
      description="Before student academic and support records are available, a coordinator must verify the enrollment-number assignment for this account." />
    <Card>
      <div className="access-request-icon"><ShieldCheck size={22} aria-hidden="true" /></div>
      <h2>Your application enrollment number</h2>
      {state.enrollment_number
        ? <p className="access-enrollment-number">{state.enrollment_number}</p>
        : <p className="form-alert" role="alert">No enrollment number is assigned. Contact a coordinator to resolve the account setup.</p>}
      <p className="page-description">This application-generated number identifies your account; it is not a password or proof of identity. The coordinator should verify your enrollment through the institution's approved process before approving access.</p>
      {request && <p>Request status: <StatusBadge status={request.status} /></p>}
      {submitted && <SuccessNotice>Your request has been sent for coordinator review.</SuccessNotice>}
      {error && <div className="form-alert" role="alert">{error}</div>}
      {request?.status === 'pending'
        ? <p className="microcopy">A coordinator must review your request. Your academic and support record pages remain unavailable while it is pending.</p>
        : <button className="button button-primary" type="button"
          disabled={!state.enrollment_number || busy}
          onClick={submit}>{busy ? 'Submitting…' : request?.status === 'rejected' ? 'Request review again' : 'Request access'}</button>}
    </Card>
    <Card className="human-review-card">
      <h2>Identity and dataset integrity</h2>
      <p>Enrollment numbers alone never authorize access to another account's data. OULAD identities are synthetic research identifiers; they are not real-world student identities. Coordinator approval is an access-control step, not a claim that OULAD records belong to a real person.</p>
    </Card>
  </>;
}
