# Pokémon Battle Mechanics Ontology

RDF/OWL + SHACL project for modeling Pokémon battles as replay-backed state transitions with explicit event provenance, materialized state assignments, and validation constraints.

## Repository layout

```text
pokemontology/
├── build/
│   └── ontology.ttl
│   └── shapes.ttl
├── ontology/
│   └── modules/
│       ├── 00-header.ttl
│       ├── 10-core.ttl
│       ├── ...
│       └── 80-materialized-state.ttl
├── shapes/
│   └── modules/
│       └── shapes.ttl
├── examples/
│   ├── fixtures/
│   │   └── froakie-caterpie-seed.ttl
│   ├── pokeapi/
│   │   └── seed-config.json
│   ├── replays/
│   │   └── gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json
│   └── slices/
│       └── showdown-finals-game1-slice.ttl
├── scripts/
│   ├── build_ontology.py
│   ├── check_ttl_parse.py
│   ├── parse_showdown_replay.py
│   ├── pokeapi_ingest.py
│   ├── replay_to_ttl_builder.py
│   └── summarize_showdown_replay.py
├── docs/
│   ├── index.html
│   ├── ontology.ttl
│   ├── shapes.ttl
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
- Built consumer shapes at `build/shapes.ttl`
- Published Pages ontology at `https://laurajoyhutchins.github.io/pokemontology/ontology.ttl`
- Canonical SHACL shapes TTL
- Published Pages shapes at `https://laurajoyhutchins.github.io/pokemontology/shapes.ttl`
- Seed/example fixture extracted from the ontology source
- Replay JSON used as source corpus
- Replay-backed TTL slice
- Sample PokeAPI seed config and an ingestion pipeline for caching raw API data and building TTL
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

This also refreshes the GitHub Pages artifacts under `docs/`.

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
python3 scripts/check_ttl_parse.py       build/ontology.ttl       build/shapes.ttl       examples/fixtures/froakie-caterpie-seed.ttl       examples/slices/showdown-finals-game1-slice.ttl
```

```bash
python3 scripts/pokeapi_ingest.py ingest \
      examples/pokeapi/seed-config.json \
      --raw-dir data/pokeapi/raw \
      --output build/pokeapi.ttl
```

```bash
python3 scripts/check_ttl_parse.py build/pokeapi.ttl
```

## PokeAPI ingestion pipeline

The repo now includes a two-stage PokeAPI pipeline:

1. `fetch` caches raw JSON under `data/pokeapi/raw/`
2. `transform` converts cached payloads into ontology-native Turtle
3. `ingest` runs both steps in sequence

Current mapping scope:
- `pokemon-species` -> `pkm:Species`
- `pokemon` -> `pkm:Variant`
- `move` -> `pkm:Move` plus snapshot `pkm:MovePropertyAssignment`
- `ability` -> `pkm:Ability`
- `type` -> `pkm:Type`
- `stat` -> `pkm:Stat`
- `version-group` -> `pkm:VersionGroup` plus linked `pkm:Ruleset`
- Pokémon move learnsets -> `pkm:MoveLearnRecord` per variant/move/version-group
- Pokémon current types, stats, and abilities -> snapshot assignments in `pkm:Ruleset_PokeAPI_CanonicalSnapshot`

The transform intentionally distinguishes between:
- version-group-scoped learnability data that PokeAPI exposes directly
- current canonical mechanics values that PokeAPI exposes without a version-group qualifier

That keeps the generated TTL useful without pretending that all mechanics data is historically version-precise.

## Notes

- The included replay-backed slice is still a partial state reconstruction, not a dense full-state model.
- The built consumer ontology is generated from modular source fragments under `ontology/modules/`.
- This repo sketch packages the latest files actually present in the workspace:
  - ontology v1.1
  - shapes v0.7
  - replay slice v0.7
