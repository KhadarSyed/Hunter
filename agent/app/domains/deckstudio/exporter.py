"""Pixel-perfect exports of the HTML deck: each slide screenshotted at 1920x1080 into a 16:9 PPTX (one full
picture per slide; the title kept under it for search and accessibility; slide text in the notes) and a PDF."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Inches

from .spec import DeckSpec

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
SETTLE_MS = 900


def screenshot_slides(html_path: Path, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(html_path).resolve().as_uri() + "?export=1", wait_until="networkidle")
        page.wait_for_timeout(SETTLE_MS)          # web fonts and photos settle
        for k, el in enumerate(page.query_selector_all("section.slide"), start=1):
            path = out_dir / f"slide_{k:02d}.png"
            el.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths


def build_pptx(pngs: list[Path], spec: DeckSpec, out: Path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    layout = prs.slide_layouts[5]          # "Title Only": the title stays searchable under the picture
    for png, s in zip(pngs, spec.slides):
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = s.question or s.title or spec.title
        slide.shapes.add_picture(str(png), Emu(0), Emu(0), SLIDE_W, SLIDE_H)
        lines = [s.kicker, s.question or s.title, s.so_what] + [f"{c.get('headline', '')}: {c.get('text', '')}" for c in s.cards]
        if s.type in ("verbatim_wall", "citations") and s.notes:
            lines.append(s.notes)
        slide.notes_slide.notes_text_frame.text = "\n".join(x for x in lines if x)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return out


def build_pdf(pngs: list[Path], out: Path) -> Path:
    images = [Image.open(p).convert("RGB") for p in pngs]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=144)
    return out


def export_all(html_path: Path, spec: DeckSpec, out_dir: Path, stem: str) -> dict:
    pngs = screenshot_slides(html_path, out_dir / "slides")
    if len(pngs) != len(spec.slides):      # never pair titles and notes with the wrong pictures
        raise RuntimeError(f"rendered {len(pngs)} slides for a {len(spec.slides)}-slide deck")
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in " -_").strip() or "Deck"
    return {"pngs": pngs, "pptx": build_pptx(pngs, spec, out_dir / f"{safe} - Deck.pptx"),
            "pdf": build_pdf(pngs, out_dir / f"{safe} - Deck.pdf")}
