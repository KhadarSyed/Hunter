import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import { intelApi } from "../../services/intel-api";
import type { RqEstimate, RqPreview, RqSummary } from "../../types/dataset";
import { QueryEditor } from "./QueryEditor";
import { TagSchemaView } from "./TagSchemaView";

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
const usd = (v: number) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);
const kTokens = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));

function Chip({ label, n, tone = "bg-slate-100 text-slate-600" }: { label: string; n: number; tone?: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums ${tone}`}>{n.toLocaleString()} {label}</span>;
}

/** Collapsible list of the approved research questions with their Boolean queries; a row opens the drawer. */
export function RqPanel({ projectId, refreshKey, onChanged, disabled }: {
  projectId: number; refreshKey: number; onChanged: () => void; disabled?: boolean;
}) {
  const [rqs, setRqs] = useState<RqSummary[]>([]);
  const [open, setOpen] = useState(true);
  const [active, setActive] = useState<RqSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => intelApi.datasetRqs(projectId).then(setRqs).catch((e) => setError(errMsg(e, "Could not load the research questions")));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [projectId, refreshKey]);
  if (rqs.length === 0 && !error) return null;

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-800">
        <Icon icon={open ? "lucide:chevron-down" : "lucide:chevron-right"} width={16} aria-hidden />
        Research questions <span className="font-normal text-slate-400">· {rqs.length}</span>
      </button>
      {error && <p role="alert" className="px-4 pb-3 text-xs text-red-700">{error}</p>}
      {open && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {rqs.map((q) => (
            <li key={q.rq_id}>
              <button type="button" onClick={() => setActive(q)}
                className="grid w-full grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-50">
                <span className="text-xs font-bold text-[#5B2C9D]">{q.rq_id}</span>
                <span className="min-w-0">
                  <span className="block truncate text-sm text-slate-800">{q.question}</span>
                  <span className="block truncate font-mono text-[11px] text-slate-400">{q.query || "No query"}</span>
                </span>
                <span className="flex flex-wrap justify-end gap-1">
                  <Chip label="matched" n={q.counts.matched} />
                  <Chip label="approved" n={q.counts.approved} tone="bg-emerald-50 text-emerald-700" />
                  {q.counts.needs_tagging > 0 && <Chip label="need tagging" n={q.counts.needs_tagging} tone="bg-amber-50 text-amber-700" />}
                  {q.counts.query_changed > 0 && <Chip label="query changed" n={q.counts.query_changed} tone="bg-amber-50 text-amber-700" />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {active && (
        <RqDrawer projectId={projectId} rq={active} disabled={disabled} onClose={() => setActive(null)}
          onChanged={() => { void load(); onChanged(); }} />
      )}
    </section>
  );
}

function RqDrawer({ projectId, rq, disabled, onClose, onChanged }: {
  projectId: number; rq: RqSummary; disabled?: boolean; onClose: () => void; onChanged: () => void;
}) {
  const [query, setQuery] = useState(rq.query);
  const [preview, setPreview] = useState<RqPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<RqEstimate | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [lists, setLists] = useState(false);
  const changed = query.trim() !== rq.query.trim();

  useEffect(() => {       // live check: validate and count the edit 400 ms after the last keystroke
    if (!changed) { setPreview(null); return; }
    setChecking(true);
    const t = window.setTimeout(() => {
      intelApi.previewRqQuery(projectId, rq.rq_id, query).then(setPreview)
        .catch((e) => setPreview({ valid: false, errors: [errMsg(e, "Could not check the query")], current: 0, edited: 0, added: [], dropped: [] }))
        .finally(() => setChecking(false));
    }, 400);
    return () => window.clearTimeout(t);
  }, [query, changed, projectId, rq.rq_id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    setBusy(true); setError(null);
    try { await fn(); return true; } catch (e) { setError(errMsg(e, fallback)); return false; } finally { setBusy(false); }
  };
  const save = async () => { if (await act(() => intelApi.saveRqQuery(projectId, rq.rq_id, query), "Could not save the query")) { onChanged(); onClose(); } };
  const askRetag = () => act(async () => setEstimate(await intelApi.estimateRqRetag(projectId, rq.rq_id)), "Could not estimate the re-tag");
  const retag = async () => { if (await act(() => intelApi.retagRq(projectId, rq.rq_id), "Could not start the re-tag")) { setEstimate(null); onChanged(); onClose(); } };
  const remove = async () => { if (await act(() => intelApi.deleteDatasetRq(projectId, rq.rq_id), "Could not delete the question")) { onChanged(); onClose(); } };
  const invalid = Boolean(preview && !preview.valid);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-label={`${rq.rq_id} query`} onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-xl flex-col gap-4 overflow-y-auto bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <span className="text-xs font-bold text-[#5B2C9D]">{rq.rq_id}</span>
            <h2 className="mt-1 text-base font-semibold text-slate-900">{rq.question}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-400 hover:bg-slate-100"><Icon icon="lucide:x" width={18} /></button>
        </div>

        <QueryEditor value={query} onChange={setQuery} invalid={invalid} />
        {invalid && <ul role="alert" className="list-disc pl-5 text-xs text-red-700">{preview!.errors.map((e) => <li key={e}>{e}</li>)}</ul>}
        {changed && (
          <div className="text-xs text-slate-600" aria-live="polite">
            {checking || !preview ? "Checking…" : preview.valid && (
              <>
                Current {preview.current.toLocaleString()} · Edited {preview.edited.toLocaleString()} ·{" "}
                <span className="text-emerald-700">+{preview.added.length} new</span> ·{" "}
                <span className="text-red-700">−{preview.dropped.length} no longer match</span>
                {(preview.added.length > 0 || preview.dropped.length > 0) && (
                  <button type="button" onClick={() => setLists((v) => !v)} className="ml-2 font-medium text-[#5B2C9D] hover:underline">{lists ? "Hide" : "Show"} titles</button>
                )}
                {lists && (
                  <div className="mt-2 grid grid-cols-2 gap-3">
                    <ul className="max-h-40 overflow-y-auto text-emerald-800">{preview.added.map((a) => <li key={a.id} className="truncate">+ {a.title}</li>)}</ul>
                    <ul className="max-h-40 overflow-y-auto text-red-800">{preview.dropped.map((a) => <li key={a.id} className="truncate">− {a.title}</li>)}</ul>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Tag schema</h3>
          <TagSchemaView fields={rq.schema.fields} />
        </div>

        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        {estimate && (
          <div role="alertdialog" className="rounded-lg border border-violet-100 bg-violet-50 px-4 py-3 text-sm text-violet-900">
            Re-tag {rq.rq_id}: {estimate.articles.toLocaleString()} articles · {estimate.batches} batches ·
            ~{kTokens(estimate.input_tokens + estimate.output_tokens)} tokens · ≈ {usd(estimate.cost_usd)}
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => setEstimate(null)} className="rounded-lg px-3 py-1 text-xs font-medium text-slate-600 hover:bg-white">Cancel</button>
              <button type="button" disabled={busy || estimate.articles === 0} onClick={() => void retag()}
                className="rounded-lg bg-[#5B2C9D] px-3 py-1 text-xs font-medium text-white disabled:opacity-50">Start re-tag</button>
            </div>
          </div>
        )}
        {confirmDelete && (
          <div role="alertdialog" className="rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-800">
            Delete {rq.rq_id}? {rq.counts.approved.toLocaleString()} approved articles leave the deck.
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => setConfirmDelete(false)} className="rounded-lg px-3 py-1 text-xs font-medium text-slate-600 hover:bg-white">Cancel</button>
              <button type="button" disabled={busy} onClick={() => void remove()} className="rounded-lg bg-red-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">Delete question</button>
            </div>
          </div>
        )}

        <div className="mt-auto flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          <button type="button" disabled={busy || disabled || !changed || checking || invalid || !preview} onClick={() => void save()}
            className="rounded-lg bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Save query</button>
          <button type="button" disabled={busy || disabled || changed} onClick={() => void askRetag()} title={changed ? "Save the query first" : undefined}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">Re-tag this question</button>
          <button type="button" disabled={busy || disabled} onClick={() => setConfirmDelete(true)}
            className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">Delete question</button>
          <button type="button" onClick={onClose} className="ml-auto rounded-lg px-4 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50">Cancel</button>
        </div>
      </aside>
    </div>
  );
}
