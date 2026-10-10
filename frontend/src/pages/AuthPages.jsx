import { useState } from 'react';
import { ArrowRight, GraduationCap, ShieldCheck } from 'lucide-react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { friendlyError } from '../api/client';
import { Field, SelectField } from '../components/Forms';

function AuthFrame({ eyebrow, title, description, children }) {
  return (
    <main className="auth-page">
      <section className="auth-story">
        <div className="auth-brand"><span className="brand-mark"><GraduationCap size={22} /></span><strong>Northstar</strong></div>
        <div className="auth-story-copy">
          <span className="auth-overline">A clearer path to support</span>
          <h1>Progress is built one thoughtful step at a time.</h1>
          <p>Academic patterns can open a conversation. They never define a student's potential.</p>
        </div>
        <div className="auth-story-footer"><ShieldCheck size={17} aria-hidden="true" /><span>Private by design · Reviewed by people</span></div>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-heading"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{description}</p></div>
          {children}
        </div>
      </section>
    </main>
  );
}

export function LoginPage() {
  const { signIn, user, loading, notice, clearNotice } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [values, setValues] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!loading && user) return <Navigate to={user.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard'} replace />;

  async function handleSubmit(event) {
    event.preventDefault(); clearNotice(); setError(''); setSubmitting(true);
    try {
      const account = await signIn(values);
      const destination = location.state?.from;
      navigate(destination?.startsWith(`/${account.role}/`) ? destination
        : account.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard', { replace: true });
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally { setSubmitting(false); }
  }

  return <AuthFrame eyebrow="Welcome back" title="Sign in to continue" description="Use your student or coordinator account to open your workspace.">
    <form className="auth-form" onSubmit={handleSubmit}>
      {notice && <div className="form-success" role="status">{notice}</div>}
      {error && <div className="form-alert" role="alert">{error}</div>}
      <Field id="email" label="Email address" type="email" autoComplete="email" required value={values.email}
        onChange={(event) => setValues({ ...values, email: event.target.value })} />
      <Field id="password" label="Password" type="password" autoComplete="current-password" required value={values.password}
        onChange={(event) => setValues({ ...values, password: event.target.value })} />
      <button className="button button-primary button-wide" disabled={submitting} type="submit">
        {submitting ? 'Signing in…' : 'Sign in'} {!submitting && <ArrowRight size={17} aria-hidden="true" />}
      </button>
      <p className="auth-footnote">New to Northstar? <Link to="/register">Create an account</Link></p>
    </form>
  </AuthFrame>;
}

export function RegisterPage() {
  const { register, user, loading } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ email: '', password: '', role: 'student', invite_code: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!loading && user) return <Navigate to={user.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard'} replace />;

  async function handleSubmit(event) {
    event.preventDefault(); setError(''); setSubmitting(true);
    try {
      const body = { email: values.email, password: values.password, role: values.role };
      if (values.role === 'coordinator') body.invite_code = values.invite_code;
      const account = await register(body);
      navigate(account.role === 'coordinator' ? '/coordinator/dashboard' : '/student/dashboard', { replace: true });
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally { setSubmitting(false); }
  }

  return <AuthFrame eyebrow="Get started" title="Create your account" description="Student accounts are open. Coordinator access requires an invitation from your institution.">
    <form className="auth-form" onSubmit={handleSubmit}>
      {error && <div className="form-alert" role="alert">{error}</div>}
      <Field id="register-email" label="Email address" type="email" autoComplete="email" required value={values.email}
        onChange={(event) => setValues({ ...values, email: event.target.value })} />
      <Field id="register-password" label="Password" type="password" autoComplete="new-password" required minLength={12}
        hint="At least 12 characters, with uppercase, lowercase, and a number."
        value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} />
      <SelectField id="role" label="Account type" value={values.role}
        onChange={(event) => setValues({ ...values, role: event.target.value })}
        options={[{ value: 'student', label: 'Student' }, { value: 'coordinator', label: 'Coordinator' }]} />
      {values.role === 'coordinator' && <Field id="invite-code" label="Coordinator invitation code" type="password" required autoComplete="off"
        value={values.invite_code} onChange={(event) => setValues({ ...values, invite_code: event.target.value })} />}
      <button className="button button-primary button-wide" disabled={submitting} type="submit">
        {submitting ? 'Creating account…' : 'Create account'} {!submitting && <ArrowRight size={17} aria-hidden="true" />}
      </button>
      <p className="auth-footnote">Already registered? <Link to="/login">Sign in</Link></p>
    </form>
  </AuthFrame>;
}
