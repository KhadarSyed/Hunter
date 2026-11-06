import { formatDateTime, formatDate } from "../utils/format";
import { useEffect, useMemo, useRef, useState } from "react";
import { intelApi, type EnrichedRecord, type BrandSentiment, type QuestionDimension, type DynamicTagDef, type TagSchemas, type RowRelations } from "../services/intel-api";
import { RelatedArticlesDrawer, type RelationKind } from "./RelatedArticlesDrawer";
import { RelationCount, clusterSummary, recordRow } from "./RecordRelations";
import { TagSchemaPanel } from "./TagSchemaPanel";
import { QuestionDrillDown, humanize } from "./QuestionDrillDown";
import { CountryFlag } from "./CountryFlag";
import { SentimentPill, PublisherCell, TriCheckbox, RecordDrawer, DynamicTagCell, approvalOf, reviewQueueOf, loadThreshold, SENTIMENT_STYLE, APPROVAL_STYLE, formatReviewedAt, THRESHOLD_KEY } from "./dataset/cells";

export { approvalOf, reviewQueueOf, loadThreshold };

const V = "#5B2C9D";
const SENTIMENT_OPTIONS = ["Positive", "Neutral", "Negative"] as const;
const CLAMP_THRESHOLD = 140; // rough chars-per-3-lines at this column's width




const rowKey = (r: Pick<EnrichedRecord, "dataset_id" | "id">) => `${r.dataset_id}:${r.id}`;


/** Which review bucket a record currently belongs to — irrelevant overrides
 * media type, so marking something irrelevant always moves it out of
 * Social/Traditional regardless of what kind of content it was. */
function bucketOf(r: EnrichedRecord): "social" | "traditional" | "irrelevant" {
  if (r.review_status === "irrelevant") return "irrelevant";
  // "Post" when derived from the source domain; a file's own media type column says "social"
  return /^(post|social)$/i.test(r.media_type || "") ? "social" : "traditional";
}



/** Clamps to a fixed 3 lines (caps row height) and — only when the text is
 * long enough that it likely overflowed — shows a "See more" link that opens
 * the full-text drill-down drawer, instead of expanding inline. */
function ClampedCell({ text, onSeeMore }: { text: string; onSeeMore: () => void }) {
  if (!text) return <span className="text-slate-300">—</span>;
  const isLong = text.length > CLAMP_THRESHOLD;
  return (
    <div>
      <span
        className="text-xs text-slate-700"
        style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}
      >
        {text}
      </span>
      {isLong && (
        <button onClick={onSeeMore} className="block text-[10px] font-medium mt-0.5 hover:underline" style={{ color: V }}>
          See more
        </button>
      )}
    </div>
  );
}




type ReviewQueue = "needs_review" | "auto_accepted" | "all";




/** One review column per question dimension across every research question (same key = same column). */
function dimensionColumns(dimensions: Record<string, QuestionDimension[]> | undefined): { key: string; label: string; judged: boolean }[] {
  const byKey = new Map<string, { key: string; label: string; judged: boolean }>();
  for (const dims of Object.values(dimensions || {})) {
    for (const d of dims) if (!byKey.has(d.key)) byKey.set(d.key, { key: d.key, label: d.label, judged: !!d.judged });
  }
  return [...byKey.values()];
}

type EnrichedArticlesTableProps = {
  records: EnrichedRecord[];
  loading: boolean;
  dimensions?: Record<string, QuestionDimension[]>;
  tagSchemas?: TagSchemas;
  projectId?: number;
};

/** One Review column per dynamic tag across every question's schema (same tag name = same column). */
function tagColumns(schemas: TagSchemas | undefined): DynamicTagDef[] {
  const byName = new Map<string, DynamicTagDef>();
  for (const s of Object.values(schemas || {})) {
    for (const t of s.schema.required_tags) if (!byName.has(t.tag_name)) byName.set(t.tag_name, t);
  }
  return [...byName.values()];
}



