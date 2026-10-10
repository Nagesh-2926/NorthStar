import { useEffect, useRef, useState } from 'react';
import { BarChart3, BookOpenCheck, ChevronDown, ClipboardList, GraduationCap,
  HeartHandshake, KeyRound, LayoutDashboard, LogOut, Menu, MessageCircleHeart, UserRound,
  UsersRound, X, Activity, Network, FileSpreadsheet, ShieldCheck } from 'lucide-react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { authApi, studentsApi } from '../api/services';
import { friendlyError } from '../api/client';
import { useResource } from '../hooks/useResource';
import { LoadingState, ErrorState } from './States';
import { StudentAccessRequestPage } from '../pages/StudentAccessRequestPage';
import { Field } from './Forms';

const studentNavigation = [
  { to: '/student/dashboard', label: 'Overview', icon: LayoutDashboard },
  { to: '/student/performance', label: 'Performance', icon: BookOpenCheck },
  { to: '/student/engagement', label: 'Engagement', icon: Activity },
  { to: '/student/predictions', label: 'Support review', icon: BarChart3 },
  { to: '/student/interventions', label: 'Support actions', icon: HeartHandshake },
  { to: '/student/study-plan', label: 'Study plan', icon: ClipboardList },
  { to: '/student/motivation', label: 'Encouragement', icon: MessageCircleHeart },
  { to: '/student/profile', label: 'My profile', icon: UserRound },
];

const coordinatorNavigation = [
  { to: '/coordinator/dashboard', label: 'Overview', icon: LayoutDashboard },
  { to: '/coordinator/students', label: 'Students', icon: UsersRound },
  { to: '/coordinator/clusters', label: 'Engagement groups', icon: Network },
  { to: '/coordinator/interventions', label: 'Interventions', icon: HeartHandshake },
  { to: '/coordinator/imports', label: 'CSV imports', icon: FileSpreadsheet },
  { to: '/coordinator/access-requests', label: 'Access requests', icon: ShieldCheck },
];

