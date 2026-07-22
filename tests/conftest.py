"""Session-scoped graph fixtures shared across test modules."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from rdflib import Graph

from pokemontology.build import build_ontology
from tests.support import REPO


SYNTHETIC_REPLAY = REPO / "examples" / "fixtures" / "synthetic-battle.json"
SYNTHETIC_SLICE = REPO / "examples" / "fixtures" / "synthetic-battle-slice.ttl"


def pytest_collection_modifyitems() -> None:
    """Redirect legacy replay-test constants to the project-authored fixture.

    Pytest may import the same test file either as ``tests.test_cli`` or
    ``test_cli`` depending on invocation and import mode. Support both forms until
    the old constants are removed directly under issue #17.
    """
    for module_name in (
        "tests.test_cli",
        "test_cli",
        "tests.test_replay_dataset",
        "test_replay_dataset",
    ):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "REPLAY_JSON"):
            module.REPLAY_JSON = SYNTHETIC_REPLAY


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
    graph.parse(SYNTHETIC_SLICE, format="turtle")
    return graph


@pytest.fixture(scope="session")
def combined_graph(ontology_graph: Graph, slice_graph: Graph) -> Graph:
    return ontology_graph + slice_graph
