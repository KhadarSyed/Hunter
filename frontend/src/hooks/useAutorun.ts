import { useEffect, useMemo, useRef } from "react";
import { intelApi, type Autorun } from "../services/intel-api";
import { useJobStatus } from "./useJobStatus";

/**
 * Follows the project's autorun (research and strategy running themselves after Brief & Scope approval) while the
 * user watches it on this page: once the chain moves past `steps` (on, finished, or stopped at a later stage),
 * `onLeave` gets the stage it is at now. A user who opens the page after the chain moved on is never moved.
 */
export function useAutorun(projectId: number | null | undefined, steps: Autorun["step"][],
                           onLeave: (step: Autorun["step"]) => void) {
  const fetchStatus = useMemo(() => (projectId ? () => intelApi.autorunStatus(projectId) : null), [projectId]);
  const { status } = useJobStatus<Autorun>(fetchStatus, { intervalMs: 3000, isTerminal: (s) => s.status !== "running" });
  const watching = useRef(false);
  const leave = useRef(onLeave);
  leave.current = onLeave;

  useEffect(() => {
    if (!status) return;
    const here = steps.includes(status.step);
    if (status.status === "running" && here) watching.current = true;
    else if (watching.current && !here) {
      watching.current = false;
      leave.current(status.step);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return status;
}
