import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { experimentsApi } from '../../api/experiments';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Button, Modal, Field, Input, Textarea } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { formatDate } from '../../lib/format';
import type { Experiment } from '../../types/platform';

export function ExperimentsPage() {
  const navigate = useNavigate();
  const { isReadOnly } = useTenantContext();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await experimentsApi.list({ pageSize: 100 });
      setExperiments(res.items);
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

  const submitCreate = async () => {
    if (!name.trim()) {
      setFormError('Experiment name is required.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await experimentsApi.create({ name: name.trim(), description: description.trim() });
      setModalOpen(false);
      setName('');
      setDescription('');
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const columns: Column<Experiment>[] = [
    { key: 'name', header: 'Experiment', render: (e) => (
      <div>
        <p className="font-medium text-text-primary">{e.name}</p>
        {e.description && <p className="text-xs text-text-muted">{e.description}</p>}
      </div>
    ) },
    { key: 'runCount', header: 'Runs', render: (e) => e.runCount ?? '—' },
    { key: 'createdBy', header: 'Created by', render: (e) => e.createdBy },
    { key: 'createdAt', header: 'Created', render: (e) => formatDate(e.createdAt) },
  ];

  return (
    <div>
      <PageHeader
        title="Experiments"
        description="Track and compare training runs across your models."
        actions={!isReadOnly && <Button onClick={() => setModalOpen(true)}>New experiment</Button>}
      />

      <DataTable
        columns={columns}
        rows={experiments}
        rowKey={(e) => e.experimentId}
        loading={loading}
        error={error}
        onRetry={load}
        onRowClick={(e) => navigate(`/workspace/experiments/${e.experimentId}`)}
        emptyTitle="No experiments yet"
        emptyDescription="Create an experiment to start tracking runs."
      />

      <Modal
        open={modalOpen}
        title="New experiment"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
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
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {formError}
            </div>
          )}
          <Field label="Name" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Credit Risk Scoring v2" />
          </Field>
          <Field label="Description">
            <Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
