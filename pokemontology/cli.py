"""Unified command-line interface for repository workflows."""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Callable
from pathlib import Path
from typing import Sequence

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ._script_loader import REPO_ROOT
from .chat import (
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    generate_sparql,
    retrieve_matches,
)
from .ingest_common import PKMI, serialize_turtle_to_path
from .io_utils import display_repo_path, format_json_text, read_json_file
from .laurel_eval import DEFAULT_SUITE, EvalConfig, describe_suite, evaluate_suite, load_suite
from .laurel import summarize_results
from .turn_order import resolve_action_order

from pokemontology.build import build_ontology, check_ttl_parse
from pokemontology.ingest import meta_ingest, pokeapi_ingest, veekun_ingest
from pokemontology.replay import (
    parse_showdown_replay,
    replay_dataset,
    replay_to_ttl_builder,
    summarize_showdown_replay,
)


class CliUsageError(ValueError):
    """Raised when CLI input is syntactically valid but unusable."""


DEFAULT_SCHEMA_INDEX = REPO_ROOT / "docs" / "schema-index.json"
DEFAULT_DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_ONTOLOGY_SOURCE = REPO_ROOT / "build" / "ontology.ttl"
DEFAULT_DOCS_ONTOLOGY_SOURCE = REPO_ROOT / "docs" / "ontology.ttl"
DEFAULT_LOOKUP_SOURCE = REPO_ROOT / "build" / "mechanics.ttl"
DEFAULT_ENTITY_INDEX = REPO_ROOT / "build" / "entity-index.json"
DEFAULT_QUERY_SOURCES = (
    DEFAULT_ONTOLOGY_SOURCE,
    DEFAULT_LOOKUP_SOURCE,
)


_TURTLE_SOURCE_CACHE: dict[tuple[tuple[str, int, int], ...], Graph] = {}
_JSON_OBJECT_CACHE: dict[tuple[str, int, int], dict[str, object]] = {}
_RAG_MATCH_CACHE: dict[tuple[str, str, int, int], list[dict[str, object]]] = {}
_ENTITY_INDEX_CACHE: dict[tuple[str, int, int], dict[str, object]] = {}

PKM_NAMESPACE = "https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#"
PKMI_NAMESPACE = "https://laurajoyhutchins.github.io/pokemontology/id/"
CURIE_PREFIXES = (
    ("pkm:", PKM_NAMESPACE),
    ("pkmi:", PKMI_NAMESPACE),
    ("rdf:", str(RDF)),
    ("rdfs:", str(RDFS)),
    ("owl:", str(OWL)),
)
PKM_HAS_CONTEXT = URIRef(f"{PKM_NAMESPACE}hasContext")
PKM_HAS_NAME = URIRef(f"{PKM_NAMESPACE}hasName")
PKM_HAS_IDENTIFIER = URIRef(f"{PKM_NAMESPACE}hasIdentifier")
PKM_BELONGS_TO_SPECIES = URIRef(f"{PKM_NAMESPACE}belongsToSpecies")
PKM_RULESET = URIRef(f"{PKM_NAMESPACE}Ruleset")
PKM_SPECIES = URIRef(f"{PKM_NAMESPACE}Species")

LOOKUP_TYPE_PRIORITY = {
    "Variant": 0,
    "Species": 1,
    "Move": 2,
    "Ability": 3,
    "Item": 4,
    "Type": 5,
    "Ruleset": 6,
}


def _repo_relative(path: Path) -> str:
    return display_repo_path(path)


def _load_json(path: Path) -> object:
    try:
        return read_json_file(path)
    except OSError as exc:
        raise CliUsageError(
            f"failed to read JSON file {_repo_relative(path)}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CliUsageError(
            f"invalid JSON in {_repo_relative(path)} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    cache_key = (
        str(path.resolve()),
        path.stat().st_mtime_ns,
        path.stat().st_size,
    )
    cached = _JSON_OBJECT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise CliUsageError(f"{label} must contain a top-level JSON object")
    _JSON_OBJECT_CACHE[cache_key] = payload
    return payload


