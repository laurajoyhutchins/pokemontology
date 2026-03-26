"""Tests that all canonical TTL files parse without error."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, URIRef

REPO = Path(__file__).parent.parent

TTL_FILES = [
    REPO / "build" / "ontology.ttl",
    REPO / "build" / "shapes.ttl",
    REPO / "docs" / "ontology.ttl",
    REPO / "docs" / "shapes.ttl",
    REPO / "examples" / "fixtures" / "froakie-caterpie-seed.ttl",
    REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl",
]


@pytest.mark.parametrize("path", TTL_FILES, ids=lambda p: p.name)
def test_ttl_parses(path: Path) -> None:
    g = Graph()
    g.parse(path, format="turtle")
    assert len(g) > 0, f"{path.name} parsed but contains no triples"


def test_built_ontology_has_single_version_info() -> None:
    g = Graph()
    g.parse(REPO / "build" / "ontology.ttl", format="turtle")
    ontology = URIRef("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl")
    values = sorted(
        str(obj)
        for obj in g.objects(
            ontology, URIRef("http://www.w3.org/2002/07/owl#versionInfo")
        )
    )
    assert values == ["1.1"]
