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
    monkeypatch.setattr(build_ontology, "PAGES_GRAPH_INDEX", tmp_path / "graph-index.json")
    monkeypatch.setattr(build_ontology, "PAGES_SPARQL_REFERENCE", tmp_path / "sparql-reference.md")
    monkeypatch.setattr(build_ontology, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(build_ontology, "OUTPUT", tmp_path / "build" / "ontology.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SHAPES", tmp_path / "build" / "shapes.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SPARQL_REFERENCE", tmp_path / "build" / "sparql-reference.md")
    monkeypatch.setattr(build_ontology, "BUILD_POKEAPI", tmp_path / "build" / "pokeapi.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_VEEKUN", tmp_path / "build" / "veekun.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_SHOWDOWN", tmp_path / "build" / "showdown.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_MECHANICS", tmp_path / "build" / "mechanics.ttl")
    monkeypatch.setattr(build_ontology, "BUILD_ENTITY_INDEX", tmp_path / "build" / "entity-index.json")
    monkeypatch.setattr(build_ontology, "BUNDLED_QUERIES_DIR", queries_dir)

    (tmp_path / "build").mkdir()
    queries_dir.mkdir(parents=True)
    (tmp_path / "build" / "pokeapi.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n"
        "\n"
        "pkm:Species_froakie a pkm:Species ;\n"
        "  pkm:hasName \"Froakie\" ;\n"
        "  pkm:hasIdentifier \"pokeapi:species:froakie\" .\n"
        "\n"
        "<https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> a pkm:Ruleset ;\n"
        "  pkm:hasName \"PokeAPI Default (Current Generation)\" .\n"
        "\n"
        "pkm:Type_water a pkm:Type ;\n"
        "  pkm:hasName \"Water\" ;\n"
        "  pkm:hasIdentifier \"pokeapi:type:water\" .\n"
        "\n"
        "pkm:Ability_torrent a pkm:Ability ;\n"
        "  pkm:hasName \"Torrent\" ;\n"
        "  pkm:hasIdentifier \"pokeapi:ability:torrent\" .\n"
        "\n"
        "pkm:Move_bubble a pkm:Move ;\n"
        "  pkm:hasName \"Bubble\" ;\n"
        "  pkm:hasIdentifier \"pokeapi:move:bubble\" .\n"
        "\n"
        "pkm:TypingAssignment_froakie a pkm:TypingAssignment ;\n"
        "  pkm:aboutPokemon pkm:Species_froakie ;\n"
        "  pkm:aboutType pkm:Type_water ;\n"
        "  pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;\n"
        "  pkm:hasTypeSlot 1 .\n"
        "\n"
        "pkm:AbilityAssignment_froakie a pkm:AbilityAssignment ;\n"
        "  pkm:aboutPokemon pkm:Species_froakie ;\n"
        "  pkm:aboutAbility pkm:Ability_torrent ;\n"
        "  pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> .\n"
        "\n"
        "pkm:MovePropertyAssignment_bubble a pkm:MovePropertyAssignment ;\n"
        "  pkm:aboutMove pkm:Move_bubble ;\n"
        "  pkm:hasMoveType pkm:Type_water ;\n"
        "  pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> .\n"
        "\n"
        "pkm:MoveLearnRecord_froakie_bubble a pkm:MoveLearnRecord ;\n"
        "  pkm:aboutPokemon pkm:Species_froakie ;\n"
        "  pkm:learnableMove pkm:Move_bubble ;\n"
        "  pkm:isLearnableInRuleset true ;\n"
        "  pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> .\n",
        encoding="utf-8",
    )
    (tmp_path / "build" / "veekun.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n",
        encoding="utf-8",
    )
    (tmp_path / "build" / "showdown.ttl").write_text(
        "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n"
        "pkm:Battle_test a pkm:Battle .\n",
        encoding="utf-8",
    )
    (queries_dir / "super_effective_moves.sparql").write_text(
        "# Super-effective move query\n"
        "# Requires: build/ontology.ttl + build/mechanics.ttl + a replay slice TTL\n"
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "ASK { ?assignment pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> . }\n",
        encoding="utf-8",
    )

    ontology_text, shapes_text, site_data = build_ontology.assemble_artifacts()
    build_ontology.write_artifacts(ontology_text, shapes_text, site_data)

    site_data = json.loads((tmp_path / "site-data.json").read_text(encoding="utf-8"))
    schema_index = json.loads((tmp_path / "schema-index.json").read_text(encoding="utf-8"))
    graph_index = json.loads((tmp_path / "graph-index.json").read_text(encoding="utf-8"))
    entity_index = json.loads((tmp_path / "build" / "entity-index.json").read_text(encoding="utf-8"))
    sparql_reference = (tmp_path / "sparql-reference.md").read_text(encoding="utf-8")
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
    assert any(artifact["path"] == "graph-index.json" for artifact in site_data["artifacts"])
    assert any(source["id"] == "src-mechanics" for source in site_data["query_sources"])
    mechanics_source = next(source for source in site_data["query_sources"] if source["id"] == "src-mechanics")
    assert mechanics_source["paths"] == [
        "mechanics-base.ttl",
        "mechanics-learnsets-current.ttl",
    ]
    assert mechanics_source["checked"] is True
    archive_source = next(
        source
        for source in site_data["query_sources"]
        if source["id"] == "src-mechanics-archive"
    )
    assert archive_source["paths"] == [
        "mechanics-learnsets-modern.ttl",
        "mechanics-learnsets-legacy.ttl",
    ]
    assert archive_source["checked"] is False
    assert "pkm:Battle_test a pkm:Battle ." in (tmp_path / "build" / "mechanics.ttl").read_text(
        encoding="utf-8"
    )
    assert not any(
        entity["curie"] == "pkm:Battle_test" for entity in entity_index["entities"]
    )
    assert "build/mechanics.ttl" in bundled_query["query"]
    assert "build/pokeapi.ttl" not in bundled_query["query"]
    assert "build/mechanics.ttl" in bundled_query["command"]
    assert "@prefix pkmi: <https://laurajoyhutchins.github.io/pokemontology/id/> ." in (
        tmp_path / "build" / "mechanics.ttl"
    ).read_text(encoding="utf-8")
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
    assert "Ruleset" in schema_index["validation"]["known_terms"]
    assert schema_index["response"]["list_preview_limit"] == 5
    assert schema_index["inference"]["webllm_model"]
    assert any(item["label"] == "Species" for item in schema_index["items"])
    assert any(item["label"] == "TypingAssignment pattern" for item in schema_index["items"])
    assert schema_example
    assert "build/mechanics.ttl" in schema_example["query"]
    assert "build/pokeapi.ttl" not in schema_example["query"]
    assert "species" in schema_index["sparse_index"]
    assert schema_index["item_norms"]
    assert entity_index["source"].endswith("build/mechanics.ttl")
    assert graph_index["source"].endswith("build/mechanics.ttl")
    assert graph_index["node_count"] >= 3
    assert graph_index["edge_count"] >= 1
    assert "belongsToSpecies" in graph_index["edge_kinds"]
    assert any(node["type"] == "Ruleset" for node in graph_index["nodes"])
    assert any(edge["kind"] == "availableIn" for edge in graph_index["edges"])
    assert isinstance(entity_index["entity_count"], int)
    assert isinstance(entity_index["entities"], list)
    assert isinstance(entity_index["rulesets"], list)
    assert "# Pokemontology SPARQL Reference" in sparql_reference
    assert "## Prefixes" in sparql_reference
    assert "`pkm:`" in sparql_reference
    assert "### TypingAssignment pattern" in sparql_reference
    assert "queries/bundled/super_effective_moves.sparql" in sparql_reference
