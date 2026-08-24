---
name: sync-collections
description: Regroups the Plex movie library into franchise/series collections (3+ owned entries), and deletes any collection left with only one item, anywhere in the library. Use when the user asks to sync, refresh, or clean up their Plex collections, or runs /sync-collections.
---

# /sync-collections

Syncs Plex collections in the "Films" library to match film franchises,
using `plex-collection-manager` (the plexapi CLI at
`src/plex_collection_manager/plex_tool.py` — the only thing that talks to
Plex) and `plex-sync-logic` (pure local diff/planning logic at
`src/plex_collection_manager/sync_logic.py`).

Run all `uv run` commands below from the project root
(`/Users/samlunn/Code/Plex/plex-collection-manager`) with the environment
loaded: `PLEX_TOKEN` from `.envrc` and `PLEX_BASE_URL=http://192.168.1.7:32400`.
Use a scratch directory for the intermediate JSON files, e.g.
`/tmp/plex-sync/`.

## 1. Snapshot current state

```bash
uv run plex-collection-manager movies > /tmp/plex-sync/movies.json
uv run plex-collection-manager collections > /tmp/plex-sync/collections.json
```

## 2. Find unclassified movies

The franchise cache lives at `data/franchise_cache.json` (create the `data/`
dir and an empty `{}` file if it doesn't exist yet — do not delete or reset
an existing cache).

```bash
uv run plex-sync-logic unclassified /tmp/plex-sync/movies.json data/franchise_cache.json
```

This returns `{"unclassified": [...], "known_franchises": [...]}`. If
`unclassified` is empty, skip to step 4.

## 3. Classify unclassified movies

Split `unclassified` into batches of **~150 movies**. Process batches
**sequentially, not in parallel** — each batch must see the franchise names
already known (including ones discovered by earlier batches in this same
run) so naming stays consistent across the whole library instead of drifting
between batches.

For each batch:

1. Launch the `franchise-classifier` subagent (via the `Agent` tool) with the
   batch's movies and the current known-franchise-name list (merge in any
   new names produced by prior batches this run) in the prompt. Ask it to
   return the JSON array described in its own instructions — nothing else.
2. Write its JSON output to a temp file, e.g. `/tmp/plex-sync/batch-N.json`.
3. Merge it into the cache immediately (so progress isn't lost if
   interrupted):

   ```bash
   uv run plex-sync-logic merge-cache data/franchise_cache.json /tmp/plex-sync/batch-N.json
   ```
4. Update your running known-franchise-name list from this batch's new
   franchise values before starting the next batch.

## 4. Compute the plan

```bash
uv run plex-sync-logic plan /tmp/plex-sync/movies.json /tmp/plex-sync/collections.json data/franchise_cache.json > /tmp/plex-sync/plan.json
```

This produces `{"creates": [...], "adds": [...], "removes": [...], "deletes": [...]}`:

- `creates` — new franchise collections to make (title + full member list; a
  franchise only appears here once the library owns 3+ of its films).
- `adds` — movies to add to an existing collection that already matches a
  franchise name.
- `removes` — movies to remove from an existing franchise-matched collection
  that no longer belong (rare; only happens if a movie's classification
  changed since the collection was last synced).
- `deletes` — **any** collection in the library, franchise-related or not,
  left with 0 or 1 items. This is intentionally global per the user's
  choice: it also cleans up unrelated single-item collections (including
  ones this tool never created), not just ones tied to a franchise.

## 5. Present the plan and confirm

Summarize the plan for the user in plain language (counts and a few example
titles per bucket is enough for large plans — don't dump all 40+ lines
verbatim). `creates` and `adds` are low-risk/reversible; `removes` and
especially `deletes` are not (deleting a collection loses any custom
artwork/summary/sort order on it). **Ask the user to confirm before
executing any `removes` or `deletes`.** You may proceed with `creates` and
`adds` without waiting, but it's fine to do everything in one confirmation
if that's simpler for the user.

## 6. Execute

Loop over the plan and call the CLI for each entry:

```bash
# creates
uv run plex-collection-manager create-collection --title "<title>" --keys <comma-separated keys>

# adds
uv run plex-collection-manager add-to-collection --key <collection_key> --movie-key <movie_key>

# removes
uv run plex-collection-manager remove-from-collection --key <collection_key> --movie-key <movie_key>

# deletes
uv run plex-collection-manager delete-collection --key <collection_key>
```

## 7. Report

Tell the user what changed: collections created (with titles), movies
added/removed, and collections deleted (with titles) — plus how many movies
are now cached/classified in total for next time.

## Notes for re-runs

- The cache means re-running this skill after adding a few new movies only
  classifies the new ones — steps 1, 2 and 4 are cheap; step 3 does little
  or nothing if nothing new was added.
- Running with no library changes should produce an empty plan (all four
  lists empty) — this is the expected idempotent result, not a bug.
- If the user wants this to run automatically on a schedule, point them at
  the `schedule` skill to register `/sync-collections` on a cadence of their
  choosing — don't set up a schedule unprompted.
