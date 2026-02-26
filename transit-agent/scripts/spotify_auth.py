#!/usr/bin/env python3
"""
One-time OAuth to get SPOTIFY_REFRESH_TOKEN. Run from transit-agent with .env containing
SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. Register redirect URI in Spotify Dashboard:
  http://127.0.0.1:8767/callback
Then run: python scripts/spotify_auth.py
Visit http://127.0.0.1:8767 and log in; the script prints the refresh token to add to .env.
Uses only stdlib + httpx (no aiohttp).
"""

import base64
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Add parent so config loads
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import config

# Must match exactly what you add in Spotify Dashboard → App → Settings → Redirect URIs
REDIRECT_URI = (config.SPOTIFY_REDIRECT_URI or "http://127.0.0.1:8767/callback").strip()
SCOPE = "user-modify-playback-state user-read-playback-state user-read-private streaming"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

refresh_token_result: list[str] = []


def basic_auth() -> str:
    raw = f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}"
    return base64.b64encode(raw.encode()).decode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "":
            if not config.SPOTIFY_CLIENT_ID:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env first.")
                return
            url = (
                f"{AUTH_URL}?response_type=code&client_id={config.SPOTIFY_CLIENT_ID}"
                f"&redirect_uri={REDIRECT_URI}&scope={SCOPE.replace(' ', '%20')}"
            )
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()
            return
        if parsed.path == "/callback":
            qs = parse_qs(parsed.query)
            code = (qs.get("code") or [None])[0]
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Missing code")
                return
            r = httpx.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {basic_auth()}",
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Token exchange failed: {r.status_code}\n{r.text}".encode())
                return
            data = r.json()
            refresh = data.get("refresh_token")
            if refresh:
                refresh_token_result.append(refresh)
            body = f"<h1>Success</h1><p>Add this to your .env:</p><pre>SPOTIFY_REFRESH_TOKEN={refresh or ''}</pre><p>Then restart the agent. You can close this tab.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main() -> None:
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        print("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in transit-agent/.env")
        print("Create an app at https://developer.spotify.com/dashboard")
        print("Add redirect URI: http://127.0.0.1:8767/callback")
        return
    # Parse host/port from redirect URI so Dashboard and server match
    from urllib.parse import urlparse
    parsed = urlparse(REDIRECT_URI)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8767
    print("Redirect URI (must match Spotify Dashboard *exactly*):")
    print(f"  {REDIRECT_URI}")
    print("In Dashboard: Your App → Settings → Redirect URIs → Add → Save")
    print()
    server = HTTPServer((host, port), Handler)
    print(f"Open {REDIRECT_URI.replace('/callback', '')} in your browser and log in with Spotify (Premium required for playback).")
    while not refresh_token_result:
        server.handle_request()
    if refresh_token_result:
        print("\nAdd to transit-agent/.env:")
        print(f"SPOTIFY_REFRESH_TOKEN={refresh_token_result[0]}")


if __name__ == "__main__":
    main()
