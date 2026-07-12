import { useEffect, useState } from 'react';
import { featureStoreApi } from '../../api/featureStore';
import { experimentsApi } from '../../api/experiments';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Card, Modal, Field, Input, Select, Textarea, InlineAlert, XIcon } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import { formatDateTime, formatRelative } from '../../lib/format';
import type { Experiment, FeatureDefinition, FeatureDtype, FeatureView, FeatureViewPreview } from '../../types/platform';

const DTYPES: FeatureDtype[] = ['string', 'int64', 'float', 'bool', 'timestamp'];

export function FeatureStorePage() {
  const { isDataScientist, isReadOnly } = useTenantContext();
  const canCreate = isDataScientist;
  const canMaterialize = !isReadOnly;

  const [views, setViews] = useState<FeatureView[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [entityColumn, setEntityColumn] = useState('');
  const [sourceTable, setSourceTable] = useState('');
  const [experimentId, setExperimentId] = useState('');
  const [features, setFeatures] = useState<FeatureDefinition[]>([{ name: '', dtype: 'string' }]);

  const [detailView, setDetailView] = useState<FeatureView | null>(null);
  const [preview, setPreview] = useState<FeatureViewPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [materializing, setMaterializing] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [v, e] = await Promise.all([
        featureStoreApi.list({ pageSize: 100 }),
        experimentsApi.list({ pageSize: 100 }),
      ]);
      setViews(v.items);
      setExperiments(e.items);
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

  const updateFeature = (idx: number, field: keyof FeatureDefinition, value: string) => {
    setFeatures((prev) => prev.map((f, i) => (i === idx ? { ...f, [field]: value } : f)));
  };
  const addFeature = () => setFeatures((prev) => [...prev, { name: '', dtype: 'string' }]);
  const removeFeature = (idx: number) => setFeatures((prev) => prev.filter((_, i) => i !== idx));

  const openCreate = () => {
    setName('');
    setDescription('');
    setEntityColumn('');
    setSourceTable('');
    setExperimentId('');
    setFeatures([{ name: '', dtype: 'string' }]);
    setFormError(null);
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    const cleanFeatures = features.filter((f) => f.name.trim());
    if (!name.trim() || !entityColumn.trim() || !sourceTable.trim() || cleanFeatures.length === 0) {
      setFormError('Name, entity column, source table, and at least one feature are required.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await featureStoreApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
        entityColumn: entityColumn.trim(),
        sourceTable: sourceTable.trim(),
        features: cleanFeatures,
        experimentId: experimentId || undefined,
      });
      setCreateOpen(false);
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const openDetail = async (view: FeatureView) => {
    setDetailView(view);
    setPreview(null);
    setDetailError(null);
    setPreviewLoading(true);
    try {
      const p = await featureStoreApi.preview(view.featureViewId);
      setPreview(p);
    } catch (err) {
      setDetailError(extractErrorMessage(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const materialize = async () => {
    if (!detailView) return;
    setMaterializing(true);
    setDetailError(null);
    try {
      const updated = await featureStoreApi.materialize(detailView.featureViewId);
      setDetailView(updated);
      const p = await featureStoreApi.preview(detailView.featureViewId);
      setPreview(p);
      await load();
    } catch (err) {
      setDetailError(extractErrorMessage(err));
    } finally {
      setMaterializing(false);
    }
  };

  const experimentName = (id: string | null) => experiments.find((e) => e.experimentId === id)?.name;

  const columns: Column<FeatureView>[] = [
    { key: 'name', header: 'Feature view', render: (v) => (
      <button onClick={() => void openDetail(v)} className="text-left font-medium text-text-primary hover:text-brand-purple">
        {v.name}
      </button>
    ) },
    { key: 'entityColumn', header: 'Entity', render: (v) => <span className="font-mono text-xs">{v.entityColumn}</span> },
    { key: 'features', header: 'Features', render: (v) => v.features.length },
    { key: 'sourceTable', header: 'Source', render: (v) => <span className="font-mono text-xs text-text-secondary">{v.sourceTable}</span> },
    { key: 'experiment', header: 'From experiment', render: (v) => experimentName(v.experimentId) ?? '—' },
    { key: 'lastMaterializedAt', header: 'Last materialized', render: (v) => formatRelative(v.lastMaterializedAt) },
  ];

  return (
    <div>
      <PageHeader
        title={
          <span className="inline-flex items-center gap-2">
            Feature Store
            <span className="rounded-full border border-brand-purple/40 bg-brand-purple/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-purple">
              Preview
            </span>
          </span>
        }
        description="Define a feature once, reuse it for both batch training and real-time lookups."
        actions={canCreate && <Button onClick={openCreate}>New feature view</Button>}
      />

      <InlineAlert tone="info" className="mb-6">
        <strong>Preview capability.</strong> This demonstrates the feature-store pattern (Feast-style): a feature
        view is defined once, and can be retrieved both as historical batch rows (offline) and as the latest
        single value per entity (online). There is no real feature-store integration yet — the batch and
        real-time data shown here is simulated.
      </InlineAlert>

      <DataTable
        columns={columns}
        rows={views}
        rowKey={(v) => v.featureViewId}
        loading={loading}
        error={error}
        onRetry={load}
        emptyTitle="No feature views yet"
        emptyDescription={canCreate ? 'Create one to see the batch + real-time preview.' : undefined}
      />

      <Modal
        open={createOpen}
        title="New feature view"
        onClose={() => setCreateOpen(false)}
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void submitCreate()}>
              Create
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
          <Field label="Name" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. customer_risk_features" />
          </Field>
          <Field label="Description">
            <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Entity column" required hint="The key features are looked up by, e.g. customer_id">
              <Input value={entityColumn} onChange={(e) => setEntityColumn(e.target.value)} className="font-mono" />
            </Field>
            <Field label="Source table" required hint="Where the batch values come from">
              <Input
                value={sourceTable}
                onChange={(e) => setSourceTable(e.target.value)}
                placeholder="PROD_DB.ML_FEATURES.CUSTOMER_FEATURES"
                className="font-mono"
              />
            </Field>
          </div>
          <Field label="Created from experiment" hint="Optional — ties this feature view back to the training work it came from.">
            <Select value={experimentId} onChange={(e) => setExperimentId(e.target.value)}>
              <option value="">(none)</option>
              {experiments.map((exp) => (
                <option key={exp.experimentId} value={exp.experimentId}>
                  {exp.name}
                </option>
              ))}
            </Select>
          </Field>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium text-text-secondary">Features</span>
              <Button variant="secondary" onClick={addFeature} className="!px-3 !py-1.5 !text-xs">
                + Add feature
              </Button>
            </div>
            <div className="space-y-2">
              {features.map((f, idx) => (
                <div key={idx} className="flex gap-2">
                  <Input
                    value={f.name}
                    onChange={(e) => updateFeature(idx, 'name', e.target.value)}
                    placeholder="feature name"
                    aria-label="Feature name"
                    className="font-mono"
                  />
                  <Select
                    value={f.dtype}
                    onChange={(e) => updateFeature(idx, 'dtype', e.target.value)}
                    aria-label="Feature data type"
                    className="!w-32"
                  >
                    {DTYPES.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </Select>
                  <Button
                    variant="ghost"
                    onClick={() => removeFeature(idx)}
                    className="!px-3"
                    aria-label="Remove feature"
                  >
                    <XIcon size={16} />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!detailView}
        title={detailView ? detailView.name : 'Feature view'}
        onClose={() => setDetailView(null)}
        size="xl"
      >
        {!detailView ? null : (
          <div className="space-y-5 text-sm">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KV label="Entity" value={detailView.entityColumn} mono />
              <KV label="Source" value={detailView.sourceTable} mono />
              <KV label="From experiment" value={experimentName(detailView.experimentId) ?? '—'} />
              <KV label="Last materialized" value={formatDateTime(detailView.lastMaterializedAt)} />
            </div>

            {detailError ? (
              <InlineAlert tone="error">{detailError}</InlineAlert>
            ) : previewLoading || !preview ? (
              <div className="flex justify-center py-10">
                <LoadingSpinner label="Loading preview…" />
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Card className="p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                      Batch (offline store)
                    </h4>
                    <span className="text-[11px] text-text-muted">{preview.offline.rows.length} rows</span>
                  </div>
                  <div className="max-h-64 overflow-auto rounded-lg border border-bg-elevated">
                    <table className="w-full border-collapse text-xs">
                      <thead className="sticky top-0 bg-bg-elevated/60">
                        <tr>
                          {preview.offline.columns.map((c) => (
                            <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-mono text-text-secondary">
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.offline.rows.map((row, i) => (
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
                </Card>

                <Card className="p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                      Real-time (online store)
                    </h4>
                    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                      {preview.online.latencyMs}ms
                    </span>
                  </div>
                  <p className="mb-3 font-mono text-xs text-text-secondary">
                    entity: <span className="text-text-primary">{preview.online.entityId}</span>
                  </p>
                  <div className="divide-y divide-bg-elevated/60 rounded-lg border border-bg-elevated">
                    {Object.entries(preview.online.values).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between px-3 py-2 text-xs">
                        <span className="font-mono text-text-secondary">{k}</span>
                        <span className="font-mono text-text-primary">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-[11px] text-text-muted">
                    As of {formatDateTime(preview.online.asOf)}
                  </p>
                  {canMaterialize && (
                    <Button
                      variant="secondary"
                      loading={materializing}
                      onClick={() => void materialize()}
                      className="mt-4 w-full"
                    >
                      Materialize now
                    </Button>
                  )}
                </Card>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-bg-elevated bg-bg-card p-3">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className={`mt-1 truncate text-text-primary ${mono ? 'font-mono text-xs' : 'text-sm'}`}>{value}</p>
    </div>
  );
}
