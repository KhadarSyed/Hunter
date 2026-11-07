import { useEffect, useRef } from "react";
import { agentSocket } from "../services/ws";

const PROGRESS_TYPES = new Set(["intel_job_update", "dataset_tagging", "intel_strategy_approved", "project_created",
  "project_deleted", "project_updated", "deliverable_run", "deliverable_progress", "deliverable_stage",
  "deliverable_completed", "deliverable_failed"]);

/** Calls `reload` when pipeline progress arrives on the socket: at once, then at most every `gapMs` while it keeps
 * coming (a trailing call catches the last message), so progress bars stay live without a request per event. */
export function useLiveRefetch(reload: () => void, gapMs = 2500) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    let last = 0;
    let timer: number | undefined;
    agentSocket.connect();
    const off = agentSocket.onMessage((msg) => {
      if (!PROGRESS_TYPES.has(msg.type)) return;
      const wait = last + gapMs - Date.now();
      if (wait <= 0) { last = Date.now(); reloadRef.current(); return; }
      if (timer === undefined) timer = window.setTimeout(() => { timer = undefined; last = Date.now(); reloadRef.current(); }, wait);
    });
    return () => { off(); if (timer !== undefined) window.clearTimeout(timer); };
  }, [gapMs]);
}
