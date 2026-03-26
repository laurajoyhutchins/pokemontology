"""Small shared IO helpers used across CLI-oriented modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._script_loader import REPO_ROOT


def display_repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(
    path: Path,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    trailing_newline: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def format_json_text(payload: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False)
