"""Tests for planner_service: prerequisite validation, deterministic plan
generation, execution units, and plan persistence."""
from __future__ import annotations

import json
import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import intelligence_store as store
from agent.app import config
from agent.app import planner_service


SAMPLE_SPEC = {
    "commissioning_brand": {
        "name": "TestBrand",
        "category": "Snacks",
        "products": ["Chips", "Pretzels"],
        "parent_company": "FoodCo",
    },
    "business_objective": "Understand snack preferences",
    "research_objective": "Map consumer snack behaviors",
    "research_questions": [
        {"question_id": "RQ1", "question": "What are the most popular snack occasions?", "priority": "primary"},
        {"question_id": "RQ2", "question": "How do consumers compare chip brands?", "priority": "primary"},
        {"question_id": "RQ3", "question": "Which platforms drive snack discovery?", "priority": "secondary"},
    ],
    "included_scope": {
        "platforms": ["Twitter/X", "Reddit", "Instagram"],
        "countries": ["United States"],
        "time_period": "Jan 2026 - Jun 2026",
        "languages": ["English"],
    },
    "excluded_scope": [
        {"description": "Generic recipe content"},
        {"description": "Wholesale bulk purchasing discussions"},
    ],
}


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    config.MEMORY_DB_PATH = tmp_path / "test_memory.db"
    store.init_intelligence_db()
    yield


def _create_project_with_all_prerequisites():
    pid = store.get_or_create_project(SAMPLE_SPEC)

    rid = store.save_background_research(pid, {
        "status": "completed",
        "web_search_executed": True,
        "news_items": [{"headline": "Test", "url": "http://example.com"}],
    }, None)
    store.approve_research(rid, "test")

    sid = store.save_search_strategy(pid, {
        "strategy_summary": "Test strategy",
        "core_queries": [{"type": "broad", "query": '"TestBrand"'}],
    })
    store.approve_strategy(sid, "test")

    eid = store.save_sample_evaluation(pid, sid, "sample.csv", "/tmp/sample.csv")
    store.update_evaluation(eid, {
        "status": "completed",
        "total_records": 200,
        "relevant_count": 150,
        "irrelevant_count": 50,
        "duplicate_count": 5,
        "detected_fields": ["content", "date", "source", "sentiment", "headline"],
        "platforms": ["Twitter/X", "Reddit"],
        "precision": 0.75,
    })

    return pid


