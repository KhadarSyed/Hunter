"""Assemble the Baby Skincare reference deck on top of the Hunter base deck."""
from __future__ import annotations


from pptx.opc.packuri import PackURI
from pptx.util import Inches

from . import blocks
from .metrics import month_label

CITES_PER_PAGE = 18


LOGO_MAX_W, LOGO_MAX_H = 0.9, 0.45
BRAND_PLOT_TOP, BRAND_PLOT_H = 1.6, 5.3   # bar plot area inside the 1.45in/5.6in brands chart (measured from render)


def _add_logo(slide, path, x: float, centre_y: float, max_h: float) -> None:
    """Fit a logo inside LOGO_MAX_W x max_h inches, preserving aspect ratio, vertically centred on centre_y."""
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(centre_y), height=Inches(max_h))
    if pic.width > Inches(LOGO_MAX_W):
        ratio = Inches(LOGO_MAX_W) / pic.width
        pic.width, pic.height = Inches(LOGO_MAX_W), int(pic.height * ratio)
    pic.top = int(Inches(centre_y) - pic.height / 2)


def paginate(entries: list, per_page: int) -> list[list]:
    return [entries[i:i + per_page] for i in range(0, len(entries), per_page)] or [[]]


def keep_cover_and_closing(prs) -> None:
    ids = prs.slides._sldIdLst
    for sld in list(ids)[1:-1]:
        prs.part.drop_rel(sld.rId)
        ids.remove(sld)
    # python-pptx names new slides slide{len+1}.xml; renumber survivors so names never collide
    for i, slide in enumerate(prs.slides, start=1):
        slide.part.partname = PackURI(f"/ppt/slides/slide{i}.xml")


def _move_to_end(prs, index: int) -> None:
    ids = prs.slides._sldIdLst
    el = list(ids)[index]
    ids.remove(el)
    ids.append(el)


def _source(cfg, theme_metrics=None) -> str:
    if theme_metrics and theme_metrics.get("date_min"):
        return (f"{month_label(theme_metrics['date_min'][:7])} – "
                f"{month_label(theme_metrics['date_max'][:7])}")
    return cfg["period_label"]


def _summary(ins: list[dict]) -> str:
    return ins[0]["text"] + blocks.citation_suffix(ins[0]["citations"]) if ins else ""


