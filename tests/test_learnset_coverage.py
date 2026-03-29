"""Regression test: cached move learned_by_pokemon references must be covered by the seed config.

This test guards against the silent gap described in issue #11, where Pokemon names
appear in PokeAPI move learned_by_pokemon lists but have no corresponding species or
variant node in the published entity index because they were never added to the seed config.

The test is skipped when no cached move data exists locally (i.e. data/pokeapi/raw/move/
has not been populated by a prior `pokemontology pokeapi fetch` run).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import REPO


RAW_MOVE_DIR = REPO / "data" / "pokeapi" / "raw" / "move"
SEED_CONFIG_PATH = REPO / "data" / "pokeapi" / "seed-config.json"

# Pokemon names that appear in learned_by_pokemon but are intentionally omitted
# from the seed config (e.g. cosmetic-only forms with no distinct mechanics).
# Extend this allowlist only for genuinely intentional exclusions; do not use it
# to paper over coverage gaps for Pokemon that should be tracked.
INTENTIONAL_EXCLUSIONS: frozenset[str] = frozenset(
    {
        # placeholder — extend here with documented rationale when needed
    }
)


def _load_seed_pokemon() -> frozenset[str]:
    payload = json.loads(SEED_CONFIG_PATH.read_text(encoding="utf-8"))
    return frozenset(payload.get("resources", {}).get("pokemon", []))


@pytest.mark.skipif(
    not RAW_MOVE_DIR.exists(),
    reason=(
        "No cached move data at data/pokeapi/raw/move/; "
        "run `.venv/bin/python -m pokemontology pokeapi fetch` first"
    ),
)
def test_learned_by_pokemon_covered_by_seed_config() -> None:
    """All learned_by_pokemon references in cached move JSONs must be in the seed config.

    If this test fails, either:
    - Add the missing Pokemon to data/pokeapi/seed-config.json, or
    - Add them to INTENTIONAL_EXCLUSIONS with a documented reason.
    """
    covered = _load_seed_pokemon()

    missing: dict[str, list[str]] = {}
    for move_path in sorted(RAW_MOVE_DIR.glob("*.json")):
        payload = json.loads(move_path.read_text(encoding="utf-8"))
        move_name = payload.get("name", move_path.stem)
        for entry in payload.get("learned_by_pokemon", []):
            poke_name = entry.get("name", "")
            if poke_name and poke_name not in covered and poke_name not in INTENTIONAL_EXCLUSIONS:
                missing.setdefault(poke_name, []).append(move_name)

    if missing:
        lines = [
            f"{len(missing)} learned_by_pokemon name(s) not covered by seed config "
            f"(add to data/pokeapi/seed-config.json or INTENTIONAL_EXCLUSIONS):",
        ]
        for poke_name in sorted(missing)[:30]:
            example_moves = ", ".join(missing[poke_name][:3])
            lines.append(f"  {poke_name!r}  (e.g. via: {example_moves})")
        if len(missing) > 30:
            lines.append(f"  ... and {len(missing) - 30} more")
        raise AssertionError("\n".join(lines))
