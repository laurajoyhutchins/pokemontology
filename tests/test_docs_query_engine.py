"""Regression checks for the docs query engine asset."""

from __future__ import annotations

import json
import re

from pokemontology._script_loader import repo_path

REPO = repo_path()
APP_JS = REPO / "docs" / "app.js"
SITE_DATA = REPO / "docs" / "site-data.json"
INDEX_HTML = REPO / "docs" / "index.html"
POKEDEX_HTML = REPO / "docs" / "pokedex.html"
GRAPH_HTML = REPO / "docs" / "graph.html"
SCHEMA_INDEX = REPO / "docs" / "schema-index.json"
GRAPH_INDEX = REPO / "docs" / "graph-index.json"
SPARQL_REFERENCE = REPO / "docs" / "sparql-reference.md"
PKM_PREFIX_TERM_RE = re.compile(r"\bpkm:([A-Za-z_][\w-]*)\b")


def test_query_engine_uses_comunica_fallback_urls() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    query_module = (REPO / "docs" / "js" / "query-execution.js").read_text(
        encoding="utf-8"
    )
    source_module = (REPO / "docs" / "js" / "docs-sources.js").read_text(
        encoding="utf-8"
    )
    assert 'import { createLaurelApp } from "./js/laurel-app.js";' in text
    assert "COMUNICA_BROWSER_URLS" in query_module
    assert "buildSelectedSources" in query_module
    assert "getCanonicalMechanicsLabel" in source_module
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
    assert "formatPrefixBlock" in text
    assert site_data["query_examples"]
    assert site_data["schema_pack"]["path"] == "schema-index.json"
    assert any(artifact["path"] == "mechanics-base.ttl" for artifact in site_data["artifacts"])
    assert any(source["id"] == "src-mechanics" for source in site_data["query_sources"])
    assert any(source["id"] == "src-mechanics-learnsets" for source in site_data["query_sources"])
    assert schema_index["examples"]
    assert schema_index["prefixes"][0]["alias"] == "pkm:"
    assert schema_index["inference"]["webllm_library_url"]
    assert schema_index["response"]["list_preview_limit"] == 5
    assert (
        site_data["query_examples"][0]["source_path"]
        == "queries/bundled/super_effective_moves.sparql"
    )


def test_generated_sparql_reference_stays_in_sync_with_schema_pack() -> None:
    text = SPARQL_REFERENCE.read_text(encoding="utf-8")
    schema_index = json.loads(SCHEMA_INDEX.read_text(encoding="utf-8"))

    assert "# Pokemontology SPARQL Reference" in text
    assert "Generated from the ontology schema pack and bundled query metadata." in text
    assert "## Prefixes" in text
    assert "`pkm:`" in text
    assert "### TypingAssignment pattern" in text
    assert "### Type effectiveness pattern" in text
    assert "queries/bundled/super_effective_moves.sparql" in text
    assert schema_index["examples"][0]["label"] in text


def test_professor_laurel_landing_page_is_primary_entry() -> None:
    text = INDEX_HTML.read_text(encoding="utf-8")
    assert "Professor Laurel" in text
    assert "Run Query" in text
    assert "Grounding Notes" in text
    assert "Generated Query" in text
    assert "Advanced Query View" in text
    assert './pokedex.html' in text
    assert './graph.html' in text


def test_pokedex_page_uses_worker_backed_graph_browser() -> None:
    html = POKEDEX_HTML.read_text(encoding="utf-8")
    script = (REPO / "docs" / "js" / "pokedex-app.js").read_text(encoding="utf-8")
    runtime = (REPO / "docs" / "js" / "browser-runtime.js").read_text(
        encoding="utf-8"
    )

    assert "Ontology Pokedex" in html
    assert 'id="pokedex-search"' in html
    assert "data-pokedex-mechanics-artifact" in html
    assert 'src="./pokedex.js"' in html
    assert 'new Worker("./workers/query-worker.js", { type: "module" })' in script
    assert 'createWorkerRpc("pokedex")' in script
    assert "mechanicsSourceCandidates" in script
    assert "getCanonicalMechanicsLabel" in script
    assert "setupThemeToggle" in runtime
    assert "pkm:TypingAssignment" in script
    assert "pkm:MoveLearnRecord" in script
    assert "pkm:aboutPokemon ?species" in script


