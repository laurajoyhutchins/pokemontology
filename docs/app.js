const THEME_STORAGE_KEY = "pokemontology-theme";

// ── Site metadata ─────────────────────────────────────────────────────────────

async function loadSiteData() {
  const response = await fetch("./site-data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load site-data.json: ${response.status}`);
  }
  return response.json();
}

// ── Theme ─────────────────────────────────────────────────────────────────────

function applyTheme(theme) {
  const root = document.documentElement;
  const toggle = document.querySelector("[data-theme-toggle]");
  const label = document.querySelector("[data-theme-label]");
  root.dataset.theme = theme;
  if (toggle) toggle.setAttribute("aria-pressed", String(theme === "dark"));
  if (label) label.textContent = theme === "dark" ? "Light" : "Dark";
}

function resolvedInitialTheme() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setupThemeToggle() {
  applyTheme(resolvedInitialTheme());
  const toggle = document.querySelector("[data-theme-toggle]");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    applyTheme(next);
  });
}

// ── Documentation renderers ───────────────────────────────────────────────────

function renderArtifacts(artifacts) {
  const target = document.querySelector("[data-artifacts]");
  if (!target) return;
  target.innerHTML = artifacts
    .map(
      (a) => `
        <article class="artifact-card fade-up delay-1">
          <h3>${a.label}</h3>
          <p>${a.description}</p>
          <div class="artifact-meta">
            <div><strong>IRI</strong> <code>${a.iri}</code></div>
            <div><a href="./${a.path}">Open ${a.path}</a></div>
          </div>
        </article>`,
    )
    .join("");
}

function renderModules(modules) {
  const target = document.querySelector("[data-modules]");
  const count = document.querySelector("[data-module-count]");
  if (!target) return;
  if (count) count.textContent = String(modules.length);
  target.innerHTML = modules
    .map(
      (m, i) => `
        <article class="module-card fade-up delay-${(i % 3) + 1}">
          <h3>${m.name.replace(/^[0-9]+-/, "").replace(/-/g, " ")}</h3>
          <p>Source module in the authoring graph.</p>
          <code>${m.source_path}</code>
        </article>`,
    )
    .join("");
}

function renderPipelines(pipelines) {
  const target = document.querySelector("[data-pipelines]");
  if (!target) return;
  target.innerHTML = pipelines
    .map(
      (p, i) => `
        <article class="pipeline-card fade-up delay-${(i % 3) + 1}">
          <h3>${p.name}</h3>
          <p>${p.summary}</p>
          <pre><code>${p.command}</code></pre>
        </article>`,
    )
    .join("");
}

function renderExamples(examples) {
  const target = document.querySelector("[data-examples]");
  if (!target) return;
  target.innerHTML = examples
    .map(
      (e, i) => `
        <article class="example-card fade-up delay-${(i % 3) + 1}">
          <span class="example-kind">${e.kind}</span>
          <h3>${e.name}</h3>
          <p>${e.summary}</p>
          <div class="example-path"><code>${e.path}</code></div>
        </article>`,
    )
    .join("");
}

function renderStats(data) {
  const repoLink = document.querySelector("[data-repository-url]");
  const pagesBase = document.querySelector("[data-pages-base-url]");
  if (repoLink) repoLink.href = data.site.repository_url;
  if (pagesBase) pagesBase.textContent = data.site.pages_base_url;
}

function renderError(error) {
  const fallback = document.querySelector("[data-site-error]");
  if (!fallback) return;
  fallback.hidden = false;
  fallback.textContent = `Site metadata unavailable: ${error.message}`;
}

// ── SPARQL Query Engine ───────────────────────────────────────────────────────

const PKM_NS = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#";

const PREFIX_MAP = [
  [PKM_NS, "pkm:"],
  ["http://www.w3.org/2002/07/owl#", "owl:"],
  ["http://www.w3.org/2000/01/rdf-schema#", "rdfs:"],
  ["http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"],
  ["http://www.w3.org/2001/XMLSchema#", "xsd:"],
  ["http://www.w3.org/ns/shacl#", "sh:"],
];

const DEFAULT_PREFIXES = `PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX pkm:  <${PKM_NS}>

`;

