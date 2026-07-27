# Third-party notices

This document records third-party projects and rights boundaries relevant to Pokemontology. It is not a legal-clearance statement.

## Franchise material

Pokémon names, characters, species, moves, abilities, items, locations, game text, artwork, sprites, logos, audiovisual material, and other franchise content may be protected by copyright, trademark, or other rights owned by Nintendo, Game Freak, Creatures Inc., The Pokémon Company, and other rights holders.

Pokemontology is unofficial and independent. No project license grants permission to use franchise material. The repository avoids official logos, artwork, sprites, screenshots, audio, fonts, and game dumps. Small terms or structured facts may appear where needed for interoperability, research fixtures, or source mapping; their presence does not imply ownership or official status.

## PokeAPI

- Project: PokeAPI
- Source: https://github.com/PokeAPI/pokeapi and https://pokeapi.co/
- Upstream software license observed during the 2026-07-21 audit: BSD-3-Clause for the PokeAPI repository.
- Use here: optional adapter and user-directed retrieval of structured API responses.
- Boundary: the upstream software license does not by itself establish that every API response, franchise name, description, or underlying datum may be redistributed under BSD-3-Clause.
- Repository policy: raw responses and bulk generated mechanics outputs are local build inputs/outputs and are not accepted as committed source unless a separate redistribution basis is documented.

## Veekun Pokédex

- Project: veekun/pokedex
- Source: https://github.com/veekun/pokedex
- Upstream license/terms: repository software and original project contributions identify an open-source license; the repository also contains structured franchise data whose independent redistribution basis may differ or remain uncertain.
- Use here: optional adapter for a user-supplied checkout/export.
- Boundary: do not treat the source-code license as a blanket license for franchise data or prose.
- Repository policy: no bulk Veekun export is distributed as part of Pokemontology's project-authored MIT material.

## Pokémon Showdown

- Projects: Pokémon Showdown server and client
- Sources: https://github.com/smogon/pokemon-showdown and https://github.com/smogon/pokemon-showdown-client
- Upstream software licenses observed during the 2026-07-21 audit: MIT for the server; AGPL-3.0 for the client.
- Use here: replay protocol interoperability and optional user-directed replay processing.
- Boundary: software licenses do not automatically grant redistribution rights to user-created replay content, chat, usernames, private access URLs, teams, or franchise data.
- Repository policy: private or third-party replay payloads must not be committed. Tests use synthetic fixtures.

## Python dependencies

Runtime and development dependencies are declared in `pyproject.toml` and requirements files. Each dependency remains under its own license. Dependency metadata and vulnerability status should be reviewed through automated dependency updates and `pip-audit`; inclusion as a dependency does not relicense it under Pokemontology's MIT terms.

## Generated outputs

Generated RDF, indexes, and site data can combine project-authored structure with third-party facts or labels. A generated file is not automatically wholly project-authored. Consult `MANIFEST.json` for source inputs and redistribution status before copying it.
