"""The language client-facing text is written in, from the project's country or region. Global (and any region not
listed) is written for the United States. Applied by wrapping the LLM client, so every drafting call of a run --
insights, summaries, the cover subtitle, the background brief -- carries the same instruction."""
from __future__ import annotations

US_ENGLISH = "American English (US spelling)"

# The New Project form's geographies (frontend/src/components/CountryFlag.tsx GEOGRAPHIES)
_LANGUAGES = {
    "global": US_ENGLISH,
    "united states": US_ENGLISH,
    "united kingdom": "British English (UK spelling)",
    "canada": "Canadian English (Canadian spelling)",
    "india": "Indian English (UK spelling)",
    "australia": "Australian English (Australian spelling)",
    "singapore": "English (UK spelling, as used in Singapore)",
    "united arab emirates": "English (UK spelling, as used in the UAE)",
    "germany": "German",
    "france": "French",
    "spain": "Spanish (Spain)",
    "italy": "Italian",
    "netherlands": "Dutch",
    "japan": "Japanese",
    "brazil": "Brazilian Portuguese",
    "mexico": "Mexican Spanish",
}
_ALIASES = {"us": "united states", "usa": "united states", "uk": "united kingdom", "great britain": "united kingdom",
            "uae": "united arab emirates", "worldwide": "global", "international": "global"}


def writing_language(geography) -> str:
    """The language for a project's geography; Global, empty or unknown is written for the United States."""
    key = " ".join(str(geography or "").lower().replace(".", "").split())
    return _LANGUAGES.get(_ALIASES.get(key, key), US_ENGLISH)


def project_geography(project: dict | None) -> str:
    spec = (project or {}).get("spec") or {}
    return str((spec.get("included_scope") or {}).get("geography") or spec.get("geography") or "")


def instruction(language: str) -> str:
    return (f"Write every piece of client-facing text in {language}. Keep brand, product, outlet and people's names, "
            "quoted source text and JSON keys exactly as given, and write numbers exactly as the facts state them "
            "(e.g. 62.5%).")


class LocaleLLM:
    """The run's LLM client with the language instruction added to every chat; everything else is delegated."""

    def __init__(self, llm, language: str):
        self._llm, self.language = llm, language

    def chat(self, messages, *args, **kwargs):
        return self._llm.chat([{"role": "system", "content": instruction(self.language)}] + list(messages), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._llm, name)


def with_locale(llm, geography):
    """`llm` writing in the geography's language (US English for Global); None stays None, and a client that is
    already wrapped is not wrapped twice."""
    if llm is None or isinstance(llm, LocaleLLM):
        return llm
    return LocaleLLM(llm, writing_language(geography))
