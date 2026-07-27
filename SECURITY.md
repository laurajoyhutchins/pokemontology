# Security policy

## Supported version

Security fixes target the current `main` branch. This research project does not currently promise long-term support for released versions.

## Reporting a vulnerability or privacy exposure

Use GitHub's private vulnerability reporting for this repository when available. Do not open a public issue containing credentials, private replay URLs, access tokens, personal data, unpublished datasets, or exploit details.

Include the affected commit/path, reproduction steps, impact, and a minimal safe example. The maintainer will acknowledge and triage reports as capacity permits; no fixed response-time guarantee is offered.

## Security boundaries

- Treat replay payloads, query logs, downloaded archives, API responses, and local databases as untrusted.
- Do not commit `.env` files, credentials, browser profiles, private source exports, or private replay links.
- Acquisition commands must use bounded requests, timeouts, response-size limits, and explicit output directories.
- Archive extraction must reject absolute paths, `..` traversal, links, and writes outside the selected destination.
- RDF parsing and validation must not dereference remote resources implicitly.
- Tests must not require uncontrolled network access.
- Query engines should impose graph-size, timeout, and result-size limits when exposed to untrusted input.

See `CONTRIBUTING.md` for source and asset restrictions.
