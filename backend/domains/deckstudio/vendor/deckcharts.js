// Draws the deck's charts with amCharts 5 from the configs in #deck-charts (built by deckstudio/amcharts.py), in place
// of each slide's SVG chart, which stays as the fallback when amCharts can not draw. In export mode (?export=1) the
// charts are drawn without animation, and window.deckCharts hands each one to the exporter as SVG.
(function () {
  "use strict";
  var exportMode = new URLSearchParams(location.search).has("export");
  var configs = JSON.parse(document.getElementById("deck-charts").textContent || "{}");
  var charts = [];
  var api = window.deckCharts = { ready: false, charts: charts };
  var LOGO_W = 64, LOGO_H = 30;

  function c(v) { return am5.color(v); }

  function rootFor(el, cfg) {
    var root = am5.Root.new(el);
    var theme = am5.Theme.new(root);
    theme.rule("Label").setAll({ fontFamily: "'" + cfg.font + "', Arial, sans-serif", fill: c(cfg.text), fontSize: 20 });
    root.setThemes(exportMode ? [theme] : [am5themes_Animated.new(root), theme]);
    root.numberFormatter.set("numberFormat", cfg.unit === "percent" ? "#.0'%'" : "#,###.#");
    return root;
  }

  function tooltip(root, cfg) {
    var t = am5.Tooltip.new(root, { getFillFromSprite: false, autoTextColor: false });
    t.get("background").setAll({ fill: c("#FFFFFF"), fillOpacity: 0.97, stroke: c(cfg.primary), strokeWidth: 1.5 });
    t.label.setAll({ fill: c(cfg.text), fontSize: 18 });
    return t;
  }

  function hide(renderer) {
    renderer.grid.template.set("forceHidden", true);
    renderer.labels.template.set("forceHidden", true);
  }

  // a label's logo (or initial), sized like the SVG chart's: within 64x30, on its dark chip when the logo is white
  function mark(root, d) {
    var size = d.size || [LOGO_W, LOGO_H];
    var box = am5.Container.new(root, { width: LOGO_W + 4, height: LOGO_H + 4, centerY: am5.p50, centerX: am5.p100, dx: -8 });
    if (d.chip) box.set("background", am5.RoundedRectangle.new(root, { fill: c(d.chip), cornerRadiusTL: 6, cornerRadiusTR: 6, cornerRadiusBL: 6, cornerRadiusBR: 6 }));
    box.children.push(am5.Picture.new(root, { src: d.logo, width: size[0], height: size[1], centerX: am5.p50, centerY: am5.p50, x: am5.p50, y: am5.p50 }));
    return box;
  }

  function categoryAxis(root, chart, cfg, horizontal) {
    var marked = cfg.data.some(function (d) { return d.logo; });
    var r = horizontal ? am5xy.AxisRendererY.new(root, { inversed: true, minGridDistance: 10, cellStartLocation: 0.16, cellEndLocation: 0.84 })
                       : am5xy.AxisRendererX.new(root, { minGridDistance: 40, cellStartLocation: 0.18, cellEndLocation: 0.82 });
    r.grid.template.set("forceHidden", true);
    r.labels.template.setAll(horizontal
      ? { fontSize: 22, paddingRight: marked ? LOGO_W + 22 : 10, maxWidth: 300, oversizedBehavior: "truncate", ellipsis: "…" }
      : { fontSize: 18, fill: c(cfg.muted), oversizedBehavior: "truncate", ellipsis: "…" });
    var axis = (horizontal ? chart.yAxes : chart.xAxes).push(am5xy.CategoryAxis.new(root, {
      categoryField: "category", renderer: r,
      bullet: marked ? function (root, axis, dataItem) {
        return am5xy.AxisBullet.new(root, { location: 0.5, sprite: mark(root, dataItem.dataContext) });
      } : undefined
    }));
    if (!horizontal) axis.onPrivate("cellWidth", function (w) { r.labels.template.set("maxWidth", w - 8); });
    axis.data.setAll(cfg.data);
    return axis;
  }

  function valueLabel(root, series, text, horizontal, fill) {
    series.bullets.push(function () {
      return am5.Bullet.new(root, {
        locationX: horizontal ? 1 : 0.5, locationY: horizontal ? 0.5 : 1,
        sprite: am5.Label.new(root, horizontal
          ? { text: text, centerY: am5.p50, dx: 10, fontSize: 21, fontWeight: "700", populateText: true }
          : { text: text, centerX: am5.p50, centerY: am5.p100, dy: -6, fontSize: 21, fontWeight: "700", populateText: true, fill: fill })
      });
    });
  }

  function columns(root, cfg, horizontal) {
    var chart = root.container.children.push(am5xy.XYChart.new(root, { panX: false, panY: false, paddingLeft: 0, paddingRight: horizontal ? 40 : 10 }));
    var cat = categoryAxis(root, chart, cfg, horizontal);
    var vr = horizontal ? am5xy.AxisRendererX.new(root, {}) : am5xy.AxisRendererY.new(root, {});
    hide(vr);
    var val = (horizontal ? chart.xAxes : chart.yAxes).push(am5xy.ValueAxis.new(root, { min: 0, extraMax: 0.12, renderer: vr }));
    var series = chart.series.push(am5xy.ColumnSeries.new(root, horizontal
      ? { xAxis: val, yAxis: cat, valueXField: "value", categoryYField: "category", maskBullets: false, tooltip: tooltip(root, cfg) }
      : { xAxis: cat, yAxis: val, valueYField: "value", categoryXField: "category", maskBullets: false, tooltip: tooltip(root, cfg) }));
    series.columns.template.setAll({
      templateField: "col", strokeOpacity: 0, cursorOverStyle: "pointer",
      tooltipText: horizontal ? "{categoryY}: [bold]{valueX}[/]" : "{categoryX}: [bold]{valueY}[/]",
      cornerRadiusTR: 4, cornerRadiusBR: horizontal ? 4 : 0, cornerRadiusTL: horizontal ? 0 : 4, cornerRadiusBL: 0
    });
    series.columns.template.states.create("hover", { fillOpacity: 1, fill: c(cfg.primary) });
    valueLabel(root, series, horizontal ? "{valueX}" : "{valueY}", horizontal, c(cfg.text));
    series.data.setAll(cfg.data.map(function (d) {
      return Object.assign({}, d, { col: { fill: c(d.color), fillOpacity: d.opacity === undefined ? (horizontal ? 1 : (d.peak ? 1 : 0.75)) : d.opacity } });
    }));
    return [chart, series];
  }

  function line(root, cfg) {
    var chart = root.container.children.push(am5xy.XYChart.new(root, { panX: false, panY: false, paddingLeft: 10, paddingTop: 40 }));
    var xr = am5xy.AxisRendererX.new(root, { minGridDistance: 70 });
    xr.grid.template.set("forceHidden", true);
    xr.labels.template.setAll({ fontSize: 18, fill: c(cfg.muted) });
    var x = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: xr }));
    x.data.setAll(cfg.data);
    var yr = am5xy.AxisRendererY.new(root, {});
    hide(yr);
    var y = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, extraMax: 0.15, renderer: yr }));
    var series = chart.series.push(am5xy.LineSeries.new(root, {
      xAxis: x, yAxis: y, valueYField: "value", categoryXField: "category", stroke: c(cfg.accent), fill: c(cfg.accent),
      tooltip: tooltip(root, cfg)
    }));
    series.set("tooltipText", "{categoryX}: [bold]{valueY}[/] " + (cfg.label || "").toLowerCase());
    series.strokes.template.setAll({ strokeWidth: 4 });
    series.fills.template.setAll({ visible: true, fillOpacity: 0.12 });
    // the peaks: a dot in the brand colour with its value above, as in the SVG chart
    series.bullets.push(function (root, s, dataItem) {
      if (!dataItem.dataContext.peak) return undefined;
      return am5.Bullet.new(root, { sprite: am5.Circle.new(root, { radius: 8, fill: c(cfg.primary) }) });
    });
    series.bullets.push(function (root, s, dataItem) {
      if (!dataItem.dataContext.peak) return undefined;
      return am5.Bullet.new(root, { sprite: am5.Label.new(root, { text: "{valueY}", populateText: true, centerX: am5.p50, centerY: am5.p100, dy: -12, fontSize: 21, fontWeight: "700", fill: c(cfg.primary) }) });
    });
    series.data.setAll(cfg.data);
    if (!exportMode) {
      var cursor = chart.set("cursor", am5xy.XYCursor.new(root, { behavior: "none", xAxis: x }));
      cursor.lineY.set("visible", false);
    }
    return [chart, series];
  }

  function doughnut(root, cfg) {
    var chart = root.container.children.push(am5percent.PieChart.new(root, { layout: root.horizontalLayout, innerRadius: am5.percent(58) }));
    var series = chart.series.push(am5percent.PieSeries.new(root, { valueField: "value", categoryField: "category", tooltip: tooltip(root, cfg) }));
    series.slices.template.setAll({ templateField: "col", strokeOpacity: 0, tooltipText: "{category}: [bold]{value}[/]", cursorOverStyle: "pointer" });
    series.labels.template.set("forceHidden", true);
    series.ticks.template.set("forceHidden", true);
    series.data.setAll(cfg.data.map(function (d) { return Object.assign({}, d, { col: { fill: c(d.color) } }); }));
    // the legend at the side, as in the SVG chart; a click on an entry hides or shows its slice
    var legend = chart.children.push(am5.Legend.new(root, { centerY: am5.p50, y: am5.p50, layout: root.verticalLayout, marginLeft: 20 }));
    legend.labels.template.setAll({ fontSize: 22, fill: c(cfg.text) });
    legend.valueLabels.template.setAll({ text: "{value}", fontSize: 22, fill: c(cfg.text), fontWeight: "700", width: 110, textAlign: "left" });
    legend.markers.template.setAll({ width: 18, height: 18 });
    legend.data.setAll(series.dataItems);
    return [chart, series];
  }

  function treemap(root, cfg) {
    var series = root.container.children.push(am5hierarchy.Treemap.new(root, {
      valueField: "value", categoryField: "category", childDataField: "children", downDepth: 1, initialDepth: 1, topDepth: 1,
      nodePaddingOuter: 0, nodePaddingInner: 4, tooltip: tooltip(root, cfg)
    }));
    series.set("colors", am5.ColorSet.new(root, { colors: cfg.data.map(function (d) { return c(d.color); }) }));
    series.rectangles.template.setAll({ cornerRadiusTL: 6, cornerRadiusTR: 6, cornerRadiusBL: 6, cornerRadiusBR: 6, strokeOpacity: 0, tooltipText: "{category}: [bold]{sum}[/]" });
    series.labels.template.setAll({ text: "[fontWeight:600]{category}[/]\n{sum}", fontSize: 21, oversizedBehavior: "truncate", templateField: "ink" });
    series.data.setAll([{ category: "All", children: cfg.data.map(function (d) { return Object.assign({}, d, { ink: { fill: c(d.ink) } }); }) }]);
    series.set("selectedDataItem", series.dataItems[0]);
    return [series, series];
  }

  function stacked(root, cfg) {
    var chart = root.container.children.push(am5xy.XYChart.new(root, { panX: false, panY: false, paddingLeft: 0, layout: root.verticalLayout }));
    var legend = chart.children.push(am5.Legend.new(root, { x: am5.p100, centerX: am5.p100, marginBottom: 6 }));
    legend.labels.template.setAll({ fontSize: 20 });
    legend.valueLabels.template.set("forceHidden", true);
    var y = categoryAxis(root, chart, cfg, true);
    var xr = am5xy.AxisRendererX.new(root, {});
    hide(xr);
    var x = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, max: 100, strictMinMax: true, calculateTotals: true, renderer: xr }));
    var all = [];
    cfg.stacks.forEach(function (s, i) {
      var series = chart.series.push(am5xy.ColumnSeries.new(root, {
        name: s.name, stacked: true, xAxis: x, yAxis: y, valueXField: s.field, valueXShow: "valueXTotalPercent",
        categoryYField: "category", fill: c(s.color), stroke: c(s.color), tooltip: tooltip(root, cfg)
      }));
      series.columns.template.setAll({ tooltipText: "{categoryY}, {name}: [bold]{valueXTotalPercent.formatNumber('#.0')}%[/]", strokeOpacity: 0 });
      series.bullets.push(function () {
        return am5.Bullet.new(root, { locationX: 0.5, sprite: am5.Label.new(root, {
          text: "{valueXTotalPercent.formatNumber('#.0')}%", populateText: true, centerX: am5.p50, centerY: am5.p50,
          fontSize: 18, fontWeight: "600", fill: c(cfg.ink[i]) }) });
      });
      // a number only where it fits inside its segment, as in the SVG chart
      series.columns.template.onPrivate("width", function (w, target) {
        (target.dataItem.bullets || []).forEach(function (b) { b.get("sprite").set("forceHidden", w < 64); });
      });
      series.data.setAll(cfg.data);
      legend.data.push(series);
      all.push(series);
    });
    return [chart, all];
  }

  function usMap(root, cfg) {
    var chart = root.container.children.push(am5map.MapChart.new(root, {
      projection: am5map.geoAlbersUsa(), panX: "none", panY: "none", wheelX: "none", wheelY: "none", layout: root.horizontalLayout
    }));
    var low = am5.Color.lighten(c(cfg.color), 0.8), high = c(cfg.color);
    function polygons(geo, extra) {
      var s = chart.series.push(am5map.MapPolygonSeries.new(root, Object.assign({ geoJSON: geo, valueField: "value", calculateAggregates: true, tooltip: tooltip(root, cfg) }, extra)));
      s.mapPolygons.template.setAll({ tooltipText: "{name}: [bold]{value}[/] articles", fill: c("#E4E4EA"), stroke: c("#FFFFFF"), strokeWidth: 0.8, interactive: true });
      s.mapPolygons.template.adapters.add("tooltipText", function (text, target) {
        return target.dataItem && target.dataItem.get("value") != null ? text : "{name}: no articles";
      });
      s.mapPolygons.template.states.create("hover", { fill: c(cfg.primary) });
      s.set("heatRules", [{ target: s.mapPolygons.template, dataField: "value", min: low, max: high, key: "fill" }]);
      return s;
    }
    var states = polygons(am5geodata_usaLow, {});
    states.data.setAll(cfg.states);
    var legend = chart.children.push(am5.HeatLegend.new(root, { orientation: "vertical", startColor: low, endColor: high, startText: "Fewer", endText: "More", stepCount: 5, y: am5.p50, centerY: am5.p50 }));
    legend.startLabel.setAll({ fontSize: 16, fill: c(cfg.muted) });
    legend.endLabel.setAll({ fontSize: 16, fill: c(cfg.muted) });
    states.events.on("datavalidated", function () {
      legend.set("startValue", states.getPrivate("valueLow"));
      legend.set("endValue", states.getPrivate("valueHigh"));
    });
    if (exportMode) return [chart, states];
    // a click on a state zooms to it and shows its counties; the house button goes back to the states
    var counties = polygons(am5geodata_usaCountiesLow, { visible: false, include: [] });
    counties.data.setAll(cfg.counties);
    var hint = chart.children.push(am5.Label.new(root, { text: "Click a state to see its counties", fontSize: 16, fill: c(cfg.muted), x: 0, y: am5.p100, centerY: am5.p100, isMeasured: false }));
    var back = chart.children.push(am5.Button.new(root, {
      x: 0, y: 0, visible: false, isMeasured: false, paddingTop: 10, paddingBottom: 10, interactiveChildren: false,
      icon: am5.Graphics.new(root, { svgPath: "M16,8 L14,8 L14,16 L10,16 L10,10 L6,10 L6,16 L2,16 L2,8 L0,8 L8,0 L16,8 Z M16,8", fill: c("#FFFFFF") })
    }));
    back.get("background").setAll({ fill: c(cfg.primary) });
    states.mapPolygons.template.events.on("click", function (ev) {
      var code = String(ev.target.dataItem.get("id")).slice(3);
      counties.set("include", am5geodata_usaCountiesLow.features
        .filter(function (f) { return f.properties.STATE === code; })
        .map(function (f) { return f.id || f.properties.id; }));
      states.zoomToDataItem(ev.target.dataItem);
      states.hide();
      counties.show();
      back.show();
      hint.hide();
    });
    back.events.on("click", function () {
      chart.goHome();
      states.show();
      counties.hide();
      back.hide();
      hint.show();
    });
    api.drill = api.drill || [];
    api.drill.push(function (stateId) {      // for checks and screenshots: drill into a state by id ("US-NY")
      var di = states.getDataItemById(stateId);
      if (di) states.mapPolygons.template.events.dispatch("click", { type: "click", target: di.get("mapPolygon") });
    });
    return [chart, states];
  }

  var BUILD = { bar: function (r, f) { return columns(r, f, true); }, column: function (r, f) { return columns(r, f, false); },
                line_peaks: line, doughnut: doughnut, treemap: treemap, stacked: stacked, us_map: usMap };

  function animate(made) {
    if (exportMode) return;
    [].concat(made[1]).forEach(function (s) { s.appear(900, 100); });
    if (made[0].appear && made[0] !== made[1]) made[0].appear(900, 100);
  }

  // logos keep their aspect ratio inside the 64x30 box (amCharts stretches a picture given both sizes)
  function sized(cfg) {
    var rows = (cfg.data || []).filter(function (d) { return d.logo; });
    return Promise.all(rows.map(function (d) {
      return new Promise(function (done) {
        var img = new Image();
        img.onload = function () {
          var k = Math.min(LOGO_W / (img.naturalWidth || LOGO_W), LOGO_H / (img.naturalHeight || LOGO_H));
          d.size = [Math.round((img.naturalWidth || LOGO_W) * k), Math.round((img.naturalHeight || LOGO_H) * k)];
          done();
        };
        img.onerror = function () { done(); };
        img.src = d.logo;
      });
    }));
  }

  function draw(svg, cfg) {
    var el = document.createElement("div");
    el.className = "amchart";
    var vb = svg.viewBox && svg.viewBox.baseVal;
    if (vb && vb.width) el.style.aspectRatio = vb.width + " / " + vb.height;   // sized as the SVG it stands in for
    svg.parentNode.insertBefore(el, svg);
    try {
      var root = rootFor(el, cfg);
      var made = BUILD[cfg.kind](root, cfg);
      animate(made);
      svg.style.display = "none";
      el.dataset.chartIndex = String(charts.length);
      charts.push({ root: root, cfg: cfg, el: el });
      return new Promise(function (done) {
        root.events.once("frameended", function () { el.dataset.ready = "1"; done(); });
        setTimeout(done, 8000);       // a chart on a hidden slide draws when shown: never hold the deck for it
      });
    } catch (e) {                     // the SVG chart stays: same data, same colours
      if (window.console) console.warn("amCharts chart not drawn, SVG fallback kept:", e);
      el.remove();
      svg.style.display = "";
      return Promise.resolve();
    }
  }

  api.svg = function (i) {
    var ch = charts[i];
    return am5.renderToSVG(ch.root, { idPrefix: "c" + i + "-", title: ch.cfg.reason || ch.cfg.label || "Chart" });
  };

  // each drawn chart swapped for its SVG export (the PDF prints vector charts, exactly as drawn)
  api.freeze = function () {
    charts.forEach(function (ch, i) {
      if (!ch.el.dataset.ready) return;
      var box = document.createElement("div");
      box.className = "amchart-svg";
      box.style.width = ch.el.offsetWidth + "px";
      box.style.height = ch.el.offsetHeight + "px";
      box.innerHTML = api.svg(i);
      ch.el.parentNode.insertBefore(box, ch.el);
      ch.el.style.display = "none";
    });
  };

  function start() {
    var pending = [];
    document.querySelectorAll("section.slide").forEach(function (section) {
      var list = configs[section.getAttribute("data-id")];
      if (!list) return;
      section.querySelectorAll("svg.chart").forEach(function (svg, k) {
        if (list[k]) pending.push(sized(list[k]).then(function () { return draw(svg, list[k]); }));
      });
    });
    // the first frame lays the chart out; the next ones draw its labels and bullets
    Promise.all(pending).then(function () { setTimeout(function () { api.ready = true; }, 600); });
  }

  if (typeof am5 === "undefined") { api.ready = true; return; }
  start();
})();
