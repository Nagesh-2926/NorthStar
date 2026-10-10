import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Activity, ArrowLeft, ArrowRight, ClipboardCheck, Filter, HeartHandshake, Search, UsersRound } from 'lucide-react';
import { analyticsApi, clustersApi, interventionsApi, predictionsApi, studentsApi } from '../api/services';
import { useResource } from '../hooks/useResource';
import { ChartCard, barData, doughnutData, lineData } from '../components/Charts';
import { Field, SelectField } from '../components/Forms';
import { Card, DataTable, MetricCard, PageHeader, PredictionSummary, RiskIndicator, SectionHeading, StatusBadge, TechnicalReference } from '../components/Primitives';
import { EmptyState, ErrorState, LoadingState, SuccessNotice } from '../components/States';
import { CoordinatorCourseDataEntry, CoordinatorEnrollmentSetup } from '../components/CoordinatorDataEntry';
import { formatDate, formatScore, sortByDateDescending, titleCase } from '../utils/format';

function ResourceFrame({ resource, children, label = 'Loading coordinator data' }) {
  if (resource.loading) return <LoadingState label={label} />;
  if (resource.error) return <ErrorState error={resource.error} onRetry={resource.retry} />;
  return children(resource.data);
}

export function CoordinatorDashboardPage() {
  const resource = useResource(async () => {
    const [overview, riskTrends, engagement, clusters, recentPredictions, latestStudents] = await Promise.all([
      analyticsApi.overview(), analyticsApi.riskTrends(90), analyticsApi.engagement(), clustersApi.profiles(),
      predictionsApi.recent(8), analyticsApi.students({ limit: 8, sort_by: 'support_score', sort_order: 'desc', risk_filter: 'review_for_support' }),
    ]);
    return { overview, riskTrends, engagement, clusters, recentPredictions, latestStudents };
  }, []);

  return <><ResourceFrame resource={resource} label="Preparing your coordinator overview">{(data) => {
    const { overview } = data;
    const distribution = overview.risk_distribution || {};
    const outcomeForecast = overview.outcome_forecast_distribution || {};
    const statusCounts = overview.intervention_status_counts || {};
    const riskLabels = ['Review suggested', 'No review flag', 'No review recorded'];
    const riskValues = [distribution.review_for_support || 0, distribution.no_flag_from_model || 0, distribution.unscored || 0];
    const scoreBands = Object.keys(overview.performance_distribution || {});
    const scoreCounts = scoreBands.map((band) => overview.performance_distribution[band]);
    // The API always returns all five bands (zero-filled), so band labels alone do not mean scores exist.
    // Each count is a stored record with a non-null score, so a recorded score of 0 still counts in its band.
    const hasRecordedScores = (overview.recorded_score_count ?? scoreCounts.reduce((sum, count) => sum + (Number(count) || 0), 0)) > 0;
    const engagementRows = data.engagement.weeks || [];
    const dateLabels = data.riskTrends.map((point) => formatDate(point.date, { month: 'short', day: 'numeric' }));
    const recentColumns = [
      { key: 'enrollment_id', label: 'Enrollment', render: (row) => <TechnicalReference label="Enrollment reference" value={row.enrollment_id} /> },
      { key: 'priority_band', label: 'Review status', render: (row) => <StatusBadge status={row.priority_band} /> },
      { key: 'support_priority_score', label: 'Model score', render: (row) => `${Math.round(row.support_priority_score * 100)} / 100` },
      { key: 'model_name', label: 'Model', render: (row) => `${titleCase(row.model_name)} · v${row.model_version}` },
      { key: 'created_at', label: 'Recorded', render: (row) => formatDate(row.created_at) },
    ];
    return <>
      <PageHeader eyebrow="COORDINATOR WORKSPACE" title="Support overview" description="A current view of enrolled students, model review signals, and support activity." />
      <div className="metric-grid metric-grid-four">
        <MetricCard label="Student profiles" value={overview.students.toLocaleString()} note="Registered student accounts" icon={UsersRound} />
        <MetricCard label="Enrollments for review" value={overview.review_for_support.toLocaleString()} note="Latest enrollment output suggests a human review" icon={HeartHandshake} />
        <MetricCard label="Open support actions" value={overview.interventions_open.toLocaleString()} note="Open or in progress" icon={ClipboardCheck} />
        <MetricCard label="Model reviews recorded" value={overview.predictions.toLocaleString()} note={`${overview.enrollments.toLocaleString()} course enrollments`} icon={Activity} />
      </div>
      <div className="dashboard-grid dashboard-grid-top">
        <ChartCard title="Latest enrollment review status" detail="One latest model output per enrollment; unscored enrollments are shown separately" type="doughnut"
          data={doughnutData(riskLabels, riskValues)} emptyDescription="No course enrollments have been added yet." />
        <ChartCard title="Recorded model-score trend" detail="Daily mean of saved model scores over the last 90 days; scores are not calibrated probabilities"
          data={lineData(dateLabels, [{ label: 'Mean support priority score', values: data.riskTrends.map((point) => point.mean_score * 100), color: '#a36d46' }])} />
      </div>
      <div className="dashboard-grid dashboard-grid-top">
        <ChartCard title="Weekly engagement" detail="Mean VLE clicks and active days across recorded weekly entries" type="bar"
          data={barData(engagementRows.map((row) => `Week ${row.week_index + 1}`), [
            { label: 'Mean clicks', values: engagementRows.map((row) => row.mean_clicks), color: '#315f55' },
            { label: 'Mean active days', values: engagementRows.map((row) => row.mean_active_days), color: '#d0a36c' },
          ])} />
        <ChartCard title="Intervention status" detail="All support actions recorded in the database" type="doughnut"
          data={doughnutData(['Open', 'In progress', 'Completed', 'Cancelled'], [statusCounts.open || 0, statusCounts.in_progress || 0, statusCounts.completed || 0, statusCounts.cancelled || 0])}
          emptyDescription="No support actions have been recorded yet." />
      </div>
      <div className="dashboard-grid dashboard-grid-top">
        <ChartCard title="Recorded score distribution" detail="Observed academic records only; final exam estimates are shown separately." type="bar"
          data={barData(hasRecordedScores ? scoreBands : [], [{ label: 'Recorded scores', values: hasRecordedScores ? scoreCounts : [], color: '#315f55' }])}
          emptyDescription="No scored academic records have been stored." />
        <ChartCard title="Saved weekly outcome signals" detail="The weekly model targets later Fail/Withdrawn outcomes; this is not a dropout-specific forecast. Scores are not calibrated probabilities." type="doughnut"
          data={doughnutData(['Review suggested', 'No review flag', 'Not generated'], [
            outcomeForecast.review_for_support || 0,
            outcomeForecast.no_flag_from_model || 0,
            outcomeForecast.not_generated || 0,
          ])} emptyDescription="No course enrollments have been added yet." />
      </div>
      <Card><SectionHeading title="Latest CSV import" detail={`${overview.imports_total} import${overview.imports_total === 1 ? '' : 's'} recorded`}
        action={<Link className="text-link" to="/coordinator/imports">Open CSV imports <ArrowRight size={15} /></Link>} />
        {overview.latest_import ? <div className="metric-grid metric-grid-four">
          <MetricCard label="File" value={overview.latest_import.filename} note={formatDate(overview.latest_import.created_at)} icon={Activity} />
          <MetricCard label="Rows checked" value={overview.latest_import.total_rows} note={`${overview.latest_import.valid_rows} imported`} icon={ClipboardCheck} />
          <MetricCard label="Rows rejected" value={overview.latest_import.invalid_rows} note="Rejected rows were not imported" icon={Filter} />
          <MetricCard label="Recorded scores" value={overview.recorded_score_count.toLocaleString()}
            note={overview.mean_recorded_score == null ? 'No score average available' : `Mean observed score ${overview.mean_recorded_score.toFixed(1)} / 100`} icon={ClipboardCheck} />
        </div> : <EmptyState title="No CSV imports yet" description="Successful coordinator uploads will appear here." />}
      </Card>
      <div className="dashboard-grid dashboard-grid-lower">
        <Card><SectionHeading title="Recent model reviews" detail="Latest saved predictions, with the model version used" />
          <DataTable columns={recentColumns} rows={data.recentPredictions} emptyTitle="No model reviews yet" emptyDescription="Recent predictions will appear here after a coordinator requests them." />
        </Card>
        <Card><SectionHeading title="Students to check in with" detail="Latest student-level review output" action={<Link className="text-link" to="/coordinator/students">View roster <ArrowRight size={15} /></Link>} />
          {data.latestStudents.items.length ? <ul className="compact-student-list">{data.latestStudents.items.map((student) => <li key={student.student_id}>
            <span className="avatar avatar-small">{student.email[0].toUpperCase()}</span><div><strong>{student.email}</strong><span>{student.enrollment_count} enrollment{student.enrollment_count === 1 ? '' : 's'}</span></div>
            <RiskIndicator prediction={student.latest_prediction} compact />
            <Link className="icon-link" aria-label={`Open ${student.email} profile`} to={`/coordinator/students/${student.student_id}`}><ArrowRight size={17} /></Link>
          </li>)}</ul> : <EmptyState title={overview.students === 0 ? 'No student profiles yet' : 'No students currently flagged for review.'}
            description={overview.students === 0 ? 'Student profiles will appear after accounts are registered.' : 'Students appear here when their latest model review suggests a check-in.'} />}
        </Card>
      </div>
      <div className="dashboard-grid dashboard-grid-lower">
        <Card><SectionHeading title="Engagement groups" detail="Latest persisted K-Means summaries" action={<Link className="text-link" to="/coordinator/clusters">Explore profiles <ArrowRight size={15} /></Link>} />
          {data.clusters.length ? <div className="cluster-mini-grid">{data.clusters.map((profile) => <div className="cluster-mini" key={profile.cluster_id}><span>Cluster {profile.cluster_id}</span><strong>{profile.student_count}</strong><small>students represented</small><p>{clusterDescription(profile)}</p></div>)}</div>
            : <EmptyState title="No cluster summaries yet" description="Cluster profiles are based on saved K-Means assignments." />}
        </Card>
        <Card className="human-review-card"><HeartHandshake size={20} aria-hidden="true" /><h2>People make the support decision</h2><p>Model scores can help prioritize a review. They do not predict a student's destiny or explain individual causes.</p><Link className="text-link" to="/coordinator/students">Open student roster <ArrowRight size={15} /></Link></Card>
      </div>
    </>;
  }}</ResourceFrame></>;
}

