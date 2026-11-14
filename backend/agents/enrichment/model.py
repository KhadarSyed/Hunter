
from pydantic import BaseModel, Field

from .brand_aspects import (
    ContentBrandAspectSentiments,
)
from .classification import ContentClassification
from .entities import ContentEntities
from .relevancy import ContentRelevancy
from .sentiment import SentimentResult


class ContentEnrichment(BaseModel):
    """
    Unified enrichment response for news articles,
    blogs, reviews and social media content.
    """

    summary: str = Field(
        min_length=1,
        description="Neutral one-to-three sentence summary of the content.",
    )

    sentiment: SentimentResult = Field(
        description="Overall sentiment and sarcasm analysis."
    )

    entities: ContentEntities = Field(
        description="All identified and grouped entities."
    )

    classification: ContentClassification = Field(
        description="Industry, category, group, signals and themes."
    )

    relevancy: ContentRelevancy = Field(
        description="Individual relevancy assessments for monitored brands."
    )

    brand_aspect_sentiments: ContentBrandAspectSentiments = Field(
        description="Sentiment analysis for individual brand aspects."
    )
