import { buildSelectedSources } from "./docs-sources.js";

const PKM_NS = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#";

const PREFIX_MAP = [
  ["https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#", "pkm:"],
  ["http://www.w3.org/2002/07/owl#", "owl:"],
  ["http://www.w3.org/2000/01/rdf-schema#", "rdfs:"],
  ["http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"],
  ["http://www.w3.org/2001/XMLSchema#", "xsd:"],
  ["http://www.w3.org/ns/shacl#", "sh:"],
];
const DEFAULT_SUMMARY_POLICY = {
  list_preview_limit: 5,
};

export const COMUNICA_BROWSER_URLS = [
  "https://rdf.js.org/comunica-browser/versions/v4/engines/query-sparql/comunica-browser.js",
  "https://cdn.jsdelivr.net/npm/@comunica/query-sparql@3/pkg/comunica-browser.js",
];

let lastSelectResult = null;
let summaryPolicy = DEFAULT_SUMMARY_POLICY;

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

function bindingTerm(binding, variable) {
  if (!binding) return null;
  if (typeof binding.get === "function") {
    return binding.get(variable);
  }
  return binding[variable] || null;
}

export function setResultsContent(html) {
  const panel = document.getElementById("qe-results");
  if (panel) panel.innerHTML = html;
}

export function toggleResultActions(show, { showExport = true } = {}) {
  const exportBtn = document.getElementById("export-csv-btn");
  const clearBtn = document.getElementById("clear-results-btn");
  if (exportBtn) {
    if (show && showExport) exportBtn.removeAttribute("hidden");
    else exportBtn.setAttribute("hidden", "");
  }
  if (clearBtn) {
    if (show) clearBtn.removeAttribute("hidden");
    else clearBtn.setAttribute("hidden", "");
  }
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
      <p class="laurel-answer-kicker">Inference Engine</p>
      <p>${escapeHtml(text)}</p>
    </div>`,
  );
}

export function configureQueryPresentation(schemaPack) {
  summaryPolicy = {
    ...DEFAULT_SUMMARY_POLICY,
    ...(schemaPack?.response || {}),
  };
}

function joinNaturalLanguageList(values) {
  if (!values.length) return "";
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

function variableLabel(variable) {
  return String(variable || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/^./, (match) => match.toLowerCase())
    .replace(/\biri\b/gi, "IRI");
}

function bindingValue(binding, variable) {
  const term = bindingTerm(binding, variable);
  return term ? shortenUri(term.value) : "";
}

function describeSingleBinding(question, vars, binding) {
  const record = Object.fromEntries(
    vars.map((variable) => [variable, bindingValue(binding, variable)]),
  );

  if (
    record.myMoveLabel &&
    record.moveTypeName &&
    record.opponentLabel &&
    record.effectiveTypeName &&
    record.factor
  ) {
    return `${record.myMoveLabel} is a ${record.moveTypeName}-type move and hits ${record.opponentLabel}'s ${record.effectiveTypeName} typing for ${record.factor}x damage.`;
  }

  if (record.moveTypeName && record.netScore) {
    return `Against this target, ${record.moveTypeName} is a strong attacking type with a net effectiveness score of ${record.netScore}.`;
  }

  const details = vars
    .map((variable) => {
      const value = record[variable];
      if (!value) return null;
      return `${variableLabel(variable)} ${value}`;
    })
    .filter(Boolean);
  if (!details.length) {
    return question ? `I found one matching result for "${question}".` : "I found one matching result.";
  }
  return details.join(", ").replace(/, ([^,]*)$/, ", and $1.") || "I found one matching result.";
}

export function summarizeQueryResult(question, result) {
  if (result.type === "boolean") {
    return result.value ? `Yes. ${question}` : `No. ${question}`;
  }
  if (result.type === "quads") {
    return `I assembled ${result.quads.length} triples from the graph for "${question}".`;
  }
  const { vars, bindings } = result;
  if (!bindings.length) {
    return question ? `I couldn't find matching graph results for "${question}".` : "I couldn't find matching graph results.";
  }
  const previewLimit = summaryPolicy.list_preview_limit || DEFAULT_SUMMARY_POLICY.list_preview_limit;

  if (vars.includes("moveTypeName") && vars.includes("netScore")) {
    const ranked = bindings
      .map((binding) => ({
        moveTypeName: bindingValue(binding, "moveTypeName"),
        netScore: bindingValue(binding, "netScore"),
      }))
      .filter((row) => row.moveTypeName);
    if (ranked.length) {
      const best = ranked[0];
      const others = ranked.slice(1, previewLimit).map((row) => row.moveTypeName);
      const followUp = others.length ? ` Other strong options are ${joinNaturalLanguageList(others)}.` : "";
      return `${best.moveTypeName} is the strongest attacking type match.${followUp}`.trim();
    }
  }

  if (vars.length === 1) {
    const values = bindings
      .map((binding) => bindingValue(binding, vars[0]))
      .filter(Boolean)
    if (values.length === 1) {
      return `The matching ${variableLabel(vars[0])} is ${values[0]}.`;
    }
    const preview = values.slice(0, previewLimit);
    return `The matching ${variableLabel(vars[0])} values are ${joinNaturalLanguageList(preview)}${values.length > previewLimit ? ", and more" : ""}.`;
  }
  if (bindings.length === 1) {
    return describeSingleBinding(question, vars, bindings[0]);
  }
  return `I found ${bindings.length} matching rows for "${question}".`;
}

export function renderQueryResults(result, question = "") {
  lastSelectResult = null;
  toggleResultActions(false);
  const summary = question ? summarizeQueryResult(question, result) : "";

  if (result.type === "boolean") {
    const cls = result.value ? "qe-ask-true" : "qe-ask-false";
    toggleResultActions(true, { showExport: false });
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
    toggleResultActions(true, { showExport: false });
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
    toggleResultActions(true, { showExport: false });
    setResultsContent('<div class="qe-empty">No results.</div>');
    return;
  }

  lastSelectResult = { vars, bindings };
  toggleResultActions(true);

  const headerCells = vars.map((v) => `<th>?${escapeHtml(v)}</th>`).join("");
  const rows = bindings
    .map((binding) => {
      const cells = vars.map((v) => `<td>${formatTermHtml(bindingTerm(binding, v))}</td>`).join("");
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
          const term = bindingTerm(binding, v);
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

export function buildSources(siteData) {
  return buildSelectedSources(siteData);
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
