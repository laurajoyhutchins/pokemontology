# Pokemontology SPARQL Reference

Generated from the ontology schema pack and bundled query metadata.
Rebuild with `python3 -m pokemontology build`.

## Prefixes

| Prefix | IRI |
| --- | --- |
| `pkm:` | `https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#` |
| `pkmi:` | `https://laurajoyhutchins.github.io/pokemontology/id/` |
| `pkmb:` | `https://laurajoyhutchins.github.io/pokemontology/battle/` |
| `rdf:` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#` |
| `rdfs:` | `http://www.w3.org/2000/01/rdf-schema#` |
| `owl:` | `http://www.w3.org/2002/07/owl#` |
| `xsd:` | `http://www.w3.org/2001/XMLSchema#` |
| `sh:` | `http://www.w3.org/ns/shacl#` |

## Common Patterns

These are the recurring graph shapes the codebase expects queries to use.

### TypingAssignment pattern

Variant typing is modeled as a contextual fact.

```sparql
TypingAssignment aboutPokemon ?pokemon ; hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ; aboutType ?type .
```

### Type effectiveness pattern

Damage multipliers come from TypeEffectivenessAssignment nodes.

```sparql
TypeEffectivenessAssignment attackerType ?moveType ; defenderType ?effectiveType ; hasDamageFactor ?factor .
```

## Canonical Query Examples

These examples are bundled into the schema pack and frontend query picker.

### super effective moves

Bundled query that links replay combatants, move typing, and type chart effectiveness.

```sparql
# Super-effective move query
# Requires: build/ontology.ttl + build/mechanics.ttl + a replay slice TTL
# Returns: move name, move type, opponent, effective defender type, multiplier
#
# For terastallized opponents, uses the Tera type as the sole defending type.
# For non-terastallized opponents, uses all base species types (dual-type compounding
# must be handled outside SPARQL or via repeated type joins).

PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

SELECT ?myMoveLabel ?moveTypeName ?opponentLabel ?effectiveTypeName ?factor
WHERE {
  # Moves used by my side in the replay
  ?action a pkm:MoveUseAction ;
          pkm:actor ?myPokemon ;
          pkm:usesMove ?moveEntity .
  ?moveEntity pkm:hasName ?myMoveLabel .

  # Move type from PokeAPI data
  ?mpa a pkm:MovePropertyAssignment ;
       pkm:aboutMove ?moveEntity ;
       pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
       pkm:hasMoveType ?moveType .
  ?moveType pkm:hasName ?moveTypeName .

  # Opponent's revealed Pokémon
  ?opponent a pkm:BattleParticipant ;
            pkm:hasCombatantLabel ?opponentLabel .
  FILTER(?myPokemon != ?opponent)

  # Effective typing: tera overrides base
  {
    # Terastallized: single tera type
    ?cta a pkm:CurrentTransformationAssignment ;
         pkm:aboutCombatant ?opponent ;
         pkm:hasTransformationState ?ts .
    ?ts pkm:hasTeraType ?effectiveType .
  }
  UNION
  {
    # Not terastallized: base species types
    FILTER NOT EXISTS {
      ?anyCta a pkm:CurrentTransformationAssignment ;
              pkm:aboutCombatant ?opponent ;
              pkm:hasTransformationState/pkm:hasTeraType [] .
    }
    ?opponent pkm:representsSpecies ?species .
    ?ta a pkm:TypingAssignment ;
        pkm:aboutPokemon ?species ;
        pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
        pkm:aboutType ?effectiveType .
  }
  ?effectiveType pkm:hasName ?effectiveTypeName .

  # Type chart — super effective only
  ?tea a pkm:TypeEffectivenessAssignment ;
       pkm:attackerType ?moveType ;
       pkm:defenderType ?effectiveType ;
       pkm:hasContext <https://laurajoyhutchins.github.io/pokemontology/id/ruleset/pokeapi-default> ;
       pkm:hasDamageFactor ?factor .
  FILTER(?factor > 1.0)
}
ORDER BY DESC(?factor) ?opponentLabel ?myMoveLabel
```

### type ask query

ASK pattern for a species with a direct typing assignment matching Fire.

```sparql
PREFIX pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#>

ASK {
  ?species pkm:hasName "Charizard" .
  ?assignment a pkm:TypingAssignment ;
              pkm:aboutPokemon ?species ;
              pkm:aboutType ?type .
  ?type pkm:hasName "Fire" .
}
```

## Bundled Query Files

| Query | Summary | Command |
| --- | --- | --- |
| `queries/bundled/super_effective_moves.sparql` | Super-effective move query | `python3 -m pokemontology query queries/bundled/super_effective_moves.sparql build/ontology.ttl build/mechanics.ttl <data.ttl>` |

## Frequently Used Terms

Selected ontology terms that appear in the bundled patterns and validator grounding:

`pkm:Ability`, `pkm:AbilityAssignment`, `pkm:Action`, `pkm:ActiveSlotAssignment`, `pkm:Battle`, `pkm:BattleAction`, `pkm:BattleCombatant`, `pkm:BattleParticipant`, `pkm:BattleSide`, `pkm:CombatantState`, `pkm:Context`, `pkm:ContextualFact`, `pkm:CurrentAbilityAssignment`, `pkm:CurrentHPAssignment`, `pkm:CurrentItemAssignment`, `pkm:CurrentPPAssignment`, `pkm:CurrentStatusAssignment`, `pkm:CurrentTerrainAssignment`, `pkm:CurrentTransformationAssignment`, `pkm:CurrentWeatherAssignment`, `pkm:DamageEvent`, `pkm:DatasetArtifact_PokeAPI`, `pkm:DatasetArtifact_PokemonKG`, `pkm:DatasetArtifact_Veekun`, `pkm:DexRecord`, `pkm:EVAssignment`, `pkm:Entity`, `pkm:Event`, `pkm:EvidenceArtifact`, `pkm:ExternalEntityReference`, `pkm:FaintEvent`, `pkm:FieldEffect`, `pkm:FieldState`, `pkm:FieldStateAssignment`, `pkm:HealingEvent`, `pkm:IVAssignment`, `pkm:Instant`, `pkm:InventoryEntry`, `pkm:Item`, `pkm:ItemPropertyAssignment`

