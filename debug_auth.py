"""Diagnostic: run the Spotify OAuth flow and dump the full callback URL.

Use when you see `server_error` or other opaque OAuth failures and need the
real `error_description` from Spotify. Replaces spotipy's silent callback
handler with one that prints everything it received.

Usage (PowerShell):
    $env:SPOTIPY_CLIENT_ID = "..."
    $env:SPOTIPY_CLIENT_SECRET = "..."
    $env:SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
    python debug_auth.py
"""

from __future__ import annotations

import http.server
import os
import socketserver
import urllib.parse
import webbrowser

from spotipy.oauth2 import SpotifyOAuth

SCOPE = "playlist-modify-public"
PORT = 8888


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        print("\n=== RAW CALLBACK PATH ===")
        print(f"http://127.0.0.1:{PORT}{self.path}")

        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        print("\n=== PARSED QUERY PARAMS ===")
        if not params:
            print("  (none — Spotify did not include any query params)")
        for k, v in params.items():
            print(f"  {k}: {v[0] if v else ''}")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<h1>Captured</h1><p>Check the terminal for details. You can close this tab.</p>"
        )

    def log_message(self, format, *args):
        return


def main() -> int:
    redirect_uri = os.environ.get(
        "SPOTIPY_REDIRECT_URI", f"http://127.0.0.1:{PORT}/callback"
    )
    oauth = SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=redirect_uri,
        scope=SCOPE,
    )
    url = oauth.get_authorize_url()
    print(f"redirect_uri being used: {redirect_uri}")
    print(f"\nOpen this URL if the browser does not pop up:\n{url}\n")
    webbrowser.open(url)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), CaptureHandler) as httpd:
        print(f"Waiting for callback on http://127.0.0.1:{PORT}/callback (Ctrl+C to abort) ...")
        httpd.handle_request()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
