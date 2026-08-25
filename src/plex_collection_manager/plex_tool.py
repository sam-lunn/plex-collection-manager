"""Thin CLI wrapper around plexapi.

This is the only code in the project allowed to talk to the Plex server.
It exposes read-only listing of movies/shows/collections, plus exactly
six mutating operations: create/edit/delete collection, add/remove an
item from a collection, and edit a show's tagline. Nothing else (no other
metadata edits, no deletes of media, no touching libraries other than the
configured movie and TV sections).

All commands print JSON to stdout on success and a JSON error object to
stderr with a non-zero exit code on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from plexapi.server import PlexServer


def _server() -> PlexServer:
    base_url = os.environ.get("PLEX_BASE_URL", "http://192.168.1.7:32400")
    token = os.environ.get("PLEX_TOKEN")
    if not token:
        raise SystemExit("PLEX_TOKEN environment variable is not set")
    return PlexServer(base_url, token)


def _movie_section(server: PlexServer):
    library_name = os.environ.get("PLEX_LIBRARY_NAME", "Films")
    return server.library.section(library_name)


def _tv_section(server: PlexServer):
    library_name = os.environ.get("PLEX_TV_LIBRARY_NAME", "TV Programmes")
    return server.library.section(library_name)


def _item_json(item) -> dict:
    return {
        "key": item.ratingKey,
        "title": item.title,
        "year": item.year,
        "guid": item.guid,
    }


def _show_json(show) -> dict:
    return {
        "key": show.ratingKey,
        "title": show.title,
        "year": show.year,
        "guid": show.guid,
        "originallyAvailableAt": str(show.originallyAvailableAt) if show.originallyAvailableAt else None,
        "leafCount": show.leafCount,
        "tagline": show.tagline or "",
    }


def _collection_json(collection) -> dict:
    items = collection.items()
    return {
        "key": collection.ratingKey,
        "title": collection.title,
        "summary": collection.summary,
        "itemCount": len(items),
        "items": [_item_json(m) for m in items],
    }


def cmd_movies(args: argparse.Namespace) -> dict:
    server = _server()
    section = _movie_section(server)
    return {"movies": [_item_json(m) for m in section.all()]}


def cmd_movie_collections(args: argparse.Namespace) -> dict:
    server = _server()
    section = _movie_section(server)
    return {"collections": [_collection_json(c) for c in section.collections()]}


def cmd_shows(args: argparse.Namespace) -> dict:
    server = _server()
    section = _tv_section(server)
    return {"shows": [_show_json(s) for s in section.all()]}


def cmd_tv_collections(args: argparse.Namespace) -> dict:
    server = _server()
    section = _tv_section(server)
    return {"collections": [_collection_json(c) for c in section.collections()]}


def cmd_create_collection(args: argparse.Namespace) -> dict:
    server = _server()
    section = _tv_section(server) if args.library == "tv" else _movie_section(server)
    keys = [int(k) for k in args.keys.split(",") if k.strip()]
    items = [server.fetchItem(k) for k in keys]
    collection = section.createCollection(title=args.title, items=items)
    return _collection_json(collection)


def cmd_edit_collection(args: argparse.Namespace) -> dict:
    server = _server()
    collection = server.fetchItem(args.key)
    if args.title is not None:
        collection.editTitle(args.title)
    if args.summary is not None:
        collection.editSummary(args.summary)
    collection.reload()
    return _collection_json(collection)


def cmd_delete_collection(args: argparse.Namespace) -> dict:
    server = _server()
    collection = server.fetchItem(args.key)
    title = collection.title
    collection.delete()
    return {"deleted": True, "key": args.key, "title": title}


def cmd_add_to_collection(args: argparse.Namespace) -> dict:
    server = _server()
    collection = server.fetchItem(args.key)
    movie = server.fetchItem(args.movie_key)
    collection.addItems([movie])
    collection.reload()
    return _collection_json(collection)


def cmd_remove_from_collection(args: argparse.Namespace) -> dict:
    server = _server()
    collection = server.fetchItem(args.key)
    movie = server.fetchItem(args.movie_key)
    collection.removeItems([movie])
    collection.reload()
    return _collection_json(collection)


def cmd_edit_show(args: argparse.Namespace) -> dict:
    server = _server()
    show = server.fetchItem(args.key)
    show.editTagline(args.tagline, locked=True)
    show.reload()
    return _show_json(show)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plex-collection-manager")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("movies", help="List all movies in the library").set_defaults(func=cmd_movies)
    sub.add_parser("movie-collections", help="List all collections in the movie library").set_defaults(func=cmd_movie_collections)
    sub.add_parser("shows", help="List all shows in the TV library").set_defaults(func=cmd_shows)
    sub.add_parser("tv-collections", help="List all collections in the TV library").set_defaults(func=cmd_tv_collections)

    p = sub.add_parser("create-collection", help="Create a collection from a list of item keys")
    p.add_argument("--title", required=True)
    p.add_argument("--keys", required=True, help="Comma-separated ratingKeys")
    p.add_argument("--library", choices=["movies", "tv"], default="movies", help="Which library section to create the collection in")
    p.set_defaults(func=cmd_create_collection)

    p = sub.add_parser("edit-collection", help="Rename and/or re-summarize a collection")
    p.add_argument("--key", required=True, type=int)
    p.add_argument("--title")
    p.add_argument("--summary")
    p.set_defaults(func=cmd_edit_collection)

    p = sub.add_parser("delete-collection", help="Delete a collection")
    p.add_argument("--key", required=True, type=int)
    p.set_defaults(func=cmd_delete_collection)

    p = sub.add_parser("add-to-collection", help="Add a movie to a collection")
    p.add_argument("--key", required=True, type=int, help="Collection ratingKey")
    p.add_argument("--movie-key", required=True, type=int, help="Movie ratingKey")
    p.set_defaults(func=cmd_add_to_collection)

    p = sub.add_parser("remove-from-collection", help="Remove a movie from a collection")
    p.add_argument("--key", required=True, type=int, help="Collection ratingKey")
    p.add_argument("--movie-key", required=True, type=int, help="Movie ratingKey")
    p.set_defaults(func=cmd_remove_from_collection)

    p = sub.add_parser("edit-show", help="Set a show's tagline (locked, so metadata refreshes won't overwrite it)")
    p.add_argument("--key", required=True, type=int, help="Show ratingKey")
    p.add_argument("--tagline", required=True)
    p.set_defaults(func=cmd_edit_show)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
    except Exception as exc:  # noqa: BLE001 - surface all errors as JSON to the caller
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
