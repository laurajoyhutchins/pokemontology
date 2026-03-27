"""Unit tests for chat.py helper functions (RAG, SPARQL validation, linting)."""

from __future__ import annotations

import pytest

from pokemontology.chat import (
    clean_sparql_output,
    compact_prompt_matches,
    cosine_similarity,
    get_minimum_score,
    lint_sparql_text,
    retrieve_matches,
    token_counts,
    tokenize,
    validate_sparql_text,
    vectorize,
)


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello World!", ["hello", "world"]),
        ("  leading and trailing  ", ["leading", "and", "trailing"]),
        ("all123numbers456", ["all123numbers456"]),
        ("hyphen-separated words", ["hyphen", "separated", "words"]),
        ("", []),
        ("!!!  ???", []),
        ("Pokémon battle", ["pok", "mon", "battle"]),
    ],
)
def test_tokenize(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


# ---------------------------------------------------------------------------
# token_counts
# ---------------------------------------------------------------------------


def test_token_counts_single_occurrence() -> None:
    assert token_counts("fire water grass") == {"fire": 1, "water": 1, "grass": 1}


def test_token_counts_repeated_token() -> None:
    assert token_counts("fire fire water") == {"fire": 2, "water": 1}


def test_token_counts_empty_string() -> None:
    assert token_counts("") == {}


# ---------------------------------------------------------------------------
# vectorize
# ---------------------------------------------------------------------------


def test_vectorize_all_present() -> None:
    assert vectorize("fire water", ["fire", "water", "grass"]) == [1, 1, 0]


def test_vectorize_none_present() -> None:
    assert vectorize("steel flying", ["fire", "water", "grass"]) == [0, 0, 0]


def test_vectorize_repeated_token() -> None:
    assert vectorize("fire fire water", ["fire", "water"]) == [2, 1]


def test_vectorize_empty_text() -> None:
    assert vectorize("", ["fire", "water"]) == [0, 0]


def test_vectorize_empty_vocabulary() -> None:
    assert vectorize("fire water", []) == []


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors() -> None:
    assert cosine_similarity([1, 1, 1], [1, 1, 1]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors() -> None:
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_similarity_zero_left_vector() -> None:
    assert cosine_similarity([0, 0], [1, 1]) == pytest.approx(0.0)


def test_cosine_similarity_zero_right_vector() -> None:
    assert cosine_similarity([1, 1], [0, 0]) == pytest.approx(0.0)


def test_cosine_similarity_proportional_vectors() -> None:
    assert cosine_similarity([2, 4], [1, 2]) == pytest.approx(1.0)


def test_cosine_similarity_partial_overlap() -> None:
    score = cosine_similarity([1, 1, 0], [1, 0, 1])
    assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# get_minimum_score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, expected",
    [
        ("fire", 0.34),           # 1 token → ≤2 threshold
        ("fire water", 0.34),     # 2 tokens → ≤2 threshold
        ("fire water grass", 0.24),   # 3 tokens → ≤5 threshold
        ("a b c d e", 0.24),      # 5 tokens → ≤5 threshold
        ("a b c d e f", 0.16),    # 6 tokens → fallback threshold
    ],
)
def test_get_minimum_score(question: str, expected: float) -> None:
    assert get_minimum_score(question) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# retrieve_matches — dense path
# ---------------------------------------------------------------------------


_DENSE_SCHEMA_PACK = {
    "vocabulary": ["fire", "water", "grass", "type"],
    "vectors": [
        [1, 0, 0, 1],  # item 0: fire type
        [0, 1, 0, 1],  # item 1: water type
        [0, 0, 1, 1],  # item 2: grass type
    ],
    "items": [
        {"label": "FireType", "kind": "class"},
        {"label": "WaterType", "kind": "class"},
        {"label": "GrassType", "kind": "class"},
    ],
}


def test_retrieve_matches_returns_top_results() -> None:
    results = retrieve_matches("fire type", _DENSE_SCHEMA_PACK, top_k=2)
    assert len(results) <= 2
    assert results[0]["label"] == "FireType"


def test_retrieve_matches_empty_schema_pack() -> None:
    assert retrieve_matches("fire type", {}) == []


def test_retrieve_matches_no_vocabulary() -> None:
    pack = {"items": [{"label": "X"}], "vocabulary": [], "vectors": []}
    assert retrieve_matches("fire", pack) == []


def test_retrieve_matches_score_below_minimum_excluded() -> None:
    # Question with >5 tokens → min_score=0.16; an orthogonal vector should score 0.0
    pack = {
        "vocabulary": ["steel"],
        "vectors": [[1]],
        "items": [{"label": "SteelType"}],
    }
    results = retrieve_matches("fire water grass poison psychic fairy", pack, top_k=5)
    assert results == []


# ---------------------------------------------------------------------------
# retrieve_matches — sparse path
# ---------------------------------------------------------------------------


def test_retrieve_matches_sparse_path() -> None:
    # sparse_index maps token → list of [item_index, weight]
    pack = {
        "items": [
            {"label": "FireType", "kind": "class"},
            {"label": "WaterType", "kind": "class"},
        ],
        "sparse_index": {
            "fire": [[0, 1.0]],
            "water": [[1, 1.0]],
            "type": [[0, 0.5], [1, 0.5]],
        },
        "item_norms": [1.118, 1.118],  # sqrt(1^2 + 0.5^2)
    }
    results = retrieve_matches("fire type", pack, top_k=2)
    assert len(results) >= 1
    assert results[0]["label"] == "FireType"


def test_retrieve_matches_sparse_empty_query() -> None:
    pack = {
        "items": [{"label": "X"}],
        "sparse_index": {"fire": [[0, 1.0]]},
        "item_norms": [1.0],
    }
    # Punctuation-only query tokenizes to nothing → no matches
    assert retrieve_matches("!!!", pack) == []


# ---------------------------------------------------------------------------
# clean_sparql_output
# ---------------------------------------------------------------------------


def test_clean_sparql_output_plain_text() -> None:
    query = "SELECT ?x WHERE { ?x a ?y . } LIMIT 1"
    assert clean_sparql_output(query) == query


def test_clean_sparql_output_fenced_block() -> None:
    raw = "Here is your query:\n```\nSELECT ?x WHERE { ?x a ?y . } LIMIT 1\n```"
    assert clean_sparql_output(raw) == "SELECT ?x WHERE { ?x a ?y . } LIMIT 1"


def test_clean_sparql_output_sparql_fenced_block() -> None:
    raw = "```sparql\nASK { ?s a <X> . }\n```"
    assert clean_sparql_output(raw) == "ASK { ?s a <X> . }"


def test_clean_sparql_output_strips_whitespace() -> None:
    assert clean_sparql_output("  SELECT ?x WHERE {} LIMIT 1  ") == "SELECT ?x WHERE {} LIMIT 1"


# ---------------------------------------------------------------------------
# validate_sparql_text
# ---------------------------------------------------------------------------

_VALID_SELECT = (
    "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
    "SELECT ?name WHERE { ?s pkm:hasName ?name . } ORDER BY ?name LIMIT 10"
)
_VALID_ASK = (
    "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
    "ASK { ?s a pkm:Species . }"
)


def test_validate_sparql_text_valid_select() -> None:
    result = validate_sparql_text(_VALID_SELECT)
    assert "SELECT" in result


def test_validate_sparql_text_valid_ask() -> None:
    result = validate_sparql_text(_VALID_ASK)
    assert "ASK" in result


def test_validate_sparql_text_unrelated_request() -> None:
    with pytest.raises(ValueError, match="unrelated"):
        validate_sparql_text("ERROR: unrelated_request")


def test_validate_sparql_text_forbidden_keyword_delete() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        validate_sparql_text("DELETE WHERE { ?s ?p ?o }")


def test_validate_sparql_text_forbidden_keyword_insert() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        validate_sparql_text("INSERT DATA { <x> <y> <z> }")


def test_validate_sparql_text_forbidden_keyword_drop() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        validate_sparql_text("DROP GRAPH <urn:x>")


def test_validate_sparql_text_not_read_only_query_type() -> None:
    # No SELECT/ASK/DESCRIBE/CONSTRUCT keyword at start
    with pytest.raises(ValueError, match="read-only"):
        validate_sparql_text("UPDATE { ?s ?p ?o }")


def test_validate_sparql_text_forbidden_keyword_in_fenced_block() -> None:
    raw = "```sparql\nDELETE WHERE { ?s ?p ?o }\n```"
    with pytest.raises(ValueError, match="forbidden"):
        validate_sparql_text(raw)


def test_validate_sparql_text_malformed_sparql() -> None:
    with pytest.raises(ValueError):
        validate_sparql_text("SELECT ?x WHERE { BROKEN {{{{")


def test_validate_sparql_text_select_star_rejected() -> None:
    bad = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT * WHERE { ?s ?p ?o . } LIMIT 5"
    )
    with pytest.raises(ValueError, match="SELECT \\*"):
        validate_sparql_text(bad)


