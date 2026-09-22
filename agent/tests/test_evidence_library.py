"""Tests for evidence_library: ingestion, exact/near-duplicate detection,
canonical selection, quality scoring, review workflow, annotations, bulk
actions, audit history, objective coverage, search/filtering, summary
metrics, representative/high-value marking, and rejected-item restore."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app import config
from agent.app import intelligence_store as store
from agent.app import evidence_library as elib


# ─── Shared fixture data ────────────────────────────────────────────────────

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

# Text pairs with pre-computed SequenceMatcher ratios (lower-cased, as the
# implementation compares), used to exercise the near-duplicate thresholds
# deterministically instead of relying on ad hoc strings.
#   TEXT_A vs TEXT_B_HIGH -> 0.9317  (>= NEAR_DUPLICATE_TEXT_THRESHOLD, 0.85)
#   TEXT_A vs TEXT_C_LOW  -> 0.3354  (below both thresholds)
#   TEXT_A vs TEXT_D_MID  -> 0.8395  (>= SAME_SOURCE_HEADLINE_THRESHOLD 0.80, < 0.85)
TEXT_A = "TestBrand launches a new spicy chip flavor for summer twenty twenty six season"
TEXT_B_HIGH = "TestBrand launches a new spicy chip flavor this summer for twenty twenty six season"
TEXT_C_LOW = "Completely unrelated commentary about rainy weather forecasts for the weekend ahead"
TEXT_D_MID = "TestBrand releases bold new spicy chip flavors across stores for summer twenty twenty six season"


class EvidenceLibraryTestCase(unittest.TestCase):
    """Common DB lifecycle + evidence-library fixture helpers.

    Each test method gets its own throwaway SQLite database (fresh
    directory + schema), so tests never leak state into one another.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="evidence_library_test_")
        config.MEMORY_DB_PATH = os.path.join(self._tmpdir, "test_memory.db")
        store.init_intelligence_db()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- fixture builders ----------------------------------------------

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

    def make_run(self, project_id, plan_id, total_units=2):
        return store.create_execution_run(project_id, plan_id, total_units)

    def make_evidence(self, run_id, **overrides):
        fields = {
            "unit_id": "EU1",
            "objective_id": "RO1",
            "evidence_type": "finding",
            "method": "Theme Clustering",
            "platform": "Reddit",
            "source": "Reddit Post",
            "date": "2026-03-01",
            "text_excerpt": "Consumers love snacking on chips during movie nights with friends.",
            "metrics": {"likes": 10, "url": "http://example.com/thread-1"},
            "confidence": "high",
            "rationale": "Representative finding about snacking occasions.",
        }
        fields.update(overrides)
        return store.save_evidence(run_id, **fields)

    def setup_project_plan_run(self, project_name="TestBrand", objectives=None,
                                units=None, total_units=2):
        pid = self.make_project(project_name)
        plan_id = self.make_plan(pid, objectives, units)
        run_id = self.make_run(pid, plan_id, total_units)
        return pid, plan_id, run_id


# ─── Ingestion ───────────────────────────────────────────────────────────────

