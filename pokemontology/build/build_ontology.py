#!/usr/bin/env python3
"""Assemble the consumer ontology file from modular Turtle source fragments."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from pokemontology._script_loader import repo_path
from pokemontology.chat import (
    ALLOWED_READ_ONLY_QUERY_TYPES,
    FORBIDDEN_SPARQL_KEYWORDS,
    PROMPT_MATCH_LIMIT,
    RETRIEVAL_MINIMUM_SCORES,
)
from pokemontology.laurel import SUMMARY_PREVIEW_LIMIT
from pokemontology.io_utils import display_repo_path, write_json_file

REPO = repo_path()
MODULES_DIR = repo_path("ontology", "modules")
BUILD_DIR = repo_path("build")
OUTPUT = BUILD_DIR / "ontology.ttl"
BUILD_SHAPES = BUILD_DIR / "shapes.ttl"
BUILD_POKEAPI = repo_path("data", "ingested", "pokeapi.ttl")
BUILD_VEEKUN = repo_path("data", "ingested", "veekun-with-learnsets.ttl")
BUILD_SHOWDOWN = repo_path("data", "ingested", "showdown.ttl")
BUILD_MECHANICS = BUILD_DIR / "mechanics.ttl"
BUILD_ENTITY_INDEX = BUILD_DIR / "entity-index.json"

PAGES_DIR = repo_path("docs")
PAGES_ONTOLOGY = PAGES_DIR / "ontology.ttl"
PAGES_SHAPES = PAGES_DIR / "shapes.ttl"
PAGES_POKEAPI = PAGES_DIR / "pokeapi.ttl"
PAGES_MECHANICS = PAGES_DIR / "mechanics.ttl"
PAGES_MECHANICS_BASE = PAGES_DIR / "mechanics-base.ttl"
PAGES_MECHANICS_CURRENT = PAGES_DIR / "mechanics-learnsets-current.ttl"
PAGES_MECHANICS_MODERN = PAGES_DIR / "mechanics-learnsets-modern.ttl"
PAGES_MECHANICS_LEGACY = PAGES_DIR / "mechanics-learnsets-legacy.ttl"
PAGES_SITE_DATA = PAGES_DIR / "site-data.json"
PAGES_SCHEMA_INDEX = PAGES_DIR / "schema-index.json"
PAGES_GRAPH_INDEX = PAGES_DIR / "graph-index.json"
PAGES_SPARQL_REFERENCE = PAGES_DIR / "sparql-reference.md"
BUILD_SPARQL_REFERENCE = BUILD_DIR / "sparql-reference.md"

SHAPES_SOURCE = repo_path("shapes", "modules", "shapes.ttl")
BUNDLED_QUERIES_DIR = repo_path("queries", "bundled")
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")
TTL_PREFIX_HEADER = """@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""
WEB_MECHANICS_SLICES = (
    {
        "key": "base",
        "label": "Mechanics Base",
        "path": "mechanics-base.ttl",
        "description": "Canonical entities, variants, typings, move properties, type chart data, and ruleset-scoped assignments excluding learnset archives.",
    },
    {
        "key": "current",
        "label": "Current Learnsets",
        "path": "mechanics-learnsets-current.ttl",
        "description": "Current-generation learnset coverage from the canonical mechanics graph, including the PokeAPI default ruleset and Scarlet/Violet-era records.",
    },
    {
        "key": "modern",
        "label": "Modern Learnsets",
        "path": "mechanics-learnsets-modern.ttl",
        "description": "Historical learnset archive for 3DS and Switch-era games prior to the current generation.",
    },
    {
        "key": "legacy",
        "label": "Legacy Learnsets",
        "path": "mechanics-learnsets-legacy.ttl",
        "description": "Older learnset archive for pre-3DS generations and side-game rulesets.",
    },
)
CURRENT_RULESET_TOKENS = ("pokeapi_default", "scarlet_violet")
MODERN_RULESET_TOKENS = (
    "x_y",
    "omega_ruby_alpha_sapphire",
    "sun_moon",
    "ultra_sun_ultra_moon",
    "lets_go",
    "sword_shield",
    "brilliant_diamond_shining_pearl",
    "legends_arceus",
)
LOOKUP_TYPE_PRIORITY = {
    "Variant": 0,
    "Species": 1,
    "Move": 2,
    "Ability": 3,
    "Item": 4,
    "Type": 5,
    "Ruleset": 6,
}
ENTITY_INDEX_TARGET_TYPES = frozenset(LOOKUP_TYPE_PRIORITY)
ENTITY_BLOCK_RE = re.compile(
    r"^(pkm:[A-Za-z0-9_]+)\s+a\s+pkm:([A-Za-z0-9_]+)\b", re.MULTILINE
)

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
    "85-meta-snapshot.ttl",
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
    for path in _query_example_paths():
        query_text = path.read_text(encoding="utf-8").strip()
        source_path = _query_source_path(path)
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
                "source_path": source_path,
                "summary": first_comment or f"Bundled query from {path.name}.",
                "query": query_text,
                "command": f"python3 -m pokemontology query {source_path} build/ontology.ttl build/mechanics.ttl <data.ttl>",
            }
        )
    return examples