def _read_text(path: Path, *, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliUsageError(
            f"failed to read {label} {_repo_relative(path)}: {exc}"
        ) from exc


def _load_turtle_sources(paths: Sequence[Path]) -> Graph:
    cache_key = tuple(
        (
            str(path.resolve()),
            path.stat().st_mtime_ns,
            path.stat().st_size,
        )
        for path in paths
    )
    cached = _TURTLE_SOURCE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    graph = Graph()
    for path in paths:
        try:
            graph.parse(path, format="turtle")
        except Exception as exc:
            raise CliUsageError(
                f"failed to parse Turtle source {_repo_relative(path)}: {exc}"
            ) from exc
    _TURTLE_SOURCE_CACHE[cache_key] = graph
    return graph


def _resolve_existing_path(
    primary: Path,
    fallback: Path | None = None,
    *,
    label: str,
) -> Path:
    if primary.exists():
        return primary
    if fallback is not None and fallback.exists():
        return fallback
    if fallback is None:
        raise CliUsageError(f"missing {label} {_repo_relative(primary)}")
    raise CliUsageError(
        f"missing {label} {_repo_relative(primary)} and fallback {_repo_relative(fallback)}"
    )


def _curie_for_iri(iri: URIRef | str) -> str:
    iri_text = str(iri)
    for prefix, namespace in CURIE_PREFIXES:
        if iri_text.startswith(namespace):
            return f"{prefix}{iri_text.removeprefix(namespace)}"
    return iri_text


def _normalize_pkm_term(value: str) -> URIRef:
    term = value.strip()
    if not term:
        raise CliUsageError("term must not be empty")
    if term.startswith("pkm:"):
        local_name = term.removeprefix("pkm:")
        if not local_name:
            raise CliUsageError("pkm term must include a local name")
        return URIRef(f"{PKM_NAMESPACE}{local_name}")
    if term.startswith(PKM_NAMESPACE) or term.startswith(PKMI_NAMESPACE):
        return URIRef(term)
    if "://" in term:
        raise CliUsageError(
            "term must be a pkm:* CURIE, a full pokemontology IRI, or a bare local term name"
        )
    return URIRef(f"{PKM_NAMESPACE}{term}")


def _load_ontology_graph(path: Path) -> Graph:
    return _load_turtle_sources((path,))


def _sorted_pkm_terms(graph: Graph, rdf_types: tuple[URIRef, ...]) -> list[URIRef]:
    return sorted(
        {
            subject
            for rdf_type in rdf_types
            for subject in graph.subjects(RDF.type, rdf_type)
            if isinstance(subject, URIRef) and str(subject).startswith(PKM_NAMESPACE)
        },
        key=lambda value: str(value),
    )


def _term_kind(graph: Graph, term: URIRef) -> str:
    if (term, RDF.type, OWL.Class) in graph:
        return "class"
    if (
        (term, RDF.type, OWL.ObjectProperty) in graph
        or (term, RDF.type, OWL.DatatypeProperty) in graph
        or (term, RDF.type, RDF.Property) in graph
    ):
        return "property"
    if (term, RDF.type, OWL.NamedIndividual) in graph:
        return "individual"
    return "term"


def _format_usage_triple(subject: URIRef, predicate: URIRef, obj: URIRef) -> str:
    return f"{_curie_for_iri(subject)} {_curie_for_iri(predicate)} {_curie_for_iri(obj)} ."


def _describe_usage_examples(graph: Graph, term: URIRef, *, limit: int = 5) -> list[str]:
    examples: list[str] = []
    seen: set[str] = set()

    def add_incoming(predicate_order: tuple[URIRef, ...] | None = None) -> bool:
        matches = sorted(
            [
                (subject, predicate)
                for subject, predicate in graph.subject_predicates(term)
                if isinstance(subject, URIRef)
                and (
                    predicate_order is None
                    or predicate in predicate_order
                )
            ],
            key=lambda value: (
                predicate_order.index(value[1]) if predicate_order else 0,
                str(value[0]),
                str(value[1]),
            ),
        )
        for subject, predicate in matches:
            rendered = _format_usage_triple(subject, predicate, term)
            if rendered not in seen:
                seen.add(rendered)
                examples.append(rendered)
            if len(examples) >= limit:
                return True
        return False

    if add_incoming((RDFS.subClassOf, RDFS.domain, RDFS.range, RDFS.subPropertyOf)):
        return examples

    for predicate, obj in graph.predicate_objects(term):
        if predicate in {RDFS.label, RDFS.comment}:
            continue
        if isinstance(obj, URIRef):
            rendered = _format_usage_triple(term, predicate, obj)
            if rendered not in seen:
                seen.add(rendered)
                examples.append(rendered)
        if len(examples) >= limit:
            return examples

    add_incoming()
    return examples


def _query_results_to_json(result) -> dict[str, object]:
    variables = [str(variable) for variable in result.vars]
    rows: list[dict[str, str | None]] = []
    for row in result:
        row_json: dict[str, str | None] = {}
        for variable in variables:
            value = row.get(variable)
            row_json[variable] = None if value is None else str(value)
        rows.append(row_json)
    return {"variables": variables, "rows": rows}


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


def _local_name(iri: str) -> str:
    if iri.startswith(PKM_NAMESPACE):
        return iri.removeprefix(PKM_NAMESPACE)
    if iri.startswith(PKMI_NAMESPACE):
        return iri.removeprefix(PKMI_NAMESPACE)
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rsplit("/", 1)[-1]


def _friendly_local_name(local_name: str) -> str:
    if "/" in local_name:
        local_name = local_name.rsplit("/", 1)[-1]
    return local_name.replace("_", " ").replace("-", " ")


def _entity_type_iri(graph: Graph, entity: URIRef) -> URIRef | None:
    candidates = sorted(
        [
            obj
            for obj in graph.objects(entity, RDF.type)
            if isinstance(obj, URIRef)
            and str(obj).startswith(PKM_NAMESPACE)
            and _local_name(str(obj)) in LOOKUP_TYPE_PRIORITY
        ],
        key=lambda value: (
            LOOKUP_TYPE_PRIORITY.get(_local_name(str(value)), 999),
            str(value),
        ),
    )
    return candidates[0] if candidates else None


def _is_instance_entity(graph: Graph, entity: URIRef) -> bool:
    if str(entity).startswith(PKMI_NAMESPACE):
        return True
    if str(entity).startswith(PKM_NAMESPACE):
        type_iri = _entity_type_iri(graph, entity)
        return type_iri is not None
    return False


def _entity_aliases(graph: Graph, entity: URIRef, type_iri: URIRef | None) -> set[str]:
    aliases = {_normalize_lookup_text(name) for name in _literal_texts(graph, entity, PKM_HAS_NAME)}
    local_name = _local_name(str(entity))
    aliases.add(_normalize_lookup_text(local_name))
    aliases.add(_normalize_lookup_text(_friendly_local_name(local_name)))
    if type_iri is not None and _local_name(str(type_iri)) == "Variant":
        for name in _literal_texts(graph, entity, PKM_HAS_NAME):
            if name.endswith("-Default"):
                aliases.add(_normalize_lookup_text(name.removesuffix("-Default")))
    return {alias for alias in aliases if alias}


def _entity_context_payloads(graph: Graph, entity: URIRef, type_iri: URIRef | None) -> list[dict[str, str]]:
    return [
        {
            "iri": str(context),
            "curie": _curie_for_iri(context),
            "label": _literal_texts(graph, context, PKM_HAS_NAME)[0]
            if _literal_texts(graph, context, PKM_HAS_NAME)
            else _local_name(str(context)),
        }
        for context in _entity_contexts(graph, entity, type_iri)
    ]


def _build_entity_index_from_ttl(path: Path) -> dict[str, object]:
    cache_key = (str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size)
    cached = _ENTITY_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    graph = _load_turtle_sources((path,))
    entities: list[dict[str, object]] = []
    rulesets: list[dict[str, str]] = []
    for entity in sorted(
        {
            subject
            for subject in graph.subjects(RDF.type, None)
            if isinstance(subject, URIRef) and _is_instance_entity(graph, subject)
        },
        key=lambda value: str(value),
    ):
        type_iri = _entity_type_iri(graph, entity)
        if type_iri is None:
            continue
        labels = _literal_texts(graph, entity, PKM_HAS_NAME)
        identifiers = _literal_texts(graph, entity, PKM_HAS_IDENTIFIER)
        entities.append(
            {
                "iri": str(entity),
                "curie": _curie_for_iri(entity),
                "type_iri": str(type_iri),
                "type_curie": _curie_for_iri(type_iri),
                "type_name": _local_name(str(type_iri)),
                "labels": labels,
                "identifiers": identifiers,
                "aliases": sorted(_entity_aliases(graph, entity, type_iri)),
                "contexts": _entity_context_payloads(graph, entity, type_iri),
            }
        )
        if type_iri == PKM_RULESET:
            rulesets.append(
                {
                    "iri": str(entity),
                    "curie": _curie_for_iri(entity),
                    "label": labels[0] if labels else _local_name(str(entity)),
                }
            )
    payload = {
        "source": _repo_relative(path),
        "entity_count": len(entities),
        "entities": entities,
        "rulesets": sorted(rulesets, key=lambda item: (item["label"], item["curie"])),
    }
    _ENTITY_INDEX_CACHE[cache_key] = payload
    return payload


def _load_entity_index(index_path: Path) -> dict[str, object]:
    payload = _load_json_object(index_path, label="entity index")
    entities = payload.get("entities")
    rulesets = payload.get("rulesets")
    if not isinstance(entities, list) or not isinstance(rulesets, list):
        raise CliUsageError("entity index must contain 'entities' and 'rulesets' lists")
    return payload


def _resolved_lookup_payload(data_path: Path, index_path: Path) -> dict[str, object]:
    use_default_index = index_path == DEFAULT_ENTITY_INDEX
    if use_default_index and data_path != DEFAULT_LOOKUP_SOURCE:
        return _build_entity_index_from_ttl(data_path)
    if index_path.exists():
        return _load_entity_index(index_path)
    return _build_entity_index_from_ttl(data_path)


def _lookup_score(query: str, item: dict[str, object]) -> int:
    normalized_query = _normalize_lookup_text(query)
    if not normalized_query:
        return 0
    aliases_raw = item.get("aliases", set())
    if isinstance(aliases_raw, set):
        aliases = aliases_raw
    elif isinstance(aliases_raw, list):
        aliases = {alias for alias in aliases_raw if isinstance(alias, str)}
    else:
        return 0
    score = 0
    if normalized_query in aliases:
        score = max(score, 400)
    for alias in aliases:
        if alias.startswith(normalized_query):
            score = max(score, 250)
        elif normalized_query in alias:
            score = max(score, 180)
        query_tokens = set(normalized_query.split())
        alias_tokens = set(alias.split())
        overlap = len(query_tokens & alias_tokens)
        if overlap:
            score = max(score, overlap * 40)
    iri = _curie_for_iri(item["iri"])
    if normalized_query == _normalize_lookup_text(iri):
        score = max(score, 420)
    return score


def _entity_contexts(graph: Graph, entity: URIRef, type_iri: URIRef | None) -> list[URIRef]:
    contexts: set[URIRef] = set()

    def add_direct_contexts(target: URIRef) -> None:
        for subject, predicate in graph.subject_predicates(target):
            if predicate == PKM_HAS_CONTEXT:
                continue
            for context in graph.objects(subject, PKM_HAS_CONTEXT):
                if isinstance(context, URIRef):
                    contexts.add(context)

    add_direct_contexts(entity)
    if type_iri == PKM_SPECIES:
        for variant in graph.subjects(PKM_BELONGS_TO_SPECIES, entity):
            if isinstance(variant, URIRef):
                add_direct_contexts(variant)
    if type_iri == PKM_RULESET:
        contexts.add(entity)
    return sorted(contexts, key=lambda value: str(value))


def cmd_rulesets(args: argparse.Namespace) -> int:
    data_path = _resolve_existing_path(args.data, label="ruleset data source")
    payload = _resolved_lookup_payload(data_path, args.index)
    rulesets = payload.get("rulesets", [])
    if not isinstance(rulesets, list):
        raise CliUsageError("entity index rulesets payload must be a list")
    for ruleset in rulesets:
        if not isinstance(ruleset, dict):
            continue
        curie = ruleset.get("curie")
        label = ruleset.get("label")
        if isinstance(curie, str) and isinstance(label, str):
            print(f"{curie}\t{label}")
        elif isinstance(curie, str):
            print(curie)
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    data_path = _resolve_existing_path(args.data, label="lookup data source")
    payload = _resolved_lookup_payload(data_path, args.index)
    entities = payload.get("entities", [])
    if not isinstance(entities, list):
        raise CliUsageError("entity index entities payload must be a list")
    matches = [item for item in entities if _lookup_score(args.query, item) > 0]
    matches.sort(
        key=lambda item: (
            -_lookup_score(args.query, item),
            LOOKUP_TYPE_PRIORITY.get(str(item["type_name"]), 999),
            str(item["curie"]),
        )
    )
    if not matches:
        print(f'No entity matches found for "{args.query}".')
        return 1
    best = matches[0]
    print(f"Query: {args.query}")
    print(f"Canonical IRI: {best['curie']}")
    print(f"Entity Type: {best['type_curie']}")
    labels = best.get("labels", [])
    if isinstance(labels, list) and labels:
        print(f"Label: {labels[0]}")
    identifiers = best.get("identifiers", [])
    if isinstance(identifiers, list) and identifiers:
        print(f"Identifier: {identifiers[0]}")
    contexts = best.get("contexts", [])
    print("Contexts:")
    if isinstance(contexts, list) and contexts:
        for context in contexts:
            if not isinstance(context, dict):
                continue
            curie = context.get("curie")
            label = context.get("label")
            if isinstance(curie, str) and isinstance(label, str):
                print(f"- {curie} ({label})")
            elif isinstance(curie, str):
                print(f"- {curie}")
    else:
        print("- none")
    if len(matches) > 1:
        print("Other matches:")
        for item in matches[1 : 1 + args.limit]:
            labels = item.get("labels", [])
            suffix = f" ({labels[0]})" if isinstance(labels, list) and labels else ""
            print(f"- {item['curie']} [{item['type_curie']}]{suffix}")
    return 0


def _print_json(payload: object, *, pretty: bool = False) -> None:
    print(format_json_text(payload, pretty=pretty))


def _return_zero(
    callback: Callable[[argparse.Namespace], object],
) -> Callable[[argparse.Namespace], int]:
    def runner(args: argparse.Namespace) -> int:
        callback(args)
        return 0

    return runner


def cmd_build(_args: argparse.Namespace) -> int:
    build_ontology.main()
    return 0


def cmd_check_ttl(args: argparse.Namespace) -> int:
    failures = 0
    for path in args.paths:
        ok, message = check_ttl_parse.check_file(path)
        print(message)
        if not ok:
            failures += 1
    return 1 if failures else 0


def cmd_parse_replay(args: argparse.Namespace) -> int:
    replay = _load_json_object(args.replay_json, label="replay JSON")
    log = replay.get("log")
    if not isinstance(log, str):
        raise CliUsageError("replay JSON must contain a string 'log' field")
    turns = parse_showdown_replay.parse_log(replay["log"])
    output = {
        "id": replay.get("id"),
        "format": replay.get("format"),
        "players": replay.get("players", []),
        "turns": turns,
    }
    _print_json(output, pretty=args.pretty)
    return 0


def cmd_summarize_replay(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.replay_json, label="replay JSON")
    _print_json(summarize_showdown_replay.summarize(payload), pretty=True)
    return 0


def cmd_build_slice(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.replay_json, label="replay JSON")
    output_path = args.output or args.replay_json.with_name(
        f"{args.replay_json.stem}-slice.ttl"
    )
    serialize_turtle_to_path(replay_to_ttl_builder.build_graph(payload), output_path)
    print(output_path)
    return 0


def cmd_resolve_order(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.state_json, label="turn-order state JSON")
    resolved = resolve_action_order(payload)
    _print_json(resolved, pretty=args.pretty)
    return 0


def cmd_meta_snapshot(args: argparse.Namespace) -> int:
    meta_ingest.cmd_meta_snapshot(args)
    return 0


def cmd_serve_docs(args: argparse.Namespace) -> int:
    handler = partial(SimpleHTTPRequestHandler, directory=str(args.docs_dir))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        bound_host, bound_port = server.server_address
        print(
            f"Serving {_repo_relative(args.docs_dir)} at http://{bound_host}:{bound_port}/"
        )
        server.serve_forever()
    return 0


def _run_query_text(
    query_text: str,
    *,
    sources: Sequence[Path],
    query_label: str,
) -> dict[str, object]:
    graph = _load_turtle_sources(sources)
    try:
        result = graph.query(query_text)
    except Exception as exc:
        raise CliUsageError(
            f"failed to execute SPARQL query {query_label}: {exc}"
        ) from exc
    if getattr(result, "type", None) == "ASK":
        return {"boolean": bool(result.askAnswer)}
    if getattr(result, "type", None) in {"CONSTRUCT", "DESCRIBE"}:
        rows = []
        for subject, predicate, obj in result.graph:
            rows.append(
                {
                    "subject": str(subject),
                    "predicate": str(predicate),
                    "object": str(obj),
                }
            )
        return {
            "answer": f"Laurel produced a graph result with {len(rows)} triples.",
            "variables": ["subject", "predicate", "object"],
            "rows": rows,
        }
    return _query_results_to_json(result)


def _resolved_query_sources(sources: Sequence[Path]) -> tuple[Path, ...]:
    if sources:
        return tuple(sources)
    return DEFAULT_QUERY_SOURCES


def _execute_query_text(
    query_text: str,
    *,
    sources: Sequence[Path],
    pretty: bool = False,
    query_label: str,
) -> int:
    _print_json(
        _run_query_text(query_text, sources=sources, query_label=query_label),
        pretty=pretty,
    )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    query_text = _read_text(args.query, label="query file")
    return _execute_query_text(
        query_text,
        sources=_resolved_query_sources(args.sources),
        pretty=args.pretty,
        query_label=_repo_relative(args.query),
    )


def _get_rag_matches(args: argparse.Namespace) -> list[dict[str, object]] | None:
    try:
        schema_index_path = _resolve_existing_path(
            args.schema_index,
            label="schema index",
        )
        cache_key = (
            str(schema_index_path.resolve()),
            args.question.strip(),
            schema_index_path.stat().st_mtime_ns,
            schema_index_path.stat().st_size,
        )
        cached = _RAG_MATCH_CACHE.get(cache_key)
        if cached is not None:
            return cached
        schema_pack = _load_json_object(schema_index_path, label="schema index")
        matches = retrieve_matches(args.question, schema_pack)
        _RAG_MATCH_CACHE[cache_key] = matches
        return matches
    except Exception:
        return None


def _resolve_ontology_arg(args: argparse.Namespace) -> Path:
    if args.ontology is not None:
        return args.ontology
    return _resolve_existing_path(
        DEFAULT_ONTOLOGY_SOURCE,
        DEFAULT_DOCS_ONTOLOGY_SOURCE,
        label="ontology source",
    )


def cmd_list_classes(args: argparse.Namespace) -> int:
    graph = _load_ontology_graph(_resolve_ontology_arg(args))
    for term in _sorted_pkm_terms(graph, (OWL.Class,)):
        print(_curie_for_iri(term))
    return 0


def cmd_list_properties(args: argparse.Namespace) -> int:
    graph = _load_ontology_graph(_resolve_ontology_arg(args))
    for term in _sorted_pkm_terms(
        graph, (OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)
    ):
        print(_curie_for_iri(term))
    return 0


def cmd_describe_term(args: argparse.Namespace) -> int:
    ontology = _resolve_ontology_arg(args)
    graph = _load_ontology_graph(ontology)
    term = _normalize_pkm_term(args.term)
    if (term, None, None) not in graph and (None, None, term) not in graph:
        raise CliUsageError(
            f"term {_curie_for_iri(term)} was not found in {_repo_relative(ontology)}"
        )
    print(_curie_for_iri(term))
    print(f"Kind: {_term_kind(graph, term)}")
    label = graph.value(term, RDFS.label)
    if label is not None:
        print(f"Label: {label}")
    comment = graph.value(term, RDFS.comment)
    if comment is not None:
        print(f"Comment: {comment}")
    examples = _describe_usage_examples(graph, term)
    if examples:
        print("Usage examples:")
        for example in examples:
            print(f"- {example}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        query_text = generate_sparql(
            args.question,
            matches=_get_rag_matches(args),
            model=args.model,
            endpoint=args.endpoint,
            timeout=args.timeout,
        )
    except Exception as exc:
        raise CliUsageError(f"failed to generate SPARQL from question: {exc}") from exc
    print(query_text)
    return 0


def cmd_laurel(args: argparse.Namespace) -> int:
    try:
        query_text = generate_sparql(
            args.question,
            matches=_get_rag_matches(args),
            model=args.model,
            endpoint=args.endpoint,
            timeout=args.timeout,
        )
    except Exception as exc:
        raise CliUsageError(f"failed to generate SPARQL from question: {exc}") from exc
    if args.print_sparql:
        print(query_text)
    payload = _run_query_text(
        query_text,
        sources=_resolved_query_sources(args.sources),
        query_label="<generated>",
    )
    if args.json:
        _print_json(
            {
                "question": args.question,
                "sparql": query_text,
                "result": payload,
                "answer": summarize_results(args.question, payload),
            },
            pretty=True,
        )
        return 0
    print(summarize_results(args.question, payload))
    return 0


def cmd_evaluate_laurel(args: argparse.Namespace) -> int:
    try:
        suite = load_suite(args.suite)
        if args.list_tiers or args.validate_suite:
            payload = {
                "suite": str(args.suite),
                "suite_overview": describe_suite(suite),
                "valid": True,
            }
            _print_json(payload, pretty=True)
            return 0
        payload = evaluate_suite(
            EvalConfig(
                suite=args.suite,
                mode=args.mode,
                tier=args.tier,
                include_adversarial=args.include_adversarial,
                sources=tuple(args.sources),
                schema_index=args.schema_index,
                model=args.model,
                endpoint=args.endpoint,
                timeout=args.timeout,
                limit=args.limit,
                save_report=args.save_report,
                execution_timeout=args.execution_timeout,
            )
        )
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc
    _print_json(payload, pretty=True)
    return 0


def add_replay_dataset_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    replay_parser = subparsers.add_parser(
        "replay", help="Acquire, curate, and transform replay datasets."
    )
    replay_subparsers = replay_parser.add_subparsers(
        dest="replay_command", required=True
    )

    fetch_index_parser = replay_subparsers.add_parser(
        "fetch-index", help="Fetch and cache replay search pages."
    )
    fetch_index_parser.add_argument(
        "--format", dest="formatid", required=True, help="Showdown format identifier."
    )
    fetch_index_parser.add_argument(
        "--index-dir",
        type=Path,
        default=replay_dataset.DEFAULT_INDEX_DIR,
        help="Directory for cached replay search pages.",
    )
    fetch_index_parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum number of search pages to fetch.",
    )
    fetch_index_parser.add_argument(
        "--user", default=None, help="Optional Showdown username filter."
    )
    fetch_index_parser.add_argument(
        "--delay-seconds",
        type=float,
        default=replay_dataset.DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_index_parser.add_argument(
        "--timeout",
        type=float,
        default=replay_dataset.DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_index_parser.add_argument(
        "--force", action="store_true", help="Refetch index pages even if cached."
    )
    fetch_index_parser.set_defaults(func=_return_zero(replay_dataset.cmd_fetch_index))

    curate_parser = replay_subparsers.add_parser(
        "curate", help="Curate replay IDs from cached search pages."
    )
    curate_parser.add_argument(
        "--index-dir",
        type=Path,
        default=replay_dataset.DEFAULT_INDEX_DIR,
        help="Directory containing cached replay search pages.",
    )
    curate_parser.add_argument(
        "--output",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    curate_parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        default=None,
        help="Required format identifier. Repeatable.",
    )
    curate_parser.add_argument(
        "--min-rating",
        type=int,
        default=None,
        help="Minimum rating required for inclusion.",
    )
    curate_parser.add_argument(
        "--min-uploadtime",
        type=int,
        default=None,
        help="Minimum upload timestamp for inclusion.",
    )
    curate_parser.add_argument(
        "--allow-non-heads-up",
        action="store_true",
        help="Allow index entries without exactly two players.",
    )
    curate_parser.set_defaults(func=_return_zero(replay_dataset.cmd_curate))

    fetch_parser = replay_subparsers.add_parser(
        "fetch", help="Fetch cached replay JSON payloads for curated replay IDs."
    )
    fetch_parser.add_argument(
        "--curated",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=replay_dataset.DEFAULT_RAW_DIR,
        help="Directory for cached replay JSON.",
    )
    fetch_parser.add_argument(
        "--delay-seconds",
        type=float,
        default=replay_dataset.DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_parser.add_argument(
        "--timeout",
        type=float,
        default=replay_dataset.DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="Refetch replay JSON even if cached."
    )
    fetch_parser.set_defaults(func=_return_zero(replay_dataset.cmd_fetch))

    transform_parser = replay_subparsers.add_parser(
        "transform", help="Build one replay slice TTL per curated cached replay."
    )
    transform_parser.add_argument(
        "--curated",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=replay_dataset.DEFAULT_RAW_DIR,
        help="Directory containing cached replay JSON.",
    )
    transform_parser.add_argument(
        "--output-dir",
        type=Path,
        default=replay_dataset.DEFAULT_OUTPUT_DIR,
        help="Directory where replay slice TTL files will be written.",
    )
    transform_parser.add_argument(
        "--bundle-output",
        type=Path,
        default=replay_dataset.DEFAULT_BUNDLE_PATH,
        help="Canonical combined replay Turtle bundle to write.",
    )
    transform_parser.set_defaults(func=_return_zero(replay_dataset.cmd_transform))


def add_pokeapi_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    pokeapi_parser = subparsers.add_parser(
        "pokeapi", help="Fetch and transform PokeAPI resources."
    )
    pokeapi_subparsers = pokeapi_parser.add_subparsers(
        dest="pokeapi_command", required=True
    )

    fetch_parser = pokeapi_subparsers.add_parser(
        "fetch", help="Fetch and cache selected PokeAPI payloads."
    )
    fetch_parser.add_argument(
        "seed",
        type=Path,
        help="Path to seed JSON describing which resources to ingest.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    fetch_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    fetch_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_fetch))

    transform_parser = pokeapi_subparsers.add_parser(
        "transform", help="Transform cached raw JSON into Turtle."
    )
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory containing cached raw JSON.",
    )
    transform_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=pokeapi_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    transform_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_transform))

    ingest_parser = pokeapi_subparsers.add_parser(
        "ingest", help="Fetch cached JSON and build a Turtle dataset."
    )
    ingest_parser.add_argument(
        "seed",
        type=Path,
        help="Path to seed JSON describing which resources to ingest.",
    )
    ingest_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    ingest_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=pokeapi_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    ingest_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    ingest_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_ingest))


