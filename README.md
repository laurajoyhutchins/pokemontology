# Pokemontology

> **Unofficial project.** Pokemontology is an independent fan, research, and data-engineering project. It is not affiliated with, endorsed by, sponsored by, or approved by Nintendo, Game Freak, Creatures Inc., or The Pokémon Company. It is not an official source of Pokémon facts, rules, terminology, or game data. Pokémon and related names and marks belong to their respective owners. This notice does not grant permission to copy or redistribute third-party material.

Pokemontology is an RDF/OWL and SHACL toolkit for studying how battle-mechanics claims, replay observations, source assertions, and project inferences can be represented as an inspectable knowledge graph.

## Status and scope

The project is experimental research software, currently version `0.1.0`. Its ontology, validation shapes, source adapters, build scripts, queries, and documentation are project-authored. Results derived from external sources may be partial, outdated, normalized, inferred, or wrong. They are not official franchise semantics.

The repository is designed around **small fixtures and reproducible transforms**, not as a complete franchise-data mirror. Large or restricted source datasets should be retrieved by users from their original sources only when their terms allow it. See [DATA_SOURCES.md](DATA_SOURCES.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and [ASSET_PROVENANCE.md](ASSET_PROVENANCE.md).

## Architecture

- `ontology/modules/`: project-authored OWL/Turtle modeling modules.
- `shapes/modules/`: project-authored SHACL validation rules.
- `pokemontology/`: project-authored Python package and command-line interface.
- `scripts/`: build, ingestion, replay, and validation entry points.
- `queries/bundled/`: project-authored SPARQL queries used by tests and documentation.
- `examples/`: small synthetic or explicitly documented fixtures.
- `build/`: deterministic generated artifacts for local consumption.
- `docs/`: GitHub Pages application and generated publication copies.
- `MANIFEST.json`: machine-readable source, artifact, and redistribution manifest.

The ontology distinguishes source assertions from project inferences. Source artifacts and external references are represented explicitly; normalized relationships are not presented as official franchise semantics. Detailed identifier, alias, language-tag, provenance, versioning, and deprecation rules are in [docs/ontology-guidelines.md](docs/ontology-guidelines.md). System boundaries and data flow are in [docs/architecture.md](docs/architecture.md).

## Install, build, and validate

Requires Python 3.11 or newer.

```bash
python3 -m pip install .
python3 -m pokemontology build
python3 -m pytest
python3 scripts/validate_publication.py
```

The build command assembles the ontology and SHACL modules into deterministic consumer artifacts. Generated outputs must not be edited manually. CI rebuilds them and fails when tracked outputs differ.

To validate ontology, shapes, and an example graph:

```bash
python3 -m pokemontology check-ttl \
  build/ontology.ttl \
  build/shapes.ttl \
  examples/fixtures/synthetic-battle-slice.ttl
```

To run a bundled query, load the built ontology plus an independently acquired mechanics graph into a SPARQL 1.1 engine, then run a query from `queries/bundled/`.

## External data and replay workflows

Source adapters are intentionally separate from the ontology model. Acquisition is opt-in and should write raw downloads only to ignored local directories.

```bash
# User-supplied PokeAPI inputs
python3 -m pokemontology pokeapi ingest \
  examples/pokeapi/seed-config.json \
  --raw-dir data/pokeapi/raw \
  --output build/pokeapi.ttl

# User-supplied Veekun checkout/export
python3 -m pokemontology veekun ingest \
  --raw-dir data/veekun/raw \
  --source-dir data/veekun/export \
  --output build/veekun.ttl
```

Do not commit downloaded archives, API responses, game data, private replay payloads, credentials, access URLs, or generated corpora. Replays may contain usernames, chat, teams, private access tokens, or other user-supplied information. Automated tests must use synthetic fixtures unless a source and redistribution basis are documented.

The bulk legacy learnset archive is intentionally excluded from the ordinary public build because its exact inputs and public redistribution basis have not been established. It may be generated locally from independently acquired inputs, but must not be committed or published without a completed source review. The remaining generated mechanics/site artifacts are explicitly marked for file-level owner review in [issue #18](https://github.com/laurajoyhutchins/pokemontology/issues/18).

## Provenance and generated artifacts

Every generated artifact must identify:

1. source inputs;
2. the transformation command;
3. tool and schema versions;
4. whether the output is checked in;
5. its redistribution status and uncertainty.

`MANIFEST.json` is the authoritative machine-readable inventory. `python3 scripts/validate_publication.py` checks required source fields, file classifications, forbidden public-file patterns, and deterministic manifest ordering.

## Licensing boundaries

The MIT license in [LICENSE](LICENSE) applies only to project-authored material for which the repository author has the right to grant that license, such as original source code, ontology modeling, SHACL shapes, queries, and documentation, unless a file says otherwise.

It does **not** license or grant rights in Pokémon names, characters, artwork, sprites, logos, game text, game data, replay content, trademarks, or any other third-party material. A software repository license cannot expand the permissions granted by an upstream source. Review [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [DATA_SOURCES.md](DATA_SOURCES.md) before reusing data or generated outputs.

## Contributing and reporting

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting code, ontology changes, data, or assets. New sources and assets require provenance, license/terms, retrieval version or date, transformations, and redistribution status.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md). Use repository issues for reproducible bugs, ontology ambiguities, provenance defects, and documentation problems. Do not post secrets, private replay URLs, personal data, or copyrighted source material in an issue.
