import { useEffect, useLayoutEffect, useRef, useState } from "react";
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import type { UsageSummary } from "../../types/usage";
import { logoRow, logoUrls } from "./chartLogos";
import { ChartToggle, type Metric } from "./UsageTrendChart";
import { stageLabel } from "./format";

type Category = "model" | "stage" | "project";
interface Bar { category: string; fresh: number; cached: number; output: number; cost: number; logos: string[] }

const MAX_PROJECT_BARS = 12;   // shortcut: only the top 12 projects get a bar; add paging if the long tail matters
const COLORS = { fresh: "#A98BD6", cached: "#CBD5E1", output: "#5B2C9D" };
const LOGO = 18;

const bar = (category: string, t: { input_tokens: number; cached_input_tokens: number; output_tokens: number; cost_usd: number },
  logos: string[] = []): Bar => ({
  // cached input is part of input_tokens, so the stack shows uncached input + cached + output = total
  category, fresh: Math.max(0, t.input_tokens - t.cached_input_tokens), cached: t.cached_input_tokens,
  output: t.output_tokens, cost: t.cost_usd, logos,
});

function bars(summary: UsageSummary, category: Category): Bar[] {
  if (category === "stage") return summary.by_stage.map((s) => bar(stageLabel(s.stage), s));
  if (category === "project") {
    return summary.by_project.slice(0, MAX_PROJECT_BARS).map((p) =>
      bar(p.project_name ?? (p.project_id === null ? "No project" : `Project #${p.project_id}`), p));
  }
  // one bar per model name (a model priced under two deployment types is summed)
  const byModel = new Map<string, Bar>();
  for (const m of summary.by_model) {
    const b = bar(m.model, m, logoUrls(m.provider, m.model));
    const prev = byModel.get(m.model);
    byModel.set(m.model, prev ? { ...prev, fresh: prev.fresh + b.fresh, cached: prev.cached + b.cached,
      output: prev.output + b.output, cost: prev.cost + b.cost } : b);
  }
  return [...byModel.values()];
}

/** Stacked tokens (uncached input, cached input, output) or cost per model, stage or project; model bars carry provider logos. */
export function UsageBarChart({ summary, projectFiltered }: { summary: UsageSummary; projectFiltered: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [metric, setMetric] = useState<Metric>("tokens");
  const [category, setCategory] = useState<Category>(projectFiltered ? "stage" : "model");
  useEffect(() => setCategory(projectFiltered ? "stage" : "model"), [projectFiltered]);

  useLayoutEffect(() => {
    if (!ref.current) return;
    const root = am5.Root.new(ref.current);
    root.numberFormatter.set("numberFormat", metric === "cost" ? "$#,##0.00##" : "#,###");
    const data = bars(summary, category);

    const chart = root.container.children.push(am5xy.XYChart.new(root, { layout: root.verticalLayout, paddingLeft: 0 }));
    const xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 20 });
    xRenderer.labels.template.setAll({
      oversizedBehavior: "wrap-no-break", textAlign: "center", fontSize: 12, paddingTop: category === "model" ? LOGO + 8 : 4,
    });
    const xAxis = chart.xAxes.push(am5xy.CategoryAxis.new(root, {
      categoryField: "category",
      renderer: xRenderer,
      // Model bars: the provider logo(s) above the full model name on the axis.
      bullet: category === "model" ? (r, _axis, dataItem) => am5xy.AxisBullet.new(r, {
        location: 0.5,
        sprite: logoRow(r, (dataItem.dataContext as Bar).logos, LOGO, { centerX: am5.p50, centerY: am5.percent(-40) }),
      }) : undefined,
    }));
    xAxis.onPrivate("cellWidth", (w) => xRenderer.labels.template.set("maxWidth", w));
    xAxis.data.setAll(data);
    const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));

    const addColumns = (name: string, field: keyof Bar, color: string, stacked: boolean) => {
      const series = chart.series.push(am5xy.ColumnSeries.new(root, {
        name, xAxis, yAxis, stacked, valueYField: field, categoryXField: "category", fill: am5.color(color), stroke: am5.color(color),
        tooltip: am5.Tooltip.new(root, { labelText: "{categoryX}\n{name}: {valueY}" }),
      }));
      series.columns.template.setAll({ width: am5.percent(60), strokeOpacity: 0 });
      series.data.setAll(data);
    };
    if (metric === "cost") {
      addColumns("Cost", "cost", COLORS.output, false);
    } else {
      addColumns("Input (uncached)", "fresh", COLORS.fresh, true);
      addColumns("Cached input", "cached", COLORS.cached, true);
      addColumns("Output", "output", COLORS.output, true);
    }
    const legend = chart.children.push(am5.Legend.new(root, { centerX: am5.p50, x: am5.p50, marginTop: 8 }));
    legend.labels.template.setAll({ fontSize: 12, fontWeight: "500" });
    legend.data.setAll(chart.series.values);
    return () => root.dispose();
  }, [summary, category, metric]);

  return (
    <section aria-labelledby="usage-bars-heading" className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-900/5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="usage-bars-heading" className="text-lg font-semibold text-slate-900">
          {metric === "cost" ? "Cost" : "Input, cached and output tokens"} by {category}
        </h2>
        <div className="flex flex-wrap gap-2">
          <ChartToggle label="Group bars by" value={category} onChange={setCategory}
            options={[{ value: "model", label: "Model" }, { value: "stage", label: "Stage" }, { value: "project", label: "Project" }]} />
          <ChartToggle label="Bar metric" value={metric} onChange={setMetric}
            options={[{ value: "tokens", label: "Tokens" }, { value: "cost", label: "Cost" }]} />
        </div>
      </div>
      <div ref={ref} style={{ height: 360 }} role="img" aria-label={`Bar chart of ${metric} by ${category}`} />
    </section>
  );
}
