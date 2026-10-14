import { useEffect, useRef, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../services/intel-api";
import type {
  DeliverableCard, DeliverableCitation, DeliverableLogLine, DeliverablePayload, DeliverableProgress, DeliverableSection,
  RepairScope,
} from "../services/intel-api";
import { RunProgress } from "../components/deliverable/RunProgress";
import { StudioDeckCard } from "../components/deliverable/StudioDeckCard";
import { agentSocket } from "../services/ws";
import { useActiveProjectId } from "../context/project-context";
import { ChartRenderer } from "../components/deliverable/ChartRenderer";
import { RunTimeline } from "../components/deliverable/RunTimeline";
import { RunLog } from "../components/deliverable/RunLog";
import { TabPanel, Tabs } from "../components/deliverable/Tabs";
import type { TabItem } from "../components/deliverable/Tabs";

type DeliverableTab = "presentation" | "overview" | "questions" | "quality" | "log";

const MAX_TABLE_ROWS = 12;
const MODULE_ICONS: Record<string, string> = {
  share_kpi: "lucide:pie-chart", volume_trend: "lucide:trending-up", sentiment_split: "lucide:smile",
  outlet_ranking: "lucide:newspaper", reach: "lucide:radio-tower", theme_clusters: "lucide:layout-grid",
  entities: "lucide:users", brand_sov: "lucide:award", top_articles: "lucide:file-text", overview: "lucide:bar-chart-3",
};
const favicon = (domain: string) => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`;

type CiteMap = Record<number, DeliverableCitation>;

/** A citation shows its source site icon (linked), never a bare number. */
function CiteChip({ n, cites }: { n: number; cites: CiteMap }) {
  const c = cites[n];
  if (!c) return null;
  if (!/^https?:\/\//i.test(c.url)) {      // broadcast clip ids and other non-web sources: shown, never linked
    return (
      <span title={`${c.outlet}: ${c.title}`}
        className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white align-middle">
        <Icon icon="lucide:tv" width={12} className="text-slate-500" />
      </span>
    );
  }
  return (
    <a href={c.url} target="_blank" rel="noopener noreferrer" title={`${c.outlet || c.domain}: ${c.title}`}
      className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white align-middle">
      <img src={favicon(c.domain)} alt={c.domain} className="h-3.5 w-3.5 rounded-sm" loading="lazy" />
    </a>
  );
}

function Cards({ cards, cites }: { cards: DeliverableCard[]; cites: CiteMap }) {
  if (!cards.length) return null;
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {cards.map((c, i) => (
        <div key={i} className="rounded-xl border border-violet-100 bg-violet-50/30 p-4">
          <p className="text-sm font-semibold text-violet-800">{c.headline}</p>
          <p className="mt-1 text-xs text-slate-600">{c.text}</p>
          <div className="mt-2">{c.citations.map((n) => <CiteChip key={n} n={n} cites={cites} />)}</div>
        </div>
      ))}
    </div>
  );
}

function LogoStrip({ names, logos }: { names: string[]; logos: Record<string, string> }) {
  const shown = names.filter((n) => logos[n]).slice(0, 8);
  if (!shown.length) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      {shown.map((n) => (
        <img key={n} src={logos[n]} alt={n} title={n} className="h-7 max-w-[90px] object-contain" loading="lazy" />
      ))}
    </div>
  );
}

function SectionView({ section, logos }: { section: DeliverableSection; logos: Record<string, string> }) {
  const icon = MODULE_ICONS[section.module];
  if (section.skipped) {
    return <p className="text-xs text-slate-400">{section.title}: {section.skipped}</p>;
  }
  const brandChart = section.module === "brand_sov" || section.id.endsWith("-brands");
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
        {icon && <Icon icon={icon} width={16} className="text-[#5B2C9D]" />}
        {section.title}
      </p>
      {section.chart && <ChartRenderer spec={section.chart} height={260} />}
      {brandChart && section.chart && <LogoStrip names={section.chart.categories} logos={logos} />}
      {section.table && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="bg-violet-50 text-violet-800">
                {section.table.header.map((h) => <th key={h} className="px-2 py-1.5 font-semibold">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {section.table.rows.slice(0, MAX_TABLE_ROWS).map((row, i) => (
                <tr key={i} className="border-t border-slate-100">
                  {row.map((v, j) => <td key={j} className="px-2 py-1.5 text-slate-600">{v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {section.notes?.filter((n) => n !== "logos").map((n) => (
        <p key={n} className="mt-1 text-[11px] text-slate-400">{n}</p>
      ))}
    </div>
  );
}

const RUN_POLL_MS = 30000;

export function DeliverablesPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId() ?? 1;
  const [payload, setPayload] = useState<DeliverablePayload>({ run: null, sections: [] });
  const [details, setDetails] = useState<Record<string, string>>({});
  const [startError, setStartError] = useState<string | null>(null);
  const [liveLog, setLiveLog] = useState<Record<number, DeliverableLogLine[]>>({});
  const [liveProgress, setLiveProgress] = useState<Record<number, DeliverableProgress>>({});
  const runIdRef = useRef<number | null>(null);
  // null = automatic: the presentation once the deck exists, the run log while it is being made (or when none exists)
  const [chosenTab, setTab] = useState<DeliverableTab | null>(null);
  const [rqTab, setRqTab] = useState("");
  // Every load is numbered; a response that is no longer the newest (a slower poll, or a project the user has
  // left) is dropped instead of overwriting fresher state
  const loadSeq = useRef(0);
  const load = (id: number) => {
    const seq = ++loadSeq.current;
    intelApi.deliverableLatest(id)
      .then((p) => { if (seq === loadSeq.current) setPayload(p); })
      .catch(() => undefined);
  };
  runIdRef.current = payload.run?.id ?? null;

  useEffect(() => {
    agentSocket.connect();
    load(projectId);
    const refresh = () => load(projectId);
    const off = agentSocket.onMessage((msg) => {
      if (msg.project_id !== projectId) return;
      // Events can beat the POST response on Generate: a run id we have not seen yet means "reload the latest"
      if (String(msg.type).startsWith("deliverable_") && msg.run_id !== runIdRef.current) refresh();
      if (msg.type === "deliverable_progress") {
        setLiveProgress((p) => ({ ...p, [msg.run_id]: { pct: msg.pct, stage: msg.stage, label: msg.label,
          started_at: msg.started_at } }));
      } else if (msg.type === "deliverable_log") {
        setLiveLog((l) => ({ ...l, [msg.run_id]: [...(l[msg.run_id] ?? []), { ts: msg.ts, message: msg.message }] }));
      } else if (msg.type === "deliverable_stage") {
        loadSeq.current++;                   // this event is newer than any load still in flight
        setPayload((p) => (p.run && p.run.id === msg.run_id
          ? { ...p, run: { ...p.run, stage: msg.stage, stages: { ...p.run.stages, [msg.stage]: msg.status } } } : p));
        if (msg.detail) setDetails((d) => ({ ...d, [msg.stage]: msg.detail }));
      } else if (msg.type === "deliverable_section" || msg.type === "deliverable_completed"
                 || msg.type === "deliverable_failed") {
        // The socket carries only ids; content comes through the access-checked REST route
        refresh();
      }
    });
    // A reconnect means events may have been missed (a server restart can end the run while the socket is down)
    const offStatus = agentSocket.onStatus((connected) => { if (connected) refresh(); });
    return () => { off(); offStatus(); loadSeq.current++; };   // responses for the old project are dropped
  }, [projectId]);

  // a new project, or a run or repair finishing, hands the tab back to the automatic choice: the deck shows as soon
  // as it exists
  const runStatus = payload.run?.status;
  const prevStatus = useRef(runStatus);
  useEffect(() => {
    if (prevStatus.current === "running" && runStatus !== "running") setTab(null);
    prevStatus.current = runStatus;
  }, [runStatus]);
  useEffect(() => { setTab(null); }, [projectId]);

  // Safety net while a run is in progress: the stored state, re-read now and then, catches a run that ended unseen
  const isRunning = payload.run?.status === "running";
  useEffect(() => {
    if (!isRunning) return;
    const timer = window.setInterval(() => {
      load(projectId);
    }, RUN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [isRunning, projectId]);

  const generate = async () => {
    setStartError(null);
    setTab(null);                         // the new run streams in the run log, then shows its deck
    setDetails({});
    try {
      const { run_id } = await intelApi.deliverableRun(projectId);
      runIdRef.current = run_id;
      setPayload((p) => (p.run?.id === run_id ? p : { run: { id: run_id, project_id: projectId, status: "running",
        stage: "gate", stages: {}, pptx_path: null, docx_path: null, error: null }, sections: [] }));
    } catch (e) {
      setStartError(e instanceof Error ? e.message : "Could not start the deliverable run");
    }
  };

  const repair = async (scope: RepairScope) => {
    const current = payload.run;
    if (!current) return;
    setStartError(null);
    // the repair's lines continue the stored log, so the stream starts from it
    setLiveLog((l) => ({ ...l, [current.id]: logLines }));
    try {
      await intelApi.deliverableRepair(projectId, current.id, scope);
      setPayload((p) => (p.run?.id === current.id ? { ...p, run: { ...p.run, status: "running", stage: "repair" } } : p));
      setTab("log");                      // the repair streams where the run did
    } catch (e) {
      setStartError(e instanceof Error ? e.message : "Could not start the repair");
    }
  };

  const run = payload.run;
  const byId = (id: string) => payload.sections.find((s) => s.id === id);
  const rqIds = [...new Set(payload.sections.map((s) => s.rq_id).filter(Boolean))] as string[];
  const collection = byId("data-collection")?.data;
  const summary = byId("executive-summary");
  const question = (rq: string) => summary?.answers?.find((a) => a.rq_id === rq)?.question ?? "";
  const overview = byId("overview");
  const qc = byId("qc")?.report;
  const visuals = byId("visuals");
  const logos = visuals?.logos ?? {};
  const cites: CiteMap = Object.fromEntries((byId("citations")?.citations ?? []).map((c) => [c.n, c]));
  const running = run?.status === "running";
  const repairing = running && run?.stage === "repair";
  // The stream and the stored log can each be ahead (reload mid-run vs. a line not yet refetched): show the longer
  const stored = byId("log")?.lines ?? [];
  const streamed = (run && liveLog[run.id]) || [];
  const logLines = streamed.length > stored.length ? streamed : stored;
  const savedProgress = byId("progress");
  const fromStore: DeliverableProgress | null = savedProgress && savedProgress.pct !== undefined
    ? { pct: savedProgress.pct, stage: savedProgress.stage ?? "", label: savedProgress.label ?? "",
        started_at: savedProgress.started_at ?? 0 } : null;
  const fromStream = run ? liveProgress[run.id] : undefined;
  const progress = fromStream && (!fromStore || fromStream.pct >= fromStore.pct) ? fromStream : fromStore;

  const studio = byId("studio");
  const hasDeck = run?.status === "completed" && !!studio;
  const tab: DeliverableTab = chosenTab ?? (hasDeck ? "presentation" : "log");
  const openChecks = (studio?.validation ?? []).filter((c) => c.status !== "pass").length
    + (studio?.checklist ?? []).filter((r) => r.status !== "covered").length;
  const activeRq = rqIds.includes(rqTab) ? rqTab : rqIds[0] ?? "";
  const tabs: TabItem<DeliverableTab>[] = [
    { id: "log", label: "Run log", icon: "lucide:scroll-text",
      badge: running ? <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" aria-label="live" /> : undefined },
    { id: "presentation", label: "Presentation", icon: "lucide:presentation",
      badge: openChecks > 0 ? <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-semibold text-amber-700">{openChecks}</span> : undefined },
    { id: "overview", label: "Overview", icon: "lucide:layout-dashboard" },
    { id: "questions", label: `Questions${rqIds.length ? ` (${rqIds.length})` : ""}`, icon: "lucide:message-circle-question" },
    { id: "quality", label: "Quality", icon: "lucide:shield-check" },
  ];
  const generateLabel = repairing ? "Repairing..." : running ? "Generating..." : run ? "Regenerate" : "Generate Deliverable";
  const rqSections = payload.sections.filter((s) => s.rq_id === activeRq && s.module !== "insights");
  const rqInsights = byId(`${activeRq.toLowerCase()}-insights`)?.insights ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-10">
      <div className="relative overflow-hidden rounded-2xl border border-violet-100 bg-gradient-to-r from-violet-50 to-white">
        {visuals?.hero?.url && (
          <img src={visuals.hero.url} alt="" className="absolute inset-y-0 right-0 h-full w-1/2 object-cover opacity-90" />
        )}
        <div className="relative flex items-start justify-between gap-4 bg-gradient-to-r from-white via-white/95 to-transparent p-6">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-900">
              Deliverables
              {visuals?.country && <Icon icon={`circle-flags:${visuals.country}`} width={22} />}
            </h1>
            <p className="mt-1 text-sm text-slate-500">Charts, tables, cited insights and a brand-styled deck, built from your approved data</p>
            <LogoStrip names={Object.keys(logos)} logos={logos} />
          </div>
          <button onClick={generate} disabled={running}
            className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {generateLabel}
          </button>
        </div>
      </div>

      {(startError || (run?.status === "failed" && run.error)) && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{startError || run?.error}</div>
      )}

      {run && progress && tab !== "log" && (running || run.status === "failed") && (
        <RunProgress progress={progress} isLive={running} failed={run.status === "failed"} />
      )}

      {run && (
        <>
          <Tabs tabs={tabs} active={tab} onChange={setTab} label="Deliverable sections" />

          {tab === "presentation" && (
            <TabPanel id="presentation">
              {studio && run.status !== "failed" ? (
                <StudioDeckCard projectId={projectId} runId={run.id} studio={studio} isRepairing={repairing} onRepair={repair} />
              ) : (
                <p className="rounded-xl border border-dashed border-slate-200 p-6 text-sm text-slate-500">
                  {running ? "The presentation appears here when the run reaches the deck." : "No presentation for this run."}
                </p>
              )}
              {run.status === "completed" && (
                <div className="flex flex-wrap gap-3">
                  <a href={intelApi.deliverableDownloadUrl(projectId, run.id, "pptx")}
                    className="inline-flex items-center gap-2 rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white">
                    <Icon icon="lucide:presentation" width={16} /> Classic deck (.pptx)</a>
                  <a href={intelApi.deliverableDownloadUrl(projectId, run.id, "docx")}
                    className="inline-flex items-center gap-2 rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D]">
                    <Icon icon="lucide:file-text" width={16} /> Word brief (.docx)</a>
                  <a href={intelApi.deliverableDownloadUrl(projectId, run.id, "xlsx")}
                    className="inline-flex items-center gap-2 rounded-lg border border-[#5B2C9D] px-4 py-2 text-sm font-medium text-[#5B2C9D]">
                    <Icon icon="lucide:table" width={16} /> Data tables (.xlsx)</a>
                </div>
              )}
            </TabPanel>
          )}

          {tab === "overview" && (
            <TabPanel id="overview">
              {collection && (
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {[["Files", collection.files, "lucide:files"], ["Unique URLs", collection.unique_urls, "lucide:link"],
                    ["Stories", collection.stories, "lucide:newspaper"], ["Base N", collection.base_n, "lucide:sigma"]].map(([label, value, icon]) => (
                    <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-4 text-center">
                      <Icon icon={String(icon)} width={18} className="mx-auto text-[#5B2C9D]" />
                      <p className="text-2xl font-bold text-[#5B2C9D]">{typeof value === "number" ? value.toLocaleString("en-US") : value}</p>
                      <p className="text-xs text-slate-500">{label}</p>
                    </div>
                  ))}
                </div>
              )}
              {summary?.answers && (
                <div className="grid gap-3 md:grid-cols-3">
                  {summary.answers.map((a) => (
                    <button key={a.rq_id} type="button" onClick={() => { setRqTab(a.rq_id); setTab("questions"); }}
                      className="rounded-xl border border-violet-100 bg-white p-4 text-left transition hover:border-violet-300 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#5B2C9D]">
                      <p className="text-3xl font-bold text-[#5B2C9D]">{a.value}</p>
                      <p className="text-xs font-semibold text-slate-700">{a.rq_id}</p>
                      <p className="text-xs text-slate-600">{a.question}</p>
                      <p className="mt-1 text-xs text-slate-500">{a.answer}</p>
                    </button>
                  ))}
                </div>
              )}
              {overview?.chart && <SectionView section={overview} logos={logos} />}
              {summary?.takeaways && summary.takeaways.length > 0 && (
                <section className="space-y-3">
                  <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
                    <Icon icon="lucide:lightbulb" width={18} className="text-[#5B2C9D]" /> Key takeaways
                  </h2>
                  <Cards cards={summary.takeaways} cites={cites} />
                </section>
              )}
              {!collection && !summary && <p className="text-sm text-slate-500">The overview fills in as the run computes its charts.</p>}
            </TabPanel>
          )}

          {tab === "questions" && (
            <TabPanel id="questions">
              {rqIds.length === 0 ? (
                <p className="text-sm text-slate-500">Each research question's charts and insights appear here as they are computed.</p>
              ) : (
                <>
                  <Tabs tabs={rqIds.map((rq) => ({ id: rq, label: rq, icon: "lucide:circle-help" }))} active={activeRq}
                    onChange={setRqTab} label="Research questions" size="sm" />
                  <section className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50/40 p-5">
                    <h2 className="text-base font-semibold text-slate-900">{activeRq}{question(activeRq) ? `: ${question(activeRq)}` : ""}</h2>
                    <Cards cards={rqInsights} cites={cites} />
                    <div className="grid gap-3 md:grid-cols-2">
                      {rqSections.map((s) => <SectionView key={s.id} section={s} logos={logos} />)}
                    </div>
                  </section>
                </>
              )}
            </TabPanel>
          )}

          {tab === "quality" && (
            <TabPanel id="quality">
              {qc ? (
                <div className={`rounded-xl border p-4 text-sm ${qc.ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                  {qc.ready ? "Ready" : `${qc.facts.length} fact issues · ${qc.layout.length} layout issues`}
                  <span className="ml-2 text-xs opacity-80">{qc.fixed} auto-fixed</span>
                </div>
              ) : <p className="text-sm text-slate-500">The fact check and layout check run after the slides are built.</p>}
              {qc && qc.pngs.length > 0 && (
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {qc.pngs.map((_, i) => (
                    <img key={i} loading="lazy" alt={`Slide ${i + 1}`} className="rounded-lg border border-slate-200"
                      src={intelApi.deliverableThumbUrl(projectId, run.id, i + 1)} />
                  ))}
                </div>
              )}
            </TabPanel>
          )}

          {tab === "log" && (
            <TabPanel id="log">
              {progress && <RunProgress progress={progress} isLive={running} failed={run.status === "failed"} />}
              <RunTimeline stages={run.stages ?? {}} details={details} />
              <RunLog lines={logLines} isLive={running} />
            </TabPanel>
          )}
        </>
      )}

      <div className="flex items-center justify-between">
        <button onClick={() => onNavigate("data-sources")} className="text-sm font-medium text-slate-500 hover:text-slate-700">
          Back to Data Sources
        </button>
        <button onClick={generate} disabled={running}
          className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {generateLabel}
        </button>
      </div>
    </div>
  );
}
