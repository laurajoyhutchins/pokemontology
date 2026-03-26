# AGENTS.md

## Purpose

This repository models Pokemon battle mechanics as RDF/OWL and SHACL, with supporting Python tooling for replay parsing, TTL generation, and PokeAPI ingestion.

## Working Rules

- Use the local virtual environment for Python commands: `.venv/bin/python`.
- Prefer the unified CLI over calling scripts directly:
  - `.venv/bin/python -m pokemontology --help`
  - `.venv/bin/python -m pokemontology build`
  - `.venv/bin/python -m pokemontology check-ttl ...`
- Keep changes minimal and repo-local. Do not introduce new dependencies unless the task requires them.

## Important Paths

- `ontology/modules/`: canonical ontology source fragments
- `shapes/modules/shapes.ttl`: canonical SHACL shapes source
- `build/`: generated consumer artifacts
- `docs/`: published copies of generated artifacts
- `scripts/build/`, `scripts/ingest/`, `scripts/replay/`: grouped script implementations used by the CLI
- `scripts/*.py`: compatibility wrappers for direct script execution
- `pokemontology/`: installable CLI package
- `tests/`: regression and validation tests

## Generated Artifacts

- Treat `build/ontology.ttl`, `build/shapes.ttl`, `docs/ontology.ttl`, and `docs/shapes.ttl` as generated files.
- If you change ontology modules or shapes, rebuild with:

```bash
.venv/bin/python -m pokemontology build
```

- Do not hand-edit generated TTL unless the user explicitly asks for that.

## Testing

- Run the full suite with:

```bash
.venv/bin/python -m pytest
```

- If you touch replay parsing, TTL generation, or CLI behavior, run the affected tests plus the full suite if practical.

## Replay Tooling

- `parse-replay` preserves a broad event stream from replay JSON.
- `summarize-replay` and `build-slice` rely on `scripts/replay/replay_parser.py`, which intentionally exposes a narrower typed event model.
- Do not silently merge those parser semantics without checking existing tests and command behavior.

## PokeAPI Tooling

- Use `pokemontology pokeapi fetch`, `transform`, and `ingest` for pipeline work.
- Preserve the distinction between cached raw API payloads and transformed ontology-native TTL.

## Edit Guidance

- Prefer editing source modules, package code, or tests instead of generated outputs.
- Add or update tests for behavioral changes.
- Keep comments short and only where they clarify non-obvious logic.
