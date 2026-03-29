#!/usr/bin/env python3
"""Fetch selected PokeAPI resources and transform them into ontology-native TTL."""

from __future__ import annotations

import argparse
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from pokemontology.ingest_common import (
    PKM,
    REPO_ROOT,
    add_dataset_artifact,
    add_dataset_header,
    add_external_reference,
    assignment_iri,
    bind_namespaces,
    entity_iri,
    instance_iri,
    sanitize_identifier,
)


REPO = REPO_ROOT
DEFAULT_RAW_DIR = REPO / "data" / "pokeapi" / "raw"
DEFAULT_OUTPUT = REPO / "data" / "ingested" / "pokeapi.ttl"
POKEAPI_BASE = "https://pokeapi.co/api/v2"
POKEAPI_ARTIFACT_IRI = instance_iri("artifact", "pokeapi")
POKEAPI_DATASET_IRI = URIRef(
    "https://laurajoyhutchins.github.io/pokemontology/data/pokeapi.ttl"
)

SUPPORTED_RESOURCES = (
    "pokemon",
    "pokemon-species",
    "move",
    "ability",
    "type",
    "stat",
    "version-group",
    "item",
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


def _term_text(term: URIRef | Literal) -> str:
    if isinstance(term, Literal):
        return term.n3()
    text = str(term)
    if text.startswith(str(PKM)):
        return f"pkm:{text.removeprefix(str(PKM))}"
    if text.startswith(str(instance_iri())):
        local = text.removeprefix(str(instance_iri())).replace("/", "\\/")
        return f"pkmi:{local}"
    if text.startswith(str(RDF)):
        local = text.removeprefix(str(RDF))
        return "a" if local == "type" else f"rdf:{local}"
    if text.startswith(str(RDFS)):
        return f"rdfs:{text.removeprefix(str(RDFS))}"
    if text.startswith(str(XSD)):
        return f"xsd:{text.removeprefix(str(XSD))}"
    return f"<{text}>"


def _write_block(
    handle: TextIO,
    subject: URIRef,
    predicate_objects: list[tuple[URIRef, URIRef | Literal]],
) -> None:
    if not predicate_objects:
        return
    subject_text = _term_text(subject)
    parts = [
        f"{_term_text(predicate)} {_term_text(obj)}"
        for predicate, obj in predicate_objects
    ]
    handle.write(f"{subject_text} " + " ; ".join(parts) + " .\n\n")


def _resource_predicates(
    rdf_class: URIRef,
    payload: dict,
    resource: str,
) -> list[tuple[URIRef, URIRef | Literal]]:
    identifier_literal = (
        Literal(f"pokeapi:{resource}:{payload['id']}")
        if "id" in payload
        else Literal(f"pokeapi:{resource}:{payload_name(payload)}")
    )
    return [
        (RDF.type, rdf_class),
        (PKM.hasName, entity_name_literal(payload)),
        (PKM.hasIdentifier, identifier_literal),
    ]


def _external_reference_predicates(
    resource: str,
    payload: dict,
    entity: URIRef,
) -> list[tuple[URIRef, URIRef | Literal]]:
    return [
        (RDF.type, PKM.ExternalEntityReference),
        (PKM.refersToEntity, entity),
        (PKM.describedByArtifact, POKEAPI_ARTIFACT_IRI),
        (
            PKM.hasExternalIRI,
            Literal(pokeapi_resource_url(resource, payload), datatype=XSD.anyURI),
        ),
    ]


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
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    print(f"skipping {resource}/{identifier}: not found (404)")
                    seen.add(key)
                    continue
                raise SystemExit(
                    f"failed to fetch {resource}/{identifier}: {exc}"
                ) from exc
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
        artifact_iri=POKEAPI_ARTIFACT_IRI,
        external_iri=pokeapi_resource_url(resource, payload),
    )


