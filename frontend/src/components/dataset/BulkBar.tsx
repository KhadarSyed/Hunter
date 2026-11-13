import { useState } from "react";
import type { RqColumn } from "../../types/dataset";

type Props = {
  count: number;
  rqs: RqColumn[];
  defaultRq: string;     // "" = all matched RQs
  busy: boolean;
  onApprove: (rqId: string | null) => void;
  onReject: (rqId: string | null, reason: string) => void;
  onClear: () => void;
  /** Irrelevant pool: only "Mark relevant for <RQ>" (an RQ is required; the next Re-tag tags the articles) */
  relevantOnly?: boolean;
};

export function BulkBar({ count, rqs, defaultRq, busy, onApprove, onReject, onClear, relevantOnly }: Props) {
  const [rq, setRq] = useState(defaultRq || (relevantOnly ? rqs[0]?.id ?? "" : ""));
  const [reason, setReason] = useState("");
  const target = rq || null;
  const btn = "text-xs font-medium px-3 py-1.5 rounded-lg text-white disabled:opacity-50";
  if (relevantOnly) return (
    <div role="region" aria-label="Bulk actions" className="flex flex-wrap items-center gap-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-2">
      <span className="text-sm font-semibold text-slate-800">{count.toLocaleString("en-US")} selected</span>
      <label className="text-xs text-slate-600">for{" "}
        <select value={rq} onChange={(e) => setRq(e.target.value)} aria-label="Research question"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs">
          {rqs.map((q) => <option key={q.id} value={q.id}>{q.id}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy || !target} onClick={() => onApprove(target)} className={btn} style={{ background: "#059669" }}>
        Mark relevant{target ? ` for ${target}` : ""}
      </button>
      <span className="text-xs text-slate-500">Run Re-tag afterwards to tag them.</span>
      <button type="button" onClick={onClear} className="ml-auto text-xs font-medium text-slate-500 hover:underline">Clear</button>
    </div>
  );
  return (
    <div role="region" aria-label="Bulk actions" className="flex flex-wrap items-center gap-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-2">
      <span className="text-sm font-semibold text-slate-800">{count.toLocaleString("en-US")} selected</span>
      <label className="text-xs text-slate-600">for{" "}
        <select value={rq} onChange={(e) => setRq(e.target.value)} aria-label="Apply to"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs">
          <option value="">all matched RQs</option>
          {rqs.map((q) => <option key={q.id} value={q.id}>{q.id}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy} onClick={() => onApprove(target)} className={btn} style={{ background: "#059669" }}>
        Approve{target ? ` for ${target}` : " for all matched RQs"}
      </button>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" maxLength={1000}
        className="w-44 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs" />
      <button type="button" disabled={busy} onClick={() => { onReject(target, reason.trim()); setReason(""); }} className={btn} style={{ background: "#dc2626" }}>
        Reject{target ? ` for ${target}` : ""}
      </button>
      <button type="button" onClick={onClear} className="ml-auto text-xs font-medium text-slate-500 hover:underline">Clear</button>
    </div>
  );
}
