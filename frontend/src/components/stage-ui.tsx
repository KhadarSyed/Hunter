/** Small pieces shared by the review-stage pages (Evidence Library, Insights, Storyline, Slide Intelligence, Research Plan). */

export const STATUS_COLORS: Record<string, string> = {
  draft: "text-slate-600 bg-slate-100 border-slate-200",
  needs_review: "text-amber-700 bg-amber-50 border-amber-200",
  approved: "text-emerald-700 bg-emerald-50 border-emerald-200",
  rejected: "text-red-700 bg-red-50 border-red-200",
};

export const CloseIcon = () => (
  <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const LockIcon = () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="text-slate-400"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>;

export const SparkleIcon = () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" /></svg>;

export function Badge({ label, colors }: { label: string; colors: string }) {
  return <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border whitespace-nowrap ${colors}`}>{label.replace(/_/g, " ")}</span>;
}

export function MetricCard({ label, value, dot }: { label: string; value: number | string; dot: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
        <span className="text-[9px] text-slate-400 font-semibold uppercase tracking-wide leading-tight">{label}</span>
      </div>
      <div className="text-xl font-bold text-slate-900 tabular-nums">{value}</div>
    </div>
  );
}

export function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score * 100));
  const color = pct >= 70 ? "from-emerald-500 to-emerald-400" : pct >= 40 ? "from-amber-500 to-yellow-400" : "from-red-500 to-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full bg-gradient-to-r ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] tabular-nums text-slate-500 w-8 text-right">{Math.round(pct)}%</span>
    </div>
  );
}

export function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">{title}</div>
      {count !== undefined && <span className="text-[10px] text-slate-400 font-medium tabular-nums">{count} items</span>}
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
}
