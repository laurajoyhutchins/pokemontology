"""Tests for the Veekun ingestion pipeline."""

from __future__ import annotations

import io
import tarfile

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pokemontology.ingest import veekun_ingest
from tests.support import copy_fixture_tree, fixture_path


PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


def test_extract_upstream_csv_archive_writes_required_files(tmp_path) -> None:
    raw_fixture = fixture_path("veekun_raw")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in raw_fixture.glob("*.csv"):
            archive.add(
                path,
                arcname=f"pokedex-master/pokedex/data/csv/{path.name}",
            )

    output_dir = tmp_path / "raw"
    veekun_ingest.extract_upstream_csv_archive(buffer.getvalue(), output_dir)

    assert (output_dir / "pokemon.csv").exists()
    assert (output_dir / "move_changelog.csv").exists()


def test_normalize_veekun_csv_emits_expected_export(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    source_dir = tmp_path / "export"
    copy_fixture_tree("veekun_raw", destination=raw_dir)

    veekun_ingest.normalize_veekun_csv(raw_dir, source_dir, include_learnsets=True)

    graph = veekun_ingest.build_graph_from_csv(source_dir)
    assert (PKM.Species_froakie, RDF.type, PKM.Species) in graph
    assert (PKM.Variant_froakie, PKM.belongsToSpecies, PKM.Species_froakie) in graph
    assert (PKM.Ruleset_x_y, RDF.type, PKM.Ruleset) in graph
    assert any(graph.triples((PKM.MovePropertyAssignment_bubble_x_y, PKM.hasPP, None)))
    assert any(
        graph.triples(
            (
                PKM.MovePropertyAssignment_bubble_omega_ruby_alpha_sapphire,
                PKM.hasPriority,
                None,
            )
        )
    )
    assert any(graph.triples((None, RDF.type, PKM.MoveLearnRecord)))


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


def test_build_graph_from_csv_allows_blank_move_numeric_fields(tmp_path) -> None:
    source_dir = tmp_path / "veekun_export"
    copy_fixture_tree("veekun_export", destination=source_dir)
    path = source_dir / "move_property_assignments.csv"
    path.write_text(
        "move_identifier,version_group_identifier,move_type_identifier,base_power,accuracy,pp,priority\n"
        "bubble,x-y,water,,100,30,0\n",
        encoding="utf-8",
    )

    graph = veekun_ingest.build_graph_from_csv(source_dir)
    assignment = PKM.MovePropertyAssignment_bubble_x_y

    assert any(graph.triples((None, RDF.type, PKM.MovePropertyAssignment)))
    assert not any(graph.triples((assignment, PKM.hasBasePower, None)))


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