def test_validate_sparql_text_unbounded_select_rejected() -> None:
    bad = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT ?name WHERE { ?s pkm:hasName ?name . }"
    )
    with pytest.raises(ValueError, match="LIMIT or ORDER BY"):
        validate_sparql_text(bad)


# ---------------------------------------------------------------------------
# lint_sparql_text
# ---------------------------------------------------------------------------


def test_lint_sparql_text_clean_query_has_no_messages() -> None:
    assert lint_sparql_text(_VALID_SELECT) == []


def test_lint_sparql_text_select_star() -> None:
    bad = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT * WHERE { ?s ?p ?o . } LIMIT 5"
    )
    messages = lint_sparql_text(bad)
    assert any("SELECT *" in m for m in messages)


def test_lint_sparql_text_no_limit_or_order_by() -> None:
    bad = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT ?name WHERE { ?s pkm:hasName ?name . }"
    )
    messages = lint_sparql_text(bad)
    assert any("LIMIT or ORDER BY" in m for m in messages)


def test_lint_sparql_text_unbound_projected_variable() -> None:
    bad = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT ?ghost WHERE { ?s pkm:hasName ?name . } ORDER BY ?name LIMIT 5"
    )
    messages = lint_sparql_text(bad)
    assert any("?ghost" in m for m in messages)


