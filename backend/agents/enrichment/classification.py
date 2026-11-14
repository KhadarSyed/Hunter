
import re

from pydantic import BaseModel, Field, model_validator

# Trailing words the LLM adds that do not change the theme ("Holiday campaign launch").
THEME_FILLER_WORDS = {
    "launch", "launches", "launched", "announcement", "announcements",
    "news", "update", "updates", "coverage", "story", "stories",
}
THEME_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}


def canonical_theme(label: str) -> str:
    """One spelling per theme, so near-duplicates group together in charts."""

    label = label.replace("/", " ").replace("&", " and ")
    words = re.sub(r"\s+", " ", label).strip(" .,;:!?-").split(" ")
    # Keep at least two words, so "Product launch" keeps its meaning.
    while len(words) > 2 and words[-1].lower() in THEME_FILLER_WORDS:
        words.pop()

    def case(index: int, word: str) -> str:
        if word != word.lower():  # keep SPF, iPhone, McDonald's as written
            return word
        if index and word in THEME_SMALL_WORDS:
            return word
        return word[:1].upper() + word[1:]

    return " ".join(case(i, w) for i, w in enumerate(words))


class ClassificationTag(BaseModel):
    """
    Represents one industry, category, group, signal or theme.
    """

    label: str = Field(
        min_length=1,
        description="Name of the classification."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-estimated classification confidence."
    )

    reason: str = Field(
        min_length=1,
        description="Reason for assigning this classification."
    )

    evidence: list[str] = Field(
        min_length=1,
        description="Supporting passages from the original content."
    )



class ContentClassification(BaseModel):
    """
    Classification structure for articles and social media content.
    """

    industry: ClassificationTag | None = Field(
        default=None,
        description="Primary industry associated with the content."
    )

    category: ClassificationTag | None = Field(
        default=None,
        description="Category within the identified industry."
    )

    group: ClassificationTag | None = Field(
        default=None,
        description="Specific group within the category."
    )

    signals: list[ClassificationTag] = Field(
        default_factory=list,
        description="Important developments or occurrences identified."
    )

    primary_theme: ClassificationTag | None = Field(
        default=None,
        description="The central theme of the content."
    )

    secondary_themes: list[ClassificationTag] = Field(
        default_factory=list,
        description="Supporting themes discussed in the content."
    )

    tertiary_themes: list[ClassificationTag] = Field(
        default_factory=list,
        description="More specific subthemes."
    )

    @model_validator(mode="after")
    def canonicalize_themes(self):
        """Also runs on tag-index reads, so cached tags get the same labels."""

        def clean(tags: list[ClassificationTag]) -> list[ClassificationTag]:
            unique: dict[str, ClassificationTag] = {}
            for tag in tags:
                label = canonical_theme(tag.label)
                unique.setdefault(label.lower(), tag.model_copy(update={"label": label}))
            return list(unique.values())

        if self.primary_theme:
            self.primary_theme = clean([self.primary_theme])[0]
        self.secondary_themes = clean(self.secondary_themes)
        self.tertiary_themes = clean(self.tertiary_themes)
        return self
