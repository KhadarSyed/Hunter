import { useEffect, useRef, useState } from "react";
import { intelApi, type EnrichedRecord, type BrandSentiment, type DynamicTagDef } from "../../services/intel-api";
import { formatDate, formatDateTime } from "../../utils/format";
import { QuestionDrillDown } from "../QuestionDrillDown";

export const V = "#5B2C9D";
const SENTIMENT_OPTIONS = ["Positive", "Neutral", "Negative"] as const;

export const SENTIMENT_STYLE: Record<string, { color: string; bg: string }> = {
  Positive: { color: "#059669", bg: "#ecfdf5" },
  Neutral: { color: "#64748b", bg: "#f1f5f9" },
  Negative: { color: "#dc2626", bg: "#fef2f2" },
};

export const APPROVAL_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  approved: { color: "#059669", bg: "#ecfdf5", label: "Approved" },
  disapproved: { color: "#dc2626", bg: "#fef2f2", label: "Disapproved" },
  auto_approved: { color: "#0f7b6c", bg: "#f0fdfa", label: "Auto-approved" },
  pending: { color: "#b45309", bg: "#fffbeb", label: "Pending review" },
};

export function publisherDomain(url: string): string {
  try {
    const host = new URL(url).hostname;
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
  }
}

export function formatReviewedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

export function SentimentPill({ sentiment, confidence }: { sentiment: string | null; confidence: number | null }) {
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

export function PublisherCell({ record }: { record: EnrichedRecord }) {
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

/** Tri-state checkbox (supports the "indeterminate" look via a DOM ref, same
 * pattern used for Select All when some-but-not-all visible rows are picked). */
export function TriCheckbox({ checked, indeterminate = false, onChange, ariaLabel }: {
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
export function RecordDrawer({
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

  const approval = APPROVAL_STYLE[approvalOf(record, loadThreshold())];

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
          {record.date && <span>• {formatDate(record.date)}</span>}
          {record.author && <span>• {record.author}</span>}
          {record.url && <a href={record.url} target="_blank" rel="noopener noreferrer" className="hover:underline" style={{ color: V }}>Open original ↗</a>}
        </div>

        <QuestionDrillDown record={record} />

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
            <FieldRow label="Published" value={record.date ? formatDate(record.date) : record.date} />
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

const DEFAULT_THRESHOLD = 70;
export const THRESHOLD_KEY = "hunter.review.confidenceThreshold";

/** Low-confidence rows the analyst hasn't decided on are pending review; the rest are auto-approved (shown,
 * labelled and counted in the analysis). An explicit approve/disapprove wins. */
export function reviewQueueOf(r: EnrichedRecord, thresholdPct: number): "needs_review" | "auto_accepted" {
  const decided = r.approval_status === "approved" || r.approval_status === "disapproved";
  const confidencePct = Math.round((r.overall_sentiment_confidence ?? 0) * 100);
  return !decided && confidencePct < thresholdPct ? "needs_review" : "auto_accepted";
}

/** The approval a row shows: the analyst's decision, else auto-approved at or above the threshold, else pending. */
export function approvalOf(r: EnrichedRecord, thresholdPct: number): "approved" | "disapproved" | "auto_approved" | "pending" {
  if (r.approval_status === "approved" || r.approval_status === "disapproved") return r.approval_status;
  return reviewQueueOf(r, thresholdPct) === "auto_accepted" ? "auto_approved" : "pending";
}

export function loadThreshold(): number {
  try {
    const raw = window.localStorage.getItem(THRESHOLD_KEY);
    const v = raw === null ? NaN : Number(raw);
    return Number.isFinite(v) && v >= 0 && v <= 100 ? v : DEFAULT_THRESHOLD;
  } catch {
    return DEFAULT_THRESHOLD;
  }
}

export function DynamicTagCell({ record, tag }: { record: EnrichedRecord; tag: DynamicTagDef }) {
  const raw = record.dynamic_tags?.[tag.tag_name];
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  if (values.length === 0) return <span className="text-slate-300 text-xs">—</span>;
  const evidence = record.tag_evidence?.[tag.tag_name];
  const confidence = record.tag_confidence?.[tag.tag_name];
  const tip = [evidence ? `Evidence: "${evidence}"` : "No quoted evidence",
               confidence != null ? `Confidence ${Math.round(confidence * 100)}%` : ""].filter(Boolean).join(" · ");
  const tone = (v: string) => v === "Yes" ? "bg-emerald-50 text-emerald-700" : v === "No" ? "bg-slate-100 text-slate-600"
    : tag.tag_type === "entity" ? "bg-sky-50 text-sky-700" : "bg-indigo-50 text-indigo-700";
  return (
    <div className="flex flex-wrap gap-1 cursor-help" title={tip}>
      {values.map((v) => <span key={v} className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${tone(v)}`}>{v}</span>)}
      {confidence != null && <span className="text-[10px] text-slate-400">{Math.round(confidence * 100)}%</span>}
    </div>
  );
}
