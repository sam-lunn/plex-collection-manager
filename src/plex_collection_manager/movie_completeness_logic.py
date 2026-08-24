"""Pure local helper logic for /find-incomplete-collections. No Plex calls
here - this only reads/writes local JSON files (the collections snapshot
already fetched via plex_tool.py, the franchise cache, and the
completeness cache) and computes what to do. Keeping this separate from
plex_tool.py keeps the Plex-facing CLI limited to exactly the operations
described in its docstring.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _norm_title(title: str) -> str:
    return title.strip().lower()


def cmd_to_check(args: argparse.Namespace) -> None:
    collections = load(args.collections)["collections"]
    franchise_cache = load(args.franchise_cache)
    known_franchises = {v["franchise"] for v in franchise_cache.values() if v.get("franchise")}

    try:
        completeness_cache = load(args.cache)
    except FileNotFoundError:
        completeness_cache = {}

    to_check = []
    skipped_non_franchise = []
    for c in collections:
        if c["title"] not in known_franchises:
            skipped_non_franchise.append(c["title"])
            continue
        if c["title"] in completeness_cache:
            continue
        to_check.append({
            "collection_key": c["key"],
            "title": c["title"],
            "owned": [{"title": i["title"], "year": i["year"]} for i in c["items"]],
        })

    print(json.dumps({
        "to_check": to_check,
        "skipped_non_franchise": sorted(skipped_non_franchise),
    }, indent=2))


def cmd_merge_cache(args: argparse.Namespace) -> None:
    try:
        cache = load(args.cache)
    except FileNotFoundError:
        cache = {}
    batch = load(args.batch)
    entries = batch if isinstance(batch, list) else batch["checked"]
    today = datetime.date.today().isoformat()
    for entry in entries:
        cache[entry["collection"]] = {
            "canonical": entry.get("canonical", []),
            "note": entry.get("note", ""),
            "checked_at": today,
        }
    save(args.cache, cache)
    print(json.dumps({"cache_size": len(cache)}, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    collections = load(args.collections)["collections"]
    cache = load(args.cache)
    by_title = {c["title"]: c for c in collections}

    incomplete = []
    complete = 0
    for title, entry in sorted(cache.items()):
        collection = by_title.get(title)
        if collection is None:
            # Collection no longer exists in Plex (renamed/deleted) - nothing to report.
            continue
        owned_titles = {_norm_title(i["title"]) for i in collection["items"]}
        missing = [
            m for m in entry.get("canonical", [])
            if _norm_title(m["title"]) not in owned_titles
        ]
        if missing:
            incomplete.append({
                "collection_key": collection["key"],
                "collection": title,
                "owned_count": len(collection["items"]),
                "missing": missing,
                "note": entry.get("note", ""),
                "checked_at": entry.get("checked_at"),
            })
        else:
            complete += 1

    print(json.dumps({"incomplete": incomplete, "complete_count": complete}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="movie-completeness-logic")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("to-check", help="List franchise collections not yet in the completeness cache")
    p.add_argument("collections")
    p.add_argument("franchise_cache")
    p.add_argument("cache")
    p.set_defaults(func=cmd_to_check)

    p = sub.add_parser("merge-cache", help="Merge a checked batch into the completeness cache")
    p.add_argument("cache")
    p.add_argument("batch")
    p.set_defaults(func=cmd_merge_cache)

    p = sub.add_parser("report", help="Diff current collection membership against cached canonical lists")
    p.add_argument("collections")
    p.add_argument("cache")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
