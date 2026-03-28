#!/usr/bin/env python3
"""Fetch, normalize, and transform Veekun data into ontology-native TTL."""

from __future__ import annotations

import argparse
import csv
import io
import tarfile
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from pokemontology.ingest_common import (
    PKM,
    REPO_ROOT,
    add_dataset_artifact as add_dataset_artifact_node,
    add_dataset_header,
    add_external_reference as add_external_reference_node,
    assignment_iri,
    bind_namespaces,
    entity_iri,
    instance_iri,
    serialize_turtle_to_path,
)


REPO = REPO_ROOT
DEFAULT_ARCHIVE_URL = "https://github.com/veekun/pokedex/archive/refs/heads/master.tar.gz"
DEFAULT_RAW_DIR = REPO / "data" / "veekun" / "raw"
DEFAULT_SOURCE_DIR = REPO / "data" / "veekun" / "export"
DEFAULT_OUTPUT = REPO / "data" / "ingested" / "veekun.ttl"
ENGLISH_LANGUAGE_ID = "9"
VEEKUN_URN_BASE = "urn:veekun"

ENTITY_FILES: dict[str, tuple[str, URIRef]] = {
    "species.csv": ("Species", PKM.Species),
    "variants.csv": ("Variant", PKM.Variant),
    "moves.csv": ("Move", PKM.Move),
    "abilities.csv": ("Ability", PKM.Ability),
    "types.csv": ("Type", PKM.Type),
    "stats.csv": ("Stat", PKM.Stat),
}

OPTIONAL_ASSIGNMENT_FILES = (
    "typing_assignments.csv",
    "ability_assignments.csv",
    "stat_assignments.csv",
    "move_property_assignments.csv",
    "move_learn_records.csv",
    "type_effectiveness_assignments.csv",
)

REQUIRED_FILES = (
    "species.csv",
    "variants.csv",
    "moves.csv",
    "abilities.csv",
    "types.csv",
    "stats.csv",
    "version_groups.csv",
)

UPSTREAM_REQUIRED_FILES = (
    "abilities.csv",
    "ability_names.csv",
    "move_changelog.csv",
    "move_names.csv",
    "moves.csv",
    "pokemon.csv",
    "pokemon_abilities.csv",
    "pokemon_form_names.csv",
    "pokemon_forms.csv",
    "pokemon_moves.csv",
    "pokemon_species.csv",
    "pokemon_species_names.csv",
    "pokemon_stats.csv",
    "pokemon_types.csv",
    "stat_names.csv",
    "stats.csv",
    "type_efficacy.csv",
    "type_names.csv",
    "types.csv",
    "version_groups.csv",
)


def titleize_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def veekun_external_iri(resource: str, identifier: str) -> str:
    return f"{VEEKUN_URN_BASE}:{resource}:{identifier}"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def iter_rows(path: Path) -> csv.DictReader[str]:
    handle = path.open(encoding="utf-8", newline="")
    try:
        reader = csv.DictReader(handle)
        yield from reader
    finally:
        handle.close()


def require_columns(
    path: Path, rows: list[dict[str, str]], columns: tuple[str, ...]
) -> None:
    if not rows:
        return
    missing = [column for column in columns if column not in rows[0]]
    if missing:
        raise SystemExit(
            f"{path.name} missing required column(s): {', '.join(missing)}"
        )