class TestIngestion(EvidenceLibraryTestCase):
    def test_ingest_creates_library_items(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt="Alpha finding about snack timing preferences.")
        self.make_evidence(run_id, text_excerpt="Beta finding about chip brand loyalty patterns.")
        self.make_evidence(run_id, text_excerpt="Gamma finding about weekend cravings behavior.")

        result = elib.ingest_evidence(pid, run_id)

        self.assertEqual(result["ingested"], 3)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["total"], 3)
        items = store.list_library_items(pid, limit=100)
        self.assertEqual(len(items), 3)

    def test_ingest_idempotent_reingest_skips(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt="Alpha finding about snack timing preferences.")
        self.make_evidence(run_id, text_excerpt="Beta finding about chip brand loyalty patterns.")

        first = elib.ingest_evidence(pid, run_id)
        second = elib.ingest_evidence(pid, run_id)

        self.assertEqual(first["ingested"], 2)
        self.assertEqual(first["skipped"], 0)
        self.assertEqual(second["ingested"], 0)
        self.assertEqual(second["skipped"], 2)
        items = store.list_library_items(pid, limit=100)
        self.assertEqual(len(items), 2)

    def test_ingest_quality_scores_assigned(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt="Alpha finding about snack timing preferences.")
        elib.ingest_evidence(pid, run_id)

        items = store.list_library_items(pid, limit=10)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIsNotNone(item["quality_score"])
        self.assertGreaterEqual(item["quality_score"], 0.0)
        self.assertLessEqual(item["quality_score"], 1.0)
        self.assertIn("quality_components", item)
        for key in elib.QUALITY_WEIGHTS:
            self.assertIn(key, item["quality_components"])

    def test_ingest_preserves_objective_and_unit(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, unit_id="EU2", objective_id="RO2",
                            text_excerpt="Distinct brand comparison finding about loyalty.")
        elib.ingest_evidence(pid, run_id)

        items = store.list_library_items(pid, limit=10)
        self.assertEqual(items[0]["unit_id"], "EU2")
        self.assertEqual(items[0]["objective_id"], "RO2")


# ─── Exact deduplication ─────────────────────────────────────────────────────

class TestExactDedup(EvidenceLibraryTestCase):
    def test_same_url_creates_duplicate_group(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt="First write-up of the thread contents.",
                            metrics={"url": "http://example.com/thread-9"})
        self.make_evidence(run_id, text_excerpt="Totally different write-up wording entirely.",
                            metrics={"url": "http://example.com/thread-9"})

        result = elib.ingest_evidence(pid, run_id)
        self.assertEqual(result["duplicates_found"], 2)

        items = store.list_library_items(pid, limit=10, sort_by="id", sort_dir="asc")
        self.assertEqual(len(items), 2)
        self.assertIsNotNone(items[0]["duplicate_group"])
        self.assertEqual(items[0]["duplicate_group"], items[1]["duplicate_group"])

    def test_same_url_canonical_assigned(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt="First write-up of the thread contents.",
                            metrics={"url": "http://example.com/thread-9"})
        self.make_evidence(run_id, text_excerpt="Totally different write-up wording entirely.",
                            metrics={"url": "http://example.com/thread-9"})
        elib.ingest_evidence(pid, run_id)

        items = store.list_library_items(pid, limit=10, sort_by="id", sort_dir="asc")
        canonical_ids = {it["canonical_id"] for it in items}
        self.assertEqual(len(canonical_ids), 1)
        canonical_id = canonical_ids.pop()
        self.assertIn(canonical_id, [it["id"] for it in items])

    def test_different_url_no_duplicate_group(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt=TEXT_A,
                            source="SourceOne", metrics={"url": "http://example.com/thread-1"})
        self.make_evidence(run_id, text_excerpt=TEXT_C_LOW,
                            source="SourceTwo", metrics={"url": "http://example.com/thread-2"})

        result = elib.ingest_evidence(pid, run_id)
        self.assertEqual(result["duplicates_found"], 0)
        items = store.list_library_items(pid, limit=10)
        for it in items:
            self.assertIsNone(it["duplicate_group"])


# ─── Near-duplicate detection ────────────────────────────────────────────────