def _query_example_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "queries/bundled/*.sparql"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return [repo_path(line) for line in sorted(result.stdout.splitlines())]
    return sorted(BUNDLED_QUERIES_DIR.glob("*.sparql"))


def _query_source_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        if path.parent.name == "bundled" and path.parent.parent.name == "queries":
            return f"queries/bundled/{path.name}"
        return path.name


def _preferred_schema_example_query(query_examples: list[dict[str, object]]) -> str:
    preferred_source = "queries/bundled/super_effective_moves.sparql"
    for example in query_examples:
        if example.get("source_path") == preferred_source:
            query = example.get("query", "")
            return query if isinstance(query, str) else ""
    if not query_examples:
        return ""
    query = query_examples[0].get("query", "")
    return query if isinstance(query, str) else ""


def _web_mechanics_slice_paths() -> dict[str, object]:
    return {
        "base": PAGES_MECHANICS_BASE,
        "current": PAGES_MECHANICS_CURRENT,
        "modern": PAGES_MECHANICS_MODERN,
        "legacy": PAGES_MECHANICS_LEGACY,
    }


def _iter_ttl_blocks(path) -> Iterator[str]:
    block_lines: list[str] = []
    with path.open("r", encoding="utf-8") as infile:
        for line in infile:
            if line.startswith("@prefix"):
                continue
            if not line.strip():
                if block_lines:
                    yield "".join(block_lines).rstrip() + "\n\n"
                    block_lines = []
                continue
            block_lines.append(line)
    if block_lines:
        yield "".join(block_lines).rstrip() + "\n\n"


def _classify_mechanics_block(block: str) -> str:
    if " a pkm:MoveLearnRecord" not in block:
        return "base"
    match = re.search(r"pkm:hasContext pkm:Ruleset_([A-Za-z0-9_]+)\s*;", block)
    ruleset_slug = match.group(1).lower() if match else ""
    if any(token in ruleset_slug for token in CURRENT_RULESET_TOKENS):
        return "current"
    if any(token in ruleset_slug for token in MODERN_RULESET_TOKENS):
        return "modern"
    return "legacy"


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


def _literal_texts(graph: Graph, subject: URIRef, predicate: URIRef) -> list[str]:
    return [
        str(obj)
        for obj in graph.objects(subject, predicate)
        if isinstance(obj, Literal)
    ]


def _normalize_lookup_text(text: str) -> str:
    return " ".join(
        "".join(
            character.lower() if character.isalnum() else " "
            for character in text.strip()
        ).split()
    )


def _friendly_local_name(local_name: str) -> str:
    return local_name.replace("_", " ")


def _entity_type_iri(graph: Graph, entity: URIRef) -> URIRef | None:
    candidates = sorted(
        [
            obj
            for obj in graph.objects(entity, RDF.type)
            if isinstance(obj, URIRef)
            and str(obj).startswith(str(PKM))
            and _local_name(str(obj)) in LOOKUP_TYPE_PRIORITY
        ],
        key=lambda value: (
            LOOKUP_TYPE_PRIORITY.get(_local_name(str(value)), 999),
            str(value),
        ),
    )
    return candidates[0] if candidates else None


