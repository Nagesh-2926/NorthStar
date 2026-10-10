import { useState } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Activity, ArrowRight, BookOpenCheck, CalendarDays, ClipboardList, HeartHandshake, MessageCircleHeart, NotebookPen, Target } from 'lucide-react';
import { studentsApi, predictionsApi, plansApi, interventionsApi } from '../api/services';
import { friendlyError } from '../api/client';
import { useResource } from '../hooks/useResource';
import { ChartCard, barData, lineData } from '../components/Charts';
import { Card, DataTable, MetricCard, PageHeader, PredictionSummary, RiskIndicator, SectionHeading, StatusBadge, TechnicalReference } from '../components/Primitives';
import { EmptyState, ErrorState, LoadingState, SuccessNotice } from '../components/States';
import { formatDate, formatScore, latestPrediction, sortByDateDescending, titleCase } from '../utils/format';

function useStudentContext() {
  return useOutletContext();
}

function useStudentBundle(student, enrollment) {
  return useResource(async () => {
    if (!student || !enrollment) return {
      performance: [], engagement: [], predictions: [], gradePredictions: [], plans: [], messages: [],
      cluster: null, interventions: [],
    };
    const [performance, engagement, predictions, gradePredictions, plans, messages, cluster, allInterventions] = await Promise.all([
      studentsApi.performance(student.id, enrollment.id),
      studentsApi.engagement(student.id, enrollment.id),
      predictionsApi.forStudent(student.id, enrollment.id),
      predictionsApi.gradeScoresForStudent(student.id, enrollment.id),
      plansApi.list(student.id, enrollment.id),
      plansApi.messages(student.id),
      studentsApi.cluster(student.id, enrollment.id).catch((error) => error.response?.status === 404 ? null : Promise.reject(error)),
      interventionsApi.list(),
    ]);
    return { performance, engagement, predictions, gradePredictions, plans, messages, cluster,
      interventions: allInterventions.filter((item) => item.enrollment_id === enrollment.id) };
  }, [student?.id, enrollment?.id]);
}

function EnrollmentEmpty() {
  return <EmptyState title="No course enrollment yet" description="Your course activity and academic records will appear here when your coordinator adds an enrollment." />;
}

function ResourceFrame({ resource, children, label = 'Loading your records' }) {
  if (resource.loading) return <LoadingState label={label} />;
  if (resource.error) return <ErrorState error={resource.error} onRetry={resource.retry} />;
  return children(resource.data);
}

function RecentActivity({ performance = [], engagement = [], predictions = [] }) {
  const items = [
    ...performance.map((row) => ({ key: row.id, label: row.record_type === 'assessment_score' ? 'Assessment score recorded' : titleCase(row.record_type), detail: row.score == null ? 'Score not recorded' : formatScore(row.score), date: row.recorded_at, icon: BookOpenCheck })),
    ...engagement.map((row) => ({ key: row.id, label: `Week ${row.week_index + 1} activity updated`, detail: `${row.clicks.toLocaleString()} VLE clicks · ${row.active_days} active days`, date: row.recorded_at, icon: Activity })),
    ...predictions.map((row) => ({ key: row.id, label: 'Support review recorded', detail: titleCase(row.priority_band), date: row.created_at, icon: HeartHandshake })),
  ].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 5);
  if (!items.length) return <EmptyState title="No recent activity" description="Recorded scores and weekly course activity will appear here." />;
  return <ul className="activity-list">{items.map((item) => <li key={item.key}>
    <span className="activity-icon"><item.icon size={16} aria-hidden="true" /></span>
    <div className="activity-copy"><strong>{item.label}</strong><span>{item.detail}</span></div>
    <time>{formatDate(item.date)}</time>
  </li>)}</ul>;
}

