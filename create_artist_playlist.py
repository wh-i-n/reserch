"""Create a public Spotify playlist containing every track by a set of artists.

Reads `artists.txt` (one Spotify artist ID per line, lines starting with `#`
are treated as comments), gathers every album / single / compilation, then
adds every unique track to a new public playlist.

Usage:
    export SPOTIPY_CLIENT_ID=...
    export SPOTIPY_CLIENT_SECRET=...
    export SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
    python create_artist_playlist.py --name "srwks. JAPAN TOUR Day1 出演者全曲"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "playlist-modify-public"
ALBUM_GROUPS = "album,single,compilation"
MARKET = "JP"


def load_artist_ids(path: Path) -> list[str]:
    ids: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.search(r"(?:artist[/:])?([0-9A-Za-z]{22})", line)
        if not match:
            print(f"warn: skipping unparseable line: {line!r}", file=sys.stderr)
            continue
        ids.append(match.group(1))
    return ids


def all_pages(sp: spotipy.Spotify, first):
    page = first
    while page:
        for item in page["items"]:
            yield item
        page = sp.next(page) if page.get("next") else None


def collect_album_ids(sp: spotipy.Spotify, artist_id: str) -> list[str]:
    first = sp.artist_albums(
        artist_id,
        album_type=ALBUM_GROUPS,
        country=MARKET,
        limit=50,
    )
    seen: set[str] = set()
    for album in all_pages(sp, first):
        if album["id"] not in seen:
            seen.add(album["id"])
    return list(seen)


def collect_track_uris(
    sp: spotipy.Spotify, album_ids: list[str], artist_id: str
) -> list[tuple[str, str]]:
    """Return (track_uri, dedupe_key) for every track on the given albums
    where the artist appears as a credited artist."""
    results: list[tuple[str, str]] = []
    for i in range(0, len(album_ids), 20):
        batch = album_ids[i : i + 20]
        albums = sp.albums(batch, market=MARKET)["albums"]
        for album in albums:
            if album is None:
                continue
            for track in album["tracks"]["items"]:
                if not any(a["id"] == artist_id for a in track["artists"]):
                    continue
                name = track["name"].lower()
                key = re.sub(r"\s+", " ", name).strip()
                results.append((track["uri"], key))
    return results


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a public Spotify playlist of every track by listed artists.")
    parser.add_argument("--name", required=True, help="Playlist name")
    parser.add_argument("--description", default="", help="Playlist description")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("artists.txt"),
        help="Path to a text file with one Spotify artist ID (or URL) per line",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"error: {args.file} not found", file=sys.stderr)
        return 1

    artist_ids = load_artist_ids(args.file)
    if not artist_ids:
        print("error: no artist IDs found", file=sys.stderr)
        return 1

    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPE))
    me = sp.current_user()

    track_uris: list[str] = []
    seen_keys: set[str] = set()

    for artist_id in artist_ids:
        artist = sp.artist(artist_id)
        print(f"\n# {artist['name']} ({artist_id})")
        album_ids = collect_album_ids(sp, artist_id)
        print(f"  albums: {len(album_ids)}")
        for uri, key in collect_track_uris(sp, album_ids, artist_id):
            dedupe = f"{artist_id}::{key}"
            if dedupe in seen_keys:
                continue
            seen_keys.add(dedupe)
            track_uris.append(uri)
        print(f"  total unique tracks so far: {len(track_uris)}")

    playlist = sp.user_playlist_create(
        user=me["id"],
        name=args.name,
        public=True,
        description=args.description,
    )
    print(f"\ncreated playlist: {playlist['external_urls']['spotify']}")

    for batch in chunked(track_uris, 100):
        sp.playlist_add_items(playlist["id"], batch)

    print(f"added {len(track_uris)} tracks across {len(artist_ids)} artists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
