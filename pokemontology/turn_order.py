"""Infer heads-up action order from a battle-state snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF


SPEED_STAGE_MULTIPLIERS = {
    -6: Fraction(2, 8),
    -5: Fraction(2, 7),
    -4: Fraction(2, 6),
    -3: Fraction(2, 5),
    -2: Fraction(2, 4),
    -1: Fraction(2, 3),
    0: Fraction(1, 1),
    1: Fraction(3, 2),
    2: Fraction(4, 2),
    3: Fraction(5, 2),
    4: Fraction(6, 2),
    5: Fraction(7, 2),
    6: Fraction(8, 2),
}

ITEM_SPEED_MULTIPLIERS = {
    "choice scarf": Fraction(3, 2),
    "iron ball": Fraction(1, 2),
    "macho brace": Fraction(1, 2),
    "power anklet": Fraction(1, 2),
    "power band": Fraction(1, 2),
    "power belt": Fraction(1, 2),
    "power bracer": Fraction(1, 2),
    "power lens": Fraction(1, 2),
    "power weight": Fraction(1, 2),
}

FORCED_LAST_ITEMS = {"full incense", "lagging tail"}
QUICK_CLAW_ITEMS = {"quick claw"}
STATUS_SPEED_MULTIPLIERS = {"par": Fraction(1, 2), "paralysis": Fraction(1, 2)}
WEATHER_SPEED_ABILITIES = {
    "chlorophyll": ("sun", Fraction(2, 1)),
    "swift swim": ("rain", Fraction(2, 1)),
    "sand rush": ("sand", Fraction(2, 1)),
    "slush rush": ("snow", Fraction(2, 1)),
}
TERRAIN_SPEED_ABILITIES = {
    "surge surfer": ("electric", Fraction(2, 1)),
}
STATUS_SPEED_ABILITIES = {"quick feet": Fraction(3, 2)}
CONDITIONAL_SPEED_ABILITIES = {"unburden": Fraction(2, 1)}
ACTIVE_DEBUFF_ABILITIES = {"slow start": Fraction(1, 2)}
FORCED_LAST_ABILITIES = {"stall"}
WEATHER_ALIASES = {
    "harsh sunlight": "sun",
    "sun": "sun",
    "sunny": "sun",
    "rain": "rain",
    "heavy rain": "rain",
    "sand": "sand",
    "sandstorm": "sand",
    "snow": "snow",
    "hail": "snow",
}
TERRAIN_ALIASES = {
    "electric": "electric",
    "electric terrain": "electric",
}
MOVE_TYPE_ALIASES = {
    "flying": "flying",
}
MOVE_CATEGORY_ALIASES = {
    "status": "status",
    "physical": "physical",
    "special": "special",
}
MOVE_PRIORITY_ABILITIES = {
    "prankster": {"status": 1},
    "gale wings": {"flying": 1},
    "triage": {"healing": 3},
}
PKM = Namespace("https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#")
DEFAULT_MECHANICS_TTL_PATHS = (
    Path("build/veekun.ttl"),
    Path("build/pokeapi.ttl"),
)
DEFAULT_MECHANICS_SEARCH_DIRS = (
    Path("build"),
    Path("docs"),
)
IGNORED_MECHANICS_TTL_NAMES = {"ontology.ttl", "shapes.ttl"}


@dataclass(frozen=True)
class MechanicsData:
    graph: Graph
    ruleset_index: MappingProxyType[str, object]
    move_index: MappingProxyType[str, object]
    move_properties_index: MappingProxyType[tuple[object, object], dict[str, object]]


@dataclass(frozen=True)
class OrderContext:
    weather: str | None
    terrain: str | None


@dataclass(frozen=True)
class SpeedModifierRule:
    apply: Callable[[CombatantOrderInput, OrderContext], Fraction]
    item_names: frozenset[str] = field(default_factory=frozenset)
    ability_names: frozenset[str] = field(default_factory=frozenset)
    status_names: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PriorityBonusRule:
    apply: Callable[[CombatantOrderInput], int]
    ability_names: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ForcedLastRule:
    apply: Callable[[CombatantOrderInput], bool]
    item_names: frozenset[str] = field(default_factory=frozenset)
    ability_names: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CombatantOrderInput:
    side: str
    speed_tier: int
    move_name: str | None = None
    move_priority: int = 0
    speed_stage: int = 0
    item: str | None = None
    ability: str | None = None
    status: str | None = None
    move_type: str | None = None
    move_category: str | None = None
    move_tags: tuple[str, ...] = ()
    tailwind: bool = False
    unburden_active: bool = False
    slow_start_active: bool = False
    at_full_hp: bool = False

    @property
    def normalized_item(self) -> str | None:
        return _normalize_optional_string(self.item)

    @property
    def normalized_ability(self) -> str | None:
        return _normalize_optional_string(self.ability)

    @property
    def normalized_status(self) -> str | None:
        return _normalize_optional_string(self.status)

    @property
    def normalized_move_type(self) -> str | None:
        return _normalize_optional_string(self.move_type, aliases=MOVE_TYPE_ALIASES)

    @property
    def normalized_move_category(self) -> str | None:
        return _normalize_optional_string(
            self.move_category, aliases=MOVE_CATEGORY_ALIASES
        )

    @property
    def normalized_move_tags(self) -> tuple[str, ...]:
        normalized: list[str] = []
        for tag in self.move_tags:
            cleaned = tag.strip().lower()
            if cleaned:
                normalized.append(cleaned)
        return tuple(sorted(set(normalized)))

    def derived_move_priority(self) -> int:
        priority = self.move_priority
        for rule in PRIORITY_BONUS_RULES:
            priority += rule.apply(self)
        return priority

    def speed_multiplier(self, weather: str | None, terrain: str | None) -> Fraction:
        context = OrderContext(weather=weather, terrain=terrain)
        multiplier = SPEED_STAGE_MULTIPLIERS[self.speed_stage]
        for rule in SPEED_MODIFIER_RULES:
            multiplier *= rule.apply(self, context)
        return multiplier

    def effective_speed(self, weather: str | None, terrain: str | None) -> Fraction:
        return Fraction(self.speed_tier) * self.speed_multiplier(weather, terrain)


def _status_speed_rule(
    combatant: CombatantOrderInput, _context: OrderContext
) -> Fraction:
    ability = combatant.normalized_ability
    status = combatant.normalized_status
    if ability == "quick feet" and status is not None:
        return STATUS_SPEED_ABILITIES[ability]
    if status in STATUS_SPEED_MULTIPLIERS:
        return STATUS_SPEED_MULTIPLIERS[status]
    return Fraction(1, 1)


def _tailwind_speed_rule(
    combatant: CombatantOrderInput, _context: OrderContext
) -> Fraction:
    return Fraction(2, 1) if combatant.tailwind else Fraction(1, 1)


def _item_speed_rule(
    combatant: CombatantOrderInput, _context: OrderContext
) -> Fraction:
    return ITEM_SPEED_MULTIPLIERS.get(combatant.normalized_item, Fraction(1, 1))


def _weather_speed_ability_rule(
    combatant: CombatantOrderInput, context: OrderContext
) -> Fraction:
    ability = combatant.normalized_ability
    if ability not in WEATHER_SPEED_ABILITIES:
        return Fraction(1, 1)
    expected_weather, multiplier = WEATHER_SPEED_ABILITIES[ability]
    return multiplier if context.weather == expected_weather else Fraction(1, 1)


def _terrain_speed_ability_rule(
    combatant: CombatantOrderInput, context: OrderContext
) -> Fraction:
    ability = combatant.normalized_ability
    if ability not in TERRAIN_SPEED_ABILITIES:
        return Fraction(1, 1)
    expected_terrain, multiplier = TERRAIN_SPEED_ABILITIES[ability]
    return multiplier if context.terrain == expected_terrain else Fraction(1, 1)


def _conditional_speed_ability_rule(
    combatant: CombatantOrderInput, _context: OrderContext
) -> Fraction:
    ability = combatant.normalized_ability
    if ability in CONDITIONAL_SPEED_ABILITIES and combatant.unburden_active:
        return CONDITIONAL_SPEED_ABILITIES[ability]
    return Fraction(1, 1)


def _active_debuff_ability_rule(
    combatant: CombatantOrderInput, _context: OrderContext
) -> Fraction:
    ability = combatant.normalized_ability
    if ability in ACTIVE_DEBUFF_ABILITIES and combatant.slow_start_active:
        return ACTIVE_DEBUFF_ABILITIES[ability]
    return Fraction(1, 1)


def _prankster_priority_rule(combatant: CombatantOrderInput) -> int:
    if (
        combatant.normalized_ability == "prankster"
        and combatant.normalized_move_category == "status"
    ):
        return MOVE_PRIORITY_ABILITIES["prankster"]["status"]
    return 0


def _gale_wings_priority_rule(combatant: CombatantOrderInput) -> int:
    if (
        combatant.normalized_ability == "gale wings"
        and combatant.at_full_hp
        and combatant.normalized_move_type == "flying"
    ):
        return MOVE_PRIORITY_ABILITIES["gale wings"]["flying"]
    return 0


def _triage_priority_rule(combatant: CombatantOrderInput) -> int:
    if (
        combatant.normalized_ability == "triage"
        and "healing" in combatant.normalized_move_tags
    ):
        return MOVE_PRIORITY_ABILITIES["triage"]["healing"]
    return 0


def _forced_last_item_rule(combatant: CombatantOrderInput) -> bool:
    return combatant.normalized_item in FORCED_LAST_ITEMS


def _forced_last_ability_rule(combatant: CombatantOrderInput) -> bool:
    return combatant.normalized_ability in FORCED_LAST_ABILITIES


SPEED_MODIFIER_RULES = (
    SpeedModifierRule(
        apply=_status_speed_rule,
        ability_names=frozenset(STATUS_SPEED_ABILITIES),
        status_names=frozenset(STATUS_SPEED_MULTIPLIERS),
    ),
    SpeedModifierRule(apply=_tailwind_speed_rule),
    SpeedModifierRule(
        apply=_item_speed_rule,
        item_names=frozenset(ITEM_SPEED_MULTIPLIERS),
    ),
    SpeedModifierRule(
        apply=_weather_speed_ability_rule,
        ability_names=frozenset(WEATHER_SPEED_ABILITIES),
    ),
    SpeedModifierRule(
        apply=_terrain_speed_ability_rule,
        ability_names=frozenset(TERRAIN_SPEED_ABILITIES),
    ),
    SpeedModifierRule(
        apply=_conditional_speed_ability_rule,
        ability_names=frozenset(CONDITIONAL_SPEED_ABILITIES),
    ),
    SpeedModifierRule(
        apply=_active_debuff_ability_rule,
        ability_names=frozenset(ACTIVE_DEBUFF_ABILITIES),
    ),
)

PRIORITY_BONUS_RULES = (
    PriorityBonusRule(
        apply=_prankster_priority_rule,
        ability_names=frozenset({"prankster"}),
    ),
    PriorityBonusRule(
        apply=_gale_wings_priority_rule,
        ability_names=frozenset({"gale wings"}),
    ),
    PriorityBonusRule(
        apply=_triage_priority_rule,
        ability_names=frozenset({"triage"}),
    ),
)

FORCED_LAST_RULES = (
    ForcedLastRule(
        apply=_forced_last_item_rule,
        item_names=frozenset(FORCED_LAST_ITEMS),
    ),
    ForcedLastRule(
        apply=_forced_last_ability_rule,
        ability_names=frozenset(FORCED_LAST_ABILITIES),
    ),
)

SUPPORTED_ITEM_VALUES = frozenset(
    QUICK_CLAW_ITEMS
    | {
        item
        for rule in SPEED_MODIFIER_RULES + FORCED_LAST_RULES
        for item in getattr(rule, "item_names", frozenset())
    }
)
SUPPORTED_ABILITY_VALUES = frozenset(
    {
        ability
        for rule in SPEED_MODIFIER_RULES + PRIORITY_BONUS_RULES + FORCED_LAST_RULES
        for ability in getattr(rule, "ability_names", frozenset())
    }
)
SUPPORTED_STATUS_VALUES = frozenset(
    {status for rule in SPEED_MODIFIER_RULES for status in rule.status_names}
)
SUPPORTED_MOVE_PRIORITY_ABILITIES = frozenset(
    {ability for rule in PRIORITY_BONUS_RULES for ability in rule.ability_names}
)


def _normalize_optional_string(
    value: str | None, *, aliases: dict[str, str] | None = None
) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if aliases is None:
        return cleaned
    return aliases.get(cleaned, cleaned)


def _normalize_weather(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("weather must be a string when present")
    return _normalize_optional_string(value, aliases=WEATHER_ALIASES)


def _normalize_terrain(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("terrain must be a string when present")
    return _normalize_optional_string(value, aliases=TERRAIN_ALIASES)


def _normalize_move_type(value: object, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"combatant {index} move_type must be a string when present")
    return _normalize_optional_string(value, aliases=MOVE_TYPE_ALIASES)


def _normalize_move_category(value: object, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"combatant {index} move_category must be a string when present"
        )
    return _normalize_optional_string(value, aliases=MOVE_CATEGORY_ALIASES)


def _normalize_move_tags(value: object, index: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"combatant {index} move_tags must be a list when present")
    normalized: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            raise ValueError(f"combatant {index} move_tags entries must be strings")
        cleaned = tag.strip().lower()
        if cleaned:
            normalized.append(cleaned)
    return tuple(sorted(set(normalized)))


def _normalize_mechanics_ttl_paths(value: object) -> tuple[Path, ...]:
    if value is None:
        discovered: list[Path] = [
            path for path in DEFAULT_MECHANICS_TTL_PATHS if path.exists()
        ]
        for directory in DEFAULT_MECHANICS_SEARCH_DIRS:
            if not directory.exists():
                continue
            for candidate in sorted(directory.glob("*.ttl")):
                if candidate.name in IGNORED_MECHANICS_TTL_NAMES:
                    continue
                if candidate not in discovered:
                    discovered.append(candidate)
        return tuple(discovered)
    if not isinstance(value, list):
        raise ValueError("mechanics_ttl_paths must be a list when present")
    paths: list[Path] = []
    for raw_path in value:
        if not isinstance(raw_path, str):
            raise ValueError("mechanics_ttl_paths entries must be strings")
        paths.append(Path(raw_path))
    return tuple(paths)


def _load_mechanics_graph(paths: tuple[Path, ...]) -> Graph | None:
    if not paths:
        return None
    graph = Graph()
    loaded_any = False
    for path in paths:
        if not path.exists():
            continue
        graph.parse(path, format="turtle")
        loaded_any = True
    return graph if loaded_any else None


_MECHANICS_DATA_CACHE: dict[tuple[tuple[str, int, int], ...], MechanicsData | None] = {}


def _mechanics_cache_key(paths: tuple[Path, ...]) -> tuple[tuple[str, int, int], ...]:
    entries: list[tuple[str, int, int]] = []
    for path in paths:
        if not path.exists():
            continue
        stat = path.stat()
        entries.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def _index_rulesets(graph: Graph) -> MappingProxyType[str, object]:
    index: dict[str, object] = {}
    for subject in graph.subjects(RDF.type, PKM.Ruleset):
        keys = {
            str(subject).strip().lower(),
            str(subject).rsplit("#", 1)[-1].strip().lower(),
        }
        keys.update(
            identifier.lower()
            for identifier in _literal_texts(graph, subject, PKM.hasIdentifier)
        )
        keys.update(
            name.lower() for name in _literal_texts(graph, subject, PKM.hasName)
        )
        for key in keys:
            if key:
                index.setdefault(key, subject)
    return MappingProxyType(index)


def _index_moves(graph: Graph) -> MappingProxyType[str, object]:
    index: dict[str, object] = {}
    for subject in graph.subjects(RDF.type, PKM.Move):
        keys = {
            str(subject).strip().lower(),
            str(subject).rsplit("#", 1)[-1].strip().lower(),
        }
        keys.update(
            name.lower() for name in _literal_texts(graph, subject, PKM.hasName)
        )
        for key in keys:
            if key:
                index.setdefault(key, subject)
    return MappingProxyType(index)


def _index_move_properties(
    graph: Graph,
) -> MappingProxyType[tuple[object, object], dict[str, object]]:
    index: dict[tuple[object, object], dict[str, object]] = {}
    for assignment in graph.subjects(RDF.type, PKM.MovePropertyAssignment):
        move_iri = next(graph.objects(assignment, PKM.aboutMove), None)
        ruleset_iri = next(graph.objects(assignment, PKM.hasContext), None)
        if move_iri is None or ruleset_iri is None:
            continue
        resolved: dict[str, object] = {}
        priority = next(graph.objects(assignment, PKM.hasPriority), None)
        if isinstance(priority, Literal):
            resolved["move_priority"] = int(priority)
        type_iri = next(graph.objects(assignment, PKM.hasMoveType), None)
        if type_iri is not None:
            resolved["move_type"] = _move_type_name(graph, type_iri)
        index[(ruleset_iri, move_iri)] = resolved
    return MappingProxyType(index)


def _load_mechanics_data(paths: tuple[Path, ...]) -> MechanicsData | None:
    if not paths:
        return None
    cache_key = _mechanics_cache_key(paths)
    if cache_key in _MECHANICS_DATA_CACHE:
        return _MECHANICS_DATA_CACHE[cache_key]
    graph = _load_mechanics_graph(paths)
    if graph is None:
        _MECHANICS_DATA_CACHE[cache_key] = None
        return None
    data = MechanicsData(
        graph=graph,
        ruleset_index=_index_rulesets(graph),
        move_index=_index_moves(graph),
        move_properties_index=_index_move_properties(graph),
    )
    _MECHANICS_DATA_CACHE[cache_key] = data
    return data


def _literal_texts(graph: Graph, subject, predicate) -> list[str]:
    return [
        str(obj).strip()
        for obj in graph.objects(subject, predicate)
        if isinstance(obj, Literal) and str(obj).strip()
    ]


def _find_ruleset_iri(mechanics_data: MechanicsData | None, ruleset: str | None):
    if mechanics_data is None or not ruleset:
        return None
    return mechanics_data.ruleset_index.get(ruleset.strip().lower())


def _find_move_iri(mechanics_data: MechanicsData | None, move_name: str | None):
    if mechanics_data is None or not move_name:
        return None
    return mechanics_data.move_index.get(move_name.strip().lower())


def _move_type_name(graph: Graph, type_iri) -> str | None:
    names = _literal_texts(graph, type_iri, PKM.hasName)
    if names:
        return names[0]
    return str(type_iri).rsplit("#", 1)[-1]


def _lookup_move_properties(
    mechanics_data: MechanicsData | None, ruleset: str | None, move_name: str | None
) -> dict[str, object]:
    if mechanics_data is None or not ruleset or not move_name:
        return {}
    ruleset_iri = _find_ruleset_iri(mechanics_data, ruleset)
    move_iri = _find_move_iri(mechanics_data, move_name)
    if ruleset_iri is None or move_iri is None:
        return {}
    return dict(mechanics_data.move_properties_index.get((ruleset_iri, move_iri), {}))


def _validate_payload(
    payload: dict,
) -> tuple[
    list[CombatantOrderInput],
    bool,
    str | None,
    str | None,
    str | None,
    tuple[Path, ...],
]:
    ruleset = payload.get("ruleset")
    if ruleset is not None and not isinstance(ruleset, str):
        raise ValueError("ruleset must be a string when present")
    mechanics_ttl_paths = _normalize_mechanics_ttl_paths(
        payload.get("mechanics_ttl_paths")
    )
    mechanics_data = _load_mechanics_data(mechanics_ttl_paths)

    combatants_raw = payload.get("combatants")
    if not isinstance(combatants_raw, list) or len(combatants_raw) != 2:
        raise ValueError("resolve-order expects exactly two combatants")

    combatants: list[CombatantOrderInput] = []
    for index, raw in enumerate(combatants_raw, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"combatant {index} must be an object")
        side = raw.get("side")
        speed_tier = raw.get("speed_tier")
        move_name = raw.get("move_name")
        move_priority = raw.get("move_priority", 0)
        speed_stage = raw.get("speed_stage", 0)
        if not isinstance(side, str) or not side.strip():
            raise ValueError(f"combatant {index} is missing a non-empty side")
        if not isinstance(speed_tier, int):
            raise ValueError(f"combatant {index} is missing integer speed_tier")
        if move_name is not None and not isinstance(move_name, str):
            raise ValueError(
                f"combatant {index} move_name must be a string when present"
            )
        if move_priority is not None and not isinstance(move_priority, int):
            raise ValueError(
                f"combatant {index} move_priority must be an integer when present"
            )
        if speed_stage not in SPEED_STAGE_MULTIPLIERS:
            raise ValueError(f"combatant {index} speed_stage must be between -6 and 6")
        looked_up_properties = _lookup_move_properties(
            mechanics_data, ruleset, move_name
        )
        if move_priority is None:
            move_priority = int(looked_up_properties.get("move_priority", 0))
        item = raw.get("item")
        if item is not None and not isinstance(item, str):
            raise ValueError(f"combatant {index} item must be a string when present")
        ability = raw.get("ability")
        if ability is not None and not isinstance(ability, str):
            raise ValueError(f"combatant {index} ability must be a string when present")
        status = raw.get("status")
        if status is not None and not isinstance(status, str):
            raise ValueError(f"combatant {index} status must be a string when present")
        move_type = _normalize_move_type(
            raw.get("move_type", looked_up_properties.get("move_type")), index
        )
        move_category = _normalize_move_category(raw.get("move_category"), index)
        move_tags = _normalize_move_tags(raw.get("move_tags"), index)
        tailwind = raw.get("tailwind", False)
        if not isinstance(tailwind, bool):
            raise ValueError(f"combatant {index} tailwind must be boolean when present")
        unburden_active = raw.get("unburden_active", False)
        if not isinstance(unburden_active, bool):
            raise ValueError(
                f"combatant {index} unburden_active must be boolean when present"
            )
        slow_start_active = raw.get("slow_start_active", False)
        if not isinstance(slow_start_active, bool):
            raise ValueError(
                f"combatant {index} slow_start_active must be boolean when present"
            )
        at_full_hp = raw.get("at_full_hp", False)
        if not isinstance(at_full_hp, bool):
            raise ValueError(
                f"combatant {index} at_full_hp must be boolean when present"
            )
        combatants.append(
            CombatantOrderInput(
                side=side,
                speed_tier=speed_tier,
                move_name=move_name,
                move_priority=move_priority,
                speed_stage=speed_stage,
                item=item,
                ability=ability,
                status=status,
                move_type=move_type,
                move_category=move_category,
                move_tags=move_tags,
                tailwind=tailwind,
                unburden_active=unburden_active,
                slow_start_active=slow_start_active,
                at_full_hp=at_full_hp,
            )
        )

    if combatants[0].side == combatants[1].side:
        raise ValueError("combatant sides must be distinct")

    trick_room = payload.get("trick_room", False)
    if not isinstance(trick_room, bool):
        raise ValueError("trick_room must be boolean when present")
    return (
        combatants,
        trick_room,
        _normalize_weather(payload.get("weather")),
        _normalize_terrain(payload.get("terrain")),
        ruleset,
        mechanics_ttl_paths,
    )


def _forced_last_group(combatant: CombatantOrderInput) -> int:
    return 1 if any(rule.apply(combatant) for rule in FORCED_LAST_RULES) else 0


def _quick_claw_probability(
    combatant: CombatantOrderInput, activates: bool
) -> Fraction:
    has_quick_claw = combatant.normalized_item in QUICK_CLAW_ITEMS
    if not has_quick_claw:
        return Fraction(1, 1) if not activates else Fraction(0, 1)
    return Fraction(1, 5) if activates else Fraction(4, 5)


def _speed_sort_key(
    combatant: CombatantOrderInput,
    trick_room: bool,
    weather: str | None,
    terrain: str | None,
) -> tuple[int, Fraction]:
    effective_speed = combatant.effective_speed(weather, terrain)
    return (
        _forced_last_group(combatant),
        effective_speed if trick_room else -effective_speed,
    )


def _speed_comparison_reason(
    first: CombatantOrderInput,
    second: CombatantOrderInput,
    trick_room: bool,
    weather: str | None,
    terrain: str | None,
) -> str:
    if _forced_last_group(first) != _forced_last_group(second):
        return "forced-last ordering"
    if first.effective_speed(weather, terrain) == second.effective_speed(
        weather, terrain
    ):
        return "speed tie"
    return (
        "lower effective speed under Trick Room"
        if trick_room
        else "higher effective speed"
    )


def _branch_result(
    first: CombatantOrderInput,
    second: CombatantOrderInput,
    probability: Fraction,
    reason: str,
    priority_bracket: int,
    random_tie: bool = False,
) -> dict:
    branch = {
        "probability": {
            "numerator": probability.numerator,
            "denominator": probability.denominator,
        },
        "first": first.side,
        "second": second.side,
        "priority_bracket": priority_bracket,
        "derived_priority": first.derived_move_priority(),
        "reason": reason,
    }
    if random_tie:
        branch["random_tie"] = True
    return branch


def _priority_values(combatants: list[CombatantOrderInput]) -> tuple[int, int]:
    return tuple(combatant.derived_move_priority() for combatant in combatants)


def _resolve_priority_branches(
    combatants: list[CombatantOrderInput],
) -> tuple[list[dict], int] | None:
    first_priority, second_priority = _priority_values(combatants)
    if first_priority == second_priority:
        return None
    ordered = sorted(
        combatants, key=lambda combatant: -combatant.derived_move_priority()
    )
    first, second = ordered
    priority_bracket = first.derived_move_priority()
    return (
        [
            _branch_result(
                first,
                second,
                Fraction(1, 1),
                "higher derived move priority",
                priority_bracket,
            )
        ],
        priority_bracket,
    )


def _speed_ordered_combatants(
    combatants: list[CombatantOrderInput],
    trick_room: bool,
    weather: str | None,
    terrain: str | None,
) -> tuple[CombatantOrderInput, CombatantOrderInput]:
    ordered = sorted(
        combatants,
        key=lambda combatant: _speed_sort_key(combatant, trick_room, weather, terrain),
    )
    return ordered[0], ordered[1]


def _speed_tie(
    first: CombatantOrderInput,
    second: CombatantOrderInput,
    weather: str | None,
    terrain: str | None,
) -> bool:
    return _forced_last_group(first) == _forced_last_group(
        second
    ) and first.effective_speed(weather, terrain) == second.effective_speed(
        weather, terrain
    )


def _resolve_quick_claw_speed_branches(
    combatants: list[CombatantOrderInput],
    priority_bracket: int,
    trick_room: bool,
    weather: str | None,
    terrain: str | None,
) -> list[dict]:
    branches: list[dict] = []
    for qc_states in product((False, True), repeat=2):
        probability = _quick_claw_probability(
            combatants[0], qc_states[0]
        ) * _quick_claw_probability(combatants[1], qc_states[1])
        if probability == 0:
            continue
        if qc_states[0] != qc_states[1]:
            quick_index = 0 if qc_states[0] else 1
            slow_index = 1 - quick_index
            branches.append(
                _branch_result(
                    combatants[quick_index],
                    combatants[slow_index],
                    probability,
                    "Quick Claw activation",
                    priority_bracket,
                )
            )
            continue

        first, second = _speed_ordered_combatants(
            combatants, trick_room, weather, terrain
        )
        reason = _speed_comparison_reason(first, second, trick_room, weather, terrain)
        if _speed_tie(first, second, weather, terrain):
            split_probability = probability / 2
            branches.append(
                _branch_result(
                    first,
                    second,
                    split_probability,
                    reason,
                    priority_bracket,
                    random_tie=True,
                )
            )
            branches.append(
                _branch_result(
                    second,
                    first,
                    split_probability,
                    reason,
                    priority_bracket,
                    random_tie=True,
                )
            )
            continue

        branches.append(
            _branch_result(
                first,
                second,
                probability,
                reason,
                priority_bracket,
            )
        )
    return branches


def _serialize_combatant(
    combatant: CombatantOrderInput, weather: str | None, terrain: str | None
) -> dict:
    effective_speed = combatant.effective_speed(weather, terrain)
    return {
        "side": combatant.side,
        "speed_tier": combatant.speed_tier,
        "move_name": combatant.move_name,
        "move_priority": combatant.move_priority,
        "derived_move_priority": combatant.derived_move_priority(),
        "speed_stage": combatant.speed_stage,
        "tailwind": combatant.tailwind,
        "item": combatant.item,
        "ability": combatant.ability,
        "status": combatant.status,
        "move_type": combatant.move_type,
        "move_category": combatant.move_category,
        "move_tags": list(combatant.move_tags),
        "unburden_active": combatant.unburden_active,
        "slow_start_active": combatant.slow_start_active,
        "at_full_hp": combatant.at_full_hp,
        "effective_speed": {
            "numerator": effective_speed.numerator,
            "denominator": effective_speed.denominator,
        },
    }


def _sorted_membership(
    values: tuple[str | None, ...], supported: set[str]
) -> tuple[list[str], list[str]]:
    present = {value for value in values if value is not None}
    return (
        sorted(value for value in present if value in supported),
        sorted(value for value in present if value not in supported),
    )


def resolve_action_order(payload: dict) -> dict:
    combatants, trick_room, weather, terrain, ruleset, mechanics_ttl_paths = (
        _validate_payload(payload)
    )
    item_values = (combatants[0].normalized_item, combatants[1].normalized_item)
    supported_items, ignored_items = _sorted_membership(
        item_values,
        set(SUPPORTED_ITEM_VALUES),
    )
    ability_values = (
        combatants[0].normalized_ability,
        combatants[1].normalized_ability,
    )
    supported_abilities, ignored_abilities = _sorted_membership(
        ability_values, set(SUPPORTED_ABILITY_VALUES)
    )
    status_values = (combatants[0].normalized_status, combatants[1].normalized_status)
    supported_statuses, ignored_statuses = _sorted_membership(
        status_values, set(SUPPORTED_STATUS_VALUES)
    )
    supported_move_priority_abilities, _ = _sorted_membership(
        ability_values, set(SUPPORTED_MOVE_PRIORITY_ABILITIES)
    )

    priority_resolution = _resolve_priority_branches(combatants)
    if priority_resolution is not None:
        branches, priority_bracket = priority_resolution
    else:
        priority_bracket = combatants[0].derived_move_priority()
        branches = _resolve_quick_claw_speed_branches(
            combatants,
            priority_bracket,
            trick_room,
            weather,
            terrain,
        )

    collapsed: dict[tuple[str, str, int, int, str, bool], Fraction] = {}
    for branch in branches:
        key = (
            branch["first"],
            branch["second"],
            branch["priority_bracket"],
            branch["derived_priority"],
            branch["reason"],
            branch.get("random_tie", False),
        )
        probability = Fraction(
            branch["probability"]["numerator"],
            branch["probability"]["denominator"],
        )
        collapsed[key] = collapsed.get(key, Fraction(0, 1)) + probability

    ordered_branches = [
        {
            "probability": {
                "numerator": probability.numerator,
                "denominator": probability.denominator,
            },
            "first": first,
            "second": second,
            "priority_bracket": priority_bracket,
            "derived_priority": derived_priority,
            "reason": reason,
            **({"random_tie": True} if random_tie else {}),
        }
        for (
            first,
            second,
            priority_bracket,
            derived_priority,
            reason,
            random_tie,
        ), probability in sorted(
            collapsed.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1],
                -item[0][2],
                -item[0][3],
                item[0][4],
            ),
        )
    ]

    return {
        "priority_bracket": priority_bracket,
        "trick_room": trick_room,
        "weather": weather,
        "terrain": terrain,
        "combatants": [
            _serialize_combatant(combatant, weather, terrain)
            for combatant in combatants
        ],
        "branches": ordered_branches,
        "supported_items_seen": supported_items,
        "ignored_items": ignored_items,
        "supported_abilities_seen": supported_abilities,
        "ignored_abilities": ignored_abilities,
        "supported_statuses_seen": supported_statuses,
        "ignored_statuses": ignored_statuses,
        "supported_move_priority_abilities_seen": supported_move_priority_abilities,
        "mechanics_ttl_paths_used": [
            str(path) for path in mechanics_ttl_paths if path.exists()
        ],
        "ruleset": ruleset,
        "assumptions": [
            "Both actions occur in a heads-up turn.",
            "Derived move priority is compared before all speed-based ordering.",
            "Only supported speed modifiers and forced-last effects are considered.",
            "Only supported move-dependent priority abilities are derived from move metadata.",
            "Local TTL lookup currently derives base move priority and move type, not move category or healing tags.",
            "Unsupported items, abilities, and statuses are treated as neutral for ordering.",
        ],
    }


def resolve_normal_priority_order(payload: dict) -> dict:
    """Backward-compatible alias for callers expecting priority 0 by default."""
    return resolve_action_order(payload)
