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

from pokemontology.ingest_common import (
    PKMB,
    bind_namespaces,
    entity_iri,
    serialize_turtle_to_path,
)
from pokemontology.replay.replay_parser import (
    PKM_PREFIX,
    actor_display_name,
    compact_species_name,
    discover_moves,
    discover_participants,
    parse_log,
    parse_player_slot,
    parse_replay_payload,
    parse_side_token,
    pokeapi_move_id,
    pokeapi_species_id,
    sanitize_identifier,
)

PKM = Namespace(PKM_PREFIX)
SITE_BASE = "https://laurajoyhutchins.github.io/pokemontology"


def _species_iri(species_raw: str) -> URIRef:
    return entity_iri("Species", pokeapi_species_id(species_raw))


def _move_iri(move_name: str) -> URIRef:
    return entity_iri("Move", pokeapi_move_id(move_name))


def _type_iri(type_name: str) -> URIRef:
    return entity_iri("Type", type_name)


def _ability_iri(ability_name: str) -> URIRef:
    return entity_iri("Ability", ability_name)


def _item_iri(item_name: str) -> URIRef:
    return entity_iri("Item", item_name)


def _stat_iri(stat_name: str) -> URIRef:
    return entity_iri("Stat", stat_name)


def _battle_iri(local_name: str) -> URIRef:
    return PKMB[local_name]


def _iri_token(iri: URIRef | str) -> str:
    text = str(iri)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    return text.rstrip("/").rsplit("/", 1)[-1]


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
    "move: Reflect": "Reflect",
    "move: Light Screen": "Light Screen",
    "move: Aurora Veil": "Aurora Veil",
    "move: Safeguard": "Safeguard",
    "move: Mist": "Mist",
    "move: Lucky Chant": "Lucky Chant",
    "Spikes": "Spikes",
    "Toxic Spikes": "Toxic Spikes",
    "Stealth Rock": "Stealth Rock",
    "move: Stealth Rock": "Stealth Rock",
    "Sticky Web": "Sticky Web",
    "move: Sticky Web": "Sticky Web",
}
TERRAIN_TOKEN_TO_NAME = {
    "move: Psychic Terrain": "Psychic Terrain",
    "move: Electric Terrain": "Electric Terrain",
    "move: Misty Terrain": "Misty Terrain",
    "move: Grassy Terrain": "Grassy Terrain",
}
WEATHER_TOKEN_TO_NAME = {
    "SunnyDay": "Harsh Sunlight",
    "RainDance": "Rain",
    "Sandstorm": "Sandstorm",
    "Hail": "Hail",
    "Snow": "Snow",
    "PrimordialSea": "Primordial Sea",
    "DesolateLand": "Desolate Land",
    "DeltaStream": "Delta Stream",
}
VOLATILE_TOKEN_TO_NAME = {
    "Protect": "Protecting",
    "move: Protect": "Protecting",
    "move: Detect": "Protecting",
    "move: King's Shield": "King's Shield",
    "move: Spiky Shield": "Spiky Shield",
    "move: Baneful Bunker": "Baneful Bunker",
    "move: Obstruct": "Obstruct",
    "move: Silk Trap": "Silk Trap",
    "confusion": "Confusion",
    "move: Confusion": "Confusion",
    "move: Leech Seed": "Leech Seed",
    "Substitute": "Substitute",
    "move: Substitute": "Substitute",
    "move: Taunt": "Taunt",
    "move: Encore": "Encore",
    "move: Disable": "Disable",
    "move: Torment": "Torment",
    "move: Embargo": "Embargo",
    "move: Heal Block": "Heal Block",
    "move: Yawn": "Yawn",
    "move: Ingrain": "Ingrain",
    "move: Aqua Ring": "Aqua Ring",
    "move: Magnet Rise": "Magnet Rise",
    "move: Destiny Bond": "Destiny Bond",
    "move: Grudge": "Grudge",
    "move: Snatch": "Snatch",
    "move: Telekinesis": "Telekinesis",
    "move: Octolock": "Octolock",
    "move: No Retreat": "No Retreat",
    "move: Tar Shot": "Tar Shot",
    "move: Syrup Bomb": "Syrup Bomb",
    "move: Curse": "Curse",
    "move: Power Trick": "Power Trick",
    "move: Bide": "Bide",
    "Truant": "Truant",
    "Salt Cure": "Salt Cure",
    "move: Salt Cure": "Salt Cure",
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
    current_stat_stages: dict[tuple[URIRef, URIRef], int] = field(default_factory=dict)
    current_status: dict[URIRef, URIRef] = field(default_factory=dict)
    current_weather: URIRef | None = None
    current_terrain: URIRef | None = None
    current_side_conditions: set[tuple[URIRef, URIRef]] = field(default_factory=set)
    current_volatile_conditions: set[tuple[URIRef, URIRef]] = field(default_factory=set)
    current_transformations: dict[URIRef, URIRef] = field(default_factory=dict)
    current_item: dict[URIRef, URIRef] = field(default_factory=dict)
    current_ability: dict[URIRef, URIRef] = field(default_factory=dict)


def combatant_iri_for_token(token: str, p1_name: str, p2_name: str) -> URIRef:
    try:
        player_id, _slot = parse_player_slot(token)
    except ValueError:
        player_id = parse_side_token(token)
    trainer = p1_name if player_id == "p1" else p2_name
    actor_name = actor_display_name(token)
    return _battle_iri(
        f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(actor_name)}"
    )


def slot_key(token: str) -> str | None:
    """Return 'p1a'/'p2b' etc., or None if the token has no slot letter."""
    try:
        player_id, slot = parse_player_slot(token)
        return f"{player_id}{slot}"
    except ValueError:
        return None


def combatant_iri_for_switch(
    token: str, species_token: str, p1_name: str, p2_name: str
) -> URIRef:
    player_id, _slot = parse_player_slot(token)
    trainer = p1_name if player_id == "p1" else p2_name
    return _battle_iri(
        f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(species_token)}"
    )


def side_iri_for_token(token: str, p1_name: str, p2_name: str) -> URIRef:
    side_id = parse_side_token(token)
    trainer = p1_name if side_id == "p1" else p2_name
    return _battle_iri(f"Side_{sanitize_identifier(trainer)}")


def side_iri_for_player_id(player_id: str, p1_name: str, p2_name: str) -> URIRef:
    trainer = p1_name if player_id == "p1" else p2_name
    return _battle_iri(f"Side_{sanitize_identifier(trainer)}")


def stat_iri_for_token(token: str) -> URIRef:
    stat_name = STAT_TOKEN_TO_NAME.get(token, token)
    return _stat_iri(stat_name)


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
    key = slot_key(token)
    if key is None:
        return None
    return active_combatants_by_slot.get(
        key, combatant_iri_for_token(token, p1_name, p2_name)
    )


def maybe_status_iri(g: Graph, token: str) -> URIRef | None:
    status_name = STATUS_TOKEN_TO_NAME.get(token.strip())
    if status_name is None:
        return None
    status_iri = _battle_iri(f"StatusCondition_{sanitize_identifier(status_name)}")
    ensure_named_entity(g, status_iri, PKM.StatusCondition, status_name)
    return status_iri