class TestPrerequisiteValidation:
    def test_nonexistent_project(self):
        result = planner_service.validate_prerequisites(9999)
        assert result["ready"] is False
        assert result["prerequisites"]["brief_scope"]["status"] == "missing"

    def test_project_without_research(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        result = planner_service.validate_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["brief_scope"]["status"] == "approved"
        assert result["prerequisites"]["background_research"]["status"] == "missing"

    def test_unapproved_research(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        store.save_background_research(pid, {"status": "completed", "web_search_executed": True}, None)
        result = planner_service.validate_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["background_research"]["status"] == "pending"

    def test_missing_strategy(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        rid = store.save_background_research(pid, {"status": "completed"}, None)
        store.approve_research(rid, "test")
        result = planner_service.validate_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["search_strategy"]["status"] == "missing"

    def test_missing_dataset(self):
        pid = store.get_or_create_project(SAMPLE_SPEC)
        rid = store.save_background_research(pid, {"status": "completed"}, None)
        store.approve_research(rid, "test")
        sid = store.save_search_strategy(pid, {"strategy_summary": "test"})
        store.approve_strategy(sid, "test")
        result = planner_service.validate_prerequisites(pid)
        assert result["ready"] is False
        assert result["prerequisites"]["dataset"]["status"] == "missing"

    def test_all_prerequisites_met(self):
        pid = _create_project_with_all_prerequisites()
        result = planner_service.validate_prerequisites(pid)
        assert result["ready"] is True
        for v in result["prerequisites"].values():
            assert v["status"] == "approved"


class TestDeterministicPlan:
    def test_builds_plan_from_spec(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {
            "available": True,
            "total_records": 200,
            "relevant_records": 150,
            "fields": ["content", "date", "source"],
        })
        assert "plan_summary" in plan
        assert "research_objectives" in plan
        assert len(plan["research_objectives"]) == 3
        assert plan["_meta"]["source"] == "deterministic"

    def test_objective_ids_sequential(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        ids = [o["objective_id"] for o in plan["research_objectives"]]
        assert ids == ["RO1", "RO2", "RO3"]

    def test_question_ids_mapped(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        for obj in plan["research_objectives"]:
            assert len(obj["business_question_ids"]) == 1
            assert obj["business_question_ids"][0].startswith("RQ")

    def test_methods_selected_by_question(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        obj_compare = next(o for o in plan["research_objectives"] if "compare" in o["objective"].lower())
        assert "Platform Comparison" in obj_compare["methods"]

    def test_empty_spec_produces_empty_plan(self):
        plan = planner_service._build_deterministic_plan(
            {"commissioning_brand": {}, "research_questions": []}, {}, {}, {}
        )
        assert plan["research_objectives"] == []


class TestExecutionUnits:
    def test_units_created_for_objectives(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "relevant_records": 150,
            "fields": ["content", "date", "source"],
        })
        assert len(plan["execution_units"]) == 3

    def test_unit_has_required_fields(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "fields": ["content"],
        })
        unit = plan["execution_units"][0]
        for field in ["id", "title", "priority", "status", "estimated_complexity",
                      "estimated_runtime", "required_datasets", "required_fields",
                      "recommended_method", "expected_output", "confidence", "dependencies"]:
            assert field in unit, f"Missing field: {field}"

    def test_unit_references_objective(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {})
        for unit in plan["execution_units"]:
            assert unit["objective_id"].startswith("RO")


class TestFieldInference:
    def test_thematic_analysis_needs_content(self):
        fields = planner_service._infer_required_fields(["Thematic Analysis"])
        assert "content" in fields

    def test_sentiment_analysis_needs_sentiment(self):
        fields = planner_service._infer_required_fields(["Sentiment Analysis"])
        assert "sentiment" in fields

    def test_trend_analysis_needs_date(self):
        fields = planner_service._infer_required_fields(["Trend Analysis"])
        assert "date" in fields

    def test_multiple_methods_merge_fields(self):
        fields = planner_service._infer_required_fields(["Sentiment Analysis", "Trend Analysis"])
        assert "sentiment" in fields
        assert "date" in fields
        assert "source" in fields


class TestMethodSelection:
    def test_sentiment_question(self):
        m = planner_service._select_method_for_question("What is the sentiment around the brand?")
        assert m == "Thematic Analysis"

    def test_trend_question(self):
        m = planner_service._select_method_for_question("Are there seasonal trends in consumption?")
        assert m == "Trend Analysis"

    def test_compare_question(self):
        m = planner_service._select_method_for_question("How does TestBrand compare to competitors?")
        assert m == "Platform Comparison"

    def test_audience_question(self):
        m = planner_service._select_method_for_question("Who are the key audience segments?")
        assert "Segmentation" in m or "Comparison" in m

    def test_default_fallback(self):
        m = planner_service._select_method_for_question("Something completely unrelated and vague")
        assert m == "Thematic Analysis"


class TestValidation:
    def test_clean_plan(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "relevant_records": 150,
            "fields": ["content", "date", "source", "headline", "sentiment"],
        })
        assert plan["validation"]["status"] in ("clean", "warnings")

    def test_missing_fields_warning(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "relevant_records": 150,
            "fields": ["content"],
        })
        warnings = plan["validation"]["warnings"]
        field_warnings = [w for w in warnings if w.get("type") == "missing_fields"]
        assert len(field_warnings) > 0

    def test_low_sample_warning(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 50,
            "relevant_records": 20,
            "fields": ["content"],
        })
        warnings = plan["validation"]["warnings"]
        sample_warnings = [w for w in warnings if w.get("type") == "low_sample_size"]
        assert len(sample_warnings) == 1

    def test_question_coverage_counted(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "fields": ["content"],
        })
        assert plan["validation"]["question_coverage"] == "3/3"


