"""Regression checks for the docs query engine asset."""

from __future__ import annotations

import json

from pokemontology._script_loader import repo_path

REPO = repo_path()
APP_JS = REPO / "docs" / "app.js"
SITE_DATA = REPO / "docs" / "site-data.json"


def test_query_engine_uses_comunica_fallback_urls() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "COMUNICA_BROWSER_URLS" in text
    assert (
        "rdf.js.org/comunica-browser/versions/v4/engines/query-sparql/comunica-browser.js"
        in text
    )
    assert (
        "cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js" in text
    )


def test_query_engine_no_longer_depends_on_stream_variables() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "executeBindingsQuery" in text
    assert "inferBindingVars" in text
    assert "stream.variables" not in text


def test_query_engine_uses_generated_query_examples() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    site_data = json.loads(SITE_DATA.read_text(encoding="utf-8"))

    assert "EXAMPLE_QUERIES" not in text
    assert "query_examples" in text
    assert site_data["query_examples"]
    assert (
        site_data["query_examples"][0]["source_path"]
        == "queries/super_effective_moves.sparql"
    )
