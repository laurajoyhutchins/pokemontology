"""Shared support helpers for the test suite."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pokemontology._script_loader import repo_path


REPO = repo_path()
FIXTURES = REPO / "tests" / "fixtures"
EXAMPLES = REPO / "examples"


def fixture_path(*parts: str) -> Path:
    return FIXTURES.joinpath(*parts)


def example_path(*parts: str) -> Path:
    return EXAMPLES.joinpath(*parts)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_fixture_tree(*parts: str, destination: Path) -> None:
    shutil.copytree(fixture_path(*parts), destination, dirs_exist_ok=True)
