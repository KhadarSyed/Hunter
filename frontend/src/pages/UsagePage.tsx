import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@iconify/react";
import { BrandLogo } from "../components/BrandLogo";
import { useAuth } from "../context/auth-context";
import { intelApi } from "../services/intel-api";
import type { UsageCall, UsageCallsPage, UsageLiveRow, UsageQuery, UsageSummary } from "../types/usage";
import { LiveFeed } from "../components/usage/LiveFeed";
import { useAgentSocket } from "../hooks/useAgentSocket";
import { KpiTiles } from "../components/usage/KpiTiles";
import { TopProjects } from "../components/usage/TopProjects";
import { SummaryTable } from "../components/usage/SummaryTable";
import { CallLogTable, CALL_PAGE_SIZE } from "../components/usage/CallLogTable";
import { ProviderLogo } from "../components/usage/ProviderLogo";
import { UsageTrendChart } from "../components/usage/UsageTrendChart";
import { UsageBarChart } from "../components/usage/UsageBarChart";
import { StageDrillDown, StageTable } from "../components/usage/StageDrillDown";
import { UsageFilters, presetRange, type Preset, type SelectOption, type UsageFilterState } from "../components/usage/UsageFilters";
import { STAGE_ICONS, STAGE_LABELS, providerLabel, stageLabel, subStageLabel } from "../components/usage/format";

const PRESET_IDS: Preset[] = ["today", "7d", "30d", "month", "custom"];
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const EXPORT_PAGE = 200;   // the API's /calls limit

const intParam = (v: string | null): number | null => {
  const n = Number(v);
  return v && Number.isInteger(n) && n > 0 ? n : null;
};

/** Filters from the URL query (?project= comes from a project card's usage icon); missing dates use the preset. */
function filtersFromUrl(): { filters: UsageFilterState; logModel: string; logSubStage: string | null } {
  const q = new URLSearchParams(window.location.search);
  const presetParam = q.get("preset") as Preset | null;
  const from = q.get("from") ?? "", to = q.get("to") ?? "";
  const hasDates = DAY_RE.test(from) && DAY_RE.test(to);
  const preset: Preset = presetParam && PRESET_IDS.includes(presetParam) ? presetParam : hasDates ? "custom" : "30d";
  // a preset is re-evaluated on load ("Today" is today), a custom range is kept as written
  const range = preset === "custom" && hasDates ? { from, to } : presetRange(preset === "custom" ? "30d" : preset);
  return {
    filters: {
      preset: preset === "custom" && !hasDates ? "30d" : preset, ...range,
      org: intParam(q.get("org")), project: intParam(q.get("project")),
      stage: q.get("stage") ?? "", model: q.get("model") ?? "",
    },
    logModel: q.get("log_model") ?? "",
    logSubStage: q.get("log_sub"),
  };
}

/** The Org filter is a super_admin control: anyone else never sends org_id, whatever the URL says. */
function toQuery(f: UsageFilterState, isSuper: boolean): UsageQuery {
  return { date_from: f.from, date_to: f.to, org_id: isSuper ? f.org : null, project_id: f.project, stage: f.stage, model: f.model };
}

