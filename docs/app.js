const THEME_STORAGE_KEY = "pokemontology-theme";

let _lastSelectResult = null;

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

// ── Navigation highlight ──────────────────────────────────────────────────────

function setupNavHighlight() {
  const sections = [...document.querySelectorAll("main section[id]")];
  const navLinks = [...document.querySelectorAll(".nav-links a[href^='#']")];
  if (!sections.length || !navLinks.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          navLinks.forEach((a) => {
            a.classList.toggle("nav-active", a.getAttribute("href") === `#${id}`);
          });
        }
      });
    },
    { rootMargin: "-20% 0px -65% 0px", threshold: 0 },
  );

  sections.forEach((s) => observer.observe(s));
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

function renderModules(modules, repositoryUrl) {
  const target = document.querySelector("[data-modules]");
  const count = document.querySelector("[data-module-count]");
  if (!target) return;
  if (count) count.textContent = String(modules.length);
  target.innerHTML = modules
    .map(
      (m, i) => `
        <article class="module-card fade-up delay-${(i % 3) + 1}">
          <h3>${m.name.replace(/^[0-9]+-/, "").replace(/-/g, " ")}</h3>
          <code>${m.source_path}</code>
          ${repositoryUrl ? `<div style="margin-top:0.5rem"><a class="example-link" href="${repositoryUrl}/blob/main/${m.source_path}" target="_blank" rel="noopener">View source →</a></div>` : ""}
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

function renderExamples(examples, repositoryUrl) {
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
          ${repositoryUrl ? `<a class="example-link" href="${repositoryUrl}/blob/main/${e.path}" target="_blank" rel="noopener">View on GitHub →</a>` : ""}
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
    group: "Schema",
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
    group: "Schema",
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
    group: "Schema",
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
    group: "Schema",
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
    group: "Schema",
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
    group: "Data",
    label: "Predicate frequency",
    query: `SELECT ?predicate (COUNT(?predicate) AS ?count)
WHERE { ?s ?predicate ?o }
GROUP BY ?predicate
ORDER BY DESC(?count)`,
  },
  {
    group: "Data",
    label: "Triple count",
    query: `SELECT (COUNT(*) AS ?triples)
WHERE { ?s ?p ?o }`,
  },
  {
    group: "Shapes",
    label: "SHACL shapes",
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
const COMUNICA_BROWSER_URLS = [
  "https://rdf.js.org/comunica-browser/versions/v4/engines/query-sparql/comunica-browser.js",
  "https://cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js",
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

function showExportBtn(show) {
  const btn = document.getElementById("export-csv-btn");
  if (!btn) return;
  if (show) btn.removeAttribute("hidden");
  else btn.setAttribute("hidden", "");
}

function renderQueryResults(result) {
  _lastSelectResult = null;
  showExportBtn(false);

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

  _lastSelectResult = { vars, bindings };
  showExportBtn(true);

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
  const sources = [];
  if (document.getElementById("src-ontology")?.checked) sources.push(new URL("./ontology.ttl", window.location.href).href);
  if (document.getElementById("src-shapes")?.checked) sources.push(new URL("./shapes.ttl", window.location.href).href);
  return sources;
}

async function iteratorToArray(stream) {
  if (!stream) return [];
  if (typeof stream.toArray === "function") {
    return stream.toArray();
  }
  const items = [];
  for await (const item of stream) {
    items.push(item);
  }
  return items;
}

function inferBindingVars(bindings) {
  const names = new Set();
  bindings.forEach((binding) => {
    if (!binding || typeof binding[Symbol.iterator] !== "function") return;
    for (const [variable] of binding) {
      if (variable?.termType === "Variable" && variable.value) {
        names.add(variable.value);
      }
    }
  });
  return [...names];
}

function normalizeMetadataVars(metadata) {
  const vars = metadata?.variables;
  if (!Array.isArray(vars)) return [];
  return vars
    .map((variable) => {
      if (typeof variable === "string") return variable.replace(/^\?/, "");
      if (variable?.value) return String(variable.value).replace(/^\?/, "");
      return "";
    })
    .filter(Boolean);
}

async function executeBindingsQuery(engine, sparql, sources) {
  if (typeof engine.query === "function") {
    const result = await engine.query(sparql, { sources });
    if (result?.resultType === "bindings") {
      const metadata = typeof result.metadata === "function" ? await result.metadata() : null;
      const stream = typeof result.execute === "function"
        ? await result.execute()
        : result.bindingsStream;
      const bindings = await iteratorToArray(stream);
      const vars = normalizeMetadataVars(metadata);
      return {
        type: "bindings",
        vars: vars.length ? vars : inferBindingVars(bindings),
        bindings,
      };
    }
  }

  const stream = await engine.queryBindings(sparql, { sources });
  const bindings = await iteratorToArray(stream);
  const vars = typeof stream?.getProperty === "function"
    ? normalizeMetadataVars(await stream.getProperty("variables"))
    : [];
  return {
    type: "bindings",
    vars: vars.length ? vars : inferBindingVars(bindings),
    bindings,
  };
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
    const quads = await iteratorToArray(stream);
    return { type: "quads", quads };
  }

  return executeBindingsQuery(engine, sparql, sources);
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function loadComunicaEngine() {
  if (window._qe_engine) return window._qe_engine;
  let lastError = null;
  for (const src of COMUNICA_BROWSER_URLS) {
    try {
      await loadScript(src);
      if (window.Comunica?.QueryEngine) {
        window._qe_engine = new window.Comunica.QueryEngine();
        return window._qe_engine;
      }
      lastError = new Error(`Comunica QueryEngine unavailable after loading ${src}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error("No SPARQL engine bundle could be loaded.");
}

function populateExampleSelect() {
  const sel = document.getElementById("example-select");
  if (!sel) return;
  const groups = [...new Set(EXAMPLE_QUERIES.map((q) => q.group).filter(Boolean))];
  groups.forEach((group) => {
    const og = document.createElement("optgroup");
    og.label = group;
    EXAMPLE_QUERIES.filter((q) => q.group === group).forEach((q) => {
      const opt = document.createElement("option");
      opt.value = q.label;
      opt.textContent = q.label;
      og.appendChild(opt);
    });
    sel.appendChild(og);
  });
  EXAMPLE_QUERIES.filter((q) => !q.group).forEach((q) => {
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
    if (q.sources) {
      document.getElementById("src-ontology").checked = q.sources.includes("ontology");
      document.getElementById("src-shapes").checked = q.sources.includes("shapes");
    }
  });

  // Copy query
  document.getElementById("copy-query-btn")?.addEventListener("click", async () => {
    const text = editor.value;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const btn = document.getElementById("copy-query-btn");
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1400);
    } catch (_) {}
  });

  // Clear editor
  document.getElementById("clear-query-btn")?.addEventListener("click", () => {
    editor.value = "";
    if (exampleSel) exampleSel.value = "";
    editor.focus();
  });

  // Export CSV
  document.getElementById("export-csv-btn")?.addEventListener("click", () => {
    if (!_lastSelectResult) return;
    const { vars, bindings } = _lastSelectResult;
    const lines = [
      vars.map((v) => JSON.stringify(v)).join(","),
      ...bindings.map((b) =>
        vars
          .map((v) => {
            const t = b.get(v);
            return t ? JSON.stringify(t.value) : '""';
          })
          .join(","),
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "sparql-results.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });

  // Run button
  runBtn?.addEventListener("click", async () => {
    const sparql = editor.value.trim();
    if (!sparql) return;

    runBtn.disabled = true;
    runLabel.textContent = "Running…";
    statusEl.textContent = "";
    _lastSelectResult = null;
    showExportBtn(false);
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
  loadComunicaEngine()
    .then(() => {
      runBtn.disabled = false;
      runLabel.textContent = "▶ Run";
    })
    .catch((error) => {
      runLabel.textContent = "Engine failed to load";
      console.error("Comunica init failed:", error);
      setResultsContent(
        `<div class="qe-error">Failed to load the SPARQL engine. ${escapeHtml(error.message)}</div>`,
      );
    });
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  setupThemeToggle();
  setupNavHighlight();
  initQueryEngine();
  try {
    const data = await loadSiteData();
    renderArtifacts(data.artifacts);
    renderModules(data.modules, data.site.repository_url);
    renderPipelines(data.pipelines);
    renderExamples(data.examples, data.site.repository_url);
    renderStats(data);
  } catch (error) {
    renderError(error);
  }
}

main();
