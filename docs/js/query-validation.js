const PREFIX_RE = /^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*$/gim;
const FORBIDDEN_RE = /\b(?:INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD|SERVICE)\b/i;
const TYPE_RE = /\b(SELECT|ASK|DESCRIBE|CONSTRUCT)\b/i;
const COMMENT_RE = /#[^\n]*/g;
const SPARQLJS_URL = "https://esm.sh/sparqljs@3.7.3";

let parserPromise = null;

export async function validateQueryAst(sparql, schemaPack) {
  const trimmed = sparql.trim();
  if (!trimmed) {
    return { ok: false, messages: ["No SPARQL was generated."], normalized: "" };
  }

  const messages = [];
  if (FORBIDDEN_RE.test(trimmed)) {
    messages.push("Forbidden SPARQL keyword detected.");
  }

  const parseResult = await parseQuery(trimmed);
  const prefixes = parseResult.prefixes;
  const queryType = parseResult.queryType;
  if (!queryType) {
    messages.push("Could not identify a read-only query type.");
  } else if (parseResult.mode === "ast") {
    messages.push("AST parser certified a read-only SPARQL shape.");
  } else {
    messages.push("Fell back to structural validation because the browser AST parser is unavailable.");
  }

  const allowedPrefixes = new Set(
    (schemaPack?.prefixes || []).map((prefix) => prefix.alias.replace(/:$/, "")),
  );
  for (const prefix of prefixes) {
    if (!allowedPrefixes.has(prefix)) {
      messages.push(`Unknown prefix "${prefix}:" is not in the Laurel schema pack.`);
    }
  }

  const normalized = trimmed
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+$/gm, "")
    .trim();

  if (messages.length) {
    return { ok: false, messages, normalized };
  }

  return {
    ok: true,
    messages: [
      `${queryType} query parsed into a read-only Laurel-safe shape.`,
      "No update or federation constructs detected.",
      "Prefixes align with the shipped schema pack.",
      ...messages.filter((message) => message.startsWith("AST parser certified")),
    ],
    normalized,
  };
}

async function parseQuery(sparql) {
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
  return {
    mode: "fallback",
    prefixes,
    queryType: TYPE_RE.exec(body)?.[1]?.toUpperCase() || "",
  };
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
