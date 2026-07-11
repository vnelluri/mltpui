import { useEffect, useState } from 'react';
import { tenantsApi } from '../../api/tenants';
import { extractErrorMessage } from '../../api/client';
import { useTenantContext } from '../../hooks/useTenantContext';
import { PageHeader, Card, Button, Field, Input, InlineAlert } from '../../components/shared/ui';
import { LoadingSpinner } from '../../components/shared/LoadingSpinner';
import type { Tenant, Framework } from '../../types/platform';

const ALL_FRAMEWORKS: Framework[] = ['pytorch', 'tensorflow', 'sklearn', 'xgboost'];

export function TenantSettingsPage() {
  const { tenantId } = useTenantContext();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [quota, setQuota] = useState(0);
  const [frameworks, setFrameworks] = useState<Framework[]>([]);

  useEffect(() => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const t = await tenantsApi.get(tenantId);
        setTenant(t);
        setQuota(t.computeQuotaVcpuHours);
        setFrameworks(t.allowedFrameworks ?? []);
      } catch (err) {
        setError(extractErrorMessage(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [tenantId]);

  const toggleFramework = (fw: Framework) => {
    setFrameworks((prev) => (prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw]));
  };

  const save = async () => {
    if (!tenantId) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const updated = await tenantsApi.update(tenantId, {
        computeQuotaVcpuHours: quota,
        allowedFrameworks: frameworks,
      });
      setTenant(updated);
      setSuccess(true);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <LoadingSpinner label="Loading settings…" />
      </div>
    );
  }

  if (!tenant) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-8 text-sm text-red-600">
        {error ?? 'No tenant assigned.'}
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Tenant Settings" description={`Configuration for ${tenant.name}.`} />

      <Card className="max-w-xl p-6">
        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <InlineAlert tone="success" className="mb-4">
            Settings saved.
          </InlineAlert>
        )}

        <Field label="Compute quota (vCPU-hours / month)" required className="mb-5">
          <Input type="number" min={0} value={quota} onChange={(e) => setQuota(Number(e.target.value) || 0)} />
        </Field>

        <Field label="Allowed frameworks" className="mb-6">
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

        <Button loading={saving} onClick={() => void save()}>
          Save settings
        </Button>
      </Card>
    </div>
  );
}
