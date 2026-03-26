"""Repository path helpers for the CLI package."""

from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)
