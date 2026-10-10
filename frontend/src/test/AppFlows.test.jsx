import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App';
import { AuthProvider } from '../auth/AuthContext';
import { TOKEN_KEY } from '../api/client';
import { CoordinatorImportsPage } from '../pages/CoordinatorImportsPage';
import { AppShell } from '../components/AppShell';

const services = vi.hoisted(() => ({
  authApi: { register: vi.fn(), login: vi.fn(), me: vi.fn(), changePassword: vi.fn() },
  studentsApi: { me: vi.fn(), detail: vi.fn(), list: vi.fn(), createEnrollment: vi.fn(), assessmentSchedule: vi.fn(),
    replaceAssessmentSchedule: vi.fn(), addPerformance: vi.fn(), addEngagement: vi.fn(), performance: vi.fn(), engagement: vi.fn(), cluster: vi.fn() },
  predictionsApi: { forStudent: vi.fn(), recent: vi.fn(), create: vi.fn(), createSequence: vi.fn(), gradeScoresForStudent: vi.fn(), createGradeScore: vi.fn() },
  clustersApi: { recent: vi.fn(), profiles: vi.fn(), assign: vi.fn() },
  interventionsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() },
  plansApi: { list: vi.fn(), create: vi.fn(), messages: vi.fn(), updateProgress: vi.fn(), askAssistant: vi.fn() },
  analyticsApi: { overview: vi.fn(), riskTrends: vi.fn(), engagement: vi.fn(), students: vi.fn() },
  importsApi: { template: vi.fn(), validate: vi.fn(), create: vi.fn() },
  accessRequestsApi: { mine: vi.fn(), create: vi.fn(), pending: vi.fn(), review: vi.fn() },
}));

vi.mock('../api/services', () => services);
vi.mock('react-chartjs-2', () => ({
  // Expose the plotted labels and values so tests can check what a chart was given, not only that it rendered.
  Bar: ({ 'aria-label': label, data }) => <div role="img" aria-label={label}
    data-labels={JSON.stringify(data.labels)} data-values={JSON.stringify(data.datasets.map((set) => set.data))} />,
  Doughnut: ({ 'aria-label': label }) => <div role="img" aria-label={label} />,
  Line: ({ 'aria-label': label }) => <div role="img" aria-label={label} />,
}));

const studentUser = { id: 'user-1', email: 'student@example.edu', role: 'student', is_active: true };
const coordinatorUser = { id: 'user-2', email: 'coordinator@example.edu', role: 'coordinator', is_active: true };
const enrollment = { id: 'enroll-1', code_module: 'AAA', code_presentation: '2013B', is_active: true };
const scheduledAssessment = { id: 'schedule-1', enrollment_id: 'enroll-1', assessment_key: 'A1752', scheduled_day: 28, weight: 10, created_at: '2025-01-01T00:00:00Z' };
const studentProfile = {
  id: 'student-1', user_id: 'user-1', created_at: '2025-01-01T00:00:00Z',
  enrollment_number: '2403031500001', access_approved: true,
  user: studentUser, enrollments: [enrollment],
};
const prediction = {
  id: 'prediction-1', enrollment_id: 'enroll-1', model_name: 'random_forest', model_version: '1.0.0',
  feature_version: 'oulad-early-risk-v1', support_priority_score: 0.63, threshold: 0.4,
  priority_band: 'review_for_support', observed_signals: { early_vle_clicks: 125, early_vle_active_days: 4 },
  created_at: '2025-01-15T10:00:00Z',
};
const plan = { id: 'plan-1', enrollment_id: 'enroll-1', content: {
  title: 'A steady plan', priorities: ['Review feedback from your recorded assessments.'],
  actions: ['Review one topic'], schedule: ['Choose two study sessions this week.'],
  goals: ['Complete two focused study sessions and mark them complete here.'],
  completed_goal_indices: [],
},
  status: 'draft', generated_by_llm: false, created_at: '2025-01-15T10:00:00Z' };
const message = { id: 'message-1', content: 'Small steps count.', source: 'fallback', created_at: '2025-01-15T10:00:00Z' };
const supportAction = { id: 'support-1', enrollment_id: 'enroll-1', title: 'Check-in', notes: 'Review next assessment.',
  status: 'open', due_date: null, created_at: '2025-01-15T10:00:00Z' };
const savedRecord = (sourceRow, overrides = {}) => ({ source_row: sourceRow, enrollment_id: `e-${sourceRow}`,
  prediction_id: `p-${sourceRow}`, cluster_record_id: `c-${sourceRow}`, cluster_id: 0, forecast_id: `f-${sourceRow}`, ...overrides });

function renderApp(path = '/login') {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

function renderShell(path = '/') {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppShell><div>Workspace content</div></AppShell></AuthProvider></MemoryRouter>);
}

function setStudentDefaults() {
  services.authApi.login.mockResolvedValue({ access_token: 'signed-token', expires_in: 1800 });
  services.authApi.register.mockResolvedValue(studentUser);
  services.authApi.me.mockResolvedValue(studentUser);
  services.authApi.changePassword.mockResolvedValue({ message: 'Password updated.' });
  services.studentsApi.me.mockResolvedValue(studentProfile);
  services.accessRequestsApi.mine.mockResolvedValue({
    access_approved: false, enrollment_number: studentProfile.enrollment_number, request: null,
  });
  services.accessRequestsApi.create.mockResolvedValue({ status: 'pending', id: 'request-1' });
  services.accessRequestsApi.pending.mockResolvedValue([]);
  services.accessRequestsApi.review.mockResolvedValue({ status: 'approved' });
  services.studentsApi.detail.mockResolvedValue(studentProfile);
  services.studentsApi.createEnrollment.mockResolvedValue(enrollment);
  services.studentsApi.assessmentSchedule.mockResolvedValue([scheduledAssessment]);
  services.studentsApi.replaceAssessmentSchedule.mockResolvedValue({ enrollment_id: enrollment.id, assessment_count: 1 });
  services.studentsApi.addPerformance.mockResolvedValue({ id: 'new-score' });
  services.studentsApi.addEngagement.mockResolvedValue({ id: 'new-week' });
  services.studentsApi.performance.mockResolvedValue([{ id: 'score-1', record_type: 'assessment_score', score: 82,
    assessment_key: '1752', submitted_day: 20, occurred_on: null, recorded_at: '2025-01-12T10:00:00Z' }]);
  services.studentsApi.engagement.mockResolvedValue([{ id: 'week-1', week_index: 0, clicks: 125, active_days: 4,
    metrics: { active_site_ids: [1, 2], activity_types: ['resource'] }, recorded_at: '2025-01-12T10:00:00Z' }]);
  services.studentsApi.cluster.mockResolvedValue({ cluster_id: 0, observed_signals: {}, assigned_at: '2025-01-12T10:00:00Z' });
  services.predictionsApi.forStudent.mockResolvedValue([prediction]);
  services.predictionsApi.recent.mockResolvedValue([prediction]);
  services.predictionsApi.create.mockResolvedValue(prediction);
  services.predictionsApi.createSequence.mockResolvedValue({ ...prediction, model_name: 'lstm_weekly' });
  services.predictionsApi.gradeScoresForStudent.mockResolvedValue([]);
  services.predictionsApi.createGradeScore.mockResolvedValue({ predicted_score: 72.5 });
  services.clustersApi.recent.mockResolvedValue([]);
  services.clustersApi.profiles.mockResolvedValue([{ cluster_id: 0, student_count: 1, enrollment_count: 1,
    model_version: '1.0.0', feature_version: 'oulad-early-risk-v1', median_features: {
      early_vle_clicks: 125, early_vle_active_days: 4, early_vle_active_weeks: 1,
      early_assessment_mean: 82, early_assessment_count: 1, early_on_time_rate: 1,
      early_assessment_coverage: 1, early_vle_active_sites: 2, early_vle_activity_types: 1,
    } }]);
  services.interventionsApi.list.mockResolvedValue([]);
  services.interventionsApi.create.mockResolvedValue({ id: 'intervention-1' });
  services.interventionsApi.update.mockResolvedValue({ id: 'intervention-1' });
  services.plansApi.list.mockResolvedValue([plan]);
  services.plansApi.create.mockResolvedValue({ study_plan: plan, motivational_message: message, generated_by_llm: false });
  services.plansApi.messages.mockResolvedValue([message]);
  services.plansApi.updateProgress.mockImplementation(async (_studentId, _planId, indices) => ({
    ...plan, content: { ...plan.content, completed_goal_indices: indices },
  }));
  services.plansApi.askAssistant.mockResolvedValue({ answer: 'Your recorded assessment score is 82.', source: 'llm' });
  services.analyticsApi.overview.mockResolvedValue({ students: 1, enrollments: 1, predictions: 1,
    review_for_support: 1, interventions_open: 0,
    risk_distribution: { review_for_support: 1, no_flag_from_model: 0, unscored: 0 },
    outcome_forecast_distribution: { review_for_support: 0, no_flag_from_model: 0, not_generated: 1 },
    performance_distribution: { '0-19': 0, '20-39': 0, '40-59': 0, '60-79': 0, '80-100': 1 },
    recorded_score_count: 1, mean_recorded_score: 82,
    imports_total: 1, latest_import: { filename: 'demo.csv', total_rows: 1,
      valid_rows: 1, invalid_rows: 0, created_at: '2025-01-15T10:00:00Z' },
    intervention_status_counts: { open: 0, in_progress: 0, completed: 0, cancelled: 0 } });
  services.analyticsApi.riskTrends.mockResolvedValue([{ date: '2025-01-15', count: 1, mean_score: 0.63 }]);
  services.analyticsApi.engagement.mockResolvedValue({ weeks: [{ week_index: 0, records: 1, mean_clicks: 125, mean_active_days: 4 }] });
  services.analyticsApi.students.mockResolvedValue({ items: [{ student_id: 'student-1', email: studentUser.email,
    created_at: '2025-01-01T00:00:00Z', enrollment_count: 1, latest_prediction: prediction }], total: 1, offset: 0, limit: 25 });
}

