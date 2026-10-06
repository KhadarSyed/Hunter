import { useEffect, useMemo, useRef, useState } from "react";
import { intelApi, type EnrichedRecord, type BrandSentiment } from "../services/intel-api";
import { CountryFlag } from "./CountryFlag";

const V = "#5B2C9D";
const SENTIMENT_OPTIONS = ["Positive", "Neutral", "Negative"] as const;
const CLAMP_THRESHOLD = 140; // rough chars-per-3-lines at this column's width

const SENTIMENT_STYLE: Record<string, { color: string; bg: string }> = {
  Positive: { color: "#059669", bg: "#ecfdf5" },
  Neutral: { color: "#64748b", bg: "#f1f5f9" },
  Negative: { color: "#dc2626", bg: "#fef2f2" },
};

const APPROVAL_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  approved: { color: "#059669", bg: "#ecfdf5", label: "Approved" },
  disapproved: { color: "#dc2626", bg: "#fef2f2", label: "Disapproved" },
  pending: { color: "#94a3b8", bg: "#f8fafc", label: "Pending" },
};

function publisherDomain(url: string): string {
  try {
    const host = new URL(url).hostname;
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
  }
}

const rowKey = (r: Pick<EnrichedRecord, "dataset_id" | "id">) => `${r.dataset_id}:${r.id}`;

function formatReviewedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Which review bucket a record currently belongs to — irrelevant overrides
 * media type, so marking something irrelevant always moves it out of
 * Social/Traditional regardless of what kind of content it was. */
function bucketOf(r: EnrichedRecord): "social" | "traditional" | "irrelevant" {
  if (r.review_status === "irrelevant") return "irrelevant";
  return r.media_type === "Post" ? "social" : "traditional";
}

function SentimentPill({ sentiment, confidence }: { sentiment: string | null; confidence: number | null }) {
  if (!sentiment) return <span className="text-slate-300 text-xs">—</span>;
  const s = SENTIMENT_STYLE[sentiment] || SENTIMENT_STYLE.Neutral;
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ color: s.color, background: s.bg }}>
        {sentiment}
      </span>
      {confidence != null && (
        <span className="text-[9px] text-slate-400 tabular-nums">{Math.round(confidence * 100)}% conf</span>
      )}
    </div>
  );
}

