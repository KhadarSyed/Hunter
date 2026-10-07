import { useEffect, useState } from "react";

const FIXABLE = ["open", "triage", "discarded", "rejected", "needs_llm"];
const POLL_MS = 5000;
import { intelApi, type AgentFix, type AgentIssue } from "../services/intel-api";

/** Issues Hunter found and the fixes it proposed: approve or reject inbox fixes; see what applied or rolled back. */
export function FixesTab() {
  const [issues, setIssues] = useState<AgentIssue[]>([]);
  const [fixes, setFixes] = useState<AgentFix[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => Promise.all([intelApi.adminIssues(), intelApi.adminFixes()])
    .then(([i, f]) => { setIssues(i); setFixes(f); }).catch(() => setMessage("Could not load fixes."));
  useEffect(() => { load(); }, []);
  const proposing = issues.some((i) => i.status === "fixing");
  useEffect(() => {                    // a proposal takes a minute or two; refresh until it lands
    if (!proposing) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [proposing]);

  const propose = async (id: number) => {
    setMessage(null);
    try {
      await intelApi.adminProposeFix(id);
      setMessage("Hunter is writing a fix for this issue. It appears under Fixes with Apply / Reject when ready.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not start a fix proposal.");
    }
    load();
  };

  const apply = async (id: number) => {
    const r = await intelApi.adminApplyFix(id).catch((e) => ({ status: "refused", reason: String(e) }));
    setMessage(r.status === "verifying" ? "Applied — the app restarts and verifies the fix." : `Not applied: ${r.reason}`);
    load();
  };
  const reject = async (id: number) => {
    const reason = window.prompt("Why reject this fix?");
    if (reason) { await intelApi.adminRejectFix(id, reason); load(); }
  };

  return (
    <div className="space-y-6">
      {message && <p role="status" className="rounded bg-slate-50 p-2 text-sm text-slate-700">{message}</p>}
      <section>
        <h3 className="text-sm font-semibold text-slate-900">Fixes</h3>
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200">
          {fixes.map((f) => {
            const issue = issues.find((i) => i.id === f.issue_id);
            return (
              <li key={f.id} className="p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <button onClick={() => setOpen(open === f.id ? null : f.id)} className="text-left font-medium text-slate-800">
                    #{f.id} {issue?.title ?? `issue ${f.issue_id}`}
                  </button>
                  <span className="shrink-0 text-xs text-slate-600">{f.tier} · {f.status}</span>
                </div>
                {f.note && <p className="mt-1 text-xs text-slate-600">{f.note}</p>}
                {open === f.id && (
                  <div className="mt-2 space-y-2">
                    {Object.entries(f.tests).map(([k, v]) => (
                      <pre key={k} className="max-h-32 overflow-auto rounded bg-slate-50 p-2 text-[11px]">{k}: {v}</pre>))}
                    <pre className="max-h-80 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-100">{f.diff}</pre>
                  </div>
                )}
                {f.status === "proposed" && f.tier !== "never" && (
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => apply(f.id)} className="rounded bg-[#5B2C9D] px-2 py-1 text-xs text-white">Apply</button>
                    <button onClick={() => reject(f.id)} className="rounded border px-2 py-1 text-xs">Reject</button>
                  </div>
                )}
              </li>
            );
          })}
          {!fixes.length && <li className="p-3 text-sm text-slate-600">No fixes yet.</li>}
        </ul>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-slate-900">Issues</h3>
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200">
          {issues.map((i) => (
            <li key={i.id} className="flex items-start justify-between gap-3 p-3 text-sm">
              <div className="min-w-0">
                <p className="text-slate-800">#{i.id} [{i.source}] {i.title}{i.seen > 1 ? ` ×${i.seen}` : ""}</p>
                {typeof i.detail?.detail === "string" && <p className="mt-0.5 truncate text-xs text-slate-600">{i.detail.detail as string}</p>}
                {i.note && <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-600">{i.note.slice(0, 300)}</p>}
              </div>
              <span className="flex shrink-0 items-center gap-2 text-xs text-slate-600">
                {i.status === "fixing" ? "proposing…" : i.status}
                {FIXABLE.includes(i.status) && (
                  <button onClick={() => propose(i.id)} disabled={proposing}
                    className="rounded bg-[#5B2C9D] px-2 py-1 text-white disabled:opacity-50">Propose fix</button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
