"""Regression checks for the docs query engine asset."""

from __future__ import annotations

import json

from pokemontology._script_loader import repo_path

REPO = repo_path()
APP_JS = REPO / "docs" / "app.js"
SITE_DATA = REPO / "docs" / "site-data.json"
INDEX_HTML = REPO / "docs" / "index.html"
SCHEMA_INDEX = REPO / "docs" / "schema-index.json"


def test_query_engine_uses_comunica_fallback_urls() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    query_module = (REPO / "docs" / "js" / "query-execution.js").read_text(
        encoding="utf-8"
    )
    assert 'import { createLaurelApp } from "./js/laurel-app.js";' in text
    assert "COMUNICA_BROWSER_URLS" in query_module
    assert (
        "rdf.js.org/comunica-browser/versions/v4/engines/query-sparql/comunica-browser.js"
        in query_module
    )
    assert (
        "cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js"
        in query_module
    )


def test_query_engine_no_longer_depends_on_stream_variables() -> None:
    text = (REPO / "docs" / "js" / "query-execution.js").read_text(encoding="utf-8")
    assert "executeBindingsQuery" in text
    assert "inferBindingVars" in text
    assert "stream.variables" not in text
    assert "summarizeQueryResult" in text


def test_query_engine_uses_generated_query_examples_and_schema_pack() -> None:
    text = (REPO / "docs" / "js" / "schema-pack.js").read_text(encoding="utf-8")
    site_data = json.loads(SITE_DATA.read_text(encoding="utf-8"))
    schema_index = json.loads(SCHEMA_INDEX.read_text(encoding="utf-8"))

    assert "schema-index.json" in text
    assert site_data["query_examples"]
    assert site_data["schema_pack"]["path"] == "schema-index.json"
    assert schema_index["examples"]
    assert (
        site_data["query_examples"][0]["source_path"]
        == "queries/super_effective_moves.sparql"
    )


def test_professor_laurel_landing_page_is_primary_entry() -> None:
    text = INDEX_HTML.read_text(encoding="utf-8")
    assert "Ask Professor Laurel." in text
    assert "Grounding Notes" in text
    assert "Generated Query" in text
    assert "Advanced Query View" in text


def test_docs_workers_are_present() -> None:
    assert (REPO / "docs" / "workers" / "retrieval-worker.js").exists()
    assert (REPO / "docs" / "workers" / "llm-worker.js").exists()
    assert (REPO / "docs" / "workers" / "query-worker.js").exists()
    retrieval_text = (REPO / "docs" / "workers" / "retrieval-worker.js").read_text(
        encoding="utf-8"
    )
    assert "minimumScore" in retrieval_text
    assert "tokenCount <= 2" in retrieval_text


def test_query_validator_enforces_ast_or_safe_fallback() -> None:
    text = (REPO / "docs" / "js" / "query-validation.js").read_text(encoding="utf-8")
    assert "SPARQLJS_URL" in text
    assert "https://esm.sh/sparqljs@3.7.3" in text
    assert "SERVICE" in text
    assert "Fell back to structural validation" in text
