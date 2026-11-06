import { useState } from "react";
import { Icon } from "@iconify/react";
import type { UsageProjectRow } from "../../types/usage";
import { ProviderLogo } from "./ProviderLogo";
import { money, num, pct, stageLabel } from "./format";

const RANKED_PREVIEW = 10;
const projectName = (p: UsageProjectRow): string => p.project_name ?? (p.project_id === null ? "No project" : `Project #${p.project_id}`);

function ShareBar({ share }: { share: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100" aria-hidden>
      <div className="h-full rounded-full bg-[#5B2C9D]" style={{ width: `${Math.min(100, Math.max(0, share))}%` }} />
    </div>
  );
}

function TopCard({ p, onPick }: { p: UsageProjectRow; onPick?: () => void }) {
  return (
    <div className="rounded-3xl border-2 border-[#5B2C9D] bg-gradient-to-br from-white to-violet-50 p-5 shadow-md">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="inline-flex items-center gap-1 rounded-full bg-[#5B2C9D] px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">
            <Icon icon="lucide:flame" width={12} aria-hidden /> Highest usage
          </span>
          <h3 className="mt-2 truncate text-xl font-bold text-slate-900">
            {onPick ? (
              <button type="button" onClick={onPick} title={`Filter to ${projectName(p)}`}
                className="max-w-full truncate text-left hover:text-[#5B2C9D] hover:underline focus-visible:outline-2 focus-visible:outline-[#5B2C9D]">
                {projectName(p)}<span className="sr-only"> (filter to this project)</span>
              </button>
            ) : projectName(p)}
          </h3>
          <p className="text-sm text-slate-500">{p.owner_name ? `Owner: ${p.owner_name}` : "No owner"}</p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold tabular-nums text-slate-900">{money(p.cost_usd)}</div>
          <div className="text-xs text-slate-500">{num(p.calls)} calls</div>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between gap-2 text-sm">
          <span className="font-semibold tabular-nums text-slate-900">{num(p.total_tokens)} tokens</span>
          <span className="font-semibold text-[#5B2C9D]">{pct(p.share_pct)} of all tokens</span>
        </div>
        <div className="mt-1.5"><ShareBar share={p.share_pct} /></div>
        <p className="mt-1.5 text-xs tabular-nums text-slate-500">
          {num(p.input_tokens)} input · {num(p.cached_input_tokens)} cached · {num(p.output_tokens)} output
          <span className="mx-2 text-slate-300">|</span>Top stage: <b className="text-slate-700">{stageLabel(p.top_stage)}</b>
        </p>
      </div>

      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
            <th className="py-1 font-semibold">Model</th>
            <th className="py-1 text-right font-semibold">Tokens</th>
            <th className="py-1 text-right font-semibold">Cost</th>
          </tr>
        </thead>
        <tbody>
          {p.models.map((m) => (
            <tr key={`${m.provider}/${m.model}`} className="border-t border-violet-100">
              <td className="py-1.5"><ProviderLogo provider={m.provider} model={m.model} /></td>
              <td className="py-1.5 text-right tabular-nums">{num(m.total_tokens)}</td>
              <td className="py-1.5 text-right tabular-nums">{money(m.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Top projects by token usage: the #1 project highlighted, then a ranked list. Clicking sets the Project filter. */
export function TopProjects({ projects, onPick }: { projects: UsageProjectRow[]; onPick: (projectId: number) => void }) {
  const [showAll, setShowAll] = useState(false);
  if (projects.length === 0) return null;
  const [top, ...rest] = projects;
  const shown = showAll ? rest : rest.slice(0, RANKED_PREVIEW - 1);
  const pickFor = (p: UsageProjectRow) => (p.project_id === null ? undefined : () => onPick(p.project_id as number));

  return (
    <section aria-labelledby="top-projects-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <h2 id="top-projects-heading" className="flex items-center gap-2 text-lg font-semibold text-slate-900">
        <Icon icon="lucide:trophy" width={18} aria-hidden className="text-[#5B2C9D]" /> Top projects by token usage
      </h2>
      <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <TopCard p={top} onPick={pickFor(top)} />
        {rest.length > 0 ? (
          <div>
            <ol className="divide-y divide-slate-100">
              {shown.map((p, i) => {
                const pick = pickFor(p);
                return (
                  <li key={p.project_id ?? "none"}>
                    <button
                      type="button"
                      disabled={!pick}
                      onClick={pick}
                      aria-label={`Filter to ${projectName(p)}`}
                      className="grid w-full grid-cols-[2rem_minmax(0,1.4fr)_minmax(0,1fr)_auto_auto] items-center gap-3 px-2 py-2.5 text-left text-sm hover:bg-slate-50 disabled:cursor-default disabled:hover:bg-transparent"
                    >
                      <span className="text-center font-bold tabular-nums text-slate-400">#{i + 2}</span>
                      <span className="min-w-0">
                        <span className="block truncate font-semibold text-slate-800">{projectName(p)}</span>
                        <span className="block truncate text-xs text-slate-500">Top stage: {stageLabel(p.top_stage)}</span>
                      </span>
                      <span className="min-w-0" title={`${num(p.total_tokens)} tokens`}>
                        <ShareBar share={p.share_pct} />
                        <span className="mt-0.5 block text-xs tabular-nums text-slate-500">{num(p.total_tokens)} · {pct(p.share_pct)}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        {p.models.map((m) => <ProviderLogo key={`${m.provider}/${m.model}`} provider={m.provider} model={m.model} nameless />)}
                      </span>
                      <span className="w-20 text-right font-semibold tabular-nums text-slate-900">{money(p.cost_usd)}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
            {rest.length > RANKED_PREVIEW - 1 && (
              <button type="button" onClick={() => setShowAll((s) => !s)} className="mt-2 text-sm font-semibold text-[#5B2C9D] hover:underline">
                {showAll ? "Show top 10" : `Show all (${projects.length})`}
              </button>
            )}
          </div>
        ) : (
          <p className="self-center text-sm text-slate-500">Only one project used the models in this range.</p>
        )}
      </div>
    </section>
  );
}