beforeEach(() => {
  window.localStorage.clear();
  Object.values(services).forEach((group) => Object.values(group).forEach((mock) => mock?.mockReset?.()));
  setStudentDefaults();
});

describe('student and coordinator frontend flows', () => {
  it.each([
    ['Support review', 'Support review', () => expect(services.predictionsApi.forStudent).toHaveBeenCalledWith('student-1', 'enroll-1')],
    ['Support actions', 'Support actions', () => expect(services.interventionsApi.list).toHaveBeenCalled()],
    ['Study plan', 'Study plan', () => {
      expect(services.plansApi.list).toHaveBeenCalledWith('student-1', 'enroll-1');
      expect(services.plansApi.messages).toHaveBeenCalledWith('student-1');
      expect(services.predictionsApi.forStudent).toHaveBeenCalledWith('student-1', 'enroll-1');
    }],
  ])('opens the %s page from student navigation and loads its data', async (linkName, heading, verifyRequests) => {
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.authApi.me.mockResolvedValue(studentUser);
    services.studentsApi.me.mockResolvedValue(studentProfile);

    const user = userEvent.setup();
    renderApp('/student/dashboard');

    await user.click(await screen.findByRole('link', { name: linkName }));
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    await waitFor(verifyRequests);
  });

  it('registers, signs in, and opens the student workspace', async () => {
    const user = userEvent.setup();
    renderApp('/register');
    await user.type(screen.getByLabelText('Email address'), 'student@example.edu');
    await user.type(screen.getByLabelText('Password'), 'SecurePass1234');
    await user.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByRole('heading', { name: 'Your overview' })).toBeInTheDocument();
    expect(services.authApi.register).toHaveBeenCalledWith({ email: 'student@example.edu', password: 'SecurePass1234', role: 'student' });
    expect(services.authApi.login).toHaveBeenCalled();
    expect(screen.queryByText(/API endpoint:/i)).not.toBeInTheDocument();
    expect(screen.getAllByText('82 / 100').length).toBeGreaterThan(0);
  });

  it('does not expose the configured API endpoint on login or registration pages', async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp('/login');
    expect(await screen.findByRole('heading', { name: 'Sign in to continue' })).toBeInTheDocument();
    expect(screen.queryByText(/API endpoint:/i)).not.toBeInTheDocument();
    unmount();

    renderApp('/register');
    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument();
    expect(screen.queryByText(/API endpoint:/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Email address'), 'student@example.edu');
    await user.type(screen.getByLabelText('Password'), 'SecurePass1234');
    await user.click(screen.getByRole('button', { name: /create account/i }));
    await screen.findByRole('heading', { name: 'Your overview' });
    expect(services.authApi.register).toHaveBeenCalledWith({ email: 'student@example.edu', password: 'SecurePass1234', role: 'student' });
    expect(services.authApi.login).toHaveBeenCalled();
  });

  it('shows invalid login credentials instead of a session-expired message', async () => {
    const user = userEvent.setup();
    services.authApi.login.mockRejectedValue({
      config: { url: '/auth/login' },
      response: { status: 401, data: { detail: 'Invalid email or password' } },
    });
    renderApp('/login');
    await user.type(screen.getByLabelText('Email address'), 'coordinator@example.edu');
    await user.type(screen.getByLabelText('Password'), 'wrong-password');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
    expect(screen.queryByText('Your session has expired. Please sign in again.')).not.toBeInTheDocument();
    expect(screen.queryByText(/API endpoint:/i)).not.toBeInTheDocument();
  });

  it('shows the coordinator invite error returned by registration', async () => {
    const user = userEvent.setup();
    services.authApi.register.mockRejectedValue({
      config: { url: '/auth/register' },
      response: { status: 403, data: { detail: 'Coordinator registration is invite-only' } },
    });
    renderApp('/register');
    await user.type(screen.getByLabelText('Email address'), 'coordinator@example.edu');
    await user.type(screen.getByLabelText('Password'), 'SecurePass1234');
    await user.selectOptions(screen.getByLabelText('Account type'), 'coordinator');
    await user.type(screen.getByLabelText('Coordinator invitation code'), 'wrong-invite');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Coordinator registration is invite-only');
    expect(screen.queryByText('Your session has expired. Please sign in again.')).not.toBeInTheDocument();
    expect(services.authApi.login).not.toHaveBeenCalled();
  });

  it('keeps unapproved student records gated until a coordinator verifies access', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.authApi.me.mockResolvedValue(studentUser);
    services.studentsApi.me.mockResolvedValue({ ...studentProfile, access_approved: false });
    renderApp('/student/dashboard');
    expect(await screen.findByRole('heading', { name: 'Coordinator verification' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Request access' }));
    expect(await screen.findByText('Your request has been sent for coordinator review.')).toBeInTheDocument();
    expect(services.accessRequestsApi.create).toHaveBeenCalledWith('2403031500001');
    expect(screen.getByText(/academic and support record pages remain unavailable/i)).toBeInTheDocument();
  });

  it('moves through student pages, creates a plan, and signs out', async () => {
    const user = userEvent.setup();
    renderApp('/login');
    await user.type(screen.getByLabelText('Email address'), studentUser.email);
    await user.type(screen.getByLabelText('Password'), 'SecurePass1234');
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByRole('heading', { name: 'Your overview' })).toBeInTheDocument();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('signed-token');

    await user.click(screen.getByRole('link', { name: 'Performance' }));
    expect(await screen.findByRole('heading', { name: 'Performance' })).toBeInTheDocument();
    expect(await screen.findByText('1752')).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Engagement' }));
    expect(await screen.findByRole('heading', { name: 'Engagement' })).toBeInTheDocument();
    expect(screen.getByText('clicks').closest('.week-clicks').textContent).toBe('125 clicks');
    await user.click(screen.getByRole('link', { name: 'Support review' }));
    expect(await screen.findByText('Model score history')).toBeInTheDocument();
    expect(screen.getByText(/not calibrated probabilities/i)).toBeInTheDocument();
    services.interventionsApi.list.mockResolvedValue([supportAction,
      { ...supportAction, id: 'other-course-action', enrollment_id: 'other-enrollment', title: 'Other course action' }]);
    await user.click(screen.getByRole('link', { name: 'Support actions' }));
    expect(await screen.findByRole('heading', { name: 'Support actions' })).toBeInTheDocument();
    expect(await screen.findByText('Check-in')).toBeInTheDocument();
    expect(screen.queryByText('Other course action')).not.toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Study plan' }));
    expect(await screen.findByRole('heading', { name: 'Study plan' })).toBeInTheDocument();
    expect(screen.getByText('Current priorities')).toBeInTheDocument();
    expect(screen.getByText('Suggested schedule')).toBeInTheDocument();
    const goal = screen.getByRole('checkbox', { name: /complete two focused study sessions/i });
    await user.click(goal);
    await waitFor(() => expect(services.plansApi.updateProgress).toHaveBeenCalledWith(
      'student-1', 'plan-1', [0],
    ));
    await user.type(screen.getByLabelText('Your question'), 'What score is recorded?');
    await user.click(screen.getByRole('button', { name: 'Ask the support assistant' }));
    expect(await screen.findByText('Your recorded assessment score is 82.')).toBeInTheDocument();
    expect(services.plansApi.askAssistant).toHaveBeenCalledWith('enroll-1', 'What score is recorded?');
    await user.click(screen.getByRole('button', { name: 'Create another plan' }));
    expect(await screen.findByText('Your supportive study plan is ready.')).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Encouragement' }));
    expect(await screen.findByRole('heading', { name: 'Messages for your journey' })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'My profile' }));
    expect(await screen.findByRole('heading', { name: 'My profile' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /account menu for student@example.edu/i }));
    await user.click(await screen.findByRole('menuitem', { name: 'Sign Out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in to continue' })).toBeInTheDocument();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('opens an accessible account menu and dismisses it with Escape or an outside click', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(studentUser);
    renderShell();

    const trigger = await screen.findByRole('button', { name: `Account menu for ${studentUser.email}` });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    await user.click(trigger);
    expect(await screen.findByRole('menu', { name: 'Account options' })).toBeInTheDocument();
    expect(screen.getByText('Student')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('menuitem', { name: 'My Profile' })).toHaveFocus());
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Change Password' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', { name: 'Account options' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    expect(await screen.findByRole('menu')).toBeInTheDocument();
    await user.click(document.body);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('keeps all coordinator navigation links and closes the mobile drawer through its scrim', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(coordinatorUser);
    renderShell('/coordinator/dashboard');

    await screen.findByRole('link', { name: 'Access requests' });
    const sidebar = screen.getByRole('complementary', { name: 'Main navigation' });
    expect(sidebar.querySelector('.brand button')).toBeNull();
    expect(within(sidebar).getByText('Northstar')).toBeInTheDocument();
    expect(within(sidebar).getByText('Student support')).toBeInTheDocument();
    for (const label of ['Overview', 'Students', 'Engagement groups', 'Interventions', 'CSV imports', 'Access requests']) {
      expect(within(sidebar).getByRole('link', { name: label })).toBeInTheDocument();
    }
    expect(within(sidebar).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    expect(within(sidebar).queryByText('Support works best when it starts with a conversation.')).not.toBeInTheDocument();
    expect(within(sidebar).queryByText(/PHASE 4/)).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: 'Open navigation menu' }));
    expect(sidebar).toHaveClass('sidebar-open');
    await user.click(screen.getByRole('button', { name: 'Close navigation' }));
    expect(sidebar).not.toHaveClass('sidebar-open');
  });

  it.each([
    [studentUser, 'Student'],
    [coordinatorUser, 'Coordinator'],
  ])('shows the correct %s account-menu actions', async (account, roleLabel) => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(account);
    if (account.role === 'student') services.studentsApi.me.mockResolvedValue(studentProfile);
    if (account.role === 'student') renderApp('/student/dashboard');
    else renderShell();

    await user.click(await screen.findByRole('button', { name: `Account menu for ${account.email}` }));
    expect(screen.getByRole('menuitem', { name: 'Change Password' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Sign Out' })).toBeInTheDocument();
    await user.click(await screen.findByRole('menuitem', { name: 'My Profile' }));
    if (account.role === 'student') {
      expect(await screen.findByRole('heading', { name: 'My profile' })).toBeInTheDocument();
      expect(screen.getByText('Course enrollments')).toBeInTheDocument();
    } else {
      const dialog = await screen.findByRole('dialog', { name: 'My Profile' });
      expect(dialog).toHaveTextContent(account.email);
      expect(dialog).toHaveTextContent(roleLabel);
      expect(dialog).toHaveTextContent('Active');
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('dialog', { name: 'My Profile' })).not.toBeInTheDocument();
    }
  });

  it('changes the authenticated user password and requires a fresh sign-in', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(studentUser);
    renderApp('/student/dashboard');

    await user.click(await screen.findByRole('button', { name: `Account menu for ${studentUser.email}` }));
    await user.click(await screen.findByRole('menuitem', { name: 'Change Password' }));
    const passwordDialog = await screen.findByRole('dialog', { name: 'Change Password' });
    expect(passwordDialog).toBeInTheDocument();
    const closeDialog = screen.getByRole('button', { name: 'Close change password' });
    const lastDialogAction = screen.getByRole('button', { name: 'Update password' });
    lastDialogAction.focus();
    await user.keyboard('{Tab}');
    expect(closeDialog).toHaveFocus();
    await user.type(await screen.findByLabelText('Current password'), 'SecurePass1234');
    await user.type(screen.getByLabelText('New password'), 'AnotherSecure5678');
    await user.type(screen.getByLabelText('Confirm new password'), 'AnotherSecure5678');
    await user.click(screen.getByRole('button', { name: 'Update password' }));

    expect(services.authApi.changePassword).toHaveBeenCalledWith({
      current_password: 'SecurePass1234', new_password: 'AnotherSecure5678',
      confirm_password: 'AnotherSecure5678',
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Password updated. Sign in using your new password.');
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('shows password-change API failures without reporting success or signing out', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(studentUser);
    services.authApi.changePassword.mockRejectedValue({
      response: { status: 400, data: { detail: 'Current password is incorrect' } },
    });
    renderApp('/student/dashboard');

    await user.click(await screen.findByRole('button', { name: `Account menu for ${studentUser.email}` }));
    await user.click(await screen.findByRole('menuitem', { name: 'Change Password' }));
    await user.type(await screen.findByLabelText('Current password'), 'wrong');
    await user.type(screen.getByLabelText('New password'), 'AnotherSecure5678');
    await user.type(screen.getByLabelText('Confirm new password'), 'AnotherSecure5678');
    await user.click(screen.getByRole('button', { name: 'Update password' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect');
    expect(screen.getByRole('dialog', { name: 'Change Password' })).toBeInTheDocument();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('existing-token');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('requires authentication before rendering a protected student route', async () => {
    renderApp('/student/dashboard');
    expect(await screen.findByRole('heading', { name: 'Sign in to continue' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Your overview' })).not.toBeInTheDocument();
  });

  it('uses transient token storage for a mocked session without modifying the saved browser login', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'existing-browser-login');
    const values = new Map([[TOKEN_KEY, 'transient-mock-login']]);
    const tokenStorage = {
      getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    };
    render(<MemoryRouter initialEntries={['/student/dashboard']}>
      <AuthProvider tokenStorage={tokenStorage}><App /></AuthProvider>
    </MemoryRouter>);
    await screen.findByRole('heading', { name: 'Your overview' });
    await user.click(screen.getByRole('button', { name: /account menu for student@example.edu/i }));
    await user.click(await screen.findByRole('menuitem', { name: 'Sign Out' }));
    await screen.findByRole('heading', { name: 'Sign in to continue' });
    expect(tokenStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('existing-browser-login');
  });

  it('redirects a student away from coordinator routes using the server role', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(studentUser);
    renderApp('/coordinator/dashboard');
    expect(await screen.findByRole('heading', { name: 'Your overview' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Support overview' })).not.toBeInTheDocument();
  });

  it('lets a coordinator request a numeric final-exam estimate for a supported course', async () => {
    const user = userEvent.setup();
    const supportedEnrollment = { ...enrollment, code_module: 'DDD', code_presentation: '2014J' };
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.studentsApi.detail.mockResolvedValue({ ...studentProfile, enrollments: [supportedEnrollment] });
    services.studentsApi.performance.mockResolvedValue([]);
    services.studentsApi.engagement.mockResolvedValue([]);
    services.studentsApi.cluster.mockResolvedValue(null);
    services.interventionsApi.list.mockResolvedValue([]);
    services.predictionsApi.forStudent.mockResolvedValue([]);
    services.predictionsApi.gradeScoresForStudent.mockResolvedValue([]);
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    renderApp('/coordinator/students/student-1');

    await user.click(await screen.findByRole('button', { name: 'Estimate final exam score' }));
    await waitFor(() => expect(services.predictionsApi.createGradeScore).toHaveBeenCalledWith('student-1', 'enroll-1'));
    expect(await screen.findByText('A numeric final-exam score estimate was saved.')).toBeInTheDocument();
  });

  it('shows a saved numeric final-exam estimate in the student portal', async () => {
    const scoreEstimate = { id: 'grade-1', enrollment_id: 'enroll-1', target_name: 'final_exam_score',
      predicted_score: 72.5, model_name: 'random_forest_final_exam_regressor', model_version: 'oulad-final-exam-v1',
      created_at: '2025-01-15T10:00:00Z' };
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    services.authApi.me.mockResolvedValue(studentUser);
    services.studentsApi.me.mockResolvedValue({ ...studentProfile, enrollments: [{ ...enrollment, code_module: 'DDD' }] });
    services.predictionsApi.gradeScoresForStudent.mockResolvedValue([scoreEstimate]);
    renderApp('/student/dashboard');

    expect(await screen.findByText('72.5 / 100')).toBeInTheDocument();
    expect(services.predictionsApi.gradeScoresForStudent).toHaveBeenCalledWith('student-1', 'enroll-1');
  });

  it('keeps a missing weekly forecast separate from a stored zero model score', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.predictionsApi.forStudent.mockResolvedValue([{ ...prediction, support_priority_score: 0,
      priority_band: 'no_flag_from_model' }]);
    services.studentsApi.performance.mockResolvedValue([{ id: 'zero-score', record_type: 'assessment_score', score: 0 }]);
    renderApp('/student/dashboard');

    expect(await screen.findByRole('heading', { name: 'Your overview' })).toBeInTheDocument();
    expect(screen.getByText('Latest recorded score').closest('section')).toHaveTextContent('0 / 100');
    expect(screen.getByText('Support priority score').parentElement).toHaveTextContent('0 / 100');
    expect(screen.getByText('Insufficient weekly history')).toBeInTheDocument();
    expect(screen.queryByText(/Saved weekly-sequence model score/)).not.toBeInTheDocument();
  });

  it('shows a saved zero weekly forecast as an output', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.predictionsApi.forStudent.mockResolvedValue([{ ...prediction, model_name: 'lstm_weekly',
      support_priority_score: 0, priority_band: 'no_flag_from_model' }]);
    renderApp('/student/dashboard');
    expect(await screen.findByText(/Saved weekly-sequence model score: 0 \/ 100/)).toBeInTheDocument();
    expect(screen.queryByText('Insufficient weekly history')).not.toBeInTheDocument();
  });

  it('shows the assigned enrollment number and keeps the student UUID in diagnostic details', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    renderApp('/student/profile');
    expect(await screen.findByText(studentProfile.enrollment_number)).toBeInTheDocument();
    expect(screen.queryByText(studentProfile.id)).not.toBeInTheDocument();
    await user.click(screen.getByText('Technical student reference'));
    expect(await screen.findByText(studentProfile.id)).toBeInTheDocument();
  });

  it('renders structured assistant validation errors without losing the study plan', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.plansApi.askAssistant.mockRejectedValue({ response: { status: 422,
      data: { detail: [{ loc: ['body', 'question'], msg: 'Question is too long.' }] } } });
    renderApp('/student/study-plan');
    await screen.findByLabelText('Your question');
    await user.type(screen.getByLabelText('Your question'), 'What is recorded?');
    await user.click(screen.getByRole('button', { name: 'Ask the support assistant' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('question: Question is too long.');
    expect(screen.getByRole('heading', { name: 'Study plan' })).toBeInTheDocument();
  });

  it('offers a retry for a failed coordinator overview without reporting an empty cohort', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.analyticsApi.overview.mockRejectedValueOnce({ response: { status: 503,
      data: { detail: 'Overview unavailable.' } } });
    renderApp('/coordinator/dashboard');
    expect(await screen.findByRole('alert')).toHaveTextContent('Overview unavailable.');
    expect(screen.queryByText('No student profiles yet')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Support overview' })).toBeInTheDocument();
  });

  it('identifies an empty coordinator cohort before describing review flags', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'signed-token');
    services.authApi.me.mockResolvedValue(coordinatorUser);
    const overview = await services.analyticsApi.overview();
    services.analyticsApi.overview.mockResolvedValue({ ...overview, students: 0, enrollments: 0 });
    services.analyticsApi.students.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 8 });
    renderApp('/coordinator/dashboard');
    expect(await screen.findByText('No student profiles yet')).toBeInTheDocument();
    expect(screen.queryByText('No students currently flagged for review.')).not.toBeInTheDocument();
  });

  it('lets a coordinator enroll a student and enter source assessment and VLE records', async () => {
    const user = userEvent.setup();
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.studentsApi.detail.mockResolvedValueOnce({ ...studentProfile, enrollments: [] }).mockResolvedValue(studentProfile);
    services.studentsApi.assessmentSchedule.mockResolvedValue([]);
    services.interventionsApi.list.mockResolvedValue([{ ...supportAction, created_at: '2025-01-11T10:00:00Z' }]);
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    renderApp('/coordinator/students/student-1');

    await screen.findByRole('heading', { name: studentUser.email });
    await user.type(screen.getByLabelText('Module code'), 'AAA');
    await user.type(screen.getByLabelText('Presentation code'), '2013B');
    await user.click(screen.getByRole('button', { name: 'Add enrollment' }));
    await screen.findByRole('heading', { name: 'Course records' });
    expect(await screen.findByText(/Scores entered before: no records \/ after: 1 record \(mean 82\.0\)/i)).toBeInTheDocument();
    expect(screen.getByText(/does not show that an intervention caused a change/i)).toBeInTheDocument();
    expect(services.studentsApi.createEnrollment).toHaveBeenCalledWith('student-1', expect.objectContaining({
      code_module: 'AAA', code_presentation: '2013B', registration_day: null,
    }));

    await user.type(screen.getByLabelText('Assessment key'), 'A1752');
    await user.type(screen.getByLabelText('Scheduled day'), '28');
    await user.click(screen.getByRole('button', { name: 'Add to schedule' }));
    await user.click(screen.getByRole('button', { name: 'Save assessment schedule' }));
    await waitFor(() => expect(services.studentsApi.replaceAssessmentSchedule).toHaveBeenCalledWith('enroll-1', {
      assessments: [{ assessment_key: 'A1752', scheduled_day: 28, weight: null }],
    }));

    await user.selectOptions(screen.getByLabelText('Assessment'), 'A1752');
    await user.type(screen.getByLabelText('Submission day'), '29');
    await user.type(screen.getByLabelText('Score'), '88');
    await user.click(screen.getByRole('button', { name: 'Record score' }));
    await waitFor(() => expect(services.studentsApi.addPerformance).toHaveBeenCalledWith('student-1', 'enroll-1', {
      record_type: 'assessment_score', assessment_key: 'A1752', submitted_day: 29, score: 88,
    }));

    await user.type(screen.getByLabelText('Course week'), '0');
    await user.type(screen.getByLabelText('VLE clicks'), '125');
    await user.type(screen.getByLabelText('Active days'), '4');
    await user.type(screen.getByLabelText('Distinct site IDs'), '11,12');
    await user.type(screen.getByLabelText('Activity types'), 'resource,forumng');
    await user.click(screen.getByRole('button', { name: 'Record weekly activity' }));
    await waitFor(() => expect(services.studentsApi.addEngagement).toHaveBeenCalledWith('student-1', 'enroll-1', {
      week_index: 0, clicks: 125, active_days: 4, active_site_ids: [11, 12], activity_types: ['resource', 'forumng'],
    }));
  });

  it('shows coordinator data, filters the roster, reviews a student, and records support', async () => {
    const user = userEvent.setup();
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.authApi.login.mockResolvedValue({ access_token: 'coordinator-token', expires_in: 1800 });
    services.analyticsApi.students.mockResolvedValue({ items: [{ student_id: 'student-1', email: studentUser.email,
      created_at: '2025-01-01T00:00:00Z', enrollment_count: 1, latest_prediction: prediction }], total: 1, offset: 0, limit: 25 });
    renderApp('/login');
    await user.type(screen.getByLabelText('Email address'), coordinatorUser.email);
    await user.type(screen.getByLabelText('Password'), 'SecurePass1234');
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByRole('heading', { name: 'Support overview' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Latest enrollment review status' })).toBeInTheDocument();
    expect(screen.getByText('Recorded score distribution')).toBeInTheDocument();
    expect(screen.getByText('Saved weekly outcome signals')).toBeInTheDocument();
    expect(screen.getByText('demo.csv')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Students' }));
    expect(await screen.findByRole('heading', { name: 'Student roster' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Review status'), 'review_for_support');
    await waitFor(() => expect(services.analyticsApi.students).toHaveBeenLastCalledWith(expect.objectContaining({ risk_filter: 'review_for_support' })));
    const search = screen.getByLabelText('Search email or student reference');
    await user.type(search, 'student@example.edu');
    await user.click(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => expect(services.analyticsApi.students).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'student@example.edu' })));
    await user.click(await screen.findByRole('link', { name: 'View profile' }));
    expect(await screen.findByRole('heading', { name: studentUser.email })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run model review' }));
    expect(await screen.findByText('A new model review was recorded for this enrollment.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Run weekly forecast' }));
    expect(await screen.findByText('A weekly LSTM forecast was saved for human review.')).toBeInTheDocument();
    expect(services.predictionsApi.createSequence).toHaveBeenCalledWith('student-1', 'enroll-1');
    await user.type(screen.getByLabelText('Action title'), 'Offer a check-in');
    await user.type(screen.getByLabelText('Notes'), 'Discuss the next assessment.');
    await user.click(screen.getByRole('button', { name: 'Record support action' }));
    expect(await screen.findByText('Support action recorded.')).toBeInTheDocument();
    expect(services.interventionsApi.create).toHaveBeenCalledWith(expect.objectContaining({ title: 'Offer a check-in', enrollment_id: 'enroll-1' }));
  });

  describe('coordinator overview empty states', () => {
    const emptyBands = { '0-19': 0, '20-39': 0, '40-59': 0, '60-79': 0, '80-100': 0 };

    async function renderOverview(overviewPatch = {}) {
      window.localStorage.setItem(TOKEN_KEY, 'coordinator-token');
      services.authApi.me.mockResolvedValue(coordinatorUser);
      const overview = await services.analyticsApi.overview();
      services.analyticsApi.overview.mockResolvedValue({ ...overview, ...overviewPatch });
      renderApp('/coordinator/dashboard');
      expect(await screen.findByRole('heading', { name: 'Support overview' })).toBeInTheDocument();
    }

    it('says no students are flagged when registered students exist but none need a check-in', async () => {
      services.analyticsApi.students.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 8 });
      await renderOverview({ students: 3, review_for_support: 0 });
      expect(screen.getByText('No students currently flagged for review.')).toBeInTheDocument();
      expect(screen.queryByText('No student profiles')).not.toBeInTheDocument();
      expect(screen.queryByText('Registered student accounts will appear here.')).not.toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('replaces the score chart with an empty state when no scored records are stored', async () => {
      await renderOverview({ performance_distribution: emptyBands, recorded_score_count: 0, mean_recorded_score: null });
      expect(screen.queryByRole('img', { name: 'Recorded score distribution' })).not.toBeInTheDocument();
      expect(screen.getByText('No scored academic records have been stored.')).toBeInTheDocument();
    });

    it('renders the score chart when scored records exist', async () => {
      await renderOverview();
      const chart = screen.getByRole('img', { name: 'Recorded score distribution' });
      expect(JSON.parse(chart.dataset.labels)).toEqual(['0-19', '20-39', '40-59', '60-79', '80-100']);
      expect(JSON.parse(chart.dataset.values)).toEqual([[0, 0, 0, 0, 1]]);
      expect(screen.queryByText('No scored academic records have been stored.')).not.toBeInTheDocument();
    });

    it('treats recorded scores of 0 as real data', async () => {
      await renderOverview({ performance_distribution: { ...emptyBands, '0-19': 2 }, recorded_score_count: 2, mean_recorded_score: 0 });
      const chart = screen.getByRole('img', { name: 'Recorded score distribution' });
      expect(JSON.parse(chart.dataset.values)).toEqual([[2, 0, 0, 0, 0]]);
      expect(screen.getByText('Mean observed score 0.0 / 100')).toBeInTheDocument();
      expect(screen.queryByText('No scored academic records have been stored.')).not.toBeInTheDocument();
    });
  });

  it('shows real cluster profiles and intervention history views', async () => {
    const user = userEvent.setup();
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.interventionsApi.list.mockResolvedValue([supportAction]);
    services.interventionsApi.update.mockResolvedValue({ ...supportAction, status: 'in_progress' });
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    renderApp('/coordinator/clusters');
    expect(await screen.findByRole('heading', { name: 'Engagement groups' })).toBeInTheDocument();
    expect(await screen.findByText(/median recorded course activity was 125 clicks/i)).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Interventions' }));
    expect(await screen.findByRole('heading', { name: 'Interventions' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Status for Check-in'), 'in_progress');
    await waitFor(() => expect(services.interventionsApi.update).toHaveBeenCalledWith('support-1', { status: 'in_progress' }));
  });

  it('shows FastAPI multipart validation details instead of a generic 422 message', async () => {
    const user = userEvent.setup();
    services.importsApi.validate.mockRejectedValue({
      response: {
        status: 422,
        data: { detail: [{ loc: ['body', 'file'], msg: 'Field required' }] },
      },
    });
    render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
    await user.upload(screen.getByLabelText('CSV file'), new File([
      'enrollment_number\n2403031528786',
    ], 'demo.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Validate file' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('file: Field required');
    expect(screen.queryByText('Request failed with status code 422')).not.toBeInTheDocument();
  });

  it('shows an unknown-enrollment rejection as a validation issue and does not enable import', async () => {
    const user = userEvent.setup();
    const file = new File(['valid CSV fixture'], 'student_upload.csv', { type: 'text/csv' });
    services.importsApi.validate.mockResolvedValue({
      valid: false,
      total_rows: 1,
      valid_rows: 0,
      invalid_rows: 1,
      forecast_rows: 0,
      unknown_enrollment_numbers: ['2403031528786'],
      errors: [{ row: 2, field: 'enrollment_number', enrollment_number: '2403031528786',
        message: 'This enrollment number is not associated with an application student.' }],
    });
    render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);

    const picker = screen.getByLabelText('CSV file');
    await user.upload(picker, file);
    expect(screen.getByText(/Selected: student_upload\.csv/)).toBeInTheDocument();
    const validateButton = screen.getByRole('button', { name: 'Validate file' });
    expect(validateButton).toBeEnabled();
    await user.click(validateButton);

    const result = await screen.findByText(/Checked 1 row: 0 valid and 1 rejected\./);
    expect(result).toHaveTextContent('Checked 1 row: 0 valid and 1 rejected. 0 valid rows have complete weekly sequences for forecast inference.');
    expect(result).toHaveClass('form-alert');
    expect(await screen.findByText(/This enrollment number is not associated with an application student\./)).toBeInTheDocument();
    expect(screen.getByText(/Unknown enrollments: 2403031528786\./)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import and analyze/i })).toBeDisabled();
    expect(services.importsApi.validate).toHaveBeenCalledWith(file);
    expect(services.importsApi.create).not.toHaveBeenCalled();
  });

  it.each([
    [{ total_rows: 1, valid_rows: 1, invalid_rows: 0, forecast_rows: 1 },
      'Checked 1 row: 1 valid and 0 rejected. 1 valid row has a complete weekly sequence for forecast inference.'],
    [{ total_rows: 2, valid_rows: 2, invalid_rows: 0, forecast_rows: 2 },
      'Checked 2 rows: 2 valid and 0 rejected. 2 valid rows have complete weekly sequences for forecast inference.'],
  ])('uses singular and plural row counts in the validation summary', async (counts, expected) => {
    const user = userEvent.setup();
    services.importsApi.validate.mockResolvedValue({ valid: true, errors: [], ...counts });
    render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
    await user.upload(screen.getByLabelText('CSV file'), new File(['csv'], 'rows.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Validate file' }));
    expect(await screen.findByText(/^Checked /)).toHaveTextContent(expected);
  });

  it('imports the validated eligible rows from a mixed coordinator CSV', async () => {
    const user = userEvent.setup();
    services.authApi.me.mockResolvedValue(coordinatorUser);
    services.importsApi.validate.mockResolvedValue({
      valid: false,
      total_rows: 3,
      valid_rows: 2,
      invalid_rows: 1,
      forecast_rows: 0,
      errors: [{ row: 3, field: 'enrollment_number', message: 'Unknown enrollment.' }],
      unknown_enrollment_numbers: ['2403031599999'],
    });
    services.importsApi.create.mockResolvedValue({
      import_id: 'import-1',
      total_rows: 3,
      valid_rows: 2,
      invalid_rows: 1,
      errors: [],
      records: [
        savedRecord(2, { prediction_id: 'prediction-a', cluster_id: 0, forecast_id: null }),
        savedRecord(4, { prediction_id: 'prediction-b', cluster_id: 1, forecast_id: null }),
      ],
    });
    window.localStorage.setItem(TOKEN_KEY, 'existing-token');
    const file = new File([
      'enrollment_number,code_module,code_presentation\n2403031500001,AAA,2013B\n2403031599999,AAA,2013B\n2403031500002,AAA,2013B',
    ], 'multi.csv', { type: 'text/csv' });

    renderApp('/coordinator/imports');
    await screen.findByLabelText('CSV file');
    expect(screen.queryByRole('link', { name: /isolated 100-row synthetic demo/i })).not.toBeInTheDocument();
    await user.upload(await screen.findByLabelText('CSV file'), file);
    await user.click(screen.getByRole('button', { name: 'Validate file' }));
    expect(await screen.findByText(/2 valid and 1 rejected/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Import and analyze/i }));
    expect(await screen.findByText(/2 of 3 rows imported/i)).toBeInTheDocument();
    expect(screen.getByText('Source row 2')).toBeInTheDocument();
    expect(screen.getByText('Source row 4')).toBeInTheDocument();
    expect(services.importsApi.create).toHaveBeenCalledWith(file);
  });

  describe('CSV import results presentation', () => {
    const validationOk = { valid: true, total_rows: 3, valid_rows: 3, invalid_rows: 0, forecast_rows: 1, errors: [] };

    it('keeps the selected CSV tied to its results while validation and import are pending', async () => {
      const user = userEvent.setup();
      let finishValidation;
      let finishImport;
      services.importsApi.validate.mockImplementation(() => new Promise((resolve) => { finishValidation = resolve; }));
      services.importsApi.create.mockImplementation(() => new Promise((resolve) => { finishImport = resolve; }));
      render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
      const picker = screen.getByLabelText('CSV file');
      const file = new File(['fixture'], 'original.csv', { type: 'text/csv' });
      const replacement = new File(['different fixture'], 'replacement.csv', { type: 'text/csv' });
      await user.upload(picker, file);
      await user.click(screen.getByRole('button', { name: 'Validate file' }));
      expect(picker).toBeDisabled();
      await user.upload(picker, replacement);
      expect(picker.files[0]).toBe(file);
      expect(screen.queryByText(/Selected: replacement.csv/)).not.toBeInTheDocument();

      finishValidation(validationOk);
      await screen.findByRole('heading', { name: 'File check' });
      expect(picker).toBeEnabled();
      await user.click(screen.getByRole('button', { name: /Import and analyze/i }));
      expect(picker).toBeDisabled();
      await user.upload(picker, replacement);
      expect(picker.files[0]).toBe(file);
      expect(services.importsApi.create).toHaveBeenCalledWith(file);
      finishImport({ import_id: 'import-1', total_rows: 1, valid_rows: 1, invalid_rows: 0,
        records: [savedRecord(2, { prediction_id: 'prediction-1', cluster_id: 0, forecast_id: null })] });
      await screen.findByRole('heading', { name: 'Import results' });
      expect(picker).toBeEnabled();
      expect(screen.getByText(/Selected: original.csv/)).toBeInTheDocument();

      await user.upload(picker, replacement);
      expect(screen.getByText(/Selected: replacement.csv/)).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Import results' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Import and analyze/i })).toBeDisabled();
    });

    async function runImport(importResponse, validationResponse = validationOk) {
      const user = userEvent.setup();
      services.importsApi.validate.mockResolvedValue(validationResponse);
      services.importsApi.create.mockResolvedValue(importResponse);
      render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
      await user.upload(screen.getByLabelText('CSV file'), new File(['fixture'], 'rows.csv', { type: 'text/csv' }));
      await user.click(screen.getByRole('button', { name: 'Validate file' }));
      await screen.findByRole('heading', { name: 'File check' });
      await user.click(screen.getByRole('button', { name: /Import and analyze/i }));
      await screen.findByRole('heading', { name: 'Import results' });
      return user;
    }

    it('labels validation as a check only and warns about rows without weekly sequences', async () => {
      const user = userEvent.setup();
      services.importsApi.validate.mockResolvedValue(validationOk);
      render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
      await user.upload(screen.getByLabelText('CSV file'), new File(['fixture'], 'rows.csv', { type: 'text/csv' }));
      await user.click(screen.getByRole('button', { name: 'Validate file' }));

      expect(await screen.findByText(/Nothing has been saved and no models have run yet/)).toBeInTheDocument();
      expect(screen.getByText(/2 valid rows have no complete eight-week weekly sequence/)).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Import results' })).not.toBeInTheDocument();
      expect(screen.queryByText(/Import saved/)).not.toBeInTheDocument();
      expect(services.importsApi.create).not.toHaveBeenCalled();
    });

    it('shows a compact table, derived counts, and a readable warning for skipped forecasts', async () => {
      const user = await runImport({
        import_id: 'import-uuid-1', already_imported: false, total_rows: 3, valid_rows: 3, invalid_rows: 0, errors: [],
        records: [
          { source_row: 2, enrollment_id: 'enroll-uuid-a', prediction_id: 'prediction-uuid-a', cluster_record_id: 'cluster-uuid-a', cluster_id: 0, forecast_id: 'forecast-uuid-a' },
          { source_row: 3, enrollment_id: 'enroll-uuid-b', prediction_id: 'prediction-uuid-b', cluster_record_id: 'cluster-uuid-b', cluster_id: 2, forecast_id: null },
          { source_row: 4, enrollment_id: 'enroll-uuid-c', prediction_id: 'prediction-uuid-c', cluster_record_id: 'cluster-uuid-c', cluster_id: 1, forecast_id: null },
        ],
      });

      expect(screen.getByText(/Import saved and analyzed: 3 of 3 rows imported; 0 rejected/)).toBeInTheDocument();
      const table = screen.getByRole('table', { name: /Imported rows/ });
      expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent))
        .toEqual(['Source row', 'Engagement group', 'Forecast status']);
      const rows = within(table).getAllByRole('row').slice(1);
      expect(rows[0]).toHaveTextContent('Source row 2Cluster 0Forecast saved');
      expect(rows[1]).toHaveTextContent('Source row 3Cluster 2Not generated · no weekly sequence');

      const counts = screen.getByText('Forecasts not generated').closest('div');
      expect(counts).toHaveTextContent('2');
      expect(screen.getByText('Forecasts saved').closest('div')).toHaveTextContent('1');
      expect(screen.getByText('Rows rejected').closest('div')).toHaveTextContent('0');
      expect(screen.getByText(/Weekly forecast not generated for 2 rows\./)).toBeInTheDocument();
      expect(screen.getByText(/so no forecast was produced for them/)).toBeInTheDocument();

      expect(screen.queryByText(/prediction-uuid-a/)).not.toBeInTheDocument();
      expect(screen.queryByText(/forecast-uuid-a/)).not.toBeInTheDocument();
      expect(screen.queryByText(/import-uuid-1/)).not.toBeInTheDocument();

      await user.click(screen.getByText('Technical details'));
      expect(await screen.findByText('prediction-uuid-a')).toBeInTheDocument();
      expect(screen.getByText('forecast-uuid-a')).toBeInTheDocument();
      expect(screen.getByText('import-uuid-1')).toBeInTheDocument();
    });

    it('does not present a previously imported file as a new successful import', async () => {
      await runImport({
        import_id: 'import-uuid-2', already_imported: true, total_rows: 1, valid_rows: 1, invalid_rows: 0, errors: [],
        records: [savedRecord(2, { prediction_id: 'p', cluster_record_id: 'c', cluster_id: 1, forecast_id: 'f' })],
        note: 'This exact file was already imported; existing generated records were returned without rerunning models.',
      });

      expect(screen.getByText(/already imported\. Previously saved results are shown below; models were not rerun/)).toBeInTheDocument();
      expect(screen.queryByText(/Import saved and analyzed/)).not.toBeInTheDocument();
      expect(screen.getByText('Rows previously imported')).toBeInTheDocument();
    });

    it('shows rejection reasons but does not confirm an import with missing API counts', async () => {
      await runImport({
        import_id: 'import-uuid-3', total_rows: 2, valid_rows: 1,
        errors: [{ row: 3, field: 'enrollment_number', enrollment_number: '2403031599999', message: 'Unknown enrollment.' }],
        records: [savedRecord(2, { prediction_id: 'p', cluster_id: 3, forecast_id: null })],
      }, { ...validationOk, valid: false, total_rows: 2, valid_rows: 1, invalid_rows: 1, forecast_rows: 0 });

      expect(screen.getByText(/this import cannot be confirmed/)).toBeInTheDocument();
      expect(screen.queryByText(/Import saved and analyzed/)).not.toBeInTheDocument();
      expect(screen.queryByText('Rows rejected')).not.toBeInTheDocument();
      const issues = screen.getByRole('heading', { name: /Rejected rows/ }).parentElement;
      expect(within(issues).getByText('Unknown enrollment.')).toBeInTheDocument();
      expect(within(issues).getByText('2403031599999')).toBeInTheDocument();
    });

    it.each([
      ['one row saved', { import_id: 'i-1', total_rows: 1, valid_rows: 1, invalid_rows: 0, errors: [], records: [savedRecord(2)] },
        'Import saved and analyzed: 1 of 1 row imported; 0 rejected.'],
      ['several rows saved', { import_id: 'i-2', total_rows: 2, valid_rows: 2, invalid_rows: 0, errors: [], records: [savedRecord(2), savedRecord(3)] },
        'Import saved and analyzed: 2 of 2 rows imported; 0 rejected.'],
      ['one row rejected', { import_id: 'i-3', total_rows: 2, valid_rows: 1, invalid_rows: 1, errors: [], records: [savedRecord(2)] },
        'Import saved with a rejected row: 1 of 2 rows imported; 1 rejected and not imported.'],
      ['several rows rejected', { import_id: 'i-4', total_rows: 5, valid_rows: 3, invalid_rows: 2, errors: [], records: [savedRecord(2), savedRecord(3), savedRecord(4)] },
        'Import saved with rejected rows: 3 of 5 rows imported; 2 rejected and not imported.'],
      ['one row previously imported', { import_id: 'i-6', already_imported: true, total_rows: 1, valid_rows: 1, invalid_rows: 0, errors: [], records: [savedRecord(2)] },
        'models were not rerun. 1 of 1 row imported; 0 rejected.'],
      ['several rows previously imported', { import_id: 'i-7', already_imported: true, total_rows: 3, valid_rows: 2, invalid_rows: 1, errors: [], records: [savedRecord(2), savedRecord(3)] },
        'models were not rerun. 2 of 3 rows imported; 1 rejected.'],
    ])('words the result banner naturally: %s', async (_case, response, expected) => {
      await runImport(response);
      const banner = screen.getByRole('heading', { name: 'Import results' }).closest('section').querySelector('.notice');
      expect(banner).toHaveTextContent(expected);
      expect(banner).not.toHaveTextContent('row(s)');
    });

    it('never shows success when the response lacks saved records', async () => {
      await runImport({ import_id: 'import-uuid-4', total_rows: 1, invalid_rows: 0, errors: [] });

      expect(screen.getByText(/this import cannot be confirmed/)).toBeInTheDocument();
      expect(screen.queryByText(/Import saved/)).not.toBeInTheDocument();
      expect(screen.queryByText('Rows imported')).not.toBeInTheDocument();
      expect(screen.queryByRole('table', { name: /Imported rows/ })).not.toBeInTheDocument();
    });

    it.each([
      ['empty records', { import_id: 'i', records: [] }],
      ['records without an import identity', { records: [savedRecord(2)] }],
      ['an already-imported flag without records', { import_id: 'i', already_imported: true }],
      ['no file total', { import_id: 'i', valid_rows: 1, invalid_rows: 0, records: [savedRecord(2)] }],
    ])('omits saved counts for an unconfirmed response: %s', async (_case, response) => {
      await runImport(response);
      expect(screen.getByText(/this import cannot be confirmed/)).toBeInTheDocument();
      expect(screen.queryByText('Rows imported')).not.toBeInTheDocument();
      expect(screen.queryByText('Rows previously imported')).not.toBeInTheDocument();
      expect(screen.queryByText('Forecasts saved')).not.toBeInTheDocument();
      expect(screen.queryByText(/models were not rerun/)).not.toBeInTheDocument();
    });

    const completeResult = { import_id: 'i', total_rows: 1, valid_rows: 1, invalid_rows: 0, records: [savedRecord(2)] };
    it.each([
      ['null record', { records: [null] }],
      ['empty record', { records: [{}] }],
      ['nonobject record', { records: ['saved'] }],
      ['missing enrollment identifier', { records: [savedRecord(2, { enrollment_id: undefined })] }],
      ['blank prediction identifier', { records: [savedRecord(2, { prediction_id: '' })] }],
      ['missing cluster record identifier', { records: [savedRecord(2, { cluster_record_id: null })] }],
      ['missing nullable forecast field', { records: [savedRecord(2, { forecast_id: undefined })] }],
      ['invalid cluster group', { records: [savedRecord(2, { cluster_id: -1 })] }],
      ['header row reported as saved', { records: [savedRecord(1)] }],
      ['source row outside file', { records: [savedRecord(3)] }],
      ['row count inconsistent with records', { valid_rows: 2, total_rows: 2 }],
      ['total count inconsistent with outcomes', { total_rows: 2 }],
      ['legacy row count contradictory', { row_count: 2 }],
      ['nonnumeric count', { invalid_rows: '0' }],
      ['object import identity', { import_id: { value: 'i' } }],
      ['duplicate source row', { total_rows: 2, valid_rows: 2, records: [savedRecord(2), savedRecord(2, { enrollment_id: 'other', prediction_id: 'other-p', cluster_record_id: 'other-c', forecast_id: null })] }],
      ['duplicate enrollment identity', { total_rows: 2, valid_rows: 2, records: [savedRecord(2), savedRecord(3, { enrollment_id: 'e-2' })] }],
      ['duplicate prediction identity', { total_rows: 2, valid_rows: 2, records: [savedRecord(2), savedRecord(3, { prediction_id: 'p-2' })] }],
      ['duplicate cluster record identity', { total_rows: 2, valid_rows: 2, records: [savedRecord(2), savedRecord(3, { cluster_record_id: 'c-2' })] }],
      ['duplicate forecast identity', { total_rows: 2, valid_rows: 2, records: [savedRecord(2), savedRecord(3, { forecast_id: 'f-2' })] }],
    ])('reports an unconfirmed import for %s without inventing saved counts', async (_case, overrides) => {
      await runImport({ ...completeResult, ...overrides });
      expect(screen.getByText(/this import cannot be confirmed/)).toBeInTheDocument();
      expect(screen.queryByText('Rows imported')).not.toBeInTheDocument();
      expect(screen.queryByText('Forecasts saved')).not.toBeInTheDocument();
      expect(screen.queryByRole('table', { name: /Imported rows/ })).not.toBeInTheDocument();
      expect(screen.queryByText('Technical details')).not.toBeInTheDocument();
    });

    it.each([null, 'unexpected response', []])('reports an unsupported top-level import response clearly', async (response) => {
      await runImport(response);
      expect(screen.getByText(/this import cannot be confirmed/)).toBeInTheDocument();
      expect(screen.queryByText('Rows imported')).not.toBeInTheDocument();
    });

    it('keeps nullable forecasts valid and handles unsupported notes and row issues without a rendering crash', async () => {
      await runImport({ ...completeResult, records: [savedRecord(2, { forecast_id: null })],
        note: { text: 'unsupported' }, errors: [null, { field: {}, message: {} }] });
      expect(screen.getByText(/Import saved and analyzed: 1 of 1 row imported; 0 rejected/)).toBeInTheDocument();
      expect(screen.getByText('Forecasts not generated').closest('div')).toHaveTextContent('1');
      expect(screen.getAllByText('No readable validation detail was returned.')).toHaveLength(2);
      expect(screen.queryByText('unsupported')).not.toBeInTheDocument();
    });

    it.each([
      { valid_rows: '3' },
      { total_rows: 4, valid_rows: 3, invalid_rows: 0, forecast_rows: 1 },
      { total_rows: 3, valid_rows: 3, invalid_rows: 0, forecast_rows: 4 },
    ])('keeps import disabled when validation counts are unsupported or inconsistent', async (response) => {
      const user = userEvent.setup();
      services.importsApi.validate.mockResolvedValue(response);
      render(<MemoryRouter><CoordinatorImportsPage /></MemoryRouter>);
      await user.upload(screen.getByLabelText('CSV file'), new File(['fixture'], 'rows.csv', { type: 'text/csv' }));
      await user.click(screen.getByRole('button', { name: 'Validate file' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('consistent validation counts');
      expect(screen.getByRole('button', { name: /Import and analyze/i })).toBeDisabled();
      expect(services.importsApi.create).not.toHaveBeenCalled();
    });
  });

});