def test_graph_page_uses_generated_projection_index() -> None:
    html = GRAPH_HTML.read_text(encoding="utf-8")
    script = (REPO / "docs" / "graph.js").read_text(encoding="utf-8")
    app = (REPO / "docs" / "js" / "graph-app.js").read_text(encoding="utf-8")
    graph_index = json.loads(GRAPH_INDEX.read_text(encoding="utf-8"))

    assert "Knowledge Graph" in html
    assert 'id="graph-search"' in html
    assert 'id="graph-controls"' in html
    assert 'id="graph-controls-body"' in html
    assert 'id="graph-controls-toggle"' in html
    assert 'id="graph-controls-reopen"' in html
    assert 'id="graph-canvas"' in html
    assert 'id="graph-hop-depth"' in html
    assert 'id="graph-node-limit"' in html
    assert 'id="graph-node-limit-max"' in html
    assert 'id="graph-clear-query"' in html
    assert 'id="graph-reset-query"' in html
    assert 'id="graph-zoom-out"' in html
    assert 'id="graph-zoom-in"' in html
    assert 'id="graph-zoom-reset"' in html
    assert 'id="graph-zoom-level"' in html
    assert "graph-cap-controls" in html
    assert 'id="graph-query-status"' in html
    assert 'data-graph-preset="Pikachu"' in html
    assert 'id="graph-detail"' in html
    assert 'id="graph-results"' not in html
    assert 'src="./graph.js"' in html
    assert 'import { createGraphApp } from "./js/graph-app.js";' in script
    assert 'fetch("./graph-index.json"' in app
    assert "buildLayout" in app
    assert "bfsNeighborhood" in app
    assert "renderQueryStatus" in app
    assert "applyQueryValue" in app
    assert "setControlsCollapsed" in app
    assert "controls.hidden = false" in app
    assert "reopen.hidden = true" in app
    assert "controls.hidden = collapsed" not in app
    assert "syncNodeLimitControls" in app
    assert "parseNodeLimitValue" in app
    assert "maxButton.hidden = !state.nodeLimitEditing" in app
    assert 'commitNodeLimitValue(state, "MAX")' in app
    assert "parseZoomValue" in app
    assert "autoCollapseControls" in app
    assert "updateZoomReadout" in app
    assert "resetViewport" in app
    assert "EDGE_KINDS" in app
    assert graph_index["node_count"] > 0
    assert graph_index["edge_count"] > 0
    assert "learnsMove" in graph_index["edge_kinds"]
    assert any(node["type"] == "Species" for node in graph_index["nodes"])


def test_docs_workers_are_present() -> None:
    assert (REPO / "docs" / "workers" / "retrieval-worker.js").exists()
    assert (REPO / "docs" / "workers" / "llm-worker.js").exists()
    assert (REPO / "docs" / "workers" / "query-worker.js").exists()
    retrieval_text = (REPO / "docs" / "workers" / "retrieval-worker.js").read_text(
        encoding="utf-8"
    )
    llm_text = (REPO / "docs" / "workers" / "llm-worker.js").read_text(encoding="utf-8")
    assert "minimumScore" in retrieval_text
    assert "sparse_index" in retrieval_text
    assert "WebGPU local inference" in llm_text
    assert "webllm_library_url" in llm_text
    assert "deterministic fallback synthesizer" in llm_text
    assert "fallbackSparql" in llm_text
    assert "Concrete transformation patterns:" in llm_text
    assert "Always bind every projected SELECT variable" in llm_text
    assert 'pkm:hasName "${species}"' in llm_text
    assert "rdfs:label" not in llm_text


def test_query_engine_defaults_to_canonical_mechanics_dataset() -> None:
    text = (REPO / "docs" / "js" / "query-execution.js").read_text(encoding="utf-8")
    index_text = INDEX_HTML.read_text(encoding="utf-8")
    sources_text = (REPO / "docs" / "js" / "docs-sources.js").read_text(
        encoding="utf-8"
    )
    assert "data-query-sources" in index_text
    assert "data-query-artifacts" in index_text
    assert "buildSelectedSources" in text
    assert '"src-mechanics"' in sources_text
    assert '"src-mechanics-learnsets"' in sources_text
    assert '"pokeapi-demo.ttl (debug)"' in sources_text
    assert '"mechanics-base.ttl"' in sources_text
    assert "siteData?.query_sources" in sources_text
    assert "source.paths" in sources_text


