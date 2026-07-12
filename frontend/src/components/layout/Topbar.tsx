import { useAuth } from '../../auth/AuthContext';
import { setActiveMembership } from '../../api/client';
import { ROLE_LABELS } from '../../auth/roles';
import type { Membership } from '../../types/platform';

function membershipLabel(m: Membership): string {
  const role = ROLE_LABELS[m.role] ?? m.role;
  if (!m.tenantId) return `${role} · All tenants`;
  // Meaningful name comes from the Tenant record via /auth/me; the raw
  // tenant id is only a fallback (e.g. tenant record not created yet).
  return `${role} · ${m.tenantName ?? m.tenantId}`;
}

function membershipValue(m: Membership): string {
  return `${m.role}|${m.tenantId ?? ''}`;
}

export function Topbar() {
  const { user, logout } = useAuth();

  const memberships = user?.memberships ?? [];
  const active = user
    ? memberships.find((m) => m.role === user.role && (m.tenantId ?? null) === user.tenantId)
    : undefined;

  const onSwitch = (value: string) => {
    const [role, tenantId] = value.split('|');
    setActiveMembership({ role, tenantId: tenantId || null });
    // Role/tenant scope every page's data — a clean reload is the simplest
    // correct way to re-render the whole app under the new membership.
    window.location.assign('/');
  };

  return (
    <header className="flex h-16 flex-shrink-0 items-center gap-4 bg-brand-valhalla px-5">
      {/* Brand */}
      <div className="flex items-center gap-3">
        <img src="/truist-logo1.svg" alt="Truist" className="logo-invert h-8 w-8" />
        <p className="text-sm font-semibold text-white">Truist Model Training (TMT)</p>
      </div>

      {/* User profile — top right */}
      <div className="ml-auto flex items-center gap-3">
        {memberships.length > 1 ? (
          <label className="flex items-center gap-2 text-xs text-white/70">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-purple-soft" />
            <select
              value={active ? membershipValue(active) : ''}
              onChange={(e) => onSwitch(e.target.value)}
              className="rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs text-white focus:outline-none [&>option]:text-text-primary"
              aria-label="Switch role and tenant"
            >
              {memberships.map((m) => (
                <option key={membershipValue(m)} value={membershipValue(m)}>
                  {membershipLabel(m)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs text-white/80">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-purple-soft" />
            {user
              ? membershipLabel(
                  active ?? {
                    role: user.role,
                    tenantId: user.tenantId,
                    tenantName: null,
                    groupName: null,
                  },
                )
              : 'Not signed in'}
          </div>
        )}

        {user && (
          <>
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-brand-purple-soft/20 text-sm font-semibold text-brand-purple-soft">
              {(user.name ?? '?').charAt(0).toUpperCase()}
            </div>
            <div className="hidden min-w-0 md:block">
              <p className="max-w-[160px] truncate text-sm font-medium text-white">{user.name}</p>
              <p className="max-w-[160px] truncate text-xs text-white/60">{user.email}</p>
            </div>
            <button
              onClick={() => void logout()}
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-medium text-white/80 transition hover:bg-white/10 hover:text-white"
            >
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
