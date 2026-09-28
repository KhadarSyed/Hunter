"""Brand logo resolution: saved table first, then Brandfetch, then Google Images.

Network calls are faked, so these tests are offline and deterministic.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("HUNTER_AGENT_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BRANDFETCH_API_KEY", "test-key")
os.environ.setdefault("BRANDFETCH_CLIENT_ID", "test-client")
os.environ.setdefault("SERP_API_KEY", "test-serp")

from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from agent.app.core import config, store  # noqa: E402
from agent.app.domains.research import brandfetch as bf  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


def fake_apis(brandfetch: dict[str, list], google: list[str], calls: list[str]):
    """requests.get stand-in: Brandfetch search results by query, Google image URLs."""
    def get(url, **kwargs):
        if "serpapi.com" in url:
            calls.append("google")
            return FakeResponse({"images_results": [{"original": u} for u in google]})
        query = requests.utils.unquote(url.rsplit("/", 1)[-1])
        calls.append(f"brandfetch:{query}")
        return FakeResponse(brandfetch.get(query, []))
    return get


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_DB_PATH", Path(tmp_path) / "memory.db")
    store.init_intelligence_db()


def test_brandfetch_result_is_saved_and_served_from_table_next_time():
    calls: list[str] = []
    apis = fake_apis({"Heineken": [{"name": "Heineken", "domain": "heineken.com"}]}, [], calls)
    with mock.patch.object(bf.requests, "get", side_effect=apis):
        first = bf.resolve_logo("Heineken")
        second = bf.resolve_logo("  heineken ")  # same brand, different spacing/case
    assert first["source"] == "brandfetch" and first["cached"] is False
    assert first["logo_url"].startswith("https://cdn.brandfetch.io/heineken.com")
    assert second["cached"] is True and second["logo_url"] == first["logo_url"]
    assert calls == ["brandfetch:Heineken"]  # the second lookup never left the table


def test_unrelated_brandfetch_match_is_rejected_and_google_svg_used():
    calls: list[str] = []
    apis = fake_apis(
        {"Acme Rockets": [{"name": "Corpay", "domain": "corpay.com"}], "AcmeRockets": []},
        ["https://example.com/photo.png", "https://cdn.x.com/acme-rockets-logo.png",
         "https://cdn.x.com/acme-rockets.svg"],
        calls,
    )
    with mock.patch.object(bf.requests, "get", side_effect=apis):
        result = bf.resolve_logo("Acme Rockets")
    assert result["source"] == "google"
    assert result["logo_url"] == "https://cdn.x.com/acme-rockets.svg"  # plausible + .svg preferred
    assert store.get_brand_logo("acme rockets")["source"] == "google"


def test_name_with_spaces_is_retried_without_them():
    apis = fake_apis(
        {"MC Donald's": [{"name": "MC", "domain": "mc-powersports.com"}],
         "MCDonald's": [{"name": "McDonald's", "domain": "mcdonalds.com"}]},
        [], [],
    )
    with mock.patch.object(bf.requests, "get", side_effect=apis):
        result = bf.resolve_logo("MC Donald's")
    assert result["source"] == "brandfetch" and result["domain"] == "mcdonalds.com"


def test_not_found_is_saved_but_generic_words_do_not_match_google():
    apis = fake_apis({}, ["https://upload.wikimedia.org/X_Corp._logo.svg"], [])
    with mock.patch.object(bf.requests, "get", side_effect=apis):
        result = bf.resolve_logo("Zxqvbnm Corp")
    assert result["source"] == "none" and result["logo_url"] is None
    assert store.get_brand_logo("zxqvbnm corp")["source"] == "none"


def test_transient_failure_is_not_saved():
    with mock.patch.object(bf.requests, "get", side_effect=requests.Timeout()):
        result = bf.resolve_logo("Brandnew Timeoutco")
    assert result["logo_url"] is None and result["cached"] is False
    assert store.get_brand_logo("brandnew timeoutco") is None  # will be retried next time
