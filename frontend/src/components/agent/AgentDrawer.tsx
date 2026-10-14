import { useCallback, useEffect, useState } from "react";
import { intelApi, type AgentState, type CopilotReply } from "../../services/intel-api";
import { agentSocket } from "../../services/ws";

type Turn = { who: "you" | "hunter"; text: string; pending?: CopilotReply["pending"] };
const STATE_CLS: Record<string, string> = {
  done: "bg-emerald-50 text-emerald-700 border-emerald-200", waiting: "bg-sky-50 text-sky-700 border-sky-200",
  ready: "bg-amber-50 text-amber-700 border-amber-200", failed: "bg-rose-50 text-rose-700 border-rose-200",
  todo: "bg-slate-50 text-slate-500 border-slate-200",
};

/** Hunter's autopilot status and the copilot chat for the active project, in a drawer on the right. */
export function AgentDrawer({ projectId }: { projectId: number }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<AgentState | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    intelApi.agentState(projectId).then(setState).catch(() => setState(null));
  }, [projectId]);

  useEffect(() => { refresh(); setTurns([]); }, [refresh]);
  useEffect(() => {
    const off = agentSocket.onMessage((m) => {
      if (m.type === "agent_event" && m.project_id === projectId) refresh();
    });
    return () => { off(); };
  }, [projectId, refresh]);

  const send = async (message: string, confirm?: string) => {
    setBusy(true); setError(null);
    if (message) setTurns((t) => [...t, { who: "you", text: message }]);
    try {
      const r = await intelApi.copilotSend(projectId, message, confirm);
      setTurns((t) => [...t, { who: "hunter", text: r.reply, pending: r.pending }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The copilot could not answer.");
    } finally { setBusy(false); setDraft(""); }
  };

  const start = async () => {
    setError(null);
    try { await intelApi.agentStart(projectId, folder || undefined); refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not start the autopilot."); }
  };

  const ap = state?.autopilot;
  return (
    <>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="fixed bottom-5 right-5 z-40 rounded-full bg-[#5B2C9D] px-4 py-2 text-sm font-medium text-white shadow-lg">
        Hunter{ap?.status === "running" ? " · driving" : ""}
      </button>
      {open && (
        <aside className="fixed right-0 top-0 z-40 flex h-full w-[380px] flex-col border-l border-slate-200 bg-white shadow-xl"
          aria-label="Hunter agent">
          <header className="border-b border-slate-200 p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">Hunter</h2>
              <button onClick={() => setOpen(false)} className="text-sm text-slate-600">Close</button>
            </div>
            <p className="mt-1 text-xs text-slate-600">
              {ap ? `Autopilot: ${ap.status} — ${ap.note}` : "Autopilot is off for this project."}
            </p>
            <ol className="mt-2 flex flex-wrap gap-1">
              {state?.status.steps.map((s) => (
                <li key={s.key} title={s.detail} className={`rounded border px-1.5 py-0.5 text-[11px] ${STATE_CLS[s.state]}`}>{s.label}</li>
              ))}
            </ol>
            <div className="mt-3 flex gap-2">
              {ap?.status === "running" ? (
                <button onClick={() => intelApi.agentStop(projectId).then(refresh)} className="rounded border px-2 py-1 text-xs">Stop</button>
              ) : (
                <>
                  <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Input folder (optional)"
                    aria-label="Input folder" className="min-w-0 flex-1 rounded border px-2 py-1 text-xs" />
                  <button onClick={start} className="rounded bg-[#5B2C9D] px-2 py-1 text-xs text-white">Drive to deck</button>
                </>
              )}
            </div>
          </header>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {turns.map((t, i) => (
              <div key={i} className={t.who === "you" ? "text-right" : ""}>
                <p className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${t.who === "you" ? "bg-[#5B2C9D] text-white" : "bg-slate-100 text-slate-800"}`}>{t.text}</p>
                {t.pending && (
                  <div className="mt-1">
                    <button disabled={busy} onClick={() => send("", t.pending!.id)}
                      className="rounded bg-emerald-700 px-2 py-1 text-xs text-white">Confirm {t.pending.tool.replace(/_/g, " ")}</button>
                  </div>
                )}
              </div>
            ))}
            {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
          </div>
          <form className="flex gap-2 border-t border-slate-200 p-3"
            onSubmit={(e) => { e.preventDefault(); if (draft.trim()) send(draft.trim()); }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder='e.g. "why is the experts question partial?"'
              className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" aria-label="Message Hunter" />
            <button disabled={busy || !draft.trim()} className="rounded bg-[#5B2C9D] px-3 py-1.5 text-sm text-white disabled:opacity-50">Send</button>
          </form>
        </aside>
      )}
    </>
  );
}
