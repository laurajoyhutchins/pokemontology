"""Integration tests for the rdflib-based replay TTL builder."""

from __future__ import annotations

import json

import pytest
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF

from pokemontology._script_loader import repo_path
from pokemontology.replay.replay_parser import parse_log
from pokemontology.replay.replay_to_ttl_builder import build_graph

REPO = repo_path()
REPLAY_JSON = (
    REPO
    / "examples"
    / "replays"
    / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
)
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


@pytest.fixture(scope="module")
def replay_payload() -> dict:
    return json.loads(REPLAY_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replay_graph(replay_payload: dict) -> Graph:
    return build_graph(replay_payload)


def test_graph_has_replay_artifact(replay_graph: Graph) -> None:
    artifacts = list(
        replay_graph.subjects(
            predicate=__import__("rdflib").RDF.type, object=PKM.ReplayArtifact
        )
    )
    assert len(artifacts) >= 1


def test_graph_has_battle(replay_graph: Graph) -> None:
    from rdflib import RDF

    battles = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Battle))
    assert len(battles) >= 1


def test_graph_has_two_battle_sides(replay_graph: Graph) -> None:
    from rdflib import RDF

    sides = list(replay_graph.subjects(predicate=RDF.type, object=PKM.BattleSide))
    assert len(sides) >= 2


def test_instantaneous_count_matches_events(
    replay_payload: dict, replay_graph: Graph
) -> None:
    from rdflib import RDF

    events = parse_log(replay_payload["log"])
    instants = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Instantaneous))
    assert len(instants) == len(events)


def test_faint_event_count(replay_payload: dict, replay_graph: Graph) -> None:
    from rdflib import RDF

    expected_faints = sum(
        1 for line in replay_payload["log"].splitlines() if line.startswith("|faint|")
    )
    faint_events = list(
        replay_graph.subjects(predicate=RDF.type, object=PKM.FaintEvent)
    )
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
    assert any(replay_graph.subjects(RDF.type, PKM.ActiveSlotAssignment))


def test_builder_emits_damage_and_healing_events(replay_graph: Graph) -> None:
    assert any(replay_graph.subjects(RDF.type, PKM.DamageEvent))
    assert any(replay_graph.subjects(RDF.type, PKM.HealingEvent))
    assert any(replay_graph.subjects(RDF.type, PKM.StatStageChangeEvent))


def test_builder_emits_status_and_target_resolution_for_supported_minor_actions() -> (
    None
):
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
    graph = build_graph(payload)

    assert any(graph.subjects(RDF.type, PKM.StatusInflictionEvent))
    assert any(graph.subjects(RDF.type, PKM.CurrentStatusAssignment))
    assert any(graph.subjects(RDF.type, PKM.TargetResolutionState))

    thunder_wave_action = next(
        action
        for action in graph.subjects(RDF.type, PKM.MoveUseAction)
        if (action, PKM.usesMove, PKM.MoveThunder_Wave) in graph
    )
    declared_targets = list(graph.objects(thunder_wave_action, PKM.hasDeclaredTarget))
    assert declared_targets

    failed_resolutions = {
        resolution
        for resolution in graph.subjects(RDF.type, PKM.TargetResolutionState)
        if (resolution, PKM.hasResolutionOutcome, None) in graph
    }
    assert any(
        (resolution, PKM.hasResolutionOutcome, Literal("failed")) in graph
        for resolution in failed_resolutions
    )


def test_builder_emits_switch_events_and_aborted_resolution_for_board_mutations() -> (
    None
):
    payload = {
        "id": "synthetic-board-mutation",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Bulbasaur",
                "|cant|p1a: Pikachu|par",
                "|drag|p2a: Squirtle|Squirtle, L50|80/100",
                "|replace|p2a: Zoroark|Zoroark, L50|70/100",
                "|detailschange|p1a: Pikachu|Pikachu-Partner, L50|90/100",
            ]
        ),
    }
    graph = build_graph(payload)

    switch_events = list(graph.subjects(RDF.type, PKM.SwitchEvent))
    assert len(switch_events) >= 4
    assert any(graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any(
        (resolution, PKM.hasResolutionOutcome, Literal("aborted")) in graph
        for resolution in graph.subjects(RDF.type, PKM.TargetResolutionState)
    )
    assert any(
        (assignment, RDF.type, PKM.CurrentHPAssignment) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentHPAssignment)
    )