export function StudentDashboardPage() {
  const { student, enrollment } = useStudentContext();
  const resource = useStudentBundle(student, enrollment);
  if (!enrollment) return <><PageHeader eyebrow="STUDENT PORTAL" title="Your overview" description="A calm place to follow course progress and support." /><EnrollmentEmpty /></>;
  return <ResourceFrame resource={resource} label="Loading your overview">{(bundle) => {
    const recentScore = bundle.performance.find((record) => record.score !== null && record.score !== undefined)?.score;
    const lastWeek = [...bundle.engagement].sort((a, b) => b.week_index - a.week_index)[0];
    const prediction = latestPrediction(bundle.predictions);
    const gradePrediction = latestPrediction(bundle.gradePredictions);
    const forecast = latestPrediction(bundle.predictions.filter((row) => row.model_name === 'lstm_weekly'));
    const observedWeeks = new Set(bundle.engagement
      .filter((row) => row.week_index >= 0 && row.week_index < 8)
      .map((row) => row.week_index));
    const missingWeeks = Array.from({ length: 8 }, (_, index) => index + 1)
      .filter((week) => !observedWeeks.has(week - 1));
    const plan = sortByDateDescending(bundle.plans)[0];
    const clicks = bundle.engagement.filter((row) => row.week_index < 8).reduce((sum, row) => sum + row.clicks, 0);
    const weekly = [...bundle.engagement].sort((a, b) => a.week_index - b.week_index);
    return <>
      <PageHeader eyebrow={`${enrollment.code_module} · ${enrollment.code_presentation}`} title="Your overview"
        description="Your records are here to support a conversation, not to define your potential." />
      <div className="metric-grid metric-grid-four">
        <MetricCard label="Latest recorded score" value={formatScore(recentScore)} note="From your academic records" icon={BookOpenCheck} />
        <MetricCard label="Early course activity" value={clicks.toLocaleString()} note="VLE clicks in weeks 1–8" icon={Activity} />
        <MetricCard label="Most recent week" value={lastWeek ? `Week ${lastWeek.week_index + 1}` : '—'} note={lastWeek ? `${lastWeek.active_days} active days recorded` : 'No weekly entry yet'} icon={CalendarDays} />
        <MetricCard label="Study goals" value={plan?.content?.actions?.length ?? 0} note={plan ? 'In your latest plan' : 'No plan created yet'} icon={Target} />
      </div>
      <div className="dashboard-grid dashboard-grid-top">
        <ChartCard title="Weekly course activity" detail="Recorded VLE clicks by course week" type="bar"
          data={barData(weekly.map((row) => `Week ${row.week_index + 1}`), [{ label: 'VLE clicks', values: weekly.map((row) => row.clicks), color: '#315f55' }])} />
        <Card className="support-card"><SectionHeading title="Support review" detail="Decision-support signal · human review required" />
          {prediction ? <><RiskIndicator prediction={prediction} /><Link className="button button-secondary button-small" to="/student/predictions">View review history <ArrowRight size={15} /></Link></>
            : <EmptyState title="No review has been recorded" description="If a coordinator completes a model review, its summary will appear here." />}
        </Card>
      </div>
      <div className="dashboard-grid dashboard-grid-lower">
        <Card><SectionHeading title="Recent activity" detail="Updates recorded for this enrollment" /><RecentActivity performance={bundle.performance} engagement={bundle.engagement} predictions={bundle.predictions} /></Card>
        <Card><SectionHeading title="Your latest study plan" detail="Supportive suggestions you can adapt" />
          {plan ? <div className="plan-preview"><h3>{plan.content?.title || 'A study plan for you'}</h3><ul>{(plan.content?.actions || []).slice(0, 3).map((action, index) => <li key={`${index}-${action}`}>{action}</li>)}</ul><Link className="text-link" to="/student/study-plan">Open study plan <ArrowRight size={15} /></Link></div>
            : <EmptyState title="No plan yet" description="A study plan becomes available after a coordinator records a support review." action={<Link className="text-link" to="/student/study-plan">View study plans <ArrowRight size={15} /></Link>} />}
        </Card>
      </div>
      <div className="dashboard-grid dashboard-grid-lower">
        <Card><SectionHeading title="End-of-course outcome signal" detail="This is not a dropout-specific forecast or a calibrated probability." />
          {forecast ? <><StatusBadge status={forecast.priority_band} /><p>Saved weekly-sequence model score: {Math.round(forecast.support_priority_score * 100)} / 100. The trained target is a later Fail/Withdrawn outcome.</p><p className="microcopy">Recorded {formatDate(forecast.created_at)} · {titleCase(forecast.model_name)} v{forecast.model_version}</p></>
            : missingWeeks.length ? <><StatusBadge status="unscored">Insufficient weekly history</StatusBadge><p>A weekly forecast requires observed records for every one of weeks 1–8. Missing: {missingWeeks.map((week) => `week ${week}`).join(', ')}. No weeks are filled in automatically.</p></>
              : <><StatusBadge status="unscored">Forecast not generated</StatusBadge><p>All eight weekly records are present, but a forecast has not been saved for this enrollment.</p></>}
        </Card>
        <Card><SectionHeading title="Final exam score estimate" detail="Separate from the support review; trained for CCC and DDD only." />
          {gradePrediction ? <><strong className="grade-score-value">{formatScore(gradePrediction.predicted_score)}</strong>
            <p>Estimated final exam assessment score using information available through course day 55. The model was evaluated on historical data and is not an overall course grade.</p>
            <p className="microcopy">Recorded {formatDate(gradePrediction.created_at)} · {titleCase(gradePrediction.model_name)} v{gradePrediction.model_version}</p></>
            : ['CCC', 'DDD'].includes(enrollment.code_module)
              ? <p>A coordinator can request an estimate for this course. Numeric exam scores are supported only for CCC and DDD; the target covers students who submitted an exam.</p>
              : <p>No numeric final exam target is available for {enrollment.code_module} in the trained source data. Your recorded academic scores remain visible above.</p>}
          {recentScore == null && <p className="microcopy">No scored academic record is stored for this enrollment.</p>}
        </Card>
      </div>
      <div className="dashboard-grid dashboard-grid-lower">
        <Card><SectionHeading title="Behavioral group" detail="Cohort-relative K-Means grouping; not a diagnosis or fixed student label." />
          {bundle.cluster ? <><StatusBadge status="active">{`Cluster ${bundle.cluster.cluster_id}`}</StatusBadge>
            <p>Recorded early activity: {bundle.cluster.observed_signals?.early_vle_clicks ?? 'not recorded'} clicks, {bundle.cluster.observed_signals?.early_vle_active_days ?? 'not recorded'} active days across {bundle.cluster.observed_signals?.early_vle_active_weeks ?? 'not recorded'} active weeks.</p>
            <p className="microcopy">Model {bundle.cluster.model_version} · {bundle.cluster.feature_version} · {formatDate(bundle.cluster.assigned_at)}</p></>
            : <EmptyState title="No behavioral grouping yet" description="A coordinator can create one when a complete eight-week activity window is recorded." />}
        </Card>
        <Card><SectionHeading title="Support actions" detail="Coordinator-recorded actions for this course." />
          {bundle.interventions.length ? <ul className="intervention-mini-list">{sortByDateDescending(bundle.interventions).slice(0, 3).map((item) => <li key={item.id}><div><strong>{item.title}</strong><span>{item.due_date ? `Due ${formatDate(item.due_date)}` : `Recorded ${formatDate(item.created_at)}`}</span></div><StatusBadge status={item.status} /></li>)}</ul>
            : <EmptyState title="No support action recorded" description="Coordinator follow-up will appear here if one is assigned." />}
          <Link className="text-link" to="/student/interventions">View support actions <ArrowRight size={15} /></Link>
        </Card>
      </div>
      <p className="disclaimer-line"><HeartHandshake size={16} aria-hidden="true" /> A coordinator reviews context before suggesting additional support.</p>
    </>;
  }}</ResourceFrame>;
}

