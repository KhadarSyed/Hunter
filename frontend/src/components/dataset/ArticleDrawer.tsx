import { useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { ArticleRow, RqColumn } from "../../types/dataset";
import { formatDate } from "../../utils/format";
import { CountryFlag } from "../CountryFlag";
import { SentimentPill } from "./cells";
import { CommentsPanel } from "./CommentsPanel";

const SENTIMENTS = ["Positive", "Neutral", "Negative"];
const input = "w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm";
const ACCESS_NOTE: Record<string, string> = {
  summary_only: "The site needs a subscription, so only the export's text is shown. The agent remembers the site and does not scrape it again.",
  blocked: "The site refused the reader, so only the export's text is shown. The agent remembers the site and does not scrape it again.",
  not_reachable: "The full article could not be read; the export's text is shown.",
};

type Tag = { label: string; confidence?: number; reason?: string; evidence?: string[] };
type Entity = { canonical_name: string; entity_type?: string; relationship_to_monitored_brand?: string | null; description?: string | null; keywords?: string[]; evidence?: string[] };
type Rich = {
  summary?: string;
  sentiment?: { sentiment: string; confidence: number; reason: string; evidence?: string[]; sarcasm?: string };
  classification?: { industry?: Tag | null; category?: Tag | null; group?: Tag | null; signals?: Tag[]; primary_theme?: Tag | null; secondary_themes?: Tag[]; tertiary_themes?: Tag[] };
  entities?: Record<string, Entity[]>;
  relevancy?: { assessments?: { brand: string; relevancy_score: number; reason: string }[] };
  brand_aspect_sentiments?: { assessments?: { brand: string; aspect: string; sentiment: string; reason: string }[] };
};

/** Right-side drawer for one article: source details and full text, the tags (the rich media-intelligence format when
 * present), per-question rows, comments for the agent, and Approve / Reject. Every edit is kept as an example for
 * similar articles (domains/feedback). */
export function ArticleDrawer({ projectId, row, rqs, activeRq, onClose, onSaved, onDecide }: {
  projectId: number; row: ArticleRow; rqs: RqColumn[]; activeRq?: string; onClose: () => void; onSaved: () => void;
  onDecide?: (status: "approved" | "irrelevant") => void;
}) {
  const t = row.tags;
  const rich = (t.format === 2 ? t.enrichment : undefined) as Rich | undefined;
  const [editing, setEditing] = useState(false);
  const [sentiment, setSentiment] = useState(row.sentiment || "Neutral");
  const [themes, setThemes] = useState([t.themes?.primary, t.themes?.secondary, t.themes?.tertiary].map((x) => x ?? ""));
  const [brands, setBrands] = useState((t.brands ?? []).map((b) => b.brand).join(", "));
  const [richText, setRichText] = useState(() => (rich ? JSON.stringify(rich, null, 2) : ""));
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      if (rich) {
        let parsed: Record<string, unknown>;
        try { parsed = JSON.parse(richText); } catch { throw new Error("The tags are not valid JSON"); }
        await intelApi.editEnrichment(projectId, row.id, parsed, comment.trim() || undefined);
      } else {
        await intelApi.editArticle(projectId, row.id, {
          sentiment, themes: themes.map((x) => x.trim()).filter(Boolean),
          brands: brands.split(",").map((b) => b.trim()).filter(Boolean), comment: comment.trim() || undefined,
        });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
      setSaving(false);
    }
  };

  const shown = activeRq ? rqs.filter((q) => q.id === activeRq) : rqs;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div role="dialog" aria-modal="true" aria-label="Article" className="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="space-y-1.5 border-b border-slate-100 p-5">
          <div className="flex items-start justify-between gap-4">
            <h3 className="text-base font-semibold text-slate-800">
              {row.url?.startsWith("http") ? <a href={row.url} target="_blank" rel="noopener noreferrer" className="hover:text-[#5B2C9D] hover:underline">{row.title || row.author_name || "(untitled)"}</a> : row.title || "(untitled)"}
            </h3>
            <button type="button" aria-label="Close" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span>{row.outlet}</span>
            {row.published && <span>{formatDate(row.published)}</span>}
            <span>{row.channel === "social" ? "Account" : "Author"}: {row.author_name || "not in the export (read from the page byline when the site allows it)"}{row.author_id ? ` (${row.author_id})` : ""}</span>
            {row.country ? <CountryFlag country={row.country} showLabel /> : <span>Country: unknown</span>}
            <span className="rounded bg-slate-100 px-1.5 py-0.5">{row.channel === "social" ? "Social post" : row.content_status.replace("_", " ")}</span>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          <section className="space-y-1">
            <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{row.channel === "social" ? "Post" : "Full article"}</h4>
            {ACCESS_NOTE[row.content_status] && <p className="text-xs text-amber-700">{ACCESS_NOTE[row.content_status]}</p>}
            <p className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-700">{row.content || row.summary || "No text."}</p>
          </section>

          <section className="rounded-xl border border-slate-200 p-3">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Tags{t.quality?.status ? ` · quality check ${t.quality.status}` : ""}</h4>
              {!editing && <button type="button" onClick={() => setEditing(true)} className="text-[11px] font-medium text-[#5B2C9D] hover:underline">Edit tags</button>}
            </div>
            {editing ? (
              <div className="space-y-2">
                {rich ? (
                  <label className="block text-xs text-slate-500">Every tagged point (checked against the format when saved)
                    <textarea value={richText} onChange={(e) => setRichText(e.target.value)} rows={18} spellCheck={false} className={`${input} font-mono text-xs`} /></label>
                ) : (
                  <>
                    <label className="block text-xs text-slate-500">Sentiment
                      <select value={sentiment} onChange={(e) => setSentiment(e.target.value)} className={input}>{SENTIMENTS.map((s) => <option key={s}>{s}</option>)}</select></label>
                    {["Primary", "Secondary", "Tertiary"].map((n, i) => (
                      <label key={n} className="block text-xs text-slate-500">{n} theme
                        <input value={themes[i]} onChange={(e) => setThemes(themes.map((x, j) => (j === i ? e.target.value : x)))} className={input} /></label>
                    ))}
                    <label className="block text-xs text-slate-500">Brands (comma-separated)
                      <input value={brands} onChange={(e) => setBrands(e.target.value)} className={input} /></label>
                  </>
                )}
                <label className="block text-xs text-slate-500">Why? (optional; the agent learns from your correction for similar articles)
                  <input value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} className={input} /></label>
                {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setEditing(false)} className="px-3 py-1.5 text-xs text-slate-500">Cancel</button>
                  <button type="button" disabled={saving} onClick={save} className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">{saving ? "Saving…" : "Save changes"}</button>
                </div>
              </div>
            ) : rich ? <RichView rich={rich} /> : (
              <div className="space-y-1.5 text-xs text-slate-700">
                <SentimentPill sentiment={row.sentiment} confidence={row.sentiment_confidence} />
                {t.sentiment_summary && <p className="text-slate-500">{t.sentiment_summary}</p>}
                <p>Themes: {[t.themes?.primary, t.themes?.secondary, t.themes?.tertiary].filter(Boolean).join(" · ") || "—"}</p>
                <p>Brands: {(t.brands ?? []).map((b) => b.brand).join(", ") || "—"}</p>
                <p>Signals: {(t.signals ?? []).join(", ") || "—"}</p>
                <p>Category / group: {[t.category, t.group].filter(Boolean).join(" · ") || "—"}</p>
                <p>Entities: {Object.entries(t.entities ?? {}).filter(([, v]) => v.length).map(([k, v]) => `${k}: ${v.join(", ")}`).join(" · ") || "—"}</p>
              </div>
            )}
          </section>

          {shown.map((q) => row.rq[q.id] && <RqRowCard key={q.id} projectId={projectId} articleId={row.id} q={q} row={row} onSaved={onSaved} />)}

          <CommentsPanel projectId={projectId} articleId={row.id} rqs={rqs} defaultRq={activeRq} />
        </div>

        {onDecide && (
          <div className="flex justify-end gap-2 border-t border-slate-100 p-4">
            <button type="button" onClick={() => onDecide("irrelevant")} className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50">Reject{activeRq ? ` for ${activeRq}` : ""}</button>
            <button type="button" onClick={() => onDecide("approved")} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700">Approve{activeRq ? ` for ${activeRq}` : ""}</button>
          </div>
        )}
      </div>
    </div>
  );
}

