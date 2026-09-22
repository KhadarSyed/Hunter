"""Tests for query_evaluator: format detection, record classification, evaluation metrics."""
from __future__ import annotations

import csv
import os
import tempfile
import pytest

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())

from agent.app.agents.query_evaluator import detect_format, classify_record, evaluate_sample


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "sample.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Headline", "URL", "Date", "Source Name", "Hit Sentence", "Reach"])
        writer.writerow(["Mrs. T's Pierogies launches new flavor", "https://example.com/1", "2026-03-15", "Frozen Food Digest", "Mrs. T's announces a new cheddar variety", "50000"])
        writer.writerow(["Mom tips for weeknight dinners", "https://example.com/2", "2026-03-10", "Parenting Today", "Quick dinner ideas for busy moms", "120000"])
        writer.writerow(["NFL Draft predictions for 2026", "https://example.com/3", "2026-03-12", "ESPN", "Top picks for the upcoming draft", "500000"])
        writer.writerow(["Best frozen meals for families", "https://example.com/4", "2026-03-08", "Good Housekeeping", "Mrs. T's pierogies and other family favorites", "80000"])
        writer.writerow(["New movie releases this week", "https://example.com/5", "2026-03-14", "Hollywood Reporter", "Latest films hitting theaters", "300000"])
    return str(path)


@pytest.fixture
def mrs_ts_spec():
    return {
        "commissioning_brand": {"name": "Mrs. T's"},
        "research_subject": {"description": "Moms and food preparation"},
        "research_questions": [
            {"id": "RQ1", "text": "What are moms' priorities when choosing frozen foods?"},
            {"id": "RQ2", "text": "What role does food preparation play in family life?"},
        ],
        "audience": {"primary": "US moms"},
    }


@pytest.fixture
def basic_strategy():
    return {
        "core_queries": [
            {"type": "balanced", "query": '(mom OR moms) AND ("Mrs. T\'s" OR pierogies)'}
        ],
        "query_modules": [
            {"module_type": "brand", "terms": ["Mrs. T's", "pierogies", "Mrs Ts"]},
            {"module_type": "audience", "terms": ["mom", "moms", "mother"]},
        ],
        "exclusion_logic": {
            "entity_exclusions": [{"term": "Mrs. Doubtfire"}],
            "spam_exclusions": ["coupon", "giveaway"],
        },
    }


class TestFormatDetection:
    def test_detect_csv(self, sample_csv):
        result = detect_format(sample_csv)
        assert result["file_type"] == "csv"
        assert result["record_count"] == 5
        assert "column_mapping" in result

    def test_detect_meltwater_flag(self, sample_csv):
        result = detect_format(sample_csv)
        assert isinstance(result["is_meltwater"], bool)

    def test_column_mapping_identifies_headline(self, sample_csv):
        result = detect_format(sample_csv)
        mapping = result["column_mapping"]
        assert "headline" in mapping

    def test_column_mapping_identifies_url(self, sample_csv):
        result = detect_format(sample_csv)
        mapping = result["column_mapping"]
        assert "url" in mapping

    def test_missing_file_returns_errors(self):
        result = detect_format("/nonexistent/file.csv")
        assert len(result["errors"]) > 0

    def test_unsupported_extension(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{}")
        result = detect_format(str(path))
        assert len(result["errors"]) > 0
        assert result["file_type"] == "unknown"


class TestRecordClassification:
    def test_relevant_brand_match(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "Mrs. T's Pierogies launches new flavor", "hit_sentence": "mom approved frozen dinner"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert result["classification"] in ("relevant", "partially_relevant")

    def test_irrelevant_no_match(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "NFL Draft predictions", "hit_sentence": "football sports picks"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert result["classification"] in ("irrelevant", "uncertain")

    def test_audience_only_no_brand_match(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "Mom tips for weeknight dinners", "hit_sentence": "busy moms cooking meals"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert result["classification"] in ("partially_relevant", "irrelevant", "uncertain")

    def test_audience_plus_brand_is_relevant(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "Mom tips for weeknight dinners with pierogies", "hit_sentence": "busy moms cooking Mrs. T's meals"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert result["classification"] in ("relevant", "partially_relevant")

    def test_classification_has_confidence(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "Test article", "hit_sentence": "test content"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert "confidence" in result
        assert result["confidence"] in ("high", "medium", "low")

    def test_classification_has_reasons(self, mrs_ts_spec, basic_strategy):
        record = {"headline": "Mrs. T's frozen pierogies review", "hit_sentence": "family dinner staple"}
        result = classify_record(record, mrs_ts_spec, basic_strategy)
        assert "reasons" in result
        assert isinstance(result["reasons"], list)


class TestEvaluateSample:
    def test_evaluate_returns_all_keys(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert "total_records" in result
        assert "valid_records" in result
        assert "duplicate_records" in result
        assert "precision_estimate" in result
        assert "false_positive_rate" in result
        assert "estimated_recall_risk" in result
        assert "classifications" in result

    def test_total_records_correct(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert result["total_records"] == 5

    def test_recall_labeled_correctly(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert "estimated_recall_risk" in result
        assert result["estimated_recall_risk"] in ("low", "moderate", "high", "very_high", "unknown")

    def test_counts_sum_correctly(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        total = (result["relevant_count"] + result["partially_relevant_count"]
                 + result["irrelevant_count"] + result["uncertain_count"])
        assert total == result["valid_records"]

    def test_precision_in_range(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert 0.0 <= result["precision_estimate"] <= 1.0

    def test_false_positive_rate_in_range(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert 0.0 <= result["false_positive_rate"] <= 1.0

    def test_no_validation_errors_for_valid_csv(self, sample_csv, mrs_ts_spec, basic_strategy):
        result = evaluate_sample(sample_csv, mrs_ts_spec, basic_strategy)
        assert result["validation_errors"] == []


class TestDeduplication:
    def test_duplicate_urls_removed(self, tmp_path, mrs_ts_spec, basic_strategy):
        path = tmp_path / "dupes.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Headline", "URL", "Date"])
            writer.writerow(["Article A", "https://example.com/same", "2026-01-01"])
            writer.writerow(["Article A Copy", "https://example.com/same", "2026-01-01"])
            writer.writerow(["Article B", "https://example.com/other", "2026-01-02"])
        result = evaluate_sample(str(path), mrs_ts_spec, basic_strategy)
        assert result["duplicate_records"] >= 1
        assert result["valid_records"] < result["total_records"]
