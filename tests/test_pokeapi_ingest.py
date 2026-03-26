"""Tests for the PokeAPI ingestion pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pokemontology._script_loader import repo_path
from scripts.ingest import pokeapi_ingest


REPO = repo_path()
FIXTURES = REPO / "tests" / "fixtures" / "pokeapi" / "raw"
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


def _copy_raw_fixtures(destination: Path) -> None:
    shutil.copytree(FIXTURES, destination, dirs_exist_ok=True)


def test_fetch_seed_data_expands_related_resources(tmp_path, monkeypatch) -> None:
    fixture_payloads: dict[tuple[str, str], dict] = {}
    for path in FIXTURES.rglob("*.json"):
        resource = path.parent.name
        identifier = path.stem
        fixture_payloads[(resource, identifier)] = json.loads(
            path.read_text(encoding="utf-8")
        )

    def fake_fetch(resource: str, identifier: str, timeout: float) -> dict:
        return fixture_payloads[(resource, identifier)]

    monkeypatch.setattr(pokeapi_ingest, "fetch_resource", fake_fetch)

    raw_dir = tmp_path / "raw"
    pokeapi_ingest.fetch_seed_data({"pokemon": ["froakie"]}, raw_dir, timeout=1.0)

    assert (raw_dir / "pokemon" / "froakie.json").exists()
    assert (raw_dir / "pokemon-species" / "froakie.json").exists()
    assert (raw_dir / "move" / "bubble.json").exists()
    assert (raw_dir / "ability" / "torrent.json").exists()
    assert (raw_dir / "type" / "water.json").exists()
    assert (raw_dir / "stat" / "hp.json").exists()
    assert (raw_dir / "version-group" / "x_y.json").exists()


def test_build_graph_from_raw_emits_expected_ontology_nodes(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    _copy_raw_fixtures(raw_dir)

    graph = pokeapi_ingest.build_graph_from_raw(raw_dir)

    species = PKM.Species_froakie
    variant = PKM.Variant_froakie
    move_record = PKM.MoveLearnRecord_froakie_bubble_x_y

    assert (species, RDF.type, PKM.Species) in graph
    assert (variant, RDF.type, PKM.Variant) in graph
    assert (variant, PKM.belongsToSpecies, species) in graph
    assert (PKM.Ruleset_x_y, RDF.type, PKM.Ruleset) in graph
    assert (move_record, RDF.type, PKM.MoveLearnRecord) in graph
    assert (move_record, PKM.hasContext, PKM.Ruleset_x_y) in graph
    assert (PKM.DatasetArtifact_PokeAPI, RDF.type, PKM.EvidenceArtifact) in graph
    assert (
        PKM.Ref_PokeAPI_pokemon_species_froakie,
        PKM.refersToEntity,
        species,
    ) in graph
    assert (
        PKM.Ref_PokeAPI_move_bubble,
        PKM.describedByArtifact,
        PKM.DatasetArtifact_PokeAPI,
    ) in graph


def test_build_ttl_from_raw_serializes_valid_turtle(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    _copy_raw_fixtures(raw_dir)

    ttl = pokeapi_ingest.build_ttl_from_raw(raw_dir)
    graph = Graph()
    graph.parse(data=ttl, format="turtle")

    assert len(graph) > 0
    assert any(graph.triples((None, RDF.type, PKM.MoveLearnRecord)))
    assert any(graph.triples((None, RDF.type, PKM.ExternalEntityReference)))
    assert any(graph.triples((None, RDF.type, PKM.MovePropertyAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.TypingAssignment)))
    assert not any(graph.triples((None, RDF.type, PKM.StatAssignment)))
    assert not any(graph.triples((None, RDF.type, PKM.AbilityAssignment)))
