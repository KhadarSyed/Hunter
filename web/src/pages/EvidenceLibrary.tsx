import { useState, useEffect, useCallback, useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { intelApi } from "../lib/intel-api";
import type { LibraryItem, EvidenceDetail } from "../data/contracts";
import { useActiveProjectId } from "../lib/project-context";

const REVIEW_STATUSES = ["unreviewed", "accepted", "rejected", "needs_review", "superseded"];
const CONFIDENCES = ["high", "medium", "low"];
const SORT_FIELDS: Record<string, string> = { quality_score: "Quality Score", date: "Date", created_at: "Created At", confidence: "Confidence" };
const LIMIT = 20;

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "--";
  const d = new Date(ts < 1e12 ? ts * 1000 : ts);
  if (isNaN(d.getTime())) return "--";
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function scorePct(v: number | null | undefined): number {
  const n = v ?? 0;
  return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
}

// ─── Icons ──────────────────────────────────────────────────────────────────

const ip = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const CheckIcon = () => <svg {...ip}><path d="M20 6L9 17l-5-5" /></svg>;
const XIcon = () => <svg {...ip}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>;
const FlagIcon = () => <svg {...ip}><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>;
const StarIcon = () => <svg {...ip}><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" /></svg>;
const GemIcon = () => <svg {...ip}><path d="M6 3h12l4 6-10 12L2 9z" /><path d="M2 9h20" /><path d="M12 3v18" /></svg>;
const PenIcon = () => <svg {...ip}><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>;
const ExpandIcon = () => <svg {...ip}><path d="M15 3h6v6" /><path d="M9 21H3v-6" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" /></svg>;
const CloseIcon = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>;
const LockIcon = () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="text-slate-400"><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>;

// ─── Shared UI ──────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  accepted: "text-emerald-700 bg-emerald-50 border-emerald-200",
  rejected: "text-red-700 bg-red-50 border-red-200",
  needs_review: "text-amber-700 bg-amber-50 border-amber-200",
  unreviewed: "text-slate-500 bg-slate-100 border-slate-200",
  superseded: "text-violet-700 bg-violet-50 border-violet-200",
  high: "text-blue-700 bg-blue-50 border-blue-200",
  medium: "text-amber-700 bg-amber-50 border-amber-200",
  low: "text-slate-500 bg-slate-100 border-slate-200",
};

