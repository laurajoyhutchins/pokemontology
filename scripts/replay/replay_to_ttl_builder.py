#!/usr/bin/env python3
"""Build a replay-backed TTL slice from a Pokémon Showdown replay JSON.

Scope:
- replay artifact
- battle + two sides
- battle participants observed in the log
- minimal move vocabulary observed in the log
- Instantaneous checkpoints around observed switch/move/faint events
- MoveUseAction and FaintEvent individuals
- simple StateTransition chain between checkpoints

This is intentionally a *builder for a minimal replay-backed slice*, not a full
battle-state reconstructor. It does not infer hidden information, exact HP
trajectories, RNG branch spaces, or dense materialized assignments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from dataclasses import dataclass, field

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from scripts.replay.replay_parser import (
    PKM_PREFIX,
    actor_display_name,
    compact_species_name,
    discover_moves,
    discover_participants,
    parse_log,
    parse_player_slot,
    parse_replay_payload,
    parse_side_token,
    sanitize_identifier,
)

PKM = Namespace(PKM_PREFIX)
SITE_BASE = "https://laurajoyhutchins.github.io/pokemontology"

STAT_TOKEN_TO_NAME = {
    "atk": "Attack",
    "def": "Defense",
    "spa": "Special Attack",
    "spd": "Special Defense",
    "spe": "Speed",
    "accuracy": "Accuracy",
    "evasion": "Evasion",
}
SIDE_CONDITION_TOKEN_TO_NAME = {
    "move: Tailwind": "Tailwind",
}
TERRAIN_TOKEN_TO_NAME = {
    "move: Psychic Terrain": "Psychic Terrain",
    "move: Grassy Terrain": "Grassy Terrain",
}
WEATHER_TOKEN_TO_NAME = {
    "SunnyDay": "Harsh Sunlight",
}
VOLATILE_TOKEN_TO_NAME = {
    "Protect": "Protecting",
    "move: Protect": "Protecting",
}
STATUS_TOKEN_TO_NAME = {
    "brn": "Burn",
    "par": "Paralysis",
    "psn": "Poison",
    "tox": "Badly Poisoned",
    "slp": "Sleep",
    "frz": "Freeze",
}


@dataclass
class ActionExecutionContext:
    action_iri: URIRef
    actor_iri: URIRef
    actor_slot: str
    declared_targets: list[URIRef] = field(default_factory=list)
    candidate_targets: list[URIRef] = field(default_factory=list)
    resolved_targets: set[URIRef] = field(default_factory=set)
    failed_targets: set[URIRef] = field(default_factory=set)
    aborted_targets: set[URIRef] = field(default_factory=set)
    redirected_from_targets: set[URIRef] = field(default_factory=set)
    hit_counts_by_target: dict[URIRef, int] = field(default_factory=dict)


@dataclass
class StateSnapshot:
    current_hp: dict[URIRef, int] = field(default_factory=dict)
    current_status: dict[URIRef, URIRef] = field(default_factory=dict)
    current_weather: URIRef | None = None
    current_terrain: URIRef | None = None
    current_side_conditions: set[tuple[URIRef, URIRef]] = field(default_factory=set)
    current_volatile_conditions: set[tuple[URIRef, URIRef]] = field(default_factory=set)
    current_transformations: dict[URIRef, URIRef] = field(default_factory=dict)


def combatant_iri_for_token(token: str, p1_name: str, p2_name: str) -> URIRef:
    player_id, _slot = parse_player_slot(token)
    trainer = p1_name if player_id == "p1" else p2_name
    actor_name = actor_display_name(token)
    return PKM[f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(actor_name)}"]


def slot_key(token: str) -> str:
    player_id, slot = parse_player_slot(token)
    return f"{player_id}{slot}"


def combatant_iri_for_switch(token: str, species_token: str, p1_name: str, p2_name: str) -> URIRef:
    player_id, _slot = parse_player_slot(token)
    trainer = p1_name if player_id == "p1" else p2_name
    return PKM[f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(species_token)}"]


def side_iri_for_token(token: str, p1_name: str, p2_name: str) -> URIRef:
    side_id = parse_side_token(token)
    trainer = p1_name if side_id == "p1" else p2_name
    return PKM[f"Side_{sanitize_identifier(trainer)}"]


def side_iri_for_player_id(player_id: str, p1_name: str, p2_name: str) -> URIRef:
    trainer = p1_name if player_id == "p1" else p2_name
    return PKM[f"Side_{sanitize_identifier(trainer)}"]


def stat_iri_for_token(token: str) -> URIRef:
    stat_name = STAT_TOKEN_TO_NAME.get(token, token)
    return PKM[f"Stat_{sanitize_identifier(stat_name)}"]


def ensure_named_entity(g: Graph, iri: URIRef, rdf_type: URIRef, name: str) -> None:
    g.add((iri, RDF.type, rdf_type))
    g.add((iri, PKM.hasName, Literal(name)))


def maybe_combatant_from_token(
    token: str,
    active_combatants_by_slot: dict[str, URIRef],
    p1_name: str,
    p2_name: str,
) -> URIRef | None:
    token = token.strip()
    if token in active_combatants_by_slot:
        return active_combatants_by_slot[token]
    try:
        key = slot_key(token)
    except ValueError:
        return None
    return active_combatants_by_slot.get(key, combatant_iri_for_token(token, p1_name, p2_name))


def maybe_status_iri(g: Graph, token: str) -> URIRef | None:
    status_name = STATUS_TOKEN_TO_NAME.get(token.strip())
    if status_name is None:
        return None
    status_iri = PKM[f"StatusCondition_{sanitize_identifier(status_name)}"]
    ensure_named_entity(g, status_iri, PKM.StatusCondition, status_name)
    return status_iri


def maybe_volatile_iri(g: Graph, token: str) -> URIRef | None:
    volatile_name = VOLATILE_TOKEN_TO_NAME.get(token.strip())
    if volatile_name is None:
        return None
    volatile_iri = PKM[f"VolatileCondition_{sanitize_identifier(volatile_name)}"]
    ensure_named_entity(g, volatile_iri, PKM.VolatileCondition, volatile_name)
    return volatile_iri


def slot_index_for_key(key: str) -> int:
    return 1 if key.endswith("a") else 2


def add_materialization_provenance(
    g: Graph,
    assignment_iri: URIRef,
    source_event: URIRef | None,
    previous_instant: URIRef | None,
) -> None:
    if source_event is not None:
        g.add((assignment_iri, PKM.materializedFromEvent, source_event))
    elif previous_instant is not None:
        g.add((assignment_iri, PKM.materializedFromPreviousInstantaneous, previous_instant))


def emit_projected_state(
    g: Graph,
    instant: URIRef,
    previous_instant: URIRef | None,
    state: StateSnapshot,
    active_combatants_by_slot: dict[str, URIRef],
    side_by_slot: dict[str, URIRef],
    artifact_iri: URIRef,
    turn: int,
    order: int,
    event_sources: dict[str, dict[object, URIRef]],
) -> None:
    instant_name = str(instant).rsplit("#", 1)[-1]

    for combatant_iri, hp_value in state.current_hp.items():
        label = str(combatant_iri).rsplit("#", 1)[-1]
        assignment_iri = PKM[f"HP_{instant_name}_{label}"]
        g.add((assignment_iri, RDF.type, PKM.CurrentHPAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasCurrentHPValue, Literal(hp_value, datatype=XSD.integer)))
        add_materialization_provenance(g, assignment_iri, event_sources["hp"].get(combatant_iri), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"hp-state-t{turn}-e{order}")))

    for combatant_iri, status_iri in state.current_status.items():
        label = str(combatant_iri).rsplit("#", 1)[-1]
        assignment_iri = PKM[f"StatusAssignment_{instant_name}_{label}"]
        g.add((assignment_iri, RDF.type, PKM.CurrentStatusAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasStatusCondition, status_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(g, assignment_iri, event_sources["status"].get(combatant_iri), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"status-state-t{turn}-e{order}")))

    if state.current_weather is not None:
        weather_name = str(state.current_weather).rsplit("#", 1)[-1]
        assignment_iri = PKM[f"Weather_{instant_name}_{weather_name}"]
        g.add((assignment_iri, RDF.type, PKM.CurrentWeatherAssignment))
        g.add((assignment_iri, PKM.aboutField, next(g.subjects(RDF.type, PKM.Battle))))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasWeatherCondition, state.current_weather))
        add_materialization_provenance(g, assignment_iri, event_sources["weather"].get("battle"), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"weather-state-t{turn}-e{order}")))

    if state.current_terrain is not None:
        terrain_name = str(state.current_terrain).rsplit("#", 1)[-1]
        assignment_iri = PKM[f"Terrain_{instant_name}_{terrain_name}"]
        g.add((assignment_iri, RDF.type, PKM.CurrentTerrainAssignment))
        g.add((assignment_iri, PKM.aboutField, next(g.subjects(RDF.type, PKM.Battle))))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasTerrainCondition, state.current_terrain))
        add_materialization_provenance(g, assignment_iri, event_sources["terrain"].get("battle"), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"terrain-state-t{turn}-e{order}")))

    for side_iri, condition_iri in sorted(state.current_side_conditions, key=lambda item: (str(item[0]), str(item[1]))):
        assignment_iri = PKM[
            f"SideCondition_{instant_name}_{str(side_iri).rsplit('#', 1)[-1]}_{str(condition_iri).rsplit('#', 1)[-1]}"
        ]
        g.add((assignment_iri, RDF.type, PKM.SideConditionAssignment))
        g.add((assignment_iri, PKM.aboutSide, side_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasSideCondition, condition_iri))
        add_materialization_provenance(g, assignment_iri, event_sources["side"].get((side_iri, condition_iri)), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"side-state-t{turn}-e{order}")))

    for combatant_iri, condition_iri in sorted(state.current_volatile_conditions, key=lambda item: (str(item[0]), str(item[1]))):
        assignment_iri = PKM[
            f"Volatile_{instant_name}_{str(combatant_iri).rsplit('#', 1)[-1]}_{str(condition_iri).rsplit('#', 1)[-1]}"
        ]
        g.add((assignment_iri, RDF.type, PKM.VolatileStatusAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasVolatileCondition, condition_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(g, assignment_iri, event_sources["volatile"].get((combatant_iri, condition_iri)), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"volatile-state-t{turn}-e{order}")))

    for combatant_iri, transformation_iri in state.current_transformations.items():
        assignment_iri = PKM[
            f"Transformation_{instant_name}_{str(combatant_iri).rsplit('#', 1)[-1]}"
        ]
        g.add((assignment_iri, RDF.type, PKM.CurrentTransformationAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasTransformationState, transformation_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(g, assignment_iri, event_sources["transformation"].get(combatant_iri), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"transformation-state-t{turn}-e{order}")))

    for slot_name, combatant_iri in sorted(active_combatants_by_slot.items()):
        assignment_iri = PKM[f"ActiveSlot_{instant_name}_{slot_name}"]
        g.add((assignment_iri, RDF.type, PKM.ActiveSlotAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.aboutSide, side_by_slot[slot_name]))
        g.add((assignment_iri, PKM.hasActiveSlotIndex, Literal(slot_index_for_key(slot_name), datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(g, assignment_iri, event_sources["active_slot"].get(slot_name), previous_instant)
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
        g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"active-slot-state-t{turn}-e{order}")))


def annotation_value(fields: list[str], marker: str) -> str | None:
    prefix = f"[{marker}] "
    exact = f"[{marker}]"
    for field in fields:
        if field == exact:
            return ""
        if field.startswith(prefix):
            return field[len(prefix):]
    return None


def target_iris_for_tokens(
    token_blob: str,
    active_combatants_by_slot: dict[str, URIRef],
    p1_name: str,
    p2_name: str,
) -> list[URIRef]:
    targets: list[URIRef] = []
    for token in token_blob.split(","):
        candidate = maybe_combatant_from_token(token.strip(), active_combatants_by_slot, p1_name, p2_name)
        if candidate is not None and candidate not in targets:
            targets.append(candidate)
    return targets


def resolution_iri_for(action_iri: URIRef, target_iri: URIRef, outcome: str, occurrence: int) -> URIRef:
    action_name = str(action_iri).rsplit("#", 1)[-1]
    target_name = str(target_iri).rsplit("#", 1)[-1]
    return PKM[f"Resolution_{action_name}_{target_name}_{sanitize_identifier(outcome)}_N{occurrence}"]


def emit_target_resolution(
    g: Graph,
    action_iri: URIRef,
    target_iri: URIRef,
    instant: URIRef,
    outcome: str,
    artifact_iri: URIRef,
    turn: int,
    order: int,
    occurrence: int = 1,
) -> URIRef:
    resolution_iri = resolution_iri_for(action_iri, target_iri, outcome, occurrence)
    g.set((resolution_iri, RDF.type, PKM.TargetResolutionState))
    g.set((resolution_iri, PKM.aboutAction, action_iri))
    g.set((resolution_iri, PKM.aboutTarget, target_iri))
    g.set((resolution_iri, PKM.hasContext, instant))
    g.set((resolution_iri, PKM.hasResolutionOutcome, Literal(outcome)))
    g.set((resolution_iri, PKM.supportedByArtifact, artifact_iri))
    g.set((resolution_iri, PKM.hasReplayTurnIndex, Literal(turn, datatype=XSD.integer)))
    g.set((resolution_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer)))
    g.set((resolution_iri, PKM.hasReplayStepLabel, Literal(f"resolution-{outcome}-t{turn}-e{order}")))
    g.add((action_iri, PKM.hasResolvedTarget, target_iri))
    return resolution_iri


def mark_redirection(context: ActionExecutionContext, target_iri: URIRef) -> None:
    if target_iri in context.candidate_targets or not context.candidate_targets:
        return
    for declared_target in context.candidate_targets:
        context.redirected_from_targets.add(declared_target)


def finalize_action_context(
    g: Graph,
    context: ActionExecutionContext | None,
    instant: URIRef | None,
    artifact_iri: URIRef,
    turn: int,
    order: int,
) -> None:
    if context is None or instant is None:
        return
    for target_iri in context.candidate_targets:
        if (
            target_iri in context.resolved_targets
            or target_iri in context.failed_targets
            or target_iri in context.aborted_targets
            or target_iri in context.redirected_from_targets
        ):
            continue
        emit_target_resolution(g, context.action_iri, target_iri, instant, "resolved", artifact_iri, turn, order)
        context.resolved_targets.add(target_iri)


def should_attribute_minor_event_to_action(current_action: ActionExecutionContext | None, fields: list[str]) -> bool:
    if current_action is None:
        return False
    source_annotation = annotation_value(fields, "from")
    if source_annotation is None:
        return True
    return source_annotation.startswith("item: Life Orb") or source_annotation == "Recoil"


def parse_hp_value(hp_status: str) -> int | None:
    hp_token = hp_status.strip().split()[0]
    if hp_token == "0":
        return 0
    if "/" not in hp_token:
        return None
    numerator, _sep, _denominator = hp_token.partition("/")
    if not numerator.isdigit():
        return None
    return int(numerator)


def discover_pre_turn_switches(log: str) -> list[tuple[str, str, str | None]]:
    switches: list[tuple[str, str, str | None]] = []
    for raw_line in log.splitlines():
        if raw_line == "|turn|1":
            break
        if not raw_line.startswith("|switch|"):
            continue
        parts = raw_line.split("|")
        if len(parts) >= 4:
            hp_status = parts[4] if len(parts) >= 5 else None
            switches.append((parts[2], parts[3], hp_status))
    return switches


def build_graph(payload: dict) -> Graph:
    g = Graph()
    g.bind("pkm", PKM)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)

    replay_id, fmt, source_url, p1_name, p2_name = parse_replay_payload(payload)
    events = parse_log(payload["log"])
    participants = discover_participants(events, p1_name, p2_name)
    for slot_token, species_token, _hp_status in discover_pre_turn_switches(payload["log"]):
        player_id, _slot = parse_player_slot(slot_token)
        trainer = p1_name if player_id == "p1" else p2_name
        iri = f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(species_token)}"
        participants.setdefault(
            iri,
            {
                "player_id": player_id,
                "trainer": trainer,
                "species_raw": species_token.split(",")[0].strip(),
                "label": f"{trainer} {species_token.split(',')[0].strip()}",
            },
        )
    moves = discover_moves(events)

    battle_slug = sanitize_identifier(replay_id)
    artifact_iri = PKM[f"ReplayArtifact_{battle_slug}"]
    battle_iri = PKM[f"Battle_{battle_slug}"]
    side_p1_iri = PKM[f"Side_{sanitize_identifier(p1_name)}"]
    side_p2_iri = PKM[f"Side_{sanitize_identifier(p2_name)}"]
    ruleset_iri = PKM[f"Ruleset_{sanitize_identifier(fmt)}"]

    slice_uri = URIRef(f"{SITE_BASE}/data/replay-slice/{battle_slug}")
    g.add((slice_uri, RDFS.label, Literal(f"Replay-backed slice for {replay_id}")))
    g.add((
        slice_uri,
        RDFS.comment,
        Literal(
            "Auto-generated minimal replay-backed TTL slice from a Pokémon Showdown "
            "replay JSON. This file captures observable actions and faints, not a "
            "dense reconstructed battle state."
        ),
    ))

    g.add((artifact_iri, RDF.type, PKM.ReplayArtifact))
    g.add((artifact_iri, PKM.hasReplayIdentifier, Literal(replay_id)))
    g.add((artifact_iri, PKM.hasSourceURL, Literal(source_url, datatype=XSD.anyURI)))
    g.add((artifact_iri, PKM.hasName, Literal(f"{fmt}: {p1_name} vs. {p2_name}")))
    g.add((artifact_iri, RDFS.comment, Literal("Source replay artifact.")))

    g.add((ruleset_iri, RDF.type, PKM.Ruleset))
    g.add((ruleset_iri, PKM.hasName, Literal(fmt)))

    g.add((battle_iri, RDF.type, PKM.Battle))
    g.add((battle_iri, PKM.operatesUnderRuleset, ruleset_iri))
    g.add((battle_iri, PKM.supportedByArtifact, artifact_iri))
    g.add((battle_iri, PKM.hasReplayTurnIndex, Literal(1, datatype=XSD.integer)))
    g.add((battle_iri, PKM.hasReplayStepLabel, Literal("battle-root")))
    g.add((battle_iri, RDFS.comment, Literal("Battle container auto-generated from replay log.")))

    g.add((side_p1_iri, RDF.type, PKM.BattleSide))
    g.add((side_p1_iri, PKM.hasSideIndex, Literal(0, datatype=XSD.integer)))
    g.add((side_p1_iri, PKM.sideOccursInBattle, battle_iri))

    g.add((side_p2_iri, RDF.type, PKM.BattleSide))
    g.add((side_p2_iri, PKM.hasSideIndex, Literal(1, datatype=XSD.integer)))
    g.add((side_p2_iri, PKM.sideOccursInBattle, battle_iri))

    for iri, info in participants.items():
        side_iri = side_p1_iri if info["player_id"] == "p1" else side_p2_iri
        combatant = PKM[iri]
        g.add((combatant, RDF.type, PKM.BattleParticipant))
        g.add((combatant, RDF.type, PKM.TransientCombatant))
        g.add((combatant, PKM.participatesInBattle, battle_iri))
        g.add((combatant, PKM.onSide, side_iri))
        g.add((combatant, PKM.hasCombatantLabel, Literal(info["label"])))

    for move_iri, move_name in moves.items():
        g.add((PKM[move_iri], RDF.type, PKM.Move))
        g.add((PKM[move_iri], PKM.hasName, Literal(move_name)))

    previous_instant = None
    for idx, ev in enumerate(events):
        instant = PKM[f"I_{idx}"]
        g.add((instant, RDF.type, PKM.Instantaneous))
        g.add((instant, PKM.hasProjectionProfile, PKM.ProjectionProfile_PartialMaterializedBattleState))
        g.add((instant, PKM.occursInBattle, battle_iri))
        if previous_instant is not None:
            g.add((instant, PKM.hasPreviousInstantaneous, previous_instant))
        g.add((instant, PKM.hasTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
        g.add((instant, PKM.hasStepIndex, Literal(ev.order, datatype=XSD.integer)))
        g.add((instant, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
        g.add((instant, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
        g.add((instant, PKM.hasReplayStepLabel, Literal(f"{ev.kind}-t{ev.turn}-e{ev.order}")))
        g.add((instant, PKM.supportedByArtifact, artifact_iri))
        previous_instant = instant

    transition_count = 0
    active_combatants_by_slot = {
        slot_key(slot_token): combatant_iri_for_switch(slot_token, species_token, p1_name, p2_name)
        for slot_token, species_token, _hp_status in discover_pre_turn_switches(payload["log"])
    }
    side_by_slot = {
        slot_key(slot_token): side_iri_for_player_id(parse_player_slot(slot_token)[0], p1_name, p2_name)
        for slot_token, _species_token, _hp_status in discover_pre_turn_switches(payload["log"])
    }
    state = StateSnapshot()
    for slot_token, species_token, hp_status in discover_pre_turn_switches(payload["log"]):
        combatant_iri = combatant_iri_for_switch(slot_token, species_token, p1_name, p2_name)
        hp_value = parse_hp_value(hp_status) if hp_status is not None else None
        if hp_value is not None:
            state.current_hp[combatant_iri] = hp_value
    latest_action_by_slot: dict[str, URIRef] = {}
    current_action: ActionExecutionContext | None = None
    previous_materialized_instant: URIRef | None = None
    for idx, ev in enumerate(events):
        instant = PKM[f"I_{idx}"]
        event_sources: dict[str, dict[object, URIRef]] = {
            "hp": {},
            "status": {},
            "weather": {},
            "terrain": {},
            "side": {},
            "volatile": {},
            "transformation": {},
            "active_slot": {},
        }

        if ev.kind == "upkeep":
            finalize_action_context(g, current_action, instant, artifact_iri, ev.turn, ev.order)
            current_action = None
            emit_projected_state(
                g,
                instant,
                previous_materialized_instant,
                state,
                active_combatants_by_slot,
                side_by_slot,
                artifact_iri,
                ev.turn,
                ev.order,
                event_sources,
            )
            previous_materialized_instant = instant
            continue

        if ev.kind in {"switch", "drag", "replace"}:
            finalize_action_context(g, current_action, instant, artifact_iri, ev.turn, ev.order)
            current_action = None
            combatant_iri = combatant_iri_for_switch(ev.fields[0], ev.fields[1], p1_name, p2_name)
            slot_name = slot_key(ev.fields[0])
            active_combatants_by_slot[slot_name] = combatant_iri
            side_by_slot[slot_name] = side_iri_for_player_id(parse_player_slot(ev.fields[0])[0], p1_name, p2_name)

            event_iri = PKM[
                f"Switch_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(ev.kind)}"
            ]

            g.add((event_iri, RDF.type, PKM.SwitchEvent))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"{ev.kind}-t{ev.turn}-e{ev.order}")))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))

            hp_value = parse_hp_value(ev.fields[2]) if len(ev.fields) > 2 else None
            if hp_value is not None:
                state.current_hp[combatant_iri] = hp_value
                event_sources["hp"][combatant_iri] = event_iri
            event_sources["active_slot"][slot_name] = event_iri
        elif ev.kind == "detailschange":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            hp_value = parse_hp_value(ev.fields[2]) if len(ev.fields) > 2 else None
            if hp_value is not None:
                state.current_hp[combatant_iri] = hp_value
        elif ev.kind == "move":
            finalize_action_context(g, current_action, instant, artifact_iri, ev.turn, ev.order)
            actor_token = ev.fields[0]
            move_name = ev.fields[1].strip()
            actor_iri = active_combatants_by_slot.get(slot_key(actor_token), combatant_iri_for_token(actor_token, p1_name, p2_name))
            actor_name = actor_display_name(actor_token)
            move_iri_node = PKM[f"Move{sanitize_identifier(move_name)}"]
            action_iri = PKM[
                f"Action_T{ev.turn}_{ev.order}_{sanitize_identifier(move_name)}_{sanitize_identifier(actor_name)}"
            ]

            g.add((action_iri, RDF.type, PKM.MoveUseAction))
            g.add((action_iri, PKM.actor, actor_iri))
            g.add((action_iri, PKM.usesMove, move_iri_node))
            g.add((action_iri, PKM.declaredInInstantaneous, instant))
            g.add((action_iri, PKM.initiatedInInstantaneous, instant))
            g.add((action_iri, PKM.hasPriorityBracket, Literal(0, datatype=XSD.integer)))
            g.add((action_iri, PKM.hasResolutionIndex, Literal(ev.order, datatype=XSD.integer)))
            g.add((action_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((action_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((action_iri, PKM.hasReplayStepLabel, Literal(f"move-t{ev.turn}-e{ev.order}")))
            g.add((action_iri, PKM.supportedByArtifact, artifact_iri))
            latest_action_by_slot[slot_key(actor_token)] = action_iri

            declared_targets: list[URIRef] = []
            if len(ev.fields) > 2:
                target_iri = maybe_combatant_from_token(ev.fields[2], active_combatants_by_slot, p1_name, p2_name)
                if target_iri is not None:
                    g.add((action_iri, PKM.hasDeclaredTarget, target_iri))
                    declared_targets.append(target_iri)

            candidate_targets = list(declared_targets)
            spread_targets = annotation_value(ev.fields[3:], "spread")
            if spread_targets:
                candidate_targets = target_iris_for_tokens(spread_targets, active_combatants_by_slot, p1_name, p2_name)

            current_action = ActionExecutionContext(
                action_iri=action_iri,
                actor_iri=actor_iri,
                actor_slot=slot_key(actor_token),
                declared_targets=declared_targets,
                candidate_targets=candidate_targets,
            )

            if idx + 1 < len(events):
                transition = PKM[f"Transition_{transition_count}"]
                next_instant = PKM[f"I_{idx + 1}"]
                g.add((transition, RDF.type, PKM.StateTransition))
                g.add((transition, PKM.fromInstantaneous, instant))
                g.add((transition, PKM.toInstantaneous, next_instant))
                g.add((transition, PKM.triggeredByAction, action_iri))
                g.add((transition, PKM.transitionOccursInBattle, battle_iri))
                transition_count += 1

        elif ev.kind in {"-damage", "-heal"}:
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            hp_value = parse_hp_value(ev.fields[1])
            if hp_value is not None:
                event_prefix = "Damage" if ev.kind == "-damage" else "Heal"
                event_type = PKM.DamageEvent if ev.kind == "-damage" else PKM.HealingEvent
                event_iri = PKM[f"{event_prefix}_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]

                g.add((event_iri, RDF.type, event_type))
                g.add((event_iri, PKM.affectsCombatant, combatant_iri))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"{ev.kind[1:]}-t{ev.turn}-e{ev.order}")))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                if should_attribute_minor_event_to_action(current_action, ev.fields[2:]):
                    mark_redirection(current_action, combatant_iri)
                    g.add((event_iri, PKM.causedByAction, current_action.action_iri))
                if should_attribute_minor_event_to_action(current_action, ev.fields[2:]):
                    if combatant_iri != current_action.actor_iri:
                        current_action.hit_counts_by_target[combatant_iri] = current_action.hit_counts_by_target.get(combatant_iri, 0) + 1
                        emit_target_resolution(
                            g,
                            current_action.action_iri,
                            combatant_iri,
                            instant,
                            "resolved",
                            artifact_iri,
                            ev.turn,
                            ev.order,
                            current_action.hit_counts_by_target[combatant_iri],
                        )
                        current_action.resolved_targets.add(combatant_iri)

                state.current_hp[combatant_iri] = hp_value
                event_sources["hp"][combatant_iri] = event_iri

        elif ev.kind == "-status":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            status_iri = maybe_status_iri(g, ev.fields[1])
            if combatant_iri is not None and status_iri is not None:
                event_iri = PKM[f"Status_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]
                causing_action = None
                for field in reversed(ev.fields[2:]):
                    candidate = maybe_combatant_from_token(field, active_combatants_by_slot, p1_name, p2_name)
                    if candidate is None:
                        continue
                    try:
                        causing_action = latest_action_by_slot.get(slot_key(field))
                    except ValueError:
                        causing_action = None
                    if causing_action is not None:
                        break

                g.add((event_iri, RDF.type, PKM.StatusInflictionEvent))
                g.add((event_iri, PKM.affectsCombatant, combatant_iri))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"status-t{ev.turn}-e{ev.order}")))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                if current_action is not None:
                    mark_redirection(current_action, combatant_iri)
                if current_action is not None and combatant_iri != current_action.actor_iri:
                    causing_action = current_action.action_iri
                if causing_action is not None:
                    g.add((event_iri, PKM.causedByAction, causing_action))
                    emit_target_resolution(
                        g,
                        causing_action,
                        combatant_iri,
                        instant,
                        "resolved",
                        artifact_iri,
                        ev.turn,
                        ev.order,
                        1 if current_action is None else current_action.hit_counts_by_target.get(combatant_iri, 0) + 1,
                    )
                    if current_action is not None and causing_action == current_action.action_iri:
                        current_action.hit_counts_by_target[combatant_iri] = current_action.hit_counts_by_target.get(combatant_iri, 0) + 1
                        current_action.resolved_targets.add(combatant_iri)

                state.current_status[combatant_iri] = status_iri
                event_sources["status"][combatant_iri] = event_iri

        elif ev.kind == "-curestatus":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is not None:
                state.current_status.pop(combatant_iri, None)

        elif ev.kind in {"-boost", "-unboost"}:
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            stat_token = ev.fields[1].strip()
            stage_delta = int(ev.fields[2])
            stage_value = stage_delta if ev.kind == "-boost" else -stage_delta
            stat_iri = stat_iri_for_token(stat_token)
            ensure_named_entity(g, stat_iri, PKM.Stat, STAT_TOKEN_TO_NAME.get(stat_token, stat_token))

            assignment_iri = PKM[
                f"Stage_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(stat_token)}"
            ]
            g.add((assignment_iri, RDF.type, PKM.StatStageAssignment))
            g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
            g.add((assignment_iri, PKM.aboutStat, stat_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.hasStageValue, Literal(stage_value, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"stage-{ev.kind[1:]}-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-weather":
            weather_token = ev.fields[0].strip()
            if weather_token == "none":
                state.current_weather = None
                event_sources["weather"]["battle"] = PKM[f"WeatherClear_T{ev.turn}_{ev.order}"]
                g.add((event_sources["weather"]["battle"], RDF.type, PKM.Event))
                g.add((event_sources["weather"]["battle"], PKM.occursInInstantaneous, instant))
                g.add((event_sources["weather"]["battle"], PKM.supportedByArtifact, artifact_iri))
                g.add((event_sources["weather"]["battle"], PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_sources["weather"]["battle"], PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_sources["weather"]["battle"], PKM.hasReplayStepLabel, Literal(f"weather-clear-t{ev.turn}-e{ev.order}")))
            else:
                weather_name = WEATHER_TOKEN_TO_NAME.get(weather_token, weather_token)
                weather_iri = PKM[f"Weather_{sanitize_identifier(weather_name)}"]
                ensure_named_entity(g, weather_iri, PKM.WeatherCondition, weather_name)

                event_iri = PKM[f"WeatherEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(weather_name)}"]
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"weather-t{ev.turn}-e{ev.order}")))
                state.current_weather = weather_iri
                event_sources["weather"]["battle"] = event_iri

        elif ev.kind == "-fieldstart":
            terrain_name = TERRAIN_TOKEN_TO_NAME.get(ev.fields[0].strip())
            if terrain_name is not None:
                terrain_iri = PKM[f"Terrain_{sanitize_identifier(terrain_name)}"]
                ensure_named_entity(g, terrain_iri, PKM.TerrainCondition, terrain_name)
                event_iri = PKM[f"TerrainEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(terrain_name)}"]
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"terrain-t{ev.turn}-e{ev.order}")))
                state.current_terrain = terrain_iri
                event_sources["terrain"]["battle"] = event_iri

        elif ev.kind == "-fieldend":
            terrain_name = TERRAIN_TOKEN_TO_NAME.get(ev.fields[0].strip())
            if terrain_name is not None:
                state.current_terrain = None

        elif ev.kind == "-sidestart":
            side_iri = side_iri_for_token(ev.fields[0], p1_name, p2_name)
            condition_name = SIDE_CONDITION_TOKEN_TO_NAME.get(ev.fields[1].strip())
            if condition_name is not None:
                condition_iri = PKM[f"SideCondition_{sanitize_identifier(condition_name)}"]
                ensure_named_entity(g, condition_iri, PKM.SideCondition, condition_name)
                event_iri = PKM[f"SideConditionEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(condition_name)}"]
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"sidecond-t{ev.turn}-e{ev.order}")))
                state.current_side_conditions.add((side_iri, condition_iri))
                event_sources["side"][(side_iri, condition_iri)] = event_iri

        elif ev.kind == "-sideend":
            side_iri = side_iri_for_token(ev.fields[0], p1_name, p2_name)
            condition_name = SIDE_CONDITION_TOKEN_TO_NAME.get(ev.fields[1].strip())
            if condition_name is not None:
                condition_iri = PKM[f"SideCondition_{sanitize_identifier(condition_name)}"]
                state.current_side_conditions.discard((side_iri, condition_iri))

        elif ev.kind == "-terastallize":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            tera_type = ev.fields[1].strip()
            transformation_name = f"Terastallized {tera_type}"
            transformation_iri = PKM[f"Transformation_{sanitize_identifier(transformation_name)}"]
            ensure_named_entity(g, transformation_iri, PKM.TransformationState, transformation_name)

            state.current_transformations[combatant_iri] = transformation_iri
            event_sources["transformation"][combatant_iri] = PKM[
                f"TransformationEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
            ]
            g.add((event_sources["transformation"][combatant_iri], RDF.type, PKM.Event))
            g.add((event_sources["transformation"][combatant_iri], PKM.occursInInstantaneous, instant))
            g.add((event_sources["transformation"][combatant_iri], PKM.supportedByArtifact, artifact_iri))
            g.add((event_sources["transformation"][combatant_iri], PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_sources["transformation"][combatant_iri], PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_sources["transformation"][combatant_iri], PKM.hasReplayStepLabel, Literal(f"tera-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-singleturn":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            volatile_iri = maybe_volatile_iri(g, ev.fields[1])
            if volatile_iri is not None:
                event_iri = PKM[
                    f"VolatileEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{str(volatile_iri).rsplit('#', 1)[-1]}"
                ]
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"volatile-t{ev.turn}-e{ev.order}")))
                state.current_volatile_conditions.add((combatant_iri, volatile_iri))
                event_sources["volatile"][(combatant_iri, volatile_iri)] = event_iri

        elif ev.kind == "-end":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            volatile_iri = maybe_volatile_iri(g, ev.fields[1]) if len(ev.fields) > 1 else None
            if combatant_iri is not None and volatile_iri is not None:
                state.current_volatile_conditions.discard((combatant_iri, volatile_iri))

        elif ev.kind == "-fail":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is not None:
                try:
                    action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                except ValueError:
                    action_iri = None
                if action_iri is not None:
                    emit_target_resolution(g, action_iri, combatant_iri, instant, "failed", artifact_iri, ev.turn, ev.order)
                    if current_action is not None and action_iri == current_action.action_iri:
                        current_action.failed_targets.add(combatant_iri)

        elif ev.kind == "-miss":
            if len(ev.fields) >= 2:
                source_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
                target_iri = maybe_combatant_from_token(ev.fields[1], active_combatants_by_slot, p1_name, p2_name)
                if source_iri is not None and target_iri is not None:
                    try:
                        action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                    except ValueError:
                        action_iri = None
                    if action_iri is not None:
                        emit_target_resolution(g, action_iri, target_iri, instant, "failed", artifact_iri, ev.turn, ev.order)
                        if current_action is not None and action_iri == current_action.action_iri:
                            current_action.failed_targets.add(target_iri)

        elif ev.kind == "cant":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is not None:
                try:
                    action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                except ValueError:
                    action_iri = None
                if action_iri is not None:
                    emit_target_resolution(g, action_iri, combatant_iri, instant, "aborted", artifact_iri, ev.turn, ev.order)
                    if current_action is not None and action_iri == current_action.action_iri:
                        current_action.aborted_targets.add(combatant_iri)

        elif ev.kind in {"-supereffective", "-resisted", "-immune", "-activate"}:
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is not None and current_action is not None:
                mark_redirection(current_action, combatant_iri)

        elif ev.kind == "faint":
            fainted_token = ev.fields[0]
            fainted_iri = active_combatants_by_slot.get(
                slot_key(fainted_token),
                combatant_iri_for_token(fainted_token, p1_name, p2_name),
            )
            fainted_name = actor_display_name(fainted_token)
            event_iri = PKM[f"Faint_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"]
            g.add((event_iri, RDF.type, PKM.FaintEvent))
            g.add((event_iri, PKM.affectsCombatant, fainted_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"faint-t{ev.turn}-e{ev.order}")))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            if should_attribute_minor_event_to_action(current_action, ev.fields[1:]):
                mark_redirection(current_action, fainted_iri)
            if should_attribute_minor_event_to_action(current_action, ev.fields[1:]):
                g.add((event_iri, PKM.causedByAction, current_action.action_iri))
                if fainted_iri != current_action.actor_iri:
                    current_action.hit_counts_by_target[fainted_iri] = current_action.hit_counts_by_target.get(fainted_iri, 0) + 1
                    emit_target_resolution(
                        g,
                        current_action.action_iri,
                        fainted_iri,
                        instant,
                        "resolved",
                        artifact_iri,
                        ev.turn,
                        ev.order,
                        current_action.hit_counts_by_target[fainted_iri],
                    )
                    current_action.resolved_targets.add(fainted_iri)

            state.current_hp[fainted_iri] = 0
            event_sources["hp"][fainted_iri] = event_iri

            fainted_slot = slot_key(fainted_token)
            active_combatants_by_slot.pop(fainted_slot, None)
            side_by_slot.pop(fainted_slot, None)

        emit_projected_state(
            g,
            instant,
            previous_materialized_instant,
            state,
            active_combatants_by_slot,
            side_by_slot,
            artifact_iri,
            ev.turn,
            ev.order,
            event_sources,
        )
        previous_materialized_instant = instant

    if events:
        finalize_action_context(
            g,
            current_action,
            PKM[f"I_{len(events) - 1}"],
            artifact_iri,
            events[-1].turn,
            events[-1].order,
        )

    return g


def build_ttl(payload: dict) -> str:
    return build_graph(payload).serialize(format="turtle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay_json", type=Path, help="Path to Pokémon Showdown replay JSON")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <replay_json stem>-slice.ttl",
    )
    args = parser.parse_args()

    payload = json.loads(args.replay_json.read_text(encoding="utf-8"))
    ttl = build_ttl(payload)

    output_path = args.output or args.replay_json.with_name(f"{args.replay_json.stem}-slice.ttl")
    output_path.write_text(ttl, encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
