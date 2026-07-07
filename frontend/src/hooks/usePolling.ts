import { useEffect, useRef } from 'react';

/**
 * Invoke `callback` immediately (optional) and then every `intervalMs`.
 * Pass `enabled=false` to pause polling. The latest callback is always used.
 */
export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  options: { enabled?: boolean; immediate?: boolean } = {},
): void {
  const { enabled = true, immediate = true } = options;
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;

    const tick = () => {
      if (active) void savedCallback.current();
    };

    if (immediate) tick();
    const id = window.setInterval(tick, intervalMs);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [enabled, immediate, intervalMs]);
}
