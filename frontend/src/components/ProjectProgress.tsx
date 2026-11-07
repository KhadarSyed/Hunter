import { STAGE_LABEL, type StageKey } from "../hooks/useStageGate";
import { Donut } from "./Donut";

/** A project's place in the pipeline: a donut with the % inside and the current stage beside it ("Complete" at 100). */
export function ProjectProgress({ pct, stage, size = 34, className = "" }: {
  pct?: number; stage?: string; size?: number; className?: string;
}) {
  const value = Math.max(0, Math.min(100, Math.round(pct ?? 0)));
  const done = value >= 100;
  const label = done ? "Complete" : STAGE_LABEL[stage as StageKey] ?? "Brief & Scope";
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Donut value={value} size={size} color={done ? "#10B981" : "#5B2C9D"} title={`Project progress: ${label}, ${value}%`}>
        {done ? <span className="text-emerald-700">✓</span> : value}
      </Donut>
      <span className="min-w-0 leading-tight">
        <span className={`block truncate text-[11px] font-semibold ${done ? "text-emerald-700" : "text-slate-700"}`}>{label}</span>
        <span className="block text-[10px] tabular-nums text-slate-400">{value}% complete</span>
      </span>
    </div>
  );
}
