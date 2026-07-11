import { useEffect, useMemo, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { governanceApi } from '../../api/governance';
import { modelsApi } from '../../api/models';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Card, Button, Field, Textarea, InlineAlert } from '../../components/shared/ui';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { ModelJourney, type JourneyStep } from '../../components/models/ModelJourney';
import { formatDate, formatDateTime } from '../../lib/format';
import type { GovernanceReview, ModelCard } from '../../types/platform';

export function ReviewDetailPage() {
  const { reviewId } = useParams<{ reviewId: string }>();
  const navigate = useNavigate();
  const { isMRM } = useTenantContext();
  const canDecide = isMRM;

  const [review, setReview] = useState<GovernanceReview | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comments, setComments] = useState('');
  const [conditions, setConditions] = useState('');
  // MRM's own review artifacts, one URI per line — attached with the decision.
  const [mrmArtifacts, setMrmArtifacts] = useState('');
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
        setMrmArtifacts((r.mrmArtifactUris ?? []).join('\n'));
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

  const journeySteps: JourneyStep[] = useMemo(() => {
    if (!review) return [];
    const decided = review.decision !== 'pending';
    const steps: JourneyStep[] = [
      {
        label: 'Initiated',
        caption: card
          ? `${formatDate(card.registeredAt)}${card.registeredBy ? ` · ${card.registeredBy}` : ''}`
          : undefined,
        state: 'done',
      },
      {
        label: 'Dev complete',
        caption: card?.artifactUri ? 'Results attached' : 'Artifact pending',
        state: 'done',
      },
      {
        label: 'Submitted to MRM',
        caption: `${review.createdAt ? formatDate(review.createdAt) : ''}${
          review.submittedBy ? ` · ${review.submittedBy}` : ''
        }`,
        state: decided ? 'done' : 'current',
      },
      decided
        ? {
            label: review.decision === 'approved' ? 'MRM approved' : 'MRM rejected',
            caption: `${formatDate(review.reviewedAt)}${review.reviewedBy ? ` · ${review.reviewedBy}` : ''}`,
            state: review.decision === 'approved' ? 'approved' : 'rejected',
          }
        : { label: 'MRM review completed', caption: 'Awaiting decision', state: 'todo' },
      card?.stage === 'Production'
        ? {
            label: 'Production',
            caption: card.promotedAt ? formatDate(card.promotedAt) : undefined,
            state: 'approved',
          }
        : {
            label: 'Production',
            caption: review.decision === 'approved' ? 'Ready to promote' : 'Requires approval',
            state: 'todo',
          },
    ];
    return steps;
  }, [review, card]);

  const decide = async (decision: 'approved' | 'rejected') => {
    if (!reviewId) return;
    if (!comments.trim()) {
      setSubmitError('Comments are required to submit a decision.');
      return;
    }
    const artifactUris = mrmArtifacts
      .split('\n')
      .map((u) => u.trim())
      .filter(Boolean);
    // MRM approves WITH their review artifacts — the evidence package is
    // part of the decision, mirroring the results the DS attached to submit.
    if (decision === 'approved' && artifactUris.length === 0) {
      setSubmitError('Attach at least one review artifact (validation report, test evidence…) to approve.');
      return;
    }
    setSubmitting(decision);
    setSubmitError(null);
    try {
      await governanceApi.decide(reviewId, {
        decision,
        comments: comments.trim(),
        conditions: conditions.trim(),
        mrmArtifactUris: artifactUris,
      });
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
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-600">
        {error ?? 'Review not found.'}
      </div>
    );
  }

  const metrics = card?.trainingRun?.metrics ?? null;

  return (
    <div>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            {review.modelName ?? review.modelId}
            {review.modelVersion ? (
              <span className="rounded-md bg-bg-elevated px-2 py-0.5 font-mono text-sm text-text-secondary">
                v{review.modelVersion}
              </span>
            ) : null}
          </span>
        }
        description={`${card?.usecaseId ? `Usecase ${card.usecaseId} · ` : ''}Tenant ${review.tenantId}`}
        actions={
          <div className="flex items-center gap-3">
            <StatusBadge status={review.decision} />
            <Link to="/governance/reviews" className="text-sm text-brand-purple hover:underline">
              ← Back to queue
            </Link>
          </div>
        }
      />

      {/* ── Model journey ──────────────────────────────────────────────── */}
      <Card className="mb-6 p-6">
        <h3 className="mb-5 text-xs font-semibold uppercase tracking-wide text-text-muted">Model journey</h3>
        <ModelJourney steps={journeySteps} />
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* ── Data scientist submission ──────────────────────────────── */}
          <Card className="p-5">
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Data scientist submission</h3>
            {!card ? (
              <p className="text-sm text-text-muted">No model card available.</p>
            ) : (
              <div className="space-y-5 text-sm">
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <KV label="Usecase" value={card.usecaseId ?? '—'} mono />
                  <KV label="Stage" value={String(card.stage)} />
                  <KV label="Framework" value={String(card.framework ?? '—')} />
                  <KV label="Run ID" value={card.trainingRun?.runId ?? '—'} mono />
                  <KV label="Has explainer" value={card.explainability.hasExplainer ? 'Yes' : 'No'} />
                </dl>
                <div>
                  <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                    Trained artifact
                  </h4>
                  <p className="break-all rounded-lg bg-bg-dark px-3 py-2 font-mono text-xs text-text-secondary">
                    {card.artifactUri ?? 'Not attached'}
                  </p>
                </div>
                <div>
                  <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                    Model documentation
                  </h4>
                  <p className="break-all rounded-lg bg-bg-dark px-3 py-2 font-mono text-xs text-text-secondary">
                    {card.documentationUri ?? 'Not submitted'}
                  </p>
                </div>
                {Object.keys(card.results ?? {}).length > 0 && (
                  <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                      Submitted results
                    </h4>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {Object.entries(card.results).map(([k, v]) => (
                        <div key={k} className="rounded-lg border border-bg-elevated bg-bg-dark px-3 py-2">
                          <p className="text-[11px] uppercase tracking-wide text-text-muted">{k}</p>
                          <p className="mt-0.5 font-mono text-sm text-text-primary">
                            {typeof v === 'number' ? v : String(v)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {metrics && Object.keys(metrics).length > 0 && (
                  <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                      Training metrics
                    </h4>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {Object.entries(metrics).map(([k, v]) => (
                        <div key={k} className="rounded-lg border border-bg-elevated bg-bg-dark px-3 py-2">
                          <p className="text-[11px] uppercase tracking-wide text-text-muted">{k}</p>
                          <p className="mt-0.5 font-mono text-sm text-text-primary">
                            {typeof v === 'number' ? v : String(v)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                    Model schema
                  </h4>
                  <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                    {JSON.stringify(card.schema, null, 2)}
                  </pre>
                </div>
                {card.description && <p className="text-xs text-text-secondary">{card.description}</p>}
              </div>
            )}
          </Card>
        </div>

        {/* ── MRM decision ───────────────────────────────────────────────── */}
        <div>
          <Card className="p-5">
            <h3 className="mb-4 text-sm font-semibold text-text-primary">MRM decision</h3>

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
                disabled={!canDecide || review.decision !== 'pending'}
                placeholder="Findings, rationale, references to model risk policy…"
              />
            </Field>
            <Field label="Conditions" className="mb-4">
              <Textarea
                rows={3}
                value={conditions}
                onChange={(e) => setConditions(e.target.value)}
                disabled={!canDecide || review.decision !== 'pending'}
                placeholder="Any conditions attached to this decision (optional)"
              />
            </Field>

            {review.decision === 'pending' ? (
              <Field
                label="Review artifacts"
                required
                className="mb-5"
                hint="One URI per line (validation report, test evidence, memo). Required to approve."
              >
                <Textarea
                  rows={3}
                  value={mrmArtifacts}
                  onChange={(e) => setMrmArtifacts(e.target.value)}
                  disabled={!canDecide}
                  placeholder={'s3://…/validation-report.pdf\nhttps://…/review-memo'}
                />
              </Field>
            ) : (
              <div className="mb-5">
                <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
                  Review artifacts
                </h4>
                {(review.mrmArtifactUris ?? []).length > 0 ? (
                  <ul className="space-y-1">
                    {(review.mrmArtifactUris ?? []).map((uri) => (
                      <li
                        key={uri}
                        className="break-all rounded-lg bg-bg-dark px-3 py-1.5 font-mono text-xs text-text-secondary"
                      >
                        {uri}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-text-muted">None attached.</p>
                )}
              </div>
            )}

            {canDecide && review.decision === 'pending' ? (
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
            ) : !canDecide ? (
              <p className="text-xs text-text-muted">Only Model Risk Management can submit a decision.</p>
            ) : null}
          </Card>
        </div>
      </div>
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className={`text-text-primary ${mono ? 'break-all font-mono text-xs leading-5' : ''}`}>{value}</dd>
    </div>
  );
}
