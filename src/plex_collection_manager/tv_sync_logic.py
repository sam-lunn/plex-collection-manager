"""Pure local helper logic for /sync-tv-collections. No Plex calls here -
this only reads/writes local JSON files (the show/collection snapshots
already fetched via plex_tool.py, and the TV status cache) and computes
what to do.

Deliberately separate from movie_sync_logic.py (the movie franchise planner):
this module has no delete code path at all, and its plan only ever
examines the 4 fixed status collections - both are meant to be verifiable
by reading this file, not just documented behavior.
"""

from __future__ import annotations

import argparse
import json
import sys

CATEGORIES = ["Ongoing", "Ended Poorly", "Ended Okay", "Ended Well"]


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def cmd_unclassified(args: argparse.Namespace) -> None:
    shows = load(args.shows)["shows"]
    try:
        cache = load(args.cache)
    except FileNotFoundError:
        cache = {}

    to_classify = []
    for s in shows:
        entry = cache.get(str(s["key"]))
        if entry is None:
            to_classify.append(s)
        elif entry.get("category") == "Ongoing":
            to_classify.append(s)
        elif (
            s.get("leafCount") is not None
            and entry.get("leaf_count") is not None
            and s["leafCount"] > entry["leaf_count"]
        ):
            # An "Ended" show grew new episodes since it was classified
            # (revival season, wrap-up special filed as an episode) - it
            # needs reclassifying rather than being trusted as settled.
            to_classify.append(s)

    print(json.dumps({"to_classify": to_classify, "categories": CATEGORIES}, indent=2))


def cmd_merge_cache(args: argparse.Namespace) -> None:
    try:
        cache = load(args.cache)
    except FileNotFoundError:
        cache = {}
    batch = load(args.batch)
    entries = batch if isinstance(batch, list) else batch["classified"]
    shows_by_key = {str(s["key"]): s for s in load(args.shows)["shows"]}

    for entry in entries:
        category = entry["category"]
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category {category!r} for show {entry.get('title')!r}")
        key = str(entry["key"])
        show = shows_by_key.get(key)
        cache[key] = {
            "title": entry["title"],
            "year": entry.get("year"),
            "category": category,
            "leaf_count": show["leafCount"] if show else None,
        }
    save(args.cache, cache)
    print(json.dumps({"cache_size": len(cache)}, indent=2))


def cmd_plan(args: argparse.Namespace) -> None:
    shows = load(args.shows)["shows"]
    collections = load(args.collections)["collections"]
    cache = load(args.cache)

    desired: dict[str, set[int]] = {name: set() for name in CATEGORIES}
    for s in shows:
        entry = cache.get(str(s["key"]))
        if entry and entry.get("category") in desired:
            desired[entry["category"]].add(s["key"])

    by_title = {c["title"].strip().lower(): c for c in collections}

    creates = []
    adds = []
    removes = []

    for category in CATEGORIES:
        keys = desired[category]
        current = by_title.get(category.strip().lower())
        if current is None:
            if keys:
                creates.append({"title": category, "keys": sorted(keys)})
            continue
        current_keys = {item["key"] for item in current["items"]}
        for k in sorted(keys - current_keys):
            adds.append({
                "collection_key": current["key"],
                "collection_title": current["title"],
                "show_key": k,
            })
        for k in sorted(current_keys - keys):
            removes.append({
                "collection_key": current["key"],
                "collection_title": current["title"],
                "show_key": k,
            })

    plan = {"creates": creates, "adds": adds, "removes": removes}
    print(json.dumps(plan, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="tv-sync-logic")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("unclassified", help="List shows needing (re)classification")
    p.add_argument("shows")
    p.add_argument("cache")
    p.set_defaults(func=cmd_unclassified)

    p = sub.add_parser("merge-cache", help="Merge a classified batch into the TV status cache")
    p.add_argument("cache")
    p.add_argument("batch")
    p.add_argument("shows")
    p.set_defaults(func=cmd_merge_cache)

    p = sub.add_parser("plan", help="Compute the create/add/remove plan for the 4 status collections")
    p.add_argument("shows")
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
