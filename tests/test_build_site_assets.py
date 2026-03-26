"""Regression checks for generated Professor Laurel schema-pack assets."""

from __future__ import annotations

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

    schema_index = (tmp_path / "schema-index.json").read_text(encoding="utf-8")
    assert '"prefixes"' in schema_index
    assert '"Species"' in schema_index
    assert '"Canonical ontological species identity' in schema_index
    assert '"TypingAssignment pattern"' in schema_index
    assert '"super-effective-moves"' in schema_index
