"""Tests for the cache-first PokeAPI scraper."""

from __future__ import annotations

import json

from pokemontology.ingest import pokeapi_scrape


def test_scrape_resource_fetches_pages_and_details_then_reuses_cache(
    tmp_path, monkeypatch
) -> None:
    responses = {
        "https://pokeapi.co/api/v2/move/?limit=2&offset=0": {
            "next": None,
            "results": [
                {"name": "bubble", "url": "https://pokeapi.co/api/v2/move/145/"},
                {"name": "growl", "url": "https://pokeapi.co/api/v2/move/45/"},
            ],
        },
        "https://pokeapi.co/api/v2/move/145/": {"id": 145, "name": "bubble"},
        "https://pokeapi.co/api/v2/move/45/": {"id": 45, "name": "growl"},
    }
    requested_urls: list[str] = []
    sleep_calls: list[float] = []

    def fake_fetch(url: str, timeout: float) -> dict:
        requested_urls.append(url)
        return responses[url]

    monkeypatch.setattr(pokeapi_scrape, "fetch_json_url", fake_fetch)
    monkeypatch.setattr(
        pokeapi_scrape.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    stats = pokeapi_scrape.scrape_resource(
        "move",
        tmp_path,
        include_details=True,
        page_size=2,
        max_pages=None,
        max_details=None,
        delay_seconds=0.25,
        timeout=1.0,
        force=False,
    )

    assert stats.page_fetches == 1
    assert stats.detail_fetches == 2
    assert stats.page_cache_hits == 0
    assert stats.detail_cache_hits == 0
    assert sleep_calls == [0.25, 0.25, 0.25]
    assert (tmp_path / "move" / "pages" / "offset_0_limit_2.json").exists()
    assert (tmp_path / "move" / "detail" / "bubble.json").exists()
    assert (tmp_path / "move" / "detail" / "growl.json").exists()

    requested_urls.clear()
    sleep_calls.clear()

    stats_cached = pokeapi_scrape.scrape_resource(
        "move",
        tmp_path,
        include_details=True,
        page_size=2,
        max_pages=None,
        max_details=None,
        delay_seconds=0.25,
        timeout=1.0,
        force=False,
    )

    assert stats_cached.page_fetches == 0
    assert stats_cached.detail_fetches == 0
    assert stats_cached.page_cache_hits == 1
    assert stats_cached.detail_cache_hits == 2
    assert requested_urls == []
    assert sleep_calls == []


def test_force_refetch_bypasses_existing_cache(tmp_path, monkeypatch) -> None:
    page_path = tmp_path / "type" / "pages" / "offset_0_limit_1.json"
    detail_path = tmp_path / "type" / "detail" / "water.json"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(
        json.dumps(
            {
                "next": None,
                "results": [
                    {"name": "water", "url": "https://pokeapi.co/api/v2/type/11/"}
                ],
            }
        )
    )
    detail_path.write_text(json.dumps({"id": 11, "name": "water"}))

    requested_urls: list[str] = []
    monkeypatch.setattr(
        pokeapi_scrape,
        "fetch_json_url",
        lambda url, timeout: (
            requested_urls.append(url)
            or (
                {
                    "next": None,
                    "results": [
                        {"name": "water", "url": "https://pokeapi.co/api/v2/type/11/"}
                    ],
                }
                if "limit=1&offset=0" in url
                else {"id": 11, "name": "water"}
            )
        ),
    )
    monkeypatch.setattr(pokeapi_scrape.time, "sleep", lambda seconds: None)

    stats = pokeapi_scrape.scrape_resource(
        "type",
        tmp_path,
        include_details=True,
        page_size=1,
        max_pages=1,
        max_details=1,
        delay_seconds=0.1,
        timeout=1.0,
        force=True,
    )

    assert stats.page_fetches == 1
    assert stats.detail_fetches == 1
    assert requested_urls == [
        "https://pokeapi.co/api/v2/type/?limit=1&offset=0",
        "https://pokeapi.co/api/v2/type/11/",
    ]