export function CoordinatorStudentsPage() {
  const [searchDraft, setSearchDraft] = useState('');
  const [query, setQuery] = useState({ search: '', risk_filter: '', sort_by: 'created_at', sort_order: 'desc', offset: 0, limit: 25 });
  const resource = useResource(() => analyticsApi.students(Object.fromEntries(Object.entries(query).filter(([, value]) => value !== ''))), [query]);
  function applySearch(event) { event.preventDefault(); setQuery((value) => ({ ...value, search: searchDraft.trim(), offset: 0 })); }
  function change(field, value) { setQuery((current) => ({ ...current, [field]: value, offset: 0 })); }

  return <><PageHeader eyebrow="STUDENT MONITORING" title="Student roster" description="Search student accounts and review the latest model output for each student's most recent course prediction." />
    <Card className="filters-card">
      <form className="roster-filters" onSubmit={applySearch}>
        <Field id="student-search" label="Search email or student reference" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Start typing…" className="search-field">
          <span className="search-input-wrap"><Search size={16} aria-hidden="true" /><input id="student-search" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Email or ID" /></span>
        </Field>
        <SelectField id="risk-filter" label="Review status" value={query.risk_filter} onChange={(event) => change('risk_filter', event.target.value)} options={[
          { value: '', label: 'All review statuses' }, { value: 'review_for_support', label: 'Review suggested' },
          { value: 'no_flag_from_model', label: 'No review flag' }, { value: 'unscored', label: 'No review recorded' },
        ]} />
        <SelectField id="sort-by" label="Sort by" value={query.sort_by} onChange={(event) => change('sort_by', event.target.value)} options={[
          { value: 'created_at', label: 'Recently registered' }, { value: 'email', label: 'Email' }, { value: 'support_score', label: 'Support score' },
        ]} />
        <SelectField id="sort-order" label="Order" value={query.sort_order} onChange={(event) => change('sort_order', event.target.value)} options={[
          { value: 'desc', label: 'Descending' }, { value: 'asc', label: 'Ascending' },
        ]} />
        <button className="button button-secondary filter-submit" type="submit"><Filter size={16} aria-hidden="true" /> Search</button>
      </form>
    </Card>
    <ResourceFrame resource={resource} label="Loading student roster">{(page) => {
      const columns = [
        { key: 'student_id', label: 'Student', render: (row) => <Link className="student-row-link" to={`/coordinator/students/${row.student_id}`}><span className="avatar avatar-small">{row.email[0].toUpperCase()}</span><span><strong>{row.email}</strong></span></Link> },
        { key: 'enrollment_count', label: 'Enrollments', render: (row) => row.enrollment_count },
        { key: 'latest_prediction', label: 'Latest review', render: (row) => row.latest_prediction ? <StatusBadge status={row.latest_prediction.priority_band} /> : <StatusBadge status="unscored">No review recorded</StatusBadge> },
        { key: 'support_priority_score', label: 'Model score', render: (row) => row.latest_prediction ? `${Math.round(row.latest_prediction.support_priority_score * 100)} / 100` : '—' },
        { key: 'created_at', label: 'Registered', render: (row) => formatDate(row.created_at) },
        { key: 'open', label: '', render: (row) => <Link className="button button-quiet button-small" to={`/coordinator/students/${row.student_id}`}>View profile <ArrowRight size={14} /></Link> },
      ];
      const start = page.total ? page.offset + 1 : 0;
      const end = Math.min(page.offset + page.items.length, page.total);
      return <Card><SectionHeading title="Students" detail={`${start}–${end} of ${page.total.toLocaleString()} profiles`} />
        {page.items.length ? <><DataTable columns={columns} rows={page.items} rowKey="student_id" />
          <div className="pagination"><span>Page {Math.floor(page.offset / page.limit) + 1} of {Math.max(1, Math.ceil(page.total / page.limit))}</span><div>
            <button className="button button-secondary button-small" disabled={page.offset <= 0} onClick={() => setQuery((current) => ({ ...current, offset: Math.max(0, current.offset - current.limit) }))}>Previous</button>
            <button className="button button-secondary button-small" disabled={page.offset + page.items.length >= page.total} onClick={() => setQuery((current) => ({ ...current, offset: current.offset + current.limit }))}>Next</button>
          </div></div>
        </> : <EmptyState title={query.search || query.risk_filter ? 'No students match these filters' : 'No student profiles yet'} description="Try another search or review status, or return when student accounts are available." />}
      </Card>;
    }}</ResourceFrame>
  </>;
}

