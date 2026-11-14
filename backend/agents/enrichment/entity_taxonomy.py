
import re

from .entities import ContentEntities

# Known entity types and their expected groups.
# This is our initial taxonomy, which we can expand later.

ENTITY_TYPE_TO_GROUP = {

    # Commercial
    "brand": "brands",
    "sub_brand": "brands",
    "company": "companies",
    "organization": "organizations",
    "product": "products",
    "service": "services",
    "payment_service": "services",  

    # Government
    "government": "government_entities",
    "ministry": "government_entities",
    "regulator": "regulators",
    "military": "military_entities",

    # People
    "person": "persons",
    "executive": "persons",
    "athlete": "persons",
    "politician": "persons",
    "scientist": "persons",
    "celebrity": "persons",

    # Geography
    "location": "locations",
    "country": "locations",
    "state": "locations",
    "city": "locations",
    "region": "locations",
    "river": "geographic_features",
    "mountain": "geographic_features",

    # Events and sports
    "event": "events",
    "conference": "events",
    "festival": "events",
    "sport": "sports_entities",
    "team": "sports_entities",
    "cricket_team": "sports_entities",
    "sports_team": "sports_entities",
    "league": "sports_entities",
    "tournament": "sports_entities",
    "club": "sports_entities",
    "federation": "sports_entities",
    "award": "awards",

    # Transportation
    "vehicle": "vehicles",
    "car": "vehicles",
    "truck": "vehicles",
    "bus": "vehicles",
    "motorcycle": "vehicles",
    "aircraft": "vehicles",
    "ship": "vehicles",
    "train": "vehicles",
    "airport": "transportation_infrastructure",
    "bridge": "transportation_infrastructure",
    "road": "transportation_infrastructure",

    # Living organisms
    "animal": "animals",
    "mammal": "animals",
    "reptile": "animals",
    "fish": "animals",
    "insect": "animals",
    "amphibian": "animals",
    "bird": "birds",
    "plant": "plants",
    "tree": "trees",
    "fungus": "fungi",
    "microorganism": "microorganisms",
    "bacteria": "microorganisms",
    "virus": "microorganisms",

    # States of matter
    "solid": "solids",
    "liquid": "liquids",
    "gas": "gases",
    "plasma": "plasmas",

    # Chemistry and materials
    "chemical": "chemical_substances",
    "chemical_substance": "chemical_substances",
    "element": "elements_compounds",
    "compound": "elements_compounds",
    "mineral": "minerals_rocks",
    "rock": "minerals_rocks",
    "mixture": "mixtures",
    "alloy": "mixtures",
    "material": "materials_substances",
    "energy_resource": "energy_resources",
    "food": "food_beverages",
    "beverage": "food_beverages",

    # Science and technology
    "technology": "technologies",
    "software": "technologies",
    "hardware": "technologies",
    "artificial_intelligence": "technologies",
    "robot": "technologies",
    "research_study": "scientific_entities",
    "scientific_discovery": "scientific_entities",

    # Healthcare
    "disease": "healthcare_entities",
    "medicine": "healthcare_entities",
    "treatment": "healthcare_entities",
    "medical_device": "healthcare_entities",

    # Education
    "school": "education_entities",
    "college": "education_entities",
    "university": "education_entities",

    # Finance
    "bank": "financial_entities",
    "currency": "financial_entities",
    "stock": "financial_entities",
    "financial_instrument": "financial_entities",
    "gdp": "economic_indicators",
    "inflation_rate": "economic_indicators",

    # Legal
    "law": "legal_entities",
    "regulation": "legal_entities",
    "court_case": "legal_entities",
    "patent": "intellectual_property",
    "trademark": "intellectual_property",

    # Media and entertainment
    "newspaper": "media_entities",
    "publication": "media_entities",
    "podcast": "media_entities",
    "film": "arts_entertainment_entities",
    "book": "arts_entertainment_entities",
    "song": "arts_entertainment_entities",
    "fictional_character": "arts_entertainment_entities",

    # Environment and astronomy
    "ecosystem": "environmental_entities",
    "storm": "weather_climate_entities",
    "earthquake": "natural_phenomena",
    "planet": "astronomical_entities",
    "star": "astronomical_entities",

    # Infrastructure and objects
    "building": "buildings_facilities",
    "stadium": "buildings_facilities",
    "object": "physical_objects",
    "machine": "machinery_equipment",
    "machinery": "machinery_equipment",

    # Digital
    "website": "digital_entities",
    "mobile_app": "digital_entities",
    "social_platform": "digital_entities",
    "campaign": "campaigns_initiatives",
    "initiative": "campaigns_initiatives",
    "concept": "concepts_movements",
    "social_movement": "concepts_movements",
    "dataset": "data_digital_assets",
}


def normalize_entity_type(entity_type: str) -> str:
    """
    Convert entity types into a standard comparison format.
    """

    normalized = entity_type.strip().casefold()

    return re.sub(r"[\s\-]+", "_", normalized)


def validate_entity_group_assignments(
    entities: ContentEntities,
) -> dict[str, list[str]]:
    """
    Check whether known entity types are stored in
    their expected groups.

    Unknown entity types are retained and flagged
    for taxonomy review.
    """

    errors = []
    review_required = []

    entity_groups = type(entities).model_fields.keys()

    for group_name in entity_groups:

        group_entities = getattr(entities, group_name)

        for index, entity in enumerate(group_entities):

            entity_type = normalize_entity_type(entity.entity_type)

            expected_group = ENTITY_TYPE_TO_GROUP.get(entity_type)

            if expected_group is None:

                review_required.append(
                    f"Unknown entity type '{entity.entity_type}' "
                    f"in group '{group_name}' at index {index}."
                )

            elif expected_group != group_name:

                errors.append(
                    f"Entity '{entity.name}' has type "
                    f"'{entity.entity_type}' and belongs in "
                    f"'{expected_group}', not '{group_name}'."
                )

    return {
        "errors": errors,
        "review_required": review_required,
    }
