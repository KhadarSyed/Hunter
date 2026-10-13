"""amCharts 5 gauge rendered locally to PNG (native PPTX charts can't draw a gauge)."""
from __future__ import annotations

import json
from pathlib import Path

from . import style

RENDER_TIMEOUT_MS = 20000
SETTLE_MS = 800
AMCHARTS_VERSION = "5.20.8"   # pinned: the unversioned /lib/5/ path changes underneath us
_CDN = f"https://cdn.amcharts.com/lib/version/{AMCHARTS_VERSION}"


def gauge_html(value: float, label: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<script src="{_CDN}/index.js"></script>
<script src="{_CDN}/xy.js"></script>
<script src="{_CDN}/radar.js"></script>
<style>html,body{{margin:0;background:#FFFFFF}}#c{{width:900px;height:560px}}</style></head>
<body><div id="c"></div><script>
const root = am5.Root.new("c");
const chart = root.container.children.push(am5radar.RadarChart.new(root, {{startAngle:180, endAngle:360, innerRadius:-28}}));
const axis = chart.xAxes.push(am5xy.ValueAxis.new(root, {{min:0, max:100, strictMinMax:true,
  renderer: am5radar.AxisRendererCircular.new(root, {{strokeOpacity:0}})}}));
axis.get("renderer").labels.template.setAll({{fontSize:18, fill:am5.color(0x{style.BODY})}});
const band = axis.createAxisRange(axis.makeDataItem({{value:0, endValue:100}}));
band.get("axisFill").setAll({{visible:true, fill:am5.color(0x{style.FOOTER_BAND}), fillOpacity:1}});
const fill = axis.createAxisRange(axis.makeDataItem({{value:0, endValue:{json.dumps(value)}}}));
fill.get("axisFill").setAll({{visible:true, fill:am5.color(0x{style.VIOLET}), fillOpacity:1}});
chart.radarContainer.children.push(am5.Label.new(root, {{text:"{value:g}%", fontSize:64, fontWeight:"700",
  fill:am5.color(0x{style.VIOLET}), centerX:am5.p50, centerY:am5.p100}}));
chart.children.push(am5.Label.new(root, {{text:{json.dumps(label)}, fontSize:22, fill:am5.color(0x{style.BODY}),
  x:am5.p50, centerX:am5.p50, y:am5.percent(88)}}));
root.events.once("frameended", () => {{ document.body.dataset.ready = "1"; }});
</script></body></html>"""


def render_gauge_png(value: float, label: str, out_path: Path) -> Path:
    from playwright.sync_api import sync_playwright
    out_path = Path(out_path)
    html_path = out_path.with_suffix(".html")
    html_path.write_text(gauge_html(value, label), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 560}, device_scale_factor=2)
        page.goto(html_path.as_uri())
        page.wait_for_selector("body[data-ready='1']", state="attached", timeout=RENDER_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        page.locator("#c").screenshot(path=str(out_path))
        browser.close()
    return out_path
