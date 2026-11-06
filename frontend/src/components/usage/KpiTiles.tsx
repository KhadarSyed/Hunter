import type { ReactNode } from "react";
import { Icon } from "@iconify/react";
import type { UsageKpis } from "../../types/usage";
import { compact, money, num } from "./format";

function Tile({ icon, label, value, title, sub, accent = false }:
  { icon: string; label: string; value: string; title: string; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-3xl p-5 shadow-sm ring-1 ${accent ? "bg-[#5B2C9D] text-white ring-[#5B2C9D]" : "bg-white ring-slate-900/5"}`}>
      <div className={`flex items-center gap-2 text-xs font-semibold uppercase tracking-wide ${accent ? "text-violet-100" : "text-slate-500"}`}>
        <Icon icon={icon} width={16} aria-hidden /> {label}
      </div>
      <div className={`mt-2 text-3xl font-bold tracking-tight tabular-nums ${accent ? "text-white" : "text-slate-900"}`} title={title}>
        {value}
      </div>
      {sub && <div className={`mt-1 text-xs tabular-nums ${accent ? "text-violet-100" : "text-slate-500"}`}>{sub}</div>}
    </div>
  );
}

/** Total cost · Tokens (input / output) · Calls · ≈ Saved by cache · NVIDIA credits. */
export function KpiTiles({ kpis }: { kpis: UsageKpis }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
      <Tile accent icon="lucide:circle-dollar-sign" label="Total cost" value={money(kpis.cost_usd)} title={`$${kpis.cost_usd}`} />
      <Tile
        icon="lucide:binary" label="Tokens (input / output)" value={compact(kpis.total_tokens)}
        title={`${num(kpis.total_tokens)} tokens`}
        sub={<span title={`${num(kpis.input_tokens)} input (${num(kpis.cached_input_tokens)} cached) / ${num(kpis.output_tokens)} output`}>
          {compact(kpis.input_tokens)} in / {compact(kpis.output_tokens)} out
        </span>}
      />
      <Tile icon="lucide:activity" label="Calls" value={compact(kpis.calls)} title={`${num(kpis.calls)} calls`}
        sub={`${num(kpis.cache_hits)} answered from cache`} />
      <Tile icon="lucide:piggy-bank" label="≈ Saved by cache" value={money(kpis.saved_by_cache_usd)} title={`$${kpis.saved_by_cache_usd}`}
        sub="Cache hits × the model's average call cost" />
      <Tile icon="simple-icons:nvidia" label="NVIDIA credits" value={compact(kpis.nvidia_credits)} title={`${num(kpis.nvidia_credits)} credits`} />
    </div>
  );
}
