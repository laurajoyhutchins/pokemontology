"""Tests for the Laurel evaluation harness."""

from __future__ import annotations

from pokemontology import cli
from pokemontology.laurel_eval import EvalConfig, evaluate_suite


def test_evaluate_suite_marks_mechanics_as_partial_when_query_is_generated(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(
        "pokemontology.laurel_eval.generate_sparql",
        lambda *args, **kwargs: "SELECT * WHERE { ?s ?p ?o } LIMIT 1",
    )

    payload = evaluate_suite(EvalConfig(limit=1, include_adversarial=False))

    assert payload["summary"]["total"] == 1
    assert payload["evaluated_interface"] == "ask translation layer"
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
        lambda *args, **kwargs: "SELECT * WHERE { ?s ?p ?o } LIMIT 1",
    )

    exit_code = cli.main(["evaluate-laurel", "--limit", "1", "--no-include-adversarial"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"summary"' in output
    assert '"results"' in output
