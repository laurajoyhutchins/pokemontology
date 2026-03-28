"""Unit tests for meta_ingest aggregation and graph building."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib.namespace import RDF

from pokemontology.ingest.meta_ingest import (
    _extract_team_species,
    aggregate,
    build_graph,
)
from pokemontology.ingest_common import PKM


EXAMPLE_REPLAY = (
    Path(__file__).parent.parent
    / "examples"
    / "replays"
    / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
)


# ---------------------------------------------------------------------------
# _extract_team_species
# ---------------------------------------------------------------------------


def test_extract_team_species_from_poke_lines():
    log = "\n".join([
        "|clearpoke",
        "|poke|p1|Koraidon, L50|",
        "|poke|p1|Rillaboom, L50, M|",
        "|poke|p2|Arceus-Fire, L50|",
        "|poke|p2|Volcarona, L50, M|",
        "|turn|1",
        "|move|p1a: Koraidon|Flare Blitz|p2a: Arceus",
    ])
    species = _extract_team_species(log)
    assert "Koraidon" in species
    assert "Rillaboom" in species
    assert "Arceus-Fire" in species
    assert "Volcarona" in species


def test_extract_team_species_fallback_to_switch():
    log = "\n".join([
        "|switch|p1a: Pikachu|Pikachu, L50|100/100",
        "|switch|p2a: Garchomp|Garchomp, L50|100/100",
        "|turn|1",
        "|switch|p1b: Eevee|Eevee, L50|100/100",
    ])
    species = _extract_team_species(log)
    assert "Pikachu" in species
    assert "Garchomp" in species
    assert "Eevee" in species


def test_extract_team_species_strips_form_suffix():
    log = "|poke|p1|Indeedee-F, L50, F|\n|poke|p2|Deoxys-Attack, L50|"
    species = _extract_team_species(log)
    assert "Indeedee-F" in species
    assert "Deoxys-Attack" in species


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_aggregate_example_replay(tmp_path):
    result = aggregate([EXAMPLE_REPLAY])
    assert result["replay_count"] == 1
    assert len(result["formats"]) == 1
    fmt = next(iter(result["formats"]))
    assert "VGC" in fmt or "Gen 9" in fmt

    species_battles = result["species_battles"]
    # Full 6-mon team preview gives 12 species (6 per player)
    assert len(species_battles) == 12
    # Every species appears in exactly 1 battle
    for battles in species_battles.values():
        assert len(battles) == 1

    move_battles = result["move_battles"]
    assert len(move_battles) > 0
    # Protect appears in the replay
    assert "Protect" in move_battles


def test_aggregate_empty():
    result = aggregate([])
    assert result["replay_count"] == 0
    assert result["species_battles"] == {}
    assert result["move_battles"] == {}


def test_aggregate_skips_missing_log(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "x-1", "format": "test", "players": ["a", "b"]}))
    result = aggregate([bad])
    assert result["replay_count"] == 1
    assert result["species_battles"] == {}


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_build_graph_contains_snapshot(tmp_path):
    g = build_graph([EXAMPLE_REPLAY], snapshot_date="2026-03-28")
    snapshots = list(g.subjects(RDF.type, PKM.MetaSnapshot))
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert "2026_03_28" in str(snapshot)


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_build_graph_species_stats(tmp_path):
    g = build_graph([EXAMPLE_REPLAY], snapshot_date="2026-03-28")
    species_stats = list(g.subjects(RDF.type, PKM.SpeciesUsageStat))
    assert len(species_stats) == 12


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_build_graph_move_stats(tmp_path):
    g = build_graph([EXAMPLE_REPLAY], snapshot_date="2026-03-28")
    move_stats = list(g.subjects(RDF.type, PKM.MoveUsageStat))
    assert len(move_stats) > 0


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_build_graph_usage_rate_in_range():
    g = build_graph([EXAMPLE_REPLAY], snapshot_date="2026-03-28")
    rates = [
        float(o)
        for _, _, o in g.triples((None, PKM.usageRate, None))
    ]
    for rate in rates:
        assert 0.0 <= rate <= 1.0


@pytest.mark.skipif(not EXAMPLE_REPLAY.exists(), reason="example replay not present")
def test_build_graph_has_ruleset_link():
    g = build_graph([EXAMPLE_REPLAY], snapshot_date="2026-03-28")
    snapshots = list(g.subjects(RDF.type, PKM.MetaSnapshot))
    assert snapshots
    ruleset_links = list(g.objects(snapshots[0], PKM.forFormat))
    assert len(ruleset_links) == 1
    assert "Ruleset_" in str(ruleset_links[0])


def test_build_graph_default_date_today():
    import datetime
    g = build_graph([], snapshot_date=None)
    snapshots = list(g.subjects(RDF.type, PKM.MetaSnapshot))
    # With no replays, still creates a snapshot but with default format
    # The snapshot date should be today
    today = datetime.date.today().isoformat().replace("-", "_")
    snapshot_iris = [str(s) for s in snapshots]
    assert any(today in iri for iri in snapshot_iris)
