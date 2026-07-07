import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { tenantsApi } from '../../api/tenants';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Button, Modal, Field, Input } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { formatDate } from '../../lib/format';
import type { Tenant, Framework } from '../../types/platform';

const ALL_FRAMEWORKS: Framework[] = ['pytorch', 'tensorflow', 'sklearn', 'xgboost'];

export function TenantsPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [tenantId, setTenantId] = useState('');
  const [name, setName] = useState('');
  const [quota, setQuota] = useState(1000);
  const [frameworks, setFrameworks] = useState<Framework[]>(ALL_FRAMEWORKS);

  const [pendingSuspend, setPendingSuspend] = useState<Tenant | null>(null);
  const [suspending, setSuspending] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await tenantsApi.list({ pageSize: 100 });
      setTenants(res.items);
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

  const toggleFramework = (fw: Framework) => {
    setFrameworks((prev) => (prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw]));
  };

  const submitCreate = async () => {
    const id = tenantId.trim().toLowerCase();
    if (!id || !name.trim()) {
      setFormError('Tenant ID and name are required.');
      return;
    }
    if (!/^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$/.test(id)) {
      setFormError('Tenant ID must be a lowercase slug (letters, digits, hyphens; 3–50 chars).');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await tenantsApi.create({
        tenantId: id,
        name: name.trim(),
        computeQuotaVcpuHours: quota,
        allowedFrameworks: frameworks,
      });
      setModalOpen(false);
      setTenantId('');
      setName('');
      setQuota(1000);
      setFrameworks(ALL_FRAMEWORKS);
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const reactivate = async (t: Tenant) => {
    try {
      await tenantsApi.reactivate(t.tenantId);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  };

  const confirmSuspend = async () => {
    if (!pendingSuspend) return;
    setSuspending(true);
    try {
      await tenantsApi.suspend(pendingSuspend.tenantId);
      setPendingSuspend(null);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSuspending(false);
    }
  };

  const columns: Column<Tenant>[] = [
    { key: 'name', header: 'Tenant', render: (t) => (
      <div>
        <p className="font-medium text-text-primary">{t.name}</p>
        <p className="font-mono text-xs text-text-muted">{t.tenantId}</p>
      </div>
    ) },
    { key: 'status', header: 'Status', render: (t) => <StatusBadge status={t.status} /> },
    { key: 'quota', header: 'Compute Quota', render: (t) => `${t.computeQuotaVcpuHours.toLocaleString()} vCPU-hrs` },
    { key: 'frameworks', header: 'Frameworks', render: (t) => (t.allowedFrameworks ?? []).join(', ') },
    { key: 'createdAt', header: 'Created', render: (t) => formatDate(t.createdAt) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (t) => (
        <Button
          variant={t.status === 'active' ? 'danger' : 'secondary'}
          onClick={(e) => {
            e.stopPropagation();
            if (t.status === 'active') {
              setPendingSuspend(t);
            } else {
              void reactivate(t);
            }
          }}
          className="!px-3 !py-1.5 !text-xs"
        >
          {t.status === 'active' ? 'Suspend' : 'Reactivate'}
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Tenants"
        description="Onboard and manage every business unit on the platform."
        actions={<Button onClick={() => setModalOpen(true)}>New tenant</Button>}
      />

      <DataTable
        columns={columns}
        rows={tenants}
        rowKey={(t) => t.tenantId}
        loading={loading}
        error={error}
        onRetry={load}
        onRowClick={(t) => navigate(`/admin/tenants/${t.tenantId}`)}
        emptyTitle="No tenants yet"
        emptyDescription="Create your first tenant to get started."
      />

      <Modal
        open={modalOpen}
        title="Create tenant"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void submitCreate()}>
              Create tenant
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
          <Field
            label="Tenant ID"
            required
            hint="The key slug used in AD group names (myapp-<tenantId>-<role>) and S3 prefixes. Cannot be changed later."
          >
            <Input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className="font-mono"
              placeholder="e.g. wealth-management"
            />
          </Field>
          <Field label="Tenant name" required hint="Display name this tenant ID maps to — editable later.">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Wealth Management" />
          </Field>
          <Field label="Compute quota (vCPU-hours / month)" required>
            <Input
              type="number"
              min={0}
              value={quota}
              onChange={(e) => setQuota(Number(e.target.value) || 0)}
            />
          </Field>
          <Field label="Allowed frameworks">
            <div className="flex flex-wrap gap-2">
              {ALL_FRAMEWORKS.map((fw) => (
                <button
                  key={fw}
                  type="button"
                  onClick={() => toggleFramework(fw)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium capitalize transition ${
                    frameworks.includes(fw)
                      ? 'border-brand-purple bg-brand-purple/15 text-brand-purple'
                      : 'border-bg-elevated text-text-secondary hover:border-brand-purple/40'
                  }`}
                >
                  {fw}
                </button>
              ))}
            </div>
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!pendingSuspend}
        title="Suspend tenant?"
        description={
          <>
            Every user in <span className="font-medium text-text-primary">{pendingSuspend?.name}</span> will
            immediately lose access to the platform. You can reactivate the tenant at any time.
          </>
        }
        tone="danger"
        confirmLabel="Suspend tenant"
        busy={suspending}
        onConfirm={() => void confirmSuspend()}
        onCancel={() => setPendingSuspend(null)}
      />
    </div>
  );
}
