"""Regression checks for generated Professor Laurel schema-pack assets."""

from __future__ import annotations

import json

from pokemontology.build import build_ontology


def test_write_artifacts_emits_schema_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_ontology, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(build_ontology, "PAGES_ONTOLOGY", tmp_path / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SHAPES", tmp_path / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_POKEAPI", tmp_path / "pokeapi.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS", tmp_path / "mechanics.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SITE_DATA", tmp_path / "site-data.json")
    monkeypatch.setattr(build_ontology, "PAGES_SCHEMA_INDEX", tmp_path / "schema-index.json")
    monkeypatch.setattr(build_ontology, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(build_ontology, "OUTPUT", tmp_path / "build" / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SHAPES", tmp_path / "build" / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_POKEAPI", tmp_path / "build" / "pokeapi.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_VEEKUN", tmp_path / "build" / "veekun.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_MECHANICS", tmp_path / "build" / "mechanics.ttl")

    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "pokeapi.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n",
        encoding="utf-8",
    )
    (tmp_path / "build" / "veekun.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n",
        encoding="utf-8",
    )

    ontology_text, shapes_text, site_data = build_ontology.assemble_artifacts()
    build_ontology.write_artifacts(ontology_text, shapes_text, site_data)

    site_data = json.loads((tmp_path / "site-data.json").read_text(encoding="utf-8"))
    schema_index = json.loads((tmp_path / "schema-index.json").read_text(encoding="utf-8"))
    assert (tmp_path / "mechanics.ttl").exists()
    assert any(artifact["path"] == "mechanics.ttl" for artifact in site_data["artifacts"])
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
    assert "Species" in schema_index["validation"]["known_terms"]
    assert "actor" in schema_index["validation"]["known_terms"]
    assert "Ruleset_PokeAPI_Default" in schema_index["validation"]["known_terms"]
    assert schema_index["response"]["list_preview_limit"] == 5
    assert schema_index["inference"]["webllm_model"]
    assert any(item["label"] == "Species" for item in schema_index["items"])
    assert any(item["label"] == "TypingAssignment pattern" for item in schema_index["items"])
    assert any(example["id"] == "super-effective-moves" for example in schema_index["examples"])
    assert "species" in schema_index["sparse_index"]
    assert schema_index["item_norms"]