export function StudentPerformancePage() {
  const { student, enrollment } = useStudentContext();
  const resource = useResource(() => enrollment ? studentsApi.performance(student.id, enrollment.id) : Promise.resolve([]), [student?.id, enrollment?.id]);
  return <><PageHeader eyebrow="YOUR LEARNING RECORD" title="Performance" description="Scores recorded for your selected course. These results show what has been recorded so far." />
    {!enrollment ? <EnrollmentEmpty /> : <ResourceFrame resource={resource} label="Loading academic records">{(records) => {
      const scores = records.filter((row) => row.score != null).slice().reverse();
      const chart = lineData(scores.map((row) => row.submitted_day != null ? `Day ${row.submitted_day}` : formatDate(row.occurred_on)), [
        { label: 'Recorded score', values: scores.map((row) => row.score), color: '#315f55' },
      ]);
      const columns = [
        { key: 'record_type', label: 'Record', render: (row) => titleCase(row.record_type) },
        { key: 'score', label: 'Score', render: (row) => formatScore(row.score) },
        { key: 'submitted_day', label: 'Course day', render: (row) => row.submitted_day == null ? '—' : `Day ${row.submitted_day}` },
        { key: 'assessment_key', label: 'Assessment', render: (row) => row.assessment_key || '—' },
        { key: 'recorded_at', label: 'Recorded', render: (row) => formatDate(row.recorded_at) },
      ];
      return <div className="stack-lg"><ChartCard title="Recorded scores" detail="Assessment scores ordered by submission day when available" data={chart} emptyDescription="Scores will appear here when they are added to your academic record." />
        <Card><SectionHeading title="Academic records" detail={`${records.length} record${records.length === 1 ? '' : 's'} for ${enrollment.code_module}`} />
          <DataTable columns={columns} rows={records} emptyTitle="No academic records" emptyDescription="Your coordinator can add scores as they become available." />
        </Card></div>;
    }}</ResourceFrame>}
  </>;
}

