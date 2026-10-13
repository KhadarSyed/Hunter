"""Load a per-project deliverable config; resolve paths against the repo root."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _resolve(p: str) -> str:
    path = Path(p)
    return str(path if path.is_absolute() else REPO_ROOT / path)


def load_config(path: str | Path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("title", "themes", "reference_deck", "output_dir", "output_name"):
        if key not in cfg:
            raise ValueError(f"deliverable config missing '{key}'")
    cfg["reference_deck"] = _resolve(cfg["reference_deck"])
    cfg["output_dir"] = _resolve(cfg["output_dir"])
    for theme in cfg["themes"]:
        for f in theme["files"]:
            f["path"] = _resolve(f["path"])
    return cfg
