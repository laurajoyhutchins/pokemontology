const CURATED_DEFAULT_QUESTION = "Which move types are super effective against Charizard?";

export async function loadSchemaPack() {
  const response = await fetch("./schema-index.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load schema-index.json: ${response.status}`);
  }
  return response.json();
}

export function formatPrefixBlock(schemaPack) {
  const prefixes = schemaPack?.prefixes || [];
  if (!prefixes.length) return "";
  return `${prefixes
    .map((prefix) => `PREFIX ${prefix.alias.padEnd(5, " ")} <${prefix.iri}>`)
    .join("\n")}\n\n`;
}

export function defaultQuestion(schemaPack) {
  const schemaExample = schemaPack?.examples?.[0]?.question?.trim();
  if (schemaExample && schemaExample !== "Which of my moves are effective against Charizard?") {
    return schemaExample;
  }
  return CURATED_DEFAULT_QUESTION;
}
