"""Unit tests for the simple parse_showdown_replay.parse_log function."""

from __future__ import annotations

import pytest

from pokemontology.replay.parse_showdown_replay import parse_log


def test_parse_log_empty_string() -> None:
    assert parse_log("") == []


def test_parse_log_blank_lines_ignored() -> None:
    assert parse_log("\n\n\n") == []


def test_parse_log_non_pipe_lines_become_raw_text() -> None:
    log = "Player 1: gg\n|turn|1\n|move|p1a: Pikachu|Thunderbolt|p2a: Squirtle"
    turns = parse_log(log)
    assert len(turns) == 2

    pre_turn = turns[0]
    assert pre_turn["turn"] == 0
    assert pre_turn["events"][0]["type"] == "raw_text"
    assert pre_turn["events"][0]["text"] == "Player 1: gg"


def test_parse_log_single_turn_move_event() -> None:
    log = "|turn|1\n|move|p1a: Pikachu|Thunderbolt|p2a: Squirtle"
    turns = parse_log(log)
    assert len(turns) == 1
    assert turns[0]["turn"] == 1
    assert len(turns[0]["events"]) == 1
    event = turns[0]["events"][0]
    assert event["type"] == "move"
    assert event["fields"][0] == "p1a: Pikachu"
    assert event["fields"][1] == "Thunderbolt"
    assert event["fields"][2] == "p2a: Squirtle"


def test_parse_log_multiple_turns() -> None:
    log = (
        "|turn|1\n"
        "|switch|p1a: Garchomp|Garchomp, L50, M|175/175\n"
        "|turn|2\n"
        "|move|p1a: Garchomp|Earthquake|p2a: Urshifu\n"
        "|faint|p2a: Urshifu\n"
    )
    turns = parse_log(log)
    assert len(turns) == 2
    assert turns[0]["turn"] == 1
    assert len(turns[0]["events"]) == 1
    assert turns[0]["events"][0]["type"] == "switch"
    assert turns[1]["turn"] == 2
    assert len(turns[1]["events"]) == 2


def test_parse_log_events_after_last_turn_captured() -> None:
    log = "|turn|1\n|move|p1a: Pikachu|Thunderbolt|p2a: Squirtle\n|win|Alice"
    turns = parse_log(log)
    assert len(turns) == 1
    types = [ev["type"] for ev in turns[0]["events"]]
    assert "move" in types
    assert "win" in types


def test_parse_log_pre_turn_events_grouped_as_turn_zero() -> None:
    log = "|player|p1|Alice|\n|player|p2|Bob|\n|turn|1\n|move|p1a: A|Tackle|p2a: B"
    turns = parse_log(log)
    # Pre-turn events get collected into turn 0 and flushed when |turn|1 is seen
    assert turns[0]["turn"] == 0
    assert any(ev["type"] == "player" for ev in turns[0]["events"])


def test_parse_log_empty_turn_still_emitted() -> None:
    # A |turn| marker immediately followed by another |turn| with no events in between.
    # Because current_turn (1) != 0 when |turn|2 is seen, turn 1 is emitted with empty events.
    log = "|turn|1\n|turn|2\n|move|p1a: A|Tackle|p2a: B"
    turns = parse_log(log)
    turn_numbers = [t["turn"] for t in turns]
    assert 1 in turn_numbers
    assert 2 in turn_numbers
    turn_1 = next(t for t in turns if t["turn"] == 1)
    assert turn_1["events"] == []


def test_parse_log_event_fields_split_correctly() -> None:
    log = "|turn|1\n|-damage|p2a: Bulbasaur|100/175"
    turns = parse_log(log)
    event = turns[0]["events"][0]
    assert event["type"] == "-damage"
    assert event["fields"] == ["p2a: Bulbasaur", "100/175"]
