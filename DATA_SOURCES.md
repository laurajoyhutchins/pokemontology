# Data sources and attribution

This inventory describes source adapters and checked-in fixtures as audited on 2026-07-21. It does not determine legal rights; it records what was verified and what remains uncertain.

| Source | URL/repository | License or stated terms | Version/retrieval | Transformations | Redistribution status | Uncertainty/restrictions |
|---|---|---|---|---|---|---|
| Project-authored ontology modules | this repository | MIT, subject to `LICENSE` boundary | repository commit | deterministic module assembly and schema-index generation | included | Does not license third-party labels or facts embedded in generated outputs. |
| Project-authored SHACL modules | this repository | MIT, subject to `LICENSE` boundary | repository commit | deterministic module assembly | included | Validates the project model, not official franchise semantics. |
| Synthetic battle fixture | `examples/fixtures/synthetic-battle.json` | MIT, project-authored | 2026-07-21 | parser and slice-generation tests | included | Uses invented participants/entities; not evidence of franchise behavior. |
| PokeAPI | https://github.com/PokeAPI/pokeapi and https://pokeapi.co/ | PokeAPI repository software: BSD-3-Clause | user-selected at retrieval time; not vendored | select, normalize, map identifiers, emit provenance-aware RDF | reference-only/local generation | No blanket redistribution basis was established for all API content or underlying franchise data. Do not commit raw/bulk responses by default. |
| Veekun Pokédex | https://github.com/veekun/pokedex | upstream repository license applies to covered upstream work | user-supplied revision; not vendored | select CSV tables, normalize identifiers, emit version-group-scoped RDF | reference-only/local generation | Source-code license may not cover all franchise facts/text. Record exact commit and terms for any proposed redistribution. |
| Pokémon Showdown replay protocol | https://github.com/smogon/pokemon-showdown | server software: MIT | user-selected revision | parse protocol events into project ontology | protocol reference only | Replay payloads are user content and may include personal data, chat, teams, or private access data. No third-party replay payload is distributed. |
| Pokémon Showdown client | https://github.com/smogon/pokemon-showdown-client | AGPL-3.0 for covered client code | not vendored | interoperability reference only | not distributed | Do not copy client code/assets into this repository without license review. |

## Required record for a new source

Every new imported source must add a `MANIFEST.json` entry containing:

- stable source identifier and name;
- source URL or repository;
- original license or stated usage terms, with a link;
- exact version, commit, release, or retrieval date;
- files/endpoints retrieved;
- transformations performed;
- whether raw input or generated output is checked in;
- redistribution status (`included`, `reference-only`, `local-only`, `quarantined`, or `owner-review-required`);
- uncertainty, restrictions, and reviewer notes.

A disclaimer is not a substitute for permission. When the redistribution basis cannot be established, keep the material out of the public tree and provide a retrieval adapter or a small synthetic fixture instead.