export function StudentEngagementPage() {
  const { student, enrollment } = useStudentContext();
  const resource = useResource(() => enrollment ? studentsApi.engagement(student.id, enrollment.id) : Promise.resolve([]), [student?.id, enrollment?.id]);
  return <><PageHeader eyebrow="COURSE ACTIVITY" title="Engagement" description="A view of recorded interactions with course learning materials. VLE activity is not attendance or proof of learning." />
    {!enrollment ? <EnrollmentEmpty /> : <ResourceFrame resource={resource} label="Loading weekly activity">{(records) => {
      const ordered = [...records].sort((a, b) => a.week_index - b.week_index);
      const chart = lineData(ordered.map((row) => `Week ${row.week_index + 1}`), [
        { label: 'VLE clicks', values: ordered.map((row) => row.clicks), color: '#315f55' },
        { label: 'Active days', values: ordered.map((row) => row.active_days), color: '#d0a36c' },
      ]);
      const weeksActive = records.filter((row) => row.clicks > 0).length;
      const totalClicks = records.reduce((sum, row) => sum + row.clicks, 0);
      return <div className="stack-lg"><div className="metric-grid metric-grid-three">
        <MetricCard label="Recorded clicks" value={totalClicks.toLocaleString()} note="Across available weeks" icon={Activity} />
        <MetricCard label="Weeks with activity" value={weeksActive} note={`${records.length} weekly entries`} icon={CalendarDays} />
        <MetricCard label="Average active days" value={records.length ? (records.reduce((sum, row) => sum + row.active_days, 0) / records.length).toFixed(1) : '—'} note="Per recorded week" icon={BookOpenCheck} />
      </div>
      <ChartCard title="Activity by course week" detail="Clicks and distinct active days reported for each week" data={chart} />
      <Card><SectionHeading title="Weekly records" detail="Distinct site and activity-type counts reflect recorded source values" />
        {records.length ? <div className="week-grid">{ordered.map((row) => <article className="week-card" key={row.id}>
          <div className="week-card-top"><strong>Week {row.week_index + 1}</strong><span>{row.active_days} active day{row.active_days === 1 ? '' : 's'}</span></div>
          <div className="week-clicks">{row.clicks.toLocaleString()} <small>clicks</small></div>
          <div className="week-tags"><span>{row.metrics?.active_site_ids?.length ?? 0} sites</span><span>{row.metrics?.activity_types?.length ?? 0} activity types</span></div>
        </article>)}</div> : <EmptyState title="No engagement data" description="Weekly learning-material activity will appear when it is recorded." />}
      </Card><p className="disclaimer-line"><Activity size={16} aria-hidden="true" />Activity records describe platform interactions; they do not measure attendance, effort, or understanding.</p></div>;
    }}</ResourceFrame>}
  </>;
}

