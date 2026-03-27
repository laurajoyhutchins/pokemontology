"""End-to-end smoke tests for the CLI and web Laurel flows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from rdflib import Graph

from tests.support import REPO
from tests.support.laurel import write_super_effective_fixture


PYTHON = Path(sys.executable)
SCHEMA_INDEX = REPO / "docs" / "schema-index.json"
SUPER_EFFECTIVE_QUERY = REPO / "queries" / "bundled" / "super_effective_moves.sparql"


def _sitecustomize_dir(tmp_path: Path) -> Path:
    hook_dir = tmp_path / "python-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import os
            from pathlib import Path

            query_file = os.environ.get("POKEMONTOLOGY_TEST_GENERATED_QUERY_FILE")
            if query_file:
                query_text = Path(query_file).read_text(encoding="utf-8")

                def _fake_generate_sparql(*args, **kwargs):
                    return query_text

                import pokemontology.chat
                import pokemontology.cli
                import pokemontology.laurel_eval

                pokemontology.chat.generate_sparql = _fake_generate_sparql
                pokemontology.cli.generate_sparql = _fake_generate_sparql
                pokemontology.laurel_eval.generate_sparql = _fake_generate_sparql
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return hook_dir


def _python_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    hook_dir = _sitecustomize_dir(tmp_path)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{hook_dir}{os.pathsep}{existing}" if existing else str(hook_dir)
    )
    env["POKEMONTOLOGY_TEST_GENERATED_QUERY_FILE"] = str(SUPER_EFFECTIVE_QUERY)
    return env


def test_cli_laurel_command_end_to_end_json(
    built_ontology_path: str, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    write_super_effective_fixture(fixture_path)

    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pokemontology",
            "laurel",
            "Which of my moves are effective against Bulbasaur?",
            built_ontology_path,
            str(fixture_path),
            "--json",
        ],
        cwd=REPO,
        env=_python_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["answer"].startswith("Laurel found 1 matching row:")
    assert payload["result"]["rows"][0]["myMoveLabel"] == "Ember"
    assert "pkm:actor" in payload["sparql"]


def test_cli_ask_command_end_to_end_outputs_sparql(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pokemontology",
            "ask",
            "Which of my moves are effective against Bulbasaur?",
        ],
        cwd=REPO,
        env=_python_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "SELECT ?myMoveLabel ?moveTypeName ?opponentLabel" in completed.stdout
    assert "pkm:actor" in completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web E2E")
def test_web_worker_pipeline_end_to_end() -> None:
    script = textwrap.dedent(
        f"""
        import fs from "node:fs";
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const schemaPack = JSON.parse(fs.readFileSync(path.join(repo, "docs", "schema-index.json"), "utf8"));

        const llmMessages = [];
        globalThis.self = {{
          postMessage(message) {{
            llmMessages.push(message);
          }},
        }};
        await import(pathToFileURL(path.join(repo, "docs", "workers", "llm-worker.js")).href + "?e2e=llm");
        await globalThis.self.onmessage({{
          data: {{
            question: "Which of my moves are effective against Charizard?",
            matches: [],
            schemaPack,
            webgpuAvailable: false,
          }},
        }});
        const generation = llmMessages.at(-1);

        const queryMessages = [];
        globalThis.self = {{
          postMessage(message) {{
            queryMessages.push(message);
          }},
        }};
        await import(pathToFileURL(path.join(repo, "docs", "workers", "query-worker.js")).href + "?e2e=query");
        await globalThis.self.onmessage({{
          data: {{
            sparql: generation.sparql,
            schemaPack,
          }},
        }});
        const validation = queryMessages.at(-1);

        console.log(JSON.stringify({{ generation, validation }}));
        """
    )

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["generation"]["backend"] in {
        "CPU fallback synthesizer",
        "deterministic fallback synthesizer",
    }
    assert "pkm:actor" in payload["generation"]["sparql"]
    assert payload["validation"]["ok"] is True
    assert "PREFIX pkm:" in payload["validation"]["normalized"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web E2E")
def test_web_worker_query_executes_actual_species_question() -> None:
    script = textwrap.dedent(
        f"""
        import fs from "node:fs";
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const schemaPack = JSON.parse(fs.readFileSync(path.join(repo, "docs", "schema-index.json"), "utf8"));

        const llmMessages = [];
        globalThis.self = {{
          postMessage(message) {{
            llmMessages.push(message);
          }},
        }};
        await import(pathToFileURL(path.join(repo, "docs", "workers", "llm-worker.js")).href + "?e2e=species");
        await globalThis.self.onmessage({{
          data: {{
            question: "Which move types are super effective against Charizard?",
            matches: [],
            schemaPack,
            webgpuAvailable: false,
          }},
        }});

        console.log(JSON.stringify(llmMessages.at(-1)));
        """
    )

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["summary"] == "Synthesized a species type-effectiveness query that works with browser demo data."
    assert 'pkm:hasName "Charizard"' in payload["sparql"]
    assert "SUM(?factorScore) AS ?netScore" in payload["sparql"]

    graph = Graph()
    graph.parse(REPO / "docs" / "ontology.ttl", format="ttl")
    graph.parse(REPO / "docs" / "pokeapi-demo.ttl", format="ttl")
    rows = list(graph.query(payload["sparql"]))

    assert rows
    scores = {str(row.moveTypeName): int(row.netScore.toPython()) for row in rows}
    assert scores["Rock"] == 2
    assert scores["Water"] == 1
    assert scores["Electric"] == 1
    assert "Ground" not in scores


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web E2E")
def test_web_page_controller_prefers_actual_pokeapi_source(tmp_path: Path) -> None:
    site_data_text = (REPO / "docs" / "site-data.json").read_text(encoding="utf-8")
    schema_index_text = SCHEMA_INDEX.read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const siteData = {site_data_text};
        const schemaPack = {schema_index_text};
        const sourceCalls = [];

        class FakeClassList {{
          constructor() {{
            this.names = new Set();
          }}
          toggle(name, force) {{
            if (force === undefined) {{
              if (this.names.has(name)) this.names.delete(name);
              else this.names.add(name);
              return this.names.has(name);
            }}
            if (force) this.names.add(name);
            else this.names.delete(name);
            return force;
          }}
        }}

        class FakeElement {{
          constructor(id = "", tag = "div") {{
            this.id = id;
            this.tagName = tag.toUpperCase();
            this.listeners = {{}};
            this.children = [];
            this.attributes = new Map();
            this.dataset = {{}};
            this.classList = new FakeClassList();
            this.hidden = false;
            this.checked = false;
            this.disabled = false;
            this.open = false;
            this.value = "";
            this.innerHTML = "";
            this.textContent = "";
            this.href = "";
          }}
          addEventListener(type, listener) {{
            (this.listeners[type] ||= []).push(listener);
          }}
          async dispatch(type, event = {{}}) {{
            for (const listener of this.listeners[type] || []) {{
              await listener({{
                preventDefault() {{}},
                stopPropagation() {{}},
                target: this,
                currentTarget: this,
                ...event,
              }});
            }}
          }}
          async click() {{
            await this.dispatch("click");
          }}
          setAttribute(name, value) {{
            this.attributes.set(name, String(value));
            if (name === "hidden") this.hidden = true;
          }}
          removeAttribute(name) {{
            this.attributes.delete(name);
            if (name === "hidden") this.hidden = false;
          }}
          appendChild(child) {{
            this.children.push(child);
            return child;
          }}
          removeChild(child) {{
            this.children = this.children.filter((entry) => entry !== child);
          }}
          focus() {{}}
        }}

        const byId = new Map();
        const bySelector = new Map();
        const selectorLists = new Map([
          ["main section[id]", []],
          [".nav-links a[href^='#']", []],
        ]);

        function registerId(id, tag = "div") {{
          const element = new FakeElement(id, tag);
          byId.set(id, element);
          return element;
        }}
        function registerSelector(selector, element) {{
          bySelector.set(selector, element);
          return element;
        }}

        const documentElement = new FakeElement("", "html");
        documentElement.dataset = {{}};
        const body = new FakeElement("", "body");
        body.dataset = {{}};
        const head = new FakeElement("", "head");

        const question = registerId("nl-question", "textarea");
        const laurelRunBtn = registerId("laurel-run-btn", "button");
        const sparqlEditor = registerId("sparql-editor", "textarea");
        registerId("generated-query-preview", "code");
        registerId("validation-list");
        registerId("validation-badge");
        registerId("grounding-notes");
        registerId("qe-results");
        registerId("laurel-status");
        const runBtn = registerId("run-btn", "button");
        const runBtnLabel = registerId("run-btn-label");
        registerId("example-select", "select");
        const srcOntology = registerId("src-ontology", "input");
        srcOntology.checked = true;
        const srcMechanics = registerId("src-mechanics", "input");
        srcMechanics.checked = true;
        const srcPokeapiDemo = registerId("src-pokeapi-demo", "input");
        srcPokeapiDemo.checked = false;
        const srcShapes = registerId("src-shapes", "input");
        srcShapes.checked = false;
        registerId("export-csv-btn", "button");
        registerId("clear-results-btn", "button");
        registerId("copy-sparql-btn", "button");
        registerId("sample-question-btn", "button");
        registerId("toggle-advanced-btn", "button");
        registerId("advanced-console", "details");
        registerId("focus-question-btn", "button");
        registerId("copy-query-btn", "button");
        registerId("clear-query-btn", "button");
        registerId("qe-status");

        registerSelector("[data-status-model]", new FakeElement("", "span"));
        registerSelector("[data-status-grounding]", new FakeElement("", "span"));
        registerSelector("[data-status-validator]", new FakeElement("", "span"));
        registerSelector("[data-grounding-count]", new FakeElement("", "span"));
        registerSelector("[data-theme-toggle]", new FakeElement("", "button"));
        registerSelector("[data-theme-label]", new FakeElement("", "span"));
        registerSelector("[data-power-toggle]", new FakeElement("", "button"));
        registerSelector("[data-power-label]", new FakeElement("", "span"));
        registerSelector("[data-repository-url]", new FakeElement("", "a"));
        registerSelector("[data-pages-base-url]", new FakeElement("", "span"));
        const siteError = registerSelector("[data-site-error]", new FakeElement("", "div"));
        siteError.hidden = true;

        const document = {{
          body,
          head,
          documentElement,
          getElementById(id) {{
            return byId.get(id) || null;
          }},
          querySelector(selector) {{
            return bySelector.get(selector) || null;
          }},
          querySelectorAll(selector) {{
            return selectorLists.get(selector) || [];
          }},
          createElement(tag) {{
            const element = new FakeElement("", tag);
            if (tag === "script") {{
              queueMicrotask(() => element.onload?.());
            }}
            return element;
          }},
        }};

        class FakeWorker {{
          constructor(url) {{
            this.url = url;
            this.onmessage = null;
            this.onerror = null;
          }}
          postMessage(payload) {{
            queueMicrotask(() => {{
              try {{
                let message;
                if (this.url.includes("retrieval-worker")) {{
                  message = {{ requestId: payload.requestId, matches: [] }};
                }} else if (this.url.includes("llm-worker")) {{
                  message = {{
                    requestId: payload.requestId,
                    backend: "CPU fallback synthesizer",
                    sparql: "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\\nSELECT ?species WHERE {{ ?species a pkm:Species }} LIMIT 1",
                    fallbackSparql: "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\\nSELECT ?species WHERE {{ ?species a pkm:Species }} LIMIT 1",
                    summary: "synthetic test response",
                  }};
                }} else {{
                  sourceCalls.push(...(payload.sources || []));
                  if (payload.action === "warmup") {{
                    message = {{ requestId: payload.requestId, ok: true, warmed: true, sources: payload.sources || [] }};
                  }} else if (payload.action === "execute") {{
                    message = {{
                      requestId: payload.requestId,
                      result: {{
                        type: "bindings",
                        vars: ["species"],
                        bindings: [],
                      }},
                    }};
                  }} else {{
                    message = {{ requestId: payload.requestId, ok: true, messages: [], normalized: payload.sparql }};
                  }}
                }}
                this.onmessage?.({{ data: message }});
              }} catch (error) {{
                this.onerror?.({{ error }});
              }}
            }});
          }}
        }}

        globalThis.document = document;
        globalThis.window = globalThis;
        Object.defineProperty(globalThis, "navigator", {{
          configurable: true,
          value: {{ gpu: null, clipboard: {{ writeText: async () => {{}} }} }},
        }});
        Object.defineProperty(globalThis, "location", {{
          configurable: true,
          value: {{ href: "http://localhost:8000/index.html" }},
        }});
        Object.defineProperty(globalThis, "localStorage", {{
          configurable: true,
          value: {{ getItem() {{ return null; }}, setItem() {{}} }},
        }});
        globalThis.matchMedia = () => ({{ matches: false }});
        globalThis.IntersectionObserver = class {{ observe() {{}} disconnect() {{}} }};
        globalThis.Worker = FakeWorker;
        globalThis.fetch = async (url) => {{
          const target = String(url);
          if (target.endsWith("site-data.json")) return {{ ok: true, json: async () => siteData }};
          if (target.endsWith("schema-index.json")) return {{ ok: true, json: async () => schemaPack }};
          throw new Error(`unexpected fetch: ${{target}}`);
        }};
        globalThis.performance = {{ now: () => 123 }};
        globalThis.URL = URL;

        const module = await import(pathToFileURL(path.join(repo, "docs", "js", "laurel-app.js")).href + "?sources-e2e");
        await module.createLaurelApp();
        question.value = "Which move types are super effective against Charizard?";
        await laurelRunBtn.click();

        console.log(JSON.stringify({{
          sourceCalls,
          runDisabled: runBtn.disabled,
          runLabel: runBtnLabel.textContent,
          editorValue: sparqlEditor.value,
        }}));
        """
    )

    script_path = tmp_path / "web-source-e2e.mjs"
    script_path.write_text(script, encoding="utf-8")

    completed = subprocess.run(
        ["node", str(script_path)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["runDisabled"] is False
    assert payload["runLabel"] == "Run SPARQL"
    assert "./pokeapi.ttl" not in payload["editorValue"]
    assert any(source.endswith("/ontology.ttl") for source in payload["sourceCalls"])
    assert any(source.endswith("/mechanics-base.ttl") for source in payload["sourceCalls"])
    assert any(source.endswith("/mechanics-learnsets-current.ttl") for source in payload["sourceCalls"])
    assert any(source.endswith("/mechanics-learnsets-modern.ttl") for source in payload["sourceCalls"])
    assert any(source.endswith("/mechanics-learnsets-legacy.ttl") for source in payload["sourceCalls"])
    assert not any(source.endswith("/pokeapi-demo.ttl") for source in payload["sourceCalls"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web integration")
def test_web_page_controller_end_to_end(tmp_path: Path) -> None:
    query_text = SUPER_EFFECTIVE_QUERY.read_text(encoding="utf-8")
    site_data_text = (REPO / "docs" / "site-data.json").read_text(encoding="utf-8")
    schema_index_text = SCHEMA_INDEX.read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const queryText = {json.dumps(query_text)};
        const siteData = {site_data_text};
        const schemaPack = {schema_index_text};

        class FakeClassList {{
          constructor() {{
            this.names = new Set();
          }}
          toggle(name, force) {{
            if (force === undefined) {{
              if (this.names.has(name)) this.names.delete(name);
              else this.names.add(name);
              return this.names.has(name);
            }}
            if (force) this.names.add(name);
            else this.names.delete(name);
            return force;
          }}
        }}

        class FakeElement {{
          constructor(id = "", tag = "div") {{
            this.id = id;
            this.tagName = tag.toUpperCase();
            this.listeners = {{}};
            this.children = [];
            this.attributes = new Map();
            this.dataset = {{}};
            this.classList = new FakeClassList();
            this.hidden = false;
            this.checked = false;
            this.disabled = false;
            this.open = false;
            this.value = "";
            this.innerHTML = "";
            this.textContent = "";
            this.href = "";
          }}
          addEventListener(type, listener) {{
            (this.listeners[type] ||= []).push(listener);
          }}
          async dispatch(type, event = {{}}) {{
            for (const listener of this.listeners[type] || []) {{
              await listener({{
                preventDefault() {{}},
                stopPropagation() {{}},
                target: this,
                currentTarget: this,
                ...event,
              }});
            }}
          }}
          async click() {{
            await this.dispatch("click");
          }}
          setAttribute(name, value) {{
            this.attributes.set(name, String(value));
            if (name === "hidden") this.hidden = true;
            if (name.startsWith("data-")) {{
              this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
            }}
          }}
          removeAttribute(name) {{
            this.attributes.delete(name);
            if (name === "hidden") this.hidden = false;
          }}
          appendChild(child) {{
            this.children.push(child);
            return child;
          }}
          removeChild(child) {{
            this.children = this.children.filter((entry) => entry !== child);
          }}
          focus() {{
            this.focused = true;
          }}
        }}

        const byId = new Map();
        const bySelector = new Map();
        const selectorLists = new Map([
          ["main section[id]", []],
          [".nav-links a[href^='#']", []],
        ]);

        function registerId(id, tag = "div") {{
          const element = new FakeElement(id, tag);
          byId.set(id, element);
          return element;
        }}
        function registerSelector(selector, element) {{
          bySelector.set(selector, element);
          return element;
        }}

        const documentElement = new FakeElement("", "html");
        documentElement.dataset = {{}};
        const body = new FakeElement("", "body");
        body.dataset = {{}};
        const head = new FakeElement("", "head");

        const question = registerId("nl-question", "textarea");
        const laurelRunBtn = registerId("laurel-run-btn", "button");
        const sparqlEditor = registerId("sparql-editor", "textarea");
        const generatedPreview = registerId("generated-query-preview", "code");
        const validationList = registerId("validation-list");
        const validationBadge = registerId("validation-badge");
        const groundingNotes = registerId("grounding-notes");
        const qeResults = registerId("qe-results");
        const laurelStatus = registerId("laurel-status");
        const runBtn = registerId("run-btn", "button");
        const runBtnLabel = registerId("run-btn-label");
        const exampleSelect = registerId("example-select", "select");
        const srcOntology = registerId("src-ontology", "input");
        srcOntology.checked = true;
        const srcShapes = registerId("src-shapes", "input");
        srcShapes.checked = false;
        registerId("export-csv-btn", "button");
        registerId("clear-results-btn", "button");
        registerId("copy-sparql-btn", "button");
        registerId("sample-question-btn", "button");
        registerId("toggle-advanced-btn", "button");
        registerId("advanced-console", "details");
        registerId("focus-question-btn", "button");
        registerId("copy-query-btn", "button");
        registerId("clear-query-btn", "button");
        registerId("qe-status");

        registerSelector("[data-status-model]", new FakeElement("", "span"));
        registerSelector("[data-status-grounding]", new FakeElement("", "span"));
        registerSelector("[data-status-validator]", new FakeElement("", "span"));
        registerSelector("[data-grounding-count]", new FakeElement("", "span"));
        registerSelector("[data-theme-toggle]", new FakeElement("", "button"));
        registerSelector("[data-theme-label]", new FakeElement("", "span"));
        registerSelector("[data-power-toggle]", new FakeElement("", "button"));
        registerSelector("[data-power-label]", new FakeElement("", "span"));
        registerSelector("[data-repository-url]", new FakeElement("", "a"));
        registerSelector("[data-pages-base-url]", new FakeElement("", "span"));
        const siteError = registerSelector("[data-site-error]", new FakeElement("", "div"));
        siteError.hidden = true;

        const document = {{
          body,
          head,
          documentElement,
          getElementById(id) {{
            return byId.get(id) || null;
          }},
          querySelector(selector) {{
            return bySelector.get(selector) || null;
          }},
          querySelectorAll(selector) {{
            return selectorLists.get(selector) || [];
          }},
          createElement(tag) {{
            return new FakeElement("", tag);
          }},
        }};

        class FakeBinding {{
          constructor(values) {{
            this.values = values;
          }}
          get(name) {{
            const value = this.values[name];
            return value === undefined ? undefined : {{ termType: "Literal", value }};
          }}
          [Symbol.iterator]() {{
            return Object.entries(this.values)
              .map(([name, value]) => [{{ termType: "Variable", value: name }}, {{ termType: "Literal", value }}])[Symbol.iterator]();
          }}
        }}

        class FakeWorker {{
          constructor(url) {{
            this.url = url;
            this.onmessage = null;
            this.onerror = null;
          }}
          postMessage(payload) {{
            queueMicrotask(() => {{
              try {{
                let message;
                if (this.url.includes("retrieval-worker")) {{
                  message = {{
                    requestId: payload.requestId,
                    matches: [{{
                      kind: "example",
                      label: "super effective moves",
                      score: 0.99,
                      query: queryText,
                    }}],
                  }};
                }} else if (this.url.includes("llm-worker")) {{
                  message = {{
                    requestId: payload.requestId,
                    backend: "CPU fallback synthesizer",
                    sparql: queryText,
                    fallbackSparql: queryText,
                    summary: "synthetic test response",
                  }};
                }} else {{
                  if (payload.action === "warmup") {{
                    message = {{
                      requestId: payload.requestId,
                      ok: true,
                      warmed: true,
                      sources: payload.sources || [],
                    }};
                  }} else if (payload.action === "execute") {{
                    message = {{
                      requestId: payload.requestId,
                      result: {{
                        type: "bindings",
                        vars: ["myMoveLabel", "moveTypeName", "opponentLabel", "effectiveTypeName", "factor"],
                        bindings: [{{
                          myMoveLabel: {{ termType: "Literal", value: "Ember" }},
                          moveTypeName: {{ termType: "Literal", value: "Fire" }},
                          opponentLabel: {{ termType: "Literal", value: "Charizard" }},
                          effectiveTypeName: {{ termType: "Literal", value: "Flying" }},
                          factor: {{ termType: "Literal", value: "2.0" }},
                        }}],
                      }},
                    }};
                  }} else {{
                    message = {{
                      requestId: payload.requestId,
                      ok: true,
                      messages: ["validated in test harness"],
                      normalized: queryText,
                    }};
                  }}
                }}
                this.onmessage?.({{ data: message }});
              }} catch (error) {{
                this.onerror?.({{ error }});
              }}
            }});
          }}
        }}

        globalThis.document = document;
        globalThis.window = globalThis;
        Object.defineProperty(globalThis, "navigator", {{
          configurable: true,
          value: {{
            gpu: null,
            clipboard: {{ writeText: async () => {{}} }},
          }},
        }});
        Object.defineProperty(globalThis, "location", {{
          configurable: true,
          value: {{ href: "https://example.test/pokemontology/docs/index.html" }},
        }});
        Object.defineProperty(globalThis, "localStorage", {{
          configurable: true,
          value: {{
          store: new Map(),
          getItem(key) {{ return this.store.has(key) ? this.store.get(key) : null; }},
          setItem(key, value) {{ this.store.set(key, String(value)); }},
          }},
        }});
        globalThis.matchMedia = () => ({{ matches: false }});
        globalThis.IntersectionObserver = class {{
          constructor() {{}}
          observe() {{}}
          disconnect() {{}}
        }};
        globalThis.Worker = FakeWorker;
        globalThis.fetch = async (url) => {{
          const target = String(url);
          if (target.endsWith("site-data.json")) {{
            return {{ ok: true, json: async () => siteData }};
          }}
          if (target.endsWith("schema-index.json")) {{
            return {{ ok: true, json: async () => schemaPack }};
          }}
          throw new Error(`unexpected fetch: ${{target}}`);
        }};
        globalThis.performance = {{ now: () => 123 }};
        globalThis.URL = URL;
        globalThis.URL.createObjectURL = () => "blob:test";
        globalThis.URL.revokeObjectURL = () => {{}};
        const module = await import(pathToFileURL(path.join(repo, "docs", "js", "laurel-app.js")).href + "?page-e2e");
        await module.createLaurelApp();
        question.value = "Which of my moves are effective against Charizard?";
        await laurelRunBtn.click();

        console.log(JSON.stringify({{
          generatedQuery: generatedPreview.textContent,
          findingsHtml: qeResults.innerHTML,
          validationHtml: validationList.innerHTML,
          validationBadge: validationBadge.textContent,
          statusText: laurelStatus.textContent,
        }}));
        """
    )

    script_path = tmp_path / "web-page-e2e.mjs"
    script_path.write_text(script, encoding="utf-8")

    completed = subprocess.run(
        ["node", str(script_path)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert "pkm:actor" in payload["generatedQuery"]
    assert "Ember is a Fire-type move" in payload["findingsHtml"]
    assert "hits Charizard's Flying typing for 2.0x damage" in payload["findingsHtml"]
    assert "validated in test harness" in payload["validationHtml"]
    assert payload["validationBadge"] == "Validated"
    assert payload["statusText"] == "Field query complete."


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web integration")
def test_web_page_controller_ignores_stale_prior_query_updates(tmp_path: Path) -> None:
    site_data_text = (REPO / "docs" / "site-data.json").read_text(encoding="utf-8")
    schema_index_text = SCHEMA_INDEX.read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const siteData = {site_data_text};
        const schemaPack = {schema_index_text};

        class FakeClassList {{
          constructor() {{
            this.names = new Set();
          }}
          toggle(name, force) {{
            if (force === undefined) {{
              if (this.names.has(name)) this.names.delete(name);
              else this.names.add(name);
              return this.names.has(name);
            }}
            if (force) this.names.add(name);
            else this.names.delete(name);
            return force;
          }}
        }}

        class FakeElement {{
          constructor(id = "", tag = "div") {{
            this.id = id;
            this.tagName = tag.toUpperCase();
            this.listeners = {{}};
            this.children = [];
            this.attributes = new Map();
            this.dataset = {{}};
            this.classList = new FakeClassList();
            this.hidden = false;
            this.checked = false;
            this.disabled = false;
            this.open = false;
            this.value = "";
            this.innerHTML = "";
            this.textContent = "";
            this.href = "";
            this.selectionStart = 0;
            this.selectionEnd = 0;
          }}
          addEventListener(type, listener) {{
            (this.listeners[type] ||= []).push(listener);
          }}
          async dispatch(type, event = {{}}) {{
            for (const listener of this.listeners[type] || []) {{
              await listener({{
                preventDefault() {{}},
                stopPropagation() {{}},
                target: this,
                currentTarget: this,
                ...event,
              }});
            }}
          }}
          async click() {{
            await this.dispatch("click");
          }}
          setAttribute(name, value) {{
            this.attributes.set(name, String(value));
            if (name === "hidden") this.hidden = true;
            if (name.startsWith("data-")) {{
              this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
            }}
          }}
          removeAttribute(name) {{
            this.attributes.delete(name);
            if (name === "hidden") this.hidden = false;
          }}
          appendChild(child) {{
            this.children.push(child);
            return child;
          }}
          removeChild(child) {{
            this.children = this.children.filter((entry) => entry !== child);
          }}
          focus() {{}}
        }}

        const byId = new Map();
        const bySelector = new Map();
        const selectorLists = new Map([
          ["main section[id]", []],
          [".nav-links a[href^='#']", []],
        ]);

        function registerId(id, tag = "div") {{
          const element = new FakeElement(id, tag);
          byId.set(id, element);
          return element;
        }}
        function registerSelector(selector, element) {{
          bySelector.set(selector, element);
          return element;
        }}

        const documentElement = new FakeElement("", "html");
        documentElement.dataset = {{}};
        const body = new FakeElement("", "body");
        body.dataset = {{}};
        const head = new FakeElement("", "head");

        const question = registerId("nl-question", "textarea");
        const laurelRunBtn = registerId("laurel-run-btn", "button");
        const sparqlEditor = registerId("sparql-editor", "textarea");
        const generatedPreview = registerId("generated-query-preview", "code");
        const validationList = registerId("validation-list");
        const validationBadge = registerId("validation-badge");
        registerId("grounding-notes");
        const qeResults = registerId("qe-results");
        const laurelStatus = registerId("laurel-status");
        const runBtn = registerId("run-btn", "button");
        registerId("run-btn-label");
        registerId("example-select", "select");
        const srcOntology = registerId("src-ontology", "input");
        srcOntology.checked = true;
        const srcMechanics = registerId("src-mechanics", "input");
        srcMechanics.checked = true;
        const srcPokeapiDemo = registerId("src-pokeapi-demo", "input");
        srcPokeapiDemo.checked = false;
        const srcShapes = registerId("src-shapes", "input");
        srcShapes.checked = false;
        registerId("export-csv-btn", "button");
        registerId("clear-results-btn", "button");
        registerId("copy-sparql-btn", "button");
        registerId("sample-question-btn", "button");
        registerId("toggle-advanced-btn", "button");
        registerId("advanced-console", "details");
        registerId("focus-question-btn", "button");
        registerId("copy-query-btn", "button");
        registerId("clear-query-btn", "button");
        registerId("qe-status");

        registerSelector("[data-status-model]", new FakeElement("", "span"));
        registerSelector("[data-status-grounding]", new FakeElement("", "span"));
        registerSelector("[data-status-validator]", new FakeElement("", "span"));
        registerSelector("[data-grounding-count]", new FakeElement("", "span"));
        registerSelector("[data-theme-toggle]", new FakeElement("", "button"));
        registerSelector("[data-theme-label]", new FakeElement("", "span"));
        registerSelector("[data-power-toggle]", new FakeElement("", "button"));
        registerSelector("[data-power-label]", new FakeElement("", "span"));
        registerSelector("[data-repository-url]", new FakeElement("", "a"));
        registerSelector("[data-pages-base-url]", new FakeElement("", "span"));
        const siteError = registerSelector("[data-site-error]", new FakeElement("", "div"));
        siteError.hidden = true;

        const document = {{
          body,
          head,
          documentElement,
          getElementById(id) {{
            return byId.get(id) || null;
          }},
          querySelector(selector) {{
            return bySelector.get(selector) || null;
          }},
          querySelectorAll(selector) {{
            return selectorLists.get(selector) || [];
          }},
          createElement(tag) {{
            return new FakeElement("", tag);
          }},
        }};

        class FakeBinding {{
          constructor(values) {{
            this.values = values;
          }}
          get(name) {{
            const value = this.values[name];
            return value === undefined ? undefined : {{ termType: "Literal", value }};
          }}
          [Symbol.iterator]() {{
            return Object.entries(this.values)
              .map(([name, value]) => [{{ termType: "Variable", value: name }}, {{ termType: "Literal", value }}])[Symbol.iterator]();
          }}
        }}

        class FakeWorker {{
          static llmQueue = [];

          constructor(url) {{
            this.url = url;
            this.onmessage = null;
            this.onerror = null;
          }}

          postMessage(payload) {{
            if (this.url.includes("retrieval-worker")) {{
              queueMicrotask(() => {{
                this.onmessage?.({{ data: {{ requestId: payload.requestId, matches: [] }} }});
              }});
              return;
            }}
            if (this.url.includes("query-worker")) {{
              queueMicrotask(() => {{
                if (payload.action === "warmup") {{
                  this.onmessage?.({{
                    data: {{
                      requestId: payload.requestId,
                      ok: true,
                      warmed: true,
                      sources: payload.sources || [],
                    }},
                  }});
                }} else if (payload.action === "execute") {{
                  const species = payload.sparql.includes("Pikachu") ? "Pikachu" : "Bulbasaur";
                  this.onmessage?.({{
                    data: {{
                      requestId: payload.requestId,
                      result: {{
                        type: "bindings",
                        vars: ["species"],
                        bindings: [{{
                          species: {{ termType: "Literal", value: species }},
                        }}],
                      }},
                    }},
                  }});
                }} else {{
                  this.onmessage?.({{
                    data: {{
                      requestId: payload.requestId,
                      ok: true,
                      messages: ["validated in test harness"],
                      normalized: payload.sparql,
                    }},
                  }});
                }}
              }});
              return;
            }}
            FakeWorker.llmQueue.push({{ worker: this, payload }});
          }}

          static respond(questionText, sparql) {{
            const index = FakeWorker.llmQueue.findIndex((entry) => entry.payload.question === questionText);
            if (index < 0) throw new Error(`missing queued LLM request for ${{questionText}}`);
            const [entry] = FakeWorker.llmQueue.splice(index, 1);
            entry.worker.onmessage?.({{
              data: {{
                requestId: entry.payload.requestId,
                backend: "CPU fallback synthesizer",
                sparql,
                fallbackSparql: sparql,
                summary: `response for ${{questionText}}`,
              }},
            }});
          }}
        }}

        globalThis.document = document;
        globalThis.window = globalThis;
        Object.defineProperty(globalThis, "navigator", {{
          configurable: true,
          value: {{
            gpu: null,
            clipboard: {{ writeText: async () => {{}} }},
          }},
        }});
        Object.defineProperty(globalThis, "location", {{
          configurable: true,
          value: {{ href: "https://example.test/pokemontology/docs/index.html" }},
        }});
        Object.defineProperty(globalThis, "localStorage", {{
          configurable: true,
          value: {{
            getItem() {{ return null; }},
            setItem() {{}},
          }},
        }});
        globalThis.matchMedia = () => ({{ matches: false }});
        globalThis.IntersectionObserver = class {{
          observe() {{}}
          disconnect() {{}}
        }};
        globalThis.Worker = FakeWorker;
        globalThis.fetch = async (url) => {{
          const target = String(url);
          if (target.endsWith("site-data.json")) return {{ ok: true, json: async () => siteData }};
          if (target.endsWith("schema-index.json")) return {{ ok: true, json: async () => schemaPack }};
          throw new Error(`unexpected fetch: ${{target}}`);
        }};
        globalThis.performance = {{ now: () => 123 }};
        globalThis.URL = URL;
        globalThis.URL.createObjectURL = () => "blob:test";
        globalThis.URL.revokeObjectURL = () => {{}};
        const module = await import(pathToFileURL(path.join(repo, "docs", "js", "laurel-app.js")).href + "?stale-query-e2e");
        await module.createLaurelApp();

        question.value = "First question";
        await question.dispatch("input");
        const firstRun = laurelRunBtn.click();
        await new Promise((resolve) => setTimeout(resolve, 0));

        question.value = "Second question";
        await question.dispatch("input");
        const secondRun = laurelRunBtn.click();
        await new Promise((resolve) => setTimeout(resolve, 0));

        FakeWorker.respond(
          "Second question",
          "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\\nSELECT ?species WHERE {{ VALUES ?species {{ \\"Pikachu\\" }} }} LIMIT 1",
        );
        await secondRun;

        FakeWorker.respond(
          "First question",
          "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\\nSELECT ?species WHERE {{ VALUES ?species {{ \\"Bulbasaur\\" }} }} LIMIT 1",
        );
        await firstRun;

        console.log(JSON.stringify({{
          generatedQuery: generatedPreview.textContent,
          findingsHtml: qeResults.innerHTML,
          statusText: laurelStatus.textContent,
          validationHtml: validationList.innerHTML,
          validationBadge: validationBadge.textContent,
          runDisabled: runBtn.disabled,
          pendingRequests: FakeWorker.llmQueue.length,
          questionValue: question.value,
          editorValue: sparqlEditor.value,
        }}));
        """
    )

    script_path = tmp_path / "web-page-stale-query-e2e.mjs"
    script_path.write_text(script, encoding="utf-8")

    completed = subprocess.run(
        ["node", str(script_path)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert "Pikachu" in payload["generatedQuery"]
    assert "Bulbasaur" not in payload["generatedQuery"]
    assert "Pikachu" in payload["findingsHtml"]
    assert "Bulbasaur" not in payload["findingsHtml"]
    assert payload["statusText"] == "Field query complete."
    assert "validated in test harness" in payload["validationHtml"]
    assert payload["validationBadge"] == "Validated"
    assert payload["runDisabled"] is False
    assert payload["pendingRequests"] == 0
    assert payload["questionValue"] == "Second question"
    assert "Pikachu" in payload["editorValue"]
