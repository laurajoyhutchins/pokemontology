"""Shared support helpers for Laurel CLI and evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path


def write_super_effective_fixture(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

pkm:Ruleset_PokeAPI_Default a pkm:Ruleset .

pkm:MyCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Charmander" .

pkm:OpponentCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Bulbasaur" ;
    pkm:representsSpecies pkm:Species_bulbasaur .

pkm:Action_Ember
    a pkm:MoveUseAction ;
    pkm:hasActor pkm:MyCombatant ;
    pkm:usesMove pkm:Move_ember .

pkm:Move_ember
    a pkm:Move ;
    pkm:hasName "Ember" .

pkm:Type_fire
    a pkm:Type ;
    pkm:hasName "Fire" .

pkm:Type_grass
    a pkm:Type ;
    pkm:hasName "Grass" .

pkm:MovePropertyAssignment_ember
    a pkm:MovePropertyAssignment ;
    pkm:aboutMove pkm:Move_ember ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:hasMoveType pkm:Type_fire .

pkm:Variant_bulbasaur
    a pkm:Variant ;
    pkm:belongsToSpecies pkm:Species_bulbasaur .

pkm:TypingAssignment_bulbasaur_grass
    a pkm:TypingAssignment ;
    pkm:aboutVariant pkm:Variant_bulbasaur ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:aboutType pkm:Type_grass .

pkm:TypeEffectivenessAssignment_fire_grass
    a pkm:TypeEffectivenessAssignment ;
    pkm:attackerType pkm:Type_fire ;
    pkm:defenderType pkm:Type_grass ;
    pkm:hasContext pkm:Ruleset_PokeAPI_Default ;
    pkm:hasDamageFactor "2.0"^^xsd:decimal .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_dense_schema_index(
    path: Path,
    *,
    vocabulary: list[str],
    vector: list[int],
    item: dict[str, object],
) -> None:
    path.write_text(
        json.dumps(
            {
                "vocabulary": vocabulary,
                "vectors": [vector],
                "items": [item],
            }
        ),
        encoding="utf-8",
    )


def write_eval_suite(path: Path, *, tier: str, item: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "tiers": [{"tier": tier, "items": [item]}],
                "adversarial": [],
            }
        ),
        encoding="utf-8",
    )


def write_charizard_fire_source(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

pkm:Species_charizard a pkm:Species ;
    rdfs:label "Charizard" .

pkm:Variant_charizard a pkm:Variant ;
    pkm:belongsToSpecies pkm:Species_charizard .

pkm:Type_fire a pkm:Type ;
    rdfs:label "Fire" .

pkm:TypingAssignment_charizard_fire a pkm:TypingAssignment ;
    pkm:aboutVariant pkm:Variant_charizard ;
    pkm:aboutType pkm:Type_fire .
""".strip()
        + "\n",
        encoding="utf-8",
    )
