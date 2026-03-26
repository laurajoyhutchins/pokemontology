#!/usr/bin/env python3
"""Extract Pokémon and move entities from raw replay JSONs to build a PokeAPI seed config.

Usage:
    python scripts/extract-replay-entities.py [--raw-dir PATH] [--output PATH]

Reads all replay JSON files in --raw-dir (default: data/replays/raw/showdown/),
uses replay_parser to extract species and move names, normalizes them to PokeAPI
identifiers, and writes a seed-config JSON to --output
(default: data/pokeapi/seed-config.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path so pokemontology package is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pokemontology.replay.replay_parser import (  # noqa: E402
    discover_moves,
    discover_participants,
    parse_log,
    parse_replay_payload,
    pokeapi_species_id,
)


def pokeapi_move_id(move_name: str) -> str:
    """Normalize a Showdown move display name to a PokeAPI move identifier.

    Examples: "Shadow Ball" → "shadow-ball", "U-turn" → "u-turn",
              "Trick Room" → "trick-room"
    """
    import re

    text = move_name.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def extract_entities_from_replay(payload: dict) -> tuple[set[str], set[str]]:
    """Return (pokemon_ids, move_ids) extracted from a single replay payload."""
    log = payload.get("log", "")
    if not isinstance(log, str) or not log.strip():
        return set(), set()

    try:
        _replay_id, _fmt, _url, p1_name, p2_name = parse_replay_payload(payload)
    except (ValueError, KeyError):
        players = payload.get("players") or ["p1", "p2"]
        p1_name = players[0] if len(players) > 0 else "p1"
        p2_name = players[1] if len(players) > 1 else "p2"

    events = parse_log(log)
    participants = discover_participants(events, p1_name, p2_name)
    moves = discover_moves(events)

    pokemon_ids: set[str] = set()
    for info in participants.values():
        species_raw = info["species_raw"]
        pokemon_ids.add(pokeapi_species_id(species_raw))

    move_ids: set[str] = set()
    for move_name in moves.values():
        move_ids.add(pokeapi_move_id(move_name))

    return pokemon_ids, move_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=REPO_ROOT / "data" / "replays" / "raw" / "showdown",
        help="Directory containing raw replay JSON files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "pokeapi" / "seed-config.json",
        help="Output path for seed-config.json.",
    )
    args = parser.parse_args()

    raw_dir: Path = args.raw_dir
    output_path: Path = args.output

    replay_files = sorted(raw_dir.glob("*.json"))
    if not replay_files:
        print(f"No replay JSON files found in {raw_dir}", file=sys.stderr)
        sys.exit(1)

    all_pokemon: set[str] = set()
    all_moves: set[str] = set()
    skipped = 0

    for replay_file in replay_files:
        try:
            payload = json.loads(replay_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: skipping {replay_file.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        try:
            pokemon_ids, move_ids = extract_entities_from_replay(payload)
        except Exception as exc:
            print(f"Warning: skipping {replay_file.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        all_pokemon.update(pokemon_ids)
        all_moves.update(move_ids)

    seed_config = {
        "resources": {
            "move": sorted(all_moves),
            "pokemon": sorted(all_pokemon),
        }
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(seed_config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(output_path),
                "replay_files": len(replay_files),
                "skipped": skipped,
                "pokemon_count": len(all_pokemon),
                "move_count": len(all_moves),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
