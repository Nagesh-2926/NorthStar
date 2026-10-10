import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { LoadingState } from '../components/States';

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingState label="Checking your session" fullPage />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function RequireRole({ roles }) {
  const { user } = useAuth();
  if (!roles.includes(user?.role)) {
    return <Navigate to={user?.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard'} replace />;
  }
  return <Outlet />;
}

export function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return <LoadingState label="Preparing your workspace" fullPage />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard'} replace />;
}
