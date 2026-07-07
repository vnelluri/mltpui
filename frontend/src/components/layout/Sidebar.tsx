import { NavLink } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { ROLE_LABELS } from '../../auth/roles';
import { StatusBadge } from '../shared/StatusBadge';

interface NavItem {
  to: string;
  label: string;
  icon: JSX.Element;
}

const icon = (d: string) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
    <path d={d} strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ICONS = {
  dashboard: icon('M4 13h6V4H4v9zm0 7h6v-5H4v5zm10 0h6V11h-6v9zm0-16v5h6V4h-6z'),
  tenants: icon('M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 9h.01M15 9h.01M9 12h.01M15 12h.01'),
  groups: icon('M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z'),
  experiments: icon('M9 3v6l-6 10a1 1 0 00.9 1.5h16.2a1 1 0 00.9-1.5L15 9V3M9 3h6M9 15h6'),
  jobs: icon('M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83'),
  submit: icon('M12 4v16m8-8H4'),
  models: icon('M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'),
  features: icon('M4 6h16M4 6a2 2 0 012-2h12a2 2 0 012 2M4 6v12a2 2 0 002 2h12a2 2 0 002-2V6M8 10h8M8 14h5'),
  notebook: icon('M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4L16.5 3.5z'),
  governance: icon('M12 2L4 6v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V6l-8-4z'),
  audit: icon('M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z'),
  snowflake: icon('M12 2v20M5 6l14 12M19 6L5 18M2 12h20'),
  settings: icon('M12 15a3 3 0 100-6 3 3 0 000 6z M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004.6 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9c.14.36.4.66.74.86.34.2.53.55.54.94V12c-.01.4-.2.75-.54.95-.34.2-.6.5-.74.86z'),
};

function itemsForRole(role: string | null | undefined): NavItem[] {
  switch (role) {
    case 'PlatformAdmin':
      return [
        { to: '/admin', label: 'Dashboard', icon: ICONS.dashboard },
        { to: '/admin/tenants', label: 'Tenants', icon: ICONS.tenants },
        { to: '/workspace/experiments', label: 'Experiments', icon: ICONS.experiments },
        { to: '/workspace/jobs', label: 'Jobs', icon: ICONS.jobs },
        { to: '/workspace/models', label: 'Models', icon: ICONS.models },
        { to: '/feature-store', label: 'Feature Store', icon: ICONS.features },
        { to: '/workspace/notebook', label: 'Notebook', icon: ICONS.notebook },
        { to: '/snowflake', label: 'Snowflake', icon: ICONS.snowflake },
        { to: '/governance', label: 'Governance', icon: ICONS.governance },
        { to: '/audit', label: 'Audit Log', icon: ICONS.audit },
      ];
    case 'TenantAdmin':
      return [
        { to: '/tenant', label: 'Dashboard', icon: ICONS.dashboard },
        { to: '/tenant/settings', label: 'Settings', icon: ICONS.settings },
        { to: '/workspace/experiments', label: 'Experiments', icon: ICONS.experiments },
        { to: '/workspace/jobs', label: 'Jobs', icon: ICONS.jobs },
        { to: '/workspace/models', label: 'Models', icon: ICONS.models },
        { to: '/feature-store', label: 'Feature Store', icon: ICONS.features },
        { to: '/workspace/notebook', label: 'Notebook', icon: ICONS.notebook },
        { to: '/snowflake', label: 'Snowflake', icon: ICONS.snowflake },
        { to: '/audit', label: 'Audit Log', icon: ICONS.audit },
      ];
    case 'DataScientist':
      return [
        { to: '/workspace', label: 'Dashboard', icon: ICONS.dashboard },
        { to: '/workspace/experiments', label: 'Experiments', icon: ICONS.experiments },
        { to: '/workspace/jobs', label: 'Jobs', icon: ICONS.jobs },
        { to: '/workspace/submit', label: 'Submit Job', icon: ICONS.submit },
        { to: '/workspace/models', label: 'Models', icon: ICONS.models },
        { to: '/feature-store', label: 'Feature Store', icon: ICONS.features },
        { to: '/workspace/notebook', label: 'Notebook', icon: ICONS.notebook },
        { to: '/snowflake', label: 'Snowflake', icon: ICONS.snowflake },
      ];
    case 'MRM':
      return [
        { to: '/governance', label: 'Governance', icon: ICONS.governance },
        { to: '/workspace/models', label: 'Models', icon: ICONS.models },
        { to: '/workspace/experiments', label: 'Experiments', icon: ICONS.experiments },
        { to: '/feature-store', label: 'Feature Store', icon: ICONS.features },
      ];
    default:
      return [];
  }
}

export function Sidebar() {
  const { user, logout } = useAuth();
  const items = itemsForRole(user?.role);

  return (
    <aside className="flex h-screen w-64 flex-shrink-0 flex-col border-r border-black/20 bg-brand-valhalla">
      <div className="flex items-center gap-3 px-5 py-6">
        <img src="/truist-logo.svg" alt="Truist" className="h-8 w-8" />
        <div>
          <p className="text-sm font-semibold text-white">Truist ML Platform</p>
          <p className="text-[11px] text-brand-purple/80">Enterprise Training</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/admin' || item.to === '/tenant' || item.to === '/workspace'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                isActive
                  ? 'bg-brand-purple text-brand-valhalla'
                  : 'text-white/70 hover:bg-white/5 hover:text-white'
              }`
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/10 px-4 py-4">
        <div className="mb-3 flex items-center gap-3">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-brand-purple/20 text-sm font-semibold text-brand-purple">
            {(user?.name ?? '?').charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">{user?.name}</p>
            <p className="truncate text-xs text-white/50">{user?.email}</p>
          </div>
        </div>
        {user && (
          <StatusBadge status={user.role} tone="purple" label={ROLE_LABELS[user.role]} className="mb-3" />
        )}
        <button
          onClick={() => void logout()}
          className="w-full rounded-lg border border-white/10 px-3 py-2 text-xs font-medium text-white/70 transition hover:bg-white/5 hover:text-white"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
