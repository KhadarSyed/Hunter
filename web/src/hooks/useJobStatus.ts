import { useEffect, useState } from "react";

interface UseJobStatusOptions<T> {
  /** Polling interval in ms. Defaults to 2000, matching every existing call site. */
  intervalMs?: number;
  /** Overrides the default "completed"/"failed" terminal check. */
  isTerminal?: (status: T) => boolean;
}

interface UseJobStatusResult<T> {
  status: T | null;
  error: Error | null;
}

function defaultIsTerminal<T extends { status: string }>(status: T): boolean {
  return status.status === "completed" || status.status === "failed";
}

/**
 * Polls `fetchStatus` on a fixed interval until it reports a terminal status,
 * replacing the hand-rolled `useRef<setInterval> + setInterval + clearInterval`
 * boilerplate that was duplicated in BackgroundResearch.tsx and
 * ResearchExecution.tsx.
 *
 * Pass `null` for `fetchStatus` to indicate "no active job" — polling is
 * skipped and any in-flight interval is cleared. `fetchStatus` should be a
 * stable reference (e.g. memoized with `useMemo`/`useCallback` keyed on the
 * job id) — a new function identity on every render restarts the interval.
 */
export function useJobStatus<T extends { status: string }>(
  fetchStatus: (() => Promise<T>) | null,
  options?: UseJobStatusOptions<T>,
): UseJobStatusResult<T> {
  const intervalMs = options?.intervalMs ?? 2000;
  const isTerminal = options?.isTerminal ?? defaultIsTerminal;

  const [status, setStatus] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!fetchStatus) {
      return;
    }

    setStatus(null);
    setError(null);

    const intervalId = setInterval(async () => {
      try {
        const result = await fetchStatus();
        setStatus(result);
        setError(null);
        if (isTerminal(result)) {
          clearInterval(intervalId);
        }
      } catch (e) {
        setError(e instanceof Error ? e : new Error("Lost connection to server"));
        clearInterval(intervalId);
      }
    }, intervalMs);

    return () => clearInterval(intervalId);
    // isTerminal is intentionally not a dependency — neither call site passes
    // a changing one, and including it would restart polling on every parent
    // render unless the caller memoizes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchStatus, intervalMs]);

  return { status, error };
}