def _entity_aliases(graph: Graph, entity: URIRef, type_iri: URIRef | None) -> list[str]:
    aliases = {
        _normalize_lookup_text(name)
        for name in _literal_texts(graph, entity, PKM.hasName)
    }
    local_name = _local_name(str(entity))
    aliases.add(_normalize_lookup_text(local_name))
    aliases.add(_normalize_lookup_text(_friendly_local_name(local_name)))
    if type_iri is not None and _local_name(str(type_iri)) == "Variant":
        for name in _literal_texts(graph, entity, PKM.hasName):
            if name.endswith("-Default"):
                aliases.add(_normalize_lookup_text(name.removesuffix("-Default")))
    return sorted(alias for alias in aliases if alias)


def _entity_contexts(graph: Graph, entity: URIRef, type_iri: URIRef | None) -> list[dict[str, str]]:
    contexts: set[URIRef] = set()

    def add_direct_contexts(target: URIRef) -> None:
        for subject, predicate in graph.subject_predicates(target):
            if predicate == PKM.hasContext:
                continue
            for context in graph.objects(subject, PKM.hasContext):
                if isinstance(context, URIRef):
                    contexts.add(context)

    add_direct_contexts(entity)
    if type_iri == PKM.Species:
        for variant in graph.subjects(PKM.belongsToSpecies, entity):
            if isinstance(variant, URIRef):
                add_direct_contexts(variant)
    if type_iri == PKM.Ruleset:
        contexts.add(entity)
    return [
        {
            "iri": str(context),
            "curie": f"pkm:{_local_name(str(context))}",
            "label": _literal_texts(graph, context, PKM.hasName)[0]
            if _literal_texts(graph, context, PKM.hasName)
            else _local_name(str(context)),
        }
        for context in sorted(contexts, key=lambda value: str(value))
    ]


