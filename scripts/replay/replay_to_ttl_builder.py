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
    sanitize_identifier,
)

PKM = Namespace(PKM_PREFIX)
SITE_BASE = "https://laurajoyhutchins.github.io/pokemontology"


def build_graph(payload: dict) -> Graph:
    g = Graph()
    g.bind("pkm", PKM)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)

    replay_id, fmt, source_url, p1_name, p2_name = parse_replay_payload(payload)
    events = parse_log(payload["log"])
    participants = discover_participants(events, p1_name, p2_name)
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
    for idx, ev in enumerate(events):
        instant = PKM[f"I_{idx}"]

        if ev.kind == "move":
            actor_token = ev.fields[0]
            move_name = ev.fields[1].strip()
            player_id, _slot = parse_player_slot(actor_token)
            actor_name = actor_display_name(actor_token)
            trainer = p1_name if player_id == "p1" else p2_name
            actor_iri = PKM[f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(actor_name)}"]
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

            if idx + 1 < len(events):
                transition = PKM[f"Transition_{transition_count}"]
                next_instant = PKM[f"I_{idx + 1}"]
                g.add((transition, RDF.type, PKM.StateTransition))
                g.add((transition, PKM.hasInputState, instant))
                g.add((transition, PKM.hasOutputState, next_instant))
                g.add((transition, PKM.triggeredBy, action_iri))
                transition_count += 1

        elif ev.kind == "faint":
            fainted_token = ev.fields[0]
            player_id, _slot = parse_player_slot(fainted_token)
            trainer = p1_name if player_id == "p1" else p2_name
            fainted_name = actor_display_name(fainted_token)
            fainted_iri = PKM[
                f"Combatant_{sanitize_identifier(trainer)}_{compact_species_name(fainted_name)}"
            ]
            event_iri = PKM[f"Faint_T{ev.turn}_{ev.order}_{sanitize_identifier(fainted_name)}"]

            g.add((event_iri, RDF.type, PKM.FaintEvent))
            g.add((event_iri, PKM.aboutCombatant, fainted_iri))
            g.add((event_iri, PKM.occursAtInstantaneous, instant))
            g.add((event_iri, PKM.hasReplayTurnIndex, Literal(ev.turn, datatype=XSD.integer)))
            g.add((event_iri, PKM.hasReplayEventOrder, Literal(ev.order, datatype=XSD.integer)))
            g.add((event_iri, PKM.supportedByArtifact, artifact_iri))

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
