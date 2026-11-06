import { useCallback, useEffect, useState } from "react";
import { intelApi } from "../services/intel-api";
import { useActiveProjectId } from "../context/project-context";
import { BooleanDisplay } from "./SearchStrategy";

type RQ = { question_id: string; question: string; query: string; status?: "draft" | "approved" };

const V = "#5B2C9D";
const isApproved = (r: RQ) => (r.status ?? "approved") === "approved";
const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

function AddForm({ onAdd }: { onAdd: (question: string, query: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    const ok = await onAdd(question.trim(), query.trim());
    setSaving(false);
    if (ok) { setQuestion(""); setQuery(""); setOpen(false); }
  };
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="w-full rounded-xl border-2 border-dashed px-5 py-4 text-sm font-medium hover:bg-[#f5f3ff]"
        style={{ borderColor: "#c4b5fd", color: V }}>+ Add research question</button>
    );
  }
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
      <label className="block text-xs font-medium text-slate-600">Research question
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} maxLength={1000}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800" />
      </label>
      <label className="block text-xs font-medium text-slate-600">Boolean query (optional)
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} maxLength={10000}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800" />
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setOpen(false)} className="text-sm px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100">Cancel</button>
        <button type="button" onClick={save} disabled={!question.trim() || saving}
          className="text-sm px-4 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
          {saving ? "Adding…" : "Add question"}
        </button>
      </div>
    </div>
  );
}

