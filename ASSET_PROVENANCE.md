# Asset provenance inventory

Audit date: 2026-07-21.

## Current policy

Pokemontology does not intentionally distribute official Pokémon logos, artwork, sprites, icons, screenshots, audio, proprietary fonts, game dumps, or extracted game assets. The public site should use project-authored HTML, CSS, text, and generic interface elements only.

| Asset class | Current intended status | Provenance requirement |
|---|---|---|
| Project UI HTML/CSS/JavaScript | project-authored | covered by the repository license boundary unless a file says otherwise |
| Generic icons | none intentionally bundled | identify author/source and license before addition |
| Pokémon artwork/sprites/logos | prohibited from contribution by default | owner permission or a documented redistribution license is required |
| Screenshots/audio/video/fonts | prohibited from contribution by default | source, rights holder, license/terms, and redistribution analysis required |
| Generated charts/diagrams | allowed when project-authored and source data is documented | record generating command and source manifest entries |

## Audit limitation

The current-tree audit reviewed documented repository paths and discoverable tracked files. Git history was sampled for relevant changes, but this document does not claim that every historical blob has been legally cleared. A private replay payload and a derived replay slice containing its access URL were removed from the current tree; the historical exposure is documented in `docs/publication-audit.md`. History was not rewritten by this pull request.
