"""Regression checks for the docs query engine asset."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).parent.parent
APP_JS = REPO / "docs" / "app.js"


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