def test_lint_sparql_text_ask_query_skips_select_checks() -> None:
    # ASK queries should not trigger SELECT-specific lint rules
    assert lint_sparql_text(_VALID_ASK) == []


def test_lint_sparql_text_order_by_satisfies_bounded_requirement() -> None:
    query = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT ?name WHERE { ?s pkm:hasName ?name . } ORDER BY ?name"
    )
    messages = lint_sparql_text(query)
    assert not any("LIMIT or ORDER BY" in m for m in messages)


def test_lint_sparql_text_limit_satisfies_bounded_requirement() -> None:
    query = (
        "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "SELECT ?name WHERE { ?s pkm:hasName ?name . } LIMIT 10"
    )
    messages = lint_sparql_text(query)
    assert not any("LIMIT or ORDER BY" in m for m in messages)


# ---------------------------------------------------------------------------
# compact_prompt_matches
# ---------------------------------------------------------------------------


def test_compact_prompt_matches_empty_input() -> None:
    assert compact_prompt_matches([]) == []
    assert compact_prompt_matches(None) == []


def test_compact_prompt_matches_deduplicates_by_label_and_iri() -> None:
    matches = [
        {"label": "Fire", "iri": "pkm:Fire", "kind": "class", "score": 0.9},
        {"label": "Fire", "iri": "pkm:Fire", "kind": "class", "score": 0.8},
    ]
    result = compact_prompt_matches(matches)
    assert len(result) == 1


def test_compact_prompt_matches_respects_limit() -> None:
    matches = [
        {"label": f"Term{i}", "iri": f"pkm:Term{i}", "kind": "term", "score": 0.5}
        for i in range(10)
    ]
    result = compact_prompt_matches(matches)
    assert len(result) <= 3  # PROMPT_MATCH_LIMIT


def test_compact_prompt_matches_prefers_example_kind() -> None:
    matches = [
        {"label": "A", "iri": "pkm:A", "kind": "term", "score": 0.9},
        {"label": "B", "iri": "pkm:B", "kind": "example", "score": 0.5},
    ]
    result = compact_prompt_matches(matches)
    # "example" has higher priority (kind_rank 0) than "term" (kind_rank 5)
    assert result[0]["kind"] == "example"