def _build_entity_index() -> dict[str, object]:
    entities_by_curie: dict[str, dict[str, object]] = {}
    variant_species: dict[str, str] = {}
    contexts_by_curie: dict[str, set[str]] = {}

    def literal_values(block: str, predicate: str) -> list[str]:
        values: list[str] = []
        for match in re.finditer(
            rf"pkm:{predicate}\s+\"((?:[^\"\\]|\\.)*)\"",
            block,
        ):
            values.append(bytes(match.group(1), "utf-8").decode("unicode_escape"))
        return values

    def curie_object(block: str, predicate: str) -> str | None:
        match = re.search(rf"pkm:{predicate}\s+(pkm:[A-Za-z0-9_]+)\b", block)
        return match.group(1) if match else None

    for source in (BUILD_POKEAPI, BUILD_VEEKUN):
        if not source.exists():
            continue
        for block in _iter_ttl_blocks(source):
            entity_match = ENTITY_BLOCK_RE.search(block)
            if entity_match is not None:
                subject_curie = entity_match.group(1)
                type_name = entity_match.group(2)
                if type_name in ENTITY_INDEX_TARGET_TYPES:
                    local_name = subject_curie.removeprefix("pkm:")
                    names = literal_values(block, "hasName")
                    identifiers = literal_values(block, "hasIdentifier")
                    entity = entities_by_curie.setdefault(
                        subject_curie,
                        {
                            "iri": str(PKM[local_name]),
                            "curie": subject_curie,
                            "type_iri": str(PKM[type_name]),
                            "type_curie": f"pkm:{type_name}",
                            "labels": [],
                            "identifiers": [],
                        },
                    )
                    entity["labels"] = names
                    entity["identifiers"] = identifiers
                    if type_name == "Variant":
                        species_curie = curie_object(block, "belongsToSpecies")
                        if species_curie is not None:
                            variant_species[subject_curie] = species_curie

            context_curie = curie_object(block, "hasContext")
            if context_curie is None:
                continue
            for predicate in (
                "aboutVariant",
                "aboutMove",
                "aboutAbility",
                "aboutItem",
                "aboutType",
            ):
                target_curie = curie_object(block, predicate)
                if target_curie is None:
                    continue
                contexts_by_curie.setdefault(target_curie, set()).add(context_curie)

    entities: list[dict[str, object]] = []
    rulesets: list[dict[str, str]] = []
    for subject_curie, entity in sorted(entities_by_curie.items()):
        type_curie = str(entity["type_curie"])
        type_name = type_curie.removeprefix("pkm:")
        contexts = set(contexts_by_curie.get(subject_curie, set()))
        if type_name == "Species":
            for variant_curie, species_curie in variant_species.items():
                if species_curie == subject_curie:
                    contexts.update(contexts_by_curie.get(variant_curie, set()))
        if type_name == "Ruleset":
            contexts.add(subject_curie)
        labels = entity.get("labels", [])
        if not isinstance(labels, list):
            labels = []
        identifiers = entity.get("identifiers", [])
        if not isinstance(identifiers, list):
            identifiers = []
        local_name = subject_curie.removeprefix("pkm:")
        aliases = {
            _normalize_lookup_text(label)
            for label in labels
            if isinstance(label, str)
        }
        aliases.add(_normalize_lookup_text(local_name))
        aliases.add(_normalize_lookup_text(_friendly_local_name(local_name)))
        if type_name == "Variant":
            for label in labels:
                if isinstance(label, str) and label.endswith("-Default"):
                    aliases.add(_normalize_lookup_text(label.removesuffix("-Default")))
        context_payloads = []
        for context_curie in sorted(contexts):
            context_entity = entities_by_curie.get(context_curie)
            context_labels = (
                context_entity.get("labels", [])
                if isinstance(context_entity, dict)
                else []
            )
            context_payloads.append(
                {
                    "iri": str(PKM[context_curie.removeprefix("pkm:")]),
                    "curie": context_curie,
                    "label": context_labels[0]
                    if isinstance(context_labels, list) and context_labels
                    else context_curie.removeprefix("pkm:"),
                }
            )
        payload = {
            **entity,
            "aliases": sorted(alias for alias in aliases if alias),
            "contexts": context_payloads,
        }
        entities.append(payload)
        if type_name == "Ruleset":
            rulesets.append(
                {
                    "iri": str(entity["iri"]),
                    "curie": subject_curie,
                    "label": labels[0] if labels else local_name,
                }
            )
    return {
        "source": display_repo_path(BUILD_MECHANICS),
        "entity_count": len(entities),
        "entities": entities,
        "rulesets": sorted(rulesets, key=lambda item: (item["label"], item["curie"])),
    }