class TestNearDedup(EvidenceLibraryTestCase):
    def test_similar_text_excerpt_creates_duplicate_group(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt=TEXT_A, source="SourceOne", metrics={"likes": 3})
        self.make_evidence(run_id, text_excerpt=TEXT_B_HIGH, source="SourceTwo", metrics={"likes": 4})

        result = elib.ingest_evidence(pid, run_id)
        self.assertEqual(result["duplicates_found"], 2)

        items = store.list_library_items(pid, limit=10)
        self.assertIsNotNone(items[0]["duplicate_group"])
        self.assertEqual(items[0]["duplicate_group"], items[1]["duplicate_group"])

    def test_dissimilar_text_no_duplicate(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        self.make_evidence(run_id, text_excerpt=TEXT_A, source="SourceOne", metrics={"likes": 3})
        self.make_evidence(run_id, text_excerpt=TEXT_C_LOW, source="SourceTwo", metrics={"likes": 4})

        result = elib.ingest_evidence(pid, run_id)
        self.assertEqual(result["duplicates_found"], 0)
        items = store.list_library_items(pid, limit=10)
        for it in items:
            self.assertIsNone(it["duplicate_group"])

    def test_same_source_moderate_similarity_dedups_only_with_matching_source(self):
        # Case 1: moderate similarity (0.80 <= ratio < 0.85) + same source -> dup.
        pid1, _, run1 = self.setup_project_plan_run(project_name="BrandSameSource")
        self.make_evidence(run1, text_excerpt=TEXT_A, source="SharedSource", metrics={"likes": 3})
        self.make_evidence(run1, text_excerpt=TEXT_D_MID, source="SharedSource", metrics={"likes": 4})
        result1 = elib.ingest_evidence(pid1, run1)
        self.assertEqual(result1["duplicates_found"], 2)

        # Case 2: same moderate similarity but different source -> not a dup.
        pid2, _, run2 = self.setup_project_plan_run(project_name="BrandDiffSource")
        self.make_evidence(run2, text_excerpt=TEXT_A, source="SourceOne", metrics={"likes": 3})
        self.make_evidence(run2, text_excerpt=TEXT_D_MID, source="SourceTwo", metrics={"likes": 4})
        result2 = elib.ingest_evidence(pid2, run2)
        self.assertEqual(result2["duplicates_found"], 0)


# ─── Canonical selection ─────────────────────────────────────────────────────

class TestCanonicalSelection(EvidenceLibraryTestCase):
    def _make_two_items(self, score_a, score_b):
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_a = self.make_evidence(run_id, text_excerpt="Existing item text about item A.")
        ev_b = self.make_evidence(run_id, text_excerpt="New item text about item B.")
        item_a_id = store.create_library_item(pid, ev_a, "RO1", "EU1")
        item_b_id = store.create_library_item(pid, ev_b, "RO1", "EU1")
        store.update_library_item(item_a_id, quality_score=score_a)
        store.update_library_item(item_b_id, quality_score=score_b)
        return item_a_id, item_b_id

    def test_higher_quality_existing_item_becomes_canonical(self):
        # item_a = candidate being linked in, item_b = pre-existing reference.
        item_a_id, item_b_id = self._make_two_items(score_a=0.3, score_b=0.9)
        elib._link_duplicates(item_a_id, item_b_id)

        item_a = store.get_library_item(item_a_id)
        item_b = store.get_library_item(item_b_id)
        self.assertEqual(item_a["canonical_id"], item_b_id)
        self.assertEqual(item_b["canonical_id"], item_b_id)

    def test_higher_quality_new_item_becomes_canonical(self):
        item_a_id, item_b_id = self._make_two_items(score_a=0.9, score_b=0.3)
        elib._link_duplicates(item_a_id, item_b_id)

        item_a = store.get_library_item(item_a_id)
        item_b = store.get_library_item(item_b_id)
        self.assertEqual(item_a["canonical_id"], item_a_id)
        self.assertEqual(item_b["canonical_id"], item_a_id)

    def test_tie_existing_item_wins_and_group_shared(self):
        item_a_id, item_b_id = self._make_two_items(score_a=0.5, score_b=0.5)
        elib._link_duplicates(item_a_id, item_b_id)

        item_a = store.get_library_item(item_a_id)
        item_b = store.get_library_item(item_b_id)
        # On a tie, the pre-existing item (item_b) wins canonical status.
        self.assertEqual(item_a["canonical_id"], item_b_id)
        self.assertIsNotNone(item_a["duplicate_group"])
        self.assertEqual(item_a["duplicate_group"], item_b["duplicate_group"])

        audit_a = store.get_library_audit(item_a_id)
        self.assertTrue(any(a["action"] == "duplicate_detected" for a in audit_a))


# ─── Quality scoring ─────────────────────────────────────────────────────────

class TestQualityScoring(EvidenceLibraryTestCase):
    def _library_item(self, **overrides):
        base = {"id": 1, "duplicate_group": None, "canonical_id": None}
        base.update(overrides)
        return base

    def test_weights_sum_to_one(self):
        total = sum(elib.QUALITY_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_source_quality_scoring(self):
        cases = [
            ({"source": "Reddit", "metrics": {"url": "http://x.com/a", "author": "jdoe"}}, 1.0),
            ({"source": "Reddit"}, 0.8),
            ({}, 0.3),
        ]
        for ev, expected in cases:
            with self.subTest(ev=ev):
                _, components = elib._calculate_quality_score(ev, self._library_item())
                self.assertEqual(components["source_quality"], expected)

    def test_completeness_scoring(self):
        full_ev = {
            "text_excerpt": "text", "source": "Reddit", "platform": "Reddit",
            "date": "2026-03-01", "metrics": {"url": "http://x.com", "likes": 1},
            "rationale": "why", "confidence": "high",
        }
        partial_ev = {"text_excerpt": "text", "source": "Reddit"}
        cases = [(full_ev, 1.0), (partial_ev, 0.25), ({}, 0.0)]
        for ev, expected in cases:
            with self.subTest(ev=ev):
                _, components = elib._calculate_quality_score(ev, self._library_item())
                self.assertEqual(components["completeness"], expected)

    def test_confidence_factor_mapping(self):
        cases = [("high", 1.0), ("medium", 0.7), ("low", 0.4), ("unclear", 0.4), (None, 0.4)]
        for confidence, expected in cases:
            with self.subTest(confidence=confidence):
                ev = {"confidence": confidence} if confidence is not None else {}
                _, components = elib._calculate_quality_score(ev, self._library_item())
                self.assertEqual(components["confidence_factor"], expected)

    def test_recency_scoring(self):
        cases = [
            ("2026-03-01", 0.8),
            ("2026-03-01T10:00:00Z", 0.8),
            ("not-a-date", 0.4),
            (None, 0.4),
        ]
        for date_value, expected in cases:
            with self.subTest(date=date_value):
                ev = {"date": date_value}
                _, components = elib._calculate_quality_score(ev, self._library_item())
                self.assertEqual(components["recency"], expected)

    def test_engagement_scoring(self):
        cases = [
            ({"likes": 5}, 0.8),
            ({"likes": 0}, 0.3),
            (None, 0.3),
            ({"sentiment": "positive"}, 0.3),  # non-numeric metric doesn't count
        ]
        for metrics, expected in cases:
            with self.subTest(metrics=metrics):
                ev = {"metrics": metrics}
                _, components = elib._calculate_quality_score(ev, self._library_item())
                self.assertEqual(components["engagement"], expected)

    def test_duplicate_risk_scoring(self):
        cases = [
            ({"id": 1, "duplicate_group": None, "canonical_id": None}, 1.0),
            ({"id": 5, "duplicate_group": "g1", "canonical_id": 5}, 0.8),
            ({"id": 5, "duplicate_group": "g1", "canonical_id": 6}, 0.4),
        ]
        for library_item, expected in cases:
            with self.subTest(library_item=library_item):
                _, components = elib._calculate_quality_score({}, library_item)
                self.assertEqual(components["duplicate_risk"], expected)

    def test_overall_score_matches_weighted_sum_and_bounds(self):
        ev = {"source": "Reddit", "text_excerpt": "t", "date": "2026-01-01",
              "confidence": "high", "metrics": {"likes": 5, "url": "http://x.com"}}
        score, components = elib._calculate_quality_score(ev, self._library_item())
        expected = round(sum(components[k] * w for k, w in elib.QUALITY_WEIGHTS.items()), 4)
        self.assertEqual(score, expected)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ─── Review workflow ─────────────────────────────────────────────────────────

class TestReviewWorkflow(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_id = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        self.item_id = store.get_library_item_by_evidence_id(ev_id)["id"]

    def test_accept_transition(self):
        result = elib.review_evidence(self.item_id, "accepted", reviewer="alice")
        self.assertEqual(result["review_status"], "accepted")
        self.assertEqual(result["reviewed_by"], "alice")

    def test_reject_transition(self):
        result = elib.review_evidence(self.item_id, "rejected", reviewer="bob")
        self.assertEqual(result["review_status"], "rejected")

    def test_needs_review_transition(self):
        result = elib.review_evidence(self.item_id, "needs_review", reviewer="carol")
        self.assertEqual(result["review_status"], "needs_review")

    def test_invalid_status_returns_error(self):
        result = elib.review_evidence(self.item_id, "bogus_status")
        self.assertIn("error", result)
        # Status should remain unchanged.
        item = store.get_library_item(self.item_id)
        self.assertEqual(item["review_status"], "unreviewed")

    def test_review_creates_audit_entry_and_annotation_note(self):
        elib.review_evidence(self.item_id, "accepted", reviewer="alice")
        audit = store.get_library_audit(self.item_id)
        review_entries = [a for a in audit if a["action"] == "review"]
        self.assertEqual(len(review_entries), 1)
        self.assertEqual(review_entries[0]["old_value"], "unreviewed")
        self.assertEqual(review_entries[0]["new_value"], "accepted")

        elib.review_evidence(self.item_id, "rejected", reviewer="dave", note="Not relevant to scope")
        annotations = store.get_library_annotations(self.item_id)
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0]["note"], "Not relevant to scope")
        audit_after_note = store.get_library_audit(self.item_id)
        self.assertTrue(any(a["action"] == "annotation" for a in audit_after_note))


# ─── Annotations ─────────────────────────────────────────────────────────────

class TestAnnotations(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_id = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        self.item_id = store.get_library_item_by_evidence_id(ev_id)["id"]

    def test_add_note_appears(self):
        elib.add_annotation(self.item_id, "Worth featuring in the deck", author="alice")
        annotations = store.get_library_annotations(self.item_id)
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0]["note"], "Worth featuring in the deck")
        self.assertEqual(annotations[0]["author"], "alice")

    def test_annotation_creates_audit(self):
        elib.add_annotation(self.item_id, "Check with client", author="bob")
        audit = store.get_library_audit(self.item_id)
        entries = [a for a in audit if a["action"] == "annotation"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["new_value"], "Check with client")
        self.assertEqual(entries[0]["actor"], "bob")

    def test_multiple_annotations_present(self):
        elib.add_annotation(self.item_id, "First note", author="alice")
        time.sleep(0.01)
        elib.add_annotation(self.item_id, "Second note", author="alice")

        annotations = store.get_library_annotations(self.item_id)
        self.assertEqual(len(annotations), 2)
        # Most recent first.
        self.assertEqual(annotations[0]["note"], "Second note")
        self.assertEqual(annotations[1]["note"], "First note")


