import { useCallback, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { jobsApi } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Select } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { JobStatusBadge } from '../../components/jobs/JobStatusBadge';
import { formatDate, formatDuration } from '../../lib/format';
import type { TrainingJob } from '../../types/platform';

const STATUS_OPTIONS = ['', 'queued', 'running', 'succeeded', 'failed', 'cancelled'];

export function JobsPage() {
  const navigate = useNavigate();
  const { canSubmitJobs } = useTenantContext();
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await jobsApi.list({ pageSize: 100, status: statusFilter || undefined });
      setJobs(res.items);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  usePolling(load, 5000, { immediate: true });

  const cancelJob = async (jobId: string) => {
    setCancellingId(jobId);
    try {
      await jobsApi.cancel(jobId);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setCancellingId(null);
    }
  };

  const columns: Column<TrainingJob>[] = [
    { key: 'name', header: 'Job', render: (j) => (
      <div>
        <p className="font-mono text-xs font-medium text-text-primary">{j.name}</p>
        <p className="text-[11px] text-text-muted">{j.jobId}</p>
      </div>
    ) },
    { key: 'status', header: 'Status', render: (j) => <JobStatusBadge status={j.status} /> },
    { key: 'computeType', header: 'Compute', render: (j) => (j.computeType === 'emr_serverless' ? 'EMR Serverless' : 'SageMaker') },
    { key: 'framework', header: 'Framework', render: (j) => j.framework },
    { key: 'duration', header: 'Duration', render: (j) => formatDuration(j.durationSeconds) },
    { key: 'createdAt', header: 'Submitted', render: (j) => formatDate(j.createdAt) },
    {
      key: 'experiment',
      header: 'Experiment',
      render: (j) =>
        j.experimentId ? (
          <Link
            to={`/workspace/experiments/${j.experimentId}`}
            onClick={(e) => e.stopPropagation()}
            className="text-xs font-medium text-brand-purple hover:underline"
          >
            View run →
          </Link>
        ) : (
          <span className="text-xs text-text-muted">—</span>
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (j) =>
        ['queued', 'running'].includes(j.status) ? (
          <Button
            variant="danger"
            className="!px-3 !py-1.5 !text-xs"
            loading={cancellingId === j.jobId}
            onClick={(e) => {
              e.stopPropagation();
              void cancelJob(j.jobId);
            }}
          >
            Cancel
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Training Jobs"
        description="Live status polls every 5 seconds."
        actions={
          <div className="flex items-center gap-3">
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="!w-40">
              {STATUS_OPTIONS.map((s) => (
                <option key={s || 'all'} value={s}>
                  {s ? s[0].toUpperCase() + s.slice(1) : 'All statuses'}
                </option>
              ))}
            </Select>
            {canSubmitJobs && <Button onClick={() => navigate('/workspace/submit')}>Submit job</Button>}
          </div>
        }
      />

      <DataTable
        columns={columns}
        rows={jobs}
        rowKey={(j) => j.jobId}
        loading={loading}
        error={error}
        onRetry={load}
        emptyTitle="No jobs found"
        emptyDescription={canSubmitJobs ? 'Submit your first training job to get started.' : undefined}
      />
    </div>
  );
}