function Sidebar({ role, open, onClose }) {
  const navigation = role === 'coordinator' ? coordinatorNavigation : studentNavigation;
  return (
    <>
      {open && <button className="sidebar-scrim" aria-label="Close navigation" onClick={onClose} />}
      <aside className={`sidebar${open ? ' sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="brand"><span className="brand-mark"><GraduationCap size={21} aria-hidden="true" /></span>
          <span><strong>Northstar</strong><small>Student support</small></span>
        </div>
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="side-nav">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={onClose} className={({ isActive }) => `nav-link${isActive ? ' nav-link-active' : ''}`}>
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}

export function AppShell({ children, enrollmentPicker }) {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const roleName = user?.role === 'coordinator' ? 'Coordinator workspace' : 'Student portal';
  const initial = user?.email?.[0]?.toUpperCase() || 'U';

  function logout(notice) {
    signOut(notice || '');
    navigate('/login', { replace: true });
  }

  return (
    <div className="app-frame">
      <Sidebar role={user?.role} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="app-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open navigation menu" onClick={() => setMenuOpen(true)}><Menu size={21} /></button>
          <div className="topbar-context"><span className="topbar-kicker">NORTHSTAR</span><strong>{roleName}</strong></div>
          <div className="topbar-actions">
            {enrollmentPicker}
            <AccountMenu user={user} initial={initial} onSignOut={() => logout()}
              onPasswordChanged={() => logout('Password updated. Sign in using your new password.')} />
          </div>
        </header>
        <main className="page-content">{children || <Outlet />}</main>
      </div>
    </div>
  );
}

function AccountMenu({ user, initial, onSignOut, onPasswordChanged }) {
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState(null);
  const navigate = useNavigate();
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const roleLabel = user?.role === 'coordinator' ? 'Coordinator' : 'Student';

  useEffect(() => {
    if (!open) return undefined;
    const focusFirstItem = () => menuRef.current?.querySelector('[role="menuitem"]')?.focus();
    requestAnimationFrame(focusFirstItem);
    const onPointerDown = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const items = [...(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])];
      if (!items.length) return;
      event.preventDefault();
      const current = items.indexOf(document.activeElement);
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? items.length - 1
          : event.key === 'ArrowDown' ? (current + 1 + items.length) % items.length
            : (current - 1 + items.length) % items.length;
      items[next].focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function openProfile() {
    setOpen(false);
    if (user?.role === 'student') {
      navigate('/student/profile');
      return;
    }
    setDialog('profile');
  }

  function openPasswordChange() {
    setOpen(false);
    setDialog('password');
  }

  function closeDialog() {
    setDialog(null);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  return <div className="account-menu-root" ref={rootRef}>
    <button
      ref={triggerRef}
      className="account-chip account-menu-trigger"
      type="button"
      aria-label={`Account menu for ${user?.email || 'your account'}`}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls="account-menu"
      onClick={() => setOpen((value) => !value)}
    >
      <span className="avatar" aria-hidden="true">{initial}</span>
      <span className="account-email">{user?.email}</span>
      <ChevronDown className="account-chevron" size={15} aria-hidden="true" />
    </button>
    <div className="account-menu" id="account-menu" role="menu" aria-label="Account options" ref={menuRef} hidden={!open}>
      <div className="account-menu-summary">
        <span className="avatar" aria-hidden="true">{initial}</span>
        <span className="account-menu-identity"><strong>{user?.email}</strong><small>{roleLabel}</small></span>
      </div>
      <div className="account-menu-divider" />
      <button className="account-menu-item" type="button" role="menuitem" onClick={openProfile}>
        <UserRound size={16} aria-hidden="true" /><span>My Profile</span>
      </button>
      <button className="account-menu-item" type="button" role="menuitem" onClick={openPasswordChange}>
        <KeyRound size={16} aria-hidden="true" /><span>Change Password</span>
      </button>
      <div className="account-menu-divider" />
      <button className="account-menu-item account-menu-signout" type="button" role="menuitem" onClick={onSignOut}>
        <LogOut size={16} aria-hidden="true" /><span>Sign Out</span>
      </button>
    </div>
    {dialog === 'profile' && <AccountProfileDialog user={user} initial={initial}
      roleLabel={roleLabel} onClose={closeDialog} />}
    {dialog === 'password' && <AccountPasswordDialog onClose={closeDialog}
      onPasswordChanged={onPasswordChanged} />}
  </div>;
}

function AccountDialog({ title, onClose, children }) {
  const closeButtonRef = useRef(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const dialog = closeButtonRef.current?.closest('[role="dialog"]');
      const items = [...(dialog?.querySelectorAll('button:not([disabled]), input:not([disabled])') || [])];
      if (!items.length) {
        event.preventDefault();
        closeButtonRef.current?.focus();
      } else if (event.shiftKey && document.activeElement === items[0]) {
        event.preventDefault();
        items.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
        event.preventDefault();
        items[0].focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return <div className="account-dialog-backdrop" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="account-profile-dialog" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title">
      <header className="account-dialog-heading">
        <div><span className="eyebrow">ACCOUNT</span><h2 id="account-dialog-title">{title}</h2></div>
        <button ref={closeButtonRef} className="icon-button" type="button" aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      {children}
    </section>
  </div>;
}

function AccountProfileDialog({ user, initial, roleLabel, onClose }) {
  return <AccountDialog title="My Profile" onClose={onClose}>
      <div className="account-profile-identity">
        <span className="profile-avatar" aria-hidden="true">{initial}</span>
        <div><strong>{user?.email}</strong><span>{roleLabel} account</span></div>
      </div>
      <dl className="account-profile-facts">
        <div><dt>Email</dt><dd>{user?.email}</dd></div>
        <div><dt>Role</dt><dd>{roleLabel}</dd></div>
        <div><dt>Account status</dt><dd>{user?.is_active ? 'Active' : 'Inactive'}</dd></div>
      </dl>
      <p className="account-profile-note">For account or identity corrections, contact your institution's coordinator.</p>
  </AccountDialog>;
}

function AccountPasswordDialog({ onClose, onPasswordChanged }) {
  const [values, setValues] = useState({ current_password: '', new_password: '', confirm_password: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await authApi.changePassword(values);
      onPasswordChanged();
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  return <AccountDialog title="Change Password" onClose={onClose}>
    <form className="account-password-form" onSubmit={submit}>
      {error && <div className="form-alert" role="alert">{error}</div>}
      <Field id="account-current-password" label="Current password" type="password" autoComplete="current-password"
        required maxLength={128} value={values.current_password}
        onChange={(event) => setValues({ ...values, current_password: event.target.value })} />
      <Field id="account-new-password" label="New password" type="password" autoComplete="new-password"
        required minLength={12} maxLength={128} hint="At least 12 characters, with uppercase, lowercase, and a number."
        value={values.new_password} onChange={(event) => setValues({ ...values, new_password: event.target.value })} />
      <Field id="account-confirm-password" label="Confirm new password" type="password" autoComplete="new-password"
        required minLength={12} maxLength={128} value={values.confirm_password}
        onChange={(event) => setValues({ ...values, confirm_password: event.target.value })} />
      <div className="account-password-actions">
        <button className="button button-quiet" type="button" onClick={onClose} disabled={submitting}>Cancel</button>
        <button className="button button-primary" type="submit" disabled={submitting}>
          {submitting ? 'Updating…' : 'Update password'}
        </button>
      </div>
    </form>
  </AccountDialog>;
}

export function StudentArea() {
  const profile = useResource(() => studentsApi.me(), []);
  const [enrollmentId, setEnrollmentId] = useState('');
  const enrollments = profile.data?.enrollments || [];

  if (profile.loading) return <LoadingState label="Loading your student profile" fullPage />;
  if (profile.error) return <main className="standalone-state"><ErrorState error={profile.error} onRetry={profile.retry} title="Your profile is unavailable" /></main>;

  const selected = enrollments.find((item) => item.id === enrollmentId) || enrollments[0] || null;
  const picker = enrollments.length > 1 ? (
    <label className="enrollment-picker"><span>Course</span><select aria-label="Select course enrollment" value={selected?.id || ''}
      onChange={(event) => setEnrollmentId(event.target.value)}>
      {enrollments.map((item) => <option key={item.id} value={item.id}>{item.code_module} · {item.code_presentation}</option>)}
    </select><ChevronDown size={13} aria-hidden="true" /></label>
  ) : selected ? <span className="course-chip">{selected.code_module} · {selected.code_presentation}</span> : null;

  return <AppShell enrollmentPicker={picker}>
    {profile.data.access_approved
      ? childrenOutlet(profile.data, selected)
      : <StudentAccessRequestPage />}
  </AppShell>;
}

function childrenOutlet(student, enrollment) {
  return <OutletWithStudent student={student} enrollment={enrollment} />;
}

function OutletWithStudent(props) {
  return <Outlet context={props} />;
}