def _build_graph_index() -> dict[str, object]:
    nodes_by_curie: dict[str, dict[str, object]] = {}
    edge_map: dict[tuple[str, str, str], dict[str, object]] = {}
    contexts_by_curie: dict[str, set[str]] = {}

    def literal_values(block: str, predicate: str) -> list[str]:
        values: list[str] = []
        for match in re.finditer(
            rf"pkm:{predicate}\s+\"((?:[^\"\\]|\\.)*)\"",
            block,
        ):
            values.append(bytes(match.group(1), "utf-8").decode("unicode_escape"))
        return values

    def curie_object(block: str, predicate: str) -> str | None:
        match = re.search(rf"pkm:{predicate}\s+(pkm:[A-Za-z0-9_]+)\b", block)
        return match.group(1) if match else None

    def node_payload(subject_curie: str, type_name: str) -> dict[str, object]:
        local_name = subject_curie.removeprefix("pkm:")
        return nodes_by_curie.setdefault(
            subject_curie,
            {
                "id": subject_curie,
                "iri": str(PKM[local_name]),
                "label": local_name,
                "type": type_name,
                "type_curie": f"pkm:{type_name}",
                "identifiers": [],
                "contexts": [],
            },
        )

    def ensure_edge(source: str, target: str, kind: str, context: str | None = None) -> None:
        if source == target:
            return
        payload = edge_map.setdefault(
            (source, target, kind),
            {
                "source": source,
                "target": target,
                "kind": kind,
                "weight": 0,
                "contexts": set(),
            },
        )
        payload["weight"] = int(payload["weight"]) + 1
        if context:
            contexts = payload.get("contexts")
            if isinstance(contexts, set):
                contexts.add(context)

    for source in (BUILD_POKEAPI, BUILD_VEEKUN):
        if not source.exists():
            continue
        for block in _iter_ttl_blocks(source):
            entity_match = ENTITY_BLOCK_RE.search(block)
            if entity_match is not None:
                subject_curie = entity_match.group(1)
                type_name = entity_match.group(2)
                if type_name in ENTITY_INDEX_TARGET_TYPES:
                    node = node_payload(subject_curie, type_name)
                    labels = literal_values(block, "hasName")
                    identifiers = literal_values(block, "hasIdentifier")
                    if labels:
                        node["label"] = labels[0]
                    node["identifiers"] = identifiers
                    if type_name == "Variant":
                        species_curie = curie_object(block, "belongsToSpecies")
                        if species_curie:
                            ensure_edge(subject_curie, species_curie, "belongsToSpecies")

            context_curie = curie_object(block, "hasContext")
            if context_curie:
                for predicate in (
                    "aboutVariant",
                    "aboutMove",
                    "aboutAbility",
                    "aboutItem",
                    "aboutType",
                ):
                    target_curie = curie_object(block, predicate)
                    if target_curie:
                        contexts_by_curie.setdefault(target_curie, set()).add(context_curie)
                        ensure_edge(target_curie, context_curie, "availableIn", context_curie)

            variant_curie = curie_object(block, "aboutVariant")
            type_curie = curie_object(block, "aboutType")
            ability_curie = curie_object(block, "aboutAbility")
            move_curie = curie_object(block, "learnableMove")
            about_move_curie = curie_object(block, "aboutMove")
            move_type_curie = curie_object(block, "hasMoveType")
            learnable_flag = re.search(r"pkm:isLearnableInRuleset\s+true\b", block)

            if variant_curie and type_curie:
                ensure_edge(variant_curie, type_curie, "hasType", context_curie)
            if variant_curie and ability_curie:
                ensure_edge(variant_curie, ability_curie, "hasAbility", context_curie)
            if variant_curie and move_curie and learnable_flag:
                ensure_edge(variant_curie, move_curie, "learnsMove", context_curie)
            if about_move_curie and move_type_curie:
                ensure_edge(about_move_curie, move_type_curie, "hasMoveType", context_curie)

    degree_by_node: dict[str, int] = {curie: 0 for curie in nodes_by_curie}
    edges: list[dict[str, object]] = []
    for payload in sorted(
        edge_map.values(),
        key=lambda item: (str(item["kind"]), str(item["source"]), str(item["target"])),
    ):
        source = str(payload["source"])
        target = str(payload["target"])
        if source not in nodes_by_curie or target not in nodes_by_curie:
            continue
        degree_by_node[source] = degree_by_node.get(source, 0) + 1
        degree_by_node[target] = degree_by_node.get(target, 0) + 1
        contexts = payload.get("contexts")
        edges.append(
            {
                "source": source,
                "target": target,
                "kind": str(payload["kind"]),
                "weight": int(payload["weight"]),
                "context_count": len(contexts) if isinstance(contexts, set) else 0,
            }
        )

    nodes = [
        {
            **{
                **node,
                "contexts": sorted(contexts_by_curie.get(subject_curie, set())),
            },
            "degree": degree_by_node.get(subject_curie, 0),
        }
        for subject_curie, node in sorted(
            nodes_by_curie.items(),
            key=lambda item: (
                LOOKUP_TYPE_PRIORITY.get(str(item[1].get("type", "")), 999),
                str(item[1].get("label", "")),
                item[0],
            ),
        )
    ]
    return {
        "source": display_repo_path(BUILD_MECHANICS),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "edge_kinds": [
            "belongsToSpecies",
            "hasType",
            "hasAbility",
            "learnsMove",
            "hasMoveType",
            "availableIn",
        ],
        "nodes": nodes,
        "edges": edges,
    }


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
            "query": _preferred_schema_example_query(query_examples),
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
  ?species pkm:hasName "Charizard" .
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


