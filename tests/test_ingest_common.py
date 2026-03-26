"""Tests for shared ingestion/reference helpers."""

from __future__ import annotations

from rdflib import Graph
from rdflib.namespace import RDF

from pokemontology.ingest_common import (
    PKM,
    add_dataset_artifact,
    add_dataset_header,
    add_external_reference,
    bind_namespaces,
    iri_for,
    sanitize_identifier,
)


def test_sanitize_identifier_normalizes_punctuation() -> None:
    assert sanitize_identifier("pokemon-species") == "pokemon_species"
    assert sanitize_identifier("  Bubble Beam  ") == "Bubble_Beam"


def test_add_external_reference_emits_standard_pattern() -> None:
    graph = Graph()
    bind_namespaces(graph)
    add_dataset_header(graph, "Test dataset", "test.ttl", "test comment")
    add_dataset_artifact(
        graph, PKM.DatasetArtifact_PokeAPI, "PokeAPI", "https://pokeapi.co/api/v2/"
    )

    entity_iri = iri_for("Move", "bubble")
    graph.add((entity_iri, RDF.type, PKM.Move))
    ref_iri = add_external_reference(
        graph,
        source_slug="PokeAPI",
        resource="move",
        identifier="bubble",
        entity_iri=entity_iri,
        artifact_iri=PKM.DatasetArtifact_PokeAPI,
        external_iri="https://pokeapi.co/api/v2/move/145/",
    )

    assert (ref_iri, RDF.type, PKM.ExternalEntityReference) in graph
    assert (ref_iri, PKM.refersToEntity, entity_iri) in graph
    assert (ref_iri, PKM.describedByArtifact, PKM.DatasetArtifact_PokeAPI) in graph
