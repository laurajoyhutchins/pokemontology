#!/usr/bin/env python3
"""Extract a compact summary from a Showdown replay JSON file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay_json", type=Path)
    args = parser.parse_args()

    replay = json.loads(args.replay_json.read_text(encoding="utf-8"))
    log = replay["log"].splitlines()

    summary = {
        "id": replay.get("id"),
        "format": replay.get("format"),
        "players": replay.get("players", []),
        "turns": [],
        "winner": None,
    }

    current_turn = None
    for line in log:
        if line.startswith("|turn|"):
            current_turn = int(line.split("|")[2])
            summary["turns"].append({"turn": current_turn, "moves": [], "faints": []})
        elif line.startswith("|move|") and current_turn is not None:
            parts = line.split("|")
            summary["turns"][-1]["moves"].append({
                "actor": parts[2],
                "move": parts[3],
                "target": parts[4] if len(parts) > 4 else None,
            })
        elif line.startswith("|faint|") and current_turn is not None:
            parts = line.split("|")
            summary["turns"][-1]["faints"].append(parts[2])
        elif line.startswith("|win|"):
            summary["winner"] = line.split("|")[2]

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
