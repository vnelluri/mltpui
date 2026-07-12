import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { tenantsApi } from '../../api/tenants';
import { jobsApi } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Card, StatTile } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { JobStatusBadge } from '../../components/jobs/JobStatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { ComputePanel } from '../../components/tenant/ComputePanel';
import { formatDate } from '../../lib/format';
import type { Tenant, TenantMetrics, TrainingJob } from '../../types/platform';

export function TenantDashboard() {
  const { tenantId } = useTenantContext();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [metrics, setMetrics] = useState<TenantMetrics | null>(null);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [t, m, j] = await Promise.all([
          tenantsApi.get(tenantId),
          tenantsApi.metrics(tenantId),
          jobsApi.list({ pageSize: 10 }),
        ]);
        if (cancelled) return;
        setTenant(t);
        setMetrics(m);
        setJobs(j.items);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading tenant dashboard…" />
      </div>
    );
  }

  if (error || !tenant) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-600">
        {error ?? 'No tenant assigned to your account.'}
      </div>
    );
  }

  const used = metrics?.computeHoursUsed ?? 0;
  const quota = tenant.computeQuotaVcpuHours || 1;
  const pct = Math.min(100, Math.round((used / quota) * 100));

  const columns: Column<TrainingJob>[] = [
    { key: 'name', header: 'Job', render: (j) => <span className="font-mono text-xs">{j.name}</span> },
    { key: 'status', header: 'Status', render: (j) => <JobStatusBadge status={j.status} /> },
    { key: 'framework', header: 'Framework', render: (j) => j.framework },
    { key: 'createdAt', header: 'Created', render: (j) => formatDate(j.createdAt) },
  ];

  return (
    <div>
      <PageHeader title={tenant.name} description="Your tenant's activity and compute usage." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatTile label="Total jobs" value={metrics?.jobCount ?? 0} />
        <StatTile label="Running now" value={metrics?.runningJobs ?? 0} accent />
        <StatTile label="Registered models" value={metrics?.registeredModels ?? '—'} />
      </div>

      {tenantId && (
        <div className="mt-6">
          <ComputePanel tenantId={tenantId} />
        </div>
      )}

      <Card className="mt-6 p-5">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-semibold text-text-primary">Compute quota usage</span>
          <span className="text-text-secondary">
            {used.toLocaleString()} / {quota.toLocaleString()} vCPU-hrs
          </span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-bg-elevated">
          <div
            className={`h-full rounded-full ${pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : 'bg-brand-purple'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </Card>

      <div className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">Recent jobs</h3>
          <Link to="/workspace/jobs" className="text-xs font-medium text-brand-purple hover:underline">
            View all jobs →
          </Link>
        </div>
        <DataTable columns={columns} rows={jobs} rowKey={(j) => j.jobId} emptyTitle="No jobs submitted yet" />
      </div>
    </div>
  );
}
