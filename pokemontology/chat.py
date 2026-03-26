"""Local-model NL-to-SPARQL translation helpers with RAG support."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib import error, request

from pyparsing import ParseException
from rdflib.plugins.sparql.parser import parseQuery


DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"

_FENCED_BLOCK_RE = re.compile(r"```(?:sparql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_PREFIX_LINE_RE = re.compile(r"^(?:PREFIX|BASE)\b.*$", re.IGNORECASE | re.MULTILINE)
_PREFIX_DECL_RE = re.compile(r"^\s*(?:PREFIX|BASE)\b", re.IGNORECASE)
_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(?:INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD|SERVICE)\b",
    re.IGNORECASE,
)
_ALLOWED_QUERY_RE = re.compile(r"^(SELECT|ASK|DESCRIBE|CONSTRUCT)\b", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text
        ).split()
        if token
    ]


def vectorize(text: str, vocabulary: list[str]) -> list[int]:
    tokens = tokenize(text)
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return [counts.get(token, 0) for token in vocabulary]


def cosine_similarity(left: list[int], right: list[int]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l, r in zip(left, right):
        dot += l * r
        left_norm += l * l
        right_norm += r * r
    if not left_norm or not right_norm:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def get_minimum_score(question: str) -> float:
    token_count = len(tokenize(question))
    if token_count <= 2:
        return 0.34
    if token_count <= 5:
        return 0.24
    return 0.16


def retrieve_matches(
    question: str, schema_pack: dict[str, any], top_k: int = 4
) -> list[dict[str, any]]:
    vocabulary = schema_pack.get("vocabulary", [])
    vectors = schema_pack.get("vectors", [])
    items = schema_pack.get("items", [])
    if not vocabulary or not vectors or not items:
        return []

    query_vector = vectorize(question, vocabulary)
    min_score = get_minimum_score(question)

    scored_items = []
    for item, vector in zip(items, vectors):
        score = cosine_similarity(query_vector, vector)
        if score >= min_score:
            scored_items.append({**item, "score": score})

    scored_items.sort(key=lambda x: x["score"], reverse=True)
    return scored_items[:top_k]


def build_prompt(question: str, matches: list[dict[str, any]] | None = None) -> str:
    grounding = ""
    if matches:
        grounding_blocks = []
        for match in matches:
            label = match.get("label", "Unknown")
            kind = match.get("kind", "term")
            summary = match.get("summary", "")
            snippet = match.get("snippet", "")
            block = f"[{kind.upper()}] {label}\nSummary: {summary}\nExample/Pattern: {snippet}"
            grounding_blocks.append(block)
        grounding = "\nRELEVANT SCHEMA CONTEXT:\n" + "\n---\n".join(grounding_blocks) + "\n"

    return (
        "You are a SPARQL generator for Pokemontology.\n"
        "Translate the user's question into a single valid SPARQL query.\n"
        "Return only SPARQL or the exact error token described below.\n\n"
        "SCHEMA CONSTRAINTS:\n"
        "- Use pkm: for https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#\n"
        "- Common prefixes: rdf:, rdfs:, owl:, xsd:\n"
        "- Output MUST be plain SPARQL only.\n"
        "- Query must be read-only (SELECT, ASK, DESCRIBE, CONSTRUCT).\n"
        "- Forbidden keywords: INSERT, DELETE, DROP, CLEAR, LOAD, CREATE, COPY, MOVE, ADD, SERVICE.\n"
        "- If unrelated to Pokemon or this schema, return exactly: ERROR: unrelated_request\n"
        f"{grounding}\n"
        f"Question: {question.strip()}\n"
        "SPARQL:\n"
    )


def clean_sparql_output(text: str) -> str:
    cleaned = text.strip()
    fenced = _FENCED_BLOCK_RE.search(cleaned)
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
    try:
        parsed = parseQuery(cleaned)
    except ParseException as exc:
        raise ValueError(
            f"generated SPARQL failed formal parsing at line {exc.lineno}, column {exc.col}: {exc.msg}"
        ) from exc
    except Exception as exc:
        raise ValueError(f"generated SPARQL failed formal parsing: {exc}") from exc
    if not parsed or (not _PREFIX_DECL_RE.match(cleaned) and not _ALLOWED_QUERY_RE.match(cleaned.lstrip())):
        raise ValueError("generated SPARQL did not parse into a supported read-only query form")
    return cleaned


def generate_sparql(
    question: str,
    *,
    matches: list[dict[str, any]] | None = None,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    timeout: float = 240.0,
) -> str:
    payload = {
        "model": model,
        "prompt": build_prompt(question, matches=matches),
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
