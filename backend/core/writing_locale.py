"""The language client-facing text is written in, from the project's country or region. Global (and any region not
listed) is written for the United States, and so is every English-speaking country: the product writes US English
only. Applied by wrapping the LLM client, so every drafting call of a run -- insights, summaries, the cover subtitle,
the background brief -- carries the same instruction; SPELLING_RULE goes on every LLM call (core/llm_provider)."""
from __future__ import annotations

US_ENGLISH = "American English (US spelling)"
# On every LLM call: whatever the language, any English the model writes is US English (tags, themes, briefs, insights)
SPELLING_RULE = ("Whenever you write English, write American English with US spelling only: organization, analyze, "
                 "summarize, prioritize, color, behavior, favorite, center, license, defense, catalog, program, gray, "
                 "canceled, labeled, modeling, traveling, judgment, toward. Never British spellings (organisation, "
                 "analyse, colour, behaviour, centre, licence, cancelled, judgement). Keep names, quotes and JSON keys "
                 "exactly as given.")

# The New Project form's geographies (frontend/src/components/CountryFlag.tsx GEOGRAPHIES)
_LANGUAGES = {
    "global": US_ENGLISH,
    "united states": US_ENGLISH,
    "united kingdom": US_ENGLISH,
    "canada": US_ENGLISH,
    "india": US_ENGLISH,
    "australia": US_ENGLISH,
    "singapore": US_ENGLISH,
    "united arab emirates": US_ENGLISH,
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
