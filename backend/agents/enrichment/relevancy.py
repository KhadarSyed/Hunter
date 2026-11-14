
from pydantic import BaseModel, Field


class BrandRelevancy(BaseModel):
    """
    Measures how relevant content is to one monitored brand.
    """

    brand: str = Field(
        min_length=1,
        description="Name of the monitored brand."
    )

    relevancy_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Degree of relevance to the monitored brand, from 0 to 1."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-estimated confidence in the relevancy assessment."
    )

    reason: str = Field(
        min_length=1,
        description="Explanation of why the content is relevant or irrelevant."
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting passages from the original content. May be empty when no relevant evidence exists."
    )


class ContentRelevancy(BaseModel):
    """
    Contains relevancy assessments for multiple monitored brands.
    """

    assessments: list[BrandRelevancy] = Field(
        default_factory=list,
        description="Individual relevancy assessments for monitored brands."
    )
