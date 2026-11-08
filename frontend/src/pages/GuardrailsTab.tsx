import { useEffect, useState } from "react";
import { useAuth } from "../context/auth-context";
import { intelApi, type Guardrail, type GuardrailInput } from "../services/intel-api";
import { fmtDate, ghostBtn, inputCls, labelCls, primaryBtn } from "../components/admin/adminUi";

const EMPTY: GuardrailInput = { title: "", body: "", active: true };

/** Settings → Guardrails: instructions sent, word for word, with every AI call your organization makes in Brief &
 * Scope, Background Research, Search Strategy, Data set tagging and the deck. Admins edit; others read. */
export function GuardrailsTab() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin";
  const [rows, setRows] = useState<Guardrail[]>([]);
  const [edit, setEdit] = useState<{ id?: number; g: GuardrailInput } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => intelApi.listGuardrails().then(setRows).catch(() => setError("Could not load guardrails"));
  useEffect(() => { load(); }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    try { await intelApi.saveGuardrail(edit.g, edit.id); setEdit(null); setError(null); load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save"); }
  };
  const remove = async (g: Guardrail) => {
    if (!window.confirm(`Delete the guardrail "${g.title}"? AI steps stop following it immediately.`)) return;
    try { await intelApi.deleteGuardrail(g.id); load(); } catch { setError("Could not delete"); }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Guardrails</h2>
          <p className="text-sm text-slate-500">Sent word for word with every AI step in Brief &amp; Scope, Background Research, Search Strategy, Data set tagging and the deck.</p>
        </div>
        {canEdit && !edit && <button className={primaryBtn} onClick={() => setEdit({ g: EMPTY })}>Add guardrail</button>}
      </div>
      {error && <div role="alert" className="text-sm text-red-600">{error}</div>}

      {edit && (
        <form onSubmit={save} className="space-y-3 rounded-xl border border-slate-200 p-4">
          <div><label className={labelCls}>Title</label>
            <input value={edit.g.title} required maxLength={200} className={inputCls}
                   onChange={(e) => setEdit({ ...edit, g: { ...edit.g, title: e.target.value } })} /></div>
          <div><label className={labelCls}>Instructions</label>
            <textarea value={edit.g.body} required rows={16} className={`${inputCls} font-mono text-xs`}
                      onChange={(e) => setEdit({ ...edit, g: { ...edit.g, body: e.target.value } })} /></div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={edit.g.active} onChange={(e) => setEdit({ ...edit, g: { ...edit.g, active: e.target.checked } })} />
            Active (sent with AI steps)
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className={ghostBtn} onClick={() => setEdit(null)}>Cancel</button>
            <button type="submit" className={primaryBtn}>Save</button>
          </div>
        </form>
      )}

      <ul className="space-y-2">
        {rows.map((g) => (
          <li key={g.id} className="rounded-xl border border-slate-200">
            <div className="flex items-center gap-3 px-4 py-3">
              <button className="flex-1 text-left" onClick={() => setOpen(open === g.id ? null : g.id)} aria-expanded={open === g.id}>
                <div className="font-medium text-slate-900">{g.title}</div>
                <div className="text-xs text-slate-500">{g.active ? "Active" : "Off"} · updated {fmtDate(g.updated_at)} · {g.body.length.toLocaleString()} characters</div>
              </button>
              {canEdit && (
                <>
                  <button className="text-xs text-[#5B2C9D] hover:underline" onClick={() => setEdit({ id: g.id, g: { title: g.title, body: g.body, active: Boolean(g.active) } })}>Edit</button>
                  <button className="text-xs text-red-600 hover:underline" onClick={() => remove(g)}>Delete</button>
                </>
              )}
            </div>
            {open === g.id && <pre className="max-h-96 overflow-auto whitespace-pre-wrap border-t border-slate-100 px-4 py-3 text-xs text-slate-700">{g.body}</pre>}
          </li>
        ))}
        {!rows.length && <li className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-400">No guardrails yet</li>}
      </ul>
    </div>
  );
}