function Card({ rq, busy, onStatus, onEdit, onDelete }: {
  rq: RQ; busy: boolean;
  onStatus: (s: "draft" | "approved") => void;
  onEdit: (question: string, query: string) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [q, setQ] = useState(rq.question);
  const [query, setQuery] = useState(rq.query);
  const approved = isApproved(rq);
  const btn = "text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50";

  const save = async () => { if (await onEdit(q.trim(), query.trim())) setEditing(false); };

  return (
    <div className={`h-full flex flex-col bg-white border rounded-xl shadow-sm ${approved ? "border-emerald-200" : "border-slate-200"}`}>
      {confirming && (
        <div className="px-5 py-3 bg-red-50 border-b border-red-100 rounded-t-xl flex items-center justify-between">
          <span className="text-xs text-red-700 font-medium">Delete {rq.question_id}?</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setConfirming(false)} className="text-[11px] font-medium px-3 py-1 rounded-lg text-slate-500 hover:bg-white">Cancel</button>
            <button type="button" onClick={() => { setConfirming(false); onDelete(); }} className="text-[11px] font-medium px-3 py-1 rounded-lg bg-red-600 text-white hover:bg-red-700">Delete</button>
          </div>
        </div>
      )}
      <div className="p-5 space-y-3 flex-1 flex flex-col min-w-0">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <span className="text-xs font-bold px-2 py-1 rounded shrink-0 tabular-nums" style={{ color: V, background: "#f5f3ff" }}>{rq.question_id}</span>
            {editing ? (
              <textarea aria-label={`${rq.question_id} question`} value={q} onChange={(e) => setQ(e.target.value)} rows={2}
                className="flex-1 text-sm font-semibold text-slate-800 border border-slate-200 rounded-lg px-3 py-2" />
            ) : (
              <p className="text-sm font-semibold text-slate-800">{rq.question}</p>
            )}
          </div>
          <span className={`text-[11px] font-semibold px-2 py-1 rounded-full shrink-0 ${approved ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
            {approved ? "Approved" : "Draft"}
          </span>
        </div>

        {editing ? (
          <textarea aria-label={`${rq.question_id} Boolean query`} value={query} onChange={(e) => setQuery(e.target.value)} rows={3}
            className="w-full font-mono text-xs text-slate-800 border border-slate-200 rounded-lg px-3 py-2" />
        ) : rq.query ? (
          <BooleanDisplay query={rq.query} label={`${rq.question_id} Query`} onCopy={() => { void navigator.clipboard?.writeText(rq.query); }} />
        ) : (
          <p className="text-xs text-slate-400">No Boolean query yet.</p>
        )}

        <div className="flex flex-wrap gap-2 justify-end mt-auto pt-1">
          {editing ? (
            <>
              <button type="button" className={btn} onClick={() => { setQ(rq.question); setQuery(rq.query); setEditing(false); }}>Cancel</button>
              <button type="button" disabled={!q.trim() || busy} onClick={save}
                className="text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>Save</button>
            </>
          ) : (
            <>
              <button type="button" className={btn} disabled={busy} onClick={() => onStatus(approved ? "draft" : "approved")}>
                {approved ? `Un-approve ${rq.question_id}` : `Approve ${rq.question_id}`}
              </button>
              <button type="button" className={btn} onClick={() => setEditing(true)}>Edit {rq.question_id}</button>
              <button type="button" className={`${btn} text-red-600`} onClick={() => setConfirming(true)}>Delete {rq.question_id}</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function MatchingLabel({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId();
  const [strategyId, setStrategyId] = useState<number | null>(null);
  const [rqs, setRqs] = useState<RQ[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const r = await intelApi.getStrategy(projectId);
      setStrategyId(r.strategy_id);
      setRqs(((r.strategy as { research_question_queries?: RQ[] }).research_question_queries) ?? []);
      setError(null);
    } catch (e) {
      setError(errMsg(e, "Failed to load research questions"));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const run = async (fn: (sid: number) => Promise<unknown>, fallback: string): Promise<boolean> => {
    if (strategyId == null) return false;
    setHint(null);
    setBusy(true);
    try { await fn(strategyId); await load(); return true; }
    catch (e) { setError(errMsg(e, fallback)); return false; }
    finally { setBusy(false); }
  };

  const edit = async (rq: RQ, question: string, query: string) => {
    const ok = await run((sid) => intelApi.editResearchQuestion(sid, rq.question_id, question, query), "Failed to save");
    if (ok && projectId) {
      const t = await intelApi.taggingState(projectId).catch(() => null);
      const tagged = !!t && (t.counts.tags.tagged ?? 0) > 0;
      setHint(tagged ? `${rq.question_id} will be re-tagged on the next Start tagging.` : null);
    }
    return ok;
  };

  const approvedCount = rqs.filter(isApproved).length;

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Matching label</h1>
        <p className="text-sm text-slate-500 mt-1">Approve the research questions to tag. Only approved questions are tagged and reach the deck.</p>
      </div>
      {error && <div role="alert" className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-4 py-2">{error}</div>}
      {hint && <div role="status" className="text-sm text-violet-800 bg-violet-50 border border-violet-100 rounded-lg px-4 py-2">{hint}</div>}
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
        <>
          {rqs.length === 0 && <p className="text-sm text-slate-500">No research questions yet. Approve a search strategy or add one.</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-stretch">
          {rqs.map((rq) => (
            <Card key={`${rq.question_id}|${rq.question}|${rq.query}`} rq={rq} busy={busy}
              onStatus={(s) => void run((sid) => intelApi.setResearchQuestionStatus(sid, rq.question_id, s), "Failed to update status")}
              onEdit={(question, query) => edit(rq, question, query)}
              onDelete={() => void run((sid) => intelApi.deleteResearchQuestion(sid, rq.question_id), "Failed to delete")} />
          ))}
          </div>
          <AddForm onAdd={(question, query) => run((sid) => intelApi.addResearchQuestion(sid, question, query), "Failed to add")} />
        </>
      )}
      <div className="flex items-center justify-between pt-2">
        <span className="text-xs text-slate-500">{approvedCount} of {rqs.length} approved</span>
        <button type="button" disabled={approvedCount === 0} onClick={() => onNavigate("data-set")}
          className="text-sm font-medium px-5 py-2 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
          Go to Data set
        </button>
      </div>
    </div>
  );
}
