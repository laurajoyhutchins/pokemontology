"""Regression tests for lightweight external dataset references."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace, URIRef


REPO = Path(__file__).parent.parent
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")
OWL_SAME_AS = URIRef("http://www.w3.org/2002/07/owl#sameAs")


def test_fixture_uses_external_reference_nodes_for_pokemonkg() -> None:
    graph = Graph()
    graph.parse(
        REPO / "examples" / "fixtures" / "froakie-caterpie-seed.ttl", format="turtle"
    )

    refs = list(
        graph.subjects(
            predicate=PKM.describedByArtifact, object=PKM.DatasetArtifact_PokemonKG
        )
    )
    assert refs, (
        "Expected at least one PokemonKG external reference node in the fixture."
    )
    for ref in refs:
        assert (ref, PKM.refersToEntity, None) in graph
        assert (ref, PKM.hasExternalIRI, None) in graph


def test_fixture_does_not_assert_owl_same_as_for_pokemonkg_links() -> None:
    graph = Graph()
    graph.parse(
        REPO / "examples" / "fixtures" / "froakie-caterpie-seed.ttl", format="turtle"
    )
    same_as_links = list(graph.triples((None, OWL_SAME_AS, None)))
    assert same_as_links == []
