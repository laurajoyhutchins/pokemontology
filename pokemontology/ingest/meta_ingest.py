"""Competitive meta snapshot ingestion.

Reads a corpus of Pokémon Showdown replay JSON files, aggregates observable
usage statistics (species appearance and move usage per battle), and emits a
pkm:MetaSnapshot TTL file with pkm:SpeciesUsageStat and pkm:MoveUsageStat
individuals.
"""

from __future__ import annotations

import argparse
import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal
from rdflib.namespace import RDF, RDFS, XSD

from pokemontology.ingest_common import (
    PKM,
    REPO_ROOT,
    bind_namespaces,
    sanitize_identifier,
    serialize_turtle_to_path,
)
from pokemontology.io_utils import read_json_file, write_json_file
from pokemontology.replay.replay_parser import (
    discover_moves,
    discover_participants,
    parse_log,
    parse_replay_payload,
    pokeapi_species_id,
    move_iri_local,
)


REPO = REPO_ROOT
DEFAULT_CURATED_PATH = REPO / "data" / "replays" / "curated" / "competitive.json"
DEFAULT_RAW_DIR = REPO / "data" / "replays" / "raw" / "showdown"
DEFAULT_OUTPUT = REPO / "build" / "meta-snapshot.ttl"


def _species_iri(species_raw: str):
    return PKM[f"Species_{sanitize_identifier(pokeapi_species_id(species_raw))}"]


def _move_iri(move_name: str):
    return PKM[move_iri_local(move_name)]


def _ruleset_iri(fmt: str):
    return PKM[f"Ruleset_{sanitize_identifier(fmt)}"]


def _snapshot_iri(fmt: str, snapshot_date: str):
    safe_fmt = sanitize_identifier(fmt)
    safe_date = snapshot_date.replace("-", "_")
    return PKM[f"MetaSnapshot_{safe_fmt}_{safe_date}"]


