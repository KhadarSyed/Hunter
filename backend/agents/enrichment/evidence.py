
import unicodedata

from .model import ContentEnrichment


def normalize_text(text: str) -> str:
    """
    Normalize text for evidence comparison.

    Handles:
    - Uppercase and lowercase differences.
    - Multiple spaces.
    - Newlines and tabs.
    - Unicode character variations.
    """

    normalized = unicodedata.normalize("NFKC", text).translate(_QUOTE_MAP)

    return " ".join(normalized.casefold().split())


# Curly quotes compare equal to straight ones.
_QUOTE_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_WRAPPER_CHARS = " \"'"


def evidence_fragments(passage: str) -> list[str]:
    """
    Normalized pieces of a quote that must each appear in the source.

    The LLM often wraps quotes in quotation marks and marks skipped text
    with "..."; neither is part of the source, so both are removed.
    """

    normalized = normalize_text(passage)
    return [
        fragment.strip(_WRAPPER_CHARS)
        for fragment in normalized.split("...")
        if fragment.strip(_WRAPPER_CHARS)
    ]


def validate_evidence_against_content(
    enrichment: ContentEnrichment,
    source_content: str,
) -> list[str]:
    """
    Verify that every supplied evidence passage exists
    in the original article or social media content.

    Returns an empty list if all evidence is found.
    """

    errors = []

    # 1. Validate original source content
    if not source_content or not source_content.strip():
        return ["Original source content is empty."]

    normalized_source = normalize_text(source_content)

    # 2. Reusable evidence validation function
    def check_evidence(path: str, passages: list[str]) -> None:

        for index, passage in enumerate(passages):

            fragments = evidence_fragments(passage)

            if not fragments:
                errors.append(
                    f"{path}[{index}] contains empty evidence."
                )

            elif any(fragment not in normalized_source for fragment in fragments):
                errors.append(
                    f"{path}[{index}] was not found in source content: "
                    f"{passage[:80]!r}"
                )

    # 3. Overall sentiment evidence
    check_evidence(
        "sentiment.evidence",
        enrichment.sentiment.evidence,
    )

    # 4. Dynamically validate every entity group
    entity_groups = type(enrichment.entities).model_fields.keys()

    for group_name in entity_groups:

        entities = getattr(enrichment.entities, group_name)

        for index, entity in enumerate(entities):

            check_evidence(
                f"entities.{group_name}[{index}].evidence",
                entity.evidence,
            )

    # 5. Validate individual classification fields
    classification_fields = [
        "industry",
        "category",
        "group",
        "primary_theme",
    ]

    for field_name in classification_fields:

        item = getattr(
            enrichment.classification,
            field_name,
        )

        if item is not None:
            check_evidence(
                f"classification.{field_name}.evidence",
                item.evidence,
            )

    # 6. Validate signals and secondary/tertiary themes
    list_fields = [
        "signals",
        "secondary_themes",
        "tertiary_themes",
    ]

    for field_name in list_fields:

        items = getattr(
            enrichment.classification,
            field_name,
        )

        for index, item in enumerate(items):

            check_evidence(
                f"classification.{field_name}[{index}].evidence",
                item.evidence,
            )

    # 7. Brand relevancy evidence
    for index, assessment in enumerate(
        enrichment.relevancy.assessments
    ):

        check_evidence(
            f"relevancy.assessments[{index}].evidence",
            assessment.evidence,
        )

    # 8. Brand aspect sentiment evidence
    for index, assessment in enumerate(
        enrichment.brand_aspect_sentiments.assessments
    ):

        check_evidence(
            f"brand_aspect_sentiments.assessments[{index}].evidence",
            assessment.evidence,
        )

    return errors
