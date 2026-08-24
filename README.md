# plex-collection-manager

Groups your Plex movie library into collections by film franchise/series
(3+ owned entries), and removes any collection left with only one item.
This only ever touches the movie library section — it never looks at or
modifies TV show collections.

## Setup

```bash
uv sync
```

Requires `PLEX_TOKEN` in `.envrc` (loaded via direnv) and a reachable Plex
server (defaults to `http://192.168.1.7:32400`, override with
`PLEX_BASE_URL`). Targets the library section named `Films` by default
(override with `PLEX_LIBRARY_NAME`).

## Usage

### Interactively

In Claude Code, run `/sync-movie-collections`. See
`.claude/skills/sync-movie-collections/SKILL.md` for what it does: it snapshots
your library, classifies any new movies into franchises (using the
`movie-franchise-classifier` subagent — model knowledge + web search, cached in
`data/franchise_cache.json` so repeat runs only classify new additions),
shows you the create/add/remove/delete plan, and applies it after you
confirm.

### From the command line

The classification step needs the model, so a full sync isn't a plain
deterministic script — but you can still trigger the whole `/sync-movie-collections`
flow from an ordinary shell (no interactive session) using Claude Code's
headless mode:

```bash
cd /Users/samlunn/Code/Plex/plex-collection-manager
claude -p "/sync-movie-collections"
```

That runs non-interactively and prints the result. By default it will still
pause to confirm before deleting or removing anything; add a permission mode
flag (e.g. `--permission-mode acceptEdits`) if you want it to proceed through
those without asking, such as when running from a script or cron.

The Plex-facing CLI (`plex-collection-manager`) and the pure local planning
logic (`plex-sync-logic`) can also be run directly, without any AI step, for
manual inspection or scripting — though on their own they don't know which
movies belong to which franchise:

```bash
uv run plex-collection-manager movies
uv run plex-collection-manager collections
uv run plex-sync-logic plan movies.json collections.json data/franchise_cache.json
```

### Scheduling

To run the sync automatically on a recurring schedule (e.g. weekly), use
Claude Code's `schedule` skill from within a session in this project:

```
/schedule
```

Follow its prompts to create a routine that runs `/sync-movie-collections` on
whatever cadence you want (e.g. `claude -p "/sync-movie-collections"` on a
weekly cron). It's not scheduled by default — this has to be set up
explicitly.
