"""Infer heads-up action order from a battle-state snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from pathlib import Path

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
        if self.item is None:
            return None
        cleaned = self.item.strip().lower()
        return cleaned or None

    @property
    def normalized_ability(self) -> str | None:
        if self.ability is None:
            return None
        cleaned = self.ability.strip().lower()
        return cleaned or None

    @property
    def normalized_status(self) -> str | None:
        if self.status is None:
            return None
        cleaned = self.status.strip().lower()
        return cleaned or None

    @property
    def normalized_move_type(self) -> str | None:
        if self.move_type is None:
            return None
        cleaned = self.move_type.strip().lower()
        return MOVE_TYPE_ALIASES.get(cleaned, cleaned or None)

    @property
    def normalized_move_category(self) -> str | None:
        if self.move_category is None:
            return None
        cleaned = self.move_category.strip().lower()
        return MOVE_CATEGORY_ALIASES.get(cleaned, cleaned or None)

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
        ability = self.normalized_ability
        if ability == "prankster" and self.normalized_move_category == "status":
            priority += MOVE_PRIORITY_ABILITIES[ability]["status"]
        if ability == "gale wings" and self.at_full_hp and self.normalized_move_type == "flying":
            priority += MOVE_PRIORITY_ABILITIES[ability]["flying"]
        if ability == "triage" and "healing" in self.normalized_move_tags:
            priority += MOVE_PRIORITY_ABILITIES[ability]["healing"]
        return priority

    def speed_multiplier(self, weather: str | None, terrain: str | None) -> Fraction:
        multiplier = SPEED_STAGE_MULTIPLIERS[self.speed_stage]
        ability = self.normalized_ability
        status = self.normalized_status
        if ability == "quick feet" and status is not None:
            multiplier *= STATUS_SPEED_ABILITIES[ability]
        elif status in STATUS_SPEED_MULTIPLIERS:
            multiplier *= STATUS_SPEED_MULTIPLIERS[status]
        if self.tailwind:
            multiplier *= 2
        item = self.normalized_item
        if item in ITEM_SPEED_MULTIPLIERS:
            multiplier *= ITEM_SPEED_MULTIPLIERS[item]
        if ability in WEATHER_SPEED_ABILITIES:
            expected_weather, weather_multiplier = WEATHER_SPEED_ABILITIES[ability]
            if weather == expected_weather:
                multiplier *= weather_multiplier
        if ability in TERRAIN_SPEED_ABILITIES:
            expected_terrain, terrain_multiplier = TERRAIN_SPEED_ABILITIES[ability]
            if terrain == expected_terrain:
                multiplier *= terrain_multiplier
        if ability in CONDITIONAL_SPEED_ABILITIES and self.unburden_active:
            multiplier *= CONDITIONAL_SPEED_ABILITIES[ability]
        if ability in ACTIVE_DEBUFF_ABILITIES and self.slow_start_active:
            multiplier *= ACTIVE_DEBUFF_ABILITIES[ability]
        return multiplier

    def effective_speed(self, weather: str | None, terrain: str | None) -> Fraction:
        return Fraction(self.speed_tier) * self.speed_multiplier(weather, terrain)


def _normalize_weather(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("weather must be a string when present")
    cleaned = value.strip().lower()
    return WEATHER_ALIASES.get(cleaned, cleaned or None)


def _normalize_terrain(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("terrain must be a string when present")
    cleaned = value.strip().lower()
    return TERRAIN_ALIASES.get(cleaned, cleaned or None)


def _normalize_move_type(value: object, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"combatant {index} move_type must be a string when present")
    cleaned = value.strip().lower()
    return MOVE_TYPE_ALIASES.get(cleaned, cleaned or None)


def _normalize_move_category(value: object, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"combatant {index} move_category must be a string when present")
    cleaned = value.strip().lower()
    return MOVE_CATEGORY_ALIASES.get(cleaned, cleaned or None)


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
        discovered: list[Path] = [path for path in DEFAULT_MECHANICS_TTL_PATHS if path.exists()]
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


def _literal_texts(graph: Graph, subject, predicate) -> list[str]:
    return [
        str(obj).strip()
        for obj in graph.objects(subject, predicate)
        if isinstance(obj, Literal) and str(obj).strip()
    ]


def _find_ruleset_iri(graph: Graph | None, ruleset: str | None):
    if graph is None or not ruleset:
        return None
    target = ruleset.strip().lower()
    for subject in graph.subjects(RDF.type, PKM.Ruleset):
        identifiers = _literal_texts(graph, subject, PKM.hasIdentifier)
        names = _literal_texts(graph, subject, PKM.hasName)
        local_name = str(subject).rsplit("#", 1)[-1].lower()
        if (
            str(subject).lower() == target
            or local_name == target
            or any(identifier.lower() == target for identifier in identifiers)
            or any(name.lower() == target for name in names)
        ):
            return subject
    return None


def _find_move_iri(graph: Graph | None, move_name: str | None):
    if graph is None or not move_name:
        return None
    target = move_name.strip().lower()
    for subject in graph.subjects(RDF.type, PKM.Move):
        names = _literal_texts(graph, subject, PKM.hasName)
        local_name = str(subject).rsplit("#", 1)[-1].lower()
        if str(subject).lower() == target or local_name == target or any(name.lower() == target for name in names):
            return subject
    return None


def _move_type_name(graph: Graph, type_iri) -> str | None:
    names = _literal_texts(graph, type_iri, PKM.hasName)
    if names:
        return names[0]
    return str(type_iri).rsplit("#", 1)[-1]


def _lookup_move_properties(graph: Graph | None, ruleset: str | None, move_name: str | None) -> dict[str, object]:
    if graph is None or not ruleset or not move_name:
        return {}
    ruleset_iri = _find_ruleset_iri(graph, ruleset)
    move_iri = _find_move_iri(graph, move_name)
    if ruleset_iri is None or move_iri is None:
        return {}

    for assignment in graph.subjects(PKM.aboutMove, move_iri):
        if (assignment, RDF.type, PKM.MovePropertyAssignment) not in graph:
            continue
        if (assignment, PKM.hasContext, ruleset_iri) not in graph:
            continue
        resolved: dict[str, object] = {}
        priority = next(graph.objects(assignment, PKM.hasPriority), None)
        if isinstance(priority, Literal):
            resolved["move_priority"] = int(priority)
        type_iri = next(graph.objects(assignment, PKM.hasMoveType), None)
        if type_iri is not None:
            resolved["move_type"] = _move_type_name(graph, type_iri)
        return resolved
    return {}


def _validate_payload(payload: dict) -> tuple[list[CombatantOrderInput], bool, str | None, str | None, str | None, tuple[Path, ...]]:
    ruleset = payload.get("ruleset")
    if ruleset is not None and not isinstance(ruleset, str):
        raise ValueError("ruleset must be a string when present")
    mechanics_ttl_paths = _normalize_mechanics_ttl_paths(payload.get("mechanics_ttl_paths"))
    mechanics_graph = _load_mechanics_graph(mechanics_ttl_paths)

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
            raise ValueError(f"combatant {index} move_name must be a string when present")
        if move_priority is not None and not isinstance(move_priority, int):
            raise ValueError(f"combatant {index} move_priority must be an integer when present")
        if speed_stage not in SPEED_STAGE_MULTIPLIERS:
            raise ValueError(f"combatant {index} speed_stage must be between -6 and 6")
        looked_up_properties = _lookup_move_properties(mechanics_graph, ruleset, move_name)
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
        move_type = _normalize_move_type(raw.get("move_type", looked_up_properties.get("move_type")), index)
        move_category = _normalize_move_category(raw.get("move_category"), index)
        move_tags = _normalize_move_tags(raw.get("move_tags"), index)
        tailwind = raw.get("tailwind", False)
        if not isinstance(tailwind, bool):
            raise ValueError(f"combatant {index} tailwind must be boolean when present")
        unburden_active = raw.get("unburden_active", False)
        if not isinstance(unburden_active, bool):
            raise ValueError(f"combatant {index} unburden_active must be boolean when present")
        slow_start_active = raw.get("slow_start_active", False)
        if not isinstance(slow_start_active, bool):
            raise ValueError(f"combatant {index} slow_start_active must be boolean when present")
        at_full_hp = raw.get("at_full_hp", False)
        if not isinstance(at_full_hp, bool):
            raise ValueError(f"combatant {index} at_full_hp must be boolean when present")
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
    return 1 if combatant.normalized_item in FORCED_LAST_ITEMS or combatant.normalized_ability in FORCED_LAST_ABILITIES else 0


def _quick_claw_probability(combatant: CombatantOrderInput, activates: bool) -> Fraction:
    has_quick_claw = combatant.normalized_item in QUICK_CLAW_ITEMS
    if not has_quick_claw:
        return Fraction(1, 1) if not activates else Fraction(0, 1)
    return Fraction(1, 5) if activates else Fraction(4, 5)


def _speed_sort_key(combatant: CombatantOrderInput, trick_room: bool, weather: str | None, terrain: str | None) -> tuple[int, Fraction]:
    effective_speed = combatant.effective_speed(weather, terrain)
    return (_forced_last_group(combatant), effective_speed if trick_room else -effective_speed)


def _speed_comparison_reason(first: CombatantOrderInput, second: CombatantOrderInput, trick_room: bool, weather: str | None, terrain: str | None) -> str:
    if _forced_last_group(first) != _forced_last_group(second):
        return "forced-last ordering"
    if first.effective_speed(weather, terrain) == second.effective_speed(weather, terrain):
        return "speed tie"
    return "lower effective speed under Trick Room" if trick_room else "higher effective speed"


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


def resolve_action_order(payload: dict) -> dict:
    combatants, trick_room, weather, terrain, ruleset, mechanics_ttl_paths = _validate_payload(payload)
    supported_items = sorted(
        {
            item
            for item in (combatants[0].normalized_item, combatants[1].normalized_item)
            if item in ITEM_SPEED_MULTIPLIERS or item in FORCED_LAST_ITEMS or item in QUICK_CLAW_ITEMS
        }
    )
    ignored_items = sorted(
        {
            item
            for item in (combatants[0].normalized_item, combatants[1].normalized_item)
            if item is not None
            and item not in ITEM_SPEED_MULTIPLIERS
            and item not in FORCED_LAST_ITEMS
            and item not in QUICK_CLAW_ITEMS
        }
    )
    supported_abilities = sorted(
        {
            ability
            for ability in (combatants[0].normalized_ability, combatants[1].normalized_ability)
            if ability in WEATHER_SPEED_ABILITIES
            or ability in TERRAIN_SPEED_ABILITIES
            or ability in STATUS_SPEED_ABILITIES
            or ability in CONDITIONAL_SPEED_ABILITIES
            or ability in ACTIVE_DEBUFF_ABILITIES
            or ability in FORCED_LAST_ABILITIES
            or ability in MOVE_PRIORITY_ABILITIES
        }
    )
    ignored_abilities = sorted(
        {
            ability
            for ability in (combatants[0].normalized_ability, combatants[1].normalized_ability)
            if ability is not None
            and ability not in WEATHER_SPEED_ABILITIES
            and ability not in TERRAIN_SPEED_ABILITIES
            and ability not in STATUS_SPEED_ABILITIES
            and ability not in CONDITIONAL_SPEED_ABILITIES
            and ability not in ACTIVE_DEBUFF_ABILITIES
            and ability not in FORCED_LAST_ABILITIES
            and ability not in MOVE_PRIORITY_ABILITIES
        }
    )
    supported_statuses = sorted(
        {
            status
            for status in (combatants[0].normalized_status, combatants[1].normalized_status)
            if status in STATUS_SPEED_MULTIPLIERS
        }
    )
    ignored_statuses = sorted(
        {
            status
            for status in (combatants[0].normalized_status, combatants[1].normalized_status)
            if status is not None and status not in STATUS_SPEED_MULTIPLIERS
        }
    )

    branches: list[dict] = []
    priority_values = {combatants[0].derived_move_priority(), combatants[1].derived_move_priority()}
    if len(priority_values) > 1:
        ordered = sorted(combatants, key=lambda combatant: -combatant.derived_move_priority())
        first, second = ordered
        branches.append(
            _branch_result(
                first,
                second,
                Fraction(1, 1),
                "higher derived move priority",
                first.derived_move_priority(),
            )
        )
    else:
        priority_bracket = combatants[0].derived_move_priority()
        for qc_states in product((False, True), repeat=2):
            probability = _quick_claw_probability(combatants[0], qc_states[0]) * _quick_claw_probability(combatants[1], qc_states[1])
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

            ordered = sorted(combatants, key=lambda combatant: _speed_sort_key(combatant, trick_room, weather, terrain))
            first, second = ordered
            random_tie = (
                _forced_last_group(first) == _forced_last_group(second)
                and first.effective_speed(weather, terrain) == second.effective_speed(weather, terrain)
            )
            if random_tie:
                split_probability = probability / 2
                branches.append(_branch_result(first, second, split_probability, _speed_comparison_reason(first, second, trick_room, weather, terrain), priority_bracket, random_tie=True))
                branches.append(_branch_result(second, first, split_probability, _speed_comparison_reason(second, first, trick_room, weather, terrain), priority_bracket, random_tie=True))
                continue

            branches.append(
                _branch_result(
                    first,
                    second,
                    probability,
                    _speed_comparison_reason(first, second, trick_room, weather, terrain),
                    priority_bracket,
                )
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
        for (first, second, priority_bracket, derived_priority, reason, random_tie), probability in sorted(
            collapsed.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1], -item[0][2], -item[0][3], item[0][4]),
        )
    ]

    return {
        "priority_bracket": max(priority_values),
        "trick_room": trick_room,
        "weather": weather,
        "terrain": terrain,
        "combatants": [
            {
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
                    "numerator": combatant.effective_speed(weather, terrain).numerator,
                    "denominator": combatant.effective_speed(weather, terrain).denominator,
                },
            }
            for combatant in combatants
        ],
        "branches": ordered_branches,
        "supported_items_seen": supported_items,
        "ignored_items": ignored_items,
        "supported_abilities_seen": supported_abilities,
        "ignored_abilities": ignored_abilities,
        "supported_statuses_seen": supported_statuses,
        "ignored_statuses": ignored_statuses,
        "supported_move_priority_abilities_seen": sorted(
            {
                ability
                for ability in (combatants[0].normalized_ability, combatants[1].normalized_ability)
                if ability in MOVE_PRIORITY_ABILITIES
            }
        ),
        "mechanics_ttl_paths_used": [str(path) for path in mechanics_ttl_paths if path.exists()],
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