export function EnrichedArticlesTable({ records, loading, dimensions, tagSchemas, projectId }: EnrichedArticlesTableProps) {
  const dimColumns = useMemo(() => dimensionColumns(dimensions), [dimensions]);
  // syndicated / similar articles per row ("<dataset_id>:<id>"): undefined while loading, null when it failed
  const [relations, setRelations] = useState<Record<string, RowRelations> | null | undefined>(undefined);
  const [openRelation, setOpenRelation] = useState<{ kind: RelationKind; record: EnrichedRecord } | null>(null);
  useEffect(() => {
    if (!projectId || records.length === 0) return;
    let cancelled = false;
    setRelations(undefined);
    intelApi.getEnrichedRelations(projectId)
      .then((r) => { if (!cancelled) setRelations(r.relations); })
      .catch(() => { if (!cancelled) setRelations(null); });
    return () => { cancelled = true; };
  }, [projectId, records.length]);
  // a tag named like a dimension column would repeat its header; its values still show under Question match
  const dynColumns = useMemo(() => tagColumns(tagSchemas).filter((t) => !dimColumns.some((d) => d.key === t.tag_name)),
    [tagSchemas, dimColumns]);
  const [localRecords, setLocalRecords] = useState<EnrichedRecord[]>(records);
  useEffect(() => { setLocalRecords(records); }, [records]);

  const [subTab, setSubTab] = useState<"social" | "traditional" | "irrelevant">("traditional");
  const [threshold, setThreshold] = useState<number>(loadThreshold);
  const [queue, setQueue] = useState<ReviewQueue>("all");
  useEffect(() => {
    try { window.localStorage.setItem(THRESHOLD_KEY, String(threshold)); } catch { /* storage unavailable */ }
  }, [threshold]);
  // A selection made in one view must never act on rows another view hides.
  useEffect(() => { setSelected(new Set()); }, [queue, threshold, subTab]);
  const [search, setSearch] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [openRecord, setOpenRecord] = useState<EnrichedRecord | null>(null);
  const [statusPending, setStatusPending] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkDisapproveOpen, setBulkDisapproveOpen] = useState(false);
  const [bulkDisapproveReason, setBulkDisapproveReason] = useState("");

  const buckets = useMemo(() => {
    const out = { social: [] as EnrichedRecord[], traditional: [] as EnrichedRecord[], irrelevant: [] as EnrichedRecord[] };
    for (const r of localRecords) out[bucketOf(r)].push(r);
    return out;
  }, [localRecords]);

  const brandColumns = useMemo(() => {
    const primary = new Set<string>();
    const others = new Set<string>();
    for (const r of localRecords) {
      for (const bs of r.brand_sentiments || []) {
        (bs.is_primary ? primary : others).add(bs.brand);
      }
    }
    return [...primary, ...[...others].filter((b) => !primary.has(b))];
  }, [localRecords]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return buckets[subTab].filter((r) => {
      if (subTab !== "irrelevant" && queue !== "all" && reviewQueueOf(r, threshold) !== queue) return false;
      if (sentimentFilter && r.overall_sentiment !== sentimentFilter) return false;
      if (q) {
        const hay = [r.title, r.content, r.source_name, r.author, ...(r.entities?.brands || [])].filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [buckets, subTab, search, sentimentFilter, queue, threshold]);

  const queueCounts = useMemo(() => {
    const relevant = localRecords.filter((r) => r.review_status !== "irrelevant");
    const needs = relevant.filter((r) => reviewQueueOf(r, threshold) === "needs_review").length;
    return { needs_review: needs, auto_accepted: relevant.length - needs, all: relevant.length };
  }, [localRecords, threshold]);

  // Approval counts are global (across every bucket), not just the active sub-tab —
  // this is a separate review workflow from the Social/Traditional/Irrelevant split.
  const approvedCount = useMemo(() => localRecords.filter((r) => r.approval_status === "approved").length, [localRecords]);
  const disapprovedCount = useMemo(() => localRecords.filter((r) => r.approval_status === "disapproved").length, [localRecords]);

  const allVisibleSelected = filtered.length > 0 && filtered.every((r) => selected.has(rowKey(r)));
  const someVisibleSelected = filtered.some((r) => selected.has(rowKey(r))) && !allVisibleSelected;

  const toggleSelect = (key: string) => {
    setSelected((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };
  const toggleSelectAll = () => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (allVisibleSelected) filtered.forEach((r) => n.delete(rowKey(r)));
      else filtered.forEach((r) => n.add(rowKey(r)));
      return n;
    });
  };

  const applyRecordUpdate = (updated: EnrichedRecord) => {
    setLocalRecords((prev) => prev.map((r) => (r.dataset_id === updated.dataset_id && r.id === updated.id) ? { ...r, ...updated } : r));
  };

  const toggleRelevance = async (r: EnrichedRecord) => {
    if (r.dataset_id == null) return;
    const nextStatus = r.review_status === "irrelevant" ? "relevant" : "irrelevant";
    const key = rowKey(r);
    setStatusPending(key);
    setToggleError(null);
    try {
      const updated = await intelApi.updateEnrichedRecord(r.dataset_id, r.id, { review_status: nextStatus });
      applyRecordUpdate({ ...r, ...updated, review_status: nextStatus });
    } catch (e) {
      setToggleError(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setStatusPending(null);
    }
  };

  const applyBulkApproval = async (status: "approved" | "disapproved", reason?: string) => {
    const targets = filtered.filter((r) => selected.has(rowKey(r)) && r.dataset_id != null);   // visible rows only
    if (targets.length === 0) return;
    setBulkPending(true);
    setToggleError(null);
    try {
      const updates: Partial<EnrichedRecord> = { approval_status: status };
      if (status === "disapproved") updates.disapproval_reason = reason;
      await Promise.all(targets.map((r) => intelApi.updateEnrichedRecord(r.dataset_id as number, r.id, updates)));
      const targetKeys = new Set(targets.map(rowKey));
      setLocalRecords((prev) => prev.map((r) => targetKeys.has(rowKey(r)) ? { ...r, ...updates } : r));
      setSelected(new Set());
      setBulkDisapproveOpen(false);
      setBulkDisapproveReason("");
    } catch (e) {
      setToggleError(e instanceof Error ? e.message : "Bulk update failed — some items may not have been updated");
    } finally {
      setBulkPending(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-4 border-slate-200 border-t-violet-600 animate-spin" />
      </div>
    );
  }

  if (localRecords.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-center space-y-2">
          <h3 className="text-sm font-semibold text-slate-700">No enriched articles yet</h3>
          <p className="text-xs text-slate-500">Enrich a dataset on the Data Sources tab to see tagged articles here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {toggleError && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 flex items-center justify-between">
          <span className="text-xs text-red-700">{toggleError}</span>
          <button onClick={() => setToggleError(null)} className="text-red-400 hover:text-red-600">
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
        </div>
      )}

      {/* Confidence threshold — low-confidence rows need review; the rest are auto-accepted */}
      <div className="mb-4 flex items-center gap-4 flex-wrap rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3">
        <label className="flex items-center gap-3 text-xs font-medium text-slate-600">
          Sentiment confidence threshold
          <input type="range" min={0} max={100} step={5} value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            aria-label="Sentiment confidence threshold" className="w-40 accent-[#5B2C9D]" />
          <span className="w-10 tabular-nums font-semibold" style={{ color: "#5B2C9D" }}>{threshold}%</span>
        </label>
        <div className="flex items-center gap-1" role="tablist" aria-label="Review queue">
          {([
            { id: "all", label: "All" },
            { id: "auto_accepted", label: "Auto-approved" },
            { id: "needs_review", label: "Pending review" },
          ] as const).map((q) => (
            <button key={q.id} role="tab" aria-selected={queue === q.id} onClick={() => setQueue(q.id)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                queue === q.id ? "text-white" : "text-slate-600 bg-white border border-slate-200 hover:bg-slate-100"
              }`}
              style={queue === q.id ? { background: "#5B2C9D" } : undefined}>
              {q.label} <span className={queue === q.id ? "text-white/80" : "text-slate-400"}>({queueCounts[q.id]})</span>
            </button>
          ))}
        </div>
        <span className="text-[11px] text-slate-500">
          Every enriched article is shown. At or above {threshold}% confidence it is auto-approved; below it stays pending review.
        </span>
      </div>

      <TagSchemaPanel schemas={tagSchemas} />

      {/* Sub-tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-slate-200">
        {([
          { id: "traditional", label: "Traditional" },
          { id: "social", label: "Social" },
          { id: "irrelevant", label: "Irrelevant" },
        ] as const).map((t) => (
          <button key={t.id} onClick={() => setSubTab(t.id)}
            className={`px-4 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
              subTab === t.id ? "border-current text-[#5B2C9D]" : "border-transparent text-slate-400 hover:text-slate-600"
            }`}>
            {t.label} <span className="text-slate-400">({buckets[t.id].length})</span>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search title, content, brand, author..."
          className="flex-1 max-w-sm text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-violet-500/20"
        />
        <select value={sentimentFilter} onChange={(e) => setSentimentFilter(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white">
          <option value="">All sentiment</option>
          {SENTIMENT_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="text-xs text-slate-400">{filtered.length} of {buckets[subTab].length} articles</span>
        <div className="flex-1" />
        {/* Approval counts — across every bucket, since approval is a separate review pass */}
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1 font-medium" style={{ color: APPROVAL_STYLE.approved.color }}>
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5" /></svg>
            {approvedCount} approved
          </span>
          <span className="flex items-center gap-1 font-medium" style={{ color: APPROVAL_STYLE.disapproved.color }}>
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            {disapprovedCount} disapproved
          </span>
        </div>
      </div>

      {/* Bulk action bar — appears once at least one row is selected */}
      {selected.size > 0 && (
        <div className="mb-3 px-4 py-2 bg-violet-50 border border-violet-100 rounded-lg">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium" style={{ color: V }}>{selected.size} selected</span>
            <div className="flex-1" />
            <button onClick={() => applyBulkApproval("approved")} disabled={bulkPending}
              className="text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: "#059669" }}>
              Approve
            </button>
            <button onClick={() => setBulkDisapproveOpen((v) => !v)} disabled={bulkPending}
              className="text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: "#dc2626" }}>
              Disapprove
            </button>
            <button onClick={() => { setSelected(new Set()); setBulkDisapproveOpen(false); }} className="text-xs font-medium text-slate-500 hover:text-slate-700">
              Clear
            </button>
          </div>
          {bulkDisapproveOpen && (
            <div className="mt-2 flex items-center gap-2">
              <input value={bulkDisapproveReason} onChange={(e) => setBulkDisapproveReason(e.target.value)}
                placeholder="Reason for disapproving (required, applies to all selected)"
                className="flex-1 text-xs border border-slate-200 rounded-lg px-2 py-1.5" />
              <button onClick={() => applyBulkApproval("disapproved", bulkDisapproveReason)}
                disabled={bulkPending || !bulkDisapproveReason.trim()}
                className="text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: "#dc2626" }}>
                Confirm
              </button>
            </div>
          )}
        </div>
      )}

      {/* The page itself scrolls (no nested overflow container here) so the
          thead's `sticky top-0` pins against that single scroll context —
          articles scroll underneath while the column headers stay put. */}
      <div className="border border-slate-200 rounded-xl bg-white">
        <table className="w-full text-sm border-collapse">
          <thead className="bg-slate-50 sticky top-0 z-10">
            <tr className="text-left text-[10px] font-semibold text-slate-500 uppercase tracking-wide">
              <th className="px-3 py-2.5 w-8">
                <TriCheckbox checked={allVisibleSelected} indeterminate={someVisibleSelected} onChange={toggleSelectAll} ariaLabel="Select all visible articles" />
              </th>
              <th className="px-3 py-2.5 w-10">S.No</th>
              <th className="px-3 py-2.5 w-36">Publisher</th>
              <th className="px-3 py-2.5 w-24">Published</th>
              <th className="px-3 py-2.5 w-56">Title / Post</th>
              <th className="px-3 py-2.5 w-20" title="The same article published by other publishers — click to see them with their tags">Syndicated</th>
              <th className="px-3 py-2.5 w-20" title="Other articles on the same theme, content or context — click to see them with their tags">Similar</th>
              <th className="px-3 py-2.5 w-64">Content</th>
              <th className="px-3 py-2.5 w-24">Author</th>
              <th className="px-3 py-2.5 w-28">Author type</th>
              {dimColumns.map((d) => (
                <th key={d.key} className="px-3 py-2.5 w-32"
                  title={d.judged ? "Tagged by the LLM from what the research question asks" : "Tagged by the LLM against the research question's terms"}>
                  {d.label}
                </th>
              ))}
              {dynColumns.map((t) => (
                <th key={`dyn-${t.tag_name}`} className="px-3 py-2.5 w-32 bg-indigo-50/60 text-indigo-800"
                  title={`${t.definition}${t.allowed_values.length ? ` (${t.allowed_values.join(" / ")})` : ""}`}>
                  {humanize(t.tag_name)}
                </th>
              ))}
              <th className="px-3 py-2.5 w-24">Country</th>
              <th className="px-3 py-2.5 w-24">Overall</th>
              {brandColumns.map((b) => (
                <th key={b} className="px-3 py-2.5 w-24">{b}</th>
              ))}
              <th className="px-3 py-2.5 w-32">Primary Theme</th>
              <th className="px-3 py-2.5 w-32">Secondary Theme</th>
              <th className="px-3 py-2.5 w-32">Tertiary Theme</th>
              <th className="px-3 py-2.5 w-32">Signals</th>
              <th className="px-3 py-2.5 w-40">Entities</th>
              <th className="px-3 py-2.5 w-44 bg-indigo-50/60 text-indigo-800" title="What the article contributes to its research question: each question tag and its value (hover for the quoted evidence)">Question match</th>
              <th className="px-3 py-2.5 w-36" title="The research question's search keywords this article contains">Keyword matches</th>
              <th className="px-3 py-2.5 w-56" title="One sentence on what the article says about its research question">Question summary</th>
              <th className="px-3 py-2.5 w-56">Reason</th>
              <th className="px-3 py-2.5 w-24">Relevance</th>
              <th className="px-3 py-2.5 w-24">Approval</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((r, i) => {
              const key = rowKey(r);
              const brandSentByName = new Map((r.brand_sentiments || []).map((bs) => [bs.brand, bs]));
              const entityCount = Object.values(r.entities || {}).reduce((n, arr) => n + (arr?.length || 0), 0);
              const isIrrelevant = r.review_status === "irrelevant";
              const approval = APPROVAL_STYLE[approvalOf(r, threshold)];
              const approvalTitle = r.reviewed_by
                ? `Reviewed by ${r.reviewed_by}${r.reviewed_at ? ` on ${formatReviewedAt(r.reviewed_at)}` : ""}${r.disapproval_reason ? ` — ${r.disapproval_reason}` : ""}`
                : undefined;
              return (
                <tr key={key} className="align-top hover:bg-slate-50/60">
                  <td className="px-3 py-2.5">
                    <TriCheckbox checked={selected.has(key)} onChange={() => toggleSelect(key)} ariaLabel={`Select ${r.title || "article"}`} />
                  </td>
                  <td className="px-3 py-2.5 text-slate-400 tabular-nums">{i + 1}</td>
                  <td className="px-3 py-2.5"><PublisherCell record={r} /></td>
                  <td className="px-3 py-2.5 text-xs text-slate-500 whitespace-nowrap">{r.date || "—"}</td>
                  <td className="px-3 py-2.5">
                    <button onClick={() => setOpenRecord(r)} className="text-left hover:underline" style={{ color: V }}>
                      <span className="text-xs font-medium"
                        style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                        {r.title || "(untitled)"}
                      </span>
                    </button>
                  </td>
                  <td className="px-3 py-2.5"><RelationCount relations={relations} rowKey={key} kind="syndicated"
                    onOpen={() => setOpenRelation({ kind: "syndicated", record: r })} /></td>
                  <td className="px-3 py-2.5"><RelationCount relations={relations} rowKey={key} kind="similar"
                    onOpen={() => setOpenRelation({ kind: "similar", record: r })} /></td>
                  <td className="px-3 py-2.5"><ClampedCell text={r.content} onSeeMore={() => setOpenRecord(r)} /></td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">{r.author || "—"}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">{r.author_type && r.author_type !== "Unknown" ? r.author_type : <span className="text-slate-300">—</span>}</td>
                  {dimColumns.map((d) => {
                    // an article another question's query routed here carries that question's tag of the same name
                    const dyn = r.dynamic_tags?.[d.key];
                    const tagged = r.question_tags?.[d.key]?.length ? r.question_tags[d.key]
                      : Array.isArray(dyn) ? dyn : dyn ? [dyn] : [];
                    return (
                      <td key={d.key} className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {tagged.length > 0
                            ? tagged.map((v) => <span key={v} className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">{v}</span>)
                            : <span className="text-slate-300 text-xs">—</span>}
                        </div>
                      </td>
                    );
                  })}
                  {dynColumns.map((t) => (
                    <td key={`dyn-${t.tag_name}`} className="px-3 py-2.5 bg-indigo-50/20"><DynamicTagCell record={r} tag={t} /></td>
                  ))}
                  <td className="px-3 py-2.5">{r.country ? <CountryFlag country={r.country} size={14} showLabel className="text-xs text-slate-600" /> : <span className="text-slate-300">—</span>}</td>
                  <td className="px-3 py-2.5"><SentimentPill sentiment={r.overall_sentiment} confidence={r.overall_sentiment_confidence} /></td>
                  {brandColumns.map((b) => {
                    const bs = brandSentByName.get(b);
                    return (
                      <td key={b} className="px-3 py-2.5">
                        {bs ? <SentimentPill sentiment={bs.sentiment} confidence={bs.confidence} /> : <span className="text-slate-300 text-xs">—</span>}
                      </td>
                    );
                  })}
                  <td className="px-3 py-2.5">
                    {r.themes?.primary ? <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-violet-50 text-violet-700 w-fit inline-block">{r.themes.primary}</span> : <span className="text-slate-300 text-xs">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-500">{r.themes?.secondary || <span className="text-slate-300">—</span>}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-400">{r.themes?.tertiary || <span className="text-slate-300">—</span>}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {(r.signals || []).length > 0
                        ? r.signals.map((s) => <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">{s}</span>)
                        : <span className="text-slate-300 text-xs">—</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-[10px] text-slate-500"
                    style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                    {entityCount > 0
                      ? Object.entries(r.entities || {}).filter(([, v]) => Array.isArray(v) && v.length).map(([k, v]) => (
                          <div key={k} className="truncate"><span className="text-slate-400 capitalize">{k}:</span> {v.join(", ")}</div>
                        ))
                      : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-[10px] text-slate-600 bg-indigo-50/20 cursor-pointer" onClick={() => setOpenRecord(r)}
                    style={{ display: "-webkit-box", WebkitLineClamp: 4, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                    {Object.keys(r.dynamic_tags || {}).length > 0
                      ? Object.entries(r.dynamic_tags || {}).map(([k, v]) => (
                          <div key={k} className="truncate" title={r.tag_evidence?.[k] ? `"${r.tag_evidence[k]}"` : "No quoted evidence"}>
                            <span className="text-slate-400">{k.replace(/_/g, " ")}:</span> {Array.isArray(v) ? v.join(", ") : v}
                          </div>
                        ))
                      : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {(r.keyword_matches || []).length > 0
                        ? (r.keyword_matches || []).slice(0, 6).map((k) => <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800">{k}</span>)
                        : <span className="text-slate-300 text-xs">—</span>}
                    </div>
                  </td>
                  <td className="px-3 py-2.5"><ClampedCell text={r.question_summary || ""} onSeeMore={() => setOpenRecord(r)} /></td>
                  <td className="px-3 py-2.5"><ClampedCell text={r.reason || ""} onSeeMore={() => setOpenRecord(r)} /></td>
                  <td className="px-3 py-2.5">
                    <button onClick={() => toggleRelevance(r)} disabled={statusPending === key}
                      className={`text-[10px] font-medium px-2 py-1 rounded-lg transition-colors disabled:opacity-50 ${
                        isIrrelevant ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100" : "bg-red-50 text-red-600 hover:bg-red-100"
                      }`}>
                      {statusPending === key ? "..." : isIrrelevant ? "Mark relevant" : "Mark irrelevant"}
                    </button>
                  </td>
                  <td className="px-3 py-2.5">
                    <span title={approvalTitle} className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full cursor-default" style={{ color: approval.color, background: approval.bg }}>
                      {approval.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {openRelation && relations && (() => {
        const byKey = new Map(localRecords.map((x) => [rowKey(x), x]));
        const related = (relations[rowKey(openRelation.record)]?.[openRelation.kind] || [])
          .map((k) => byKey.get(k)).filter((x): x is EnrichedRecord => !!x);
        return (
          <RelatedArticlesDrawer kind={openRelation.kind}
            source={{ title: openRelation.record.title, publisher: openRelation.record.source_name }}
            related={related.map(recordRow)} summary={clusterSummary(openRelation.record, related)}
            onClose={() => setOpenRelation(null)} />
        );
      })()}
      {openRecord && (
        <RecordDrawer
          record={openRecord}
          datasetId={openRecord.dataset_id}
          onClose={() => setOpenRecord(null)}
          onSaved={(updated) => { applyRecordUpdate(updated); setOpenRecord(updated); }}
        />
      )}
    </div>
  );
}