def test_query_validator_enforces_ast_or_safe_fallback() -> None:
    text = (REPO / "docs" / "js" / "query-validation.js").read_text(encoding="utf-8")
    assert "SPARQLJS_URL" in text
    assert "https://esm.sh/sparqljs@3.7.3" in text
    assert "forbidden_keywords" in text
    assert "allowed_query_types" in text
    assert "known_terms" in text
    assert "SELECT *" in text
    assert "outside the shipped schema pack" in text
    assert "Fell back to structural validation" in text


def test_schema_pack_examples_match_ontology_terms() -> None:
    schema_index = json.loads(SCHEMA_INDEX.read_text(encoding="utf-8"))
    examples = {example["id"]: example for example in schema_index["examples"]}
    assert "pkm:actor" in examples["super-effective-moves"]["query"]
    assert "pkm:hasActor" not in examples["super-effective-moves"]["query"]
    assert "pkm:hasName \"Charizard\"" in examples["charizard-fire-check"]["query"]
    assert "rdfs:label" not in examples["charizard-fire-check"]["query"]


def test_schema_pack_examples_only_reference_known_ontology_terms() -> None:
    schema_index = json.loads(SCHEMA_INDEX.read_text(encoding="utf-8"))
    known_terms = set(schema_index["validation"]["known_terms"])
    for example in schema_index["examples"]:
        used_terms = set(PKM_PREFIX_TERM_RE.findall(example.get("query", "")))
        assert used_terms <= known_terms, (example["id"], sorted(used_terms - known_terms))


def test_frontend_fallback_worker_avoids_stale_ontology_patterns() -> None:
    llm_text = (REPO / "docs" / "workers" / "llm-worker.js").read_text(encoding="utf-8")
    assert "pkm:hasActor" not in llm_text
    assert "rdfs:label" not in llm_text
    assert "pkm:hasName" in llm_text


def test_laurel_app_retries_with_safe_fallback_on_validation_failure() -> None:
    app_text = (REPO / "docs" / "js" / "laurel-app.js").read_text(encoding="utf-8")
    assert "Primary translation failed validation. Trying Laurel fallback" in app_text
    assert "generation.fallbackSparql" in app_text
    assert "Primary browser-local translation failed validation; Laurel fell back to a bundled safe query." in app_text


def test_laurel_app_worker_transport_supports_overlapping_requests() -> None:
    app_text = (REPO / "docs" / "js" / "laurel-app.js").read_text(encoding="utf-8")
    runtime_text = (REPO / "docs" / "js" / "browser-runtime.js").read_text(
        encoding="utf-8"
    )
    retrieval_text = (REPO / "docs" / "workers" / "retrieval-worker.js").read_text(
        encoding="utf-8"
    )
    llm_text = (REPO / "docs" / "workers" / "llm-worker.js").read_text(
        encoding="utf-8"
    )
    query_text = (REPO / "docs" / "workers" / "query-worker.js").read_text(
        encoding="utf-8"
    )

    assert 'createWorkerRpc("req")' in app_text
    assert "worker.__pendingRequests = new Map()" in runtime_text
    assert "worker.__pendingRequests.set(requestId" in runtime_text
    assert "requestId: `req-${++nextWorkerRequestId}`" not in app_text
    assert "requestId," in retrieval_text
    assert "self.postMessage({ requestId, matches })" in retrieval_text
    assert "requestId," in llm_text
    assert "self.postMessage({ requestId, ...validation })" in query_text
    assert 'action = "validate"' in query_text
    assert 'action === "warmup"' in query_text
    assert 'action === "execute"' in query_text
    assert "new Store()" in query_text
    assert "storeCache" in query_text


def test_laurel_app_executes_queries_from_worker_backed_store() -> None:
    app_text = (REPO / "docs" / "js" / "laurel-app.js").read_text(encoding="utf-8")
    query_text = (REPO / "docs" / "workers" / "query-worker.js").read_text(
        encoding="utf-8"
    )

    assert 'action: "warmup"' in app_text
    assert 'action: "execute"' in app_text
    assert "Warming local query graph" in query_text
    assert "Local query graph ready." in query_text
    assert "engine.queryBindings(sparql, { sources: querySources })" in query_text