export function CoordinatorStudentDetailPage() {
  const { studentId } = useParams();
  const [enrollmentId, setEnrollmentId] = useState('');
  const profile = useResource(() => studentsApi.detail(studentId), [studentId]);
  const student = profile.data;
  const enrollment = student?.enrollments?.find((item) => item.id === enrollmentId) || student?.enrollments?.[0] || null;
  const records = useResource(async () => {
    if (!student || !enrollment) return { performance: [], engagement: [], predictions: [], gradePredictions: [], cluster: null, interventions: [] };
    const [performance, engagement, predictions, gradePredictions, cluster, allInterventions] = await Promise.all([
      studentsApi.performance(student.id, enrollment.id), studentsApi.engagement(student.id, enrollment.id),
      predictionsApi.forStudent(student.id, enrollment.id),
      predictionsApi.gradeScoresForStudent(student.id, enrollment.id),
      studentsApi.cluster(student.id, enrollment.id).catch((error) => error.response?.status === 404 ? null : Promise.reject(error)),
      interventionsApi.list(),
    ]);
    return { performance, engagement, predictions, gradePredictions, cluster, interventions: allInterventions.filter((row) => row.enrollment_id === enrollment.id) };
  }, [student?.id, enrollment?.id]);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [interventionForm, setInterventionForm] = useState({ title: '', notes: '', due_date: '' });

  async function runPrediction() {
    setActionBusy(true); setActionError(''); setNotice('');
    try { await predictionsApi.create(student.id, enrollment.id); records.retry(); setNotice('A new model review was recorded for this enrollment.'); }
    catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }
  async function runSequencePrediction() {
    setActionBusy(true); setActionError(''); setNotice('');
    try {
      await predictionsApi.createSequence(student.id, enrollment.id);
      records.retry(); setNotice('A weekly LSTM forecast was saved for human review.');
    } catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }
  async function runGradeScorePrediction() {
    setActionBusy(true); setActionError(''); setNotice('');
    try {
      await predictionsApi.createGradeScore(student.id, enrollment.id);
      records.retry(); setNotice('A numeric final-exam score estimate was saved.');
    } catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }
  async function runCluster() {
    setActionBusy(true); setActionError(''); setNotice('');
    try { await clustersApi.assign(student.id, enrollment.id); records.retry(); setNotice('The latest engagement group assignment has been saved.'); }
    catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }
  async function createIntervention(event) {
    event.preventDefault(); setActionBusy(true); setActionError(''); setNotice('');
    try {
      await interventionsApi.create({ enrollment_id: enrollment.id, ...interventionForm, due_date: interventionForm.due_date || null });
      setInterventionForm({ title: '', notes: '', due_date: '' }); records.retry(); setNotice('Support action recorded.');
    } catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }
  async function updateIntervention(id, status) {
    setActionBusy(true); setActionError('');
    try { await interventionsApi.update(id, { status }); records.retry(); }
    catch (error) { setActionError(error); }
    finally { setActionBusy(false); }
  }

  return <>
    {profile.loading ? <LoadingState label="Loading student profile" /> : profile.error ? <ErrorState error={profile.error} onRetry={profile.retry} /> : <>
      <Link to="/coordinator/students" className="back-link"><ArrowLeft size={16} /> Back to student roster</Link>
      <PageHeader eyebrow="STUDENT PROFILE" title={student.user.email} description={`Enrollment number ${student.enrollment_number || 'not assigned'} · Created ${formatDate(student.created_at)}`} />
      <TechnicalReference label="Technical student reference" value={student.id} />
      {student.enrollments.length > 1 && <div className="detail-enrollment-picker"><SelectField id="detail-enrollment" label="Course enrollment" value={enrollment?.id || ''}
        onChange={(event) => setEnrollmentId(event.target.value)} options={student.enrollments.map((item) => ({ value: item.id, label: `${item.code_module} · ${item.code_presentation}` }))} /></div>}
      {!enrollment ? <CoordinatorEnrollmentSetup studentId={student.id} onCreated={(created) => {
        setEnrollmentId(created.id); setNotice('Course enrollment added.'); profile.retry();
      }} /> : <ResourceFrame resource={records} label="Loading academic and support history">{(data) => {
        const recent = sortByDateDescending(data.predictions);
        const academic = data.performance.filter((record) => record.score != null).slice().reverse();
        const weeks = [...data.engagement].sort((a, b) => a.week_index - b.week_index);
        const latest = recent[0];
        return <>
          {actionError && <div className="form-alert" role="alert">{friendlyActionError(actionError)}</div>}{notice && <SuccessNotice>{notice}</SuccessNotice>}
          <div className="metric-grid metric-grid-four">
            <MetricCard label="Academic records" value={data.performance.length} note="For this enrollment" icon={ClipboardCheck} />
            <MetricCard label="Activity weeks" value={data.engagement.length} note="Weekly records available" icon={Activity} />
            <MetricCard label="Model reviews" value={data.predictions.length} note="Saved for this enrollment" icon={HeartHandshake} />
            <MetricCard label="Interventions" value={data.interventions.length} note={`${data.interventions.filter((item) => ['open', 'in_progress'].includes(item.status)).length} open or in progress`} icon={UsersRound} />
          </div>
          <div className="detail-actions"><div><span className="eyebrow">COORDINATOR ACTIONS</span><p>Model outputs support review. Confirm context before offering support.</p></div>
            <div><button className="button button-secondary" onClick={runPrediction} disabled={actionBusy}><Activity size={16} />Run model review</button>
              {['CCC', 'DDD'].includes(enrollment.code_module) && <button className="button button-secondary" onClick={runGradeScorePrediction} disabled={actionBusy}>Estimate final exam score</button>}
              <button className="button button-secondary" onClick={runSequencePrediction} disabled={actionBusy}>Run weekly forecast</button>
              <button className="button button-secondary" onClick={runCluster} disabled={actionBusy}>Refresh engagement group</button></div>
          </div>
          <p className="inline-hint">The weekly forecast requires an observed record for each of weeks 1–8. Enter zero values only for weeks confirmed to have no activity.</p>
          <CoordinatorCourseDataEntry studentId={student.id} enrollment={enrollment} onChanged={records.retry} />
          <div className="dashboard-grid dashboard-grid-top">
            <Card><SectionHeading title="Latest model output" detail="A score is a prompt for human review, not an individual explanation" />
              {latest ? <><RiskIndicator prediction={latest} /><div className="detail-model-meta"><span>{titleCase(latest.model_name)} · v{latest.model_version}</span><span>{formatDate(latest.created_at)}</span></div>
                {latest.observed_signals && <div className="signal-grid">{Object.entries(latest.observed_signals).filter(([key, value]) => key !== 'weekly_sequence' && value != null).map(([key, value]) => <div key={key}><span>{titleCase(key)}</span><strong>{typeof value === 'number' ? Number(value.toFixed(2)).toLocaleString() : String(value)}</strong></div>)}</div>}
              </> : <EmptyState title="No model review yet" description="A coordinator can run the saved model on this enrollment's recorded data." />}
            </Card>
            <Card><SectionHeading title="Behavioral cluster" detail="Cohort-relative pattern; the identifier has no standalone meaning" />
              {data.cluster ? <><div className="cluster-id-display"><span>Cluster</span><strong>{data.cluster.cluster_id}</strong><small>{data.cluster.feature_version} · {formatDate(data.cluster.assigned_at)}</small></div>
                <div className="signal-grid">{Object.entries(data.cluster.observed_signals || {}).map(([key, value]) => <div key={key}><span>{titleCase(key)}</span><strong>{value == null ? 'Not recorded' : Number(value).toLocaleString()}</strong></div>)}</div>
              </> : <EmptyState title="No cluster assignment" description="Run an engagement group assignment when weekly records are available." />}
            </Card>
          </div>
          <div className="dashboard-grid dashboard-grid-top">
            <Card><SectionHeading title="Numeric final exam estimates" detail="Exam score target, separate from the Fail/Withdrawn support classifier." />
              {data.gradePredictions.length ? <div className="review-history">{sortByDateDescending(data.gradePredictions).map((row) => <div className="review-history-row" key={row.id}><div><strong>{formatScore(row.predicted_score)}</strong><span>Estimated score</span></div><div><span>{titleCase(row.model_name)} · {row.target_name}</span><time>{formatDate(row.created_at)}</time></div></div>)}</div>
                : ['CCC', 'DDD'].includes(enrollment.code_module)
                  ? <EmptyState title="No numeric estimate yet" description="A coordinator can request a final exam score estimate for this course." />
                  : <EmptyState title="Numeric score target unavailable" description={`No final exam score model is trained for ${enrollment.code_module} in the available source data.`} />}
            </Card>
            <ChartCard title="Recorded academic scores" detail="Scores in submission order" data={lineData(academic.map((row) => row.submitted_day != null ? `Day ${row.submitted_day}` : formatDate(row.occurred_on)), [{ label: 'Score', values: academic.map((row) => row.score), color: '#315f55' }])} />
            <ChartCard title="Weekly engagement" detail="Observed VLE clicks and active days" type="bar" data={barData(weeks.map((row) => `Week ${row.week_index + 1}`), [
              { label: 'Clicks', values: weeks.map((row) => row.clicks), color: '#315f55' }, { label: 'Active days', values: weeks.map((row) => row.active_days), color: '#d0a36c' },
            ])} />
          </div>
          <div className="dashboard-grid dashboard-grid-lower">
            <Card><SectionHeading title="Prediction history" detail="Saved model and feature versions" />
              {recent.length ? <div className="review-history">{recent.map((row) => <div className="review-history-row" key={row.id}><div><StatusBadge status={row.priority_band} /><strong>{Math.round(row.support_priority_score * 100)} / 100</strong></div><div><span>{titleCase(row.model_name)} · {row.feature_version}</span><time>{formatDate(row.created_at)}</time></div></div>)}</div> : <EmptyState title="No prediction history" description="Saved model reviews will appear here." />}
            </Card>
            <Card><SectionHeading title="Intervention history" detail="Human-authored support actions" />
              {data.interventions.length ? <ul className="intervention-mini-list">{sortByDateDescending(data.interventions).map((item) => <li key={item.id}><div><strong>{item.title}</strong><span>{item.notes || 'No notes added'} · {formatDate(item.created_at)}</span>
                <span>{interventionOutcomeSummary(item, data.performance, data.engagement)}</span>
                <span>Comparison uses record-entry timestamps and does not show that an intervention caused a change.</span></div>
                <select aria-label={`Status for ${item.title}`} value={item.status} disabled={actionBusy} onChange={(event) => updateIntervention(item.id, event.target.value)}>{['open', 'in_progress', 'completed', 'cancelled'].map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}</select></li>)}</ul>
                : <EmptyState title="No interventions recorded" description="Add a support action after reviewing context." />}
            </Card>
          </div>
          <Card><SectionHeading title="Record an intervention" detail="Document a human-reviewed check-in or support action" />
            <form className="intervention-form" onSubmit={createIntervention}>
              <Field id="intervention-title" label="Action title" required maxLength={160} value={interventionForm.title} onChange={(event) => setInterventionForm({ ...interventionForm, title: event.target.value })} placeholder="e.g. Offer a check-in" />
              <Field id="intervention-notes" label="Notes" maxLength={4000} value={interventionForm.notes} onChange={(event) => setInterventionForm({ ...interventionForm, notes: event.target.value })} placeholder="Relevant context or agreed next steps" />
              <Field id="intervention-date" label="Optional due date" type="date" value={interventionForm.due_date} onChange={(event) => setInterventionForm({ ...interventionForm, due_date: event.target.value })} />
              <button className="button button-primary" disabled={actionBusy || !interventionForm.title.trim()} type="submit">Record support action</button>
            </form>
          </Card>
        </>;
      }}</ResourceFrame>}
    </>}
  </>;
}

