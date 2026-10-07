import { useEffect, useState } from "react";
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
            <li key={i.id} className="flex items-center justify-between gap-3 p-3 text-sm">
              <span className="text-slate-800">#{i.id} [{i.source}] {i.title}{i.seen > 1 ? ` ×${i.seen}` : ""}</span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-slate-600">{i.status}
                {["discarded", "rejected", "needs_llm"].includes(i.status) &&
                  <button onClick={() => intelApi.adminRetryIssue(i.id).then(load)} className="rounded border px-1.5 py-0.5">Retry</button>}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
