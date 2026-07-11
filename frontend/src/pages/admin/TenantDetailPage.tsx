import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { tenantsApi } from '../../api/tenants';
import { jobsApi } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Card, StatTile } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { JobStatusBadge } from '../../components/jobs/JobStatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { formatDate, formatDuration } from '../../lib/format';
import type { Tenant, TenantMetrics, TrainingJob } from '../../types/platform';

export function TenantDetailPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [metrics, setMetrics] = useState<TenantMetrics | null>(null);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    (async () => {
      try {
        const [t, m, j] = await Promise.all([
          tenantsApi.get(tenantId),
          tenantsApi.metrics(tenantId),
          jobsApi.list({ tenantId, pageSize: 100 }),
        ]);
        if (cancelled) return;
        setTenant(t);
        setMetrics(m);
        setJobs(j.items.filter((job) => job.tenantId === tenantId));
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
        <LoadingSpinner label="Loading tenant…" />
      </div>
    );
  }

  if (error || !tenant) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-600">
        {error ?? 'Tenant not found.'}
      </div>
    );
  }

  const jobColumns: Column<TrainingJob>[] = [
    { key: 'name', header: 'Job', render: (j) => <span className="font-mono text-xs">{j.name}</span> },
    { key: 'status', header: 'Status', render: (j) => <JobStatusBadge status={j.status} /> },
    { key: 'framework', header: 'Framework', render: (j) => j.framework },
    { key: 'duration', header: 'Duration', render: (j) => formatDuration(j.durationSeconds) },
    { key: 'createdAt', header: 'Created', render: (j) => formatDate(j.createdAt) },
  ];

  return (
    <div>
      <PageHeader
        title={tenant.name}
        description={tenant.tenantId}
        actions={
          <Link to="/admin/tenants" className="text-sm text-brand-purple hover:underline">
            ← Back to tenants
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Status" value={<StatusBadge status={tenant.status} />} />
        <StatTile label="Jobs" value={metrics?.jobCount ?? jobs.length} />
        <StatTile label="Registered models" value={metrics?.registeredModels ?? '—'} />
        <StatTile
          label="Compute used"
          value={`${metrics?.computeHoursUsed ?? 0} / ${tenant.computeQuotaVcpuHours}`}
          hint="vCPU-hours"
        />
      </div>

      <Card className="mt-6 p-5">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">Settings</h3>
        <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-text-muted">Allowed frameworks</dt>
            <dd className="mt-1 text-text-primary">{(tenant.allowedFrameworks ?? []).join(', ') || '—'}</dd>
          </div>
          <div>
            <dt className="text-text-muted">S3 bucket</dt>
            <dd className="mt-1 font-mono text-xs text-text-primary">{tenant.s3BucketName || '—'}</dd>
          </div>
          <div>
            <dt className="text-text-muted">EMR application</dt>
            <dd className="mt-1 font-mono text-xs text-text-primary">{tenant.emrApplicationId || 'Not configured'}</dd>
          </div>
          <div>
            <dt className="text-text-muted">SageMaker domain</dt>
            <dd className="mt-1 font-mono text-xs text-text-primary">{tenant.sagemakerDomainId || 'Not configured'}</dd>
          </div>
          <div>
            <dt className="text-text-muted">Execution role</dt>
            <dd className="mt-1 font-mono text-xs text-text-primary">{tenant.executionRoleArn || 'Not provisioned'}</dd>
          </div>
          <div>
            <dt className="text-text-muted">Provisioning</dt>
            <dd className="mt-1 text-text-primary">{tenant.provisioningStatus ?? 'active'}</dd>
          </div>
        </dl>
      </Card>

      <div className="mt-8">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">Recent jobs</h3>
        <DataTable columns={jobColumns} rows={jobs.slice(0, 10)} rowKey={(j) => j.jobId} emptyTitle="No jobs yet" />
      </div>
    </div>
  );
}
