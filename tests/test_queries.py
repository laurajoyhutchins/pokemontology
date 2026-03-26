"""Regression tests for bundled SPARQL queries and the query CLI."""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph

from pokemontology import cli
from pokemontology.chat import validate_sparql_text
from tests.support import REPO
from tests.support.laurel import write_dense_schema_index, write_super_effective_fixture


SUPER_EFFECTIVE_QUERY = REPO / "queries" / "super_effective_moves.sparql"


def test_super_effective_moves_query_returns_expected_row(
    built_ontology_text: str, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    write_super_effective_fixture(fixture_path)

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
    write_super_effective_fixture(fixture_path)

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
    write_super_effective_fixture(fixture_path)

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


def test_ask_command_passes_retrieved_matches(capsys, monkeypatch: object, tmp_path: Path) -> None:
    schema_index = tmp_path / "schema-index.json"
    write_dense_schema_index(
        schema_index,
        vocabulary=["effective", "bulbasaur", "move"],
        vector=[1, 1, 1],
        item={
            "label": "Super-effective moves",
            "kind": "pattern",
            "summary": "Match a combatant move to a defender typing.",
            "snippet": "Which of my moves are effective against Bulbasaur?",
        },
    )

    captured_matches: list[dict[str, object]] | None = None
    generated_query = SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")

    def fake_generate_sparql(*args, **kwargs):
        nonlocal captured_matches
        captured_matches = kwargs.get("matches")
        return generated_query

    monkeypatch.setattr(cli, "generate_sparql", fake_generate_sparql)

    exit_code = cli.main(
        [
            "ask",
            "Which of my moves are effective against Bulbasaur?",
            "--schema-index",
            str(schema_index),
        ]
    )

    assert exit_code == 0
    assert captured_matches is not None
    assert captured_matches[0]["label"] == "Super-effective moves"
    output = capsys.readouterr().out
    assert "SELECT ?myMoveLabel ?moveTypeName ?opponentLabel" in output


def test_laurel_command_answers_from_generated_query(
    built_ontology_path: str, tmp_path: Path, capsys, monkeypatch: object
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    write_super_effective_fixture(fixture_path)

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
    write_super_effective_fixture(fixture_path)

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


def test_validate_sparql_text_rejects_malformed_read_only_query() -> None:
    try:
        validate_sparql_text(
            "PREFIX pkm: <https://example.test#>\nSELECT WHERE { ?s ?p ?o }"
        )
    except ValueError as exc:
        assert "failed formal parsing" in str(exc)
    else:
        raise AssertionError("expected malformed read-only SPARQL to be rejected")


def test_validate_sparql_text_rejects_select_star() -> None:
    try:
        validate_sparql_text(
            "PREFIX pkm: <https://example.test#>\nSELECT * WHERE { ?s ?p ?o } LIMIT 5"
        )
    except ValueError as exc:
        assert "SELECT * is too broad" in str(exc)
    else:
        raise AssertionError("expected SELECT * SPARQL to be rejected")


def test_validate_sparql_text_requires_bounded_select() -> None:
    try:
        validate_sparql_text(
            "PREFIX pkm: <https://example.test#>\nSELECT ?s WHERE { ?s ?p ?o }"
        )
    except ValueError as exc:
        assert "must include LIMIT or ORDER BY" in str(exc)
    else:
        raise AssertionError("expected unbounded SELECT SPARQL to be rejected")
