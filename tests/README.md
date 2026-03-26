# Tests

Placeholder for validation and regression tests.

Suggested initial tests:
- build ontology, shapes, and fixtures/examples all parse as Turtle
- replay slice conforms to SHACL
- faint events imply post-state HP = 0 where modeled
- materialized stat stage uniqueness per participant/stat/instant
- PokeAPI ingestion expands linked resources and serializes valid TTL from cached payloads

Laurel-specific fixture builders used by the CLI and evaluation harness tests live in `tests/_laurel_support.py`.

Laurel harness maintenance tips:
- Inspect suite metadata without running a model: `.venv/bin/python -m pokemontology evaluate-laurel --list-tiers`
- Validate suite structure only: `.venv/bin/python -m pokemontology evaluate-laurel --validate-suite`
- Add small one-off Laurel test suites with `write_eval_suite()` or `write_eval_suite_payload()` from `tests/_laurel_support.py`
