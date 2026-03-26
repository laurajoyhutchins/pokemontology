#!/usr/bin/env python3
"""Assemble the consumer ontology file from modular Turtle source fragments."""
from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
MODULES_DIR = REPO / "ontology" / "modules"
BUILD_DIR = REPO / "build"
OUTPUT = BUILD_DIR / "ontology.ttl"
BUILD_SHAPES = BUILD_DIR / "shapes.ttl"
PAGES_DIR = REPO / "docs"
PAGES_ONTOLOGY = PAGES_DIR / "ontology.ttl"
PAGES_SHAPES = PAGES_DIR / "shapes.ttl"
PAGES_SITE_DATA = PAGES_DIR / "site-data.json"
SHAPES_SOURCE = REPO / "shapes" / "modules" / "shapes.ttl"

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
    if not SHAPES_SOURCE.exists():
        raise SystemExit(f"missing shapes source: {SHAPES_SOURCE.relative_to(REPO)}")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    chunks = []
    for name in MODULE_ORDER:
        path = MODULES_DIR / name
        text = path.read_text(encoding="utf-8").strip()
        chunks.append(text)

    ontology_text = "\n\n".join(chunks) + "\n"
    shapes_text = SHAPES_SOURCE.read_text(encoding="utf-8")
    site_data = {
        "site": {
            "title": "Pokemontology",
            "tagline": "A public ontology for Pokemon battle mechanics, replay-backed state, and validation.",
            "repository_url": "https://github.com/laurajoyhutchins/pokemontology",
            "pages_base_url": "https://laurajoyhutchins.github.io/pokemontology/",
        },
        "artifacts": [
            {
                "label": "Ontology",
                "path": "ontology.ttl",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#",
                "description": "Published OWL/Turtle bundle assembled from the modular ontology source.",
            },
            {
                "label": "SHACL Shapes",
                "path": "shapes.ttl",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/shapes.ttl#",
                "description": "Validation shapes used for replay slices, save-state data, and ingestion outputs.",
            },
        ],
        "modules": [
            {
                "name": name.removesuffix(".ttl"),
                "source_path": f"ontology/modules/{name}",
            }
            for name in MODULE_ORDER
        ],
        "pipelines": [
            {
                "name": "Replay ingestion",
                "summary": "Acquire public Showdown replays, curate a competitive corpus, and transform JSON logs into ontology slices.",
                "command": "python3 -m pokemontology replay transform --output-dir build/replays",
            },
            {
                "name": "PokeAPI ingestion",
                "summary": "Cache public API resources and convert the cleanly mappable subset into ontology-native Turtle.",
                "command": "python3 -m pokemontology pokeapi ingest examples/pokeapi/seed-config.json --raw-dir data/pokeapi/raw --output build/pokeapi.ttl",
            },
            {
                "name": "Veekun ingestion",
                "summary": "Transform a local normalized export into version-group-scoped mechanics assignments with explicit provenance.",
                "command": "python3 -m pokemontology veekun transform --source-dir tests/fixtures/veekun_export --output build/veekun.ttl",
            },
        ],
        "examples": [
            {
                "name": "Replay-backed battle slice",
                "path": "examples/slices/showdown-finals-game1-slice.ttl",
                "kind": "Turtle slice",
                "summary": "A worked example of a replay-derived battle graph with events, assignments, and validation coverage.",
            },
            {
                "name": "Seed fixture",
                "path": "examples/fixtures/froakie-caterpie-seed.ttl",
                "kind": "Fixture data",
                "summary": "Compact seed data for ontology tests and examples around owned combatants, moves, and save-state entities.",
            },
            {
                "name": "Replay JSON source",
                "path": "examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json",
                "kind": "Replay JSON",
                "summary": "A cached Showdown replay used as a source document for parsing, summarization, and slice generation.",
            },
            {
                "name": "PokeAPI seed config",
                "path": "examples/pokeapi/seed-config.json",
                "kind": "Ingest config",
                "summary": "A sample seed file for fetching and transforming a narrow, ontology-safe subset of PokeAPI data.",
            },
        ],
    }

    OUTPUT.write_text(ontology_text, encoding="utf-8")
    BUILD_SHAPES.write_text(shapes_text, encoding="utf-8")
    PAGES_ONTOLOGY.write_text(ontology_text, encoding="utf-8")
    PAGES_SHAPES.write_text(shapes_text, encoding="utf-8")
    PAGES_SITE_DATA.write_text(json.dumps(site_data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"wrote {BUILD_SHAPES.relative_to(REPO)}")
    print(f"wrote {PAGES_ONTOLOGY.relative_to(REPO)}")
    print(f"wrote {PAGES_SHAPES.relative_to(REPO)}")
    print(f"wrote {PAGES_SITE_DATA.relative_to(REPO)}")


if __name__ == "__main__":
    main()