export function CoordinatorClustersPage() {
  const resource = useResource(() => clustersApi.profiles(), []);
  return <><PageHeader eyebrow="BEHAVIORAL ANALYTICS" title="Engagement groups" description="Cohort-relative K-Means clusters summarized from the latest recorded assignment for each enrollment." />
    <p className="disclaimer-line"><Activity size={16} aria-hidden="true" />Cluster IDs are arbitrary group identifiers. The statistics describe recorded activity and do not label a student.</p>
    <ResourceFrame resource={resource} label="Loading cluster profiles">{(profiles) => profiles.length ? <>
      <div className="dashboard-grid cluster-charts">
        <ChartCard title="Students represented" detail="Distinct student profiles in the latest assignments" type="bar" data={barData(profiles.map((item) => `Cluster ${item.cluster_id}`), [{ label: 'Students', values: profiles.map((item) => item.student_count), color: '#315f55' }])} />
        <ChartCard title="Median active weeks" detail="Observed weeks with VLE clicks in the early window" type="bar" data={barData(profiles.map((item) => `Cluster ${item.cluster_id}`), [{ label: 'Active weeks', values: profiles.map((item) => item.median_features.early_vle_active_weeks ?? 0), color: '#94aa88' }])} />
      </div>
      <div className="cluster-profile-grid">{profiles.map((profile) => <Card className="cluster-profile-card" key={profile.cluster_id}>
        <div className="cluster-profile-head"><span className="cluster-number">{profile.cluster_id}</span><div><span className="eyebrow">COHORT-RELATIVE GROUP</span><h2>Cluster {profile.cluster_id}</h2></div></div>
        <p className="cluster-generated-description">{clusterDescription(profile)}</p>
        <div className="cluster-counts"><div><strong>{profile.student_count.toLocaleString()}</strong><span>students represented</span></div><div><strong>{profile.enrollment_count.toLocaleString()}</strong><span>course enrollments</span></div></div>
        <h3>Median observed features</h3><div className="signal-grid">{Object.entries(profile.median_features).map(([key, value]) => <div key={key}><span>{titleCase(key)}</span><strong>{value == null ? 'Not recorded' : Number(value.toFixed(1)).toLocaleString()}</strong></div>)}</div>
        <p className="cluster-version">Model v{profile.model_version} · {profile.feature_version}</p>
      </Card>)}</div>
    </> : <Card><EmptyState title="No cluster assignments yet" description="Profiles appear when a coordinator saves K-Means assignments based on recorded course activity." /></Card>}</ResourceFrame>
  </>;
}

