let enginePromise = null;

self.onmessage = async (event) => {
  const { question, matches = [], schemaPack, webgpuAvailable } = event.data;
  const inferenceConfig = schemaPack?.inference || {};

  if (webgpuAvailable) {
    self.postMessage({
      type: "progress",
      backend: "WebGPU local inference",
      message: "Loading browser-local model…",
    });
    try {
      const engine = await getWebLlmEngine(inferenceConfig);
      self.postMessage({
        type: "progress",
        backend: "WebGPU local inference",
        message: "Running browser-local translation…",
      });
      const sparql = await generateWithWebLlm(engine, question || "", matches, schemaPack);
      self.postMessage({
        backend: "WebGPU local inference",
        sparql,
        fallbackSparql: buildFallbackQuery(question || "", matches, schemaPack).sparql,
        summary: "Translated with a browser-local model and Laurel grounding notes.",
      });
      return;
    } catch (error) {
      self.postMessage({
        type: "progress",
        backend: "Inference fallback",
        message: `Local model unavailable, falling back to deterministic translator: ${error.message}`,
      });
    }
  }

  const answer = buildFallbackQuery(question || "", matches, schemaPack);
  self.postMessage({
    backend: webgpuAvailable ? "deterministic fallback synthesizer" : "CPU fallback synthesizer",
    sparql: answer.sparql,
    fallbackSparql: answer.sparql,
    summary: answer.summary,
  });
};

async function getWebLlmEngine(inferenceConfig) {
  if (enginePromise) return enginePromise;
  enginePromise = loadWebLlmEngine(inferenceConfig);
  return enginePromise;
}

async function loadWebLlmEngine(inferenceConfig) {
  const libraryUrl = inferenceConfig.webllm_library_url || "https://esm.run/@mlc-ai/web-llm";
  const model = inferenceConfig.webllm_model || "Llama-3.2-1B-Instruct-q4f32_1-MLC";
  const module = await import(libraryUrl);
  const createEngine = module.CreateMLCEngine || module.CreateWebWorkerMLCEngine;
  if (typeof createEngine !== "function") {
    throw new Error("WebLLM engine factory was not available.");
  }
  return createEngine(model, {
    initProgressCallback(report) {
      const text = report?.text || report?.progress || "Loading browser-local model…";
      self.postMessage({
        type: "progress",
        backend: "WebGPU local inference",
        message: String(text),
      });
    },
  });
}

async function generateWithWebLlm(engine, question, matches, schemaPack) {
  const inferenceConfig = schemaPack?.inference || {};
  const completion = await engine.chat.completions.create({
    messages: [
      {
        role: "system",
        content: buildSystemPrompt(matches, schemaPack),
      },
      {
        role: "user",
        content: question,
      },
    ],
    temperature: inferenceConfig.temperature ?? 0,
    max_tokens: inferenceConfig.max_tokens || 320,
  });
  const content = completion?.choices?.[0]?.message?.content;
  if (typeof content !== "string" || !content.trim()) {
    throw new Error("The browser-local model did not return SPARQL text.");
  }
  return cleanModelOutput(content);
}

function buildSystemPrompt(matches, schemaPack) {
  const promptMatches = compactMatches(matches, schemaPack?.retrieval?.prompt_match_limit || 3);
  const context = promptMatches
    .map((match) => {
      const summary = compactText(match.summary || "", 180);
      const snippet = compactText(match.snippet || "", 220);
      return `[${String(match.kind || "term").toUpperCase()}] ${match.label}\nSummary: ${summary}\nExample: ${snippet}`;
    })
    .join("\n---\n");
  return [
    "You are Professor Laurel's browser-local SPARQL generator for Pokemontology.",
    "Return exactly one read-only SPARQL query and nothing else.",
    "Allowed query forms: SELECT, ASK, DESCRIBE, CONSTRUCT.",
    `Forbidden keywords: ${(schemaPack?.validation?.forbidden_keywords || []).join(", ")}.`,
    "If the question is unrelated to Pokemon mechanics or the supplied schema context, return exactly: ERROR: unrelated_request",
    context ? `Relevant grounding notes:\n${context}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function compactMatches(matches, limit) {
  const seen = new Set();
  return [...(matches || [])]
    .sort((left, right) => scoreMatch(left) - scoreMatch(right))
    .filter((match) => {
      const key = `${match.label || ""}::${match.iri || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);
}

function scoreMatch(match) {
  const kind = String(match.kind || "term");
  const rank = {
    example: 0,
    pattern: 1,
    class: 2,
    property: 3,
    individual: 4,
    term: 5,
  }[kind] ?? 6;
  return (rank * 1000) - Math.round(Number(match.score || 0) * 100);
}

function compactText(text, limit) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  if (compact.length <= limit) return compact;
  return `${compact.slice(0, limit - 1).trim()}…`;
}

