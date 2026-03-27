# AGENTS.md

## Purpose

This repository models Pokemon battle mechanics as RDF/OWL and SHACL, with supporting Python tooling for replay parsing, TTL generation, and PokeAPI ingestion. It also includes "Professor Laurel," a natural-language-to-SPARQL reasoning pipeline for querying Pokemon mechanics.

## Working Rules

- Use the local virtual environment for Python commands: `.venv/bin/python`.
- Always use the unified CLI over calling individual scripts:
  - `.venv/bin/python -m pokemontology --help`
  - `.venv/bin/python -m pokemontology build`
  - `.venv/bin/python -m pokemontology laurel "Can Water-type Pokemon be burned?" data/pokeapi/transformed/pokeapi.ttl`
- Keep changes minimal and repo-local. Do not introduce new dependencies unless the task requires them.
- After finishing code changes, commit them and push the branch.
- Follow the reified `pkm:ContextualFact` pattern for mechanics that vary by generation.

## Important Paths

- `ontology/modules/`: Canonical ontology source fragments.
- `shapes/modules/shapes.ttl`: Canonical SHACL shapes source.
- `pokemontology/`: Unified Python package for all logic.
- `build/`: Generated consumer artifacts (e.g., `ontology.ttl`, `schema-index.json`).
- `docs/`: Published site data and workers for the web frontend.
- `queries/bundled/`: Tracked SPARQL queries consumed by docs, tests, and examples.
- `queries/scratch/`: Local scratch queries and fixtures; do not wire build/docs/tests to this directory.
- `tests/`: Regression, validation, and evaluation suites.
- `data/`: Cached raw API payloads and transformed TTL.

## Generated Artifacts

- Treat `build/ontology.ttl`, `build/shapes.ttl`, `docs/ontology.ttl`, and `docs/shapes.ttl` as generated files.
- Treat `build/mechanics.ttl` as the canonical local mechanics bundle.
- Treat `docs/mechanics-base.ttl`, `docs/mechanics-learnsets-current.ttl`, `docs/mechanics-learnsets-modern.ttl`, `docs/mechanics-learnsets-legacy.ttl`, `docs/site-data.json`, and `docs/schema-index.json` as generated publishable web artifacts.
- Rebuild these with:
  ```bash
  .venv/bin/python -m pokemontology build
  ```
- `build/schema-index.json` is also a generated artifact used for RAG grounding.
- If you change ontology/build/docs source wiring, rebuild before finishing and make sure generated files are committed.

## Professor Laurel (NL-to-SPARQL)

Professor Laurel translates natural-language questions into SPARQL queries, executes them, and synthesizes answers.

- **Requirements**: Local Ollama instance running `qwen2.5:1.5b` (default).
- **RAG Grounding**: Uses `build/schema-index.json` for vector-based retrieval of relevant ontology terms.
- **Commands**:
  - `ask`: Translates a question to SPARQL and prints it.
  - `laurel`: Full pipeline (translate -> execute -> summarize).
  - `evaluate-laurel`: Runs the evaluation suite for accuracy and safety.

## Testing & Evaluation

- **Unit/Integration Tests**: Run with `.venv/bin/python -m pytest`.
- **Fast regression gate**: Prefer running
  ```bash
  .venv/bin/python -m pytest tests/test_cli.py tests/test_turn_order.py tests/test_build_site_assets.py tests/test_docs_query_engine.py tests/test_e2e.py
  ```
  when changing CLI/build/frontend alignment.
- **Laurel Evaluation**: Run with `.venv/bin/python -m pokemontology evaluate-laurel`.
  - The suite is defined in `tests/fixtures/laurel_eval_suite.json`.
  - It includes mechanics tiers (easy, medium, hard, gen-specific) and adversarial safety checks.

## CI/CD Procedure

- GitHub Actions `CI` is the main required gate for PRs and `main`.
- `CI` rebuilds generated artifacts and fails if committed generated files drift from a fresh `.venv/bin/python -m pokemontology build`.
- `CI` also enforces size checks on published `docs/*.ttl` artifacts; avoid growing web bundles casually.
- GitHub Pages deploys from the `pages` workflow after `CI` succeeds on `main`.

## Replay Tooling

- `parse-replay`: Broad event stream from Showdown JSON logs.
- `summarize-replay`: Typed event model for higher-level reasoning.
- `build-slice`: Converts a replay into a replay-backed Turtle slice (`pkm:Event` and `pkm:Action`).

## PokeAPI Tooling

- Use `pokemontology pokeapi fetch`, `transform`, and `ingest` for pipeline work.
- Cached raw API payloads are in `data/pokeapi/raw/`.
- Transformed ontology-native TTL is in `data/pokeapi/transformed/`.

## Edit Guidance

- Prefer editing source modules in `ontology/modules/` or package code in `pokemontology/`.
- Add or update tests for behavioral changes.
- Never block a safety validator; adversarial prompts must return `ERROR: unrelated_request`.
