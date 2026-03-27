"""Tests for the unified pokemontology CLI."""

from __future__ import annotations

import json
from pathlib import Path

from pokemontology import cli
from tests.support import REPO, write_json


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
    write_json(replay_path, {"id": "missing-log"})

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


def test_query_command_defaults_to_build_sources(capsys, monkeypatch: object) -> None:
    captured: dict[str, object] = {}

    def fake_execute(query_text, *, sources, pretty=False, query_label):
        captured["query_text"] = query_text
        captured["sources"] = tuple(sources)
        captured["pretty"] = pretty
        captured["query_label"] = query_label
        return 0

    monkeypatch.setattr(cli, "_execute_query_text", fake_execute)

    query_path = REPO / "queries" / "super_effective_moves.sparql"
    exit_code = cli.main(["query", str(query_path)])

    assert exit_code == 0
    assert captured["sources"] == cli.DEFAULT_QUERY_SOURCES
    assert captured["pretty"] is False
    assert captured["query_label"] == "queries/super_effective_moves.sparql"


def test_laurel_command_defaults_to_build_sources(monkeypatch: object, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_generate_sparql(*_args, **_kwargs):
        return "SELECT * WHERE { ?s ?p ?o } LIMIT 1"

    def fake_run_query_text(query_text, *, sources, query_label):
        captured["query_text"] = query_text
        captured["sources"] = tuple(sources)
        captured["query_label"] = query_label
        return {"variables": ["answer"], "rows": [{"answer": "ok"}]}

    monkeypatch.setattr(cli, "generate_sparql", fake_generate_sparql)
    monkeypatch.setattr(cli, "_run_query_text", fake_run_query_text)

    exit_code = cli.main(["laurel", "Is Charizard Fire type?"])

    assert exit_code == 0
    assert captured["sources"] == cli.DEFAULT_QUERY_SOURCES
    assert captured["query_label"] == "<generated>"


def test_resolve_order_command_outputs_json(tmp_path, capsys) -> None:
    state_path = tmp_path / "order-state.json"
    write_json(
        state_path,
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
        },
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
    write_json(
        state_path,
        {
            "combatants": [
                {"side": "p1", "speed_tier": 120},
                {"side": "p2", "speed_tier": 150},
            ]
        },
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


def test_serve_docs_command_uses_localhost_and_docs_dir(capsys, monkeypatch: object) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, address, handler_factory) -> None:
            captured["address"] = address
            captured["handler_factory"] = handler_factory
            self.server_address = address
            self.served = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def serve_forever(self) -> None:
            self.served = True
            captured["served"] = True

    monkeypatch.setattr(cli, "ThreadingHTTPServer", FakeServer)

    exit_code = cli.main(["serve-docs"])

    assert exit_code == 0
    assert captured["address"] == ("localhost", 8000)
    assert captured["served"] is True

    handler = captured["handler_factory"]
    assert getattr(handler, "keywords", {})["directory"] == str(REPO / "docs")

    output = capsys.readouterr().out.strip()
    assert output == "Serving docs at http://localhost:8000/"


def test_serve_docs_command_accepts_custom_bindings(
    tmp_path: Path, monkeypatch: object
) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, address, handler_factory) -> None:
            captured["address"] = address
            captured["handler_factory"] = handler_factory
            self.server_address = address

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def serve_forever(self) -> None:
            return None

    docs_dir = tmp_path / "site"
    docs_dir.mkdir()

    monkeypatch.setattr(cli, "ThreadingHTTPServer", FakeServer)

    exit_code = cli.main(
        [
            "serve-docs",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "--docs-dir",
            str(docs_dir),
        ]
    )

    assert exit_code == 0
    assert captured["address"] == ("127.0.0.1", 8080)
    handler = captured["handler_factory"]
    assert getattr(handler, "keywords", {})["directory"] == str(docs_dir)


def test_replay_curate_command_writes_curated_file(tmp_path, capsys) -> None:
    index_dir = tmp_path / "index" / "gen9vgc2025reggbo3" / "all"
    index_dir.mkdir(parents=True)
    write_json(
        index_dir / "page_1.json",
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
        ],
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
