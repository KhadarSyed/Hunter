"""Tests for web_research_adapter: entity validation, source classification, date parsing, dedup."""
from __future__ import annotations

import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.web_research_adapter import (
    EntityValidator,
    _classify_source_tier,
    _parse_date,
    _deduplicate_results,
    _is_blocked,
    build_search_queries,
)


@pytest.fixture
def validator():
    return EntityValidator("Mrs. T's Pierogies", "frozen food", "US")


class TestEntityValidator:
    def test_rejects_mrs_doubtfire(self, validator):
        result = validator.validate("Mrs. Doubtfire Review: Still a Classic", "The film Mrs. Doubtfire", "https://imdb.com/mrs-doubtfire")
        assert result["relevant"] is False

    def test_rejects_mrs_fields(self, validator):
        result = validator.validate("Mrs. Fields Cookies Opens New Store", "cookies", "https://example.com/cookies")
        assert result["relevant"] is False

    def test_rejects_mr_t_actor(self, validator):
        result = validator.validate("Mr. T Returns to Television", "The actor Mr. T", "https://example.com/mr-t")
        assert result["relevant"] is False

    def test_accepts_mrs_ts_pierogies(self, validator):
        result = validator.validate("Mrs. T's Pierogies Launches New Flavor", "frozen foods", "https://example.com/mrsts")
        assert result["relevant"] is True

    def test_rejects_grammar_honorific(self, validator):
        result = validator.validate("How to Address a Mrs. vs Ms.", "grammar etiquette", "https://example.com/grammar")
        assert result["relevant"] is False

    def test_accepts_relevant_result(self, validator):
        result = validator.validate("Frozen Pierogi Sales Rise in 2026", "Mrs. T's leads the category", "https://example.com/sales")
        assert result["relevant"] is True


class TestSourceClassification:
    def test_tier1_government(self):
        assert _classify_source_tier("https://www.fda.gov/food/safety") == "tier_1"

    def test_tier1_wire_service(self):
        assert _classify_source_tier("https://apnews.com/article/frozen-food") == "tier_1"

    def test_tier1_major_paper(self):
        assert _classify_source_tier("https://www.nytimes.com/2026/01/food") == "tier_1"

    def test_tier2_trade(self):
        assert _classify_source_tier("https://www.progressivegrocer.com/frozen") == "tier_2"

    def test_tier3_blog(self):
        assert _classify_source_tier("https://medium.com/pierogies") == "tier_3"

    def test_tier3_unknown_defaults(self):
        assert _classify_source_tier("https://obscure-site.example.com") == "tier_3"

    def test_tier1_edu(self):
        assert _classify_source_tier("https://research.harvard.edu/paper") == "tier_1"


class TestDateParsing:
    def test_iso_date(self):
        dt = _parse_date("2026-03-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_us_date(self):
        dt = _parse_date("03/15/2026")
        assert dt is not None

    def test_long_date(self):
        dt = _parse_date("March 15, 2026")
        assert dt is not None

    def test_invalid_date(self):
        assert _parse_date("not a date") is None

    def test_empty_date(self):
        assert _parse_date("") is None

    def test_iso_with_time(self):
        dt = _parse_date("2026-03-15T14:30:00")
        assert dt is not None
        assert dt.day == 15


class TestDeduplication:
    def test_dedup_by_url(self):
        results = [
            {"url": "https://example.com/a", "title": "Article A"},
            {"url": "https://example.com/a", "title": "Article A Copy"},
            {"url": "https://example.com/b", "title": "Article B"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 2

    def test_dedup_by_title_hash(self):
        results = [
            {"url": "https://a.com/1", "title": "Mrs. T's launches new flavor"},
            {"url": "https://b.com/2", "title": "Mrs. T's launches new flavor"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 1

    def test_no_dedup_needed(self):
        results = [
            {"url": "https://a.com/1", "title": "Article A"},
            {"url": "https://b.com/2", "title": "Article B"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 2


class TestBlockedDomains:
    def test_blocked_wikipedia(self):
        assert _is_blocked("https://en.wikipedia.org/wiki/Pierogi") is True

    def test_blocked_indian_tld(self):
        assert _is_blocked("https://example.co.in/food") is True

    def test_blocked_social(self):
        assert _is_blocked("https://twitter.com/MrsTsPierogies") is True

    def test_allowed_domain(self):
        assert _is_blocked("https://www.nytimes.com/article") is False

    def test_blocked_reddit(self):
        assert _is_blocked("https://www.reddit.com/r/food") is True

    def test_allowed_trade_pub(self):
        assert _is_blocked("https://www.progressivegrocer.com/article") is False


class TestQueryGeneration:
    def test_build_queries_returns_list(self):
        queries = build_search_queries(
            brand_name="Mrs. T's",
            parent_company=None,
            category="frozen food",
            products=["pierogies"],
            geography="US",
            audience="moms",
            research_questions=["What are moms' priorities?"],
        )
        assert isinstance(queries, list)
        assert len(queries) >= 3

    def test_queries_have_required_fields(self):
        queries = build_search_queries(
            brand_name="TestBrand",
            parent_company=None,
            category="consumer goods",
            products=[],
            geography="US",
            audience="consumers",
            research_questions=["Test question"],
        )
        for q in queries:
            assert "query" in q
            assert "family" in q
            assert len(q["query"]) > 0
