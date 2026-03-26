"""SHACL conformance: the example slice must conform to the shapes graph."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pyshacl import validate
from rdflib import Graph

from scripts.replay.replay_to_ttl_builder import build_graph

REPO = Path(__file__).parent.parent

ONTOLOGY = REPO / "build" / "ontology.ttl"
SHAPES = REPO / "build" / "shapes.ttl"
SLICE = REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl"
REPLAY_JSON = (
    REPO
    / "examples"
    / "replays"
    / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
)

# Parsed once per session; pyshacl reads but does not mutate these graphs.
_shapes_graph: Graph | None = None
_ontology_graph: Graph | None = None


def _get_shapes_graph() -> Graph:
    global _shapes_graph
    if _shapes_graph is None:
        _shapes_graph = Graph()
        _shapes_graph.parse(SHAPES, format="turtle")
    return _shapes_graph


def _get_ontology_graph() -> Graph:
    global _ontology_graph
    if _ontology_graph is None:
        _ontology_graph = Graph()
        _ontology_graph.parse(ONTOLOGY, format="turtle")
    return _ontology_graph


def _load(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


def _validate_data_graph(
    data_graph: Graph, *, inference: str = "rdfs"
) -> tuple[bool, str]:
    conforms, _results_graph, results_text = validate(
        data_graph=data_graph,
        shacl_graph=_get_shapes_graph(),
        ont_graph=_get_ontology_graph(),
        inference=inference,
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


@pytest.mark.slow
def test_generated_replay_graph_conforms_to_shapes() -> None:
    import json

    payload = json.loads(REPLAY_JSON.read_text(encoding="utf-8"))
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Generated replay graph violates SHACL:\n{results_text}"


def test_synthetic_status_and_target_resolution_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-status-targeting",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Thunder Wave|p2a: Bulbasaur",
                "|-status|p2a: Bulbasaur|par",
                "|move|p2a: Bulbasaur|Sleep Powder|p1a: Pikachu",
                "|-miss|p2a: Bulbasaur|p1a: Pikachu",
                "|move|p2a: Bulbasaur|Protect|p2a: Bulbasaur",
                "|-fail|p2a: Bulbasaur",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, (
        f"Synthetic status/target-resolution graph violates SHACL:\n{results_text}"
    )


def test_synthetic_teardown_projection_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-teardown-projection",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|-weather|SunnyDay",
                "|-fieldstart|move: Psychic Terrain",
                "|-sidestart|p1: Alice|move: Tailwind",
                "|-status|p2a: Bulbasaur|par",
                "|-singleturn|p1a: Pikachu|Protect",
                "|turn|2",
                "|upkeep",
                "|-curestatus|p2a: Bulbasaur|par",
                "|-weather|none",
                "|-fieldend|move: Psychic Terrain",
                "|-sideend|p1: Alice|move: Tailwind",
                "|-end|p1a: Pikachu|move: Protect",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, (
        f"Synthetic teardown/projection graph violates SHACL:\n{results_text}"
    )


def test_synthetic_stage_projection_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-stage-projection",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Nasty Plot|p1a: Pikachu",
                "|-boost|p1a: Pikachu|spa|2",
                "|turn|2",
                "|upkeep",
                "|move|p1a: Pikachu|Pain Split|p2a: Bulbasaur",
                "|-sethp|p1a: Pikachu|70/100|p2a: Bulbasaur|70/100|[from] move: Pain Split",
                "|-clearboost|p1a: Pikachu",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic stage projection graph violates SHACL:\n{results_text}"


def test_synthetic_item_and_ability_observation_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-item-ability-observation",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Knock Off|p2a: Bulbasaur",
                "|-ability|p2a: Bulbasaur|Overgrow",
                "|-enditem|p2a: Bulbasaur|Eviolite",
                "|move|p2a: Bulbasaur|Trick|p1a: Pikachu",
                "|-item|p1a: Pikachu|Leftovers|[from] move: Trick",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, (
        f"Synthetic item/ability observation graph violates SHACL:\n{results_text}"
    )


def test_synthetic_volatile_start_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-volatile-start",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Confuse Ray|p2a: Bulbasaur",
                "|-start|p2a: Bulbasaur|confusion",
                "|move|p2a: Bulbasaur|Destiny Bond|p2a: Bulbasaur",
                "|-singlemove|p2a: Bulbasaur|move: Destiny Bond",
                "|turn|2",
                "|upkeep",
                "|-end|p2a: Bulbasaur|confusion",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic volatile -start graph violates SHACL:\n{results_text}"


def test_synthetic_forme_change_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-formechange",
        "format": "[Gen 6] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Charizard|Charizard, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Charizard|Ember|p2a: Bulbasaur",
                "|-mega|p1a: Charizard|Charizard-Mega-Y|Charizardite Y",
                "|-formechange|p1a: Charizard|Charizard-Mega-Y, L50|100/100",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic forme change graph violates SHACL:\n{results_text}"


def test_synthetic_boost_operations_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-boost-ops",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Belly Drum|p1a: Pikachu",
                "|-setboost|p1a: Pikachu|atk|6",
                "|move|p2a: Bulbasaur|Topsy-Turvy|p1a: Pikachu",
                "|-invertboost|p1a: Pikachu",
                "|turn|2",
                "|upkeep",
                "|move|p1a: Pikachu|Guard Swap|p2a: Bulbasaur",
                "|-swapboost|p1a: Pikachu|p2a: Bulbasaur|def,spd",
                "|move|p2a: Bulbasaur|Haze|p1a: Pikachu",
                "|-clearpositiveboost|p1a: Pikachu|p2a: Bulbasaur|[from] move: Haze",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic boost-ops graph violates SHACL:\n{results_text}"


def test_synthetic_battle_outcome_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-battle-outcome",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Bulbasaur",
                "|-damage|p2a: Bulbasaur|0 fnt",
                "|faint|p2a: Bulbasaur",
                "|win|Alice",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic battle outcome graph violates SHACL:\n{results_text}"


def test_synthetic_cureteam_graph_conforms_to_shapes() -> None:
    payload = {
        "id": "synthetic-cureteam",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Blissey|Blissey, L50|100/100",
                "|switch|p2a: Venusaur|Venusaur, L50|100/100",
                "|-status|p1a: Blissey|brn",
                "|move|p1a: Blissey|Aromatherapy|p1a: Blissey",
                "|-cureteam|p1a: Blissey",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"Synthetic cureteam graph violates SHACL:\n{results_text}"


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
        ),
        inference="none",
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
        ),
        inference="none",
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
        ),
        inference="none",
    )
    assert conforms, f"510-total EV spread should conform, but got:\n{results_text}"


def test_typing_assignment_rejects_duplicate_type_slots_per_variant_and_ruleset() -> (
    None
):
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
        ),
        inference="none",
    )
    assert not conforms
    assert "per variant/ruleset/type-slot" in results_text


def test_shacl_rejects_undeclared_pkm_predicates() -> None:
    conforms, results_text = _validate_data_graph(
        _parse_ttl(
            """
            @prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .

            pkm:Battle1 a pkm:Battle ;
                pkm:notDeclaredPredicate pkm:Anything .
            """
        ),
        inference="none",
    )
    assert not conforms
    assert "declared as an ontology property" in results_text


def test_synthetic_represents_species_conforms() -> None:
    payload = {
        "id": "synthetic-represents-species",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"representsSpecies graph violates SHACL:\n{results_text}"


def test_synthetic_has_tera_type_conforms() -> None:
    payload = {
        "id": "synthetic-has-tera-type",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|-terastallize|p1a: Pikachu|Electric",
            ]
        ),
    }
    conforms, results_text = _validate_data_graph(build_graph(payload))
    assert conforms, f"hasTeraType graph violates SHACL:\n{results_text}"
