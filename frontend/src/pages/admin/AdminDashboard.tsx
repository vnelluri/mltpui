import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { tenantsApi } from '../../api/tenants';
import { jobsApi } from '../../api/jobs';
import { modelsApi } from '../../api/models';
import { auditApi } from '../../api/audit';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, StatTile, Card } from '../../components/shared/ui';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { formatRelative } from '../../lib/format';
import type { Tenant, TrainingJob, ModelVersion, AuditEvent } from '../../types/platform';

export function AdminDashboard() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [t, j, m, a] = await Promise.all([
          tenantsApi.list({ pageSize: 100 }),
          jobsApi.list({ pageSize: 200 }),
          modelsApi.list({ pageSize: 200 }),
          auditApi.list({ pageSize: 8 }),
        ]);
        if (cancelled) return;
        setTenants(t.items);
        setJobs(j.items);
        setModels(m.items);
        setEvents(a.items);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading platform overview…" />
      </div>
    );
  }

  const activeTenants = tenants.filter((t) => t.status === 'active').length;
  const runningJobs = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;
  const productionModels = models.filter((m) => m.stage === 'Production').length;

  return (
    <div>
      <PageHeader
        title="Platform Overview"
        description="Cross-tenant activity across the ML Training Platform."
      />

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Tenants" value={tenants.length} hint={`${activeTenants} active`} accent />
        <StatTile label="Training Jobs" value={jobs.length} hint={`${runningJobs} in flight`} />
        <StatTile label="Registered Models" value={models.length} hint={`${productionModels} in Production`} />
        <StatTile label="Recent Audit Events" value={events.length} hint="Last 8 shown below" />
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Tenant health</h3>
            <Link to="/admin/tenants" className="text-xs font-medium text-brand-purple hover:underline">
              Manage tenants →
            </Link>
          </div>
          {tenants.length === 0 ? (
            <EmptyState title="No tenants yet" />
          ) : (
            <ul className="space-y-3">
              {tenants.map((t) => (
                <li key={t.tenantId} className="flex items-center justify-between text-sm">
                  <div>
                    <p className="font-medium text-text-primary">{t.name}</p>
                    <p className="text-xs text-text-muted">{t.tenantId}</p>
                  </div>
                  <StatusBadge status={t.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Recent activity</h3>
            <Link to="/audit" className="text-xs font-medium text-brand-purple hover:underline">
              View audit log →
            </Link>
          </div>
          {events.length === 0 ? (
            <EmptyState title="No activity yet" />
          ) : (
            <ul className="space-y-3">
              {events.map((e) => (
                <li key={e.eventId} className="text-sm">
                  <p className="text-text-primary">
                    <span className="font-mono text-xs text-brand-purple">{e.action}</span>{' '}
                    <span className="text-text-muted">on {e.resourceType}</span>
                  </p>
                  <p className="text-xs text-text-muted">
                    {e.userId} · {formatRelative(e.timestamp)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
