"""Unit tests for the shared replay_parser module."""

from __future__ import annotations

import pytest

from pokemontology.replay.replay_parser import (
    ReplayEvent,
    compact_species_name,
    discover_moves,
    discover_participants,
    parse_log,
    parse_player_slot,
    parse_side_token,
    sanitize_identifier,
)


# ---------------------------------------------------------------------------
# sanitize_identifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Garchomp", "Garchomp"),
        ("Iron Hands", "Iron_Hands"),
        ("Urshifu-Rapid-Strike", "Urshifu_Rapid_Strike"),
        ("  spaces  ", "spaces"),
        ("", "Unnamed"),
        ("123start", "N_123start"),
        ("Pokémon", "Pok_mon"),
        ("A__B", "A_B"),
        ("--leading--", "leading"),
    ],
)
def test_sanitize_identifier(text: str, expected: str) -> None:
    assert sanitize_identifier(text) == expected


# ---------------------------------------------------------------------------
# compact_species_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("p1a: Garchomp, L50, M", "Garchomp"),
        ("p2b: Iron Hands, L50", "IronHands"),
        ("Urshifu-Rapid-Strike", "Urshifu_Rapid_Strike"),
        ("p1a: Indeedee♀, L50", "IndeedeeF"),
        ("p2a: Gardevoir♂, L50", "GardevoirM"),
        ("p1b: Calyrex-Ice*", "Calyrex_Ice"),
    ],
)
def test_compact_species_name(raw: str, expected: str) -> None:
    assert compact_species_name(raw) == expected


# ---------------------------------------------------------------------------
# parse_player_slot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("p1a: Garchomp", ("p1", "a")),
        ("p2b: Iron Hands", ("p2", "b")),
        ("p1b: Calyrex-Ice", ("p1", "b")),
        ("p2a: Urshifu", ("p2", "a")),
    ],
)
def test_parse_player_slot_valid(raw: str, expected: tuple[str, str]) -> None:
    assert parse_player_slot(raw) == expected


@pytest.mark.parametrize("raw", ["not-a-slot", "p3a: Pikachu", "p1: Garchomp"])
def test_parse_player_slot_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_player_slot(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("p1: Alice", "p1"),
        ("p2: Bob", "p2"),
    ],
)
def test_parse_side_token_valid(raw: str, expected: str) -> None:
    assert parse_side_token(raw) == expected


@pytest.mark.parametrize("raw", ["p1a: Garchomp", "p3: Alice", "Alice"])
def test_parse_side_token_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_side_token(raw)


# ---------------------------------------------------------------------------
# parse_log
# ---------------------------------------------------------------------------

FIXTURE_LOG = """|start
|turn|1
|switch|p1a: Garchomp|Garchomp, L50, M|175/175
|switch|p2a: Urshifu-Rapid-Strike|Urshifu-Rapid-Strike, L50|175/175
|move|p1a: Garchomp|Earthquake|p2a: Urshifu-Rapid-Strike
|turn|2
|move|p2a: Urshifu-Rapid-Strike|Surging Strikes|p1a: Garchomp
|faint|p1a: Garchomp
"""


def test_parse_log_basic() -> None:
    events = parse_log(FIXTURE_LOG)
    assert len(events) == 5
    assert events[0].kind == "switch"
    assert events[0].turn == 1
    assert events[0].order == 0
    assert events[1].kind == "switch"
    assert events[1].turn == 1
    assert events[1].order == 1
    assert events[2].kind == "move"
    assert events[2].turn == 1
    assert events[2].order == 2
    assert events[3].kind == "move"
    assert events[3].turn == 2
    assert events[3].order == 0
    assert events[4].kind == "faint"
    assert events[4].turn == 2
    assert events[4].order == 1


def test_parse_log_skips_pre_turn_lines() -> None:
    log = """|player|p1|Alice|
|player|p2|Bob|
|turn|1
|switch|p1a: Pikachu|Pikachu, L50|100/100
"""
    events = parse_log(log)
    assert all(ev.turn > 0 for ev in events)
    assert len(events) == 1


