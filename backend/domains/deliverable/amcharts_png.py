"""Charts PowerPoint can not draw natively (treemap; the gauge lives in gauge.py) rendered with amCharts 5 to PNG."""
from __future__ import annotations

import json
from pathlib import Path

from . import style
from .gauge import _CDN, RENDER_TIMEOUT_MS, SETTLE_MS


def render_html_png(html: str, out_path: Path, width: int = 900, height: int = 560) -> Path:
    from playwright.sync_api import sync_playwright
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html, wait_until="networkidle", timeout=RENDER_TIMEOUT_MS)
        # Raises when amCharts never drew (CDN unreachable) instead of saving a blank picture
        page.wait_for_selector("body[data-ready='1']", state="attached", timeout=RENDER_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        page.screenshot(path=str(out_path))
        browser.close()
    return out_path


def treemap_html(categories: list[str], values: list[float], palette: list[str] | None = None) -> str:
    data = [{"name": c, "value": v} for c, v in zip(categories, values)]
    colors = ["#" + c for c in (palette or style.PALETTE)]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<script src="{_CDN}/index.js"></script><script src="{_CDN}/hierarchy.js"></script>
<style>html,body{{margin:0;background:#FFFFFF}}#c{{width:900px;height:560px}}</style></head>
<body><div id="c"></div><script>
const root = am5.Root.new("c");
const s = root.container.children.push(am5hierarchy.Treemap.new(root, {{
  downDepth: 1, initialDepth: 1, valueField: "value", categoryField: "name", childDataField: "children",
  nodePaddingOuter: 4, nodePaddingInner: 4}}));
s.set("colors", am5.ColorSet.new(root, {{colors: {json.dumps(colors)}.map(c => am5.color(c))}}));
s.labels.template.setAll({{fontSize: 16, fill: am5.color("#{style.BODY}"), text: "{{category}}: {{sum}}", oversizedBehavior: "wrap", textAlign: "center"}});
s.data.setAll([{{name: "root", children: {json.dumps(data).replace("</", "<\\/")}}}]);
s.set("selectedDataItem", s.dataItems[0]);
root.events.once("frameended", () => {{ document.body.dataset.ready = "1"; }});
</script></body></html>"""


def render_treemap_png(categories: list[str], values: list[float], out_path: Path,
                       palette: list[str] | None = None) -> Path:
    return render_html_png(treemap_html(categories, values, palette), out_path)
