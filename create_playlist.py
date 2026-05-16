"""Create a public Spotify playlist from a list of song queries.

Usage:
    1. pip install -r requirements.txt
    2. Register an app at https://developer.spotify.com/dashboard
       and set its Redirect URI to http://127.0.0.1:8888/callback
    3. Export credentials:
           export SPOTIPY_CLIENT_ID=...
           export SPOTIPY_CLIENT_SECRET=...
           export SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
    4. Edit songs.txt (one "song name - artist" per line) or pass --file
    5. python create_playlist.py --name "My Playlist" --file songs.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "playlist-modify-public"


def load_queries(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def search_track(sp: spotipy.Spotify, query: str) -> str | None:
    result = sp.search(q=query, type="track", limit=1)
    items = result.get("tracks", {}).get("items", [])
    if not items:
        return None
    return items[0]["uri"]


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a public Spotify playlist.")
    parser.add_argument("--name", required=True, help="Playlist name")
    parser.add_argument("--description", default="", help="Playlist description")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("songs.txt"),
        help="Path to a text file with one search query per line",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"error: {args.file} not found", file=sys.stderr)
        return 1

    queries = load_queries(args.file)
    if not queries:
        print("error: no queries found in file", file=sys.stderr)
        return 1

    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPE))
    user_id = sp.current_user()["id"]

    playlist = sp.user_playlist_create(
        user=user_id,
        name=args.name,
        public=True,
        description=args.description,
    )
    playlist_id = playlist["id"]
    print(f"created playlist: {playlist['external_urls']['spotify']}")

    track_uris: list[str] = []
    for query in queries:
        uri = search_track(sp, query)
        if uri:
            track_uris.append(uri)
            print(f"  found: {query}")
        else:
            print(f"  miss : {query}")

    for batch in chunked(track_uris, 100):
        sp.playlist_add_items(playlist_id, batch)

    print(f"added {len(track_uris)} / {len(queries)} tracks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
