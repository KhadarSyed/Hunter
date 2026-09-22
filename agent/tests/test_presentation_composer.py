"""Tests for Presentation Composer: generation, slide operations, layout/visual
selection, confidence scoring, flow analysis, validation, review workflow,
and persistence."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import presentation_composer as pc
from agent.app import evidence_library as elib
from agent.app import insight_generator as igen
from agent.app import storyline_builder as sbuilder


DEFAULT_OBJECTIVES = [
    {"objective_id": "RO1", "objective": "Understand trends", "title": "Trends",
     "priority": "high", "platforms": ["Reddit", "Twitter/X"]},
    {"objective_id": "RO2", "objective": "Compare brands", "title": "Brand Comparison",
     "priority": "medium", "platforms": ["Reddit"]},
]
DEFAULT_UNITS = [
    {"id": "EU1", "objective_id": "RO1", "recommended_method": "Theme Clustering"},
    {"id": "EU2", "objective_id": "RO2", "recommended_method": "Sentiment Analysis"},
]


class PCTestCase(unittest.TestCase):
    """Common lifecycle + fixtures for all PC tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="pc_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test_memory.db")
        store.init_intelligence_db()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _create_project(self):
        spec = {"commissioning_brand": {"name": "TestBrand"}, "project_name": "TestBrand"}
        return store.get_or_create_project(spec)

    def _create_full_pipeline(self):
        """Build a project through evidence → insights → approved storyline + SI slides."""
        pid = self._create_project()

        plan = {
            "plan_summary": "Test plan",
            "research_objectives": DEFAULT_OBJECTIVES,
            "execution_units": DEFAULT_UNITS,
        }
        plan_id = store.save_research_plan(pid, plan, source="deterministic")
        store.approve_plan(plan_id, "test")

        run_id = store.create_execution_run(pid, plan_id, 2)
        store.update_execution_run(run_id, status="completed")

        for i in range(3):
            store.save_evidence(
                run_id, unit_id="EU1", objective_id="RO1",
                evidence_type="finding", method="Theme Clustering",
                platform="Reddit", source="Reddit Post", date="2026-03-01",
                text_excerpt=f"Evidence item {i} about brand trends finding {i}.",
                metrics={"likes": i, "url": f"http://example.com/pc-{i}"},
                confidence="high", rationale="Test.",
            )

        elib.ingest_evidence(pid, run_id)
        items = store.list_library_items(pid)
        elib.bulk_review([it["id"] for it in items], "accepted", "test")

        igen.generate_insights(pid)
        for ins in store.list_insights(pid):
            igen.review_insight(ins["id"], "approved", "test")

        result = sbuilder.generate_storyline(pid)
        storyline_id = result["storyline_id"]
        store.update_storyline(storyline_id, status="approved")

        si_pres_id = store.create_si_presentation("deck.pptx", "/tmp/deck.pptx", 1024)
        si_slide_id = store.create_si_slide(
            si_pres_id, 1,
            all_text="Brand growth analysis",
            title_text="Brand Growth",
            body_text="Analysis content",
            shape_count=5, text_shape_count=3,
            chart_count=1, table_count=0,
            image_count=0, placeholder_count=2,
        )
        store.update_si_slide(si_slide_id, purpose="key_finding",
                             layout_type="title_body", visual_type="bar_chart")

        return pid, storyline_id


# ─── Constant Tests ─────────────────────────────────────────────────────

class TestConstants(PCTestCase):
    def test_slide_purposes_count(self):
        self.assertEqual(len(pc.SLIDE_PURPOSES), 17)

    def test_content_block_types_count(self):
        self.assertEqual(len(pc.CONTENT_BLOCK_TYPES), 16)

    def test_visual_types_count(self):
        self.assertEqual(len(pc.VISUAL_TYPES), 20)

    def test_flow_stages_count(self):
        self.assertEqual(len(pc.FLOW_STAGES), 8)

    def test_section_purpose_map_complete(self):
        for section, purpose in pc._SECTION_TO_SLIDE_PURPOSE.items():
            self.assertIn(purpose, pc.SLIDE_PURPOSES,
                          f"Purpose '{purpose}' for section '{section}' not in SLIDE_PURPOSES")

    def test_section_flow_map_complete(self):
        for section, stage in pc._SECTION_TO_FLOW_STAGE.items():
            self.assertIn(stage, pc.FLOW_STAGES,
                          f"Stage '{stage}' for section '{section}' not in FLOW_STAGES")

    def test_purpose_visual_map_covers_all(self):
        for p in pc.SLIDE_PURPOSES:
            self.assertIn(p, pc._PURPOSE_VISUAL_MAP)

    def test_purpose_duration_covers_all(self):
        for p in pc.SLIDE_PURPOSES:
            self.assertIn(p, pc._PURPOSE_DURATION)