def maybe_volatile_iri(g: Graph, token: str) -> URIRef | None:
    volatile_name = VOLATILE_TOKEN_TO_NAME.get(token.strip())
    if volatile_name is None:
        return None
    volatile_iri = _battle_iri(
        f"VolatileCondition_{sanitize_identifier(volatile_name)}"
    )
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
        g.add(
            (
                assignment_iri,
                PKM.materializedFromPreviousInstantaneous,
                previous_instant,
            )
        )


def emit_projected_state(
    g: Graph,
    instant: URIRef,
    previous_instant: URIRef | None,
    battle_iri: URIRef,
    state: StateSnapshot,
    active_combatants_by_slot: dict[str, URIRef],
    side_by_slot: dict[str, URIRef],
    artifact_iri: URIRef,
    turn: int,
    order: int,
    event_sources: dict[str, dict[object, URIRef]],
) -> None:
    instant_name = _iri_token(instant)

    for combatant_iri, hp_value in state.current_hp.items():
        label = _iri_token(combatant_iri)
        assignment_iri = _battle_iri(f"HP_{instant_name}_{label}")
        g.add((assignment_iri, RDF.type, PKM.CurrentHPAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add(
            (
                assignment_iri,
                PKM.hasCurrentHPValue,
                Literal(hp_value, datatype=XSD.integer),
            )
        )
        add_materialization_provenance(
            g, assignment_iri, event_sources["hp"].get(combatant_iri), previous_instant
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"hp-state-t{turn}-e{order}"),
            )
        )

    for (combatant_iri, stat_iri), stage_value in sorted(
        state.current_stat_stages.items(),
        key=lambda item: (str(item[0][0]), str(item[0][1])),
    ):
        label = _iri_token(combatant_iri)
        stat_label = _iri_token(stat_iri)
        assignment_iri = _battle_iri(f"Stage_{instant_name}_{label}_{stat_label}")
        g.add((assignment_iri, RDF.type, PKM.StatStageAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.aboutStat, stat_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add(
            (
                assignment_iri,
                PKM.hasStageValue,
                Literal(stage_value, datatype=XSD.integer),
            )
        )
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["stage"].get((combatant_iri, stat_iri)),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"stage-state-t{turn}-e{order}"),
            )
        )

    for combatant_iri, status_iri in state.current_status.items():
        label = _iri_token(combatant_iri)
        assignment_iri = _battle_iri(f"StatusAssignment_{instant_name}_{label}")
        g.add((assignment_iri, RDF.type, PKM.CurrentStatusAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasStatusCondition, status_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["status"].get(combatant_iri),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"status-state-t{turn}-e{order}"),
            )
        )

    if state.current_weather is not None:
        weather_name = _iri_token(state.current_weather)
        assignment_iri = _battle_iri(f"Weather_{instant_name}_{weather_name}")
        g.add((assignment_iri, RDF.type, PKM.CurrentWeatherAssignment))
        g.add((assignment_iri, PKM.aboutField, battle_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasWeatherCondition, state.current_weather))
        add_materialization_provenance(
            g, assignment_iri, event_sources["weather"].get("battle"), previous_instant
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"weather-state-t{turn}-e{order}"),
            )
        )

    if state.current_terrain is not None:
        terrain_name = _iri_token(state.current_terrain)
        assignment_iri = _battle_iri(f"Terrain_{instant_name}_{terrain_name}")
        g.add((assignment_iri, RDF.type, PKM.CurrentTerrainAssignment))
        g.add((assignment_iri, PKM.aboutField, battle_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasTerrainCondition, state.current_terrain))
        add_materialization_provenance(
            g, assignment_iri, event_sources["terrain"].get("battle"), previous_instant
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"terrain-state-t{turn}-e{order}"),
            )
        )

    for side_iri, condition_iri in sorted(
        state.current_side_conditions, key=lambda item: (str(item[0]), str(item[1]))
    ):
        assignment_iri = _battle_iri(
            f"SideCondition_{instant_name}_{_iri_token(side_iri)}_{_iri_token(condition_iri)}"
        )
        g.add((assignment_iri, RDF.type, PKM.SideConditionAssignment))
        g.add((assignment_iri, PKM.aboutSide, side_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        g.add((assignment_iri, PKM.hasSideCondition, condition_iri))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["side"].get((side_iri, condition_iri)),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"side-state-t{turn}-e{order}"),
            )
        )

    for combatant_iri, condition_iri in sorted(
        state.current_volatile_conditions, key=lambda item: (str(item[0]), str(item[1]))
    ):
        assignment_iri = _battle_iri(
            f"Volatile_{instant_name}_{_iri_token(combatant_iri)}_{_iri_token(condition_iri)}"
        )
        g.add((assignment_iri, RDF.type, PKM.VolatileStatusAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasVolatileCondition, condition_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["volatile"].get((combatant_iri, condition_iri)),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"volatile-state-t{turn}-e{order}"),
            )
        )

    for combatant_iri, transformation_iri in state.current_transformations.items():
        assignment_iri = _battle_iri(
            f"Transformation_{instant_name}_{_iri_token(combatant_iri)}"
        )
        g.add((assignment_iri, RDF.type, PKM.CurrentTransformationAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasTransformationState, transformation_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["transformation"].get(combatant_iri),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"transformation-state-t{turn}-e{order}"),
            )
        )

    for combatant_iri, item_iri in state.current_item.items():
        label = _iri_token(combatant_iri)
        assignment_iri = _battle_iri(f"Item_{instant_name}_{label}")
        g.add((assignment_iri, RDF.type, PKM.CurrentItemAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasCurrentItem, item_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["item"].get(combatant_iri),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"item-state-t{turn}-e{order}"),
            )
        )

    for combatant_iri, ability_iri in state.current_ability.items():
        label = _iri_token(combatant_iri)
        assignment_iri = _battle_iri(f"Ability_{instant_name}_{label}")
        g.add((assignment_iri, RDF.type, PKM.CurrentAbilityAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.hasCurrentAbility, ability_iri))
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["ability"].get(combatant_iri),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"ability-state-t{turn}-e{order}"),
            )
        )

    for slot_name, combatant_iri in sorted(active_combatants_by_slot.items()):
        assignment_iri = _battle_iri(f"ActiveSlot_{instant_name}_{slot_name}")
        g.add((assignment_iri, RDF.type, PKM.ActiveSlotAssignment))
        g.add((assignment_iri, PKM.aboutCombatant, combatant_iri))
        g.add((assignment_iri, PKM.aboutSide, side_by_slot[slot_name]))
        g.add(
            (
                assignment_iri,
                PKM.hasActiveSlotIndex,
                Literal(slot_index_for_key(slot_name), datatype=XSD.integer),
            )
        )
        g.add((assignment_iri, PKM.hasContext, instant))
        add_materialization_provenance(
            g,
            assignment_iri,
            event_sources["active_slot"].get(slot_name),
            previous_instant,
        )
        g.add((assignment_iri, PKM.supportedByArtifact, artifact_iri))
        g.add(
            (
                assignment_iri,
                PKM.hasReplayTurnIndex,
                Literal(turn, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayEventOrder,
                Literal(order, datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasReplayStepLabel,
                Literal(f"active-slot-state-t{turn}-e{order}"),
            )
        )


def annotation_value(fields: list[str], marker: str) -> str | None:
    prefix = f"[{marker}] "
    exact = f"[{marker}]"
    for field in fields:
        if field == exact:
            return ""
        if field.startswith(prefix):
            return field[len(prefix) :]
    return None


def target_iris_for_tokens(
    token_blob: str,
    active_combatants_by_slot: dict[str, URIRef],
    p1_name: str,
    p2_name: str,
) -> list[URIRef]:
    targets: list[URIRef] = []
    for token in token_blob.split(","):
        candidate = maybe_combatant_from_token(
            token.strip(), active_combatants_by_slot, p1_name, p2_name
        )
        if candidate is not None and candidate not in targets:
            targets.append(candidate)
    return targets


def resolution_iri_for(
    action_iri: URIRef, target_iri: URIRef, outcome: str, occurrence: int
) -> URIRef:
    action_name = _iri_token(action_iri)
    target_name = _iri_token(target_iri)
    return _battle_iri(
        f"Resolution_{action_name}_{target_name}_{sanitize_identifier(outcome)}_N{occurrence}"
    )


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
    g.set(
        (resolution_iri, PKM.hasReplayEventOrder, Literal(order, datatype=XSD.integer))
    )
    g.set(
        (
            resolution_iri,
            PKM.hasReplayStepLabel,
            Literal(f"resolution-{outcome}-t{turn}-e{order}"),
        )
    )
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
        emit_target_resolution(
            g,
            context.action_iri,
            target_iri,
            instant,
            "resolved",
            artifact_iri,
            turn,
            order,
        )
        context.resolved_targets.add(target_iri)


def should_attribute_minor_event_to_action(
    current_action: ActionExecutionContext | None, fields: list[str]
) -> bool:
    if current_action is None:
        return False
    source_annotation = annotation_value(fields, "from")
    if source_annotation is None:
        return True
    return (
        source_annotation.startswith("item: Life Orb") or source_annotation == "Recoil"
    )


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
    bind_namespaces(g)

    replay_id, fmt, source_url, p1_name, p2_name = parse_replay_payload(payload)
    events = parse_log(payload["log"])
    participants = discover_participants(events, p1_name, p2_name)
    for slot_token, species_token, _hp_status in discover_pre_turn_switches(
        payload["log"]
    ):
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
    artifact_iri = _battle_iri(f"ReplayArtifact_{battle_slug}")
    battle_iri = _battle_iri(f"Battle_{battle_slug}")
    side_p1_iri = _battle_iri(f"Side_{sanitize_identifier(p1_name)}")
    side_p2_iri = _battle_iri(f"Side_{sanitize_identifier(p2_name)}")
    ruleset_iri = _battle_iri(f"Ruleset_{sanitize_identifier(fmt)}")

    slice_uri = URIRef(f"{SITE_BASE}/data/replay-slice/{battle_slug}")
    g.add((slice_uri, RDFS.label, Literal(f"Replay-backed slice for {replay_id}")))
    g.add(
        (
            slice_uri,
            RDFS.comment,
            Literal(
                "Auto-generated minimal replay-backed TTL slice from a Pokémon Showdown "
                "replay JSON. This file captures observable actions and faints, not a "
                "dense reconstructed battle state."
            ),
        )
    )

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
    g.add(
        (
            battle_iri,
            RDFS.comment,
            Literal("Battle container auto-generated from replay log."),
        )
    )

    g.add((side_p1_iri, RDF.type, PKM.BattleSide))
    g.add((side_p1_iri, PKM.hasSideIndex, Literal(0, datatype=XSD.integer)))
    g.add((side_p1_iri, PKM.sideOccursInBattle, battle_iri))

    g.add((side_p2_iri, RDF.type, PKM.BattleSide))
    g.add((side_p2_iri, PKM.hasSideIndex, Literal(1, datatype=XSD.integer)))
    g.add((side_p2_iri, PKM.sideOccursInBattle, battle_iri))

    for iri, info in participants.items():
        side_iri = side_p1_iri if info["player_id"] == "p1" else side_p2_iri
        combatant = _battle_iri(iri)
        g.add((combatant, RDF.type, PKM.BattleParticipant))
        g.add((combatant, RDF.type, PKM.TransientCombatant))
        g.add((combatant, PKM.participatesInBattle, battle_iri))
        g.add((combatant, PKM.onSide, side_iri))
        g.add((combatant, PKM.hasCombatantLabel, Literal(info["label"])))
        g.add((combatant, PKM.representsSpecies, _species_iri(info["species_raw"])))

    for _move_key, move_name in moves.items():
        move_iri = _move_iri(move_name)
        g.add((move_iri, RDF.type, PKM.Move))
        g.add((move_iri, PKM.hasName, Literal(move_name)))

    previous_instant = None
    for idx, ev in enumerate(events):
        instant = _battle_iri(f"I_{idx}")
        g.add((instant, RDF.type, PKM.Instantaneous))
        g.add(
            (
                instant,
                PKM.hasProjectionProfile,
                PKM.ProjectionProfile_PartialMaterializedBattleState,
            )
        )
        g.add((instant, PKM.occursInBattle, battle_iri))
        if previous_instant is not None:
            g.add((instant, PKM.hasPreviousInstantaneous, previous_instant))
        g.add((instant, PKM.hasTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
        g.add((instant, PKM.hasStepIndex, Literal(ev.order, datatype=XSD.integer)))
        g.add((instant, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
        g.add(
            (instant, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer))
        )
        g.add(
            (
                instant,
                PKM.hasReplayStepLabel,
                Literal(f"{ev.kind}-t{ev.turn}-e{ev.order}"),
            )
        )
        g.add((instant, PKM.supportedByArtifact, artifact_iri))
        previous_instant = instant

    transition_count = 0
    active_combatants_by_slot = {
        slot_key(slot_token): combatant_iri_for_switch(
            slot_token, species_token, p1_name, p2_name
        )
        for slot_token, species_token, _hp_status in discover_pre_turn_switches(
            payload["log"]
        )
    }
    side_by_slot = {
        slot_key(slot_token): side_iri_for_player_id(
            parse_player_slot(slot_token)[0], p1_name, p2_name
        )
        for slot_token, _species_token, _hp_status in discover_pre_turn_switches(
            payload["log"]
        )
    }
    state = StateSnapshot()
    for slot_token, species_token, hp_status in discover_pre_turn_switches(
        payload["log"]
    ):
        combatant_iri = combatant_iri_for_switch(
            slot_token, species_token, p1_name, p2_name
        )
        hp_value = parse_hp_value(hp_status) if hp_status is not None else None
        if hp_value is not None:
            state.current_hp[combatant_iri] = hp_value
    latest_action_by_slot: dict[str, URIRef] = {}
    current_action: ActionExecutionContext | None = None
    previous_materialized_instant: URIRef | None = None
    for idx, ev in enumerate(events):
        instant = _battle_iri(f"I_{idx}")
        event_sources: dict[str, dict[object, URIRef]] = {
            "hp": {},
            "stage": {},
            "status": {},
            "weather": {},
            "terrain": {},
            "side": {},
            "volatile": {},
            "transformation": {},
            "item": {},
            "ability": {},
            "active_slot": {},
        }

        if ev.kind == "upkeep":
            finalize_action_context(
                g, current_action, instant, artifact_iri, ev.turn, ev.order
            )
            current_action = None
            emit_projected_state(
                g,
                instant,
                previous_materialized_instant,
                battle_iri,
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
            finalize_action_context(
                g, current_action, instant, artifact_iri, ev.turn, ev.order
            )
            current_action = None
            combatant_iri = combatant_iri_for_switch(
                ev.fields[0], ev.fields[1], p1_name, p2_name
            )
            slot_name = slot_key(ev.fields[0])
            active_combatants_by_slot[slot_name] = combatant_iri
            side_by_slot[slot_name] = side_iri_for_player_id(
                parse_player_slot(ev.fields[0])[0], p1_name, p2_name
            )

            event_iri = _battle_iri(
                f"Switch_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(ev.kind)}"
            )

            g.add((event_iri, RDF.type, PKM.SwitchEvent))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"{ev.kind}-t{ev.turn}-e{ev.order}"),
                )
            )
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
            finalize_action_context(
                g, current_action, instant, artifact_iri, ev.turn, ev.order
            )
            actor_token = ev.fields[0]
            move_name = ev.fields[1].strip()
            actor_iri = active_combatants_by_slot.get(
                slot_key(actor_token),
                combatant_iri_for_token(actor_token, p1_name, p2_name),
            )
            actor_name = actor_display_name(actor_token)
            move_iri_node = _move_iri(move_name)
            action_iri = _battle_iri(
                f"Action_T{ev.turn}_{ev.order}_{sanitize_identifier(move_name)}_{sanitize_identifier(actor_name)}"
            )

            g.add((action_iri, RDF.type, PKM.MoveUseAction))
            g.add((action_iri, PKM.actor, actor_iri))
            g.add((action_iri, PKM.usesMove, move_iri_node))
            g.add((action_iri, PKM.declaredInInstantaneous, instant))
            g.add((action_iri, PKM.initiatedInInstantaneous, instant))
            g.add(
                (action_iri, PKM.hasPriorityBracket, Literal(0, datatype=XSD.integer))
            )
            g.add(
                (
                    action_iri,
                    PKM.hasResolutionIndex,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    action_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    action_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    action_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"move-t{ev.turn}-e{ev.order}"),
                )
            )
            g.add((action_iri, PKM.supportedByArtifact, artifact_iri))
            latest_action_by_slot[slot_key(actor_token)] = action_iri

            declared_targets: list[URIRef] = []
            if len(ev.fields) > 2:
                target_iri = maybe_combatant_from_token(
                    ev.fields[2], active_combatants_by_slot, p1_name, p2_name
                )
                if target_iri is not None:
                    g.add((action_iri, PKM.hasDeclaredTarget, target_iri))
                    declared_targets.append(target_iri)

            candidate_targets = list(declared_targets)
            spread_targets = annotation_value(ev.fields[3:], "spread")
            if spread_targets:
                candidate_targets = target_iris_for_tokens(
                    spread_targets, active_combatants_by_slot, p1_name, p2_name
                )

            current_action = ActionExecutionContext(
                action_iri=action_iri,
                actor_iri=actor_iri,
                actor_slot=slot_key(actor_token),
                declared_targets=declared_targets,
                candidate_targets=candidate_targets,
            )

            if idx + 1 < len(events):
                transition = _battle_iri(f"Transition_{transition_count}")
                next_instant = _battle_iri(f"I_{idx + 1}")
                g.add((transition, RDF.type, PKM.StateTransition))
                g.add((transition, PKM.fromInstantaneous, instant))
                g.add((transition, PKM.toInstantaneous, next_instant))
                g.add((transition, PKM.triggeredByAction, action_iri))
                g.add((transition, PKM.transitionOccursInBattle, battle_iri))
                transition_count += 1

        elif ev.kind in {"-damage", "-heal", "-sethp"}:
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            hp_value = parse_hp_value(ev.fields[1])
            if hp_value is not None:
                event_prefix = (
                    "Damage"
                    if ev.kind == "-damage"
                    else "Heal"
                    if ev.kind == "-heal"
                    else "SetHP"
                )
                event_type = (
                    PKM.DamageEvent
                    if ev.kind == "-damage"
                    else PKM.HealingEvent
                    if ev.kind == "-heal"
                    else PKM.Event
                )
                event_iri = _battle_iri(
                    f"{event_prefix}_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
                )

                g.add((event_iri, RDF.type, event_type))
                g.add((event_iri, PKM.affectsCombatant, combatant_iri))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"{ev.kind[1:]}-t{ev.turn}-e{ev.order}"),
                    )
                )
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                if should_attribute_minor_event_to_action(
                    current_action, ev.fields[2:]
                ):
                    mark_redirection(current_action, combatant_iri)
                    g.add((event_iri, PKM.causedByAction, current_action.action_iri))
                if should_attribute_minor_event_to_action(
                    current_action, ev.fields[2:]
                ):
                    if combatant_iri != current_action.actor_iri:
                        current_action.hit_counts_by_target[combatant_iri] = (
                            current_action.hit_counts_by_target.get(combatant_iri, 0)
                            + 1
                        )
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

                if ev.kind == "-sethp" and len(ev.fields) >= 4 and slot_key(ev.fields[2]) is not None:
                    partner_iri = active_combatants_by_slot.get(
                        slot_key(ev.fields[2]),
                        combatant_iri_for_token(ev.fields[2], p1_name, p2_name),
                    )
                    partner_hp_value = parse_hp_value(ev.fields[3])
                    if partner_hp_value is not None:
                        partner_event_iri = _battle_iri(
                            f"SetHP_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[2]))}"
                        )
                        g.add((partner_event_iri, RDF.type, PKM.Event))
                        g.add((partner_event_iri, PKM.affectsCombatant, partner_iri))
                        g.add((partner_event_iri, PKM.occursInInstantaneous, instant))
                        g.add(
                            (
                                partner_event_iri,
                                PKM.hasReplayTurnIndex,
                                Literal(ev.turn, datatype=XSD.integer),
                            )
                        )
                        g.add(
                            (
                                partner_event_iri,
                                PKM.hasReplayEventOrder,
                                Literal(ev.order, datatype=XSD.integer),
                            )
                        )
                        g.add(
                            (
                                partner_event_iri,
                                PKM.hasReplayStepLabel,
                                Literal(f"sethp-t{ev.turn}-e{ev.order}"),
                            )
                        )
                        g.add(
                            (partner_event_iri, PKM.supportedByArtifact, artifact_iri)
                        )
                        if should_attribute_minor_event_to_action(
                            current_action, ev.fields[4:]
                        ):
                            g.add(
                                (
                                    partner_event_iri,
                                    PKM.causedByAction,
                                    current_action.action_iri,
                                )
                            )
                        state.current_hp[partner_iri] = partner_hp_value
                        event_sources["hp"][partner_iri] = partner_event_iri

        elif ev.kind == "-status":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            status_iri = maybe_status_iri(g, ev.fields[1])
            if combatant_iri is not None and status_iri is not None:
                event_iri = _battle_iri(
                    f"Status_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
                )
                causing_action = None
                for field in reversed(ev.fields[2:]):
                    candidate = maybe_combatant_from_token(
                        field, active_combatants_by_slot, p1_name, p2_name
                    )
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
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"status-t{ev.turn}-e{ev.order}"),
                    )
                )
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                if current_action is not None:
                    mark_redirection(current_action, combatant_iri)
                if (
                    current_action is not None
                    and combatant_iri != current_action.actor_iri
                ):
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
                        1
                        if current_action is None
                        else current_action.hit_counts_by_target.get(combatant_iri, 0)
                        + 1,
                    )
                    if (
                        current_action is not None
                        and causing_action == current_action.action_iri
                    ):
                        current_action.hit_counts_by_target[combatant_iri] = (
                            current_action.hit_counts_by_target.get(combatant_iri, 0)
                            + 1
                        )
                        current_action.resolved_targets.add(combatant_iri)

                state.current_status[combatant_iri] = status_iri
                event_sources["status"][combatant_iri] = event_iri

        elif ev.kind == "-curestatus":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                state.current_status.pop(combatant_iri, None)

        elif ev.kind in {"-boost", "-unboost"}:
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            stat_token = ev.fields[1].strip()
            stage_delta = int(ev.fields[2])
            stage_delta = stage_delta if ev.kind == "-boost" else -stage_delta
            stat_iri = stat_iri_for_token(stat_token)
            ensure_named_entity(
                g, stat_iri, PKM.Stat, STAT_TOKEN_TO_NAME.get(stat_token, stat_token)
            )
            event_iri = _battle_iri(
                f"StageChange_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(stat_token)}"
            )
            g.add((event_iri, RDF.type, PKM.StatStageChangeEvent))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.aboutStat, stat_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasStageDelta,
                    Literal(stage_delta, datatype=XSD.integer),
                )
            )
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"stage-{ev.kind[1:]}-t{ev.turn}-e{ev.order}"),
                )
            )
            current_stage = state.current_stat_stages.get((combatant_iri, stat_iri), 0)
            state.current_stat_stages[(combatant_iri, stat_iri)] = max(
                -6, min(6, current_stage + stage_delta)
            )
            event_sources["stage"][(combatant_iri, stat_iri)] = event_iri

        elif ev.kind in {"-clearboost", "-clearallboost"}:
            if ev.kind == "-clearboost":
                combatants = [
                    active_combatants_by_slot.get(
                        slot_key(ev.fields[0]),
                        combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
                    )
                ]
            else:
                combatants = sorted(set(active_combatants_by_slot.values()), key=str)
            for combatant_iri in combatants:
                matching_keys = [
                    key
                    for key in state.current_stat_stages
                    if key[0] == combatant_iri and state.current_stat_stages[key] != 0
                ]
                for key in matching_keys:
                    _combatant_iri, stat_iri = key
                    prior_stage = state.current_stat_stages[key]
                    event_iri = _battle_iri(
                        f"StageChange_T{ev.turn}_{ev.order}_{_iri_token(combatant_iri)}_{_iri_token(stat_iri)}_clear"
                    )
                    g.add((event_iri, RDF.type, PKM.StatStageChangeEvent))
                    g.add((event_iri, PKM.affectsCombatant, combatant_iri))
                    g.add((event_iri, PKM.aboutStat, stat_iri))
                    g.add(
                        (
                            event_iri,
                            PKM.hasStageDelta,
                            Literal(-prior_stage, datatype=XSD.integer),
                        )
                    )
                    g.add((event_iri, PKM.occursInInstantaneous, instant))
                    g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                    g.add(
                        (
                            event_iri,
                            PKM.hasReplayTurnIndex,
                            Literal(ev.turn, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            event_iri,
                            PKM.hasReplayEventOrder,
                            Literal(ev.order, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            event_iri,
                            PKM.hasReplayStepLabel,
                            Literal(f"stage-clear-t{ev.turn}-e{ev.order}"),
                        )
                    )
                    state.current_stat_stages[key] = 0
                    event_sources["stage"][key] = event_iri

        elif ev.kind == "-weather":
            weather_token = ev.fields[0].strip()
            if weather_token == "none":
                state.current_weather = None
                event_sources["weather"]["battle"] = _battle_iri(
                    f"WeatherClear_T{ev.turn}_{ev.order}"
                )
                g.add((event_sources["weather"]["battle"], RDF.type, PKM.Event))
                g.add(
                    (
                        event_sources["weather"]["battle"],
                        PKM.occursInInstantaneous,
                        instant,
                    )
                )
                g.add(
                    (
                        event_sources["weather"]["battle"],
                        PKM.supportedByArtifact,
                        artifact_iri,
                    )
                )
                g.add(
                    (
                        event_sources["weather"]["battle"],
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_sources["weather"]["battle"],
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_sources["weather"]["battle"],
                        PKM.hasReplayStepLabel,
                        Literal(f"weather-clear-t{ev.turn}-e{ev.order}"),
                    )
                )
            else:
                weather_name = WEATHER_TOKEN_TO_NAME.get(weather_token, weather_token)
                weather_iri = _battle_iri(
                    f"Weather_{sanitize_identifier(weather_name)}"
                )
                ensure_named_entity(g, weather_iri, PKM.WeatherCondition, weather_name)

                event_iri = _battle_iri(
                    f"WeatherEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(weather_name)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"weather-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_weather = weather_iri
                event_sources["weather"]["battle"] = event_iri

        elif ev.kind == "-fieldstart":
            terrain_name = TERRAIN_TOKEN_TO_NAME.get(ev.fields[0].strip())
            if terrain_name is not None:
                terrain_iri = _battle_iri(
                    f"Terrain_{sanitize_identifier(terrain_name)}"
                )
                ensure_named_entity(g, terrain_iri, PKM.TerrainCondition, terrain_name)
                event_iri = _battle_iri(
                    f"TerrainEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(terrain_name)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"terrain-t{ev.turn}-e{ev.order}"),
                    )
                )
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
                condition_iri = _battle_iri(
                    f"SideCondition_{sanitize_identifier(condition_name)}"
                )
                ensure_named_entity(g, condition_iri, PKM.SideCondition, condition_name)
                event_iri = _battle_iri(
                    f"SideConditionEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(condition_name)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"sidecond-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_side_conditions.add((side_iri, condition_iri))
                event_sources["side"][(side_iri, condition_iri)] = event_iri

        elif ev.kind == "-sideend":
            side_iri = side_iri_for_token(ev.fields[0], p1_name, p2_name)
            condition_name = SIDE_CONDITION_TOKEN_TO_NAME.get(ev.fields[1].strip())
            if condition_name is not None:
                condition_iri = _battle_iri(
                    f"SideCondition_{sanitize_identifier(condition_name)}"
                )
                state.current_side_conditions.discard((side_iri, condition_iri))

        elif ev.kind == "-terastallize":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            tera_type = ev.fields[1].strip()
            transformation_name = f"Terastallized {tera_type}"
            transformation_iri = _battle_iri(
                f"Transformation_{sanitize_identifier(transformation_name)}"
            )
            ensure_named_entity(
                g, transformation_iri, PKM.TransformationState, transformation_name
            )
            type_iri = _type_iri(tera_type)
            g.add((transformation_iri, PKM.hasTeraType, type_iri))

            state.current_transformations[combatant_iri] = transformation_iri
            event_sources["transformation"][combatant_iri] = _battle_iri(
                f"TransformationEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
            )
            g.add((event_sources["transformation"][combatant_iri], RDF.type, PKM.Event))
            g.add(
                (
                    event_sources["transformation"][combatant_iri],
                    PKM.occursInInstantaneous,
                    instant,
                )
            )
            g.add(
                (
                    event_sources["transformation"][combatant_iri],
                    PKM.supportedByArtifact,
                    artifact_iri,
                )
            )
            g.add(
                (
                    event_sources["transformation"][combatant_iri],
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_sources["transformation"][combatant_iri],
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_sources["transformation"][combatant_iri],
                    PKM.hasReplayStepLabel,
                    Literal(f"tera-t{ev.turn}-e{ev.order}"),
                )
            )

        elif ev.kind == "-singleturn":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            volatile_iri = maybe_volatile_iri(g, ev.fields[1])
            if volatile_iri is not None:
                event_iri = _battle_iri(
                    f"VolatileEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{_iri_token(volatile_iri)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"volatile-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_volatile_conditions.add((combatant_iri, volatile_iri))
                event_sources["volatile"][(combatant_iri, volatile_iri)] = event_iri

        elif ev.kind == "-end":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            volatile_iri = (
                maybe_volatile_iri(g, ev.fields[1]) if len(ev.fields) > 1 else None
            )
            if combatant_iri is not None and volatile_iri is not None:
                state.current_volatile_conditions.discard((combatant_iri, volatile_iri))

        elif ev.kind == "-item":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            item_name = ev.fields[1].strip()
            item_iri = _item_iri(item_name)
            ensure_named_entity(g, item_iri, PKM.Item, item_name)
            event_iri = _battle_iri(
                f"ItemEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
            )
            g.add((event_iri, RDF.type, PKM.Event))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"item-t{ev.turn}-e{ev.order}"),
                )
            )
            state.current_item[combatant_iri] = item_iri
            event_sources["item"][combatant_iri] = event_iri

        elif ev.kind == "-enditem":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                state.current_item.pop(combatant_iri, None)

        elif ev.kind == "-ability":
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            ability_name = ev.fields[1].strip()
            ability_iri = _ability_iri(ability_name)
            ensure_named_entity(g, ability_iri, PKM.Ability, ability_name)
            event_iri = _battle_iri(
                f"AbilityEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
            )
            g.add((event_iri, RDF.type, PKM.Event))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"ability-t{ev.turn}-e{ev.order}"),
                )
            )
            state.current_ability[combatant_iri] = ability_iri
            event_sources["ability"][combatant_iri] = event_iri

        elif ev.kind == "-endability":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                state.current_ability.pop(combatant_iri, None)

        elif ev.kind == "-start":
            # Volatile condition begins (Confusion, Leech Seed, Substitute, Taunt, etc.)
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            volatile_iri = (
                maybe_volatile_iri(g, ev.fields[1]) if len(ev.fields) > 1 else None
            )
            if combatant_iri is not None and volatile_iri is not None:
                event_iri = _battle_iri(
                    f"VolatileEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{_iri_token(volatile_iri)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"volatile-start-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_volatile_conditions.add((combatant_iri, volatile_iri))
                event_sources["volatile"][(combatant_iri, volatile_iri)] = event_iri

        elif ev.kind == "-singlemove":
            # Single-move volatile effect (Destiny Bond, Grudge, Snatch)
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            volatile_iri = (
                maybe_volatile_iri(g, ev.fields[1]) if len(ev.fields) > 1 else None
            )
            if combatant_iri is not None and volatile_iri is not None:
                event_iri = _battle_iri(
                    f"VolatileEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{_iri_token(volatile_iri)}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"singlemove-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_volatile_conditions.add((combatant_iri, volatile_iri))
                event_sources["volatile"][(combatant_iri, volatile_iri)] = event_iri

        elif ev.kind in {"-formechange", "-mega", "-primal", "-burst"}:
            # Temporary forme change / mega evolution / ultra burst
            try:
                combatant_iri = active_combatants_by_slot.get(
                    slot_key(ev.fields[0]),
                    combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
                )
            except (ValueError, IndexError):
                combatant_iri = None
            if combatant_iri is not None:
                if ev.kind == "-formechange" and ev.fields:
                    forme_name = (
                        ev.fields[1].strip().split(",")[0]
                        if len(ev.fields) > 1
                        else "Unknown"
                    )
                    transformation_name = f"Forme: {forme_name}"
                elif ev.kind == "-mega" and len(ev.fields) > 1:
                    transformation_name = f"Mega: {ev.fields[1].strip()}"
                elif ev.kind == "-primal":
                    transformation_name = f"Primal: {actor_display_name(ev.fields[0])}"
                elif ev.kind == "-burst" and len(ev.fields) > 1:
                    transformation_name = f"Ultra Burst: {ev.fields[1].strip()}"
                else:
                    transformation_name = (
                        f"{ev.kind[1:].title()}: {actor_display_name(ev.fields[0])}"
                    )
                transformation_iri = _battle_iri(
                    f"Transformation_{sanitize_identifier(transformation_name)}"
                )
                ensure_named_entity(
                    g, transformation_iri, PKM.TransformationState, transformation_name
                )
                event_iri = _battle_iri(
                    f"FormChangeEvent_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}"
                )
                g.add((event_iri, RDF.type, PKM.Event))
                g.add((event_iri, PKM.occursInInstantaneous, instant))
                g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        event_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"{ev.kind[1:]}-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_transformations[combatant_iri] = transformation_iri
                event_sources["transformation"][combatant_iri] = event_iri

        elif ev.kind == "-setboost":
            # Direct stat stage set (e.g. Belly Drum sets Attack to +6)
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            stat_token = ev.fields[1].strip()
            target_stage = max(-6, min(6, int(ev.fields[2])))
            stat_iri = stat_iri_for_token(stat_token)
            ensure_named_entity(
                g, stat_iri, PKM.Stat, STAT_TOKEN_TO_NAME.get(stat_token, stat_token)
            )
            current_stage = state.current_stat_stages.get((combatant_iri, stat_iri), 0)
            delta = target_stage - current_stage
            event_iri = _battle_iri(
                f"StageChange_T{ev.turn}_{ev.order}_{sanitize_identifier(actor_display_name(ev.fields[0]))}_{sanitize_identifier(stat_token)}_set"
            )
            g.add((event_iri, RDF.type, PKM.StatStageChangeEvent))
            g.add((event_iri, PKM.affectsCombatant, combatant_iri))
            g.add((event_iri, PKM.aboutStat, stat_iri))
            g.add((event_iri, PKM.hasStageDelta, Literal(delta, datatype=XSD.integer)))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"stage-set-t{ev.turn}-e{ev.order}"),
                )
            )
            state.current_stat_stages[(combatant_iri, stat_iri)] = target_stage
            event_sources["stage"][(combatant_iri, stat_iri)] = event_iri

        elif ev.kind == "-swapboost":
            # Swap stat stages between two combatants (Guard Swap, Power Swap, Heart Swap)
            source_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            target_iri = (
                maybe_combatant_from_token(
                    ev.fields[1], active_combatants_by_slot, p1_name, p2_name
                )
                if len(ev.fields) > 1
                else None
            )
            if target_iri is not None:
                stats_token = ev.fields[2].strip() if len(ev.fields) > 2 else None
                stats_to_swap = (
                    [s.strip() for s in stats_token.split(",")]
                    if stats_token
                    else list(STAT_TOKEN_TO_NAME.keys())
                )
                for stat_token in stats_to_swap:
                    if stat_token not in STAT_TOKEN_TO_NAME:
                        continue
                    stat_iri = stat_iri_for_token(stat_token)
                    ensure_named_entity(
                        g, stat_iri, PKM.Stat, STAT_TOKEN_TO_NAME[stat_token]
                    )
                    s_stage = state.current_stat_stages.get((source_iri, stat_iri), 0)
                    t_stage = state.current_stat_stages.get((target_iri, stat_iri), 0)
                    if s_stage == t_stage:
                        continue
                    # Source gets target's old stage
                    if t_stage != 0:
                        state.current_stat_stages[(source_iri, stat_iri)] = t_stage
                    elif (source_iri, stat_iri) in state.current_stat_stages:
                        del state.current_stat_stages[(source_iri, stat_iri)]
                    # Target gets source's old stage
                    if s_stage != 0:
                        state.current_stat_stages[(target_iri, stat_iri)] = s_stage
                    elif (target_iri, stat_iri) in state.current_stat_stages:
                        del state.current_stat_stages[(target_iri, stat_iri)]
                    # Emit one event per stat per affected combatant
                    for affected_iri, stage_delta in [
                        (source_iri, t_stage - s_stage),
                        (target_iri, s_stage - t_stage),
                    ]:
                        ev_iri = _battle_iri(
                            f"StageChange_T{ev.turn}_{ev.order}_{_iri_token(affected_iri)}_{sanitize_identifier(stat_token)}_swap"
                        )
                        g.add((ev_iri, RDF.type, PKM.StatStageChangeEvent))
                        g.add((ev_iri, PKM.affectsCombatant, affected_iri))
                        g.add((ev_iri, PKM.aboutStat, stat_iri))
                        g.add(
                            (
                                ev_iri,
                                PKM.hasStageDelta,
                                Literal(stage_delta, datatype=XSD.integer),
                            )
                        )
                        g.add((ev_iri, PKM.occursInInstantaneous, instant))
                        g.add((ev_iri, PKM.supportedByArtifact, artifact_iri))
                        g.add(
                            (
                                ev_iri,
                                PKM.hasReplayTurnIndex,
                                Literal(ev.turn, datatype=XSD.integer),
                            )
                        )
                        g.add(
                            (
                                ev_iri,
                                PKM.hasReplayEventOrder,
                                Literal(ev.order, datatype=XSD.integer),
                            )
                        )
                        g.add(
                            (
                                ev_iri,
                                PKM.hasReplayStepLabel,
                                Literal(f"stage-swapboost-t{ev.turn}-e{ev.order}"),
                            )
                        )
                        event_sources["stage"][(affected_iri, stat_iri)] = ev_iri

        elif ev.kind == "-invertboost":
            # Negate all stat stages for a combatant (Topsy-Turvy)
            combatant_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            matching_keys = [
                k
                for k in state.current_stat_stages
                if k[0] == combatant_iri and state.current_stat_stages[k] != 0
            ]
            for key in matching_keys:
                _c, stat_iri = key
                prior_stage = state.current_stat_stages[key]
                ev_iri = _battle_iri(
                    f"StageChange_T{ev.turn}_{ev.order}_{_iri_token(combatant_iri)}_{_iri_token(stat_iri)}_invert"
                )
                g.add((ev_iri, RDF.type, PKM.StatStageChangeEvent))
                g.add((ev_iri, PKM.affectsCombatant, combatant_iri))
                g.add((ev_iri, PKM.aboutStat, stat_iri))
                g.add(
                    (
                        ev_iri,
                        PKM.hasStageDelta,
                        Literal(-2 * prior_stage, datatype=XSD.integer),
                    )
                )
                g.add((ev_iri, PKM.occursInInstantaneous, instant))
                g.add((ev_iri, PKM.supportedByArtifact, artifact_iri))
                g.add(
                    (
                        ev_iri,
                        PKM.hasReplayTurnIndex,
                        Literal(ev.turn, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        ev_iri,
                        PKM.hasReplayEventOrder,
                        Literal(ev.order, datatype=XSD.integer),
                    )
                )
                g.add(
                    (
                        ev_iri,
                        PKM.hasReplayStepLabel,
                        Literal(f"stage-invertboost-t{ev.turn}-e{ev.order}"),
                    )
                )
                state.current_stat_stages[key] = -prior_stage
                event_sources["stage"][key] = ev_iri

        elif ev.kind == "-copyboost":
            # Copy stat stages from source to target (Psych Up)
            target_iri = active_combatants_by_slot.get(
                slot_key(ev.fields[0]),
                combatant_iri_for_token(ev.fields[0], p1_name, p2_name),
            )
            source_iri = (
                maybe_combatant_from_token(
                    ev.fields[1], active_combatants_by_slot, p1_name, p2_name
                )
                if len(ev.fields) > 1
                else None
            )
            if source_iri is not None:
                all_stat_iris = {
                    k[1]
                    for k in state.current_stat_stages
                    if k[0] in (source_iri, target_iri)
                }
                for stat_iri in all_stat_iris:
                    source_stage = state.current_stat_stages.get(
                        (source_iri, stat_iri), 0
                    )
                    target_old = state.current_stat_stages.get(
                        (target_iri, stat_iri), 0
                    )
                    delta = source_stage - target_old
                    if delta == 0:
                        continue
                    ev_iri = _battle_iri(
                        f"StageChange_T{ev.turn}_{ev.order}_{_iri_token(target_iri)}_{_iri_token(stat_iri)}_copy"
                    )
                    g.add((ev_iri, RDF.type, PKM.StatStageChangeEvent))
                    g.add((ev_iri, PKM.affectsCombatant, target_iri))
                    g.add((ev_iri, PKM.aboutStat, stat_iri))
                    g.add(
                        (
                            ev_iri,
                            PKM.hasStageDelta,
                            Literal(delta, datatype=XSD.integer),
                        )
                    )
                    g.add((ev_iri, PKM.occursInInstantaneous, instant))
                    g.add((ev_iri, PKM.supportedByArtifact, artifact_iri))
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayTurnIndex,
                            Literal(ev.turn, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayEventOrder,
                            Literal(ev.order, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayStepLabel,
                            Literal(f"stage-copyboost-t{ev.turn}-e{ev.order}"),
                        )
                    )
                    if source_stage != 0:
                        state.current_stat_stages[(target_iri, stat_iri)] = source_stage
                    elif (target_iri, stat_iri) in state.current_stat_stages:
                        del state.current_stat_stages[(target_iri, stat_iri)]
                    event_sources["stage"][(target_iri, stat_iri)] = ev_iri

        elif ev.kind in {"-clearpositiveboost", "-clearnegativeboost"}:
            # Partial boost clearing
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                positive = ev.kind == "-clearpositiveboost"
                matching_keys = [
                    k
                    for k in state.current_stat_stages
                    if k[0] == combatant_iri
                    and (
                        state.current_stat_stages[k] > 0
                        if positive
                        else state.current_stat_stages[k] < 0
                    )
                ]
                for key in matching_keys:
                    _c, stat_iri = key
                    prior_stage = state.current_stat_stages[key]
                    ev_iri = _battle_iri(
                        f"StageChange_T{ev.turn}_{ev.order}_{_iri_token(combatant_iri)}_{_iri_token(stat_iri)}_partialclear"
                    )
                    g.add((ev_iri, RDF.type, PKM.StatStageChangeEvent))
                    g.add((ev_iri, PKM.affectsCombatant, combatant_iri))
                    g.add((ev_iri, PKM.aboutStat, stat_iri))
                    g.add(
                        (
                            ev_iri,
                            PKM.hasStageDelta,
                            Literal(-prior_stage, datatype=XSD.integer),
                        )
                    )
                    g.add((ev_iri, PKM.occursInInstantaneous, instant))
                    g.add((ev_iri, PKM.supportedByArtifact, artifact_iri))
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayTurnIndex,
                            Literal(ev.turn, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayEventOrder,
                            Literal(ev.order, datatype=XSD.integer),
                        )
                    )
                    g.add(
                        (
                            ev_iri,
                            PKM.hasReplayStepLabel,
                            Literal(f"stage-partial-clear-t{ev.turn}-e{ev.order}"),
                        )
                    )
                    state.current_stat_stages[key] = 0
                    event_sources["stage"][key] = ev_iri

        elif ev.kind == "-cureteam":
            # Aromatherapy / Heal Bell: cure status on all Pokémon on one side
            try:
                player_id = parse_player_slot(ev.fields[0])[0] if ev.fields else None
            except ValueError:
                player_id = None
            if player_id is not None:
                side_participants = {
                    _battle_iri(iri)
                    for iri, info in participants.items()
                    if info["player_id"] == player_id
                }
                for c_iri in list(state.current_status.keys()):
                    if c_iri in side_participants:
                        state.current_status.pop(c_iri, None)

        elif ev.kind in {"win", "tie"}:
            # Battle result
            outcome = ev.fields[0].strip() if ev.kind == "win" and ev.fields else "tie"
            g.set(
                (
                    battle_iri,
                    PKM.hasBattleOutcome,
                    Literal(outcome, datatype=XSD.string),
                )
            )

        elif ev.kind == "-notarget":
            # Move had no valid target (target fainted before resolution)
            if current_action is not None:
                for target_iri in list(current_action.candidate_targets):
                    if (
                        target_iri not in current_action.resolved_targets
                        and target_iri not in current_action.failed_targets
                    ):
                        emit_target_resolution(
                            g,
                            current_action.action_iri,
                            target_iri,
                            instant,
                            "failed",
                            artifact_iri,
                            ev.turn,
                            ev.order,
                        )
                        current_action.failed_targets.add(target_iri)

        elif ev.kind == "-block":
            # Effect blocked (e.g. ability negates a move)
            combatant_iri = (
                maybe_combatant_from_token(
                    ev.fields[0], active_combatants_by_slot, p1_name, p2_name
                )
                if ev.fields
                else None
            )
            if combatant_iri is not None and current_action is not None:
                mark_redirection(current_action, combatant_iri)

        elif ev.kind == "-crit":
            # Critical hit — update the current target resolution if possible
            combatant_iri = (
                maybe_combatant_from_token(
                    ev.fields[0], active_combatants_by_slot, p1_name, p2_name
                )
                if ev.fields
                else None
            )
            if combatant_iri is not None and current_action is not None:
                mark_redirection(current_action, combatant_iri)

        elif ev.kind in {
            "-prepare",
            "-hitcount",
            "-zpower",
            "-zbroken",
            "-mustrecharge",
        }:
            # Minor annotation events — emit an event node for provenance
            tag_label = ev.kind.lstrip("-")
            event_iri = _battle_iri(
                f"Event_{sanitize_identifier(tag_label)}_T{ev.turn}_{ev.order}"
            )
            g.add((event_iri, RDF.type, PKM.Event))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"{tag_label}-t{ev.turn}-e{ev.order}"),
                )
            )

        elif ev.kind == "-fail":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                try:
                    action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                except ValueError:
                    action_iri = None
                if action_iri is not None:
                    emit_target_resolution(
                        g,
                        action_iri,
                        combatant_iri,
                        instant,
                        "failed",
                        artifact_iri,
                        ev.turn,
                        ev.order,
                    )
                    if (
                        current_action is not None
                        and action_iri == current_action.action_iri
                    ):
                        current_action.failed_targets.add(combatant_iri)

        elif ev.kind == "-miss":
            if len(ev.fields) >= 2:
                source_iri = maybe_combatant_from_token(
                    ev.fields[0], active_combatants_by_slot, p1_name, p2_name
                )
                target_iri = maybe_combatant_from_token(
                    ev.fields[1], active_combatants_by_slot, p1_name, p2_name
                )
                if source_iri is not None and target_iri is not None:
                    try:
                        action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                    except ValueError:
                        action_iri = None
                    if action_iri is not None:
                        emit_target_resolution(
                            g,
                            action_iri,
                            target_iri,
                            instant,
                            "failed",
                            artifact_iri,
                            ev.turn,
                            ev.order,
                        )
                        if (
                            current_action is not None
                            and action_iri == current_action.action_iri
                        ):
                            current_action.failed_targets.add(target_iri)

        elif ev.kind == "cant":
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None:
                try:
                    action_iri = latest_action_by_slot.get(slot_key(ev.fields[0]))
                except ValueError:
                    action_iri = None
                if action_iri is not None:
                    emit_target_resolution(
                        g,
                        action_iri,
                        combatant_iri,
                        instant,
                        "aborted",
                        artifact_iri,
                        ev.turn,
                        ev.order,
                    )
                    if (
                        current_action is not None
                        and action_iri == current_action.action_iri
                    ):
                        current_action.aborted_targets.add(combatant_iri)

        elif ev.kind in {"-supereffective", "-resisted", "-immune", "-activate"}:
            combatant_iri = maybe_combatant_from_token(
                ev.fields[0], active_combatants_by_slot, p1_name, p2_name
            )
            if combatant_iri is not None and current_action is not None:
                mark_redirection(current_action, combatant_iri)

        elif ev.kind == "faint":
            fainted_token = ev.fields[0]
            fainted_iri = active_combatants_by_slot.get(
                slot_key(fainted_token),
                combatant_iri_for_token(fainted_token, p1_name, p2_name),
            )
            fainted_name = actor_display_name(fainted_token)
            event_iri = _battle_iri(
                f"Faint_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"
            )
            g.add((event_iri, RDF.type, PKM.FaintEvent))
            g.add((event_iri, PKM.affectsCombatant, fainted_iri))
            g.add((event_iri, PKM.occursInInstantaneous, instant))
            g.add(
                (
                    event_iri,
                    PKM.hasReplayTurnIndex,
                    Literal(ev.turn, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayEventOrder,
                    Literal(ev.order, datatype=XSD.integer),
                )
            )
            g.add(
                (
                    event_iri,
                    PKM.hasReplayStepLabel,
                    Literal(f"faint-t{ev.turn}-e{ev.order}"),
                )
            )
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))
            if should_attribute_minor_event_to_action(current_action, ev.fields[1:]):
                mark_redirection(current_action, fainted_iri)
            if should_attribute_minor_event_to_action(current_action, ev.fields[1:]):
                g.add((event_iri, PKM.causedByAction, current_action.action_iri))
                if fainted_iri != current_action.actor_iri:
                    current_action.hit_counts_by_target[fainted_iri] = (
                        current_action.hit_counts_by_target.get(fainted_iri, 0) + 1
                    )
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
            battle_iri,
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
            _battle_iri(f"I_{len(events) - 1}"),
            artifact_iri,
            events[-1].turn,
            events[-1].order,
        )

    return g


def build_ttl(payload: dict) -> str:
    return build_graph(payload).serialize(format="turtle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "replay_json", type=Path, help="Path to Pokémon Showdown replay JSON"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <replay_json stem>-slice.ttl",
    )
    args = parser.parse_args()

    payload = json.loads(args.replay_json.read_text(encoding="utf-8"))
    output_path = args.output or args.replay_json.with_name(
        f"{args.replay_json.stem}-slice.ttl"
    )
    serialize_turtle_to_path(build_graph(payload), output_path)
    print(output_path)


if __name__ == "__main__":
    main()
