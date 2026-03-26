#!/usr/bin/env python3
"""Scrape PokeAPI list/detail data with cache-first fair-use behavior.

This script is intentionally conservative:
- GET requests only
- explicit User-Agent
- on-disk caching of every fetched response
- delay between network requests
- optional pagination/detail limits
- resumable runs that skip cached responses by default
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pokemontology.ingest_common import REPO_ROOT, sanitize_identifier


REPO = REPO_ROOT
DEFAULT_CACHE_DIR = REPO / "data" / "pokeapi" / "scrape-cache"
DEFAULT_DELAY_SECONDS = 0.5
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_SIZE = 100
POKEAPI_BASE = "https://pokeapi.co/api/v2"
USER_AGENT = (
    "pokemontology-scraper/0.1 (+https://laurajoyhutchins.github.io/pokemontology/)"
)

ALLOWED_RESOURCES = {
    "ability",
    "move",
    "pokemon",
    "pokemon-species",
    "stat",
    "type",
    "version-group",
}


@dataclass
class ScrapeStats:
    page_cache_hits: int = 0
    page_fetches: int = 0
    detail_cache_hits: int = 0
    detail_fetches: int = 0
    detail_seen: int = 0


def page_cache_path(cache_dir: Path, resource: str, offset: int, limit: int) -> Path:
    return cache_dir / resource / "pages" / f"offset_{offset}_limit_{limit}.json"


def detail_cache_path(cache_dir: Path, resource: str, name: str) -> Path:
    return cache_dir / resource / "detail" / f"{sanitize_identifier(name)}.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json_url(url: str, timeout: float) -> dict[str, Any]:
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
    timeout: float,
    delay_seconds: float,
    force: bool,
) -> tuple[dict[str, Any], bool]:
    if cache_path.exists() and not force:
        return read_json(cache_path), False

    payload = fetch_json_url(url, timeout=timeout)
    write_json(cache_path, payload)
    time.sleep(delay_seconds)
    return payload, True


def scrape_resource(
    resource: str,
    cache_dir: Path,
    *,
    include_details: bool,
    page_size: int,
    max_pages: int | None,
    max_details: int | None,
    delay_seconds: float,
    timeout: float,
    force: bool,
) -> ScrapeStats:
    stats = ScrapeStats()
    offset = 0
    page_count = 0

    while True:
        if max_pages is not None and page_count >= max_pages:
            break

        page_url = f"{POKEAPI_BASE}/{resource}/?limit={page_size}&offset={offset}"
        page_path = page_cache_path(cache_dir, resource, offset, page_size)
        page_payload, fetched = fetch_with_cache(
            page_url,
            page_path,
            timeout=timeout,
            delay_seconds=delay_seconds,
            force=force,
        )
        if fetched:
            stats.page_fetches += 1
        else:
            stats.page_cache_hits += 1

        page_count += 1
        results = page_payload.get("results", [])

        if include_details:
            for entry in results:
                if max_details is not None and stats.detail_seen >= max_details:
                    return stats
                name = entry.get("name")
                url = entry.get("url")
                if not name or not url:
                    continue

                detail_path = detail_cache_path(cache_dir, resource, name)
                _, detail_fetched = fetch_with_cache(
                    url,
                    detail_path,
                    timeout=timeout,
                    delay_seconds=delay_seconds,
                    force=force,
                )
                stats.detail_seen += 1
                if detail_fetched:
                    stats.detail_fetches += 1
                else:
                    stats.detail_cache_hits += 1

        next_url = page_payload.get("next")
        if not next_url:
            break

        offset += page_size

    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "resource",
        choices=sorted(ALLOWED_RESOURCES),
        help="PokeAPI resource to scrape.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory where page/detail JSON responses will be cached.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fetch detail documents for each list result in addition to paginated list pages.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Page size for list endpoint requests.",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None, help="Stop after this many list pages."
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=None,
        help="Stop after this many detail documents.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Delay after each network request to avoid hammering PokeAPI.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch pages/details even when a cached response already exists.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    stats = scrape_resource(
        args.resource,
        args.cache_dir,
        include_details=args.details,
        page_size=args.page_size,
        max_pages=args.max_pages,
        max_details=args.max_details,
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "resource": args.resource,
                "cache_dir": str(args.cache_dir),
                "page_cache_hits": stats.page_cache_hits,
                "page_fetches": stats.page_fetches,
                "detail_cache_hits": stats.detail_cache_hits,
                "detail_fetches": stats.detail_fetches,
                "detail_seen": stats.detail_seen,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