class TestPlanPersistence:
    def test_save_and_retrieve_plan(self):
        pid = _create_project_with_all_prerequisites()
        plan_data = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan_id = store.save_research_plan(pid, plan_data, source="deterministic")
        assert plan_id > 0

        retrieved = store.get_latest_plan(pid)
        assert retrieved is not None
        assert retrieved["id"] == plan_id
        assert retrieved["source"] == "deterministic"
        assert retrieved["approval_status"] == "pending"

    def test_approve_plan(self):
        pid = _create_project_with_all_prerequisites()
        plan_data = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan_id = store.save_research_plan(pid, plan_data)
        assert store.approve_plan(plan_id, "tester") is True

        retrieved = store.get_latest_plan(pid)
        assert retrieved["approval_status"] == "approved"
        assert retrieved["approved_by"] == "tester"

    def test_reject_plan(self):
        pid = _create_project_with_all_prerequisites()
        plan_data = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        plan_id = store.save_research_plan(pid, plan_data)
        assert store.reject_plan(plan_id, "needs work") is True

        retrieved = store.get_latest_plan(pid)
        assert retrieved["approval_status"] == "rejected"
        assert retrieved["notes"] == "needs work"

    def test_nonexistent_plan(self):
        assert store.get_latest_plan(9999) is None

    def test_approve_nonexistent(self):
        assert store.approve_plan(9999) is False

    def test_reject_nonexistent(self):
        assert store.reject_plan(9999) is False


class TestDatasetMetadata:
    def test_extract_with_evaluation(self):
        meta = planner_service._extract_dataset_metadata({
            "evaluation": {
                "total_records": 200,
                "relevant_count": 150,
                "irrelevant_count": 50,
                "detected_fields": ["content", "date"],
                "platforms": ["Twitter/X"],
                "precision": 0.75,
            }
        })
        assert meta["available"] is True
        assert meta["total_records"] == 200
        assert "content" in meta["fields"]

    def test_extract_without_evaluation(self):
        meta = planner_service._extract_dataset_metadata(None)
        assert meta["available"] is False
        assert meta["total_records"] == 0

    def test_extract_empty_evaluation(self):
        meta = planner_service._extract_dataset_metadata({"evaluation": None})
        assert meta["available"] is False


class TestPlanEnrichment:
    def test_project_overview_added(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        enriched = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "relevant_records": 150,
            "fields": ["content"],
            "platforms": ["Twitter/X"],
        })
        assert "project_overview" in enriched
        assert enriched["project_overview"]["brand"] == "TestBrand"
        assert enriched["project_overview"]["category"] == "Snacks"

    def test_evidence_requirements_built(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        enriched = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {
            "total_records": 200,
            "relevant_records": 150,
        })
        assert "evidence_requirements" in enriched
        assert "mandatory" in enriched["evidence_requirements"]

    def test_analysis_methods_summary(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        enriched = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {})
        assert "analysis_methods" in enriched
        assert len(enriched["analysis_methods"]) > 0
        for m in enriched["analysis_methods"]:
            assert "method" in m
            assert "description" in m

    def test_deliverables_built(self):
        plan = planner_service._build_deterministic_plan(SAMPLE_SPEC, {}, {}, {})
        enriched = planner_service._enrich_plan_with_metadata(plan, SAMPLE_SPEC, {}, {}, {})
        assert "expected_deliverables" in enriched
        assert len(enriched["expected_deliverables"]) > 0
