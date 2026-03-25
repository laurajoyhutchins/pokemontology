# Pokémon Battle Mechanics Ontology

RDF/OWL + SHACL project for modeling Pokémon battles as replay-backed state transitions with explicit event provenance, materialized state assignments, and validation constraints.

## Repository layout

```text
pokemontology/
├── build/
│   └── ontology.ttl
├── ontology/
│   └── modules/
│       ├── 00-header.ttl
│       ├── 10-core.ttl
│       ├── ...
│       └── 80-materialized-state.ttl
├── shapes/
│   └── pokemon-mechanics-shapes.ttl
├── examples/
│   ├── fixtures/
│   │   └── froakie-caterpie-seed.ttl
│   ├── replays/
│   │   └── gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json
│   └── slices/
│       └── showdown-finals-game1-slice.ttl
├── scripts/
│   ├── build_ontology.py
│   ├── check_ttl_parse.py
│   ├── parse_showdown_replay.py
│   ├── replay_to_ttl_builder.py
│   └── summarize_showdown_replay.py
├── docs/
│   ├── repo-structure.md
│   └── roadmap.md
├── tests/
│   └── README.md
├── .gitignore
├── MANIFEST.json
├── pyproject.toml
└── requirements.txt
```

## Included files

- Modular ontology source fragments under `ontology/modules/`
- Built consumer ontology at `build/ontology.ttl`
- Canonical SHACL shapes TTL
- Seed/example fixture extracted from the ontology source
- Replay JSON used as source corpus
- Replay-backed TTL slice
- Utility scripts for replay parsing, summary, slice building, and TTL syntax checking

## Suggested workflow

1. Put a Showdown replay JSON under `examples/replays/`.
2. Generate a minimal event-layer slice with `scripts/replay_to_ttl_builder.py`.
3. Enrich the slice with materialized state assignments where needed.
4. Validate ontology + shapes + slice together.
5. Add regression tests for each modeling extension.

Rebuild the consumer ontology after editing source modules:

```bash
python3 scripts/build_ontology.py
```

## Example commands

```bash
python scripts/parse_showdown_replay.py       examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json       --pretty
```

```bash
python scripts/summarize_showdown_replay.py       examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json
```

```bash
python scripts/replay_to_ttl_builder.py       examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json       -o examples/slices/generated-slice.ttl
```

```bash
python3 scripts/check_ttl_parse.py       build/ontology.ttl       shapes/pokemon-mechanics-shapes.ttl       examples/fixtures/froakie-caterpie-seed.ttl       examples/slices/showdown-finals-game1-slice.ttl
```

## Notes

- The included replay-backed slice is still a partial state reconstruction, not a dense full-state model.
- The built consumer ontology is generated from modular source fragments under `ontology/modules/`.
- This repo sketch packages the latest files actually present in the workspace:
  - ontology v1.1
  - shapes v0.7
  - replay slice v0.7
