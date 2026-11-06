import { useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { ArticleRow, RqColumn } from "../../types/dataset";
import { formatDate } from "../../utils/format";
import { CountryFlag } from "../CountryFlag";
import { SentimentPill } from "./cells";

const SENTIMENTS = ["Positive", "Neutral", "Negative"];
const input = "w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm";

/** Right-side drawer for one article: the export's fields, its tags, per-RQ rows, and an edit of sentiment,
 * themes and brands (the server approves an edited article for every RQ it matched). */
export function ArticleDrawer({ projectId, row, rqs, onClose, onSaved }: {
  projectId: number; row: ArticleRow; rqs: RqColumn[]; onClose: () => void; onSaved: () => void;
}) {
  const t = row.tags;
  const [editing, setEditing] = useState(false);
  const [sentiment, setSentiment] = useState(row.sentiment || "Neutral");
  const [themes, setThemes] = useState([t.themes?.primary, t.themes?.secondary, t.themes?.tertiary].map((x) => x ?? ""));
  const [brands, setBrands] = useState((t.brands ?? []).map((b) => b.brand).join(", "));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await intelApi.editArticle(projectId, row.id, {
        sentiment, themes: themes.map((x) => x.trim()).filter(Boolean),
        brands: brands.split(",").map((b) => b.trim()).filter(Boolean),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div role="dialog" aria-modal="true" aria-label="Article" className="relative h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-start justify-between gap-4">
          <h3 className="text-base font-semibold text-slate-800">{row.title || "(untitled)"}</h3>
          <button type="button" aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-slate-400">
          <span>{row.outlet}</span>
          {row.published && <span>• {formatDate(row.published)}</span>}
          {row.country && <CountryFlag country={row.country} showLabel />}
          {row.url && <a href={row.url} target="_blank" rel="noopener noreferrer" className="text-[#5B2C9D] hover:underline">Open original ↗</a>}
        </div>
        <p className="mb-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{row.content || row.summary}</p>

        <div className="mb-4 rounded-xl border border-slate-200 p-3">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Tags</h4>
            {!editing && <button type="button" onClick={() => setEditing(true)} className="text-[11px] font-medium text-[#5B2C9D] hover:underline">Edit tags</button>}
          </div>
          {editing ? (
            <div className="space-y-2">
              <label className="block text-xs text-slate-500">Sentiment
                <select value={sentiment} onChange={(e) => setSentiment(e.target.value)} className={input}>{SENTIMENTS.map((s) => <option key={s}>{s}</option>)}</select></label>
              {["Primary", "Secondary", "Tertiary"].map((n, i) => (
                <label key={n} className="block text-xs text-slate-500">{n} theme
                  <input value={themes[i]} onChange={(e) => setThemes(themes.map((x, j) => (j === i ? e.target.value : x)))} className={input} /></label>
              ))}
              <label className="block text-xs text-slate-500">Brands (comma-separated)
                <input value={brands} onChange={(e) => setBrands(e.target.value)} className={input} /></label>
              {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEditing(false)} className="px-3 py-1.5 text-xs text-slate-500">Cancel</button>
                <button type="button" disabled={saving} onClick={save} className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">{saving ? "Saving…" : "Save changes"}</button>
              </div>
            </div>
          ) : (
            <div className="space-y-1.5 text-xs text-slate-700">
              <SentimentPill sentiment={row.sentiment} confidence={row.sentiment_confidence} />
              <p>Themes: {[t.themes?.primary, t.themes?.secondary, t.themes?.tertiary].filter(Boolean).join(" · ") || "—"}</p>
              <p>Brands: {(t.brands ?? []).map((b) => b.brand).join(", ") || "—"}</p>
              <p>Signals: {(t.signals ?? []).join(", ") || "—"}</p>
            </div>
          )}
        </div>

        {rqs.map((q) => {
          const rr = row.rq[q.id];
          return rr && (
            <div key={q.id} className="mb-3 rounded-xl border border-slate-200 p-3 text-xs text-slate-700">
              <p className="font-semibold text-slate-800">{q.id} · {rr.status}</p>
              {rr.summary && <p className="mt-1">{rr.summary}</p>}
              {rr.reason && <p className="mt-1 text-slate-500">{rr.reason}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
