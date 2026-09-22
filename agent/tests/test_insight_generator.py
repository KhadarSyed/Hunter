"""Tests for insight_generator: prerequisites validation, insight generation,
evidence traceability, confidence calculation, contradiction detection,
insight classification, review workflow, regeneration, quality validation,
and summary metrics."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import evidence_library as elib
from agent.app import insight_generator as igen


DEFAULT_OBJECTIVES = [
    {
        "objective_id": "RO1",
        "objective": "Understand snack occasions",
        "title": "Snack Occasions",
        "priority": "high",
        "platforms": ["Reddit", "Twitter/X"],
    },
    {
        "objective_id": "RO2",
        "objective": "Compare chip brand loyalty",
        "title": "Brand Comparison",
        "priority": "medium",
        "platforms": ["Reddit"],
    },
]

DEFAULT_UNITS = [
    {"id": "EU1", "objective_id": "RO1", "recommended_method": "Theme Clustering"},
    {"id": "EU2", "objective_id": "RO2", "recommended_method": "Sentiment Analysis"},
]


class InsightTestCase(unittest.TestCase):
    """Common DB lifecycle + fixture builders for insight tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="insight_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test_memory.db")
        store.init_intelligence_db()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def make_project(self, name="TestBrand"):
        spec = {"commissioning_brand": {"name": name}, "project_name": name}
        return store.get_or_create_project(spec)

    def make_plan(self, project_id, objectives=None, units=None, approve=True):
        plan = {
            "plan_summary": "Test plan",
            "research_objectives": DEFAULT_OBJECTIVES if objectives is None else objectives,
            "execution_units": DEFAULT_UNITS if units is None else units,
        }
        plan_id = store.save_research_plan(project_id, plan, source="deterministic")
        if approve:
            store.approve_plan(plan_id, "test")
        return plan_id

    def make_run(self, project_id, plan_id, total_units=2, complete=True):
        run_id = store.create_execution_run(project_id, plan_id, total_units)
        if complete:
            store.update_execution_run(run_id, status="completed")
        return run_id

    def make_evidence(self, run_id, **overrides):
        fields = {
            "unit_id": "EU1",
            "objective_id": "RO1",
            "evidence_type": "finding",
            "method": "Theme Clustering",
            "platform": "Reddit",
            "source": "Reddit Post",
            "date": "2026-03-01",
            "text_excerpt": "Consumers love snacking on chips during movie nights.",
            "metrics": {"likes": 10, "url": "http://example.com/thread-1"},
            "confidence": "high",
            "rationale": "Representative finding.",
        }
        fields.update(overrides)
        return store.save_evidence(run_id, **fields)

    def setup_full_pipeline(self, evidence_count=3, accept=True):
        """Create project, approved plan, completed run, ingested+accepted evidence.
        Returns (project_id, plan_id, run_id, library_item_ids).
        """
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id, complete=True)
        for i in range(evidence_count):
            self.make_evidence(
                run_id,
                text_excerpt=f"Evidence item {i} about snacking occasions finding {i}.",
                metrics={"likes": i, "url": f"http://example.com/thread-{100 + i}"},
                platform="Reddit" if i % 2 == 0 else "Twitter/X",
            )
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        item_ids = [it["id"] for it in items]
        if accept:
            elib.bulk_review(item_ids, "accepted", "test")
        return pid, plan_id, run_id, item_ids


# ─── Prerequisites ─────────────────────────────────────────────────────────

class TestPrerequisites(InsightTestCase):
    def test_no_plan_blocks(self):
        pid = self.make_project()
        result = igen.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("plan" in b.lower() for b in result["blockers"]))

    def test_unapproved_plan_blocks(self):
        pid = self.make_project()
        self.make_plan(pid, approve=False)
        result = igen.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("not approved" in b.lower() for b in result["blockers"]))

    def test_no_execution_run_blocks(self):
        pid = self.make_project()
        self.make_plan(pid)
        result = igen.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("execution" in b.lower() for b in result["blockers"]))

    def test_incomplete_run_blocks(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        self.make_run(pid, plan_id, complete=False)
        result = igen.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("not completed" in b.lower() for b in result["blockers"]))

    def test_empty_library_blocks(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        self.make_run(pid, plan_id, complete=True)
        result = igen.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("empty" in b.lower() for b in result["blockers"]))

    def test_all_met_passes(self):
        pid, _, _, _ = self.setup_full_pipeline()
        result = igen.validate_prerequisites(pid)
        self.assertTrue(result["valid"])


