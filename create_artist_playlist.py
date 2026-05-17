"""Create a public Spotify playlist from a set of artists.

Reads `artists.txt`. Each non-comment line is:

    <artist_id_or_url>  [mode]  [# optional comment]

where `mode` is one of:
    all          — include every credited track
    top:N        — include the N most popular tracks
    (omitted)    — falls back to --default-top

Usage:
    # interactive (developer machine, opens a browser once):
    export SPOTIPY_CLIENT_ID=...
    export SPOTIPY_CLIENT_SECRET=...
    export SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
    python create_artist_playlist.py --name "出演者プレイリスト" --default-top 12

    # headless (cloud / Android-driven Claude sessions): also set
    # SPOTIPY_REFRESH_TOKEN. Obtain it from the `.cache` file produced by the
    # interactive run above.
    export SPOTIPY_REFRESH_TOKEN=AQA...
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "playlist-modify-public"
ALBUM_GROUPS = "album,single,compilation"
MARKET = "JP"


def build_spotify_client() -> spotipy.Spotify:
    """Authenticate against Spotify.

    Headless mode: if SPOTIPY_REFRESH_TOKEN is set, refresh an access token
    directly — no browser, suitable for cloud/CI runs.

    Interactive mode: fall back to SpotifyOAuth's full code flow, which spins
    up a local callback server. Use this on a developer machine the first time
    to obtain the refresh token (read it out of `.cache` afterwards).
    """
    refresh_token = os.environ.get("SPOTIPY_REFRESH_TOKEN")
    if refresh_token:
        client_id = os.environ["SPOTIPY_CLIENT_ID"]
        client_secret = os.environ["SPOTIPY_CLIENT_SECRET"]
        oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=os.environ.get(
                "SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
            ),
            scope=SCOPE,
        )
        token_info = oauth.refresh_access_token(refresh_token)
        return spotipy.Spotify(auth=token_info["access_token"])
    return spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPE))


@dataclass
class ArtistSpec:
    artist_id: str
    mode: str  # "all" or "top"
    top_n: int  # only used when mode == "top"


def parse_artists_file(path: Path, default_top: int) -> list[ArtistSpec]:
    specs: list[ArtistSpec] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        body = raw.split("#", 1)[0].strip()
        if not body:
            continue
        tokens = body.split()
        id_match = re.search(r"(?:artist[/:])?([0-9A-Za-z]{22})", tokens[0])
        if not id_match:
            print(f"warn: skipping unparseable line: {raw!r}", file=sys.stderr)
            continue
        artist_id = id_match.group(1)
        mode = "top"
        top_n = default_top
        if len(tokens) >= 2:
            spec = tokens[1].lower()
            if spec == "all":
                mode = "all"
            elif spec.startswith("top:"):
                mode = "top"
                top_n = int(spec.split(":", 1)[1])
            else:
                print(f"warn: unknown mode {spec!r} on line {raw!r}", file=sys.stderr)
        specs.append(ArtistSpec(artist_id=artist_id, mode=mode, top_n=top_n))
    return specs


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
    return list({album["id"] for album in all_pages(sp, first)})


def collect_track_ids(
    sp: spotipy.Spotify, album_ids: list[str], artist_id: str
) -> list[tuple[str, str]]:
    """Return (track_id, dedupe_key) for tracks credited to the artist."""
    results: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for i in range(0, len(album_ids), 20):
        batch = album_ids[i : i + 20]
        albums = sp.albums(batch, market=MARKET)["albums"]
        for album in albums:
            if album is None:
                continue
            for track in album["tracks"]["items"]:
                if not any(a["id"] == artist_id for a in track["artists"]):
                    continue
                key = re.sub(r"\s+", " ", track["name"].lower()).strip()
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                results.append((track["id"], key))
    return results


def hydrate_popularity(sp: spotipy.Spotify, track_ids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in range(0, len(track_ids), 50):
        chunk = track_ids[i : i + 50]
        for t in sp.tracks(chunk, market=MARKET)["tracks"]:
            if t is None:
                continue
            out[t["id"]] = t.get("popularity", 0)
    return out


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a public Spotify playlist from listed artists."
    )
    parser.add_argument("--name", required=True, help="Playlist name")
    parser.add_argument("--description", default="", help="Playlist description")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("artists.txt"),
        help="Path to a text file with one Spotify artist ID per line",
    )
    parser.add_argument(
        "--default-top",
        type=int,
        default=10,
        help="Fallback top-N for artists with no explicit mode",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"error: {args.file} not found", file=sys.stderr)
        return 1

    specs = parse_artists_file(args.file, args.default_top)
    if not specs:
        print("error: no artist IDs found", file=sys.stderr)
        return 1

    sp = build_spotify_client()
    me = sp.current_user()

    track_uris: list[str] = []
    seen_uris: set[str] = set()

    for spec in specs:
        artist = sp.artist(spec.artist_id)
        mode_label = "all" if spec.mode == "all" else f"top:{spec.top_n}"
        print(f"\n# {artist['name']} ({spec.artist_id}) [{mode_label}]")

        album_ids = collect_album_ids(sp, spec.artist_id)
        print(f"  albums: {len(album_ids)}")
        tracks = collect_track_ids(sp, album_ids, spec.artist_id)
        print(f"  unique tracks: {len(tracks)}")

        if spec.mode == "top":
            track_ids = [tid for tid, _ in tracks]
            pop = hydrate_popularity(sp, track_ids)
            tracks.sort(key=lambda x: pop.get(x[0], 0), reverse=True)
            tracks = tracks[: spec.top_n]
            print(f"  keeping top {len(tracks)} by popularity")

        for tid, _ in tracks:
            uri = f"spotify:track:{tid}"
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            track_uris.append(uri)

    playlist = sp.user_playlist_create(
        user=me["id"],
        name=args.name,
        public=True,
        description=args.description,
    )
    print(f"\ncreated playlist: {playlist['external_urls']['spotify']}")

    for batch in chunked(track_uris, 100):
        sp.playlist_add_items(playlist["id"], batch)

    print(f"added {len(track_uris)} tracks total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
