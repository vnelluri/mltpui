import { useEffect, useState } from 'react';
import { auditApi } from '../../api/audit';
import { extractErrorMessage } from '../../api/client';
import { PageHeader, Input, Select } from '../../components/shared/ui';
import { DataTable, type Column } from '../../components/shared/DataTable';
import { formatDateTime } from '../../lib/format';
import type { AuditEvent } from '../../types/platform';

const RESOURCE_TYPES = [
  '', 'Tenant', 'TrainingJob', 'Experiment', 'ExperimentRun', 'ModelVersion',
  'GovernanceReview', 'NotebookSession', 'SnowflakeTokenCache',
];

export function AuditLogPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [userId, setUserId] = useState('');
  const [resourceType, setResourceType] = useState('');

  const pageSize = 20;

  const load = async () => {
    setLoading(true);
    try {
      const res = await auditApi.list({
        page,
        pageSize,
        userId: userId || undefined,
        resourceType: resourceType || undefined,
      });
      setEvents(res.items);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, resourceType]);

  const columns: Column<AuditEvent>[] = [
    { key: 'timestamp', header: 'Time', render: (e) => formatDateTime(e.timestamp) },
    { key: 'action', header: 'Action', render: (e) => <span className="font-mono text-xs">{e.action}</span> },
    { key: 'resourceType', header: 'Resource', render: (e) => e.resourceType },
    { key: 'resourceId', header: 'Resource ID', render: (e) => <span className="font-mono text-xs">{e.resourceId ?? '—'}</span> },
    { key: 'userId', header: 'User', render: (e) => e.userId },
    { key: 'tenantId', header: 'Tenant', render: (e) => e.tenantId ?? 'Platform-wide' },
    { key: 'ipAddress', header: 'IP', render: (e) => e.ipAddress ?? '—' },
  ];

  return (
    <div>
      <PageHeader
        title="Audit Log"
        description="Every mutating action taken on the platform."
        actions={
          <div className="flex items-center gap-3">
            <Input
              placeholder="Filter by user ID"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setPage(1);
                  void load();
                }
              }}
              className="!w-48"
            />
            <Select
              value={resourceType}
              onChange={(e) => {
                setResourceType(e.target.value);
                setPage(1);
              }}
              className="!w-48"
            >
              {RESOURCE_TYPES.map((r) => (
                <option key={r || 'all'} value={r}>
                  {r || 'All resource types'}
                </option>
              ))}
            </Select>
          </div>
        }
      />

      <DataTable
        columns={columns}
        rows={events}
        rowKey={(e) => e.eventId}
        loading={loading}
        error={error}
        onRetry={load}
        total={total}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        emptyTitle="No audit events found"
      />
    </div>
  );
}
