import { Button } from '../shared/ui';
import type { UseSnowflakeResult } from '../../hooks/useSnowflake';

interface SnowflakeConnectBannerProps {
  snowflake: UseSnowflakeResult;
  className?: string;
}

/**
 * Three-state Snowflake connection banner driven by the useSnowflake hook.
 * States: connected (green) · not connected (amber) · expired (red).
 */
export function SnowflakeConnectBanner({ snowflake, className = '' }: SnowflakeConnectBannerProps) {
  const { state, status, minutesRemaining, loading, connect, disconnect, error } = snowflake;

  const config = {
    connected: { dot: 'bg-emerald-400', ring: 'border-emerald-500/30 bg-emerald-500/5' },
    not_connected: { dot: 'bg-amber-400', ring: 'border-amber-500/30 bg-amber-500/5' },
    expired: { dot: 'bg-red-400', ring: 'border-red-500/30 bg-red-500/5' },
    unknown: { dot: 'bg-text-muted', ring: 'border-bg-elevated bg-bg-card' },
  }[state];

  return (
    <div
      className={`flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${config.ring} ${className}`}
    >
      <div className="flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5">
          {state === 'connected' && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          )}
          <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${config.dot}`} />
        </span>
        <div className="text-sm">
          {state === 'connected' && (
            <span className="text-text-primary">
              Connected to Snowflake as{' '}
              <span className="font-mono font-medium text-emerald-600">{status?.snowflakeUsername}</span>
              {minutesRemaining !== null && (
                <span className="ml-2 text-text-muted">· Expires in {minutesRemaining}m</span>
              )}
            </span>
          )}
          {state === 'not_connected' && <span className="text-text-primary">Not connected to Snowflake</span>}
          {state === 'expired' && <span className="text-red-700">Snowflake session expired</span>}
          {state === 'unknown' && <span className="text-text-secondary">Checking Snowflake connection…</span>}
          {error && <div className="mt-0.5 text-xs text-red-600">{error}</div>}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {state === 'connected' && (
          <Button variant="secondary" loading={loading} onClick={() => void disconnect()}>
            Disconnect
          </Button>
        )}
        {state === 'not_connected' && (
          <Button loading={loading} onClick={() => void connect()}>
            Connect
          </Button>
        )}
        {state === 'expired' && (
          <Button loading={loading} onClick={() => void connect()}>
            Reconnect
          </Button>
        )}
      </div>
    </div>
  );
}