function Badge({ label, variant }: { label: string; variant: string }) {
  return <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border whitespace-nowrap ${STATUS_COLORS[variant] || STATUS_COLORS.unreviewed}`}>{label.replace(/_/g, " ")}</span>;
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">{title}</div>
      {count !== undefined && <span className="text-[10px] text-slate-400 font-medium tabular-nums">{count} items</span>}
      <div className="flex-1 border-t border-slate-200" />
    </div>
  );
}

function MetricCard({ label, value, dot }: { label: string; value: number; dot: string }) {
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

function QualityBar({ score }: { score: number | null | undefined }) {
  const pct = scorePct(score);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2 w-24">
      <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden"><div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} /></div>
      <span className="text-[11px] tabular-nums text-slate-500 w-7 text-right">{score !== null && score !== undefined ? Math.round(pct) : "--"}</span>
    </div>
  );
}

function IconButton({ title, onClick, active, activeColor, busy, children }: { title: string; onClick: () => void; active?: boolean; activeColor?: string; busy?: boolean; children: ReactNode }) {
  return (
    <button title={title} onClick={onClick} disabled={busy}
      className={`w-7 h-7 flex items-center justify-center rounded-md border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${active ? activeColor || "text-blue-600 bg-blue-50 border-blue-200" : "text-slate-400 bg-white border-slate-200 hover:text-slate-700 hover:bg-slate-50"}`}>
      {children}
    </button>
  );
}

function ItemActions({ item, busy, onReview, onToggleRep, onToggleHV, onNote, onDetail, compact }: {
  item: LibraryItem; busy: boolean; onReview: (status: string) => void; onToggleRep: () => void; onToggleHV: () => void; onNote?: () => void; onDetail?: () => void; compact?: boolean;
}) {
  return (
    <div className="flex items-center gap-1">
      <IconButton title="Accept" onClick={() => onReview("accepted")} busy={busy} active={item.review_status === "accepted"} activeColor="text-emerald-600 bg-emerald-50 border-emerald-200"><CheckIcon /></IconButton>
      <IconButton title="Reject" onClick={() => onReview("rejected")} busy={busy} active={item.review_status === "rejected"} activeColor="text-red-600 bg-red-50 border-red-200"><XIcon /></IconButton>
      <IconButton title="Needs Review" onClick={() => onReview("needs_review")} busy={busy} active={item.review_status === "needs_review"} activeColor="text-amber-600 bg-amber-50 border-amber-200"><FlagIcon /></IconButton>
      <IconButton title="Mark Representative" onClick={onToggleRep} busy={busy} active={item.is_representative} activeColor="text-violet-600 bg-violet-50 border-violet-200"><StarIcon /></IconButton>
      <IconButton title="Mark High Value" onClick={onToggleHV} busy={busy} active={item.is_high_value} activeColor="text-blue-600 bg-blue-50 border-blue-200"><GemIcon /></IconButton>
      {!compact && onNote && <IconButton title="Add Note" onClick={onNote} busy={busy}><PenIcon /></IconButton>}
      {!compact && onDetail && <IconButton title="View Detail" onClick={onDetail} busy={busy}><ExpandIcon /></IconButton>}
    </div>
  );
}

function FilterSelect({ label, value, onChange, options, labels }: { label: string; value: string; onChange: (v: string) => void; options: string[]; labels?: Record<string, string> }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="border border-slate-200 rounded-lg px-2.5 py-1.5 text-[11px] text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400">
      {options.map((o) => <option key={o} value={o}>{o === "all" ? `All ${label}` : labels?.[o] || o.replace(/_/g, " ")}</option>)}
    </select>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[9px] text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="text-slate-700 font-medium truncate">{value}</div>
    </div>
  );
}

// ─── Table & Card views ─────────────────────────────────────────────────────

interface RowHandlers {
  selectedIds: Set<number>;
  busyItemId: number | null;
  onToggleSelect: (id: number) => void;
  onReview: (item: LibraryItem, status: string) => void;
  onToggleRep: (item: LibraryItem) => void;
  onToggleHV: (item: LibraryItem) => void;
  onNote: (item: LibraryItem) => void;
  onDetail: (item: LibraryItem) => void;
}

function EvidenceTable({ items, selectedIds, busyItemId, onToggleSelect, onToggleSelectAll, onReview, onToggleRep, onToggleHV, onNote, onDetail }: RowHandlers & { items: LibraryItem[]; onToggleSelectAll: () => void }) {
  const allSelected = items.length > 0 && selectedIds.size === items.length;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-[10px] text-slate-400 uppercase tracking-wider border-b border-slate-200">
            <th className="pb-2 pr-2 font-semibold w-8"><input type="checkbox" checked={allSelected} onChange={onToggleSelectAll} className="rounded border-slate-300" /></th>
            <th className="pb-2 pr-3 font-semibold">ID</th>
            <th className="pb-2 pr-3 font-semibold">Status</th>
            <th className="pb-2 pr-3 font-semibold">Excerpt</th>
            <th className="pb-2 pr-3 font-semibold">Source</th>
            <th className="pb-2 pr-3 font-semibold">Platform</th>
            <th className="pb-2 pr-3 font-semibold">Method</th>
            <th className="pb-2 pr-3 font-semibold">Confidence</th>
            <th className="pb-2 pr-3 font-semibold">Quality</th>
            <th className="pb-2 font-semibold text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b border-slate-100 last:border-0 align-top hover:bg-slate-50/60 transition-colors">
              <td className="py-2.5 pr-2"><input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => onToggleSelect(item.id)} className="rounded border-slate-300" /></td>
              <td className="py-2.5 pr-3 font-semibold text-slate-500 tabular-nums">#{item.id}</td>
              <td className="py-2.5 pr-3">
                <Badge label={item.review_status} variant={item.review_status} />
                {(item.is_representative || item.is_high_value) && (
                  <div className="flex gap-1.5 mt-1">
                    {item.is_representative && <span title="Representative" className="text-[9px] text-violet-600 font-semibold">★ Rep</span>}
                    {item.is_high_value && <span title="High Value" className="text-[9px] text-blue-600 font-semibold">◆ HV</span>}
                  </div>
                )}
              </td>
              <td className="py-2.5 pr-3 max-w-[260px]"><p className="text-slate-700 truncate" title={item.text_excerpt}>{item.text_excerpt}</p></td>
              <td className="py-2.5 pr-3 text-slate-500 max-w-[110px] truncate">{item.source || "--"}</td>
              <td className="py-2.5 pr-3 text-slate-500 whitespace-nowrap">{item.platform || "--"}</td>
              <td className="py-2.5 pr-3 text-slate-500 whitespace-nowrap">{item.method}</td>
              <td className="py-2.5 pr-3"><Badge label={item.confidence} variant={item.confidence} /></td>
              <td className="py-2.5 pr-3"><QualityBar score={item.quality_score} /></td>
              <td className="py-2.5">
                <div className="flex justify-end">
                  <ItemActions item={item} busy={busyItemId === item.id} onReview={(s) => onReview(item, s)} onToggleRep={() => onToggleRep(item)} onToggleHV={() => onToggleHV(item)} onNote={() => onNote(item)} onDetail={() => onDetail(item)} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceCard({ item, selected, busy, onToggleSelect, onReview, onToggleRep, onToggleHV, onNote, onDetail }: {
  item: LibraryItem; selected: boolean; busy: boolean; onToggleSelect: () => void; onReview: (item: LibraryItem, status: string) => void; onToggleRep: (item: LibraryItem) => void; onToggleHV: (item: LibraryItem) => void; onNote: (item: LibraryItem) => void; onDetail: (item: LibraryItem) => void;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <input type="checkbox" checked={selected} onChange={onToggleSelect} className="rounded border-slate-300" />
          <span className="text-[10px] font-semibold text-slate-400 tabular-nums">#{item.id}</span>
          <Badge label={item.review_status} variant={item.review_status} />
        </div>
        <div className="flex items-center gap-2 text-[11px] font-semibold">
          {item.is_representative && <span title="Representative" className="text-violet-500">★</span>}
          {item.is_high_value && <span title="High Value" className="text-blue-500">◆</span>}
        </div>
      </div>
      <p className="text-[12px] text-slate-700 leading-relaxed line-clamp-4">{item.text_excerpt}</p>
      <div className="flex items-center flex-wrap gap-x-2 gap-y-1 text-[10px] text-slate-400">
        <span>{item.source || "Unknown source"}</span>
        {item.platform && <><span>&middot;</span><span>{item.platform}</span></>}
        {item.date && <><span>&middot;</span><span>{item.date}</span></>}
        <span>&middot;</span><span>{item.method}</span>
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <Badge label={item.confidence} variant={item.confidence} />
        <QualityBar score={item.quality_score} />
      </div>
      <div className="flex justify-end pt-1">
        <ItemActions item={item} busy={busy} onReview={(s) => onReview(item, s)} onToggleRep={() => onToggleRep(item)} onToggleHV={() => onToggleHV(item)} onNote={() => onNote(item)} onDetail={() => onDetail(item)} />
      </div>
    </div>
  );
}

// ─── Detail Drawer ──────────────────────────────────────────────────────────

function DetailDrawer({ itemId, detail, loading, busy, noteDraft, setNoteDraft, noteSubmitting, noteRef, onSubmitNote, onClose, onReview, onToggleRep, onToggleHV }: {
  itemId: number; detail: EvidenceDetail | null; loading: boolean; busy: boolean; noteDraft: string; setNoteDraft: (v: string) => void; noteSubmitting: boolean; noteRef: RefObject<HTMLTextAreaElement>;
  onSubmitNote: () => void; onClose: () => void; onReview: (status: string) => void; onToggleRep: () => void; onToggleHV: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-slate-900/30 z-40 animate-fade-in" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-full sm:w-[460px] bg-white shadow-2xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 flex items-center justify-between z-10">
          <div>
            <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Evidence #{itemId}</div>
            {detail && <Badge label={detail.item.review_status} variant={detail.item.review_status} />}
          </div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"><CloseIcon /></button>
        </div>

        {loading && <div className="p-5 text-[12px] text-slate-400">Loading detail...</div>}

        {!loading && detail && (
          <div className="p-5 space-y-5">
            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Full Excerpt</div>
              <p className="text-[13px] text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-3 whitespace-pre-wrap">{detail.item.text_excerpt}</p>
            </div>

            <div>
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Metadata</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12px]">
                <MetaRow label="Source" value={detail.item.source || "--"} />
                <MetaRow label="Platform" value={detail.item.platform || "--"} />
                <MetaRow label="Date" value={detail.item.date || "--"} />
                <MetaRow label="Evidence Type" value={detail.item.evidence_type || "--"} />
                <MetaRow label="Method" value={detail.item.method} />
                <MetaRow label="Dataset" value={detail.item.dataset || "--"} />
                <MetaRow label="Objective" value={detail.item.objective_id} />
                <MetaRow label="Unit" value={detail.item.unit_id} />
              </div>
            </div>

            {detail.item.rationale && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Rationale</div>
                <p className="text-[12px] text-slate-600 italic leading-relaxed">{detail.item.rationale}</p>
              </div>
            )}

            <div className="flex items-start gap-6">
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Confidence</div>
                <Badge label={detail.item.confidence} variant={detail.item.confidence} />
              </div>
              <div className="flex-1">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1.5">Quality Score</div>
                <QualityBar score={detail.item.quality_score} />
              </div>
            </div>

            {detail.item.quality_components && Object.keys(detail.item.quality_components).length > 0 && (
              <div>
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Quality Components</div>
                <div className="space-y-1.5">
                  {Object.entries(detail.item.quality_components).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-2 text-[11px]">
                      <span className="w-28 text-slate-400 capitalize shrink-0">{k.replace(/_/g, " ")}</span>
                      <QualityBar score={v} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Review Status</div>
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <Badge label={detail.item.review_status} variant={detail.item.review_status} />
                {detail.item.reviewed_by && <span className="text-[11px] text-slate-400">by {detail.item.reviewed_by} &middot; {formatDateTime(detail.item.reviewed_at)}</span>}
              </div>
              <ItemActions item={detail.item} busy={busy} onReview={onReview} onToggleRep={onToggleRep} onToggleHV={onToggleHV} compact />
            </div>

            <div className="flex items-center gap-4 text-[11px]">
              <span className={detail.item.is_representative ? "text-violet-600 font-semibold" : "text-slate-300"}>★ Representative</span>
              <span className={detail.item.is_high_value ? "text-blue-600 font-semibold" : "text-slate-300"}>◆ High Value</span>
            </div>

            {detail.item.duplicate_group && (
              <div className="border-t border-slate-100 pt-4">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">
                  Duplicate Group &middot; {detail.duplicate_members.length} member{detail.duplicate_members.length !== 1 ? "s" : ""}
                </div>
                <div className="space-y-1.5">
                  {detail.duplicate_members.map((m) => (
                    <div key={m.id} className="text-[11px] text-slate-500 flex items-start gap-2">
                      <span className="font-semibold text-slate-600 shrink-0">#{m.id}</span>
                      {m.id === detail.item.canonical_id && <span className="text-emerald-600 text-[9px] font-bold uppercase shrink-0 mt-0.5">Canonical</span>}
                      <span className="truncate">{m.text_excerpt.slice(0, 70)}...</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Annotations ({detail.annotations.length})</div>
              <div className="space-y-2 mb-3 max-h-40 overflow-y-auto">
                {detail.annotations.length === 0 && <p className="text-[11px] text-slate-300">No notes yet</p>}
                {detail.annotations.map((a) => (
                  <div key={a.id} className="bg-slate-50 rounded-lg p-2.5">
                    <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                      <span className="font-semibold text-slate-500">{a.author}</span>
                      <span>{formatDateTime(a.created_at)}</span>
                    </div>
                    <p className="text-[12px] text-slate-700 leading-relaxed">{a.note}</p>
                  </div>
                ))}
              </div>
              <textarea ref={noteRef} value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)} placeholder="Add a note..." rows={2}
                className="w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-[12px] focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none" />
              <button onClick={onSubmitNote} disabled={noteSubmitting || !noteDraft.trim()} className="mt-2 px-3 py-1.5 text-[11px] font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {noteSubmitting ? "Saving..." : "Add Note"}
              </button>
            </div>

            <div className="border-t border-slate-100 pt-4">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-2">Audit Trail ({detail.audit.length})</div>
              <div className="space-y-2.5 max-h-48 overflow-y-auto">
                {detail.audit.length === 0 && <p className="text-[11px] text-slate-300">No history yet</p>}
                {detail.audit.map((a) => (
                  <div key={a.id} className="flex items-start gap-2 text-[11px]">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 mt-1.5 shrink-0" />
                    <div className="min-w-0">
                      <span className="text-slate-600 font-medium">{a.actor}</span>
                      <span className="text-slate-400"> {a.action}{a.field ? ` – ${a.field}` : ""}</span>
                      {a.old_value && a.new_value && <span className="text-slate-400"> ({a.old_value} &rarr; {a.new_value})</span>}
                      <div className="text-[10px] text-slate-300">{formatDateTime(a.created_at)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

interface LibrarySummaryMetricsLite {
  total: number; unreviewed: number; accepted: number; rejected: number; needs_review: number;
  representative: number; high_value: number; duplicate_groups: number; objectives_covered: number; objectives_insufficient: number;
}

export function EvidenceLibrary({ onNavigate }: { onNavigate: (page: string) => void }) {
  const projectId = useActiveProjectId() ?? 1;

  const [locked, setLocked] = useState<boolean | null>(null);
  const [summary, setSummary] = useState<LibrarySummaryMetricsLite | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"card" | "table">("table");

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [objectiveFilter, setObjectiveFilter] = useState("all");
  const [methodFilter, setMethodFilter] = useState("all");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [sortBy, setSortBy] = useState("quality_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const [filterOptions, setFilterOptions] = useState<{ objectives: string[]; methods: string[]; platforms: string[] }>({ objectives: [], methods: [], platforms: [] });
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [busyItemId, setBusyItemId] = useState<number | null>(null);

  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteSubmitting, setNoteSubmitting] = useState(false);
  const [focusNoteOnOpen, setFocusNoteOnOpen] = useState(false);
  const noteRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const loadSummary = useCallback(async () => {
    try {
      const s = await intelApi.getLibrarySummary(projectId);
      if (!s || s.total === 0) { setSummary(null); setLocked(true); } else { setSummary(s); setLocked(false); }
    } catch { setSummary(null); setLocked(true); }
  }, [projectId]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const loadFilterOptions = useCallback(async () => {
    try {
      const all = (await intelApi.listLibraryItems(projectId, { limit: 500 })) as unknown as LibraryItem[];
      setFilterOptions({
        objectives: Array.from(new Set(all.map((i) => i.objective_id).filter(Boolean))).sort(),
        methods: Array.from(new Set(all.map((i) => i.method).filter(Boolean))).sort(),
        platforms: Array.from(new Set(all.map((i) => i.platform).filter((p): p is string => !!p))).sort(),
      });
    } catch { /* non-fatal */ }
  }, [projectId]);

  useEffect(() => { if (locked === false) loadFilterOptions(); }, [locked, loadFilterOptions]);

  const fetchItems = useCallback(async (startOffset: number, append: boolean) => {
    append ? setLoadingMore(true) : setLoadingItems(true);
    setError(null);
    try {
      const opts = {
        review_status: statusFilter !== "all" ? statusFilter : undefined,
        objective_id: objectiveFilter !== "all" ? objectiveFilter : undefined,
        method: methodFilter !== "all" ? methodFilter : undefined,
        platform: platformFilter !== "all" ? platformFilter : undefined,
        confidence: confidenceFilter !== "all" ? confidenceFilter : undefined,
        search: search || undefined,
        sort_by: sortBy,
        sort_dir: sortDir,
        limit: LIMIT,
        offset: startOffset,
      };
      const data = (await intelApi.listLibraryItems(projectId, opts)) as unknown as LibraryItem[];
      setItems((prev) => (append ? [...prev, ...data] : data));
      setHasMore(data.length === LIMIT);
      setOffset(startOffset + data.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load evidence");
    } finally {
      setLoadingItems(false);
      setLoadingMore(false);
    }
  }, [projectId, statusFilter, objectiveFilter, methodFilter, platformFilter, confidenceFilter, search, sortBy, sortDir]);

  useEffect(() => {
    if (locked === false) { setSelectedIds(new Set()); fetchItems(0, false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locked, fetchItems]);

  const handleReview = async (item: LibraryItem, status: string) => {
    setBusyItemId(item.id);
    try {
      await intelApi.reviewEvidence(item.id, status);
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, review_status: status as LibraryItem["review_status"], reviewed_by: "analyst", reviewed_at: Date.now() / 1000 } : i)));
      loadSummary();
      if (detailId === item.id) loadDetail(item.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); } finally { setBusyItemId(null); }
  };

  const handleToggleRep = async (item: LibraryItem) => {
    setBusyItemId(item.id);
    try {
      const next = !item.is_representative;
      await intelApi.markRepresentative(item.id, next);
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_representative: next } : i)));
      loadSummary();
      if (detailId === item.id) loadDetail(item.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); } finally { setBusyItemId(null); }
  };

  const handleToggleHV = async (item: LibraryItem) => {
    setBusyItemId(item.id);
    try {
      const next = !item.is_high_value;
      await intelApi.markHighValue(item.id, next);
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_high_value: next } : i)));
      loadSummary();
      if (detailId === item.id) loadDetail(item.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); } finally { setBusyItemId(null); }
  };

  const handleBulkReview = async (status: string) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      await intelApi.bulkReview(Array.from(selectedIds), status);
      setItems((prev) => prev.map((i) => (selectedIds.has(i.id) ? { ...i, review_status: status as LibraryItem["review_status"] } : i)));
      setSelectedIds(new Set());
      loadSummary();
    } catch (e) { setError(e instanceof Error ? e.message : "Bulk action failed"); } finally { setBulkBusy(false); }
  };

  const loadDetail = useCallback(async (id: number) => {
    setDetailLoading(true);
    try {
      const d = (await intelApi.getLibraryDetail(id)) as unknown as EvidenceDetail;
      setDetail(d);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load detail"); } finally { setDetailLoading(false); }
  }, []);

  const openDetail = (item: LibraryItem, focusNote = false) => {
    setDetailId(item.id);
    setDetail(null);
    setFocusNoteOnOpen(focusNote);
    loadDetail(item.id);
  };

  const closeDetail = () => { setDetailId(null); setDetail(null); setNoteDraft(""); };

  useEffect(() => {
    if (detail && focusNoteOnOpen && noteRef.current) { noteRef.current.focus(); setFocusNoteOnOpen(false); }
  }, [detail, focusNoteOnOpen]);

  const submitNote = async () => {
    if (!detailId || !noteDraft.trim()) return;
    setNoteSubmitting(true);
    try {
      await intelApi.annotateEvidence(detailId, noteDraft.trim());
      setNoteDraft("");
      await loadDetail(detailId);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add note"); } finally { setNoteSubmitting(false); }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) => (prev.size === items.length && items.length > 0 ? new Set() : new Set(items.map((i) => i.id))));
  };

  if (locked === null) {
    return <div className="max-w-6xl mx-auto px-8 py-10"><div className="text-[13px] text-slate-400">Loading Evidence Library...</div></div>;
  }

  if (locked) {
    return (
      <div className="max-w-4xl mx-auto px-8 py-10">
        <div className="mb-6">
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 7</div>
          <h1 className="text-xl font-bold text-slate-900">Evidence Library</h1>
          <p className="text-[13px] text-slate-400 mt-1">Review, validate, and curate evidence collected during Research Execution</p>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-8 shadow-sm text-center">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-slate-100 flex items-center justify-center"><LockIcon /></div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">Evidence Library requires completed Research Execution</h3>
          <p className="text-[12px] text-slate-400 max-w-sm mx-auto mb-4">Run and complete Research Execution to collect evidence before it can be reviewed, classified, and curated here.</p>
          <button onClick={() => onNavigate("research-execution")} className="text-[12px] text-blue-600 hover:text-blue-700 font-semibold">Go to Research Execution</button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-8 py-10">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-1">Stage 7</div>
          <h1 className="text-xl font-bold text-slate-900">Evidence Library</h1>
          <p className="text-[13px] text-slate-400 mt-1">Review, validate, and curate evidence collected during Research Execution</p>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-700 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 font-semibold">&times;</button>
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          <MetricCard label="Total Evidence" value={summary.total} dot="bg-blue-500" />
          <MetricCard label="Accepted" value={summary.accepted} dot="bg-emerald-500" />
          <MetricCard label="Rejected" value={summary.rejected} dot="bg-red-400" />
          <MetricCard label="Needs Review" value={summary.needs_review} dot="bg-amber-500" />
          <MetricCard label="Unreviewed" value={summary.unreviewed} dot="bg-slate-400" />
          <MetricCard label="Representative" value={summary.representative} dot="bg-violet-500" />
          <MetricCard label="High Value" value={summary.high_value} dot="bg-blue-500" />
          <MetricCard label="Duplicate Groups" value={summary.duplicate_groups} dot="bg-slate-400" />
          <MetricCard label="Objectives Covered" value={summary.objectives_covered} dot="bg-emerald-500" />
          <MetricCard label="Objectives Insufficient" value={summary.objectives_insufficient} dot="bg-red-400" />
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm mb-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex-1 relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></svg>
            <input type="text" placeholder="Search evidence excerpts..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
              className="w-full border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-[13px] text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all" />
          </div>
          <div className="flex items-center bg-slate-50 border border-slate-200 rounded-lg p-0.5 text-[11px]">
            <button onClick={() => setView("table")} className={`px-3 py-1.5 rounded-md font-semibold transition-all ${view === "table" ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}>Table</button>
            <button onClick={() => setView("card")} className={`px-3 py-1.5 rounded-md font-semibold transition-all ${view === "card" ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}>Card</button>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <FilterSelect label="Statuses" value={statusFilter} onChange={setStatusFilter} options={["all", ...REVIEW_STATUSES]} />
          <FilterSelect label="Objectives" value={objectiveFilter} onChange={setObjectiveFilter} options={["all", ...filterOptions.objectives]} />
          <FilterSelect label="Methods" value={methodFilter} onChange={setMethodFilter} options={["all", ...filterOptions.methods]} />
          <FilterSelect label="Platforms" value={platformFilter} onChange={setPlatformFilter} options={["all", ...filterOptions.platforms]} />
          <FilterSelect label="Confidence" value={confidenceFilter} onChange={setConfidenceFilter} options={["all", ...CONFIDENCES]} />
          <div className="w-px h-6 bg-slate-200 mx-1" />
          <span className="text-[10px] text-slate-400 font-semibold uppercase">Sort</span>
          <FilterSelect label="Sort" value={sortBy} onChange={setSortBy} options={Object.keys(SORT_FIELDS)} labels={SORT_FIELDS} />
          <button onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))} title={sortDir === "asc" ? "Ascending" : "Descending"} className="w-8 h-8 flex items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={sortDir === "asc" ? "M12 19V5M5 12l7-7 7 7" : "M12 5v14M19 12l-7 7-7-7"} /></svg>
          </button>
        </div>
      </div>

      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-xl px-4 py-2.5 mb-4">
          <span className="text-[12px] font-semibold text-blue-700">{selectedIds.size} selected</span>
          <div className="flex-1" />
          <button onClick={() => handleBulkReview("accepted")} disabled={bulkBusy} className="px-3 py-1.5 text-[11px] font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors">Accept Selected</button>
          <button onClick={() => handleBulkReview("rejected")} disabled={bulkBusy} className="px-3 py-1.5 text-[11px] font-semibold bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors">Reject Selected</button>
          <button onClick={() => handleBulkReview("needs_review")} disabled={bulkBusy} className="px-3 py-1.5 text-[11px] font-semibold bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors">Needs Review</button>
          <button onClick={() => setSelectedIds(new Set())} className="px-2 py-1.5 text-[11px] font-semibold text-slate-500 hover:text-slate-700">Clear</button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <SectionHeader title="Evidence Items" count={items.length} />

        {loadingItems ? (
          <div className="text-center py-12 text-[12px] text-slate-400">Loading evidence...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-12 text-[12px] text-slate-400">No evidence items match your filters</div>
        ) : view === "table" ? (
          <EvidenceTable items={items} selectedIds={selectedIds} busyItemId={busyItemId} onToggleSelect={toggleSelect} onToggleSelectAll={toggleSelectAll}
            onReview={handleReview} onToggleRep={handleToggleRep} onToggleHV={handleToggleHV} onNote={(item) => openDetail(item, true)} onDetail={(item) => openDetail(item, false)} />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {items.map((item) => (
              <EvidenceCard key={item.id} item={item} selected={selectedIds.has(item.id)} busy={busyItemId === item.id} onToggleSelect={() => toggleSelect(item.id)}
                onReview={handleReview} onToggleRep={handleToggleRep} onToggleHV={handleToggleHV} onNote={(item2) => openDetail(item2, true)} onDetail={(item2) => openDetail(item2, false)} />
            ))}
          </div>
        )}

        {hasMore && !loadingItems && (
          <div className="text-center mt-5">
            <button onClick={() => fetchItems(offset, true)} disabled={loadingMore} className="px-5 py-2 text-[12px] font-semibold text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 disabled:opacity-50 transition-colors">
              {loadingMore ? "Loading..." : "Load More"}
            </button>
          </div>
        )}
      </div>

      {detailId !== null && (
        <DetailDrawer itemId={detailId} detail={detail} loading={detailLoading} busy={busyItemId === detailId} noteDraft={noteDraft} setNoteDraft={setNoteDraft}
          noteSubmitting={noteSubmitting} noteRef={noteRef} onSubmitNote={submitNote} onClose={closeDetail}
          onReview={(status) => detail && handleReview(detail.item, status)} onToggleRep={() => detail && handleToggleRep(detail.item)} onToggleHV={() => detail && handleToggleHV(detail.item)} />
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between pt-6">
        <button onClick={() => onNavigate("research-execution")} className="px-4 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
          Back to Research Execution
        </button>
        <button onClick={() => onNavigate("insights")} className="px-5 py-2.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          Proceed to Insights
        </button>
      </div>
    </div>
  );
}
