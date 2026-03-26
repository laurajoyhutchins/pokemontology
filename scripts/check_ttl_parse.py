#!/usr/bin/env python3
"""Compatibility wrapper for the reorganized TTL parse checker."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
repo_str = str(REPO)
if repo_str not in sys.path:
    sys.path.insert(0, repo_str)

_IMPL = importlib.import_module("scripts.build.check_ttl_parse")
check_file = _IMPL.check_file
main = _IMPL.main

if __name__ != "__main__":
    sys.modules[__name__] = _IMPL


if __name__ == "__main__":
    main()
