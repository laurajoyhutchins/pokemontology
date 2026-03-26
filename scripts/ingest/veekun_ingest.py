#!/usr/bin/env python3
"""Transform a normalized local Veekun export into ontology-native TTL.

This script is intentionally local-only. It expects CSV exports prepared from a
local Veekun checkout/database and does not download or republish upstream
dataset dumps on its own.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from pokemontology.ingest_common import (
    PKM,
    REPO_ROOT,
    add_dataset_artifact as add_dataset_artifact_node,
    add_dataset_header,
    add_external_reference as add_external_reference_node,
    bind_namespaces,
    iri_for,
)


REPO = REPO_ROOT
DEFAULT_SOURCE_DIR = REPO / "data" / "veekun" / "export"
DEFAULT_OUTPUT = REPO / "build" / "veekun.ttl"

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

VEEKUN_URN_BASE = "urn:veekun"


def veekun_external_iri(resource: str, identifier: str) -> str:
    return f"{VEEKUN_URN_BASE}:{resource}:{identifier}"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def add_veekun_external_reference(
    g: Graph, resource: str, identifier: str, entity_iri: URIRef
) -> None:
    add_external_reference_node(
        g,
        source_slug="Veekun",
        resource=resource,
        identifier=identifier,
        entity_iri=entity_iri,
        artifact_iri=PKM.DatasetArtifact_Veekun,
        external_iri=veekun_external_iri(resource, identifier),
    )


def add_named_entity(
    g: Graph, class_name: str, rdf_class: URIRef, row: dict[str, str], resource: str
) -> URIRef:
    identifier = row["identifier"]
    iri = iri_for(class_name, identifier)
    g.add((iri, RDF.type, rdf_class))
    g.add((iri, PKM.hasName, Literal(row["name"])))
    g.add((iri, PKM.hasIdentifier, Literal(f"veekun:{resource}:{identifier}")))
    add_veekun_external_reference(g, resource, identifier, iri)
    return iri


def add_version_group(g: Graph, row: dict[str, str]) -> URIRef:
    identifier = row["identifier"]
    version_group_iri = iri_for("VersionGroup", identifier)
    ruleset_iri = iri_for("Ruleset", identifier)

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
        g, PKM.DatasetArtifact_Veekun, "Veekun", "https://github.com/veekun/pokedex"
    )


def add_variant_links(g: Graph, rows: list[dict[str, str]]) -> None:
    for row in rows:
        variant_iri = iri_for("Variant", row["identifier"])
        species_iri = iri_for("Species", row["species_identifier"])
        g.add((variant_iri, PKM.belongsToSpecies, species_iri))


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
        "Auto-generated TTL dataset built from a local normalized Veekun export. "
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

    optional_rows: dict[str, list[dict[str, str]]] = {}
    for filename in OPTIONAL_ASSIGNMENT_FILES:
        path = source_dir / filename
        if path.exists():
            optional_rows[filename] = read_rows(path)

    for row in optional_rows.get("typing_assignments.csv", []):
        assignment_iri = iri_for(
            "TypingAssignment",
            f"{row['variant_identifier']}_{row['type_identifier']}_{row['version_group_identifier']}_{row['type_slot']}",
        )
        g.add((assignment_iri, RDF.type, PKM.TypingAssignment))
        g.add(
            (
                assignment_iri,
                PKM.aboutVariant,
                iri_for("Variant", row["variant_identifier"]),
            )
        )
        g.add((assignment_iri, PKM.aboutType, iri_for("Type", row["type_identifier"])))
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasTypeSlot,
                Literal(int(row["type_slot"]), datatype=XSD.integer),
            )
        )

    for row in optional_rows.get("ability_assignments.csv", []):
        assignment_iri = iri_for(
            "AbilityAssignment",
            f"{row['variant_identifier']}_{row['ability_identifier']}_{row['version_group_identifier']}",
        )
        g.add((assignment_iri, RDF.type, PKM.AbilityAssignment))
        g.add(
            (
                assignment_iri,
                PKM.aboutVariant,
                iri_for("Variant", row["variant_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.aboutAbility,
                iri_for("Ability", row["ability_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.isHiddenAbility,
                Literal(
                    row["is_hidden_ability"].lower() == "true", datatype=XSD.boolean
                ),
            )
        )

    for row in optional_rows.get("stat_assignments.csv", []):
        assignment_iri = iri_for(
            "StatAssignment",
            f"{row['variant_identifier']}_{row['stat_identifier']}_{row['version_group_identifier']}",
        )
        g.add((assignment_iri, RDF.type, PKM.StatAssignment))
        g.add(
            (
                assignment_iri,
                PKM.aboutVariant,
                iri_for("Variant", row["variant_identifier"]),
            )
        )
        g.add((assignment_iri, PKM.aboutStat, iri_for("Stat", row["stat_identifier"])))
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasValue,
                Literal(int(row["value"]), datatype=XSD.integer),
            )
        )

    for row in optional_rows.get("move_property_assignments.csv", []):
        assignment_iri = iri_for(
            "MovePropertyAssignment",
            f"{row['move_identifier']}_{row['version_group_identifier']}",
        )
        g.add((assignment_iri, RDF.type, PKM.MovePropertyAssignment))
        g.add((assignment_iri, PKM.aboutMove, iri_for("Move", row["move_identifier"])))
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasMoveType,
                iri_for("Type", row["move_type_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasBasePower,
                Literal(int(row["base_power"]), datatype=XSD.integer),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasAccuracy,
                Literal(int(row["accuracy"]), datatype=XSD.integer),
            )
        )
        g.add(
            (assignment_iri, PKM.hasPP, Literal(int(row["pp"]), datatype=XSD.integer))
        )
        g.add(
            (
                assignment_iri,
                PKM.hasPriority,
                Literal(int(row["priority"]), datatype=XSD.integer),
            )
        )

    for row in optional_rows.get("move_learn_records.csv", []):
        assignment_iri = iri_for(
            "MoveLearnRecord",
            f"{row['variant_identifier']}_{row['move_identifier']}_{row['version_group_identifier']}",
        )
        g.add((assignment_iri, RDF.type, PKM.MoveLearnRecord))
        g.add(
            (
                assignment_iri,
                PKM.aboutVariant,
                iri_for("Variant", row["variant_identifier"]),
            )
        )
        g.add(
            (assignment_iri, PKM.learnableMove, iri_for("Move", row["move_identifier"]))
        )
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.isLearnableInRuleset,
                Literal(row["is_learnable"].lower() == "true", datatype=XSD.boolean),
            )
        )

    for row in optional_rows.get("type_effectiveness_assignments.csv", []):
        assignment_iri = iri_for(
            "TypeEffectivenessAssignment",
            f"{row['attacker_type_identifier']}_{row['defender_type_identifier']}_{row['version_group_identifier']}",
        )
        g.add((assignment_iri, RDF.type, PKM.TypeEffectivenessAssignment))
        g.add(
            (
                assignment_iri,
                PKM.attackerType,
                iri_for("Type", row["attacker_type_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.defenderType,
                iri_for("Type", row["defender_type_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasContext,
                iri_for("Ruleset", row["version_group_identifier"]),
            )
        )
        g.add(
            (
                assignment_iri,
                PKM.hasDamageFactor,
                Literal(row["damage_factor"], datatype=XSD.decimal),
            )
        )

    return g


def build_ttl_from_csv(source_dir: Path) -> str:
    return build_graph_from_csv(source_dir).serialize(format="turtle")


def cmd_transform(args: argparse.Namespace) -> None:
    ttl = build_ttl_from_csv(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(ttl, encoding="utf-8")
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
