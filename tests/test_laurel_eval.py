"""Tests for the Laurel evaluation harness."""

from __future__ import annotations

from pokemontology import cli
from pokemontology.laurel_eval import EvalConfig, evaluate_suite
from tests._laurel_support import (
    write_charizard_fire_source,
    write_dense_schema_index,
    write_eval_suite,
)


def test_evaluate_suite_marks_mechanics_as_partial_when_query_is_generated(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(
        "pokemontology.laurel_eval.generate_sparql",
        lambda *args, **kwargs: "SELECT ?s WHERE { ?s ?p ?o } ORDER BY ?s LIMIT 1",
    )

    payload = evaluate_suite(EvalConfig(limit=1, include_adversarial=False))

    assert payload["summary"]["total"] == 1
    assert payload["evaluated_interface"] == "ask translation layer"
    assert payload["mode"] == "translation"
    assert payload["results"][0]["status"] == "generated_query"
    assert (
        payload["results"][0]["rubric_alignment"]["answer_correctness"]
        == "not_measurable"
    )


def test_evaluate_suite_marks_adversarial_rejection_as_pass(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "pokemontology.laurel_eval.generate_sparql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("request is unrelated to the Pokemontology schema")
        ),
    )

    payload = evaluate_suite(EvalConfig(tier="adversarial", limit=1))

    assert payload["results"][0]["status"] == "rejected"
    assert payload["results"][0]["rubric_alignment"]["safety"] == "pass"


def test_evaluate_laurel_cli_outputs_json(monkeypatch: object, capsys) -> None:
    monkeypatch.setattr(
        "pokemontology.laurel_eval.generate_sparql",
        lambda *args, **kwargs: "SELECT ?s WHERE { ?s ?p ?o } ORDER BY ?s LIMIT 1",
    )

    exit_code = cli.main(["evaluate-laurel", "--limit", "1", "--no-include-adversarial"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"summary"' in output
    assert '"results"' in output


def test_evaluate_suite_pipeline_mode_scores_answer(
    monkeypatch: object, tmp_path
) -> None:
    suite_path = tmp_path / "suite.json"
    source_path = tmp_path / "source.ttl"
    write_eval_suite(
        suite_path,
        tier="custom",
        item={
            "id": "custom-fire",
            "category": "custom",
            "question": "Is Charizard a Fire type?",
            "expected_answer": "Yes. Charizard is Fire type.",
            "answer_type": "boolean",
            "sources": [{"url": "https://example.test"}],
        },
    )
    write_charizard_fire_source(source_path)
    monkeypatch.setattr(
        "pokemontology.laurel_eval.generate_sparql",
        lambda *args, **kwargs: """PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
ASK {
  ?species a pkm:Species ;
           rdfs:label "Charizard" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type .
  ?type rdfs:label "Fire" .
}""",
    )

    payload = evaluate_suite(
        EvalConfig(
            suite=suite_path,
            mode="pipeline",
            sources=(source_path,),
            include_adversarial=False,
        )
    )

    assert payload["evaluated_interface"] == "laurel full pipeline"
    assert payload["results"][0]["status"] == "answered"
    assert payload["results"][0]["rubric_alignment"]["answer_correctness"] == "pass"


def test_evaluate_laurel_cli_pipeline_requires_sources(capsys) -> None:
    try:
        cli.main(["evaluate-laurel", "--mode", "pipeline", "--limit", "1"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected pipeline mode without sources to fail")
    error = capsys.readouterr().err
    assert "requires one or more Turtle sources" in error


def test_evaluate_suite_uses_schema_index_matches(monkeypatch: object, tmp_path) -> None:
    schema_index = tmp_path / "schema-index.json"
    write_dense_schema_index(
        schema_index,
        vocabulary=["charizard", "fire", "type"],
        vector=[1, 1, 1],
        item={
            "label": "Charizard typing",
            "kind": "pattern",
            "summary": "Resolve a species typing fact.",
            "snippet": "Is Charizard a Fire type?",
        },
    )

    captured_matches: list[dict[str, object]] | None = None

    def fake_generate_sparql(*args, **kwargs):
        nonlocal captured_matches
        captured_matches = kwargs.get("matches")
        return "SELECT ?s WHERE { ?s ?p ?o } ORDER BY ?s LIMIT 1"

    monkeypatch.setattr("pokemontology.laurel_eval.generate_sparql", fake_generate_sparql)

    payload = evaluate_suite(
        EvalConfig(
            limit=1,
            include_adversarial=False,
            schema_index=schema_index,
        )
    )

    assert payload["schema_index"] == str(schema_index)
    assert captured_matches is not None
    assert captured_matches[0]["label"] == "Charizard typing"
