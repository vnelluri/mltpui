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

  const [pendingDelete, setPendingDelete] = useState<Tenant | null>(null);
  const [deleteData, setDeleteData] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);

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
    // The exact slug rule (charset + length, tied to IAM/group-name limits)
    // is enforced by the backend; surface its 400 rather than duplicating the
    // regex here, where it would silently drift from the server's.
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

  const retryProvisioning = async (t: Tenant) => {
    setRetryingId(t.tenantId);
    try {
      await tenantsApi.retryProvisioning(t.tenantId);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setRetryingId(null);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await tenantsApi.remove(pendingDelete.tenantId, deleteData);
      setPendingDelete(null);
      setDeleteData(false);
      await load();
    } catch (err) {
      // A partial teardown returns 502 with the resume instruction — surface
      // it and keep the dialog open so "Delete" retries.
      setError(extractErrorMessage(err));
      setPendingDelete(null);
      setDeleteData(false);
      await load();
    } finally {
      setDeleting(false);
    }
  };

  const columns: Column<Tenant>[] = [
    { key: 'name', header: 'Tenant', render: (t) => (
      <div>
        <p className="font-medium text-text-primary">{t.name}</p>
        <p className="font-mono text-xs text-text-muted">{t.tenantId}</p>
      </div>
    ) },
    { key: 'status', header: 'Status', render: (t) => (
      <div className="flex items-center gap-1.5">
        <StatusBadge status={t.status} />
        {t.status !== 'deleted' && t.provisioningStatus && t.provisioningStatus !== 'active' && (
          <span title={t.provisioningError ?? undefined}>
            <StatusBadge
              status={t.provisioningStatus}
              label={`provisioning ${t.provisioningStatus}`}
            />
          </span>
        )}
      </div>
    ) },
    { key: 'quota', header: 'Compute Quota', render: (t) => `${t.computeQuotaVcpuHours.toLocaleString()} vCPU-hrs` },
    { key: 'frameworks', header: 'Frameworks', render: (t) => (t.allowedFrameworks ?? []).join(', ') },
    { key: 'createdAt', header: 'Created', render: (t) => formatDate(t.createdAt) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (t) => {
        if (t.status === 'deleted') {
          return <span className="text-xs text-text-muted">—</span>;
        }
        return (
          <div className="flex items-center justify-end gap-2">
            {t.provisioningStatus === 'failed' && (
              <Button
                variant="secondary"
                loading={retryingId === t.tenantId}
                onClick={(e) => {
                  e.stopPropagation();
                  void retryProvisioning(t);
                }}
                className="!px-3 !py-1.5 !text-xs"
              >
                Retry provisioning
              </Button>
            )}
            {t.status === 'active' ? (
              <Button
                variant="danger"
                onClick={(e) => {
                  e.stopPropagation();
                  setPendingSuspend(t);
                }}
                className="!px-3 !py-1.5 !text-xs"
              >
                Suspend
              </Button>
            ) : (
              <>
                <Button
                  variant="secondary"
                  onClick={(e) => {
                    e.stopPropagation();
                    void reactivate(t);
                  }}
                  className="!px-3 !py-1.5 !text-xs"
                >
                  Reactivate
                </Button>
                <Button
                  variant="danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteData(false);
                    setPendingDelete(t);
                  }}
                  className="!px-3 !py-1.5 !text-xs"
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        );
      },
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
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700">
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
        open={!!pendingDelete}
        title="Delete tenant?"
        description={
          <div className="space-y-3">
            <p>
              This tears down{' '}
              <span className="font-medium text-text-primary">{pendingDelete?.name}</span>
              &apos;s dataplane resources (EMR Serverless application, execution role; the KMS
              key gets a 30-day recovery window) and permanently marks the tenant deleted.
              It cannot be reactivated — only a new tenant can replace it.
            </p>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={deleteData}
                onChange={(e) => setDeleteData(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                Also permanently delete the tenant&apos;s S3 artifacts
                <span className="block text-xs text-text-muted">
                  Off by default — model artifacts are usually retained for MRM/governance.
                </span>
              </span>
            </label>
          </div>
        }
        tone="danger"
        confirmLabel={deleteData ? 'Delete tenant + data' : 'Delete tenant'}
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteData(false);
        }}
      />

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
