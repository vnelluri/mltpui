import { useEffect, useState } from 'react';
import { groupMappingsApi } from '../../api/groupMappings';
import { tenantsApi } from '../../api/tenants';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Button, Modal, Field, Input, Select, InlineAlert } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { ROLES, ROLE_LABELS } from '../../auth/roles';
import { formatDate } from '../../lib/format';
import type { GroupMapping, Role, Tenant } from '../../types/platform';

export function GroupMappingsPage() {
  const [mappings, setMappings] = useState<GroupMapping[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<GroupMapping | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<GroupMapping | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [groupId, setGroupId] = useState('');
  const [role, setRole] = useState<Role>('DataScientist');
  const [tenantId, setTenantId] = useState('');
  const [description, setDescription] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [m, t] = await Promise.all([groupMappingsApi.list({ pageSize: 100 }), tenantsApi.list({ pageSize: 100 })]);
      setMappings(m.items);
      setTenants(t.items);
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

  const openCreate = () => {
    setEditing(null);
    setGroupId('');
    setRole('DataScientist');
    setTenantId(tenants[0]?.tenantId ?? '');
    setDescription('');
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (gm: GroupMapping) => {
    setEditing(gm);
    setGroupId(gm.groupId);
    setRole(gm.role);
    setTenantId(gm.tenantId ?? '');
    setDescription(gm.description ?? '');
    setFormError(null);
    setModalOpen(true);
  };

  const submit = async () => {
    if (!groupId.trim()) {
      setFormError('Entra Group Object ID is required.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        await groupMappingsApi.update(editing.groupId, { role, tenantId: tenantId || undefined, description });
      } else {
        await groupMappingsApi.create({ groupId: groupId.trim(), role, tenantId, description });
      }
      setModalOpen(false);
      await load();
    } catch (err) {
      setFormError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await groupMappingsApi.remove(pendingDelete.groupId);
      setPendingDelete(null);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const columns: Column<GroupMapping>[] = [
    { key: 'groupId', header: 'Entra Group ID', render: (gm) => <span className="font-mono text-xs">{gm.groupId}</span> },
    { key: 'description', header: 'Description', render: (gm) => gm.description || '—' },
    { key: 'role', header: 'Role', render: (gm) => <StatusBadge status={gm.role} label={ROLE_LABELS[gm.role]} /> },
    { key: 'tenant', header: 'Tenant', render: (gm) => gm.tenantId ?? 'Platform-wide' },
    { key: 'createdAt', header: 'Created', render: (gm) => formatDate(gm.createdAt) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (gm) => (
        <div className="flex justify-end gap-2">
          <Button variant="secondary" className="!px-3 !py-1.5 !text-xs" onClick={() => openEdit(gm)}>
            Edit
          </Button>
          <Button variant="danger" className="!px-3 !py-1.5 !text-xs" onClick={() => setPendingDelete(gm)}>
            Delete
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Group Mappings"
        description="Map Entra ID security groups to a role and tenant. This is the source of truth for access — no manual role assignment."
        actions={<Button onClick={openCreate}>Add mapping</Button>}
      />

      <InlineAlert tone="info" className="mb-6">
        To find a group's Object ID: Azure Portal → Entra ID → Groups → select group → Overview → Object ID.
      </InlineAlert>

      <DataTable
        columns={columns}
        rows={mappings}
        rowKey={(gm) => gm.groupId}
        loading={loading}
        error={error}
        onRetry={load}
        emptyTitle="No group mappings yet"
        emptyDescription="Users cannot access the platform until their Entra group is mapped."
      />

      <Modal
        open={modalOpen}
        title={editing ? 'Edit group mapping' : 'Add group mapping'}
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void submit()}>
              {editing ? 'Save changes' : 'Create mapping'}
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
          <Field label="Entra Group Object ID" required hint="e.g. aaaaaaaa-0001-0001-0001-000000000001">
            <Input
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              disabled={!!editing}
              className="font-mono"
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </Field>
          <Field label="Description">
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Risk Analytics Data Scientists"
            />
          </Field>
          <Field label="Role" required>
            <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Tenant" hint="Leave blank for platform-wide roles (Platform Admin, MRM).">
            <Select value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
              <option value="">Platform-wide</option>
              {tenants.map((t) => (
                <option key={t.tenantId} value={t.tenantId}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!pendingDelete}
        title="Delete group mapping?"
        description={
          <>
            Users in <span className="font-mono text-text-primary">{pendingDelete?.groupId}</span> will lose
            access on their next login. This cannot be undone.
          </>
        }
        tone="danger"
        confirmLabel="Delete mapping"
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
