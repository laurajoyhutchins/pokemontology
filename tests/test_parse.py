"""Tests that all canonical TTL files parse without error."""

from __future__ import annotations

import pytest
from rdflib import Graph, URIRef

from pokemontology._script_loader import repo_path


REPO = repo_path()
EXAMPLE_TTL_FILES = [
    REPO / "docs" / "ontology.ttl",
    REPO / "docs" / "shapes.ttl",
    REPO / "examples" / "fixtures" / "froakie-caterpie-seed.ttl",
    REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl",
]


def test_built_ontology_parses(built_ontology_text: str) -> None:
    graph = Graph()
    graph.parse(data=built_ontology_text, format="turtle")
    assert len(graph) > 0


def test_built_shapes_parse(built_shapes_text: str) -> None:
    graph = Graph()
    graph.parse(data=built_shapes_text, format="turtle")
    assert len(graph) > 0


@pytest.mark.parametrize("path", EXAMPLE_TTL_FILES, ids=lambda p: p.name)
def test_repo_ttl_parses(path: Path) -> None:
    graph = Graph()
    graph.parse(path, format="turtle")
    assert len(graph) > 0, f"{path.name} parsed but contains no triples"


def test_built_ontology_has_single_version_info(ontology_graph: Graph) -> None:
    ontology = URIRef("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl")
    values = sorted(
        str(obj)
        for obj in ontology_graph.objects(
            ontology, URIRef("http://www.w3.org/2002/07/owl#versionInfo")
        )
    )
    assert values == ["1.1"]
