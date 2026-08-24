---
name: find-incomplete-collections
description: Checks every franchise/series collection in the Plex movie library against its full canonical filmography and reports which owned collections are missing films. Read-only — never creates, edits, or deletes anything in Plex. Use when the user asks which movie collections are incomplete, what films they're missing from a series, or runs /find-incomplete-collections.
---

# /find-incomplete-collections

Reports which franchise collections in the "Films" library are missing
films, using `plex-collection-manager` (the plexapi CLI at
`src/plex_collection_manager/plex_tool.py` — the only thing that talks to
Plex, used here only for read-only listing) and `plex-movie-completeness-logic`
(pure local diff/planning logic at
`src/plex_collection_manager/movie_completeness_logic.py`).

This is **read-only**: it never creates, edits, adds to, removes from, or
deletes any Plex collection. It only reports what's missing so the user can
decide what to do about it.

Only collections whose title matches a known franchise name in
`cache/franchise_cache.json` (i.e. collections `/sync-movie-collections`
would recognize) are checked — a collection has to have a well-defined
canonical membership (a real film series) for "complete/incomplete" to mean
anything, so arbitrary hand-made collections (e.g. "Christmas Movies") are
skipped.

Run all `uv run` commands below from the project root
(`/Users/samlunn/Code/Plex/plex-collection-manager`) with the environment
loaded: `PLEX_TOKEN` from `.envrc` and `PLEX_BASE_URL=http://192.168.1.7:32400`.
Use a scratch directory for the intermediate JSON files, e.g.
`/tmp/plex-completeness/`.

## 1. Snapshot current state

```bash
uv run plex-collection-manager movie-collections > /tmp/plex-completeness/collections.json
```

`cache/franchise_cache.json` should already exist from prior
`/sync-movie-collections` runs — if it doesn't, run that skill first (this
skill has nothing to check against without it).

## 2. Find franchise collections not yet checked

The completeness cache lives at `cache/franchise_completeness_cache.json`
(create the `cache/` dir and an empty `{}` file if it doesn't exist yet —
do not delete or reset an existing cache).

```bash
uv run plex-movie-completeness-logic to-check /tmp/plex-completeness/collections.json cache/franchise_cache.json cache/franchise_completeness_cache.json
```

This returns `{"to_check": [...], "skipped_non_franchise": [...]}`. Each
`to_check` entry is a collection with its currently-owned titles/years. If
`to_check` is empty, skip to step 4.

Unlike the sync skills, there's no automatic "recheck" trigger here — once
a franchise's canonical filmography is cached, it's treated as still
correct on later runs (a franchise's full film list rarely changes, and the
report step in step 4 always re-diffs against whatever the user currently
owns, so newly-added or removed movies are reflected without needing a
fresh search). If the user specifically wants a franchise re-verified
(e.g. they suspect a new sequel was announced since it was last checked),
delete that franchise's entry from `cache/franchise_completeness_cache.json`
and re-run this skill.

## 3. Check

Split `to_check` into batches of **~25 collections** (research-heavy, like
the TV classifier, not a quick lookup). Process batches **sequentially**
to keep WebSearch usage predictable — this task burns search budget fast
since every collection needs a real filmography lookup, not just a
one-line fact check.

For each batch:

1. Launch the `movie-collection-completeness-checker` subagent (via the
   `Agent` tool) with the batch's collections in the prompt. Ask it to
   return the JSON array described in its own instructions — nothing else.
2. Write its JSON output to a temp file, e.g.
   `/tmp/plex-completeness/batch-N.json`.
3. If the subagent's response flags that it ran out of WebSearch budget or
   couldn't fully verify some collections, don't merge those specific
   collections into the cache — only merge the ones it actually confirmed.
   Note which were skipped so you can mention it to the user and re-run
   them later with a fresh budget.
4. Merge the confirmed results into the cache:

   ```bash
   uv run plex-movie-completeness-logic merge-cache cache/franchise_completeness_cache.json /tmp/plex-completeness/batch-N.json
   ```

## 4. Compute the report

```bash
uv run plex-movie-completeness-logic report /tmp/plex-completeness/collections.json cache/franchise_completeness_cache.json > /tmp/plex-completeness/report.json
```

This produces `{"incomplete": [...], "complete_count": <int>}`. Each
`incomplete` entry is `{"collection_key", "collection", "owned_count",
"missing": [{"title", "year", "released"}], "note", "checked_at"}`.

## 5. Report to the user

List each incomplete collection with what's missing — separate released
films (things they could actually go add) from announced/upcoming ones
(`"released": false`) so the two don't read as the same kind of gap.
Mention the total count of fully-complete collections too. If any
collections were skipped this run due to a WebSearch budget shortfall
(step 3), call those out separately as unverified rather than silently
omitting them.

## Notes for re-runs

- Re-running after the library changes (movies added/removed, or new
  collections created by `/sync-movie-collections`) only needs to check
  franchises that don't have a completeness-cache entry yet — step 1, 2,
  and 4 are cheap; step 3 does little or nothing if no new franchise
  collections appeared.
- If the user wants this to run automatically on a schedule, point them at
  the `schedule` skill to register `/find-incomplete-collections` on a
  cadence of their choosing — don't set up a schedule unprompted.
