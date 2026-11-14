
from typing import Literal

from pydantic import BaseModel, Field


class BrandAspectSentiment(BaseModel):
    """
    Represents sentiment toward one specific aspect of a brand.
    """

    brand: str = Field(
        min_length=1,
        description="Name of the brand: a monitored brand or any other brand found in the content."
    )

    aspect: str = Field(
        min_length=1,
        description="Specific aspect of the brand being discussed."
    )

    sentiment: Literal[
        "positive",
        "negative",
        "neutral",
        "mixed"
    ] = Field(
        description="Sentiment expressed toward this brand aspect."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-estimated confidence in the aspect sentiment."
    )

    reason: str = Field(
        min_length=1,
        description="Explanation for the assigned aspect sentiment."
    )

    evidence: list[str] = Field(
        min_length=1,
        description="Exact supporting passages from the original content."
    )


class ContentBrandAspectSentiments(BaseModel):
    """
    Groups aspect-level sentiment assessments across monitored brands.
    """

    assessments: list[BrandAspectSentiment] = Field(
        default_factory=list,
        description="Individual brand aspect sentiment assessments."
    )
