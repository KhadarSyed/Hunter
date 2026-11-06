import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import { useAgentSocket } from "../../hooks/useAgentSocket";
import { compact, money } from "./format";

/** LLM cost of one project so far, moving live as its calls are recorded. */
export function ProjectCostChip({ projectId }: { projectId: number }) {
  const [total, setTotal] = useState<{ cost_usd: number; total_tokens: number } | null>(null);
  useEffect(() => {
    let alive = true;
    setTotal(null);
    intelApi.projectUsageTotal(projectId).then((t) => { if (alive) setTotal(t); }).catch(() => {});
    return () => { alive = false; };
  }, [projectId]);
  useAgentSocket((m) => {
    if (m.type !== "llm_usage" || Number(m.project_id) !== projectId) return;
    setTotal((t) => ({ cost_usd: (t?.cost_usd ?? 0) + (Number(m.cost_usd) || 0),
                       total_tokens: (t?.total_tokens ?? 0) + (Number(m.total_tokens) || 0) }));
  });
  return (
    <div>
      <div className="text-[10px] text-slate-400 uppercase tracking-wider font-medium mb-1">LLM cost so far</div>
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-800 tabular-nums" title="Every LLM call this project made, live">
        <Icon icon="lucide:circle-dollar-sign" width={14} aria-hidden className="text-[#5B2C9D]" />
        {total ? `${money(total.cost_usd)} · ${compact(total.total_tokens)} tokens` : "…"}
      </span>
    </div>
  );
}
