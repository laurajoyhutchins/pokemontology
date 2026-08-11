# Tests

The repository has two complementary regression tiers.

## Required CI: fast regressions

The `CI` workflow runs a selected set of fast, high-signal suites on pull requests and `main` changes. It covers CLI behavior, turn order, generated site assets, the browser query engine, and end-to-end behavior without paying the cost of every slow/full-graph test on every change.

The equivalent focused command is:

```bash
.venv/bin/python -m pytest tests/test_cli.py tests/test_turn_order.py tests/test_build_site_assets.py tests/test_docs_query_engine.py tests/test_e2e.py
```

## Nightly Audit: complete regressions

`Nightly Audit` deliberately expands beyond required CI and runs every collected pytest test, including tests marked `slow` that are excluded by the repository's default pytest configuration:

```bash
.venv/bin/python -m pytest -m ''
```

The `full-regressions` job is authoritative for the complete suite. It is independent of Professor Laurel and Ollama configuration. A missing `OLLAMA_BASE_URL` skips only the separate optional `laurel-evaluation` job and cannot turn a failing full-regression job green.

Every nightly full-regression run records the exact checked-out head and uploads JUnit output even when pytest fails. That artifact is the durable handoff for reproducing a nightly failure: use the recorded SHA and the exact command above rather than diagnosing from a later branch state.

## Shared support

Shared suite support lives in `tests/support/`.
- `tests/support/__init__.py` contains repo paths plus common JSON and fixture-copy helpers.
- `tests/support/laurel.py` contains Laurel-specific fixture builders for the CLI and evaluation harness tests.

Laurel harness maintenance tips:
- Inspect suite metadata without running a model: `.venv/bin/python -m pokemontology evaluate-laurel --list-tiers`
- Validate suite structure only: `.venv/bin/python -m pokemontology evaluate-laurel --validate-suite`
- Add small one-off Laurel test suites with `write_eval_suite()` or `write_eval_suite_payload()` from `tests/support/laurel.py`
