"""Tests for normal-priority action order inference."""

from __future__ import annotations

from pathlib import Path

from pokemontology.turn_order import resolve_normal_priority_order


def write_mechanics_ttl(path: Path) -> None:
    path.write_text(
        """
@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

pkm:Ruleset_Test a pkm:Ruleset ;
    pkm:hasIdentifier "test:ruleset" ;
    pkm:hasName "Test Ruleset" .

pkm:Type_Flying a pkm:Type ;
    pkm:hasName "Flying" .

pkm:Type_Normal a pkm:Type ;
    pkm:hasName "Normal" .

pkm:Move_Protect a pkm:Move ;
    pkm:hasName "Protect" .

pkm:Move_Brave_Bird a pkm:Move ;
    pkm:hasName "Brave Bird" .

pkm:MovePropertyAssignment_Protect a pkm:MovePropertyAssignment ;
    pkm:aboutMove pkm:Move_Protect ;
    pkm:hasContext pkm:Ruleset_Test ;
    pkm:hasMoveType pkm:Type_Normal ;
    pkm:hasPriority "4"^^xsd:integer .

pkm:MovePropertyAssignment_Brave_Bird a pkm:MovePropertyAssignment ;
    pkm:aboutMove pkm:Move_Brave_Bird ;
    pkm:hasContext pkm:Ruleset_Test ;
    pkm:hasMoveType pkm:Type_Flying ;
    pkm:hasPriority "0"^^xsd:integer .
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_resolve_order_prefers_higher_effective_speed() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 120,
                    "speed_stage": 1,
                    "item": "Choice Scarf",
                },
                {"side": "p2", "speed_tier": 150, "speed_stage": 0},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        }
    ]


def test_resolve_order_inverts_speed_under_trick_room() -> None:
    resolved = resolve_normal_priority_order(
        {
            "trick_room": True,
            "combatants": [
                {"side": "p1", "speed_tier": 120},
                {"side": "p2", "speed_tier": 80, "tailwind": True},
            ],
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "lower effective speed under Trick Room",
        }
    ]


def test_resolve_order_applies_forced_last_items_before_speed() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 50, "item": "Lagging Tail"},
                {"side": "p2", "speed_tier": 10},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p2",
            "second": "p1",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "forced-last ordering",
        }
    ]


def test_resolve_order_emits_quick_claw_branches() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 90, "item": "Quick Claw"},
                {"side": "p2", "speed_tier": 100},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 4, "denominator": 5},
            "first": "p2",
            "second": "p1",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        },
        {
            "probability": {"numerator": 1, "denominator": 5},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "Quick Claw activation",
        },
    ]


def test_resolve_order_splits_speed_ties_into_random_branches() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 100},
                {"side": "p2", "speed_tier": 100},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 2},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "speed tie",
            "random_tie": True,
        },
        {
            "probability": {"numerator": 1, "denominator": 2},
            "first": "p2",
            "second": "p1",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "speed tie",
            "random_tie": True,
        },
    ]


def test_resolve_order_applies_paralysis_speed_drop() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 120, "status": "par"},
                {"side": "p2", "speed_tier": 70},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p2",
            "second": "p1",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        }
    ]


def test_resolve_order_quick_feet_overrides_paralysis_drop() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 70,
                    "ability": "Quick Feet",
                    "status": "par",
                },
                {"side": "p2", "speed_tier": 100},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        }
    ]


def test_resolve_order_applies_weather_speed_ability() -> None:
    resolved = resolve_normal_priority_order(
        {
            "weather": "rain",
            "combatants": [
                {"side": "p1", "speed_tier": 80, "ability": "Swift Swim"},
                {"side": "p2", "speed_tier": 120},
            ],
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        }
    ]


def test_resolve_order_applies_unburden_when_active() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 90,
                    "ability": "Unburden",
                    "unburden_active": True,
                },
                {"side": "p2", "speed_tier": 150},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "higher effective speed",
        }
    ]


def test_resolve_order_applies_slow_start_and_stall() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 200,
                    "ability": "Slow Start",
                    "slow_start_active": True,
                },
                {"side": "p2", "speed_tier": 20, "ability": "Stall"},
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 0,
            "derived_priority": 0,
            "reason": "forced-last ordering",
        }
    ]


def test_resolve_order_prefers_higher_move_priority_before_speed() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 10, "move_priority": 1},
                {"side": "p2", "speed_tier": 999, "move_priority": 0},
            ]
        }
    )

    assert resolved["priority_bracket"] == 1
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 1,
            "derived_priority": 1,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_ignores_quick_claw_when_priorities_differ() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {"side": "p1", "speed_tier": 10, "move_priority": 1},
                {
                    "side": "p2",
                    "speed_tier": 999,
                    "move_priority": 0,
                    "item": "Quick Claw",
                },
            ]
        }
    )

    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 1,
            "derived_priority": 1,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_derives_prankster_priority_from_status_move() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 10,
                    "ability": "Prankster",
                    "move_category": "status",
                },
                {"side": "p2", "speed_tier": 999},
            ]
        }
    )

    assert resolved["priority_bracket"] == 1
    assert resolved["combatants"][0]["derived_move_priority"] == 1
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 1,
            "derived_priority": 1,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_derives_gale_wings_only_at_full_hp() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 10,
                    "ability": "Gale Wings",
                    "move_type": "Flying",
                    "at_full_hp": True,
                },
                {"side": "p2", "speed_tier": 999},
            ]
        }
    )

    assert resolved["priority_bracket"] == 1
    assert resolved["combatants"][0]["derived_move_priority"] == 1
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 1,
            "derived_priority": 1,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_derives_triage_priority_from_healing_tag() -> None:
    resolved = resolve_normal_priority_order(
        {
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 10,
                    "ability": "Triage",
                    "move_tags": ["healing"],
                },
                {"side": "p2", "speed_tier": 999, "move_priority": 2},
            ]
        }
    )

    assert resolved["priority_bracket"] == 3
    assert resolved["combatants"][0]["derived_move_priority"] == 3
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 3,
            "derived_priority": 3,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_looks_up_move_priority_from_local_ttl(tmp_path: Path) -> None:
    mechanics_path = tmp_path / "mechanics.ttl"
    write_mechanics_ttl(mechanics_path)

    resolved = resolve_normal_priority_order(
        {
            "ruleset": "test:ruleset",
            "mechanics_ttl_paths": [str(mechanics_path)],
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 1,
                    "move_name": "Protect",
                    "move_priority": None,
                },
                {"side": "p2", "speed_tier": 999},
            ],
        }
    )

    assert resolved["priority_bracket"] == 4
    assert resolved["combatants"][0]["move_priority"] == 4
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 4,
            "derived_priority": 4,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_looks_up_move_type_for_gale_wings(tmp_path: Path) -> None:
    mechanics_path = tmp_path / "mechanics.ttl"
    write_mechanics_ttl(mechanics_path)

    resolved = resolve_normal_priority_order(
        {
            "ruleset": "test:ruleset",
            "mechanics_ttl_paths": [str(mechanics_path)],
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 1,
                    "move_name": "Brave Bird",
                    "move_priority": None,
                    "ability": "Gale Wings",
                    "at_full_hp": True,
                },
                {"side": "p2", "speed_tier": 999},
            ],
        }
    )

    assert resolved["priority_bracket"] == 1
    assert resolved["combatants"][0]["move_type"] == "flying"
    assert resolved["combatants"][0]["derived_move_priority"] == 1
    assert resolved["branches"] == [
        {
            "probability": {"numerator": 1, "denominator": 1},
            "first": "p1",
            "second": "p2",
            "priority_bracket": 1,
            "derived_priority": 1,
            "reason": "higher derived move priority",
        }
    ]


def test_resolve_order_auto_discovers_local_mechanics_ttl(
    tmp_path: Path, monkeypatch
) -> None:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    write_mechanics_ttl(build_dir / "mechanics.ttl")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_normal_priority_order(
        {
            "ruleset": "test:ruleset",
            "combatants": [
                {
                    "side": "p1",
                    "speed_tier": 1,
                    "move_name": "Protect",
                    "move_priority": None,
                },
                {"side": "p2", "speed_tier": 999},
            ],
        }
    )

    assert resolved["priority_bracket"] == 4
    assert resolved["mechanics_ttl_paths_used"] == ["build/mechanics.ttl"]
    assert resolved["combatants"][0]["move_priority"] == 4
