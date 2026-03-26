#!/usr/bin/env python3
"""Compatibility wrapper for the reorganized PokeAPI scraper."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
repo_str = str(REPO)
if repo_str not in sys.path:
    sys.path.insert(0, repo_str)

_IMPL = importlib.import_module("scripts.ingest.pokeapi_scrape")

if __name__ == "__main__":
    _IMPL.main()
else:
    sys.modules[__name__] = _IMPL
