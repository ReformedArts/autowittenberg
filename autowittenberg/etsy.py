"""Minimal read-only client for the Etsy Open API v3.

Only public shop data is read (active listings, their photos, titles, descriptions,
tags, links), so an API key is enough — no OAuth login is required.
"""
import html
import time

from . import config  # imported first so its warning filter applies

import requests

BASE_URL = "https://openapi.etsy.com/v3/application"
TIMEOUT = 20


class EtsyError(Exception):
    pass


class EtsyClient:
    def __init__(self, api_key=None, shared_secret=None):
        api_key = api_key or config.require("ETSY_API_KEY")
        shared_secret = shared_secret or config.optional("ETSY_SHARED_SECRET")
        # Etsy now expects "keystring:shared_secret" in the x-api-key header.
        header = f"{api_key}:{shared_secret}" if shared_secret else api_key
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": header})

    def _get(self, path, params=None):
        url = f"{BASE_URL}{path}"
        # One gentle retry on rate limits or Etsy server hiccups, never more.
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=TIMEOUT)
            except requests.RequestException as e:
                if attempt == 0:
                    time.sleep(5)
                    continue
                raise EtsyError(f"Could not reach Etsy: {e}") from e
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(5)
                continue
            if not resp.ok:
                raise EtsyError(f"Etsy returned {resp.status_code} for {path}: {resp.text[:300]}")
            return resp.json()

    def find_shop(self, shop_name):
        data = self._get("/shops", {"shop_name": shop_name})
        for shop in data.get("results", []):
            if shop.get("shop_name", "").lower() == shop_name.lower():
                return shop
        raise EtsyError(f"No Etsy shop named '{shop_name}' was found.")

    def active_listings(self, shop_id):
        """All active listings. Deactivated, expired, and sold-out listings are not returned."""
        listings, offset = [], 0
        while True:
            data = self._get(
                f"/shops/{shop_id}/listings/active",
                {"limit": 100, "offset": offset},
            )
            batch = data.get("results", [])
            listings.extend(batch)
            offset += len(batch)
            if not batch or offset >= data.get("count", 0):
                return listings

    def listing_images(self, listing_id):
        data = self._get(f"/listings/{listing_id}/images")
        return sorted(data.get("results", []), key=lambda img: img.get("rank", 0))


def fetch_shop_snapshot(client=None, shop_name=None):
    """Returns a simplified snapshot of every active listing and all of its photos."""
    client = client or EtsyClient()
    shop = client.find_shop(shop_name or config.require("ETSY_SHOP_NAME"))
    listings = []
    for raw in client.active_listings(shop["shop_id"]):
        images = client.listing_images(raw["listing_id"])
        listings.append({
            "listing_id": raw["listing_id"],
            "title": html.unescape(raw.get("title", "")),
            "description": raw.get("description", ""),
            "tags": raw.get("tags", []),
            "url": raw.get("url", "").split("?")[0],
            "images": [
                {
                    "image_id": img["listing_image_id"],
                    "rank": img.get("rank"),
                    "url": img.get("url_fullxfull"),
                    "width": img.get("full_width"),
                    "height": img.get("full_height"),
                }
                for img in images
            ],
        })
    return {"shop_id": shop["shop_id"], "shop_name": shop["shop_name"], "listings": listings}