# ─── Bulk actions ────────────────────────────────────────────────────────────

class TestBulkActions(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        self.pid, self.plan_id, self.run_id = self.setup_project_plan_run()
        self.ev_ids = [
            self.make_evidence(self.run_id, text_excerpt=f"Distinct bulk finding number {i} about snacks.",
                                metrics={"likes": i, "url": f"http://example.com/bulk-{i}"})
            for i in range(3)
        ]
        elib.ingest_evidence(self.pid, self.run_id)
        self.item_ids = [store.get_library_item_by_evidence_id(e)["id"] for e in self.ev_ids]

    def test_bulk_accept_updates_all(self):
        result = elib.bulk_review(self.item_ids, "accepted", reviewer="alice")
        self.assertEqual(result["updated"], 3)
        for item_id in self.item_ids:
            item = store.get_library_item(item_id)
            self.assertEqual(item["review_status"], "accepted")
            self.assertEqual(item["reviewed_by"], "alice")

    def test_bulk_audit_per_item(self):
        elib.bulk_review(self.item_ids, "rejected", reviewer="bob")
        for item_id in self.item_ids:
            audit = store.get_library_audit(item_id)
            bulk_entries = [a for a in audit if a["action"] == "bulk_review"]
            self.assertEqual(len(bulk_entries), 1)
            self.assertEqual(bulk_entries[0]["new_value"], "rejected")

    def test_bulk_invalid_status_returns_error(self):
        result = elib.bulk_review(self.item_ids, "bogus", reviewer="carol")
        self.assertIn("error", result)
        for item_id in self.item_ids:
            item = store.get_library_item(item_id)
            self.assertEqual(item["review_status"], "unreviewed")


# ─── Audit history ───────────────────────────────────────────────────────────

class TestAuditHistory(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_id = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        self.item_id = store.get_library_item_by_evidence_id(ev_id)["id"]

    def test_new_item_has_no_audit(self):
        audit = store.get_library_audit(self.item_id)
        self.assertEqual(audit, [])

    def test_multiple_actions_create_ordered_entries(self):
        elib.review_evidence(self.item_id, "needs_review", reviewer="alice")
        time.sleep(0.01)
        elib.add_annotation(self.item_id, "Looks promising", author="alice")
        time.sleep(0.01)
        elib.mark_representative(self.item_id, True, reviewer="alice")
        time.sleep(0.01)
        elib.review_evidence(self.item_id, "accepted", reviewer="alice")

        audit = store.get_library_audit(self.item_id)
        self.assertEqual(len(audit), 4)
        # get_library_audit orders most-recent-first.
        actions_most_recent_first = [a["action"] for a in audit]
        self.assertEqual(
            actions_most_recent_first,
            ["review", "mark_representative", "annotation", "review"],
        )

    def test_audit_actions_recorded_with_correct_actor(self):
        elib.review_evidence(self.item_id, "accepted", reviewer="zoe")
        audit = store.get_library_audit(self.item_id)
        self.assertEqual(audit[0]["actor"], "zoe")


# ─── Objective coverage ──────────────────────────────────────────────────────

class TestObjectiveCoverage(EvidenceLibraryTestCase):
    def test_coverage_status_levels(self):
        cases = [
            (0, "insufficient"),
            (2, "partial"),
            (5, "sufficient"),
        ]
        for accepted_count, expected_status in cases:
            with self.subTest(accepted=accepted_count):
                pid, plan_id, run_id = self.setup_project_plan_run(
                    project_name=f"Brand-{accepted_count}"
                )
                total_records = max(accepted_count, 1)
                ev_ids = [
                    self.make_evidence(
                        run_id, objective_id="RO1", unit_id="EU1",
                        text_excerpt=f"Distinct RO1 finding number {i} for case {accepted_count}.",
                    )
                    for i in range(total_records)
                ]
                elib.ingest_evidence(pid, run_id)
                for ev_id in ev_ids[:accepted_count]:
                    item_id = store.get_library_item_by_evidence_id(ev_id)["id"]
                    elib.review_evidence(item_id, "accepted")

                report = elib.get_coverage_report(pid)
                ro1 = next(o for o in report["objectives"] if o["objective_id"] == "RO1")
                self.assertEqual(ro1["coverage_status"], expected_status)
                self.assertEqual(ro1["accepted_evidence"], accepted_count)

    def test_no_approved_plan_returns_error(self):
        pid = self.make_project()
        self.make_plan(pid, approve=False)
        report = elib.get_coverage_report(pid)
        self.assertIn("error", report)


# ─── Search and filtering ────────────────────────────────────────────────────

class TestSearchFiltering(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        self.pid, self.plan_id, self.run_id = self.setup_project_plan_run()
        self.ev_reddit = self.make_evidence(
            self.run_id, objective_id="RO1", unit_id="EU1", platform="Reddit",
            confidence="high", text_excerpt="Snack lovers discuss chip flavors on Reddit threads.",
        )
        self.ev_twitter = self.make_evidence(
            self.run_id, objective_id="RO2", unit_id="EU2", platform="Twitter/X",
            confidence="medium", text_excerpt="Brand loyalty debate trends on social media timelines.",
        )
        elib.ingest_evidence(self.pid, self.run_id)
        self.item_reddit = store.get_library_item_by_evidence_id(self.ev_reddit)
        self.item_twitter = store.get_library_item_by_evidence_id(self.ev_twitter)
        elib.review_evidence(self.item_reddit["id"], "accepted")

    def test_filter_by_status(self):
        results = elib.search_evidence(self.pid, review_status="accepted")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.item_reddit["id"])

    def test_filter_by_objective(self):
        results = elib.search_evidence(self.pid, objective_id="RO2")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.item_twitter["id"])

    def test_search_text_match(self):
        results = elib.search_evidence(self.pid, query="chip flavors")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.item_reddit["id"])

        no_match = elib.search_evidence(self.pid, query="nonexistent topic xyz")
        self.assertEqual(no_match, [])

    def test_filter_by_platform_and_confidence(self):
        by_platform = elib.search_evidence(self.pid, platform="Reddit")
        self.assertEqual(len(by_platform), 1)
        self.assertEqual(by_platform[0]["platform"], "Reddit")

        by_confidence = elib.search_evidence(self.pid, confidence="medium")
        self.assertEqual(len(by_confidence), 1)
        self.assertEqual(by_confidence[0]["id"], self.item_twitter["id"])

    def test_sort_by_quality_score_desc(self):
        results = elib.search_evidence(self.pid, sort_by="quality_score", sort_dir="desc")
        self.assertEqual(len(results), 2)
        self.assertGreaterEqual(results[0]["quality_score"], results[1]["quality_score"])


