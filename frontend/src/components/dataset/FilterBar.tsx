import type { ArticleFacets, ArticleFilters, RqColumn, StatusFilter } from "../../types/dataset";

const STATUSES: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "All" }, { id: "approved", label: "Approved" }, { id: "review", label: "Review" },
  { id: "irrelevant", label: "Irrelevant" }, { id: "no_match", label: "No RQ match" },
];
const sel = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700";

type Props = {
  filters: ArticleFilters;
  rqs: RqColumn[];
  facets: ArticleFacets;   // the channel's dropdown values
  onChange: (patch: Partial<ArticleFilters>) => void;
};

export function FilterBar({ filters, rqs, facets, onChange }: Props) {
  // The column shows consolidated titles but the API filters on the raw label: list title, value label.
  const labelTitle = new Map(facets.themes.map((t) => [t.label, t.title]));
  const themes = facets.themes.map((t) => t.label);
  const titleCount = new Map<string, number>();
  themes.forEach((l) => titleCount.set(labelTitle.get(l) ?? l, (titleCount.get(labelTitle.get(l) ?? l) ?? 0) + 1));
  const themeOptions = themes.map((l) => {
    const title = labelTitle.get(l) ?? l;
    return { value: l, text: (titleCount.get(title) ?? 0) > 1 ? `${title} (${l})` : title };
  }).sort((a, b) => a.text.localeCompare(b.text));
  const { brands, content_statuses: contentStatuses } = facets;
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
      <input type="search" aria-label="Search articles" placeholder="Search title, summary or outlet" value={filters.q} maxLength={200}
        onChange={(e) => onChange({ q: e.target.value })} className={`${sel} w-56`} />
    </div>
  );
}
