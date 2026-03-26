"""Unified command-line interface for repository workflows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ._script_loader import REPO_ROOT

from scripts.build import build_ontology, check_ttl_parse
from scripts.ingest import pokeapi_ingest, veekun_ingest
from scripts.replay import parse_showdown_replay, replay_to_ttl_builder, summarize_showdown_replay


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def cmd_build(_args: argparse.Namespace) -> int:
    build_ontology.main()
    return 0


def cmd_check_ttl(args: argparse.Namespace) -> int:
    failures = 0
    for path in args.paths:
        ok, message = check_ttl_parse.check_file(path)
        print(message)
        if not ok:
            failures += 1
    return 1 if failures else 0


def cmd_parse_replay(args: argparse.Namespace) -> int:
    replay = json.loads(args.replay_json.read_text(encoding="utf-8"))
    turns = parse_showdown_replay.parse_log(replay["log"])
    output = {
        "id": replay.get("id"),
        "format": replay.get("format"),
        "players": replay.get("players", []),
        "turns": turns,
    }
    if args.pretty:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0


def cmd_summarize_replay(args: argparse.Namespace) -> int:
    payload = json.loads(args.replay_json.read_text(encoding="utf-8"))
    print(json.dumps(summarize_showdown_replay.summarize(payload), ensure_ascii=False, indent=2))
    return 0


def cmd_build_slice(args: argparse.Namespace) -> int:
    payload = json.loads(args.replay_json.read_text(encoding="utf-8"))
    ttl = replay_to_ttl_builder.build_ttl(payload)
    output_path = args.output or args.replay_json.with_name(f"{args.replay_json.stem}-slice.ttl")
    output_path.write_text(ttl, encoding="utf-8")
    print(output_path)
    return 0


def add_pokeapi_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    pokeapi_parser = subparsers.add_parser("pokeapi", help="Fetch and transform PokeAPI resources.")
    pokeapi_subparsers = pokeapi_parser.add_subparsers(dest="pokeapi_command", required=True)

    fetch_parser = pokeapi_subparsers.add_parser("fetch", help="Fetch and cache selected PokeAPI payloads.")
    fetch_parser.add_argument("seed", type=Path, help="Path to seed JSON describing which resources to ingest.")
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    fetch_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    fetch_parser.set_defaults(func=lambda args: (pokeapi_ingest.cmd_fetch(args), 0)[1])

    transform_parser = pokeapi_subparsers.add_parser("transform", help="Transform cached raw JSON into Turtle.")
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory containing cached raw JSON.",
    )
    transform_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=pokeapi_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    transform_parser.set_defaults(func=lambda args: (pokeapi_ingest.cmd_transform(args), 0)[1])

    ingest_parser = pokeapi_subparsers.add_parser("ingest", help="Fetch cached JSON and build a Turtle dataset.")
    ingest_parser.add_argument("seed", type=Path, help="Path to seed JSON describing which resources to ingest.")
    ingest_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    ingest_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=pokeapi_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    ingest_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    ingest_parser.set_defaults(func=lambda args: (pokeapi_ingest.cmd_ingest(args), 0)[1])


def add_veekun_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    veekun_parser = subparsers.add_parser("veekun", help="Transform a local normalized Veekun export into Turtle.")
    veekun_subparsers = veekun_parser.add_subparsers(dest="veekun_command", required=True)

    transform_parser = veekun_subparsers.add_parser("transform", help="Transform local Veekun CSV export into Turtle.")
    transform_parser.add_argument(
        "--source-dir",
        type=Path,
        default=veekun_ingest.DEFAULT_SOURCE_DIR,
        help="Directory containing normalized Veekun CSV export files.",
    )
    transform_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=veekun_ingest.DEFAULT_OUTPUT,
        help="Output TTL path.",
    )
    transform_parser.set_defaults(func=lambda args: (veekun_ingest.cmd_transform(args), 0)[1])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pokemontology",
        description="Unified CLI for building, validating, and transforming pokemontology data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_cmd = subparsers.add_parser("build", help="Assemble ontology and shapes artifacts.")
    build_parser_cmd.set_defaults(func=cmd_build)

    check_parser = subparsers.add_parser("check-ttl", help="Parse Turtle files with rdflib.")
    check_parser.add_argument("paths", nargs="+", type=Path, help="TTL files to parse.")
    check_parser.set_defaults(func=cmd_check_ttl)

    parse_parser = subparsers.add_parser("parse-replay", help="Parse a Showdown replay into a turn/event stream.")
    parse_parser.add_argument("replay_json", type=Path, help="Path to Showdown replay JSON.")
    parse_parser.add_argument("--pretty", action="store_true", help="Print parsed turns as indented JSON.")
    parse_parser.set_defaults(func=cmd_parse_replay)

    summarize_parser = subparsers.add_parser("summarize-replay", help="Summarize a Showdown replay JSON.")
    summarize_parser.add_argument("replay_json", type=Path, help="Path to Showdown replay JSON.")
    summarize_parser.set_defaults(func=cmd_summarize_replay)

    slice_parser = subparsers.add_parser("build-slice", help="Build a replay-backed Turtle slice.")
    slice_parser.add_argument("replay_json", type=Path, help="Path to Showdown replay JSON.")
    slice_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <replay_json stem>-slice.ttl.",
    )
    slice_parser.set_defaults(func=cmd_build_slice)

    add_pokeapi_subcommands(subparsers)
    add_veekun_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
