import { useState } from 'react';
import { studentsApi } from '../api/services';
import { friendlyError } from '../api/client';
import { useResource } from '../hooks/useResource';
import { Card, SectionHeading } from './Primitives';
import { Field, SelectField } from './Forms';
import { EmptyState, ErrorState, LoadingState, SuccessNotice } from './States';

const optionalInteger = (value) => value.trim() === '' ? null : Number(value);

export function CoordinatorEnrollmentSetup({ studentId, onCreated }) {
  const [form, setForm] = useState({ code_module: '', code_presentation: '', registration_day: '',
    num_of_prev_attempts: '', studied_credits: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const enrollment = await studentsApi.createEnrollment(studentId, {
        code_module: form.code_module.trim().toUpperCase(),
        code_presentation: form.code_presentation.trim().toUpperCase(),
        registration_day: optionalInteger(form.registration_day),
        num_of_prev_attempts: optionalInteger(form.num_of_prev_attempts),
        studied_credits: optionalInteger(form.studied_credits),
      });
      setForm({ code_module: '', code_presentation: '', registration_day: '', num_of_prev_attempts: '', studied_credits: '' });
      onCreated(enrollment);
    } catch (requestError) { setError(friendlyError(requestError)); }
    finally { setBusy(false); }
  }

  return <Card><SectionHeading title="Add a course enrollment" detail="Enrollment context is used to organize academic and weekly activity records." />
    {error && <div className="form-alert" role="alert">{error}</div>}
    <form className="data-entry-form" onSubmit={submit}>
      <div className="data-entry-grid">
        <Field id="new-module" label="Module code" required maxLength={8} value={form.code_module}
          onChange={(event) => setForm({ ...form, code_module: event.target.value })} placeholder="e.g. AAA" />
        <Field id="new-presentation" label="Presentation code" required maxLength={8} value={form.code_presentation}
          onChange={(event) => setForm({ ...form, code_presentation: event.target.value })} placeholder="e.g. 2014J" />
        <Field id="new-registration-day" label="Registration day" type="number" min={-322} max={49} step={1}
          value={form.registration_day} onChange={(event) => setForm({ ...form, registration_day: event.target.value })}
          hint="Optional; relative to course start." />
        <Field id="new-previous-attempts" label="Previous attempts" type="number" min={0} max={6} step={1}
          value={form.num_of_prev_attempts} onChange={(event) => setForm({ ...form, num_of_prev_attempts: event.target.value })} />
        <Field id="new-studied-credits" label="Studied credits" type="number" min={30} max={655} step={1}
          value={form.studied_credits} onChange={(event) => setForm({ ...form, studied_credits: event.target.value })} />
      </div>
      <button className="button button-primary" type="submit" disabled={busy || !form.code_module.trim() || !form.code_presentation.trim()}>
        {busy ? 'Adding enrollment…' : 'Add enrollment'}
      </button>
    </form>
  </Card>;
}

function parseIntegerList(value, label) {
  if (!value.trim()) return [];
  const items = value.split(',').map((item) => item.trim());
  if (items.some((item) => !/^\d+$/.test(item))) throw new Error(`${label} must be comma-separated nonnegative whole numbers.`);
  return items.map(Number);
}