# ─── Insight Generation ────────────────────────────────────────────────────

class TestInsightGeneration(InsightTestCase):
    def test_generate_creates_insights(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        result = igen.generate_insights(pid)
        self.assertNotIn("error", result)
        self.assertGreaterEqual(result["generated"], 1)
        self.assertEqual(result["objectives_covered"], 1)
        self.assertIn("generation_id", result)

    def test_generate_fails_without_prereqs(self):
        pid = self.make_project()
        result = igen.generate_insights(pid)
        self.assertIn("error", result)
        self.assertIn("blockers", result)

    def test_generated_insight_has_required_fields(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        self.assertGreaterEqual(len(insights), 1)
        ins = insights[0]
        for field in ("title", "executive_summary", "observation", "interpretation",
                      "business_impact", "confidence_score", "status", "objective_id",
                      "insight_type", "evidence_count"):
            self.assertIn(field, ins, f"Missing field: {field}")
        self.assertEqual(ins["status"], "draft")

    def test_generated_insight_has_evidence_mapped(self):
        pid, _, _, item_ids = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        self.assertGreaterEqual(len(insights), 1)
        evidence = store.get_insight_evidence(insights[0]["id"])
        self.assertGreaterEqual(len(evidence), 1)

    def test_skips_objectives_with_no_accepted_evidence(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id, complete=True)
        self.make_evidence(run_id, objective_id="RO1",
                           metrics={"likes": 1, "url": "http://example.com/t-200"})
        self.make_evidence(run_id, objective_id="RO2",
                           metrics={"likes": 2, "url": "http://example.com/t-201"})
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        ro1_items = [it["id"] for it in items if it.get("objective_id") == "RO1"]
        elib.bulk_review(ro1_items, "accepted", "test")
        result = igen.generate_insights(pid)
        self.assertEqual(result["objectives_covered"], 1)
        self.assertEqual(result["objectives_skipped"], 1)

    def test_audit_trail_on_generation(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=2)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        audit = store.get_insight_audit(insights[0]["id"])
        self.assertGreaterEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "generated")


# ─── Evidence Traceability ─────────────────────────────────────────────────

class TestEvidenceTraceability(InsightTestCase):
    def test_evidence_ids_traceable(self):
        pid, _, _, item_ids = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        evidence = store.get_insight_evidence(insights[0]["id"])
        mapped_ids = {e["library_item_id"] for e in evidence}
        for iid in item_ids:
            self.assertIn(iid, mapped_ids)

    def test_evidence_roles_assigned(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        evidence = store.get_insight_evidence(insights[0]["id"])
        roles = {e["role"] for e in evidence}
        self.assertTrue(roles.issubset({"supporting", "contradictory"}))

    def test_get_supporting_evidence(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        supporting = igen.get_supporting_evidence(insights[0]["id"])
        for e in supporting:
            self.assertEqual(e["role"], "supporting")


# ─── Confidence Calculation ────────────────────────────────────────────────

class TestConfidenceCalculation(InsightTestCase):
    def test_confidence_range(self):
        items = [
            {"platform": "Reddit", "confidence": "high", "quality_score": 0.9, "id": 1, "text_excerpt": "positive growth"},
            {"platform": "Twitter/X", "confidence": "medium", "quality_score": 0.7, "id": 2, "text_excerpt": "some data"},
        ]
        score, rationale = igen._calculate_confidence(items)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertIn("evidence_count", rationale)

    def test_empty_evidence_zero_confidence(self):
        score, rationale = igen._calculate_confidence([])
        self.assertEqual(score, 0.0)

    def test_more_evidence_higher_confidence(self):
        base = {"platform": "Reddit", "confidence": "high", "quality_score": 0.8, "text_excerpt": "good stuff"}
        small = [dict(base, id=i) for i in range(1, 3)]
        large = [dict(base, id=i) for i in range(1, 8)]
        score_s, _ = igen._calculate_confidence(small)
        score_l, _ = igen._calculate_confidence(large)
        self.assertGreater(score_l, score_s)

    def test_multi_platform_higher_confidence(self):
        single = [
            {"platform": "Reddit", "confidence": "high", "quality_score": 0.8, "id": 1, "text_excerpt": "good"},
            {"platform": "Reddit", "confidence": "high", "quality_score": 0.8, "id": 2, "text_excerpt": "also good"},
        ]
        multi = [
            {"platform": "Reddit", "confidence": "high", "quality_score": 0.8, "id": 1, "text_excerpt": "good"},
            {"platform": "Twitter/X", "confidence": "high", "quality_score": 0.8, "id": 2, "text_excerpt": "also good"},
        ]
        score_s, _ = igen._calculate_confidence(single)
        score_m, _ = igen._calculate_confidence(multi)
        self.assertGreater(score_m, score_s)


# ─── Contradiction Detection ──────────────────────────────────────────────

class TestContradictionDetection(InsightTestCase):
    def test_no_contradictions_when_uniform(self):
        items = [
            {"id": 1, "text_excerpt": "Strong growth and positive reception"},
            {"id": 2, "text_excerpt": "Increase in trust and opportunity"},
        ]
        text, ids = igen._detect_contradictions(items)
        self.assertIsNone(text)
        self.assertEqual(ids, [])

    def test_detects_contradictions(self):
        items = [
            {"id": 1, "text_excerpt": "Strong growth and positive reception"},
            {"id": 2, "text_excerpt": "Decline and failure observed, weak performance"},
        ]
        text, ids = igen._detect_contradictions(items)
        self.assertIsNotNone(text)
        self.assertIn("contradictory", text.lower())
        self.assertGreater(len(ids), 0)

    def test_minority_camp_is_contradicting(self):
        items = [
            {"id": 1, "text_excerpt": "Strong growth and positive success"},
            {"id": 2, "text_excerpt": "Benefit and advantage gained"},
            {"id": 3, "text_excerpt": "Decline and failure, weak outlook"},
        ]
        text, ids = igen._detect_contradictions(items)
        self.assertIsNotNone(text)
        self.assertIn(3, ids)
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)

    def test_contradiction_penalty_lowers_confidence(self):
        uniform = [
            {"id": 1, "platform": "Reddit", "confidence": "high", "quality_score": 0.8, "text_excerpt": "Strong growth"},
            {"id": 2, "platform": "Reddit", "confidence": "high", "quality_score": 0.8, "text_excerpt": "Positive success"},
        ]
        mixed = [
            {"id": 1, "platform": "Reddit", "confidence": "high", "quality_score": 0.8, "text_excerpt": "Strong growth"},
            {"id": 2, "platform": "Reddit", "confidence": "high", "quality_score": 0.8, "text_excerpt": "Decline failure weak"},
        ]
        score_u, _ = igen._calculate_confidence(uniform)
        score_m, _ = igen._calculate_confidence(mixed)
        self.assertGreater(score_u, score_m)


# ─── Insight Type Classification ───────────────────────────────────────────

class TestClassification(InsightTestCase):
    def test_audience_classification(self):
        obj = {"objective": "Understand audience segments and demographic preferences"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "audience")

    def test_crisis_classification(self):
        obj = {"objective": "Identify crisis risk factors"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "crisis")

    def test_trend_classification(self):
        obj = {"objective": "Track emerging trends in the market"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "trend")

    def test_brand_classification(self):
        obj = {"objective": "Evaluate brand perception and reputation"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "brand")

    def test_competitive_classification(self):
        obj = {"objective": "Analyze competitive landscape"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "competitive")

    def test_media_classification(self):
        obj = {"objective": "Track media coverage of the product launch"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "media")

    def test_opportunity_classification(self):
        obj = {"objective": "Identify growth opportunity in new markets"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "opportunity")

    def test_default_behavioural(self):
        obj = {"objective": "General research question about consumer patterns"}
        result = igen._classify_insight_type(obj, [])
        self.assertEqual(result, "behavioural")


# ─── Review Workflow ───────────────────────────────────────────────────────

class TestReviewWorkflow(InsightTestCase):
    def _generate_one(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        return pid, insights[0]["id"]

    def test_approve_insight(self):
        _, iid = self._generate_one()
        result = igen.review_insight(iid, "approved", "analyst")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["reviewed_by"], "analyst")
        self.assertIsNotNone(result.get("reviewed_at"))

    def test_reject_insight(self):
        _, iid = self._generate_one()
        result = igen.review_insight(iid, "rejected", "analyst", notes="Not compelling")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "rejected")

    def test_invalid_status_rejected(self):
        _, iid = self._generate_one()
        result = igen.review_insight(iid, "bogus_status")
        self.assertIn("error", result)

    def test_review_nonexistent_insight(self):
        result = igen.review_insight(99999, "approved")
        self.assertIn("error", result)

    def test_request_revision(self):
        _, iid = self._generate_one()
        result = igen.request_revision(iid, "Needs more detail", "analyst")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["analyst_notes"], "Needs more detail")

    def test_update_analyst_notes(self):
        _, iid = self._generate_one()
        result = igen.update_analyst_notes(iid, "Check platform coverage", "analyst")
        self.assertNotIn("error", result)
        self.assertEqual(result["analyst_notes"], "Check platform coverage")

    def test_review_creates_audit(self):
        _, iid = self._generate_one()
        igen.review_insight(iid, "approved", "analyst")
        audit = store.get_insight_audit(iid)
        actions = [a["action"] for a in audit]
        self.assertIn("review", actions)

    def test_revision_creates_audit(self):
        _, iid = self._generate_one()
        igen.request_revision(iid, "Needs work", "analyst")
        audit = store.get_insight_audit(iid)
        actions = [a["action"] for a in audit]
        self.assertIn("revision_requested", actions)


