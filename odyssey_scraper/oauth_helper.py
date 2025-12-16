from __future__ import annotations

import argparse
import base64
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import requests


AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


class _CallbackState:
    def __init__(self) -> None:
        self.code: Optional[str] = None
        self.error: Optional[str] = None


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _build_authorize_url(*, client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": "permanent",
        "scope": " ".join(scopes),
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def _exchange_code_for_tokens(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    user_agent: str,
) -> dict:
    headers = {"Authorization": _basic_auth_header(client_id, client_secret), "User-Agent": user_agent}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def run_oauth_flow(*, client_id: str, client_secret: str, redirect_uri: str, user_agent: str) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("redirect_uri must be http://localhost:<port>/callback (or 127.0.0.1)")
    port = parsed.port or 8080
    path = parsed.path or "/callback"

    state = secrets.token_urlsafe(16)
    cb = _CallbackState()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            try:
                u = urllib.parse.urlparse(self.path)
                if u.path != path:
                    self.send_response(404)
                    self.end_headers()
                    return

                qs = urllib.parse.parse_qs(u.query)
                if qs.get("state", [""])[0] != state:
                    cb.error = "state_mismatch"
                elif "error" in qs:
                    cb.error = qs.get("error", ["unknown_error"])[0]
                else:
                    cb.code = qs.get("code", [""])[0] or None

                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                if cb.code:
                    self.wfile.write(b"OK. You can close this tab and return to the terminal.\n")
                else:
                    self.wfile.write(b"OAuth failed. Return to the terminal for details.\n")
            except Exception:
                cb.error = "handler_exception"
                self.send_response(500)
                self.end_headers()

        def log_message(self, format, *args):  # noqa: A003
            # Silence default HTTP server logs
            return

    server = HTTPServer(("127.0.0.1", port), Handler)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    scopes = ["identity", "read"]
    url = _build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, scopes=scopes, state=state)
    print("\n1) Open this URL in your browser (logged into the account with subreddit access):\n")
    print(url)
    print("\n2) Click 'Allow'. You should be redirected back to localhost.\n")

    start = time.time()
    while time.time() - start < 180:
        if cb.code or cb.error:
            break
        time.sleep(0.25)

    server.shutdown()

    if cb.error:
        raise RuntimeError(f"OAuth error: {cb.error}")
    if not cb.code:
        raise RuntimeError("Timed out waiting for OAuth callback.")

    tokens = _exchange_code_for_tokens(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code=cb.code,
        user_agent=user_agent,
    )
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError(f"No refresh_token returned. Response keys: {list(tokens.keys())}")
    return str(refresh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Get a Reddit refresh token for Odyssey scraper")
    parser.add_argument("--client-id", default=os.getenv("REDDIT_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("REDDIT_CLIENT_SECRET"))
    parser.add_argument("--redirect-uri", default=os.getenv("REDDIT_REDIRECT_URI", "http://localhost:8080/callback"))
    parser.add_argument("--user-agent", default=os.getenv("REDDIT_USER_AGENT", "odyssey-scraper/1.0"))
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        raise RuntimeError("Missing --client-id/--client-secret (or set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET).")

    refresh = run_oauth_flow(
        client_id=args.client_id,
        client_secret=args.client_secret,
        redirect_uri=args.redirect_uri,
        user_agent=args.user_agent,
    )
    print("\nRefresh token (store this as REDDIT_REFRESH_TOKEN):\n")
    print(refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




