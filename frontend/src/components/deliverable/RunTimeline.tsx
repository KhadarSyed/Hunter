const STAGES = ["gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc",
  "index", "design", "assets", "compose", "export"] as const;
const LABELS: Record<string, string> = { gate: "Gate", ingest: "Ingest", routing: "Routing", plan: "Plan",
  classify: "Classify", compute: "Compute", insights: "Insights", template: "Template", render: "Render", qc: "QC",
  index: "References", design: "Design", assets: "Photos", compose: "Compose", export: "Export" };

export function RunTimeline({ stages, details }: { stages: Record<string, string>; details: Record<string, string> }) {
  return (
    <ol className="flex flex-nowrap gap-1 overflow-x-auto" aria-label="Deliverable stages">
      {STAGES.map((s) => {
        const st = stages[s];
        const cls = st === "done" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : st === "running" ? "bg-violet-50 text-violet-700 border-violet-200 animate-pulse"
          : st === "failed" ? "bg-red-50 text-red-700 border-red-200" : "bg-white text-slate-500 border-slate-200";
        return (
          <li key={s} className={`shrink-0 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-medium ${cls}`}
              title={details[s] ? `${LABELS[s]} · ${details[s]}` : LABELS[s]}>
            {LABELS[s]}
          </li>
        );
      })}
    </ol>
  );
}
