"""Command line for the deck-studio skill: index references, show rules, render and export from a slide spec."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...core import store
from . import exporter, indexer
from .creative import compose
from .spec import DeckSpec


def _load(path: str) -> DeckSpec:
    return DeckSpec.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deck-studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="index the reference decks folder")
    sub.add_parser("rules", help="print the design rules of a family").add_argument("--family", default="topic_map")
    sub.add_parser("spec", help="print the slide spec path of a run").add_argument("--run", type=int, required=True)
    rd = sub.add_parser("render", help="render deck.html from a slide spec")
    rd.add_argument("--spec", required=True)
    rd.add_argument("--out", required=True)
    rd.add_argument("--no-creative", action="store_true")
    ex = sub.add_parser("export", help="export PPTX and PDF from a rendered deck")
    ex.add_argument("--html", required=True)
    ex.add_argument("--spec", required=True)
    ex.add_argument("--out", required=True)
    a = p.parse_args(argv)
    store.init_intelligence_db()
    if a.cmd == "index":
        print(json.dumps(indexer.index_library()))
    elif a.cmd == "rules":
        print(json.dumps(indexer.design_rules(a.family), indent=2))
    elif a.cmd == "spec":
        print(Path((store.get_deliverable_run(a.run) or {}).get("deck_dir") or "") / "spec.json")
    elif a.cmd == "render":
        llm = None
        if not a.no_creative:
            from ...core.anthropic_client import get_llm_client
            llm = get_llm_client()
        path, report = compose(_load(a.spec), Path(a.out), llm, indexer.reference_text_shingles())
        print(json.dumps({"html": str(path), "slides": report}))
    else:
        spec = _load(a.spec)
        out = exporter.export_all(Path(a.html), spec, Path(a.out), spec.title)
        print(json.dumps({"pptx": str(out["pptx"]), "pdf": str(out["pdf"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
