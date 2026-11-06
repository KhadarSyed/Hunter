import type { ReactNode } from "react";
import { formatDate } from "../../utils/format";
import type { EnrichedRecord, DynamicTagDef, RowRelations } from "../../services/intel-api";
import type { ArticleRow, Channel, RqColumn, RqRow } from "../../types/dataset";
import { CountryFlag } from "../CountryFlag";
import { RelationCount } from "../RecordRelations";
import type { RelationKind } from "../RelatedArticlesDrawer";
import { ContentCell } from "./ContentCell";
import { DynamicTagCell, PublisherCell, SentimentPill } from "./cells";
import type { GroupId } from "./ColumnPicker";

export type Col = { id: string; group: GroupId; head: string; w: number; cell: (r: ArticleRow) => ReactNode };
export type ColCtx = {
  brands: string[];
  rqs: RqColumn[];
  relations: Record<string, RowRelations>;
  openRelation: (row: ArticleRow, kind: RelationKind) => void;
};

const dash = <span className="text-slate-300 text-xs">—</span>;
const text = (v: string | null | undefined) => (v ? <span className="text-xs text-slate-700">{v}</span> : dash);
const PILL: Record<string, string> = { approved: "bg-emerald-50 text-emerald-700", irrelevant: "bg-red-50 text-red-700", pending: "bg-amber-50 text-amber-700" };

function Chips({ values, tone = "bg-indigo-50 text-indigo-700" }: { values: string[]; tone?: string }) {
  if (values.length === 0) return dash;
  return <div className="flex flex-wrap gap-1">{values.map((v, i) => <span key={`${i}-${v}`} className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${tone}`}>{v}</span>)}</div>;
}

const THEME_LEVELS = [["primary", "Primary theme"], ["secondary", "Secondary theme"], ["tertiary", "Tertiary theme"]] as const;

export function brandNames(rows: ArticleRow[]): string[] {
  return [...new Set(rows.flatMap((r) => (r.tags.brands ?? []).map((b) => b.brand)))];
}

function rqColumns(q: RqColumn): Col[] {
  const rowOf = (r: ArticleRow): RqRow | undefined => r.rq[q.id];
  const tagCols: Col[] = q.tag_columns.map((t) => ({
    id: `${q.id}.${t.key}`, group: "rq", w: 150, head: `${q.id} · ${t.review_column || t.key}`,
    cell: (r) => {
      const rr = rowOf(r);
      if (!rr || !(t.key in rr.tags)) return dash;
      return <DynamicTagCell record={{ dynamic_tags: rr.tags, tag_evidence: rr.evidence } as unknown as EnrichedRecord}
        tag={{ tag_name: t.key, tag_type: t.type } as unknown as DynamicTagDef} />;
    },
  }));
  return [
    ...tagCols,
    { id: `${q.id}.kw`, group: "rq", w: 150, head: `${q.id} · Matched keywords`, cell: (r) => <Chips values={rowOf(r)?.keywords ?? []} tone="bg-slate-100 text-slate-600" /> },
    { id: `${q.id}.sum`, group: "rq", w: 260, head: `${q.id} · Summary & reason`,
      cell: (r) => { const rr = rowOf(r); return rr?.summary || rr?.reason
        ? <div className="text-xs text-slate-700 space-y-0.5">{rr.summary && <p>{rr.summary}</p>}{rr.reason && <p className="text-slate-500">{rr.reason}</p>}</div> : dash; } },
    { id: `${q.id}.status`, group: "rq", w: 100, head: `${q.id} · Status`,
      cell: (r) => { const rr = rowOf(r); return rr
        ? <><span title={rr.decided_by ? `Decided by ${rr.decided_by}${rr.decided_at ? ` on ${new Date(Number(rr.decided_at) * 1000).toLocaleString()}` : ""}` : "Auto"} className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${PILL[rr.status]}`}>{rr.status === "irrelevant" ? "Rejected" : rr.status === "pending" ? "Review" : "Approved"}</span>
          {rr.query_changed && <span title="The question's query changed; this decision was kept" className="ml-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700">query changed</span>}
          </> : dash; } },
  ];
}

