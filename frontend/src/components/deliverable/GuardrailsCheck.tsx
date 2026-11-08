import { useEffect, useState } from "react";
import { intelApi, type GuardrailIssue, type GuardrailsCheck as Result } from "../../services/intel-api";

type Props = { projectId: number; runId: number };

/** Deliverables › Guardrails check: the finished deck against the organization's guardrails. The word check runs in
 * code (free, instant) every time the deck is shown; the AI review of meaning-level rules is one optional call. */
export function GuardrailsCheck({ projectId, runId }: Props) {
  const [result, setResult] = useState<Result | null>(null);
  const [ai, setAi] = useState<GuardrailIssue[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setResult(null); setAi(null); setError("");
    intelApi.guardrailsCheck(projectId, runId).then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "Check failed"));
  }, [projectId, runId]);

  const review = async () => {
    setBusy(true); setError("");
    try { setAi((await intelApi.guardrailsAiReview(projectId, runId)).issues); setOpen(true); }
    catch (e) { setError(e instanceof Error ? e.message.replace(/^\d+:\s*/, "") : "AI review failed"); }
    finally { setBusy(false); }
  };

  if (error) return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">Guardrails check: {error}</div>;
  if (!result) return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">Checking the deck against your guardrails…</div>;
  const words = result.issues.filter((i) => i.rule === "prohibited word");
  const other = result.issues.filter((i) => i.rule !== "prohibited word");
  const all = [...result.issues, ...(ai ?? []).map((i) => ({ ...i, rule: `AI: ${i.rule}` }))];
  const tone = words.length ? "border-red-200 bg-red-50"
    : other.length || (ai && ai.length) ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50";

  return (
    <section className={`rounded-xl border p-4 ${tone}`} aria-label="Guardrails check">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Guardrails check · {result.terms_checked === 0 ? "no prohibited word list in your guardrails"
              : words.length ? `${words.length} prohibited word${words.length === 1 ? "" : "s"}` : "no prohibited words"}
            {other.length > 0 && ` · ${other.length} repetition${other.length === 1 ? "" : "s"}`}
            {ai !== null && ` · AI review: ${ai.length} finding${ai.length === 1 ? "" : "s"}`}
          </div>
          <div className="text-xs text-slate-600">{result.slides} slides checked against {result.terms_checked} prohibited terms and their word forms.</div>
        </div>
        <div className="flex gap-2">
          {all.length > 0 && (
            <button onClick={() => setOpen((o) => !o)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700">
              {open ? "Hide" : "Show"} findings
            </button>
          )}
          <button onClick={review} disabled={busy} title="One call to your organization's model: factual, speculative, AI-sounding or overlapping wording"
            className="rounded-lg bg-[#5B2C9D] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            {busy ? "Reviewing…" : ai === null ? "Run AI review" : "Review again"}
          </button>
        </div>
      </div>
      {open && all.length > 0 && (
        <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-left text-[10px] uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-1.5">Slide</th><th className="px-3 py-1.5">Rule</th><th className="px-3 py-1.5">Found</th><th className="px-3 py-1.5">Suggestion</th></tr>
            </thead>
            <tbody>
              {all.map((i, k) => (
                <tr key={k} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-1.5 tabular-nums">{i.slide || "—"}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{i.rule}{i.term ? <span className="ml-1 font-mono text-red-700">{i.term}</span> : null}</td>
                  <td className="px-3 py-1.5 text-slate-600">{i.excerpt}</td>
                  <td className="px-3 py-1.5 text-slate-600">{i.suggestion ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