export function StudentPredictionsPage() {
  const { student, enrollment } = useStudentContext();
  const resource = useResource(() => enrollment ? predictionsApi.forStudent(student.id, enrollment.id) : Promise.resolve([]), [student?.id, enrollment?.id]);
  return <><PageHeader eyebrow="DECISION SUPPORT" title="Support review" description="Model outputs are prompts for a human conversation, not predictions of your personal outcome." />
    {!enrollment ? <EnrollmentEmpty /> : <ResourceFrame resource={resource} label="Loading support reviews">{(predictions) => {
      const sorted = sortByDateDescending(predictions);
      const chronological = [...sorted].reverse();
      return <div className="stack-lg">
        {sorted[0] && <Card className="latest-review"><SectionHeading title="Most recent model output" detail="A coordinator considers the wider context before acting." /><PredictionSummary prediction={sorted[0]} />
          <div className="review-detail-grid"><div><span>Threshold used</span><strong>{(sorted[0].threshold * 100).toFixed(0)} / 100</strong></div><div><span>Feature contract</span><strong>{sorted[0].feature_version}</strong></div><div><span>Recorded</span><strong>{formatDate(sorted[0].created_at)}</strong></div></div>
          {sorted[0].observed_signals && <div className="signals-block"><h3>Observed inputs</h3><p>These are recorded signals provided to the model. They are not individual causes.</p>
            <div className="signal-grid">{Object.entries(sorted[0].observed_signals).filter(([key, value]) => key !== 'weekly_sequence' && value != null).map(([key, value]) => <div key={key}><span>{titleCase(key)}</span><strong>{typeof value === 'number' ? Number(value.toFixed(2)).toLocaleString() : String(value)}</strong></div>)}</div>
          </div>}
        </Card>}
        <ChartCard title="Model score history" detail="Scores are shown as stored and are not calibrated probabilities" data={lineData(chronological.map((row) => formatDate(row.created_at, { month: 'short', day: 'numeric' })), [{ label: 'Support priority score', values: chronological.map((row) => row.support_priority_score * 100), color: '#a36d46' }])} emptyDescription="A coordinator has not recorded a model review for this course yet." />
        <Card><SectionHeading title="Review history" detail="Model and feature versions are included for transparency" />
          {sorted.length ? <div className="review-history">{sorted.map((row) => <div className="review-history-row" key={row.id}><div><StatusBadge status={row.priority_band} /><strong>{Math.round(row.support_priority_score * 100)} / 100 score</strong></div><div><span>{titleCase(row.model_name)} · v{row.model_version}</span><time>{formatDate(row.created_at)}</time></div></div>)}</div>
            : <EmptyState title="No review history" description="If a coordinator records a model review, it will appear here." />}
        </Card>
      </div>;
    }}</ResourceFrame>}
  </>;
}

