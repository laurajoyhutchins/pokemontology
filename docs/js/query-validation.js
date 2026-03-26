const PREFIX_RE = /^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*$/gim;
const FORBIDDEN_RE = /\b(?:INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD|SERVICE)\b/i;
const TYPE_RE = /\b(SELECT|ASK|DESCRIBE|CONSTRUCT)\b/i;
const COMMENT_RE = /#[^\n]*/g;

export async function validateQueryAst(sparql, schemaPack) {
  const trimmed = sparql.trim();
  if (!trimmed) {
    return { ok: false, messages: ["No SPARQL was generated."], normalized: "" };
  }

  const messages = [];
  if (FORBIDDEN_RE.test(trimmed)) {
    messages.push("Forbidden SPARQL keyword detected.");
  }

  const withoutComments = trimmed.replace(COMMENT_RE, "");
  const prefixes = [...withoutComments.matchAll(PREFIX_RE)].map((match) => match[1]);
  const body = withoutComments.replace(PREFIX_RE, "").trim();
  const queryType = TYPE_RE.exec(body)?.[1]?.toUpperCase() || "";
  if (!queryType) {
    messages.push("Could not identify a read-only query type.");
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
    ],
    normalized,
  };
}