def test_builder_expands_spread_targets_and_tracks_mixed_outcomes() -> None:
    payload = {
        "id": "synthetic-spread-resolution",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Charizard|Charizard, L50|100/100",
                "|switch|p2a: Venusaur|Venusaur, L50|100/100",
                "|switch|p2b: Blastoise|Blastoise, L50|100/100",
                "|move|p1a: Charizard|Heat Wave|p2a: Venusaur|[spread] p2a,p2b",
                "|-damage|p2a: Venusaur|40/100",
                "|-miss|p1a: Charizard|p2b: Blastoise",
            ]
        ),
    }
    graph = build_graph(payload)

    heat_wave_action = next(
        action
        for action in graph.subjects(RDF.type, PKM.MoveUseAction)
        if (action, PKM.usesMove, PKM.MoveHeat_Wave) in graph
    )
    resolved_targets = set(graph.objects(heat_wave_action, PKM.hasResolvedTarget))
    assert PKM.Combatant_Bob_Venusaur in resolved_targets
    assert PKM.Combatant_Bob_Blastoise in resolved_targets

    resolutions = list(graph.subjects(RDF.type, PKM.TargetResolutionState))
    assert any(
        (resolution, PKM.aboutTarget, PKM.Combatant_Bob_Venusaur) in graph
        and (resolution, PKM.hasResolutionOutcome, Literal("resolved")) in graph
        for resolution in resolutions
    )
    assert any(
        (resolution, PKM.aboutTarget, PKM.Combatant_Bob_Blastoise) in graph
        and (resolution, PKM.hasResolutionOutcome, Literal("failed")) in graph
        for resolution in resolutions
    )


def test_damage_events_link_back_to_current_action_when_targeted() -> None:
    payload = {
        "id": "synthetic-causality",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Eevee|Eevee, L50|100/100",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Eevee",
                "|-damage|p2a: Eevee|10/100",
            ]
        ),
    }
    graph = build_graph(payload)

    damage_event = next(graph.subjects(RDF.type, PKM.DamageEvent))
    causing_action = next(graph.objects(damage_event, PKM.causedByAction))
    assert (causing_action, RDF.type, PKM.MoveUseAction) in graph


def test_builder_distinguishes_declared_and_resolved_targets_under_redirection() -> (
    None
):
    payload = {
        "id": "synthetic-redirection",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Gyarados|Gyarados, L50|100/100",
                "|switch|p2b: Rhydon|Rhydon, L50|100/100",
                "|move|p1a: Pikachu|Thunderbolt|p2a: Gyarados",
                "|-activate|p2b: Rhydon|ability: Lightning Rod",
                "|-damage|p2b: Rhydon|60/100",
            ]
        ),
    }
    graph = build_graph(payload)

    action = next(
        action
        for action in graph.subjects(RDF.type, PKM.MoveUseAction)
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


def test_builder_projects_persistent_state_and_applies_teardown_events() -> None:
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
    graph = build_graph(payload)

    upkeep_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("upkeep-t2-e0")) in graph
    )
    cure_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-curestatus-t2-e1")) in graph
    )
    weather_clear_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-weather-t2-e2")) in graph
    )
    field_end_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-fieldend-t2-e3")) in graph
    )
    side_end_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-sideend-t2-e4")) in graph
    )
    volatile_end_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-end-t2-e5")) in graph
    )

    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.ActiveSlotAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentWeatherAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentTerrainAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.SideConditionAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentStatusAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.VolatileStatusAssignment)
    )

    assert not any(
        (assignment, PKM.hasContext, cure_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentStatusAssignment)
    )
    assert not any(
        (assignment, PKM.hasContext, weather_clear_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentWeatherAssignment)
    )
    assert not any(
        (assignment, PKM.hasContext, field_end_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentTerrainAssignment)
    )
    assert not any(
        (assignment, PKM.hasContext, side_end_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.SideConditionAssignment)
    )
    assert not any(
        (assignment, PKM.hasContext, volatile_end_instant) in graph
        for assignment in graph.subjects(RDF.type, PKM.VolatileStatusAssignment)
    )