function PublisherCell({ record }: { record: EnrichedRecord }) {
  const [failed, setFailed] = useState(false);
  const domain = publisherDomain(record.url);
  return (
    <div className="flex items-center gap-2 min-w-0">
      {domain && !failed ? (
        <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`} alt=""
          onError={() => setFailed(true)} className="w-4 h-4 rounded-sm shrink-0" />
      ) : (
        <span className="w-4 h-4 rounded-full bg-slate-100 shrink-0" />
      )}
      <span className="truncate text-xs text-slate-700" title={record.source_name}>{record.source_name || "—"}</span>
    </div>
  );
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

/** Tri-state checkbox (supports the "indeterminate" look via a DOM ref, same
 * pattern used for Select All when some-but-not-all visible rows are picked). */
function TriCheckbox({ checked, indeterminate = false, onChange, ariaLabel }: {
  checked: boolean; indeterminate?: boolean; onChange: () => void; ariaLabel: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate && !checked; }, [indeterminate, checked]);
  return <input ref={ref} type="checkbox" checked={checked} onChange={onChange} aria-label={ariaLabel} className="w-3.5 h-3.5 rounded accent-[#5B2C9D]" />;
}

function FieldRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-2 text-xs py-1">
      <span className="text-slate-400 shrink-0">{label}</span>
      <span className="text-slate-700 break-words">{value || <span className="text-slate-300">—</span>}</span>
    </div>
  );
}

/** Right-side drill-down drawer: the uploaded source data (read-only) and the
 * LLM-tagged data (editable) in one scrollable panel, plus the approve/
 * disapprove decision with a mandatory reason on disapproval and visible
 * attribution for whoever last acted on the record. */
function RecordDrawer({
  record, datasetId, onClose, onSaved,
}: {
  record: EnrichedRecord;
  datasetId: number | undefined;
  onClose: () => void;
  onSaved: (updated: EnrichedRecord) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const [sentiment, setSentiment] = useState(record.overall_sentiment || "Neutral");
  const [confidence, setConfidence] = useState(Math.round((record.overall_sentiment_confidence ?? 0.5) * 100));
  const [themePrimary, setThemePrimary] = useState(record.themes?.primary || "");
  const [themeSecondary, setThemeSecondary] = useState(record.themes?.secondary || "");
  const [themeTertiary, setThemeTertiary] = useState(record.themes?.tertiary || "");
  const [signals, setSignals] = useState((record.signals || []).join(", "));
  const [reason, setReason] = useState(record.reason || "");
  const [brandSentiments, setBrandSentiments] = useState<BrandSentiment[]>(record.brand_sentiments || []);

  const [disapproveOpen, setDisapproveOpen] = useState(false);
  const [disapproveReason, setDisapproveReason] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState("");

  const updateBrand = (i: number, patch: Partial<BrandSentiment>) => {
    setBrandSentiments((prev) => prev.map((b, bi) => bi === i ? { ...b, ...patch } : b));
  };

  const handleSave = async () => {
    if (datasetId == null) return;
    setSaving(true);
    setSaveError("");
    try {
      const updates: Partial<EnrichedRecord> = {
        overall_sentiment: sentiment as EnrichedRecord["overall_sentiment"],
        overall_sentiment_confidence: confidence / 100,
        themes: { primary: themePrimary || null, secondary: themeSecondary || null, tertiary: themeTertiary || null },
        signals: signals.split(",").map((s) => s.trim()).filter(Boolean),
        reason,
        brand_sentiments: brandSentiments,
      };
      const updated = await intelApi.updateEnrichedRecord(datasetId, record.id, updates);
      onSaved({ ...record, ...updated });
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  };

  const submitApproval = async (status: "approved" | "disapproved", withReason?: string) => {
    if (datasetId == null) return;
    setActionPending(true);
    setActionError("");
    try {
      const updates: Partial<EnrichedRecord> = { approval_status: status };
      if (status === "disapproved") updates.disapproval_reason = withReason;
      const updated = await intelApi.updateEnrichedRecord(datasetId, record.id, updates);
      onSaved({ ...record, ...updated });
      setDisapproveOpen(false);
      setDisapproveReason("");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to update approval status");
    } finally {
      setActionPending(false);
    }
  };

  const approval = APPROVAL_STYLE[record.approval_status || "pending"];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative w-full max-w-xl h-full bg-white shadow-2xl overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 mb-3">
          <h3 className="text-base font-semibold text-slate-800">{record.title || "(untitled)"}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 shrink-0">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
          </button>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400 mb-4 flex-wrap">
          <span>{record.source_name}</span>
          {record.date && <span>• {record.date}</span>}
          {record.author && <span>• {record.author}</span>}
          {record.url && <a href={record.url} target="_blank" rel="noopener noreferrer" className="hover:underline" style={{ color: V }}>Open original ↗</a>}
        </div>

        {/* Approval decision — the analyst's sign-off, separate from review_status (relevant/irrelevant) */}
        <div className="rounded-xl border border-slate-200 p-3 mb-4 bg-slate-50/60">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ color: approval.color, background: approval.bg }}>
              {approval.label}
            </span>
            <div className="flex items-center gap-2">
              <button onClick={() => submitApproval("approved")} disabled={actionPending || record.approval_status === "approved"}
                className="text-[11px] font-medium px-2.5 py-1 rounded-lg text-white disabled:opacity-40" style={{ background: "#059669" }}>
                Approve
              </button>
              <button onClick={() => setDisapproveOpen((v) => !v)} disabled={actionPending}
                className="text-[11px] font-medium px-2.5 py-1 rounded-lg text-white disabled:opacity-40" style={{ background: "#dc2626" }}>
                Disapprove
              </button>
            </div>
          </div>
          {disapproveOpen && (
            <div className="mt-2 space-y-2">
              <textarea
                value={disapproveReason}
                onChange={(e) => setDisapproveReason(e.target.value)}
                placeholder="Reason for disapproving (required)"
                rows={2}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-xs"
              />
              <div className="flex items-center gap-2 justify-end">
                <button onClick={() => setDisapproveOpen(false)} className="text-[11px] font-medium px-2.5 py-1 rounded-lg text-slate-500 hover:bg-slate-100">Cancel</button>
                <button
                  onClick={() => submitApproval("disapproved", disapproveReason)}
                  disabled={actionPending || !disapproveReason.trim()}
                  className="text-[11px] font-medium px-2.5 py-1 rounded-lg text-white disabled:opacity-40" style={{ background: "#dc2626" }}>
                  Confirm disapprove
                </button>
              </div>
            </div>
          )}
          {record.approval_status === "disapproved" && record.disapproval_reason && (
            <p className="text-xs text-red-600 mt-2"><span className="font-semibold">Reason: </span>{record.disapproval_reason}</p>
          )}
          {record.reviewed_by && (
            <p className="text-[10px] text-slate-400 mt-2">
              Last reviewed by <span className="font-medium text-slate-500">{record.reviewed_by}</span>
              {record.reviewed_at && <> on {formatReviewedAt(record.reviewed_at)}</>}
            </p>
          )}
          {actionError && <p className="text-xs text-red-600 mt-2">{actionError}</p>}
        </div>

        {/* Uploaded data — exactly what came from the source export, never touched by tagging/editing */}
        <div className="mb-4">
          <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Uploaded data</h4>
          <div className="rounded-xl border border-slate-200 p-3 space-y-0.5">
            <FieldRow label="Title / Post" value={record.title} />
            <FieldRow label="Author" value={record.author} />
            <FieldRow label="Published" value={record.date} />
            <FieldRow label="Country" value={record.country} />
            <FieldRow label="Media type" value={record.media_type} />
            {record.reach && <FieldRow label="Reach" value={record.reach} />}
            <div className="pt-2 mt-1 border-t border-slate-100">
              {/* Preserves the original line breaks/paragraph spacing from the source export —
                  this platform's uploaded datasets are plain text (no embedded HTML/images). */}
              <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{record.content}</div>
            </div>
          </div>
        </div>

        {/* Tagged data — LLM output, editable by an analyst */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <h4 className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">Tagged data</h4>
            {!editing && (
              <button onClick={() => setEditing(true)}
                className="text-[11px] font-medium px-2 py-0.5 rounded-lg border hover:bg-violet-50"
                style={{ color: V, borderColor: "#ddd6fe" }}>
                Edit tags
              </button>
            )}
          </div>
          <div className="rounded-xl border border-slate-200 p-3 space-y-3">
            {!editing ? (
              <>
                <div className="flex items-center gap-4 text-xs flex-wrap">
                  <span><span className="text-slate-400">Sentiment:</span> <span className="font-medium">{record.overall_sentiment || "—"}</span></span>
                  <span><span className="text-slate-400">Primary theme:</span> <span className="font-medium">{record.themes?.primary || "—"}</span></span>
                </div>
                <FieldRow label="Secondary" value={record.themes?.secondary} />
                <FieldRow label="Tertiary" value={record.themes?.tertiary} />
                <FieldRow label="Signals" value={(record.signals || []).join(", ")} />
                {(record.brand_sentiments || []).length > 0 && (
                  <div className="text-xs space-y-1">
                    <span className="text-slate-400 block">Brand sentiment</span>
                    {record.brand_sentiments.map((bs) => (
                      <div key={bs.brand} className="flex items-center gap-2">
                        <span className="font-medium w-28 truncate">{bs.brand}{bs.is_primary ? " (primary)" : ""}</span>
                        <SentimentPill sentiment={bs.sentiment} confidence={bs.confidence} />
                      </div>
                    ))}
                  </div>
                )}
                {record.reason && <p className="text-xs text-slate-500 pt-1 border-t border-slate-100"><span className="font-semibold text-slate-400 uppercase tracking-wide">Reason for picking up this article: </span>{record.reason}</p>}
              </>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-xs">
                    <span className="text-slate-400 block mb-1">Overall sentiment</span>
                    <select value={sentiment} onChange={(e) => setSentiment(e.target.value as typeof sentiment)} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm">
                      {SENTIMENT_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </label>
                  <label className="text-xs">
                    <span className="text-slate-400 block mb-1">Confidence (%)</span>
                    <input type="number" min={0} max={100} value={confidence} onChange={(e) => setConfidence(Number(e.target.value))}
                      className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" />
                  </label>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <label className="text-xs"><span className="text-slate-400 block mb-1">Primary theme</span>
                    <input value={themePrimary} onChange={(e) => setThemePrimary(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" /></label>
                  <label className="text-xs"><span className="text-slate-400 block mb-1">Secondary theme</span>
                    <input value={themeSecondary} onChange={(e) => setThemeSecondary(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" /></label>
                  <label className="text-xs"><span className="text-slate-400 block mb-1">Tertiary theme</span>
                    <input value={themeTertiary} onChange={(e) => setThemeTertiary(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" /></label>
                </div>
                <label className="text-xs block"><span className="text-slate-400 block mb-1">Signals (comma-separated)</span>
                  <input value={signals} onChange={(e) => setSignals(e.target.value)} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" /></label>
                {brandSentiments.length > 0 && (
                  <div>
                    <span className="text-xs text-slate-400 block mb-1">Per-brand sentiment</span>
                    <div className="space-y-2">
                      {brandSentiments.map((bs, i) => (
                        <div key={bs.brand} className="flex items-center gap-2">
                          <span className="text-xs font-medium w-28 truncate">{bs.brand}{bs.is_primary ? " (primary)" : ""}</span>
                          <select value={bs.sentiment || "Neutral"} onChange={(e) => updateBrand(i, { sentiment: e.target.value as BrandSentiment["sentiment"] })}
                            className="border border-slate-200 rounded-lg px-2 py-1 text-xs">
                            {SENTIMENT_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                          </select>
                          <input type="number" min={0} max={100}
                            value={Math.round((bs.confidence ?? 0.5) * 100)}
                            onChange={(e) => updateBrand(i, { confidence: Number(e.target.value) / 100 })}
                            className="w-16 border border-slate-200 rounded-lg px-2 py-1 text-xs" />
                          <span className="text-[10px] text-slate-400">% conf</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <label className="text-xs block"><span className="text-slate-400 block mb-1">Reason for picking up this article</span>
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm" /></label>
                {saveError && <div className="text-xs text-red-600">{saveError}</div>}
                <div className="flex items-center gap-2 justify-end pt-1">
                  <button onClick={() => setEditing(false)} className="text-xs font-medium px-3 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100">Cancel</button>
                  <button onClick={handleSave} disabled={saving}
                    className="text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
                    {saving ? "Saving..." : "Save changes"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

type ReviewQueue = "needs_review" | "auto_accepted" | "all";
const DEFAULT_THRESHOLD = 70;
const THRESHOLD_KEY = "hunter.review.confidenceThreshold";

/** Low-confidence rows the analyst hasn't decided on go to the review queue; the rest are auto-accepted
 * (still relevant and counted in analysis, just hidden from the queue). An explicit approve/disapprove wins. */
export function reviewQueueOf(r: EnrichedRecord, thresholdPct: number): "needs_review" | "auto_accepted" {
  const decided = r.approval_status === "approved" || r.approval_status === "disapproved";
  const confidencePct = Math.round((r.overall_sentiment_confidence ?? 0) * 100);
  return !decided && confidencePct < thresholdPct ? "needs_review" : "auto_accepted";
}

function loadThreshold(): number {
  try {
    const v = Number(window.localStorage.getItem(THRESHOLD_KEY));
    return Number.isFinite(v) && v > 0 && v <= 100 ? v : DEFAULT_THRESHOLD;
  } catch {
    return DEFAULT_THRESHOLD;
  }
}

export function EnrichedArticlesTable({ records, loading }: { records: EnrichedRecord[]; loading: boolean }) {
  const [localRecords, setLocalRecords] = useState<EnrichedRecord[]>(records);
  useEffect(() => { setLocalRecords(records); }, [records]);

  const [subTab, setSubTab] = useState<"social" | "traditional" | "irrelevant">("traditional");
  const [threshold, setThreshold] = useState<number>(loadThreshold);
  const [queue, setQueue] = useState<ReviewQueue>("needs_review");
  useEffect(() => {
    try { window.localStorage.setItem(THRESHOLD_KEY, String(threshold)); } catch { /* storage unavailable */ }
  }, [threshold]);
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
    const targets = localRecords.filter((r) => selected.has(rowKey(r)) && r.dataset_id != null);
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
            { id: "needs_review", label: "Needs review" },
            { id: "auto_accepted", label: "Auto-accepted" },
            { id: "all", label: "All" },
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
          Below {threshold}% confidence goes to review; the rest are auto-accepted and still count in the analysis.
        </span>
      </div>

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
              <th className="px-3 py-2.5 w-64">Content</th>
              <th className="px-3 py-2.5 w-24">Author</th>
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
              const approval = APPROVAL_STYLE[r.approval_status || "pending"];
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
                  <td className="px-3 py-2.5"><ClampedCell text={r.content} onSeeMore={() => setOpenRecord(r)} /></td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">{r.author || "—"}</td>
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
                      ? Object.entries(r.entities || {}).filter(([, v]) => v?.length).map(([k, v]) => (
                          <div key={k} className="truncate"><span className="text-slate-400 capitalize">{k}:</span> {v.join(", ")}</div>
                        ))
                      : <span className="text-slate-300">—</span>}
                  </td>
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
