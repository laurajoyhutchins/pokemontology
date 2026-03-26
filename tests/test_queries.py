"""Regression tests for bundled SPARQL queries and the query CLI."""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph

from pokemontology import cli
from pokemontology._script_loader import repo_path
from pokemontology.chat import validate_sparql_text


REPO = repo_path()
SUPER_EFFECTIVE_QUERY = REPO / "queries" / "super_effective_moves.sparql"


def _write_super_effective_fixture(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

pkm:Ruleset_PokeAPI_Default a pkm:Ruleset .

pkm:MyCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Charmander" .

pkm:OpponentCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Bulbasaur" ;
    pkm:representsSpecies pkm:Species_bulbasaur .

pkm:Action_Ember
    a pkm:MoveUseAction ;
    pkm:hasActor pkm:MyCombatant ;
    pkm:usesMove pkm:Move_ember .

pkm:Move_ember
    a pkm:Move ;
    pkm:hasName "Ember" .

pkm:Type_fire
    a pkm:Type ;
    pkm:hasName "Fire" .

pkm:Type_grass
    a pkm:Type ;
    pkm:hasName "Grass" .

pkm:MovePropertyAssignment_ember
    a pkm:MovePropertyAssignment ;
    pkm:aboutMove pkm:Move_ember ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:hasMoveType pkm:Type_fire .

pkm:Variant_bulbasaur
    a pkm:Variant ;
    pkm:belongsToSpecies pkm:Species_bulbasaur .

pkm:TypingAssignment_bulbasaur_grass
    a pkm:TypingAssignment ;
    pkm:aboutVariant pkm:Variant_bulbasaur ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:aboutType pkm:Type_grass .

pkm:TypeEffectivenessAssignment_fire_grass
    a pkm:TypeEffectivenessAssignment ;
    pkm:attackerType pkm:Type_fire ;
    pkm:defenderType pkm:Type_grass ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:hasDamageFactor "2.0"^^xsd:decimal .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_super_effective_moves_query_returns_expected_row(
    built_ontology_text: str, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    _write_super_effective_fixture(fixture_path)

    graph = Graph()
    graph.parse(data=built_ontology_text, format="turtle")
    graph.parse(fixture_path, format="turtle")

    rows = list(graph.query(SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")))

    assert len(rows) == 1
    row = rows[0]
    assert str(row.myMoveLabel) == "Ember"
    assert str(row.moveTypeName) == "Fire"
    assert str(row.opponentLabel) == "Bulbasaur"
    assert str(row.effectiveTypeName) == "Grass"
    assert str(row.factor) == "2.0"


def test_query_command_outputs_json_results(
    built_ontology_path: str, tmp_path: Path, capsys
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    _write_super_effective_fixture(fixture_path)

    exit_code = cli.main(
        [
            "query",
            str(SUPER_EFFECTIVE_QUERY),
            built_ontology_path,
            str(fixture_path),
            "--pretty",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["variables"] == [
        "myMoveLabel",
        "moveTypeName",
        "opponentLabel",
        "effectiveTypeName",
        "factor",
    ]
    assert output["rows"] == [
        {
            "myMoveLabel": "Ember",
            "moveTypeName": "Fire",
            "opponentLabel": "Bulbasaur",
            "effectiveTypeName": "Grass",
            "factor": "2.0",
        }
    ]


def test_load_turtle_sources_reuses_cached_graph(
    built_ontology_path: str, tmp_path: Path, monkeypatch: object
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    _write_super_effective_fixture(fixture_path)

    parse_calls = 0
    original_parse = Graph.parse

    def counting_parse(self, *args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(self, *args, **kwargs)

    monkeypatch.setattr(Graph, "parse", counting_parse)
    cli._TURTLE_SOURCE_CACHE.clear()

    sources = [Path(built_ontology_path), fixture_path]
    first = cli._load_turtle_sources(sources)
    second = cli._load_turtle_sources(sources)

    assert first is second
    assert parse_calls == 2


def test_ask_command_outputs_generated_sparql(capsys, monkeypatch: object) -> None:
    generated_query = SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "generate_sparql", lambda *args, **kwargs: generated_query)

    exit_code = cli.main(["ask", "Which of my moves are effective against Bulbasaur?"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "SELECT ?myMoveLabel ?moveTypeName ?opponentLabel" in output


def test_laurel_command_answers_from_generated_query(
    built_ontology_path: str, tmp_path: Path, capsys, monkeypatch: object
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    _write_super_effective_fixture(fixture_path)

    generated_query = SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "generate_sparql", lambda *args, **kwargs: generated_query)

    exit_code = cli.main(
        [
            "laurel",
            "Which of my moves are effective against Bulbasaur?",
            built_ontology_path,
            str(fixture_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Laurel found 1 matching row:" in output
    assert "myMoveLabel=Ember" in output


def test_laurel_command_can_emit_json(
    built_ontology_path: str, tmp_path: Path, capsys, monkeypatch: object
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    _write_super_effective_fixture(fixture_path)

    generated_query = SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "generate_sparql", lambda *args, **kwargs: generated_query)

    exit_code = cli.main(
        [
            "laurel",
            "Which of my moves are effective against Bulbasaur?",
            built_ontology_path,
            str(fixture_path),
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["answer"].startswith("Laurel found 1 matching row:")
    assert "SELECT ?myMoveLabel" in output["sparql"]


def test_validate_sparql_text_rejects_updates() -> None:
    try:
        validate_sparql_text("PREFIX pkm: <https://example.test#>\nDELETE WHERE { ?s ?p ?o }")
    except ValueError as exc:
        assert "forbidden update keywords" in str(exc)
    else:
        raise AssertionError("expected update SPARQL to be rejected")
