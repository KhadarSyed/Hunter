
from .model import ContentEnrichment
from .brand_relevancy import (
    MISSING_ASPECT,
    find_brands_without_aspects,
    find_unsupported_relevancy,
    validate_monitored_brand_relevancy,
)
from .entity_taxonomy import (
    validate_entity_group_assignments,
)
from .evidence import (
    validate_evidence_against_content,
)


def validate_enrichment_quality(
    enrichment: ContentEnrichment,
    source_content: str,
    monitored_brands: list[str],
) -> dict:
    """
    Runs all enrichment quality checks and generates
    one consolidated validation report.
    """

    errors = []
    review_required = []

    # 1. Validate monitored-brand relevancy
    relevancy_errors = validate_monitored_brand_relevancy(
        enrichment.relevancy,
        monitored_brands,
    )

    errors.extend(
        f"RELEVANCY: {error}"
        for error in relevancy_errors
    )

    # 2. Verify evidence against original content
    evidence_errors = validate_evidence_against_content(
        enrichment,
        source_content,
    )

    errors.extend(
        f"EVIDENCE: {error}"
        for error in evidence_errors
    )

    # 3. Validate entity group assignments
    taxonomy_result = validate_entity_group_assignments(
        enrichment.entities
    )

    errors.extend(
        f"TAXONOMY: {error}"
        for error in taxonomy_result["errors"]
    )

    review_required.extend(
        taxonomy_result["review_required"]
    )

    # 4. Relevant-level scores must be backed by evidence
    review_required.extend(
        f"RELEVANCY: {issue}"
        for issue in find_unsupported_relevancy(enrichment.relevancy)
    )

    # 5. Every brand found needs at least one aspect sentiment
    review_required.extend(
        f"{MISSING_ASPECT} {issue}"
        for issue in find_brands_without_aspects(enrichment)
    )

    # 6. Determine final quality status
    if errors:
        status = "failed"

    elif review_required:
        status = "review_required"

    else:
        status = "passed"

    # 5. Return consolidated report
    return {
        "status": status,
        "is_valid": len(errors) == 0,
        "error_count": len(errors),
        "review_count": len(review_required),
        "errors": errors,
        "review_required": review_required,
    }