function TagLine({ name, tag }: { name: string; tag?: Tag | null }) {
  if (!tag) return null;
  return (
    <div className="text-xs">
      <span className="font-semibold text-slate-700">{name}: {tag.label}</span>
      {tag.confidence != null && <span className="text-slate-400"> · {Math.round(tag.confidence * 100)}%</span>}
      {tag.reason && <p className="text-slate-500">{tag.reason}</p>}
      {tag.evidence?.[0] && <p className="border-l-2 border-slate-200 pl-2 text-slate-400">“{tag.evidence[0]}”</p>}
    </div>
  );
}

function RichView({ rich }: { rich: Rich }) {
  const c = rich.classification ?? {};
  const ents = Object.entries(rich.entities ?? {}).filter(([, v]) => v?.length);
  return (
    <div className="space-y-3 text-xs text-slate-700">
      {rich.summary && <p>{rich.summary}</p>}
      {rich.sentiment && (
        <div><span className="font-semibold capitalize">Sentiment: {rich.sentiment.sentiment}</span>
          <span className="text-slate-400"> · {Math.round(rich.sentiment.confidence * 100)}% · sarcasm {rich.sentiment.sarcasm ?? "absent"}</span>
          <p className="text-slate-500">{rich.sentiment.reason}</p></div>
      )}
      {(rich.relevancy?.assessments ?? []).map((a) => (
        <p key={a.brand}><span className="font-semibold">Relevancy to {a.brand}: {Math.round(a.relevancy_score * 100)}%</span> <span className="text-slate-500">{a.reason}</span></p>
      ))}
      {(rich.brand_aspect_sentiments?.assessments ?? []).map((a, i) => (
        <p key={i}><span className="font-semibold">{a.brand} · {a.aspect}:</span> <span className="capitalize">{a.sentiment}</span> <span className="text-slate-500">{a.reason}</span></p>
      ))}
      <TagLine name="Industry" tag={c.industry} /><TagLine name="Category" tag={c.category} /><TagLine name="Group" tag={c.group} />
      <TagLine name="Primary theme" tag={c.primary_theme} />
      {(c.secondary_themes ?? []).map((x, i) => <TagLine key={`s${i}`} name="Secondary theme" tag={x} />)}
      {(c.tertiary_themes ?? []).map((x, i) => <TagLine key={`t${i}`} name="Tertiary theme" tag={x} />)}
      {(c.signals ?? []).map((x, i) => <TagLine key={`g${i}`} name="Signal" tag={x} />)}
      {ents.map(([group, list]) => (
        <div key={group}><p className="font-semibold capitalize">{group.replace(/_/g, " ")}</p>
          {list.map((e, i) => (
            <p key={i} className="text-slate-600">{e.canonical_name}{e.relationship_to_monitored_brand ? ` (${e.relationship_to_monitored_brand})` : ""}
              {e.description ? ` · ${e.description}` : ""}{e.keywords?.length ? ` · keywords: ${e.keywords.join(", ")}` : ""}</p>
          ))}</div>
      ))}
    </div>
  );
}

