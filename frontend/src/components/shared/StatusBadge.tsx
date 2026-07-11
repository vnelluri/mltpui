type Tone = 'green' | 'amber' | 'red' | 'blue' | 'purple' | 'gray';

const TONE_CLASSES: Record<Tone, string> = {
  green: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30',
  amber: 'bg-amber-500/15 text-amber-600 border-amber-500/30',
  red: 'bg-red-500/15 text-red-600 border-red-500/30',
  blue: 'bg-sky-500/15 text-sky-600 border-sky-500/30',
  purple: 'bg-brand-purple/15 text-brand-purple border-brand-purple/30',
  gray: 'bg-bg-elevated text-text-secondary border-bg-elevated',
};

const LABEL_TONES: Record<string, Tone> = {
  // Tenants / users
  active: 'green',
  suspended: 'red',
  inactive: 'gray',
  // Jobs
  queued: 'amber',
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  cancelled: 'gray',
  // Runs
  finished: 'green',
  // Model stages
  none: 'gray',
  staging: 'amber',
  production: 'green',
  archived: 'gray',
  // Governance
  approved: 'green',
  rejected: 'red',
  pending: 'amber',
  // Roles
  platformadmin: 'purple',
  tenantadmin: 'blue',
  datascientist: 'green',
  mrm: 'amber',
};

interface StatusBadgeProps {
  status: string;
  label?: string;
  tone?: Tone;
  className?: string;
}

export function StatusBadge({ status, label, tone, className = '' }: StatusBadgeProps) {
  const resolvedTone = tone ?? LABEL_TONES[status.toLowerCase()] ?? 'gray';
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${TONE_CLASSES[resolvedTone]} ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label ?? status}
    </span>
  );
}
