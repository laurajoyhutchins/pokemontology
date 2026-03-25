#!/usr/bin/env python3
"""Extract a compact summary from a Showdown replay JSON file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from replay_parser import parse_log, parse_replay_payload


def _get_winner(log: str) -> str | None:
    for line in log.splitlines():
        if line.startswith("|win|"):
            return line.split("|")[2]
    return None


def summarize(payload: dict) -> dict:
    replay_id, fmt, _, p1, p2 = parse_replay_payload(payload)
    events = parse_log(payload["log"])

    turns_by_num: dict[int, dict] = {}
    for ev in events:
        if ev.turn not in turns_by_num:
            turns_by_num[ev.turn] = {"turn": ev.turn, "moves": [], "faints": []}
        turn_data = turns_by_num[ev.turn]
        if ev.kind == "move":
            turn_data["moves"].append({
                "actor": ev.fields[0],
                "move": ev.fields[1],
                "target": ev.fields[2] if len(ev.fields) > 2 else None,
            })
        elif ev.kind == "faint":
            turn_data["faints"].append(ev.fields[0])

    return {
        "id": replay_id,
        "format": fmt,
        "players": payload.get("players", []),
        "turns": list(turns_by_num.values()),
        "winner": _get_winner(payload["log"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay_json", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.replay_json.read_text(encoding="utf-8"))
    print(json.dumps(summarize(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
