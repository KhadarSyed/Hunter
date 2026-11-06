import { STAGE_LABEL, type StageKey } from "../hooks/useStageGate";

/** A project's place in the pipeline: a thin bar with the current stage, or "Complete". */
export function ProjectProgress({ pct, stage, className = "" }: { pct?: number; stage?: string; className?: string }) {
  const value = Math.max(0, Math.min(100, Math.round(pct ?? 0)));
  const done = value >= 100;
  const label = done ? "Complete" : STAGE_LABEL[stage as StageKey] ?? "Brief & Scope";
  return (
    <div className={`w-full ${className}`} title={`${label} · ${value}%`}>
      <div className="mb-1 flex items-center justify-between text-[11px] font-medium">
        <span className={done ? "text-emerald-700" : "text-slate-500"}>
          {done ? "✓ " : ""}{label}
        </span>
        <span className="tabular-nums text-slate-400">{value}%</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100" role="progressbar"
           aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} aria-label={`Project progress: ${label}`}>
        <div className={`h-full rounded-full transition-[width] duration-500 ease-out ${done ? "bg-emerald-500" : "bg-[#5B2C9D]"}`}
             style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
