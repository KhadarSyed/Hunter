"""The browser QA agent: walks a project's main pages with Playwright, checks what a person would notice (faded pages,
unreadable text, overflowing content, internal codes, console errors, failed requests, wrong counts) and files each
finding as an issue."""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from ...core import config, store
from ...core.auth import SESSION_COOKIE_NAME

logger = logging.getLogger(__name__)
WALK = ("landing", "projects", "dashboard", "background-research", "search-strategy", "data-sources", "deliverables")
FADE_SAMPLE_MS = 150
FADED_BELOW = 0.6
SETTLE_MS = 1500
NAV_TIMEOUT_MS = 30000
_EMPTY_ACTIVITY = ("no activity", "no recent")


@dataclass(frozen=True)
class Finding:
    page: str
    kind: str
    detail: str
    screenshot: str | None = None


GENERIC_CHECKS_JS = r"""() => {
  const out = [];
  const lum = c => { const m = c.match(/[\d.]+/g); if (!m) return null; const [r, g, b] = m.slice(0, 3).map(Number)
    .map(v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    return [.2126 * r + .7152 * g + .0722 * b, m[3]]; };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
    if (s.backgroundImage !== 'none') return null; const m = s.backgroundColor.match(/[\d.]+/g);
    if (m && (m.length < 4 || Number(m[3]) > .5)) return s.backgroundColor; } return 'rgb(255,255,255)'; };
  const root = document.getElementById('root') || document.body;
  const seen = new Set();
  for (const el of root.querySelectorAll('*')) {
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    const r = el.getBoundingClientRect();
    if (!own || r.width === 0 || r.height === 0) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || Number(s.opacity) === 0) continue;
    const text = el.innerText.trim();
    if (/\bRQ\d+\b/.test(text) && !/\bRQ\d+\b\s*[:"“-]?\s*["“]?\s*\w+.*\?/.test(text) && !seen.has('code')) {
      seen.add('code'); out.push({kind: 'internal_code', detail: text.slice(0, 120)}); }
    const bg = bgOf(el); const f = lum(s.color); const b = bg && lum(bg);
    if (f && b && (f[1] === undefined || Number(f[1]) > .5)) {
      const ratio = (Math.max(f[0], b[0]) + .05) / (Math.min(f[0], b[0]) + .05);
      const big = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && Number(s.fontWeight) >= 700);
      const key = 'contrast:' + text.slice(0, 30);
      if (ratio < (big ? 3 : 4.5) && !seen.has(key)) {
        seen.add(key); out.push({kind: 'low_contrast', detail: `${ratio.toFixed(2)}:1 "${text.slice(0, 60)}"`}); }
    }
  }
  if (document.documentElement.scrollWidth > innerWidth + 2)
    out.push({kind: 'overflow_x', detail: `${document.documentElement.scrollWidth}px wide in a ${innerWidth}px window`});
  return out;
}"""
FADE_JS = """() => { const r = document.getElementById('root') || document.body; let min = 1;
  for (let e = r.firstElementChild || r; e; e = e.firstElementChild) {
    min = Math.min(min, Number(getComputedStyle(e).opacity)); if (e.children.length !== 1) break; } return min; }"""
PILLS_JS = """() => { const ol = document.querySelector('[aria-label="Deliverable stages"]'); if (!ol) return null;
  return new Set([...ol.children].map(li => Math.round(li.getBoundingClientRect().top))).size; }"""
DASHBOARD_JS = """async (pid) => {
  const r = await fetch(`/api/intel/deliverable/${pid}/latest`, {credentials: 'include'}); if (!r.ok) return null;
  const d = await r.json();
  const ev = await fetch(`/api/intel/agent/${pid}/events?limit=1`, {credentials: 'include'});
  const events = ev.ok ? await ev.json() : [];
  const leaf = label => [...document.querySelectorAll('*')].find(e => e.childElementCount === 0 && e.textContent.trim() === label);
  const card = label => { const el = leaf(label); const box = el && el.closest('div'); return box && box.parentElement ? box.parentElement.innerText : ''; };
  const heading = leaf('Recent Activity'); const panel = heading && heading.closest('section') || (heading && heading.parentElement && heading.parentElement.parentElement);
  return {completed: !!(d.run && d.run.status === 'completed'), insights: card('Insights'), slides: card('Slides'),
          downloads: card('Downloads'), activityText: panel ? panel.innerText : '', hasActivity: events.length > 0 || !!d.run}; }"""


