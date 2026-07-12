import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { jobsApi } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import { useTenantContext } from '../../hooks/useTenantContext';
import { useAuth } from '../../auth/AuthContext';
import { PageHeader, Button, Select, Modal, Field, Input, InlineAlert, XIcon } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { JobStatusBadge } from '../../components/jobs/JobStatusBadge';
import { formatDate, formatDateTime, formatDuration } from '../../lib/format';
import { localToday, swapDatedPrefix } from '../../lib/jobs';
import type { TrainingJob } from '../../types/platform';

const STATUS_OPTIONS = ['', 'queued', 'running', 'succeeded', 'failed', 'cancelled'];

export function JobsPage() {
  const navigate = useNavigate();
  const { canSubmitJobs } = useTenantContext();
  const { user } = useAuth();
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [myJobsOnly, setMyJobsOnly] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Detail view: full configuration + failure reason + log stream for one job.
  const [detailJob, setDetailJob] = useState<TrainingJob | null>(null);
  const [detailLogsUrl, setDetailLogsUrl] = useState<string | null>(null);

  // Re-run: submit a NEW job copied from an existing one, changing only what
  // a DS actually changes between runs — the as-of date and hyperparameters.
  // (Structural changes — data source, script, resources — go through Clone,
  // which reopens the full wizard from the detail view.)
  const [rerunJob, setRerunJob] = useState<TrainingJob | null>(null);
  const [rerunDate, setRerunDate] = useState('');
  const [rerunParams, setRerunParams] = useState<{ key: string; value: string }[]>([]);
  const [rerunSaving, setRerunSaving] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await jobsApi.list({ pageSize: 100, status: statusFilter || undefined });
      setJobs(res.items);
      // Keep an open detail modal in sync with the poll — otherwise it shows
      // a stale status forever and offers Cancel on a finished job.
      setDetailJob((d) => (d ? res.items.find((j) => j.jobId === d.jobId) ?? d : d));
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
      setDetailJob(null);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setCancellingId(null);
    }
  };

  const openDetail = (j: TrainingJob) => {
    setDetailJob(j);
    setDetailLogsUrl(null);
    // Log-stream URL is resolved server-side per compute backend.
    jobsApi
      .logs(j.jobId)
      .then((r) => setDetailLogsUrl(r.logStreamUrl))
      .catch(() => setDetailLogsUrl(null));
  };

  // Clone: reopen the submit wizard pre-filled from this job — the DS
  // iteration loop is tweak-one-thing-and-resubmit, not re-enter-everything.
  const cloneJob = (j: TrainingJob) => {
    navigate('/workspace/submit', { state: { cloneFrom: j } });
  };

  /** Output path for a re-run: swap the trailing date segment when the job
   * followed the …/<name>/<as-of-date>/ convention, so backfills land in
   * their own prefix; custom paths are reused untouched. */
  const rerunOutputPath = (j: TrainingJob, newDate: string): string =>
    swapDatedPrefix(j.s3OutputPath, j.asOfDate, newDate) || j.s3OutputPath || '';

  const openRerun = (j: TrainingJob) => {
    setRerunJob(j);
    setRerunDate(j.asOfDate ?? localToday());
    setRerunParams(Object.entries(j.hyperparameters ?? {}).map(([key, value]) => ({ key, value: String(value) })));
    setRerunError(null);
  };

  const submitRerun = async () => {
    if (!rerunJob) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rerunDate)) {
      setRerunError('Pick a valid as-of date.');
      return;
    }
    setRerunSaving(true);
    setRerunError(null);
    try {
      const hyperparameters: Record<string, string> = {};
      rerunParams.forEach((row) => {
        if (row.key.trim()) hyperparameters[row.key.trim()] = row.value;
      });
      const job = await jobsApi.submit({
        name: rerunJob.name,
        computeType: rerunJob.computeType,
        framework: rerunJob.framework,
        asOfDate: rerunDate,
        entryPointScript: rerunJob.entryPointScript,
        s3InputPath: rerunJob.s3InputPath || '',
        s3OutputPath: rerunOutputPath(rerunJob, rerunDate),
        instanceType: rerunJob.instanceType,
        instanceCount: rerunJob.instanceCount,
        volumeSizeGb: rerunJob.volumeSizeGb,
        hyperparameters,
        ...(rerunJob.snowflakeDatabase
          ? {
              snowflakeDatabase: rerunJob.snowflakeDatabase,
              snowflakeSchema: rerunJob.snowflakeSchema ?? undefined,
              snowflakeTable: rerunJob.snowflakeTable ?? undefined,
              snowflakeWarehouse: rerunJob.snowflakeWarehouse ?? undefined,
              snowflakeSql: rerunJob.snowflakeSql ?? undefined,
            }
          : {}),
        ...(rerunJob.computeType === 'emr_serverless'
          ? {
              driverMemory: rerunJob.driverMemory ?? undefined,
              executorMemory: rerunJob.executorMemory ?? undefined,
              maxExecutors: rerunJob.maxExecutors ?? undefined,
            }
          : {}),
      });
      setNotice(`Re-run submitted as ${job.jobId} (as of ${rerunDate}).`);
      setRerunJob(null);
      await load();
    } catch (err) {
      setRerunError(extractErrorMessage(err));
    } finally {
      setRerunSaving(false);
    }
  };

  const columns: Column<TrainingJob>[] = [
    { key: 'name', header: 'Job', render: (j) => (
      <div>
        <p className="font-mono text-xs font-medium text-text-primary">{j.name}</p>
        <p className="text-[11px] text-text-muted">{j.jobId}</p>
      </div>
    ) },
    { key: 'status', header: 'Status', render: (j) => (
      <span title={j.statusReason ?? undefined}>
        <JobStatusBadge status={j.status} />
      </span>
    ) },
    { key: 'computeType', header: 'Compute', render: (j) => (j.computeType === 'emr_serverless' ? 'EMR Serverless' : 'SageMaker') },
    { key: 'framework', header: 'Framework', render: (j) => j.framework },
    { key: 'asOfDate', header: 'As of', render: (j) => (
      <span className="font-mono text-xs">{j.asOfDate ?? '—'}</span>
    ) },
    { key: 'duration', header: 'Duration', render: (j) => formatDuration(j.durationSeconds) },
    { key: 'createdAt', header: 'Submitted', render: (j) => formatDate(j.createdAt) },
    // Experiments are a PREVIEW feature, not part of this release — the
    // linked run stays on the job record but the Experiment column/link is
    // intentionally not shown.
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (j) => (
        <div className="flex items-center justify-end gap-2">
          {['queued', 'running'].includes(j.status) && (
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
          )}
          {canSubmitJobs && ['succeeded', 'failed', 'cancelled'].includes(j.status) && (
            <Button
              variant="secondary"
              className="!px-3 !py-1.5 !text-xs"
              title="Run again with a different as-of date and/or hyperparameters — everything else is reused"
              onClick={(e) => {
                e.stopPropagation();
                openRerun(j);
              }}
            >
              Re-run
            </Button>
          )}
        </div>
      ),
    },
  ];

  const visibleJobs = myJobsOnly && user ? jobs.filter((j) => j.userId === user.userId) : jobs;

  return (
    <div>
      <PageHeader
        title="Training Jobs"
        description="Live status polls every 5 seconds."
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 whitespace-nowrap text-xs text-text-secondary">
              <input type="checkbox" checked={myJobsOnly} onChange={(e) => setMyJobsOnly(e.target.checked)} />
              My jobs
            </label>
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

      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <DataTable
        columns={columns}
        rows={visibleJobs}
        rowKey={(j) => j.jobId}
        loading={loading}
        error={error}
        onRetry={load}
        onRowClick={openDetail}
        emptyTitle="No jobs found"
        emptyDescription={canSubmitJobs ? 'Submit your first training job to get started.' : undefined}
      />

      {/* ── Job detail: full config, failure reason, logs ────────────────── */}
      <Modal
        open={!!detailJob}
        title={detailJob ? detailJob.name : 'Job detail'}
        onClose={() => setDetailJob(null)}
        size="lg"
        footer={
          detailJob && (
            <>
              {canSubmitJobs && (
                <Button
                  variant="secondary"
                  title="Full edit — reopens the wizard to change data source, script, or resources"
                  onClick={() => cloneJob(detailJob)}
                >
                  Clone
                </Button>
              )}
              {['queued', 'running'].includes(detailJob.status) && (
                <Button
                  variant="danger"
                  loading={cancellingId === detailJob.jobId}
                  onClick={() => void cancelJob(detailJob.jobId)}
                >
                  Cancel job
                </Button>
              )}
              {canSubmitJobs && ['succeeded', 'failed', 'cancelled'].includes(detailJob.status) && (
                <Button
                  onClick={() => {
                    setDetailJob(null);
                    openRerun(detailJob);
                  }}
                >
                  Re-run
                </Button>
              )}
            </>
          )
        }
      >
        {detailJob && (
          <div className="space-y-4 text-sm">
            <div className="flex items-center gap-3">
              <JobStatusBadge status={detailJob.status} />
              <span className="font-mono text-xs text-text-muted">{detailJob.jobId}</span>
              {detailLogsUrl && (
                <a
                  href={detailLogsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto text-xs font-medium text-brand-purple hover:underline"
                >
                  Open log stream ↗
                </a>
              )}
            </div>

            {detailJob.statusReason && (
              <InlineAlert tone={detailJob.status === 'failed' ? 'error' : 'warn'}>
                {detailJob.statusReason}
              </InlineAlert>
            )}

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
              <DetailKV label="Compute" value={detailJob.computeType === 'emr_serverless' ? 'EMR Serverless' : 'SageMaker'} />
              <DetailKV label="Framework" value={detailJob.framework} />
              <DetailKV label="As-of date" value={detailJob.asOfDate ?? '—'} mono />
              <DetailKV
                label="Instance"
                value={`${detailJob.instanceType || '—'} × ${detailJob.instanceCount}, ${detailJob.volumeSizeGb}GB`}
              />
              <DetailKV label="Submitted" value={formatDateTime(detailJob.createdAt)} />
              <DetailKV label="Started" value={detailJob.startedAt ? formatDateTime(detailJob.startedAt) : '—'} />
              <DetailKV
                label="Completed"
                value={
                  detailJob.completedAt
                    ? `${formatDateTime(detailJob.completedAt)} (${formatDuration(detailJob.durationSeconds)})`
                    : '—'
                }
              />
              <DetailKV label="Submitted by" value={detailJob.userId} />
              <DetailKV label="Linked run" value={detailJob.experimentRunId ?? '—'} mono />
              {detailJob.computeType === 'emr_serverless' && (
                <DetailKV
                  label="Spark"
                  value={`driver ${detailJob.driverMemory ?? '—'} · executor ${detailJob.executorMemory ?? '—'} · max ${detailJob.maxExecutors ?? '—'}`}
                />
              )}
            </dl>

            <DetailUri label="Entry point" value={detailJob.entryPointScript} />
            <DetailUri
              label="Data source"
              value={
                detailJob.snowflakeDatabase
                  ? `Snowflake: ${detailJob.snowflakeDatabase}.${detailJob.snowflakeSchema}.${detailJob.snowflakeTable}${
                      detailJob.snowflakeSql ? ' (custom SQL)' : ''
                    }`
                  : detailJob.s3InputPath || '—'
              }
            />
            {detailJob.snowflakeSql && <DetailUri label="SQL" value={detailJob.snowflakeSql} />}
            <DetailUri label="Output path" value={detailJob.s3OutputPath || '—'} />

            {Object.keys(detailJob.hyperparameters ?? {}).length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">Hyperparameters</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(detailJob.hyperparameters).map(([k, v]) => (
                    <span key={k} className="rounded-md bg-bg-dark px-2 py-1 font-mono text-xs text-text-secondary">
                      {k}={String(v)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* ── Re-run: new run, new date/params, everything else reused ─────── */}
      <Modal
        open={!!rerunJob}
        title={rerunJob ? `Re-run — ${rerunJob.name}` : 'Re-run'}
        onClose={() => setRerunJob(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRerunJob(null)}>
              Cancel
            </Button>
            <Button loading={rerunSaving} onClick={() => void submitRerun()}>
              Re-run job
            </Button>
          </>
        }
      >
        {rerunJob && (
          <div className="space-y-4">
            {rerunError && <InlineAlert tone="error">{rerunError}</InlineAlert>}
            <p className="text-xs text-text-muted">
              Submits a new job reusing <span className="font-mono">{rerunJob.jobId}</span>&apos;s script, data
              source, and resources — only the as-of date and hyperparameters below change. For structural
              edits use Clone in the job detail.
            </p>
            <Field label="As-of date" required hint="Your script receives it as AS_OF_DATE.">
              <Input type="date" value={rerunDate} onChange={(e) => setRerunDate(e.target.value)} className="!w-48" />
            </Field>
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium text-text-secondary">Hyperparameters</p>
                <Button
                  variant="secondary"
                  className="!px-3 !py-1 !text-xs"
                  onClick={() => setRerunParams((p) => [...p, { key: '', value: '' }])}
                >
                  + Add row
                </Button>
              </div>
              <div className="space-y-2">
                {rerunParams.map((row, idx) => (
                  <div key={idx} className="flex gap-2">
                    <Input
                      value={row.key}
                      onChange={(e) =>
                        setRerunParams((p) => p.map((r, i) => (i === idx ? { ...r, key: e.target.value } : r)))
                      }
                      placeholder="key"
                      aria-label="Hyperparameter key"
                      className="font-mono"
                    />
                    <Input
                      value={row.value}
                      onChange={(e) =>
                        setRerunParams((p) => p.map((r, i) => (i === idx ? { ...r, value: e.target.value } : r)))
                      }
                      placeholder="value"
                      aria-label="Hyperparameter value"
                      className="font-mono"
                    />
                    <Button
                      variant="ghost"
                      className="!px-3"
                      onClick={() => setRerunParams((p) => p.filter((_, i) => i !== idx))}
                      aria-label="Remove hyperparameter"
                    >
                      <XIcon size={16} />
                    </Button>
                  </div>
                ))}
                {rerunParams.length === 0 && <p className="text-sm text-text-muted">No hyperparameters set.</p>}
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">Output path</p>
              <p className="break-all rounded-lg bg-bg-dark px-3 py-1.5 font-mono text-xs text-text-secondary">
                {rerunOutputPath(rerunJob, rerunDate) || '—'}
              </p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function DetailKV({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className={`mt-0.5 text-text-primary ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
    </div>
  );
}

function DetailUri({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</p>
      <p className="break-all rounded-lg bg-bg-dark px-3 py-1.5 font-mono text-xs text-text-secondary">{value}</p>
    </div>
  );
}