def test_parse_log_keeps_supported_state_events() -> None:
    log = """|turn|1
|weather|SunnyDay|[upkeep]
|upkeep
|drag|p2a: Mewtwo|Mewtwo, L50|100/100
|move|p1a: Charizard|Flamethrower|p2a: Mewtwo
|-damage|p2a: Mewtwo|100/200
|-sethp|p1a: Charizard|150/200|p2a: Mewtwo|120/200|[from] move: Pain Split
|-status|p2a: Mewtwo|brn
|-curestatus|p2a: Mewtwo|brn
|-boost|p1a: Charizard|spa|1
|-clearboost|p1a: Charizard
|-miss|p1a: Charizard|p2a: Mewtwo
|-fail|p2a: Mewtwo
|-supereffective|p2a: Mewtwo
|-activate|p1a: Charizard|ability: Blaze
|cant|p2a: Mewtwo|par
|-fieldstart|move: Psychic Terrain
|-fieldend|move: Psychic Terrain
|-sidestart|p1: Alice|move: Tailwind
|-sideend|p1: Alice|move: Tailwind
|replace|p2a: Zoroark|Zoroark, L50|100/100
|detailschange|p1a: Charizard|Charizard-Mega-X, L50|150/200
|-singleturn|p1a: Charizard|Protect
|-end|p1a: Charizard|move: Protect
|faint|p2a: Mewtwo
"""
    events = parse_log(log)
    kinds = [ev.kind for ev in events]
    assert kinds == [
        "upkeep",
        "drag",
        "move",
        "-damage",
        "-sethp",
        "-status",
        "-curestatus",
        "-boost",
        "-clearboost",
        "-miss",
        "-fail",
        "-supereffective",
        "-activate",
        "cant",
        "-fieldstart",
        "-fieldend",
        "-sidestart",
        "-sideend",
        "replace",
        "detailschange",
        "-singleturn",
        "-end",
        "faint",
    ]


# ---------------------------------------------------------------------------
# discover_participants
# ---------------------------------------------------------------------------


def test_discover_participants() -> None:
    events = parse_log(FIXTURE_LOG)
    parts = discover_participants(events, "Alice", "Bob")
    assert len(parts) == 2
    iris = list(parts.keys())
    assert any("Garchomp" in iri for iri in iris)
    assert any("Urshifu" in iri for iri in iris)
    for info in parts.values():
        assert "player_id" in info
        assert "trainer" in info
        assert "label" in info


# ---------------------------------------------------------------------------
# discover_moves
# ---------------------------------------------------------------------------


def test_discover_moves() -> None:
    events = parse_log(FIXTURE_LOG)
    moves = discover_moves(events)
    assert len(moves) == 2
    assert "MoveEarthquake" in moves
    assert "MoveSurging_Strikes" in moves
    assert moves["MoveEarthquake"] == "Earthquake"
    assert moves["MoveSurging_Strikes"] == "Surging Strikes"


def test_discover_moves_deduplicates_same_move() -> None:
    log = """|turn|1
|move|p1a: Garchomp|Earthquake|p2a: Urshifu
|turn|2
|move|p1a: Garchomp|Earthquake|p2a: Urshifu
"""
    events = parse_log(log)
    moves = discover_moves(events)
    assert len(moves) == 1


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------


def test_collision_detection_moves() -> None:
    """Two move names that sanitize to the same IRI must raise ValueError."""
    # "Air Slash" and "Air-Slash" both → sanitize_identifier → "Air_Slash"
    # so both map to IRI "MoveAir_Slash"
    log = """|turn|1
|move|p1a: Togekiss|Air Slash|p2a: Garchomp
|move|p2a: Garchomp|Air-Slash|p1a: Togekiss
"""
    events = parse_log(log)
    with pytest.raises(ValueError, match="IRI collision"):
        discover_moves(events)


def test_collision_detection_participants() -> None:
    """Two species names that produce the same compact IRI must raise ValueError."""
    # "Mr. Mime" and "Mr Mime" both → compact_species_name → "MrMime"
    # (dot removal and space removal commute to same result)
    # For the same trainer, this creates an IRI collision.
    ev1 = ReplayEvent(
        turn=1,
        order=0,
        kind="switch",
        fields=["p1a: Mr. Mime", "Mr. Mime, L50", "120/120"],
        raw="",
    )
    ev2 = ReplayEvent(
        turn=1,
        order=1,
        kind="switch",
        fields=["p1b: Mr Mime", "Mr Mime, L50", "120/120"],
        raw="",
    )
    with pytest.raises(ValueError, match="IRI collision"):
        discover_participants([ev1, ev2], "Alice", "Bob")
