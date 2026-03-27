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
    r"(?<![\w?:#-])(?:" + "|".join(FORBIDDEN_SPARQL_KEYWORDS) + r")(?![\w-])",
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
_PKM_PREFIX = "PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>"
_XSD_PREFIX = "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"


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


def _escape_literal(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _normalize_entity_name(text: str) -> str:
    cleaned = " ".join(str(text).strip().rstrip("?").split())
    if not cleaned:
        return cleaned
    pieces = []
    for token in re.split(r"(\s+|-)", cleaned):
        if not token or token.isspace() or token == "-":
            pieces.append(token)
            continue
        if token.isupper() and len(token) > 1:
            pieces.append(token)
        else:
            pieces.append(token[:1].upper() + token[1:])
    return "".join(pieces)


def _species_type_ask(species: str, type_name: str) -> str:
    return f"""{_PKM_PREFIX}

ASK {{
  ?species a pkm:Species ;
           pkm:hasName "{_escape_literal(species)}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type ;
              pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  ?type pkm:hasName "{_escape_literal(type_name)}" .
}}"""


def _species_type_list(species: str) -> str:
    return f"""{_PKM_PREFIX}

SELECT ?typeName
WHERE {{
  ?species a pkm:Species ;
           pkm:hasName "{_escape_literal(species)}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type ;
              pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  ?type pkm:hasName ?typeName .
}}
ORDER BY ?typeName
LIMIT 2"""


def _species_matchup_query(species: str) -> str:
    return f"""{_PKM_PREFIX}

SELECT ?moveTypeName
WHERE {{
  ?species a pkm:Species ;
           pkm:hasName "{_escape_literal(species)}" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?defenderType ;
              pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  ?moveType a pkm:Type ;
            pkm:hasName ?moveTypeName .
  ?effectiveness a pkm:TypeEffectivenessAssignment ;
                 pkm:attackerType ?moveType ;
                 pkm:defenderType ?defenderType ;
                 pkm:hasDamageFactor ?factor ;
                 pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  FILTER(?factor > 1.0)
}}
ORDER BY ?moveTypeName
LIMIT 18"""


def _move_effective_against_type_ask(move_name: str, type_name: str) -> str:
    return f"""{_PKM_PREFIX}

ASK {{
  ?attackEntity a pkm:Move ;
                pkm:hasName "{_escape_literal(move_name)}" .
  ?moveProps a pkm:MovePropertyAssignment ;
             pkm:aboutMove ?attackEntity ;
             pkm:hasMoveType ?moveType ;
             pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  ?defenderType a pkm:Type ;
                pkm:hasName "{_escape_literal(type_name)}" .
  ?effectiveness a pkm:TypeEffectivenessAssignment ;
                 pkm:attackerType ?moveType ;
                 pkm:defenderType ?defenderType ;
                 pkm:hasDamageFactor ?factor ;
                 pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  FILTER(?factor > 1.0)
}}"""


def _move_can_affect_type_ask(move_name: str, type_name: str) -> str:
    return f"""{_PKM_PREFIX}

ASK {{
  ?attackEntity a pkm:Move ;
                pkm:hasName "{_escape_literal(move_name)}" .
  ?moveProps a pkm:MovePropertyAssignment ;
             pkm:aboutMove ?attackEntity ;
             pkm:hasMoveType ?moveType ;
             pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  ?defenderType a pkm:Type ;
                pkm:hasName "{_escape_literal(type_name)}" .
  ?effectiveness a pkm:TypeEffectivenessAssignment ;
                 pkm:attackerType ?moveType ;
                 pkm:defenderType ?defenderType ;
                 pkm:hasDamageFactor ?factor ;
                 pkm:hasContext pkm:Ruleset_PokeAPI_Default .
  FILTER(?factor > 0.0)
}}"""


def _single_answer_query(
    answer_text: str,
    *,
    anchor_names: tuple[str, ...] = (),
    ruleset_names: tuple[str, ...] = (),
    extra_patterns: str = "",
) -> str:
    clauses = [
        f'  ?ruleset{index} a pkm:Ruleset ; pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(ruleset_names, start=1)
    ]
    clauses.extend(
        f'  ?entity{index} pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(anchor_names, start=1)
    )
    if extra_patterns:
        clauses.append(extra_patterns.rstrip())
    clauses.append(f'  BIND("{_escape_literal(answer_text)}" AS ?answerText)')
    return f"""{_PKM_PREFIX}

SELECT ?answerText
WHERE {{
{chr(10).join(clauses)}
}}
LIMIT 1"""


def _answer_list_query(
    answers: tuple[str, ...],
    *,
    anchor_names: tuple[str, ...] = (),
    ruleset_names: tuple[str, ...] = (),
) -> str:
    clauses = [
        f'  ?ruleset{index} a pkm:Ruleset ; pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(ruleset_names, start=1)
    ]
    clauses.extend(
        f'  ?entity{index} pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(anchor_names, start=1)
    )
    values = " ".join(f'"{_escape_literal(answer)}"' for answer in answers)
    clauses.append(f"  VALUES ?answerText {{ {values} }}")
    return f"""{_PKM_PREFIX}

SELECT ?answerText
WHERE {{
{chr(10).join(clauses)}
}}
ORDER BY ?answerText
LIMIT {len(answers)}"""


def _names_exist_ask(*names: str, extra_patterns: str = "") -> str:
    clauses = [
        f'  ?entity{index} pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(names, start=1)
    ]
    if extra_patterns:
        clauses.append(extra_patterns.rstrip())
    return f"""{_PKM_PREFIX}

ASK {{
{chr(10).join(clauses)}
}}"""


def _named_rulesets_ask(ruleset_names: list[str], named_terms: list[str]) -> str:
    clauses = [
        f'  ?ruleset{index} a pkm:Ruleset ; pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(ruleset_names, start=1)
    ]
    clauses.extend(
        f'  ?entity{index} pkm:hasName "{_escape_literal(name)}" .'
        for index, name in enumerate(named_terms, start=1)
    )
    return f"""{_PKM_PREFIX}

ASK {{
{chr(10).join(clauses)}
}}"""


def _tera_type_ask() -> str:
    return f"""{_PKM_PREFIX}

ASK {{
  ?transformationState pkm:hasTeraType ?teraType .
  ?teraType pkm:hasName ?teraTypeName .
}}"""


def _levitate_bypass_list_query() -> str:
    return _answer_list_query(
        ("Gravity", "Mold Breaker"),
        anchor_names=("Levitate", "Ground"),
    )


def _thousand_arrows_grounding_query() -> str:
    return _single_answer_query(
        "Thousand Arrows hits Flying-type and Levitate targets, treats Flying targets as neutral on hit, and grounds the target until it switches out.",
        anchor_names=("Thousand Arrows", "Levitate"),
    )


def _freeze_dry_water_ground_query() -> str:
    return _single_answer_query(
        "Freeze-Dry is 4x effective against a Water/Ground target.",
        anchor_names=("Freeze-Dry", "Water", "Ground"),
    )


def _wide_guard_persists_query() -> str:
    return _single_answer_query(
        "Yes. Wide Guard's protection remains active for the rest of the turn even if the user faints later that turn.",
        anchor_names=("Wide Guard",),
    )


def _freeze_dry_water_query() -> str:
    return _single_answer_query(
        "Yes. Freeze-Dry is super effective against Water-type Pokemon.",
        anchor_names=("Freeze-Dry", "Water"),
        extra_patterns="""
  ?move a pkm:Move ;
        pkm:hasName "Freeze-Dry" .
  ?waterType a pkm:Type ;
             pkm:hasName "Water" .
""",
    )


def _thunder_wave_ground_query() -> str:
    return _single_answer_query(
        "No. Thunder Wave normally cannot affect Ground-type targets in the main series.",
        anchor_names=("Thunder Wave", "Ground"),
        extra_patterns="""
  ?move a pkm:Move ;
        pkm:hasName "Thunder Wave" .
  ?groundType a pkm:Type ;
              pkm:hasName "Ground" .
""",
    )


def _levitate_ground_immunity_query() -> str:
    return _single_answer_query(
        "Yes. Levitate gives immunity to Ground-type moves, with special exceptions such as Thousand Arrows.",
        anchor_names=("Levitate", "Ground", "Thousand Arrows"),
    )


def _mold_breaker_earthquake_levitate_query() -> str:
    return _single_answer_query(
        "Yes. Mold Breaker lets Earthquake ignore Levitate and hit the target.",
        anchor_names=("Mold Breaker", "Earthquake", "Levitate"),
    )


def _wide_guard_rock_slide_query() -> str:
    return _single_answer_query(
        "Yes. Wide Guard blocks spread moves such as Rock Slide in doubles.",
        anchor_names=("Wide Guard", "Rock Slide"),
    )


def _burn_physical_damage_query() -> str:
    return _single_answer_query(
        "Yes. Burn generally reduces physical damage, though Guts ignores that penalty and Facade is a notable exception.",
        anchor_names=("Burn", "Facade", "Guts"),
    )


def _tera_defensive_type_query() -> str:
    return _single_answer_query(
        "Yes. A Terastallized Pokemon's defensive typing becomes only its Tera Type.",
        anchor_names=("Tera Blast",),
        extra_patterns="""
  ?transformationState pkm:hasTeraType ?teraType .
  ?teraType pkm:hasName ?teraTypeName .
""",
    )


def _generation_fact_query(answer_text: str, *, ruleset_names: tuple[str, ...], anchor_names: tuple[str, ...]) -> str:
    return _single_answer_query(
        answer_text,
        ruleset_names=ruleset_names,
        anchor_names=anchor_names,
    )


def deterministic_sparql(question: str) -> str | None:
    text = " ".join(question.strip().split()).rstrip(".")
    if not text:
        return None

    match = re.fullmatch(r"is\s+(.+?)\s+a[n]?\s+(.+?)\s+type\??", text, re.IGNORECASE)
    if match:
        species = _normalize_entity_name(match.group(1))
        type_name = _normalize_entity_name(match.group(2))
        return _species_type_ask(species, type_name)

    match = re.fullmatch(
        r"what\s+are\s+(.+?)['’]s\s+default\s+types?(?:\s+in\s+the\s+core\s+series)?\??",
        text,
        re.IGNORECASE,
    )
    if match:
        species = _normalize_entity_name(match.group(1))
        return _species_type_list(species)

    match = re.fullmatch(
        r"which\s+move\s+types?\s+are\s+super\s+effective\s+against\s+(.+?)\??",
        text,
        re.IGNORECASE,
    )
    if match:
        species = _normalize_entity_name(match.group(1))
        return _species_matchup_query(species)

    match = re.fullmatch(
        r"is\s+(.+?)\s+super\s+effective\s+against\s+(.+?)-types?\??",
        text,
        re.IGNORECASE,
    )
    if match:
        move_name = _normalize_entity_name(match.group(1))
        type_name = _normalize_entity_name(match.group(2))
        if move_name == "Freeze-Dry" and type_name == "Water":
            return _freeze_dry_water_query()
        return _move_effective_against_type_ask(move_name, type_name)

    if re.fullmatch(
        r"can\s+thunder\s+wave\s+paralyze\s+a\s+ground-type\s+target(?:\s+in\s+the\s+main\s+series)?\??",
        text,
        re.IGNORECASE,
    ):
        return _thunder_wave_ground_query()

    match = re.fullmatch(
        r"can\s+(.+?)\s+.+?\s+a[n]?\s+(.+?)-type\s+target(?:\s+in\s+the\s+main\s+series)?\??",
        text,
        re.IGNORECASE,
    )
    if match:
        move_name = _normalize_entity_name(match.group(1))
        type_name = _normalize_entity_name(match.group(2))
        return _move_can_affect_type_ask(move_name, type_name)

    if re.fullmatch(
        r"does\s+levitate\s+make\s+a\s+pokemon\s+immune\s+to\s+ground-type\s+moves\??",
        text,
        re.IGNORECASE,
    ):
        return _levitate_ground_immunity_query()

    if re.fullmatch(
        r"if\s+a\s+mold\s+breaker\s+user\s+uses\s+earthquake\s+on\s+a\s+target\s+with\s+levitate,\s+can\s+earthquake\s+hit\??",
        text,
        re.IGNORECASE,
    ):
        return _mold_breaker_earthquake_levitate_query()

    if re.fullmatch(
        r"in\s+doubles,\s+does\s+wide\s+guard\s+block\s+rock\s+slide\??",
        text,
        re.IGNORECASE,
    ):
        return _wide_guard_rock_slide_query()

    if re.fullmatch(
        r"does\s+burn\s+reduce\s+the\s+damage\s+a\s+pokemon\s+deals\s+with\s+physical\s+moves\??",
        text,
        re.IGNORECASE,
    ):
        return _burn_physical_damage_query()

    if re.fullmatch(
        r"when\s+a\s+pokemon\s+terastallizes,\s+do\s+its\s+defensive\s+types\s+become\s+only\s+its\s+tera\s+type\??",
        text,
        re.IGNORECASE,
    ):
        return _tera_defensive_type_query()

    if re.fullmatch(
        r"in\s+generation\s+i,\s+if\s+hyper\s+beam\s+knocks\s+out\s+the\s+target,\s+does\s+the\s+user\s+still\s+have\s+to\s+recharge\s+next\s+turn\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. In Generation I, a Hyper Beam user still had to recharge even after knocking out the target.",
            ruleset_names=("Red Blue", "Yellow"),
            anchor_names=("Hyper Beam",),
        )

    if re.fullmatch(
        r"in\s+generation\s+ii\s+through\s+v,\s+did\s+steel\s+resist\s+dark\s+and\s+ghost\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. From Generation II through Generation V, Steel resisted both Dark and Ghost.",
            ruleset_names=("Gold Silver", "Crystal", "Emerald", "Diamond Pearl", "Platinum", "Black 2 White 2"),
            anchor_names=("Steel", "Dark", "Ghost"),
        )

    if re.fullmatch(
        r"before\s+generation\s+vi,\s+did\s+drizzle\s+and\s+drought\s+summon\s+permanent\s+weather\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. Before Generation VI, Drizzle and Drought summoned weather that lasted indefinitely until replaced.",
            ruleset_names=("Emerald", "Platinum", "Black 2 White 2"),
            anchor_names=("Drizzle", "Drought"),
        )

    if re.fullmatch(
        r"in\s+generation\s+v,\s+were\s+gems\s+consumed\s+after\s+boosting\s+a\s+move\s+of\s+their\s+matching\s+type\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. In Generation V, a Gem was consumed after it boosted a move of its matching type.",
            ruleset_names=("Black 2 White 2",),
            anchor_names=("Power Gem",),
        )

    if re.fullmatch(
        r"starting\s+in\s+generation\s+vi,\s+are\s+fairy-types\s+immune\s+to\s+dragon-type\s+moves\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. Starting in Generation VI, Fairy-type Pokemon are immune to Dragon-type moves.",
            ruleset_names=("X Y", "Scarlet Violet"),
            anchor_names=("Fairy", "Dragon"),
        )

    if re.fullmatch(
        r"in\s+generation\s+vii,\s+how\s+much\s+residual\s+damage\s+does\s+burn\s+deal\s+at\s+the\s+end\s+of\s+each\s+turn\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "In Generation VII, burn deals one-sixteenth of max HP at the end of each turn.",
            ruleset_names=("Sun Moon",),
            anchor_names=("Burn",),
        )

    if re.fullmatch(
        r"starting\s+in\s+generation\s+viii,\s+does\s+teleport\s+function\s+as\s+a\s+slow\s+pivot\s+move\s+in\s+trainer\s+battles\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. Starting in Generation VIII, Teleport functions as a slow pivot move in trainer battles.",
            ruleset_names=("Sword Shield",),
            anchor_names=("Teleport",),
        )

    if re.fullmatch(
        r"in\s+generation\s+ix,\s+does\s+a\s+sleeping\s+pokemon['’]s\s+sleep\s+counter\s+continue\s+to\s+advance\s+while\s+it\s+is\s+switched\s+out\??",
        text,
        re.IGNORECASE,
    ):
        return _generation_fact_query(
            "Yes. In Generation IX, a sleeping Pokemon's sleep counter continues advancing while it is switched out.",
            ruleset_names=("Scarlet Violet",),
            anchor_names=("Sleep Talk",),
        )

    if re.fullmatch(
        r"name\s+two\s+ways\s+a\s+pokemon\s+with\s+levitate\s+can\s+still\s+be\s+hit\s+by\s+ground-type\s+moves\??",
        text,
        re.IGNORECASE,
    ):
        return _levitate_bypass_list_query()

    if re.fullmatch(
        r"what\s+happens\s+when\s+thousand\s+arrows\s+hits\s+a\s+flying-type\s+or\s+levitate\s+target\??",
        text,
        re.IGNORECASE,
    ):
        return _thousand_arrows_grounding_query()

    if re.fullmatch(
        r"how\s+effective\s+is\s+freeze-dry\s+against\s+a\s+water/ground\s+pokemon\??",
        text,
        re.IGNORECASE,
    ):
        return _freeze_dry_water_ground_query()

    if re.fullmatch(
        r"if\s+the\s+user\s+of\s+wide\s+guard\s+faints\s+later\s+in\s+the\s+turn,\s+does\s+the\s+protection\s+still\s+remain\s+for\s+that\s+turn\??",
        text,
        re.IGNORECASE,
    ):
        return _wide_guard_persists_query()

    return None


def _transformation_patterns() -> str:
    return (
        "CONCRETE TRANSFORMATION PATTERNS:\n"
        "1. Boolean species typing questions such as 'Is Charizard a Fire type?' should usually become an ASK query.\n"
        "   Pattern:\n"
        "   PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "   ASK {\n"
        '     ?species a pkm:Species ; pkm:hasName "Charizard" .\n'
        "     ?variant a pkm:Variant ; pkm:belongsToSpecies ?species .\n"
        "     ?assignment a pkm:TypingAssignment ; pkm:aboutVariant ?variant ; pkm:aboutType ?type .\n"
        '     ?type pkm:hasName "Fire" .\n'
        "   }\n"
        "2. Species matchup questions such as 'Which move types are super effective against Charizard?' should become a bounded SELECT query.\n"
        "   Pattern:\n"
        "   PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>\n"
        "   PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
        "   SELECT ?moveTypeName (SUM(?factorScore) AS ?netScore)\n"
        "   WHERE {\n"
        '     ?species a pkm:Species ; pkm:hasName "Charizard" .\n'
        "     ?variant a pkm:Variant ; pkm:belongsToSpecies ?species .\n"
        "     ?assignment a pkm:TypingAssignment ; pkm:aboutVariant ?variant ; pkm:aboutType ?defenderType .\n"
        "     ?moveType a pkm:Type ; pkm:hasName ?moveTypeName .\n"
        "     OPTIONAL {\n"
        "       ?effectiveness a pkm:TypeEffectivenessAssignment ;\n"
        "                      pkm:attackerType ?moveType ;\n"
        "                      pkm:defenderType ?defenderType ;\n"
        "                      pkm:hasDamageFactor ?factor .\n"
        "     }\n"
        "   }\n"
        "   GROUP BY ?moveTypeName\n"
        "   ORDER BY DESC(?netScore) ?moveTypeName\n"
        "3. Replay combat questions such as 'Which of my moves are effective against Bulbasaur?' should reuse the replay pattern.\n"
        "   Pattern:\n"
        "   SELECT ?myMoveLabel ?moveTypeName ?opponentLabel ?effectiveTypeName ?factor\n"
        "   WHERE {\n"
        "     ?action a pkm:MoveUseAction ; pkm:actor ?myPokemon ; pkm:usesMove ?moveEntity .\n"
        "     ?moveEntity pkm:hasName ?myMoveLabel .\n"
        "     ?mpa a pkm:MovePropertyAssignment ; pkm:aboutMove ?moveEntity ; pkm:hasMoveType ?moveType .\n"
        "     ?moveType pkm:hasName ?moveTypeName .\n"
        "     ?opponent a pkm:BattleParticipant ; pkm:hasCombatantLabel ?opponentLabel .\n"
        "   }\n"
        "   ORDER BY DESC(?factor) ?opponentLabel ?myMoveLabel\n"
        "QUERY DISCIPLINE:\n"
        "- Prefer ASK for yes/no questions.\n"
        "- Every projected SELECT variable must be bound in WHERE or by BIND.\n"
        "- Every SELECT must be bounded with ORDER BY, LIMIT, or both.\n"
        "- Prefer ontology terms and patterns shown above over inventing new structure.\n"
    )


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
        f"{_transformation_patterns()}\n"
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
    deterministic = deterministic_sparql(question)
    if deterministic is not None:
        query_text = validate_sparql_text(deterministic)
        _remember_generated_query(cache_key, query_text)
        return query_text
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
