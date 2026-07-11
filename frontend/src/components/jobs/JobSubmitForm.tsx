import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { jobsApi, type SubmitJobPayload } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { useSnowflake } from '../../hooks/useSnowflake';
import { useTenantContext } from '../../hooks/useTenantContext';
import { deriveOutputPath, localToday, swapDatedPrefix } from '../../lib/jobs';
import { Button, Card, Field, Input, InlineAlert } from '../shared/ui';
import { SnowflakeConnectBanner } from '../snowflake/SnowflakeConnectBanner';
import { SnowflakeTableBrowser, type SnowflakeSelection } from '../snowflake/SnowflakeTableBrowser';
import { S3Browser } from '../s3/S3Browser';
import type { ComputeType, Framework, SnowflakePreview, TrainingJob } from '../../types/platform';

// Four steps: everything a run NEEDS is on the happy path; resources and
// hyperparameters have sensible defaults and live in the Script step's
// collapsible "Advanced" section.
const STEPS = ['Setup', 'Data source', 'Script', 'Review'];

const COMPUTE_OPTIONS: { value: ComputeType; label: string; description: string }[] = [
  { value: 'emr_serverless', label: 'EMR Serverless', description: 'Spark-based distributed training, auto-scaling compute.' },
  { value: 'sagemaker', label: 'SageMaker Training', description: 'Managed training jobs with built-in framework containers.' },
];

const FRAMEWORK_OPTIONS: { value: Framework; label: string }[] = [
  { value: 'pytorch', label: 'PyTorch' },
  { value: 'tensorflow', label: 'TensorFlow' },
  { value: 'sklearn', label: 'scikit-learn' },
  { value: 'xgboost', label: 'XGBoost' },
];

interface HyperparamRow {
  key: string;
  value: string;
}

