"""SHACL conformance: the example slice must conform to the shapes graph."""
from __future__ import annotations

from pathlib import Path

from pyshacl import validate
from rdflib import Graph

REPO = Path(__file__).parent.parent

ONTOLOGY = REPO / "build" / "ontology.ttl"
SHAPES = REPO / "build" / "shapes.ttl"
SLICE = REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl"


def _load(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


def test_slice_conforms_to_shapes() -> None:
    conforms, results_graph, results_text = validate(
        data_graph=_load(SLICE),
        shacl_graph=_load(SHAPES),
        ont_graph=_load(ONTOLOGY),
        inference="rdfs",
        abort_on_first=False,
    )
    assert conforms, f"SHACL violations found:\n{results_text}"
