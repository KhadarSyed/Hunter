import { useCallback, useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";
import { useAgentSocket } from "./useAgentSocket";

export type GateState = "done" | "running" | "open" | "locked";
export const STAGE_KEYS = ["brief_scope", "background_research", "search_strategy", "matching_label", "data_set",
  "deliverables"] as const;
export type StageKey = (typeof STAGE_KEYS)[number];
export const STAGE_SLUG: Record<StageKey, string> = {
  brief_scope: "brief-scope-review", background_research: "background-research", search_strategy: "search-strategy",
  matching_label: "matching-label", data_set: "data-set", deliverables: "deliverables",
};
export const STAGE_LABEL: Record<StageKey, string> = {
  brief_scope: "Brief & Scope", background_research: "Background Research", search_strategy: "Search Strategy",
  matching_label: "Matching label", data_set: "Data set", deliverables: "Deliverables",
};
/** Pages that belong to a stage (and so are locked with it). */
export const PAGE_STAGE: Record<string, StageKey> = {
  "brief-scope-review": "brief_scope", "brief-analysis": "brief_scope", "background-research": "background_research",
  "search-strategy": "search_strategy", "query-evaluation": "search_strategy", "matching-label": "matching_label",
  "data-set": "data_set", deliverables: "deliverables", "research-plan": "deliverables",
};

/** The page a project opens on: the stage it is at (finished projects open on Deliverables). */
export function landingPage(currentStage?: string | null): string {
  return STAGE_SLUG[currentStage as StageKey] ?? "dashboard";
}

/** Where a locked page should send the user instead, and why; null when the page is open. */
export function gateRedirect(gates: Record<string, GateState>, page: string): { target: string; message: string } | null {
  const stage = PAGE_STAGE[page];
  if (!stage || gates[stage] !== "locked") return null;
  const blocking = STAGE_KEYS.find((k) => gates[k] !== "done") ?? "brief_scope";
  const why = gates[blocking] === "running" ? "is still running" : "is not complete yet";
  return { target: STAGE_SLUG[blocking],
           message: `${STAGE_LABEL[blocking]} ${why} — ${STAGE_LABEL[stage]} opens when it is done.` };
}

const REFRESH_TYPES = new Set(["intel_job_update", "dataset_tagging", "intel_strategy_approved", "project_updated",
  "intel_spec_approved", "intel_brief_approved", "deliverable_run"]);

export function useStageGate(projectId: number | null) {
  const [data, setData] = useState<{ gates: Record<string, GateState>; progressPct: number; currentStage: string } | null>(null);
  const refresh = useCallback(() => {
    if (!projectId) { setData(null); return; }
    intelApi.projectGates(projectId)
      .then((r) => setData({ gates: r.gates, progressPct: r.progress_pct, currentStage: r.current_stage }))
      .catch(() => { /* the server still 409s a locked stage; leave the last known gates */ });
  }, [projectId]);
  useEffect(refresh, [refresh]);
  useAgentSocket((m) => {
    if (!projectId || !REFRESH_TYPES.has(m.type)) return;
    if (m.project_id != null && Number(m.project_id) !== projectId) return;
    if (m.type === "intel_job_update" && !["completed", "failed"].includes(String(m.status ?? ""))) return;
    if (m.type === "dataset_tagging" && m.phase !== "done") return;
    refresh();
  });
  return { gates: data?.gates ?? null, progressPct: data?.progressPct ?? 0, currentStage: data?.currentStage ?? "", refresh };
}
