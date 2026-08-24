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
import html
import json
import re
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _norm_title(title: str) -> str:
    # Plex titles and researched canonical titles routinely differ only in
    # punctuation style (an em dash vs "--" vs "-", a colon before a
    # subtitle, a trailing period) - normalize those away so real matches
    # aren't reported as missing just because of formatting.
    t = title.strip().lower()
    t = re.sub(r"[-‐‑‒–—―]+", " ", t)  # hyphen/dash variants
    t = re.sub(r"[:,.!]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def cmd_to_check(args: argparse.Namespace) -> None:
    collections = load(args.collections)["collections"]
    franchise_cache = load(args.franchise_cache)
    known_franchises = {
        _norm_title(v["franchise"]) for v in franchise_cache.values() if v.get("franchise")
    }

    try:
        completeness_cache = load(args.cache)
    except FileNotFoundError:
        completeness_cache = {}
    checked_titles = {_norm_title(t) for t in completeness_cache}

    to_check = []
    skipped_non_franchise = []
    for c in collections:
        if _norm_title(c["title"]) not in known_franchises:
            skipped_non_franchise.append(c["title"])
            continue
        if _norm_title(c["title"]) in checked_titles:
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
        canonical = [
            {**m, "title": html.unescape(m["title"])}
            for m in entry.get("canonical", [])
        ]
        cache[html.unescape(entry["collection"])] = {
            "canonical": canonical,
            "note": html.unescape(entry.get("note", "")),
            "checked_at": today,
        }
    save(args.cache, cache)
    print(json.dumps({"cache_size": len(cache)}, indent=2))


def _missing_for_collection(canonical: list, owned_items: list) -> list:
    # Match each canonical entry to an owned item in two passes, consuming
    # owned items as they're matched so the same physical file can't satisfy
    # two different canonical entries.
    #
    # Pass 1 - title, disambiguated by year when the title repeats. A plain
    # "is this title anywhere in owned" check is unsafe: a franchise can
    # reuse the exact same title for a remake (e.g. "Cinderella" 1950 and
    # 2015, "Mulan" 1998 and 2020) - if only the original is owned, a
    # title-only check would wrongly treat the remake as owned too. So
    # within a group of canonical entries sharing a normalized title, each
    # is only matched to an owned item of the same normalized title AND the
    # same year. Titles that aren't duplicated within this collection are
    # matched on title alone, regardless of year, since there's no other
    # candidate they could be confused with.
    owned_pool = list(owned_items)
    canon_title_counts: dict = {}
    for m in canonical:
        t = _norm_title(m["title"])
        canon_title_counts[t] = canon_title_counts.get(t, 0) + 1

    unmatched_canonical = []
    for m in canonical:
        t = _norm_title(m["title"])
        duplicated = canon_title_counts.get(t, 0) > 1
        match_idx = None
        for idx, i in enumerate(owned_pool):
            if _norm_title(i["title"]) != t:
                continue
            if duplicated and i.get("year") != m.get("year"):
                continue
            match_idx = idx
            break
        if match_idx is not None:
            owned_pool.pop(match_idx)
        else:
            unmatched_canonical.append(m)

    # Pass 2 - year fallback, for titles that never matched at all (an
    # alternate/regional Plex title - "Fast & Furious 7" vs the researched
    # "Furious 7", "A Simple Favour" vs "A Simple Favor"). Only applied when
    # the year uniquely identifies one film on each remaining side, so it
    # can't silently pair up two different films that merely share a year.
    owned_year_counts: dict = {}
    for i in owned_pool:
        owned_year_counts[i.get("year")] = owned_year_counts.get(i.get("year"), 0) + 1
    canon_year_counts: dict = {}
    for m in unmatched_canonical:
        canon_year_counts[m.get("year")] = canon_year_counts.get(m.get("year"), 0) + 1

    still_missing = []
    for m in unmatched_canonical:
        year = m.get("year")
        if year is not None and owned_year_counts.get(year, 0) == 1 and canon_year_counts.get(year, 0) == 1:
            continue
        still_missing.append(m)
    return still_missing


def cmd_report(args: argparse.Namespace) -> None:
    collections = load(args.collections)["collections"]
    cache = load(args.cache)
    by_title = {_norm_title(c["title"]): c for c in collections}

    incomplete = []
    complete = 0
    for title, entry in sorted(cache.items()):
        collection = by_title.get(_norm_title(title))
        if collection is None:
            # Collection no longer exists in Plex (renamed/deleted) - nothing to report.
            continue
        canonical = entry.get("canonical", [])
        missing = _missing_for_collection(canonical, collection["items"])
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
