"""Tests that all canonical TTL files parse without error."""
from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph

REPO = Path(__file__).parent.parent

TTL_FILES = [
    REPO / "build" / "ontology.ttl",
    REPO / "shapes" / "pokemon-mechanics-shapes.ttl",
    REPO / "examples" / "fixtures" / "froakie-caterpie-seed.ttl",
    REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl",
]


@pytest.mark.parametrize("path", TTL_FILES, ids=lambda p: p.name)
def test_ttl_parses(path: Path) -> None:
    g = Graph()
    g.parse(path, format="turtle")
    assert len(g) > 0, f"{path.name} parsed but contains no triples"
