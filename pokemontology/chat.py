"""Local-model NL-to-SPARQL translation helpers."""

from __future__ import annotations

import json
import re
from urllib import error, request


DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"

_SCHEMA_SUMMARY = """Prefixes:
- Use pkm: for https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#
- Common prefixes: rdf:, rdfs:, owl:, xsd:

Core classes:
- pkm:Species
- pkm:Variant
- pkm:Ruleset
- pkm:BattleParticipant
- pkm:Move
- pkm:Type

Relationship patterns:
- Variants belong to species and carry contextual assignments.
- Contextual facts often reify assignments for a subject inside a ruleset or version group.
- Typing may appear through assignment nodes that connect a variant to a type in context.
- Move learnsets may appear through assignment nodes that connect a variant or species to a move in context.
- Type effectiveness may appear through assignment nodes connecting attacking type, defending type, and multiplier.

Output requirements:
- Return SPARQL only.
- Query must be read-only and start with PREFIX/BASE declarations if needed, then SELECT, ASK, DESCRIBE, or CONSTRUCT.
- Never use INSERT, DELETE, DROP, CLEAR, LOAD, CREATE, COPY, MOVE, or ADD.
- If the request is unrelated to Pokemon or this schema, return exactly: ERROR: unrelated_request

Few-shot examples:
Question: What moves can Froakie learn?
SPARQL:
PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?move WHERE {
  ?species a pkm:Species ;
           rdfs:label "Froakie" .
  ?variant a pkm:Variant ;
           pkm:hasSpecies ?species .
  ?assignment pkm:hasSubject ?variant ;
              pkm:hasMove ?move .
}

Question: Is Charizard a Fire type?
SPARQL:
PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
ASK {
  ?species a pkm:Species ;
           rdfs:label "Charizard" .
  ?variant a pkm:Variant ;
           pkm:hasSpecies ?species .
  ?assignment pkm:hasSubject ?variant ;
              pkm:hasType ?type .
  ?type rdfs:label "Fire" .
}
"""

_FENCED_BLOCK_RE = re.compile(r"```(?:sparql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_PREFIX_LINE_RE = re.compile(r"^(?:PREFIX|BASE)\b.*$", re.IGNORECASE | re.MULTILINE)
_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(?:INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD)\b",
    re.IGNORECASE,
)
_ALLOWED_QUERY_RE = re.compile(r"^(SELECT|ASK|DESCRIBE|CONSTRUCT)\b", re.IGNORECASE)


def build_prompt(question: str) -> str:
    return (
        "You are a SPARQL generator for Pokemontology.\n"
        "Translate the user's question into a single valid SPARQL query.\n"
        "Return only SPARQL or the exact error token described below.\n\n"
        f"{_SCHEMA_SUMMARY}\n"
        f"Question: {question.strip()}\n"
        "SPARQL:\n"
    )


def clean_sparql_output(text: str) -> str:
    cleaned = text.strip()
    fenced = _FENCED_BLOCK_RE.fullmatch(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    return cleaned


def validate_sparql_text(text: str) -> str:
    cleaned = clean_sparql_output(text)
    if cleaned == "ERROR: unrelated_request":
        raise ValueError("request is unrelated to the Pokemontology schema")
    if _FORBIDDEN_KEYWORD_RE.search(cleaned):
        raise ValueError("generated SPARQL contains forbidden update keywords")
    stripped = _PREFIX_LINE_RE.sub("", cleaned).lstrip()
    if not _ALLOWED_QUERY_RE.match(stripped):
        raise ValueError("generated SPARQL must be a read-only SELECT, ASK, DESCRIBE, or CONSTRUCT query")
    return cleaned


def generate_sparql(
    question: str,
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    timeout: float = 240.0,
) -> str:
    payload = {
        "model": model,
        "prompt": build_prompt(question),
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.URLError as exc:
        raise RuntimeError(f"failed to reach Ollama endpoint {endpoint}: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
        raise RuntimeError("Ollama response did not include a text payload")
    return validate_sparql_text(parsed["response"])
