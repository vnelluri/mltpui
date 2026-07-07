import { useTenantContext } from '../../hooks/useTenantContext';

const TENANT_LABELS: Record<string, string> = {
  'tenant-risk-analytics': 'Risk Analytics',
  'tenant-fraud-detection': 'Fraud Detection',
  'tenant-compliance': 'Compliance',
};

export function Topbar({ title }: { title?: string }) {
  const { tenantId, isPlatformAdmin, isMRM } = useTenantContext();

  const scopeLabel = isPlatformAdmin || isMRM
    ? 'All tenants'
    : tenantId
      ? TENANT_LABELS[tenantId] ?? tenantId
      : 'No tenant assigned';

  return (
    <header className="flex h-16 flex-shrink-0 items-center justify-between border-b border-bg-elevated bg-bg-dark/80 px-6 backdrop-blur">
      <h2 className="text-sm font-medium text-text-secondary">{title ?? ''}</h2>
      <div className="flex items-center gap-2 rounded-full border border-bg-elevated bg-bg-card px-3 py-1.5 text-xs text-text-secondary">
        <span className="h-1.5 w-1.5 rounded-full bg-brand-purple" />
        {scopeLabel}
      </div>
    </header>
  );
}
