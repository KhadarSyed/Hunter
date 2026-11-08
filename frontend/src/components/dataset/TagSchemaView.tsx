import { useEffect } from "react";
import type { TagSchemaField } from "../../types/dataset";

const V = "#5B2C9D";

/** "sentiment_toward_brand" -> "Sentiment toward brand". */
export const readable = (name: string) => {
  const s = name.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

const KIND: Record<string, string> = {
  classification: "Pick one",
  multi_classification: "Pick any that apply",
  entity: "Names found in the article",
};

/** A question's tag schema in plain words: each field's name, what it captures, and the values it may take. */
export function TagSchemaView({ fields }: { fields: TagSchemaField[] }) {
  if (fields.length === 0) return <p className="text-sm text-slate-400">No tag schema yet; it is built at the first tagging run.</p>;
  return (
    <ul className="space-y-3">
      {fields.map((f) => (
        <li key={f.name} className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-semibold text-slate-800">{readable(f.name)}</span>
            <span className="rounded-full bg-[#f5f3ff] px-2 py-0.5 text-[11px] font-medium" style={{ color: V }}>
              {KIND[f.type] ?? readable(f.type)}
            </span>
          </div>
          {f.definition && <p className="mt-1 text-xs text-slate-500">{f.definition}</p>}
          {f.values.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {f.values.map((v) => (
                <span key={v} className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-700">{readable(v)}</span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs italic text-slate-400">Any value the article names</p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The tag schema in a pop-up window; closes on Escape, the backdrop or the Close button. */
export function TagSchemaModal({ title, fields, onClose }: { title: string; fields: TagSchemaField[]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label={`Tag schema: ${title}`}
        className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-slate-50 shadow-xl">
        <div className="flex items-start justify-between gap-4 rounded-t-xl border-b border-slate-200 bg-white px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-slate-900">Tag schema</h2>
            <p className="mt-0.5 text-sm text-slate-500">{title}</p>
            <p className="mt-1 text-xs text-slate-400">The tags each matched article gets for this question ({fields.length} fields).</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="rounded-lg px-2 py-1 text-lg leading-none text-slate-500 hover:bg-slate-100">×</button>
        </div>
        <div className="overflow-y-auto px-6 py-4"><TagSchemaView fields={fields} /></div>
        <div className="flex justify-end rounded-b-xl border-t border-slate-200 bg-white px-6 py-3">
          <button type="button" onClick={onClose} className="rounded-lg px-4 py-1.5 text-sm font-medium text-white" style={{ background: V }}>Close</button>
        </div>
      </div>
    </div>
  );
}