def test_builder_projects_stat_stage_state_and_handles_sethp() -> None:
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
    graph = build_graph(payload)

    boost_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-boost-t1-e3")) in graph
    )
    upkeep_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("upkeep-t2-e0")) in graph
    )
    sethp_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-sethp-t2-e2")) in graph
    )
    clear_instant = next(
        instant
        for instant in graph.subjects(RDF.type, PKM.Instantaneous)
        if (instant, PKM.hasReplayStepLabel, Literal("-clearboost-t2-e3")) in graph
    )

    assert any(
        (assignment, PKM.hasContext, boost_instant) in graph
        and (assignment, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (assignment, PKM.aboutStat, PKM.Stat_Special_Attack) in graph
        and (assignment, PKM.hasStageValue, Literal(2)) in graph
        for assignment in graph.subjects(RDF.type, PKM.StatStageAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, upkeep_instant) in graph
        and (assignment, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (assignment, PKM.aboutStat, PKM.Stat_Special_Attack) in graph
        and (assignment, PKM.hasStageValue, Literal(2)) in graph
        for assignment in graph.subjects(RDF.type, PKM.StatStageAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, clear_instant) in graph
        and (assignment, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (assignment, PKM.aboutStat, PKM.Stat_Special_Attack) in graph
        and (assignment, PKM.hasStageValue, Literal(0)) in graph
        for assignment in graph.subjects(RDF.type, PKM.StatStageAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, sethp_instant) in graph
        and (assignment, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (assignment, PKM.hasCurrentHPValue, Literal(70)) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentHPAssignment)
    )
    assert any(
        (assignment, PKM.hasContext, sethp_instant) in graph
        and (assignment, PKM.aboutCombatant, PKM.Combatant_Bob_Bulbasaur) in graph
        and (assignment, PKM.hasCurrentHPValue, Literal(70)) in graph
        for assignment in graph.subjects(RDF.type, PKM.CurrentHPAssignment)
    )


def test_builder_emits_multiple_resolution_nodes_for_multi_hit_moves() -> None:
    payload = {
        "id": "synthetic-multihit",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Urshifu|Urshifu-Rapid-Strike, L50|100/100",
                "|switch|p2a: Tyranitar|Tyranitar, L50|100/100",
                "|move|p1a: Urshifu|Surging Strikes|p2a: Tyranitar",
                "|-damage|p2a: Tyranitar|80/100",
                "|-damage|p2a: Tyranitar|60/100",
                "|-damage|p2a: Tyranitar|40/100",
            ]
        ),
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
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Bulbasaur|Bulbasaur, L50|100/100",
                "|switch|p2a: Squirtle|Squirtle, L50|100/100",
                "|move|p1a: Bulbasaur|Tackle|p2a: Squirtle",
                "|-damage|p2a: Squirtle|90/100",
                "|upkeep",
                "|-heal|p1a: Bulbasaur|100/100|[from] Grassy Terrain",
            ]
        ),
    }
    graph = build_graph(payload)

    heal_event = next(graph.subjects(RDF.type, PKM.HealingEvent))
    assert not list(graph.objects(heal_event, PKM.causedByAction))


def test_builder_uses_only_declared_pkm_predicates(
    replay_graph: Graph, ontology_graph: Graph
) -> None:
    declared = {
        predicate
        for predicate in ontology_graph.subjects(RDF.type, None)
        if str(predicate).startswith(str(PKM))
        and any(
            property_type
            in (
                RDF.Property,
                OWL.AnnotationProperty,
                OWL.ObjectProperty,
                OWL.DatatypeProperty,
            )
            for property_type in ontology_graph.objects(predicate, RDF.type)
        )
    }

    used = {
        predicate
        for _, predicate, _ in replay_graph
        if str(predicate).startswith(str(PKM))
    }
    assert used <= declared, (
        f"undeclared pkm: predicates in replay graph: {sorted(str(p) for p in used - declared)}"
    )


