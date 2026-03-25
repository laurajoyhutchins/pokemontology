#!/usr/bin/env python3
"""Parse a Pokémon Showdown replay JSON file into a simple turn/event stream."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_log(log: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current_turn = 0
    current_events: list[dict[str, Any]] = []

    for raw_line in log.splitlines():
        if not raw_line:
            continue
        if not raw_line.startswith("|"):
            current_events.append({"type": "raw_text", "text": raw_line})
            continue

        parts = raw_line.split("|")
        tag = parts[1] if len(parts) > 1 else ""

        if tag == "turn":
            if current_events or current_turn != 0:
                turns.append({"turn": current_turn, "events": current_events})
            current_turn = int(parts[2])
            current_events = []
            continue

        event: dict[str, Any] = {"type": tag, "fields": parts[2:]}
        current_events.append(event)

    if current_events:
        turns.append({"turn": current_turn, "events": current_events})

    return turns


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay_json", type=Path, help="Path to Showdown replay JSON")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print parsed turns as indented JSON",
    )
    args = parser.parse_args()

    replay = json.loads(args.replay_json.read_text(encoding="utf-8"))
    turns = parse_log(replay["log"])

    output = {
        "id": replay.get("id"),
        "format": replay.get("format"),
        "players": replay.get("players", []),
        "turns": turns,
    }

    if args.pretty:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
