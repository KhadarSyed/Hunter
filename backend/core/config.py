"""Central configuration: repo/data paths, and `AppSettings` (process/environment config read once from
environment variables / .env and validated at startup)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BACKEND_DIR.parent
# AlphaMetricx's wordmark, top right on every deck slide
PARTNER_LOGO = next((p for p in (REPO_ROOT / "frontend" / "public" / "alphametricx.png",
                                 BACKEND_DIR / "static" / "alphametricx.png") if p.exists()), None)
# HUNTER_AGENT_DATA_DIR lets a deployment keep runtime data somewhere other than data/.
DATA_DIR = Path(os.getenv("HUNTER_AGENT_DATA_DIR") or REPO_ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DELIVERABLE_DIR = DATA_DIR / "deliverables"
DELIVERABLE_DIR.mkdir(parents=True, exist_ok=True)
# Throwaway copies of S3-stored logos, favicons and icons for renderers that need a file path; S3 is the store.
ASSET_CACHE_DIR = Path(tempfile.gettempdir()) / "hunter-asset-cache"


def input_roots() -> list[Path]:
    """Folders the agent may read client inputs (briefs, Meltwater exports) from: HUNTER_AGENT_INPUT_ROOTS, ';'-separated.
    None by default, so no folder is readable until an admin names one."""
    return [Path(p.strip()) for p in (os.getenv("HUNTER_AGENT_INPUT_ROOTS") or "").split(";") if p.strip()]


AGENT_INPUT_ROOTS = input_roots()
TEMPLATES_DIR = REPO_ROOT / "PPT Templates"   # reference decks shipped with the repo

# Not a database file any more: core/db.py hashes this path into the Postgres schema name, so it must not change.
MEMORY_DB_PATH = DATA_DIR / "memory.db"
TEMPLATE_PATH = DATA_DIR / "hunter_template.pptx"


DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]   # the Vite dev server
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


class AppSettings(BaseSettings):
    """Environment configuration, validated once at startup (see get_app_settings)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Hunter Intelligence Platform"
    app_version: str = "1.0.0"
    environment: str = Field("development", description="development | production")
    log_level: str = "INFO"
    # Browser origins (other than this server's own) allowed to call the API with the session cookie: CORS_ORIGINS,
    # a comma list or JSON array of exact http(s) origins. Default: the local Vite dev server.
    cors_origins: Annotated[list[str], NoDecode] = DEV_ORIGINS
    # Shared secret for /api/* (header X-API-Key, or ?api_key= for the WebSocket).
    # Empty = auth disabled, which is only allowed when environment != production.
    api_key: str = ""
    # Transactional mail (ZeptoMail SMTP, ZEPTO_* in .env). No server, password or sender = mail is skipped.
    zepto_server: str = ""               # smtp.zeptomail.com (or a regional host)
    zepto_smtp_port: int = 587           # 587 STARTTLS, 465 SSL
    zepto_username: str = ""             # "emailapikey" for ZeptoMail
    zepto_passwd_key: str = ""           # the Send Mail token
    zepto_from: str = ""                 # verified sender address
    mail_from_name: str = "Hunter"
    support_email: str = "support@alphametricx.com"   # the "Questions?" address in every email footer
    # The frontend's base URL, for links in emails: APP_URL, else the address Render gives the service, else local Vite.
    app_url: str = os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:5173"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _origins(cls, v):
        """Exact origins only: "*" with credentials would let any site act as the signed-in user."""
        if isinstance(v, str) and not v.strip():
            return list(DEV_ORIGINS)                    # CORS_ORIGINS= left blank (as in .env.example)
        if isinstance(v, str):
            v = json.loads(v) if v.strip().startswith("[") else v.split(",")
        out = [str(o).strip().rstrip("/") for o in v if str(o).strip()]
        bad = [o for o in out if not _ORIGIN.match(o)]
        if bad:
            raise ValueError(f"CORS_ORIGINS must be exact http(s) origins like https://app.example.com, not {bad}")
        return out

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_app_settings() -> AppSettings:
    settings = AppSettings()
    if settings.is_production and not settings.api_key:
        raise RuntimeError("API_KEY must be set when ENVIRONMENT=production")
    return settings


LOW_MEMORY_BYTES = 1536 * 1024 * 1024
_CGROUP_LIMITS = ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes")


@lru_cache(maxsize=1)
def low_memory() -> bool:
    """True inside a container capped under ~1.5 GB (Render's free plan gives 512 MB), where parallel photo decoding
    and several headless browsers at once get the process killed. HUNTER_LOW_MEMORY=1/0 overrides the detection."""
    forced = os.environ.get("HUNTER_LOW_MEMORY", "").strip()
    if forced in ("0", "1"):
        return forced == "1"
    for path in _CGROUP_LIMITS:
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            continue
        if raw.isdigit():
            return int(raw) < LOW_MEMORY_BYTES
    return False
