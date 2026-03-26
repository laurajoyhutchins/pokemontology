#!/usr/bin/env python3
"""Sanity-check Turtle files with rdflib parsing."""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import Graph


def check_file(path: Path) -> tuple[bool, str]:
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
        return True, f"{path.name}: ok ({len(graph)} triples)"
    except Exception as exc:
        return False, f"{path.name}: parse failed: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path, help="TTL files to parse")
    args = parser.parse_args()

    failures = 0
    for path in args.paths:
        ok, message = check_file(path)
        print(message)
        if not ok:
            failures += 1

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
