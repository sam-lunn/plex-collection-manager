---
name: sync-tv-collections
description: Sorts every show in the Plex TV library into exactly one of four fixed collections (Ongoing, Ended Poorly, Ended Okay, Ended Well) based on whether it has ended and how well its ending was received. Never touches any other collection and never deletes a collection. Use when the user asks to sync, refresh, or classify their Plex TV show status collections, or runs /sync-tv-collections.
---

# /sync-tv-collections

Sorts shows in the "TV Programmes" library into exactly 4 fixed
collections — Ongoing, Ended Poorly, Ended Okay, Ended Well — using
`plex-collection-manager` (the plexapi CLI at
`src/plex_collection_manager/plex_tool.py` — the only thing that talks to
Plex) and `plex-tv-sync-logic` (pure local diff/planning logic at
`src/plex_collection_manager/tv_sync_logic.py`).

This is deliberately narrower than `/sync-movie-collections`: it **never**
touches any collection other than these 4 exact names, and it **never
deletes** a collection — `plex-tv-sync-logic plan`'s output has no
`deletes` key at all, so there's nothing to even loop over in step 6.

Run all `uv run` commands below from the project root
(`/Users/samlunn/Code/Plex/plex-collection-manager`) with the environment
loaded: `PLEX_TOKEN` from `.envrc` and `PLEX_BASE_URL=http://192.168.1.7:32400`.
Use a scratch directory for the intermediate JSON files, e.g.
`/tmp/plex-tv-sync/`.

## 1. Snapshot current state

```bash
uv run plex-collection-manager shows > /tmp/plex-tv-sync/shows.json
uv run plex-collection-manager tv-collections > /tmp/plex-tv-sync/collections.json
```

## 2. Find shows needing (re)classification

The status cache lives at `data/tv_status_cache.json` (create the `data/`
dir and an empty `{}` file if it doesn't exist yet — do not delete or
reset an existing cache).

```bash
uv run plex-tv-sync-logic unclassified /tmp/plex-tv-sync/shows.json data/tv_status_cache.json
```

This returns `{"to_classify": [...], "categories": [...]}`, where
`to_classify` includes: shows never classified before, shows currently
cached as "Ongoing" (always re-checked, since a show's status can change),
and shows cached as one of the 3 "Ended" buckets whose episode count has
grown since they were classified (a revival season or wrap-up special
filed as a new episode — see "Notes for re-runs" below). If
`to_classify` is empty, skip to step 4.

## 3. Classify

Split `to_classify` into batches of **~40 shows** (smaller than the movie
tool's ~150 — judging how an ending was received needs real per-show
research far more often than franchise-membership lookups do, so smaller
batches keep each subagent call focused). Unlike the movie classifier,
there's no "known names so far" list to thread between batches (the 4
categories are fixed), so batches have no ordering dependency — running
them sequentially is simplest for a first pass, but launching them in
parallel is safe here if you want it faster.

For each batch:

1. Launch the `tv-show-status-classifier` subagent (via the `Agent` tool)
   with the batch's shows in the prompt. Ask it to return the JSON array
   described in its own instructions — nothing else.
2. Write its JSON output to a temp file, e.g. `/tmp/plex-tv-sync/batch-N.json`.
3. Merge it into the cache immediately (so progress isn't lost if
   interrupted):

   ```bash
   uv run plex-tv-sync-logic merge-cache data/tv_status_cache.json /tmp/plex-tv-sync/batch-N.json /tmp/plex-tv-sync/shows.json
   ```

   (`merge-cache` takes the shows snapshot too — it records each show's
   *current* episode count into the cache itself, so the classifier never
   needs to know about or echo that bookkeeping.)

## 4. Compute the plan

```bash
uv run plex-tv-sync-logic plan /tmp/plex-tv-sync/shows.json /tmp/plex-tv-sync/collections.json data/tv_status_cache.json > /tmp/plex-tv-sync/plan.json
```

This produces `{"creates": [...], "adds": [...], "removes": [...]}` —
note there is no `deletes` key:

- `creates` — one of the 4 collections that doesn't exist yet but has at
  least one show belonging to it.
- `adds` — shows to add to an existing one of the 4 collections.
- `removes` — shows to remove from an existing one of the 4 collections
  because they no longer belong there (see below — this is normal here,
  not an edge case).

A category with zero shows and no existing collection is simply skipped
(never creates an empty collection). An existing collection that drains
to zero members via `removes` is left in place empty, not deleted.

## 5. Present the plan and confirm

Summarize the plan for the user in plain language. `creates` and `adds`
are low-risk/reversible and can proceed without waiting. **Ask the user to
confirm before executing `removes`** — nothing is ever destroyed, but a
`remove` does change collection membership (typically because a show
moved from one status bucket to another), so it shouldn't happen silently
the first time you show the user a plan. It's fine to do everything in
one confirmation if that's simpler for the user.

## 6. Execute

Loop over the plan and call the CLI for each entry (reusing `--movie-key`
for a show's ratingKey is intentional — the underlying Plex operation is
identical for any item type, and the flag name matches the movie tool's
existing convention):

```bash
# creates
uv run plex-collection-manager create-collection --title "<title>" --keys <comma-separated keys>

# adds
uv run plex-collection-manager add-to-collection --key <collection_key> --movie-key <show_key>

# removes
uv run plex-collection-manager remove-from-collection --key <collection_key> --movie-key <show_key>
```

There is no delete step — nothing in this workflow ever deletes a
collection.

## 7. Report

Tell the user what changed: collections created, shows added/removed per
bucket (and, if relevant, which shows moved from one bucket to another),
plus how many shows are now cached in total.

## Notes for re-runs

- Unlike the movie sync, don't expect an empty plan to become the norm
  long-term. Every run always re-checks currently-"Ongoing" shows (that
  pool doesn't shrink toward zero — new shows added to the library start
  life as Ongoing too, so it stabilizes around however many shows are
  actually airing, not zero) and any "Ended" show whose episode count grew
  since classification. A small steady trickle of `adds`/`removes` moving
  shows between buckets over time is expected behavior, not a bug.
- The episode-count staleness check has a known limitation: it only
  catches a revival filed as new episodes/seasons of the existing Plex
  show entry. A wrap-up film added as a separate item in the *Movies*
  library (not an episode of the show) won't trigger reclassification,
  since this feature only reads the TV library.
- Any pre-existing collection exactly named one of the 4 targets — even
  one the user made by hand with unrelated content — will be taken over
  and resynced to match. That's the point of the feature, but worth
  surfacing plainly the first time it happens for a given library.
- If the user wants this to run automatically on a schedule, point them
  at the `schedule` skill to register `/sync-tv-collections` on a cadence
  of their choosing — don't set up a schedule unprompted.
