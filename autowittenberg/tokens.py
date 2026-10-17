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


def load_access_token():
    """Current access token without refreshing or saving anything (used by the summary job).
    Returns None when there is no vault or it cannot be read."""
    key = config.optional("TOKEN_VAULT_KEY")
    if not key or not VAULT_PATH.exists():
        return None
    try:
        return json.loads(Fernet(key.encode()).decrypt(VAULT_PATH.read_bytes()))["access_token"]
    except Exception:
        return None


IG_VAULT_PATH = Path(__file__).parent.parent / "data" / "instagram_token.enc"
IG_REFRESH_AFTER_DAYS = 20  # the token lasts 60 days; renewing at 20 keeps a wide safety margin


def ensure_fresh_instagram_token(log=print):
    """Same idea as Pinterest's vault: in the cloud (TOKEN_VAULT_KEY set) the newest token lives
    encrypted in the repo and is renewed every 20 days; locally the token in .env is used as is."""
    from .instagram import refresh_token
    key = config.optional("TOKEN_VAULT_KEY")
    if not key:
        return
    vault = Fernet(key.encode())
    now = dt.datetime.now(dt.timezone.utc)
    data = json.loads(vault.decrypt(IG_VAULT_PATH.read_bytes())) if IG_VAULT_PATH.exists() else None
    if data is None:
        data = {"access_token": config.require("INSTAGRAM_ACCESS_TOKEN"), "saved_at": now.isoformat()}
        IG_VAULT_PATH.write_bytes(vault.encrypt(json.dumps(data).encode()))
    elif now - dt.datetime.fromisoformat(data["saved_at"]) > dt.timedelta(days=IG_REFRESH_AFTER_DAYS):
        data = {"access_token": refresh_token(data["access_token"]), "saved_at": now.isoformat()}
        IG_VAULT_PATH.write_bytes(vault.encrypt(json.dumps(data).encode()))
        log("Instagram sign-in renewed and saved (encrypted).")
    os.environ["INSTAGRAM_ACCESS_TOKEN"] = data["access_token"]


def load_instagram_token():
    """Current Instagram token without renewing or saving anything (used by the summary job);
    falls back to the INSTAGRAM_ACCESS_TOKEN setting."""
    key = config.optional("TOKEN_VAULT_KEY")
    if key and IG_VAULT_PATH.exists():
        try:
            return json.loads(Fernet(key.encode()).decrypt(IG_VAULT_PATH.read_bytes()))["access_token"]
        except Exception:
            pass
    return config.optional("INSTAGRAM_ACCESS_TOKEN") or None
