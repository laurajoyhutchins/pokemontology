"""Integration tests for the rdflib-based replay TTL builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace

from scripts.replay.replay_parser import parse_log
from scripts.replay.replay_to_ttl_builder import build_graph

REPO = Path(__file__).parent.parent
REPLAY_JSON = REPO / "examples" / "replays" / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


@pytest.fixture(scope="module")
def replay_payload() -> dict:
    return json.loads(REPLAY_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replay_graph(replay_payload: dict) -> Graph:
    return build_graph(replay_payload)


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
