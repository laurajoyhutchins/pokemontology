# Public-repository publication audit

Audit date: 2026-07-21  
Baseline commit: `a455d5e035af2712db3931e73af43818a8e88e4f`

## Scope reviewed

The audit reviewed the current README, license, manifest, package metadata, CI workflow, documented repository structure, ontology/SHACL architecture, ingestion and replay workflows described by the project, public documentation, representative generated RDF, and discoverable recent history. It classified project-authored code/modeling, external data adapters, generated outputs, replay material, and asset policy.

This is a technical and provenance audit, not legal advice or a claim of legal clearance.

## Material classifications

1. **Project-authored:** Python source, build/validation scripts, ontology modeling modules, SHACL shapes, bundled SPARQL, site code, and documentation, except where a file says otherwise.
2. **Third-party software:** runtime/development dependencies and upstream interoperability projects, under their own licenses.
3. **External structured data:** PokeAPI and Veekun inputs, whose source-code licenses do not automatically resolve all rights in delivered franchise data.
4. **Franchise material:** names, terms, facts, and generated representations that remain subject to third-party rights.
5. **Generated material:** assembled ontology, shapes, schema indexes, mechanics graphs, replay slices, and site data; these may combine project-authored structure with third-party facts.
6. **Unestablished basis:** third-party replay payloads and derived outputs containing private access data or user identifiers.

## Remediation

- Added a prominent unofficial-project and third-party-rights disclaimer.
- Limited the MIT license to project-authored material the author can license.
- Added source, third-party, asset, architecture, ontology, contribution, conduct, and security documentation.
- Replaced the stale manifest with a machine-readable source/artifact policy.
- Removed a tracked private Pokémon Showdown replay containing player identifiers, team details, chat, a private flag, and a password-bearing URL.
- Removed its derived replay slice, which repeated the private URL and player identifiers.
- Added synthetic fixtures for parser and RDF examples.
- Added publication-policy validation and CI coverage.
- Strengthened ignore rules and pinned workflow actions.

## Historical exposure

The removed replay and derived slice remain in Git history at earlier commits. This pull request does not rewrite history because doing so would disrupt existing clones and references. The exposure and removal reason are documented here. Repository owner review is still required to decide whether a coordinated history rewrite and credential/access invalidation is warranted.

## Remaining uncertainty

The audit did not establish a blanket redistribution basis for all franchise facts embedded in generated mechanics files. Existing generated outputs therefore require owner review before being described as freely redistributable. A follow-up issue tracks a file-by-file generated-output/source inventory and, where needed, removal from publication.
