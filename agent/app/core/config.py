"""Central configuration.

Two kinds of settings live here:
- `AppSettings` — process/environment config (CORS, API key, log level, provider keys),
  read once from environment variables / .env and validated at startup.
- `Settings` — the Brief-to-Deck agent's user-editable folders and models, stored in
  data/settings.json and edited from the UI Settings panel.
"""
from __future__ import annotations

import json
import os
import dataclasses
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent.parent  # agent/app
AGENT_DIR = APP_DIR.parent                         # agent/
# HUNTER_AGENT_DATA_DIR lets tests (and deployments) keep data out of agent/data.
DATA_DIR = Path(os.getenv("HUNTER_AGENT_DATA_DIR") or AGENT_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"

SETTINGS_PATH = DATA_DIR / "settings.json"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
TEMPLATE_PATH = DATA_DIR / "hunter_template.pptx"

DEFAULT_SETTINGS = {
    "repo_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\All PPT Decks",
    "briefs_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\New Client Brief Feeder Agent",
    "output_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\Agent Output",
    "ignore_patterns": ["Combined_*"],
    "top_k_candidates": 8,
    "relevance_threshold": 0.42,
}


@dataclass
class Settings:
    repo_dir: str
    briefs_dir: str
    output_dir: str
    ignore_patterns: list
    top_k_candidates: int
    relevance_threshold: float

    def to_dict(self):
        return asdict(self)


def load_settings() -> Settings:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    known_fields = {f.name for f in dataclasses.fields(Settings)}
    return Settings(**{k: v for k, v in merged.items() if k in known_fields})


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")


def ensure_dirs(settings: Settings) -> None:
    for d in (settings.briefs_dir, settings.output_dir):
        Path(d).mkdir(parents=True, exist_ok=True)


class AppSettings(BaseSettings):
    """Environment configuration, validated once at startup (see get_app_settings)."""

    model_config = SettingsConfigDict(env_file=AGENT_DIR.parent / ".env", env_file_encoding="utf-8", extra="ignore")

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

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_app_settings() -> AppSettings:
    settings = AppSettings()
    if settings.is_production and not settings.api_key:
        raise RuntimeError("API_KEY must be set when ENVIRONMENT=production")
    return settings