def add_version_group_context(g: Graph, payload: dict) -> URIRef:
    version_group_name = payload_name(payload)
    version_group_iri = entity_iri("VersionGroup", version_group_name)
    ruleset_iri = entity_iri("Ruleset", version_group_name)

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


def is_default_pokemon(
    pokemon_payload: dict, species_payloads: dict[str, dict]
) -> bool:
    pokemon_name = payload_name(pokemon_payload)
    species_name = pokemon_payload.get("species", {}).get("name")
    species_payload = species_payloads.get(species_name or "")
    if species_payload:
        for variety in species_payload.get("varieties", []):
            pokemon_entry = variety.get("pokemon", {})
            if pokemon_entry.get("name") == pokemon_name:
                return bool(variety.get("is_default"))
    return pokemon_name == species_name


def variant_display_name(
    pokemon_payload: dict, species_payloads: dict[str, dict]
) -> str:
    pokemon_name = payload_name(pokemon_payload)
    species_name = pokemon_payload.get("species", {}).get("name")
    species_payload = species_payloads.get(species_name or "")
    species_display = english_name(species_payload) if species_payload else None
    if species_display and pokemon_name.startswith(f"{species_name}-"):
        suffix = pokemon_name.removeprefix(f"{species_name}-")
        return f"{titleize_name(suffix)} {species_display}"
    return titleize_name(pokemon_name)