function parseTextList(value) {
  if (!value.trim()) return [];
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

export function CoordinatorCourseDataEntry({ studentId, enrollment, onChanged }) {
  const schedule = useResource(() => studentsApi.assessmentSchedule(enrollment.id), [enrollment.id]);
  const [queuedAssessments, setQueuedAssessments] = useState([]);
  const [scheduleForm, setScheduleForm] = useState({ assessment_key: '', scheduled_day: '', weight: '' });
  const [scoreForm, setScoreForm] = useState({ assessment_key: '', submitted_day: '', score: '' });
  const [weekForm, setWeekForm] = useState({ week_index: '', clicks: '', active_days: '', active_site_ids: '', activity_types: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const scheduled = schedule.data || [];

  function addScheduledAssessment(event) {
    event.preventDefault(); setError(''); setNotice('');
    const key = scheduleForm.assessment_key.trim();
    if (scheduled.some((item) => item.assessment_key === key) || queuedAssessments.some((item) => item.assessment_key === key)) {
      setError('That assessment key is already in this schedule.'); return;
    }
    setQueuedAssessments((items) => [...items, { assessment_key: key,
      scheduled_day: optionalInteger(scheduleForm.scheduled_day), weight: scheduleForm.weight.trim() ? Number(scheduleForm.weight) : null }]);
    setScheduleForm({ assessment_key: '', scheduled_day: '', weight: '' });
  }

  async function saveSchedule() {
    setBusy(true); setError(''); setNotice('');
    const assessments = [...scheduled.map(({ assessment_key, scheduled_day, weight }) => ({ assessment_key, scheduled_day, weight })), ...queuedAssessments];
    try {
      await studentsApi.replaceAssessmentSchedule(enrollment.id, { assessments });
      schedule.setData(assessments); setQueuedAssessments([]); setNotice('Assessment schedule saved.'); onChanged();
    } catch (requestError) { setError(friendlyError(requestError)); }
    finally { setBusy(false); }
  }

  async function addScore(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await studentsApi.addPerformance(studentId, enrollment.id, { record_type: 'assessment_score',
        assessment_key: scoreForm.assessment_key, submitted_day: Number(scoreForm.submitted_day), score: Number(scoreForm.score) });
      setScoreForm({ assessment_key: '', submitted_day: '', score: '' }); setNotice('Assessment score recorded.'); onChanged();
    } catch (requestError) { setError(friendlyError(requestError)); }
    finally { setBusy(false); }
  }

  async function addEngagement(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await studentsApi.addEngagement(studentId, enrollment.id, { week_index: Number(weekForm.week_index),
        clicks: Number(weekForm.clicks), active_days: Number(weekForm.active_days),
        active_site_ids: parseIntegerList(weekForm.active_site_ids, 'Site IDs'),
        activity_types: parseTextList(weekForm.activity_types) });
      setWeekForm({ week_index: '', clicks: '', active_days: '', active_site_ids: '', activity_types: '' });
      setNotice('Weekly activity recorded.'); onChanged();
    } catch (requestError) { setError(requestError instanceof Error && !requestError.response ? requestError.message : friendlyError(requestError)); }
    finally { setBusy(false); }
  }

  return <section className="coordinator-data-entry" aria-label="Course data entry">
    <SectionHeading title="Course records" detail="Enter institution-recorded values. The early models use scheduled assessments and VLE activity from course days 0–55." />
    {error && <div className="form-alert" role="alert">{error}</div>}{notice && <SuccessNotice>{notice}</SuccessNotice>}
    <div className="data-entry-grid data-entry-cards">
      <Card><SectionHeading title="Assessment schedule" detail="Assessment keys link due dates to recorded scores." />
        {schedule.loading ? <LoadingState label="Loading assessment schedule" /> : schedule.error ? <ErrorState error={schedule.error} onRetry={schedule.retry} /> : <>
          {scheduled.length || queuedAssessments.length ? <ul className="schedule-list">{[...scheduled, ...queuedAssessments].map((item) => <li key={item.assessment_key}>
            <strong>{item.assessment_key}</strong><span>{item.scheduled_day == null ? 'Date not recorded' : `Day ${item.scheduled_day}`}</span><span>{item.weight == null ? 'Weight not recorded' : `${item.weight}%`}</span>
          </li>)}</ul> : <EmptyState title="No assessments scheduled" description="Add the source assessment key and course-relative due day." />}
          <form className="data-entry-form" onSubmit={addScheduledAssessment}>
            <div className="data-entry-grid">
              <Field id="schedule-key" label="Assessment key" required maxLength={64} pattern="[A-Za-z0-9_-]+" value={scheduleForm.assessment_key}
                onChange={(event) => setScheduleForm({ ...scheduleForm, assessment_key: event.target.value })} />
              <Field id="schedule-day" label="Scheduled day" type="number" min={-365} max={500} step={1} value={scheduleForm.scheduled_day}
                onChange={(event) => setScheduleForm({ ...scheduleForm, scheduled_day: event.target.value })} />
              <Field id="schedule-weight" label="Weight (%)" type="number" min={0} max={100} step="any" value={scheduleForm.weight}
                onChange={(event) => setScheduleForm({ ...scheduleForm, weight: event.target.value })} />
            </div>
            <button className="button button-secondary" type="submit" disabled={!scheduleForm.assessment_key.trim()}>Add to schedule</button>
          </form>
          {queuedAssessments.length > 0 && <button className="button button-primary" type="button" disabled={busy}
            onClick={saveSchedule}>{busy ? 'Saving…' : 'Save assessment schedule'}</button>}
        </>}
      </Card>

      <Card><SectionHeading title="Assessment score" detail="Record a score against a scheduled assessment." />
        <form className="data-entry-form" onSubmit={addScore}>
          <SelectField id="score-assessment-key" label="Assessment" required value={scoreForm.assessment_key}
            onChange={(event) => setScoreForm({ ...scoreForm, assessment_key: event.target.value })}
            options={[{ value: '', label: schedule.loading ? 'Loading schedule…' : 'Select an assessment' }, ...scheduled.map((item) => ({ value: item.assessment_key, label: `${item.assessment_key}${item.scheduled_day == null ? '' : ` · due day ${item.scheduled_day}`}` }))]} />
          <div className="data-entry-grid">
            <Field id="score-day" label="Submission day" type="number" min={0} max={608} step={1} required value={scoreForm.submitted_day}
              onChange={(event) => setScoreForm({ ...scoreForm, submitted_day: event.target.value })} />
            <Field id="score-value" label="Score" type="number" min={0} max={100} step="any" required value={scoreForm.score}
              onChange={(event) => setScoreForm({ ...scoreForm, score: event.target.value })} />
          </div>
          <button className="button button-primary" type="submit" disabled={busy || schedule.loading || schedule.error || !scheduled.length || !scoreForm.assessment_key}>{busy ? 'Saving…' : 'Record score'}</button>
        </form>
      </Card>

      <Card><SectionHeading title="Weekly VLE activity" detail="Record aggregate clicks, active days, and source dimensions." />
        <form className="data-entry-form" onSubmit={addEngagement}>
          <div className="data-entry-grid">
            <Field id="activity-week" label="Course week" type="number" min={0} max={60} step={1} required value={weekForm.week_index}
              onChange={(event) => setWeekForm({ ...weekForm, week_index: event.target.value })} />
            <Field id="activity-clicks" label="VLE clicks" type="number" min={0} max={9481} step={1} required value={weekForm.clicks}
              onChange={(event) => setWeekForm({ ...weekForm, clicks: event.target.value })} />
            <Field id="activity-days" label="Active days" type="number" min={0} max={7} step={1} required value={weekForm.active_days}
              onChange={(event) => setWeekForm({ ...weekForm, active_days: event.target.value })} />
            <Field id="activity-sites" label="Distinct site IDs" value={weekForm.active_site_ids}
              onChange={(event) => setWeekForm({ ...weekForm, active_site_ids: event.target.value })} hint="Comma-separated IDs, if available." />
            <Field id="activity-types" label="Activity types" value={weekForm.activity_types}
              onChange={(event) => setWeekForm({ ...weekForm, activity_types: event.target.value })} hint="Comma-separated source values, if available." />
          </div>
          <button className="button button-primary" type="submit" disabled={busy || weekForm.week_index === '' || weekForm.clicks === '' || weekForm.active_days === ''}>{busy ? 'Saving…' : 'Record weekly activity'}</button>
          <p className="form-footnote">Weeks 0–7 and their distinct dates feed the current early-window models. Activity does not indicate attendance or learning quality.</p>
        </form>
      </Card>
    </div>
  </section>;
}
