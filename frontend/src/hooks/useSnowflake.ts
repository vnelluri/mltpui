import { useCallback, useState } from 'react';
import { snowflakeApi } from '../api/snowflake';
import { extractErrorMessage } from '../api/client';
import { usePolling } from './usePolling';
import type { SnowflakeStatus } from '../types/platform';

export type SnowflakeConnectionState = 'connected' | 'not_connected' | 'expired' | 'unknown';

export interface UseSnowflakeResult {
  status: SnowflakeStatus | null;
  state: SnowflakeConnectionState;
  minutesRemaining: number | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
}

function computeState(status: SnowflakeStatus | null): {
  state: SnowflakeConnectionState;
  minutesRemaining: number | null;
} {
  if (!status) return { state: 'unknown', minutesRemaining: null };
  if (!status.connected || !status.expiresAt) {
    return { state: 'not_connected', minutesRemaining: null };
  }
  const expiry = new Date(status.expiresAt).getTime();
  const now = Date.now();
  const minutes = Math.round((expiry - now) / 60000);
  if (minutes <= 0) return { state: 'expired', minutesRemaining: 0 };
  return { state: 'connected', minutesRemaining: minutes };
}

/**
 * Polls GET /snowflake/status every 60s. Exposes connect/disconnect helpers.
 */
export function useSnowflake(pollMs = 60000): UseSnowflakeResult {
  const [status, setStatus] = useState<SnowflakeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await snowflakeApi.status();
      setStatus(result);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(refresh, pollMs, { immediate: true });

  const connect = useCallback(async () => {
    setLoading(true);
    try {
      const result = await snowflakeApi.connect();
      setStatus(result);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    setLoading(true);
    try {
      await snowflakeApi.disconnect();
      setStatus({ connected: false, snowflakeUsername: null, expiresAt: null });
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const { state, minutesRemaining } = computeState(status);

  return { status, state, minutesRemaining, loading, error, refresh, connect, disconnect };
}
