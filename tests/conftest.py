"""Session-scoped graph fixtures shared across test modules."""
from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph

REPO = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def ontology_graph() -> Graph:
    g = Graph()
    g.parse(REPO / "ontology" / "pokemon-mechanics-ontology.ttl", format="turtle")
    return g


@pytest.fixture(scope="session")
def slice_graph() -> Graph:
    g = Graph()
    g.parse(REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl", format="turtle")
    return g


@pytest.fixture(scope="session")
def combined_graph(ontology_graph: Graph, slice_graph: Graph) -> Graph:
    return ontology_graph + slice_graph