# ─── Prerequisites ──────────────────────────────────────────────────────

class TestPrerequisites(PCTestCase):
    def test_no_storyline_blocks(self):
        pid = self._create_project()
        result = pc.validate_prerequisites(pid)
        self.assertFalse(result["valid"])
        self.assertTrue(any("storyline" in b.lower() for b in result["blockers"]))

    def test_all_prereqs_met(self):
        pid, _ = self._create_full_pipeline()
        result = pc.validate_prerequisites(pid)
        self.assertTrue(result["valid"])


# ─── Generation ─────────────────────────────────────────────────────────

class TestGeneration(PCTestCase):
    def test_generate_fails_without_prereqs(self):
        pid = self._create_project()
        result = pc.generate_presentation(pid)
        self.assertIn("error", result)
        self.assertIn("blockers", result)

    def test_generate_succeeds(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        self.assertNotIn("error", result)
        self.assertIn("presentation_id", result)
        self.assertGreaterEqual(result["slides_created"], 3)
        self.assertGreater(result["estimated_duration_minutes"], 0)

    def test_generate_creates_cover_and_agenda(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        slides = store.list_pc_slides(result["presentation_id"])
        purposes = [s["slide_purpose"] for s in slides]
        self.assertEqual(purposes[0], "cover")
        self.assertEqual(purposes[1], "agenda")

    def test_generate_creates_conclusion_if_missing(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        slides = store.list_pc_slides(result["presentation_id"])
        purposes = [s["slide_purpose"] for s in slides]
        self.assertIn("conclusion", purposes)

    def test_generate_persists_presentation(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        pres = store.get_pc_presentation(result["presentation_id"])
        self.assertIsNotNone(pres)
        self.assertEqual(pres["status"], "draft")
        self.assertEqual(pres["project_id"], pid)

    def test_generate_creates_audit_entry(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        audit = store.get_pc_audit(result["presentation_id"])
        self.assertGreater(len(audit), 0)
        self.assertEqual(audit[0]["action"], "generated")

    def test_generate_slide_has_content_blocks(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        slides = store.list_pc_slides(result["presentation_id"])
        content_slide = [s for s in slides if s["slide_purpose"] not in ("cover", "agenda")][0]
        blocks = content_slide.get("content_blocks_json")
        self.assertIsNotNone(blocks)
        self.assertIsInstance(blocks, list)
        self.assertGreater(len(blocks), 0)

    def test_generate_slide_has_confidence(self):
        pid, _ = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        slides = store.list_pc_slides(result["presentation_id"])
        content_slide = [s for s in slides if s["slide_purpose"] not in ("cover", "agenda")][0]
        conf = content_slide.get("confidence_json")
        self.assertIsNotNone(conf)
        self.assertIn("evidence_coverage", conf)
        self.assertIn("storyline_coverage", conf)
        self.assertIn("overall", conf)
        self.assertGreater(conf["overall"], 0)


# ─── Visual Selection ──────────────────────────────────────────────────

class TestVisualSelection(PCTestCase):
    def test_si_chart_takes_priority(self):
        result = pc._select_visual("key_finding", "text_only", "bar_chart", [], [1])
        self.assertEqual(result, "bar_chart")

    def test_si_visual_over_default(self):
        result = pc._select_visual("key_finding", "heatmap", None, [], [1])
        self.assertEqual(result, "heatmap")

    def test_text_only_fallback_to_purpose_default(self):
        result = pc._select_visual("trend", "text_only", None, [], [1])
        self.assertEqual(result, "line_chart")

    def test_no_evidence_fallback(self):
        result = pc._select_visual("cover", "text_only", None, [], [])
        self.assertEqual(result, "kpi_cards")

    def test_invalid_chart_ignored(self):
        result = pc._select_visual("key_finding", "text_only", "not_a_chart", [], [1])
        self.assertEqual(result, "bar_chart")


# ─── Layout Explanation ─────────────────────────────────────────────────

class TestLayoutExplanation(PCTestCase):
    def test_basic_explanation(self):
        text = pc._explain_layout("title_body", "key_findings", [])
        self.assertIn("title_body", text)
        self.assertIn("key findings", text)

    def test_none_layout_returns_empty(self):
        self.assertEqual(pc._explain_layout(None, "key_findings", []), "")

    def test_historical_match_mentioned(self):
        historical = [{"layout_type": "title_body"}, {"layout_type": "other"}]
        text = pc._explain_layout("title_body", "key_findings", historical)
        self.assertIn("historical", text)


# ─── Confidence Scoring ─────────────────────────────────────────────────

class TestConfidenceScoring(PCTestCase):
    def test_full_confidence(self):
        conf = pc._compute_confidence(
            [1, 2, 3, 4, 5],
            [{"confidence_score": 0.9}, {"confidence_score": 0.8}],
            [{"similarity_score": 0.8}],
            "bar_chart",
            "title_body",
        )
        self.assertGreater(conf["overall"], 0.7)
        self.assertGreaterEqual(conf["evidence_coverage"], 0.9)
        self.assertGreaterEqual(conf["storyline_coverage"], 0.9)
        self.assertGreaterEqual(conf["historical_layout_match"], 0.5)

    def test_low_evidence_flagged(self):
        conf = pc._compute_confidence([], [], [], "kpi_cards", "title_body")
        self.assertLess(conf["evidence_coverage"], 0.5)
        self.assertIn("low_confidence_reasons", conf)

    def test_no_historical_low_match(self):
        conf = pc._compute_confidence([1], [{"confidence_score": 0.7}], [], "bar_chart", "title_body")
        self.assertLessEqual(conf["historical_layout_match"], 0.3)

    def test_weights_sum_correctly(self):
        conf = pc._compute_confidence([1, 2, 3], [{"confidence_score": 0.9}], [], "bar_chart", "title_body")
        expected = round(
            conf["evidence_coverage"] * 0.30 +
            conf["storyline_coverage"] * 0.25 +
            conf["historical_layout_match"] * 0.25 +
            conf["visual_suitability"] * 0.20, 3,
        )
        self.assertAlmostEqual(conf["overall"], expected, places=2)


# ─── Content Blocks ─────────────────────────────────────────────────────

class TestContentBlocks(PCTestCase):
    def test_exec_summary_blocks(self):
        node = {"title": "Summary", "purpose": "Summarize findings",
                "narrative_summary": "Key narrative"}
        insights = [{"title": "Insight 1"}, {"title": "Insight 2"}]
        blocks = pc._build_content_blocks("executive_summary", node, insights, [1])
        types = [b["type"] for b in blocks]
        self.assertIn("title", types)
        self.assertIn("executive_summary", types)
        self.assertIn("metrics", types)

    def test_recommendation_blocks(self):
        node = {"title": "Recs", "narrative_summary": "Take action"}
        insights = [{"title": "Rec 1"}, {"title": "Rec 2"}]
        blocks = pc._build_content_blocks("recommendation", node, insights, [])
        types = [b["type"] for b in blocks]
        self.assertIn("recommendation", types)

    def test_evidence_panel_included(self):
        node = {"title": "Finding", "narrative_summary": "Evidence shows..."}
        blocks = pc._build_content_blocks("key_finding", node, [], [1, 2, 3])
        types = [b["type"] for b in blocks]
        self.assertIn("evidence_panel", types)
        self.assertIn("source", types)

    def test_no_evidence_no_panel(self):
        node = {"title": "Finding", "narrative_summary": "No evidence"}
        blocks = pc._build_content_blocks("key_finding", node, [], [])
        types = [b["type"] for b in blocks]
        self.assertNotIn("evidence_panel", types)


# ─── Slide Operations ──────────────────────────────────────────────────

class TestSlideOperations(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_update_slide_title(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        slide_id = slides[0]["id"]
        updated = pc.update_slide(slide_id, {"title": "New Title"})
        self.assertEqual(updated["title"], "New Title")

    def test_update_slide_invalid_field_rejected(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        slide_id = slides[0]["id"]
        result = pc.update_slide(slide_id, {"presentation_id": 999})
        self.assertIn("error", result)

    def test_update_nonexistent_slide(self):
        result = pc.update_slide(99999, {"title": "x"})
        self.assertIn("error", result)

    def test_select_layout(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        content_slides = [s for s in slides if s["slide_purpose"] not in ("cover", "agenda")]
        if content_slides:
            sid = content_slides[0]["id"]
            updated = pc.select_layout(sid, "two_column", "Better for comparison")
            self.assertEqual(updated["layout_recommendation"], "two_column")

    def test_select_visual(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        content_slides = [s for s in slides if s["slide_purpose"] not in ("cover", "agenda")]
        if content_slides:
            sid = content_slides[0]["id"]
            updated = pc.select_visual(sid, "heatmap")
            self.assertEqual(updated["recommended_visual"], "heatmap")

    def test_select_layout_creates_audit(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        content_slides = [s for s in slides if s["slide_purpose"] not in ("cover", "agenda")]
        if content_slides:
            sid = content_slides[0]["id"]
            pc.select_layout(sid, "two_column")
            audit = store.get_pc_audit(res["presentation_id"])
            layout_entries = [a for a in audit if a["action"] == "layout_changed"]
            self.assertGreater(len(layout_entries), 0)


# ─── Review Workflow ────────────────────────────────────────────────────

class TestReviewWorkflow(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_approve_slide(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        updated = pc.review_slide(slides[0]["id"], "approved")
        self.assertEqual(updated["status"], "approved")

    def test_reject_slide(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        updated = pc.review_slide(slides[0]["id"], "rejected")
        self.assertEqual(updated["status"], "rejected")

    def test_invalid_status_rejected(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        result = pc.review_slide(slides[0]["id"], "invalid_status")
        self.assertIn("error", result)

    def test_lock_slide(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        updated = pc.lock_slide(slides[0]["id"])
        self.assertEqual(updated["is_locked"], 1)

    def test_unlock_slide(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        pc.lock_slide(slides[0]["id"])
        updated = pc.unlock_slide(slides[0]["id"])
        self.assertEqual(updated["is_locked"], 0)

    def test_approve_presentation(self):
        res = self._generate()
        updated = pc.approve_presentation(res["presentation_id"])
        self.assertEqual(updated["status"], "approved")
        self.assertIsNotNone(updated.get("approved_by"))

    def test_reject_presentation(self):
        res = self._generate()
        updated = pc.reject_presentation(res["presentation_id"])
        self.assertEqual(updated["status"], "rejected")


# ─── Reorder ────────────────────────────────────────────────────────────

class TestReorder(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_reorder_slides(self):
        res = self._generate()
        slides = store.list_pc_slides(res["presentation_id"])
        ids = [s["id"] for s in slides]
        reversed_ids = list(reversed(ids))
        result = pc.reorder_slides(res["presentation_id"], reversed_ids)
        self.assertTrue(result.get("reordered"))

    def test_reorder_invalid_slide(self):
        res = self._generate()
        result = pc.reorder_slides(res["presentation_id"], [99999])
        self.assertIn("error", result)

    def test_reorder_nonexistent_presentation(self):
        result = pc.reorder_slides(99999, [1, 2])
        self.assertIn("error", result)


# ─── Transitions ────────────────────────────────────────────────────────

class TestTransitions(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_generate_transitions(self):
        res = self._generate()
        tr = pc.generate_transitions(res["presentation_id"])
        self.assertGreater(tr["transitions_updated"], 0)

    def test_transitions_populate_slides(self):
        res = self._generate()
        pc.generate_transitions(res["presentation_id"])
        slides = store.list_pc_slides(res["presentation_id"])
        with_transition = [s for s in slides if s.get("transition_to_next")]
        self.assertGreater(len(with_transition), 0)


# ─── Validation ─────────────────────────────────────────────────────────

class TestValidation(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_valid_presentation(self):
        res = self._generate()
        v = pc.validate_presentation(res["presentation_id"])
        self.assertTrue(v["valid"])

    def test_nonexistent_presentation(self):
        v = pc.validate_presentation(99999)
        self.assertFalse(v["valid"])
        self.assertTrue(any("not found" in i for i in v["issues"]))

    def test_warns_missing_sections(self):
        res = self._generate()
        v = pc.validate_presentation(res["presentation_id"])
        self.assertIsInstance(v.get("warnings"), list)


# ─── Detail & Summary ──────────────────────────────────────────────────

class TestDetailAndSummary(PCTestCase):
    def _generate(self):
        pid, _ = self._create_full_pipeline()
        return pc.generate_presentation(pid)

    def test_get_detail(self):
        res = self._generate()
        detail = pc.get_presentation_detail(res["presentation_id"])
        self.assertIn("presentation", detail)
        self.assertIn("slides", detail)
        self.assertIn("flow_analysis", detail)
        self.assertIn("total_duration_minutes", detail)
        self.assertGreater(detail["total_duration_minutes"], 0)

    def test_detail_flow_analysis(self):
        res = self._generate()
        detail = pc.get_presentation_detail(res["presentation_id"])
        flow = detail["flow_analysis"]
        self.assertIn("stages_present", flow)
        self.assertIn("stages_missing", flow)
        self.assertIn("flow_complete", flow)

    def test_get_summary(self):
        pid, _ = self._create_full_pipeline()
        res = pc.generate_presentation(pid)
        summary = pc.get_presentation_summary(pid)
        self.assertEqual(summary["presentation_count"], 1)
        self.assertEqual(summary["latest_status"], "draft")
        self.assertGreater(summary["total_slides"], 0)
        self.assertGreater(summary["total_duration_minutes"], 0)

    def test_summary_no_presentation(self):
        pid = self._create_project()
        summary = pc.get_presentation_summary(pid)
        self.assertEqual(summary["presentation_count"], 0)
        self.assertIsNone(summary["latest_status"])

    def test_detail_nonexistent(self):
        detail = pc.get_presentation_detail(99999)
        self.assertIn("error", detail)


# ─── Store CRUD ─────────────────────────────────────────────────────────

class TestStoreCRUD(PCTestCase):
    def test_create_and_get_presentation(self):
        pid = store.create_pc_presentation(
            1, 1, "Test Pres",
            executive_summary="Summary",
        )
        pres = store.get_pc_presentation(pid)
        self.assertIsNotNone(pres)
        self.assertEqual(pres["title"], "Test Pres")
        self.assertEqual(pres["status"], "draft")

    def test_list_presentations(self):
        store.create_pc_presentation(1, 1, "Pres 1")
        store.create_pc_presentation(1, 1, "Pres 2")
        plist = store.list_pc_presentations(1)
        self.assertEqual(len(plist), 2)

    def test_get_latest_presentation(self):
        store.create_pc_presentation(1, 1, "Pres 1")
        store.create_pc_presentation(1, 1, "Pres 2")
        latest = store.get_latest_pc_presentation(1)
        self.assertEqual(latest["title"], "Pres 2")

    def test_update_presentation(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        store.update_pc_presentation(pid, status="approved", total_slides=10)
        pres = store.get_pc_presentation(pid)
        self.assertEqual(pres["status"], "approved")
        self.assertEqual(pres["total_slides"], 10)

    def test_delete_presentation(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        store.delete_pc_presentation(pid)
        self.assertIsNone(store.get_pc_presentation(pid))

    def test_create_and_get_slide(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        sid = store.create_pc_slide(
            pid, 0, "cover", "Cover Slide",
            narrative="Test narrative",
            content_blocks=[{"type": "title", "content": "Hello"}],
            confidence={"overall": 0.9},
            overall_confidence=0.9,
        )
        slide = store.get_pc_slide(sid)
        self.assertIsNotNone(slide)
        self.assertEqual(slide["title"], "Cover Slide")
        self.assertEqual(slide["slide_purpose"], "cover")
        self.assertIsInstance(slide["content_blocks_json"], list)
        self.assertIsInstance(slide["confidence_json"], dict)

    def test_list_slides(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        store.create_pc_slide(pid, 0, "cover", "Slide 1", overall_confidence=1.0)
        store.create_pc_slide(pid, 1, "agenda", "Slide 2", overall_confidence=1.0)
        slides = store.list_pc_slides(pid)
        self.assertEqual(len(slides), 2)

    def test_update_slide(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        sid = store.create_pc_slide(pid, 0, "cover", "Old", overall_confidence=1.0)
        store.update_pc_slide(sid, title="New Title", status="approved")
        slide = store.get_pc_slide(sid)
        self.assertEqual(slide["title"], "New Title")
        self.assertEqual(slide["status"], "approved")

    def test_reorder_slides_store(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        s1 = store.create_pc_slide(pid, 0, "cover", "S1", overall_confidence=1.0)
        s2 = store.create_pc_slide(pid, 1, "agenda", "S2", overall_confidence=1.0)
        store.reorder_pc_slides(pid, [s2, s1])
        slides = store.list_pc_slides(pid)
        self.assertEqual(slides[0]["id"], s2)
        self.assertEqual(slides[1]["id"], s1)

    def test_count_slides(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        store.create_pc_slide(pid, 0, "cover", "S1", overall_confidence=1.0)
        store.create_pc_slide(pid, 1, "agenda", "S2", overall_confidence=1.0)
        self.assertEqual(store.count_pc_slides(pid), 2)

    def test_audit_trail(self):
        pid = store.create_pc_presentation(1, 1, "Test")
        store.add_pc_audit(pid, action="test_action", field="test_field",
                          new_value="test_value", actor="tester")
        audit = store.get_pc_audit(pid)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "test_action")


# ─── Flow Analysis ──────────────────────────────────────────────────────

class TestFlowAnalysis(PCTestCase):
    def test_empty_slides(self):
        flow = pc._analyze_flow([])
        self.assertEqual(len(flow["stages_present"]), 0)
        self.assertEqual(len(flow["stages_missing"]), 8)
        self.assertFalse(flow["flow_complete"])

    def test_many_stages_present(self):
        slides = [
            {"slide_purpose": "executive_summary"},
            {"slide_purpose": "situation"},
            {"slide_purpose": "competitive_perspective"},
            {"slide_purpose": "key_findings"},
            {"slide_purpose": "risks"},
            {"slide_purpose": "recommendations"},
            {"slide_purpose": "conclusion"},
        ]
        flow = pc._analyze_flow(slides)
        self.assertGreaterEqual(len(flow["stages_present"]), 6)
        self.assertEqual(flow["total_slides"], 7)

    def test_partial_stages(self):
        slides = [
            {"slide_purpose": "cover"},
            {"slide_purpose": "context"},
        ]
        flow = pc._analyze_flow(slides)
        self.assertFalse(flow["flow_complete"])
        self.assertGreater(len(flow["stages_missing"]), 0)


# ─── Helper Functions ───────────────────────────────────────────────────

class TestHelpers(PCTestCase):
    def test_extract_key_message_from_insights(self):
        insights = [
            {"title": "Low", "confidence_score": 0.3, "executive_summary": "Low summary"},
            {"title": "High", "confidence_score": 0.9, "executive_summary": "High summary"},
        ]
        msg = pc._extract_key_message({"narrative_summary": "fallback"}, insights)
        self.assertEqual(msg, "High summary")

    def test_extract_key_message_fallback(self):
        msg = pc._extract_key_message({"narrative_summary": "Node narrative"}, [])
        self.assertEqual(msg, "Node narrative")

    def test_build_speaker_notes(self):
        notes = pc._build_speaker_notes(
            "key_finding",
            {"transition_text": "Next we look at..."},
            [{"title": "Insight A"}, {"title": "Insight B"}],
        )
        self.assertIn("2 approved insight", notes)
        self.assertIn("Next we look at", notes)

    def test_infer_business_objective(self):
        obj = pc._infer_business_objective("key_finding", {})
        self.assertIn("research", obj.lower())

    def test_build_presentation_title(self):
        title = pc._build_presentation_title({"title": "My Story"}, None)
        self.assertEqual(title, "My Story")


if __name__ == "__main__":
    unittest.main()
