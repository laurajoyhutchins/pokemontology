# Contributing

Contributions are welcome when they are reproducible, narrowly scoped, and compatible with the repository's public-data policy.

## Before opening a pull request

1. Open or reference a repository issue for substantial changes.
2. Keep ontology source, external source assertions, and project inferences distinct.
3. Add tests before changing behavior.
4. Run:
   ```bash
   python3 -m pytest
   python3 -m pokemontology build
   python3 scripts/validate_publication.py
   git diff --exit-code
   ```
5. Complete the provenance checklist in the pull-request template.

## Data and asset rules

Do not submit:

- copyrighted artwork, sprites, logos, screenshots, audio, proprietary fonts, or game dumps;
- copied game text, strategy-guide text, wiki prose, or documentation;
- leaked, private, access-controlled, or unpublished material;
- private replay payloads, replay passwords/tokens, chat logs, browser profiles, or user identifiers;
- bulk API responses, source exports, or generated corpora without a documented redistribution basis;
- code copied from another project without preserving its license and attribution.

Every proposed source or asset must identify its name, URL/repository, license or stated terms, exact version/retrieval date, transformations, redistribution status, and known uncertainty. When rights are unclear, add an adapter or synthetic fixture instead of committing the material.

## Ontology contributions

Follow `docs/ontology-guidelines.md`. Canonical identifiers are project identifiers, not declarations of official terminology. Use language-tagged display labels where appropriate, preserve aliases as aliases, and attach provenance to source assertions. Clearly label project inferences and normalization choices.

## Generated files

Do not edit generated artifacts directly. Change source modules or generation code, rebuild, and commit the deterministic result. `MANIFEST.json` must be updated when source inputs or redistribution status changes.