export function buildColumns(ctx: ColCtx, channel: Channel): Col[] {
  const rel = (kind: RelationKind) => (r: ArticleRow) =>
    <RelationCount relations={ctx.relations} rowKey={String(r.id)} kind={kind} onOpen={() => ctx.openRelation(r, kind)} />;
  const asRecord = (r: ArticleRow) => ({ url: r.url, source_name: r.outlet ?? "" }) as unknown as EnrichedRecord;
  const cols: Col[] = [
    { id: "content", group: "details", w: 300, head: "Content", cell: (r) => <ContentCell row={r} /> },
    { id: "cstatus", group: "details", w: 100, head: "Content status", cell: (r) => text(r.content_status.replace("_", " ")) },
    { id: "outlet", group: "details", w: 150, head: "Outlet", cell: (r) => <PublisherCell record={asRecord(r)} /> },
    { id: "date", group: "details", w: 100, head: "Date", cell: (r) => text(formatDate(r.published)) },
    { id: "country", group: "details", w: 130, head: "Country", cell: (r) => (r.country ? <CountryFlag country={r.country} showLabel className="text-xs text-slate-700" /> : dash) },
    { id: "synd", group: "details", w: 90, head: "Syndicated", cell: rel("syndicated") },
    { id: "sim", group: "details", w: 80, head: "Similar", cell: rel("similar") },
  ];
  if (channel === "social") {
    cols.push(
      { id: "author", group: "author", w: 140, head: "Author", cell: (r) => text(r.author_name) },
      { id: "authorid", group: "author", w: 120, head: "Author ID", cell: (r) => text(r.author_id) },
      { id: "post", group: "author", w: 120, head: "Post ID", cell: (r) => text(r.post_id) },
      { id: "atype", group: "author", w: 110, head: "Author type", cell: (r) => text(r.tags.author_type) },
    );
  }
  cols.push({ id: "sent", group: "sentiment", w: 110, head: "Sentiment",
    cell: (r) => <span title={r.tags.sentiment_summary ?? ""}><SentimentPill sentiment={r.sentiment} confidence={r.sentiment_confidence} /></span> });
  for (const name of ctx.brands) {
    cols.push({ id: `brand.${name}`, group: "sentiment", w: 110, head: name, cell: (r) => {
      const b = r.tags.brands?.find((x) => x.brand === name);
      return b ? <span title={b.summary ?? ""}><SentimentPill sentiment={b.sentiment} confidence={b.confidence} /></span> : dash; } });
  }
  for (const [level, head] of THEME_LEVELS) {
    cols.push({ id: `theme.${level}`, group: "themes", w: 170, head, cell: (r) => {
      const raw = r.tags.themes?.[level];
      if (!raw) return dash;
      const title = r.theme_titles?.[raw] ?? raw;
      return <span className="text-xs text-slate-700" title={`Label: ${raw}`}>{title}</span>; } });
  }
  cols.push(
    { id: "signals", group: "other", w: 170, head: "Signals", cell: (r) => <Chips values={r.tags.signals ?? []} tone="bg-amber-50 text-amber-700" /> },
    { id: "entities", group: "other", w: 200, head: "Entities", cell: (r) => <Chips values={Object.values(r.tags.entities ?? {}).flat()} tone="bg-sky-50 text-sky-700" /> },
    { id: "category", group: "other", w: 120, head: "Category", cell: (r) => text(r.tags.category) },
    { id: "group", group: "other", w: 120, head: "Group", cell: (r) => text(r.tags.group) },
  );
  ctx.rqs.forEach((q) => cols.push(...rqColumns(q)));
  cols.push({ id: "matched", group: "rq", w: 160, head: "Matched RQs", cell: (r) => <Chips values={r.matched_rqs} tone="bg-violet-50 text-[#5B2C9D]" /> });
  return cols;
}
