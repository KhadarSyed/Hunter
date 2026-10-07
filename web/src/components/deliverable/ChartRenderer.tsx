import { useLayoutEffect, useRef } from "react";
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import * as am5percent from "@amcharts/amcharts5/percent";
import * as am5radar from "@amcharts/amcharts5/radar";
import * as am5hierarchy from "@amcharts/amcharts5/hierarchy";

export interface ChartSpec {
  kind: "kpi" | "line_peaks" | "bar" | "column" | "doughnut" | "gauge" | "treemap";
  categories: string[];
  values: number[];
  peaks?: number[];
  unit?: "count" | "percent";
  series_label?: string;
}

const VIOLET = "#5B2C9D";
const HOUSE = ["D9C8F0", "FDE3D2", "D4E6F7", "D3F0E3"];
const fmt = (v: number, unit?: string) => (unit === "percent" ? `${v}%` : v.toLocaleString());

type Datum = { category: string; value: number; peak: boolean };

function buildXY(root: am5.Root, spec: ChartSpec, fill: string) {
  const chart = root.container.children.push(am5xy.XYChart.new(root, { paddingLeft: 0 }));
  const data: Datum[] = spec.categories.map((c, i) => ({ category: c, value: spec.values[i] ?? 0, peak: (spec.peaks ?? []).includes(i) }));
  const percent = spec.unit === "percent";
  if (spec.kind === "bar") {
    const yAxis = chart.yAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: am5xy.AxisRendererY.new(root, { inversed: true, minGridDistance: 12 }) }));
    const xAxis = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererX.new(root, {}) }));
    yAxis.data.setAll(data);
    const series = chart.series.push(am5xy.ColumnSeries.new(root, { xAxis, yAxis, valueXField: "value", categoryYField: "category" }));
    series.columns.template.setAll({ fill: am5.color(`#${fill}`), strokeOpacity: 0, cornerRadiusTR: 4, cornerRadiusBR: 4 });
    series.bullets.push(() => am5.Bullet.new(root, { locationX: 1, sprite: am5.Label.new(root, {
      text: percent ? "{valueX}%" : "{valueX}", populateText: true, fontSize: 11, dx: 6, centerY: am5.p50, fill: am5.color("#404040") }) }));
    series.data.setAll(data);
    return;
  }
  const xAxis = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 30 }) }));
  const yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));
  xAxis.data.setAll(data);
  if (spec.kind === "line_peaks") {
    const series = chart.series.push(am5xy.LineSeries.new(root, { xAxis, yAxis, valueYField: "value", categoryXField: "category", stroke: am5.color("#8FB8E0") }));
    series.strokes.template.setAll({ strokeWidth: 2 });
    series.bullets.push((_r, _s, dataItem) => {
      const ctx = dataItem.dataContext as Datum;
      if (!ctx.peak) return undefined;
      const box = am5.Container.new(root, {});
      box.children.push(am5.Circle.new(root, { radius: 6, fill: am5.color(VIOLET) }));
      box.children.push(am5.Label.new(root, { text: String(ctx.value), centerX: am5.p50, centerY: am5.p100, dy: -8, fill: am5.color(VIOLET), fontWeight: "600", fontSize: 12 }));
      return am5.Bullet.new(root, { sprite: box });
    });
    series.data.setAll(data);
    return;
  }
  const series = chart.series.push(am5xy.ColumnSeries.new(root, { xAxis, yAxis, valueYField: "value", categoryXField: "category" }));
  series.columns.template.setAll({ fill: am5.color(`#${fill}`), strokeOpacity: 0, cornerRadiusTL: 4, cornerRadiusTR: 4 });
  series.bullets.push(() => am5.Bullet.new(root, { locationY: 1, sprite: am5.Label.new(root, {
    text: percent ? "{valueY}%" : "{valueY}", populateText: true, fontSize: 11, centerX: am5.p50, dy: -14, fill: am5.color("#404040") }) }));
  series.data.setAll(data);
}

export function ChartRenderer({ spec, height = 280, palette = HOUSE }: { spec: ChartSpec; height?: number; palette?: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!ref.current || spec.kind === "kpi") return;
    const root = am5.Root.new(ref.current);
    const colors = palette.map((c) => am5.color(`#${c}`));
    if (spec.kind === "doughnut") {
      const chart = root.container.children.push(am5percent.PieChart.new(root, { innerRadius: am5.percent(55) }));
      const series = chart.series.push(am5percent.PieSeries.new(root, { valueField: "value", categoryField: "category" }));
      series.get("colors")?.set("colors", colors);
      series.labels.template.setAll({ text: "{category}: {value}%", fontSize: 11 });
      series.data.setAll(spec.categories.map((c, i) => ({ category: c, value: spec.values[i] })));
    } else if (spec.kind === "gauge") {
      const chart = root.container.children.push(am5radar.RadarChart.new(root, { startAngle: 180, endAngle: 360, innerRadius: -20 }));
      const axis = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, max: 100, strictMinMax: true, renderer: am5radar.AxisRendererCircular.new(root, {}) }));
      const range = axis.createAxisRange(axis.makeDataItem({ value: 0, endValue: spec.values[0] }));
      range.get("axisFill")?.setAll({ visible: true, fill: am5.color(VIOLET), fillOpacity: 0.85 });
      chart.radarContainer.children.push(am5.Label.new(root, { text: `${spec.values[0]}%`, centerX: am5.p50, centerY: am5.p100, fontSize: 28, fontWeight: "700", fill: am5.color(VIOLET) }));
    } else if (spec.kind === "treemap") {
      const series = root.container.children.push(am5hierarchy.Treemap.new(root, { valueField: "value", categoryField: "name", childDataField: "children", initialDepth: 1, downDepth: 1 }));
      series.set("colors", am5.ColorSet.new(root, { colors }));
      series.labels.template.setAll({ text: "{category}\n{sum}", fontSize: 12, fill: am5.color("#404040") });
      series.data.setAll([{ name: "root", children: spec.categories.map((c, i) => ({ name: c, value: spec.values[i] })) }]);
      series.set("selectedDataItem", series.dataItems[0]);
    } else {
      buildXY(root, spec, palette[0]);
    }
    return () => root.dispose();
  }, [spec, palette]);

  if (spec.kind === "kpi") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-violet-100 bg-violet-50/40 py-6">
        <span className="text-4xl font-bold" style={{ color: VIOLET }}>{fmt(spec.values[0], spec.unit)}</span>
        <span className="mt-1 text-xs font-medium text-slate-600">{spec.categories[0]}</span>
      </div>
    );
  }
  return <div ref={ref} style={{ width: "100%", height }} role="img" aria-label={spec.series_label || spec.kind} />;
}
