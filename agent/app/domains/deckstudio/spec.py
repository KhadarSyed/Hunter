"""The slide spec: the contract every renderer (HTML now; editable PPTX and video later) reads."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

SPEC_VERSION = 1


@dataclass
class DeckTokens:
    background: str = "FFFFFF"
    surface: str = "F7F5FB"
    primary: str = "3D1A6B"
    accent: str = "A87DC8"
    text: str = "1F1F1F"
    muted: str = "5A5A6A"
    on_dark: str = "FFFFFF"
    series: list[str] = field(default_factory=lambda: ["5E35B1", "E4572E", "196B24", "0F9ED5", "A02B93", "E97132"])
    overlay: str = "linear-gradient(90deg, rgba(30,10,60,.85), rgba(30,10,60,.2))"
    title_font: str = "Playfair Display"
    body_font: str = "Inter"
    mood: list[str] = field(default_factory=list)
    design_system: str = ""
    type_scale: dict = field(default_factory=dict)
    chrome_font: str = ""
    radius: int = 18


@dataclass
class SlideSpec:
    id: str
    type: str
    treatment: str = "plain"
    kicker: str = ""
    title: str = ""
    question: str = ""
    so_what: str = ""
    n_label: str = ""
    charts: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    logos: dict[str, str] = field(default_factory=dict)
    image: dict = field(default_factory=dict)
    facts_allowed: list[str] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    notes: str = ""
    reference: dict = field(default_factory=dict)


@dataclass
class DeckSpec:
    version: int
    title: str
    subtitle: str
    period: str
    base_n: int
    family: str
    family_reason: str
    tokens: DeckTokens | None
    slides: list[SlideSpec]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DeckSpec":
        tokens = DeckTokens(**d["tokens"]) if d.get("tokens") else None
        return DeckSpec(**{**d, "tokens": tokens, "slides": [SlideSpec(**s) for s in d["slides"]]})
