import { useCallback, useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";
import { STAGE_KEYS, STAGE_LABEL } from "../hooks/useStageGate";
import { useLiveRefetch } from "../hooks/useLiveRefetch";
import { Donut } from "./Donut";

type Detail = Record<string, { state: "done" | "running" | "open" | "locked"; pct: number; sub: string }>;

const RING: Record<string, string> = { done: "#10B981", running: "#5B2C9D", open: "#5B2C9D", locked: "#CBD5E1" };
const STATE_TEXT: Record<string, string> = { done: "Done", running: "Running", open: "Next", locked: "Locked" };

/** The six pipeline stages of one project, each with its donut, state and live sub-stage (what it is doing now). */
export function PipelineDrillDown({ projectId, className = "" }: { projectId: number; className?: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    intelApi.projectGates(projectId).then((r) => { setDetail(r.detail ?? null); setError(false); }).catch(() => setError(true));
  }, [projectId]);
  useEffect(load, [load]);
  useLiveRefetch(load);       // job, tagging and deck events move the sub-stages live

  if (error && !detail) return <p className={`text-xs text-red-600 ${className}`}>Could not load the pipeline.</p>;
  if (!detail) return <p className={`text-xs text-slate-400 ${className}`}>Loading pipeline…</p>;
  return (
    <ol className={`space-y-1.5 ${className}`} aria-label="Pipeline stages">
      {STAGE_KEYS.map((k) => {
        const d = detail[k] ?? { state: "locked", pct: 0, sub: "" };
        return (
          <li key={k} className="flex items-center gap-2.5">
            <Donut value={d.state === "done" ? 100 : d.pct} size={26} color={RING[d.state]} spin={d.state === "running" && d.pct === 0}
                   title={`${STAGE_LABEL[k]}: ${STATE_TEXT[d.state]}${d.state === "running" ? ` ${d.pct}%` : ""}`}>
              {d.state === "done" ? <span className="text-emerald-600">✓</span> : d.state === "locked" ? "" : null}
            </Donut>
            <span className="min-w-0 flex-1 leading-tight">
              <span className={`block truncate text-xs font-semibold ${d.state === "locked" ? "text-slate-400" : "text-slate-800"}`}>
                {STAGE_LABEL[k]}
                <span className={`ml-1.5 text-[10px] font-medium ${d.state === "done" ? "text-emerald-600" : d.state === "running" ? "text-[#5B2C9D]" : "text-slate-400"}`}>
                  {STATE_TEXT[d.state]}{d.state === "running" && d.pct > 0 ? ` · ${d.pct}%` : ""}
                </span>
              </span>
              {d.sub && <span className="block truncate text-[11px] text-slate-500" title={d.sub}>{d.sub}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
