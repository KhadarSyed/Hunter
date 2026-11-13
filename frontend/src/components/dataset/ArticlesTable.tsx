import { useEffect, useMemo, useState } from "react";
import { intelApi } from "../../services/intel-api";
import type { RowRelations } from "../../services/intel-api";
import type { ArticleRow, Channel, RqColumn } from "../../types/dataset";
import { RelatedArticlesDrawer, type RelationKind } from "../RelatedArticlesDrawer";
import { ArticleDrawer } from "./ArticleDrawer";
import { TriCheckbox } from "./cells";
import { brandNames, buildColumns } from "./columns";
import type { GroupId } from "./ColumnPicker";

export const PAGE_SIZE = 100;
const STATUS_PILL: Record<ArticleRow["status"], string> = {
  Approved: "bg-emerald-50 text-emerald-700", Review: "bg-amber-50 text-amber-700",
  Irrelevant: "bg-red-50 text-red-700", "No RQ match": "bg-slate-100 text-slate-500",
};
// Sticky offsets of the pinned columns: checkbox 40, S.No 56, Status 120, then the title.
const STATUS_W = 150;
const PIN = { check: 0, sno: 40, status: 96, title: 96 + STATUS_W };
const th = "px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-500 bg-slate-50 border-b border-slate-200 whitespace-nowrap";

type Props = {
  projectId: number;
  channel: Channel;
  rows: ArticleRow[];
  brands: string[];           // every brand of the channel: one column each
  rqs: RqColumn[];
  total: number;
  offset: number;
  loading: boolean;
  hidden: GroupId[];
  selected: Set<number>;
  selectionComplete: boolean;  // every matching row (all pages) is selected
  onToggle: (id: number) => void;
  onToggleAll: () => void;
  onPage: (offset: number) => void;
  onDecide: (id: number, status: "approved" | "irrelevant") => void;
  /** keep an article the exclusion list blocked (asks for a comment); absent while tagging runs */
  onKeep?: (row: ArticleRow) => void;
  /** false until tagging has run: no row decisions or selection yet */
  canDecide?: boolean;
  /** false: rows can be selected but have no per-row Approve / Reject (the Irrelevant pool) */
  rowActions?: boolean;
  onEdited: () => void;
};

