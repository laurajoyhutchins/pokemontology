"""Regression checks for generated Professor Laurel schema-pack assets."""

from __future__ import annotations

import json

from pokemontology.build import build_ontology


def test_write_artifacts_emits_schema_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_ontology, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(build_ontology, "PAGES_ONTOLOGY", tmp_path / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SHAPES", tmp_path / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SITE_DATA", tmp_path / "site-data.json")
    monkeypatch.setattr(build_ontology, "PAGES_SCHEMA_INDEX", tmp_path / "schema-index.json")
    monkeypatch.setattr(build_ontology, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(build_ontology, "OUTPUT", tmp_path / "build" / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SHAPES", tmp_path / "build" / "shapes.ttl")

    ontology_text, shapes_text, site_data = build_ontology.assemble_artifacts()
    build_ontology.write_artifacts(ontology_text, shapes_text, site_data)

    schema_index = json.loads((tmp_path / "schema-index.json").read_text(encoding="utf-8"))
    assert schema_index["prefixes"]
    assert schema_index["retrieval"]["top_k"] == 4
    assert schema_index["retrieval"]["minimum_scores"][0] == {
        "max_tokens": 2,
        "score": 0.34,
    }
    assert schema_index["validation"]["allowed_query_types"] == [
        "SELECT",
        "ASK",
        "DESCRIBE",
        "CONSTRUCT",
    ]
    assert "SERVICE" in schema_index["validation"]["forbidden_keywords"]
    assert any(item["label"] == "Species" for item in schema_index["items"])
    assert any(item["label"] == "TypingAssignment pattern" for item in schema_index["items"])
    assert any(example["id"] == "super-effective-moves" for example in schema_index["examples"])
