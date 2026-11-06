import { Icon } from "@iconify/react";
import type { UsageLiveRow } from "../../types/usage";
import { ProviderLogo } from "./ProviderLogo";
import { money, num, stageLabel } from "./format";

const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** The newest LLM calls as they happen (socket `llm_usage`), newest first. */
export function LiveFeed({ rows, paused, connected, onTogglePause, projectName }: {
  rows: UsageLiveRow[]; paused: boolean; connected: boolean; onTogglePause: () => void; projectName: (id: number) => string;
}) {
  const live = connected && !paused;
  return (
    <section aria-labelledby="live-feed-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <div className="mb-3 flex items-center gap-3">
        <h2 id="live-feed-heading" className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon icon="lucide:activity" width={18} aria-hidden className="text-[#5B2C9D]" /> Live calls
        </h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${
          live ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
          <span className="relative flex h-2 w-2">
            {live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-slate-400"}`} />
          </span>
          {paused ? "Paused" : connected ? "Live" : "Reconnecting"}
        </span>
        <button type="button" onClick={onTogglePause}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50">
          <Icon icon={paused ? "lucide:play" : "lucide:pause"} width={12} aria-hidden /> {paused ? "Resume" : "Pause"}
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">
          Waiting for LLM calls. They appear here the moment a stage, tagging or a deck run calls a model.
        </p>
      ) : (
        <ol className="max-h-80 divide-y divide-slate-100 overflow-y-auto" aria-live="polite">
          {rows.map((r, i) => (
            <li key={`${r.ts}-${i}`} className="grid grid-cols-[4.5rem_minmax(0,1.3fr)_minmax(0,1fr)_auto_auto] items-center gap-3 py-2 text-sm">
              <span className="tabular-nums text-xs text-slate-400">{time(r.ts)}</span>
              <span className="flex min-w-0 items-center gap-2">
                <ProviderLogo provider={r.provider} model={r.model} size={18} />
                {r.error ? <span className="rounded bg-red-50 px-1.5 text-[10px] font-semibold text-red-600">error</span> : null}
                {r.cache_hit ? <span className="rounded bg-sky-50 px-1.5 text-[10px] font-semibold text-sky-700">cache</span> : null}
              </span>
              <span className="min-w-0 truncate text-xs text-slate-500" title={r.sub_stage || undefined}>
                {r.project_id !== null ? projectName(r.project_id) : "No project"} · {stageLabel(r.stage)}{r.sub_stage ? ` › ${r.sub_stage}` : ""}
              </span>
              <span className="tabular-nums text-xs text-slate-500" title="input → output tokens">{num(r.input_tokens)} → {num(r.output_tokens)}</span>
              <span className="w-16 text-right font-semibold tabular-nums text-slate-900">{money(r.cost_usd)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
