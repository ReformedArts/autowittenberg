"""One-time setup: connect AutoWittenberg to your Pinterest account.

Opens Pinterest's approval page in your browser. After you click "Give access",
Pinterest sends you back to a temporary page on your own computer, which captures the
approval code, swaps it for access tokens, and saves them to your .env file.
Tokens are never printed.

Run with:   .venv/bin/python pinterest_authorize.py            (real Pinterest)
            .venv/bin/python pinterest_authorize.py --sandbox   (Pinterest practice environment)
"""
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from autowittenberg import config
from autowittenberg.pinterest import PinterestError, exchange_code_for_token

PORT = 8085
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = "boards:read,boards:write,pins:read,pins:write"


class _CallbackHandler(BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if urlparse(self.path).path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        _CallbackHandler.result = {k: v[0] for k, v in query.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font-family:sans-serif;padding:40px'>"
            b"<h2>Pinterest connected.</h2>"
            b"<p>You can close this tab and go back to the Terminal.</p></body></html>"
        )

    def log_message(self, *args):
        pass


def main():
    sandbox = "--sandbox" in sys.argv
    app_id = config.require("PINTEREST_APP_ID")
    config.require("PINTEREST_APP_SECRET")

    state = secrets.token_urlsafe(16)
    auth_url = "https://www.pinterest.com/oauth/?" + urlencode({
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    })

    server = HTTPServer(("localhost", PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("\nOpening Pinterest in your browser. Click 'Give access' to approve.")
    print("(If it doesn't open on its own, copy this link into your browser:)\n")
    print(auth_url + "\n")
    webbrowser.open(auth_url)

    thread.join(timeout=300)
    server.server_close()
    result = _CallbackHandler.result

    if not result:
        raise SystemExit("Timed out waiting for Pinterest approval (5 minutes). Run this again to retry.")
    if result.get("state") != state:
        raise SystemExit("Security check failed (state mismatch). Nothing was saved. Run this again.")
    if "code" not in result:
        raise SystemExit(f"Pinterest did not approve the request: {result.get('error_description') or result}")

    try:
        tokens = exchange_code_for_token(result["code"], REDIRECT_URI, sandbox=sandbox)
    except PinterestError as e:
        raise SystemExit(f"\nCould not get tokens from Pinterest:\n  {e}\n")

    prefix = "PINTEREST_SANDBOX_" if sandbox else "PINTEREST_"
    config.save_to_env_file(f"{prefix}ACCESS_TOKEN", tokens["access_token"])
    if tokens.get("refresh_token"):
        config.save_to_env_file(f"{prefix}REFRESH_TOKEN", tokens["refresh_token"])

    print("\nSuccess. Pinterest is connected and the tokens were saved to your .env file.")
    print(f"Permissions granted: {tokens.get('scope')}")


if __name__ == "__main__":
    main()
