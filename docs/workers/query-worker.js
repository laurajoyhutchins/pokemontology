import { validateQueryAst } from "../js/query-validation.js";

const COMUNICA_WORKER_URLS = [
  "https://esm.sh/@comunica/query-sparql@4?bundle",
  "https://esm.sh/@comunica/query-sparql@3?bundle",
];
const N3_WORKER_URLS = [
  "https://esm.sh/n3@1.17.4",
];

let cachedQueryEngine = null;
let cachedN3 = null;
const storeCache = new Map();

function normalizeSourceKey(sources = []) {
  return JSON.stringify([...sources].sort());
}

async function importFromFallback(urls) {
  let lastError = null;
  for (const url of urls) {
    try {
      return await import(url);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error("Failed to load browser query runtime.");
}

async function loadQueryEngine() {
  if (cachedQueryEngine) return cachedQueryEngine;
  const module = await importFromFallback(COMUNICA_WORKER_URLS);
  const QueryEngine = module.QueryEngine ?? module.default?.QueryEngine ?? module.default;
  if (!QueryEngine) {
    throw new Error("Comunica QueryEngine unavailable in worker runtime.");
  }
  cachedQueryEngine = new QueryEngine();
  return cachedQueryEngine;
}

async function loadN3() {
  if (cachedN3) return cachedN3;
  cachedN3 = await importFromFallback(N3_WORKER_URLS);
  return cachedN3;
}

function serializeTerm(term) {
  if (!term) return null;
  const payload = {
    termType: term.termType,
    value: term.value,
  };
  if (term.language) payload.language = term.language;
  if (term.datatype?.value) {
    payload.datatype = {
      termType: term.datatype.termType,
      value: term.datatype.value,
    };
  }
  return payload;
}

function serializeBinding(binding, vars) {
  const row = {};
  vars.forEach((variable) => {
    row[variable] = serializeTerm(binding.get(variable) || binding.get(`?${variable}`));
  });
  return row;
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

async function loadStoreForSources(sources, requestId) {
  const sourceKey = normalizeSourceKey(sources);
  const cached = storeCache.get(sourceKey);
  if (cached) return cached;

  self.postMessage({
    requestId,
    type: "progress",
    stage: "loading",
    message: "Warming local query graph…",
  });

  const [{ Parser, Store }] = await Promise.all([loadN3(), loadQueryEngine()]);
  const store = new Store();
  for (const source of sources) {
    self.postMessage({
      requestId,
      type: "progress",
      stage: "loading",
      message: `Loading ${source.split("/").at(-1)}…`,
    });
    const response = await fetch(source, { cache: "force-cache" });
    if (!response.ok) {
      throw new Error(`Failed to load ${source}: ${response.status}`);
    }
    const text = await response.text();
    const parser = new Parser({ baseIRI: source });
    store.addQuads(parser.parse(text));
  }

  storeCache.set(sourceKey, store);
  self.postMessage({
    requestId,
    type: "progress",
    stage: "ready",
    message: "Local query graph ready.",
  });
  return store;
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

async function executeQuery({ sparql, sources, requestId }) {
  if (!sparql?.trim()) {
    throw new Error("Cannot execute an empty SPARQL query.");
  }
  if (!Array.isArray(sources) || !sources.length) {
    throw new Error("Select at least one source.");
  }

  const [engine, store] = await Promise.all([
    loadQueryEngine(),
    loadStoreForSources(sources, requestId),
  ]);
  const querySources = [store];
  const queryType = detectQueryType(sparql);

  if (queryType === "boolean") {
    const value = await engine.queryBoolean(sparql, { sources: querySources });
    return { type: "boolean", value };
  }

  if (queryType === "quads") {
    const stream = await engine.queryQuads(sparql, { sources: querySources });
    const quads = await iteratorToArray(stream);
    return {
      type: "quads",
      quads: quads.map((quad) => ({
        subject: serializeTerm(quad.subject),
        predicate: serializeTerm(quad.predicate),
        object: serializeTerm(quad.object),
      })),
    };
  }

  const stream = await engine.queryBindings(sparql, { sources: querySources });
  const bindings = await iteratorToArray(stream);
  const vars =
    typeof stream?.getProperty === "function"
      ? (await stream.getProperty("variables") || [])
          .map((variable) => variable?.value || String(variable || "").replace(/^\?/, ""))
          .filter(Boolean)
      : inferBindingVars(bindings);
  return {
    type: "bindings",
    vars,
    bindings: bindings.map((binding) => serializeBinding(binding, vars)),
  };
}

self.onmessage = async (event) => {
  const { action = "validate", sparql, schemaPack, requestId, sources = [] } = event.data;
  try {
    if (action === "warmup") {
      await loadStoreForSources(sources, requestId);
      self.postMessage({
        requestId,
        ok: true,
        sources,
        warmed: true,
      });
      return;
    }

    if (action === "execute") {
      const result = await executeQuery({ sparql, sources, requestId });
      self.postMessage({ requestId, result });
      return;
    }

    const validation = await validateQueryAst(sparql, schemaPack);
    self.postMessage({ requestId, ...validation });
  } catch (error) {
    self.postMessage({
      requestId,
      error: error?.message || String(error),
    });
  }
};
