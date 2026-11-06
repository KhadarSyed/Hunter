import { useLayoutEffect, useRef, useState } from "react";
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import type { TrendGrain, UsageTrendRow } from "../../types/usage";
import { logoRow, logoUrls } from "./chartLogos";

export type Metric = "cost" | "tokens";

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;
const MAX_POINTS = 400;   // a range with more buckets than this is drawn from its last 400
const LOGO = 16;
const SERIES_COLORS = ["#5B2C9D", "#0F7B6C", "#E07B39", "#2563EB", "#DB2777", "#65A30D", "#7C3AED", "#0891B2"];
const GRAIN_LABEL: Record<TrendGrain, string> = { hour: "Hourly", day: "Daily", month: "Monthly", year: "Yearly" };
const TOOLTIP_FORMAT: Record<TrendGrain, string> = { hour: "MMM d, HH:00", day: "MMM d, yyyy", month: "MMM yyyy", year: "yyyy" };

/** A two-or-three way switch above a chart. */
export function ChartToggle<T extends string>({ label, value, options, onChange }:
  { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-full bg-slate-100 p-0.5 text-xs font-semibold">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={`rounded-full px-3 py-1 ${value === o.value ? "bg-white text-[#5B2C9D] shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** The UTC bucket a call falls in, in the API's text form (2026-11-07T04 / 2026-11-07 / 2026-11 / 2026). */
export function bucketOf(tsSeconds: number, grain: TrendGrain): string {
  const iso = new Date(tsSeconds * 1000).toISOString();
  return grain === "hour" ? iso.slice(0, 13) : grain === "day" ? iso.slice(0, 10) : grain === "month" ? iso.slice(0, 7) : iso.slice(0, 4);
}

/** A bucket's start, in UTC ms. */
function bucketMs(b: string): number {
  const [date, hour] = b.split("T");
  const [y, m = 1, d = 1] = date.split("-").map(Number);
  return Date.UTC(y, m - 1, d, hour ? Number(hour) : 0);
}

/** Every bucket of the range (a model with no calls in one draws 0); a range ending today stops at the current bucket. */
function rangeBuckets(from: string, to: string, grain: TrendGrain): number[] {
  const start = grain === "month" ? from.slice(0, 7) : grain === "year" ? from.slice(0, 4) : from;
  let t = bucketMs(start);
  const last = Math.min(bucketMs(to) + (grain === "hour" ? DAY_MS - HOUR_MS : 0), bucketMs(bucketOf(Date.now() / 1000, grain)));
  if (!Number.isFinite(t) || !Number.isFinite(last) || last < t) return [];
  const out: number[] = [];
  while (t <= last) {
    out.push(t);
    const d = new Date(t);
    t = grain === "hour" ? t + HOUR_MS : grain === "day" ? t + DAY_MS
      : grain === "month" ? Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) : Date.UTC(d.getUTCFullYear() + 1, 0, 1);
  }
  return out.slice(-MAX_POINTS);
}

type Built = { series: Map<string, am5xy.LineSeries>; total: am5xy.LineSeries; buckets: number[] };

/** Cost or tokens over time, bucketed by the range (hour / day / month / year): one line per model (legend =
 * provider logos + full model name) and a dashed Total. Live data moves the points in place; the chart is only
 * rebuilt when the range, metric or set of models changes. */
export function UsageTrendChart({ rows, from, to, grain = "day" }: { rows: UsageTrendRow[]; from: string; to: string; grain?: TrendGrain }) {
  const ref = useRef<HTMLDivElement>(null);
  const built = useRef<Built | null>(null);
  const [metric, setMetric] = useState<Metric>("cost");
  const field = metric === "cost" ? "cost_usd" : "total_tokens";
  const models = [...new Map(rows.map((r) => [`${r.provider}/${r.model}`, { provider: r.provider, model: r.model }])).entries()];
  const modelsKey = models.map(([k]) => k).sort().join("|");

  const valuesOf = (key: string, buckets: number[]): number[] => {
    const by = new Map<number, number>();
    for (const r of rows) {
      if (`${r.provider}/${r.model}` !== key) continue;
      const t = bucketMs(r.bucket);
      by.set(t, (by.get(t) ?? 0) + (Number(r[field]) || 0));
    }
    return buckets.map((t) => by.get(t) ?? 0);
  };

  // Moves only the points that changed, so amCharts animates them instead of redrawing the chart.
  const apply = () => {
    const b = built.current;
    if (!b) return;
    const totals = b.buckets.map(() => 0);
    const put = (s: am5xy.LineSeries, vals: number[]) => {
      if (s.data.length !== vals.length) { s.data.setAll(b.buckets.map((t, i) => ({ date: t, value: vals[i] }))); return; }
      vals.forEach((v, i) => {
        if ((s.data.getIndex(i) as { value: number }).value !== v) s.data.setIndex(i, { date: b.buckets[i], value: v });
      });
    };
    for (const [key, s] of b.series) {
      const vals = valuesOf(key, b.buckets);
      vals.forEach((v, i) => { totals[i] += v; });
      put(s, vals);
    }
    put(b.total, totals);
  };

  useLayoutEffect(() => {
    if (!ref.current) return;
    const root = am5.Root.new(ref.current);
    root.utc = true;   // the API's buckets are UTC
    root.numberFormatter.set("numberFormat", metric === "cost" ? "$#,##0.00##" : "#,###");

    const chart = root.container.children.push(am5xy.XYChart.new(root, { layout: root.verticalLayout, paddingLeft: 0 }));
    const xAxis = chart.xAxes.push(am5xy.DateAxis.new(root, {
      baseInterval: { timeUnit: grain, count: 1 },
      tooltipDateFormat: TOOLTIP_FORMAT[grain],
      renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 60 }),
    }));
    const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));
    chart.set("cursor", am5xy.XYCursor.new(root, { behavior: "none", xAxis }));

    const buckets = rangeBuckets(from, to, grain);
    const addLine = (name: string, color: string, dashed = false) => {
      const s = chart.series.push(am5xy.LineSeries.new(root, {
        name, xAxis, yAxis, valueXField: "date", valueYField: "value", stroke: am5.color(color), fill: am5.color(color),
        tooltip: am5.Tooltip.new(root, { labelText: "{name}: {valueY}" }),
      }));
      s.strokes.template.setAll({ strokeWidth: 2, ...(dashed ? { strokeDasharray: [6, 4] } : {}) });
      return s;
    };
    const series = new Map<string, am5xy.LineSeries>();
    const logosBySeries = new Map<am5xy.XYSeries, string[]>();
    models.forEach(([key, m], i) => {
      const s = addLine(m.model, SERIES_COLORS[i % SERIES_COLORS.length]);
      series.set(key, s);
      logosBySeries.set(s, logoUrls(m.provider, m.model));
    });
    const total = addLine("Total", "#0F172A", true);
    built.current = { series, total, buckets };
    apply();

    const legend = chart.children.push(am5.Legend.new(root, { useDefaultMarker: true, centerX: am5.p50, x: am5.p50, marginTop: 8 }));
    legend.labels.template.setAll({ fontSize: 12, fontWeight: "500" });
    legend.data.setAll(chart.series.values);
    // Each model's marker: its line colour as a dot, then the provider logo(s); the label is the full model name.
    for (const item of legend.dataItems) {
      const s = item.dataContext as am5xy.XYSeries;
      const urls = logosBySeries.get(s);
      if (!urls) continue;   // Total keeps its plain swatch
      const marker = item.get("marker");
      item.get("markerRectangle").set("forceHidden", true);
      marker.setAll({ layout: root.horizontalLayout, width: 14 + urls.length * (LOGO + 3), height: 18 });
      marker.children.push(am5.Circle.new(root, { radius: 5, fill: s.get("stroke"), centerY: am5.p50, y: am5.p50, marginRight: 4 }));
      marker.children.push(logoRow(root, urls, LOGO, { centerY: am5.p50, y: am5.p50 }));
    }
    return () => { built.current = null; root.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to, grain, metric, modelsKey]);

  // new rows (a live call, a quiet re-read): move the points in place
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(apply, [rows]);

  const title = `${GRAIN_LABEL[grain]} ${metric === "cost" ? "cost" : "tokens"} by model`;
  return (
    <section aria-labelledby="usage-trend-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="usage-trend-heading" className="text-lg font-semibold text-slate-900">{title}</h2>
        <ChartToggle label="Trend metric" value={metric} onChange={setMetric}
          options={[{ value: "cost", label: "Cost" }, { value: "tokens", label: "Tokens" }]} />
      </div>
      <div ref={ref} style={{ height: 360 }} role="img" aria-label={`Line chart of ${title.toLowerCase()}, with a dashed total`} />
    </section>
  );
}
