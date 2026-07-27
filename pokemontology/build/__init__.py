"""Build and validation implementations with public-publication safeguards."""

from __future__ import annotations

from . import build_ontology as build_ontology

_UNOFFICIAL_DISCLAIMER = (
    "Unofficial independent fan, research, and data-engineering project; not "
    "affiliated with, endorsed by, sponsored by, or approved by Nintendo, Game "
    "Freak, Creatures Inc., or The Pokémon Company, and not an official source "
    "of franchise facts, rules, terminology, or game data."
)
_LEGACY_PUBLICATION_PATH = "mechanics-learnsets-legacy.ttl"

# The historical learnset slice is a bulk generated franchise-data artifact whose
# public redistribution basis has not been established. Keep local generation
# capabilities in the ingestion pipeline, but do not publish that slice from the
# ordinary project build.
build_ontology.WEB_MECHANICS_SLICES = tuple(
    entry
    for entry in build_ontology.WEB_MECHANICS_SLICES
    if entry.get("path") != _LEGACY_PUBLICATION_PATH
)


def _public_web_mechanics_slice_paths() -> dict[str, object]:
    return {
        "base": build_ontology.PAGES_MECHANICS_BASE,
        "current": build_ontology.PAGES_MECHANICS_CURRENT,
        "modern": build_ontology.PAGES_MECHANICS_MODERN,
    }


build_ontology._web_mechanics_slice_paths = _public_web_mechanics_slice_paths

_original_assemble_artifacts = build_ontology.assemble_artifacts
_original_write_artifacts = build_ontology.write_artifacts


def _assemble_public_artifacts() -> tuple[str, str, dict[str, object]]:
    ontology_text, shapes_text, site_data = _original_assemble_artifacts()

    site = site_data.get("site")
    if isinstance(site, dict):
        site["tagline"] = "An unofficial ontology and data-engineering research toolkit."
        site["disclaimer"] = _UNOFFICIAL_DISCLAIMER

    artifacts = site_data.get("artifacts")
    if isinstance(artifacts, list):
        site_data["artifacts"] = [
            artifact
            for artifact in artifacts
            if not (
                isinstance(artifact, dict)
                and artifact.get("path") == _LEGACY_PUBLICATION_PATH
            )
        ]

    query_sources = site_data.get("query_sources")
    if isinstance(query_sources, list):
        for source in query_sources:
            if not isinstance(source, dict):
                continue
            paths = source.get("paths")
            if isinstance(paths, list):
                source["paths"] = [
                    path for path in paths if path != _LEGACY_PUBLICATION_PATH
                ]
            if source.get("id") == "src-mechanics-archive":
                source["label"] = "review-pending modern learnset archive"

    site_data["examples"] = [
        {
            "name": "Synthetic replay JSON",
            "path": "examples/fixtures/synthetic-battle.json",
            "kind": "Project-authored synthetic fixture",
            "summary": "Invented replay-shaped input used for parser and privacy-safe regression coverage.",
        },
        {
            "name": "Synthetic battle slice",
            "path": "examples/fixtures/synthetic-battle-slice.ttl",
            "kind": "Project-authored synthetic Turtle fixture",
            "summary": "A small provenance-marked graph that does not reproduce a third-party replay.",
        },
        {
            "name": "Seed fixture",
            "path": "examples/fixtures/froakie-caterpie-seed.ttl",
            "kind": "Fixture data",
            "summary": "Compact research fixture retained for ontology tests; third-party terminology remains subject to the repository license boundary.",
        },
        {
            "name": "PokeAPI seed config",
            "path": "examples/pokeapi/seed-config.json",
            "kind": "Retrieval configuration",
            "summary": "A configuration reference for user-directed local retrieval; it is not a bundled dataset.",
        },
    ]

    pipelines = site_data.get("pipelines")
    if isinstance(pipelines, list):
        for pipeline in pipelines:
            if isinstance(pipeline, dict) and pipeline.get("name") == "Replay ingestion":
                pipeline["summary"] = (
                    "Transform user-supplied replay JSON into ontology slices after "
                    "privacy, source, and redistribution review."
                )

    return ontology_text, shapes_text, site_data


def _write_public_artifacts(
    ontology_text: str,
    shapes_text: str,
    site_data: dict[str, object],
) -> None:
    _original_write_artifacts(ontology_text, shapes_text, site_data)
    build_ontology.PAGES_MECHANICS_LEGACY.unlink(missing_ok=True)


build_ontology.assemble_artifacts = _assemble_public_artifacts
build_ontology.write_artifacts = _write_public_artifacts

__all__ = ["build_ontology"]
