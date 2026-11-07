import { useEffect, useRef } from "react";
import { Donut } from "../Donut";
import { Icon } from "@iconify/react";
import type { UsageStageRow } from "../../types/usage";
import { ProviderLogo } from "./ProviderLogo";
import { STAGE_ICONS, money, num, stageLabel, subStageLabel } from "./format";

const FOCUSABLE = 'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
const STAGE_HEADERS = ["Stage", "Calls", "Input", "Cached", "Output", "Total", "Cost"];

/** One row per pipeline stage; a row opens that stage's drill-down. */
export function StageTable({ rows, onOpen }: { rows: UsageStageRow[]; onOpen: (stage: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
            {STAGE_HEADERS.map((h, i) => (
              <th key={h} scope="col" className={`px-3 py-2 font-semibold ${i ? "text-right" : "text-left"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.stage} className="border-b border-slate-100 tabular-nums hover:bg-violet-50/60">
              <td className="px-3 py-2">
                <button type="button" onClick={() => onOpen(s.stage)}
                  className="inline-flex items-center gap-2 font-semibold text-slate-800 hover:text-[#5B2C9D] hover:underline focus-visible:outline-2 focus-visible:outline-[#5B2C9D]">
                  <Icon icon={STAGE_ICONS[s.stage] ?? "lucide:circle-dashed"} width={16} aria-hidden className="text-[#5B2C9D]" />
                  {stageLabel(s.stage)}<span className="sr-only"> (show sub-stages)</span>
                </button>
              </td>
              <td className="px-3 py-2 text-right">{num(s.calls)}</td>
              <td className="px-3 py-2 text-right">{num(s.input_tokens)}</td>
              <td className="px-3 py-2 text-right">{num(s.cached_input_tokens)}</td>
              <td className="px-3 py-2 text-right">{num(s.output_tokens)}</td>
              <td className="px-3 py-2 text-right font-semibold">{num(s.total_tokens)}</td>
              <td className="px-3 py-2 text-right font-semibold text-slate-900">{money(s.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-2xl bg-slate-50 px-3 py-2">
    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
    <div className="text-base font-bold tabular-nums text-slate-900">{value}</div>
  </div>
);

/** A modal with one stage's totals and its sub-stages; "Show these calls" narrows the call log to them. */
export function StageDrillDown({ stage, scope, onClose, onShowCalls }:
  { stage: UsageStageRow; scope: string; onClose: () => void; onShowCalls: (subStage: string | null) => void }) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => { if (opener && document.contains(opener)) opener.focus(); };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab" || !panel.current) return;
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const first = items[0], last = items[items.length - 1];
    // the panel itself holds focus after a click on its plain space: Shift+Tab from there wraps to the end
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const label = stageLabel(stage.stage);
  const share = (t: number) => (stage.total_tokens ? (100 * t) / stage.total_tokens : 0);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby="stage-drill-title" aria-describedby="stage-drill-scope"
        tabIndex={-1} onKeyDown={onKeyDown}
        className="outline-none max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <h2 id="stage-drill-title" className="flex items-center gap-2 text-xl font-bold text-slate-900">
            <Icon icon={STAGE_ICONS[stage.stage] ?? "lucide:circle-dashed"} width={20} aria-hidden className="text-[#5B2C9D]" />
            {label} <span className="font-medium text-slate-500">· sub-stages</span>
          </h2>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100">
            <Icon icon="lucide:x" width={18} aria-hidden />
          </button>
        </div>

        <p id="stage-drill-scope" className="mt-1 text-sm text-slate-500">{scope}</p>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Calls" value={num(stage.calls)} />
          <Stat label="Input" value={num(stage.input_tokens)} />
          <Stat label="Cached" value={num(stage.cached_input_tokens)} />
          <Stat label="Output" value={num(stage.output_tokens)} />
          <Stat label="Total tokens" value={num(stage.total_tokens)} />
          <Stat label="Cost" value={money(stage.cost_usd)} />
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
                <th scope="col" className="px-2 py-2 text-left font-semibold">Sub-stage</th>
                <th scope="col" className="px-2 py-2 text-left font-semibold">Share of tokens</th>
                {["Calls", "Input", "Cached", "Output", "Total", "Cost", "Avg latency"].map((h) => (
                  <th key={h} scope="col" className="px-2 py-2 text-right font-semibold">{h}</th>
                ))}
                <th scope="col" className="px-2 py-2 text-left font-semibold">Models</th>
                <th scope="col" className="px-2 py-2"><span className="sr-only">Calls</span></th>
              </tr>
            </thead>
            <tbody>
              {stage.sub_stages.map((s) => (
                <tr key={s.sub_stage || "(none)"} className="border-b border-slate-100 tabular-nums">
                  <td className={`whitespace-nowrap px-2 py-2 font-semibold ${s.sub_stage ? "text-slate-800" : "italic text-slate-500"}`}>{subStageLabel(s.sub_stage)}</td>
                  <td className="w-40 px-2 py-2" title={`${share(s.total_tokens).toFixed(1)}% of ${label} tokens`}>
                    <Donut value={share(s.total_tokens)} size={34} title={`${share(s.total_tokens).toFixed(1)}% of ${label} tokens`}>
                      {`${Math.round(share(s.total_tokens))}%`}
                    </Donut>
                  </td>
                  <td className="px-2 py-2 text-right">{num(s.calls)}</td>
                  <td className="px-2 py-2 text-right">{num(s.input_tokens)}</td>
                  <td className="px-2 py-2 text-right">{num(s.cached_input_tokens)}</td>
                  <td className="px-2 py-2 text-right">{num(s.output_tokens)}</td>
                  <td className="px-2 py-2 text-right font-semibold">{num(s.total_tokens)}</td>
                  <td className="px-2 py-2 text-right font-semibold text-slate-900">{money(s.cost_usd)}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right text-slate-600">{s.avg_latency_ms === null ? "—" : `${num(s.avg_latency_ms)} ms`}</td>
                  <td className="px-2 py-2">
                    <span className="flex items-center gap-1">
                      {s.models.map((m) => <ProviderLogo key={`${m.provider}/${m.model}`} provider={m.provider} model={m.model} nameless />)}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right">
                    <button type="button" onClick={() => onShowCalls(s.sub_stage)}
                      aria-label={`Show the calls of ${label}: ${subStageLabel(s.sub_stage)}`}
                      className="whitespace-nowrap text-xs font-semibold text-[#5B2C9D] hover:underline">Calls</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-5 flex flex-col items-end gap-1">
          <button type="button" onClick={() => onShowCalls(null)} aria-describedby="stage-drill-hint"
            className="inline-flex items-center gap-2 rounded-full bg-[#5B2C9D] px-5 py-2.5 text-sm font-semibold text-white shadow-md hover:bg-[#4a2380]">
            <Icon icon="lucide:list" width={16} aria-hidden /> Show these calls
          </button>
          <span id="stage-drill-hint" className="text-xs text-slate-500">Filters the whole page to this stage</span>
        </div>
      </div>
    </div>
  );
}
