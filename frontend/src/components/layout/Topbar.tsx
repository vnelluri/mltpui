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

export function Topbar({ title }: { title?: string }) {
  const { user } = useAuth();

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
    <header className="flex h-16 flex-shrink-0 items-center justify-between border-b border-bg-elevated bg-bg-dark/80 px-6 backdrop-blur">
      <h2 className="text-sm font-medium text-text-secondary">{title ?? ''}</h2>
      {memberships.length > 1 ? (
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <span className="h-1.5 w-1.5 rounded-full bg-brand-purple" />
          <select
            value={active ? membershipValue(active) : ''}
            onChange={(e) => onSwitch(e.target.value)}
            className="rounded-full border border-bg-elevated bg-bg-card px-3 py-1.5 text-xs text-text-secondary focus:outline-none"
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
        <div className="flex items-center gap-2 rounded-full border border-bg-elevated bg-bg-card px-3 py-1.5 text-xs text-text-secondary">
          <span className="h-1.5 w-1.5 rounded-full bg-brand-purple" />
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
    </header>
  );
}
