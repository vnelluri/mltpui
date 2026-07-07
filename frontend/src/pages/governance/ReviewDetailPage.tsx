import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { governanceApi } from '../../api/governance';
import { modelsApi } from '../../api/models';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Card, Button, Field, Textarea, InlineAlert } from '../../components/shared/ui';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { formatDateTime } from '../../lib/format';
import type { GovernanceReview, ModelCard } from '../../types/platform';

export function ReviewDetailPage() {
  const { reviewId } = useParams<{ reviewId: string }>();
  const navigate = useNavigate();
  const { isMRM } = useTenantContext();

  const [review, setReview] = useState<GovernanceReview | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comments, setComments] = useState('');
  const [conditions, setConditions] = useState('');
  const [submitting, setSubmitting] = useState<'approved' | 'rejected' | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!reviewId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await governanceApi.get(reviewId);
        if (cancelled) return;
        setReview(r);
        setComments(r.comments ?? '');
        setConditions(r.conditions ?? '');
        if (r.modelName && r.modelVersion) {
          // Model names are tenant-scoped; MRM reads across tenants, so the
          // review's tenant disambiguates the lookup.
          const c = await modelsApi.getCard(r.modelName, r.modelVersion, r.tenantId);
          if (!cancelled) setCard(c);
        }
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reviewId]);

  const decide = async (decision: 'approved' | 'rejected') => {
    if (!reviewId) return;
    if (!comments.trim()) {
      setSubmitError('Comments are required to submit a decision.');
      return;
    }
    setSubmitting(decision);
    setSubmitError(null);
    try {
      await governanceApi.decide(reviewId, { decision, comments: comments.trim(), conditions: conditions.trim() });
      // Decision recorded — return to the queue, where this review now shows
      // its final status and the next pending one is front and center.
      navigate('/governance/reviews');
    } catch (err) {
      setSubmitError(extractErrorMessage(err));
      setSubmitting(null);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading review…" />
      </div>
    );
  }

  if (error || !review) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-300">
        {error ?? 'Review not found.'}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={`${review.modelName ?? review.modelId} ${review.modelVersion ? `v${review.modelVersion}` : ''}`}
        description={`Tenant: ${review.tenantId}`}
        actions={
          <div className="flex items-center gap-3">
            <StatusBadge status={review.decision} />
            <Link to="/governance/reviews" className="text-sm text-brand-purple hover:underline">
              ← Back to queue
            </Link>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card className="p-5">
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Model card</h3>
            {!card ? (
              <p className="text-sm text-text-muted">No model card available.</p>
            ) : (
              <div className="space-y-5 text-sm">
                <dl className="grid grid-cols-2 gap-3">
                  <KV label="Stage" value={String(card.stage)} />
                  <KV label="Framework" value={String(card.framework ?? '—')} />
                  <KV label="Has explainer" value={card.explainability.hasExplainer ? 'Yes' : 'No'} />
                  <KV
                    label="Drift baseline"
                    value={card.explainability.driftBaselineUri ? 'Configured' : 'Not configured'}
                  />
                </dl>
                {card.trainingRun ? (
                  <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                      Training metrics
                    </h4>
                    <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                      {JSON.stringify(card.trainingRun.metrics ?? {}, null, 2)}
                    </pre>
                  </div>
                ) : null}
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">Schema</h4>
                  <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                    {JSON.stringify(card.schema, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </Card>
        </div>

        <div>
          <Card className="p-5">
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Decision</h3>

            {submitError && (
              <InlineAlert tone="error" className="mb-4">
                {submitError}
              </InlineAlert>
            )}

            {review.decision !== 'pending' && (
              <InlineAlert tone={review.decision === 'approved' ? 'success' : 'error'} className="mb-4">
                {review.decision === 'approved' ? 'Approved' : 'Rejected'} by {review.reviewedBy} on{' '}
                {formatDateTime(review.reviewedAt)}
              </InlineAlert>
            )}

            <Field label="Comments" required className="mb-4">
              <Textarea
                rows={4}
                value={comments}
                onChange={(e) => setComments(e.target.value)}
                disabled={!isMRM}
                placeholder="Findings, rationale, references to model risk policy…"
              />
            </Field>
            <Field label="Conditions" className="mb-5">
              <Textarea
                rows={3}
                value={conditions}
                onChange={(e) => setConditions(e.target.value)}
                disabled={!isMRM}
                placeholder="Any conditions attached to this decision (optional)"
              />
            </Field>

            {isMRM ? (
              <div className="flex gap-3">
                <Button
                  variant="danger"
                  className="flex-1"
                  loading={submitting === 'rejected'}
                  onClick={() => void decide('rejected')}
                >
                  Reject
                </Button>
                <Button className="flex-1" loading={submitting === 'approved'} onClick={() => void decide('approved')}>
                  Approve
                </Button>
              </div>
            ) : (
              <p className="text-xs text-text-muted">Only Model Risk Management can submit a decision.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="text-text-primary">{value}</dd>
    </div>
  );
}
