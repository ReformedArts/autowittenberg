"""Keeps the Pinterest sign-in fresh when running in the cloud.

Pinterest's refresh token changes each time it is used, so the newest one has to be saved
somewhere between runs. It is stored encrypted in data/pinterest_tokens.enc; the key that
unlocks it lives only in the TOKEN_VAULT_KEY secret, never in the repository.
Without TOKEN_VAULT_KEY (normal use on your own computer) this does nothing and the
tokens in .env are used as-is.
"""
import datetime as dt
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

from . import config
from .pinterest import refresh_access_token

VAULT_PATH = Path(__file__).parent.parent / "data" / "pinterest_tokens.enc"
REFRESH_AFTER_DAYS = 7  # access tokens last 30 days and refresh tokens 60; weekly keeps both well inside


def ensure_fresh_tokens(log=print):
    key = config.optional("TOKEN_VAULT_KEY")
    if not key:
        return
    vault = Fernet(key.encode())
    data = json.loads(vault.decrypt(VAULT_PATH.read_bytes())) if VAULT_PATH.exists() else None
    now = dt.datetime.now(dt.timezone.utc)

    if data is not None:
        age = now - dt.datetime.fromisoformat(data["saved_at"])
        if age < dt.timedelta(days=REFRESH_AFTER_DAYS):
            os.environ["PINTEREST_ACCESS_TOKEN"] = data["access_token"]
            return

    refresh_token = data["refresh_token"] if data else config.require("PINTEREST_REFRESH_TOKEN")
    new = refresh_access_token(refresh_token)
    data = {
        "access_token": new["access_token"],
        "refresh_token": new.get("refresh_token", refresh_token),
        "saved_at": now.isoformat(),
    }
    VAULT_PATH.write_bytes(vault.encrypt(json.dumps(data).encode()))
    os.environ["PINTEREST_ACCESS_TOKEN"] = data["access_token"]
    log("Pinterest sign-in refreshed and saved (encrypted).")
