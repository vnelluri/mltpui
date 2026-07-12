import { useEffect, useState } from 'react';
import { notebooksApi } from '../../api/notebooks';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Card, InlineAlert } from '../../components/shared/ui';
import { EmptyState } from '../../components/shared/EmptyState';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { formatDateTime, formatRelative } from '../../lib/format';
import type { NotebookSession, SessionType } from '../../types/platform';

const OPTIONS: { type: SessionType; title: string; description: string; logo: string }[] = [
  {
    type: 'emr_studio',
    title: 'EMR Studio',
    description: 'Jupyter-based notebooks backed by EMR Serverless, ideal for large-scale Spark workloads.',
    logo: '/emr.svg',
  },
  {
    type: 'sagemaker_studio',
    title: 'SageMaker Studio',
    description: 'Fully managed ML IDE with built-in framework kernels and one-click training/deployment.',
    logo: '/SageMaker.svg',
  },
];

export function NotebookPage() {
  const { tenantId, isReadOnly } = useTenantContext();
  // Notebooks are launched into a specific tenant's EMR Studio / SageMaker
  // domain. Platform Admin spans every tenant (tenantId is always null for
  // that role, by design) and MRM is read-only — neither has a tenant to
  // launch into, so show why instead of a button that silently does nothing.
  const canLaunch = !!tenantId && !isReadOnly;
  const [sessions, setSessions] = useState<NotebookSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState<SessionType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await notebooksApi.sessions();
      setSessions(res.items);
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

  const launch = async (sessionType: SessionType) => {
    if (!tenantId) {
      setError('Notebooks are launched within a specific tenant — this role has no tenant assigned.');
      return;
    }
    setLaunching(sessionType);
    try {
      const session = await notebooksApi.launch({ sessionType, tenantId });
      if (session.presignedUrl) {
        window.open(session.presignedUrl, '_blank', 'noopener,noreferrer');
      }
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLaunching(null);
    }
  };

  return (
    <div>
      <PageHeader title="Notebooks" description="Launch a personal notebook environment for interactive work." />

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {!canLaunch && (
        <InlineAlert tone="info" className="mb-6">
          Notebooks are launched within a specific tenant, so this role can't launch one directly.{' '}
          {isReadOnly
            ? 'MRM is read-only.'
            : 'Platform Admin spans every tenant rather than being assigned to one.'}{' '}
          Sign in as a Tenant Admin or Data Scientist to launch a notebook.
        </InlineAlert>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        {OPTIONS.map((opt) => (
          <Card key={opt.type} className="flex flex-col p-6">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-purple/15">
              <img src={opt.logo} alt="" className="h-8 w-8" />
            </div>
            <h3 className="text-base font-semibold text-text-primary">{opt.title}</h3>
            <p className="mt-2 flex-1 text-sm text-text-secondary">{opt.description}</p>
            <Button
              className="mt-5"
              disabled={!canLaunch}
              loading={launching === opt.type}
              onClick={() => void launch(opt.type)}
            >
              {launching !== opt.type && <img src={opt.logo} alt="" className="h-4 w-4" />}
              Launch {opt.title}
            </Button>
          </Card>
        ))}
      </div>

      <div className="mt-10">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">Active sessions</h3>
        {loading ? (
          <div className="flex justify-center py-10">
            <LoadingSpinner label="Loading sessions…" />
          </div>
        ) : sessions.length === 0 ? (
          <EmptyState title="No active sessions" description="Launch a notebook above to get started." />
        ) : (
          <div className="divide-y divide-bg-elevated overflow-hidden rounded-xl border border-bg-elevated bg-bg-card">
            {sessions.map((s) => (
              <div key={s.sessionId} className="flex items-center justify-between px-5 py-4 text-sm">
                <div>
                  <p className="font-medium text-text-primary">
                    {s.sessionType === 'emr_studio' ? 'EMR Studio' : 'SageMaker Studio'}
                  </p>
                  <p className="text-xs text-text-muted">
                    Launched {formatRelative(s.createdAt)} · expires {formatDateTime(s.urlExpiresAt)}
                  </p>
                </div>
                {/* URLs are returned once at launch and never persisted
                    (they're credentials) — past sessions are metadata only. */}
                {s.presignedUrl ? (
                  <a
                    href={s.presignedUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-medium text-brand-purple hover:underline"
                  >
                    Reopen →
                  </a>
                ) : (
                  <span className="text-xs text-text-muted">Relaunch to open</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
