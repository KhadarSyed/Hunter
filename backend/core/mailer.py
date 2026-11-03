"""Transactional email through ZeptoMail SMTP (Zoho). Never raises: returns whether the server accepted the message."""
from __future__ import annotations

import base64
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .config import get_app_settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 20


def send_email(to_address: str, to_name: str, subject: str, html: str, text: str,
               inline_images: list[dict] | None = None) -> bool:
    """inline_images: [{"cid", "mime_type", "content" (base64)}], referenced in the HTML as src="cid:<cid>"."""
    s = get_app_settings()
    if not (s.zepto_server.strip() and s.zepto_passwd_key.strip() and s.zepto_from.strip()):
        logger.warning("Mail not configured (ZEPTO_SERVER / ZEPTO_PASSWD_KEY / ZEPTO_FROM): skipped %r", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((s.mail_from_name, s.zepto_from.strip()))
    msg["To"] = formataddr((to_name or "", to_address))
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[1]
    for img in inline_images or []:
        maintype, _, subtype = img["mime_type"].partition("/")
        html_part.add_related(base64.b64decode(img["content"]), maintype=maintype, subtype=subtype,
                              cid=f"<{img['cid']}>")
    try:
        ctx = ssl.create_default_context()
        if s.zepto_smtp_port == 465:
            server = smtplib.SMTP_SSL(s.zepto_server.strip(), 465, timeout=TIMEOUT_S, context=ctx)
        else:
            server = smtplib.SMTP(s.zepto_server.strip(), s.zepto_smtp_port, timeout=TIMEOUT_S)
            server.starttls(context=ctx)
        with server:
            server.login(s.zepto_username.strip() or "emailapikey", s.zepto_passwd_key.strip())
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        logger.error("Mail send failed for %r: %s %s", subject, type(e).__name__, str(e)[:200])
        return False
    logger.info("Mail sent: %r", subject)
    return True
