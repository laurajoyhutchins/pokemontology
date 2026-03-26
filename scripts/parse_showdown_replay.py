#!/usr/bin/env python3
"""Compatibility wrapper for the reorganized replay parser."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
repo_str = str(REPO)
if repo_str not in sys.path:
    sys.path.insert(0, repo_str)

_IMPL = importlib.import_module("scripts.replay.parse_showdown_replay")
main = _IMPL.main
parse_log = _IMPL.parse_log

if __name__ != "__main__":
    sys.modules[__name__] = _IMPL


if __name__ == "__main__":
    main()
