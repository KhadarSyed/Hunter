
from .relevancy import ContentRelevancy

# Prefix of the review issue raised when a found brand has no aspect sentiment (triggers self-correction).
MISSING_ASPECT = "ASPECT:"


def same_brand(first: str, second: str) -> bool:
    """Brand names match ignoring case, or when one contains the other (Aquaphor / Aquaphor Baby)."""

    first, second = first.strip().lower(), second.strip().lower()
    return bool(first and second) and (first in second or second in first)


def find_brands_without_aspects(enrichment) -> list[str]:
    """Brands in entities.brands that have no brand aspect sentiment."""

    aspect_brands = [a.brand for a in enrichment.brand_aspect_sentiments.assessments]
    return [
        f"Brand '{entity.canonical_name}' was found but has no brand aspect sentiment."
        for entity in enrichment.entities.brands
        if not any(
            same_brand(brand, entity.canonical_name) or same_brand(brand, entity.name)
            for brand in aspect_brands
        )
    ]


def validate_monitored_brand_relevancy(
    relevancy: ContentRelevancy,
    monitored_brands: list[str],
) -> list[str]:
    """
    Validate that relevancy assessments contain exactly
    the configured monitored brands.

    Returns an empty list when all business rules pass.
    Otherwise, returns a list of validation errors.
    """

    errors = []

    # 1. Normalize the monitored brand configuration
    configured_brands = {
        brand.strip().casefold(): brand.strip()
        for brand in monitored_brands
        if brand and brand.strip()
    }

    if not configured_brands:
        return ["No monitored brands have been configured."]

    # 2. Track brands returned by GPT
    assessed_brands = set()

    for assessment in relevancy.assessments:

        brand_key = assessment.brand.strip().casefold()

        # 3. Detect unexpected brands
        if brand_key not in configured_brands:
            errors.append(
                f"Unexpected brand assessment: {assessment.brand}"
            )
            continue

        # 4. Detect duplicate assessments
        if brand_key in assessed_brands:
            errors.append(
                f"Duplicate relevancy assessment: {assessment.brand}"
            )
            continue

        assessed_brands.add(brand_key)

    # 5. Detect missing monitored brands
    for brand_key, brand_name in configured_brands.items():

        if brand_key not in assessed_brands:
            errors.append(
                f"Missing relevancy assessment for monitored brand: "
                f"{brand_name}"
            )

    return errors


# Scores at or above this mark the content as relevant to the brand.
RELEVANCY_THRESHOLD = 0.5


def find_unsupported_relevancy(relevancy: ContentRelevancy) -> list[str]:
    """Relevant-level scores with no quoted evidence need a human check."""

    return [
        f"Relevancy score {assessment.relevancy_score:.2f} for "
        f"{assessment.brand} has no supporting evidence."
        for assessment in relevancy.assessments
        if assessment.relevancy_score >= RELEVANCY_THRESHOLD
        and not assessment.evidence
    ]
