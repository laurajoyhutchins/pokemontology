"""Tests for the unified pokemontology CLI."""

from __future__ import annotations

import json

from pokemontology import cli
from pokemontology._script_loader import repo_path


REPO = repo_path()
REPLAY_JSON = (
    REPO
    / "examples"
    / "replays"
    / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
)


def test_parse_replay_command_outputs_json(capsys) -> None:
    exit_code = cli.main(["parse-replay", str(REPLAY_JSON), "--pretty"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["id"]
    assert output["turns"]


def test_parse_replay_command_reports_invalid_json(tmp_path, capsys) -> None:
    replay_path = tmp_path / "bad.json"
    replay_path.write_text("{not valid json", encoding="utf-8")

    try:
        cli.main(["parse-replay", str(replay_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parse-replay to exit with a usage error")

    error = capsys.readouterr().err
    assert "invalid JSON" in error
    assert "line 1, column 2" in error


def test_parse_replay_command_requires_top_level_object(tmp_path, capsys) -> None:
    replay_path = tmp_path / "replay.json"
    replay_path.write_text('["not", "an", "object"]', encoding="utf-8")

    try:
        cli.main(["parse-replay", str(replay_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parse-replay to exit with a usage error")

    error = capsys.readouterr().err
    assert "top-level JSON object" in error


def test_parse_replay_command_requires_log_field(tmp_path, capsys) -> None:
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps({"id": "missing-log"}), encoding="utf-8")

    try:
        cli.main(["parse-replay", str(replay_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parse-replay to exit with a usage error")

    error = capsys.readouterr().err
    assert "string 'log' field" in error


def test_check_ttl_command_succeeds(built_ontology_path: str, capsys) -> None:
    exit_code = cli.main(["check-ttl", built_ontology_path])
    assert exit_code == 0

    output = capsys.readouterr().out
    assert "ontology.ttl: ok" in output


def test_build_slice_command_writes_file(tmp_path, capsys) -> None:
    output_path = tmp_path / "slice.ttl"
    exit_code = cli.main(
        ["build-slice", str(REPLAY_JSON), "--output", str(output_path)]
    )
    assert exit_code == 0
    assert output_path.exists()

    printed = capsys.readouterr().out.strip()
    assert printed == str(output_path)


def test_resolve_order_command_outputs_json(tmp_path, capsys) -> None:
    state_path = tmp_path / "order-state.json"
    state_path.write_text(
        json.dumps(
            {
                "combatants": [
                    {
                        "side": "p1",
                        "speed_tier": 120,
                        "speed_stage": 1,
                        "item": "Choice Scarf",
                    },
                    {"side": "p2", "speed_tier": 150},
                ]
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["resolve-order", str(state_path), "--pretty"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["branches"][0]["first"] == "p1"
    assert output["priority_bracket"] == 0


def test_resolve_order_command_skips_mechanics_graph_when_not_needed(
    tmp_path, capsys, monkeypatch: object
) -> None:
    state_path = tmp_path / "order-state.json"
    state_path.write_text(
        json.dumps(
            {
                "combatants": [
                    {"side": "p1", "speed_tier": 120},
                    {"side": "p2", "speed_tier": 150},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fail_normalize(_value):
        raise AssertionError("mechanics TTL discovery should not run for basic speed ordering")

    monkeypatch.setattr("pokemontology.turn_order._normalize_mechanics_ttl_paths", fail_normalize)

    exit_code = cli.main(["resolve-order", str(state_path), "--pretty"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["branches"][0]["first"] == "p2"


def test_resolve_order_command_requires_top_level_object(tmp_path, capsys) -> None:
    state_path = tmp_path / "order-state.json"
    state_path.write_text('["bad"]', encoding="utf-8")

    try:
        cli.main(["resolve-order", str(state_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected resolve-order to exit with a usage error")

    error = capsys.readouterr().err
    assert "turn-order state JSON must contain a top-level JSON object" in error


def test_replay_curate_command_writes_curated_file(tmp_path, capsys) -> None:
    index_dir = tmp_path / "index" / "gen9vgc2025reggbo3" / "all"
    index_dir.mkdir(parents=True)
    (index_dir / "page_1.json").write_text(
        json.dumps(
            [
                {
                    "id": "battle-1",
                    "format": "gen9vgc2025reggbo3",
                    "players": ["Alice", "Bob"],
                    "rating": 1700,
                },
                {
                    "id": "battle-2",
                    "format": "gen9vgc2025reggbo3",
                    "players": ["Solo"],
                    "rating": 1800,
                },
            ]
        ),
        encoding="utf-8",
    )
    curated = tmp_path / "curated.json"

    exit_code = cli.main(
        [
            "replay",
            "curate",
            "--index-dir",
            str(tmp_path / "index"),
            "--output",
            str(curated),
            "--format",
            "gen9vgc2025reggbo3",
            "--min-rating",
            "1600",
        ]
    )
    assert exit_code == 0
    payload = json.loads(curated.read_text(encoding="utf-8"))
    assert payload["replay_ids"] == ["battle-1"]
    output = json.loads(capsys.readouterr().out)
    assert output["replay_count"] == 1
