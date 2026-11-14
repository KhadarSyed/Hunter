import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { intelApi } from "../services/intel-api";
import { useActiveProjectId } from "../context/project-context";
import { TagSchemaModal } from "../components/dataset/TagSchemaView";
import type { TagSchemaField } from "../types/dataset";
import { BooleanDisplay } from "./SearchStrategy";
import { Modal } from "../components/admin/adminUi";

type RQ = { question_id: string; question: string; query: string; status?: "draft" | "approved" };

const V = "#5B2C9D";
const isApproved = (r: RQ) => (r.status ?? "approved") === "approved";
const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const QUERY_LINES = 15;           // a card shows this many lines of its query; the rest scrolls

/** The question in at most 3 lines; when it is longer, hovering (or focusing) it shows the whole text. */
function ClampedQuestion({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [clamped, setClamped] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setClamped(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(check);
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [text]);
  return (
    <div className="group relative min-w-0 flex-1">
      <p ref={ref} tabIndex={clamped ? 0 : undefined}
         className="line-clamp-3 rounded text-sm font-semibold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-violet-200">
        {text}
      </p>
      {clamped && (
        <div role="tooltip"
             className="invisible absolute left-0 top-full z-30 mt-1 w-[min(32rem,80vw)] rounded-lg border border-slate-200 bg-white p-3 text-sm font-semibold text-slate-800 opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
          {text}
        </div>
      )}
    </div>
  );
}

/** The whole question and its query in a pop-up; it closes once the change is saved. */
function EditModal({ rq, busy, error, onSave, onClose }: {
  rq: RQ; busy: boolean; error: string | null;
  onSave: (question: string, query: string) => Promise<boolean>; onClose: () => void;
}) {
  const [q, setQ] = useState(rq.question);
  const [query, setQuery] = useState(rq.query);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  const save = async () => {
    setFailed(false);
    if (await onSave(q.trim(), query.trim())) onClose();
    else setFailed(true);
  };
  return (
    <Modal title={"Edit " + rq.question_id} onClose={() => { if (!busy) onClose(); }} wide>
      <div className="space-y-4">
        <label className="block text-xs font-semibold text-slate-600">Research question
          <textarea autoFocus aria-label={rq.question_id + " question"} value={q} onChange={(e) => setQ(e.target.value)}
            rows={4} maxLength={1000}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800 focus:border-[#5B2C9D] focus:outline-none" />
        </label>
        <label className="block text-xs font-semibold text-slate-600">Boolean query
          <textarea aria-label={rq.question_id + " Boolean query"} value={query} onChange={(e) => setQuery(e.target.value)}
            rows={12} maxLength={20000}
            className="mt-1 max-h-[45vh] w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs leading-relaxed text-slate-800 focus:border-[#5B2C9D] focus:outline-none" />
        </label>
        {failed && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error || "Could not save the change"}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" disabled={busy} onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">Cancel</button>
          <button type="button" disabled={!q.trim() || busy} onClick={save}
            className="rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" style={{ background: V }}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function AddForm({ onAdd, onClose }: { onAdd: (question: string, query: string) => Promise<boolean>; onClose: () => void }) {
  const [question, setQuestion] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    const ok = await onAdd(question.trim(), query.trim());
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <div className="bg-white rounded-xl border-2 p-5 space-y-3" style={{ borderColor: "#c4b5fd" }}>
      <h2 className="text-sm font-semibold text-slate-800">New research question</h2>
      <label className="block text-xs font-medium text-slate-600">Research question
        <textarea autoFocus value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} maxLength={1000}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800" />
      </label>
      <label className="block text-xs font-medium text-slate-600">Boolean query (optional)
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} maxLength={10000}
          className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800" />
      </label>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="text-sm px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100">Cancel</button>
        <button type="button" onClick={save} disabled={!question.trim() || saving}
          className="text-sm px-4 py-1.5 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
          {saving ? "Adding…" : "Add question"}
        </button>
      </div>
    </div>
  );
}

function Card({ rq, busy, error, schema, onStatus, onEdit, onDelete }: {
  rq: RQ; busy: boolean; error: string | null; schema?: TagSchemaField[];
  onStatus: (s: "draft" | "approved") => void;
  onEdit: (question: string, query: string) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  const approved = isApproved(rq);
  const btn = "text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50";

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
            <ClampedQuestion text={rq.question} />
          </div>
          <span className={`text-[11px] font-semibold px-2 py-1 rounded-full shrink-0 ${approved ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
            {approved ? "Approved" : "Draft"}
          </span>
        </div>

        {rq.query ? (
          <BooleanDisplay query={rq.query} label={`${rq.question_id} Query`} maxLines={QUERY_LINES} onCopy={() => { void navigator.clipboard?.writeText(rq.query); }} />
        ) : (
          <p className="text-xs text-slate-400">No Boolean query yet.</p>
        )}
        {schema && (
          <button type="button" onClick={() => setShowSchema(true)}
            className="self-start text-xs font-medium hover:underline" style={{ color: V }}>
            View tag schema · {schema.length} field{schema.length === 1 ? "" : "s"}
          </button>
        )}
        {showSchema && schema && (
          <TagSchemaModal title={`${rq.question_id} · ${rq.question}`} fields={schema} onClose={() => setShowSchema(false)} />
        )}

        {editing && <EditModal rq={rq} busy={busy} error={error} onSave={onEdit} onClose={() => setEditing(false)} />}

        <div className="flex flex-wrap gap-2 justify-end mt-auto pt-1">
          <button type="button" className={btn} disabled={busy} onClick={() => onStatus(approved ? "draft" : "approved")}>
            {approved ? `Un-approve ${rq.question_id}` : `Approve ${rq.question_id}`}
          </button>
          <button type="button" className={btn} onClick={() => setEditing(true)}>Edit {rq.question_id}</button>
          <button type="button" className={`${btn} text-red-600`} onClick={() => setConfirming(true)}>Delete {rq.question_id}</button>
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
  const [adding, setAdding] = useState(false);
  // Tag schemas per approved RQ (built at the first tagging run), shown read-only on each card
  const [schemas, setSchemas] = useState<Record<string, TagSchemaField[]>>({});
  useEffect(() => {
    if (!projectId) return;
    intelApi.datasetRqs(projectId)
      .then((list) => setSchemas(Object.fromEntries(list.map((q) => [q.rq_id, q.schema.fields]))))
      .catch(() => setSchemas({}));
  }, [projectId, rqs]);

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
    <div className="min-h-full flex flex-col">
      <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-slate-900">Matching label</h1>
            <p className="text-sm text-slate-500 mt-0.5">Approve the research questions to tag. Only approved questions are tagged and reach the deck.</p>
          </div>
          <button type="button" onClick={() => setAdding(true)} disabled={adding || strategyId == null}
            className="shrink-0 text-sm font-medium px-4 py-2 rounded-lg border disabled:opacity-50 hover:bg-[#f5f3ff]"
            style={{ borderColor: V, color: V }}>+ Add research question</button>
        </div>
      </div>

      <div className="flex-1 max-w-7xl w-full mx-auto px-6 py-6 space-y-5">
        {error && <div role="alert" className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-4 py-2">{error}</div>}
        {hint && <div role="status" className="text-sm text-violet-800 bg-violet-50 border border-violet-100 rounded-lg px-4 py-2">{hint}</div>}
        {adding && (
          <AddForm onClose={() => setAdding(false)}
            onAdd={(question, query) => run((sid) => intelApi.addResearchQuestion(sid, question, query), "Failed to add")} />
        )}
        {loading ? <p className="text-sm text-slate-400">Loading…</p> : (
          <>
            {rqs.length === 0 && <p className="text-sm text-slate-500">No research questions yet. Approve a search strategy or add one.</p>}
            {/* every question in one row: they share the width, each at least 20rem; more than fit scroll sideways */}
            <div className="grid grid-flow-col auto-cols-[minmax(20rem,1fr)] gap-4 items-stretch overflow-x-auto pb-3">
            {rqs.map((rq) => (
              <Card key={rq.question_id} rq={rq} busy={busy} error={error} schema={schemas[rq.question_id]}
                onStatus={(s) => void run((sid) => intelApi.setResearchQuestionStatus(sid, rq.question_id, s), "Failed to update status")}
                onEdit={(question, query) => edit(rq, question, query)}
                onDelete={() => void run((sid) => intelApi.deleteResearchQuestion(sid, rq.question_id), "Failed to delete")} />
            ))}
            </div>
          </>
        )}
      </div>

      <div className="sticky bottom-0 z-20 border-t border-slate-200 bg-white/95 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <button type="button" onClick={() => onNavigate("search-strategy")}
            className="text-sm font-medium px-4 py-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
            ← Back to Search Strategy
          </button>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-500">{approvedCount} of {rqs.length} approved</span>
            <button type="button" disabled={approvedCount === 0} onClick={() => onNavigate("data-set")}
              className="text-sm font-medium px-5 py-2 rounded-lg text-white disabled:opacity-50" style={{ background: V }}>
              Go to Data set →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
