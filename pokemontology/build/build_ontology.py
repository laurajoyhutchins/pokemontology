#!/usr/bin/env python3
"""Assemble the consumer ontology file from modular Turtle source fragments."""

from __future__ import annotations

import json
import math
import re
import shutil

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from pokemontology._script_loader import repo_path
from pokemontology.chat import (
    ALLOWED_READ_ONLY_QUERY_TYPES,
    FORBIDDEN_SPARQL_KEYWORDS,
    PROMPT_MATCH_LIMIT,
    RETRIEVAL_MINIMUM_SCORES,
)
from pokemontology.laurel import SUMMARY_PREVIEW_LIMIT

REPO = repo_path()
MODULES_DIR = repo_path("ontology", "modules")
BUILD_DIR = repo_path("build")
OUTPUT = BUILD_DIR / "ontology.ttl"
BUILD_SHAPES = BUILD_DIR / "shapes.ttl"
PAGES_DIR = repo_path("docs")
PAGES_ONTOLOGY = PAGES_DIR / "ontology.ttl"
PAGES_SHAPES = PAGES_DIR / "shapes.ttl"
BUILD_POKEAPI = BUILD_DIR / "pokeapi.ttl"
PAGES_POKEAPI = PAGES_DIR / "pokeapi.ttl"
PAGES_SITE_DATA = PAGES_DIR / "site-data.json"
PAGES_SCHEMA_INDEX = PAGES_DIR / "schema-index.json"
SHAPES_SOURCE = repo_path("shapes", "modules", "shapes.ttl")
QUERIES_DIR = repo_path("queries")
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")

MODULE_ORDER = [
    "00-header.ttl",
    "10-core.ttl",
    "20-ruleset-mechanics.ttl",
    "30-save-state.ttl",
    "40-battle.ttl",
    "45-battle-resolution.ttl",
    "50-instantaneous-state.ttl",
    "60-actions-events.ttl",
    "70-provenance.ttl",
    "80-materialized-state.ttl",
]


def _validate_sources() -> None:
    missing = [name for name in MODULE_ORDER if not (MODULES_DIR / name).exists()]
    if missing:
        formatted = ", ".join(missing)
        raise SystemExit(f"missing ontology module(s): {formatted}")
    if not SHAPES_SOURCE.exists():
        raise SystemExit(f"missing shapes source: {SHAPES_SOURCE.relative_to(REPO)}")


def _query_examples() -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    for path in sorted(QUERIES_DIR.glob("*.sparql")):
        query_text = path.read_text(encoding="utf-8").strip()
        first_comment = next(
            (
                line.removeprefix("#").strip()
                for line in query_text.splitlines()
                if line.startswith("#") and line.removeprefix("#").strip()
            ),
            "",
        )
        examples.append(
            {
                "group": "Bundled Queries",
                "label": path.stem.replace("_", " "),
                "source_path": str(path.relative_to(REPO)),
                "summary": first_comment or f"Bundled query from {path.name}.",
                "query": query_text,
                "command": f"python3 -m pokemontology query {path.relative_to(REPO)} build/ontology.ttl <data.ttl>",
            }
        )
    return examples


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in text
        ).split()
        if token
    ]


def _local_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rsplit("/", 1)[-1]


def _pkm_terms_from_text(text: object) -> set[str]:
    if not isinstance(text, str):
        return set()
    return {
        match.group(1)
        for match in re.finditer(r"\bpkm:([A-Za-z_][\w-]*)\b", text)
    }


def _ontology_grounding_items(ontology_text: str) -> list[dict[str, object]]:
    graph = Graph()
    graph.parse(data=ontology_text, format="turtle")
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    kind_priority = (
        (OWL.Class, "class"),
        (OWL.ObjectProperty, "property"),
        (OWL.DatatypeProperty, "property"),
        (OWL.NamedIndividual, "individual"),
    )

    for subject in sorted(
        {
            subject
            for subject in graph.subjects(RDF.type, None)
            if isinstance(subject, URIRef) and str(subject).startswith(str(PKM))
        },
        key=lambda value: str(value),
    ):
        iri = str(subject)
        if iri in seen:
            continue
        label = graph.value(subject, RDFS.label)
        comment = graph.value(subject, RDFS.comment)
        if label is None and comment is None:
            continue
        kind = "term"
        for rdf_type, candidate_kind in kind_priority:
            if (subject, RDF.type, rdf_type) in graph:
                kind = candidate_kind
                break
        items.append(
            {
                "kind": kind,
                "label": str(label) if label is not None else _local_name(iri),
                "iri": iri,
                "summary": str(comment) if comment is not None else f"Pokemontology term {_local_name(iri)}.",
                "snippet": f"Ontology term `{_local_name(iri)}` from the published pkm namespace.",
            }
        )
        seen.add(iri)
    return items


