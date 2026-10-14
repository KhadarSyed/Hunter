"""Logos as the deck shows them: empty margins trimmed so the mark fills its chip, and a light (white) logo flagged
so it is set on a dark chip instead of disappearing into a white one."""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops

logger = logging.getLogger(__name__)

ALPHA_VISIBLE = 32          # pixels fainter than this are background
WHITE_CUTOFF = 245          # an opaque logo's white margin
LIGHT_LUMA = 200            # a pixel this bright reads as white on a white chip
LIGHT_SHARE = 0.8           # a logo is light when most of its visible pixels are
TRIM_PAD = 4                # px kept around the trimmed mark
SAMPLE_SIZE = (160, 160)


def _content_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] < 255:                      # transparent background: crop to what is drawn
        return alpha.point(lambda a: 255 if a > ALPHA_VISIBLE else 0).getbbox()
    rgb = img.convert("RGB")                             # opaque: crop the white margin
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).convert("L")
    return diff.point(lambda v: 255 if v > 255 - WHITE_CUTOFF else 0).getbbox()


def is_light(img: Image.Image) -> bool:
    """Most of the logo's visible pixels are near white: on a white chip it would vanish."""
    small = img.convert("RGBA").resize(SAMPLE_SIZE)
    if small.getchannel("A").getextrema()[0] == 255:    # an opaque logo carries its own background
        return False
    lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b, a in small.getdata() if a > ALPHA_VISIBLE]
    return bool(lumas) and sum(v >= LIGHT_LUMA for v in lumas) / len(lumas) >= LIGHT_SHARE


@lru_cache(maxsize=4096)
def prepare(path: str | None, out_dir: Path) -> tuple[str, bool] | None:
    """(the trimmed copy's path, light?) or None when the file is missing or unreadable."""
    if not path or not Path(path).exists():
        return None
    try:
        with Image.open(path) as raw:
            img = raw.convert("RGBA")
        box = _content_box(img)
        if box:
            l, t, r, b = box
            img = img.crop((max(0, l - TRIM_PAD), max(0, t - TRIM_PAD),
                            min(img.width, r + TRIM_PAD), min(img.height, b + TRIM_PAD)))
        tag = hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:8]   # same name, other folder
        out = out_dir / "assets" / f"{Path(path).stem}-{tag}-mark.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return str(out), is_light(img)
    except (OSError, ValueError) as e:     # an unreadable logo is shown as it is
        logger.info("logo left as is (%s): %s", Path(path).name, type(e).__name__)
        return str(path), False
