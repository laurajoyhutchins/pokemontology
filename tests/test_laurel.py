"""Unit tests for laurel.py summarize_results helper."""

from __future__ import annotations

import pytest

from pokemontology.laurel import summarize_results


# ---------------------------------------------------------------------------
# Pre-existing "answer" field short-circuits everything
# ---------------------------------------------------------------------------


def test_summarize_results_returns_preexisting_answer() -> None:
    payload = {"answer": "It depends on the generation.", "rows": []}
    assert summarize_results("Any question?", payload) == "It depends on the generation."


# ---------------------------------------------------------------------------
# Boolean (ASK) results
# ---------------------------------------------------------------------------


def test_summarize_results_boolean_true_with_question() -> None:
    result = summarize_results("Can Water-type be burned?", {"boolean": True})
    assert result == "Yes. For: Can Water-type be burned?"


def test_summarize_results_boolean_false_with_question() -> None:
    result = summarize_results("Can Water-type be burned?", {"boolean": False})
    assert result == "No. For: Can Water-type be burned?"


def test_summarize_results_boolean_true_no_question() -> None:
    assert summarize_results("", {"boolean": True}) == "Yes."


def test_summarize_results_boolean_false_no_question() -> None:
    assert summarize_results("  ", {"boolean": False}) == "No."


# ---------------------------------------------------------------------------
# Non-list rows
# ---------------------------------------------------------------------------


def test_summarize_results_rows_not_list() -> None:
    result = summarize_results("Q?", {"rows": "bad"})
    assert result == "Laurel could not interpret the query output."


def test_summarize_results_no_rows_key() -> None:
    result = summarize_results("Q?", {})
    assert result == "Laurel could not interpret the query output."


# ---------------------------------------------------------------------------
# Empty rows list
# ---------------------------------------------------------------------------


def test_summarize_results_empty_rows() -> None:
    assert summarize_results("Q?", {"rows": []}) == "Laurel found no matching results."


# ---------------------------------------------------------------------------
# Single-variable results
# ---------------------------------------------------------------------------


def test_summarize_results_single_var_one_value() -> None:
    payload = {
        "variables": ["typeName"],
        "rows": [{"typeName": "Fire"}],
    }
    assert summarize_results("Q?", payload) == "Laurel found 1 result: Fire."


def test_summarize_results_single_var_multiple_values() -> None:
    payload = {
        "variables": ["typeName"],
        "rows": [{"typeName": "Fire"}, {"typeName": "Water"}, {"typeName": "Grass"}],
    }
    result = summarize_results("Q?", payload)
    assert result == "Laurel found 3 results: Fire, Water, Grass."


def test_summarize_results_single_var_truncates_at_preview_limit() -> None:
    payload = {
        "variables": ["typeName"],
        "rows": [{"typeName": str(i)} for i in range(7)],
    }
    result = summarize_results("Q?", payload)
    assert "…" in result
    assert "Laurel found 7 results:" in result


def test_summarize_results_answer_text_var_single_value() -> None:
    payload = {
        "variables": ["answerText"],
        "rows": [{"answerText": "Yes, Levitate grants Ground immunity."}],
    }
    assert summarize_results("Q?", payload) == "Yes, Levitate grants Ground immunity."


def test_summarize_results_answer_text_var_multiple_values() -> None:
    payload = {
        "variables": ["answerText"],
        "rows": [{"answerText": "Gravity"}, {"answerText": "Mold Breaker"}],
    }
    result = summarize_results("Q?", payload)
    assert "Gravity" in result
    assert "Mold Breaker" in result


def test_summarize_results_answer_var_single_value() -> None:
    payload = {
        "variables": ["answer"],
        "rows": [{"answer": "Pikachu"}],
    }
    assert summarize_results("Q?", payload) == "Pikachu"


def test_summarize_results_single_var_missing_values_in_rows() -> None:
    # Rows that don't contain the variable value at all
    payload = {
        "variables": ["typeName"],
        "rows": [{"otherKey": "irrelevant"}],
    }
    result = summarize_results("Q?", payload)
    assert result == "Laurel found 1 matching rows."


# ---------------------------------------------------------------------------
# Multi-variable results
# ---------------------------------------------------------------------------


def test_summarize_results_single_row_multi_var() -> None:
    payload = {
        "variables": ["moveName", "typeName"],
        "rows": [{"moveName": "Flamethrower", "typeName": "Fire"}],
    }
    result = summarize_results("Q?", payload)
    assert result.startswith("Laurel found 1 matching row:")
    assert "moveName=Flamethrower" in result
    assert "typeName=Fire" in result


def test_summarize_results_multiple_rows_multi_var() -> None:
    payload = {
        "variables": ["moveName", "typeName"],
        "rows": [
            {"moveName": "Flamethrower", "typeName": "Fire"},
            {"moveName": "Surf", "typeName": "Water"},
        ],
    }
    result = summarize_results("Q?", payload)
    assert result == "Laurel found 2 matching rows."
