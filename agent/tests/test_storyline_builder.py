"""Tests for storyline_builder: prerequisites validation, storyline generation,
narrative pattern selection, node generation, merge/split, reordering,
review workflow, validation, detail/summary, and store CRUD."""
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
from agent.app import storyline_builder as sbuilder


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


class StorylineTestCase(unittest.TestCase):
    """Common DB lifecycle + fixture helpers for storyline tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="storyline_test_")
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

    def setup_with_approved_insights(self, insight_count=3):
        """Full pipeline through to approved insights.
        Returns (project_id, insight_ids).
        """
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id, complete=True)
        for i in range(insight_count):
            self.make_evidence(
                run_id,
                text_excerpt=f"Evidence item {i} about snacking occasions finding {i}.",
                metrics={"likes": i, "url": f"http://example.com/thread-{200 + i}"},
                platform="Reddit" if i % 2 == 0 else "Twitter/X",
            )
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        elib.bulk_review([it["id"] for it in items], "accepted", "test")
        igen.generate_insights(pid)
        insights = store.list_insights(pid)
        for ins in insights:
            igen.review_insight(ins["id"], "approved", "test")
        return pid, [ins["id"] for ins in insights]


# ─── Prerequisites ─────────────────────────────────────────────────────────

class TestPrerequisites(StorylineTestCase):
    def test_no_plan_blocks(self):
        pid = self.make_project()
        result = sbuilder.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("plan" in b.lower() for b in result["blockers"]))

    def test_no_approved_insights_blocks(self):
        pid = self.make_project()
        plan_id = self.make_plan(pid)
        run_id = self.make_run(pid, plan_id)
        self.make_evidence(run_id, metrics={"likes": 1, "url": "http://example.com/t-300"})
        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        elib.bulk_review([it["id"] for it in items], "accepted", "test")
        igen.generate_insights(pid)
        result = sbuilder.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("approved insights" in b.lower() for b in result["blockers"]))

    def test_all_met_passes(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.validate_prerequisites(pid)
        self.assertTrue(result["valid"])


# ─── Pattern Selection ─────────────────────────────────────────────────────

class TestPatternSelection(StorylineTestCase):
    def test_default_executive_briefing(self):
        insights = [{"insight_type": "behavioural"}]
        result = sbuilder._select_narrative_pattern(insights)
        self.assertEqual(result, "executive_briefing")

    def test_crisis_pattern(self):
        insights = [{"insight_type": "crisis"}, {"insight_type": "crisis"}, {"insight_type": "risk"}]
        result = sbuilder._select_narrative_pattern(insights)
        self.assertEqual(result, "crisis_analysis")

    def test_brand_pattern(self):
        insights = [{"insight_type": "brand"}, {"insight_type": "brand"}]
        result = sbuilder._select_narrative_pattern(insights)
        self.assertEqual(result, "brand_health_review")

    def test_competitive_pattern(self):
        insights = [{"insight_type": "competitive"}, {"insight_type": "competitive"}]
        result = sbuilder._select_narrative_pattern(insights)
        self.assertEqual(result, "competitive_landscape")

    def test_consumer_pattern(self):
        insights = [
            {"insight_type": "audience"}, {"insight_type": "audience"},
            {"insight_type": "behavioural"},
        ]
        result = sbuilder._select_narrative_pattern(insights)
        self.assertEqual(result, "consumer_insights")


# ─── Storyline Generation ─────────────────────────────────────────────────

class TestStorylineGeneration(StorylineTestCase):
    def test_generate_creates_storyline(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        self.assertNotIn("error", result)
        self.assertIn("storyline_id", result)
        self.assertGreaterEqual(result["nodes_created"], 1)
        self.assertIn("narrative_pattern", result)

    def test_generate_fails_without_prereqs(self):
        pid = self.make_project()
        result = sbuilder.generate_storyline(pid)
        self.assertIn("error", result)
        self.assertIn("blockers", result)

    def test_generated_storyline_has_nodes(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        storyline = store.get_storyline(result["storyline_id"])
        self.assertIsNotNone(storyline)
        self.assertEqual(storyline["status"], "draft")
        nodes = store.list_story_nodes(result["storyline_id"])
        self.assertGreaterEqual(len(nodes), 1)

    def test_nodes_have_required_fields(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        nodes = store.list_story_nodes(result["storyline_id"])
        for node in nodes:
            for field in ("title", "section_type", "order_position",
                          "suggested_visual", "priority", "status"):
                self.assertIn(field, node, f"Missing field: {field}")

    def test_nodes_have_insights_mapped(self):
        pid, insight_ids = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        nodes = store.list_story_nodes(result["storyline_id"])
        all_mapped = set()
        for node in nodes:
            node_insights = store.get_node_insights(node["id"])
            for m in node_insights:
                all_mapped.add(m["insight_id"])
        self.assertGreaterEqual(len(all_mapped), 1)

    def test_total_duration_calculated(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        self.assertGreater(result["total_duration_minutes"], 0)
        storyline = store.get_storyline(result["storyline_id"])
        self.assertGreater(storyline["total_duration_minutes"], 0)

    def test_audit_trail_on_generation(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        audit = store.get_storyline_audit(result["storyline_id"])
        self.assertGreaterEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "generated")


# ─── Node Operations ──────────────────────────────────────────────────────

class TestNodeOperations(StorylineTestCase):
    def _generate_storyline(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        return pid, result["storyline_id"]

    def test_reorder_nodes(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        if len(nodes) < 2:
            self.skipTest("Need at least 2 nodes to test reorder")
        reversed_ids = [n["id"] for n in reversed(nodes)]
        result = sbuilder.reorder_nodes(sid, reversed_ids)
        self.assertNotIn("error", result)
        self.assertTrue(result["reordered"])

    def test_reorder_nonexistent_storyline(self):
        result = sbuilder.reorder_nodes(99999, [1, 2])
        self.assertIn("error", result)

    def test_merge_nodes(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        if len(nodes) < 2:
            self.skipTest("Need at least 2 nodes to test merge")
        id_a, id_b = nodes[0]["id"], nodes[1]["id"]
        result = sbuilder.merge_nodes(id_a, id_b)
        self.assertNotIn("error", result)
        self.assertIsNone(store.get_story_node(id_b))
        merged = store.get_story_node(id_a)
        self.assertIn("&", merged["title"])

    def test_merge_nonexistent_node(self):
        result = sbuilder.merge_nodes(99999, 99998)
        self.assertIn("error", result)

    def test_split_node(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        long_node = None
        for n in nodes:
            narrative = n.get("narrative_summary") or ""
            if narrative.count(".") >= 2:
                long_node = n
                break
        if not long_node:
            self.skipTest("No node with enough content to split")
        result = sbuilder.split_node(long_node["id"])
        self.assertNotIn("error", result)
        self.assertIn("original_node", result)
        self.assertIn("new_node", result)

    def test_split_short_node_fails(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "conclusion", "Short", 0,
                                       narrative_summary="One sentence only")
        result = sbuilder.split_node(nid)
        self.assertIn("error", result)


# ─── Review Workflow ───────────────────────────────────────────────────────

class TestReviewWorkflow(StorylineTestCase):
    def _generate_storyline(self):
        pid, _ = self.setup_with_approved_insights()
        result = sbuilder.generate_storyline(pid)
        return pid, result["storyline_id"]

    def test_approve_node(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        result = sbuilder.review_node(nodes[0]["id"], "approved")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "approved")

    def test_reject_node(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        result = sbuilder.review_node(nodes[0]["id"], "rejected")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "rejected")

    def test_invalid_node_status(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        result = sbuilder.review_node(nodes[0]["id"], "bogus")
        self.assertIn("error", result)

    def test_review_nonexistent_node(self):
        result = sbuilder.review_node(99999, "approved")
        self.assertIn("error", result)

    def test_approve_storyline(self):
        _, sid = self._generate_storyline()
        result = sbuilder.approve_storyline(sid)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "approved")
        self.assertIsNotNone(result.get("approved_at"))

    def test_reject_storyline(self):
        _, sid = self._generate_storyline()
        result = sbuilder.reject_storyline(sid)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "rejected")

    def test_approve_nonexistent_storyline(self):
        result = sbuilder.approve_storyline(99999)
        self.assertIn("error", result)

    def test_review_creates_audit(self):
        _, sid = self._generate_storyline()
        nodes = store.list_story_nodes(sid)
        sbuilder.review_node(nodes[0]["id"], "approved", "analyst")
        audit = store.get_storyline_audit(sid)
        actions = [a["action"] for a in audit]
        self.assertIn("node_review", actions)


# ─── Validation ────────────────────────────────────────────────────────────

class TestValidation(StorylineTestCase):
    def test_valid_storyline(self):
        pid, _ = self.setup_with_approved_insights()
        gen = sbuilder.generate_storyline(pid)
        result = sbuilder.validate_storyline(gen["storyline_id"])
        self.assertTrue(result["valid"])

    def test_nonexistent_storyline(self):
        result = sbuilder.validate_storyline(99999)
        self.assertFalse(result["valid"])

    def test_empty_storyline_fails(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Empty")
        result = sbuilder.validate_storyline(sid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no story nodes" in i.lower() for i in result["issues"]))

    def test_duplicate_title_detected(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        store.create_story_node(sid, "key_findings", "Same Title", 0,
                                narrative_summary="First content.")
        store.create_story_node(sid, "risks", "Same Title", 1,
                                narrative_summary="Second content.")
        result = sbuilder.validate_storyline(sid)
        self.assertTrue(any("duplicate" in i.lower() for i in result.get("issues", [])))


# ─── Detail & Summary ─────────────────────────────────────────────────────

class TestDetailAndSummary(StorylineTestCase):
    def test_get_detail(self):
        pid, _ = self.setup_with_approved_insights()
        gen = sbuilder.generate_storyline(pid)
        detail = sbuilder.get_storyline_detail(gen["storyline_id"])
        self.assertIn("storyline", detail)
        self.assertIn("nodes", detail)
        self.assertIn("audit_history", detail)
        self.assertGreaterEqual(len(detail["nodes"]), 1)
        for node in detail["nodes"]:
            self.assertIn("insights", node)
            self.assertIn("insight_count", node)

    def test_detail_nonexistent(self):
        result = sbuilder.get_storyline_detail(99999)
        self.assertIn("error", result)

    def test_get_summary(self):
        pid, _ = self.setup_with_approved_insights()
        sbuilder.generate_storyline(pid)
        summary = sbuilder.get_storyline_summary(pid)
        self.assertGreaterEqual(summary["storyline_count"], 1)
        self.assertGreaterEqual(summary["total_nodes"], 1)
        self.assertGreater(summary["total_duration_minutes"], 0)
        self.assertIsNotNone(summary["latest_pattern"])

    def test_summary_empty_project(self):
        pid = self.make_project()
        summary = sbuilder.get_storyline_summary(pid)
        self.assertEqual(summary["storyline_count"], 0)
        self.assertIsNone(summary["latest_pattern"])


# ─── Store Functions ───────────────────────────────────────────────────────

class TestStorylineStore(StorylineTestCase):
    def test_create_and_get_storyline(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test Storyline")
        s = store.get_storyline(sid)
        self.assertIsNotNone(s)
        self.assertEqual(s["title"], "Test Storyline")
        self.assertEqual(s["status"], "draft")

    def test_get_latest_storyline(self):
        pid = self.make_project()
        store.create_storyline(pid, "executive_briefing", "First")
        store.create_storyline(pid, "crisis_analysis", "Second")
        latest = store.get_latest_storyline(pid)
        self.assertEqual(latest["title"], "Second")

    def test_update_storyline(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        store.update_storyline(sid, status="approved", approved_by="analyst")
        s = store.get_storyline(sid)
        self.assertEqual(s["status"], "approved")
        self.assertIsNotNone(s["approved_at"])

    def test_delete_storyline_cascades(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Node", 0)
        store.add_storyline_audit(sid, action="test", actor="test")
        store.delete_storyline(sid)
        self.assertIsNone(store.get_storyline(sid))
        self.assertIsNone(store.get_story_node(nid))
        self.assertEqual(len(store.get_storyline_audit(sid)), 0)

    def test_create_and_get_node(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Key Findings", 0,
                                       purpose="Present findings",
                                       narrative_summary="The findings show...",
                                       is_key_message=True)
        node = store.get_story_node(nid)
        self.assertIsNotNone(node)
        self.assertEqual(node["title"], "Key Findings")
        self.assertTrue(node["is_key_message"])
        self.assertFalse(node["is_locked"])

    def test_list_nodes_ordered(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        store.create_story_node(sid, "conclusion", "Last", 2)
        store.create_story_node(sid, "executive_summary", "First", 0)
        store.create_story_node(sid, "key_findings", "Middle", 1)
        nodes = store.list_story_nodes(sid)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0]["title"], "First")
        self.assertEqual(nodes[1]["title"], "Middle")
        self.assertEqual(nodes[2]["title"], "Last")

    def test_update_node(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Test", 0)
        store.update_story_node(nid, status="approved", reviewed_by="analyst",
                                 is_key_message=True)
        node = store.get_story_node(nid)
        self.assertEqual(node["status"], "approved")
        self.assertTrue(node["is_key_message"])
        self.assertIsNotNone(node["reviewed_at"])

    def test_delete_node_cascades(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Test", 0)
        iid = store.create_insight(pid, "RO1", "behavioural", "Ins")
        store.add_node_insight(nid, iid)
        store.delete_story_node(nid)
        self.assertIsNone(store.get_story_node(nid))
        self.assertEqual(len(store.get_node_insights(nid)), 0)

    def test_node_insight_mapping(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Test", 0)
        iid = store.create_insight(pid, "RO1", "behavioural", "Insight A")
        mid = store.add_node_insight(nid, iid)
        mappings = store.get_node_insights(nid)
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["insight_id"], iid)
        self.assertEqual(mappings[0]["insight_title"], "Insight A")
        store.remove_node_insight(nid, iid)
        self.assertEqual(len(store.get_node_insights(nid)), 0)

    def test_reorder_respects_locked(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        n1 = store.create_story_node(sid, "executive_summary", "ES", 0)
        n2 = store.create_story_node(sid, "key_findings", "KF", 1)
        store.update_story_node(n1, is_locked=True)
        store.reorder_story_nodes(sid, [n2, n1])
        node1 = store.get_story_node(n1)
        self.assertEqual(node1["order_position"], 0)

    def test_audit_trail(self):
        pid = self.make_project()
        sid = store.create_storyline(pid, "executive_briefing", "Test")
        nid = store.create_story_node(sid, "key_findings", "Test", 0)
        store.add_storyline_audit(sid, action="test", node_id=nid,
                                   field="status", new_value="draft", actor="system")
        audit = store.get_storyline_audit(sid)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "test")
        self.assertEqual(audit[0]["node_id"], nid)


if __name__ == "__main__":
    unittest.main()
