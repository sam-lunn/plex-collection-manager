"""Pure local helper logic for /sync-collections. No Plex calls here -
this only reads/writes local JSON files (the movie/collection snapshots
already fetched via plex_tool.py, and the franchise cache) and computes
what to do. Keeping this separate from plex_tool.py keeps the Plex-facing
CLI limited to exactly the operations described in its docstring.
"""

from __future__ import annotations

import argparse
import html
import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def cmd_unclassified(args: argparse.Namespace) -> None:
    movies = load(args.movies)["movies"]
    try:
        cache = load(args.cache)
    except FileNotFoundError:
        cache = {}
    unclassified = [m for m in movies if str(m["key"]) not in cache]
    known_franchises = sorted({v["franchise"] for v in cache.values() if v.get("franchise")})
    print(json.dumps({"unclassified": unclassified, "known_franchises": known_franchises}, indent=2))


def cmd_merge_cache(args: argparse.Namespace) -> None:
    try:
        cache = load(args.cache)
    except FileNotFoundError:
        cache = {}
    batch = load(args.batch)
    entries = batch if isinstance(batch, list) else batch["classified"]
    for entry in entries:
        franchise = entry.get("franchise")
        cache[str(entry["key"])] = {
            "title": entry["title"],
            "year": entry.get("year"),
            "franchise": html.unescape(franchise) if franchise else franchise,
        }
    save(args.cache, cache)
    print(json.dumps({"cache_size": len(cache)}, indent=2))


def cmd_plan(args: argparse.Namespace) -> None:
    movies = load(args.movies)["movies"]
    collections = load(args.collections)["collections"]
    cache = load(args.cache)

    owned_keys = {m["key"] for m in movies}

    desired: dict[str, set[int]] = {}
    for m in movies:
        entry = cache.get(str(m["key"]))
        if entry and entry.get("franchise"):
            desired.setdefault(entry["franchise"], set()).add(m["key"])
    desired = {name: keys for name, keys in desired.items() if len(keys) >= 3}

    by_title = {c["title"].strip().lower(): c for c in collections}
    matched_collection_keys: set[int] = set()

    creates = []
    adds = []
    removes = []

    for franchise, keys in sorted(desired.items()):
        current = by_title.get(franchise.strip().lower())
        if current is None:
            creates.append({"title": franchise, "keys": sorted(keys)})
            continue
        matched_collection_keys.add(current["key"])
        current_keys = {item["key"] for item in current["items"]}
        for k in sorted(keys - current_keys):
            adds.append({
                "collection_key": current["key"],
                "collection_title": current["title"],
                "movie_key": k,
            })
        for k in sorted(current_keys - keys):
            removes.append({
                "collection_key": current["key"],
                "collection_title": current["title"],
                "movie_key": k,
            })

    deletes = []
    for c in collections:
        if c["key"] in matched_collection_keys:
            continue
        # Item count after this run, for collections we're not touching, is
        # just its current count (items no longer in the library don't count).
        final_count = len({i["key"] for i in c["items"]} & owned_keys)
        if final_count <= 1:
            deletes.append({
                "collection_key": c["key"],
                "collection_title": c["title"],
                "item_count": final_count,
            })

    plan = {"creates": creates, "adds": adds, "removes": removes, "deletes": deletes}
    print(json.dumps(plan, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="sync-logic")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("unclassified", help="List movies not yet in the franchise cache")
    p.add_argument("movies")
    p.add_argument("cache")
    p.set_defaults(func=cmd_unclassified)

    p = sub.add_parser("merge-cache", help="Merge a classified batch into the franchise cache")
    p.add_argument("cache")
    p.add_argument("batch")
    p.set_defaults(func=cmd_merge_cache)

    p = sub.add_parser("plan", help="Compute the create/add/remove/delete plan")
    p.add_argument("movies")
    p.add_argument("collections")
    p.add_argument("cache")
    p.set_defaults(func=cmd_plan)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
