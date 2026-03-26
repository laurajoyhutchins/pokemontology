self.onmessage = async (event) => {
  const { question, matches = [], schemaPack, webgpuAvailable } = event.data;
  const answer = buildQuery(question || "", matches, schemaPack);
  self.postMessage({
    backend: webgpuAvailable ? "webgpu-ready fallback synthesizer" : "cpu fallback synthesizer",
    sparql: answer.sparql,
    summary: answer.summary,
  });
};

function buildQuery(question, matches, schemaPack) {
  const lower = question.toLowerCase();
  const examples = schemaPack?.examples || [];
  const superEffective = examples.find((example) => example.id === "super-effective-moves");
  if (/\beffective\b/.test(lower) && /\bmove/.test(lower) && superEffective) {
    return {
      sparql: superEffective.query,
      summary: "Matched to the bundled super-effective move template while browser-local model integration is still warming up.",
    };
  }

  const typeCheck = /^is\s+(.+?)\s+a[n]?\s+(.+?)\s+type\??$/i.exec(question.trim());
  if (typeCheck) {
    const species = escapeLiteral(typeCheck[1]);
    const typeName = escapeLiteral(typeCheck[2]);
    return {
      sparql: `PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

ASK {
  ?species a pkm:Species ;
           rdfs:label "${species}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type .
  ?type rdfs:label "${typeName}" .
}`,
      summary: "Synthesized a typed ASK query from the question pattern.",
    };
  }

  const bestExample = matches.find((match) => match.kind === "example" && match.query);
  if (bestExample) {
    return {
      sparql: bestExample.query,
      summary: `Reused the closest bundled example query: ${bestExample.label}.`,
    };
  }

  return {
    sparql: `PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

SELECT ?entity WHERE {
  ?entity a pkm:Species .
}
LIMIT 25`,
    summary: "Fell back to a safe exploratory SELECT query because no stronger pattern matched.",
  };
}

function escapeLiteral(text) {
  return String(text).replace(/["\\]/g, "\\$&");
}
