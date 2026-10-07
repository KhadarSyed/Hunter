const STAGES = ["gate", "ingest", "routing", "plan", "classify", "compute", "insights", "template", "render", "qc",
  "index", "design", "assets", "compose", "export"] as const;
const LABELS: Record<string, string> = { gate: "Gate", ingest: "Ingest", routing: "Routing", plan: "Plan",
  classify: "Classify", compute: "Compute", insights: "Insights", template: "Template", render: "Render", qc: "QC",
  index: "References", design: "Design", assets: "Photos", compose: "Compose", export: "Export" };

export function RunTimeline({ stages, details }: { stages: Record<string, string>; details: Record<string, string> }) {
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Deliverable stages">
      {STAGES.map((s) => {
        const st = stages[s];
        const cls = st === "done" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : st === "running" ? "bg-violet-50 text-violet-700 border-violet-200 animate-pulse"
          : st === "failed" ? "bg-red-50 text-red-700 border-red-200" : "bg-white text-slate-400 border-slate-200";
        return (
          <li key={s} className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${cls}`} title={details[s] || ""}>
            {LABELS[s]}{details[s] ? <span className="ml-1 font-normal opacity-80">· {details[s]}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