function csvCell(v: unknown): string {
  let s = v === null || v === undefined ? "" : String(v);
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;   // keep spreadsheet apps from running it as a formula
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
const csvRow = (cells: unknown[]): string => cells.map(csvCell).join(",");

function buildCsv(f: UsageFilterState, s: UsageSummary, calls: UsageCall[]): string {
  const lines = [
    csvRow(["Usage & cost", `${f.from} to ${f.to} (UTC days)`]),
    "",
    csvRow(["Model summary"]),
    csvRow(["Model", "Provider", "Deployment type", "Calls", "Input tokens", "Cached input tokens", "Output tokens", "Total tokens", "Cost (USD)"]),
    ...s.by_model.map((m) => csvRow([m.model, providerLabel(m.provider), m.deployment_type, m.calls, m.input_tokens,
      m.cached_input_tokens, m.output_tokens, m.total_tokens, m.cost_usd])),
    "",
    csvRow(["Top projects by token usage"]),
    csvRow(["Rank", "Project", "Owner", "Input tokens", "Cached input tokens", "Output tokens", "Total tokens", "Share %", "Calls", "Top stage", "Models", "Cost (USD)"]),
    ...s.by_project.map((p, i) => csvRow([i + 1, p.project_name ?? (p.project_id === null ? "No project" : `#${p.project_id}`), p.owner_name,
      p.input_tokens, p.cached_input_tokens, p.output_tokens, p.total_tokens, p.share_pct, p.calls, stageLabel(p.top_stage),
      p.models.map((m) => m.model).join("; "), p.cost_usd])),
    "",
    csvRow(["By stage"]),
    csvRow(["Stage", "Calls", "Input tokens", "Cached input tokens", "Output tokens", "Total tokens", "Cost (USD)"]),
    ...s.by_stage.map((st) => csvRow([stageLabel(st.stage), st.calls, st.input_tokens, st.cached_input_tokens,
      st.output_tokens, st.total_tokens, st.cost_usd])),
    "",
    csvRow(["Sub-stages"]),
    csvRow(["Stage", "Sub-stage", "Calls", "Input tokens", "Cached input tokens", "Output tokens", "Total tokens", "Cost (USD)",
      "Avg latency (ms)", "Models"]),
    ...s.by_stage.flatMap((st) => st.sub_stages.map((x) => csvRow([stageLabel(st.stage), subStageLabel(x.sub_stage), x.calls,
      x.input_tokens, x.cached_input_tokens, x.output_tokens, x.total_tokens, x.cost_usd, x.avg_latency_ms,
      x.models.map((m) => m.model).join("; ")]))),
    "",
    csvRow(["Call log"]),
    csvRow(["Date and time (UTC)", "Project", "Stage", "Sub-stage", "Provider", "Model", "Kind", "Input tokens", "Cached input tokens", "Output tokens",
      "Total tokens", "Cost (USD)", "Latency (ms)", "Cache hit", "Failed"]),
    ...calls.map((c) => csvRow([new Date(c.ts * 1000).toISOString(), c.project_name ?? c.project_id, stageLabel(c.stage), c.sub_stage ? subStageLabel(c.sub_stage) : "", providerLabel(c.provider),
      c.model, c.kind, c.input_tokens, c.cached_input_tokens, c.output_tokens, c.total_tokens, c.cost_usd, c.latency_ms,
      c.cache_hit ? "yes" : "no", c.error ? "yes" : "no"])),
  ];
  return lines.join("\r\n");
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob(["﻿", text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);   // after the browser has started the download
}

const errText = (e: unknown, fallback: string): string => (e instanceof Error ? e.message : fallback);

/** Usage & cost: LLM tokens and cost per model, stage and project over a date range, for the caller's role scope. */
export function UsagePage(_props: { onNavigate: (page: string) => void }) {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const initial = useMemo(filtersFromUrl, []);
  const [filters, setFilters] = useState<UsageFilterState>(initial.filters);
  const [logModel, setLogModel] = useState(initial.logModel);   // the summary-table row that narrows the call log only
  const [logSubStage, setLogSubStage] = useState<string | null>(initial.logSubStage);   // narrows the call log; "" = unattributed
  const [openStage, setOpenStage] = useState<string | null>(null);   // the stage whose drill-down is open
  const callLogHeading = useRef<HTMLHeadingElement>(null);
  // a project's Top stage chip: the stage to open once that project's summary has landed (never range-wide data)
  const pendingStage = useRef<{ project: number; stage: string } | null>(null);
  const [callOffset, setCallOffset] = useState(0);

  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  const [calls, setCalls] = useState<UsageCallsPage | null>(null);
  const [callsLoading, setCallsLoading] = useState(true);
  const [callsError, setCallsError] = useState("");
  const [retry, setRetry] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  const [projects, setProjects] = useState<{ id: number; name: string; brand: string | null; org_id: number | null }[]>([]);
  const [orgs, setOrgs] = useState<{ id: number; name: string }[]>([]);
  const [knownModels, setKnownModels] = useState<{ provider: string; model: string }[]>([]);
  // Live: each recorded call arrives on the socket; tiles move at once, the rest re-reads quietly every 10 s at most
  const [liveRows, setLiveRows] = useState<UsageLiveRow[]>([]);
  const [paused, setPaused] = useState(false);
  const [liveTick, setLiveTick] = useState(0);
  const quietSummary = useRef(false);
  const quietCalls = useRef(false);
  const liveTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(liveTimer.current), []);

  // Review Focus 3: each fetch takes the next id; a response whose id is no longer the latest is dropped.
  // Cleanup bumps the id too, so a response arriving after unmount or a filter change is ignored.
  const summarySeq = useRef(0);
  const callsSeq = useRef(0);

  const query = useMemo(() => toQuery(filters, isSuper), [filters, isSuper]);
  const queryKey = JSON.stringify(query);
  const callQuery = useMemo(() => ({ ...query, model: logModel || query.model, sub_stage: logSubStage }), [query, logModel, logSubStage]);
  const callKey = JSON.stringify(callQuery);

  const updateFilters = (next: UsageFilterState) => {
    // a new Org drops a Project filter that is not one of that org's projects
    const orphan = next.org !== filters.org && next.org !== null && next.project !== null && projects.length > 0
      && !projects.some((p) => p.id === next.project && p.org_id === next.org);
    setFilters(orphan ? { ...next, project: null } : next);
    if (pendingStage.current && next.project !== pendingStage.current.project) pendingStage.current = null;
    if (next.stage !== filters.stage) setLogSubStage(null);   // a sub-stage only means something within its stage
    setCallOffset(0);
  };
  const pickLogModel = (m: string) => { setLogModel(m); setCallOffset(0); };
  const pickLogSubStage = (sub: string | null) => { setLogSubStage(sub); setCallOffset(0); };
  const showStageCalls = (stage: string, sub: string | null) => {
    updateFilters({ ...filters, stage });
    pickLogSubStage(sub);
    setOpenStage(null);
    // after the modal has closed and handed focus back to its opener: bring the call log into view
    setTimeout(() => callLogHeading.current?.focus(), 0);
  };
  const openStageRow = summary?.by_stage.find((s) => s.stage === openStage) ?? null;
  const openProjectStage = (projectId: number | null, stage: string) => {
    if (projectId === null || projectId === filters.project) { setOpenStage(stage); return; }
    pendingStage.current = { project: projectId, stage };
    updateFilters({ ...filters, project: projectId });
  };
  const projectName = (id: number): string =>
    projects.find((p) => p.id === id)?.name ?? summary?.by_project.find((p) => p.project_id === id)?.project_name ?? `#${id}`;
  const stageScope = filters.project === null ? "All projects in range" : `Project: ${projectName(filters.project)}`;

  useEffect(() => {
    const id = ++summarySeq.current;
    if (!quietSummary.current) setSummaryLoading(true);
    quietSummary.current = false;
    setSummaryError("");
    intelApi.usageSummary(query).then((s) => {
      if (id !== summarySeq.current) return;
      setSummary(s);
      const pending = pendingStage.current;
      if (pending && query.project_id === pending.project) {
        pendingStage.current = null;
        setOpenStage(pending.stage);
      }
      if (!query.model) setKnownModels(s.by_model.map((m) => ({ provider: m.provider, model: m.model })));
    }).catch((e) => {
      if (id !== summarySeq.current) return;
      pendingStage.current = null;
      setSummaryError(errText(e, "Could not load usage"));
    }).finally(() => {
      if (id === summarySeq.current) setSummaryLoading(false);
    });
    return () => { summarySeq.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, retry, liveTick]);

  useEffect(() => {
    const id = ++callsSeq.current;
    if (!quietCalls.current) setCallsLoading(true);
    quietCalls.current = false;
    setCallsError("");
    intelApi.usageCalls(callQuery, callOffset, CALL_PAGE_SIZE).then((c) => {
      if (id === callsSeq.current) setCalls(c);
    }).catch((e) => {
      if (id === callsSeq.current) setCallsError(errText(e, "Could not load the call log"));
    }).finally(() => {
      if (id === callsSeq.current) setCallsLoading(false);
    });
    return () => { callsSeq.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callKey, callOffset, retry, liveTick]);

  const todayUtc = new Date().toISOString().slice(0, 10);
  const matchesFilters = (r: UsageLiveRow): boolean =>
    (filters.preset !== "custom" || filters.to >= todayUtc)    // a preset range always ends now, even past midnight
    && (query.project_id == null || r.project_id === query.project_id)
    && (query.org_id == null || r.org_id === query.org_id)
    && (!query.stage || r.stage === query.stage)
    && (!query.model || r.model === query.model);
  const { connected } = useAgentSocket((m) => {
    if (m.type !== "llm_usage" || paused) return;
    const r = m as unknown as UsageLiveRow;
    if (!matchesFilters(r)) return;
    setLiveRows((prev) => [r, ...prev].slice(0, 50));
    setSummary((s) => s && {
      ...s, kpis: {
        ...s.kpis, calls: s.kpis.calls + (r.cache_hit ? 0 : 1), cost_usd: s.kpis.cost_usd + (r.cost_usd || 0),
        cache_hits: s.kpis.cache_hits + (r.cache_hit ? 1 : 0),
        nvidia_credits: s.kpis.nvidia_credits + (r.provider === "nvidia" ? Number(r.credits) || 0 : 0),
        input_tokens: s.kpis.input_tokens + r.input_tokens, output_tokens: s.kpis.output_tokens + r.output_tokens,
        cached_input_tokens: s.kpis.cached_input_tokens + r.cached_input_tokens, total_tokens: s.kpis.total_tokens + r.total_tokens,
      },
    });
    if (liveTimer.current === undefined) {
      liveTimer.current = window.setTimeout(() => {
        liveTimer.current = undefined;
        quietSummary.current = true;
        quietCalls.current = true;
        setLiveTick((t) => t + 1);
      }, 10_000);
    }
  });

  // Mirror every filter into the URL so a refresh or a shared link reopens the same view.
  useEffect(() => {
    const q = new URLSearchParams({ preset: filters.preset, from: filters.from, to: filters.to });
    if (isSuper && filters.org !== null) q.set("org", String(filters.org));
    if (filters.project !== null) q.set("project", String(filters.project));
    if (filters.stage) q.set("stage", filters.stage);
    if (filters.model) q.set("model", filters.model);
    if (logModel) q.set("log_model", logModel);
    if (logSubStage !== null) q.set("log_sub", logSubStage);
    window.history.replaceState(window.history.state, "", `${window.location.pathname}?${q}`);
  }, [filters, logModel, logSubStage, isSuper]);

  // Project options: the role-scoped projects list (the same list the Projects page shows).
  useEffect(() => {
    let alive = true;
    intelApi.listProjects().then((list) => {
      if (alive) setProjects(list.map((p) => ({ id: p.id, name: p.project_name, brand: p.brand, org_id: p.org_id ?? null })));
    }).catch(() => { /* the filter still works from the URL; the options just stay empty */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!isSuper) return;
    let alive = true;
    intelApi.listOrganizations().then((list) => {
      if (alive) setOrgs(list.filter((o) => !o.archived_at).map((o) => ({ id: o.id, name: o.name })));
    }).catch(() => {});
    return () => { alive = false; };
  }, [isSuper]);

  const orgOptions: SelectOption[] | null = isSuper
    ? orgs.map((o) => ({ value: String(o.id), label: o.name, icon: <Icon icon="lucide:building-2" width={16} aria-hidden className="text-slate-500" /> }))
    : null;
  const projectOptions: SelectOption[] = projects
    .filter((p) => !isSuper || filters.org === null || p.org_id === filters.org)
    .map((p) => ({ value: String(p.id), label: p.name, icon: <BrandLogo brandName={p.brand ?? ""} projectId={p.id} size={16} /> }));
  if (filters.project !== null && !projectOptions.some((o) => o.value === String(filters.project))) {
    projectOptions.unshift({ value: String(filters.project), label: `Project #${filters.project}` });
  }
  const stageOptions: SelectOption[] = Object.keys(STAGE_LABELS).map((s) => ({
    value: s, label: STAGE_LABELS[s], icon: <Icon icon={STAGE_ICONS[s]} width={16} aria-hidden className="text-[#5B2C9D]" />,
  }));
  const models = filters.model && !knownModels.some((m) => m.model === filters.model)
    ? [...knownModels, { provider: summary?.by_model[0]?.provider ?? "", model: filters.model }] : knownModels;
  const modelOptions: SelectOption[] = models.map((m) => ({
    value: m.model, label: m.model, icon: <ProviderLogo provider={m.provider} model={m.model} nameless />,
  }));

  const exportCsv = async () => {
    if (!summary) return;
    setExporting(true);
    setExportError("");
    try {
      const all: UsageCall[] = [];
      for (let offset = 0; ; offset += EXPORT_PAGE) {
        const page = await intelApi.usageCalls(callQuery, offset, EXPORT_PAGE);
        all.push(...page.rows);
        if (page.rows.length < EXPORT_PAGE || all.length >= page.total) break;
      }
      download(`usage-${filters.from}-to-${filters.to}.csv`, buildCsv(filters, summary, all));
    } catch (e) {
      setExportError(errText(e, "Could not export"));
    } finally {
      setExporting(false);
    }
  };

  const isEmpty = summary !== null && summary.kpis.calls === 0;

  return (
    <div className="min-h-full bg-gradient-to-br from-slate-100 via-slate-50 to-violet-50 px-8 py-8">
      <nav className="text-sm text-slate-500">
        Reports <span className="mx-2 text-slate-300">›</span>
        <span className="font-semibold text-slate-900">Usage & cost</span>
      </nav>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Usage & cost</h1>
          <p className="mt-1 text-sm text-slate-600">Tokens and cost of every LLM call, per model, stage and project.</p>
        </div>
        <div className="flex items-center gap-3">
          {exportError && <span role="alert" className="text-sm text-red-600">{exportError}</span>}
          <button
            type="button"
            onClick={exportCsv}
            disabled={!summary || summaryLoading || exporting || isEmpty}
            className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-md transition-colors hover:bg-slate-800 disabled:opacity-50"
          >
            <Icon icon={exporting ? "lucide:loader-2" : "lucide:download"} width={16} aria-hidden className={exporting ? "animate-spin" : ""} />
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
        </div>
      </div>

      <div className="mt-6">
        <UsageFilters value={filters} onChange={updateFilters} orgOptions={orgOptions}
          projectOptions={projectOptions} stageOptions={stageOptions} modelOptions={modelOptions} />
      </div>

      <div className="mt-6">
        <LiveFeed rows={liveRows} paused={paused} connected={connected} onTogglePause={() => setPaused((v) => !v)}
          projectName={projectName} />
      </div>

      {summaryError ? (
        <div role="alert" className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          {summaryError} <button type="button" onClick={() => setRetry((r) => r + 1)} className="ml-2 font-semibold underline">Retry</button>
        </div>
      ) : summary === null ? (
        <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4" aria-busy="true">
          {Array.from({ length: 5 }, (_, i) => <div key={i} className="h-32 animate-pulse rounded-3xl bg-white/70 ring-1 ring-slate-900/5" />)}
        </div>
      ) : isEmpty ? (
        <div className="mt-6 flex flex-col items-center rounded-3xl border-2 border-dashed border-slate-300 bg-white/60 px-6 py-16 text-center">
          <Icon icon="lucide:receipt" width={36} aria-hidden className="text-slate-400" />
          <p className="mt-3 text-base font-semibold text-slate-700">No LLM calls in this range</p>
          <p className="mt-1 text-sm text-slate-500">Pick a wider date range or clear a filter.</p>
        </div>
      ) : (
        <div className={`mt-6 space-y-6 transition-opacity ${summaryLoading ? "opacity-60" : ""}`} aria-busy={summaryLoading}>
          <KpiTiles kpis={summary.kpis} live={connected && !paused} />

          {filters.project === null && (
            <TopProjects projects={summary.by_project} onPick={(id) => updateFilters({ ...filters, project: id })} onStage={openProjectStage} />
          )}

          <div data-slot="usage-charts" className="grid gap-6 2xl:grid-cols-2">
            <UsageTrendChart rows={summary.trend} from={filters.from} to={filters.to} />
            <UsageBarChart summary={summary} projectFiltered={filters.project !== null} onPickStage={setOpenStage} />
          </div>

          <section aria-labelledby="model-summary-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
            <h2 id="model-summary-heading" className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Icon icon="lucide:cpu" width={18} aria-hidden className="text-[#5B2C9D]" /> Models
            </h2>
            <SummaryTable rows={summary.by_model} selectedModel={logModel} onPickModel={pickLogModel} />
          </section>

          <section aria-labelledby="stage-summary-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
            <h2 id="stage-summary-heading" className="mb-3 flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Icon icon="lucide:layers" width={18} aria-hidden className="text-[#5B2C9D]" /> By stage
              <span className="text-sm font-normal text-slate-500">· pick a stage for its sub-stages</span>
            </h2>
            <StageTable rows={summary.by_stage} onOpen={setOpenStage} />
          </section>

          <section aria-labelledby="call-log-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 id="call-log-heading" ref={callLogHeading} tabIndex={-1} className="scroll-mt-4 outline-none flex items-center gap-2 text-lg font-semibold text-slate-900">
                <Icon icon="lucide:list" width={18} aria-hidden className="text-[#5B2C9D]" /> Call log
              </h2>
              {logModel && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#5B2C9D]/10 py-1 pl-3 pr-1.5 text-xs font-semibold text-[#5B2C9D]">
                  Model: {logModel}
                  <button type="button" aria-label="Show calls of every model" onClick={() => pickLogModel("")} className="rounded-full p-0.5 hover:bg-[#5B2C9D]/20">
                    <Icon icon="lucide:x" width={12} aria-hidden />
                  </button>
                </span>
              )}
              {logSubStage !== null && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-[#5B2C9D]/10 py-1 pl-3 pr-1.5 text-xs font-semibold text-[#5B2C9D]">
                  Sub-stage: {subStageLabel(logSubStage)}
                  <button type="button" aria-label="Show calls of every sub-stage" onClick={() => pickLogSubStage(null)} className="rounded-full p-0.5 hover:bg-[#5B2C9D]/20">
                    <Icon icon="lucide:x" width={12} aria-hidden />
                  </button>
                </span>
              )}
            </div>
            {callsError ? (
              <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {callsError} <button type="button" onClick={() => setRetry((r) => r + 1)} className="ml-2 font-semibold underline">Retry</button>
              </div>
            ) : calls === null ? (
              <div className="h-40 animate-pulse rounded-2xl bg-slate-100" aria-busy="true" />
            ) : calls.total === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">No LLM calls in this range</p>
            ) : (
              <CallLogTable rows={calls.rows} total={calls.total} offset={callOffset} loading={callsLoading} onOffset={setCallOffset} />
            )}
          </section>
        </div>
      )}
      {openStageRow && (
        <StageDrillDown stage={openStageRow} scope={stageScope} onClose={() => setOpenStage(null)}
          onShowCalls={(sub) => showStageCalls(openStageRow.stage, sub)} />
      )}
    </div>
  );
}
