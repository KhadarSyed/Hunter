"""Per-article LLM labelling. Labels outside the schema become 'unknown'; nothing is invented."""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)
BATCH = 8
MAX_TEXT = 4000

SCHEMAS: dict[str, dict] = {
    "expert": {"list_field": "experts", "item": {
        "name": None, "expert_type": ["dermatologist", "pediatrician", "other_hcp", "non_hcp_expert"],
        "affiliation": ["affiliated", "independent"], "brand": None, "evidence": None}},
    "celebrity": {"list_field": "celebrities", "item": {
        "name": None, "role": ["spokesperson", "product_mention", "lifestyle"]}},
    "deal": {"list_field": "deals", "item": {
        "product": None, "retailer": None, "deal_type": ["discount", "freebie", "bundle"]}},
    "parenting": {"list_field": "topics", "item": {
        "topic": ["sun_safety", "eczema_dryness", "bathing", "diapering", "ingredients", "sleep_routine", "other"]}},
}

_INSTRUCTIONS = {
    "expert": "List every expert quoted or cited. expert_type: dermatologist, pediatrician, other_hcp "
              "(nurse, pharmacist, other clinician) or non_hcp_expert. affiliation: 'affiliated' only if the "
              "text states a tie to a brand (employee, consultant, paid partner, spokesperson) and name it in "
              "brand; 'independent' only if the text makes clear there is no brand tie; otherwise omit it. "
              "evidence: the exact short phrase that supports the label.",
    "celebrity": "List every celebrity named. role: spokesperson (paid/brand partner), product_mention, or lifestyle.",
    "deal": "List each promoted product with its retailer and deal_type (discount, freebie, bundle). retailer is "
            "the store or marketplace selling it (e.g. Amazon, Target, Walmart) — never the product's own brand; "
            "leave retailer empty if the text names no store.",
    "parenting": "List the parenting-advice topics covered.",
}