export function CoordinatorInterventionsPage() {
  const resource = useResource(() => interventionsApi.list(), []);
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  async function updateStatus(id, status) {
    setBusyId(id); setActionError(null);
    try {
      await interventionsApi.update(id, { status });
      resource.setData(resource.data.map((item) => item.id === id ? { ...item, status } : item));
    } catch (error) { setActionError(error); }
    finally { setBusyId(null); }
  }

  return <><PageHeader eyebrow="HUMAN-LED SUPPORT" title="Interventions" description="Track check-ins and agreed support actions. Model outputs do not create interventions automatically." />
    {actionError && <ErrorState error={actionError} title="The intervention status was not updated" />}
    <SelectField id="intervention-filter" label="Filter by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} options={[
      { value: '', label: 'All statuses' }, ...['open', 'in_progress', 'completed', 'cancelled'].map((value) => ({ value, label: titleCase(value) })),
    ]} />
    <ResourceFrame resource={resource} label="Loading interventions">{(all) => {
      const rows = all.filter((item) => !statusFilter || item.status === statusFilter);
      const columns = [
        { key: 'title', label: 'Support action', render: (row) => <div className="table-primary"><strong>{row.title}</strong><span>{row.notes || 'No notes'}</span></div> },
        { key: 'enrollment_id', label: 'Enrollment', render: (row) => <TechnicalReference label="Enrollment reference" value={row.enrollment_id} /> },
        { key: 'status', label: 'Status', render: (row) => <select className="table-select" aria-label={`Status for ${row.title}`} value={row.status} disabled={busyId === row.id} onChange={(event) => updateStatus(row.id, event.target.value)}>{['open', 'in_progress', 'completed', 'cancelled'].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select> },
        { key: 'due_date', label: 'Due date', render: (row) => row.due_date ? formatDate(row.due_date, { dateStyle: 'medium', timeZone: 'UTC' }) : '—' },
        { key: 'created_at', label: 'Created', render: (row) => formatDate(row.created_at) },
      ];
      return <Card><SectionHeading title="Support action log" detail={`${rows.length} shown from ${all.length} recorded actions`} />
        {rows.length ? <DataTable columns={columns} rows={rows} /> : <EmptyState title={all.length ? 'No actions match this status' : 'No interventions yet'} description={all.length ? 'Choose another status filter.' : 'When a coordinator records a support action, it will appear here.'} />}
      </Card>;
    }}</ResourceFrame>
  </>;
}

