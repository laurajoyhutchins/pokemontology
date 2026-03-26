"""Tests for the unified pokemontology CLI."""
from __future__ import annotations

import json
from pathlib import Path

from pokemontology import cli


REPO = Path(__file__).parent.parent
REPLAY_JSON = REPO / "examples" / "replays" / "gen9vgc2025regjbo3-2414024536-ey54jc53vyjqy20sq0ww1l5nd3bq5qhpw.json"
ONTOLOGY = REPO / "build" / "ontology.ttl"


def test_parse_replay_command_outputs_json(capsys) -> None:
    exit_code = cli.main(["parse-replay", str(REPLAY_JSON), "--pretty"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["id"]
    assert output["turns"]


def test_check_ttl_command_succeeds(capsys) -> None:
    exit_code = cli.main(["check-ttl", str(ONTOLOGY)])
    assert exit_code == 0

    output = capsys.readouterr().out
    assert "ontology.ttl: ok" in output


def test_build_slice_command_writes_file(tmp_path, capsys) -> None:
    output_path = tmp_path / "slice.ttl"
    exit_code = cli.main(["build-slice", str(REPLAY_JSON), "--output", str(output_path)])
    assert exit_code == 0
    assert output_path.exists()

    printed = capsys.readouterr().out.strip()
    assert printed == str(output_path)
