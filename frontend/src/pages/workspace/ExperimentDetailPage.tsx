import { useEffect, useMemo, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { experimentsApi } from '../../api/experiments';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Card } from '../../components/shared/ui';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { formatDateTime, formatNumber } from '../../lib/format';
import type { Experiment, ExperimentRun } from '../../types/platform';

const LOWER_IS_BETTER = ['loss', 'psi', 'error', 'latency'];

function isLowerBetter(metricName: string): boolean {
  const lower = metricName.toLowerCase();
  return LOWER_IS_BETTER.some((token) => lower.includes(token));
}

export function ExperimentDetailPage() {
  const { experimentId } = useParams<{ experimentId: string }>();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!experimentId) return;
    let cancelled = false;
    (async () => {
      try {
        const [exp, runsRes] = await Promise.all([
          experimentsApi.get(experimentId),
          experimentsApi.listRuns(experimentId, { pageSize: 200 }),
        ]);
        if (cancelled) return;
        setExperiment(exp);
        setRuns(runsRes.items);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  const { paramKeys, metricKeys, bestByMetric } = useMemo(() => {
    const params = new Set<string>();
    const metrics = new Set<string>();
    runs.forEach((r) => {
      Object.keys(r.params ?? {}).forEach((k) => params.add(k));
      Object.keys(r.metrics ?? {}).forEach((k) => metrics.add(k));
    });
    const best: Record<string, { runId: string; value: number }> = {};
    metrics.forEach((m) => {
      const lowerBetter = isLowerBetter(m);
      let winner: { runId: string; value: number } | null = null;
      runs.forEach((r) => {
        const value = r.metrics?.[m];
        if (typeof value !== 'number') return;
        if (!winner || (lowerBetter ? value < winner.value : value > winner.value)) {
          winner = { runId: r.runId, value };
        }
      });
      if (winner) best[m] = winner;
    });
    return { paramKeys: Array.from(params), metricKeys: Array.from(metrics), bestByMetric: best };
  }, [runs]);

  const chartMetric = metricKeys.includes('auc') ? 'auc' : metricKeys[0];
  const chartData = runs
    .filter((r) => typeof r.metrics?.[chartMetric] === 'number')
    .map((r) => ({ name: r.runId.slice(-8), value: r.metrics[chartMetric] }));

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading experiment…" />
      </div>
    );
  }

  if (error || !experiment) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-300">
        {error ?? 'Experiment not found.'}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={experiment.name}
        description={experiment.description || `${runs.length} run${runs.length === 1 ? '' : 's'}`}
        actions={
          <Link to="/workspace/experiments" className="text-sm text-brand-purple hover:underline">
            ← Back to experiments
          </Link>
        }
      />

      {runs.length === 0 ? (
        <EmptyState title="No runs yet" description="Runs are created automatically when a training job completes." />
      ) : (
        <>
          {chartMetric && chartData.length > 0 && (
            <Card className="mb-6 p-5">
              <h3 className="mb-4 text-sm font-semibold text-text-primary">
                {chartMetric.toUpperCase()} by run
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1A1230" />
                    <XAxis dataKey="name" stroke="#5A5280" fontSize={11} />
                    <YAxis stroke="#5A5280" fontSize={11} />
                    <Tooltip
                      contentStyle={{ background: '#120D22', border: '1px solid #1A1230', borderRadius: 8 }}
                      labelStyle={{ color: '#F0EEFF' }}
                    />
                    <Bar dataKey="value" fill="#A6A3E0" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}

          <div className="overflow-hidden rounded-xl border border-bg-elevated bg-bg-card">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-bg-elevated bg-bg-elevated/40">
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary">
                      Run
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary">
                      Started
                    </th>
                    {paramKeys.map((k) => (
                      <th key={k} className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary">
                        {k}
                      </th>
                    ))}
                    {metricKeys.map((k) => (
                      <th key={k} className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.runId} className="border-b border-bg-elevated/60 last:border-0">
                      <td className="px-4 py-3 font-mono text-xs text-text-primary">{run.runId.slice(-10)}</td>
                      <td className="px-4 py-3 capitalize text-text-secondary">{run.status}</td>
                      <td className="px-4 py-3 text-text-secondary">{formatDateTime(run.startTime)}</td>
                      {paramKeys.map((k) => (
                        <td key={k} className="px-4 py-3 font-mono text-xs text-text-secondary">
                          {run.params?.[k] ?? '—'}
                        </td>
                      ))}
                      {metricKeys.map((k) => {
                        const value = run.metrics?.[k];
                        const isBest = bestByMetric[k]?.runId === run.runId;
                        return (
                          <td
                            key={k}
                            className={`px-4 py-3 font-mono text-xs ${
                              isBest ? 'font-semibold text-emerald-300' : 'text-text-primary'
                            }`}
                          >
                            {formatNumber(value)}
                            {isBest && ' ★'}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
