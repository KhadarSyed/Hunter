import { Icon } from "@iconify/react";
import type { UsageCall } from "../../types/usage";
import { ProviderLogo } from "./ProviderLogo";
import { money, num, stageLabel, subStageLabel } from "./format";

export const CALL_PAGE_SIZE = 50;

const HEADERS = ["Date and time", "Project", "Stage", "Sub-stage", "Model", "Kind", "Input", "Output", "Total", "Cost", "Latency", "Cache hit"];
const NUMERIC_FROM = 6;

/** The newest calls first, 50 per page; times are shown in the viewer's local time zone. */
export function CallLogTable({ rows, total, offset, loading, onOffset }:
  { rows: UsageCall[]; total: number; offset: number; loading: boolean; onOffset: (offset: number) => void }) {
  const last = Math.min(offset + rows.length, total);
  return (
    <div>
      <div className={`overflow-x-auto transition-opacity ${loading ? "opacity-50" : ""}`} aria-busy={loading}>
        <table className="w-full min-w-[1200px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
              {HEADERS.map((h, i) => (
                <th key={h} scope="col" className={`px-3 py-2 font-semibold ${i >= NUMERIC_FROM && i < HEADERS.length - 1 ? "text-right" : "text-left"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ts}-${offset + i}`} className="border-b border-slate-100 tabular-nums hover:bg-slate-50">
                <td className="whitespace-nowrap px-3 py-2 text-slate-700">{new Date(r.ts * 1000).toLocaleString("en-US")}</td>
                <td className="max-w-[14rem] truncate px-3 py-2 text-slate-800" title={r.project_name ?? undefined}>
                  {r.project_name ?? (r.project_id === null ? <span className="text-slate-400">No project</span> : `#${r.project_id}`)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-700">{stageLabel(r.stage)}</td>
                <td className={`whitespace-nowrap px-3 py-2 ${r.sub_stage ? "text-slate-700" : "text-slate-400"}`}>{r.sub_stage ? subStageLabel(r.sub_stage) : "—"}</td>
                <td className="max-w-[16rem] px-3 py-2"><ProviderLogo provider={r.provider} model={r.model} /></td>
                <td className="px-3 py-2 text-slate-700">
                  {r.kind}
                  {r.error ? (
                    <span className="mt-1 block max-w-[18rem] rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-700" title={r.error_reason || "Failed"}>
                      <b className="font-semibold">Failed</b>{r.error_reason ? `: ${r.error_reason}` : ""}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right">{num(r.input_tokens)}</td>
                <td className="px-3 py-2 text-right">{num(r.output_tokens)}</td>
                <td className="px-3 py-2 text-right font-semibold">{num(r.total_tokens)}</td>
                <td className="px-3 py-2 text-right font-semibold text-slate-900">{money(r.cost_usd)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right text-slate-600">{r.latency_ms === null ? "—" : `${num(Math.round(r.latency_ms))} ms`}</td>
                <td className="px-3 py-2">
                  {r.cache_hit ? (
                    <span className="inline-flex items-center gap-1 text-emerald-700"><Icon icon="lucide:check-circle-2" width={14} aria-hidden /> Yes</span>
                  ) : <span className="text-slate-400">No</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
        <span className="tabular-nums">{total === 0 ? "No calls" : `${num(offset + 1)}–${num(last)} of ${num(total)} calls`}</span>
        <div className="flex gap-2">
          <button type="button" aria-label="Previous page" disabled={offset === 0 || loading}
            onClick={() => onOffset(Math.max(0, offset - CALL_PAGE_SIZE))}
            className="rounded-lg border border-slate-200 bg-white p-1.5 hover:bg-slate-50 disabled:opacity-40">
            <Icon icon="lucide:chevron-left" width={16} aria-hidden />
          </button>
          <button type="button" aria-label="Next page" disabled={offset + CALL_PAGE_SIZE >= total || loading}
            onClick={() => onOffset(offset + CALL_PAGE_SIZE)}
            className="rounded-lg border border-slate-200 bg-white p-1.5 hover:bg-slate-50 disabled:opacity-40">
            <Icon icon="lucide:chevron-right" width={16} aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
