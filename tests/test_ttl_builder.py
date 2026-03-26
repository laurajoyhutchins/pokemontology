"""Integration tests for the rdflib-based replay TTL builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF

from scripts.replay.replay_parser import parse_log
from scripts.replay.replay_to_ttl_builder import build_graph

REPO = Path(__file__).parent.parent
REPLAY_JSON = REPO / "examples" / "replays" / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
ONTOLOGY = REPO / "build" / "ontology.ttl"
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


@pytest.fixture(scope="module")
def replay_payload() -> dict:
    return json.loads(REPLAY_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replay_graph(replay_payload: dict) -> Graph:
    return build_graph(replay_payload)


@pytest.fixture(scope="module")
def ontology_graph() -> Graph:
    graph = Graph()
    graph.parse(ONTOLOGY, format="turtle")
    return graph


def test_graph_has_replay_artifact(replay_graph: Graph) -> None:
    artifacts = list(replay_graph.subjects(predicate=__import__("rdflib").RDF.type, object=PKM.ReplayArtifact))
    assert len(artifacts) >= 1


def test_graph_has_battle(replay_graph: Graph) -> None:
    from rdflib import RDF
    battles = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Battle))
    assert len(battles) >= 1


def test_graph_has_two_battle_sides(replay_graph: Graph) -> None:
    from rdflib import RDF
    sides = list(replay_graph.subjects(predicate=RDF.type, object=PKM.BattleSide))
    assert len(sides) >= 2


def test_instantaneous_count_matches_events(replay_payload: dict, replay_graph: Graph) -> None:
    from rdflib import RDF
    events = parse_log(replay_payload["log"])
    instants = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Instantaneous))
    assert len(instants) == len(events)


def test_faint_event_count(replay_payload: dict, replay_graph: Graph) -> None:
    from rdflib import RDF
    expected_faints = sum(
        1 for line in replay_payload["log"].splitlines()
        if line.startswith("|faint|")
    )
    faint_events = list(replay_graph.subjects(predicate=RDF.type, object=PKM.FaintEvent))
    assert len(faint_events) == expected_faints


def test_graph_serializes_valid_turtle(replay_graph: Graph) -> None:
    ttl = replay_graph.serialize(format="turtle")
    g2 = Graph()
    g2.parse(data=ttl, format="turtle")
    assert len(g2) == len(replay_graph)


def test_state_transitions_use_declared_battle_predicates(replay_graph: Graph) -> None:
    for transition in replay_graph.subjects(RDF.type, PKM.StateTransition):
        assert (transition, PKM.fromInstantaneous, None) in replay_graph
        assert (transition, PKM.toInstantaneous, None) in replay_graph
        assert (transition, PKM.triggeredByAction, None) in replay_graph
        assert (transition, PKM.transitionOccursInBattle, None) in replay_graph
        assert (transition, PKM.hasInputState, None) not in replay_graph
        assert (transition, PKM.hasOutputState, None) not in replay_graph
        assert (transition, PKM.triggeredBy, None) not in replay_graph


def test_faint_events_use_declared_event_predicates(replay_graph: Graph) -> None:
    for event in replay_graph.subjects(RDF.type, PKM.FaintEvent):
        assert (event, PKM.affectsCombatant, None) in replay_graph
        assert (event, PKM.occursInInstantaneous, None) in replay_graph
        assert (event, PKM.aboutCombatant, None) not in replay_graph
        assert (event, PKM.occursAtInstantaneous, None) not in replay_graph


def test_builder_materializes_replay_observed_assignments(replay_graph: Graph) -> None:
    assert any(replay_graph.subjects(RDF.type, PKM.CurrentHPAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.StatStageAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.CurrentWeatherAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.CurrentTerrainAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.SideConditionAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.CurrentTransformationAssignment))
    assert any(replay_graph.subjects(RDF.type, PKM.VolatileStatusAssignment))


def test_builder_emits_damage_and_healing_events(replay_graph: Graph) -> None:
    assert any(replay_graph.subjects(RDF.type, PKM.DamageEvent))
    assert any(replay_graph.subjects(RDF.type, PKM.HealingEvent))


def test_builder_emits_status_and_target_resolution_for_supported_minor_actions() -> None:
    payload = {
        "id": "synthetic-status-targeting",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Pikachu|Pikachu, L50|100/100",
            "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
            "|move|p1a: Pikachu|Thunder Wave|p2a: Bulbasaur",
            "|-status|p2a: Bulbasaur|par",
            "|move|p2a: Bulbasaur|Sleep Powder|p1a: Pikachu",
            "|-miss|p2a: Bulbasaur|p1a: Pikachu",
            "|move|p2a: Bulbasaur|Protect|p2a: Bulbasaur",
            "|-fail|p2a: Bulbasaur",
        ]),
    }
    graph = build_graph(payload)

    assert any(graph.subjects(RDF.type, PKM.StatusInflictionEvent))
    assert any(graph.subjects(RDF.type, PKM.CurrentStatusAssignment))
    assert any(graph.subjects(RDF.type, PKM.TargetResolutionState))

    thunder_wave_action = next(
        action for action in graph.subjects(RDF.type, PKM.MoveUseAction)
        if (action, PKM.usesMove, PKM.MoveThunder_Wave) in graph
    )
    declared_targets = list(graph.objects(thunder_wave_action, PKM.hasDeclaredTarget))
    assert declared_targets

    failed_resolutions = {
        resolution
        for resolution in graph.subjects(RDF.type, PKM.TargetResolutionState)
        if (resolution, PKM.hasResolutionOutcome, None) in graph
    }
    assert any((resolution, PKM.hasResolutionOutcome, Literal("failed")) in graph for resolution in failed_resolutions)


def test_builder_emits_switch_events_and_aborted_resolution_for_board_mutations() -> None:
    payload = {
        "id": "synthetic-board-mutation",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Pikachu|Pikachu, L50|100/100",
            "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
            "|move|p1a: Pikachu|Thunderbolt|p2a: Bulbasaur",
            "|cant|p1a: Pikachu|par",
            "|drag|p2a: Squirtle|Squirtle, L50|80/100",
            "|replace|p2a: Zoroark|Zoroark, L50|70/100",
            "|detailschange|p1a: Pikachu|Pikachu-Partner, L50|90/100",
        ]),
    }
    graph = build_graph(payload)

    switch_events = list(graph.subjects(RDF.type, PKM.SwitchEvent))
    assert len(switch_events) >= 4
    assert any(graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any((resolution, PKM.hasResolutionOutcome, Literal("aborted")) in graph for resolution in graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any((assignment, RDF.type, PKM.CurrentHPAssignment) in graph for assignment in graph.subjects(RDF.type, PKM.CurrentHPAssignment))


def test_builder_expands_spread_targets_and_tracks_mixed_outcomes() -> None:
    payload = {
        "id": "synthetic-spread-resolution",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Charizard|Charizard, L50|100/100",
            "|switch|p2a: Venusaur|Venusaur, L50|100/100",
            "|switch|p2b: Blastoise|Blastoise, L50|100/100",
            "|move|p1a: Charizard|Heat Wave|p2a: Venusaur|[spread] p2a,p2b",
            "|-damage|p2a: Venusaur|40/100",
            "|-miss|p1a: Charizard|p2b: Blastoise",
        ]),
    }
    graph = build_graph(payload)

    heat_wave_action = next(
        action for action in graph.subjects(RDF.type, PKM.MoveUseAction)
        if (action, PKM.usesMove, PKM.MoveHeat_Wave) in graph
    )
    resolved_targets = set(graph.objects(heat_wave_action, PKM.hasResolvedTarget))
    assert PKM.Combatant_Bob_Venusaur in resolved_targets
    assert PKM.Combatant_Bob_Blastoise in resolved_targets

    resolutions = list(graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any((resolution, PKM.aboutTarget, PKM.Combatant_Bob_Venusaur) in graph and (resolution, PKM.hasResolutionOutcome, Literal("resolved")) in graph for resolution in resolutions)
    assert any((resolution, PKM.aboutTarget, PKM.Combatant_Bob_Blastoise) in graph and (resolution, PKM.hasResolutionOutcome, Literal("failed")) in graph for resolution in resolutions)


def test_damage_events_link_back_to_current_action_when_targeted() -> None:
    payload = {
        "id": "synthetic-causality",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Pikachu|Pikachu, L50|100/100",
            "|switch|p2a: Eevee|Eevee, L50|100/100",
            "|move|p1a: Pikachu|Thunderbolt|p2a: Eevee",
            "|-damage|p2a: Eevee|10/100",
        ]),
    }
    graph = build_graph(payload)

    damage_event = next(graph.subjects(RDF.type, PKM.DamageEvent))
    causing_action = next(graph.objects(damage_event, PKM.causedByAction))
    assert (causing_action, RDF.type, PKM.MoveUseAction) in graph


def test_builder_distinguishes_declared_and_resolved_targets_under_redirection() -> None:
    payload = {
        "id": "synthetic-redirection",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Pikachu|Pikachu, L50|100/100",
            "|switch|p2a: Gyarados|Gyarados, L50|100/100",
            "|switch|p2b: Rhydon|Rhydon, L50|100/100",
            "|move|p1a: Pikachu|Thunderbolt|p2a: Gyarados",
            "|-activate|p2b: Rhydon|ability: Lightning Rod",
            "|-damage|p2b: Rhydon|60/100",
        ]),
    }
    graph = build_graph(payload)

    action = next(
        action for action in graph.subjects(RDF.type, PKM.MoveUseAction)
        if (action, PKM.usesMove, PKM.MoveThunderbolt) in graph
    )
    declared_targets = set(graph.objects(action, PKM.hasDeclaredTarget))
    resolved_targets = set(graph.objects(action, PKM.hasResolvedTarget))

    assert declared_targets == {PKM.Combatant_Bob_Gyarados}
    assert resolved_targets == {PKM.Combatant_Bob_Rhydon}

    resolutions = list(graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any(
        (resolution, PKM.aboutTarget, PKM.Combatant_Bob_Rhydon) in graph
        and (resolution, PKM.hasResolutionOutcome, Literal("resolved")) in graph
        for resolution in resolutions
    )
    assert not any(
        (resolution, PKM.aboutTarget, PKM.Combatant_Bob_Gyarados) in graph
        and (resolution, PKM.hasResolutionOutcome, Literal("resolved")) in graph
        for resolution in resolutions
    )


def test_builder_emits_multiple_resolution_nodes_for_multi_hit_moves() -> None:
    payload = {
        "id": "synthetic-multihit",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Urshifu|Urshifu-Rapid-Strike, L50|100/100",
            "|switch|p2a: Tyranitar|Tyranitar, L50|100/100",
            "|move|p1a: Urshifu|Surging Strikes|p2a: Tyranitar",
            "|-damage|p2a: Tyranitar|80/100",
            "|-damage|p2a: Tyranitar|60/100",
            "|-damage|p2a: Tyranitar|40/100",
        ]),
    }
    graph = build_graph(payload)

    resolutions = [
        resolution
        for resolution in graph.subjects(RDF.type, PKM.TargetResolutionState)
        if (resolution, PKM.aboutTarget, PKM.Combatant_Bob_Tyranitar) in graph
        and (resolution, PKM.hasResolutionOutcome, Literal("resolved")) in graph
    ]
    assert len(resolutions) == 3


def test_upkeep_breaks_action_causality_for_residual_healing() -> None:
    payload = {
        "id": "synthetic-upkeep-residual",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join([
            "|turn|1",
            "|switch|p1a: Bulbasaur|Bulbasaur, L50|100/100",
            "|switch|p2a: Squirtle|Squirtle, L50|100/100",
            "|move|p1a: Bulbasaur|Tackle|p2a: Squirtle",
            "|-damage|p2a: Squirtle|90/100",
            "|upkeep",
            "|-heal|p1a: Bulbasaur|100/100|[from] Grassy Terrain",
        ]),
    }
    graph = build_graph(payload)

    heal_event = next(graph.subjects(RDF.type, PKM.HealingEvent))
    assert not list(graph.objects(heal_event, PKM.causedByAction))


def test_builder_uses_only_declared_pkm_predicates(replay_graph: Graph, ontology_graph: Graph) -> None:
    declared = {
        predicate
        for predicate in ontology_graph.subjects(RDF.type, None)
        if str(predicate).startswith(str(PKM))
        and any(
            property_type in (
                RDF.Property,
                OWL.AnnotationProperty,
                OWL.ObjectProperty,
                OWL.DatatypeProperty,
            )
            for property_type in ontology_graph.objects(predicate, RDF.type)
        )
    }

    used = {predicate for _, predicate, _ in replay_graph if str(predicate).startswith(str(PKM))}
    assert used <= declared, f"undeclared pkm: predicates in replay graph: {sorted(str(p) for p in used - declared)}"
