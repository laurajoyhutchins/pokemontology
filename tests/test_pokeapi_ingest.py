"""Tests for the PokeAPI ingestion pipeline."""

from __future__ import annotations

import json

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pokemontology.ingest import pokeapi_ingest
from tests.support import copy_fixture_tree, fixture_path


PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")
PKMI = Namespace("https://laurajoyhutchins.github.io/pokemontology/id/")


def test_fetch_seed_data_expands_related_resources(tmp_path, monkeypatch) -> None:
    fixture_payloads: dict[tuple[str, str], dict] = {}
    for path in fixture_path("pokeapi", "raw").rglob("*.json"):
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
    copy_fixture_tree("pokeapi", "raw", destination=raw_dir)

    graph = pokeapi_ingest.build_graph_from_raw(raw_dir)

    species = PKMI["species/froakie"]
    move_record = PKMI["assignment/move-learn/pokemon/froakie/move/bubble/ruleset/x-y"]

    assert (species, RDF.type, PKM.Species) in graph
    assert not any(graph.triples((PKMI["variant/froakie"], RDF.type, PKM.Variant)))
    assert (PKMI["ruleset/x-y"], RDF.type, PKM.Ruleset) in graph
    assert (move_record, RDF.type, PKM.MoveLearnRecord) in graph
    assert (move_record, PKM.hasContext, PKMI["ruleset/x-y"]) in graph
    assert (move_record, PKM.aboutPokemon, species) in graph
    assert (PKMI["artifact/pokeapi"], RDF.type, PKM.EvidenceArtifact) in graph
    assert (
        PKMI["reference/pokeapi/pokemon-species/froakie"],
        PKM.refersToEntity,
        species,
    ) in graph
    assert (
        PKMI["reference/pokeapi/move/bubble"],
        PKM.describedByArtifact,
        PKMI["artifact/pokeapi"],
    ) in graph
    assert (
        PKMI["reference/pokeapi/pokemon/froakie"],
        PKM.refersToEntity,
        species,
    ) in graph


def test_build_ttl_from_raw_serializes_valid_turtle(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    copy_fixture_tree("pokeapi", "raw", destination=raw_dir)

    ttl = pokeapi_ingest.build_ttl_from_raw(raw_dir)
    graph = Graph()
    graph.parse(data=ttl, format="turtle")

    assert len(graph) > 0
    assert any(graph.triples((None, RDF.type, PKM.MoveLearnRecord)))
    assert any(graph.triples((None, RDF.type, PKM.ExternalEntityReference)))
    assert any(graph.triples((None, RDF.type, PKM.MovePropertyAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.TypingAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.StatAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.AbilityAssignment)))
