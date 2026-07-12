import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { jobsApi } from '../../api/jobs';
import { experimentsApi } from '../../api/experiments';
import { modelsApi } from '../../api/models';
import { extractErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { PageHeader, StatTile, Card, Button } from '../../components/shared/ui';
import { JobStatusBadge } from '../../components/jobs/JobStatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { ComputePanel } from '../../components/tenant/ComputePanel';
import { useTenantContext } from '../../hooks/useTenantContext';
import { formatRelative } from '../../lib/format';
import type { TrainingJob, Experiment } from '../../types/platform';

export function DataScientistDashboard() {
  const { user } = useAuth();
  const { tenantId } = useTenantContext();
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [myModelCount, setMyModelCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        // These endpoints are tenant-scoped server-side for a Data Scientist;
        // "mine" is filtered client-side since there's no userId query param.
        const [j, e, m] = await Promise.all([
          jobsApi.list({ pageSize: 100 }),
          experimentsApi.list({ pageSize: 100 }),
          modelsApi.list({ pageSize: 100 }),
        ]);
        if (cancelled) return;
        setJobs(j.items.filter((job) => job.userId === user.userId));
        setExperiments(e.items.filter((exp) => exp.createdBy === user.userId));
        setMyModelCount(m.items.filter((mv) => mv.registeredBy === user.userId).length);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading your dashboard…" />
      </div>
    );
  }

  const runningNow = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length;
  const succeeded = jobs.filter((j) => j.status === 'succeeded').length;
  const recentJobs = [...jobs].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 6);
  const recentExperiments = [...experiments]
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, 6);

  return (
    <div>
      <PageHeader
        title={`Welcome back${user?.name ? `, ${user.name.split(' ')[0]}` : ''}`}
        description="Your jobs, experiments, and models at a glance."
        actions={
          <Link to="/workspace/submit">
            <Button>Submit job</Button>
          </Link>
        }
      />

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="My jobs" value={jobs.length} />
        <StatTile label="Running now" value={runningNow} accent />
        <StatTile label="Succeeded" value={succeeded} />
        <StatTile label="Models registered" value={myModelCount} />
      </div>

      {tenantId && (
        <div className="mt-4">
          <ComputePanel tenantId={tenantId} compact />
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Recent jobs</h3>
            <Link to="/workspace/jobs" className="text-xs font-medium text-brand-purple hover:underline">
              View all jobs →
            </Link>
          </div>
          {recentJobs.length === 0 ? (
            <EmptyState
              title="No jobs yet"
              description="Submit your first training job to get started."
              action={
                <Link to="/workspace/submit">
                  <Button>Submit job</Button>
                </Link>
              }
            />
          ) : (
            <ul className="space-y-3">
              {recentJobs.map((j) => (
                <li key={j.jobId} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs font-medium text-text-primary">{j.name}</p>
                    <p className="text-xs text-text-muted">
                      {j.framework} · {formatRelative(j.createdAt)}
                    </p>
                  </div>
                  <JobStatusBadge status={j.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Experiments are a PREVIEW feature — not part of this release, so
            the panel is informational only (no navigation into it). */}
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">My experiments</h3>
            <span className="rounded-full border border-bg-elevated bg-bg-dark px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-text-muted">
              Preview
            </span>
          </div>
          {recentExperiments.length === 0 ? (
            <EmptyState title="No experiments yet" description="Experiment tracking arrives in a later release." />
          ) : (
            <ul className="space-y-3">
              {recentExperiments.map((exp) => (
                <li key={exp.experimentId} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-text-primary">{exp.name}</p>
                    <p className="text-xs text-text-muted">{formatRelative(exp.createdAt)}</p>
                  </div>
                  {exp.runCount !== undefined && (
                    <span className="flex-shrink-0 text-xs text-text-muted">{exp.runCount} runs</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
