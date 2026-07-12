import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { governanceApi } from '../../api/governance';
import { modelsApi } from '../../api/models';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Card, StatTile } from '../../components/shared/ui';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { formatRelative } from '../../lib/format';
import { S3UploadCard } from '../../components/s3/S3UploadCard';
import type { GovernanceReview, ModelVersion } from '../../types/platform';

export function GovernanceDashboard() {
  const [reviews, setReviews] = useState<GovernanceReview[]>([]);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [r, m] = await Promise.all([
          governanceApi.list({ pageSize: 200 }),
          modelsApi.list({ pageSize: 200 }),
        ]);
        if (cancelled) return;
        setReviews(r.items);
        setModels(m.items);
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
        <LoadingSpinner label="Loading governance overview…" />
      </div>
    );
  }

  const pending = reviews.filter((r) => r.decision === 'pending');
  const approved = reviews.filter((r) => r.decision === 'approved');
  const rejected = reviews.filter((r) => r.decision === 'rejected');
  const productionModels = models.filter((m) => m.stage === 'Production');

  return (
    <div>
      <PageHeader title="Governance" description="Model risk review across every tenant." />

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Pending review" value={pending.length} accent />
        <StatTile label="Approved" value={approved.length} />
        <StatTile label="Rejected" value={rejected.length} />
        <StatTile label="Production models" value={productionModels.length} />
      </div>

      {/* Renders for MRM only (the card self-gates by role). */}
      <div className="mt-4">
        <S3UploadCard />
      </div>

      <Card className="mt-8 p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">Awaiting review</h3>
          <Link to="/governance/reviews" className="text-xs font-medium text-brand-purple hover:underline">
            View full queue →
          </Link>
        </div>
        {pending.length === 0 ? (
          <EmptyState title="Nothing pending" description="All submitted models have been reviewed." />
        ) : (
          <ul className="divide-y divide-bg-elevated">
            {pending.map((r) => (
              <li key={r.reviewId} className="py-3">
                <Link to={`/governance/reviews/${r.reviewId}`} className="flex items-center justify-between text-sm">
                  <div>
                    <p className="font-medium text-text-primary">
                      {r.modelName ?? r.modelId} {r.modelVersion ? `v${r.modelVersion}` : ''}
                    </p>
                    <p className="text-xs text-text-muted">Tenant: {r.tenantId}</p>
                  </div>
                  <StatusBadge status={r.decision} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="mt-6 p-5">
        <h3 className="mb-4 text-sm font-semibold text-text-primary">Recently decided</h3>
        {approved.length + rejected.length === 0 ? (
          <EmptyState title="No decisions yet" />
        ) : (
          <ul className="divide-y divide-bg-elevated">
            {[...approved, ...rejected]
              .sort((a, b) => (b.reviewedAt ?? '').localeCompare(a.reviewedAt ?? ''))
              .slice(0, 5)
              .map((r) => (
                <li key={r.reviewId} className="py-3">
                  <Link to={`/governance/reviews/${r.reviewId}`} className="flex items-center justify-between text-sm">
                    <div>
                      <p className="font-medium text-text-primary">
                        {r.modelName ?? r.modelId} {r.modelVersion ? `v${r.modelVersion}` : ''}
                      </p>
                      <p className="text-xs text-text-muted">
                        {r.reviewedBy} · {formatRelative(r.reviewedAt)}
                      </p>
                    </div>
                    <StatusBadge status={r.decision} />
                  </Link>
                </li>
              ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
