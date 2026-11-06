import { useCallback, useEffect, useRef, useState } from "react";
import { intelApi } from "../services/intel-api";
import { agentSocket } from "../services/ws";
import { useActiveProjectId } from "../context/project-context";
import { Tabs } from "../components/deliverable/Tabs";
import { ArticlesTable, PAGE_SIZE } from "../components/dataset/ArticlesTable";
import { BulkBar } from "../components/dataset/BulkBar";
import { ColumnPicker, loadHidden, saveHidden, type GroupId } from "../components/dataset/ColumnPicker";
import { FilterBar } from "../components/dataset/FilterBar";
import type { ArticleFacets, ArticleFilters, ArticlePage, Channel, RqStatus, UploadResult } from "../types/dataset";

const V = "#5B2C9D";
const UNDO_MS = 10_000;
const EMPTY: ArticleFilters = { channel: "traditional", status: "all", rq: "", sentiment: "", theme: "", brand: "", content_status: "", q: "" };
const NO_PAGE: ArticlePage = { rows: [], total: 0, rqs: [] };
const NO_FACETS: ArticleFacets = { themes: [], brands: [], content_statuses: [] };
const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

type Progress = { phase: string; done: number; total: number; minutesLeft: number | null };
type Toast = { token: string; text: string };

function UploadBanner({ result }: { result: UploadResult }) {
  const failed = result.files.filter((f) => f.error);
  return (
    <div className="space-y-1">
      <div role="status" className="rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
        {result.added.toLocaleString()} articles uploaded ({result.traditional.toLocaleString()} traditional, {result.social.toLocaleString()} social, {result.duplicates.toLocaleString()} duplicates removed)
      </div>
      {failed.map((f) => <div key={f.file_name} role="alert" className="rounded-lg border border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">{f.file_name}: {f.error}</div>)}
    </div>
  );
}

