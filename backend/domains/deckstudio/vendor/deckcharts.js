// Draws the deck's charts with amCharts 5 from the configs in #deck-charts (built by deckstudio/amcharts.py), in place
// of each slide's SVG chart, which stays as the fallback when amCharts can not draw. In export mode (?export=1) the
// charts are drawn without animation, and window.deckCharts hands each one to the exporter as SVG.
(function () {
  "use strict";
  var exportMode = new URLSearchParams(location.search).has("export");
  var configs = JSON.parse(document.getElementById("deck-charts").textContent || "{}");
  var charts = [];
  var api = window.deckCharts = { ready: false, charts: charts, configs: configs };
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
    var y = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, extraMax: 0.25, renderer: yr }));   // room for the peak's value
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
    zoomable(root, chart, x, cfg.data.length);
    return [chart, series];
  }

  // a trend is live: drag across it to zoom into those periods (amCharts' own zoom-out button returns), and a long
  // one gets a scrollbar to pan; the wheel stays the deck's, it turns the slides. Export draws the whole range.
  var ZOOM_SCROLLBAR_POINTS = 12;
  function zoomable(root, chart, x, points) {
    if (exportMode) return;
    var cursor = chart.set("cursor", am5xy.XYCursor.new(root, { behavior: "zoomX", xAxis: x }));
    cursor.lineY.set("forceHidden", true);
    if (points > ZOOM_SCROLLBAR_POINTS) chart.set("scrollbarX", am5.Scrollbar.new(root, { orientation: "horizontal", opposite: true }));
  }

  // each legend entry's logo beside its name, its name in its colour (as amCharts' images-as-markers)
  function legendLogos(root, legend, items) {
    legend.dataItems.forEach(function (di, i) {
      var it = items[i];
      if (!it || !it.logo) return;
      var size = it.size || [LOGO_W, LOGO_H];
      di.get("marker").setAll({ width: size[0], height: size[1] });
      if (it.chip) di.get("marker").set("background", am5.RoundedRectangle.new(root, { fill: c(it.chip), cornerRadiusTL: 4, cornerRadiusTR: 4, cornerRadiusBL: 4, cornerRadiusBR: 4 }));
      di.get("marker").children.push(am5.Picture.new(root, { src: it.logo, width: size[0], height: size[1], centerY: am5.p50, y: am5.p50 }));
      di.get("markerRectangle").set("forceHidden", true);
      di.get("label").set("fill", c(it.color));
    });
  }

  // one line per brand (as amCharts' multiple line series demo): the client's line thicker with its peaks marked,
  // a dot per point that lists that brand's articles for that period, the brands' logos in the legend
  function multiLine(root, cfg) {
    var chart = root.container.children.push(am5xy.XYChart.new(root, { panX: false, panY: false, paddingLeft: 10, paddingTop: 20, layout: root.verticalLayout }));
    var legend = chart.children.unshift(am5.Legend.new(root, { x: am5.p50, centerX: am5.p50, marginBottom: 10 }));
    legend.labels.template.setAll({ fontSize: 20, fill: c(cfg.text) });
    legend.valueLabels.template.set("forceHidden", true);
    var xr = am5xy.AxisRendererX.new(root, { minGridDistance: 70 });
    xr.grid.template.set("forceHidden", true);
    xr.labels.template.setAll({ fontSize: 18, fill: c(cfg.muted) });
    var x = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "category", renderer: xr }));
    x.data.setAll(cfg.data);
    var yr = am5xy.AxisRendererY.new(root, {});
    yr.grid.template.setAll({ strokeOpacity: 0.08 });
    yr.labels.template.setAll({ fontSize: 16, fill: c(cfg.muted) });
    var y = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, extraMax: 0.2, renderer: yr }));
    var all = cfg.lines.map(function (ln) {
      var s = chart.series.push(am5xy.LineSeries.new(root, {
        name: ln.name, xAxis: x, yAxis: y, valueYField: ln.field, categoryXField: "category",
        stroke: c(ln.color), fill: c(ln.color), tooltip: tooltip(root, cfg)
      }));
      s.get("tooltip").label.set("text", "{name}, {categoryX}: [bold]{valueY}[/] " + (cfg.label || "").toLowerCase());
      s.strokes.template.setAll({ strokeWidth: ln.client ? 5 : 3 });
      s.bullets.push(function (root, series, dataItem) {
        var dot = am5.Circle.new(root, { radius: ln.client ? 6 : 4, fill: c(ln.color), stroke: c("#FFFFFF"), strokeWidth: 1.5,
                                         cursorOverStyle: cfg.drill && !exportMode ? "pointer" : "default" });
        dot.events.on("click", function () { cfg.pick(ln.name + "\t" + dataItem.dataContext.category, ln.name + " · " + dataItem.dataContext.category); });
        return am5.Bullet.new(root, { sprite: dot });
      });
      if (ln.client) s.bullets.push(function (root, series, dataItem) {   // the client's peaks, valued as in the single line
        if (!dataItem.dataContext[ln.peak]) return undefined;
        return am5.Bullet.new(root, { sprite: am5.Label.new(root, { text: "{" + ln.field + "}", populateText: true, centerX: am5.p50, centerY: am5.p100, dy: -10, fontSize: 20, fontWeight: "700", fill: c(ln.color) }) });
      });
      s.data.setAll(cfg.data);
      return s;
    });
    legend.data.setAll(chart.series.values);
    legendLogos(root, legend, cfg.lines);
    zoomable(root, chart, x, cfg.data.length);
    return [chart, all];
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
    legendLogos(root, legend, cfg.stacks);
    return [chart, all];
  }

  function usMap(root, cfg) {
    var chart = root.container.children.push(am5map.MapChart.new(root, {
      // the wheel turns the deck's slides, so it never zooms the map; drag still pans a drilled-in state
      projection: am5map.geoAlbersUsa(), panX: "translateX", panY: "translateY", wheelX: "none", wheelY: "none",
      layout: root.horizontalLayout, paddingTop: cfg.note ? 56 : 0      // room for the note on what is not mapped
    }));
    var low = am5.Color.lighten(c(cfg.color), 0.8), high = c(cfg.color);
    function polygons(geo, extra) {
      var s = chart.series.push(am5map.MapPolygonSeries.new(root, Object.assign({ geoJSON: geo, valueField: "value", calculateAggregates: true, tooltip: tooltip(root, cfg) }, extra)));
      s.mapPolygons.template.setAll({ tooltipText: "{name}: [bold]{value}[/] articles", fill: c("#E4E4EA"), stroke: c("#FFFFFF"), strokeWidth: 0.8, interactive: true });
      // the total, then one line per channel it ran on: "California: 23 articles\nFacebook 8\nX 5\nNews 7"
      s.mapPolygons.template.adapters.add("tooltipText", function (text, target) {
        var di = target.dataItem;
        if (!di || di.get("value") == null) return "{name}: no articles";
        var channels = (di.dataContext || {}).channels;
        return channels ? text + "\n" + String(channels).split(" · ").join("\n") : text;
      });
      // a click on a state or county also lists its articles
      s.mapPolygons.template.events.on("click", function (ev) {
        var d = ev.target.dataItem && ev.target.dataItem.dataContext;
        if (d && d.value != null && cfg.pick) cfg.pick(d.id, d.name);
      });
      // hover outlines the area: a fill would read as "most articles" on this scale
      s.mapPolygons.template.states.create("hover", { stroke: c(cfg.text), strokeWidth: 2.5 });
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
    // what the map leaves out, on the map (exported with it): posts with no location, by channel
    if (cfg.note) root.container.children.push(am5.Label.new(root, { text: cfg.note, fontSize: 16, fill: c(cfg.muted),
      x: am5.p50, centerX: am5.p50, y: 0, maxWidth: 900, oversizedBehavior: "wrap", textAlign: "center" }));
    if (exportMode) return [chart, states];
    // a click on a state zooms to it and shows its counties; the house button goes back to the states
    var counties = null;     // made on the first drill: an empty series makes the map's bounds NaN and zooming blanks it
    var hint = root.container.children.push(am5.Label.new(root, { text: "Click a state to see its counties", fontSize: 16, fill: c(cfg.muted), x: 70, y: am5.p100, centerY: am5.p100 }));
    var back = root.container.children.push(am5.Button.new(root, {
      x: 0, y: 0, visible: false, paddingTop: 10, paddingBottom: 10, interactiveChildren: false,
      icon: am5.Graphics.new(root, { svgPath: "M16,8 L14,8 L14,16 L10,16 L10,10 L6,10 L6,16 L2,16 L2,8 L0,8 L8,0 L16,8 Z M16,8", fill: c("#FFFFFF") })
    }));
    back.get("background").setAll({ fill: c(cfg.primary) });
    // as amCharts' drill-down congressional map: zoom to the state, then swap the states for its counties (the
    // state's part of the bundled county map, so it works offline)
    function drillTo(dataItem) {
      var code = String(dataItem.get("id")).slice(3);
      hint.hide();
      states.zoomToDataItem(dataItem).waitForStop().then(function () {
        var geo = { type: "FeatureCollection", features: am5geodata_usaCountiesLow.features
          .filter(function (f) { return f.properties.STATE === code; }) };
        // affectsBounds false: the map stays fitted to the states, so the zoom to the state frames its counties
        if (counties) counties.set("geoJSON", geo);
        else counties = polygons(geo, { visible: false, affectsBounds: false });
        counties.data.setAll(cfg.counties.filter(function (k) { return k.state === "US-" + code; }));
        counties.show();
        states.hide(100);
        back.show();
      });
    }
    states.mapPolygons.template.events.on("click", function (ev) { drillTo(ev.target.dataItem); });
    back.events.on("click", function () {
      chart.goHome();
      states.show();
      if (counties) counties.hide();
      back.hide();
      hint.show();
    });
    return [chart, states];
  }

  // themes as packed bubbles: size = articles, colour = the theme's net sentiment (as amCharts' packed circles demo)
  function bubble(root, cfg) {
    var series = root.container.children.push(am5hierarchy.Pack.new(root, {
      valueField: "value", categoryField: "category", childDataField: "children", topDepth: 1, initialDepth: 1,
      nodePadding: 6, tooltip: tooltip(root, cfg)
    }));
    series.set("colors", am5.ColorSet.new(root, { colors: cfg.data.map(function (d) { return c(d.color); }) }));
    series.circles.template.setAll({ strokeOpacity: 0, fillOpacity: 0.92, cursorOverStyle: "pointer",
      tooltipText: cfg.toned ? "{category}: [bold]{sum}[/] articles, net sentiment {tone}" : "{category}: [bold]{sum}[/] articles" });
    series.labels.template.setAll({ text: "[fontWeight:600]{category}[/]\n{sum}", fontSize: 19, fill: c("#FFFFFF"),
      oversizedBehavior: "fit", textAlign: "center" });
    series.data.setAll([{ category: "All", children: cfg.data.map(function (d) {
      return Object.assign({}, d, { tone: d.tone == null ? "n/a" : (d.tone > 0 ? "+" : "") + d.tone });
    }) }]);
    if (cfg.toned) {                 // the colour key: what green, grey and red mean
      var key = root.container.children.push(am5.Label.new(root, { x: am5.p100, centerX: am5.p100, y: am5.p100, centerY: am5.p100,
        text: "[#2E7D32]●[/] mostly positive   [#8A8A99]●[/] mixed   [#C62828]●[/] mostly negative", fontSize: 16, fill: c(cfg.muted) }));
      key.toFront();
    }
    return [series, series];
  }

  // a breakdown with levels as amCharts' sunburst: the parts in the inner ring, what each is made of around it; a
  // click on a segment lists its articles (the built-in zoom stays off: the deck's wheel and clicks are its own)
  function sunburst(root, cfg) {
    var series = root.container.children.push(am5hierarchy.Sunburst.new(root, {
      valueField: "value", categoryField: "name", childDataField: "children", topDepth: 1, initialDepth: 2,
      downDepth: 2, innerRadius: am5.percent(22), tooltip: tooltip(root, cfg)
    }));
    series.slices.template.setAll({ templateField: "col", strokeOpacity: 1, stroke: c("#FFFFFF"), strokeWidth: 2,
      tooltipText: "{category}: [bold]{sum}[/] " + (cfg.label === "Source" ? "articles" : "") });
    series.nodes.template.setAll({ toggleKey: "none", cursorOverStyle: cfg.drill && !exportMode ? "pointer" : "default" });
    series.labels.template.setAll({ text: "{category}", fontSize: 16, fill: c("#FFFFFF"), oversizedBehavior: "truncate" });
    series.nodes.template.events.on("click", function (ev) {
      var d = ev.target.dataItem && ev.target.dataItem.dataContext;
      if (d && d.key) cfg.pick(d.key, String(d.key).replace("\t", " · "));
    });
    series.data.setAll(cfg.data);
    series.set("selectedDataItem", series.dataItems[0]);
    return [series, series];
  }

  // two dimensions crossed (as amCharts' heat map demo): each cell shaded by its share of the row's articles
  function heatmap(root, cfg) {
    var chart = root.container.children.push(am5xy.XYChart.new(root, { panX: false, panY: false, wheelX: "none", wheelY: "none", paddingLeft: 0, layout: root.verticalLayout }));
    var yr = am5xy.AxisRendererY.new(root, { inversed: true, minGridDistance: 10 });
    yr.grid.template.set("visible", false);
    yr.labels.template.setAll({ fontSize: 19, maxWidth: 260, oversizedBehavior: "truncate", ellipsis: "…" });
    var y = chart.yAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "row", renderer: yr }));
    var xr = am5xy.AxisRendererX.new(root, { opposite: true, minGridDistance: 10 });
    xr.grid.template.set("visible", false);
    xr.labels.template.setAll({ fontSize: 17, fill: c(cfg.muted), oversizedBehavior: "wrap", textAlign: "center" });
    xr.labels.template.adapters.add("maxWidth", function () { return Math.max(60, x.width() / Math.max(1, cfg.cols.length) - 8); });
    var x = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "col", renderer: xr }));
    var series = chart.series.push(am5xy.ColumnSeries.new(root, {
      calculateAggregates: true, clustered: false, stroke: c("#FFFFFF"), xAxis: x, yAxis: y,
      categoryXField: "col", categoryYField: "row", valueField: "value", tooltip: tooltip(root, cfg)
    }));
    series.columns.template.setAll({ tooltipText: "{categoryY}, {categoryX}: [bold]{value}%[/] ({count} articles)",
      strokeOpacity: 1, strokeWidth: 3, width: am5.percent(100), height: am5.percent(100), cursorOverStyle: "pointer" });
    series.set("heatRules", [{ target: series.columns.template, dataField: "value", min: c(cfg.low), max: c(cfg.primary), key: "fill" }]);
    series.bullets.push(function (root, s, dataItem) {
      var dark = dataItem.get("value") > 0.55 * (s.getPrivate("valueHigh") || 1);
      return am5.Bullet.new(root, { sprite: am5.Label.new(root, { text: "{value}%", populateText: true, centerX: am5.p50, centerY: am5.p50,
        fontSize: 18, fontWeight: "700", fill: c(dark ? "#FFFFFF" : cfg.text) }) });
    });
    series.data.setAll(cfg.cells);
    y.data.setAll(cfg.rows.map(function (r) { return { row: r }; }));
    x.data.setAll(cfg.cols.map(function (k) { return { col: k }; }));
    return [chart, series];
  }

  // a flow (brand -> award) as amCharts' Sankey: each band as wide as the articles that link the two
  function sankey(root, cfg) {
    var series = root.container.children.push(am5flow.Sankey.new(root, {
      sourceIdField: "from", targetIdField: "to", valueField: "value", nodeWidth: 18, nodePadding: 14,
      paddingLeft: 10, paddingRight: 220, tooltip: tooltip(root, cfg)
    }));
    // node ids are the names (a column named like a row gets a trailing space, so the two stay apart)
    function colId(k) { return cfg.rows.indexOf(k) >= 0 ? k + " " : k; }
    series.nodes.set("colors", am5.ColorSet.new(root, { colors: cfg.colors.map(function (k) { return c(k); }) }));
    series.nodes.data.setAll(cfg.rows.concat(cfg.cols.map(colId)).map(function (id) { return { id: id }; }));
    series.nodes.labels.template.setAll({ fontSize: 19, fill: c(cfg.text) });
    series.links.template.setAll({ fillStyle: "source", fillOpacity: 0.35, cursorOverStyle: "pointer",
      tooltipText: "{row} → {col}: [bold]{count}[/] articles" });
    series.data.setAll(cfg.cells.map(function (k) { return { from: k.row, to: colId(k.col), value: k.count, row: k.row, col: k.col, count: k.count }; }));
    return [series, series];
  }

  var BUILD = { bar: function (r, f) { return columns(r, f, true); }, column: function (r, f) { return columns(r, f, false); },
                line_peaks: line, doughnut: doughnut, treemap: treemap, stacked: stacked, us_map: usMap,
                bubble: bubble, heatmap: heatmap, sankey: sankey, multi_line: multiLine,
                sunburst: sunburst };

  // which part of each kind is clicked, and the key its articles are filed under (see renderer._drill_data)
  function pickable(made, cfg) {
    if (exportMode || !cfg.drill) return;
    // the list's template covers parts made later; parts made already (a hierarchy or flow builds them as its data
    // is set) get the handler themselves; one click opens one list either way
    function on(list, key) {
      function handle(ev) {
        var e = ev.originalEvent || {};
        if (e.deckPicked) return;
        e.deckPicked = true;
        var d = ev.target.dataItem && ev.target.dataItem.dataContext;
        if (d) cfg.pick.apply(null, key(d, ev.target));
      }
      list.template.setAll({ cursorOverStyle: "pointer" });
      list.template.events.on("click", handle);
      list.each(function (sprite) { sprite.set("cursorOverStyle", "pointer"); sprite.events.on("click", handle); });
    }
    var cat = function (d) { return [d.category, d.category]; };
    var s = made[1];
    if (cfg.kind === "bar" || cfg.kind === "column") on(s.columns, cat);
    else if (cfg.kind === "doughnut") on(s.slices, cat);
    else if (cfg.kind === "treemap") on(s.rectangles, cat);
    else if (cfg.kind === "bubble") on(s.nodes, cat);          // the node: its circle and its label
    else if (cfg.kind === "stacked") s.forEach(function (x) {
      on(x.columns, function (d) {
        var k = d.key + "\t" + x.get("name");
        return cfg.drill[k] ? [k, d.key + " · " + x.get("name")] : [d.key, d.key];
      });
    });
    else if (cfg.kind === "heatmap") on(s.columns, function (d) { return [d.row + "\t" + d.col, d.row + " · " + d.col]; });
    else if (cfg.kind === "sankey") {
      on(s.links, function (d) { return [d.row + "\t" + d.col, d.row + " → " + d.col]; });
      on(s.nodes.rectangles, function (d) { return [d.id, d.id]; });
    } else if (cfg.kind === "line_peaks") {
      // a line has no element per point: the click picks the category under the pointer
      var chart = made[0], x = chart.xAxes.getIndex(0);
      chart.plotContainer.setAll({ interactive: true, cursorOverStyle: "pointer" });
      chart.plotContainer.events.on("click", function (ev) {
        var p = chart.plotContainer.toLocal(ev.point);
        var i = x.axisPositionToIndex(x.toAxisPosition(p.x / chart.plotContainer.width()));
        var d = cfg.data[i];
        if (d) cfg.pick(d.category, d.category);
      });
    }
  }

  function animate(made) {
    if (exportMode) return;
    [].concat(made[1]).forEach(function (s) { s.appear(900, 100); });
    if (made[0].appear && made[0] !== made[1]) made[0].appear(900, 100);
  }

  // logos keep their aspect ratio inside the 64x30 box (amCharts stretches a picture given both sizes)
  function sized(cfg) {
    var rows = (cfg.data || []).concat(cfg.lines || [], cfg.stacks || []).filter(function (d) { return d.logo; });
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
    // why this chart: a small "i" in the chart's corner, its hover text the choice and what else was considered
    if (cfg.reason && !exportMode) {
      var why = document.createElement("span");
      why.className = "chart-why";
      why.textContent = "i";
      if (cfg.kind === "us_map") { why.style.right = "auto"; why.style.left = "4px"; }   // the heat legend is at the right
      why.title = "Why this chart: " + cfg.reason + (cfg.alternatives ? "\nAlso considered: " + cfg.alternatives : "");
      el.appendChild(why);
    }
    svg.parentNode.insertBefore(el, svg);
    try {
      var root = rootFor(el, cfg);
      cfg.pick = function (key, label) {          // a click on a chart element lists its articles (drill.js)
        if (!exportMode && window.deckDrill && cfg.drill) window.deckDrill.open(el.closest("section.slide"), cfg, String(key), label);
      };
      var made = BUILD[cfg.kind](root, cfg);
      pickable(made, cfg);
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
      if (ch.dead || !ch.el.dataset.ready) return;
      var box = document.createElement("div");
      box.className = "amchart-svg";
      box.style.width = ch.el.offsetWidth + "px";
      box.style.height = ch.el.offsetHeight + "px";
      box.innerHTML = api.svg(i);
      ch.el.parentNode.insertBefore(box, ch.el);
      ch.el.style.display = "none";
    });
  };

  // a slide's charts drawn again from new configs (the 24h dashboard after a Refresh); a slide not shown yet just
  // keeps the new configs for when it is
  api.redraw = function (slideId, list) {
    configs[slideId] = list;
    var section = document.querySelector('section.slide[data-id="' + slideId + '"]');
    if (!section || !section.dataset.chartsDrawn) return Promise.resolve();
    charts.forEach(function (ch) {
      if (!ch.dead && section.contains(ch.el)) { ch.root.dispose(); ch.el.remove(); ch.dead = true; }
    });
    return Promise.all([].map.call(section.querySelectorAll("svg.chart"), function (svg, k) {
      svg.style.display = "";
      return list[k] ? sized(list[k]).then(function () { return draw(svg, list[k]); }) : null;
    }));
  };

  function start() {
    var pending = [];
    function drawSlide(section) {
      var list = configs[section.getAttribute("data-id")];
      if (!list || section.dataset.chartsDrawn) return;
      section.dataset.chartsDrawn = "1";
      section.querySelectorAll("svg.chart").forEach(function (svg, k) {
        if (list[k]) pending.push(sized(list[k]).then(function () { return draw(svg, list[k]); }));
      });
    }
    // a chart is drawn when its slide is shown: one made in a hidden slide fits its map to a 0x0 box (zooming then
    // blanks it), and its entrance animation would play unseen
    document.querySelectorAll("section.slide").forEach(function (section) {
      if (exportMode || section.classList.contains("active")) drawSlide(section);
      else new MutationObserver(function (_, obs) {
        if (section.classList.contains("active")) { obs.disconnect(); drawSlide(section); }
      }).observe(section, { attributes: true, attributeFilter: ["class"] });
    });
    // the first frame lays the chart out; the next ones draw its labels and bullets
    Promise.all(pending).then(function () { setTimeout(function () { api.ready = true; }, 600); });
  }

  if (typeof am5 === "undefined") { api.ready = true; return; }
  start();
})();
