#!/usr/bin/env python3
"""Fetch selected PokeAPI resources and transform them into ontology-native TTL."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from pokemontology.ingest_common import (
    PKM,
    REPO_ROOT,
    add_dataset_artifact,
    add_dataset_header,
    add_external_reference,
    bind_namespaces,
    iri_for,
    sanitize_identifier,
)


REPO = REPO_ROOT
DEFAULT_RAW_DIR = REPO / "data" / "pokeapi" / "raw"
DEFAULT_OUTPUT = REPO / "build" / "pokeapi.ttl"
POKEAPI_BASE = "https://pokeapi.co/api/v2"

SUPPORTED_RESOURCES = (
    "pokemon",
    "pokemon-species",
    "move",
    "ability",
    "type",
    "stat",
    "version-group",
)


def titleize_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def english_name(payload: dict) -> str | None:
    for entry in payload.get("names", []):
        language = entry.get("language", {}).get("name")
        if language == "en":
            return entry.get("name")
    return None


def payload_name(payload: dict) -> str:
    return str(payload["name"])


def pokeapi_resource_url(resource: str, payload: dict) -> str:
    identifier = payload.get("id", payload_name(payload))
    return f"{POKEAPI_BASE}/{resource}/{identifier}/"


def entity_name_literal(payload: dict) -> Literal:
    return Literal(english_name(payload) or titleize_name(payload_name(payload)))


def boolean_literal(value: bool) -> Literal:
    return Literal(bool(value), datatype=XSD.boolean)


def load_seed_config(path: Path) -> dict[str, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        raise SystemExit("seed config must contain a top-level 'resources' object")

    normalized: dict[str, list[str]] = {}
    for resource, identifiers in resources.items():
        if resource not in SUPPORTED_RESOURCES:
            raise SystemExit(f"unsupported resource in seed config: {resource}")
        if not isinstance(identifiers, list) or not all(
            isinstance(item, str) for item in identifiers
        ):
            raise SystemExit(f"resource '{resource}' must map to a list of strings")
        normalized[resource] = identifiers
    return normalized


def cache_path(raw_dir: Path, resource: str, identifier: str) -> Path:
    return raw_dir / resource / f"{sanitize_identifier(identifier)}.json"


def fetch_resource(resource: str, identifier: str, timeout: float) -> dict:
    quoted = urllib.parse.quote(identifier)
    url = f"{POKEAPI_BASE}/{resource}/{quoted}/"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "pokemontology-ingest/0.1 (+https://laurajoyhutchins.github.io/pokemontology/)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_related(resource: str, payload: dict) -> list[tuple[str, str]]:
    related: list[tuple[str, str]] = []
    if resource == "pokemon":
        species = payload.get("species", {}).get("name")
        if species:
            related.append(("pokemon-species", species))

        for ability in payload.get("abilities", []):
            name = ability.get("ability", {}).get("name")
            if name:
                related.append(("ability", name))

        for move in payload.get("moves", []):
            name = move.get("move", {}).get("name")
            if name:
                related.append(("move", name))
            for detail in move.get("version_group_details", []):
                version_group = detail.get("version_group", {}).get("name")
                if version_group:
                    related.append(("version-group", version_group))

        for stat in payload.get("stats", []):
            name = stat.get("stat", {}).get("name")
            if name:
                related.append(("stat", name))

        for type_slot in payload.get("types", []):
            name = type_slot.get("type", {}).get("name")
            if name:
                related.append(("type", name))

    elif resource == "move":
        move_type = payload.get("type", {}).get("name")
        if move_type:
            related.append(("type", move_type))

    return related


def fetch_seed_data(
    seed_config: dict[str, list[str]], raw_dir: Path, timeout: float
) -> None:
    queue = deque[tuple[str, str]]()
    for resource, identifiers in seed_config.items():
        for identifier in identifiers:
            queue.append((resource, identifier))

    seen: set[tuple[str, str]] = set()
    while queue:
        resource, identifier = queue.popleft()
        key = (resource, identifier)
        if key in seen:
            continue

        path = cache_path(raw_dir, resource, identifier)
        if path.exists():
            payload = load_payload(path)
        else:
            try:
                payload = fetch_resource(resource, identifier, timeout)
            except urllib.error.URLError as exc:
                raise SystemExit(
                    f"failed to fetch {resource}/{identifier}: {exc}"
                ) from exc
            write_payload(path, payload)

        seen.add(key)
        for related in discover_related(resource, payload):
            if related not in seen:
                queue.append(related)


def load_raw_payloads(raw_dir: Path) -> dict[str, list[dict]]:
    payloads: dict[str, list[dict]] = {resource: [] for resource in SUPPORTED_RESOURCES}
    for resource in SUPPORTED_RESOURCES:
        resource_dir = raw_dir / resource
        if not resource_dir.exists():
            continue
        for path in sorted(resource_dir.glob("*.json")):
            payloads[resource].append(load_payload(path))
    return payloads


def add_named_resource(
    g: Graph, iri: URIRef, rdf_class: URIRef, payload: dict, resource: str
) -> None:
    g.add((iri, RDF.type, rdf_class))
    g.add((iri, PKM.hasName, entity_name_literal(payload)))
    if "id" in payload:
        g.add((iri, PKM.hasIdentifier, Literal(f"pokeapi:{resource}:{payload['id']}")))
    else:
        g.add(
            (
                iri,
                PKM.hasIdentifier,
                Literal(f"pokeapi:{resource}:{payload_name(payload)}"),
            )
        )
    add_external_reference(
        g,
        source_slug="PokeAPI",
        resource=resource,
        identifier=payload_name(payload),
        entity_iri=iri,
        artifact_iri=PKM.DatasetArtifact_PokeAPI,
        external_iri=pokeapi_resource_url(resource, payload),
    )


def add_version_group_context(g: Graph, payload: dict) -> URIRef:
    version_group_name = payload_name(payload)
    version_group_iri = iri_for("VersionGroup", version_group_name)
    ruleset_iri = iri_for("Ruleset", version_group_name)

    add_named_resource(g, version_group_iri, PKM.VersionGroup, payload, "version-group")
    g.add((ruleset_iri, RDF.type, PKM.Ruleset))
    g.add((ruleset_iri, PKM.hasName, entity_name_literal(payload)))
    g.add((ruleset_iri, PKM.hasVersionGroup, version_group_iri))
    g.add(
        (
            ruleset_iri,
            PKM.hasIdentifier,
            Literal(f"pokeapi:ruleset:{version_group_name}"),
        )
    )
    return ruleset_iri


def default_variant_name(
    pokemon_payload: dict, species_payloads: dict[str, dict]
) -> str:
    pokemon_name = payload_name(pokemon_payload)
    species_name = pokemon_payload.get("species", {}).get("name")
    species_payload = species_payloads.get(species_name or "")
    species_display = english_name(species_payload) if species_payload else None
    if "-" not in pokemon_name and species_display:
        return f"{species_display}-Default"
    return titleize_name(pokemon_name)


def build_graph_from_raw(raw_dir: Path) -> Graph:
    payloads = load_raw_payloads(raw_dir)
    species_by_name = {payload_name(item): item for item in payloads["pokemon-species"]}
    version_groups_by_name = {
        payload_name(item): item for item in payloads["version-group"]
    }

    g = Graph()
    bind_namespaces(g)
    add_dataset_header(
        g,
        "PokeAPI ingestion dataset",
        "pokeapi.ttl",
        "Auto-generated TTL dataset built from cached PokeAPI payloads. "
        "Only data that maps cleanly into the ontology is emitted: canonical entities, "
        "variant-to-species links, version-group contexts, and version-group-scoped move learnability.",
    )
    add_dataset_artifact(g, PKM.DatasetArtifact_PokeAPI, "PokeAPI", f"{POKEAPI_BASE}/")

    # Synthetic default ruleset for current-gen PokeAPI data (referenced throughout)
    default_ruleset_iri = PKM["Ruleset_PokeAPI_Default"]
    g.add((default_ruleset_iri, RDF.type, PKM.Ruleset))
    g.add(
        (
            default_ruleset_iri,
            PKM.hasName,
            Literal("PokeAPI Default (Current Generation)"),
        )
    )
    g.add((default_ruleset_iri, PKM.hasIdentifier, Literal("pokeapi:ruleset:current")))

    for payload in payloads["type"]:
        add_named_resource(
            g, iri_for("Type", payload_name(payload)), PKM.Type, payload, "type"
        )

    for payload in payloads["stat"]:
        add_named_resource(
            g, iri_for("Stat", payload_name(payload)), PKM.Stat, payload, "stat"
        )

    for payload in payloads["ability"]:
        add_named_resource(
            g,
            iri_for("Ability", payload_name(payload)),
            PKM.Ability,
            payload,
            "ability",
        )

    for payload in payloads["move"]:
        move_name = payload_name(payload)
        add_named_resource(g, iri_for("Move", move_name), PKM.Move, payload, "move")
        move_type_name = payload.get("type", {}).get("name")
        if move_type_name:
            type_iri = iri_for("Type", move_type_name)
            move_iri = iri_for("Move", move_name)
            mpa_iri = iri_for("MovePropertyAssignment", f"{move_name}_current")
            g.add((mpa_iri, RDF.type, PKM.MovePropertyAssignment))
            g.add((mpa_iri, PKM.aboutMove, move_iri))
            g.add((mpa_iri, PKM.hasContext, default_ruleset_iri))
            g.add((mpa_iri, PKM.hasMoveType, type_iri))
            base_power = payload.get("power")
            if base_power is not None:
                g.add(
                    (
                        mpa_iri,
                        PKM.hasBasePower,
                        Literal(base_power, datatype=XSD.integer),
                    )
                )
            accuracy = payload.get("accuracy")
            if accuracy is not None:
                g.add(
                    (mpa_iri, PKM.hasAccuracy, Literal(accuracy, datatype=XSD.integer))
                )
            priority = payload.get("priority")
            if priority is not None:
                g.add(
                    (mpa_iri, PKM.hasPriority, Literal(priority, datatype=XSD.integer))
                )
            pp = payload.get("pp")
            if pp is not None:
                g.add((mpa_iri, PKM.hasPP, Literal(pp, datatype=XSD.integer)))

    for payload in payloads["pokemon-species"]:
        add_named_resource(
            g,
            iri_for("Species", payload_name(payload)),
            PKM.Species,
            payload,
            "pokemon-species",
        )

    for payload in payloads["version-group"]:
        add_version_group_context(g, payload)

    # TypeEffectivenessAssignment from type.damage_relations
    damage_factor_map = {
        "double_damage_to": Decimal("2.0"),
        "half_damage_to": Decimal("0.5"),
        "no_damage_to": Decimal("0.0"),
    }
    for payload in payloads["type"]:
        attacker_iri = iri_for("Type", payload_name(payload))
        relations = payload.get("damage_relations", {})
        for relation_key, factor in damage_factor_map.items():
            for defender_entry in relations.get(relation_key, []):
                defender_name = defender_entry["name"]
                defender_iri = iri_for("Type", defender_name)
                assignment_iri = iri_for(
                    "TypeEffectivenessAssignment",
                    f"{payload_name(payload)}_{defender_name}_current",
                )
                g.add((assignment_iri, RDF.type, PKM.TypeEffectivenessAssignment))
                g.add((assignment_iri, PKM.attackerType, attacker_iri))
                g.add((assignment_iri, PKM.defenderType, defender_iri))
                g.add((assignment_iri, PKM.hasContext, default_ruleset_iri))
                g.add(
                    (
                        assignment_iri,
                        PKM.hasDamageFactor,
                        Literal(factor, datatype=XSD.decimal),
                    )
                )

    learn_records_seen: set[tuple[str, str, str]] = set()
    for payload in payloads["pokemon"]:
        pokemon_name = payload_name(payload)
        variant_iri = iri_for("Variant", pokemon_name)
        species_name = payload.get("species", {}).get("name")
        if not species_name:
            raise SystemExit(f"pokemon payload missing species link: {pokemon_name}")
        species_iri = iri_for("Species", species_name)

        g.add((variant_iri, RDF.type, PKM.Variant))
        g.add((variant_iri, PKM.belongsToSpecies, species_iri))
        g.add(
            (
                variant_iri,
                PKM.hasName,
                Literal(default_variant_name(payload, species_by_name)),
            )
        )
        g.add(
            (
                variant_iri,
                PKM.hasIdentifier,
                Literal(f"pokeapi:pokemon:{payload['id']}"),
            )
        )
        add_external_reference(
            g,
            source_slug="PokeAPI",
            resource="pokemon",
            identifier=pokemon_name,
            entity_iri=variant_iri,
            artifact_iri=PKM.DatasetArtifact_PokeAPI,
            external_iri=pokeapi_resource_url("pokemon", payload),
        )

        # TypingAssignment from pokemon.types
        for type_slot in payload.get("types", []):
            slot_num = type_slot.get("slot", 1)
            type_name = type_slot.get("type", {}).get("name")
            if not type_name:
                continue
            type_iri = iri_for("Type", type_name)
            typing_assignment_iri = iri_for(
                "TypingAssignment",
                f"{pokemon_name}_{type_name}_current",
            )
            g.add((typing_assignment_iri, RDF.type, PKM.TypingAssignment))
            g.add((typing_assignment_iri, PKM.aboutVariant, variant_iri))
            g.add((typing_assignment_iri, PKM.aboutType, type_iri))
            g.add((typing_assignment_iri, PKM.hasContext, default_ruleset_iri))
            g.add(
                (
                    typing_assignment_iri,
                    PKM.hasTypeSlot,
                    Literal(slot_num, datatype=XSD.integer),
                )
            )

        for move_entry in payload.get("moves", []):
            move_name = move_entry.get("move", {}).get("name")
            if not move_name:
                continue
            for detail in move_entry.get("version_group_details", []):
                version_group_name = detail.get("version_group", {}).get("name")
                if not version_group_name:
                    continue
                if version_group_name not in version_groups_by_name:
                    continue
                key = (pokemon_name, move_name, version_group_name)
                if key in learn_records_seen:
                    continue
                learn_records_seen.add(key)
                assignment_iri = iri_for(
                    "MoveLearnRecord",
                    f"{pokemon_name}_{move_name}_{version_group_name}",
                )
                g.add((assignment_iri, RDF.type, PKM.MoveLearnRecord))
                g.add((assignment_iri, PKM.aboutVariant, variant_iri))
                g.add((assignment_iri, PKM.learnableMove, iri_for("Move", move_name)))
                g.add(
                    (
                        assignment_iri,
                        PKM.hasContext,
                        iri_for("Ruleset", version_group_name),
                    )
                )
                g.add((assignment_iri, PKM.isLearnableInRuleset, boolean_literal(True)))

    return g


def build_ttl_from_raw(raw_dir: Path) -> str:
    return build_graph_from_raw(raw_dir).serialize(format="turtle")


def cmd_fetch(args: argparse.Namespace) -> None:
    fetch_seed_data(load_seed_config(args.seed), args.raw_dir, args.timeout)
    print(args.raw_dir)


def cmd_transform(args: argparse.Namespace) -> None:
    ttl = build_ttl_from_raw(args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(ttl, encoding="utf-8")
    print(args.output)


def cmd_ingest(args: argparse.Namespace) -> None:
    fetch_seed_data(load_seed_config(args.seed), args.raw_dir, args.timeout)
    ttl = build_ttl_from_raw(args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(ttl, encoding="utf-8")
    print(args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
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
        default=DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    fetch_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    transform_parser = subparsers.add_parser(
        "transform", help="Transform cached raw JSON into Turtle."
    )
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Directory containing cached raw JSON.",
    )
    transform_parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output TTL path."
    )
    transform_parser.set_defaults(func=cmd_transform)

    ingest_parser = subparsers.add_parser(
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
        default=DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    ingest_parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output TTL path."
    )
    ingest_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
