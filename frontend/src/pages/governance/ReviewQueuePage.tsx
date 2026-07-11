import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { governanceApi } from '../../api/governance';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Select } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { ModelJourneyMini } from '../../components/models/ModelJourney';
import { formatDate } from '../../lib/format';
import type { GovernanceReview, ModelDevStatus } from '../../types/platform';

/** A review's decision maps directly onto the model-journey stage. */
const DECISION_TO_DEV_STATUS: Record<string, ModelDevStatus> = {
  pending: 'submitted_to_mrm',
  approved: 'mrm_approved',
  rejected: 'mrm_rejected',
};

const DECISION_OPTIONS = ['', 'pending', 'approved', 'rejected'];

export function ReviewQueuePage() {
  const navigate = useNavigate();
  const [reviews, setReviews] = useState<GovernanceReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionFilter, setDecisionFilter] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await governanceApi.list({ pageSize: 200 });
      setReviews(res.items);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = decisionFilter ? reviews.filter((r) => r.decision === decisionFilter) : reviews;

  const columns: Column<GovernanceReview>[] = [
    { key: 'model', header: 'Model', render: (r) => (
      <div>
        <p className="font-medium text-text-primary">{r.modelName ?? r.modelId}</p>
        {r.modelVersion && <p className="text-xs text-text-muted">v{r.modelVersion}</p>}
      </div>
    ) },
    { key: 'tenant', header: 'Tenant', render: (r) => r.tenantId },
    { key: 'submitted', header: 'Submitted', render: (r) => (
      <div>
        <span className="block">{r.createdAt ? formatDate(r.createdAt) : '—'}</span>
        {r.submittedBy && <span className="block text-xs text-text-muted">{r.submittedBy}</span>}
      </div>
    ) },
    { key: 'journey', header: 'Journey', render: (r) => (
      <ModelJourneyMini devStatus={DECISION_TO_DEV_STATUS[r.decision] ?? 'submitted_to_mrm'} />
    ) },
    { key: 'decision', header: 'Decision', render: (r) => <StatusBadge status={r.decision} /> },
    { key: 'reviewedBy', header: 'Reviewed by', render: (r) => r.reviewedBy ?? '—' },
    { key: 'reviewedAt', header: 'Reviewed', render: (r) => formatDate(r.reviewedAt) },
  ];

  return (
    <div>
      <PageHeader
        title="Review Queue"
        description="All governance reviews across every tenant."
        actions={
          <Select value={decisionFilter} onChange={(e) => setDecisionFilter(e.target.value)} className="!w-40">
            {DECISION_OPTIONS.map((d) => (
              <option key={d || 'all'} value={d}>
                {d ? d[0].toUpperCase() + d.slice(1) : 'All decisions'}
              </option>
            ))}
          </Select>
        }
      />

      <DataTable
        columns={columns}
        rows={filtered}
        rowKey={(r) => r.reviewId}
        loading={loading}
        error={error}
        onRetry={load}
        onRowClick={(r) => navigate(`/governance/reviews/${r.reviewId}`)}
        emptyTitle="No reviews found"
      />
    </div>
  );
}