export function StudentStudyPlanPage() {
  const { student, enrollment } = useStudentContext();
  const resource = useResource(async () => {
    if (!enrollment) return { plans: [], messages: [], predictions: [] };
    const [plans, messages, predictions] = await Promise.all([
      plansApi.list(student.id, enrollment.id), plansApi.messages(student.id), predictionsApi.forStudent(student.id, enrollment.id),
    ]);
    return { plans, messages, predictions };
  }, [student?.id, enrollment?.id]);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [assistantQuestion, setAssistantQuestion] = useState('');
  const [assistantAnswer, setAssistantAnswer] = useState(null);
  const [assistantError, setAssistantError] = useState('');
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [progressBusy, setProgressBusy] = useState(null);

  async function createPlan() {
    setCreating(true); setActionError(null); setSuccess(false);
    try {
      const result = await plansApi.create(student.id, enrollment.id);
      resource.setData({ ...resource.data, plans: [result.study_plan, ...(resource.data?.plans || [])], messages: [result.motivational_message, ...(resource.data?.messages || [])] });
      setSuccess(true);
    } catch (error) { setActionError(error); }
    finally { setCreating(false); }
  }

  async function updateGoal(index, completed) {
    const current = sortByDateDescending(resource.data?.plans || [])[0];
    if (!current) return;
    setProgressBusy(index);
    setActionError(null);
    const completedGoalIndices = new Set(current.content?.completed_goal_indices || []);
    if (completed) completedGoalIndices.add(index);
    else completedGoalIndices.delete(index);
    try {
      const updated = await plansApi.updateProgress(student.id, current.id, [...completedGoalIndices]);
      resource.setData({ ...resource.data,
        plans: resource.data.plans.map((plan) => plan.id === updated.id ? updated : plan) });
    } catch (error) { setActionError(error); }
    finally { setProgressBusy(null); }
  }

  async function askAssistant(event) {
    event.preventDefault();
    setAssistantBusy(true);
    setAssistantError('');
    setAssistantAnswer(null);
    try {
      const answer = await plansApi.askAssistant(enrollment.id, assistantQuestion);
      setAssistantAnswer(answer);
      setAssistantQuestion('');
    } catch (error) {
      setAssistantError(friendlyError(error));
    } finally { setAssistantBusy(false); }
  }

  return <><PageHeader eyebrow="PERSONAL SUPPORT" title="Study plan" description="Practical suggestions to adapt to your schedule, priorities, and learning preferences." />
    <ResourceFrame resource={resource} label="Loading your study plan">{(data) => {
      if (!enrollment) return <EnrollmentEmpty />;
      const plans = sortByDateDescending(data.plans);
      const current = plans[0];
      const prediction = latestPrediction(data.predictions);
      const message = sortByDateDescending(data.messages)[0];
      const completedGoals = new Set(current?.content?.completed_goal_indices || []);
      return <div className="stack-lg">
        {actionError && <div className="form-alert" role="alert">{(awaitFriendlyError(actionError))}</div>}
        {success && <SuccessNotice>Your supportive study plan is ready.</SuccessNotice>}
        <Card className="plan-action-card"><div><span className="eyebrow">SUPPORTIVE RECOMMENDATIONS</span><h2>{current?.content?.title || 'Choose a helpful next step'}</h2><p>Suggestions are optional starting points. Adjust them to fit your circumstances.</p></div>
          <button className="button button-primary" onClick={createPlan} disabled={creating || !prediction}>{creating ? 'Preparing suggestions…' : current ? 'Create another plan' : 'Create a study plan'}</button>
        </Card>
        {!prediction && <p className="inline-hint">A coordinator must first record a support review before a study plan can be generated.</p>}
        <div className="study-plan-grid">
          <Card><SectionHeading title="Suggested activities" detail="Based on your recorded course context" />
            {current?.content?.actions?.length ? <ol className="action-list">{current.content.actions.map((action, index) => <li key={`${index}-${action}`}><span className="action-number">{String(index + 1).padStart(2, '0')}</span><span>{action}</span></li>)}</ol>
              : <EmptyState title="No recommendations yet" description="When a plan is created, its suggested activities will appear here." />}
            {current?.content?.priorities?.length > 0 && <><h3>Current priorities</h3><ul>{current.content.priorities.map((priority) => <li key={priority}>{priority}</li>)}</ul></>}
            {current?.content?.schedule?.length > 0 && <><h3>Suggested schedule</h3><ul>{current.content.schedule.map((item) => <li key={item}>{item}</li>)}</ul></>}
            {current?.content?.goals?.length > 0 && <><h3>Goals and progress</h3><p>{completedGoals.size} of {current.content.goals.length} goals marked complete.</p><ul className="action-list">{current.content.goals.map((goal, index) => <li key={`${index}-${goal}`}>
              <label><input type="checkbox" checked={completedGoals.has(index)} disabled={progressBusy !== null} onChange={(event) => updateGoal(index, event.target.checked)} />{goal}</label>
            </li>)}</ul></>}
          </Card>
          <Card><SectionHeading title="A note for you" detail="Encouragement, not a judgment" />
            {message ? <blockquote className="motivation-quote">“{message.content}”<cite>{message.source === 'llm' ? 'Support recommendation' : 'Local supportive message'} · {formatDate(message.created_at)}</cite></blockquote>
              : <EmptyState title="No message yet" description="A supportive message will be shown after a plan is created." />}
            {current && <div className="plan-foot"><StatusBadge status={current.status} /><span>Created {formatDate(current.created_at)}</span><span>{current.generated_by_llm ? 'AI-assisted recommendation' : 'Local recommendation'}</span></div>}
          </Card>
        </div>
        <Card><SectionHeading title="Ask about your recorded course data" detail="The assistant receives only this student's stored summary, records, visible support actions, study plan, and assessment schedule. It cannot see other students or unstored course materials." />
          <form className="intervention-form" onSubmit={askAssistant}>
            <label htmlFor="support-assistant-question">Your question</label>
            <textarea id="support-assistant-question" maxLength={1000} value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} placeholder="Ask about a score, activity record, support action, or study goal." required />
            <button className="button button-primary" type="submit" disabled={assistantBusy || !assistantQuestion.trim() || !prediction}>{assistantBusy ? 'Checking your records…' : 'Ask the support assistant'}</button>
          </form>
          {!prediction && <p className="inline-hint">A coordinator review is required before the assistant can use a current course context.</p>}
          {assistantError && <div className="form-alert" role="alert">{assistantError}</div>}
          {assistantAnswer && <div className="plan-preview" role="status"><h3>Answer from {assistantAnswer.source === 'llm' ? 'the AI support assistant' : 'local support guidance'}</h3><p>{assistantAnswer.answer}</p></div>}
        </Card>
        <Card><SectionHeading title="Earlier plans" detail="You remain in control of which suggestions to use." />
          {plans.length > 1 ? <ul className="past-plan-list">{plans.slice(1).map((plan) => <li key={plan.id}><div><strong>{plan.content?.title || 'Study plan'}</strong><span>{formatDate(plan.created_at)}</span></div><StatusBadge status={plan.status} /></li>)}</ul>
            : <EmptyState title="No earlier plans" description="Future plans will be listed here." />}
        </Card>
      </div>;
    }}</ResourceFrame>
  </>;
}