const EXAMPLE_QUERIES = [
  {
    label: "All pkm: classes",
    query:
      DEFAULT_PREFIXES +
      `SELECT ?class ?label ?comment
WHERE {
  ?class a owl:Class .
  FILTER(STRSTARTS(STR(?class), STR(pkm:)))
  OPTIONAL { ?class rdfs:label ?label }
  OPTIONAL { ?class rdfs:comment ?comment }
}
ORDER BY ?class`,
  },
  {
    label: "Object properties",
    query:
      DEFAULT_PREFIXES +
      `SELECT ?prop ?label ?domain ?range
WHERE {
  ?prop a owl:ObjectProperty .
  FILTER(STRSTARTS(STR(?prop), STR(pkm:)))
  OPTIONAL { ?prop rdfs:label ?label }
  OPTIONAL { ?prop rdfs:domain ?domain }
  OPTIONAL { ?prop rdfs:range ?range }
}
ORDER BY ?label`,
  },
  {
    label: "Datatype properties",
    query:
      DEFAULT_PREFIXES +
      `SELECT ?prop ?label ?domain ?range
WHERE {
  ?prop a owl:DatatypeProperty .
  FILTER(STRSTARTS(STR(?prop), STR(pkm:)))
  OPTIONAL { ?prop rdfs:label ?label }
  OPTIONAL { ?prop rdfs:domain ?domain }
  OPTIONAL { ?prop rdfs:range ?range }
}
ORDER BY ?label`,
  },
  {
    label: "Class hierarchy",
    query:
      DEFAULT_PREFIXES +
      `SELECT ?class ?parent ?label
WHERE {
  ?class a owl:Class .
  FILTER(STRSTARTS(STR(?class), STR(pkm:)))
  OPTIONAL {
    ?class rdfs:subClassOf ?parent .
    FILTER(!isBlank(?parent))
  }
  OPTIONAL { ?class rdfs:label ?label }
}
ORDER BY ?parent ?class`,
  },
  {
    label: "Functional properties",
    query:
      DEFAULT_PREFIXES +
      `SELECT ?prop ?label ?domain ?range
WHERE {
  ?prop a owl:FunctionalProperty .
  FILTER(STRSTARTS(STR(?prop), STR(pkm:)))
  OPTIONAL { ?prop rdfs:label ?label }
  OPTIONAL { ?prop rdfs:domain ?domain }
  OPTIONAL { ?prop rdfs:range ?range }
}
ORDER BY ?label`,
  },
  {
    label: "Predicate frequency",
    query: `SELECT ?predicate (COUNT(?predicate) AS ?count)
WHERE { ?s ?predicate ?o }
GROUP BY ?predicate
ORDER BY DESC(?count)`,
  },
  {
    label: "Triple count",
    query: `SELECT (COUNT(*) AS ?triples)
WHERE { ?s ?p ?o }`,
  },
  {
    label: "SHACL shapes (sources: shapes.ttl)",
    sources: ["shapes"],
    query:
      `PREFIX sh:   <http://www.w3.org/ns/shacl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?shape ?targetClass ?label
WHERE {
  ?shape a sh:NodeShape .
  OPTIONAL { ?shape sh:targetClass ?targetClass }
  OPTIONAL { ?shape rdfs:label ?label }
}
ORDER BY ?shape`,
  },
];

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function shortenUri(uri) {
  for (const [ns, prefix] of PREFIX_MAP) {
    if (uri.startsWith(ns)) return prefix + uri.slice(ns.length);
  }
  return uri;
}

function formatTermHtml(term) {
  if (!term) return '<span class="term-empty">—</span>';
  if (term.termType === "NamedNode") {
    const short = escapeHtml(shortenUri(term.value));
    const full = escapeHtml(term.value);
    return `<a class="term-iri" href="${full}" target="_blank" rel="noopener" title="${full}">${short}</a>`;
  }
  if (term.termType === "Literal") {
    return `<span class="term-literal">${escapeHtml(term.value)}</span>`;
  }
  if (term.termType === "BlankNode") {
    return `<span class="term-blank">_:${escapeHtml(term.value)}</span>`;
  }
  return escapeHtml(String(term.value));
}

function setResultsContent(html) {
  const panel = document.getElementById("qe-results");
  if (panel) panel.innerHTML = html;
}

