"""Central configuration for the Hunter brief-to-deck agent.

Settings are stored in data/settings.json and can be edited from the UI Settings
panel; this module holds the defaults and the load/save helpers.
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, asdict, field

APP_DIR = Path(__file__).resolve().parent
AGENT_DIR = APP_DIR.parent
DATA_DIR = AGENT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_PATH = DATA_DIR / "settings.json"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
TEMPLATE_PATH = DATA_DIR / "hunter_template.pptx"

DEFAULT_SETTINGS = {
    "repo_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\All PPT Decks",
    "briefs_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\New Client Brief Feeder Agent",
    "output_dir": r"C:\Users\sweta.shah\OneDrive - InfoVision, Inc\Hunter PR\2026\Agent Output",
    "ignore_patterns": ["Combined_*"],
    "ollama_host": "http://localhost:11434",
    "embed_model": "nomic-embed-text",
    "chat_model": "qwen2.5:3b",
    "top_k_candidates": 8,
    "relevance_threshold": 0.42,
}


@dataclass
class Settings:
    repo_dir: str
    briefs_dir: str
    output_dir: str
    ignore_patterns: list
    ollama_host: str
    embed_model: str
    chat_model: str
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
    return Settings(**merged)


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")


def ensure_dirs(settings: Settings) -> None:
    for d in (settings.briefs_dir, settings.output_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
