"""Ask Azure OpenAI (gpt-4.1, image input) whether a candidate photo fits the slide. None = could not judge."""
from __future__ import annotations

import base64
import logging
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)
THUMB_PX = 512
_PROMPT = ("Answer YES or NO first. Is this photo a good, on-topic image for a presentation slide about {label}, "
           "for the {category} category{brands}{products}? Say NO for logos alone, charts, screenshots of text, "
           "watermarked stock, unrelated scenes, or a different brand's product.")


def _thumb(data: bytes) -> str:
    with Image.open(BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX))
        out = BytesIO()
        im.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode("ascii")


def matches(llm, image_bytes: bytes, s, slide_label: str) -> bool | None:
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return None
    text = _PROMPT.format(label=slide_label, category=s.category,
                          brands=f", brands {', '.join(s.brands)}" if s.brands else "",
                          products=f", products {', '.join(s.products[:3])}" if s.products else "")
    try:
        reply = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_thumb(image_bytes)}"}}]}])
    except Exception as e:      # the text gate still applies when vision is unavailable
        logger.warning("vision check skipped: %s", type(e).__name__)
        return None
    head = (reply or "").strip().upper()
    return True if head.startswith("YES") else False if head.startswith("NO") else None


_LOGO_PROMPT = ("Answer YES or NO first. Is this image the logo (wordmark or symbol) of the brand \"{brand}\" itself? "
                "Say NO if it shows a different brand, even one from the same company.")


def is_logo_of(llm, image_bytes: bytes, brand: str) -> bool | None:
    """Whether a candidate logo is the brand's own (Brandfetch records can carry a sister brand's wordmark).
    None = could not judge."""
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return None
    try:
        reply = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": _LOGO_PROMPT.format(brand=brand)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_thumb(image_bytes)}"}}]}])
    except Exception as e:      # an unjudged logo is kept, as before
        logger.warning("logo check skipped: %s", type(e).__name__)
        return None
    head = (reply or "").strip().upper()
    return True if head.startswith("YES") else False if head.startswith("NO") else None
