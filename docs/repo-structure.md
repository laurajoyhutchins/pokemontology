# Repository Structure

This project is easiest to maintain if it keeps three layers separate:

1. **Ontology layer**  
   Stable RDF/OWL vocabulary for battle entities, transitions, materialized assignments, and provenance.

2. **Validation layer**  
   SHACL constraints for structure, cardinality, and replay-state consistency.

3. **Corpus layer**  
   Raw replay JSON plus replay-derived RDF slices and test fixtures.

## Current directories

- `build/` — consumer-facing built ontology and shapes artifacts
- `docs/` — GitHub Pages site plus published `ontology.ttl` / `shapes.ttl`
- `ontology/modules/` — modular ontology source fragments
- `shapes/modules/` — SHACL source fragments
- `examples/fixtures/` — seed/example RDF fixtures kept out of the ontology schema
- `examples/replays/` — source replay payloads
- `examples/slices/` — replay-derived RDF examples
- `scripts/build/` — build and syntax-check implementations
- `scripts/ingest/` — external-data acquisition and transform implementations
- `scripts/replay/` — replay parsing, summary, and slice-building implementations
- `docs/` — project notes
- `tests/` — validation/regression test area

## Recommended next additions

- `scripts/validate_with_shacl.py`
- `scripts/enrich_slice_state.py`
- `tests/test_shapes_conformance.py`
- `docs/modeling-decisions.md`
- `docs/epistemic-status.md`