def _extract_team_species(log: str) -> list[str]:
    """Extract all species declared in team preview (|poke| lines).

    In VGC team preview, each player declares their full team with lines like:
        |poke|p1|Koraidon, L50|
        |poke|p2|Arceus-Fire, L50|
    This gives the complete team composition including Pokemon not brought to battle.
    If no |poke| lines are found, falls back to all switch events (pre- and in-battle).
    """
    species: list[str] = []
    for line in log.splitlines():
        if not line.startswith("|poke|"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        species_token = parts[3].strip()
        species_raw = species_token.split(",")[0].strip()
        if species_raw:
            species.append(species_raw)

    if species:
        return species

    # Fallback: parse all switch events regardless of turn number
    for line in log.splitlines():
        if not line.startswith("|switch|"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        species_token = parts[3].strip()
        species_raw = species_token.split(",")[0].strip()
        if species_raw:
            species.append(species_raw)

    return species


def aggregate(
    replay_paths: list[Path],
) -> dict[str, Any]:
    """Aggregate usage statistics from a list of replay JSON paths.

    Returns a dict with keys:
        formats: set of format strings observed across replays
        replay_count: int
        species_battles: dict mapping species_raw → set of replay IDs where it appeared
        move_battles: dict mapping move_name → set of replay IDs where it was used
    """
    species_battles: dict[str, set[str]] = defaultdict(set)
    move_battles: dict[str, set[str]] = defaultdict(set)
    formats: set[str] = set()

    for replay_path in replay_paths:
        payload = read_json_file(replay_path)
        try:
            replay_id, fmt, _url, p1, p2 = parse_replay_payload(payload)
        except (KeyError, ValueError):
            continue

        log = payload.get("log")
        if not isinstance(log, str):
            continue

        formats.add(fmt)

        for species_raw in _extract_team_species(log):
            species_battles[species_raw].add(replay_id)

        events = parse_log(log)
        moves = discover_moves(events)
        for move_name in moves.values():
            move_battles[move_name].add(replay_id)

    return {
        "formats": formats,
        "replay_count": len(replay_paths),
        "species_battles": species_battles,
        "move_battles": move_battles,
    }


def build_graph(
    replay_paths: list[Path],
    *,
    snapshot_date: str | None = None,
) -> Graph:
    """Build an RDF graph containing a MetaSnapshot from the given replay JSONs.

    Args:
        replay_paths: Paths to Pokémon Showdown replay JSON files.
        snapshot_date: ISO date string (YYYY-MM-DD). Defaults to today.
    """
    if snapshot_date is None:
        snapshot_date = datetime.date.today().isoformat()

    data = aggregate(replay_paths)
    n = data["replay_count"]
    formats = data["formats"]
    species_battles: dict[str, set[str]] = data["species_battles"]
    move_battles: dict[str, set[str]] = data["move_battles"]

    fmt = next(iter(sorted(formats))) if formats else "Unknown Format"
    if len(formats) > 1:
        fmt = next(iter(sorted(formats)))

    g = Graph()
    bind_namespaces(g)

    ruleset = _ruleset_iri(fmt)
    g.add((ruleset, RDF.type, PKM.Ruleset))
    g.add((ruleset, PKM.hasName, Literal(fmt)))

    snapshot = _snapshot_iri(fmt, snapshot_date)
    g.add((snapshot, RDF.type, PKM.MetaSnapshot))
    g.add((snapshot, RDFS.label, Literal(f"Meta snapshot: {fmt} ({snapshot_date})")))
    g.add((snapshot, PKM.forFormat, ruleset))
    g.add((snapshot, PKM.snapshotDate, Literal(snapshot_date, datatype=XSD.date)))
    g.add((snapshot, PKM.replayCount, Literal(n, datatype=XSD.integer)))

    for species_raw, battle_set in sorted(
        species_battles.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        count = len(battle_set)
        rate = round(count / n, 6) if n > 0 else 0.0
        species_iri = _species_iri(species_raw)
        stat_iri = PKM[
            f"SpeciesUsageStat_{sanitize_identifier(fmt)}_{snapshot_date.replace('-', '_')}"
            f"_{sanitize_identifier(pokeapi_species_id(species_raw))}"
        ]
        g.add((species_iri, RDF.type, PKM.Species))
        g.add((species_iri, PKM.hasName, Literal(species_raw)))
        g.add((stat_iri, RDF.type, PKM.SpeciesUsageStat))
        g.add((stat_iri, PKM.inSnapshot, snapshot))
        g.add((stat_iri, PKM.aboutSpecies, species_iri))
        g.add((stat_iri, PKM.usageCount, Literal(count, datatype=XSD.integer)))
        g.add((stat_iri, PKM.usageRate, Literal(rate, datatype=XSD.decimal)))

    for move_name, battle_set in sorted(
        move_battles.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        count = len(battle_set)
        rate = round(count / n, 6) if n > 0 else 0.0
        move_iri = _move_iri(move_name)
        stat_iri = PKM[
            f"MoveUsageStat_{sanitize_identifier(fmt)}_{snapshot_date.replace('-', '_')}"
            f"_{sanitize_identifier(move_iri_local(move_name))}"
        ]
        g.add((move_iri, RDF.type, PKM.Move))
        g.add((move_iri, PKM.hasName, Literal(move_name)))
        g.add((stat_iri, RDF.type, PKM.MoveUsageStat))
        g.add((stat_iri, PKM.inSnapshot, snapshot))
        g.add((stat_iri, PKM.aboutMove, move_iri))
        g.add((stat_iri, PKM.usageCount, Literal(count, datatype=XSD.integer)))
        g.add((stat_iri, PKM.usageRate, Literal(rate, datatype=XSD.decimal)))

    return g


def _load_replay_paths_from_curated(curated_path: Path, raw_dir: Path) -> list[Path]:
    payload = read_json_file(curated_path)
    if isinstance(payload, dict):
        replay_ids = payload.get("replay_ids", [])
    elif isinstance(payload, list):
        replay_ids = payload
    else:
        replay_ids = []
    return [raw_dir / f"{rid}.json" for rid in replay_ids]


def cmd_meta_snapshot(args: argparse.Namespace) -> None:
    if args.replay_json:
        replay_paths = list(args.replay_json)
    elif args.curated and args.raw_dir:
        replay_paths = _load_replay_paths_from_curated(args.curated, args.raw_dir)
    else:
        replay_paths = _load_replay_paths_from_curated(
            DEFAULT_CURATED_PATH, DEFAULT_RAW_DIR
        )

    missing = [p for p in replay_paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"WARNING: missing replay JSON: {p}")
        replay_paths = [p for p in replay_paths if p.exists()]

    if not replay_paths:
        raise SystemExit("No replay JSON files found. Run 'replay fetch' first.")

    output = args.output or DEFAULT_OUTPUT
    g = build_graph(replay_paths, snapshot_date=args.date)
    serialize_turtle_to_path(g, output)

    species_count = sum(1 for _, _, _ in g.triples((None, RDF.type, PKM.SpeciesUsageStat)))
    move_count = sum(1 for _, _, _ in g.triples((None, RDF.type, PKM.MoveUsageStat)))
    print(
        f"Written: {output}\n"
        f"  replays: {len(replay_paths)}\n"
        f"  species usage stats: {species_count}\n"
        f"  move usage stats: {move_count}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a competitive meta snapshot from Showdown replay JSON files."
    )
    parser.add_argument(
        "replay_json",
        nargs="*",
        type=Path,
        help="One or more Showdown replay JSON paths. Mutually exclusive with --curated.",
    )
    parser.add_argument(
        "--curated",
        type=Path,
        default=None,
        help=f"Path to curated replay list JSON (default: {DEFAULT_CURATED_PATH}).",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help=f"Directory containing cached replay JSON (default: {DEFAULT_RAW_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output TTL path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Snapshot date as YYYY-MM-DD (default: today).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cmd_meta_snapshot(args)


if __name__ == "__main__":
    main()
