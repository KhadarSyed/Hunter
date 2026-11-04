import type { EnrichedRecord, RowRelations } from "../services/intel-api";
import type { RelatedRow, RelationKind } from "./RelatedArticlesDrawer";

/** Review-tab helpers for the Syndicated / Similar columns: the count button and what its drawer shows. */

const YES = /^(yes|true)$/i;

/** The tags worth reading across a cluster: tone, theme, signals and every question tag that is not a plain "No". */
export function recordTags(r: EnrichedRecord): string[] {
  const tags: string[] = [];
  if (r.overall_sentiment) tags.push(r.overall_sentiment);
  if (r.themes?.primary) tags.push(r.themes.primary);
  tags.push(...(r.signals || []));
  for (const [name, value] of Object.entries(r.dynamic_tags || {})) {
    const values = (Array.isArray(value) ? value : [value]).filter((v) => v && !/^(no|false|none)$/i.test(v));
    const label = name.replace(/_/g, " ");
    tags.push(...values.map((v) => (YES.test(v) ? label : `${label}: ${v}`)));
  }
  if (r.review_status === "irrelevant") tags.push("Marked irrelevant");
  return [...new Set(tags)];
}

export function recordRow(r: EnrichedRecord): RelatedRow {
  return { key: `${r.dataset_id}:${r.id}`, url: r.url, title: r.title, publisher: r.source_name,
           date: r.date, content: r.content, tags: recordTags(r) };
}

/** Combined reach, first/latest date and negative share: how far and how fast the story is spreading. */
export function clusterSummary(source: EnrichedRecord, related: EnrichedRecord[]): string {
  const all = [source, ...related];
  const reach = all.reduce((sum, r) => sum + (Number(String(r.reach || "").replace(/[^\d.]/g, "")) || 0), 0);
  // the Review tab's dates read day first ("25-09-2026"): sort on year-month-day, show them as written
  const sortable = (d: string) => d.replace(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})/, (_, a, b, y) =>
    `${y}-${b.padStart(2, "0")}-${a.padStart(2, "0")}`);
  const dates = all.map((r) => r.date).filter(Boolean).sort((a, b) => sortable(a).localeCompare(sortable(b)));
  const negative = all.filter((r) => r.overall_sentiment === "Negative").length;
  const parts = [`${all.length} articles`];
  if (reach > 0) parts.push(`combined reach ${reach.toLocaleString()}`);
  if (dates.length > 1) parts.push(`${dates[0]} → ${dates[dates.length - 1]}`);
  if (negative) parts.push(`${negative} negative`);
  return parts.join(" · ");
}

type CountProps = {
  relations: Record<string, RowRelations> | null | undefined;
  rowKey: string;
  kind: RelationKind;
  onOpen: () => void;
};

export function RelationCount({ relations, rowKey, kind, onOpen }: CountProps) {
  if (relations === undefined) return <span className="text-slate-300" title="Finding related articles…">…</span>;
  if (relations === null) return <span className="text-slate-300" title="Could not load">—</span>;
  const count = relations[rowKey]?.[kind]?.length ?? 0;
  if (count === 0) return <span className="text-slate-300">0</span>;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="px-1.5 py-0.5 rounded bg-violet-50 text-[#5B2C9D] font-semibold hover:bg-violet-100 hover:underline"
      aria-label={`${count} ${kind} article${count === 1 ? "" : "s"}`}
    >
      {count}
    </button>
  );
}
