"""Tests for the replay acquisition and curation pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pokemontology.replay import replay_dataset
from tests.support import REPO, read_json, write_json


REPLAY_JSON = (
    REPO
    / "examples"
    / "replays"
    / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
)
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


def test_fetch_index_caches_search_pages(tmp_path, monkeypatch) -> None:
    responses = {
        replay_dataset._search_url(
            formatid="gen9vgc2025reggbo3", page=1, username=None
        ): [
            {
                "id": "battle-1",
                "format": "gen9vgc2025reggbo3",
                "players": ["a", "b"],
                "rating": 1600,
            },
        ],
        replay_dataset._search_url(
            formatid="gen9vgc2025reggbo3", page=2, username=None
        ): [],
    }
    requested: list[str] = []
    sleep_calls: list[float] = []

    def fake_fetch(url: str, timeout: float) -> object:
        requested.append(url)
        return responses[url]

    monkeypatch.setattr(replay_dataset, "fetch_json_url", fake_fetch)
    monkeypatch.setattr(
        replay_dataset.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    stats = replay_dataset.fetch_index(
        formatid="gen9vgc2025reggbo3",
        index_dir=tmp_path,
        max_pages=None,
        username=None,
        delay_seconds=0.25,
        timeout=1.0,
        force=False,
    )

    assert stats.fetches == 2
    assert stats.pages_seen == 2
    assert stats.entries_seen == 1
    assert sleep_calls == [0.25, 0.25]
    assert (tmp_path / "gen9vgc2025reggbo3" / "all" / "page_1.json").exists()

    requested.clear()
    sleep_calls.clear()
    cached = replay_dataset.fetch_index(
        formatid="gen9vgc2025reggbo3",
        index_dir=tmp_path,
        max_pages=1,
        username=None,
        delay_seconds=0.25,
        timeout=1.0,
        force=False,
    )
    assert cached.cache_hits == 1
    assert cached.fetches == 0
    assert requested == []
    assert sleep_calls == []


def test_curate_replay_ids_filters_on_format_rating_and_player_count(tmp_path) -> None:
    page_dir = tmp_path / "index" / "gen9vgc2025reggbo3" / "all"
    page_dir.mkdir(parents=True)
    write_json(
        page_dir / "page_1.json",
        [
            {
                "id": "keep-me",
                "format": "gen9vgc2025reggbo3",
                "players": ["a", "b"],
                "rating": 1650,
            },
            {
                "id": "too-low",
                "format": "gen9vgc2025reggbo3",
                "players": ["a", "b"],
                "rating": 1200,
            },
            {
                "id": "wrong-format",
                "format": "gen9ou",
                "players": ["a", "b"],
                "rating": 1900,
            },
            {
                "id": "not-heads-up",
                "format": "gen9vgc2025reggbo3",
                "players": ["solo"],
                "rating": 1700,
            },
        ],
    )

    curated_path = tmp_path / "curated.json"
    payload = replay_dataset.curate_replay_ids(
        tmp_path / "index",
        curated_path,
        formats={"gen9vgc2025reggbo3"},
        min_rating=1500,
        min_uploadtime=None,
        require_two_players=True,
    )

    assert payload["replay_ids"] == ["keep-me"]
    assert read_json(curated_path)["replay_ids"] == ["keep-me"]


def test_fetch_replays_uses_curated_ids_and_caches_json(tmp_path, monkeypatch) -> None:
    curated_path = tmp_path / "curated.json"
    write_json(curated_path, {"replay_ids": ["battle-1", "battle-2"]})
    requested: list[str] = []
    sleep_calls: list[float] = []

    def fake_fetch(url: str, timeout: float) -> object:
        requested.append(url)
        replay_id = url.rsplit("/", 1)[-1].removesuffix(".json")
        return {
            "id": replay_id,
            "format": "gen9vgc2025reggbo3",
            "players": ["Alice", "Bob"],
            "log": "|turn|1\n|switch|p1a: Pikachu|Pikachu, L50|100/100\n",
        }

    monkeypatch.setattr(replay_dataset, "fetch_json_url", fake_fetch)
    monkeypatch.setattr(
        replay_dataset.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    stats = replay_dataset.fetch_replays(
        curated_path,
        tmp_path / "raw",
        delay_seconds=0.5,
        timeout=1.0,
        force=False,
    )

    assert stats.fetches == 2
    assert stats.replay_ids_seen == 2
    assert sleep_calls == [0.5, 0.5]
    assert requested == [
        "https://replay.pokemonshowdown.com/battle-1.json",
        "https://replay.pokemonshowdown.com/battle-2.json",
    ]
    assert (tmp_path / "raw" / "battle-1.json").exists()


def test_transform_replays_writes_ttl_and_manifest(tmp_path) -> None:
    curated_path = tmp_path / "curated.json"
    write_json(curated_path, {"replay_ids": ["battle-1"]})
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    replay_payload = json.loads(REPLAY_JSON.read_text(encoding="utf-8"))
    replay_payload["id"] = "battle-1"
    write_json(raw_dir / "battle-1.json", replay_payload)

    stats = replay_dataset.transform_replays(curated_path, raw_dir, tmp_path / "ttl")

    assert stats.replay_ids_seen == 1
    assert stats.slices_written == 1
    ttl_path = tmp_path / "ttl" / "battle-1.ttl"
    assert ttl_path.exists()
    manifest = read_json(tmp_path / "ttl" / "manifest.json")
    assert manifest["slices"][0]["id"] == "battle-1"

    graph = Graph()
    graph.parse(ttl_path, format="turtle")
    assert any(graph.triples((None, RDF.type, PKM.Battle)))


def test_transform_replays_writes_canonical_bundle(tmp_path) -> None:
    curated_path = tmp_path / "curated.json"
    write_json(curated_path, {"replay_ids": ["battle-1"]})
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    replay_payload = json.loads(REPLAY_JSON.read_text(encoding="utf-8"))
    replay_payload["id"] = "battle-1"
    write_json(raw_dir / "battle-1.json", replay_payload)

    bundle_path = tmp_path / "ingested" / "showdown.ttl"
    stats = replay_dataset.transform_replays(
        curated_path,
        raw_dir,
        tmp_path / "ttl",
        bundle_path=bundle_path,
    )

    assert stats.bundle_written is True
    assert bundle_path.exists()

    graph = Graph()
    graph.parse(bundle_path, format="turtle")
    assert any(graph.triples((None, RDF.type, PKM.Battle)))
