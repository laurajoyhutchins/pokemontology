# Architecture and data flow

## Layers

1. **Project model** — OWL/Turtle modules define project-specific classes and properties. SHACL modules define validation expectations.
2. **Source adapters** — PokeAPI, Veekun, and replay adapters parse externally supplied input into source-local records.
3. **Assertion mapping** — adapters emit explicit evidence artifacts and external references. A source assertion records what a source states; it is not an official endorsement.
4. **Inference and normalization** — project rules create normalized identifiers or derived relationships. These are marked as project modeling decisions.
5. **Build and publication** — deterministic builders assemble ontology/shapes and copy approved outputs to `build/` and `docs/`.
6. **Queries and UI** — bundled SPARQL and the browser query engine consume built artifacts.

## Trust boundaries

Downloaded data, replay logs, archives, RDF documents, and query text are untrusted. Acquisition is opt-in and network-free tests use synthetic fixtures. Raw inputs and local databases belong in ignored directories. Generated artifacts that include third-party facts remain subject to their source restrictions.

## Source versus inference

Use evidence artifacts and source references for externally asserted facts. Use an explicit project-inference marker or derivation link for computed relationships. Avoid `owl:sameAs` unless identity is justified. A normalized label, alias, inferred matchup, or replay reconstruction must not be described as official semantics.

## Reproducibility contract

A generated output is reproducible only when its manifest entry records ordered inputs, a command, tool/schema version, deterministic serialization, and redistribution status. Publication checks fail for missing metadata, forbidden private-file patterns, or non-canonical manifest ordering.
