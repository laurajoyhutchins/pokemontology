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
}
STATUS_TOKEN_TO_NAME = {
    "brn": "Burn",
    "par": "Paralysis",
    "psn": "Poison",
    "tox": "Badly Poisoned",
    "slp": "Sleep",
    "frz": "Freeze",
}


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


def discover_pre_turn_switches(log: str) -> list[tuple[str, str]]:
    switches: list[tuple[str, str]] = []
    for raw_line in log.splitlines():
        if raw_line == "|turn|1":
            break
        if not raw_line.startswith("|switch|"):
            continue
        parts = raw_line.split("|")
        if len(parts) >= 4:
            switches.append((parts[2], parts[3]))
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
    for slot_token, species_token in discover_pre_turn_switches(payload["log"]):
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
        g.add((instant, PKM.hasProjectionProfile, PKM.ProjectionProfile_ReplayObservedOnly))
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
        for slot_token, species_token in discover_pre_turn_switches(payload["log"])
    }
    latest_action_by_slot: dict[str, URIRef] = {}
    for idx, ev in enumerate(events):
        instant = PKM[f"I_{idx}"]

        if ev.kind in {"switch", "drag", "replace"}:
            combatant_iri = combatant_iri_for_switch(ev.fields[0], ev.fields[1], p1_name, p2_name)
            active_combatants_by_slot[slot_key(ev.fields[0])] = combatant_iri

            event_iri = PKM[
                f"Switch_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(ev.kind)}"
            ]
            hp_assignment = PKM[
                f"HP_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(ev.kind)}"
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
                g.add((hp_assignment, RDF.type, PKM.CurrentHPAssignment))
                g.add((hp_assignment, PKM.aboutCombatant, combatant_iri))
                g.add((hp_assignment, PKM.hasContext, instant))
                g.add((hp_assignment, PKM.hasCurrentHPValue, Literal(hp_value, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.materializedFromEvent, event_iri))
                g.add((hp_assignment, PKM.supportedByArtifact, artifact_iri))
                g.add((hp_assignment, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.hasReplayStepLabel, Literal(f"hp-{ev.kind}-t{ev.turn}-e{ev.order}")))
            continue

        if ev.kind == "detailschange":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            hp_value = parse_hp_value(ev.fields[2]) if len(ev.fields) > 2 else None
            if hp_value is not None:
                hp_assignment = PKM[
                    f"HP_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_detailschange"
                ]
                g.add((hp_assignment, RDF.type, PKM.CurrentHPAssignment))
                g.add((hp_assignment, PKM.aboutCombatant, combatant_iri))
                g.add((hp_assignment, PKM.hasContext, instant))
                g.add((hp_assignment, PKM.hasCurrentHPValue, Literal(hp_value, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.supportedByArtifact, artifact_iri))
                g.add((hp_assignment, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
                g.add((hp_assignment, PKM.hasReplayStepLabel, Literal(f"hp-detailschange-t{ev.turn}-e{ev.order}")))
            continue

        if ev.kind == "move":
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

            if len(ev.fields) > 2:
                target_iri = maybe_combatant_from_token(ev.fields[2], active_combatants_by_slot, p1_name, p2_name)
                if target_iri is not None:
                    g.add((action_iri, PKM.hasDeclaredTarget, target_iri))

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
            if hp_value is None:
                continue

            event_prefix = "Damage" if ev.kind == "-damage" else "Heal"
            event_type = PKM.DamageEvent if ev.kind == "-damage" else PKM.HealingEvent
            event_iri = PKM[f"{event_prefix}_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]
            hp_assignment = PKM[f"HP_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]

            g.add((event_iri, RDF.type, event_type))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"{ev.kind[1:]}-t{ev.turn}-e{ev.order}")))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))

            g.add((hp_assignment, RDF.type, PKM.CurrentHPAssignment))
            g.add((hp_assignment, PKM.aboutCombatant, combatant_iri))
            g.add((hp_assignment, PKM.hasContext, instant))
            g.add((hp_assignment, PKM.hasCurrentHPValue, Literal(hp_value, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.materializedFromEvent, event_iri))
            g.add((hp_assignment, PKM.supportedByArtifact, artifact_iri))
            g.add((hp_assignment, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.hasReplayStepLabel, Literal(f"hp-{ev.kind[1:]}-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-status":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            status_iri = maybe_status_iri(g, ev.fields[1])
            if combatant_iri is None or status_iri is None:
                continue

            event_iri = PKM[f"Status_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]
            assignment_iri = PKM[f"StatusAssignment_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"]
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
            if causing_action is not None:
                g.add((event_iri, PKM.causedByAction, causing_action))

            g.add((assignment_iri, RDF.type, PKM.CurrentStatusAssignment))
            g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
            g.add((assignment_iri, PKM.hasStatusCondition, status_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.materializedFromEvent, event_iri))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"status-assign-t{ev.turn}-e{ev.order}")))

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
            weather_name = WEATHER_TOKEN_TO_NAME.get(ev.fields[0].strip(), ev.fields[0].strip())
            weather_iri = PKM[f"Weather_{sanitize_identifier(weather_name)}"]
            ensure_named_entity(g, weather_iri, PKM.WeatherCondition, weather_name)

            assignment_iri = PKM[f"Weather_T{ev.turn}_{ev.order}_{sanitize_identifier(weather_name)}"]
            g.add((assignment_iri, RDF.type, PKM.CurrentWeatherAssignment))
            g.add((assignment_iri, PKM.aboutField, battle_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.hasWeatherCondition, weather_iri))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"weather-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-fieldstart":
            terrain_name = TERRAIN_TOKEN_TO_NAME.get(ev.fields[0].strip())
            if terrain_name is None:
                continue
            terrain_iri = PKM[f"Terrain_{sanitize_identifier(terrain_name)}"]
            ensure_named_entity(g, terrain_iri, PKM.TerrainCondition, terrain_name)

            assignment_iri = PKM[f"Terrain_T{ev.turn}_{ev.order}_{sanitize_identifier(terrain_name)}"]
            g.add((assignment_iri, RDF.type, PKM.CurrentTerrainAssignment))
            g.add((assignment_iri, PKM.aboutField, battle_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.hasTerrainCondition, terrain_iri))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"terrain-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-sidestart":
            side_iri = side_iri_for_token(ev.fields[0], p1_name, p2_name)
            condition_name = SIDE_CONDITION_TOKEN_TO_NAME.get(ev.fields[1].strip())
            if condition_name is None:
                continue
            condition_iri = PKM[f"SideCondition_{sanitize_identifier(condition_name)}"]
            ensure_named_entity(g, condition_iri, PKM.SideCondition, condition_name)

            assignment_iri = PKM[f"SideCondition_T{ev.turn}_{ev.order}_{sanitize_identifier(condition_name)}"]
            g.add((assignment_iri, RDF.type, PKM.SideConditionAssignment))
            g.add((assignment_iri, PKM.aboutSide, side_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.hasSideCondition, condition_iri))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"sidecond-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-terastallize":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            tera_type = ev.fields[1].strip()
            transformation_name = f"Terastallized {tera_type}"
            transformation_iri = PKM[f"Transformation_{sanitize_identifier(transformation_name)}"]
            ensure_named_entity(g, transformation_iri, PKM.TransformationState, transformation_name)

            assignment_iri = PKM[
                f"Transformation_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
            ]
            g.add((assignment_iri, RDF.type, PKM.CurrentTransformationAssignment))
            g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
            g.add((assignment_iri, PKM.hasTransformationState, transformation_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"tera-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-singleturn":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            volatile_name = VOLATILE_TOKEN_TO_NAME.get(ev.fields[1].strip())
            if volatile_name is None:
                continue
            volatile_iri = PKM[f"VolatileCondition_{sanitize_identifier(volatile_name)}"]
            ensure_named_entity(g, volatile_iri, PKM.VolatileCondition, volatile_name)

            assignment_iri = PKM[
                f"Volatile_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(volatile_name)}"
            ]
            g.add((assignment_iri, RDF.type, PKM.VolatileStatusAssignment))
            g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
            g.add((assignment_iri, PKM.hasVolatileCondition, volatile_iri))
            g.add((assignment_iri, PKM.hasContext, instant))
            g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((assignment_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((assignment_iri, PKM.hasReplayStepLabel, Literal(f"volatile-t{ev.turn}-e{ev.order}")))

        elif ev.kind == "-fail":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is None:
                continue
            try:
                action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
            except ValueError:
                action_iri = None
            if action_iri is None:
                continue
            resolution_iri = PKM[
                f"Resolution_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_fail"
            ]
            g.add((resolution_iri, RDF.type, PKM.TargetResolutionState))
            g.add((resolution_iri, PKM.aboutAction, action_iri))
            g.add((resolution_iri, PKM.aboutTarget, combatant_iri))
            g.add((resolution_iri, PKM.hasContext, instant))
            g.add((resolution_iri, PKM.hasResolutionOutcome, Literal("failed")))
            g.add((resolution_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((resolution_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayStepLabel, Literal(f"resolution-fail-t{ev.turn}-e{ev.order}")))
            g.add((action_iri, PKM.hasResolvedTarget, combatant_iri))

        elif ev.kind == "-miss":
            if len(ev.fields) < 2:
                continue
            source_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            target_iri = maybe_combatant_from_token(ev.fields[1], active_combatants_by_slot, p1_name, p2_name)
            if source_iri is None or target_iri is None:
                continue
            try:
                action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
            except ValueError:
                action_iri = None
            if action_iri is None:
                continue
            resolution_iri = PKM[
                f"Resolution_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(actor_display_name(ev.fields[1]))}_miss"
            ]
            g.add((resolution_iri, RDF.type, PKM.TargetResolutionState))
            g.add((resolution_iri, PKM.aboutAction, action_iri))
            g.add((resolution_iri, PKM.aboutTarget, target_iri))
            g.add((resolution_iri, PKM.hasContext, instant))
            g.add((resolution_iri, PKM.hasResolutionOutcome, Literal("failed")))
            g.add((resolution_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((resolution_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayStepLabel, Literal(f"resolution-miss-t{ev.turn}-e{ev.order}")))
            g.add((action_iri, PKM.hasResolvedTarget, target_iri))

        elif ev.kind == "cant":
            combatant_iri = maybe_combatant_from_token(ev.fields[0], active_combatants_by_slot, p1_name, p2_name)
            if combatant_iri is None:
                continue
            try:
                action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
            except ValueError:
                action_iri = None
            if action_iri is None:
                continue
            resolution_iri = PKM[
                f"Resolution_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_cant"
            ]
            g.add((resolution_iri, RDF.type, PKM.TargetResolutionState))
            g.add((resolution_iri, PKM.aboutAction, action_iri))
            g.add((resolution_iri, PKM.aboutTarget, combatant_iri))
            g.add((resolution_iri, PKM.hasContext, instant))
            g.add((resolution_iri, PKM.hasResolutionOutcome, Literal("aborted")))
            g.add((resolution_iri, PKM.supportedByArtifact, artifact_iri))
            g.add((resolution_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((resolution_iri, PKM.hasReplayStepLabel, Literal(f"resolution-cant-t{ev.turn}-e{ev.order}")))
            g.add((action_iri, PKM.hasResolvedTarget, combatant_iri))

        elif ev.kind == "faint":
            fainted_token = ev.fields[0]
            fainted_iri = active_combatants_by_slot.get(
                slot_key(fainted_token),
                combatant_iri_for_token(fainted_token, p1_name, p2_name),
            )
            fainted_name = actor_display_name(fainted_token)
            event_iri = PKM[f"Faint_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"]
            hp_assignment = PKM[f"HP_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"]

            g.add((event_iri, RDF.type, PKM.FaintEvent))
            g.add((event_iri, PKM.affectsCombatant, fainted_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayStepLabel, Literal(f"faint-t{ev.turn}-e{ev.order}")))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))

            g.add((hp_assignment, RDF.type, PKM.CurrentHPAssignment))
            g.add((hp_assignment, PKM.aboutCombatant, fainted_iri))
            g.add((hp_assignment, PKM.hasContext, instant))
            g.add((hp_assignment, PKM.hasCurrentHPValue, Literal(0, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.materializedFromEvent, event_iri))
            g.add((hp_assignment, PKM.supportedByArtifact, artifact_iri))
            g.add((hp_assignment, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((hp_assignment, PKM.hasReplayStepLabel, Literal(f"hp-faint-t{ev.turn}-e{ev.order}")))

            active_combatants_by_slot.pop(slot_key(fainted_token), None)

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
