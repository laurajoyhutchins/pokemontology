"""Shared helpers for source ingestion and external reference emission."""

from __future__ import annotations

import re
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from ._script_loader import REPO_ROOT


SITE_BASE = "https://laurajoyhutchins.github.io/pokemontology"
PKM = Namespace(f"{SITE_BASE}/ontology.ttl#")
PKMI = Namespace(f"{SITE_BASE}/id/")

INSTANCE_KIND_BY_CLASS_NAME = {
    "Species": "species",
    "Variant": "variant",
    "Move": "move",
    "Ability": "ability",
    "Item": "item",
    "Type": "type",
    "Stat": "stat",
    "Ruleset": "ruleset",
    "VersionGroup": "version-group",
    "TypingAssignment": "assignment/typing",
    "StatAssignment": "assignment/stat",
    "AbilityAssignment": "assignment/ability",
    "MoveLearnRecord": "assignment/move-learn",
    "MovePropertyAssignment": "assignment/move-property",
    "ItemPropertyAssignment": "assignment/item-property",
    "TypeEffectivenessAssignment": "assignment/type-effectiveness",
    "Ref": "reference",
    "DatasetArtifact": "artifact",
}


def sanitize_identifier(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "Unnamed"
    if value[0].isdigit():
        return f"N_{value}"
    return value


def sanitize_path_segment(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        return "unnamed"
    if value[0].isdigit():
        return f"n-{value}"
    return value


def vocab_iri(local_name: str) -> URIRef:
    return PKM[local_name]


def instance_iri(*segments: str) -> URIRef:
    path = "/".join(sanitize_path_segment(segment) for segment in segments if segment)
    return URIRef(f"{PKMI}{path}")


def entity_iri(class_name: str, identifier: str) -> URIRef:
    kind = INSTANCE_KIND_BY_CLASS_NAME.get(class_name)
    if kind is None:
        raise KeyError(f"unsupported instance class name: {class_name}")
    return instance_iri(kind, identifier)


def assignment_iri(class_name: str, *segments: str) -> URIRef:
    kind = INSTANCE_KIND_BY_CLASS_NAME.get(class_name)
    if kind is None or not kind.startswith("assignment/"):
        raise KeyError(f"unsupported assignment class name: {class_name}")
    prefix_segments = kind.split("/")
    return instance_iri(*prefix_segments, *segments)


def bind_namespaces(g: Graph) -> None:
    g.bind("pkm", PKM)
    g.bind("pkmi", PKMI)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)


def add_dataset_header(
    g: Graph, dataset_name: str, dataset_path: str, comment: str
) -> URIRef:
    dataset_iri = URIRef(f"{SITE_BASE}/data/{dataset_path}")
    g.add((dataset_iri, RDFS.label, Literal(dataset_name)))
    g.add((dataset_iri, RDFS.comment, Literal(comment)))
    return dataset_iri


def add_dataset_artifact(
    g: Graph, artifact_iri: URIRef, name: str, source_url: str
) -> None:
    g.add((artifact_iri, RDF.type, PKM.EvidenceArtifact))
    g.add((artifact_iri, PKM.hasName, Literal(name)))
    g.add((artifact_iri, PKM.hasSourceURL, Literal(source_url, datatype=XSD.anyURI)))


def add_external_reference(
    g: Graph,
    *,
    source_slug: str,
    resource: str,
    identifier: str,
    entity_iri: URIRef,
    artifact_iri: URIRef,
    external_iri: str,
) -> URIRef:
    ref_iri = instance_iri("reference", source_slug, resource, identifier)
    g.add((ref_iri, RDF.type, PKM.ExternalEntityReference))
    g.add((ref_iri, PKM.refersToEntity, entity_iri))
    g.add((ref_iri, PKM.describedByArtifact, artifact_iri))
    g.add((ref_iri, PKM.hasExternalIRI, Literal(external_iri, datatype=XSD.anyURI)))
    return ref_iri


def serialize_turtle_to_path(graph: Graph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(path), format="turtle")
