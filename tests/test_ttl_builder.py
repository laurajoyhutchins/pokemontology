"""Integration tests for the rdflib-based replay TTL builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF

from scripts.replay.replay_parser import parse_log
from scripts.replay.replay_to_ttl_builder import build_graph

REPO = Path(__file__).parent.parent
REPLAY_JSON = REPO / "examples" / "replays" / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
ONTOLOGY = REPO / "build" / "ontology.ttl"
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


@pytest.fixture(scope="module")
def replay_payload() -> dict:
    return json.loads(REPLAY_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replay_graph(replay_payload: dict) -> Graph:
    return build_graph(replay_payload)


@pytest.fixture(scope="module")
def ontology_graph() -> Graph:
    graph = Graph()
    graph.parse(ONTOLOGY, format="turtle")
    return graph


def test_graph_has_replay_artifact(replay_graph: Graph) -> None:
    artifacts = list(replay_graph.subjects(predicate=__import__("rdflib").RDF.type, object=PKM.ReplayArtifact))
    assert len(artifacts) >= 1


def test_graph_has_battle(replay_graph: Graph) -> None:
    from rdflib import RDF
    battles = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Battle))
    assert len(battles) >= 1


def test_graph_has_two_battle_sides(replay_graph: Graph) -> None:
    from rdflib import RDF
    sides = list(replay_graph.subjects(predicate=RDF.type, object=PKM.BattleSide))
    assert len(sides) >= 2


def test_instantaneous_count_matches_events(replay_payload: dict, replay_graph: Graph) -> None:
    from rdflib import RDF
    events = parse_log(replay_payload["log"])
    instants = list(replay_graph.subjects(predicate=RDF.type, object=PKM.Instantaneous))
    assert len(instants) == len(events)


def test_faint_event_count(replay_payload: dict, replay_graph: Graph) -> None:
    from rdflib import RDF
    expected_faints = sum(
        1 for line in replay_payload["log"].splitlines()
        if line.startswith("|faint|")
    )
    faint_events = list(replay_graph.subjects(predicate=RDF.type, object=PKM.FaintEvent))
    assert len(faint_events) == expected_faints


def test_graph_serializes_valid_turtle(replay_graph: Graph) -> None:
    ttl = replay_graph.serialize(format="turtle")
    g2 = Graph()
    g2.parse(data=ttl, format="turtle")
    assert len(g2) == len(replay_graph)


def test_state_transitions_use_declared_battle_predicates(replay_graph: Graph) -> None:
    for transition in replay_graph.subjects(RDF.type, PKM.StateTransition):
        assert (transition, PKM.fromInstantaneous, None) in replay_graph
        assert (transition, PKM.toInstantaneous, None) in replay_graph
        assert (transition, PKM.triggeredByAction, None) in replay_graph
        assert (transition, PKM.transitionOccursInBattle, None) in replay_graph
        assert (transition, PKM.hasInputState, None) not in replay_graph
        assert (transition, PKM.hasOutputState, None) not in replay_graph
        assert (transition, PKM.triggeredBy, None) not in replay_graph


def test_faint_events_use_declared_event_predicates(replay_graph: Graph) -> None:
    for event in replay_graph.subjects(RDF.type, PKM.FaintEvent):
        assert (event, PKM.affectsCombatant, None) in replay_graph
        assert (event, PKM.occursInInstantaneous, None) in replay_graph
        assert (event, PKM.aboutCombatant, None) not in replay_graph
        assert (event, PKM.occursAtInstantaneous, None) not in replay_graph


def test_builder_uses_only_declared_pkm_predicates(replay_graph: Graph, ontology_graph: Graph) -> None:
    declared = {
        predicate
        for predicate in ontology_graph.subjects(RDF.type, None)
        if str(predicate).startswith(str(PKM))
        and any(
            property_type in (
                RDF.Property,
                OWL.AnnotationProperty,
                OWL.ObjectProperty,
                OWL.DatatypeProperty,
            )
            for property_type in ontology_graph.objects(predicate, RDF.type)
        )
    }

    used = {predicate for _, predicate, _ in replay_graph if str(predicate).startswith(str(PKM))}
    assert used <= declared, f"undeclared pkm: predicates in replay graph: {sorted(str(p) for p in used - declared)}"
