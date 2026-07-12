import { useCallback, useState } from 'react';
import { tenantsApi } from '../../api/tenants';
import { usePolling } from '../../hooks/usePolling';
import { Card } from '../shared/ui';
import { StatusBadge } from '../shared/StatusBadge';
import type { TenantComputeStats } from '../../types/platform';

const STATE_TONES: Record<string, 'green' | 'amber' | 'gray'> = {
  STARTED: 'green',
  CREATING: 'amber',
  STARTING: 'amber',
  STOPPING: 'amber',
  STOPPED: 'gray',
  UNKNOWN: 'gray',
};

/** Cluster-level view of the tenant's EMR Serverless application: job counts,
 * application state, and ESTIMATED utilization (phase 1 — real CloudWatch
 * worker metrics are a later phase). Polls every 30s. */
export function ComputePanel({ tenantId, compact = false }: { tenantId: string; compact?: boolean }) {
  const [stats, setStats] = useState<TenantComputeStats | null>(null);

  const load = useCallback(async () => {
    try {
      setStats(await tenantsApi.computeStats(tenantId));
    } catch {
      setStats(null); // degrade silently — the panel just shows a dash state
    }
  }, [tenantId]);

  usePolling(load, 30_000, { immediate: true });

  const state = stats?.applicationState ?? 'UNKNOWN';
  const utilization = stats?.utilizationPct ?? null;

  const meter = (
    <div className="flex-1">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-text-secondary">
          Capacity{' '}
          <span className="text-text-muted">
            ({stats ? `${stats.allocatedVcpuEstimate} / ${stats.maxVcpu ?? '—'} vCPU` : '—'}
            {stats?.estimated ? ', estimated' : ''})
          </span>
        </span>
        <span className="font-mono text-text-primary">{utilization !== null ? `${utilization}%` : '—'}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-bg-elevated">
        <div
          className={`h-full rounded-full transition-all ${
            (utilization ?? 0) >= 85 ? 'bg-amber-500' : 'bg-brand-purple'
          }`}
          style={{ width: `${Math.min(100, utilization ?? 0)}%` }}
        />
      </div>
    </div>
  );

  if (compact) {
    return (
      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-6">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-text-muted">Compute</span>
          <StatusBadge status={state} tone={STATE_TONES[state] ?? 'gray'} label={state.toLowerCase()} />
        </div>
        <span className="whitespace-nowrap text-sm text-text-secondary">
          <span className="font-semibold text-text-primary">{stats?.runningJobs ?? '—'}</span> running ·{' '}
          <span className="font-semibold text-text-primary">{stats?.queuedJobs ?? '—'}</span> queued
        </span>
        {meter}
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Compute — EMR Serverless</h3>
        <StatusBadge status={state} tone={STATE_TONES[state] ?? 'gray'} label={state.toLowerCase()} />
      </div>
      <div className="mb-5 grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-bg-elevated bg-bg-dark px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-text-muted">Running jobs</p>
          <p className="mt-1 text-2xl font-semibold text-text-primary">{stats?.runningJobs ?? '—'}</p>
        </div>
        <div className="rounded-lg border border-bg-elevated bg-bg-dark px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-text-muted">Queued jobs</p>
          <p className="mt-1 text-2xl font-semibold text-text-primary">{stats?.queuedJobs ?? '—'}</p>
        </div>
      </div>
      {meter}
      {stats?.applicationId && (
        <p className="mt-3 font-mono text-xs text-text-muted">{stats.applicationId}</p>
      )}
    </Card>
  );
}
