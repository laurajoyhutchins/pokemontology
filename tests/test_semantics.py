"""Semantic regression tests against the example slice."""
from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDF

REPO = Path(__file__).parent.parent

ONTOLOGY = REPO / "ontology" / "pokemon-mechanics-ontology.ttl"
SLICE = REPO / "examples" / "slices" / "showdown-finals-game1-slice.ttl"

PKM = Namespace("http://example.org/pokemon-ontology#")


def _graph() -> Graph:
    g = Graph()
    g.parse(ONTOLOGY, format="turtle")
    g.parse(SLICE, format="turtle")
    return g


# ---------------------------------------------------------------------------
# Faint events → HP=0
# ---------------------------------------------------------------------------

def test_faint_events_have_hp_zero_assignment() -> None:
    """Every FaintEvent must have a corresponding CurrentHPAssignment of 0
    for the affected combatant at the same Instantaneous."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?faintEvent ?combatant ?instant WHERE {
        ?faintEvent a pkm:FaintEvent ;
                    pkm:affectsCombatant ?combatant ;
                    pkm:occursInInstantaneous ?instant .

        FILTER NOT EXISTS {
            ?hp a pkm:CurrentHPAssignment ;
                pkm:aboutCombatant ?combatant ;
                pkm:hasContext ?instant ;
                pkm:hasCurrentHPValue 0 .
        }
    }
    """
    missing = list(g.query(query))
    assert missing == [], (
        "FaintEvent(s) missing a HP=0 CurrentHPAssignment at their instantaneous:\n"
        + "\n".join(f"  {row.faintEvent} → {row.combatant} @ {row.instant}" for row in missing)
    )


def test_faint_hp_assignments_are_zero() -> None:
    """All CurrentHPAssignments at a FaintEvent instantaneous for the fainted
    combatant must have value 0 (no non-zero HP recorded at faint)."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?hp ?combatant ?instant ?value WHERE {
        ?faintEvent a pkm:FaintEvent ;
                    pkm:affectsCombatant ?combatant ;
                    pkm:occursInInstantaneous ?instant .
        ?hp a pkm:CurrentHPAssignment ;
            pkm:aboutCombatant ?combatant ;
            pkm:hasContext ?instant ;
            pkm:hasCurrentHPValue ?value .
        FILTER (?value != 0)
    }
    """
    bad = list(g.query(query))
    assert bad == [], (
        "Non-zero HP recorded at faint instantaneous:\n"
        + "\n".join(f"  {row.hp} = {row.value} for {row.combatant} @ {row.instant}" for row in bad)
    )


# ---------------------------------------------------------------------------
# StatStageAssignment uniqueness
# ---------------------------------------------------------------------------

def test_stat_stage_uniqueness() -> None:
    """At most one StatStageAssignment per (combatant, stat, instantaneous)."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?combatant ?stat ?instant (COUNT(?ssa) AS ?count) WHERE {
        ?ssa a pkm:StatStageAssignment ;
             pkm:aboutCombatant ?combatant ;
             pkm:aboutStat ?stat ;
             pkm:hasContext ?instant .
    }
    GROUP BY ?combatant ?stat ?instant
    HAVING (COUNT(?ssa) > 1)
    """
    duplicates = list(g.query(query))
    assert duplicates == [], (
        "Duplicate StatStageAssignments found (combatant, stat, instant):\n"
        + "\n".join(
            f"  {row.combatant} / {row.stat} @ {row.instant} → {row['count']} assignments"
            for row in duplicates
        )
    )


# ---------------------------------------------------------------------------
# Instantaneous chain integrity
# ---------------------------------------------------------------------------

def test_instantaneous_chain_is_acyclic() -> None:
    """hasPreviousInstantaneous must form a DAG (no cycles)."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?instant WHERE {
        ?instant pkm:hasPreviousInstantaneous+ ?instant .
    }
    """
    cycles = list(g.query(query))
    assert cycles == [], (
        "Cycles detected in hasPreviousInstantaneous chain:\n"
        + "\n".join(f"  {row.instant}" for row in cycles)
    )


def test_each_instantaneous_has_at_most_one_predecessor() -> None:
    """Each Instantaneous must have at most one hasPreviousInstantaneous."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?instant (COUNT(?prev) AS ?count) WHERE {
        ?instant a pkm:Instantaneous ;
                 pkm:hasPreviousInstantaneous ?prev .
    }
    GROUP BY ?instant
    HAVING (COUNT(?prev) > 1)
    """
    bad = list(g.query(query))
    assert bad == [], (
        "Instantaneous nodes with multiple predecessors:\n"
        + "\n".join(f"  {row.instant} has {row['count']} predecessors" for row in bad)
    )


# ---------------------------------------------------------------------------
# Battle participant membership
# ---------------------------------------------------------------------------

def test_all_combatants_belong_to_a_battle() -> None:
    """Every BattleParticipant must participate in exactly one Battle."""
    g = _graph()
    query = """
    PREFIX pkm: <http://example.org/pokemon-ontology#>

    SELECT ?combatant (COUNT(DISTINCT ?battle) AS ?count) WHERE {
        ?combatant a pkm:BattleParticipant .
        OPTIONAL { ?combatant pkm:participatesInBattle ?battle . }
    }
    GROUP BY ?combatant
    HAVING (COUNT(DISTINCT ?battle) != 1)
    """
    bad = list(g.query(query))
    assert bad == [], (
        "BattleParticipants not in exactly one Battle:\n"
        + "\n".join(f"  {row.combatant} (battles: {row['count']})" for row in bad)
    )