# ─── Summary metrics ─────────────────────────────────────────────────────────

class TestSummaryMetrics(EvidenceLibraryTestCase):
    _SUMMARY_TEXTS = [
        "Consumers prefer crunchy chips during late night movie watching sessions at home.",
        "Brand awareness on Twitter increased sharply after the celebrity endorsement campaign.",
        "Reddit threads show strong preference for spicy flavors among younger demographics.",
        "Instagram engagement metrics suggest visual packaging drives purchase consideration.",
    ]

    def setUp(self):
        super().setUp()
        self.pid, self.plan_id, self.run_id = self.setup_project_plan_run()
        self.ev_ids = [
            self.make_evidence(self.run_id, objective_id="RO1", unit_id="EU1",
                                text_excerpt=self._SUMMARY_TEXTS[i],
                                metrics={"likes": 10 + i, "url": f"http://example.com/thread-{100 + i}"})
            for i in range(4)
        ]
        elib.ingest_evidence(self.pid, self.run_id)
        self.item_ids = [store.get_library_item_by_evidence_id(e)["id"] for e in self.ev_ids]
        elib.review_evidence(self.item_ids[0], "accepted")
        elib.review_evidence(self.item_ids[1], "rejected")
        elib.review_evidence(self.item_ids[2], "needs_review")
        # item_ids[3] stays unreviewed.
        elib.mark_representative(self.item_ids[0], True)
        elib.mark_high_value(self.item_ids[0], True)

    def test_total_and_per_status_counts(self):
        summary = elib.get_summary_metrics(self.pid)
        self.assertEqual(summary["total_items"], 4)
        self.assertEqual(summary["by_status"]["accepted"], 1)
        self.assertEqual(summary["by_status"]["rejected"], 1)
        self.assertEqual(summary["by_status"]["needs_review"], 1)
        self.assertEqual(summary["by_status"]["unreviewed"], 1)
        self.assertEqual(summary["by_status"]["superseded"], 0)

    def test_representative_and_high_value_counts(self):
        summary = elib.get_summary_metrics(self.pid)
        self.assertEqual(summary["representative"], 1)
        self.assertEqual(summary["high_value"], 1)

    def test_duplicate_groups_count_zero_when_no_dupes(self):
        summary = elib.get_summary_metrics(self.pid)
        self.assertEqual(summary["duplicate_groups"], 0)

    def test_objective_coverage_present(self):
        summary = elib.get_summary_metrics(self.pid)
        self.assertIn("RO1", summary["objective_coverage"])
        self.assertEqual(summary["objective_coverage"]["RO1"]["total_evidence"], 4)
        self.assertEqual(summary["objective_coverage"]["RO1"]["accepted_evidence"], 1)


