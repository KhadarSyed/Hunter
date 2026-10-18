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
           "watermarked stock, unrelated scenes, a different brand's product, or an older generation or vintage model "
           "instead of the current one.")
# the cover's product box names one product: on-topic is not enough, it must be that product and recognisably so
_EXACT_PROMPT = ("Answer YES or NO first. Does this photo clearly show the {product} by {brand} itself -- that exact "
                 "product or model, current generation? Say NO when it shows a different model or product of the same "
                 "brand (for a car: another body style or model line), when the product cannot be identified from "
                 "the photo, or for logos alone, screenshots, renders of text or watermarked stock.")
# the client's cover and closing slides wear the client: a generic or another brand's product is not theirs
_OWN_BRAND_PROMPT = ("Answer YES or NO first. Is this photo recognisably about {brand} -- a {brand} product, store or "
                     "asset, identifiable as {brand} by its logo, badge or distinctive design? Say NO when it shows "
                     "another brand's product, an unbranded or generic scene that could belong to any brand, a vintage "
                     "model, logos alone, screenshots or watermarked stock.")


def _thumb(data: bytes) -> str:
    with Image.open(BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX))
        out = BytesIO()
        im.save(out, "JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode("ascii")


def matches(llm, image_bytes: bytes, s, slide_label: str, exact: bool = False, own_brand: str = "") -> bool | None:
    """`exact`: the photo must show the subjects' first product itself (the cover's product box), not merely fit.
    `own_brand`: the photo must be recognisably that brand's (the deck's opening and closing slides)."""
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return None
    if own_brand:
        text = _OWN_BRAND_PROMPT.format(brand=own_brand)
    elif exact and s.products:
        text = _EXACT_PROMPT.format(product=s.products[0], brand=", ".join(s.brands) or s.category)
    else:
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
_LOGO_CATEGORY = (" The brand meant is the one in {category}: say NO for a company from another industry that shares "
                  "the name (e.g. a wordmark that also reads 'water filters' or 'bank').")


_LOGO_SOURCE = (" The image was taken from the website {domain}: use what you know about whose site that is (a "
                "namesake's site means NO even when the wordmark spells the name).")


def is_logo_of(llm, image_bytes: bytes, brand: str, category: str = "", domain: str = "") -> bool | None:
    """Whether a candidate logo is the brand's own (Brandfetch records can carry a sister brand's wordmark).
    None = could not judge."""
    if llm is None or not getattr(llm, "is_reachable", lambda: False)():
        return None
    try:
        reply = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": _LOGO_PROMPT.format(brand=brand)
             + (_LOGO_CATEGORY.format(category=category) if category else "")
             + (_LOGO_SOURCE.format(domain=domain) if domain else "")},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_thumb(image_bytes)}"}}]}])
    except Exception as e:      # an unjudged logo is kept, as before
        logger.warning("logo check skipped: %s", type(e).__name__)
        return None
    head = (reply or "").strip().upper()
    return True if head.startswith("YES") else False if head.startswith("NO") else None