def add_veekun_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    veekun_parser = subparsers.add_parser(
        "veekun", help="Fetch, normalize, and transform Veekun data into Turtle."
    )
    veekun_subparsers = veekun_parser.add_subparsers(
        dest="veekun_command", required=True
    )

    fetch_parser = veekun_subparsers.add_parser(
        "fetch", help="Fetch the upstream Veekun CSV snapshot."
    )
    fetch_parser.add_argument(
        "--archive-url",
        default=veekun_ingest.DEFAULT_ARCHIVE_URL,
        help="Tar.gz archive URL for veekun/pokedex.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_RAW_DIR,
        help="Directory to store required upstream Veekun CSV files.",
    )
    fetch_parser.add_argument(
        "--timeout", type=float, default=60.0, help="HTTP timeout in seconds."
    )
    fetch_parser.set_defaults(func=_return_zero(veekun_ingest.cmd_fetch))

    normalize_parser = veekun_subparsers.add_parser(
        "normalize",
        help="Normalize upstream Veekun CSVs into the repository's transform format.",
    )
    normalize_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_RAW_DIR,
        help="Directory containing upstream Veekun CSV files.",
    )
    normalize_parser.add_argument(
        "--source-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_SOURCE_DIR,
        help="Directory for normalized Veekun CSV export files.",
    )
    normalize_parser.add_argument(
        "--include-learnsets",
        action="store_true",
        help="Emit normalized move learn records. This can produce a very large dataset.",
    )
    normalize_parser.add_argument(
        "--version-group",
        action="append",
        default=[],
        help="Limit normalization to one or more Veekun version-group identifiers.",
    )
    normalize_parser.set_defaults(func=_return_zero(veekun_ingest.cmd_normalize))

    transform_parser = veekun_subparsers.add_parser(
        "transform", help="Transform local Veekun CSV export into Turtle."
    )
    transform_parser.add_argument(
        "--source-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_SOURCE_DIR,
        help="Directory containing normalized Veekun CSV export files.",
    )
    transform_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=veekun_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    transform_parser.set_defaults(func=_return_zero(veekun_ingest.cmd_transform))

    ingest_parser = veekun_subparsers.add_parser(
        "ingest", help="Fetch, normalize, and transform Veekun data into Turtle."
    )
    ingest_parser.add_argument(
        "--archive-url",
        default=veekun_ingest.DEFAULT_ARCHIVE_URL,
        help="Tar.gz archive URL for veekun/pokedex.",
    )
    ingest_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_RAW_DIR,
        help="Directory to store required upstream Veekun CSV files.",
    )
    ingest_parser.add_argument(
        "--source-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_SOURCE_DIR,
        help="Directory for normalized Veekun CSV export files.",
    )
    ingest_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=veekun_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    ingest_parser.add_argument(
        "--timeout", type=float, default=60.0, help="HTTP timeout in seconds."
    )
    ingest_parser.add_argument(
        "--include-learnsets",
        action="store_true",
        help="Emit move learn records. This can produce a very large dataset.",
    )
    ingest_parser.add_argument(
        "--version-group",
        action="append",
        default=[],
        help="Limit normalization to one or more Veekun version-group identifiers.",
    )
    ingest_parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Reuse an existing raw Veekun CSV snapshot instead of downloading it again.",
    )
    ingest_parser.set_defaults(func=_return_zero(veekun_ingest.cmd_ingest))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pokemontology",
        description="Unified CLI for building, validating, and transforming pokemontology data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_cmd = subparsers.add_parser(
        "build", help="Assemble ontology and shapes artifacts."
    )
    build_parser_cmd.set_defaults(func=cmd_build)

    check_parser = subparsers.add_parser(
        "check-ttl", help="Parse Turtle files with rdflib."
    )
    check_parser.add_argument("paths", nargs="+", type=Path, help="TTL files to parse.")
    check_parser.set_defaults(func=cmd_check_ttl)

    query_parser = subparsers.add_parser(
        "query", help="Run a SPARQL query against one or more Turtle sources."
    )
    query_parser.add_argument("query", type=Path, help="Path to a SPARQL query file.")
    query_parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="Optional Turtle files to load into the query graph. Defaults to build/ontology.ttl and build/mechanics.ttl.",
    )
    query_parser.add_argument(
        "--pretty", action="store_true", help="Print query results as indented JSON."
    )
    query_parser.set_defaults(func=cmd_query)

    lookup_parser = subparsers.add_parser(
        "lookup", help="Search mechanics entities by name and list their ruleset contexts."
    )
    lookup_parser.add_argument("query", help="Entity search text, such as Gengar.")
    lookup_parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_LOOKUP_SOURCE,
        help="Mechanics Turtle file to inspect. Defaults to build/mechanics.ttl.",
    )
    lookup_parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_ENTITY_INDEX,
        help="Warm-start entity index JSON. Defaults to build/entity-index.json.",
    )
    lookup_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of additional matches to print after the best result.",
    )
    lookup_parser.set_defaults(func=cmd_lookup)

    rulesets_parser = subparsers.add_parser(
        "rulesets", help="List available ruleset context individuals from mechanics data."
    )
    rulesets_parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_LOOKUP_SOURCE,
        help="Mechanics Turtle file to inspect. Defaults to build/mechanics.ttl.",
    )
    rulesets_parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_ENTITY_INDEX,
        help="Warm-start entity index JSON. Defaults to build/entity-index.json.",
    )
    rulesets_parser.set_defaults(func=cmd_rulesets)

    list_classes_parser = subparsers.add_parser(
        "list-classes", help="List ontology classes in the pkm namespace."
    )
    list_classes_parser.add_argument(
        "--ontology",
        type=Path,
        default=None,
        help="Ontology Turtle file to inspect. Defaults to build/ontology.ttl, falling back to docs/ontology.ttl.",
    )
    list_classes_parser.set_defaults(func=cmd_list_classes)

    list_properties_parser = subparsers.add_parser(
        "list-properties", help="List ontology properties in the pkm namespace."
    )
    list_properties_parser.add_argument(
        "--ontology",
        type=Path,
        default=None,
        help="Ontology Turtle file to inspect. Defaults to build/ontology.ttl, falling back to docs/ontology.ttl.",
    )
    list_properties_parser.set_defaults(func=cmd_list_properties)

    describe_parser = subparsers.add_parser(
        "describe", help="Describe one ontology term and show example usage."
    )
    describe_parser.add_argument("term", help="Term to inspect, such as pkm:ContextualFact.")
    describe_parser.add_argument(
        "--ontology",
        type=Path,
        default=None,
        help="Ontology Turtle file to inspect. Defaults to build/ontology.ttl, falling back to docs/ontology.ttl.",
    )
    describe_parser.set_defaults(func=cmd_describe_term)

    ask_parser = subparsers.add_parser(
        "ask",
        help="Translate a natural-language question to SPARQL with a local Ollama model.",
    )
    ask_parser.add_argument("question", help="Natural-language question to translate.")
    ask_parser.add_argument(
        "--schema-index",
        type=Path,
        default=DEFAULT_SCHEMA_INDEX,
        help="Path to the schema-index.json for RAG grounding.",
    )
    ask_parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model name to use for translation.",
    )
    ask_parser.add_argument(
        "--endpoint",
        default=DEFAULT_OLLAMA_ENDPOINT,
        help="Ollama generate endpoint URL.",
    )
    ask_parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Timeout in seconds for the Ollama request.",
    )
    ask_parser.set_defaults(func=cmd_ask)

    laurel_parser = subparsers.add_parser(
        "laurel",
        help="Translate a natural-language question to SPARQL, execute it, and summarize the results in natural language.",
    )
    laurel_parser.add_argument("question", help="Natural-language question to translate.")
    laurel_parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="Optional Turtle files to load into the query graph. Defaults to build/ontology.ttl and build/mechanics.ttl.",
    )
    laurel_parser.add_argument(
        "--schema-index",
        type=Path,
        default=DEFAULT_SCHEMA_INDEX,
        help="Path to the schema-index.json for RAG grounding.",
    )
    laurel_parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model name to use for translation.",
    )
    laurel_parser.add_argument(
        "--endpoint",
        default=DEFAULT_OLLAMA_ENDPOINT,
        help="Ollama generate endpoint URL.",
    )
    laurel_parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Timeout in seconds for the Ollama request.",
    )
    laurel_parser.add_argument(
        "--print-sparql",
        action="store_true",
        help="Print the generated SPARQL before answering.",
    )
    laurel_parser.add_argument(
        "--json",
        action="store_true",
        help="Print question, generated SPARQL, raw results, and synthesized answer as JSON.",
    )
    laurel_parser.set_defaults(func=cmd_laurel)

    eval_parser = subparsers.add_parser(
        "evaluate-laurel",
        help="Run the Laurel evaluation suite against the current NL-to-SPARQL generator.",
    )
    eval_parser.add_argument(
        "--suite",
        type=Path,
        default=DEFAULT_SUITE,
        help="Path to the Laurel evaluation suite JSON.",
    )
    eval_parser.add_argument(
        "--schema-index",
        type=Path,
        default=DEFAULT_SCHEMA_INDEX,
        help="Path to the schema-index.json for RAG grounding.",
    )
    eval_parser.add_argument(
        "--mode",
        choices=["translation", "pipeline"],
        default="translation",
        help="Whether to evaluate just NL-to-SPARQL translation or the full Laurel answer pipeline.",
    )
    eval_parser.add_argument(
        "--tier",
        default=None,
        help="Optional tier to evaluate, such as easy, medium, hard, generation-specific, or adversarial.",
    )
    eval_parser.add_argument(
        "--list-tiers",
        action="store_true",
        help="Print suite metadata and tier counts without running the model.",
    )
    eval_parser.add_argument(
        "--validate-suite",
        action="store_true",
        help="Validate the suite structure and print a summary without running the model.",
    )
    eval_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of evaluated items.",
    )
    eval_parser.add_argument(
        "--include-adversarial",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to include adversarial prompts in the evaluation run.",
    )
    eval_parser.add_argument(
        "--save-report",
        type=Path,
        default=None,
        help="Optional path to save a detailed JSON report with SPARQL, answers, raw payloads, and timings.",
    )
    eval_parser.add_argument(
        "--execution-timeout",
        type=float,
        default=None,
        help="Optional per-query execution timeout in seconds for pipeline evaluation reports.",
    )
    eval_parser.add_argument(
        "sources",
        nargs="*",
        type=Path,
        help="Optional Turtle sources. Required when --mode pipeline is used.",
    )
    eval_parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model name to use for translation.",
    )
    eval_parser.add_argument(
        "--endpoint",
        default=DEFAULT_OLLAMA_ENDPOINT,
        help="Ollama generate endpoint URL.",
    )
    eval_parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Timeout in seconds for each Ollama request.",
    )
    eval_parser.set_defaults(func=cmd_evaluate_laurel)

    parse_parser = subparsers.add_parser(
        "parse-replay", help="Parse a Showdown replay into a turn/event stream."
    )
    parse_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    parse_parser.add_argument(
        "--pretty", action="store_true", help="Print parsed turns as indented JSON."
    )
    parse_parser.set_defaults(func=cmd_parse_replay)

    summarize_parser = subparsers.add_parser(
        "summarize-replay", help="Summarize a Showdown replay JSON."
    )
    summarize_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    summarize_parser.set_defaults(func=cmd_summarize_replay)

    slice_parser = subparsers.add_parser(
        "build-slice", help="Build a replay-backed Turtle slice."
    )
    slice_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    slice_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <replay_json stem>-slice.ttl.",
    )
    slice_parser.set_defaults(func=cmd_build_slice)

    resolve_parser = subparsers.add_parser(
        "resolve-order",
        help="Infer heads-up action order from move priority and battle-state snapshot inputs.",
    )
    resolve_parser.add_argument(
        "state_json", type=Path, help="Path to turn-order input JSON."
    )
    resolve_parser.add_argument(
        "--pretty", action="store_true", help="Print inferred order as indented JSON."
    )
    resolve_parser.set_defaults(func=cmd_resolve_order)

    serve_parser = subparsers.add_parser(
        "serve-docs",
        help="Serve docs/index.html locally for frontend testing.",
    )
    serve_parser.add_argument(
        "--host",
        default="localhost",
        help="Interface to bind. Defaults to localhost.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind. Defaults to 8000.",
    )
    serve_parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DEFAULT_DOCS_DIR,
        help="Directory to serve. Defaults to the repository docs/ folder.",
    )
    serve_parser.set_defaults(func=cmd_serve_docs)

    meta_parser = subparsers.add_parser(
        "meta-snapshot",
        help="Aggregate a competitive usage MetaSnapshot from Showdown replay JSON files.",
    )
    meta_parser.add_argument(
        "replay_json",
        nargs="*",
        type=Path,
        help="One or more Showdown replay JSON paths. If omitted, reads from --curated list.",
    )
    meta_parser.add_argument(
        "--curated",
        type=Path,
        default=None,
        help="Path to curated replay list JSON. Defaults to data/replays/curated/competitive.json.",
    )
    meta_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Directory containing cached replay JSON. Defaults to data/replays/raw/showdown.",
    )
    meta_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to build/meta-snapshot.ttl.",
    )
    meta_parser.add_argument(
        "--date",
        default=None,
        help="Snapshot date as YYYY-MM-DD. Defaults to today.",
    )
    meta_parser.set_defaults(func=cmd_meta_snapshot)

    add_replay_dataset_subcommands(subparsers)
    add_pokeapi_subcommands(subparsers)
    add_veekun_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.func(args))
    except CliUsageError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
