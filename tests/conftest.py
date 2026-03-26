"""Session-scoped graph fixtures shared across test modules."""

from __future__ import annotations

import pytest
from rdflib import Graph

from pokemontology._script_loader import repo_path
from scripts.build import build_ontology


REPO = repo_path()


@pytest.fixture(scope="session")
def built_artifacts() -> tuple[str, str, dict[str, object]]:
    return build_ontology.assemble_artifacts()


@pytest.fixture(scope="session")
def built_ontology_text(built_artifacts: tuple[str, str, dict[str, object]]) -> str:
    return built_artifacts[0]


@pytest.fixture(scope="session")
def built_shapes_text(built_artifacts: tuple[str, str, dict[str, object]]) -> str:
    return built_artifacts[1]


@pytest.fixture(scope="session")
def built_ontology_path(
    built_ontology_text: str, tmp_path_factory: pytest.TempPathFactory
) -> str:
    path = tmp_path_factory.mktemp("built-artifacts") / "ontology.ttl"
    path.write_text(built_ontology_text, encoding="utf-8")
    return str(path)


@pytest.fixture(scope="session")
def built_shapes_path(
    built_shapes_text: str, tmp_path_factory: pytest.TempPathFactory
) -> str:
    path = tmp_path_factory.mktemp("built-artifacts") / "shapes.ttl"
    path.write_text(built_shapes_text, encoding="utf-8")
    return str(path)


@pytest.fixture(scope="session")
def ontology_graph(built_ontology_text: str) -> Graph:
    graph = Graph()
    graph.parse(data=built_ontology_text, format="turtle")
    return graph


@pytest.fixture(scope="session")
def shapes_graph(built_shapes_text: str) -> Graph:
    graph = Graph()
    graph.parse(data=built_shapes_text, format="turtle")
    return graph


@pytest.fixture(scope="session")
def slice_graph() -> Graph:
    graph = Graph()
    graph.parse(
        REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl",
        format="turtle",
    )
    return graph


@pytest.fixture(scope="session")
def combined_graph(ontology_graph: Graph, slice_graph: Graph) -> Graph:
    return ontology_graph + slice_graph