function renderQueryResults(result) {
  if (result.type === "boolean") {
    const cls = result.value ? "qe-ask-true" : "qe-ask-false";
    setResultsContent(
      `<div class="qe-ask-result ${cls}">
        <span class="ask-label">ASK</span>
        <span class="ask-value">${result.value ? "TRUE" : "FALSE"}</span>
      </div>`,
    );
    return;
  }

  if (result.type === "quads") {
    const lines = result.quads
      .map(
        (q) =>
          `${shortenUri(q.subject.value)} ${shortenUri(q.predicate.value)} ${
            q.object.termType === "Literal"
              ? `"${q.object.value}"`
              : shortenUri(q.object.value)
          } .`,
      )
      .join("\n");
    setResultsContent(
      `<div class="qe-construct">
        <pre class="qe-construct-pre"><code>${escapeHtml(lines)}</code></pre>
        <p class="qe-count">${result.quads.length} triple${result.quads.length !== 1 ? "s" : ""}</p>
      </div>`,
    );
    return;
  }

  const { vars, bindings } = result;

  if (bindings.length === 0) {
    setResultsContent('<div class="qe-empty">No results.</div>');
    return;
  }

  const headerCells = vars.map((v) => `<th>?${escapeHtml(v)}</th>`).join("");
  const rows = bindings
    .map((b) => {
      const cells = vars.map((v) => `<td>${formatTermHtml(b.get(v))}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  setResultsContent(
    `<div class="qe-table-wrap">
      <table class="qe-table">
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="qe-count">${bindings.length} result${bindings.length !== 1 ? "s" : ""}</p>`,
  );
}

function detectQueryType(sparql) {
  const stripped = sparql
    .replace(/#[^\n]*/g, "")
    .replace(/\bPREFIX\s+\S*\s*<[^>]*>/gi, "")
    .trim()
    .toUpperCase();
  if (stripped.startsWith("ASK")) return "boolean";
  if (stripped.startsWith("CONSTRUCT") || stripped.startsWith("DESCRIBE")) return "quads";
  return "bindings";
}

function buildSources() {
  const base = new URL("./", window.location.href).href;
  const sources = [];
  if (document.getElementById("src-ontology")?.checked) sources.push(base + "ontology.ttl");
  if (document.getElementById("src-shapes")?.checked) sources.push(base + "shapes.ttl");
  return sources;
}

async function executeQuery(sparql, sources) {
  const engine = window._qe_engine;
  if (!engine) throw new Error("SPARQL engine not ready.");

  const queryType = detectQueryType(sparql);

  if (queryType === "boolean") {
    const value = await engine.queryBoolean(sparql, { sources });
    return { type: "boolean", value };
  }

  if (queryType === "quads") {
    const stream = await engine.queryQuads(sparql, { sources });
    const quads = await stream.toArray();
    return { type: "quads", quads };
  }

  const stream = await engine.queryBindings(sparql, { sources });
  const vars = stream.variables.map((v) => v.value);
  const bindings = await stream.toArray();
  return { type: "bindings", vars, bindings };
}

function populateExampleSelect() {
  const sel = document.getElementById("example-select");
  if (!sel) return;
  EXAMPLE_QUERIES.forEach((q) => {
    const opt = document.createElement("option");
    opt.value = q.label;
    opt.textContent = q.label;
    sel.appendChild(opt);
  });
}

function initQueryEngine() {
  const editor = document.getElementById("sparql-editor");
  const runBtn = document.getElementById("run-btn");
  const runLabel = document.getElementById("run-btn-label");
  const statusEl = document.getElementById("qe-status");
  const exampleSel = document.getElementById("example-select");

  if (!editor) return;

  // Set default query
  editor.value = EXAMPLE_QUERIES[0].query;

  populateExampleSelect();

  // Tab key → indent with spaces
  editor.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      editor.value = editor.value.slice(0, start) + "  " + editor.value.slice(end);
      editor.selectionStart = editor.selectionEnd = start + 2;
    }
    // Ctrl/Cmd+Enter → run
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!runBtn.disabled) runBtn.click();
    }
  });

  // Example selector
  exampleSel?.addEventListener("change", (e) => {
    const q = EXAMPLE_QUERIES.find((x) => x.label === e.target.value);
    if (!q) return;
    editor.value = q.query;
    // If the example specifies preferred sources, set them
    if (q.sources) {
      document.getElementById("src-ontology").checked = q.sources.includes("ontology");
      document.getElementById("src-shapes").checked = q.sources.includes("shapes");
    }
  });

  // Run button
  runBtn?.addEventListener("click", async () => {
    const sparql = editor.value.trim();
    if (!sparql) return;

    runBtn.disabled = true;
    runLabel.textContent = "Running…";
    statusEl.textContent = "";
    setResultsContent('<div class="qe-loading"><span class="qe-spinner"></span> Querying…</div>');

    try {
      const sources = buildSources();
      if (sources.length === 0) throw new Error("Select at least one source.");

      const t0 = performance.now();
      const result = await executeQuery(sparql, sources);
      const ms = Math.round(performance.now() - t0);

      renderQueryResults(result);
      statusEl.textContent = `${ms}ms`;
    } catch (err) {
      setResultsContent(
        `<div class="qe-error"><strong>Error:</strong> ${escapeHtml(err.message)}</div>`,
      );
      statusEl.textContent = "";
    } finally {
      runBtn.disabled = false;
      runLabel.textContent = "▶ Run";
    }
  });

  // Load Comunica dynamically
  const script = document.createElement("script");
  script.src =
    "https://cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js";
  script.onload = () => {
    try {
      window._qe_engine = new window.Comunica.QueryEngine();
      runBtn.disabled = false;
      runLabel.textContent = "▶ Run";
    } catch (e) {
      runLabel.textContent = "Engine error";
      console.error("Comunica init failed:", e);
    }
  };
  script.onerror = () => {
    runLabel.textContent = "Engine failed to load";
    setResultsContent(
      '<div class="qe-error">Failed to load the SPARQL engine from CDN. Check your network connection.</div>',
    );
  };
  document.head.appendChild(script);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  setupThemeToggle();
  initQueryEngine();
  try {
    const data = await loadSiteData();
    renderArtifacts(data.artifacts);
    renderModules(data.modules);
    renderPipelines(data.pipelines);
    renderExamples(data.examples);
    renderStats(data);
  } catch (error) {
    renderError(error);
  }
}

main();
