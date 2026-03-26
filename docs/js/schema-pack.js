export async function loadSchemaPack() {
  const response = await fetch("./schema-index.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load schema-index.json: ${response.status}`);
  }
  return response.json();
}

export function defaultQuestion(schemaPack) {
  return (
    schemaPack?.examples?.[0]?.question ||
    "Which of my moves are effective against Charizard?"
  );
}
