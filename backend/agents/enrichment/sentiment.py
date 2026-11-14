
from typing import Literal

from pydantic import BaseModel, Field


class SentimentResult(BaseModel):
    """
    Defines the expected article sentiment output.
    """

    sentiment: Literal[
        "positive",
        "negative",
        "neutral",
        "mixed"
    ] = Field(
        description="Overall sentiment of the article."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-estimated sentiment confidence between 0 and 1."
    )

    reason: str = Field(
        min_length=1,
        description="Explanation for the sentiment classification."
    )

    evidence: list[str] = Field(
        min_length=1,
        description="Exact supporting passages from the article."
    )


    sarcasm: Literal[
        "present",
        "absent",
        "uncertain"
    ] = Field(
        description="Whether the article or post uses sarcasm."
    )

    sarcasm_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the sarcasm classification."
    )

    sarcasm_reason: str = Field(
        min_length=1,
        description="Explanation for detecting or not detecting sarcasm."
    )
