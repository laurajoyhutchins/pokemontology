#!/usr/bin/env python3
"""Validate public-repository licensing, provenance, and fixture policy."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SOURCE_FIELDS = {
    "id", "name", "url", "license_or_terms", "version_or_retrieval",
    "transformations", "redistribution_status", "uncertainty",
}
REQUIRED_ARTIFACT_FIELDS = {
    "path", "classification", "inputs", "command", "tool_and_schema_version",
    "checked_in", "generated", "redistribution_status",
}
REQUIRED_FILES = {
    "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "DATA_SOURCES.md",
    "ASSET_PROVENANCE.md", "SECURITY.md", "CONTRIBUTING.md", "MANIFEST.json",
}
SENSITIVE_TEXT = (
    '"private": 1',
    '"password":',
)


def load_manifest(root: Path = ROOT) -> dict[str, Any]:
    return json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("manifest_version") != "2.0":
        errors.append("MANIFEST.json must use manifest_version 2.0")
    sources = manifest.get("sources")
    artifacts = manifest.get("artifacts")
    if not isinstance(sources, list) or not sources:
        errors.append("MANIFEST.json must contain a non-empty sources list")
        sources = []
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("MANIFEST.json must contain a non-empty artifacts list")
        artifacts = []

    source_ids: list[str] = []
    for index, source in enumerate(sources):
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
        if missing:
            errors.append(f"sources[{index}] missing: {', '.join(missing)}")
        source_ids.append(str(source.get("id", "")))
    if source_ids != sorted(source_ids):
        errors.append("sources must be sorted by id for deterministic serialization")
    if len(source_ids) != len(set(source_ids)):
        errors.append("source ids must be unique")

    artifact_paths: list[str] = []
    for index, artifact in enumerate(artifacts):
        missing = sorted(REQUIRED_ARTIFACT_FIELDS - set(artifact))
        if missing:
            errors.append(f"artifacts[{index}] missing: {', '.join(missing)}")
        artifact_paths.append(str(artifact.get("path", "")))
    if artifact_paths != sorted(artifact_paths):
        errors.append("artifacts must be sorted by path for deterministic serialization")
    if len(artifact_paths) != len(set(artifact_paths)):
        errors.append("artifact paths must be unique")
    return errors


def iter_public_text_files(root: Path = ROOT):
    excluded = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build"}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf"}:
            continue
        yield path


def validate_tree(manifest: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for required in sorted(REQUIRED_FILES):
        if not (root / required).is_file():
            errors.append(f"required publication file missing: {required}")

    patterns = manifest.get("forbidden_public_patterns", [])
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in patterns):
            errors.append(f"forbidden public path: {rel}")

    for path in iter_public_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root).as_posix()
        for marker in SENSITIVE_TEXT:
            if marker in text and rel not in {"scripts/validate_publication.py", "tests/test_publication_policy.py"}:
                errors.append(f"sensitive/private replay marker in {rel}: {marker}")
    return errors


def main() -> int:
    try:
        manifest = load_manifest()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"publication validation failed: {exc}", file=sys.stderr)
        return 1
    errors = validate_manifest(manifest) + validate_tree(manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("publication policy validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
