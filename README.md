# Pokemontology

Pokemontology is an RDF/OWL + SHACL project for representing Pokémon battle mechanics as explicit, replay-backed state transitions.

It combines:
- a published ontology namespace
- published SHACL validation shapes
- replay parsing and TTL slice generation
- provenance-aware ingestion pipelines for external Pokémon data sources
- a live in-browser SPARQL query engine on the public site

## Public artifacts

| Resource | URL |
|----------|-----|
| Site + query engine | `https://laurajoyhutchins.github.io/pokemontology/` |
| Ontology | `https://laurajoyhutchins.github.io/pokemontology/ontology.ttl` |
| SHACL shapes | `https://laurajoyhutchins.github.io/pokemontology/shapes.ttl` |

The public site is the canonical namespace for the built ontology and shapes. It includes an in-browser SPARQL query engine — load the page, pick a source, and run queries against the live ontology without any local setup.

## What this models

Pokemontology targets the mechanics layer of Pokémon, not just a static encyclopedia.

Core modeling areas:
- ruleset-scoped mechanics: move learnability, type effectiveness, base typing, move properties
- save-state entities: owned Pokémon, slots, IVs, EVs, inventory
- battle participants, actions, events, and state transitions
- instantaneous and materialized battle state
- Tera type overrides and transformation states
- provenance and evidence for externally sourced or replay-derived assertions

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

## Common workflows

### Build a replay-backed TTL slice

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

Validate ontology, shapes, and data together:

```bash
python3 -m pokemontology check-ttl \
  build/ontology.ttl \
  build/shapes.ttl \
  examples/slices/showdown-finals-game1-slice.ttl
```

### Acquire and transform replay corpora

```bash
# Fetch search/index pages
python3 -m pokemontology replay fetch-index \
  --format gen9vgc2025reggbo3 --max-pages 3

# Curate a competitive subset
python3 -m pokemontology replay curate \
  --format gen9vgc2025reggbo3 --min-rating 1600

# Fetch replay payloads, then transform to TTL
python3 -m pokemontology replay fetch
python3 -m pokemontology replay transform --output-dir build/replays
```

### Ingest PokeAPI data

```bash
python3 -m pokemontology pokeapi ingest \
  examples/pokeapi/seed-config.json \
  --raw-dir data/pokeapi/raw \
  --output build/pokeapi.ttl
```

This emits type effectiveness, base typing, move properties (type, base power, accuracy, PP, priority), learnsets, and canonical entity definitions — all anchored to a synthetic `pkm:Ruleset_PokeAPI_Default` context node for current-gen data.

### Transform Veekun exports

```bash
python3 -m pokemontology veekun transform \
  --source-dir tests/fixtures/veekun_export \
  --output build/veekun.ttl
```

## Querying

SPARQL query files live in `queries/`. Load `build/ontology.ttl` (or `build/pokeapi.ttl`) into any SPARQL 1.1 endpoint and run them, or use the live query engine on the public site.

Notable query:

**`queries/super_effective_moves.sparql`** — given a replay slice and PokeAPI data loaded together, returns which of your moves are super-effective against each revealed opponent, accounting for Tera type overrides. Requires `build/ontology.ttl` + `build/pokeapi.ttl` + a replay TTL slice as sources.

## Data source coverage

### PokeAPI

Mapping scope:

| PokeAPI resource | Ontology output |
|-----------------|-----------------|
| `pokemon-species` | `pkm:Species` |
| `pokemon` | `pkm:Variant` + `pkm:TypingAssignment` |
| `type` | `pkm:Type` + `pkm:TypeEffectivenessAssignment` |
| `move` | `pkm:Move` + `pkm:MovePropertyAssignment` (type, base power, accuracy, PP, priority) |
| `ability` | `pkm:Ability` |
| `stat` | `pkm:Stat` |
| `version-group` | `pkm:VersionGroup` + linked `pkm:Ruleset` |
| *(learnsets)* | `pkm:MoveLearnRecord` |

Type effectiveness entries for neutral (×1.0) matchups are omitted — only super-effective (×2.0), not-very-effective (×0.5), and immune (×0.0) pairs are emitted, which is sufficient for the SPARQL queries.

### Veekun

The Veekun pipeline is local-only and targets version-group-scoped mechanics not cleanly available from PokeAPI. Outputs include `pkm:TypingAssignment`, `pkm:AbilityAssignment`, `pkm:StatAssignment`, `pkm:MovePropertyAssignment`, `pkm:MoveLearnRecord`, and `pkm:TypeEffectivenessAssignment`.

## External data policy

External-source integrations follow a consistent contract:

1. Acquire or cache source data without ontology assumptions
2. Normalize to a stable source-local format
3. Transform only the subset that maps cleanly into pokemontology

All ingesters:
- emit one `pkm:EvidenceArtifact` per upstream source
- emit `pkm:ExternalEntityReference` nodes for local-to-upstream links
- use `pkm:refersToEntity`, `pkm:describedByArtifact`, `pkm:hasExternalIRI`
- avoid `owl:sameAs` by default
- emit contextual facts only when the source provides real context

Shared helper code lives in `pokemontology/ingest_common.py`.

## Repository layout

```
pokemontology/
├── ontology/modules/      modular ontology source (OWL/Turtle)
├── shapes/modules/        SHACL source
├── build/                 generated consumer artifacts
├── docs/                  GitHub Pages site, published TTL, and query engine
├── examples/              fixtures, replay JSON, example slices
├── queries/               SPARQL query files
├── scripts/build/         build and validation scripts
├── scripts/ingest/        external data acquisition and transform
├── scripts/replay/        replay parsing and dataset tooling
└── tests/                 regression coverage
```

## Notes

- The built ontology is assembled from `ontology/modules/` by `python3 -m pokemontology build`.
- Replay-backed TTL slices are partial reconstructions from the observable replay log — they do not capture hidden information or dense full-state snapshots.
- Each `BattleParticipant` in a replay slice carries a `pkm:representsSpecies` link so it can be joined against PokeAPI-derived type data in SPARQL queries.
- Terastallized `TransformationState` individuals carry a `pkm:hasTeraType` link used by the super-effective move query.

## License

MIT License. See `LICENSE`.
