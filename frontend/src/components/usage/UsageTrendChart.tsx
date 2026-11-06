import { useLayoutEffect, useRef, useState } from "react";
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import type { UsageTrendRow } from "../../types/usage";
import { logoRow, logoUrls } from "./chartLogos";

export type Metric = "cost" | "tokens";

const DAY_MS = 86_400_000;
const MAX_DAYS = 400;   // a custom range longer than this is drawn from its last 400 days
const LOGO = 16;
const SERIES_COLORS = ["#5B2C9D", "#0F7B6C", "#E07B39", "#2563EB", "#DB2777", "#65A30D", "#7C3AED", "#0891B2"];

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

const utcDay = (day: string): number => {
  const [y, m, d] = day.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
};

/** Every UTC day of the range, so a model with no calls on a day draws 0 instead of skipping it. */
function rangeDays(from: string, to: string): number[] {
  const start = utcDay(from), end = utcDay(to);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
  const first = Math.max(start, end - (MAX_DAYS - 1) * DAY_MS);
  const days: number[] = [];
  for (let t = first; t <= end; t += DAY_MS) days.push(t);
  return days;
}

/** Daily cost or tokens: one line per model (legend = provider logos + full model name) and a dashed Total. */
export function UsageTrendChart({ rows, from, to }: { rows: UsageTrendRow[]; from: string; to: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [metric, setMetric] = useState<Metric>("cost");

  useLayoutEffect(() => {
    if (!ref.current) return;
    const root = am5.Root.new(ref.current);
    root.utc = true;   // the API's days are UTC dates
    root.numberFormatter.set("numberFormat", metric === "cost" ? "$#,##0.00##" : "#,###");

    const chart = root.container.children.push(am5xy.XYChart.new(root, { layout: root.verticalLayout, paddingLeft: 0 }));
    const xAxis = chart.xAxes.push(am5xy.DateAxis.new(root, {
      baseInterval: { timeUnit: "day", count: 1 },
      renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 60 }),
    }));
    const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));
    chart.set("cursor", am5xy.XYCursor.new(root, { behavior: "none", xAxis }));

    const days = rangeDays(from, to);
    const field = metric === "cost" ? "cost_usd" : "total_tokens";
    const models = new Map<string, { provider: string; model: string; byDay: Map<number, number> }>();
    for (const r of rows) {
      const key = `${r.provider}/${r.model}`;
      if (!models.has(key)) models.set(key, { provider: r.provider, model: r.model, byDay: new Map() });
      const byDay = models.get(key)!.byDay;
      const t = utcDay(r.day);
      byDay.set(t, (byDay.get(t) ?? 0) + (Number(r[field]) || 0));
    }

    const logosBySeries = new Map<am5xy.XYSeries, string[]>();
    const addLine = (name: string, color: string, values: (t: number) => number, dashed = false) => {
      const series = chart.series.push(am5xy.LineSeries.new(root, {
        name, xAxis, yAxis, valueXField: "date", valueYField: "value", stroke: am5.color(color), fill: am5.color(color),
        tooltip: am5.Tooltip.new(root, { labelText: "{name}: {valueY}" }),
      }));
      series.strokes.template.setAll({ strokeWidth: 2, ...(dashed ? { strokeDasharray: [6, 4] } : {}) });
      series.data.setAll(days.map((t) => ({ date: t, value: values(t) })));
      return series;
    };
    [...models.values()].forEach((m, i) => {
      const s = addLine(m.model, SERIES_COLORS[i % SERIES_COLORS.length], (t) => m.byDay.get(t) ?? 0);
      logosBySeries.set(s, logoUrls(m.provider, m.model));
    });
    addLine("Total", "#0F172A", (t) => [...models.values()].reduce((sum, m) => sum + (m.byDay.get(t) ?? 0), 0), true);

    const legend = chart.children.push(am5.Legend.new(root, { useDefaultMarker: true, centerX: am5.p50, x: am5.p50, marginTop: 8 }));
    legend.labels.template.setAll({ fontSize: 12, fontWeight: "500" });
    legend.data.setAll(chart.series.values);
    // Each model's marker: its line colour as a dot, then the provider logo(s); the label is the full model name.
    for (const item of legend.dataItems) {
      const series = item.dataContext as am5xy.XYSeries;
      const urls = logosBySeries.get(series);
      if (!urls) continue;   // Total keeps its plain swatch
      const marker = item.get("marker");
      item.get("markerRectangle").set("forceHidden", true);
      marker.setAll({ layout: root.horizontalLayout, width: 14 + urls.length * (LOGO + 3), height: 18 });
      marker.children.push(am5.Circle.new(root, { radius: 5, fill: series.get("stroke"), centerY: am5.p50, y: am5.p50, marginRight: 4 }));
      marker.children.push(logoRow(root, urls, LOGO, { centerY: am5.p50, y: am5.p50 }));
    }
    return () => root.dispose();
  }, [rows, from, to, metric]);

  return (
    <section aria-labelledby="usage-trend-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="usage-trend-heading" className="text-lg font-semibold text-slate-900">Daily {metric === "cost" ? "cost" : "tokens"} by model</h2>
        <ChartToggle label="Trend metric" value={metric} onChange={setMetric}
          options={[{ value: "cost", label: "Cost" }, { value: "tokens", label: "Tokens" }]} />
      </div>
      <div ref={ref} style={{ height: 360 }} role="img" aria-label={`Line chart of daily ${metric} per model, with a dashed total`} />
    </section>
  );
}
