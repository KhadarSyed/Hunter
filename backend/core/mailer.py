"""Transactional email through ZeptoMail (Zoho). Never raises: returns whether the API accepted the message."""
from __future__ import annotations

import logging

import requests

from .config import get_app_settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 15
_PREFIX = "zoho-enczapikey "


def _auth_header(token: str) -> str:
    key = token.strip()
    if key.lower().startswith(_PREFIX):
        key = key[len(_PREFIX):].strip()
    return f"Zoho-enczapikey {key}"


def send_email(to_address: str, to_name: str, subject: str, html: str, text: str,
               inline_images: list[dict] | None = None) -> bool:
    """inline_images: [{"cid", "mime_type", "content" (base64)}], referenced in the HTML as src="cid:<cid>"."""
    settings = get_app_settings()
    if not (settings.zeptomail_token.strip() and settings.mail_from.strip()):
        logger.warning("Mail not configured (ZEPTOMAIL_TOKEN / MAIL_FROM): skipped %r", subject)
        return False
    body = {"from": {"address": settings.mail_from.strip(), "name": settings.mail_from_name},
            "to": [{"email_address": {"address": to_address, "name": to_name or to_address}}],
            "subject": subject, "htmlbody": html, "textbody": text}
    if inline_images:
        body["inline_images"] = inline_images
    try:
        r = requests.post(settings.zeptomail_url, json=body, timeout=TIMEOUT_S,
                          headers={"Authorization": _auth_header(settings.zeptomail_token),
                                   "Accept": "application/json"})
    except requests.RequestException as e:
        logger.error("Mail send failed for %r: %s", subject, type(e).__name__)
        return False
    if 200 <= r.status_code < 300:
        logger.info("Mail sent: %r (HTTP %s)", subject, r.status_code)
        return True
    logger.error("Mail rejected for %r: HTTP %s %s", subject, r.status_code, r.text[:300])
    return False