# ─── Regeneration ──────────────────────────────────────────────────────────

class TestRegeneration(InsightTestCase):
    def test_regenerate_replaces_insight(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        old_id = insights[0]["id"]
        result = igen.regenerate_insight(old_id)
        self.assertNotIn("error", result)
        self.assertIsNone(store.get_insight(old_id))
        new_insights = store.list_insights(pid)
        self.assertGreaterEqual(len(new_insights), 1)
        self.assertNotEqual(new_insights[0]["id"], old_id)

    def test_regenerate_nonexistent(self):
        result = igen.regenerate_insight(99999)
        self.assertIn("error", result)

    def test_regenerate_creates_audit(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        old_id = insights[0]["id"]
        new_insight = igen.regenerate_insight(old_id)
        audit = store.get_insight_audit(new_insight["id"])
        actions = [a["action"] for a in audit]
        self.assertIn("regenerated", actions)


# ─── Detail & Summary ─────────────────────────────────────────────────────

class TestDetailAndSummary(InsightTestCase):
    def test_get_insight_detail(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        detail = igen.get_insight_detail(insights[0]["id"])
        self.assertIn("insight", detail)
        self.assertIn("evidence", detail)
        self.assertIn("supporting_evidence", detail)
        self.assertIn("contradictory_evidence", detail)
        self.assertIn("audit_history", detail)

    def test_detail_nonexistent(self):
        result = igen.get_insight_detail(99999)
        self.assertIn("error", result)

    def test_get_insights_summary(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        summary = igen.get_insights_summary(pid)
        self.assertGreaterEqual(summary["total_insights"], 1)
        self.assertIn("by_status", summary)
        self.assertIn("by_type", summary)
        self.assertIn("avg_confidence", summary)
        self.assertIn("objectives_covered", summary)
        self.assertGreaterEqual(summary["objectives_covered"], 1)

    def test_summary_empty_project(self):
        pid = self.make_project()
        summary = igen.get_insights_summary(pid)
        self.assertEqual(summary["total_insights"], 0)
        self.assertEqual(summary["avg_confidence"], 0.0)


# ─── Quality Validation ───────────────────────────────────────────────────

class TestQualityValidation(InsightTestCase):
    def test_valid_insight_passes(self):
        pid, _, _, _ = self.setup_full_pipeline(evidence_count=3)
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        result = igen.validate_insight_quality(insights[0]["id"])
        self.assertTrue(result["valid"])

    def test_nonexistent_insight_fails(self):
        result = igen.validate_insight_quality(99999)
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["issues"]), 0)

    def test_single_platform_warning(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id, complete=True)
        for i in range(3):
            self.make_evidence(
                run_id, platform="Reddit",
                text_excerpt=f"Single platform evidence {i}",
                metrics={"likes": i, "url": f"http://example.com/thread-{300 + i}"},
            )
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        elib.bulk_review([it["id"] for it in items], "accepted", "test")
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        result = igen.validate_insight_quality(insights[0]["id"])
        self.assertTrue(any("single-platform" in w.lower() for w in result.get("warnings", [])))


# ─── Store Functions ───────────────────────────────────────────────────────

class TestInsightStore(InsightTestCase):
    def test_create_and_get(self):
        pid = self.make_project()
        iid = store.create_insight(pid, "RO1", "behavioural", "Test Insight")
        ins = store.get_insight(iid)
        self.assertIsNotNone(ins)
        self.assertEqual(ins["title"], "Test Insight")
        self.assertEqual(ins["status"], "draft")

    def test_list_with_filters(self):
        pid = self.make_project()
        store.create_insight(pid, "RO1", "behavioural", "Insight A")
        store.create_insight(pid, "RO2", "trend", "Insight B")
        all_ins = store.list_insights(pid)
        self.assertEqual(len(all_ins), 2)
        filtered = store.list_insights(pid, objective_id="RO1")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["objective_id"], "RO1")

    def test_update_insight(self):
        pid = self.make_project()
        iid = store.create_insight(pid, "RO1", "behavioural", "Test")
        store.update_insight(iid, status="approved", reviewed_by="analyst")
        ins = store.get_insight(iid)
        self.assertEqual(ins["status"], "approved")
        self.assertIsNotNone(ins["reviewed_at"])

    def test_delete_cascades(self):
        pid = self.make_project()
        iid = store.create_insight(pid, "RO1", "behavioural", "Test")
        store.add_insight_audit(iid, action="test", actor="test")
        store.delete_insight(iid)
        self.assertIsNone(store.get_insight(iid))
        self.assertEqual(len(store.get_insight_audit(iid)), 0)

    def test_platforms_stored_as_json(self):
        pid = self.make_project()
        iid = store.create_insight(pid, "RO1", "behavioural", "Test",
                                   platforms_represented=["Reddit", "Twitter/X"])
        ins = store.get_insight(iid)
        self.assertIsInstance(ins["platforms_represented"], list)
        self.assertIn("Reddit", ins["platforms_represented"])

    def test_count_insights(self):
        pid = self.make_project()
        store.create_insight(pid, "RO1", "behavioural", "A")
        store.create_insight(pid, "RO1", "behavioural", "B")
        self.assertEqual(store.count_insights(pid), 2)
        store.update_insight(1, status="approved")
        self.assertEqual(store.count_insights(pid, status="approved"), 1)

    def test_status_counts(self):
        pid = self.make_project()
        i1 = store.create_insight(pid, "RO1", "behavioural", "A")
        i2 = store.create_insight(pid, "RO1", "trend", "B")
        store.update_insight(i1, status="approved")
        counts = store.get_insight_status_counts(pid)
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["by_status"].get("approved"), 1)
        self.assertEqual(counts["by_status"].get("draft"), 1)

    def test_evidence_mapping(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id)
        eid = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        iid = store.create_insight(pid, "RO1", "behavioural", "Test")
        mid = store.add_insight_evidence(iid, items[0]["id"], role="supporting")
        evidence = store.get_insight_evidence(iid)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["role"], "supporting")
        store.remove_insight_evidence(iid, items[0]["id"])
        self.assertEqual(len(store.get_insight_evidence(iid)), 0)

    def test_audit_trail(self):
        pid = self.make_project()
        iid = store.create_insight(pid, "RO1", "behavioural", "Test")
        store.add_insight_audit(iid, action="created", field="status",
                                old_value=None, new_value="draft", actor="system")
        audit = store.get_insight_audit(iid)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "created")
        self.assertEqual(audit[0]["new_value"], "draft")


if __name__ == "__main__":
    unittest.main()