def _render_sparql_reference(
    schema_pack: dict[str, object], site_data: dict[str, object]
) -> str:
    prefixes = schema_pack.get("prefixes", [])
    items = schema_pack.get("items", [])
    examples = schema_pack.get("examples", [])
    query_examples = site_data.get("query_examples", [])

    pattern_items = [
        item
        for item in items
        if item.get("kind") == "pattern"
        and isinstance(item.get("label"), str)
        and isinstance(item.get("snippet"), str)
    ]
    primary_examples = [
        example
        for example in examples
        if isinstance(example.get("label"), str) and isinstance(example.get("query"), str)
    ]

    lines = [
        "# Pokemontology SPARQL Reference",
        "",
        "Generated from the ontology schema pack and bundled query metadata.",
        "Rebuild with `python3 -m pokemontology build`.",
        "",
        "## Prefixes",
        "",
        "| Prefix | IRI |",
        "| --- | --- |",
    ]
    for prefix in prefixes:
        alias = prefix.get("alias", "")
        iri = prefix.get("iri", "")
        lines.append(f"| `{alias}` | `{iri}` |")

    lines.extend(
        [
            "",
            "## Common Patterns",
            "",
            "These are the recurring graph shapes the codebase expects queries to use.",
            "",
        ]
    )
    for item in pattern_items:
        lines.extend(
            [
                f"### {item['label']}",
                "",
                item.get("summary", ""),
                "",
                "```sparql",
                item["snippet"],
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Canonical Query Examples",
            "",
            "These examples are bundled into the schema pack and frontend query picker.",
            "",
        ]
    )
    for example in primary_examples:
        lines.extend(
            [
                f"### {example['label']}",
                "",
                example.get("summary", ""),
                "",
                "```sparql",
                example["query"].strip(),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Bundled Query Files",
            "",
            "| Query | Summary | Command |",
            "| --- | --- | --- |",
        ]
    )
    for example in query_examples:
        source_path = example.get("source_path", "")
        summary = example.get("summary", "")
        command = example.get("command", "")
        lines.append(f"| `{source_path}` | {summary} | `{command}` |")

    known_terms = schema_pack.get("validation", {}).get("known_terms", [])
    lines.extend(
        [
            "",
            "## Frequently Used Terms",
            "",
            "Selected ontology terms that appear in the bundled patterns and validator grounding:",
            "",
            ", ".join(f"`pkm:{term}`" for term in known_terms[:40]),
            "",
        ]
    )
    return "\n".join(lines)


def _merge_mechanics_data() -> None:
    # Use direct file concatenation for performance on large TTL files (~180MB)
    sources = [BUILD_POKEAPI, BUILD_VEEKUN, BUILD_SHOWDOWN]
    with BUILD_MECHANICS.open("w", encoding="utf-8") as outfile:
        # Write prefix header once
        outfile.write("@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n")
        outfile.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
        outfile.write("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")

        for src in sources:
            if src.exists():
                with src.open("r", encoding="utf-8") as infile:
                    for line in infile:
                        # Skip prefix lines to avoid duplication
                        if not line.startswith("@prefix"):
                            outfile.write(line)
                outfile.write("\n")


def _write_mechanics_web_slices() -> None:
    sources = [s for s in (BUILD_POKEAPI, BUILD_VEEKUN) if s.exists()]
    if not sources:
        return
    slice_paths = _web_mechanics_slice_paths()
    handles = {}
    try:
        for key, path in slice_paths.items():
            handle = path.open("w", encoding="utf-8")
            handle.write(TTL_PREFIX_HEADER)
            handles[key] = handle

        for source in sources:
            for block in _iter_ttl_blocks(source):
                handles[_classify_mechanics_block(block)].write(block)
    finally:
        for handle in handles.values():
            handle.close()


