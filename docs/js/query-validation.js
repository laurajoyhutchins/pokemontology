const PREFIX_RE = /^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*$/gim;
const COMMENT_RE = /#[^\n]*/g;
const SPARQLJS_URL = "https://esm.sh/sparqljs@3.7.3";
const PROJECTED_VAR_RE = /\?([A-Za-z_][\w-]*)/g;
const PKM_TERM_RE = /\bpkm:([A-Za-z_][\w-]*)\b/g;
const LIMIT_RE = /\bLIMIT\s+\d+\b/i;
const ORDER_BY_RE = /\bORDER\s+BY\b/i;

let parserPromise = null;

export async function validateQueryAst(sparql, schemaPack) {
  const trimmed = sparql.trim();
  if (!trimmed) {
    return { ok: false, messages: ["No SPARQL was generated."], normalized: "" };
  }

  const errors = [];
  const notes = [];
  const forbiddenKeywords = schemaPack?.validation?.forbidden_keywords || [];
  const allowedQueryTypes = schemaPack?.validation?.allowed_query_types || [];
  const knownTerms = new Set(schemaPack?.validation?.known_terms || []);
  const forbiddenRe = buildKeywordRegex(forbiddenKeywords);
  if (forbiddenRe && forbiddenRe.test(trimmed)) {
    errors.push("Forbidden SPARQL keyword detected.");
  }

  const parseResult = await parseQuery(trimmed, allowedQueryTypes);
  const prefixes = parseResult.prefixes;
  const queryType = parseResult.queryType;
  if (!queryType) {
    errors.push(parseResult.error ? `SPARQL parsing failed: ${parseResult.error.message || parseResult.error}` : "Could not identify a read-only query type.");
  } else if (allowedQueryTypes.length && !allowedQueryTypes.includes(queryType)) {
    errors.push(`Query type "${queryType}" is not in the Laurel read-only allowlist.`);
  } else if (parseResult.mode === "ast") {
    notes.push("AST parser certified a read-only SPARQL shape.");
  } else {
    notes.push("Fell back to structural validation because the browser AST parser is unavailable.");
  }

  const allowedPrefixes = new Set(
    (schemaPack?.prefixes || []).map((prefix) => prefix.alias.replace(/:$/, "")),
  );
  for (const prefix of prefixes) {
    if (!allowedPrefixes.has(prefix)) {
      errors.push(`Unknown prefix "${prefix}:" is not in the Laurel schema pack.`);
    }
  }

  errors.push(...lintQuerySemantics(trimmed, queryType, knownTerms));

  const normalized = trimmed
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .trim();

  if (errors.length) {
    return { ok: false, messages: [...errors, ...notes], normalized };
  }

  return {
    ok: true,
    messages: [
      `${queryType} query parsed into a read-only Laurel-safe shape.`,
      "No update or federation constructs detected.",
      "Prefixes align with the shipped schema pack.",
      ...notes,
    ],
    normalized,
  };
}

function lintQuerySemantics(sparql, queryType, knownTerms) {
  const messages = [];
  if (/^\s*(?:PREFIX\b.*\n)*\s*SELECT\s+\*/im.test(sparql)) {
    messages.push("Generated SELECT queries must project explicit variables instead of SELECT *.");
  }
  if (queryType === "SELECT" && !LIMIT_RE.test(sparql) && !ORDER_BY_RE.test(sparql)) {
    messages.push("Generated SELECT queries must include LIMIT or ORDER BY for bounded execution.");
  }

  const withoutComments = sparql.replace(COMMENT_RE, "");
  const body = withoutComments.replace(PREFIX_RE, "");
  const pkmTerms = [...body.matchAll(PKM_TERM_RE)].map((match) => match[1]);
  const unknownTerms = [...new Set(pkmTerms.filter((term) => knownTerms.size && !knownTerms.has(term)))];
  if (unknownTerms.length) {
    messages.push(`Generated query uses unknown pkm terms: ${unknownTerms.map((term) => `pkm:${term}`).join(", ")}`);
  }

  if (queryType === "SELECT") {
    const selectBody = body.split(/\bWHERE\b/i)[0] || body;
    const whereBody = body.split(/\bWHERE\b/i).slice(1).join(" WHERE ");
    const projected = [...new Set([...selectBody.matchAll(PROJECTED_VAR_RE)].map((match) => match[1]))];
    const bound = new Set([...whereBody.matchAll(PROJECTED_VAR_RE)].map((match) => match[1]));
    const unbound = projected.filter((variable) => !bound.has(variable));
    if (unbound.length) {
      messages.push(`Projected variables are not bound in WHERE: ${unbound.map((variable) => `?${variable}`).join(", ")}`);
    }
  }

  return messages;
}

async function parseQuery(sparql, allowedQueryTypes) {
  const parser = await loadParser();
  if (parser) {
    try {
      const parsed = parser.parse(sparql);
      return {
        mode: "ast",
        prefixes: Object.keys(parsed.prefixes || {}),
        queryType: String(parsed.queryType || "").toUpperCase(),
      };
    } catch (error) {
      return {
        mode: "ast",
        prefixes: [],
        queryType: "",
        error,
      };
    }
  }

  const withoutComments = sparql.replace(COMMENT_RE, "");
  const prefixes = [...withoutComments.matchAll(PREFIX_RE)].map((match) => match[1]);
  const body = withoutComments.replace(PREFIX_RE, "").trim();
  const typeRe = buildKeywordRegex(allowedQueryTypes, { anchored: false });
  return {
    mode: "fallback",
    prefixes,
    queryType: typeRe?.exec(body)?.[1]?.toUpperCase() || "",
  };
}

function buildKeywordRegex(keywords, { anchored = false } = {}) {
  if (!keywords.length) return null;
  const source = keywords.map((keyword) => escapeRegex(keyword)).join("|");
  return new RegExp(anchored ? `^(${source})\\b` : `\\b(${source})\\b`, "i");
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function loadParser() {
  if (parserPromise) return parserPromise;
  parserPromise = import(SPARQLJS_URL)
    .then((module) => {
      const Parser = module.Parser || module.default?.Parser;
      return Parser ? new Parser() : null;
    })
    .catch(() => null);
  return parserPromise;
}
