"""Minimal client for the Pinterest API v5: OAuth token handling, boards, and posting pins."""
import base64
from pathlib import Path

import requests

from . import config

BASE_URL = "https://api.pinterest.com/v5"
SANDBOX_BASE_URL = "https://api-sandbox.pinterest.com/v5"
TIMEOUT = 30


class PinterestError(Exception):
    pass


def _basic_auth_header():
    client_id = config.require("PINTEREST_APP_ID")
    client_secret = config.require("PINTEREST_APP_SECRET")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    return {"Authorization": f"Basic {basic}"}


def exchange_code_for_token(code, redirect_uri, sandbox=False):
    """One-time exchange of an OAuth authorization code for an access + refresh token."""
    resp = requests.post(
        f"{SANDBOX_BASE_URL if sandbox else BASE_URL}/oauth/token",
        headers={**_basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "continuous_refresh": "true",
        },
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise PinterestError(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def refresh_access_token(refresh_token=None):
    """Exchanges a refresh token for a fresh access token + a new (rotated) refresh token.

    The continuous refresh token expires 60 days after it's last used, so this needs to
    run, and its new refresh_token needs to be saved, at least that often.
    """
    refresh_token = refresh_token or config.require("PINTEREST_REFRESH_TOKEN")
    resp = requests.post(
        f"{BASE_URL}/oauth/token",
        headers={**_basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise PinterestError(f"Token refresh failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


class PinterestClient:
    def __init__(self, access_token=None, sandbox=False):
        self.base_url = SANDBOX_BASE_URL if sandbox else BASE_URL
        token_name = "PINTEREST_SANDBOX_ACCESS_TOKEN" if sandbox else "PINTEREST_ACCESS_TOKEN"
        self.access_token = access_token or config.require(token_name)
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _request(self, method, path, **kwargs):
        resp = self.session.request(method, f"{self.base_url}{path}", timeout=TIMEOUT, **kwargs)
        if not resp.ok:
            raise PinterestError(f"Pinterest {method} {path} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def list_boards(self):
        boards, bookmark = [], None
        while True:
            params = {"page_size": 25}
            if bookmark:
                params["bookmark"] = bookmark
            data = self._request("GET", "/boards", params=params)
            boards.extend(data.get("items", []))
            bookmark = data.get("bookmark")
            if not bookmark:
                return boards

    def find_board(self, name):
        for board in self.list_boards():
            if board.get("name", "").strip().lower() == name.strip().lower():
                return board
        return None

    def create_board(self, name, description=""):
        return self._request("POST", "/boards", json={"name": name, "description": description})

    def get_or_create_board(self, name, description=""):
        return self.find_board(name) or self.create_board(name, description)

    def create_pin(self, board_id, image_path, title, description, link):
        image_bytes = Path(image_path).read_bytes()
        payload = {
            "board_id": board_id,
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode("ascii"),
            },
            "title": title[:100],
            "description": description[:500],
            "link": link,
        }
        return self._request("POST", "/pins", json=payload)
