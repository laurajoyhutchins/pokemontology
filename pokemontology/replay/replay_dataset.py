#!/usr/bin/env python3
"""Acquire, curate, and transform competitive replay datasets.

This module keeps replay acquisition split into four stages:
- fetch-index: cache search/index pages
- curate: derive a replay-id list from cached index entries
- fetch: cache replay JSON payloads for curated replay IDs
- transform: build one TTL slice per cached replay JSON
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pokemontology.ingest_common import REPO_ROOT, serialize_turtle_to_path
from pokemontology.io_utils import format_json_text, read_json_file, write_json_file
from pokemontology.replay import replay_to_ttl_builder


REPO = REPO_ROOT
DEFAULT_INDEX_DIR = REPO / "data" / "replays" / "index" / "showdown"
DEFAULT_RAW_DIR = REPO / "data" / "replays" / "raw" / "showdown"
DEFAULT_CURATED_PATH = REPO / "data" / "replays" / "curated" / "competitive.json"
DEFAULT_OUTPUT_DIR = REPO / "build" / "replays"
DEFAULT_BUNDLE_PATH = REPO / "data" / "ingested" / "showdown.ttl"

SHOWDOWN_SEARCH_URL = "https://replay.pokemonshowdown.com/search.json"
SHOWDOWN_REPLAY_URL = "https://replay.pokemonshowdown.com/{replay_id}.json"
USER_AGENT = "pokemontology-replay-acquisition/0.1 (+https://laurajoyhutchins.github.io/pokemontology/)"
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class IndexFetchStats:
    cache_hits: int = 0
    fetches: int = 0
    pages_seen: int = 0
    entries_seen: int = 0


@dataclass
class ReplayFetchStats:
    cache_hits: int = 0
    fetches: int = 0
    replay_ids_seen: int = 0


@dataclass
class TransformStats:
    replay_ids_seen: int = 0
    slices_written: int = 0
    bundle_written: bool = False


def fetch_json_url(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_with_cache(
    url: str,
    cache_path: Path,
    *,
    timeout: float,
    delay_seconds: float,
    force: bool,
) -> tuple[Any, bool]:
    if cache_path.exists() and not force:
        return read_json_file(cache_path), False

    payload = fetch_json_url(url, timeout=timeout)
    write_json_file(cache_path, payload)
    time.sleep(delay_seconds)
    return payload, True


def index_cache_path(
    index_dir: Path, *, formatid: str, page: int, username: str | None
) -> Path:
    safe_user = username or "all"
    return index_dir / formatid / safe_user / f"page_{page}.json"


def replay_cache_path(raw_dir: Path, replay_id: str) -> Path:
    return raw_dir / f"{replay_id}.json"


def _search_url(*, formatid: str, page: int, username: str | None) -> str:
    query = {"format": formatid, "page": str(page)}
    if username:
        query["user"] = username
    return f"{SHOWDOWN_SEARCH_URL}?{urllib.parse.urlencode(query)}"


def _normalize_search_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if isinstance(payload, dict):
        for key in ("results", "replays", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
    raise ValueError("unsupported replay search payload format")


def fetch_index(
    *,
    formatid: str,
    index_dir: Path,
    max_pages: int | None,
    username: str | None,
    delay_seconds: float,
    timeout: float,
    force: bool,
) -> IndexFetchStats:
    stats = IndexFetchStats()
    page = 1

    while True:
        if max_pages is not None and stats.pages_seen >= max_pages:
            break

        cache_path = index_cache_path(
            index_dir, formatid=formatid, page=page, username=username
        )
        payload, fetched = fetch_with_cache(
            _search_url(formatid=formatid, page=page, username=username),
            cache_path,
            timeout=timeout,
            delay_seconds=delay_seconds,
            force=force,
        )
        entries = _normalize_search_entries(payload)
        stats.pages_seen += 1
        stats.entries_seen += len(entries)
        if fetched:
            stats.fetches += 1
        else:
            stats.cache_hits += 1

        if not entries:
            break
        page += 1

    return stats


def _iter_index_entries(index_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(index_dir.rglob("page_*.json")):
        entries.extend(_normalize_search_entries(read_json_file(path)))
    return entries


def curate_replay_ids(
    index_dir: Path,
    curated_path: Path,
    *,
    formats: set[str] | None,
    min_rating: int | None,
    min_uploadtime: int | None,
    require_two_players: bool,
) -> dict[str, Any]:
    selected: dict[str, dict[str, Any]] = {}

    for entry in _iter_index_entries(index_dir):
        replay_id = str(entry.get("id") or "").strip()
        if not replay_id:
            continue

        formatid = str(entry.get("format") or entry.get("formatid") or "").strip()
        rating = entry.get("rating")
        uploadtime = entry.get("uploadtime")
        players = entry.get("players") or []

        if formats and formatid not in formats:
            continue
        if (
            min_rating is not None
            and isinstance(rating, (int, float))
            and rating < min_rating
        ):
            continue
        if min_rating is not None and rating is None:
            continue
        if (
            min_uploadtime is not None
            and isinstance(uploadtime, (int, float))
            and uploadtime < min_uploadtime
        ):
            continue
        if require_two_players and len(players) != 2:
            continue

        selected[replay_id] = {
            "id": replay_id,
            "format": formatid,
            "players": players,
            "rating": rating,
            "uploadtime": uploadtime,
            "source": "pokemon-showdown-search",
        }

    payload = {
        "source": "pokemon-showdown-search",
        "criteria": {
            "formats": sorted(formats) if formats else None,
            "min_rating": min_rating,
            "min_uploadtime": min_uploadtime,
            "require_two_players": require_two_players,
        },
        "replay_ids": sorted(selected),
        "replays": [selected[replay_id] for replay_id in sorted(selected)],
    }
    write_json_file(curated_path, payload)
    return payload


def load_curated_replay_ids(curated_path: Path) -> list[str]:
    payload = read_json_file(curated_path)
    if isinstance(payload, dict):
        replay_ids = payload.get("replay_ids")
        if isinstance(replay_ids, list):
            return [str(item) for item in replay_ids if str(item).strip()]
    if isinstance(payload, list):
        return [str(item) for item in payload if str(item).strip()]
    raise ValueError("curated replay file must be a list or an object with replay_ids")


def fetch_replays(
    curated_path: Path,
    raw_dir: Path,
    *,
    delay_seconds: float,
    timeout: float,
    force: bool,
) -> ReplayFetchStats:
    stats = ReplayFetchStats()

    for replay_id in load_curated_replay_ids(curated_path):
        stats.replay_ids_seen += 1
        _, fetched = fetch_with_cache(
            SHOWDOWN_REPLAY_URL.format(replay_id=replay_id),
            replay_cache_path(raw_dir, replay_id),
            timeout=timeout,
            delay_seconds=delay_seconds,
            force=force,
        )
        if fetched:
            stats.fetches += 1
        else:
            stats.cache_hits += 1

    return stats


def _write_bundle_from_slices(bundle_path: Path, slice_paths: list[Path]) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with bundle_path.open("w", encoding="utf-8") as outfile:
        outfile.write(
            "@prefix pkm: <https://laurajoyhutchins.github.io/pokemontology/ontology.ttl#> .\n"
        )
        outfile.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
        outfile.write("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")
        for slice_path in slice_paths:
            with slice_path.open("r", encoding="utf-8") as infile:
                for line in infile:
                    if not line.startswith("@prefix"):
                        outfile.write(line)
            outfile.write("\n")


def transform_replays(
    curated_path: Path,
    raw_dir: Path,
    output_dir: Path,
    *,
    bundle_path: Path | None = None,
) -> TransformStats:
    stats = TransformStats()
    manifest: list[dict[str, str]] = []
    slice_paths: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for replay_id in load_curated_replay_ids(curated_path):
        stats.replay_ids_seen += 1
        payload_path = replay_cache_path(raw_dir, replay_id)
        if not payload_path.exists():
            raise FileNotFoundError(
                f"missing cached replay JSON for {replay_id}: {payload_path}"
            )

        payload = read_json_file(payload_path)
        ttl_path = output_dir / f"{replay_id}.ttl"
        serialize_turtle_to_path(replay_to_ttl_builder.build_graph(payload), ttl_path)
        manifest.append({"id": replay_id, "ttl_path": str(ttl_path)})
        slice_paths.append(ttl_path)
        stats.slices_written += 1

    write_json_file(
        output_dir / "manifest.json",
        {
            "source": "pokemon-showdown-search",
            "curated_path": str(curated_path),
            "slices": manifest,
        },
    )
    if bundle_path is not None:
        _write_bundle_from_slices(bundle_path, slice_paths)
        stats.bundle_written = True
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_index_parser = subparsers.add_parser(
        "fetch-index", help="Fetch and cache Pokémon Showdown replay search pages."
    )
    fetch_index_parser.add_argument(
        "--format",
        dest="formatid",
        required=True,
        help="Showdown format identifier, e.g. gen9vgc2025reggbo3.",
    )
    fetch_index_parser.add_argument(
        "--index-dir",
        type=Path,
        default=DEFAULT_INDEX_DIR,
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
        default=DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_index_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_index_parser.add_argument(
        "--force", action="store_true", help="Refetch index pages even if cached."
    )

    curate_parser = subparsers.add_parser(
        "curate", help="Curate replay IDs from cached replay search pages."
    )
    curate_parser.add_argument(
        "--index-dir",
        type=Path,
        default=DEFAULT_INDEX_DIR,
        help="Directory containing cached replay search pages.",
    )
    curate_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CURATED_PATH,
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
        help="Minimum ladder rating required for inclusion.",
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
        help="Allow replay index entries without exactly two players.",
    )

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch and cache replay JSON payloads for curated replay IDs."
    )
    fetch_parser.add_argument(
        "--curated",
        type=Path,
        default=DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    fetch_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Directory for cached replay JSON.",
    )
    fetch_parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Delay after each network request.",
    )
    fetch_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="Refetch replay JSON even if cached."
    )

    transform_parser = subparsers.add_parser(
        "transform", help="Build one replay slice TTL per curated cached replay."
    )
    transform_parser.add_argument(
        "--curated",
        type=Path,
        default=DEFAULT_CURATED_PATH,
        help="Path to curated replay list JSON.",
    )
    transform_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Directory containing cached replay JSON.",
    )
    transform_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where replay slice TTL files will be written.",
    )
    transform_parser.add_argument(
        "--bundle-output",
        type=Path,
        default=DEFAULT_BUNDLE_PATH,
        help="Canonical combined replay Turtle bundle to write.",
    )

    return parser


def cmd_fetch_index(args: argparse.Namespace) -> None:
    stats = fetch_index(
        formatid=args.formatid,
        index_dir=args.index_dir,
        max_pages=args.max_pages,
        username=args.user,
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        force=args.force,
    )
    print(
        format_json_text(
            {
                "format": args.formatid,
                "index_dir": str(args.index_dir),
                "pages_seen": stats.pages_seen,
                "entries_seen": stats.entries_seen,
                "cache_hits": stats.cache_hits,
                "fetches": stats.fetches,
            },
            pretty=True,
        )
    )


def cmd_curate(args: argparse.Namespace) -> None:
    payload = curate_replay_ids(
        args.index_dir,
        args.output,
        formats=set(args.formats) if args.formats else None,
        min_rating=args.min_rating,
        min_uploadtime=args.min_uploadtime,
        require_two_players=not args.allow_non_heads_up,
    )
    print(
        format_json_text(
            {
                "output": str(args.output),
                "replay_count": len(payload["replay_ids"]),
            },
            pretty=True,
        )
    )


def cmd_fetch(args: argparse.Namespace) -> None:
    stats = fetch_replays(
        args.curated,
        args.raw_dir,
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        force=args.force,
    )
    print(
        format_json_text(
            {
                "curated": str(args.curated),
                "raw_dir": str(args.raw_dir),
                "replay_ids_seen": stats.replay_ids_seen,
                "cache_hits": stats.cache_hits,
                "fetches": stats.fetches,
            },
            pretty=True,
        )
    )


def cmd_transform(args: argparse.Namespace) -> None:
    stats = transform_replays(
        args.curated,
        args.raw_dir,
        args.output_dir,
        bundle_path=args.bundle_output,
    )
    print(
        format_json_text(
            {
                "curated": str(args.curated),
                "output_dir": str(args.output_dir),
                "bundle_output": str(args.bundle_output),
                "replay_ids_seen": stats.replay_ids_seen,
                "slices_written": stats.slices_written,
                "bundle_written": stats.bundle_written,
            },
            pretty=True,
        )
    )


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "fetch-index":
        cmd_fetch_index(args)
    elif args.command == "curate":
        cmd_curate(args)
    elif args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "transform":
        cmd_transform(args)
    else:
        raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