function awaitFriendlyError(error) {
  if (!error?.response) return 'The service could not be reached. Check your connection and try again.';
  if (error.response.status === 409) return error.response.data?.detail || 'A coordinator review is needed first.';
  if (error.response.status === 401) return 'Your session has expired. Please sign in again.';
  if (error.response.status === 403) return 'Your account does not have permission to do that.';
  if (error.response.status >= 500) return 'The service had a problem. Please try again in a moment.';
  return 'The plan could not be prepared. Please try again.';
}

export function StudentMotivationPage() {
  const { student } = useStudentContext();
  const resource = useResource(() => plansApi.messages(student.id), [student?.id]);
  return <><PageHeader eyebrow="ENCOURAGEMENT" title="Messages for your journey" description="Short reminders connected with study plans, shared to encourage—not to measure—your progress." />
    <ResourceFrame resource={resource} label="Loading your messages">{(messages) => {
      const ordered = sortByDateDescending(messages);
      return ordered.length ? <div className="message-grid">{ordered.map((message) => <Card className="message-card" key={message.id}>
        <span className="message-icon"><MessageCircleHeart size={18} aria-hidden="true" /></span><blockquote>“{message.content}”</blockquote>
        <div><StatusBadge status={message.source} /><time>{formatDate(message.created_at)}</time></div>
      </Card>)}</div> : <Card><EmptyState title="No messages yet" description="Supportive messages appear here when a study plan is created." action={<Link className="text-link" to="/student/study-plan">Open study plan <ArrowRight size={15} /></Link>} /></Card>;
    }}</ResourceFrame>
  </>;
}

