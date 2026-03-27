"""Regression tests for bundled SPARQL queries and the query CLI."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rdflib import Graph
from rdflib.namespace import RDF

from pokemontology import cli
from pokemontology.chat import (
    LaurelIntent,
    build_prompt,
    compile_intent,
    generate_sparql,
    parse_intent,
    validate_sparql_text,
)
from tests.support import REPO
from tests.support.laurel import write_dense_schema_index, write_super_effective_fixture


SUPER_EFFECTIVE_QUERY = REPO / "queries" / "bundled" / "super_effective_moves.sparql"
PKM_PREFIX_TERM_RE = re.compile(r"\bpkm:([A-Za-z_][\w-]*)\b")


def _declared_pkm_terms(graph: Graph) -> set[str]:
    declared: set[str] = set()
    for subject in graph.subjects(RDF.type, None):
        subject_text = str(subject)
        if "#" not in subject_text:
            continue
        namespace, local = subject_text.rsplit("#", 1)
        if namespace != "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl":
            continue
        declared.add(local)
    return declared


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


def test_bundled_super_effective_query_only_uses_declared_ontology_terms(
    ontology_graph: Graph,
) -> None:
    declared = _declared_pkm_terms(ontology_graph)
    used = {
        term
        for term in PKM_PREFIX_TERM_RE.findall(SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8"))
        if "_" not in term
    }
    assert used <= declared, sorted(used - declared)


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


def test_build_prompt_includes_concrete_transformation_patterns() -> None:
    prompt = build_prompt("Is Charizard a Fire type?")
    assert "CONCRETE TRANSFORMATION PATTERNS:" in prompt
    assert "Boolean species typing questions" in prompt
    assert "Species matchup questions" in prompt
    assert "Replay combat questions" in prompt
    assert "Every projected SELECT variable must be bound" in prompt
    assert "Every SELECT must be bounded with ORDER BY, LIMIT, or both." in prompt


def test_generate_sparql_uses_deterministic_species_type_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql("Is Charizard a Fire type?")

    assert 'pkm:hasName "Charizard"' in query_text
    assert 'pkm:hasName "Fire"' in query_text
    assert "ASK {" in query_text


def test_generate_sparql_uses_deterministic_species_matchup_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql("Which move types are super effective against Charizard?")

    assert 'pkm:hasName "Charizard"' in query_text
    assert "SELECT ?moveTypeName" in query_text
    assert "ORDER BY ?moveTypeName" in query_text


def test_parse_intent_maps_paraphrases_to_same_burn_intent() -> None:
    canonical = parse_intent("Does burn reduce the damage a Pokemon deals with physical moves?")
    paraphrase = parse_intent("Can burn cut the power of physical attacks?")

    assert canonical == LaurelIntent(kind="burn_physical_damage")
    assert paraphrase == canonical


def test_parse_intent_maps_paraphrases_to_same_levitate_intent() -> None:
    canonical = parse_intent("Does Levitate make a Pokemon immune to Ground-type moves?")
    paraphrase = parse_intent("Is a Pokemon with Levitate immune to Ground-type attacks?")

    assert canonical == LaurelIntent(kind="levitate_ground_immunity")
    assert paraphrase == canonical


def test_compile_intent_produces_same_query_for_burn_paraphrases() -> None:
    left = compile_intent(parse_intent("Does burn reduce the damage a Pokemon deals with physical moves?"))
    right = compile_intent(parse_intent("Can burn cut the power of physical attacks?"))

    assert left == right
    assert left is not None
    assert "SELECT ?answerText" in left


def test_compile_intent_produces_same_query_for_levitate_paraphrases() -> None:
    left = compile_intent(parse_intent("Does Levitate make a Pokemon immune to Ground-type moves?"))
    right = compile_intent(parse_intent("Is a Pokemon with Levitate immune to Ground-type attacks?"))

    assert left == right
    assert left is not None
    assert "Thousand Arrows" in left


def test_generate_sparql_uses_deterministic_move_type_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql("Is Freeze-Dry super effective against Water-types?")

    assert 'pkm:hasName "Freeze-Dry"' in query_text
    assert 'pkm:hasName "Water"' in query_text
    assert "SELECT ?answerText" in query_text
    assert "Freeze-Dry is super effective against Water-type Pokemon" in query_text


def test_generate_sparql_preserves_thunder_wave_move_name(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "Can Thunder Wave paralyze a Ground-type target in the main series?"
    )

    assert 'pkm:hasName "Thunder Wave"' in query_text
    assert 'pkm:hasName "Thunder"' not in query_text
    assert "SELECT ?answerText" in query_text


def test_generate_sparql_uses_deterministic_ability_exception_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "If a Mold Breaker user uses Earthquake on a target with Levitate, can Earthquake hit?"
    )

    assert "SELECT ?answerText" in query_text
    assert 'pkm:hasName "Mold Breaker"' in query_text
    assert 'pkm:hasName "Earthquake"' in query_text
    assert 'pkm:hasName "Levitate"' in query_text


def test_generate_sparql_uses_deterministic_generation_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "Starting in Generation VI, are Fairy-types immune to Dragon-type moves?"
    )

    assert "SELECT ?answerText" in query_text
    assert 'pkm:hasName "X Y"' in query_text
    assert 'pkm:hasName "Scarlet Violet"' in query_text
    assert 'pkm:hasName "Fairy"' in query_text
    assert 'pkm:hasName "Dragon"' in query_text


def test_generate_sparql_uses_deterministic_hard_levitate_bypass_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "Name two ways a Pokemon with Levitate can still be hit by Ground-type moves."
    )

    assert "SELECT ?answerText" in query_text
    assert 'VALUES ?answerText { "Gravity" "Mold Breaker" }' in query_text
    assert "LIMIT 2" in query_text


def test_generate_sparql_uses_deterministic_hard_thousand_arrows_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "What happens when Thousand Arrows hits a Flying-type or Levitate target?"
    )

    assert 'pkm:hasName "Thousand Arrows"' in query_text
    assert "SELECT ?answerText" in query_text
    assert "grounds the target until it switches out" in query_text


def test_generate_sparql_uses_deterministic_hard_freeze_dry_dual_type_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql("How effective is Freeze-Dry against a Water/Ground Pokemon?")

    assert 'pkm:hasName "Freeze-Dry"' in query_text
    assert 'pkm:hasName "Water"' in query_text
    assert 'pkm:hasName "Ground"' in query_text
    assert "SELECT ?answerText" in query_text
    assert "4x effective" in query_text


def test_generate_sparql_uses_deterministic_hard_wide_guard_persistence_pattern(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.chat.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not be called")),
    )

    query_text = generate_sparql(
        "If the user of Wide Guard faints later in the turn, does the protection still remain for that turn?"
    )

    assert "SELECT ?answerText" in query_text
    assert 'pkm:hasName "Wide Guard"' in query_text
    assert "remains active for the rest of the turn" in query_text


def test_laurel_summarizer_returns_curated_answer_text() -> None:
    from pokemontology.laurel import summarize_results

    answer = summarize_results(
        "Does Levitate make a Pokemon immune to Ground-type moves?",
        {
            "variables": ["answerText"],
            "rows": [
                {
                    "answerText": "Yes. Levitate gives immunity to Ground-type moves, with special exceptions such as Thousand Arrows."
                }
            ],
        },
    )

    assert answer.startswith("Yes. Levitate gives immunity")


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


def test_validate_sparql_text_allows_move_terms_without_treating_them_as_update_keywords() -> None:
    query = """PREFIX pkm: <https://example.test#>

ASK {
  ?attackEntity a pkm:Move .
  ?assignment a pkm:MovePropertyAssignment ;
              pkm:aboutMove ?attackEntity .
}"""

    assert validate_sparql_text(query) == query
