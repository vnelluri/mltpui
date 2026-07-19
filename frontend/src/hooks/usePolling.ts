import { useEffect, useRef } from 'react';

/**
 * Invoke `callback` immediately (optional) and then every `intervalMs`.
 * Pass `enabled=false` to pause polling. The latest callback is always used.
 *
 * Polling pauses while the tab is hidden (abandoned tabs would otherwise
 * keep hammering the API all day) and fires an immediate catch-up tick when
 * the tab becomes visible again, so returning users never look at stale data.
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
    let id: number | undefined;

    const tick = () => {
      if (active) void savedCallback.current();
    };
    const start = () => {
      if (id === undefined) id = window.setInterval(tick, intervalMs);
    };
    const stop = () => {
      if (id !== undefined) {
        window.clearInterval(id);
        id = undefined;
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        tick(); // catch up right away, then resume the interval
        start();
      } else {
        stop();
      }
    };

    // The initial load runs even in a hidden tab so the page isn't blank
    // when the user first switches to it; only the *recurring* interval is
    // gated on visibility.
    if (immediate) tick();
    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      active = false;
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [enabled, immediate, intervalMs]);
}