def require_fieldnames(
    path: Path, fieldnames: list[str] | None, columns: tuple[str, ...]
) -> None:
    if fieldnames is None:
        raise SystemExit(f"{path.name} is missing a CSV header row")
    missing = [column for column in columns if column not in fieldnames]
    if missing:
        raise SystemExit(
            f"{path.name} missing required column(s): {', '.join(missing)}"
        )


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def open_csv_writer(path: Path, fieldnames: tuple[str, ...]) -> tuple[object, csv.DictWriter[str]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    return handle, writer


def add_veekun_external_reference(
    g: Graph, resource: str, identifier: str, entity_iri: URIRef
) -> None:
    add_external_reference_node(
        g,
        source_slug="Veekun",
        resource=resource,
        identifier=identifier,
        entity_iri=entity_iri,
        artifact_iri=instance_iri("artifact", "veekun"),
        external_iri=veekun_external_iri(resource, identifier),
    )


def add_named_entity(
    g: Graph, class_name: str, rdf_class: URIRef, row: dict[str, str], resource: str
) -> URIRef:
    identifier = row["identifier"]
    iri = entity_iri(class_name, identifier)
    g.add((iri, RDF.type, rdf_class))
    g.add((iri, PKM.hasName, Literal(row["name"])))
    g.add((iri, PKM.hasIdentifier, Literal(f"veekun:{resource}:{identifier}")))
    add_veekun_external_reference(g, resource, identifier, iri)
    return iri


def add_version_group(g: Graph, row: dict[str, str]) -> URIRef:
    identifier = row["identifier"]
    version_group_iri = entity_iri("VersionGroup", identifier)
    ruleset_iri = entity_iri("Ruleset", identifier)

    g.add((version_group_iri, RDF.type, PKM.VersionGroup))
    g.add((version_group_iri, PKM.hasName, Literal(row["name"])))
    g.add(
        (
            version_group_iri,
            PKM.hasIdentifier,
            Literal(f"veekun:version-group:{identifier}"),
        )
    )
    add_veekun_external_reference(g, "version-group", identifier, version_group_iri)

    g.add((ruleset_iri, RDF.type, PKM.Ruleset))
    g.add((ruleset_iri, PKM.hasName, Literal(row["name"])))
    g.add((ruleset_iri, PKM.hasIdentifier, Literal(f"veekun:ruleset:{identifier}")))
    g.add((ruleset_iri, PKM.hasVersionGroup, version_group_iri))
    add_veekun_external_reference(g, "ruleset", identifier, ruleset_iri)
    return ruleset_iri


def add_veekun_dataset_artifact(g: Graph) -> None:
    add_dataset_artifact_node(
        g, instance_iri("artifact", "veekun"), "Veekun", "https://github.com/veekun/pokedex"
    )


def add_variant_links(g: Graph, rows: list[dict[str, str]]) -> None:
    for row in rows:
        variant_iri = entity_iri("Variant", row["identifier"])
        species_iri = entity_iri("Species", row["species_identifier"])
        g.add((variant_iri, PKM.belongsToSpecies, species_iri))


def mechanics_subject_iri(subject_kind: str, subject_identifier: str) -> URIRef:
    if subject_kind == "species":
        return entity_iri("Species", subject_identifier)
    if subject_kind == "variant":
        return entity_iri("Variant", subject_identifier)
    raise SystemExit(f"unsupported mechanics subject kind: {subject_kind}")


def add_optional_int(g: Graph, subject: URIRef, predicate: URIRef, value: str) -> None:
    if value.strip():
        g.add((subject, predicate, Literal(int(value), datatype=XSD.integer)))


def build_graph_from_csv(source_dir: Path) -> Graph:
    missing = [name for name in REQUIRED_FILES if not (source_dir / name).exists()]
    if missing:
        raise SystemExit(f"missing Veekun export file(s): {', '.join(missing)}")

    g = Graph()
    bind_namespaces(g)
    add_dataset_header(
        g,
        "Veekun ingestion dataset",
        "veekun.ttl",
        "Auto-generated TTL dataset built from a normalized Veekun export. "
        "This transform emits version-group-scoped mechanics facts where the source export "
        "provides explicit context, plus lightweight external references back to Veekun.",
    )
    add_veekun_dataset_artifact(g)

    entity_rows: dict[str, list[dict[str, str]]] = {}
    for filename, (class_name, rdf_class) in ENTITY_FILES.items():
        rows = read_rows(source_dir / filename)
        require_columns(source_dir / filename, rows, ("identifier", "name"))
        entity_rows[filename] = rows
        for row in rows:
            add_named_entity(
                g, class_name, rdf_class, row, filename.removesuffix(".csv")
            )

    variant_rows = entity_rows["variants.csv"]
    require_columns(
        source_dir / "variants.csv",
        variant_rows,
        ("identifier", "name", "species_identifier"),
    )
    add_variant_links(g, variant_rows)

    version_group_rows = read_rows(source_dir / "version_groups.csv")
    require_columns(
        source_dir / "version_groups.csv", version_group_rows, ("identifier", "name")
    )
    for row in version_group_rows:
        add_version_group(g, row)

    path = source_dir / "typing_assignments.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "pokemon_kind",
                    "pokemon_identifier",
                    "type_identifier",
                    "version_group_identifier",
                    "type_slot",
                ),
            )
            for row in reader:
                typing_assignment_iri = assignment_iri(
                    "TypingAssignment",
                    row["pokemon_kind"],
                    row["pokemon_identifier"],
                    "type",
                    row["type_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                    "slot",
                    row["type_slot"],
                )
                g.add((typing_assignment_iri, RDF.type, PKM.TypingAssignment))
                g.add(
                    (
                        typing_assignment_iri,
                        PKM.aboutPokemon,
                        mechanics_subject_iri(row["pokemon_kind"], row["pokemon_identifier"]),
                    )
                )
                g.add((typing_assignment_iri, PKM.aboutType, entity_iri("Type", row["type_identifier"])))
                g.add(
                    (
                        typing_assignment_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        typing_assignment_iri,
                        PKM.hasTypeSlot,
                        Literal(int(row["type_slot"]), datatype=XSD.integer),
                    )
                )

    path = source_dir / "ability_assignments.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "pokemon_kind",
                    "pokemon_identifier",
                    "ability_identifier",
                    "version_group_identifier",
                    "is_hidden_ability",
                ),
            )
            for row in reader:
                ability_assignment_iri = assignment_iri(
                    "AbilityAssignment",
                    row["pokemon_kind"],
                    row["pokemon_identifier"],
                    "ability",
                    row["ability_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                )
                g.add((ability_assignment_iri, RDF.type, PKM.AbilityAssignment))
                g.add(
                    (
                        ability_assignment_iri,
                        PKM.aboutPokemon,
                        mechanics_subject_iri(row["pokemon_kind"], row["pokemon_identifier"]),
                    )
                )
                g.add(
                    (
                        ability_assignment_iri,
                        PKM.aboutAbility,
                        entity_iri("Ability", row["ability_identifier"]),
                    )
                )
                g.add(
                    (
                        ability_assignment_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        ability_assignment_iri,
                        PKM.isHiddenAbility,
                        Literal(
                            row["is_hidden_ability"].lower() == "true",
                            datatype=XSD.boolean,
                        ),
                    )
                )

    path = source_dir / "stat_assignments.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "pokemon_kind",
                    "pokemon_identifier",
                    "stat_identifier",
                    "version_group_identifier",
                    "value",
                ),
            )
            for row in reader:
                stat_assignment_iri = assignment_iri(
                    "StatAssignment",
                    row["pokemon_kind"],
                    row["pokemon_identifier"],
                    "stat",
                    row["stat_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                )
                g.add((stat_assignment_iri, RDF.type, PKM.StatAssignment))
                g.add(
                    (
                        stat_assignment_iri,
                        PKM.aboutPokemon,
                        mechanics_subject_iri(row["pokemon_kind"], row["pokemon_identifier"]),
                    )
                )
                g.add((stat_assignment_iri, PKM.aboutStat, entity_iri("Stat", row["stat_identifier"])))
                g.add(
                    (
                        stat_assignment_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        stat_assignment_iri,
                        PKM.hasValue,
                        Literal(int(row["value"]), datatype=XSD.integer),
                    )
                )

    path = source_dir / "move_property_assignments.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "move_identifier",
                    "version_group_identifier",
                    "move_type_identifier",
                    "base_power",
                    "accuracy",
                    "pp",
                    "priority",
                ),
            )
            for row in reader:
                move_property_assignment_iri = assignment_iri(
                    "MovePropertyAssignment",
                    row["move_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                )
                g.add((move_property_assignment_iri, RDF.type, PKM.MovePropertyAssignment))
                g.add((move_property_assignment_iri, PKM.aboutMove, entity_iri("Move", row["move_identifier"])))
                g.add(
                    (
                        move_property_assignment_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        move_property_assignment_iri,
                        PKM.hasMoveType,
                        entity_iri("Type", row["move_type_identifier"]),
                    )
                )
                add_optional_int(g, move_property_assignment_iri, PKM.hasBasePower, row["base_power"])
                add_optional_int(g, move_property_assignment_iri, PKM.hasAccuracy, row["accuracy"])
                add_optional_int(g, move_property_assignment_iri, PKM.hasPP, row["pp"])
                add_optional_int(g, move_property_assignment_iri, PKM.hasPriority, row["priority"])

    path = source_dir / "move_learn_records.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "pokemon_kind",
                    "pokemon_identifier",
                    "move_identifier",
                    "version_group_identifier",
                    "is_learnable",
                ),
            )
            for row in reader:
                move_learn_record_iri = assignment_iri(
                    "MoveLearnRecord",
                    row["pokemon_kind"],
                    row["pokemon_identifier"],
                    "move",
                    row["move_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                )
                g.add((move_learn_record_iri, RDF.type, PKM.MoveLearnRecord))
                g.add(
                    (
                        move_learn_record_iri,
                        PKM.aboutPokemon,
                        mechanics_subject_iri(row["pokemon_kind"], row["pokemon_identifier"]),
                    )
                )
                g.add(
                    (move_learn_record_iri, PKM.learnableMove, entity_iri("Move", row["move_identifier"]))
                )
                g.add(
                    (
                        move_learn_record_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        move_learn_record_iri,
                        PKM.isLearnableInRuleset,
                        Literal(row["is_learnable"].lower() == "true", datatype=XSD.boolean),
                    )
                )

    path = source_dir / "type_effectiveness_assignments.csv"
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            require_fieldnames(
                path,
                reader.fieldnames,
                (
                    "attacker_type_identifier",
                    "defender_type_identifier",
                    "version_group_identifier",
                    "damage_factor",
                ),
            )
            for row in reader:
                type_effectiveness_iri = assignment_iri(
                    "TypeEffectivenessAssignment",
                    row["attacker_type_identifier"],
                    row["defender_type_identifier"],
                    "ruleset",
                    row["version_group_identifier"],
                )
                g.add((type_effectiveness_iri, RDF.type, PKM.TypeEffectivenessAssignment))
                g.add(
                    (
                        type_effectiveness_iri,
                        PKM.attackerType,
                        entity_iri("Type", row["attacker_type_identifier"]),
                    )
                )
                g.add(
                    (
                        type_effectiveness_iri,
                        PKM.defenderType,
                        entity_iri("Type", row["defender_type_identifier"]),
                    )
                )
                g.add(
                    (
                        type_effectiveness_iri,
                        PKM.hasContext,
                        entity_iri("Ruleset", row["version_group_identifier"]),
                    )
                )
                g.add(
                    (
                        type_effectiveness_iri,
                        PKM.hasDamageFactor,
                        Literal(row["damage_factor"], datatype=XSD.decimal),
                    )
                )

    return g


def build_ttl_from_csv(source_dir: Path) -> str:
    return build_graph_from_csv(source_dir).serialize(format="turtle")


def fetch_upstream_archive(archive_url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        archive_url,
        headers={
            "User-Agent": "pokemontology-veekun/0.1 (+https://laurajoyhutchins.github.io/pokemontology/)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def extract_upstream_csv_archive(archive_bytes: bytes, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(UPSTREAM_REQUIRED_FILES)
    found: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = Path(member.name)
            if len(path.parts) < 5:
                continue
            if tuple(path.parts[-4:-1]) != ("pokedex", "data", "csv"):
                continue
            filename = path.name
            if filename not in wanted:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            (raw_dir / filename).write_bytes(extracted.read())
            found.add(filename)
    missing = sorted(wanted - found)
    if missing:
        raise SystemExit(
            f"archive missing required Veekun CSV file(s): {', '.join(missing)}"
        )


def english_name_map(path: Path, id_field: str, value_field: str) -> dict[str, str]:
    rows = read_rows(path)
    require_columns(path, rows, (id_field, "local_language_id", value_field))
    names: dict[str, str] = {}
    for row in rows:
        if row["local_language_id"] != ENGLISH_LANGUAGE_ID:
            continue
        value = row[value_field].strip()
        if value:
            names[row[id_field]] = value
    return names


def version_group_rows_by_filter(
    version_groups: list[dict[str, str]],
    allowed_identifiers: set[str] | None,
) -> list[dict[str, str]]:
    if allowed_identifiers is None:
        return version_groups
    filtered = [
        row for row in version_groups if row["identifier"] in allowed_identifiers
    ]
    missing = sorted(
        identifier
        for identifier in allowed_identifiers
        if identifier not in {row["identifier"] for row in filtered}
    )
    if missing:
        raise SystemExit(
            f"unknown Veekun version group identifier(s): {', '.join(missing)}"
        )
    return filtered


def current_properties_for_version_group(
    base_row: dict[str, str],
    changelog_rows: list[dict[str, str]],
    version_group_order: int,
    version_group_orders: dict[str, int],
) -> dict[str, str]:
    merged = {
        "move_type_identifier": base_row["move_type_identifier"],
        "base_power": base_row["base_power"],
        "accuracy": base_row["accuracy"],
        "pp": base_row["pp"],
        "priority": base_row["priority"],
    }
    for row in changelog_rows:
        changed_order = version_group_orders.get(row["changed_in_version_group_id"])
        if changed_order is None or changed_order > version_group_order:
            continue
        if row["move_type_identifier"]:
            merged["move_type_identifier"] = row["move_type_identifier"]
        for field in ("base_power", "accuracy", "pp", "priority"):
            if row[field]:
                merged[field] = row[field]
    return merged


def normalize_veekun_csv(
    raw_dir: Path,
    source_dir: Path,
    *,
    include_learnsets: bool = False,
    version_group_identifiers: tuple[str, ...] = (),
) -> None:
    missing = [name for name in UPSTREAM_REQUIRED_FILES if not (raw_dir / name).exists()]
    if missing:
        raise SystemExit(f"missing Veekun raw CSV file(s): {', '.join(missing)}")

    version_groups_all = read_rows(raw_dir / "version_groups.csv")
    require_columns(
        raw_dir / "version_groups.csv",
        version_groups_all,
        ("id", "identifier", "generation_id", "order"),
    )
    version_groups_all.sort(key=lambda row: int(row["order"]))
    allowed_identifiers = set(version_group_identifiers) if version_group_identifiers else None
    version_groups = version_group_rows_by_filter(version_groups_all, allowed_identifiers)
    version_group_ids = {row["id"] for row in version_groups}
    version_group_orders = {row["id"]: int(row["order"]) for row in version_groups_all}

    species_rows = read_rows(raw_dir / "pokemon_species.csv")
    require_columns(
        raw_dir / "pokemon_species.csv",
        species_rows,
        ("id", "identifier", "generation_id"),
    )
    species_by_id = {row["id"]: row for row in species_rows}
    species_names = english_name_map(
        raw_dir / "pokemon_species_names.csv", "pokemon_species_id", "name"
    )

    pokemon_rows = read_rows(raw_dir / "pokemon.csv")
    require_columns(
        raw_dir / "pokemon.csv",
        pokemon_rows,
        ("id", "identifier", "species_id", "is_default"),
    )
    pokemon_by_id = {row["id"]: row for row in pokemon_rows}

    pokemon_forms = read_rows(raw_dir / "pokemon_forms.csv")
    require_columns(
        raw_dir / "pokemon_forms.csv",
        pokemon_forms,
        ("pokemon_id", "introduced_in_version_group_id"),
    )
    introduced_by_pokemon_id: dict[str, str] = {}
    for row in pokemon_forms:
        introduced = row["introduced_in_version_group_id"].strip()
        if not introduced:
            continue
        current = introduced_by_pokemon_id.get(row["pokemon_id"])
        if current is None or version_group_orders[introduced] < version_group_orders[current]:
            introduced_by_pokemon_id[row["pokemon_id"]] = introduced

    form_names = english_name_map(
        raw_dir / "pokemon_form_names.csv", "pokemon_form_id", "pokemon_name"
    )
    form_name_by_pokemon_id: dict[str, str] = {}
    for row in pokemon_forms:
        pokemon_name = form_names.get(row["id"], "").strip()
        if pokemon_name:
            form_name_by_pokemon_id[row["pokemon_id"]] = pokemon_name

    abilities_rows = read_rows(raw_dir / "abilities.csv")
    require_columns(raw_dir / "abilities.csv", abilities_rows, ("id", "identifier"))
    ability_names = english_name_map(raw_dir / "ability_names.csv", "ability_id", "name")
    abilities_by_id = {row["id"]: row for row in abilities_rows}

    types_rows = read_rows(raw_dir / "types.csv")
    require_columns(raw_dir / "types.csv", types_rows, ("id", "identifier", "generation_id"))
    type_names = english_name_map(raw_dir / "type_names.csv", "type_id", "name")
    types_by_id = {row["id"]: row for row in types_rows}

    stats_rows = read_rows(raw_dir / "stats.csv")
    require_columns(raw_dir / "stats.csv", stats_rows, ("id", "identifier"))
    stat_names = english_name_map(raw_dir / "stat_names.csv", "stat_id", "name")
    stats_by_id = {row["id"]: row for row in stats_rows}

    move_rows = read_rows(raw_dir / "moves.csv")
    require_columns(
        raw_dir / "moves.csv",
        move_rows,
        ("id", "identifier", "generation_id", "type_id", "power", "pp", "accuracy", "priority"),
    )
    move_names = english_name_map(raw_dir / "move_names.csv", "move_id", "name")
    move_identifier_by_id = {row["id"]: row["identifier"] for row in move_rows}
    version_group_identifier_by_id = {
        row["id"]: row["identifier"] for row in version_groups
    }

    source_dir.mkdir(parents=True, exist_ok=True)

    write_csv(
        source_dir / "species.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": species_names.get(row["id"], titleize_name(row["identifier"])),
            }
            for row in species_rows
        ],
    )

    variant_rows: list[dict[str, str]] = []
    for row in pokemon_rows:
        if row["is_default"] == "1":
            continue
        species = species_by_id[row["species_id"]]
        variant_rows.append(
            {
                "identifier": row["identifier"],
                "name": form_name_by_pokemon_id.get(
                    row["id"],
                    titleize_name(row["identifier"]),
                ),
                "species_identifier": species["identifier"],
            }
        )
    write_csv(
        source_dir / "variants.csv",
        ("identifier", "name", "species_identifier"),
        variant_rows,
    )

    write_csv(
        source_dir / "moves.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": move_names.get(row["id"], titleize_name(row["identifier"])),
            }
            for row in move_rows
        ],
    )
    write_csv(
        source_dir / "abilities.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": ability_names.get(row["id"], titleize_name(row["identifier"])),
            }
            for row in abilities_rows
        ],
    )
    write_csv(
        source_dir / "types.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": type_names.get(row["id"], titleize_name(row["identifier"])),
            }
            for row in types_rows
        ],
    )
    write_csv(
        source_dir / "stats.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": stat_names.get(row["id"], titleize_name(row["identifier"])),
            }
            for row in stats_rows
        ],
    )
    write_csv(
        source_dir / "version_groups.csv",
        ("identifier", "name"),
        [
            {
                "identifier": row["identifier"],
                "name": titleize_name(row["identifier"]),
            }
            for row in version_groups
        ],
    )

    version_groups_by_intro: dict[str, list[dict[str, str]]] = {}
    for row in version_groups_all:
        intro_id = row["id"]
        version_groups_by_intro[intro_id] = [
            candidate
            for candidate in version_groups
            if version_group_orders[candidate["id"]] >= version_group_orders[intro_id]
        ]

    def version_groups_from_generation(generation_id: str) -> list[dict[str, str]]:
        return [
            row
            for row in version_groups
            if int(row["generation_id"]) >= int(generation_id)
        ]

    def introduced_version_groups_for_pokemon(pokemon_id: str) -> list[dict[str, str]]:
        introduced = introduced_by_pokemon_id.get(pokemon_id)
        if introduced:
            return version_groups_by_intro.get(introduced, [])
        species = species_by_id[pokemon_by_id[pokemon_id]["species_id"]]
        return version_groups_from_generation(species["generation_id"])

    def mechanics_subject_for_pokemon(pokemon: dict[str, str]) -> tuple[str, str]:
        if pokemon["is_default"] == "1":
            species = species_by_id[pokemon["species_id"]]
            return ("species", species["identifier"])
        return ("variant", pokemon["identifier"])

    handle, writer = open_csv_writer(
        source_dir / "typing_assignments.csv",
        ("pokemon_kind", "pokemon_identifier", "type_identifier", "version_group_identifier", "type_slot"),
    )
    try:
        with (raw_dir / "pokemon_types.csv").open(encoding="utf-8", newline="") as handle_in:
            reader = csv.DictReader(handle_in)
            require_fieldnames(
                raw_dir / "pokemon_types.csv",
                reader.fieldnames,
                ("pokemon_id", "type_id", "slot"),
            )
            for row in reader:
                pokemon = pokemon_by_id[row["pokemon_id"]]
                pokemon_kind, pokemon_identifier = mechanics_subject_for_pokemon(pokemon)
                pokemon_version_groups = introduced_version_groups_for_pokemon(row["pokemon_id"])
                for version_group in pokemon_version_groups:
                    writer.writerow(
                        {
                            "pokemon_kind": pokemon_kind,
                            "pokemon_identifier": pokemon_identifier,
                            "type_identifier": types_by_id[row["type_id"]]["identifier"],
                            "version_group_identifier": version_group["identifier"],
                            "type_slot": row["slot"],
                        }
                    )
    finally:
        handle.close()

    handle, writer = open_csv_writer(
        source_dir / "ability_assignments.csv",
        (
            "pokemon_kind",
            "pokemon_identifier",
            "ability_identifier",
            "version_group_identifier",
            "is_hidden_ability",
        ),
    )
    try:
        with (raw_dir / "pokemon_abilities.csv").open(encoding="utf-8", newline="") as handle_in:
            reader = csv.DictReader(handle_in)
            require_fieldnames(
                raw_dir / "pokemon_abilities.csv",
                reader.fieldnames,
                ("pokemon_id", "ability_id", "is_hidden"),
            )
            for row in reader:
                pokemon = pokemon_by_id[row["pokemon_id"]]
                pokemon_kind, pokemon_identifier = mechanics_subject_for_pokemon(pokemon)
                pokemon_version_groups = introduced_version_groups_for_pokemon(row["pokemon_id"])
                for version_group in pokemon_version_groups:
                    writer.writerow(
                        {
                            "pokemon_kind": pokemon_kind,
                            "pokemon_identifier": pokemon_identifier,
                            "ability_identifier": abilities_by_id[row["ability_id"]]["identifier"],
                            "version_group_identifier": version_group["identifier"],
                            "is_hidden_ability": "true" if row["is_hidden"] == "1" else "false",
                        }
                    )
    finally:
        handle.close()

    handle, writer = open_csv_writer(
        source_dir / "stat_assignments.csv",
        ("pokemon_kind", "pokemon_identifier", "stat_identifier", "version_group_identifier", "value"),
    )
    try:
        with (raw_dir / "pokemon_stats.csv").open(encoding="utf-8", newline="") as handle_in:
            reader = csv.DictReader(handle_in)
            require_fieldnames(
                raw_dir / "pokemon_stats.csv",
                reader.fieldnames,
                ("pokemon_id", "stat_id", "base_stat"),
            )
            for row in reader:
                pokemon = pokemon_by_id[row["pokemon_id"]]
                pokemon_kind, pokemon_identifier = mechanics_subject_for_pokemon(pokemon)
                pokemon_version_groups = introduced_version_groups_for_pokemon(row["pokemon_id"])
                for version_group in pokemon_version_groups:
                    writer.writerow(
                        {
                            "pokemon_kind": pokemon_kind,
                            "pokemon_identifier": pokemon_identifier,
                            "stat_identifier": stats_by_id[row["stat_id"]]["identifier"],
                            "version_group_identifier": version_group["identifier"],
                            "value": row["base_stat"],
                        }
                    )
    finally:
        handle.close()

    move_changelog_rows = read_rows(raw_dir / "move_changelog.csv")
    require_columns(
        raw_dir / "move_changelog.csv",
        move_changelog_rows,
        (
            "move_id",
            "changed_in_version_group_id",
            "type_id",
            "power",
            "pp",
            "accuracy",
            "priority",
        ),
    )
    move_changelog_by_move_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in move_changelog_rows:
        move_changelog_by_move_id[row["move_id"]].append(
            {
                "changed_in_version_group_id": row["changed_in_version_group_id"],
                "move_type_identifier": types_by_id[row["type_id"]]["identifier"]
                if row["type_id"]
                else "",
                "base_power": row["power"],
                "pp": row["pp"],
                "accuracy": row["accuracy"],
                "priority": row["priority"],
            }
        )
    for rows in move_changelog_by_move_id.values():
        rows.sort(key=lambda row: version_group_orders[row["changed_in_version_group_id"]])

    handle, writer = open_csv_writer(
        source_dir / "move_property_assignments.csv",
        (
            "move_identifier",
            "version_group_identifier",
            "move_type_identifier",
            "base_power",
            "accuracy",
            "pp",
            "priority",
        ),
    )
    try:
        for row in move_rows:
            move_version_groups = version_groups_from_generation(row["generation_id"])
            base_row = {
                "move_type_identifier": types_by_id[row["type_id"]]["identifier"],
                "base_power": row["power"],
                "accuracy": row["accuracy"],
                "pp": row["pp"],
                "priority": row["priority"],
            }
            changelog_rows = move_changelog_by_move_id.get(row["id"], [])
            for version_group in move_version_groups:
                properties = current_properties_for_version_group(
                    base_row,
                    changelog_rows,
                    version_group_orders[version_group["id"]],
                    version_group_orders,
                )
                writer.writerow(
                    {
                        "move_identifier": row["identifier"],
                        "version_group_identifier": version_group["identifier"],
                        **properties,
                    }
                )
    finally:
        handle.close()

    if include_learnsets:
        handle, writer = open_csv_writer(
            source_dir / "move_learn_records.csv",
            (
                "pokemon_kind",
                "pokemon_identifier",
                "move_identifier",
                "version_group_identifier",
                "is_learnable",
            ),
        )
        try:
            seen: set[tuple[str, str, str]] = set()
            with (raw_dir / "pokemon_moves.csv").open(encoding="utf-8", newline="") as handle_in:
                reader = csv.DictReader(handle_in)
                require_fieldnames(
                    raw_dir / "pokemon_moves.csv",
                    reader.fieldnames,
                    ("pokemon_id", "version_group_id", "move_id"),
                )
                for row in reader:
                    if row["version_group_id"] not in version_group_ids:
                        continue
                    key = (row["pokemon_id"], row["move_id"], row["version_group_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    pokemon = pokemon_by_id[row["pokemon_id"]]
                    pokemon_kind, pokemon_identifier = mechanics_subject_for_pokemon(pokemon)
                    writer.writerow(
                        {
                            "pokemon_kind": pokemon_kind,
                            "pokemon_identifier": pokemon_identifier,
                            "move_identifier": move_identifier_by_id[row["move_id"]],
                            "version_group_identifier": version_group_identifier_by_id[row["version_group_id"]],
                            "is_learnable": "true",
                        }
                    )
        finally:
            handle.close()
    else:
        path = source_dir / "move_learn_records.csv"
        if path.exists():
            path.unlink()

    handle, writer = open_csv_writer(
        source_dir / "type_effectiveness_assignments.csv",
        (
            "attacker_type_identifier",
            "defender_type_identifier",
            "version_group_identifier",
            "damage_factor",
        ),
    )
    try:
        with (raw_dir / "type_efficacy.csv").open(encoding="utf-8", newline="") as handle_in:
            reader = csv.DictReader(handle_in)
            require_fieldnames(
                raw_dir / "type_efficacy.csv",
                reader.fieldnames,
                ("damage_type_id", "target_type_id", "damage_factor"),
            )
            for row in reader:
                attacker = types_by_id[row["damage_type_id"]]
                defender = types_by_id[row["target_type_id"]]
                start_generation = max(
                    int(attacker["generation_id"]),
                    int(defender["generation_id"]),
                )
                for version_group in version_groups_from_generation(str(start_generation)):
                    writer.writerow(
                        {
                            "attacker_type_identifier": attacker["identifier"],
                            "defender_type_identifier": defender["identifier"],
                            "version_group_identifier": version_group["identifier"],
                            "damage_factor": str(int(row["damage_factor"]) / 100),
                        }
                    )
    finally:
        handle.close()


def cmd_fetch(args: argparse.Namespace) -> None:
    try:
        archive_bytes = fetch_upstream_archive(args.archive_url, args.timeout)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"failed to fetch Veekun archive: {exc}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"failed to fetch Veekun archive: {exc}") from exc
    extract_upstream_csv_archive(archive_bytes, args.raw_dir)
    print(args.raw_dir)


def cmd_normalize(args: argparse.Namespace) -> None:
    normalize_veekun_csv(
        args.raw_dir,
        args.source_dir,
        include_learnsets=args.include_learnsets,
        version_group_identifiers=tuple(args.version_group),
    )
    print(args.source_dir)


def cmd_transform(args: argparse.Namespace) -> None:
    serialize_turtle_to_path(build_graph_from_csv(args.source_dir), args.output)
    print(args.output)


def cmd_ingest(args: argparse.Namespace) -> None:
    if not args.skip_fetch:
        cmd_fetch(args)
    normalize_veekun_csv(
        args.raw_dir,
        args.source_dir,
        include_learnsets=args.include_learnsets,
        version_group_identifiers=tuple(args.version_group),
    )
    serialize_turtle_to_path(build_graph_from_csv(args.source_dir), args.output)
    print(args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing normalized Veekun CSV export files.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output TTL path."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cmd_transform(args)


if __name__ == "__main__":
    main()
