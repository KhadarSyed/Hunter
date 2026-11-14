import { useEffect, useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { ArticleComment, RqColumn } from "../../types/dataset";

const KIND: Record<string, string> = {
  comment: "Note for article tagging", rq_comment: "Note for", edit: "Tags corrected", reject: "Rejected for",
  relevant: "Marked relevant for", keep: "Kept although blocked",
};

/** Notes for the agent on one article. "This article" guides article tagging for similar articles, "a question"
 * guides that question's tagging; both are kept in the organization's memory and listed here with who and when. */
export function CommentsPanel({ projectId, articleId, rqs, defaultRq }: {
  projectId: number; articleId: number; rqs: RqColumn[]; defaultRq?: string;
}) {
  const [items, setItems] = useState<ArticleComment[]>([]);
  const [text, setText] = useState("");
  const [scope, setScope] = useState(defaultRq || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(0);

  useEffect(() => {
    let stale = false;
    intelApi.articleComments(projectId, articleId).then((c) => { if (!stale) setItems(c); }).catch(() => { /* list stays empty */ });
    return () => { stale = true; };
  }, [projectId, articleId, key]);

  const add = async () => {
    setSaving(true);
    setError("");
    try {
      await intelApi.addArticleComment(projectId, articleId, text.trim(), scope || null);
      setText("");
      window.setTimeout(() => setKey((k) => k + 1), 600);       // the note is saved in the background
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save the note"); }
    finally { setSaving(false); }
  };

  return (
    <section aria-label="Comments" className="space-y-2 rounded-xl border border-slate-200 p-3">
      <h4 className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Comments for the agent</h4>
      <label className="block text-xs text-slate-500">About
        <select value={scope} onChange={(e) => setScope(e.target.value)} className="mt-1 block w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm">
          <option value="">This article (guides article tagging)</option>
          {rqs.map((q) => <option key={q.id} value={q.id}>{q.id}: {q.question.slice(0, 70)}</option>)}
        </select>
      </label>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={1000} aria-label="Comment"
        placeholder="e.g. Bingo night is an event, not gaming" className="block w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm" />
      {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
      <div className="flex justify-end">
        <button type="button" disabled={saving || !text.trim()} onClick={() => void add()}
          className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">{saving ? "Saving…" : "Add comment"}</button>
      </div>
      {items.length > 0 && (
        <ul className="space-y-1.5 border-t border-slate-100 pt-2">
          {items.map((c) => (
            <li key={c.id} className="text-xs text-slate-700">
              <span className="font-semibold">{KIND[c.kind] ?? c.kind}{c.rq_id ? ` ${c.rq_id}` : ""}</span>
              <span className="text-slate-400"> · {c.by ?? "analyst"} · {new Date(c.at * 1000).toLocaleString("en-US")}</span>
              {c.comment && <p className="mt-0.5 text-slate-600">“{c.comment}”</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