export function JobSubmitForm() {
  const navigate = useNavigate();
  const snowflake = useSnowflake();
  const { tenantId } = useTenantContext();
  // "Clone" from the Jobs page: the wizard opens pre-filled with an existing
  // job's configuration, landing on Review — tweak-and-resubmit in one click.
  const clone = (useLocation().state as { cloneFrom?: TrainingJob } | null)?.cloneFrom;
  const [step, setStep] = useState(clone ? STEPS.length - 1 : 0);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [name, setName] = useState(clone?.name ?? '');
  const [computeType, setComputeType] = useState<ComputeType>(clone?.computeType ?? 'emr_serverless');
  const [framework, setFramework] = useState<Framework>(clone?.framework ?? 'pytorch');
  // Data snapshot date: clone keeps the original (reproducibility); change it
  // to backfill a different day. New jobs default to the LOCAL calendar day.
  const [asOfDate, setAsOfDate] = useState(clone?.asOfDate ?? localToday());

  const [dataTab, setDataTab] = useState<'snowflake' | 's3'>(
    clone ? (clone.snowflakeDatabase ? 'snowflake' : 's3') : 'snowflake',
  );
  const [snowflakeSelection, setSnowflakeSelection] = useState<SnowflakeSelection | null>(
    clone?.snowflakeDatabase
      ? { database: clone.snowflakeDatabase, schema: clone.snowflakeSchema ?? '', table: clone.snowflakeTable ?? '' }
      : null,
  );
  const [snowflakePreview, setSnowflakePreview] = useState<SnowflakePreview | null>(null);
  const [useCustomSql, setUseCustomSql] = useState(!!clone?.snowflakeSql);
  const [customSql, setCustomSql] = useState(clone?.snowflakeSql ?? '');
  const [s3InputPath, setS3InputPath] = useState(clone?.s3InputPath ?? '');

  const [entryPointScript, setEntryPointScript] = useState(clone?.entryPointScript ?? '');
  const [s3OutputPath, setS3OutputPath] = useState(clone?.s3OutputPath ?? '');
  // Whether the output path is still ours to keep date-consistent. A cloned
  // path that follows the dated-prefix convention stays LIVE (changing the
  // as-of date must move the prefix, or a backfill would overwrite the
  // original day's artifacts); only a custom cloned path — or a manual edit —
  // freezes it.
  const cloneHasDatedPath = !!(clone?.s3OutputPath && clone.asOfDate && clone.s3OutputPath.endsWith(`/${clone.asOfDate}/`));
  const [outputEdited, setOutputEdited] = useState(!!clone?.s3OutputPath && !cloneHasDatedPath);

  const [instanceType, setInstanceType] = useState(clone?.instanceType || 'ml.m5.xlarge');
  const [instanceCount, setInstanceCount] = useState(clone?.instanceCount ?? 1);
  const [volumeSizeGb, setVolumeSizeGb] = useState(clone?.volumeSizeGb ?? 30);
  const [driverMemory, setDriverMemory] = useState(clone?.driverMemory ?? '4g');
  const [executorMemory, setExecutorMemory] = useState(clone?.executorMemory ?? '4g');
  const [maxExecutors, setMaxExecutors] = useState(clone?.maxExecutors ?? 4);

  const [hyperparams, setHyperparams] = useState<HyperparamRow[]>(
    clone && Object.keys(clone.hyperparameters ?? {}).length
      ? Object.entries(clone.hyperparameters).map(([key, value]) => ({ key, value: String(value) }))
      : [
          { key: 'learning_rate', value: '0.001' },
          { key: 'epochs', value: '10' },
        ],
  );

  // Keep the output path date-consistent (convention: each day's run lands in
  // its own prefix instead of overwriting). Stops as soon as the user takes
  // over the field. Cloned conventional paths keep their original BASE and
  // only the date segment moves; fresh jobs derive fully from the name.
  useEffect(() => {
    if (outputEdited) return;
    if (cloneHasDatedPath) {
      setS3OutputPath(swapDatedPrefix(clone?.s3OutputPath, clone?.asOfDate, asOfDate));
      return;
    }
    setS3OutputPath(deriveOutputPath(name, framework, tenantId, asOfDate));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, framework, tenantId, asOfDate, outputEdited]);

  const updateHyperparam = (idx: number, field: 'key' | 'value', value: string) => {
    setHyperparams((prev) => prev.map((row, i) => (i === idx ? { ...row, [field]: value } : row)));
  };
  const addHyperparam = () => setHyperparams((prev) => [...prev, { key: '', value: '' }]);
  const removeHyperparam = (idx: number) => setHyperparams((prev) => prev.filter((_, i) => i !== idx));

  const canGoNext = (() => {
    switch (step) {
      case 0:
        return !!computeType && !!framework;
      case 1:
        return dataTab === 's3' ? !!s3InputPath : !!snowflakeSelection;
      case 2:
        return !!entryPointScript && !!s3OutputPath;
      default:
        return true;
    }
  })();

  const expiresSoon =
    snowflake.status?.expiresAt &&
    snowflake.minutesRemaining !== null &&
    snowflake.minutesRemaining < 30;

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const hyperparameters: Record<string, string> = {};
      hyperparams.forEach((row) => {
        if (row.key.trim()) hyperparameters[row.key.trim()] = row.value;
      });

      const payload: SubmitJobPayload = {
        name: name.trim() || `${framework}-job-${Date.now()}`,
        computeType,
        framework,
        asOfDate: asOfDate || undefined,
        entryPointScript,
        s3InputPath: dataTab === 's3' ? s3InputPath : '',
        s3OutputPath,
        instanceType,
        instanceCount,
        volumeSizeGb,
        hyperparameters,
      };

      if (computeType === 'emr_serverless') {
        payload.driverMemory = driverMemory;
        payload.executorMemory = executorMemory;
        payload.maxExecutors = maxExecutors;
      }

      if (dataTab === 'snowflake' && snowflakeSelection) {
        payload.snowflakeDatabase = snowflakeSelection.database;
        payload.snowflakeSchema = snowflakeSelection.schema;
        payload.snowflakeTable = snowflakeSelection.table;
        payload.snowflakeWarehouse = 'COMPUTE_WH';
        if (useCustomSql && customSql.trim()) {
          payload.snowflakeSql = customSql.trim();
        }
      }

      const job = await jobsApi.submit(payload);
      navigate('/workspace/jobs', { state: { submittedJobId: job.jobId } });
    } catch (err) {
      setSubmitError(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      {/* Step indicator */}
      <div className="mb-8 flex items-center gap-2 overflow-x-auto pb-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex flex-shrink-0 items-center gap-2">
            <button
              onClick={() => i < step && setStep(i)}
              disabled={i > step}
              className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition ${
                i === step
                  ? 'bg-brand-purple text-white'
                  : i < step
                    ? 'bg-brand-purple/20 text-brand-purple'
                    : 'bg-bg-elevated text-text-muted'
              }`}
            >
              {i + 1}
            </button>
            <span className={`text-xs font-medium ${i === step ? 'text-text-primary' : 'text-text-muted'}`}>
              {label}
            </span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-bg-elevated" />}
          </div>
        ))}
      </div>

      <Card className="p-6">
        {step === 0 && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Job name" hint="Optional — auto-generated when empty. Also drives the default output path.">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. fraud-model-v3-retrain" />
              </Field>
              <Field
                label="As-of date"
                hint="The data snapshot date this run trains on — your script receives it as AS_OF_DATE. Change it to backfill a different day."
              >
                <Input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
              </Field>
            </div>
            <div>
              <h3 className="mb-3 text-sm font-semibold text-text-primary">Compute type</h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {COMPUTE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setComputeType(opt.value)}
                    className={`rounded-xl border p-5 text-left transition ${
                      computeType === opt.value
                        ? 'border-brand-purple bg-brand-purple/10'
                        : 'border-bg-elevated hover:border-brand-purple/40'
                    }`}
                  >
                    <p className="text-sm font-semibold text-text-primary">{opt.label}</p>
                    <p className="mt-1 text-xs text-text-secondary">{opt.description}</p>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-3 text-sm font-semibold text-text-primary">Framework</h3>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {FRAMEWORK_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setFramework(opt.value)}
                    className={`rounded-xl border p-4 text-center transition ${
                      framework === opt.value
                        ? 'border-brand-purple bg-brand-purple/10 text-brand-purple'
                        : 'border-bg-elevated text-text-secondary hover:border-brand-purple/40'
                    }`}
                  >
                    <p className="text-sm font-semibold">{opt.label}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div>
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Data source</h3>
            <div className="mb-4 flex gap-2">
              <button
                onClick={() => setDataTab('snowflake')}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  dataTab === 'snowflake' ? 'bg-brand-purple text-white' : 'bg-bg-elevated text-text-secondary'
                }`}
              >
                Snowflake
              </button>
              <button
                onClick={() => setDataTab('s3')}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  dataTab === 's3' ? 'bg-brand-purple text-white' : 'bg-bg-elevated text-text-secondary'
                }`}
              >
                S3
              </button>
              <button
                disabled
                title="Coming soon — pull training data straight from a registered Feature View instead of a raw table/path."
                className="flex cursor-not-allowed items-center gap-2 rounded-lg bg-bg-elevated/50 px-4 py-2 text-sm font-medium text-text-muted"
              >
                Feature Store
                <span className="rounded-full border border-brand-purple/40 bg-brand-purple/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-purple">
                  Soon
                </span>
              </button>
            </div>

            {dataTab === 'snowflake' ? (
              <div className="space-y-4">
                <SnowflakeConnectBanner snowflake={snowflake} />
                {snowflake.state === 'connected' && (
                  <>
                    <SnowflakeTableBrowser
                      selected={snowflakeSelection}
                      onSelectTable={(sel, preview) => {
                        setSnowflakeSelection(sel);
                        setSnowflakePreview(preview);
                      }}
                    />
                    {snowflakeSelection && (
                      <div className="rounded-lg border border-bg-elevated bg-bg-dark px-4 py-3 text-sm">
                        <p className="font-mono text-xs text-text-secondary">
                          {snowflakeSelection.database}.{snowflakeSelection.schema}.{snowflakeSelection.table}
                        </p>
                        <label className="mt-3 flex items-center gap-2 text-xs text-text-secondary">
                          <input
                            type="checkbox"
                            checked={useCustomSql}
                            onChange={(e) => setUseCustomSql(e.target.checked)}
                          />
                          Use a custom SQL query instead of a full table read
                        </label>
                        {useCustomSql && (
                          <textarea
                            value={customSql}
                            onChange={(e) => setCustomSql(e.target.value)}
                            rows={4}
                            placeholder={`SELECT * FROM ${snowflakeSelection.table} WHERE ...`}
                            className="mt-2 w-full rounded-lg border border-bg-elevated bg-bg-card px-3 py-2 font-mono text-xs text-text-primary focus:border-brand-purple focus:outline-none"
                          />
                        )}
                        {snowflakePreview && (
                          <div className="mt-3 max-h-48 overflow-auto rounded-lg border border-bg-elevated">
                            <table className="w-full border-collapse text-xs">
                              <thead className="bg-bg-elevated/60">
                                <tr>
                                  {snowflakePreview.columns.map((c) => (
                                    <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-mono text-text-secondary">
                                      {c}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {snowflakePreview.rows.slice(0, 10).map((row, i) => (
                                  <tr key={i} className="border-t border-bg-elevated/60">
                                    {row.map((cell, j) => (
                                      <td key={j} className="whitespace-nowrap px-2 py-1 font-mono text-text-primary">
                                        {String(cell)}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                <S3Browser selectedPath={s3InputPath || null} onSelectPath={setS3InputPath} />
                <Field label="S3 input path" required hint="Auto-filled by the browser above, or type/edit a path directly.">
                  <Input
                    value={s3InputPath}
                    onChange={(e) => setS3InputPath(e.target.value)}
                    placeholder="s3://ml-platform-artifacts/tenant/data/input/"
                    className="font-mono"
                  />
                </Field>
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <h3 className="mb-1 text-sm font-semibold text-text-primary">Script</h3>
            <Field label="Entry point script (S3 path)" required>
              <Input
                value={entryPointScript}
                onChange={(e) => setEntryPointScript(e.target.value)}
                placeholder="s3://ml-platform-artifacts/tenant/scripts/train.py"
                className="font-mono"
              />
            </Field>
            <Field
              label="Output S3 path"
              required
              hint="Defaulted from the job name — this is what “Add run” later attaches to a model."
            >
              <Input
                value={s3OutputPath}
                onChange={(e) => {
                  setOutputEdited(true);
                  setS3OutputPath(e.target.value);
                }}
                placeholder="s3://ml-platform-artifacts/tenant/models/run-1/"
                className="font-mono"
              />
            </Field>

            {/* Resources + hyperparameters ship with sensible defaults — they
                live behind "Advanced" so the happy path stays 3 clicks. */}
            <div className="rounded-xl border border-bg-elevated">
              <button
                type="button"
                onClick={() => setAdvancedOpen((o) => !o)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary transition hover:text-text-primary"
              >
                <span>
                  Advanced — resources & hyperparameters
                  <span className="ml-2 text-xs text-text-muted">
                    {instanceType} × {instanceCount} · {hyperparams.filter((h) => h.key).length} hyperparameter(s)
                  </span>
                </span>
                <span className="text-xs">{advancedOpen ? '▲' : '▼'}</span>
              </button>
              {advancedOpen && (
                <div className="space-y-4 border-t border-bg-elevated p-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <Field label="Instance type">
                      <Input value={instanceType} onChange={(e) => setInstanceType(e.target.value)} />
                    </Field>
                    <Field label="Instance count">
                      <Input type="number" min={1} value={instanceCount} onChange={(e) => setInstanceCount(Number(e.target.value) || 1)} />
                    </Field>
                    <Field label="Volume size (GB)">
                      <Input type="number" min={10} value={volumeSizeGb} onChange={(e) => setVolumeSizeGb(Number(e.target.value) || 10)} />
                    </Field>
                  </div>
                  {computeType === 'emr_serverless' && (
                    <div className="grid grid-cols-1 gap-4 border-t border-bg-elevated pt-4 sm:grid-cols-3">
                      <Field label="Driver memory">
                        <Input value={driverMemory} onChange={(e) => setDriverMemory(e.target.value)} placeholder="4g" />
                      </Field>
                      <Field label="Executor memory">
                        <Input value={executorMemory} onChange={(e) => setExecutorMemory(e.target.value)} placeholder="4g" />
                      </Field>
                      <Field label="Max executors">
                        <Input type="number" min={1} value={maxExecutors} onChange={(e) => setMaxExecutors(Number(e.target.value) || 1)} />
                      </Field>
                    </div>
                  )}
                  <div className="border-t border-bg-elevated pt-4">
                    <div className="mb-3 flex items-center justify-between">
                      <p className="text-sm font-medium text-text-secondary">Hyperparameters</p>
                      <Button variant="secondary" onClick={addHyperparam} className="!px-3 !py-1.5 !text-xs">
                        + Add row
                      </Button>
                    </div>
                    <div className="space-y-2">
                      {hyperparams.map((row, idx) => (
                        <div key={idx} className="flex gap-2">
                          <Input
                            value={row.key}
                            onChange={(e) => updateHyperparam(idx, 'key', e.target.value)}
                            placeholder="key"
                            className="font-mono"
                          />
                          <Input
                            value={row.value}
                            onChange={(e) => updateHyperparam(idx, 'value', e.target.value)}
                            placeholder="value"
                            className="font-mono"
                          />
                          <Button variant="ghost" onClick={() => removeHyperparam(idx)} className="!px-3">
                            ✕
                          </Button>
                        </div>
                      ))}
                      {hyperparams.length === 0 && (
                        <p className="text-sm text-text-muted">No hyperparameters set.</p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5">
            <h3 className="text-sm font-semibold text-text-primary">Review and submit</h3>

            {clone && (
              <InlineAlert tone="info">
                Cloned from <span className="font-mono">{clone.jobId}</span> — everything is pre-filled;
                use Back to tweak any step, then submit.
              </InlineAlert>
            )}

            {expiresSoon && (
              <InlineAlert tone="warn">
                Your Snowflake session expires in {snowflake.minutesRemaining} minutes — it may expire before
                this job finishes reading its input data. Consider reconnecting before submitting.
              </InlineAlert>
            )}

            {submitError && <InlineAlert tone="error">{submitError}</InlineAlert>}

            <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
              <Row label="Job name" value={name || '(auto-generated)'} />
              <Row label="As-of date" value={asOfDate || '(today)'} />
              <Row label="Compute type" value={computeType === 'emr_serverless' ? 'EMR Serverless' : 'SageMaker Training'} />
              <Row label="Framework" value={framework} />
              <Row
                label="Data source"
                value={
                  dataTab === 'snowflake' && snowflakeSelection
                    ? `Snowflake: ${snowflakeSelection.database}.${snowflakeSelection.schema}.${snowflakeSelection.table}${
                        useCustomSql ? ' (custom SQL)' : ''
                      }`
                    : `S3: ${s3InputPath}`
                }
              />
              <Row label="Entry point" value={entryPointScript} mono />
              <Row label="Output path" value={s3OutputPath} mono />
              <Row label="Instance" value={`${instanceType} × ${instanceCount}, ${volumeSizeGb}GB volume`} />
              <Row label="Hyperparameters" value={hyperparams.filter((h) => h.key).map((h) => `${h.key}=${h.value}`).join(', ') || '—'} />
            </dl>

            <Button className="w-full" loading={submitting} onClick={() => void submit()}>
              Submit training job
            </Button>
          </div>
        )}
      </Card>

      <div className="mt-6 flex justify-between">
        <Button variant="secondary" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
          Back
        </Button>
        {step < STEPS.length - 1 && (
          <Button onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))} disabled={!canGoNext}>
            Next
          </Button>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className={`mt-1 text-text-primary ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
    </div>
  );
}
