"""Helpers for importing legacy script modules from the repository tree."""
from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if not SCRIPTS_DIR.exists():
    raise RuntimeError(f"expected scripts directory at {SCRIPTS_DIR}")

scripts_path = str(SCRIPTS_DIR)
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)
