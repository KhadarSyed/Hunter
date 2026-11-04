import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { Latest24hArticle, Latest24hRefresh } from "../../services/intel-api";
import { agentSocket } from "../../services/ws";
import { ChartRenderer } from "./ChartRenderer";

// running totals only: which source found what stays in the stored refresh
type Live = { refreshId: number; total: number; kept: number | null };

const TOP_STORIES = 10;
// one distinct light tint per brand (the house palette has four, and the brand + five competitors need six)
const BRAND_TINTS = ["B794E8", "F9B98E", "8FB8E0", "8FD3B6", "F2A7C3", "F6D57A", "A3A8F0", "9ED9E8"];
const domainOf = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; } };
const favicon = (url: string) => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domainOf(url))}&sz=64`;
const timeOf = (date: string) => {
  const d = new Date(date);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

function Cite({ n, byN }: { n: number; byN: Record<number, Latest24hArticle> }) {
  const a = byN[n];
  if (!a || !/^https?:\/\//i.test(a.url)) return null;
  return (
    <a href={a.url} target="_blank" rel="noopener noreferrer" title={`${a.outlet}: ${a.title}`}
      className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white align-middle">
      <img src={favicon(a.url)} alt={a.outlet} className="h-3.5 w-3.5 rounded-sm" loading="lazy" />
    </a>
  );
}

/** "Refresh latest 24h": fetches the brand's and competitors' last-24h coverage, streams per-source counts, then
 * shows a cited "What's new" summary, charts and the top new stories. The latest refresh is reloaded from the server.
 * Collapsed on every visit: a header row (title, last refresh, chevron) the user opens. */
export function Latest24hPanel({ projectId }: { projectId: number }) {
  const [refresh, setRefresh] = useState<Latest24hRefresh | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    let current = true;
    const load = () => intelApi.latest24hLatest(projectId)
      .then((r) => { if (current) setRefresh(r.refresh); })
      .catch(() => undefined);
    setRefresh(null);
    setLive(null);
    load();
    const off = agentSocket.onMessage((msg) => {
      if (msg.type !== "latest24h_progress" || msg.project_id !== projectId) return;
      if (msg.phase === "completed" || msg.phase === "failed") {
        load().then(() => { if (current) setLive(null); });
        return;
      }
      setLive((l) => {
        const base: Live = l && l.refreshId === msg.refresh_id ? l : { refreshId: msg.refresh_id, total: 0, kept: null };
        if (msg.phase === "filtered") return { ...base, total: msg.total, kept: msg.kept };
        return { ...base, total: Math.max(base.total, msg.total ?? 0) };
      });
    });
    return () => { current = false; off(); };
  }, [projectId]);

  const start = async () => {
    setError(null);
    try {
      const { refresh_id } = await intelApi.latest24hRefresh(projectId);
      setLive((l) => (l && l.refreshId === refresh_id ? l : { refreshId: refresh_id, total: 0, kept: null }));
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "Could not start the refresh");
    }
  };

  const running = !!live || refresh?.status === "running";
  const articles = refresh?.articles ?? [];
  const byN = Object.fromEntries(articles.map((a) => [a.n, a]));
  const charts = refresh?.charts ?? {};

  return (
    <section className="space-y-4 rounded-2xl border border-violet-100 bg-white p-5" aria-labelledby="latest24h-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={() => setIsOpen((o) => !o)} aria-expanded={isOpen} aria-controls="latest24h-body"
          className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5B2C9D]">
          <Icon icon="lucide:chevron-right" width={18} className={`shrink-0 text-slate-500 transition-transform ${isOpen ? "rotate-90" : ""}`} />
          <span className="min-w-0">
            <span id="latest24h-heading" className="flex items-center gap-2 text-base font-semibold text-slate-900">
              <Icon icon="lucide:radio" width={18} className="text-[#5B2C9D]" /> What's new in the last 7 days
            </span>
            <span className="block text-xs text-slate-500" aria-live="polite">
              {live
                ? `${live.total} articles fetched${live.kept !== null ? ` · ${live.kept} kept after dedupe and relevance checks · writing the summary…` : ""}`
                : refresh?.finished_at
                  ? `Last refreshed ${new Date(refresh.finished_at * 1000).toLocaleString("en-GB")} · ${refresh.fetched} fetched, ${refresh.kept} kept`
                  : "Fresh coverage of the brand and its competitors"}
            </span>
          </span>
        </button>
        <button onClick={start} disabled={running}
          className="inline-flex items-center gap-2 rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D] hover:bg-violet-50 disabled:opacity-50">
          <Icon icon="lucide:refresh-cw" width={15} className={running ? "animate-spin" : ""} />
          {running ? "Refreshing…" : "Refresh last 7 days"}
        </button>
      </div>

      {error && <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {isOpen && (<div id="latest24h-body" className="space-y-4">
      {!live && refresh?.status === "failed" && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">The last refresh failed: {refresh.error}</p>
      )}

      {!live && refresh?.status === "completed" && (
        <>
          {articles.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">No new coverage in the last 7 days</p>
          ) : (
            <>
              <ul className="space-y-2">
                {(refresh.summary?.bullets ?? []).map((b, i) => (
                  <li key={i} className="flex gap-2 text-sm text-slate-700">
                    <Icon icon="lucide:sparkle" width={14} className="mt-1 shrink-0 text-[#5B2C9D]" />
                    <span>{b.text}{b.citations.map((n) => <Cite key={n} n={n} byN={byN} />)}</span>
                  </li>
                ))}
              </ul>
              <div className="grid gap-3 md:grid-cols-2">
                {charts.share && (
                  <div className="rounded-xl border border-slate-200 p-3">
                    <p className="mb-1 text-sm font-semibold text-slate-800">Share of coverage by brand</p>
                    <ChartRenderer spec={charts.share} height={300} palette={BRAND_TINTS} legend />
                  </div>
                )}
                {charts.timeline && (
                  <div className="rounded-xl border border-slate-200 p-3">
                    <p className="mb-1 text-sm font-semibold text-slate-800">Articles per day (UTC)</p>
                    <ChartRenderer spec={charts.timeline} height={300} />
                  </div>
                )}
                {charts.outlets && (
                  <div className="rounded-xl border border-slate-200 p-3 md:col-span-2">
                    <p className="mb-1 text-sm font-semibold text-slate-800">Top outlets in the last 7 days</p>
                    <ChartRenderer spec={charts.outlets} height={260} />
                  </div>
                )}
              </div>
              <div>
                <p className="mb-2 text-sm font-semibold text-slate-800">Top new stories</p>
                <ol className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                  {articles.slice(0, TOP_STORIES).map((a) => (
                    <li key={a.n} className="flex items-start gap-3 px-3 py-2">
                      <img src={favicon(a.url)} alt="" className="mt-0.5 h-4 w-4 rounded-sm" loading="lazy" />
                      <div className="min-w-0">
                        <a href={a.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-slate-800 hover:text-[#5B2C9D] hover:underline">
                          [{a.n}] {a.title}
                        </a>
                        <p className="text-xs text-slate-500">
                          {a.outlet} · {timeOf(a.date)} · {a.brands.join(", ")}{a.copies > 1 ? ` · carried ${a.copies}×` : ""}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            </>
          )}
        </>
      )}
      </div>)}
    </section>
  );
}
