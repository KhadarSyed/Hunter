"""Central configuration: repo/data paths, and `AppSettings` (process/environment config read once from
environment variables / .env and validated at startup)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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


def input_roots() -> list[Path]:
    """Folders the agent may read client inputs (briefs, Meltwater exports) from: HUNTER_AGENT_INPUT_ROOTS, ';'-separated.
    None by default, so no folder is readable until an admin names one."""
    return [Path(p.strip()) for p in (os.getenv("HUNTER_AGENT_INPUT_ROOTS") or "").split(";") if p.strip()]


AGENT_INPUT_ROOTS = input_roots()
TEMPLATES_DIR = REPO_ROOT / "PPT Templates"   # reference decks shipped with the repo

# Not a database file any more: core/db.py hashes this path into the Postgres schema name, so it must not change.
MEMORY_DB_PATH = DATA_DIR / "memory.db"
TEMPLATE_PATH = DATA_DIR / "hunter_template.pptx"


class AppSettings(BaseSettings):
    """Environment configuration, validated once at startup (see get_app_settings)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Hunter Intelligence Platform"
    app_version: str = "1.0.0"
    environment: str = Field("development", description="development | production")
    log_level: str = "INFO"
    # Browser origins allowed to call the API (Vite dev server + the backend-served SPA).
    cors_origins: list[str] = [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8002", "http://127.0.0.1:8002",
    ]
    # Shared secret for /api/* (header X-API-Key, or ?api_key= for the WebSocket).
    # Empty = auth disabled, which is only allowed when environment != production.
    api_key: str = ""
    brandfetch_api_key: str = ""
    brandfetch_client_id: str = ""
    # Transactional mail (ZeptoMail SMTP, ZEPTO_* in .env). No server, password or sender = mail is skipped.
    zepto_server: str = ""               # smtp.zeptomail.com (or a regional host)
    zepto_smtp_port: int = 587           # 587 STARTTLS, 465 SSL
    zepto_username: str = ""             # "emailapikey" for ZeptoMail
    zepto_passwd_key: str = ""           # the Send Mail token
    zepto_from: str = ""                 # verified sender address
    mail_from_name: str = "Hunter"
    # The frontend's base URL, for links in emails: APP_URL, else the address Render gives the service, else local Vite.
    app_url: str = os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:5173"
    # Chat model price in USD per million tokens, for the tagging cost estimate (gpt-5 list price; set your Azure rate).
    # gpt-5's hidden reasoning is billed as output, so a call costs more output than its visible reply.
    llm_price_input_per_1m: float = 1.25
    llm_price_output_per_1m: float = 10.0

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