def assemble_artifacts() -> tuple[str, str, dict[str, object]]:
    _validate_sources()
    _merge_mechanics_data()
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
            *[
                {
                    "label": entry["label"],
                    "path": entry["path"],
                    "iri": f"https://laurajoyhutchins.github.io/pokemontology/{entry['path']}#",
                    "description": entry["description"],
                }
                for entry in WEB_MECHANICS_SLICES
            ],
            {
                "label": "Graph Projection Index",
                "path": "graph-index.json",
                "iri": "https://laurajoyhutchins.github.io/pokemontology/graph-index.json",
                "description": "Generated JSON projection of the published entity graph for the interactive website visualizer.",
            },
        ],
        "query_sources": [
            {
                "id": "src-ontology",
                "label": "ontology.ttl",
                "paths": ["ontology.ttl"],
                "checked": True,
                "role": "ontology",
            },
            {
                "id": "src-mechanics",
                "label": "canonical mechanics core",
                "paths": [
                    PAGES_MECHANICS_BASE.name,
                    PAGES_MECHANICS_CURRENT.name,
                ],
                "checked": True,
                "role": "mechanics",
            },
            {
                "id": "src-mechanics-archive",
                "label": "historical learnset archive",
                "paths": [
                    PAGES_MECHANICS_MODERN.name,
                    PAGES_MECHANICS_LEGACY.name,
                ],
                "checked": False,
                "role": "archive",
            },
            {
                "id": "src-pokeapi-demo",
                "label": "pokeapi-demo.ttl (debug)",
                "paths": ["pokeapi-demo.ttl"],
                "checked": False,
                "role": "debug",
            },
            {
                "id": "src-shapes",
                "label": "shapes.ttl",
                "paths": ["shapes.ttl"],
                "checked": False,
                "role": "shapes",
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
                "summary": "Fetch the upstream Veekun CSV snapshot, normalize it, and emit version-group-scoped mechanics assignments with explicit provenance.",
                "command": "python3 -m pokemontology veekun ingest --raw-dir data/veekun/raw --source-dir data/veekun/export --output build/veekun.ttl",
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

    _write_mechanics_web_slices()
    if PAGES_MECHANICS.exists():
        PAGES_MECHANICS.unlink()

    schema_pack = _schema_pack(ontology_text, site_data["query_examples"])
    sparql_reference = _render_sparql_reference(schema_pack, site_data)

    PAGES_SITE_DATA.write_text(json.dumps(site_data, indent=2) + "\n", encoding="utf-8")
    PAGES_SCHEMA_INDEX.write_text(
        json.dumps(schema_pack, indent=2) + "\n",
        encoding="utf-8",
    )
    PAGES_GRAPH_INDEX.write_text(
        json.dumps(_build_graph_index(), indent=2) + "\n",
        encoding="utf-8",
    )
    write_json_file(BUILD_ENTITY_INDEX, _build_entity_index())
    BUILD_SPARQL_REFERENCE.write_text(sparql_reference + "\n", encoding="utf-8")
    PAGES_SPARQL_REFERENCE.write_text(sparql_reference + "\n", encoding="utf-8")


def main() -> None:
    ontology_text, shapes_text, site_data = assemble_artifacts()
    write_artifacts(ontology_text, shapes_text, site_data)
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"wrote {BUILD_SHAPES.relative_to(REPO)}")
    print(f"wrote {PAGES_ONTOLOGY.relative_to(REPO)}")
    print(f"wrote {PAGES_SHAPES.relative_to(REPO)}")
    for path in _web_mechanics_slice_paths().values():
        print(f"wrote {path.relative_to(REPO)}")
    print(f"wrote {PAGES_SITE_DATA.relative_to(REPO)}")
    print(f"wrote {PAGES_SCHEMA_INDEX.relative_to(REPO)}")
    print(f"wrote {PAGES_GRAPH_INDEX.relative_to(REPO)}")
    print(f"wrote {BUILD_ENTITY_INDEX.relative_to(REPO)}")
    print(f"wrote {BUILD_SPARQL_REFERENCE.relative_to(REPO)}")
    print(f"wrote {PAGES_SPARQL_REFERENCE.relative_to(REPO)}")


if __name__ == "__main__":
    main()
