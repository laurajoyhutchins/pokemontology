#!/usr/bin/env python3
"""Shared parsing utilities for Pokémon Showdown replay JSON files.

This module provides the canonical types and functions for extracting typed
events from a replay log, used by replay_to_ttl_builder and
summarize_showdown_replay.

Note: parse_showdown_replay.py has a different parse_log with different
semantics (all event types, returns list[dict]) and is intentionally not
merged here.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable


PKM_PREFIX = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#"
SUPPORTED_EVENT_TAGS = {
    "switch",
    "drag",
    "replace",
    "detailschange",
    "move",
    "faint",
    "-damage",
    "-heal",
    "-status",
    "-curestatus",
    "-boost",
    "-unboost",
    "-fail",
    "-miss",
    "-weather",
    "-fieldstart",
    "-sidestart",
    "-terastallize",
    "-singleturn",
    "cant",
}


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


def parse_side_token(raw: str) -> str:
    """Return 'p1' or 'p2' from strings like 'p1: Alice'."""
    match = re.match(r"^(p[12]):", raw.strip())
    if not match:
        raise ValueError(f"Could not parse side token from {raw!r}")
    return match.group(1)


@dataclass
class ReplayEvent:
    turn: int
    order: int
    kind: str
    fields: list[str]
    raw: str


def parse_log(log: str) -> list[ReplayEvent]:
    """Parse replay log lines for the replay-backed event/state slice."""
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
        if tag in SUPPORTED_EVENT_TAGS:
            events.append(ReplayEvent(turn=turn, order=order, kind=tag, fields=parts[2:], raw=raw_line))
            order += 1

    return events


def parse_replay_payload(payload: dict) -> tuple[str, str, str, str, str]:
    """Return (replay_id, fmt, source_url, p1_name, p2_name)."""
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


def discover_participants(
    events: Iterable[ReplayEvent], p1_name: str, p2_name: str
) -> OrderedDict[str, dict]:
    """Build an ordered mapping of IRI → participant info from switch events.

    Raises ValueError if two distinct species names produce the same IRI
    (silent IRI collision).
    """
    participants: OrderedDict[str, dict] = OrderedDict()

    for ev in events:
        if ev.kind != "switch":
            continue
        slot_token = ev.fields[0]
        species_token = ev.fields[1]
        player_id, _slot = parse_player_slot(slot_token)
        species_compact = compact_species_name(species_token)
        trainer = p1_name if player_id == "p1" else p2_name
        iri = f"Combatant_{sanitize_identifier(trainer)}_{species_compact}"
        species_raw = species_token.split(",")[0].strip()
        label = f"{trainer} {species_raw}"

        if iri in participants:
            existing_species = participants[iri]["species_raw"]
            if existing_species != species_raw:
                raise ValueError(
                    f"IRI collision in participants: '{iri}' maps to both "
                    f"'{existing_species}' and '{species_raw}'"
                )
        else:
            participants[iri] = {
                "player_id": player_id,
                "trainer": trainer,
                "species_raw": species_raw,
                "label": label,
            }

    return participants


def discover_moves(events: Iterable[ReplayEvent]) -> OrderedDict[str, str]:
    """Build an ordered mapping of IRI → move name from move events.

    Raises ValueError if two distinct move names produce the same IRI
    (silent IRI collision).
    """
    moves: OrderedDict[str, str] = OrderedDict()
    for ev in events:
        if ev.kind != "move":
            continue
        move_name = ev.fields[1].strip()
        iri = f"Move{sanitize_identifier(move_name)}"
        if iri in moves:
            if moves[iri] != move_name:
                raise ValueError(
                    f"IRI collision in moves: '{iri}' maps to both "
                    f"'{moves[iri]}' and '{move_name}'"
                )
        else:
            moves[iri] = move_name
    return moves