def test_builder_emits_item_and_ability_assignments_on_observation() -> None:
    payload = {
        "id": "item-ability-test",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|-ability|p2a: Bulbasaur|Overgrow",
                "|-item|p1a: Pikachu|Leftovers|[from] move: Trick",
            ]
        ),
    }
    graph = build_graph(payload)

    item_assignments = list(graph.subjects(RDF.type, PKM.CurrentItemAssignment))
    ability_assignments = list(graph.subjects(RDF.type, PKM.CurrentAbilityAssignment))
    assert item_assignments, "expected at least one CurrentItemAssignment"
    assert ability_assignments, "expected at least one CurrentAbilityAssignment"

    item_iri = next(graph.objects(item_assignments[0], PKM.hasCurrentItem))
    assert str(item_iri).endswith("Leftovers")

    ability_iri = next(graph.objects(ability_assignments[0], PKM.hasCurrentAbility))
    assert str(ability_iri).endswith("Overgrow")


def test_builder_clears_item_and_ability_on_end_events() -> None:
    payload = {
        "id": "item-ability-end-test",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|-ability|p2a: Bulbasaur|Overgrow",
                "|-item|p1a: Pikachu|Leftovers|[from] move: Trick",
                "|-endability|p2a: Bulbasaur|Overgrow",
                "|-enditem|p1a: Pikachu|Leftovers",
            ]
        ),
    }
    graph = build_graph(payload)

    # After enditem/endability, final instants should carry no assignments
    item_assignments = list(graph.subjects(RDF.type, PKM.CurrentItemAssignment))
    ability_assignments = list(graph.subjects(RDF.type, PKM.CurrentAbilityAssignment))
    # Assignments may exist on earlier instants but the last instant should have none
    last_instant = PKM[
        f"I_{len(list(graph.subjects(RDF.type, PKM.Instantaneous))) - 1}"
    ]
    assert not any(
        graph.value(a, PKM.hasContext) == last_instant for a in item_assignments
    ), "CurrentItemAssignment should not persist after -enditem"
    assert not any(
        graph.value(a, PKM.hasContext) == last_instant for a in ability_assignments
    ), "CurrentAbilityAssignment should not persist after -endability"


def test_builder_tracks_volatile_start_and_clears_on_end() -> None:
    payload = {
        "id": "volatile-start-test",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|move|p1a: Pikachu|Confuse Ray|p2a: Bulbasaur",
                "|-start|p2a: Bulbasaur|confusion",
                "|turn|2",
                "|upkeep",
                "|-end|p2a: Bulbasaur|confusion",
            ]
        ),
    }
    graph = build_graph(payload)

    # After -start, VolatileStatusAssignment should be present before the -end
    start_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-start-t1-e3")) in graph
    )
    end_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-end-t2-e1")) in graph
    )

    volatile_assignments = list(graph.subjects(RDF.type, PKM.VolatileStatusAssignment))
    assert any(
        (a, PKM.hasContext, start_instant) in graph for a in volatile_assignments
    ), "VolatileStatusAssignment should be present after -start"
    assert not any(
        (a, PKM.hasContext, end_instant) in graph for a in volatile_assignments
    ), "VolatileStatusAssignment should be removed after -end"


