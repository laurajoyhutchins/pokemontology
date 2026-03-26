"""Unified command-line interface for repository workflows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Sequence

from ._script_loader import REPO_ROOT
from .turn_order import resolve_action_order

from scripts.build import build_ontology, check_ttl_parse
from scripts.ingest import pokeapi_ingest, veekun_ingest
from scripts.replay import (
    parse_showdown_replay,
    replay_dataset,
    replay_to_ttl_builder,
    summarize_showdown_replay,
)


class CliUsageError(ValueError):
    """Raised when CLI input is syntactically valid but unusable."""


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliUsageError(
            f"failed to read JSON file {_repo_relative(path)}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CliUsageError(
            f"invalid JSON in {_repo_relative(path)} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise CliUsageError(f"{label} must contain a top-level JSON object")
    return payload


def _print_json(payload: object, *, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False))


def _return_zero(
    callback: Callable[[argparse.Namespace], object],
) -> Callable[[argparse.Namespace], int]:
    def runner(args: argparse.Namespace) -> int:
        callback(args)
        return 0

    return runner


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
    replay = _load_json_object(args.replay_json, label="replay JSON")
    log = replay.get("log")
    if not isinstance(log, str):
        raise CliUsageError("replay JSON must contain a string 'log' field")
    turns = parse_showdown_replay.parse_log(replay["log"])
    output = {
        "id": replay.get("id"),
        "format": replay.get("format"),
        "players": replay.get("players", []),
        "turns": turns,
    }
    _print_json(output, pretty=args.pretty)
    return 0


def cmd_summarize_replay(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.replay_json, label="replay JSON")
    _print_json(summarize_showdown_replay.summarize(payload), pretty=True)
    return 0


def cmd_build_slice(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.replay_json, label="replay JSON")
    ttl = replay_to_ttl_builder.build_ttl(payload)
    output_path = args.output or args.replay_json.with_name(
        f"{args.replay_json.stem}-slice.ttl"
    )
    output_path.write_text(ttl, encoding="utf-8")
    print(output_path)
    return 0


def cmd_resolve_order(args: argparse.Namespace) -> int:
    payload = _load_json_object(args.state_json, label="turn-order state JSON")
    resolved = resolve_action_order(payload)
    _print_json(resolved, pretty=args.pretty)
    return 0


def add_replay_dataset_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    replay_parser = subparsers.add_parser(
        "replay", help="Acquire, curate, and transform replay datasets."
    )
    replay_subparsers = replay_parser.add_subparsers(
        dest="replay_command", required=True
    )

    fetch_index_parser = replay_subparsers.add_parser(
        "fetch-index", help="Fetch and cache replay search pages."
    )
    fetch_index_parser.add_argument(
        "--format", dest="formatid", required=True, help="Showdown format identifier."
    )
    fetch_index_parser.add_argument(
        "--index-dir",
        type=Path,
        default=replay_dataset.DEFAULT_INDEX_DIR,
        help="Directory for cached replay search pages.",
    )
    fetch_index_parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum number of search pages to fetch.",
    )
    fetch_index_parser.add_argument(
        "--user", default=None, help="Optional Showdown username filter."
    )
    fetch_index_parser.add_argument(
        "--delay-seconds",
        type=float,
        default=replay_dataset.DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_index_parser.add_argument(
        "--timeout",
        type=float,
        default=replay_dataset.DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_index_parser.add_argument(
        "--force", action="store_true", help="Refetch index pages even if cached."
    )
    fetch_index_parser.set_defaults(func=_return_zero(replay_dataset.cmd_fetch_index))

    curate_parser = replay_subparsers.add_parser(
        "curate", help="Curate replay IDs from cached search pages."
    )
    curate_parser.add_argument(
        "--index-dir",
        type=Path,
        default=replay_dataset.DEFAULT_INDEX_DIR,
        help="Directory containing cached replay search pages.",
    )
    curate_parser.add_argument(
        "--output",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    curate_parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        default=None,
        help="Required format identifier. Repeatable.",
    )
    curate_parser.add_argument(
        "--min-rating",
        type=int,
        default=None,
        help="Minimum rating required for inclusion.",
    )
    curate_parser.add_argument(
        "--min-uploadtime",
        type=int,
        default=None,
        help="Minimum upload timestamp for inclusion.",
    )
    curate_parser.add_argument(
        "--allow-non-heads-up",
        action="store_true",
        help="Allow index entries without exactly two players.",
    )
    curate_parser.set_defaults(func=_return_zero(replay_dataset.cmd_curate))

    fetch_parser = replay_subparsers.add_parser(
        "fetch", help="Fetch cached replay JSON payloads for curated replay IDs."
    )
    fetch_parser.add_argument(
        "--curated",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=replay_dataset.DEFAULT_RAW_DIR,
        help="Directory for cached replay JSON.",
    )
    fetch_parser.add_argument(
        "--delay-seconds",
        type=float,
        default=replay_dataset.DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_parser.add_argument(
        "--timeout",
        type=float,
        default=replay_dataset.DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="Refetch replay JSON even if cached."
    )
    fetch_parser.set_defaults(func=_return_zero(replay_dataset.cmd_fetch))

    transform_parser = replay_subparsers.add_parser(
        "transform", help="Build one replay slice TTL per curated cached replay."
    )
    transform_parser.add_argument(
        "--curated",
        type=Path,
        default=replay_dataset.DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=replay_dataset.DEFAULT_RAW_DIR,
        help="Directory containing cached replay JSON.",
    )
    transform_parser.add_argument(
        "--output-dir",
        type=Path,
        default=replay_dataset.DEFAULT_OUTPUT_DIR,
        help="Directory where replay slice TTL files will be written.",
    )
    transform_parser.set_defaults(func=_return_zero(replay_dataset.cmd_transform))


def add_pokeapi_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    pokeapi_parser = subparsers.add_parser(
        "pokeapi", help="Fetch and transform PokeAPI resources."
    )
    pokeapi_subparsers = pokeapi_parser.add_subparsers(
        dest="pokeapi_command", required=True
    )

    fetch_parser = pokeapi_subparsers.add_parser(
        "fetch", help="Fetch and cache selected PokeAPI payloads."
    )
    fetch_parser.add_argument(
        "seed",
        type=Path,
        help="Path to seed JSON describing which resources to ingest.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=pokeapi_ingest.DEFAULT_RAW_DIR,
        help="Directory for cached raw JSON.",
    )
    fetch_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    fetch_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_fetch))

    transform_parser = pokeapi_subparsers.add_parser(
        "transform", help="Transform cached raw JSON into Turtle."
    )
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
    transform_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_transform))

    ingest_parser = pokeapi_subparsers.add_parser(
        "ingest", help="Fetch cached JSON and build a Turtle dataset."
    )
    ingest_parser.add_argument(
        "seed",
        type=Path,
        help="Path to seed JSON describing which resources to ingest.",
    )
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
    ingest_parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    ingest_parser.set_defaults(func=_return_zero(pokeapi_ingest.cmd_ingest))


def add_veekun_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    veekun_parser = subparsers.add_parser(
        "veekun", help="Transform a local normalized Veekun export into Turtle."
    )
    veekun_subparsers = veekun_parser.add_subparsers(
        dest="veekun_command", required=True
    )

    transform_parser = veekun_subparsers.add_parser(
        "transform", help="Transform local Veekun CSV export into Turtle."
    )
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
    transform_parser.set_defaults(func=_return_zero(veekun_ingest.cmd_transform))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pokemontology",
        description="Unified CLI for building, validating, and transforming pokemontology data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_cmd = subparsers.add_parser(
        "build", help="Assemble ontology and shapes artifacts."
    )
    build_parser_cmd.set_defaults(func=cmd_build)

    check_parser = subparsers.add_parser(
        "check-ttl", help="Parse Turtle files with rdflib."
    )
    check_parser.add_argument("paths", nargs="+", type=Path, help="TTL files to parse.")
    check_parser.set_defaults(func=cmd_check_ttl)

    parse_parser = subparsers.add_parser(
        "parse-replay", help="Parse a Showdown replay into a turn/event stream."
    )
    parse_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    parse_parser.add_argument(
        "--pretty", action="store_true", help="Print parsed turns as indented JSON."
    )
    parse_parser.set_defaults(func=cmd_parse_replay)

    summarize_parser = subparsers.add_parser(
        "summarize-replay", help="Summarize a Showdown replay JSON."
    )
    summarize_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    summarize_parser.set_defaults(func=cmd_summarize_replay)

    slice_parser = subparsers.add_parser(
        "build-slice", help="Build a replay-backed Turtle slice."
    )
    slice_parser.add_argument(
        "replay_json", type=Path, help="Path to Showdown replay JSON."
    )
    slice_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output TTL path. Defaults to <replay_json stem>-slice.ttl.",
    )
    slice_parser.set_defaults(func=cmd_build_slice)

    resolve_parser = subparsers.add_parser(
        "resolve-order",
        help="Infer heads-up action order from move priority and battle-state snapshot inputs.",
    )
    resolve_parser.add_argument(
        "state_json", type=Path, help="Path to turn-order input JSON."
    )
    resolve_parser.add_argument(
        "--pretty", action="store_true", help="Print inferred order as indented JSON."
    )
    resolve_parser.set_defaults(func=cmd_resolve_order)

    add_replay_dataset_subcommands(subparsers)
    add_pokeapi_subcommands(subparsers)
    add_veekun_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.func(args))
    except CliUsageError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
