"""Shared support helpers for Laurel CLI and evaluation tests."""

from __future__ import annotations

from pathlib import Path

from tests.support import write_json


def write_super_effective_fixture(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> a pkm:Ruleset .

pkm:MyCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Charmander" .

pkm:OpponentCombatant
    a pkm:BattleParticipant ;
    pkm:hasCombatantLabel "Bulbasaur" ;
    pkm:representsSpecies pkm:Species_bulbasaur .

pkm:Action_Ember
    a pkm:MoveUseAction ;
    pkm:actor pkm:MyCombatant ;
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
    pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
    pkm:hasMoveType pkm:Type_fire .

pkm:TypingAssignment_bulbasaur_grass
    a pkm:TypingAssignment ;
    pkm:aboutPokemon pkm:Species_bulbasaur ;
    pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
    pkm:aboutType pkm:Type_grass .

pkm:TypeEffectivenessAssignment_fire_grass
    a pkm:TypeEffectivenessAssignment ;
    pkm:attackerType pkm:Type_fire ;
    pkm:defenderType pkm:Type_grass ;
    pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
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
    write_json(
        path,
        {
            "vocabulary": vocabulary,
            "vectors": [vector],
            "items": [item],
        },
    )


def write_eval_suite(path: Path, *, tier: str, item: dict[str, object]) -> None:
    write_eval_suite_payload(
        path,
        tiers=[{"tier": tier, "items": [item]}],
        adversarial=[],
    )


def write_eval_suite_payload(
    path: Path,
    *,
    tiers: list[dict[str, object]],
    adversarial: list[dict[str, object]],
) -> None:
    write_json(
        path,
        {
            "suite_name": "Test Laurel Suite",
            "version": "test",
            "scope": "Test scope",
            "notes": ["Test suite payload."],
            "tiers": tiers,
            "adversarial": adversarial,
        },
    )


def write_charizard_fire_source(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
pkm:Species_charizard a pkm:Species ;
    pkm:hasName "Charizard" .

pkm:Type_fire a pkm:Type ;
    pkm:hasName "Fire" .

pkm:TypingAssignment_charizard_fire a pkm:TypingAssignment ;
    pkm:aboutPokemon pkm:Species_charizard ;
    pkm:aboutType pkm:Type_fire .
""".strip()
        + "\n",
        encoding="utf-8",
    )