def _zeroish(card_text: str) -> bool:
    return any(line.strip() in ("0", "None") for line in card_text.splitlines())


def _activity_empty(panel_text: str) -> bool:
    lines = [l.strip() for l in panel_text.splitlines() if l.strip() and l.strip() != "Recent Activity"]
    return not lines or any(l.lower().startswith(_EMPTY_ACTIVITY) for l in lines)


def check_page(page, name: str, project_id: int | None) -> list[Finding]:
    found: list[Finding] = []
    page.wait_for_timeout(FADE_SAMPLE_MS)
    opacity = page.evaluate(FADE_JS)
    if opacity < FADED_BELOW:
        found.append(Finding(name, "faded_on_load", f"page content opacity {opacity:.2f} {FADE_SAMPLE_MS}ms after load"))
    page.wait_for_timeout(SETTLE_MS)
    found += [Finding(name, f["kind"], f["detail"]) for f in page.evaluate(GENERIC_CHECKS_JS)]
    if name in ("deliverables", "any"):
        rows = page.evaluate(PILLS_JS)
        if rows and rows > 1:
            found.append(Finding(name, "stage_pills_wrap", f"stage list spans {rows} rows"))
    if name == "dashboard" and project_id:
        d = page.evaluate(DASHBOARD_JS, project_id)
        if d and d["completed"] and any(_zeroish(d[k]) for k in ("insights", "slides", "downloads")):
            found.append(Finding(name, "stat_mismatch", "dashboard shows 0/None while the deliverable run is complete"))
        if d and d["hasActivity"] and _activity_empty(d["activityText"]):
            found.append(Finding(name, "empty_activity", "Recent Activity is empty although the project has runs"))
    return found


def _check_project_switch(page, project_id: int) -> list[Finding]:
    card = page.locator(f"[data-project-id='{project_id}']").first
    if card.count() == 0:
        return []
    card.click()
    page.wait_for_timeout(SETTLE_MS)
    path = page.evaluate("() => location.pathname")
    return [] if path.startswith(f"/{project_id}/") else [
        Finding("projects", "url_project_mismatch", f"after opening project {project_id} the URL is {path}")]


def walk(base_url: str, user_id: int, project_id: int, out_dir: Path, pages=WALK) -> list[Finding]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    token, _ = store.create_session(user_id)
    host = base_url.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies([{"name": SESSION_COOKIE_NAME, "value": token, "domain": host, "path": "/"}])
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url.split('?')[0]}") if r.status >= 400 else None)
            for name in pages:
                errors.clear()
                path = f"/{name}" if name in ("landing", "projects") else f"/{project_id}/{name}"
                page.goto(base_url.rstrip("/") + path, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                here = check_page(page, name, project_id)
                if name == "projects":
                    here += _check_project_switch(page, project_id)
                here += [Finding(name, "failed_request" if e.startswith("HTTP") else "console_error", e[:200])
                         for e in dict.fromkeys(errors)]
                if here:
                    shot = out_dir / f"{name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    here = [Finding(f.page, f.kind, f.detail, str(shot)) for f in here]
                findings += here
            browser.close()
    finally:
        store.delete_session(token)
    return findings


def file_findings(findings: list[Finding], project_id: int) -> list[int]:
    from .repair import issues
    return [issues.file_issue("qa_browser", f.kind, f"{f.page}: {f.kind}",
                              {"page": f.page, "kind": f.kind, "detail": f.detail, "screenshot": f.screenshot},
                              project_id)[0] for f in findings]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Walk the app as a user and report what looks broken.")
    ap.add_argument("--base", default="http://127.0.0.1:8002")
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--pages", default=",".join(WALK))
    ap.add_argument("--file", action="store_true", help="file each finding as an issue")
    a = ap.parse_args(argv)
    found = walk(a.base, a.user, a.project, config.DATA_DIR / "qa" / str(a.project), a.pages.split(","))
    for f in found:
        print(f.page, f.kind, f.detail)
    if a.file:
        print("filed", file_findings(found, a.project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
