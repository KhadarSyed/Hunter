import { useState } from "react";
import { Icon } from "@iconify/react";
import type { UsageModelRow } from "../../types/usage";
import { ProviderLogo } from "./ProviderLogo";
import { money, num, providerLabel } from "./format";

type SortKey = "model" | "provider" | "deployment_type" | "calls" | "input_tokens" | "cached_input_tokens" | "output_tokens" | "total_tokens" | "cost_usd";

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "model", label: "Model" },
  { key: "provider", label: "Provider" },
  { key: "deployment_type", label: "Deployment type" },
  { key: "calls", label: "Calls", numeric: true },
  { key: "input_tokens", label: "Input", numeric: true },
  { key: "cached_input_tokens", label: "Cached input", numeric: true },
  { key: "output_tokens", label: "Output", numeric: true },
  { key: "total_tokens", label: "Total", numeric: true },
  { key: "cost_usd", label: "Cost", numeric: true },
];
const NUMERIC_KEYS = COLUMNS.filter((c) => c.numeric).map((c) => c.key) as Exclude<SortKey, "model" | "provider" | "deployment_type">[];

/** One row per model with a totals row; sortable; clicking a row filters the call log to that model. */
export function SummaryTable({ rows, selectedModel, onPickModel }:
  { rows: UsageModelRow[]; selectedModel: string; onPickModel: (model: string) => void }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "cost_usd", desc: true });
  const sorted = [...rows].sort((a, b) => {
    const av = a[sort.key] ?? "", bv = b[sort.key] ?? "";
    const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
    return sort.desc ? -cmp : cmp;
  });
  const totals = Object.fromEntries(NUMERIC_KEYS.map((k) => [k, rows.reduce((s, r) => s + (Number(r[k]) || 0), 0)])) as Record<typeof NUMERIC_KEYS[number], number>;
  const toggle = (key: SortKey) => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
            {COLUMNS.map((c) => (
              <th key={c.key} scope="col" aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}
                className={`px-3 py-2 font-semibold ${c.numeric ? "text-right" : "text-left"}`}>
                <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 hover:text-slate-800">
                  {c.label}
                  {sort.key === c.key && <Icon icon={sort.desc ? "lucide:arrow-down" : "lucide:arrow-up"} width={12} aria-hidden />}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const isSelected = selectedModel === r.model;
            return (
              <tr
                key={`${r.provider}/${r.model}/${r.deployment_type}`}
                tabIndex={0}
                aria-selected={isSelected}
                title="Show this model's calls in the call log"
                onClick={() => onPickModel(isSelected ? "" : r.model)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPickModel(isSelected ? "" : r.model); } }}
                className={`cursor-pointer border-b border-slate-100 tabular-nums ${isSelected ? "bg-[#5B2C9D]/10" : "hover:bg-slate-50"}`}
              >
                <td className="px-3 py-2.5"><ProviderLogo provider={r.provider} model={r.model} size={18} /></td>
                <td className="px-3 py-2.5 text-slate-700">{providerLabel(r.provider)}</td>
                <td className="px-3 py-2.5 text-slate-700">{r.deployment_type || "—"}</td>
                <td className="px-3 py-2.5 text-right">{num(r.calls)}</td>
                <td className="px-3 py-2.5 text-right">{num(r.input_tokens)}</td>
                <td className="px-3 py-2.5 text-right">{num(r.cached_input_tokens)}</td>
                <td className="px-3 py-2.5 text-right">{num(r.output_tokens)}</td>
                <td className="px-3 py-2.5 text-right font-semibold">{num(r.total_tokens)}</td>
                <td className="px-3 py-2.5 text-right font-semibold text-slate-900">
                  {r.priced === false
                    ? <span className="font-medium text-amber-700" title="No price set for this model: Settings → LLM Providers → Set price (the first price also costs its earlier calls)">no price set</span>
                    : money(r.cost_usd)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-slate-300 bg-slate-50 font-bold tabular-nums text-slate-900">
            <td className="px-3 py-2.5" colSpan={3}>Total</td>
            <td className="px-3 py-2.5 text-right">{num(totals.calls)}</td>
            <td className="px-3 py-2.5 text-right">{num(totals.input_tokens)}</td>
            <td className="px-3 py-2.5 text-right">{num(totals.cached_input_tokens)}</td>
            <td className="px-3 py-2.5 text-right">{num(totals.output_tokens)}</td>
            <td className="px-3 py-2.5 text-right">{num(totals.total_tokens)}</td>
            <td className="px-3 py-2.5 text-right">{money(totals.cost_usd)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
