import type { ArticleFilters, ArticleRow, RqColumn, StatusFilter } from "../../types/dataset";

const STATUSES: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "All" }, { id: "approved", label: "Approved" }, { id: "review", label: "Review" },
  { id: "irrelevant", label: "Irrelevant" }, { id: "no_match", label: "No RQ match" },
];
const sel = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700";

const unique = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => !!x))].sort();

type Props = {
  filters: ArticleFilters;
  rqs: RqColumn[];
  options: ArticleRow[];   // rows the dropdown values are drawn from
  onChange: (patch: Partial<ArticleFilters>) => void;
};

export function FilterBar({ filters, rqs, options, onChange }: Props) {
  // The column shows consolidated titles but the API filters on the raw label: list title, value label.
  const labelTitle = new Map(options.flatMap((r) => Object.entries(r.theme_titles ?? {})));
  const themes = unique(options.flatMap((r) => Object.values(r.tags.themes ?? {})));
  const titleCount = new Map<string, number>();
  themes.forEach((l) => titleCount.set(labelTitle.get(l) ?? l, (titleCount.get(labelTitle.get(l) ?? l) ?? 0) + 1));
  const themeOptions = themes.map((l) => {
    const title = labelTitle.get(l) ?? l;
    return { value: l, text: (titleCount.get(title) ?? 0) > 1 ? `${title} (${l})` : title };
  }).sort((a, b) => a.text.localeCompare(b.text));
  const brands = unique(options.flatMap((r) => (r.tags.brands ?? []).map((b) => b.brand)));
  const contentStatuses = unique(options.map((r) => r.content_status));
  const select = (label: string, key: "rq" | "sentiment" | "theme" | "brand" | "content_status", values: { value: string; text: string }[], all: string) => (
    <select aria-label={label} className={sel} value={filters[key]} onChange={(e) => onChange({ [key]: e.target.value })}>
      <option value="">{all}</option>
      {values.map((v) => <option key={v.value} value={v.value}>{v.text}</option>)}
    </select>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Status" className="flex overflow-hidden rounded-lg border border-slate-200">
        {STATUSES.map((s) => (
          <button key={s.id} type="button" aria-pressed={filters.status === s.id} onClick={() => onChange({ status: s.id })}
            className={`px-3 py-1.5 text-xs font-medium ${filters.status === s.id ? "bg-[#5B2C9D] text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>{s.label}</button>
        ))}
      </div>
      {select("Research question", "rq", rqs.map((q) => ({ value: q.id, text: q.id })), "All RQs")}
      {select("Sentiment", "sentiment", ["Positive", "Neutral", "Negative"].map((v) => ({ value: v, text: v })), "Any sentiment")}
      {select("Theme", "theme", themeOptions, "Any theme")}
      {select("Brand", "brand", brands.map((v) => ({ value: v, text: v })), "Any brand")}
      {select("Content status", "content_status", contentStatuses.map((v) => ({ value: v, text: v })), "Any content status")}
      <input type="search" aria-label="Search articles" placeholder="Search title or content" value={filters.q} maxLength={200}
        onChange={(e) => onChange({ q: e.target.value })} className={`${sel} w-56`} />
    </div>
  );
}
