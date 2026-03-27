"""Regression checks for generated Professor Laurel schema-pack assets."""

from __future__ import annotations

import json

from pokemontology.build import build_ontology


def test_write_artifacts_emits_schema_index(tmp_path, monkeypatch) -> None:
    queries_dir = tmp_path / "queries" / "bundled"
    monkeypatch.setattr(build_ontology, "PAGES_DIR", tmp_path)
    monkeypatch.setattr(build_ontology, "PAGES_ONTOLOGY", tmp_path / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SHAPES", tmp_path / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_POKEAPI", tmp_path / "pokeapi.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS", tmp_path / "mechanics.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS_BASE", tmp_path / "mechanics-base.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS_CURRENT", tmp_path / "mechanics-learnsets-current.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS_MODERN", tmp_path / "mechanics-learnsets-modern.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_MECHANICS_LEGACY", tmp_path / "mechanics-learnsets-legacy.ttl")
    monkeypatch.setattr(build_ontology, "PAGES_SITE_DATA", tmp_path / "site-data.json")
    monkeypatch.setattr(build_ontology, "PAGES_SCHEMA_INDEX", tmp_path / "schema-index.json")
    monkeypatch.setattr(build_ontology, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(build_ontology, "OUTPUT", tmp_path / "build" / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SHAPES", tmp_path / "build" / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_POKEAPI", tmp_path / "build" / "pokeapi.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_VEEKUN", tmp_path / "build" / "veekun.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_MECHANICS", tmp_path / "build" / "mechanics.ttl")
    monkeypatch.setattr(build_ontology, "BUNDLED_QUERIES_DIR", queries_dir)

    (tmp_path / "build").mkdir()
    queries_dir.mkdir(parents=True)
    (tmp_path / "build" / "pokeapi.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n",
        encoding="utf-8",
    )
    (tmp_path / "build" / "veekun.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n",
        encoding="utf-8",
    )
    (queries_dir / "super_effective_moves.sparql").write_text(
        "# Super-effective move query\n"
        "# Requires: build/ontology.ttl + build/mechanics.ttl + a replay slice TTL\n"
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "ASK { ?assignment pkm:hasContext pkm:Ruleset_PokeAPI_Default . }\n",
        encoding="utf-8",
    )

    ontology_text, shapes_text, site_data = build_ontology.assemble_artifacts()
    build_ontology.write_artifacts(ontology_text, shapes_text, site_data)

    site_data = json.loads((tmp_path / "site-data.json").read_text(encoding="utf-8"))
    schema_index = json.loads((tmp_path / "schema-index.json").read_text(encoding="utf-8"))
    bundled_query = next(
        example
        for example in site_data["query_examples"]
        if example["source_path"] == "queries/bundled/super_effective_moves.sparql"
    )
    schema_example = next(
        example
        for example in schema_index["examples"]
        if example["id"] == "super-effective-moves"
    )
    assert (tmp_path / "mechanics-base.ttl").exists()
    assert (tmp_path / "mechanics-learnsets-current.ttl").exists()
    assert (tmp_path / "mechanics-learnsets-modern.ttl").exists()
    assert (tmp_path / "mechanics-learnsets-legacy.ttl").exists()
    assert any(artifact["path"] == "mechanics-base.ttl" for artifact in site_data["artifacts"])
    assert any(source["id"] == "src-mechanics" for source in site_data["query_sources"])
    mechanics_source = next(source for source in site_data["query_sources"] if source["id"] == "src-mechanics")
    assert mechanics_source["paths"] == [
        "mechanics-base.ttl",
        "mechanics-learnsets-current.ttl",
        "mechanics-learnsets-modern.ttl",
        "mechanics-learnsets-legacy.ttl",
    ]
    assert "build/mechanics.ttl" in bundled_query["query"]
    assert "build/pokeapi.ttl" not in bundled_query["query"]
    assert "build/mechanics.ttl" in bundled_query["command"]
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
    assert schema_example
    assert "build/mechanics.ttl" in schema_example["query"]
    assert "build/pokeapi.ttl" not in schema_example["query"]
    assert "species" in schema_index["sparse_index"]
    assert schema_index["item_norms"]