function clusterDescription(profile) {
  const f = profile.median_features || {};
  const clicks = f.early_vle_clicks == null ? 'not recorded' : `${Math.round(f.early_vle_clicks).toLocaleString()} clicks`;
  const days = f.early_vle_active_days == null ? 'not recorded' : `${Number(f.early_vle_active_days.toFixed(1))} active days`;
  const weeks = f.early_vle_active_weeks == null ? 'not recorded' : `${Number(f.early_vle_active_weeks.toFixed(1))} active weeks`;
  const score = f.early_assessment_mean == null ? null : ` and a median recorded assessment score of ${Number(f.early_assessment_mean.toFixed(1))}`;
  return `In this group, median recorded course activity was ${clicks} across ${days} and ${weeks}${score || ''}. These cohort statistics describe the saved assignments; they do not explain an individual student's outcome.`;
}

function interventionOutcomeSummary(intervention, performance, engagement) {
  const interventionTime = Date.parse(intervention.created_at);
  const split = (records) => ({
    before: records.filter((record) => Date.parse(record.recorded_at) <= interventionTime),
    after: records.filter((record) => Date.parse(record.recorded_at) > interventionTime),
  });
  const scores = split(performance.filter((record) => record.score != null));
  const activity = split(engagement);
  const summarize = (records, measure) => records.length
    ? `${records.length} record${records.length === 1 ? '' : 's'} (mean ${measure(records).toFixed(1)})`
    : 'no records';
  const mean = (records, value) => records.reduce((total, record) => total + value(record), 0) / records.length;
  const scoreMeasure = (records) => mean(records, (record) => record.score);
  const clickMeasure = (records) => mean(records, (record) => record.clicks);
  return `Scores entered before: ${summarize(scores.before, scoreMeasure)} / after: ${summarize(scores.after, scoreMeasure)}. Weekly activity entered before: ${summarize(activity.before, clickMeasure)} (mean clicks/week) / after: ${summarize(activity.after, clickMeasure)} (mean clicks/week).`;
}

function friendlyActionError(error) {
  if (error.response?.status === 409) return error.response.data?.detail || 'Review the current records before trying again.';
  if (error.response?.status === 422) return 'The saved records do not meet this model version’s input requirements.';
  if (error.response?.status === 503) return 'The saved model is unavailable right now.';
  if (error.response?.status === 403) return 'Your account does not have permission to do that.';
  if (error.response?.status === 404) return 'This student or enrollment is no longer available.';
  return 'The service could not complete this action. Try again or check your connection.';
}
