"""Unit tests for io_utils helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pokemontology.io_utils import (
    display_repo_path,
    format_json_text,
    read_json_file,
    write_json_file,
)
from pokemontology._script_loader import REPO_ROOT


# ---------------------------------------------------------------------------
# display_repo_path
# ---------------------------------------------------------------------------


def test_display_repo_path_inside_repo() -> None:
    path = REPO_ROOT / "pokemontology" / "cli.py"
    result = display_repo_path(path)
    assert result == "pokemontology/cli.py"


def test_display_repo_path_outside_repo(tmp_path: Path) -> None:
    external = tmp_path / "some_file.json"
    result = display_repo_path(external)
    # Should return the absolute string, not a relative path
    assert result == str(external)


# ---------------------------------------------------------------------------
# read_json_file
# ---------------------------------------------------------------------------


def test_read_json_file_object(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('{"key": "value", "n": 42}', encoding="utf-8")
    result = read_json_file(p)
    assert result == {"key": "value", "n": 42}


def test_read_json_file_array(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text('[1, 2, 3]', encoding="utf-8")
    assert read_json_file(p) == [1, 2, 3]


# ---------------------------------------------------------------------------
# write_json_file
# ---------------------------------------------------------------------------


def test_write_json_file_default_options(tmp_path: Path) -> None:
    p = tmp_path / "out.json"
    write_json_file(p, {"b": 2, "a": 1})
    text = p.read_text(encoding="utf-8")
    # Default: sort_keys=True, indent=2, trailing_newline=True
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed == {"a": 1, "b": 2}
    assert '"a"' in text
    # Indented output has newlines within the braces
    assert "\n" in text.strip()


def test_write_json_file_no_trailing_newline(tmp_path: Path) -> None:
    p = tmp_path / "out.json"
    write_json_file(p, {"x": 1}, trailing_newline=False)
    text = p.read_text(encoding="utf-8")
    assert not text.endswith("\n")


def test_write_json_file_compact(tmp_path: Path) -> None:
    p = tmp_path / "out.json"
    write_json_file(p, {"x": 1}, indent=None)
    text = p.read_text(encoding="utf-8")
    assert "\n" not in text.rstrip("\n")


def test_write_json_file_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "deep" / "out.json"
    write_json_file(p, [1, 2, 3])
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == [1, 2, 3]


def test_write_json_file_unsorted_keys(tmp_path: Path) -> None:
    p = tmp_path / "out.json"
    write_json_file(p, {"z": 3, "a": 1}, sort_keys=False)
    text = p.read_text(encoding="utf-8")
    # Without sort_keys the insertion order is preserved; "z" comes before "a"
    assert text.index('"z"') < text.index('"a"')


# ---------------------------------------------------------------------------
# format_json_text
# ---------------------------------------------------------------------------


def test_format_json_text_compact() -> None:
    result = format_json_text({"b": 2, "a": 1}, pretty=False)
    parsed = json.loads(result)
    assert parsed == {"b": 2, "a": 1}
    assert "\n" not in result


def test_format_json_text_pretty() -> None:
    result = format_json_text({"b": 2, "a": 1}, pretty=True)
    parsed = json.loads(result)
    assert parsed == {"b": 2, "a": 1}
    assert "\n" in result


def test_format_json_text_non_ascii_preserved() -> None:
    result = format_json_text({"name": "Pokémon"}, pretty=False)
    assert "Pokémon" in result


def test_format_json_text_array() -> None:
    assert format_json_text([1, 2, 3], pretty=False) == "[1, 2, 3]"