function RqRowCard({ projectId, articleId, q, row, onSaved }: { projectId: number; articleId: number; q: RqColumn; row: ArticleRow; onSaved: () => void }) {
  const rr = row.rq[q.id];
  const [editing, setEditing] = useState(false);
  const [confidence, setConfidence] = useState(rr.match_confidence ?? 0);
  const [reason, setReason] = useState(rr.reason ?? "");
  const [tags, setTags] = useState(() => JSON.stringify(rr.tags ?? {}, null, 2));
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const save = async () => {
    setError("");
    try {
      let parsed: Record<string, unknown>;
      try { parsed = JSON.parse(tags); } catch { throw new Error("The question's tags are not valid JSON"); }
      await intelApi.editRqRow(projectId, articleId, q.id, { match_confidence: confidence, reason, tags: parsed, comment: comment.trim() || undefined });
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save"); }
  };
  return (
    <section className="space-y-1.5 rounded-xl border border-slate-200 p-3 text-xs text-slate-700">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold text-slate-800">{q.id} · {rr.status === "irrelevant" ? "rejected" : rr.status}{rr.match_confidence != null ? ` · ${Math.round(rr.match_confidence * 100)}%` : ""}</p>
        {!editing && <button type="button" onClick={() => setEditing(true)} className="text-[11px] font-medium text-[#5B2C9D] hover:underline">Edit</button>}
      </div>
      <p className="text-slate-500">{q.question}</p>
      {editing ? (
        <div className="space-y-2">
          <label className="block text-slate-500">Match confidence (0–1)
            <input type="number" min={0} max={1} step={0.01} value={confidence} onChange={(e) => setConfidence(Number(e.target.value))} className={input} /></label>
          <label className="block text-slate-500">Why it matches
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} className={input} /></label>
          <label className="block text-slate-500">{q.id} tags
            <textarea value={tags} onChange={(e) => setTags(e.target.value)} rows={6} spellCheck={false} className={`${input} font-mono text-xs`} /></label>
          <label className="block text-slate-500">Note for this question's tagging (optional)
            <input value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} className={input} /></label>
          {error && <p role="alert" className="text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setEditing(false)} className="px-3 py-1.5 text-slate-500">Cancel</button>
            <button type="button" onClick={() => void save()} className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 font-medium text-white">Save</button>
          </div>
        </div>
      ) : (
        <>
          {rr.reason && <p>{rr.reason}</p>}
          {Object.entries(rr.tags ?? {}).map(([k, v]) => <p key={k}><span className="font-semibold">{k}:</span> {Array.isArray(v) ? v.join(", ") : String(v)}</p>)}
          {rr.keywords?.length > 0 && <p className="text-slate-500">Query terms found: {rr.keywords.join(", ")}</p>}
        </>
      )}
    </section>
  );
}