export function DataSet() {
  const projectId = useActiveProjectId();
  const [filters, setFilters] = useState<ArticleFilters>(EMPTY);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ArticlePage>(NO_PAGE);
  const [facets, setFacets] = useState<ArticleFacets>(NO_FACETS);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [hidden, setHiddenState] = useState<GroupId[]>(loadHidden);
  const [reloadKey, setReloadKey] = useState(0);   // the page itself
  const [dataKey, setDataKey] = useState(0);       // what the dropdowns read

  const [uploading, setUploading] = useState(false);
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [tagged, setTagged] = useState(0);
  const [articleTotal, setArticleTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const phaseStart = useRef<{ phase: string; at: number; seeded: boolean }>({ phase: "", at: 0, seeded: false });
  const toastTimer = useRef<number | undefined>(undefined);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const reloadData = useCallback(() => { setReloadKey((k) => k + 1); setDataKey((k) => k + 1); }, []);

  // A new tab, filter or scope never keeps the old selection.
  const changeFilters = (patch: Partial<ArticleFilters>) => { setFilters((f) => ({ ...f, ...patch })); setOffset(0); setSelected(new Set()); };

  useEffect(() => {
    if (!projectId) return;
    let stale = false;
    setLoading(true);
    const id = window.setTimeout(() => {
      intelApi.listArticles(projectId, filters, offset, PAGE_SIZE)
        .then((p) => { if (!stale) { setPage(p); setError(null); } })
        .catch((e) => { if (!stale) setError(errMsg(e, "Failed to load articles")); })
        .finally(() => { if (!stale) setLoading(false); });
    }, filters.q ? 300 : 0);
    return () => { stale = true; window.clearTimeout(id); };
  }, [projectId, filters, offset, reloadKey]);

  // The channel's dropdown values (themes, brands, content statuses), computed on the server.
  useEffect(() => {
    if (!projectId) return;
    let stale = false;
    intelApi.articleFacets(projectId, filters.channel)
      .then((f) => { if (!stale) setFacets(f); })
      .catch((e) => { if (!stale) { setFacets(NO_FACETS); setError(errMsg(e, "Could not load the filter options")); } });
    return () => { stale = true; };
  }, [projectId, filters.channel, dataKey]);

  const syncTagging = useCallback(async () => {
    if (!projectId) return;
    try {
      const t = await intelApi.taggingState(projectId);
      setTagged(t.counts.tags.tagged ?? 0);
      setArticleTotal(t.counts.total);
      setProgress(t.running ? { phase: t.phase ?? "", done: t.done, total: t.total, minutesLeft: t.minutes_left } : null);
      // Seed the phase clock from the server's ETA (left = elapsed / done * remaining) so a page opened mid-run keeps counting.
      const remaining = t.total - t.done;
      const elapsedMin = t.running && t.minutes_left != null && t.done > 0 && remaining > 0 ? (t.minutes_left * t.done) / remaining : 0;
      phaseStart.current = { phase: t.running ? (t.phase ?? "") : "", at: Date.now() - elapsedMin * 60000, seeded: t.running && (t.done === 0 || t.minutes_left != null) };
    } catch { /* the strip simply stays as it was */ }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    agentSocket.connect();
    void syncTagging();
    const offMsg = agentSocket.onMessage((m) => {
      if (m.type !== "dataset_tagging" || m.project_id !== projectId) return;
      if (m.phase === "done") { setProgress(null); void syncTagging(); reloadData(); return; }
      if (phaseStart.current.phase !== m.phase) {
        // First event of a phase we did not see start (page opened mid-run): no guess, ask the server for its ETA.
        const midRun = m.done > 1;
        phaseStart.current = { phase: m.phase, at: Date.now(), seeded: !midRun };
        if (midRun) void syncTagging();
      }
      const elapsedMin = (Date.now() - phaseStart.current.at) / 60000;
      const left = phaseStart.current.seeded && m.done > 0 ? Math.round((elapsedMin / m.done) * (m.total - m.done) * 10) / 10 : null;
      setProgress({ phase: m.phase, done: m.done, total: m.total, minutesLeft: left });
    });
    const offStatus = agentSocket.onStatus((connected) => { if (connected) void syncTagging(); });
    return () => { offMsg(); offStatus(); };
  }, [projectId, syncTagging, reloadData]);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const onFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!projectId || list.length === 0 || uploading) return;
    setUploading(true);
    setError(null);
    try {
      setUpload(await intelApi.uploadArticles(projectId, list));
      reloadData();
      void syncTagging();
    } catch (e) { setError(errMsg(e, "Upload failed")); }
    finally { setUploading(false); }
  };

  const startTagging = async () => {
    if (!projectId) return;
    setError(null);
    try {
      await intelApi.startTagging(projectId);
      setProgress({ phase: "starting", done: 0, total: 0, minutesLeft: null });
    } catch (e) { setError(errMsg(e, "Could not start tagging")); }
  };

  const decide = async (ids: number[], rqId: string | null, status: RqStatus, reason?: string) => {
    if (!projectId || ids.length === 0) return;
    setBusy(true);
    try {
      const r = await intelApi.decideArticles(projectId, ids, rqId, status, reason);
      const verb = status === "approved" ? "Approved" : status === "irrelevant" ? "Rejected" : "Reset";
      window.clearTimeout(toastTimer.current);
      setToast({ token: r.undo_token, text: `${verb} ${ids.length.toLocaleString()} article${ids.length === 1 ? "" : "s"}${rqId ? ` for ${rqId}` : ""}` });
      toastTimer.current = window.setTimeout(() => setToast(null), UNDO_MS);
      setSelected(new Set());
      reload();
    } catch (e) { setError(errMsg(e, "Could not save the decision")); }
    finally { setBusy(false); }
  };

  const undo = async () => {
    if (!projectId || !toast) return;
    try { await intelApi.undoDecision(projectId, toast.token); reload(); }
    catch (e) { setError(errMsg(e, "Nothing to undo")); }
    window.clearTimeout(toastTimer.current);
    setToast(null);
  };

  const toggleAll = async () => {
    if (!projectId) return;
    if (selected.size === page.total && page.total > 0) { setSelected(new Set()); return; }
    try { setSelected(new Set(await intelApi.articleIds(projectId, filters))); }
    catch (e) { setError(errMsg(e, "Could not select all")); }
  };

  const toggleRow = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const setHidden = (h: GroupId[]) => { setHiddenState(h); saveHidden(h); };
  const running = progress !== null;
  const pct = progress && progress.total > 0 ? Math.round((progress.done * 100) / progress.total) : 0;

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 px-6 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <button type="button" onClick={startTagging} disabled={running || articleTotal === 0}
            className="rounded-lg px-5 py-2 text-sm font-medium text-white disabled:opacity-50" style={{ background: V }}>
            {tagged > 0 ? "Re-tag" : "Start tagging"}
          </button>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Data set</h1>
            <p className="text-sm text-slate-500">Upload article files, tag them against the approved research questions, then approve or reject per question.</p>
          </div>
        </div>
      </div>

      <label onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (!uploading) void onFiles(e.dataTransfer.files); }}
        className="flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-6 py-6 text-center hover:bg-[#f5f3ff]" style={{ borderColor: "#c4b5fd" }}>
        <span className="text-sm font-medium" style={{ color: V }}>{uploading ? "Uploading…" : "Drop article files here or click to choose"}</span>
        <span className="text-xs text-slate-500">.csv, .xlsx or .xls — several files at once; a link already uploaded is counted once</span>
        <input type="file" multiple accept=".csv,.xlsx,.xls" className="sr-only" disabled={uploading} aria-label="Upload article files"
          onChange={(e) => { void onFiles(e.target.files ?? []); e.target.value = ""; }} />
      </label>

      {upload && <UploadBanner result={upload} />}
      {error && <div role="alert" className="rounded-lg border border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      {progress && (
        <div role="status" aria-label="Tagging progress" className="rounded-lg border border-violet-100 bg-violet-50 px-4 py-2">
          <div className="flex justify-between text-xs font-medium text-violet-900">
            <span>Tagging: {progress.phase} — {progress.done.toLocaleString()} of {progress.total.toLocaleString()}</span>
            <span>{progress.minutesLeft != null ? `about ${progress.minutesLeft} min left` : "estimating time…"}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-violet-100"><div className="h-full rounded-full" style={{ width: `${pct}%`, background: V }} /></div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Channel> label="Channel" active={filters.channel} onChange={(c) => changeFilters({ ...EMPTY, channel: c })}
          tabs={[{ id: "traditional", label: "Traditional", icon: "mdi:newspaper-variant-outline" }, { id: "social", label: "Social media", icon: "mdi:account-group-outline" }]} />
        <ColumnPicker hidden={hidden} onChange={setHidden} />
      </div>

      <FilterBar filters={filters} rqs={page.rqs} facets={facets} onChange={changeFilters} />

      {selected.size > 0 && (
        <BulkBar key={filters.rq} count={selected.size} rqs={page.rqs} defaultRq={filters.rq} busy={busy}
          onApprove={(rq) => void decide([...selected], rq, "approved")}
          onReject={(rq, reason) => void decide([...selected], rq, "irrelevant", reason)}
          onClear={() => setSelected(new Set())} />
      )}

      {projectId && (
        <ArticlesTable projectId={projectId} channel={filters.channel} rows={page.rows} brands={facets.brands} rqs={page.rqs}
          total={page.total} offset={offset} loading={loading} hidden={hidden} selected={selected}
          selectionComplete={page.total > 0 && selected.size === page.total}
          onToggle={toggleRow} onToggleAll={() => void toggleAll()} onPage={setOffset}
          onDecide={(id, status) => void decide([id], filters.rq || null, status)} onEdited={reloadData} />
      )}

      {toast && (
        <div role="status" className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-4 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white shadow-xl">
          {toast.text}
          <button type="button" onClick={undo} className="font-semibold text-violet-300 hover:underline">Undo</button>
        </div>
      )}
    </div>
  );
}