# ─── Mark representative / high-value ───────────────────────────────────────

class TestMarking(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_id = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        self.item_id = store.get_library_item_by_evidence_id(ev_id)["id"]

    def test_mark_and_unmark_representative(self):
        result = elib.mark_representative(self.item_id, True, reviewer="alice")
        self.assertTrue(result["success"])
        item = store.get_library_item(self.item_id)
        self.assertEqual(item["is_representative"], 1)

        result2 = elib.mark_representative(self.item_id, False, reviewer="alice")
        self.assertTrue(result2["success"])
        item2 = store.get_library_item(self.item_id)
        self.assertEqual(item2["is_representative"], 0)

    def test_mark_high_value_creates_audit(self):
        elib.mark_high_value(self.item_id, True, reviewer="bob")
        item = store.get_library_item(self.item_id)
        self.assertEqual(item["is_high_value"], 1)

        audit = store.get_library_audit(self.item_id)
        entries = [a for a in audit if a["action"] == "mark_high_value"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["new_value"], "1")

    def test_mark_nonexistent_item_returns_error(self):
        result = elib.mark_representative(999999, True)
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# ─── Restore rejected ────────────────────────────────────────────────────────

class TestRestore(EvidenceLibraryTestCase):
    def setUp(self):
        super().setUp()
        pid, plan_id, run_id = self.setup_project_plan_run()
        ev_id = self.make_evidence(run_id)
        elib.ingest_evidence(pid, run_id)
        self.item_id = store.get_library_item_by_evidence_id(ev_id)["id"]

    def test_restore_rejected_to_needs_review(self):
        elib.review_evidence(self.item_id, "rejected", reviewer="alice")
        result = elib.restore_rejected(self.item_id, reviewer="bob")
        self.assertEqual(result["review_status"], "needs_review")

    def test_restore_creates_audit_entry(self):
        elib.review_evidence(self.item_id, "rejected", reviewer="alice")
        elib.restore_rejected(self.item_id, reviewer="bob")

        audit = store.get_library_audit(self.item_id)
        restore_entries = [a for a in audit if a["action"] == "restore"]
        self.assertEqual(len(restore_entries), 1)
        self.assertEqual(restore_entries[0]["old_value"], "rejected")
        self.assertEqual(restore_entries[0]["new_value"], "needs_review")

    def test_restore_error_cases(self):
        cases = [
            ("unreviewed_item", self.item_id),
            ("nonexistent_item", 999999),
        ]
        for label, item_id in cases:
            with self.subTest(case=label):
                result = elib.restore_rejected(item_id)
                self.assertIn("error", result)


# ─── Blocking coverage gaps ──────────────────────────────────────────────────

class TestBlockingCoverage(EvidenceLibraryTestCase):
    def test_high_priority_zero_accepted_is_blocking(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        # RO1 is "high" priority in DEFAULT_OBJECTIVES; no evidence at all.
        report = elib.get_coverage_report(pid)
        ro1 = next(o for o in report["objectives"] if o["objective_id"] == "RO1")
        self.assertTrue(ro1["is_blocking_gap"])
        # summary.blocking_gaps is a count of blocking objectives, not a list.
        self.assertEqual(report["summary"]["blocking_gaps"], 1)

    def test_medium_priority_zero_accepted_not_blocking(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        # RO2 is "medium" priority; zero accepted evidence should not block.
        report = elib.get_coverage_report(pid)
        ro2 = next(o for o in report["objectives"] if o["objective_id"] == "RO2")
        self.assertFalse(ro2["is_blocking_gap"])
        self.assertEqual(report["summary"]["blocking_gaps"], 1)  # only RO1 blocks

    def test_platform_gap_detected(self):
        pid, plan_id, run_id = self.setup_project_plan_run()
        # RO1 requires Reddit + Twitter/X; only Reddit is actually covered.
        self.make_evidence(run_id, objective_id="RO1", unit_id="EU1", platform="Reddit",
                            text_excerpt="Reddit-only finding leaves a Twitter/X coverage gap.")
        elib.ingest_evidence(pid, run_id)

        report = elib.get_coverage_report(pid)
        ro1 = next(o for o in report["objectives"] if o["objective_id"] == "RO1")
        self.assertIn("Twitter/X", ro1["platform_gaps"])
        self.assertNotIn("Reddit", ro1["platform_gaps"])


if __name__ == "__main__":
    unittest.main()
