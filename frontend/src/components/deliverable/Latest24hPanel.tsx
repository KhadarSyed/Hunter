import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { Latest24hArticle, Latest24hRefresh, Latest24hSourceCount } from "../../services/intel-api";
import { agentSocket } from "../../services/ws";
import { ChartRenderer } from "./ChartRenderer";

type Live = { refreshId: number; counts: Record<string, Latest24hSourceCount>; total: number; kept: number | null };

const SOURCE_LABELS: Record<string, string> = { serpapi: "SerpAPI", tavily: "Tavily", google_news_rss: "Google News" };
const TOP_STORIES = 10;
// one distinct light tint per brand (the house palette has four, and the brand + five competitors need six)
const BRAND_TINTS = ["B794E8", "F9B98E", "8FB8E0", "8FD3B6", "F2A7C3", "F6D57A", "A3A8F0", "9ED9E8"];
const domainOf = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; } };
const favicon = (url: string) => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domainOf(url))}&sz=64`;
const timeOf = (date: string) => {
  const d = new Date(date);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

function SourceLine({ c }: { c: Latest24hSourceCount }) {
  const failed = c.status === "failed";
  return (
    <li className={`flex items-center gap-2 text-sm ${failed ? "text-red-600" : "text-slate-700"}`}>
      <Icon icon={failed ? "lucide:circle-x" : c.status === "done" ? "lucide:circle-check" : "lucide:loader-circle"} width={15}
        className={c.status === "fetching" ? "animate-spin text-[#5B2C9D]" : failed ? "" : "text-emerald-600"} />
      <span className="font-medium">{c.label}:</span>
      {failed ? <span>failed</span>
        : <span>{c.status === "fetching" ? "fetching… " : ""}<b className="tabular-nums">{c.found}</b> found</span>}
    </li>
  );
}

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
 * shows a cited "What's new" summary, charts and the top new stories. The latest refresh is reloaded from the server. */
export function Latest24hPanel({ projectId }: { projectId: number }) {
  const [refresh, setRefresh] = useState<Latest24hRefresh | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        const base: Live = l && l.refreshId === msg.refresh_id ? l : { refreshId: msg.refresh_id, counts: {}, total: 0, kept: null };
        if (msg.phase === "filtered") return { ...base, total: msg.total, kept: msg.kept };
        return { ...base, total: Math.max(base.total, msg.total ?? 0),
          counts: { ...base.counts, [msg.source]: { label: SOURCE_LABELS[msg.source] ?? msg.source, status: msg.status, found: msg.found } } };
      });
    });
    return () => { current = false; off(); };
  }, [projectId]);

  const start = async () => {
    setError(null);
    try {
      const { refresh_id } = await intelApi.latest24hRefresh(projectId);
      setLive((l) => (l && l.refreshId === refresh_id ? l : { refreshId: refresh_id, counts: {}, total: 0, kept: null }));
    } catch (e) {
      setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "Could not start the 24h refresh");
    }
  };

  const running = !!live || refresh?.status === "running";
  const articles = refresh?.articles ?? [];
  const byN = Object.fromEntries(articles.map((a) => [a.n, a]));
  const charts = refresh?.charts ?? {};
  const counts = live?.counts ?? {};

  return (
    <section className="space-y-4 rounded-2xl border border-violet-100 bg-white p-5" aria-labelledby="latest24h-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="latest24h-heading" className="flex items-center gap-2 text-base font-semibold text-slate-900">
            <Icon icon="lucide:radio" width={18} className="text-[#5B2C9D]" /> What's new in the last 24h
          </h2>
          <p className="text-xs text-slate-500">
            {refresh?.finished_at && !live
              ? `Last refreshed ${new Date(refresh.finished_at * 1000).toLocaleString("en-GB")} · ${refresh.fetched} fetched, ${refresh.kept} kept`
              : "Fresh coverage of the brand and its competitors from SerpAPI, Tavily and Google News"}
          </p>
        </div>
        <button onClick={start} disabled={running}
          className="inline-flex items-center gap-2 rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D] hover:bg-violet-50 disabled:opacity-50">
          <Icon icon="lucide:refresh-cw" width={15} className={running ? "animate-spin" : ""} />
          {running ? "Refreshing…" : "Refresh latest 24h"}
        </button>
      </div>

      {error && <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {live && (
        <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-4" aria-live="polite">
          <ul className="space-y-1">
            {Object.keys(SOURCE_LABELS).map((s) => (
              <SourceLine key={s} c={counts[s] ?? { label: SOURCE_LABELS[s], status: "fetching", found: 0 }} />
            ))}
          </ul>
          <p className="mt-3 text-sm text-slate-800"><b className="tabular-nums">{live.total}</b> articles fetched</p>
          {live.kept !== null
            ? <p className="text-sm font-semibold text-[#5B2C9D]"><span className="tabular-nums">{live.kept}</span> kept after dedupe and relevance checks · writing the summary…</p>
            : <p className="text-xs text-slate-500">Dedupe and relevance checks run when every source is done</p>}
        </div>
      )}

      {!live && refresh?.status === "failed" && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">The last refresh failed: {refresh.error}</p>
      )}

      {!live && refresh?.status === "completed" && (
        <>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {Object.entries(refresh.counts).map(([s, c]) => (
              <li key={s} className={c.status === "failed" ? "text-red-600" : ""}>{c.label}: {c.status === "failed" ? "failed" : `${c.found} found`}</li>
            ))}
          </ul>
          {articles.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">No new coverage in the last 24h</p>
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
                    <p className="mb-1 text-sm font-semibold text-slate-800">Share of 24h coverage by brand</p>
                    <ChartRenderer spec={charts.share} height={300} palette={BRAND_TINTS} legend />
                  </div>
                )}
                {charts.timeline && (
                  <div className="rounded-xl border border-slate-200 p-3">
                    <p className="mb-1 text-sm font-semibold text-slate-800">Articles per hour (UTC)</p>
                    <ChartRenderer spec={charts.timeline} height={300} />
                  </div>
                )}
                {charts.outlets && (
                  <div className="rounded-xl border border-slate-200 p-3 md:col-span-2">
                    <p className="mb-1 text-sm font-semibold text-slate-800">Top outlets in the last 24h</p>
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
    </section>
  );
}
