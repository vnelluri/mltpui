import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { jobsApi, type SubmitJobPayload } from '../../api/jobs';
import { extractErrorMessage } from '../../api/client';
import { useSnowflake } from '../../hooks/useSnowflake';
import { Button, Card, Field, Input, InlineAlert } from '../shared/ui';
import { SnowflakeConnectBanner } from '../snowflake/SnowflakeConnectBanner';
import { SnowflakeTableBrowser, type SnowflakeSelection } from '../snowflake/SnowflakeTableBrowser';
import { S3Browser } from '../s3/S3Browser';
import type { ComputeType, Framework, SnowflakePreview } from '../../types/platform';

const STEPS = ['Compute', 'Framework', 'Data source', 'Script', 'Resources', 'Hyperparameters', 'Review'];

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
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [computeType, setComputeType] = useState<ComputeType>('emr_serverless');
  const [framework, setFramework] = useState<Framework>('pytorch');

  const [dataTab, setDataTab] = useState<'snowflake' | 's3'>('snowflake');
  const [snowflakeSelection, setSnowflakeSelection] = useState<SnowflakeSelection | null>(null);
  const [snowflakePreview, setSnowflakePreview] = useState<SnowflakePreview | null>(null);
  const [useCustomSql, setUseCustomSql] = useState(false);
  const [customSql, setCustomSql] = useState('');
  const [s3InputPath, setS3InputPath] = useState('');

  const [entryPointScript, setEntryPointScript] = useState('');
  const [s3OutputPath, setS3OutputPath] = useState('');

  const [instanceType, setInstanceType] = useState('ml.m5.xlarge');
  const [instanceCount, setInstanceCount] = useState(1);
  const [volumeSizeGb, setVolumeSizeGb] = useState(30);
  const [driverMemory, setDriverMemory] = useState('4g');
  const [executorMemory, setExecutorMemory] = useState('4g');
  const [maxExecutors, setMaxExecutors] = useState(4);

  const [hyperparams, setHyperparams] = useState<HyperparamRow[]>([
    { key: 'learning_rate', value: '0.001' },
    { key: 'epochs', value: '10' },
  ]);

  const updateHyperparam = (idx: number, field: 'key' | 'value', value: string) => {
    setHyperparams((prev) => prev.map((row, i) => (i === idx ? { ...row, [field]: value } : row)));
  };
  const addHyperparam = () => setHyperparams((prev) => [...prev, { key: '', value: '' }]);
  const removeHyperparam = (idx: number) => setHyperparams((prev) => prev.filter((_, i) => i !== idx));

  const canGoNext = (() => {
    switch (step) {
      case 0:
        return !!computeType;
      case 1:
        return !!framework;
      case 2:
        return dataTab === 's3' ? !!s3InputPath : !!snowflakeSelection;
      case 3:
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
                  ? 'bg-brand-purple text-brand-valhalla'
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
          <div>
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Choose a compute type</h3>
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
        )}

        {step === 1 && (
          <div>
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Choose a framework</h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {FRAMEWORK_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setFramework(opt.value)}
                  className={`rounded-xl border p-5 text-center transition ${
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
        )}

        {step === 2 && (
          <div>
            <h3 className="mb-4 text-sm font-semibold text-text-primary">Data source</h3>
            <div className="mb-4 flex gap-2">
              <button
                onClick={() => setDataTab('snowflake')}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  dataTab === 'snowflake' ? 'bg-brand-purple text-brand-valhalla' : 'bg-bg-elevated text-text-secondary'
                }`}
              >
                Snowflake
              </button>
              <button
                onClick={() => setDataTab('s3')}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  dataTab === 's3' ? 'bg-brand-purple text-brand-valhalla' : 'bg-bg-elevated text-text-secondary'
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

        {step === 3 && (
          <div className="space-y-4">
            <h3 className="mb-1 text-sm font-semibold text-text-primary">Script</h3>
            <Field label="Job name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. fraud-model-v3-retrain" />
            </Field>
            <Field label="Entry point script (S3 path)" required>
              <Input
                value={entryPointScript}
                onChange={(e) => setEntryPointScript(e.target.value)}
                placeholder="s3://ml-platform-artifacts/tenant/scripts/train.py"
                className="font-mono"
              />
            </Field>
            <Field label="Output S3 path" required>
              <Input
                value={s3OutputPath}
                onChange={(e) => setS3OutputPath(e.target.value)}
                placeholder="s3://ml-platform-artifacts/tenant/models/run-1/"
                className="font-mono"
              />
            </Field>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <h3 className="mb-1 text-sm font-semibold text-text-primary">Resources</h3>
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
          </div>
        )}

        {step === 5 && (
          <div>
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Hyperparameters</h3>
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
        )}

        {step === 6 && (
          <div className="space-y-5">
            <h3 className="text-sm font-semibold text-text-primary">Review and submit</h3>

            {expiresSoon && (
              <InlineAlert tone="warn">
                Your Snowflake session expires in {snowflake.minutesRemaining} minutes — it may expire before
                this job finishes reading its input data. Consider reconnecting before submitting.
              </InlineAlert>
            )}

            {submitError && <InlineAlert tone="error">{submitError}</InlineAlert>}

            <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
              <Row label="Job name" value={name || '(auto-generated)'} />
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
