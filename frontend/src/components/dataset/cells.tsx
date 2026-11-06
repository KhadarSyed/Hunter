import { useEffect, useRef, useState } from "react";
import { type EnrichedRecord, type DynamicTagDef } from "../../services/intel-api";

export const V = "#5B2C9D";

export const SENTIMENT_STYLE: Record<string, { color: string; bg: string }> = {
  Positive: { color: "#059669", bg: "#ecfdf5" },
  Neutral: { color: "#64748b", bg: "#f1f5f9" },
  Negative: { color: "#dc2626", bg: "#fef2f2" },
};

export function publisherDomain(url: string): string {
  try {
    const host = new URL(url).hostname;
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "";
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
