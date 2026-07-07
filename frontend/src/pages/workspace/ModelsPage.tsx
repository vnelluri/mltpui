import { useEffect, useState, type ReactNode } from 'react';
import { modelsApi } from '../../api/models';
import { governanceApi } from '../../api/governance';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Modal, Field, Input, Select, Textarea } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { formatDate } from '../../lib/format';
import type { ModelVersion, ModelStage, Framework, ModelCard } from '../../types/platform';

const STAGES: ModelStage[] = ['None', 'Staging', 'Production', 'Archived'];
const FRAMEWORKS: Framework[] = ['pytorch', 'tensorflow', 'sklearn', 'xgboost'];

export function ModelsPage() {
  const { isDataScientist, isTenantAdmin, isPlatformAdmin } = useTenantContext();
  const canRegister = isDataScientist;
  const canTransition = isTenantAdmin || isPlatformAdmin;
  // Submitting FOR review is the model owner's action; MRM only decides.
  const canSubmitReview = isDataScientist || isTenantAdmin || isPlatformAdmin;

  const [models, setModels] = useState<ModelVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [runId, setRunId] = useState('');
  const [framework, setFramework] = useState<Framework>('pytorch');
  const [description, setDescription] = useState('');

  const [cardModel, setCardModel] = useState<ModelVersion | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [cardLoading, setCardLoading] = useState(false);

  const [submittingReview, setSubmittingReview] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await modelsApi.list({ pageSize: 200 });
      setModels(res.items);
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

  const submitRegister = async () => {
    if (!name.trim() || !runId.trim()) {
      setFormError('Model name and run ID are required.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await modelsApi.register({ name: name.trim(), runId: runId.trim(), framework, description: description.trim() });
      setRegisterOpen(false);
      setName('');
      setRunId('');
      setDescription('');
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const changeStage = async (model: ModelVersion, stage: ModelStage) => {
    try {
      await modelsApi.setStage(model.name, model.version, stage, model.tenantId);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  };

  const openCard = async (model: ModelVersion) => {
    setCardModel(model);
    setCard(null);
    setCardLoading(true);
    try {
      const c = await modelsApi.getCard(model.name, model.version, model.tenantId);
      setCard(c);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setCardLoading(false);
    }
  };

  const submitForReview = async (m: ModelVersion) => {
    setSubmittingReview(`${m.name}-${m.version}`);
    setNotice(null);
    try {
      // Idempotent server-side: re-submitting returns the existing pending
      // review instead of stacking duplicates in the MRM queue.
      const review = await governanceApi.create({
        modelId: m.modelId,
        modelName: m.name,
        modelVersion: m.version,
        tenantId: m.tenantId,
      });
      setNotice(
        `${m.name} v${m.version} is ${
          review.decision === 'pending' ? 'awaiting MRM review' : `already ${review.decision}`
        } (review ${review.reviewId}).`,
      );
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSubmittingReview(null);
    }
  };

  const columns: Column<ModelVersion>[] = [
    { key: 'name', header: 'Model', render: (m) => (
      <button onClick={() => void openCard(m)} className="text-left font-medium text-text-primary hover:text-brand-purple">
        {m.name}
      </button>
    ) },
    { key: 'version', header: 'Version', render: (m) => <span className="font-mono text-xs">v{m.version}</span> },
    {
      key: 'stage',
      header: 'Stage',
      render: (m) =>
        canTransition ? (
          <Select
            value={m.stage}
            onChange={(e) => void changeStage(m, e.target.value as ModelStage)}
            className="!w-36 !py-1 !text-xs"
          >
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        ) : (
          <StatusBadge status={m.stage} />
        ),
    },
    { key: 'framework', header: 'Framework', render: (m) => m.framework },
    { key: 'registeredBy', header: 'Registered by', render: (m) => m.registeredBy },
    { key: 'registeredAt', header: 'Registered', render: (m) => formatDate(m.registeredAt) },
    ...(canSubmitReview
      ? [
          {
            key: 'actions',
            header: '',
            render: (m: ModelVersion) =>
              m.stage !== 'Archived' ? (
                <Button
                  variant="secondary"
                  className="!px-3 !py-1 !text-xs"
                  loading={submittingReview === `${m.name}-${m.version}`}
                  onClick={() => void submitForReview(m)}
                >
                  Submit for review
                </Button>
              ) : null,
          } as Column<ModelVersion>,
        ]
      : []),
  ];

  return (
    <div>
      <PageHeader
        title="Model Registry"
        description="Registered model versions and their governance stage."
        actions={canRegister && <Button onClick={() => setRegisterOpen(true)}>Register model</Button>}
      />

      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          {notice}
        </div>
      )}

      <DataTable
        columns={columns}
        rows={models}
        rowKey={(m) => `${m.name}-${m.version}`}
        loading={loading}
        error={error}
        onRetry={load}
        emptyTitle="No models registered yet"
      />

      <Modal
        open={registerOpen}
        title="Register model version"
        onClose={() => setRegisterOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRegisterOpen(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void submitRegister()}>
              Register
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {formError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {formError}
            </div>
          )}
          <Field label="Model name" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. fraud-detector" />
          </Field>
          <Field label="Run ID" required hint="Copy from the experiment run you want to register.">
            <Input value={runId} onChange={(e) => setRunId(e.target.value)} className="font-mono" />
          </Field>
          <Field label="Framework" required>
            <Select value={framework} onChange={(e) => setFramework(e.target.value as Framework)}>
              {FRAMEWORKS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Description">
            <Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
      </Modal>

      <Modal
        open={!!cardModel}
        title={cardModel ? `${cardModel.name} v${cardModel.version} — Model Card` : 'Model Card'}
        onClose={() => setCardModel(null)}
        size="xl"
      >
        {cardLoading || !card ? (
          <div className="flex justify-center py-10">
            <LoadingSpinner label="Loading model card…" />
          </div>
        ) : (
          <div className="space-y-5 text-sm">
            <Section title="Overview">
              <KV label="Stage" value={String(card.stage)} />
              <KV label="Framework" value={String(card.framework ?? '—')} />
              <KV label="Artifact URI" value={String(card.artifactUri ?? '—')} mono />
              <KV label="Has explainer" value={card.hasExplainer ? 'Yes' : 'No'} />
            </Section>
            <Section title="Schema">
              <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                {JSON.stringify({ input: card.inputSchema, output: card.outputSchema }, null, 2)}
              </pre>
            </Section>
            {'trainingRun' in card && card.trainingRun ? (
              <Section title="Training run">
                <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                  {JSON.stringify(card.trainingRun, null, 2)}
                </pre>
              </Section>
            ) : null}
            {'governance' in card && card.governance ? (
              <Section title="Governance">
                <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                  {JSON.stringify(card.governance, null, 2)}
                </pre>
              </Section>
            ) : null}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">{title}</h4>
      {children}
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-bg-elevated/60 py-1.5 last:border-0">
      <span className="text-text-secondary">{label}</span>
      <span className={`text-text-primary ${mono ? 'font-mono text-xs' : ''}`}>{value}</span>
    </div>
  );
}
