# Proposal: Add RDF-Backed Move Category Lookup for Turn Order

## Summary

Turn-order inference currently derives move priority and move type from local Turtle mechanics data, but `move_category` is still provided only through direct input payloads. We should add RDF-backed move category lookup as an additive follow-up so turn-order logic can consume richer mechanics data without making ongoing replay ingestion or TTL generation runs brittle.

This proposal intentionally excludes broad move-tag modeling for now. `move category` is stable and low-risk. Tags such as `healing`, `contact`, or `sound` likely need more source and modeling review first.

## Motivation

- Reduce hardcoded turn-order assumptions in [turn_order.py](/home/phthalo/pokemontology/pokemontology/turn_order.py).
- Extend the existing `MovePropertyAssignment` pattern instead of introducing a second mechanics lookup path.
- Keep ontology-backed mechanics aligned across CLI queries, docs, and resolver behavior.
- Avoid blocking current ingestion work by making the change additive and tolerant of missing data.

## Current State

`turn_order.py` already looks up:

- `move_priority`
- `move_type`

from ruleset-scoped move property assignments in local TTL files.

It does not yet look up:

- `move_category`

As a result, effects such as Prankster depend on callers passing category data in the input payload instead of reusing canonical mechanics data.

## Proposal

Add RDF-backed move category support in the mechanics pipeline and make turn-order resolution consume it opportunistically.

### Scope

1. Extend move-property extraction in `turn_order.py` so `_lookup_move_properties()` can return `move_category` when present.
2. Add a canonical RDF representation for move category in the ontology/mechanics data path.
3. Update the ingestion/build pipeline that produces move mechanics TTL so category is emitted where source data supports it.
4. Keep payload-provided `move_category` as an override and keep missing RDF category neutral.

### Non-Goals

- Do not require move category to exist in all TTL outputs yet.
- Do not refactor replay builders during active ingestion runs.
- Do not add general move-tag modeling in the same change.
- Do not make SHACL require the new category facts until the pipeline emits them consistently.

## Suggested Rollout

### Phase 1: Additive Lookup

- Introduce `move_category` support in the move-property indexing path.
- Prefer TTL-derived category in `turn_order.py` when available.
- Preserve direct payload input and existing fallback behavior.

### Phase 2: Ingestion Support

- Add category emission in the mechanics TTL generation path.
- Cover at least one known move/category example in tests.

### Phase 3: Broader Use

- Update any query/docs surfaces that should expose category as part of move mechanics.
- Reassess whether move tags should follow the same pattern.

## Data Model Direction

This should follow the same general pattern already used for ruleset-scoped move properties:

- a move property assignment
- about a move
- in a ruleset context
- carrying a category value

Whether the category object is modeled as a controlled term, enum-like class, or literal should be decided based on the existing ontology style for move types and related mechanics terms.

## Risks

- Source-of-truth drift if category is hardcoded in Python and RDF simultaneously.
- Premature tag modeling if this expands into a broader “move tags” project too early.
- Temporary partial coverage while ingestion catches up.

These risks are manageable if the first implementation is strictly additive and fallback-friendly.

## Testing

- Add a focused turn-order regression showing Prankster priority can be derived from TTL-backed `move_category`.
- Keep existing payload-based tests passing.
- Run the full test suite after the ingestion/build update.

## Open Questions

- What is the preferred ontology representation for move category values?
- Which ingestion source should be authoritative for category?
- Should category live only in ruleset-scoped property assignments, or also on the move itself when not ruleset-variant?

## Suggested Issue Title

Add RDF-backed move category lookup for turn-order inference

## Suggested Issue Body

Add RDF-backed `move_category` support to the turn-order mechanics lookup path.

Context:
- `turn_order.py` already derives `move_priority` and `move_type` from local mechanics TTL.
- `move_category` is still only supplied through input payloads.
- This means mechanics such as Prankster cannot yet rely on canonical RDF-backed move metadata.

Proposal:
- Extend the existing move-property assignment path to include `move_category`.
- Update turn-order lookup to consume RDF-backed category when present.
- Keep payload-provided category as an override and keep missing RDF category neutral.
- Limit this change to move category for now; defer broader move-tag modeling until ingestion semantics are clearer.

Acceptance criteria:
- `turn_order.py` can derive `move_category` from mechanics TTL.
- Existing payload-based behavior remains backward-compatible.
- At least one regression test demonstrates TTL-backed category affecting derived priority.
- Full test suite passes after the change.
