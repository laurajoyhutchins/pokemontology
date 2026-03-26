"""SHACL conformance: the example slice must conform to the shapes graph."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

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


def _validate_data_graph(data_graph: Graph) -> tuple[bool, str]:
    conforms, results_graph, results_text = validate(
        data_graph=data_graph,
        shacl_graph=_load(SHAPES),
        ont_graph=_load(ONTOLOGY),
        inference="rdfs",
        abort_on_first=False,
    )
    return conforms, results_text


def _parse_ttl(ttl: str) -> Graph:
    g = Graph()
    g.parse(data=dedent(ttl), format="turtle")
    return g


def test_slice_conforms_to_shapes() -> None:
    conforms, results_text = _validate_data_graph(_load(SLICE))
    assert conforms, f"SHACL violations found:\n{results_text}"


def test_iv_assignment_rejects_values_above_31() -> None:
    conforms, results_text = _validate_data_graph(
        _parse_ttl(
            """
            @prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .

            pkm:Save1 a pkm:SaveFile .
            pkm:Mon1 a pkm:OwnedPokemon .
            pkm:HP a pkm:Stat .

            pkm:BadIV
                a pkm:IVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:HP ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasIVValue 32 .
            """
        )
    )
    assert not conforms
    assert "IV value in [0, 31]" in results_text


def test_ev_assignment_rejects_total_above_510() -> None:
    conforms, results_text = _validate_data_graph(
        _parse_ttl(
            """
            @prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .

            pkm:Save1 a pkm:SaveFile .
            pkm:Mon1 a pkm:OwnedPokemon .
            pkm:HP a pkm:Stat .
            pkm:Attack a pkm:Stat .
            pkm:Defense a pkm:Stat .

            pkm:EV1
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:HP ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 252 .

            pkm:EV2
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:Attack ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 252 .

            pkm:EV3
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:Defense ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 8 .
            """
        )
    )
    assert not conforms
    assert "must not exceed 510" in results_text


def test_ev_assignment_allows_total_of_510() -> None:
    conforms, results_text = _validate_data_graph(
        _parse_ttl(
            """
            @prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .

            pkm:Save1 a pkm:SaveFile .
            pkm:Mon1 a pkm:OwnedPokemon .
            pkm:HP a pkm:Stat .
            pkm:Attack a pkm:Stat .
            pkm:Defense a pkm:Stat .

            pkm:EV1
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:HP ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 252 .

            pkm:EV2
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:Attack ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 252 .

            pkm:EV3
                a pkm:EVAssignment ;
                pkm:aboutOwnedPokemon pkm:Mon1 ;
                pkm:aboutStat pkm:Defense ;
                pkm:hasContext pkm:Save1 ;
                pkm:hasEVValue 6 .
            """
        )
    )
    assert conforms, f"510-total EV spread should conform, but got:\n{results_text}"


def test_typing_assignment_rejects_duplicate_type_slots_per_variant_and_ruleset() -> None:
    conforms, results_text = _validate_data_graph(
        _parse_ttl(
            """
            @prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .

            pkm:Rule1 a pkm:Ruleset .
            pkm:Var1 a pkm:Variant .
            pkm:Fire a pkm:Type .
            pkm:Water a pkm:Type .

            pkm:Typing1
                a pkm:TypingAssignment ;
                pkm:aboutVariant pkm:Var1 ;
                pkm:aboutType pkm:Fire ;
                pkm:hasContext pkm:Rule1 ;
                pkm:hasTypeSlot 1 .

            pkm:Typing2
                a pkm:TypingAssignment ;
                pkm:aboutVariant pkm:Var1 ;
                pkm:aboutType pkm:Water ;
                pkm:hasContext pkm:Rule1 ;
                pkm:hasTypeSlot 1 .
            """
        )
    )
    assert not conforms
    assert "per variant/ruleset/type-slot" in results_text