def _stream_turtle_from_raw(raw_dir: Path, handle: TextIO) -> None:
    payloads = load_raw_payloads(raw_dir)
    species_by_name = {payload_name(item): item for item in payloads["pokemon-species"]}
    version_groups_by_name = {
        payload_name(item): item for item in payloads["version-group"]
    }

    handle.write("@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n")
    handle.write("@prefix pkmi: <https://laurajoyhutchins.github.io/pokemontology/id/> .\n")
    handle.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
    handle.write("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")

    _write_block(
        handle,
        POKEAPI_DATASET_IRI,
        [
            (RDFS.label, Literal("PokeAPI ingestion dataset")),
            (
                RDFS.comment,
                Literal(
                    "Auto-generated TTL dataset built from cached PokeAPI payloads. "
                    "Only data that maps cleanly into the ontology is emitted: canonical entities, "
                    "variant-to-species links, version-group contexts, and version-group-scoped move learnability."
                ),
            ),
        ],
    )
    _write_block(
        handle,
        POKEAPI_ARTIFACT_IRI,
        [
            (RDF.type, PKM.EvidenceArtifact),
            (PKM.hasName, Literal("PokeAPI")),
            (PKM.hasSourceURL, Literal(f"{POKEAPI_BASE}/", datatype=XSD.anyURI)),
        ],
    )

    default_ruleset_iri = entity_iri("Ruleset", "PokeAPI_Default")
    _write_block(
        handle,
        default_ruleset_iri,
        [
            (RDF.type, PKM.Ruleset),
            (PKM.hasName, Literal("PokeAPI Default (Current Generation)")),
            (PKM.hasIdentifier, Literal("pokeapi:ruleset:current")),
        ],
    )

    def write_named_resource(resource: str, class_name: str, payload: dict) -> URIRef:
        iri = entity_iri(class_name, payload_name(payload))
        _write_block(
            handle,
            iri,
            _resource_predicates(getattr(PKM, class_name), payload, resource),
        )
        _write_block(
            handle,
            instance_iri("reference", "PokeAPI", resource, payload_name(payload)),
            _external_reference_predicates(resource, payload, iri),
        )
        return iri

    for payload in payloads["type"]:
        write_named_resource("type", "Type", payload)

    for payload in payloads["stat"]:
        write_named_resource("stat", "Stat", payload)

    for payload in payloads["ability"]:
        write_named_resource("ability", "Ability", payload)

    for payload in payloads["item"]:
        item_name = payload_name(payload)
        item_iri = write_named_resource("item", "Item", payload)
        _write_block(
            handle,
            assignment_iri("ItemPropertyAssignment", item_name, "current"),
            [
                (RDF.type, PKM.ItemPropertyAssignment),
                (PKM.aboutItem, item_iri),
                (PKM.hasContext, default_ruleset_iri),
            ],
        )

    for payload in payloads["move"]:
        move_name = payload_name(payload)
        move_iri = write_named_resource("move", "Move", payload)
        move_type_name = payload.get("type", {}).get("name")
        if not move_type_name:
            continue
        predicates: list[tuple[URIRef, URIRef | Literal]] = [
            (RDF.type, PKM.MovePropertyAssignment),
            (PKM.aboutMove, move_iri),
            (PKM.hasContext, default_ruleset_iri),
            (PKM.hasMoveType, entity_iri("Type", move_type_name)),
        ]
        for predicate, key in (
            (PKM.hasBasePower, "power"),
            (PKM.hasAccuracy, "accuracy"),
            (PKM.hasPriority, "priority"),
            (PKM.hasPP, "pp"),
        ):
            value = payload.get(key)
            if value is not None:
                predicates.append((predicate, Literal(value, datatype=XSD.integer)))
        _write_block(
            handle,
            assignment_iri("MovePropertyAssignment", move_name, "current"),
            predicates,
        )

    for payload in payloads["pokemon-species"]:
        write_named_resource("pokemon-species", "Species", payload)

    for payload in payloads["version-group"]:
        version_group_name = payload_name(payload)
        version_group_iri = write_named_resource("version-group", "VersionGroup", payload)
        _write_block(
            handle,
            entity_iri("Ruleset", version_group_name),
            [
                (RDF.type, PKM.Ruleset),
                (PKM.hasName, entity_name_literal(payload)),
                (PKM.hasVersionGroup, version_group_iri),
                (PKM.hasIdentifier, Literal(f"pokeapi:ruleset:{version_group_name}")),
            ],
        )

    damage_factor_map = {
        "double_damage_to": Decimal("2.0"),
        "half_damage_to": Decimal("0.5"),
        "no_damage_to": Decimal("0.0"),
    }
    for payload in payloads["type"]:
        attacker_name = payload_name(payload)
        attacker_iri = entity_iri("Type", attacker_name)
        relations = payload.get("damage_relations", {})
        for relation_key, factor in damage_factor_map.items():
            for defender_entry in relations.get(relation_key, []):
                defender_name = defender_entry["name"]
                _write_block(
                    handle,
                    assignment_iri(
                        "TypeEffectivenessAssignment",
                        attacker_name,
                        defender_name,
                        "current",
                    ),
                    [
                        (RDF.type, PKM.TypeEffectivenessAssignment),
                        (PKM.attackerType, attacker_iri),
                        (PKM.defenderType, entity_iri("Type", defender_name)),
                        (PKM.hasContext, default_ruleset_iri),
                        (PKM.hasDamageFactor, Literal(factor, datatype=XSD.decimal)),
                    ],
                )

    learn_records_seen: set[tuple[str, str, str]] = set()
    for payload in payloads["pokemon"]:
        pokemon_name = payload_name(payload)
        species_name = payload.get("species", {}).get("name")
        if not species_name:
            raise SystemExit(f"pokemon payload missing species link: {pokemon_name}")
        species_iri = entity_iri("Species", species_name)
        mechanics_target = species_iri
        if not is_default_pokemon(payload, species_by_name):
            mechanics_target = entity_iri("Variant", pokemon_name)
            _write_block(
                handle,
                mechanics_target,
                [
                    (RDF.type, PKM.Variant),
                    (PKM.belongsToSpecies, species_iri),
                    (PKM.hasName, Literal(variant_display_name(payload, species_by_name))),
                    (PKM.hasIdentifier, Literal(f"pokeapi:pokemon:{payload['id']}")),
                ],
            )
        _write_block(
            handle,
            instance_iri("reference", "PokeAPI", "pokemon", pokemon_name),
            _external_reference_predicates("pokemon", payload, mechanics_target),
        )

        for type_slot in payload.get("types", []):
            type_name = type_slot.get("type", {}).get("name")
            if not type_name:
                continue
            _write_block(
                handle,
                assignment_iri(
                    "TypingAssignment",
                    "pokemon",
                    pokemon_name,
                    "type",
                    type_name,
                    "current",
                ),
                [
                    (RDF.type, PKM.TypingAssignment),
                    (PKM.aboutPokemon, mechanics_target),
                    (PKM.aboutType, entity_iri("Type", type_name)),
                    (PKM.hasContext, default_ruleset_iri),
                    (
                        PKM.hasTypeSlot,
                        Literal(type_slot.get("slot", 1), datatype=XSD.integer),
                    ),
                ],
            )

        for ability_slot in payload.get("abilities", []):
            ability_name = ability_slot.get("ability", {}).get("name")
            if not ability_name:
                continue
            _write_block(
                handle,
                assignment_iri(
                    "AbilityAssignment",
                    "pokemon",
                    pokemon_name,
                    "ability",
                    ability_name,
                    "current",
                ),
                [
                    (RDF.type, PKM.AbilityAssignment),
                    (PKM.aboutPokemon, mechanics_target),
                    (PKM.aboutAbility, entity_iri("Ability", ability_name)),
                    (PKM.hasContext, default_ruleset_iri),
                    (
                        PKM.isHiddenAbility,
                        boolean_literal(ability_slot.get("is_hidden", False)),
                    ),
                ],
            )

        for stat_slot in payload.get("stats", []):
            stat_name = stat_slot.get("stat", {}).get("name")
            base_stat = stat_slot.get("base_stat")
            if not stat_name or base_stat is None:
                continue
            _write_block(
                handle,
                assignment_iri(
                    "StatAssignment",
                    "pokemon",
                    pokemon_name,
                    "stat",
                    stat_name,
                    "current",
                ),
                [
                    (RDF.type, PKM.StatAssignment),
                    (PKM.aboutPokemon, mechanics_target),
                    (PKM.aboutStat, entity_iri("Stat", stat_name)),
                    (PKM.hasContext, default_ruleset_iri),
                    (PKM.hasValue, Literal(base_stat, datatype=XSD.integer)),
                ],
            )

        for move_entry in payload.get("moves", []):
            move_name = move_entry.get("move", {}).get("name")
            if not move_name:
                continue
            for detail in move_entry.get("version_group_details", []):
                version_group_name = detail.get("version_group", {}).get("name")
                if not version_group_name or version_group_name not in version_groups_by_name:
                    continue
                key = (pokemon_name, move_name, version_group_name)
                if key in learn_records_seen:
                    continue
                learn_records_seen.add(key)
                _write_block(
                    handle,
                    assignment_iri(
                        "MoveLearnRecord",
                        "pokemon",
                        pokemon_name,
                        "move",
                        move_name,
                        "ruleset",
                        version_group_name,
                    ),
                    [
                        (RDF.type, PKM.MoveLearnRecord),
                        (PKM.aboutPokemon, mechanics_target),
                        (PKM.learnableMove, entity_iri("Move", move_name)),
                        (PKM.hasContext, entity_iri("Ruleset", version_group_name)),
                        (PKM.isLearnableInRuleset, boolean_literal(True)),
                    ],
                )


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
    add_dataset_artifact(g, POKEAPI_ARTIFACT_IRI, "PokeAPI", f"{POKEAPI_BASE}/")

    # Synthetic default ruleset for current-gen PokeAPI data (referenced throughout)
    default_ruleset_iri = entity_iri("Ruleset", "PokeAPI_Default")
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
            g, entity_iri("Type", payload_name(payload)), PKM.Type, payload, "type"
        )

    for payload in payloads["stat"]:
        add_named_resource(
            g, entity_iri("Stat", payload_name(payload)), PKM.Stat, payload, "stat"
        )

    for payload in payloads["ability"]:
        add_named_resource(
            g,
            entity_iri("Ability", payload_name(payload)),
            PKM.Ability,
            payload,
            "ability",
        )

    for payload in payloads["item"]:
        item_name = payload_name(payload)
        item_iri = entity_iri("Item", item_name)
        add_named_resource(g, item_iri, PKM.Item, payload, "item")
        ipa_iri = assignment_iri("ItemPropertyAssignment", item_name, "current")
        g.add((ipa_iri, RDF.type, PKM.ItemPropertyAssignment))
        g.add((ipa_iri, PKM.aboutItem, item_iri))
        g.add((ipa_iri, PKM.hasContext, default_ruleset_iri))

    for payload in payloads["move"]:
        move_name = payload_name(payload)
        add_named_resource(g, entity_iri("Move", move_name), PKM.Move, payload, "move")
        move_type_name = payload.get("type", {}).get("name")
        if move_type_name:
            type_iri = entity_iri("Type", move_type_name)
            move_iri = entity_iri("Move", move_name)
            mpa_iri = assignment_iri("MovePropertyAssignment", move_name, "current")
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
            entity_iri("Species", payload_name(payload)),
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
        attacker_iri = entity_iri("Type", payload_name(payload))
        relations = payload.get("damage_relations", {})
        for relation_key, factor in damage_factor_map.items():
            for defender_entry in relations.get(relation_key, []):
                defender_name = defender_entry["name"]
                defender_iri = entity_iri("Type", defender_name)
                type_effectiveness_iri = assignment_iri(
                    "TypeEffectivenessAssignment",
                    payload_name(payload),
                    defender_name,
                    "current",
                )
                g.add((type_effectiveness_iri, RDF.type, PKM.TypeEffectivenessAssignment))
                g.add((type_effectiveness_iri, PKM.attackerType, attacker_iri))
                g.add((type_effectiveness_iri, PKM.defenderType, defender_iri))
                g.add((type_effectiveness_iri, PKM.hasContext, default_ruleset_iri))
                g.add(
                    (
                        type_effectiveness_iri,
                        PKM.hasDamageFactor,
                        Literal(factor, datatype=XSD.decimal),
                    )
                )

    learn_records_seen: set[tuple[str, str, str]] = set()
    for payload in payloads["pokemon"]:
        pokemon_name = payload_name(payload)
        species_name = payload.get("species", {}).get("name")
        if not species_name:
            raise SystemExit(f"pokemon payload missing species link: {pokemon_name}")
        species_iri = entity_iri("Species", species_name)
        mechanics_subject_iri = species_iri
        if not is_default_pokemon(payload, species_by_name):
            variant_iri = entity_iri("Variant", pokemon_name)
            mechanics_subject_iri = variant_iri
            g.add((variant_iri, RDF.type, PKM.Variant))
            g.add((variant_iri, PKM.belongsToSpecies, species_iri))
            g.add(
                (
                    variant_iri,
                    PKM.hasName,
                    Literal(variant_display_name(payload, species_by_name)),
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
            entity_iri=mechanics_subject_iri,
            artifact_iri=POKEAPI_ARTIFACT_IRI,
            external_iri=pokeapi_resource_url("pokemon", payload),
        )

        # TypingAssignment from pokemon.types
        for type_slot in payload.get("types", []):
            slot_num = type_slot.get("slot", 1)
            type_name = type_slot.get("type", {}).get("name")
            if not type_name:
                continue
            type_iri = entity_iri("Type", type_name)
            typing_assignment_iri = assignment_iri(
                "TypingAssignment",
                "pokemon",
                pokemon_name,
                "type",
                type_name,
                "current",
            )
            g.add((typing_assignment_iri, RDF.type, PKM.TypingAssignment))
            g.add((typing_assignment_iri, PKM.aboutPokemon, mechanics_subject_iri))
            g.add((typing_assignment_iri, PKM.aboutType, type_iri))
            g.add((typing_assignment_iri, PKM.hasContext, default_ruleset_iri))
            g.add(
                (
                    typing_assignment_iri,
                    PKM.hasTypeSlot,
                    Literal(slot_num, datatype=XSD.integer),
                )
            )

        # AbilityAssignment from pokemon.abilities
        for ability_slot in payload.get("abilities", []):
            ability_name = ability_slot.get("ability", {}).get("name")
            if not ability_name:
                continue
            ability_iri = entity_iri("Ability", ability_name)
            is_hidden = ability_slot.get("is_hidden", False)
            ability_assignment_iri = assignment_iri(
                "AbilityAssignment",
                "pokemon",
                pokemon_name,
                "ability",
                ability_name,
                "current",
            )
            g.add((ability_assignment_iri, RDF.type, PKM.AbilityAssignment))
            g.add((ability_assignment_iri, PKM.aboutPokemon, mechanics_subject_iri))
            g.add((ability_assignment_iri, PKM.aboutAbility, ability_iri))
            g.add((ability_assignment_iri, PKM.hasContext, default_ruleset_iri))
            g.add((ability_assignment_iri, PKM.isHiddenAbility, boolean_literal(is_hidden)))

        # StatAssignment from pokemon.stats
        for stat_slot in payload.get("stats", []):
            stat_name = stat_slot.get("stat", {}).get("name")
            base_stat = stat_slot.get("base_stat")
            if not stat_name or base_stat is None:
                continue
            stat_iri = entity_iri("Stat", stat_name)
            stat_assignment_iri = assignment_iri(
                "StatAssignment",
                "pokemon",
                pokemon_name,
                "stat",
                stat_name,
                "current",
            )
            g.add((stat_assignment_iri, RDF.type, PKM.StatAssignment))
            g.add((stat_assignment_iri, PKM.aboutPokemon, mechanics_subject_iri))
            g.add((stat_assignment_iri, PKM.aboutStat, stat_iri))
            g.add((stat_assignment_iri, PKM.hasContext, default_ruleset_iri))
            g.add(
                (
                    stat_assignment_iri,
                    PKM.hasValue,
                    Literal(base_stat, datatype=XSD.integer),
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
                move_learn_record_iri = assignment_iri(
                    "MoveLearnRecord",
                    "pokemon",
                    pokemon_name,
                    "move",
                    move_name,
                    "ruleset",
                    version_group_name,
                )
                g.add((move_learn_record_iri, RDF.type, PKM.MoveLearnRecord))
                g.add((move_learn_record_iri, PKM.aboutPokemon, mechanics_subject_iri))
                g.add((move_learn_record_iri, PKM.learnableMove, entity_iri("Move", move_name)))
                g.add(
                    (
                        move_learn_record_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", version_group_name),
                    )
                )
                g.add((move_learn_record_iri, PKM.isLearnableInRuleset, boolean_literal(True)))

    return g


def write_turtle_from_raw(raw_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        _stream_turtle_from_raw(raw_dir, handle)


def build_ttl_from_raw(raw_dir: Path) -> str:
    buffer = io.StringIO()
    _stream_turtle_from_raw(raw_dir, buffer)
    return buffer.getvalue()


def cmd_fetch(args: argparse.Namespace) -> None:
    fetch_seed_data(load_seed_config(args.seed), args.raw_dir, args.timeout)
    print(args.raw_dir)


def cmd_transform(args: argparse.Namespace) -> None:
    write_turtle_from_raw(args.raw_dir, args.output)
    print(args.output)


def cmd_ingest(args: argparse.Namespace) -> None:
    fetch_seed_data(load_seed_config(args.seed), args.raw_dir, args.timeout)
    write_turtle_from_raw(args.raw_dir, args.output)
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
