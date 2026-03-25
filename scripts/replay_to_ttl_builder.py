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
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PKM_PREFIX = "http://example.org/pokemon-ontology#"


def sanitize_identifier(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "Unnamed"
    if text[0].isdigit():
        text = f"N_{text}"
    return text


def compact_species_name(raw: str) -> str:
    """Normalize battle log Pokémon names to a stable compact label."""
    text = raw.strip()
    text = re.sub(r",\s*L\d+.*$", "", text)
    text = text.replace("p1a: ", "").replace("p1b: ", "")
    text = text.replace("p2a: ", "").replace("p2b: ", "")
    text = text.replace("*", "")
    text = text.replace(" ", "")
    text = text.replace(".", "")
    text = text.replace("♀", "F").replace("♂", "M")
    return sanitize_identifier(text)


def actor_display_name(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^p[12][ab]:\s*", "", text)
    return text


def parse_player_slot(raw: str) -> tuple[str, str]:
    """Return ('p1'|'p2', 'a'|'b') from strings like 'p1a: Deoxys'."""
    match = re.match(r"^(p[12])([ab]):", raw.strip())
    if not match:
        raise ValueError(f"Could not parse player slot from {raw!r}")
    return match.group(1), match.group(2)


@dataclass
class ReplayEvent:
    turn: int
    order: int
    kind: str
    fields: list[str]
    raw: str


def parse_log(log: str) -> list[ReplayEvent]:
    turn = 0
    order = 0
    events: list[ReplayEvent] = []

    for raw_line in log.splitlines():
        if not raw_line.startswith("|"):
            continue
        parts = raw_line.split("|")
        tag = parts[1] if len(parts) > 1 else ""
        if tag == "turn":
            turn = int(parts[2])
            order = 0
            continue
        if turn == 0:
            continue
        if tag in {"switch", "move", "faint"}:
            events.append(ReplayEvent(turn=turn, order=order, kind=tag, fields=parts[2:], raw=raw_line))
            order += 1

    return events


def parse_replay_payload(payload: dict) -> tuple[str, str, str, str]:
    replay_id = payload.get("id", "unknown-replay")
    fmt = payload.get("format", "Unknown Format")
    source_url = payload.get("source_url")
    if not source_url:
        password = payload.get("password")
        if password:
            source_url = f"https://replay.pokemonshowdown.com/{replay_id}-{password}.json"
        else:
            source_url = f"https://replay.pokemonshowdown.com/{replay_id}.json"
    players = payload.get("players") or ["p1", "p2"]
    if len(players) < 2:
        raise ValueError("Replay payload does not include two players.")
    return replay_id, fmt, source_url, players[0], players[1]


def discover_participants(events: Iterable[ReplayEvent], p1_name: str, p2_name: str) -> OrderedDict[str, dict]:
    participants: OrderedDict[str, dict] = OrderedDict()

    for ev in events:
        if ev.kind == "switch":
            slot_token = ev.fields[0]
            species_token = ev.fields[1]
            player_id, _slot = parse_player_slot(slot_token)
            species_compact = compact_species_name(species_token)
            trainer = p1_name if player_id == "p1" else p2_name
            iri = f"Combatant_{sanitize_identifier(trainer)}_{species_compact}"
            label = f"{trainer} {species_token.split(',')[0].strip()}"
            participants.setdefault(
                iri,
                {
                    "player_id": player_id,
                    "trainer": trainer,
                    "species_raw": species_token.split(",")[0].strip(),
                    "label": label,
                },
            )

    return participants


def discover_moves(events: Iterable[ReplayEvent]) -> OrderedDict[str, str]:
    moves: OrderedDict[str, str] = OrderedDict()
    for ev in events:
        if ev.kind != "move":
            continue
        move_name = ev.fields[1].strip()
        iri = f"Move{sanitize_identifier(move_name)}"
        moves.setdefault(iri, move_name)
    return moves


def build_ttl(payload: dict) -> str:
    replay_id, fmt, source_url, p1_name, p2_name = parse_replay_payload(payload)
    events = parse_log(payload["log"])
    participants = discover_participants(events, p1_name, p2_name)
    moves = discover_moves(events)

    battle_slug = sanitize_identifier(replay_id)
    artifact_iri = f"ReplayArtifact_{battle_slug}"
    battle_iri = f"Battle_{battle_slug}"
    side_p1_iri = f"Side_{sanitize_identifier(p1_name)}"
    side_p2_iri = f"Side_{sanitize_identifier(p2_name)}"
    ruleset_iri = f"Ruleset_{sanitize_identifier(fmt)}"

    lines: list[str] = []
    add = lines.append

    add('@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .')
    add('@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .')
    add('@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .')
    add(f'@prefix pkm:  <{PKM_PREFIX}> .')
    add("")
    add(f"<http://example.org/replay-slice/{battle_slug}>")
    add(f'    rdfs:label "Replay-backed slice for {replay_id}" ;')
    add('    rdfs:comment "Auto-generated minimal replay-backed TTL slice from a Pokémon Showdown replay JSON. This file captures observable actions and faints, not a dense reconstructed battle state." .')
    add("")
    add(f"pkm:{artifact_iri}")
    add("    a pkm:ReplayArtifact ;")
    add(f'    pkm:hasReplayIdentifier "{replay_id}" ;')
    add(f'    pkm:hasSourceURL "{source_url}"^^xsd:anyURI ;')
    add(f'    pkm:hasName "{fmt}: {p1_name} vs. {p2_name}" ;')
    add('    rdfs:comment "Source replay artifact." .')
    add("")
    add(f'pkm:{ruleset_iri} a pkm:Ruleset ; pkm:hasName "{fmt}" .')
    add("")
    add(f"pkm:{battle_iri}")
    add("    a pkm:Battle ;")
    add(f"    pkm:operatesUnderRuleset pkm:{ruleset_iri} ;")
    add(f"    pkm:supportedByArtifact pkm:{artifact_iri} ;")
    add('    rdfs:comment "Battle container auto-generated from replay log." .')
    add("")
    add(f"pkm:{side_p1_iri} a pkm:BattleSide ; pkm:hasSideIndex 0 ; pkm:sideOccursInBattle pkm:{battle_iri} .")
    add(f"pkm:{side_p2_iri} a pkm:BattleSide ; pkm:hasSideIndex 1 ; pkm:sideOccursInBattle pkm:{battle_iri} .")
    add("")

    add("# Observed battle participants")
    for iri, info in participants.items():
        side_iri = side_p1_iri if info["player_id"] == "p1" else side_p2_iri
        add(f"pkm:{iri} a pkm:BattleParticipant, pkm:TransientCombatant ;")
        add(f"    pkm:participatesInBattle pkm:{battle_iri} ;")
        add(f"    pkm:onSide pkm:{side_iri} ;")
        add(f'    pkm:hasCombatantLabel "{info["label"]}" ;')
        add("    pkm:isActive true .")
        add("")

    add("# Observed move vocabulary")
    for move_iri, move_name in moves.items():
        add(f'pkm:{move_iri} a pkm:Move ; pkm:hasName "{move_name}" .')
    add("")

    add("# Instantaneous checkpoints")
    previous_i = None
    for idx, ev in enumerate(events):
        instant_iri = f"I_{idx}"
        add(f"pkm:{instant_iri} a pkm:Instantaneous ;")
        add("    pkm:hasProjectionProfile pkm:ProjectionProfile_ReplayObservedOnly ;")
        add(f"    pkm:occursInBattle pkm:{battle_iri} ;")
        if previous_i is not None:
            add(f"    pkm:hasPreviousInstantaneous pkm:{previous_i} ;")
        add(f"    pkm:hasTurnIndex {ev.turn} ;")
        add(f"    pkm:hasStepIndex {ev.order} ;")
        add(f"    pkm:hasReplayTurnIndex {ev.turn} ;")
        add(f"    pkm:hasReplayEventOrder {ev.order} ;")
        add(f'    pkm:hasReplayStepLabel "{ev.kind}-t{ev.turn}-e{ev.order}" ;')
        add(f"    pkm:supportedByArtifact pkm:{artifact_iri} .")
        add("")
        previous_i = instant_iri

    add("# Action and event layer")
    transition_count = 0
    faint_count = 0
    for idx, ev in enumerate(events):
        instant_iri = f"I_{idx}"

        if ev.kind == "move":
            actor_token = ev.fields[0]
            move_name = ev.fields[1].strip()
            player_id, _slot = parse_player_slot(actor_token)
            actor_name = actor_display_name(actor_token)
            trainer = p1_name if player_id == "p1" else p2_name
            actor_iri = f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(actor_name)}"
            move_iri = f"Move{sanitize_identifier(move_name)}"
            action_iri = f"Action_T{ev.turn}_{ev.order}_{sanitize_identifier(move_name)}_{sanitize_identifier(actor_name)}"

            add(f"pkm:{action_iri} a pkm:MoveUseAction ;")
            add(f"    pkm:actor pkm:{actor_iri} ;")
            add(f"    pkm:usesMove pkm:{move_iri} ;")
            add(f"    pkm:declaredInInstantaneous pkm:{instant_iri} ;")
            add(f"    pkm:initiatedInInstantaneous pkm:{instant_iri} ;")
            add("    pkm:hasPriorityBracket 0 ;")
            add(f"    pkm:hasResolutionIndex {ev.order} ;")
            add(f"    pkm:hasReplayTurnIndex {ev.turn} ;")
            add(f"    pkm:hasReplayEventOrder {ev.order} ;")
            add(f'    pkm:hasReplayStepLabel "move-t{ev.turn}-e{ev.order}" ;')
            add(f"    pkm:supportedByArtifact pkm:{artifact_iri} .")
            add("")

            if idx + 1 < len(events):
                transition_iri = f"Transition_{transition_count}"
                next_instant = f"I_{idx + 1}"
                add(f"pkm:{transition_iri} a pkm:StateTransition ;")
                add(f"    pkm:hasInputState pkm:{instant_iri} ;")
                add(f"    pkm:hasOutputState pkm:{next_instant} ;")
                add(f"    pkm:triggeredBy pkm:{action_iri} .")
                add("")
                transition_count += 1

        elif ev.kind == "faint":
            fainted_token = ev.fields[0]
            player_id, _slot = parse_player_slot(fainted_token)
            trainer = p1_name if player_id == "p1" else p2_name
            fainted_name = actor_display_name(fainted_token)
            fainted_iri = f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(fainted_name)}"
            event_iri = f"Faint_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"

            add(f"pkm:{event_iri} a pkm:FaintEvent ;")
            add(f"    pkm:aboutCombatant pkm:{fainted_iri} ;")
            add(f"    pkm:occursAtInstantaneous pkm:{instant_iri} ;")
            add(f"    pkm:hasReplayTurnIndex {ev.turn} ;")
            add(f"    pkm:hasReplayEventOrder {ev.order} ;")
            add(f"    pkm:supportedByArtifact pkm:{artifact_iri} .")
            add("")
            faint_count += 1

    add("")
    add("# Summary")
    add(f'# Observed participants: {len(participants)}')
    add(f'# Observed moves: {len(moves)}')
    add(f'# Checkpoints: {len(events)}')
    add(f'# Faint events: {faint_count}')

    return "\n".join(lines) + "\n"


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
