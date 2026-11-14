
from typing import Literal

from pydantic import BaseModel, Field


class EntityResult(BaseModel):
    """
    Represents one entity identified in an article,
    news report, blog, review or social media content.
    """

    name: str = Field(
        min_length=1,
        description="Entity name exactly as mentioned in the content."
    )

    canonical_name: str = Field(
        min_length=1,
        description="Standardized or normalized entity name."
    )

    entity_type: str = Field(
        min_length=1,
        description=(
            "Specific entity subtype, such as brand, company, "
            "athlete, bird, tree, vehicle, liquid, solid, gas, "
            "chemical compound, river, software or organization."
        )
    )

    relationship_to_monitored_brand: Literal[
        "monitored_brand",
        "competitor",
        "partner",
        "customer",
        "mentioned",
        "unknown"
    ] | None = Field(
        default=None,
        description="Relationship to the monitored brand, when applicable."
    )

    designation: str | None = Field(
        default=None,
        description="Professional designation, title or role, when applicable."
    )

    # Hunter addition: events and campaigns need "what it is about" and, for campaigns, their keywords.
    description: str | None = Field(
        default=None,
        description="For events and campaigns: one sentence on what it is about, from the content."
    )

    keywords: list[str] = Field(
        default_factory=list,
        description="For campaigns: the campaign's slogan, hashtags and related terms used in the content."
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-estimated entity identification confidence."
    )

    evidence: list[str] = Field(
        min_length=1,
        description="Exact supporting passages from the original content."
    )


class ContentEntities(BaseModel):
    """
    Universal grouped entity detection schema.

    Supports editorial articles, news, blogs, reviews,
    social media, sports, business, science, technology,
    entertainment, nature and other content categories.

    Entity types remain extensible to support new discoveries.
    """

    # ==========================================
    # 1. COMMERCIAL AND BUSINESS ENTITIES
    # ==========================================

    brands: list[EntityResult] = Field(default_factory=list)

    companies: list[EntityResult] = Field(default_factory=list)

    organizations: list[EntityResult] = Field(default_factory=list)

    products: list[EntityResult] = Field(default_factory=list)

    services: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 2. GOVERNMENT AND REGULATORY ENTITIES
    # ==========================================

    government_entities: list[EntityResult] = Field(default_factory=list)

    regulators: list[EntityResult] = Field(default_factory=list)

    military_entities: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 3. PEOPLE AND PROFESSIONAL ENTITIES
    # ==========================================

    persons: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 4. GEOGRAPHICAL ENTITIES
    # ==========================================

    locations: list[EntityResult] = Field(default_factory=list)

    geographic_features: list[EntityResult] = Field(default_factory=list)

    geological_entities: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 5. EVENTS AND SPORTS
    # ==========================================

    events: list[EntityResult] = Field(default_factory=list)

    sports_entities: list[EntityResult] = Field(default_factory=list)

    awards: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 6. TRANSPORTATION AND INFRASTRUCTURE
    # ==========================================

    vehicles: list[EntityResult] = Field(default_factory=list)

    transportation_infrastructure: list[EntityResult] = Field(
        default_factory=list
    )

    # ==========================================
    # 7. LIVING ORGANISMS AND BIOLOGICAL ENTITIES
    # ==========================================

    animals: list[EntityResult] = Field(default_factory=list)

    birds: list[EntityResult] = Field(default_factory=list)

    plants: list[EntityResult] = Field(default_factory=list)

    trees: list[EntityResult] = Field(default_factory=list)

    fungi: list[EntityResult] = Field(default_factory=list)

    microorganisms: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 8. PHYSICAL STATES OF MATTER
    # ==========================================

    solids: list[EntityResult] = Field(default_factory=list)

    liquids: list[EntityResult] = Field(default_factory=list)

    gases: list[EntityResult] = Field(default_factory=list)

    plasmas: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 9. CHEMICAL, MATERIAL AND NATURAL RESOURCES
    # ==========================================

    chemical_substances: list[EntityResult] = Field(default_factory=list)

    elements_compounds: list[EntityResult] = Field(default_factory=list)

    minerals_rocks: list[EntityResult] = Field(default_factory=list)

    mixtures: list[EntityResult] = Field(default_factory=list)

    materials_substances: list[EntityResult] = Field(default_factory=list)

    energy_resources: list[EntityResult] = Field(default_factory=list)

    food_beverages: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 10. SCIENCE AND TECHNOLOGY
    # ==========================================

    technologies: list[EntityResult] = Field(default_factory=list)

    scientific_entities: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 11. HEALTHCARE AND LIFE SCIENCES
    # ==========================================

    healthcare_entities: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 12. EDUCATION AND FINANCIAL ENTITIES
    # ==========================================

    education_entities: list[EntityResult] = Field(default_factory=list)

    financial_entities: list[EntityResult] = Field(default_factory=list)

    economic_indicators: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 13. LEGAL AND INTELLECTUAL PROPERTY
    # ==========================================

    legal_entities: list[EntityResult] = Field(default_factory=list)

    intellectual_property: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 14. MEDIA, ARTS AND ENTERTAINMENT
    # ==========================================

    media_entities: list[EntityResult] = Field(default_factory=list)

    arts_entertainment_entities: list[EntityResult] = Field(
        default_factory=list
    )

    cultural_entities: list[EntityResult] = Field(default_factory=list)

    languages: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 15. ENVIRONMENT AND NATURAL PHENOMENA
    # ==========================================

    environmental_entities: list[EntityResult] = Field(default_factory=list)

    weather_climate_entities: list[EntityResult] = Field(
        default_factory=list
    )

    natural_phenomena: list[EntityResult] = Field(default_factory=list)

    astronomical_entities: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 16. BUILDINGS AND PHYSICAL INFRASTRUCTURE
    # ==========================================

    buildings_facilities: list[EntityResult] = Field(default_factory=list)

    physical_objects: list[EntityResult] = Field(default_factory=list)

    machinery_equipment: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 17. DIGITAL AND CONCEPTUAL ENTITIES
    # ==========================================

    digital_entities: list[EntityResult] = Field(default_factory=list)

    campaigns_initiatives: list[EntityResult] = Field(default_factory=list)

    concepts_movements: list[EntityResult] = Field(default_factory=list)

    data_digital_assets: list[EntityResult] = Field(default_factory=list)

    # ==========================================
    # 18. EXTENSIBILITY
    # ==========================================

    other_entities: list[EntityResult] = Field(
        default_factory=list,
        description=(
            "Identifiable entities that do not fit any existing "
            "group. Preserve their specific entity_type."
        )
    )
