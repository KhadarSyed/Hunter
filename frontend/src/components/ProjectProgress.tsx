import { STAGE_LABEL, type StageKey } from "../hooks/useStageGate";

/** A project's place in the pipeline: a donut with the % inside and the current stage beside it ("Complete" at 100). */
export function ProjectProgress({ pct, stage, size = 34, className = "" }: {
  pct?: number; stage?: string; size?: number; className?: string;
}) {
  const value = Math.max(0, Math.min(100, Math.round(pct ?? 0)));
  const done = value >= 100;
  const label = done ? "Complete" : STAGE_LABEL[stage as StageKey] ?? "Brief & Scope";
  const stroke = Math.max(3, Math.round(size / 9));
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const color = done ? "#10B981" : "#5B2C9D";
  return (
    <div className={`flex items-center gap-2 ${className}`} title={`${label} · ${value}%`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0 -rotate-90" role="progressbar"
           aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} aria-label={`Project progress: ${label}, ${value}%`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#EEF0F4" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
                strokeDasharray={circ} strokeDashoffset={circ * (1 - value / 100)}
                style={{ transition: "stroke-dashoffset 600ms ease-out" }} />
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" transform={`rotate(90 ${size / 2} ${size / 2})`}
              fontSize={Math.round(size * 0.3)} fontWeight={700} fill={done ? "#047857" : "#1e1833"}>
          {done ? "✓" : value}
        </text>
      </svg>
      <span className="min-w-0 leading-tight">
        <span className={`block truncate text-[11px] font-semibold ${done ? "text-emerald-700" : "text-slate-700"}`}>{label}</span>
        <span className="block text-[10px] tabular-nums text-slate-400">{value}% complete</span>
      </span>
    </div>
  );
}
