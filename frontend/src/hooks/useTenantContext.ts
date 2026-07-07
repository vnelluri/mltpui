import { useAuth } from '../auth/AuthContext';
import type { Role } from '../types/platform';

export interface TenantContext {
  tenantId: string | null;
  role: Role | null;
  isPlatformAdmin: boolean;
  isMRM: boolean;
  isTenantAdmin: boolean;
  isDataScientist: boolean;
  /** True for roles that may mutate resources (submit jobs, register models). */
  canSubmitJobs: boolean;
  /** True for read-only governance roles. */
  isReadOnly: boolean;
}

export function useTenantContext(): TenantContext {
  const { user } = useAuth();
  const role = user?.role ?? null;
  return {
    tenantId: user?.tenantId ?? null,
    role,
    isPlatformAdmin: role === 'PlatformAdmin',
    isMRM: role === 'MRM',
    isTenantAdmin: role === 'TenantAdmin',
    isDataScientist: role === 'DataScientist',
    canSubmitJobs: role === 'DataScientist',
    isReadOnly: role === 'MRM',
  };
}
