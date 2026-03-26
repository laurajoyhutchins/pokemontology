"""Shared helpers for source ingestion and external reference emission."""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from ._script_loader import REPO_ROOT


SITE_BASE = "https://laurajoyhutchins.github.io/pokemontology"
PKM = Namespace(f"{SITE_BASE}/ontology.ttl#")


def sanitize_identifier(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in value.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "unnamed"


def iri_for(class_name: str, identifier: str) -> URIRef:
    return PKM[f"{class_name}_{sanitize_identifier(identifier)}"]


def bind_namespaces(g: Graph) -> None:
    g.bind("pkm", PKM)
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
    ref_iri = iri_for("Ref", f"{source_slug}_{resource}_{identifier}")
    g.add((ref_iri, RDF.type, PKM.ExternalEntityReference))
    g.add((ref_iri, PKM.refersToEntity, entity_iri))
    g.add((ref_iri, PKM.describedByArtifact, artifact_iri))
    g.add((ref_iri, PKM.hasExternalIRI, Literal(external_iri, datatype=XSD.anyURI)))
    return ref_iri
