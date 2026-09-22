"""Tests for PowerPoint Renderer: rendering pipeline, chart/table/image engines,
theme management, text overflow, placeholder fitting, branding, downloads,
render jobs, metrics, history, and validation."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import presentation_composer as pc
from agent.app import pptx_renderer as renderer
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


class RendererTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="renderer_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test_memory.db")
        config.DATA_DIR = self._tmpdir
        store.init_intelligence_db()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _create_project(self):
        spec = {"commissioning_brand": {"name": "TestBrand"}, "project_name": "TestBrand"}
        return store.get_or_create_project(spec)

    def _create_full_pipeline(self):
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
                metrics={"likes": i, "url": f"http://example.com/r-{i}"},
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

    def _create_presentation(self):
        pid, sid = self._create_full_pipeline()
        result = pc.generate_presentation(pid)
        return result["presentation_id"], pid


# ── Constants & Setup Tests ──────────────────────────────────────────

class TestConstants(RendererTestCase):
    def test_valid_job_types(self):
        self.assertEqual(renderer.VALID_JOB_TYPES, {"full", "slide", "section"})

    def test_valid_job_statuses(self):
        self.assertIn("pending", renderer.VALID_JOB_STATUSES)
        self.assertIn("completed", renderer.VALID_JOB_STATUSES)
        self.assertIn("failed", renderer.VALID_JOB_STATUSES)

    def test_chart_renderers_registry(self):
        self.assertIn("bar_chart", renderer.CHART_RENDERERS)
        self.assertIn("line_chart", renderer.CHART_RENDERERS)
        self.assertIn("pie", renderer.CHART_RENDERERS)
        self.assertIn("stacked_bar", renderer.CHART_RENDERERS)
        self.assertIn("scatter", renderer.CHART_RENDERERS)
        self.assertIn("bubble", renderer.CHART_RENDERERS)
        self.assertIn("area", renderer.CHART_RENDERERS)
        self.assertIn("donut", renderer.CHART_RENDERERS)

    def test_visual_renderers_registry(self):
        self.assertIn("bar_chart", renderer.VISUAL_RENDERERS)
        self.assertIn("table", renderer.VISUAL_RENDERERS)
        self.assertIn("kpi_cards", renderer.VISUAL_RENDERERS)
        self.assertIn("timeline", renderer.VISUAL_RENDERERS)
        self.assertIn("funnel", renderer.VISUAL_RENDERERS)
        self.assertIn("network", renderer.VISUAL_RENDERERS)
        self.assertIn("map", renderer.VISUAL_RENDERERS)
        self.assertIn("dashboard", renderer.VISUAL_RENDERERS)
        self.assertIn("matrix", renderer.VISUAL_RENDERERS)
        self.assertIn("heatmap", renderer.VISUAL_RENDERERS)

    def test_purpose_renderers(self):
        self.assertIn("cover", renderer.PURPOSE_RENDERERS)
        self.assertIn("conclusion", renderer.PURPOSE_RENDERERS)
        self.assertIn("appendix", renderer.PURPOSE_RENDERERS)

    def test_series_palette_length(self):
        self.assertEqual(len(renderer.SERIES_PALETTE), 8)

    def test_slide_dimensions(self):
        self.assertAlmostEqual(renderer.SLIDE_WIDTH_INCHES, 13.333, places=2)
        self.assertAlmostEqual(renderer.SLIDE_HEIGHT_INCHES, 7.5, places=1)


# ── Theme Tests ──────────────────────────────────────────────────────

class TestThemeManagement(RendererTestCase):
    def test_resolve_default_theme(self):
        theme = renderer._resolve_theme()
        self.assertIn("primary_color", theme)
        self.assertIn("font_heading", theme)

    def test_resolve_hunter_default(self):
        theme = renderer._resolve_theme("hunter_default")
        self.assertEqual(theme["primary_color"], "#5B2C9D")

    def test_resolve_nonexistent_falls_back(self):
        theme = renderer._resolve_theme("nonexistent_theme_xyz")
        self.assertIn("primary_color", theme)

    def test_hex_to_rgb(self):
        rgb = renderer._hex_to_rgb("#5B2C9D")
        self.assertEqual(rgb, renderer.VIOLET)

    def test_hex_to_rgb_no_hash(self):
        rgb = renderer._hex_to_rgb("1A1A1A")
        self.assertEqual(rgb, renderer.BLACK)

    def test_list_themes(self):
        themes = renderer.list_themes()
        self.assertGreaterEqual(len(themes), 1)
        names = [t["name"] for t in themes]
        self.assertIn("Hunter PR Default", names)

    def test_ensure_default_theme_idempotent(self):
        store.ensure_default_theme()
        store.ensure_default_theme()
        themes = store.list_themes()
        default_count = sum(1 for t in themes if t["id"] == "hunter_default")
        self.assertEqual(default_count, 1)


# ── Layout Engine Tests ──────────────────────────────────────────────

class TestLayoutEngine(RendererTestCase):
    def test_get_region_content_default(self):
        r = renderer._get_region("body")
        self.assertEqual(len(r), 4)
        self.assertAlmostEqual(r[0], 0.3)

    def test_get_region_cover(self):
        r = renderer._get_region("title", "cover")
        self.assertAlmostEqual(r[0], 0.8)
        self.assertAlmostEqual(r[1], 2.0)

    def test_get_region_divider(self):
        r = renderer._get_region("title", "divider")
        self.assertAlmostEqual(r[0], 0.8)
        self.assertAlmostEqual(r[1], 2.5)

    def test_get_region_unknown_falls_back(self):
        r = renderer._get_region("nonexistent_region")
        self.assertEqual(len(r), 4)

    def test_all_regions_have_4_values(self):
        for name, r in renderer.REGION_CONTENT.items():
            self.assertEqual(len(r), 4, f"Region {name} should have 4 values")
        for name, r in renderer.REGION_COVER.items():
            self.assertEqual(len(r), 4, f"Cover region {name} should have 4 values")
        for name, r in renderer.REGION_DIVIDER.items():
            self.assertEqual(len(r), 4, f"Divider region {name} should have 4 values")


# ── Text Engine Tests (via python-pptx) ──────────────────────────────

class TestTextEngine(RendererTestCase):
    def test_add_textbox(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        box = renderer._add_textbox(slide, 1, 1, 5, 1, "Hello World", font_size=16, bold=True)
        self.assertIsNotNone(box)
        self.assertEqual(box.text_frame.paragraphs[0].runs[0].text, "Hello World")

    def test_add_body_text(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        box = renderer._add_body_text(slide, ["Para one", "Para two", "Para three"])
        self.assertIsNotNone(box)
        paras = box.text_frame.paragraphs
        self.assertEqual(len(paras), 3)
        self.assertEqual(paras[0].runs[0].text, "Para one")

    def test_add_bullet_list(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        box = renderer._add_bullet_list(slide, ["Item A", "Item B"])
        self.assertIsNotNone(box)
        first_text = box.text_frame.paragraphs[0].runs[0].text
        self.assertTrue(first_text.startswith("•"))

    def test_add_speaker_notes(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        renderer._add_speaker_notes(slide, "These are speaker notes for the presenter.")
        notes_text = slide.notes_slide.notes_text_frame.text
        self.assertIn("speaker notes", notes_text)

    def test_add_speaker_notes_empty(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        renderer._add_speaker_notes(slide, "")
        self.assertTrue(True)


# ── Chart Engine Tests ───────────────────────────────────────────────

class TestChartEngine(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_bar_chart(self):
        prs, slide = self._make_slide()
        data = {"categories": ["Q1", "Q2", "Q3"], "series": [{"name": "Rev", "values": [10, 20, 30]}]}
        result = renderer._render_bar_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_stacked_bar(self):
        prs, slide = self._make_slide()
        data = {"categories": ["A", "B"], "series": [{"name": "S1", "values": [5, 10]}, {"name": "S2", "values": [3, 7]}]}
        result = renderer._render_stacked_bar(slide, data)
        self.assertIsNotNone(result)

    def test_render_line_chart(self):
        prs, slide = self._make_slide()
        data = {"categories": ["Jan", "Feb", "Mar"], "series": [{"name": "Trend", "values": [10, 15, 12]}]}
        result = renderer._render_line_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_pie_chart(self):
        prs, slide = self._make_slide()
        data = {"categories": ["A", "B", "C"], "values": [40, 35, 25]}
        result = renderer._render_pie_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_donut_chart(self):
        prs, slide = self._make_slide()
        data = {"categories": ["Pos", "Neg", "Neu"], "values": [50, 30, 20]}
        result = renderer._render_donut_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_area_chart(self):
        prs, slide = self._make_slide()
        data = {"categories": ["W1", "W2", "W3"], "series": [{"name": "Volume", "values": [100, 150, 120]}]}
        result = renderer._render_area_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_scatter_chart(self):
        prs, slide = self._make_slide()
        data = {"series": [{"name": "Data", "points": [(1, 2), (3, 4), (5, 6)]}]}
        result = renderer._render_scatter_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_bubble_chart(self):
        prs, slide = self._make_slide()
        data = {"series": [{"name": "Bubbles", "points": [(1, 2, 10), (3, 4, 20)]}]}
        result = renderer._render_bubble_chart(slide, data)
        self.assertIsNotNone(result)

    def test_render_chart_dispatch(self):
        prs, slide = self._make_slide()
        data = {"categories": ["X", "Y"], "series": [{"name": "V", "values": [5, 8]}]}
        result = renderer._render_chart(slide, "bar_chart", data)
        self.assertIsNotNone(result)

    def test_render_chart_fallback(self):
        prs, slide = self._make_slide()
        data = {"categories": ["A"], "series": [{"name": "V", "values": [1]}]}
        result = renderer._render_chart(slide, "unknown_chart_type", data)
        self.assertIsNotNone(result)


# ── Table Engine Tests ───────────────────────────────────────────────

class TestTableEngine(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_table_with_headers(self):
        prs, slide = self._make_slide()
        data = {"headers": ["Name", "Value", "Delta"], "rows": [["Brand A", "45%", "+5%"], ["Brand B", "30%", "-2%"]]}
        result = renderer._render_table(slide, data)
        self.assertIsNotNone(result)

    def test_render_table_without_headers(self):
        prs, slide = self._make_slide()
        data = {"rows": [["Cell 1", "Cell 2"], ["Cell 3", "Cell 4"]]}
        result = renderer._render_table(slide, data)
        self.assertIsNotNone(result)

    def test_render_table_empty(self):
        prs, slide = self._make_slide()
        data = {"headers": [], "rows": []}
        result = renderer._render_table(slide, data)
        self.assertIsNone(result)

    def test_render_table_alternating_rows(self):
        prs, slide = self._make_slide()
        data = {"headers": ["A", "B"], "rows": [["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"]]}
        result = renderer._render_table(slide, data)
        self.assertIsNotNone(result)


# ── KPI Cards Engine Tests ──────────────────────────────────────────

class TestKPICards(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_kpi_cards(self):
        prs, slide = self._make_slide()
        items = [{"value": "4.2M", "label": "Reach"}, {"value": "67%", "label": "Sentiment"}, {"value": "1.2K", "label": "Mentions"}]
        renderer._render_kpi_cards(slide, items)
        self.assertGreater(len(slide.shapes), 0)

    def test_render_kpi_cards_empty(self):
        prs, slide = self._make_slide()
        renderer._render_kpi_cards(slide, [])
        self.assertEqual(len(slide.shapes), 0)

    def test_render_kpi_cards_single(self):
        prs, slide = self._make_slide()
        renderer._render_kpi_cards(slide, [{"value": "99%", "label": "Score"}])
        self.assertGreater(len(slide.shapes), 0)


# ── Timeline Engine Tests ───────────────────────────────────────────

class TestTimelineEngine(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_timeline(self):
        prs, slide = self._make_slide()
        items = [{"date": "Jan 2026", "label": "Launch"}, {"date": "Mar 2026", "label": "Growth"}]
        renderer._render_timeline(slide, items)
        self.assertGreater(len(slide.shapes), 0)

    def test_render_timeline_empty(self):
        prs, slide = self._make_slide()
        renderer._render_timeline(slide, [])
        self.assertEqual(len(slide.shapes), 0)


# ── Funnel Engine Tests ─────────────────────────────────────────────

class TestFunnelEngine(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_funnel(self):
        prs, slide = self._make_slide()
        stages = [{"label": "Aware", "value": "1000"}, {"label": "Consider", "value": "500"}, {"label": "Buy", "value": "100"}]
        renderer._render_funnel(slide, stages)
        self.assertGreater(len(slide.shapes), 0)

    def test_render_funnel_empty(self):
        prs, slide = self._make_slide()
        renderer._render_funnel(slide, [])
        self.assertEqual(len(slide.shapes), 0)


# ── Network Engine Tests ────────────────────────────────────────────

class TestNetworkEngine(RendererTestCase):
    def _make_slide(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        slide = prs.slides.add_slide(renderer._blank_layout(prs))
        return prs, slide

    def test_render_network(self):
        prs, slide = self._make_slide()
        data = {"nodes": [{"label": "Brand"}, {"label": "Consumer"}, {"label": "Media"}]}
        renderer._render_network(slide, data)
        self.assertGreater(len(slide.shapes), 0)

    def test_render_network_empty(self):
        prs, slide = self._make_slide()
        renderer._render_network(slide, {"nodes": []})
        self.assertEqual(len(slide.shapes), 0)


# ── Slide Rendering Tests ───────────────────────────────────────────

class TestSlideRenderers(RendererTestCase):
    def _make_prs(self):
        from pptx import Presentation as PptxPres
        from pptx.util import Inches
        prs = PptxPres()
        prs.slide_width = Inches(renderer.SLIDE_WIDTH_INCHES)
        prs.slide_height = Inches(renderer.SLIDE_HEIGHT_INCHES)
        return prs

    def test_render_cover_slide(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        slide = renderer._render_cover_slide(prs, {"title": "Test Deck", "subtitle": "Q1 2026"}, theme, 1)
        self.assertIsNotNone(slide)
        self.assertEqual(len(prs.slides), 1)

    def test_render_agenda_slide(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        all_slides = [
            {"slide_purpose": "cover", "title": "Cover"},
            {"slide_purpose": "key_finding", "title": "Finding 1"},
            {"slide_purpose": "trend", "title": "Trend Analysis"},
            {"slide_purpose": "conclusion", "title": "Summary"},
        ]
        slide = renderer._render_agenda_slide(prs, {"title": "Agenda"}, theme, 2, all_slides)
        self.assertIsNotNone(slide)

    def test_render_conclusion_slide(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        data = {
            "title": "Conclusions",
            "content_blocks_json": [
                {"type": "narrative", "content": "Key finding summary"},
                {"type": "recommendation", "content": "Increase social monitoring"},
            ],
            "speaker_notes": "Wrap up the presentation.",
        }
        slide = renderer._render_conclusion_slide(prs, data, theme, 10)
        self.assertIsNotNone(slide)

    def test_render_content_slide_text(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        data = {
            "title": "Key Finding",
            "slide_purpose": "key_finding",
            "key_message": "Brand awareness grew 15%",
            "content_blocks_json": [
                {"type": "narrative", "content": "Analysis shows growth across all segments."},
                {"type": "evidence_panel", "content": "Reddit posts confirm trend."},
            ],
            "recommended_visual": "text_only",
            "speaker_notes": "Discuss growth drivers.",
        }
        slide = renderer._render_content_slide(prs, data, theme, 3)
        self.assertIsNotNone(slide)

    def test_render_content_slide_with_chart(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        data = {
            "title": "Trend Analysis",
            "slide_purpose": "trend",
            "content_blocks_json": [
                {"type": "metrics", "content": "Q1: 100"},
                {"type": "metrics", "content": "Q2: 150"},
                {"type": "narrative", "content": "Upward trend confirmed."},
            ],
            "recommended_visual": "bar_chart",
        }
        slide = renderer._render_content_slide(prs, data, theme, 4)
        self.assertIsNotNone(slide)

    def test_render_content_slide_with_quote(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        data = {
            "title": "Consumer Voice",
            "slide_purpose": "sentiment",
            "content_blocks_json": [
                {"type": "quote", "content": "This brand changed my life."},
            ],
            "recommended_visual": "quote",
        }
        slide = renderer._render_content_slide(prs, data, theme, 5)
        self.assertIsNotNone(slide)

    def test_render_divider_slide(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        slide = renderer._render_divider_slide(prs, {"title": "Section Break", "subtitle": "Details follow"}, theme, 6)
        self.assertIsNotNone(slide)

    def test_render_appendix_slide(self):
        prs = self._make_prs()
        theme = renderer._resolve_theme()
        slide = renderer._render_appendix_slide(prs, {"title": "Appendix: Data Sources"}, theme, 15)
        self.assertIsNotNone(slide)


# ── Validation Tests ─────────────────────────────────────────────────

class TestValidation(RendererTestCase):
    def test_validate_nonexistent(self):
        result = renderer.validate_for_render(9999)
        self.assertFalse(result["valid"])
        self.assertIn("not found", result["issues"][0].lower())

    def test_validate_no_slides(self):
        pid = self._create_project()
        pres_id = store.create_pc_presentation(pid, 1, "Empty Deck")
        result = renderer.validate_for_render(pres_id)
        self.assertFalse(result["valid"])

    def test_validate_with_slides(self):
        pres_id, _ = self._create_presentation()
        result = renderer.validate_for_render(pres_id)
        self.assertTrue(result["valid"])

    def test_validate_warns_on_rejected_slides(self):
        pres_id, _ = self._create_presentation()
        slides = store.list_pc_slides(pres_id)
        if slides:
            store.update_pc_slide(slides[0]["id"], status="rejected")
        result = renderer.validate_for_render(pres_id)
        self.assertTrue(any("rejected" in w.lower() for w in result.get("warnings", [])))


# ── Full Render Pipeline Tests ───────────────────────────────────────

class TestRenderPipeline(RendererTestCase):
    def test_render_full_presentation(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        self.assertEqual(result["status"], "completed")
        self.assertIn("job_id", result)
        self.assertGreater(result["slide_count"], 0)
        self.assertGreater(result["file_size_bytes"], 0)
        self.assertTrue(os.path.exists(result["output_path"]))

    def test_render_creates_pptx_file(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        self.assertTrue(result["output_path"].endswith(".pptx"))
        self.assertTrue(os.path.exists(result["output_path"]))

    def test_render_creates_job(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        job = store.get_render_job(result["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["presentation_id"], pres_id)

    def test_render_creates_rendered_presentation(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        rendered = store.get_latest_rendered(pres_id)
        self.assertIsNotNone(rendered)
        self.assertEqual(rendered["job_id"], result["job_id"])

    def test_render_creates_metrics(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        metrics = store.get_render_metrics(result["job_id"])
        self.assertGreater(len(metrics), 0)

    def test_render_creates_history(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        history = store.get_render_history(pres_id)
        actions = [h["action"] for h in history]
        self.assertIn("render_started", actions)
        self.assertIn("render_completed", actions)

    def test_render_invalid_presentation(self):
        result = renderer.render_presentation(9999)
        self.assertIn("error", result)

    def test_render_increments_version(self):
        pres_id, _ = self._create_presentation()
        r1 = renderer.render_presentation(pres_id)
        r2 = renderer.render_presentation(pres_id)
        self.assertEqual(r1["version"], 1)
        self.assertEqual(r2["version"], 2)


# ── Single Slide Render Tests ────────────────────────────────────────

class TestRenderSlide(RendererTestCase):
    def test_render_single_slide(self):
        pres_id, _ = self._create_presentation()
        slides = store.list_pc_slides(pres_id)
        self.assertGreater(len(slides), 0)
        result = renderer.render_slide(slides[0]["id"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(os.path.exists(result["output_path"]))

    def test_render_slide_not_found(self):
        result = renderer.render_slide(99999)
        self.assertIn("error", result)

    def test_render_slide_creates_job(self):
        pres_id, _ = self._create_presentation()
        slides = store.list_pc_slides(pres_id)
        result = renderer.render_slide(slides[0]["id"])
        job = store.get_render_job(result["job_id"])
        self.assertEqual(job["job_type"], "slide")


# ── Section Render Tests ────────────────────────────────────────────

class TestRenderSection(RendererTestCase):
    def test_render_section(self):
        pres_id, _ = self._create_presentation()
        slides = store.list_pc_slides(pres_id)
        purposes = set(s["slide_purpose"] for s in slides)
        content_purpose = next((p for p in purposes if p not in ("cover", "agenda")), None)
        if content_purpose:
            result = renderer.render_section(pres_id, content_purpose)
            self.assertEqual(result["status"], "completed")
            self.assertGreater(result["slide_count"], 0)

    def test_render_section_no_match(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_section(pres_id, "nonexistent_purpose_xyz")
        self.assertIn("error", result)


# ── Download Tests ──────────────────────────────────────────────────

class TestDownload(RendererTestCase):
    def test_get_download_path(self):
        pres_id, _ = self._create_presentation()
        result = renderer.render_presentation(pres_id)
        path = renderer.get_download_path(result["job_id"])
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))

    def test_get_download_path_not_found(self):
        path = renderer.get_download_path("nonexistent-job-id")
        self.assertIsNone(path)

    def test_get_download_path_incomplete_job(self):
        store.create_render_job("test-job-123", 1, job_type="full")
        path = renderer.get_download_path("test-job-123")
        self.assertIsNone(path)


# ── Render Summary Tests ────────────────────────────────────────────

class TestRenderSummary(RendererTestCase):
    def test_empty_summary(self):
        pres_id, _ = self._create_presentation()
        summary = renderer.get_render_summary(pres_id)
        self.assertEqual(summary["total_renders"], 0)
        self.assertFalse(summary["has_download"])

    def test_summary_after_render(self):
        pres_id, _ = self._create_presentation()
        renderer.render_presentation(pres_id)
        summary = renderer.get_render_summary(pres_id)
        self.assertEqual(summary["total_renders"], 1)
        self.assertTrue(summary["has_download"])
        self.assertIsNotNone(summary["latest_render"])


# ── Store CRUD Tests ────────────────────────────────────────────────

class TestStoreCRUD(RendererTestCase):
    def test_create_and_get_render_job(self):
        jid = store.create_render_job("job-1", 1, job_type="full")
        job = store.get_render_job(jid)
        self.assertIsNotNone(job)
        self.assertEqual(job["job_type"], "full")
        self.assertEqual(job["status"], "pending")

    def test_update_render_job(self):
        jid = store.create_render_job("job-2", 1)
        store.update_render_job(jid, status="running", progress_pct=50)
        job = store.get_render_job(jid)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["progress_pct"], 50)

    def test_list_render_jobs(self):
        store.create_render_job("job-3a", 1)
        store.create_render_job("job-3b", 1)
        jobs = store.list_render_jobs(1)
        self.assertEqual(len(jobs), 2)

    def test_create_rendered_presentation(self):
        store.create_render_job("job-4", 1)
        rp_id = store.create_rendered_presentation("job-4", 1, "/tmp/test.pptx", slide_count=5)
        rp = store.get_rendered_presentation(rp_id)
        self.assertIsNotNone(rp)
        self.assertEqual(rp["slide_count"], 5)

    def test_list_rendered_presentations(self):
        store.create_render_job("job-5", 1)
        store.create_rendered_presentation("job-5", 1, "/tmp/test1.pptx")
        store.create_rendered_presentation("job-5", 1, "/tmp/test2.pptx")
        rps = store.list_rendered_presentations(1)
        self.assertEqual(len(rps), 2)

    def test_get_latest_rendered(self):
        store.create_render_job("job-6", 1)
        store.create_rendered_presentation("job-6", 1, "/tmp/old.pptx", version=1)
        store.create_rendered_presentation("job-6", 1, "/tmp/new.pptx", version=2)
        latest = store.get_latest_rendered(1)
        self.assertEqual(latest["version"], 2)

    def test_add_render_metric(self):
        store.create_render_job("job-7", 1)
        mid = store.add_render_metric("job-7", 1, 0, "content", duration_ms=45)
        metrics = store.get_render_metrics("job-7")
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["duration_ms"], 45)

    def test_create_theme(self):
        tid = store.create_theme("test_theme", "Test Theme", primary_color="#FF0000")
        theme = store.get_theme(tid)
        self.assertIsNotNone(theme)
        self.assertEqual(theme["primary_color"], "#FF0000")

    def test_list_themes(self):
        store.ensure_default_theme()
        themes = store.list_themes()
        self.assertGreaterEqual(len(themes), 1)

    def test_create_template_version(self):
        store.create_theme("tv_theme", "TV Theme")
        tv_id = store.create_template_version("tv_theme", "/path/to/v1.pptx", changelog="Initial")
        versions = store.list_template_versions("tv_theme")
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)

    def test_template_version_auto_increments(self):
        store.create_theme("tv2_theme", "TV2 Theme")
        store.create_template_version("tv2_theme", "/path/v1.pptx")
        store.create_template_version("tv2_theme", "/path/v2.pptx")
        versions = store.list_template_versions("tv2_theme")
        self.assertEqual(len(versions), 2)
        version_nums = [v["version"] for v in versions]
        self.assertIn(1, version_nums)
        self.assertIn(2, version_nums)

    def test_add_render_history(self):
        store.create_render_job("job-h1", 1)
        hid = store.add_render_history(1, "job-h1", "render_started", actor="test")
        history = store.get_render_history(1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "render_started")

    def test_render_history_with_details(self):
        store.create_render_job("job-h2", 1)
        store.add_render_history(1, "job-h2", "render_completed",
                                 details={"slide_count": 10, "duration_ms": 500})
        history = store.get_render_history(1)
        self.assertEqual(history[0]["details_json"]["slide_count"], 10)


# ── Extract Data Helpers Tests ──────────────────────────────────────

class TestExtractHelpers(RendererTestCase):
    def test_extract_chart_data_from_metrics(self):
        blocks = [
            {"type": "metrics", "content": "Revenue: 1.2M"},
            {"type": "metrics", "content": "Growth: 15"},
        ]
        data = renderer._extract_chart_data(blocks, {"title": "Test"})
        self.assertGreater(len(data["categories"]), 0)

    def test_extract_chart_data_fallback(self):
        blocks = [{"type": "narrative", "content": "Some text only"}]
        data = renderer._extract_chart_data(blocks, {"title": "Fallback"})
        self.assertGreater(len(data["categories"]), 0)
        self.assertGreater(len(data["series"]), 0)

    def test_extract_table_data_none(self):
        blocks = [{"type": "narrative", "content": "No table here"}]
        result = renderer._extract_table_data(blocks)
        self.assertIsNone(result)

    def test_extract_table_data_from_json(self):
        import json
        table_json = json.dumps({"headers": ["A", "B"], "rows": [["1", "2"]]})
        blocks = [{"type": "chart", "content": table_json}]
        result = renderer._extract_table_data(blocks)
        self.assertIsNotNone(result)
        self.assertEqual(result["headers"], ["A", "B"])


# ── Branding Tests ──────────────────────────────────────────────────

class TestBranding(RendererTestCase):
    def test_brand_colors_defined(self):
        self.assertEqual(renderer.VIOLET, renderer._hex_to_rgb("#5B2C9D"))
        self.assertEqual(renderer.BLACK, renderer._hex_to_rgb("#1A1A1A"))

    def test_default_theme_has_brand_palette(self):
        store.ensure_default_theme()
        theme = store.get_theme("hunter_default")
        palette = theme.get("color_palette_json", [])
        self.assertGreater(len(palette), 0)
        self.assertIn("#5E35B1", palette)

    def test_custom_theme_render(self):
        store.create_theme("custom_test", "Custom Theme",
                           primary_color="#FF0000", font_heading="Arial")
        theme = renderer._resolve_theme("custom_test")
        self.assertEqual(theme["primary_color"], "#FF0000")
        self.assertEqual(theme["font_heading"], "Arial")


if __name__ == "__main__":
    unittest.main()
