import type { Role } from '../types/platform';

export const ROLES: Role[] = ['PlatformAdmin', 'TenantAdmin', 'DataScientist', 'MRM'];

// Highest privilege first — mirrors backend precedence: PlatformAdmin > MRM > TenantAdmin > DataScientist
const ROLE_PRIORITY: Record<Role, number> = {
  PlatformAdmin: 4,
  MRM: 3,
  TenantAdmin: 2,
  DataScientist: 1,
};

export const ROLE_LABELS: Record<Role, string> = {
  PlatformAdmin: 'Platform Admin',
  TenantAdmin: 'Tenant Admin',
  DataScientist: 'Data Scientist',
  MRM: 'Model Risk Management',
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  PlatformAdmin: 'Manage all tenants and platform settings across the platform.',
  TenantAdmin: "Manage your tenant's users, jobs, and settings.",
  DataScientist: 'Submit jobs, run experiments, and register models.',
  MRM: 'Read-only governance review across all tenants.',
};

export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && ROLES.includes(value as Role);
}

/**
 * Resolve the highest-privilege role from a list of role strings.
 * Used only for display/debug when decoding the custom:groups claim — the
 * authoritative role always comes from GET /auth/me.
 */
export function parseTenantRole(roles: string[]): Role | null {
  const valid = roles.filter(isRole);
  if (valid.length === 0) return null;
  return valid.sort((a, b) => ROLE_PRIORITY[b] - ROLE_PRIORITY[a])[0];
}

export function hasRole(role: Role | null | undefined, allowed: Role[]): boolean {
  if (!role) return false;
  return allowed.includes(role);
}

export function landingPathForRole(role: Role): string {
  switch (role) {
    case 'PlatformAdmin':
      return '/admin';
    case 'TenantAdmin':
      return '/tenant';
    case 'DataScientist':
      return '/workspace';
    case 'MRM':
      return '/governance';
    default:
      return '/login';
  }
}
