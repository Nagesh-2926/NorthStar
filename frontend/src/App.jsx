import { Link, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { HomeRedirect, RequireAuth, RequireRole } from './auth/RouteGuards';
import { AppShell, StudentArea } from './components/AppShell';
import { LoadingState } from './components/States';
import { LoginPage, RegisterPage } from './pages/AuthPages';
import { CoordinatorClustersPage, CoordinatorDashboardPage, CoordinatorInterventionsPage,
  CoordinatorStudentDetailPage, CoordinatorStudentsPage } from './pages/CoordinatorPages';
import { CoordinatorImportsPage } from './pages/CoordinatorImportsPage';
import { CoordinatorAccessRequestsPage } from './pages/CoordinatorAccessRequestsPage';
import { StudentDashboardPage, StudentEngagementPage, StudentMotivationPage,
  StudentInterventionsPage, StudentPerformancePage, StudentPredictionsPage,
  StudentProfilePage, StudentStudyPlanPage } from './pages/StudentPages';

function CoordinatorArea() {
  return <AppShell><Outlet /></AppShell>;
}

function NotFoundPage() {
  return <main className="not-found"><div><span className="eyebrow">404 · PAGE NOT FOUND</span><h1>This page is not in your workspace.</h1><p>Use your navigation to return to a page available to your account.</p><Link className="button button-primary" to="/">Go to my workspace</Link></div></main>;
}

export default function App() {
  const { loading } = useAuth();
  if (loading) return <LoadingState label="Checking your account" fullPage />;
  return <Routes>
    <Route path="/" element={<HomeRedirect />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route element={<RequireAuth />}>
      <Route element={<RequireRole roles={['student']} />}>
        <Route element={<StudentArea />}>
          <Route path="/student/dashboard" element={<StudentDashboardPage />} />
          <Route path="/student/performance" element={<StudentPerformancePage />} />
          <Route path="/student/engagement" element={<StudentEngagementPage />} />
          <Route path="/student/predictions" element={<StudentPredictionsPage />} />
          <Route path="/student/interventions" element={<StudentInterventionsPage />} />
          <Route path="/student/study-plan" element={<StudentStudyPlanPage />} />
          <Route path="/student/motivation" element={<StudentMotivationPage />} />
          <Route path="/student/profile" element={<StudentProfilePage />} />
        </Route>
      </Route>
      <Route element={<RequireRole roles={['coordinator']} />}>
        <Route element={<CoordinatorArea />}>
          <Route path="/coordinator/dashboard" element={<CoordinatorDashboardPage />} />
          <Route path="/coordinator/students" element={<CoordinatorStudentsPage />} />
          <Route path="/coordinator/students/:studentId" element={<CoordinatorStudentDetailPage />} />
          <Route path="/coordinator/clusters" element={<CoordinatorClustersPage />} />
          <Route path="/coordinator/interventions" element={<CoordinatorInterventionsPage />} />
          <Route path="/coordinator/imports" element={<CoordinatorImportsPage />} />
          <Route path="/coordinator/access-requests" element={<CoordinatorAccessRequestsPage />} />
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
