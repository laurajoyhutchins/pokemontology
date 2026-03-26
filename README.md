# Pokemontology

Pokemontology is an RDF/OWL + SHACL project for representing Pokemon battle mechanics as explicit, replay-backed state transitions.

It combines:
- a published ontology namespace
- published SHACL validation shapes
- replay parsing and slice generation tools
- provenance-aware ingestion pipelines for external Pokemon data sources

## Public artifacts

- GitHub Pages site: `https://laurajoyhutchins.github.io/pokemontology/`
- Ontology: `https://laurajoyhutchins.github.io/pokemontology/ontology.ttl`
- SHACL shapes: `https://laurajoyhutchins.github.io/pokemontology/shapes.ttl`

The public site is the canonical namespace for the built ontology and shapes.

## What this models

Pokemontology is aimed at the mechanics layer of Pokemon, not just a static encyclopedia.

Core modeling areas:
- ruleset-scoped mechanics such as move learnability and contextual assignments
- save-state entities such as owned Pokemon, slots, IVs, EVs, and inventory data
- battle participants, actions, events, and state transitions
- instantaneous and materialized battle state
- provenance and evidence for externally sourced or replay-derived assertions

This makes it suitable for:
- replay-backed battle analysis
- ontology-native validation with SHACL
- structured ingestion from sources like PokeAPI and Veekun
- building a machine-readable mechanics knowledge base with explicit context

## Project status

The repo already includes:
- a modular source ontology under `ontology/modules/`
- built consumer artifacts under `build/`
- published Pages artifacts under `docs/`
- replay tooling for parsing public Pokemon Showdown replays into TTL slices
- ingestion pipelines for PokeAPI and Veekun-shaped exports
- test coverage for ontology parsing, SHACL conformance, replay conversion, and ingestion contracts

## Quick start

Install the project:

```bash
python3 -m pip install .
```

Build the published ontology and shapes:

```bash
python3 -m pokemontology build
```

Run the test suite:

```bash
python3 -m pytest
```

See the CLI:

```bash
python3 -m pokemontology --help
```

## Common workflows

### Build a replay-backed slice

Parse a replay:

```bash
python3 -m pokemontology parse-replay \
  examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json \
  --pretty
```

Summarize a replay:

```bash
python3 -m pokemontology summarize-replay \
  examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json
```

Generate a Turtle slice:

```bash
python3 -m pokemontology build-slice \
  examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json \
  -o examples/slices/generated-slice.ttl
```

Validate ontology, shapes, and example data together:

```bash
python3 -m pokemontology check-ttl \
  build/ontology.ttl \
  build/shapes.ttl \
  examples/fixtures/froakie-caterpie-seed.ttl \
  examples/slices/showdown-finals-game1-slice.ttl
```

### Acquire and transform replay corpora

Fetch replay search/index pages:

```bash
python3 -m pokemontology replay fetch-index \
  --format gen9vgc2025reggbo3 \
  --max-pages 3
```

Curate a competitive subset:

```bash
python3 -m pokemontology replay curate \
  --format gen9vgc2025reggbo3 \
  --min-rating 1600
```

Fetch replay payloads:

```bash
python3 -m pokemontology replay fetch
```

Transform cached replays into TTL:

```bash
python3 -m pokemontology replay transform \
  --output-dir build/replays
```

### Ingest PokeAPI data

Fetch and transform the cleanly mappable subset:

```bash
python3 -m pokemontology pokeapi ingest \
  examples/pokeapi/seed-config.json \
  --raw-dir data/pokeapi/raw \
  --output build/pokeapi.ttl
```

Validate the result:

```bash
python3 -m pokemontology check-ttl build/pokeapi.ttl
```

Fair-use raw scraping is also available:

```bash
python3 scripts/ingest/pokeapi_scrape.py move \
  --details \
  --max-pages 1 \
  --max-details 25 \
  --delay-seconds 0.5
```

### Transform Veekun exports

```bash
python3 -m pokemontology veekun transform \
  --source-dir tests/fixtures/veekun_export \
  --output build/veekun.ttl
```

## External data policy

External-source integrations in this repo follow a consistent contract:

1. Acquire or cache source data without ontology assumptions
2. Normalize it into a stable source-local format
3. Transform only the subset that maps cleanly into pokemontology

All ingesters are expected to:
- emit one `pkm:EvidenceArtifact` per upstream source
- emit `pkm:ExternalEntityReference` nodes for local-to-upstream links
- use `pkm:refersToEntity`, `pkm:describedByArtifact`, and `pkm:hasExternalIRI`
- avoid `owl:sameAs` by default
- emit contextual facts only when the source provides real context

Shared helper code for this lives in `pokemontology/ingest_common.py`.

## Data source coverage

### PokeAPI

PokeAPI is used for the subset that maps cleanly to canonical entities and version-group-scoped learnset facts.

Current mapping scope:
- `pokemon-species` -> `pkm:Species`
- `pokemon` -> `pkm:Variant`
- `move` -> `pkm:Move`
- `ability` -> `pkm:Ability`
- `type` -> `pkm:Type`
- `stat` -> `pkm:Stat`
- `version-group` -> `pkm:VersionGroup` plus linked `pkm:Ruleset`
- move learnsets -> `pkm:MoveLearnRecord`

The transform intentionally does not emit contextual mechanics facts that PokeAPI exposes only as a current snapshot.

### Veekun

The Veekun pipeline is local-only and aimed at ontology areas where Veekun is stronger than PokeAPI, especially version-group-scoped mechanics.

Targeted outputs include:
- `pkm:TypingAssignment`
- `pkm:AbilityAssignment`
- `pkm:StatAssignment`
- `pkm:MovePropertyAssignment`
- `pkm:MoveLearnRecord`
- `pkm:TypeEffectivenessAssignment`

## Repository layout

```text
pokemontology/
├── ontology/modules/      modular ontology source
├── shapes/modules/        SHACL source
├── build/                 generated consumer artifacts
├── docs/                  GitHub Pages site and published TTL files
├── examples/              fixtures, replay JSON, and example slices
├── scripts/build/         build and validation scripts
├── scripts/ingest/        external data acquisition and transform scripts
├── scripts/replay/        replay parsing and replay-dataset tooling
└── tests/                 regression coverage
```

## Notes

- The built ontology is generated from the modular sources under `ontology/modules/`.
- The published Pages site is refreshed by `python3 -m pokemontology build`.
- Replay-backed slices are still partial reconstructions, not dense full-state captures of every battle fact.

## License

This repository is licensed under the MIT License. See `LICENSE`.
