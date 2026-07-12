import { useEffect, useState, type ReactNode } from 'react';
import { modelsApi } from '../../api/models';
import { governanceApi } from '../../api/governance';
import { jobsApi } from '../../api/jobs';
import { notebooksApi } from '../../api/notebooks';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Modal, Field, Input, Select, Textarea } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { ModelJourneyTrack } from '../../components/models/ModelJourney';
import { isValidS3Uri, S3_URI_FORMAT_HINT } from '../../lib/s3';
import type { ModelVersion, Framework, ModelCard, SessionType, TrainingJob } from '../../types/platform';

const FRAMEWORKS: Framework[] = ['pytorch', 'tensorflow', 'sklearn', 'xgboost'];

export function ModelsPage() {
  const { isDataScientist, isTenantAdmin, isPlatformAdmin } = useTenantContext();
  const canRegister = isDataScientist;
  const canTransition = isTenantAdmin || isPlatformAdmin;
  // Submitting FOR review is the model owner's action; MRM only decides.
  const canSubmitReview = isDataScientist || isTenantAdmin || isPlatformAdmin;
  // Notebook launch is tenant-scoped work (backend requires DS/TenantAdmin).
  const canLaunchNotebook = isDataScientist || isTenantAdmin;

  const [models, setModels] = useState<ModelVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [regModelId, setRegModelId] = useState('');
  const [regVersion, setRegVersion] = useState('');
  const [usecaseId, setUsecaseId] = useState('');
  const [framework, setFramework] = useState<Framework>('pytorch');
  const [description, setDescription] = useState('');

  const [cardModel, setCardModel] = useState<ModelVersion | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [cardLoading, setCardLoading] = useState(false);

  // Archive (retire) a version — admin action, reachable from the card modal.
  const [archiveTarget, setArchiveTarget] = useState<ModelVersion | null>(null);
  const [archiving, setArchiving] = useState(false);

  const [submittingReview, setSubmittingReview] = useState<string | null>(null);
  const [launchingNotebook, setLaunchingNotebook] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // "Attach results": post-training update with the artifact + run MRM needs.
  const [updateModel, setUpdateModel] = useState<ModelVersion | null>(null);
  const [updArtifactUri, setUpdArtifactUri] = useState('');
  const [updRunId, setUpdRunId] = useState('');
  const [updDescription, setUpdDescription] = useState('');
  const [updError, setUpdError] = useState<string | null>(null);
  const [updSaving, setUpdSaving] = useState(false);

  const [updModelSchema, setUpdModelSchema] = useState('');
  const [updResults, setUpdResults] = useState('');
  const [updDocumentationUri, setUpdDocumentationUri] = useState('');

  // Promote-to-Production prompt: deployment readiness is gated on change
  // management, so the promotion must reference a ServiceNow change ticket.
  const [promoteModel, setPromoteModel] = useState<ModelVersion | null>(null);
  const [snowTicket, setSnowTicket] = useState('');
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);

  // Succeeded jobs offered as one-click prefill in the attach dialog — the
  // run id and output artifact live on the job record; nobody should have to
  // copy-paste them across pages.
  const [attachJobs, setAttachJobs] = useState<TrainingJob[]>([]);
  const [attachJobPick, setAttachJobPick] = useState('');

  const openUpdate = (m: ModelVersion) => {
    setUpdateModel(m);
    setUpdArtifactUri(m.artifactUri ?? '');
    setUpdRunId(m.runId ?? '');
    setUpdDescription(m.description ?? '');
    setUpdModelSchema(Object.keys(m.modelSchema ?? {}).length ? JSON.stringify(m.modelSchema, null, 2) : '');
    setUpdResults(Object.keys(m.results ?? {}).length ? JSON.stringify(m.results, null, 2) : '');
    setUpdDocumentationUri(m.documentationUri ?? '');
    setUpdError(null);
    setAttachJobPick('');
    jobsApi
      .list({ pageSize: 100, status: 'succeeded' })
      .then((res) => setAttachJobs(res.items.filter((j) => j.tenantId === m.tenantId).slice(0, 25)))
      .catch(() => setAttachJobs([]));
  };

  /** Parse an optional JSON textarea: '' -> undefined, invalid JSON / non-object -> error string. */
  const parseJsonField = (label: string, text: string): { value?: Record<string, unknown>; error?: string } => {
    if (!text.trim()) return {};
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return { error: `${label} must be a JSON object, e.g. {"auc": 0.94}.` };
      }
      return { value: parsed as Record<string, unknown> };
    } catch {
      return { error: `${label} is not valid JSON.` };
    }
  };

  const submitUpdate = async () => {
    if (!updateModel) return;
    if (!updArtifactUri.trim()) {
      setUpdError('Artifact URI is required — MRM reviews the trained binary.');
      return;
    }
    if (!isValidS3Uri(updArtifactUri)) {
      setUpdError(`Artifact URI must look like ${S3_URI_FORMAT_HINT}.`);
      return;
    }
    if (updDocumentationUri.trim() && !isValidS3Uri(updDocumentationUri)) {
      setUpdError(`Model documentation must look like ${S3_URI_FORMAT_HINT}.`);
      return;
    }
    const schema = parseJsonField('Model schema', updModelSchema);
    const results = parseJsonField('Results', updResults);
    if (schema.error || results.error) {
      setUpdError(schema.error ?? results.error ?? null);
      return;
    }
    setUpdSaving(true);
    setUpdError(null);
    try {
      await modelsApi.update(
        updateModel.name,
        updateModel.version,
        {
          artifactUri: updArtifactUri.trim(),
          runId: updRunId.trim() || undefined,
          description: updDescription.trim() || undefined,
          modelSchema: schema.value,
          results: results.value,
          documentationUri: updDocumentationUri.trim() || undefined,
        },
        updateModel.tenantId,
      );
      setNotice(`Results attached to ${updateModel.name} v${updateModel.version} — ready to submit for review.`);
      setUpdateModel(null);
      await load();
    } catch (err) {
      setUpdError(extractErrorMessage(err));
    } finally {
      setUpdSaving(false);
    }
  };

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
    if (!regModelId.trim()) {
      setFormError('Model ID is required — it is the model’s inventory key.');
      return;
    }
    if (!name.trim()) {
      setFormError('Model name is required.');
      return;
    }
    const versionText = regVersion.trim();
    const uc = usecaseId.trim().toUpperCase();
    if (!/^UC-\d{4}$/.test(uc)) {
      setFormError('Usecase ID must be in the form UC-#### (e.g. UC-1111).');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      // Registration happens at inception, before training — the run and
      // artifact are attached later via "Attach results".
      await modelsApi.register({
        modelId: regModelId.trim(),
        name: name.trim(),
        version: versionText || undefined,
        usecaseId: uc,
        framework,
        description: description.trim(),
      });
      setRegisterOpen(false);
      setName('');
      setRegModelId('');
      setRegVersion('');
      setUsecaseId('');
      setDescription('');
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const openRegisterBlank = () => {
    setRegModelId('');
    setName('');
    setRegVersion('');
    setUsecaseId('');
    setFramework('pytorch');
    setDescription('');
    setFormError(null);
    setRegisterOpen(true);
  };

  // "New version" from a registry row: identity fields (Model ID, name,
  // usecase, framework) must match the lineage anyway — prefill them and
  // leave the version on auto-next.
  const openRegisterNewVersion = (m: ModelVersion) => {
    setRegModelId(m.modelId);
    setName(m.name);
    setRegVersion('');
    setUsecaseId(m.usecaseId ?? '');
    setFramework((m.framework as Framework) || 'pytorch');
    setDescription('');
    setFormError(null);
    setRegisterOpen(true);
  };

  const confirmArchive = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await modelsApi.archive(archiveTarget.name, archiveTarget.version, archiveTarget.tenantId);
      setNotice(`${archiveTarget.name} v${archiveTarget.version} archived.`);
      setArchiveTarget(null);
      setCardModel(null);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
      setArchiveTarget(null);
    } finally {
      setArchiving(false);
    }
  };

  const submitPromote = async () => {
    if (!promoteModel) return;
    const ticket = snowTicket.trim().toUpperCase();
    if (!/^CHG\d{4,}$/.test(ticket)) {
      setPromoteError('Enter the ServiceNow change ticket authorizing this deployment, e.g. CHG0012345.');
      return;
    }
    setPromoting(true);
    setPromoteError(null);
    try {
      await modelsApi.setStage(promoteModel.name, promoteModel.version, 'Production', promoteModel.tenantId, ticket);
      setNotice(`${promoteModel.name} v${promoteModel.version} is approved for Prod — change ${ticket}.`);
      setPromoteModel(null);
      setSnowTicket('');
      await load();
    } catch (err) {
      setPromoteError(extractErrorMessage(err));
    } finally {
      setPromoting(false);
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
      // Refresh so the journey track flips to "Submitted to MRM" (devStatus
      // is derived server-side from the model's reviews).
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSubmittingReview(null);
    }
  };

  // Launch a notebook in COLLABORATIVE mode: the session is tagged with the
  // model's use case, so everyone launching from this row lands in the same
  // shared workspace instead of an isolated personal session.
  const launchNotebook = async (m: ModelVersion, sessionType: SessionType) => {
    const key = `${m.name}-${m.version}-${sessionType}`;
    setLaunchingNotebook(key);
    setNotice(null);
    try {
      const session = await notebooksApi.launch({
        sessionType,
        tenantId: m.tenantId,
        usecaseId: m.usecaseId ?? undefined,
      });
      if (session.presignedUrl) {
        window.open(session.presignedUrl, '_blank', 'noopener,noreferrer');
      }
      const studio = sessionType === 'emr_studio' ? 'EMR Studio' : 'SageMaker Studio';
      setNotice(
        m.usecaseId
          ? `${studio} opened in collaborative mode — workspace shared with everyone on ${m.usecaseId}.`
          : `${studio} session opened.`,
      );
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLaunchingNotebook(null);
    }
  };

  const columns: Column<ModelVersion>[] = [
    { key: 'name', header: 'Model', className: 'min-w-[260px]', headerClassName: 'min-w-[260px]', render: (m) => (
      <div className="flex items-center justify-between gap-2">
        <button onClick={() => void openCard(m)} className="text-left hover:text-brand-purple">
          <span className="block font-medium text-text-primary">{m.name}</span>
          {/* modelId is the inventory key — always visible under the name */}
          <span className="block font-mono text-xs text-text-muted">
            {m.modelId} · v{m.version}
            {m.framework ? ` · ${m.framework}` : ''}
          </span>
        </button>
        {(canRegister || (canLaunchNotebook && m.stage !== 'Archived')) && (
          <span className="ml-auto flex items-center gap-1">
            {canLaunchNotebook && m.stage !== 'Archived' && (
              <>
                <NotebookLaunchIcon
                  studio="emr_studio"
                  usecaseId={m.usecaseId}
                  loading={launchingNotebook === `${m.name}-${m.version}-emr_studio`}
                  onClick={() => void launchNotebook(m, 'emr_studio')}
                />
                <NotebookLaunchIcon
                  studio="sagemaker_studio"
                  usecaseId={m.usecaseId}
                  loading={launchingNotebook === `${m.name}-${m.version}-sagemaker_studio`}
                  onClick={() => void launchNotebook(m, 'sagemaker_studio')}
                />
              </>
            )}
            {canRegister && (
              <button
                onClick={() => openRegisterNewVersion(m)}
                title={`Register a new version of ${m.name} (${m.modelId})`}
                aria-label={`Register a new version of ${m.name}`}
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-bg-elevated bg-bg-elevated/40 text-text-secondary transition hover:border-brand-purple/50 hover:text-brand-purple"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </span>
        )}
      </div>
    ) },
    {
      key: 'usecase',
      header: 'Usecase',
      render: (m) =>
        m.usecaseId ? (
          <span className="whitespace-nowrap rounded-md bg-brand-purple/10 px-2 py-0.5 font-mono text-xs text-brand-purple">
            {m.usecaseId}
          </span>
        ) : (
          <span className="text-xs text-text-muted">—</span>
        ),
    },
    // Progress stretches to fill the remaining row width (w-full on an
    // auto-layout table gives this column all the slack space). The track is
    // also the action surface: chevron circles advance the journey (attach
    // results, submit to MRM) and — for admins — promote the governance
    // stage via the terminal circle (None → Staging → Production).
    {
      key: 'progress',
      header: 'Progress',
      align: 'center',
      className: 'w-full',
      headerClassName: 'w-full',
      render: (m) => {
        const canAct = canSubmitReview && m.stage !== 'Archived';
        // The terminal circle acts only once MRM has approved: "Prod ready"
        // → click → SNOW change ticket prompt → Production.
        const approvedForProd =
          m.devStatus === 'mrm_approved' && m.stage !== 'Production' && m.stage !== 'Archived';
        return (
          <ModelJourneyTrack
            devStatus={m.devStatus}
            submitting={submittingReview === `${m.name}-${m.version}`}
            onAttachResults={canAct ? () => openUpdate(m) : undefined}
            onSubmitToMrm={canAct ? () => void submitForReview(m) : undefined}
            stage={m.stage}
            onAdvanceStage={
              canTransition && approvedForProd
                ? () => {
                    setPromoteModel(m);
                    setSnowTicket('');
                    setPromoteError(null);
                  }
                : undefined
            }
          />
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Model Registry"
        description="Registered model versions and their governance stage."
        actions={canRegister && <Button onClick={openRegisterBlank}>Register model</Button>}
      />

      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">
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
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700">
              {formError}
            </div>
          )}
          <Field
            label="Model ID"
            required
            hint="The model's unique inventory key, shared by every version (e.g. MDL-0001)."
          >
            <Input
              value={regModelId}
              onChange={(e) => setRegModelId(e.target.value)}
              className="font-mono"
              placeholder="MDL-0001"
            />
          </Field>
          <Field label="Model name" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. fraud-detector" />
          </Field>
          <Field
            label="Version"
            hint="Free-form (e.g. 2, 1.0.3, 2024-Q1). Leave empty to use the next numeric version for this model name."
          >
            <Input
              value={regVersion}
              onChange={(e) => setRegVersion(e.target.value)}
              className="font-mono"
              placeholder="auto (next)"
            />
          </Field>
          <Field
            label="Usecase ID"
            required
            hint="Format UC-#### — the business use case this model serves; collaborative notebooks and MRM review are organized around it."
          >
            <Input
              value={usecaseId}
              onChange={(e) => setUsecaseId(e.target.value)}
              className="font-mono uppercase"
              maxLength={7}
              placeholder="UC-1111"
            />
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
        open={!!updateModel}
        title={updateModel ? `Attach results — ${updateModel.name} v${updateModel.version}` : 'Attach results'}
        onClose={() => setUpdateModel(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setUpdateModel(null)}>
              Cancel
            </Button>
            <Button loading={updSaving} onClick={() => void submitUpdate()}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {updError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700">
              {updError}
            </div>
          )}
          <p className="text-xs text-text-muted">
            Attach the trained model binary and run so MRM has something to review.
            Locked once a review is pending or approved.
          </p>
          {attachJobs.length > 0 && (
            <Field
              label="Prefill from a succeeded job (optional)"
              hint="Fills the run ID and artifact URI from the job's record — still editable below."
            >
              <Select
                value={attachJobPick}
                onChange={(e) => {
                  setAttachJobPick(e.target.value);
                  const j = attachJobs.find((x) => x.jobId === e.target.value);
                  if (j) {
                    setUpdArtifactUri(j.s3OutputPath ?? '');
                    setUpdRunId(j.experimentRunId ?? '');
                  }
                }}
              >
                <option value="">— pick a job —</option>
                {attachJobs.map((j) => (
                  <option key={j.jobId} value={j.jobId}>
                    {j.jobId} · {j.name}
                    {j.asOfDate ? ` · as of ${j.asOfDate}` : ''}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Artifact URI" required hint="s3:// path to the trained model output — must exist.">
            <Input
              value={updArtifactUri}
              onChange={(e) => setUpdArtifactUri(e.target.value)}
              className="font-mono"
              placeholder="s3://ml-platform-artifacts/<tenant>/models/…"
            />
          </Field>
          <Field label="Run ID (optional)" hint="The experiment run this binary came from (lineage for MRM).">
            <Input value={updRunId} onChange={(e) => setUpdRunId(e.target.value)} className="font-mono" />
          </Field>
          <Field
            label="Model schema (JSON)"
            hint='The model&apos;s I/O contract — shown to MRM, e.g. {"customer_id": "string", "prediction": "float"}.'
          >
            <Textarea
              rows={4}
              value={updModelSchema}
              onChange={(e) => setUpdModelSchema(e.target.value)}
              className="font-mono"
              placeholder='{"feature_name": "dtype", "prediction": "float"}'
            />
          </Field>
          <Field
            label="Results (JSON)"
            hint='Evaluation results submitted for review, e.g. {"auc": 0.94, "f1": 0.88}.'
          >
            <Textarea
              rows={3}
              value={updResults}
              onChange={(e) => setUpdResults(e.target.value)}
              className="font-mono"
              placeholder='{"auc": 0.94, "f1": 0.88}'
            />
          </Field>
          <Field
            label="Model documentation (S3 URI)"
            hint="s3:// path to the model documentation package — must exist."
          >
            <Input
              value={updDocumentationUri}
              onChange={(e) => setUpdDocumentationUri(e.target.value)}
              className="font-mono"
              placeholder="s3://ml-platform-artifacts/<tenant>/docs/…"
            />
          </Field>
          <Field label="Description">
            <Textarea rows={3} value={updDescription} onChange={(e) => setUpdDescription(e.target.value)} />
          </Field>
        </div>
      </Modal>

      <Modal
        open={!!promoteModel}
        title={promoteModel ? `Promote to Production — ${promoteModel.name} v${promoteModel.version}` : 'Promote to Production'}
        onClose={() => setPromoteModel(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPromoteModel(null)}>
              Cancel
            </Button>
            <Button loading={promoting} onClick={() => void submitPromote()}>
              Approve for Prod
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {promoteError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700">
              {promoteError}
            </div>
          )}
          <p className="text-xs text-text-muted">
            MRM has approved this version — it is ready for deployment. Production promotion is
            gated on change management: enter the ServiceNow change ticket that authorizes it.
          </p>
          <Field label="ServiceNow change ticket" required hint="Recorded on the model and in the audit trail.">
            <Input
              value={snowTicket}
              onChange={(e) => setSnowTicket(e.target.value)}
              className="font-mono uppercase"
              placeholder="CHG0012345"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={!!cardModel}
        title={cardModel ? `${cardModel.name} v${cardModel.version} — Model Card` : 'Model Card'}
        onClose={() => setCardModel(null)}
        size="xl"
        footer={
          canTransition && cardModel && cardModel.stage !== 'Archived' ? (
            <Button variant="danger" onClick={() => setArchiveTarget(cardModel)}>
              Archive version
            </Button>
          ) : undefined
        }
      >
        {cardLoading || !card ? (
          <div className="flex justify-center py-10">
            <LoadingSpinner label="Loading model card…" />
          </div>
        ) : (
          <div className="space-y-5 text-sm">
            <Section title="Overview">
              <KV label="Model ID" value={String(card.modelId)} mono />
              <KV label="Usecase" value={String(card.usecaseId ?? '—')} mono />
              <KV label="Stage" value={String(card.stage)} />
              <KV label="Framework" value={String(card.framework ?? '—')} />
              <KV label="Artifact URI" value={String(card.artifactUri ?? '—')} mono />
              <KV label="Documentation" value={String(card.documentationUri ?? '—')} mono />
              <KV label="SNOW change ticket" value={String(card.snowTicketId ?? '—')} mono />
              <KV label="Has explainer" value={card.explainability.hasExplainer ? 'Yes' : 'No'} />
            </Section>
            <Section title="Model schema">
              <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                {JSON.stringify(card.schema, null, 2)}
              </pre>
            </Section>
            {Object.keys(card.results ?? {}).length > 0 && (
              <Section title="Results">
                <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                  {JSON.stringify(card.results, null, 2)}
                </pre>
              </Section>
            )}
            {card.trainingRun ? (
              <Section title="Training run">
                <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                  {JSON.stringify(card.trainingRun, null, 2)}
                </pre>
              </Section>
            ) : null}
            <Section title="Governance">
              <pre className="overflow-auto rounded-lg bg-bg-dark p-3 font-mono text-xs text-text-secondary">
                {JSON.stringify(card.governance, null, 2)}
              </pre>
            </Section>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!archiveTarget}
        title={archiveTarget ? `Archive ${archiveTarget.name} v${archiveTarget.version}?` : 'Archive version'}
        description="Archived versions leave the active registry journey; the record and its review history remain for audit."
        confirmLabel="Archive"
        tone="danger"
        busy={archiving}
        onConfirm={() => void confirmArchive()}
        onCancel={() => setArchiveTarget(null)}
      />
    </div>
  );
}

/** Compact per-row launch button: opens the studio in collaborative mode
 * scoped to the model's use case. */
function NotebookLaunchIcon({
  studio,
  usecaseId,
  loading,
  onClick,
}: {
  studio: SessionType;
  usecaseId?: string | null;
  loading: boolean;
  onClick: () => void;
}) {
  const label = studio === 'emr_studio' ? 'EMR Studio' : 'SageMaker Studio';
  const title = usecaseId
    ? `Open ${label} — collaborative workspace for ${usecaseId}`
    : `Open ${label}`;
  return (
    <button
      onClick={onClick}
      disabled={loading}
      title={title}
      aria-label={title}
      className="flex h-7 w-7 items-center justify-center rounded-lg border border-bg-elevated bg-bg-elevated/40 text-text-secondary transition hover:border-brand-purple/50 hover:text-brand-purple disabled:cursor-not-allowed disabled:opacity-50"
    >
      {loading ? (
        <span className="h-3.5 w-3.5 animate-spin-slow rounded-full border-2 border-current/30 border-t-current" />
      ) : (
        // Official AWS product icons (same assets as the Notebooks page).
        <img
          src={studio === 'emr_studio' ? '/emr.svg' : '/SageMaker.svg'}
          alt=""
          className="h-[15px] w-[15px]"
        />
      )}
    </button>
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
