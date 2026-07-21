# Ontology contribution and naming guidelines

## Namespace policy

The published project namespace is `https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#`. Project terms use this namespace. External identifiers remain external references rather than being silently recast as project-owned terms.

## Canonical identifiers

Canonical identifiers are stable project identifiers selected for engineering consistency. They are not claims about official franchise identifiers or terminology. Use ASCII-safe, deterministic identifiers; do not derive identity solely from a display label.

## Labels and aliases

- `rdfs:label` is a display label, not the identifier.
- Preserve source spellings as provenance-bearing source values.
- Store alternate labels as aliases rather than silently replacing canonical identifiers.
- Do not use an alias to assert identity between distinct source entities.
- Franchise terminology is quoted or referenced as source terminology, not adopted as an official project definition.

## Language tags

Human-readable labels and descriptions should use BCP 47 language tags when language is known. Do not invent translations. Untagged literals are allowed for source values whose language is unknown.

## Assertions and inferences

Externally sourced assertions must link to an evidence/source artifact. Computed, normalized, or inferred relationships must identify the project rule or transformation that produced them. Never present a project inference as an official rule.

## Versioning and deprecation

Ontology releases follow semantic versioning for project contracts:

- patch: compatible documentation, validation, or implementation fixes;
- minor: additive terms or compatible modeling capabilities;
- major: incompatible identifier or semantic changes.

Deprecated terms remain resolvable for at least one minor release when practical, carry a deprecation marker, identify their replacement, and include migration notes. Do not silently reuse a deprecated identifier for a new meaning.

## Validation

Required checks include Turtle/RDF parsing, SHACL validation, namespace and identifier checks, deterministic builds, manifest validation, and representative SPARQL tests. The expected reasoning profile is conservative RDF/OWL usage plus explicit application transformations; consumers must not assume a complete OWL DL reasoner or closed-world semantics.

## Quality limitations

External data can be incomplete, inconsistent, version-dependent, or stale. Replay-derived state is observational and may omit hidden information. Source mappings and normalization are project decisions. Conflicting assertions should remain traceable rather than being collapsed without evidence.
