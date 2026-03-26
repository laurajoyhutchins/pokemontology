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
│   ├── build/
│   │   ├── build_ontology.py
│   │   └── check_ttl_parse.py
│   ├── ingest/
│   │   ├── pokeapi_ingest.py
│   │   ├── pokeapi_scrape.py
│   │   └── veekun_ingest.py
│   ├── replay/
│   │   ├── parse_showdown_replay.py
│   │   ├── replay_parser.py
│   │   ├── replay_to_ttl_builder.py
│   │   └── summarize_showdown_replay.py
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
- Script implementations organized by `build`, `ingest`, and `replay`

## Suggested workflow

1. Put a Showdown replay JSON under `examples/replays/`.
2. Generate a minimal event-layer slice with `python3 -m pokemontology build-slice ...`.
3. Enrich the slice with materialized state assignments where needed.
4. Validate ontology + shapes + slice together.
5. Add regression tests for each modeling extension.

Rebuild the consumer ontology after editing source modules:

```bash
python3 -m pokemontology build
```

This also refreshes the GitHub Pages artifacts under `docs/`.

## CLI

The repository now exposes a unified CLI:

```bash
python3 -m pokemontology --help
```

If installed as a console script, the same commands are available under:

```bash
pokemontology --help
```

## Example commands

```bash
python3 -m pokemontology parse-replay \
      examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json \
      --pretty
```

```bash
python3 -m pokemontology summarize-replay \
      examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json
```

```bash
python3 -m pokemontology build-slice \
      examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json \
      -o examples/slices/generated-slice.ttl
```

```bash
python3 -m pokemontology check-ttl \
      build/ontology.ttl \
      build/shapes.ttl \
      examples/fixtures/froakie-caterpie-seed.ttl \
      examples/slices/showdown-finals-game1-slice.ttl
```

```bash
python3 -m pokemontology pokeapi ingest \
      examples/pokeapi/seed-config.json \
      --raw-dir data/pokeapi/raw \
      --output build/pokeapi.ttl
```

```bash
python3 -m pokemontology check-ttl build/pokeapi.ttl
```

```bash
python3 scripts/ingest/pokeapi_scrape.py move \
      --details \
      --max-pages 1 \
      --max-details 25 \
      --delay-seconds 0.5
```

```bash
python3 -m pokemontology veekun transform \
      --source-dir tests/fixtures/veekun_export \
      --output build/veekun.ttl
```

## PokeAPI ingestion pipeline

The repo now includes a two-stage PokeAPI pipeline:

1. `pokemontology pokeapi fetch` caches raw JSON under `data/pokeapi/raw/`
2. `pokemontology pokeapi transform` converts cached payloads into ontology-native Turtle
3. `pokemontology pokeapi ingest` runs both steps in sequence

Current mapping scope:
- `pokemon-species` -> `pkm:Species`
- `pokemon` -> `pkm:Variant`
- `move` -> `pkm:Move`
- `ability` -> `pkm:Ability`
- `type` -> `pkm:Type`
- `stat` -> `pkm:Stat`
- `version-group` -> `pkm:VersionGroup` plus linked `pkm:Ruleset`
- Pokémon move learnsets -> `pkm:MoveLearnRecord` per variant/move/version-group

The transform intentionally excludes data that PokeAPI exposes only as a current canonical snapshot without a clean ontology context. In particular, it does not emit `pkm:TypingAssignment`, `pkm:StatAssignment`, `pkm:AbilityAssignment`, or `pkm:MovePropertyAssignment`, because those are contextual facts in the ontology and PokeAPI does not provide the necessary ruleset precision for them.

## Ingestion standard

External-source integrations in this repo now follow a standard contract:

1. Acquire/cache source data without ontology assumptions
2. Normalize it into a stable source-local export format
3. Transform only the subset that maps cleanly into pokemontology

All transforms should:
- emit one `pkm:EvidenceArtifact` per upstream source
- emit `pkm:ExternalEntityReference` nodes for local-to-upstream links
- use `pkm:refersToEntity`, `pkm:describedByArtifact`, and `pkm:hasExternalIRI`
- avoid `owl:sameAs` by default
- emit contextual facts only when the source provides real context, not just a current snapshot

The shared helper implementation for this contract lives in `pokemontology/ingest_common.py`.

## PokeAPI scraping

The repo also includes a dedicated scraper at `scripts/ingest/pokeapi_scrape.py` for pulling raw PokeAPI data while following the project’s published fair-use guidance:
- cache every response to disk
- send an explicit `User-Agent`
- pace requests with a configurable delay
- support resumable runs by skipping already cached pages/details
- stay within an allowlist of supported resources

This follows PokeAPI’s official documentation and fair-use policy, which says developers should locally cache resources and limit request frequency:
- https://staging.pokeapi.co/docs/v2

The scraper is for raw collection only. Use the ingestion pipeline afterward to convert the subset that maps cleanly into ontology-native Turtle.

## Veekun ingestion scaffold

The repo also includes a local-only Veekun transform at `scripts/ingest/veekun_ingest.py`.

This scaffold expects a normalized CSV export directory, not a live download. It is designed for the ontology areas where Veekun is stronger than PokeAPI:
- `pkm:VersionGroup` / `pkm:Ruleset`
- `pkm:TypingAssignment`
- `pkm:AbilityAssignment`
- `pkm:StatAssignment`
- `pkm:MovePropertyAssignment`
- `pkm:MoveLearnRecord`
- `pkm:TypeEffectivenessAssignment`

It also emits `pkm:ExternalEntityReference` nodes back to `pkm:DatasetArtifact_Veekun`.

The scaffold is intentionally local-only because Veekun’s software is MIT-licensed, but upstream notes that included game-derived data is used at the user’s own legal risk. That makes Veekun a strong source for internal/reference workflows, but not something this repo should blindly repackage in bulk.

## Notes

- The included replay-backed slice is still a partial state reconstruction, not a dense full-state model.
- The built consumer ontology is generated from modular source fragments under `ontology/modules/`.
- This repo sketch packages the latest files actually present in the workspace:
  - ontology v1.1
  - shapes v0.7
  - replay slice v0.7