function cleanModelOutput(text) {
  const fenced = text.match(/```(?:sparql)?\s*([\s\S]*?)```/i);
  return (fenced ? fenced[1] : text).trim();
}

function buildFallbackQuery(question, matches, schemaPack) {
  const lower = question.toLowerCase();
  const examples = schemaPack?.examples || [];
  const superEffective = examples.find((example) => example.id === "super-effective-moves");
  const superEffectiveTypes = /^which\s+move\s+types?\s+are\s+super\s+effective\s+against\s+(.+?)\??$/i.exec(question.trim());
  if (superEffectiveTypes) {
    const species = escapeLiteral(superEffectiveTypes[1]);
    return {
      sparql: `PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?moveTypeName (SUM(?factorScore) AS ?netScore)
WHERE {
  ?species a pkm:Species ;
           pkm:hasName "${species}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?defenderType .
  ?moveType a pkm:Type ;
            pkm:hasName ?moveTypeName .
  OPTIONAL {
    ?effectiveness a pkm:TypeEffectivenessAssignment ;
                   pkm:attackerType ?moveType ;
                   pkm:defenderType ?defenderType ;
                   pkm:hasDamageFactor ?factor .
  }
  BIND(
    IF(!BOUND(?factor), 0,
      IF(?factor = "0.0"^^xsd:decimal, -99,
        IF(?factor = "0.25"^^xsd:decimal, -2,
          IF(?factor = "0.5"^^xsd:decimal, -1,
            IF(?factor = "1.0"^^xsd:decimal, 0,
              IF(?factor = "2.0"^^xsd:decimal, 1,
                IF(?factor = "4.0"^^xsd:decimal, 2, 0)
              )
            )
          )
        )
      )
    ) AS ?factorScore
  )
}
GROUP BY ?moveTypeName
HAVING (SUM(?factorScore) > 0)
ORDER BY DESC(?netScore) ?moveTypeName`,
      summary: "Synthesized a species type-effectiveness query that works with browser demo data.",
    };
  }
  if (/\beffective\b/.test(lower) && /\bmove/.test(lower) && superEffective) {
    return {
      sparql: superEffective.query,
      summary: "Matched to the bundled super-effective move template while browser-local inference was unavailable.",
    };
  }

  const typeCheck = /^is\s+(.+?)\s+a[n]?\s+(.+?)\s+type\??$/i.exec(question.trim());
  if (typeCheck) {
    const species = escapeLiteral(typeCheck[1]);
    const typeName = escapeLiteral(typeCheck[2]);
    return {
      sparql: `PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

ASK {
  ?species a pkm:Species ;
           pkm:hasName "${species}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type .
  ?type pkm:hasName "${typeName}" .
}`,
      summary: "Synthesized a typed ASK query from the question pattern.",
    };
  }

  const bestExample = (matches || []).find((match) => match.kind === "example" && match.query);
  if (bestExample) {
    return {
      sparql: bestExample.query,
      summary: `Reused the closest bundled example query: ${bestExample.label}.`,
    };
  }

  return {
    sparql: `PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

SELECT ?entity
WHERE {
  ?entity a pkm:Species .
}
ORDER BY ?entity
LIMIT 25`,
    summary: "Fell back to a safe exploratory SELECT query because no stronger pattern matched.",
  };
}

function escapeLiteral(text) {
  return String(text).replace(/["\\]/g, "\\$&");
}
