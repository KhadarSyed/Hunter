import { useEffect, useState } from "react";
import type { DeliverableProgress } from "../../services/intel-api";

const STAGES = ["gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc"];
const NAMES: Record<string, string> = {
  gate: "Checking approvals", ingest: "Ingesting datasets", routing: "Routing articles to questions",
  plan: "Planning analyses", classify: "Classifying entities", compute: "Computing charts and tables",
  insights: "Drafting cited insights", template: "Choosing a template", render: "Building slides",
  qc: "Fact check and layout QC",
};
const MIN_PCT_FOR_ESTIMATE = 5;

function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** Where the run is, what it is doing right now, how far along it is and roughly how long is left. */
export function RunProgress({ progress, isLive, failed }: { progress: DeliverableProgress; isLive: boolean; failed: boolean }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!isLive) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [isLive]);

  const elapsed = now - progress.started_at;
  const step = STAGES.indexOf(progress.stage) + 1;
  const remaining = progress.pct >= MIN_PCT_FOR_ESTIMATE && progress.pct < 100
    ? (elapsed * (100 - progress.pct)) / progress.pct : null;
  const bar = failed ? "bg-red-500" : progress.pct >= 100 ? "bg-emerald-500" : "bg-[#5B2C9D]";

  return (
    <div className="rounded-xl border border-violet-100 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[#5B2C9D]">
            {step > 0 ? `Step ${step} of ${STAGES.length} · ${NAMES[progress.stage] ?? progress.stage}` : "Starting"}
          </p>
          <p className="mt-1 truncate text-sm font-medium text-slate-800">{progress.label}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-2xl font-bold text-[#5B2C9D]">{progress.pct}%</p>
          <p className="text-[11px] text-slate-500">
            {isLive ? `${duration(elapsed)} elapsed` : null}
            {isLive && remaining !== null ? ` · ~${duration(remaining)} left` : null}
          </p>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full transition-all duration-500 ${bar}`} style={{ width: `${progress.pct}%` }} />
      </div>
    </div>
  );
}
