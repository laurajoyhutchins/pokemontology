from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_publication", ROOT / "scripts" / "validate_publication.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_manifest_and_public_tree_pass_policy() -> None:
    manifest = MODULE.load_manifest(ROOT)
    assert MODULE.validate_manifest(manifest) == []
    assert MODULE.validate_tree(manifest, ROOT) == []


def test_manifest_requires_complete_source_metadata() -> None:
    manifest = {
        "manifest_version": "2.0",
        "sources": [{"id": "incomplete"}],
        "artifacts": [],
    }
    errors = MODULE.validate_manifest(manifest)
    assert any("license_or_terms" in error for error in errors)
    assert any("non-empty artifacts" in error for error in errors)


def test_private_replay_payload_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("x", encoding="utf-8")
    for path in MODULE.REQUIRED_FILES - {"LICENSE", "MANIFEST.json"}:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    manifest = {
        "manifest_version": "2.0",
        "sources": [],
        "artifacts": [],
        "forbidden_public_patterns": [],
    }
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    replay = tmp_path / "leak.json"
    replay.write_text('{"private": 1, "password": "secret"}', encoding="utf-8")
    errors = MODULE.validate_tree(manifest, tmp_path)
    assert any("sensitive/private replay marker" in error for error in errors)
