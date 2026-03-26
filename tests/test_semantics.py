"""Semantic regression tests against the example slice."""

from __future__ import annotations

from rdflib import Graph, Namespace, RDF

PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")


# ---------------------------------------------------------------------------
# Faint events → HP=0
# ---------------------------------------------------------------------------


def test_faint_events_have_hp_zero_assignment(combined_graph: Graph) -> None:
    """Every FaintEvent must have a corresponding CurrentHPAssignment of 0
    for the affected combatant at the same Instantaneous."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

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
    missing = list(combined_graph.query(query))
    assert missing == [], (
        "FaintEvent(s) missing a HP=0 CurrentHPAssignment at their instantaneous:\n"
        + "\n".join(
            f"  {row.faintEvent} → {row.combatant} @ {row.instant}" for row in missing
        )
    )


def test_faint_hp_assignments_are_zero(combined_graph: Graph) -> None:
    """All CurrentHPAssignments at a FaintEvent instantaneous for the fainted
    combatant must have value 0 (no non-zero HP recorded at faint)."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

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
    bad = list(combined_graph.query(query))
    assert bad == [], "Non-zero HP recorded at faint instantaneous:\n" + "\n".join(
        f"  {row.hp} = {row.value} for {row.combatant} @ {row.instant}" for row in bad
    )


# ---------------------------------------------------------------------------
# StatStageAssignment uniqueness
# ---------------------------------------------------------------------------


def test_stat_stage_uniqueness(combined_graph: Graph) -> None:
    """At most one StatStageAssignment per (combatant, stat, instantaneous)."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

    SELECT ?combatant ?stat ?instant (COUNT(?ssa) AS ?count) WHERE {
        ?ssa a pkm:StatStageAssignment ;
             pkm:aboutCombatant ?combatant ;
             pkm:aboutStat ?stat ;
             pkm:hasContext ?instant .
    }
    GROUP BY ?combatant ?stat ?instant
    HAVING (COUNT(?ssa) > 1)
    """
    duplicates = list(combined_graph.query(query))
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


def test_instantaneous_chain_is_acyclic(combined_graph: Graph) -> None:
    """hasPreviousInstantaneous must form a DAG (no cycles)."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

    SELECT ?instant WHERE {
        ?instant pkm:hasPreviousInstantaneous+ ?instant .
    }
    """
    cycles = list(combined_graph.query(query))
    assert cycles == [], (
        "Cycles detected in hasPreviousInstantaneous chain:\n"
        + "\n".join(f"  {row.instant}" for row in cycles)
    )


def test_each_instantaneous_has_at_most_one_predecessor(combined_graph: Graph) -> None:
    """Each Instantaneous must have at most one hasPreviousInstantaneous."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

    SELECT ?instant (COUNT(?prev) AS ?count) WHERE {
        ?instant a pkm:Instantaneous ;
                 pkm:hasPreviousInstantaneous ?prev .
    }
    GROUP BY ?instant
    HAVING (COUNT(?prev) > 1)
    """
    bad = list(combined_graph.query(query))
    assert bad == [], "Instantaneous nodes with multiple predecessors:\n" + "\n".join(
        f"  {row.instant} has {row['count']} predecessors" for row in bad
    )


# ---------------------------------------------------------------------------
# Battle participant membership
# ---------------------------------------------------------------------------


def test_all_combatants_belong_to_a_battle(combined_graph: Graph) -> None:
    """Every BattleParticipant must participate in exactly one Battle."""
    query = """
    PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

    SELECT ?combatant (COUNT(DISTINCT ?battle) AS ?count) WHERE {
        ?combatant a pkm:BattleParticipant .
        OPTIONAL { ?combatant pkm:participatesInBattle ?battle . }
    }
    GROUP BY ?combatant
    HAVING (COUNT(DISTINCT ?battle) != 1)
    """
    bad = list(combined_graph.query(query))
    assert bad == [], "BattleParticipants not in exactly one Battle:\n" + "\n".join(
        f"  {row.combatant} (battles: {row['count']})" for row in bad
    )
