#!/usr/bin/env python3
"""Assemble the consumer ontology file from modular Turtle source fragments."""
from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "ontology" / "modules"
OUTPUT = REPO / "build" / "ontology.ttl"

MODULE_ORDER = [
    "00-header.ttl",
    "10-core.ttl",
    "20-ruleset-mechanics.ttl",
    "30-save-state.ttl",
    "40-battle.ttl",
    "45-battle-resolution.ttl",
    "50-instantaneous-state.ttl",
    "60-actions-events.ttl",
    "70-provenance.ttl",
    "80-materialized-state.ttl",
]


def main() -> None:
    missing = [name for name in MODULE_ORDER if not (MODULES_DIR / name).exists()]
    if missing:
        formatted = ", ".join(missing)
        raise SystemExit(f"missing ontology module(s): {formatted}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for name in MODULE_ORDER:
        path = MODULES_DIR / name
        text = path.read_text(encoding="utf-8").strip()
        chunks.append(text)

    OUTPUT.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