def test_builder_handles_setboost_and_invertboost() -> None:
    payload = {
        "id": "setboost-invertboost-test",
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
            ]
        ),
    }
    graph = build_graph(payload)

    setboost_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-setboost-t1-e3")) in graph
    )
    invert_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-invertboost-t1-e5")) in graph
    )

    # After setboost, Attack should be +6
    assert any(
        (a, PKM.hasContext, setboost_instant) in graph
        and (a, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (a, PKM.aboutStat, PKM.Stat_Attack) in graph
        and (a, PKM.hasStageValue, Literal(6)) in graph
        for a in graph.subjects(RDF.type, PKM.StatStageAssignment)
    ), "Expected +6 Attack after setboost"

    # After invertboost, Attack should be -6
    assert any(
        (a, PKM.hasContext, invert_instant) in graph
        and (a, PKM.aboutCombatant, PKM.Combatant_Alice_Pikachu) in graph
        and (a, PKM.aboutStat, PKM.Stat_Attack) in graph
        and (a, PKM.hasStageValue, Literal(-6)) in graph
        for a in graph.subjects(RDF.type, PKM.StatStageAssignment)
    ), "Expected -6 Attack after invertboost"


def test_builder_records_battle_outcome_on_win() -> None:
    payload = {
        "id": "win-test",
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
    graph = build_graph(payload)

    battle = next(graph.subjects(RDF.type, PKM.Battle))
    outcome = graph.value(battle, PKM.hasBattleOutcome)
    assert outcome is not None, "Battle should have hasBattleOutcome after |win|"
    assert str(outcome) == "Alice"


def test_builder_records_battle_outcome_on_tie() -> None:
    payload = {
        "id": "tie-test",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Bulbasaur|Bulbasaur, L50|100/100",
                "|tie|",
            ]
        ),
    }
    graph = build_graph(payload)

    battle = next(graph.subjects(RDF.type, PKM.Battle))
    outcome = graph.value(battle, PKM.hasBattleOutcome)
    assert outcome is not None, "Battle should have hasBattleOutcome after |tie|"
    assert str(outcome) == "tie"


def test_builder_emits_represents_species() -> None:
    payload = {
        "id": "synthetic-species-link",
        "format": "[Gen 9] Custom Game",
        "players": ["Alice", "Bob"],
        "log": "\n".join(
            [
                "|turn|1",
                "|switch|p1a: Pikachu|Pikachu, L50|100/100",
                "|switch|p2a: Mr. Mime|Mr. Mime, L50|100/100",
            ]
        ),
    }
    graph = build_graph(payload)

    pikachu = PKM["Combatant_Alice_Pikachu"]
    mr_mime = PKM["Combatant_Bob_MrMime"]

    pikachu_species = list(graph.objects(pikachu, PKM.representsSpecies))
    assert len(pikachu_species) == 1
    assert str(pikachu_species[0]) == str(PKM["Species_pikachu"])

    mr_mime_species = list(graph.objects(mr_mime, PKM.representsSpecies))
    assert len(mr_mime_species) == 1
    assert str(mr_mime_species[0]) == str(PKM["Species_mr_mime"])


def test_builder_emits_has_tera_type() -> None:
    payload = {
        "id": "synthetic-tera",
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
    graph = build_graph(payload)

    transformation_iri = PKM["Transformation_Terastallized_Electric"]
    tera_types = list(graph.objects(transformation_iri, PKM.hasTeraType))
    assert len(tera_types) == 1
    assert str(tera_types[0]) == str(PKM["Type_electric"])


def test_builder_handles_cureteam() -> None:
    # Blissey (p1) uses Aromatherapy, curing its own side's status conditions.
    payload = {
        "id": "cureteam-test",
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
    graph = build_graph(payload)

    # Status should be present after -status event
    status_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-status-t1-e2")) in graph
    )
    cure_instant = next(
        i
        for i in graph.subjects(RDF.type, PKM.Instantaneous)
        if (i, PKM.hasReplayStepLabel, Literal("-cureteam-t1-e4")) in graph
    )

    status_assignments = list(graph.subjects(RDF.type, PKM.CurrentStatusAssignment))
    assert any(
        (a, PKM.hasContext, status_instant) in graph for a in status_assignments
    ), "Status should be present after -status"
    assert not any(
        (a, PKM.hasContext, cure_instant) in graph for a in status_assignments
    ), "Status should be cleared after -cureteam on the user's side"