export function ArticlesTable(p: Props) {
  const [drawer, setDrawer] = useState<ArticleRow | null>(null);
  const [relation, setRelation] = useState<{ row: ArticleRow; kind: RelationKind } | null>(null);
  const relations = useMemo(() => Object.fromEntries(p.rows.map((r) => [String(r.id),
    { syndicated: (r.syndicated ?? []).map(String), similar: (r.similar ?? []).map(String) } as RowRelations])), [p.rows]);
  const [related, setRelated] = useState<ArticleRow[]>([]);
  const cols = useMemo(
    () => buildColumns({ brands: p.brands.length ? p.brands : brandNames(p.rows), rqs: p.rqs, relations, openRelation: (row, kind) => setRelation({ row, kind }) }, p.channel)
      .filter((c) => !p.hidden.includes(c.group)),
    [p.rows, p.brands, p.rqs, relations, p.channel, p.hidden]);
  // Syndicated / Similar articles may sit on other pages: fetch them by id when the drawer opens.
  useEffect(() => {
    setRelated([]);
    const ids = relation ? (relation.kind === "syndicated" ? relation.row.syndicated : relation.row.similar) ?? [] : [];
    if (ids.length === 0) return;
    let stale = false;
    intelApi.articlesByIds(p.projectId, ids).then((rows) => { if (!stale) setRelated(rows); }).catch(() => { /* drawer shows none */ });
    return () => { stale = true; };
  }, [relation, p.projectId]);
  const pinned = (left: number, extra: string) => ({ className: `sticky z-10 bg-white group-hover:bg-slate-50 ${extra}`, style: { left } });
  const last = Math.min(p.offset + PAGE_SIZE, p.total);

  return (
    <div>
      <div className="overflow-auto rounded-xl border border-slate-200 bg-white max-h-[70vh]">
        <table className="min-w-max border-separate border-spacing-0 text-sm">
          <thead className="sticky top-0 z-20">
            <tr>
              <th className={`${th} sticky z-30 w-10`} style={{ left: PIN.check }}>
                <TriCheckbox ariaLabel="Select all matching articles" checked={p.selectionComplete && p.total > 0}
                  indeterminate={p.selected.size > 0} onChange={p.onToggleAll} />
              </th>
              <th className={`${th} sticky z-30`} style={{ left: PIN.sno }}>S.No</th>
              <th className={`${th} sticky z-30`} style={{ left: PIN.status, width: STATUS_W, minWidth: STATUS_W, maxWidth: STATUS_W }}>Status</th>
              <th className={`${th} sticky z-30`} style={{ left: PIN.title, minWidth: 260 }}>Title</th>
              {cols.map((c) => <th key={c.id} className={th} style={{ minWidth: c.w }}>{c.head}</th>)}
            </tr>
          </thead>
          <tbody>
            {p.rows.map((r, i) => (
              <tr key={r.id} className="group align-top">
                <td {...pinned(PIN.check, "px-3 py-2.5 border-b border-slate-100")}>
                  {p.canDecide !== false && <TriCheckbox ariaLabel={`Select article ${i + 1 + p.offset}`} checked={p.selected.has(r.id)} onChange={() => p.onToggle(r.id)} />}
                </td>
                <td {...pinned(PIN.sno, "px-3 py-2.5 border-b border-slate-100 text-xs text-slate-400 tabular-nums")}>{p.offset + i + 1}</td>
                <td {...pinned(PIN.status, "px-3 py-2.5 border-b border-slate-100 overflow-hidden")} style={{ left: PIN.status, width: STATUS_W, minWidth: STATUS_W, maxWidth: STATUS_W }}>
                  <div className="flex items-center gap-1.5">
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full whitespace-nowrap truncate ${STATUS_PILL[r.status]}`}>{r.status}</span>
                    {p.canDecide !== false && p.rowActions !== false && <span className="invisible group-hover:visible group-focus-within:visible flex gap-0.5 shrink-0">
                      <button type="button" aria-label="Approve this article" title="Approve" onClick={() => p.onDecide(r.id, "approved")}
                        className="w-5 h-5 rounded text-emerald-700 hover:bg-emerald-50 text-xs">✓</button>
                      <button type="button" aria-label="Reject this article" title="Reject" onClick={() => p.onDecide(r.id, "irrelevant")}
                        className="w-5 h-5 rounded text-red-700 hover:bg-red-50 text-xs">✕</button>
                    </span>}
                  </div>
                  {r.excluded_reason && (
                    <div className="mt-1 space-y-1">
                      <span title={r.excluded_reason} className="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-slate-800 text-white">Blocked</span>
                      {p.onKeep && <button type="button" onClick={() => p.onKeep?.(r)} title="Keep this article: it is relevant despite the exclusion list"
                        className="block text-[11px] font-medium text-[#5B2C9D] hover:underline">Mark relevant</button>}
                    </div>
                  )}
                  {r.keep_at && (
                    <span title={`Kept relevant by ${r.keep_by ?? "an analyst"}: ${r.keep_comment ?? ""}`}
                      className="mt-1 inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">Kept · {r.keep_by ?? "analyst"}</span>
                  )}
                </td>
                <td {...pinned(PIN.title, "px-3 py-2.5 border-b border-slate-100 border-r")}>
                  <button type="button" onClick={() => setDrawer(r)} className="text-left text-xs font-medium text-[#5B2C9D] hover:underline line-clamp-3 max-w-[260px]">
                    {r.title || "(untitled)"}
                  </button>
                </td>
                {cols.map((c) => <td key={c.id} className="px-3 py-2.5 border-b border-slate-100" style={{ maxWidth: c.w + 40 }}>{c.cell(r)}</td>)}
              </tr>
            ))}
            {p.rows.length === 0 && (
              <tr><td colSpan={cols.length + 4} className="px-4 py-10 text-center text-sm text-slate-400">
                {p.loading ? "Loading…" : "No articles match."}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between pt-2 text-xs text-slate-500">
        <span>{p.total === 0 ? "0 articles" : `${p.offset + 1}–${last} of ${p.total.toLocaleString("en-US")}`}</span>
        <span className="flex gap-2">
          <button type="button" disabled={p.offset === 0} onClick={() => p.onPage(Math.max(0, p.offset - PAGE_SIZE))} className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40">Previous</button>
          <button type="button" disabled={last >= p.total} onClick={() => p.onPage(p.offset + PAGE_SIZE)} className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40">Next</button>
        </span>
      </div>
      {drawer && <ArticleDrawer projectId={p.projectId} row={drawer} rqs={p.rqs} onClose={() => setDrawer(null)} onSaved={() => { setDrawer(null); p.onEdited(); }} />}
      {relation && (
        <RelatedArticlesDrawer kind={relation.kind} source={{ title: relation.row.title, publisher: relation.row.outlet }}
          related={related
            .map((x) => ({ key: String(x.id), url: x.url, title: x.title, publisher: x.outlet, date: x.published ?? "",
              content: x.content || x.summary, tags: [x.sentiment, x.tags.themes?.primary].filter((t): t is string => !!t) }))}
          onClose={() => setRelation(null)} />
      )}
    </div>
  );
}