def _schema_pack(
    ontology_text: str, query_examples: list[dict[str, object]]
) -> dict[str, object]:
    prefixes = [
        {
            "alias": "pkm:",
            "iri": "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#",
        },
        {"alias": "rdf:", "iri": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"},
        {"alias": "rdfs:", "iri": "http://www.w3.org/2000/01/rdf-schema#"},
        {"alias": "owl:", "iri": "http://www.w3.org/2002/07/owl#"},
        {"alias": "xsd:", "iri": "http://www.w3.org/2001/XMLSchema#"},
        {"alias": "sh:", "iri": "http://www.w3.org/ns/shacl#"},
    ]
    items = _ontology_grounding_items(ontology_text)
    known_terms = {
        _local_name(str(item["iri"]))
        for item in items
        if isinstance(item.get("iri"), str) and str(item["iri"]).startswith(str(PKM))
    }
    items.extend(
        [
        {
            "kind": "pattern",
            "label": "TypingAssignment pattern",
            "iri": "",
            "summary": "Variant typing is modeled as a contextual fact.",
            "snippet": "TypingAssignment aboutVariant ?variant ; hasContext pkm:Ruleset_PokeAPI_Default ; aboutType ?type .",
        },
        {
            "kind": "pattern",
            "label": "Type effectiveness pattern",
            "iri": "",
            "summary": "Damage multipliers come from TypeEffectivenessAssignment nodes.",
            "snippet": "TypeEffectivenessAssignment attackerType ?moveType ; defenderType ?effectiveType ; hasDamageFactor ?factor .",
        },
        ]
    )
    examples: list[dict[str, object]] = [
        {
            "id": "super-effective-moves",
            "kind": "example",
            "label": "super effective moves",
            "question": "Which of my moves are effective against Charizard?",
            "summary": "Bundled query that links replay combatants, move typing, and type chart effectiveness.",
            "snippet": "Use MoveUseAction, MovePropertyAssignment, TypingAssignment, and TypeEffectivenessAssignment together.",
            "query": query_examples[0]["query"] if query_examples else "",
        },
        {
            "id": "charizard-fire-check",
            "kind": "example",
            "label": "type ask query",
            "question": "Is Charizard a Fire type?",
            "summary": "ASK pattern for a species whose variant has a typing assignment matching Fire.",
            "snippet": "Match Species, then Variant, then TypingAssignment aboutVariant/aboutType.",
            "query": """PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

ASK {
  ?species a pkm:Species ;
           pkm:hasName "Charizard" .
  ?variant a pkm:Variant ;
           pkm:belongsToSpecies ?species .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutVariant ?variant ;
              pkm:aboutType ?type .
  ?type pkm:hasName "Fire" .
}""",
        },
    ]
    items.extend(examples)
    for example in examples:
        known_terms.update(_pkm_terms_from_text(example.get("query", "")))
    for example in query_examples:
        known_terms.update(_pkm_terms_from_text(example.get("query", "")))
    sparse_index: dict[str, list[list[int | float]]] = {}
    item_norms: list[float] = []
    for index, item in enumerate(items):
        counts: dict[str, int] = {}
        for token in _tokenize(f"{item['label']} {item['summary']} {item['snippet']}"):
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            sparse_index.setdefault(token, []).append([index, count])
        item_norms.append(math.sqrt(sum(count * count for count in counts.values())))
    return {
        "prefixes": prefixes,
        "retrieval": {
            "top_k": 4,
            "prompt_match_limit": PROMPT_MATCH_LIMIT,
            "minimum_scores": [
                {
                    "max_tokens": max_tokens,
                    "score": score,
                }
                for max_tokens, score in RETRIEVAL_MINIMUM_SCORES
            ],
        },
        "validation": {
            "allowed_query_types": list(ALLOWED_READ_ONLY_QUERY_TYPES),
            "forbidden_keywords": list(FORBIDDEN_SPARQL_KEYWORDS),
            "known_terms": sorted(known_terms),
        },
        "response": {
            "list_preview_limit": SUMMARY_PREVIEW_LIMIT,
        },
        "inference": {
            "webllm_model": "Llama-3.2-1B-Instruct-q4f32_1-MLC",
            "webllm_library_url": "https://esm.run/@mlc-ai/web-llm",
            "temperature": 0.0,
            "max_tokens": 320,
        },
        "items": items,
        "examples": examples,
        "sparse_index": sparse_index,
        "item_norms": item_norms,
    }


def assemble_artifacts() -> tuple[str, str, dict[str, object]]:
    _validate_sources()
    chunks = []
    for name in MODULE_ORDER:
        path = MODULES_DIR / name
        text = path.read_text(encoding="utf-8").strip()
        chunks.append(text)

    ontology_text = "\n\n".join(chunks) + "\n"
    shapes_text = SHAPES_SOURCE.read_text(encoding="utf-8")
    query_examples = _query_examples()
    site_data = {
        "site": {
            "title": "Pokemontology",
            "tagline": "A public ontology for Pokemon battle mechanics, replay-backed state, and validation.",
            "repository_url": "https://github.com/laurajoyhutchins/pokemontology",
            "pages_base_url": "https://laurajoyhutchins.github.io/pokemontology/",
        },
        "artifacts": [
            {
                "label": "Ontology",
                "path": "ontology.ttl",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#",
                "description": "Published OWL/Turtle bundle assembled from the modular ontology source.",
            },
            {
                "label": "SHACL Shapes",
                "path": "shapes.ttl",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/shapes.ttl#",
                "description": "Validation shapes used for replay slices, save-state data, and ingestion outputs.",
            },
            {
                "label": "PokeAPI Mechanics Data",
                "path": "pokeapi.ttl",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/pokeapi.ttl#",
                "description": "Published ontology-native mechanics dataset transformed from the repository's cached PokeAPI ingest output.",
            },
        ],
        "modules": [
            {
                "name": name.removesuffix(".ttl"),
                "source_path": f"ontology/modules/{name}",
            }
            for name in MODULE_ORDER
        ],
        "pipelines": [
            {
                "name": "Replay ingestion",
                "summary": "Acquire public Showdown replays, curate a competitive corpus, and transform JSON logs into ontology slices.",
                "command": "python3 -m pokemontology replay transform --output-dir build/replays",
            },
            {
                "name": "PokeAPI ingestion",
                "summary": "Cache public API resources and convert the cleanly mappable subset into ontology-native Turtle.",
                "command": "python3 -m pokemontology pokeapi ingest examples/pokeapi/seed-config.json --raw-dir data/pokeapi/raw --output build/pokeapi.ttl",
            },
            {
                "name": "Veekun ingestion",
                "summary": "Transform a local normalized export into version-group-scoped mechanics assignments with explicit provenance.",
                "command": "python3 -m pokemontology veekun transform --source-dir tests/fixtures/veekun_export --output build/veekun.ttl",
            },
        ],
        "examples": [
            {
                "name": "Replay-backed battle slice",
                "path": "examples/slices/showdown-finals-game1-slice.ttl",
                "kind": "Turtle slice",
                "summary": "A worked example of a replay-derived battle graph with events, assignments, and validation coverage.",
            },
            {
                "name": "Seed fixture",
                "path": "examples/fixtures/froakie-caterpie-seed.ttl",
                "kind": "Fixture data",
                "summary": "Compact seed data for ontology tests and examples around owned combatants, moves, and save-state entities.",
            },
            {
                "name": "Replay JSON source",
                "path": "examples/replays/gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json",
                "kind": "Replay JSON",
                "summary": "A cached Showdown replay used as a source document for parsing, summarization, and slice generation.",
            },
            {
                "name": "PokeAPI seed config",
                "path": "examples/pokeapi/seed-config.json",
                "kind": "Ingest config",
                "summary": "A sample seed file for fetching and transforming a narrow, ontology-safe subset of PokeAPI data.",
            },
        ],
        "query_examples": query_examples,
        "schema_pack": {
            "path": "schema-index.json",
            "summary": "Compact grounding pack for Professor Laurel retrieval, local translation, and validator checks.",
        },
    }
    return ontology_text, shapes_text, site_data


def write_artifacts(
    ontology_text: str, shapes_text: str, site_data: dict[str, object]
) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    OUTPUT.write_text(ontology_text, encoding="utf-8")
    BUILD_SHAPES.write_text(shapes_text, encoding="utf-8")
    PAGES_ONTOLOGY.write_text(ontology_text, encoding="utf-8")
    PAGES_SHAPES.write_text(shapes_text, encoding="utf-8")
    if BUILD_POKEAPI.exists():
        shutil.copyfile(BUILD_POKEAPI, PAGES_POKEAPI)
    PAGES_SITE_DATA.write_text(json.dumps(site_data, indent=2) + "\n", encoding="utf-8")
    PAGES_SCHEMA_INDEX.write_text(
        json.dumps(_schema_pack(ontology_text, site_data["query_examples"]), indent=2)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    ontology_text, shapes_text, site_data = assemble_artifacts()
    write_artifacts(ontology_text, shapes_text, site_data)
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"wrote {BUILD_SHAPES.relative_to(REPO)}")
    print(f"wrote {PAGES_ONTOLOGY.relative_to(REPO)}")
    print(f"wrote {PAGES_SHAPES.relative_to(REPO)}")
    if BUILD_POKEAPI.exists():
        print(f"wrote {PAGES_POKEAPI.relative_to(REPO)}")
    print(f"wrote {PAGES_SITE_DATA.relative_to(REPO)}")
    print(f"wrote {PAGES_SCHEMA_INDEX.relative_to(REPO)}")


if __name__ == "__main__":
    main()