export function StudentInterventionsPage() {
  const { student, enrollment } = useStudentContext();
  const resource = useResource(() => enrollment ? interventionsApi.list() : Promise.resolve([]),
    [student?.id, enrollment?.id]);

  return <><PageHeader eyebrow="COORDINATOR SUPPORT" title="Support actions"
      description="Review support actions recorded for your selected course." />
    {!enrollment ? <EnrollmentEmpty /> : <ResourceFrame resource={resource} label="Loading support actions">{(records) => {
      const actions = records.filter((record) => record.enrollment_id === enrollment.id);
      return <Card><SectionHeading title={`Support actions for ${enrollment.code_module}`}
        detail="These notes are here to support a conversation with your coordinator." />
        {actions.length ? <ul className="activity-list">{sortByDateDescending(actions).map((action) => <li key={action.id}>
          <span className="activity-icon"><HeartHandshake size={16} aria-hidden="true" /></span>
          <div className="activity-copy"><strong>{action.title}</strong>
            <span>{action.notes || 'No additional notes.'}</span>
            {action.due_date && <span>Due {formatDate(action.due_date)}</span>}
          </div>
          <StatusBadge status={action.status} />
        </li>)}</ul> : <EmptyState title="No support actions yet"
          description="Any support action your coordinator records for this course will appear here." />}
      </Card>;
    }}</ResourceFrame>}
  </>;
}

export function StudentProfilePage() {
  const { student, enrollment } = useStudentContext();
  const { user } = useAuth();
  return <><PageHeader eyebrow="ACCOUNT" title="My profile" description="Your account and course enrollment information." />
    <div className="profile-grid"><Card className="profile-card"><span className="profile-avatar">{user.email[0].toUpperCase()}</span><div><span className="eyebrow">STUDENT ACCOUNT</span><h2>{user.email}</h2><p>Profile created {formatDate(student.created_at)}</p></div>
      <div className="profile-facts"><div><span>Account type</span><strong>Student</strong></div><div><span>Enrollment number</span><strong>{student.enrollment_number || 'Not assigned'}</strong></div></div>
      <TechnicalReference label="Technical student reference" value={student.id} /></Card>
      <Card><SectionHeading title="Course enrollments" detail="Course information recorded by your institution" />
        {student.enrollments?.length ? <ul className="enrollment-list">{student.enrollments.map((item) => <li key={item.id} className={item.id === enrollment?.id ? 'enrollment-selected' : ''}>
          <div><strong>{item.code_module} · {item.code_presentation}</strong><span>{item.is_active ? 'Current enrollment' : 'Inactive enrollment'}</span></div><StatusBadge status={item.is_active ? 'active' : 'cancelled'} />
        </li>)}</ul> : <EnrollmentEmpty />}
      </Card></div>
    <p className="disclaimer-line"><NotebookPen size={16} aria-hidden="true" />If an account or course detail needs correction, contact your institution's coordinator.</p>
  </>;
}
