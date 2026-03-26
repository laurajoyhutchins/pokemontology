"""Tests for the local-only Veekun ingestion scaffold."""

from __future__ import annotations

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pokemontology.ingest import veekun_ingest
from tests.support import copy_fixture_tree


PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


def test_build_graph_from_csv_emits_contextual_mechanics_assignments(tmp_path) -> None:
    source_dir = tmp_path / "veekun_export"
    copy_fixture_tree("veekun_export", destination=source_dir)

    graph = veekun_ingest.build_graph_from_csv(source_dir)

    assert (PKM.DatasetArtifact_Veekun, RDF.type, PKM.EvidenceArtifact) in graph
    assert (PKM.Species_froakie, RDF.type, PKM.Species) in graph
    assert (PKM.Variant_froakie, PKM.belongsToSpecies, PKM.Species_froakie) in graph
    assert (PKM.Ruleset_x_y, RDF.type, PKM.Ruleset) in graph
    assert any(graph.triples((None, RDF.type, PKM.TypingAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.AbilityAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.StatAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.MovePropertyAssignment)))
    assert any(graph.triples((None, RDF.type, PKM.MoveLearnRecord)))
    assert any(graph.triples((None, RDF.type, PKM.TypeEffectivenessAssignment)))


def test_build_ttl_from_csv_serializes_valid_turtle(tmp_path) -> None:
    source_dir = tmp_path / "veekun_export"
    copy_fixture_tree("veekun_export", destination=source_dir)

    ttl = veekun_ingest.build_ttl_from_csv(source_dir)
    graph = Graph()
    graph.parse(data=ttl, format="turtle")

    assert len(graph) > 0
    assert any(graph.triples((None, RDF.type, PKM.ExternalEntityReference)))
    assert (
        PKM.Ref_Veekun_species_froakie,
        PKM.refersToEntity,
        PKM.Species_froakie,
    ) in graph
