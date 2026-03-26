"""Local-model NL-to-SPARQL translation helpers with RAG support."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib import error, request

from pyparsing import ParseException
from rdflib.plugins.sparql.parser import parseQuery


DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"
FORBIDDEN_SPARQL_KEYWORDS = (
    "INSERT",
    "DELETE",
    "DROP",
    "CLEAR",
    "LOAD",
    "CREATE",
    "COPY",
    "MOVE",
    "ADD",
    "SERVICE",
)
ALLOWED_READ_ONLY_QUERY_TYPES = ("SELECT", "ASK", "DESCRIBE", "CONSTRUCT")
RETRIEVAL_MINIMUM_SCORES = (
    (2, 0.34),
    (5, 0.24),
    (None, 0.16),
)
PROMPT_MATCH_LIMIT = 3
PROMPT_SUMMARY_LIMIT = 180
PROMPT_SNIPPET_LIMIT = 220
GENERATION_CACHE_SIZE = 64

_FENCED_BLOCK_RE = re.compile(r"```(?:sparql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_PREFIX_LINE_RE = re.compile(r"^(?:PREFIX|BASE)\b.*$", re.IGNORECASE | re.MULTILINE)
_PREFIX_DECL_RE = re.compile(r"^\s*(?:PREFIX|BASE)\b", re.IGNORECASE)
_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(FORBIDDEN_SPARQL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_ALLOWED_QUERY_RE = re.compile(
    r"^(" + "|".join(ALLOWED_READ_ONLY_QUERY_TYPES) + r")\b", re.IGNORECASE
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_WHERE_VAR_RE = re.compile(r"\bWHERE\s*\{([^}]*)\}", re.IGNORECASE | re.DOTALL)
_PROJECTED_VAR_RE = re.compile(r"\?([A-Za-z_][\w-]*)")
_GENERATION_CACHE: dict[tuple[str, str, str, str], str] = {}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text
        ).split()
        if token
    ]


def token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def vectorize(text: str, vocabulary: list[str]) -> list[int]:
    counts = token_counts(text)
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
    for max_tokens, score in RETRIEVAL_MINIMUM_SCORES:
        if max_tokens is None or token_count <= max_tokens:
            return score
    return RETRIEVAL_MINIMUM_SCORES[-1][1]


def retrieve_matches(
    question: str, schema_pack: dict[str, Any], top_k: int = 4
) -> list[dict[str, Any]]:
    items = schema_pack.get("items", [])
    if not items:
        return []

    sparse_index = schema_pack.get("sparse_index")
    item_norms = schema_pack.get("item_norms")
    if isinstance(sparse_index, dict) and isinstance(item_norms, list):
        return _retrieve_sparse_matches(question, items, sparse_index, item_norms, top_k=top_k)

    vocabulary = schema_pack.get("vocabulary", [])
    vectors = schema_pack.get("vectors", [])
    if not vocabulary or not vectors:
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


def _retrieve_sparse_matches(
    question: str,
    items: list[dict[str, Any]],
    sparse_index: dict[str, list[list[int | float]]],
    item_norms: list[float],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    query_counts = token_counts(question)
    if not query_counts:
        return []
    query_norm = math.sqrt(sum(count * count for count in query_counts.values()))
    if not query_norm:
        return []

    scores: dict[int, float] = {}
    for token, query_weight in query_counts.items():
        for item_index, item_weight in sparse_index.get(token, []):
            scores[item_index] = scores.get(item_index, 0.0) + (query_weight * float(item_weight))

    min_score = get_minimum_score(question)
    ranked: list[dict[str, Any]] = []
    for item_index, dot in scores.items():
        item_norm = item_norms[item_index] if item_index < len(item_norms) else 0.0
        if not item_norm:
            continue
        score = dot / (query_norm * item_norm)
        if score >= min_score:
            ranked.append({**items[item_index], "score": score})

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def _trim_prompt_text(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _score_prompt_match(match: dict[str, Any]) -> tuple[int, float]:
    kind = str(match.get("kind", "term"))
    kind_rank = {
        "example": 0,
        "pattern": 1,
        "class": 2,
        "property": 3,
        "individual": 4,
        "term": 5,
    }.get(kind, 6)
    return (kind_rank, -float(match.get("score", 0.0)))


def compact_prompt_matches(matches: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not matches:
        return []
    chosen: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for match in sorted(matches, key=_score_prompt_match):
        key = (str(match.get("label", "")), str(match.get("iri", "")))
        if key in seen_keys:
            continue
        chosen.append(match)
        seen_keys.add(key)
        if len(chosen) >= PROMPT_MATCH_LIMIT:
            break
    return chosen


def build_prompt(question: str, matches: list[dict[str, Any]] | None = None) -> str:
    grounding = ""
    prompt_matches = compact_prompt_matches(matches)
    if prompt_matches:
        grounding_blocks = []
        for match in prompt_matches:
            label = match.get("label", "Unknown")
            kind = match.get("kind", "term")
            summary = _trim_prompt_text(match.get("summary", ""), PROMPT_SUMMARY_LIMIT)
            snippet = _trim_prompt_text(match.get("snippet", ""), PROMPT_SNIPPET_LIMIT)
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
    lint_messages = lint_sparql_text(cleaned)
    if lint_messages:
        raise ValueError(f"generated SPARQL failed semantic lint: {'; '.join(lint_messages)}")
    return cleaned


def lint_sparql_text(text: str) -> list[str]:
    cleaned = clean_sparql_output(text)
    stripped = _PREFIX_LINE_RE.sub("", cleaned).lstrip()
    query_type_match = _ALLOWED_QUERY_RE.match(stripped)
    query_type = query_type_match.group(1).upper() if query_type_match else ""

    messages: list[str] = []
    if re.search(r"\bSELECT\s+\*", stripped, re.IGNORECASE):
        messages.append("SELECT * is too broad for generated Laurel queries")
    if query_type == "SELECT" and not _LIMIT_RE.search(cleaned) and not _ORDER_BY_RE.search(cleaned):
        messages.append("SELECT queries must include LIMIT or ORDER BY for bounded execution")

    body_match = _WHERE_VAR_RE.search(cleaned)
    body = body_match.group(1) if body_match else cleaned
    body_vars = set(_PROJECTED_VAR_RE.findall(body))
    if query_type == "SELECT":
        select_clause = stripped.split("WHERE", 1)[0]
        projected = set(_PROJECTED_VAR_RE.findall(select_clause))
        unbound = sorted(var for var in projected if var not in body_vars)
        if unbound:
            messages.append("projected variables are not bound in WHERE: " + ", ".join(f"?{var}" for var in unbound))
    return messages


def _generation_cache_key(
    question: str,
    matches: list[dict[str, Any]] | None,
    model: str,
    endpoint: str,
) -> tuple[str, str, str, str]:
    prompt_matches = compact_prompt_matches(matches)
    match_fingerprint = json.dumps(
        [
            {
                "label": match.get("label"),
                "kind": match.get("kind"),
                "summary": match.get("summary"),
                "snippet": match.get("snippet"),
            }
            for match in prompt_matches
        ],
        sort_keys=True,
    )
    return (question.strip(), model, endpoint, match_fingerprint)


def _remember_generated_query(key: tuple[str, str, str, str], query_text: str) -> None:
    _GENERATION_CACHE[key] = query_text
    if len(_GENERATION_CACHE) > GENERATION_CACHE_SIZE:
        oldest_key = next(iter(_GENERATION_CACHE))
        del _GENERATION_CACHE[oldest_key]


def generate_sparql(
    question: str,
    *,
    matches: list[dict[str, Any]] | None = None,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    timeout: float = 240.0,
) -> str:
    cache_key = _generation_cache_key(question, matches, model, endpoint)
    cached = _GENERATION_CACHE.get(cache_key)
    if cached is not None:
        return cached
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
    query_text = validate_sparql_text(parsed["response"])
    _remember_generated_query(cache_key, query_text)
    return query_text
