const PKM_NS = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#";

const PREFIX_MAP = [
  [PKM_NS, "pkm:"],
  ["http://www.w3.org/2002/07/owl#", "owl:"],
  ["http://www.w3.org/2000/01/rdf-schema#", "rdfs:"],
  ["http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"],
  ["http://www.w3.org/2001/XMLSchema#", "xsd:"],
  ["http://www.w3.org/ns/shacl#", "sh:"],
];

export const DEFAULT_PREFIXES = `PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX pkm:  <${PKM_NS}>

`;

export const COMUNICA_BROWSER_URLS = [
  "https://rdf.js.org/comunica-browser/versions/v4/engines/query-sparql/comunica-browser.js",
  "https://cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js",
];

let lastSelectResult = null;

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

export function setResultsContent(html) {
  const panel = document.getElementById("qe-results");
  if (panel) panel.innerHTML = html;
}

export function showExportBtn(show) {
  const btn = document.getElementById("export-csv-btn");
  if (!btn) return;
  if (show) btn.removeAttribute("hidden");
  else btn.setAttribute("hidden", "");
}

export function renderGeneratedQuery(queryText) {
  const preview = document.getElementById("generated-query-preview");
  if (!preview) return;
  preview.textContent = queryText || "No SPARQL generated yet.";
}

export function renderValidation(validation) {
  const target = document.getElementById("validation-list");
  const badge = document.getElementById("validation-badge");
  if (!target || !badge) return;
  if (!validation) {
    badge.textContent = "Awaiting validation";
    target.innerHTML = '<div class="validation-item">Validation notes will appear here before execution.</div>';
    return;
  }
  badge.textContent = validation.ok ? "Validated" : "Needs repair";
  target.innerHTML = validation.messages
    .map((message) => `<div class="validation-item">${escapeHtml(message)}</div>`)
    .join("");
}

export function renderGrounding(matches) {
  const target = document.getElementById("grounding-notes");
  const count = document.querySelector("[data-grounding-count]");
  if (!target) return;
  if (count) {
    count.textContent = `${matches.length} ${matches.length === 1 ? "match" : "matches"}`;
  }
  if (!matches.length) {
    target.innerHTML = `<div class="qe-empty">No strong schema grounding notes were found.</div>`;
    return;
  }
  target.innerHTML = matches
    .map(
      (match) => `
        <article class="grounding-card">
          <div class="grounding-meta">
            <span class="grounding-kind">${escapeHtml(match.kind)}</span>
            <span class="grounding-score">${Math.round((match.score || 0) * 100)}%</span>
          </div>
          <h3>${escapeHtml(match.label)}</h3>
          <p>${escapeHtml(match.summary || match.snippet || "")}</p>
          ${match.iri ? `<code>${escapeHtml(match.iri)}</code>` : ""}
        </article>`,
    )
    .join("");
}

export function renderFindingsSummary(text) {
  setResultsContent(
    `<div class="laurel-answer">
      <p class="laurel-answer-kicker">Professor Laurel</p>
      <p>${escapeHtml(text)}</p>
    </div>`,
  );
}

export function summarizeQueryResult(question, result) {
  if (result.type === "boolean") {
    return `${result.value ? "Yes." : "No."} ${question}`.trim();
  }
  if (result.type === "quads") {
    return `Laurel assembled ${result.quads.length} triples from the generated SPARQL.`;
  }
  const { vars, bindings } = result;
  if (!bindings.length) {
    return "Laurel found no matching results.";
  }
  if (vars.length === 1) {
    const values = bindings
      .map((binding) => binding.get(vars[0])?.value)
      .filter(Boolean);
    if (values.length === 1) {
      return `Laurel found 1 result: ${values[0]}.`;
    }
    if (values.length > 1) {
      const preview = values.slice(0, 5).join(", ");
      return `Laurel found ${values.length} results: ${preview}${values.length > 5 ? ", …" : ""}.`;
    }
  }
  if (bindings.length === 1) {
    const fields = vars
      .map((variable) => `${variable}=${bindings[0].get(variable)?.value ?? "—"}`)
      .join(", ");
    return `Laurel found 1 matching row: ${fields}.`;
  }
  return `Laurel found ${bindings.length} matching rows.`;
}

export function renderQueryResults(result, question = "") {
  lastSelectResult = null;
  showExportBtn(false);
  const summary = question ? summarizeQueryResult(question, result) : "";

  if (result.type === "boolean") {
    const cls = result.value ? "qe-ask-true" : "qe-ask-false";
    setResultsContent(
      `<div class="laurel-answer-inline">${escapeHtml(summary)}</div>
      <div class="qe-ask-result ${cls}">
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
      `<div class="laurel-answer-inline">${escapeHtml(summary)}</div>
      <div class="qe-construct">
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

  lastSelectResult = { vars, bindings };
  showExportBtn(true);

  const headerCells = vars.map((v) => `<th>?${escapeHtml(v)}</th>`).join("");
  const rows = bindings
    .map((binding) => {
      const cells = vars.map((v) => `<td>${formatTermHtml(binding.get(v))}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  setResultsContent(
    `${summary ? `<div class="laurel-answer-inline">${escapeHtml(summary)}</div>` : ""}
    <div class="qe-table-wrap">
      <table class="qe-table">
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="qe-count">${bindings.length} result${bindings.length !== 1 ? "s" : ""}</p>`,
  );
}

export function exportLastResultsToCsv() {
  if (!lastSelectResult) return;
  const { vars, bindings } = lastSelectResult;
  const lines = [
    vars.map((v) => JSON.stringify(v)).join(","),
    ...bindings.map((binding) =>
      vars
        .map((v) => {
          const term = binding.get(v);
          return term ? JSON.stringify(term.value) : '""';
        })
        .join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "sparql-results.csv";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
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

export function buildSources() {
  const sources = [];
  if (document.getElementById("src-ontology")?.checked) {
    sources.push(new URL("./ontology.ttl", window.location.href).href);
  }
  if (document.getElementById("src-shapes")?.checked) {
    sources.push(new URL("./shapes.ttl", window.location.href).href);
  }
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

export async function executeQuery(sparql, sources) {
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

export async function loadComunicaEngine() {
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
