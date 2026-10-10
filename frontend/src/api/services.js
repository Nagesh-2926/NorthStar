import api from './client';

const data = (request) => request.then((response) => response.data);

export const authApi = {
  register: (body) => data(api.post('/auth/register', body)),
  login: (body) => data(api.post('/auth/login', body)),
  me: () => data(api.get('/auth/me')),
  changePassword: (body) => data(api.post('/auth/change-password', body)),
};

export const studentsApi = {
  me: () => data(api.get('/students/me')),
  detail: (studentId) => data(api.get(`/students/${studentId}`)),
  list: (params) => data(api.get('/students', { params })),
  createEnrollment: (studentId, body) => data(api.post(`/students/${studentId}/enrollments`, body)),
  assessmentSchedule: (enrollmentId) => data(api.get(`/enrollments/${enrollmentId}/assessment-schedule`)),
  replaceAssessmentSchedule: (enrollmentId, body) => data(api.put(`/enrollments/${enrollmentId}/assessment-schedule`, body)),
  addPerformance: (studentId, enrollmentId, body) => data(api.post(`/students/${studentId}/performance`, body, { params: { enrollment_id: enrollmentId } })),
  addEngagement: (studentId, enrollmentId, body) => data(api.post(`/students/${studentId}/engagement`, body, { params: { enrollment_id: enrollmentId } })),
  performance: (studentId, enrollmentId) => data(api.get(`/students/${studentId}/performance`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
  engagement: (studentId, enrollmentId) => data(api.get(`/students/${studentId}/engagement`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
  cluster: (studentId, enrollmentId) => data(api.get(`/students/${studentId}/cluster`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
};

export const predictionsApi = {
  forStudent: (studentId, enrollmentId) => data(api.get(`/predictions/${studentId}`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
  recent: (limit = 100) => data(api.get('/predictions', { params: { limit } })),
  create: (studentId, enrollmentId) => data(api.post(`/predictions/${studentId}`, {
    enrollment_id: enrollmentId,
  })),
  createSequence: (studentId, enrollmentId) => data(api.post(`/predictions/${studentId}/sequence`, {
    enrollment_id: enrollmentId,
  })),
  gradeScoresForStudent: (studentId, enrollmentId) => data(api.get(`/predictions/${studentId}/grade-score`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
  createGradeScore: (studentId, enrollmentId) => data(api.post(`/predictions/${studentId}/grade-score`, {
    enrollment_id: enrollmentId,
  })),
};

export const clustersApi = {
  recent: () => data(api.get('/clusters')),
  profiles: () => data(api.get('/analytics/clusters')),
  assign: (studentId, enrollmentId) => data(api.post(`/clusters/${studentId}`, {
    enrollment_id: enrollmentId,
  })),
};

export const interventionsApi = {
  list: () => data(api.get('/interventions')),
  create: (body) => data(api.post('/interventions', body)),
  update: (id, body) => data(api.put(`/interventions/${id}`, body)),
};

export const plansApi = {
  list: (studentId, enrollmentId) => data(api.get(`/students/${studentId}/study-plan`, {
    params: enrollmentId ? { enrollment_id: enrollmentId } : {},
  })),
  create: (studentId, enrollmentId) => data(api.post(`/students/${studentId}/study-plan`, {
    enrollment_id: enrollmentId,
  })),
  updateProgress: (studentId, planId, completedGoalIndices) => data(api.put(
    `/students/${studentId}/study-plan/${planId}/progress`,
    { completed_goal_indices: completedGoalIndices },
  )),
  askAssistant: (enrollmentId, question) => data(api.post('/students/me/support-assistant', {
    enrollment_id: enrollmentId,
    question,
  })),
  messages: (studentId) => data(api.get(`/students/${studentId}/motivational-messages`)),
};

export const analyticsApi = {
  overview: () => data(api.get('/analytics/overview')),
  riskTrends: (days = 90) => data(api.get('/analytics/risk-trends', { params: { days } })),
  engagement: () => data(api.get('/analytics/engagement')),
  students: (params) => data(api.get('/analytics/monitoring/students', { params })),
};

export const importsApi = {
  template: () => api.get('/imports/template', { responseType: 'blob' }),
  validate: (file) => uploadCsv('/imports/validate', file),
  create: (file) => uploadCsv('/imports', file),
};

function uploadCsv(path, file) {
  const form = new FormData();
  form.append('file', file);
  return data(api.post(path, form, {
    // False prevents Axios's POST default from overriding the browser boundary.
    headers: { 'Content-Type': false },
  }));
}

export const accessRequestsApi = {
  mine: () => data(api.get('/access-requests/me')),
  create: (enrollmentNumber) => data(api.post('/access-requests', {
    enrollment_number: enrollmentNumber,
  })),
  pending: () => data(api.get('/access-requests')),
  review: (requestId, status) => data(api.patch(`/access-requests/${requestId}`, { status })),
};
