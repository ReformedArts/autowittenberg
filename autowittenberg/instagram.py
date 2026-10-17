"""Minimal client for the Instagram API with Instagram Login (publishing a carousel or single image)."""
import time

import requests

from . import config

GRAPH = "https://graph.instagram.com/v26.0"
TIMEOUT = 60


class InstagramError(Exception):
    pass


class InstagramClient:
    def __init__(self, token=None):
        self.token = token or config.require("INSTAGRAM_ACCESS_TOKEN")
        self._user_id = None

    def _call(self, method, path, **params):
        params["access_token"] = self.token
        kwargs = {"params": params} if method == "GET" else {"data": params}
        resp = requests.request(method, f"{GRAPH}/{path}", timeout=TIMEOUT, **kwargs)
        if not resp.ok:
            raise InstagramError(f"Instagram {method} {path} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def me(self):
        return self._call("GET", "me", fields="user_id,username,name,account_type,followers_count,media_count")

    @property
    def user_id(self):
        if self._user_id is None:
            self._user_id = self.me()["user_id"]
        return self._user_id

    def publishing_limit(self):
        return self._call("GET", f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")["data"][0]

    def _container(self, **params):
        return self._call("POST", f"{self.user_id}/media", **params)["id"]

    def create_image(self, image_url, caption=None, alt_text=None, carousel_item=False):
        params = {"image_url": image_url}
        if caption:
            params["caption"] = caption
        if alt_text:
            params["alt_text"] = alt_text
        if carousel_item:
            params["is_carousel_item"] = "true"
        return self._container(**params)

    def create_carousel(self, child_ids, caption):
        return self._container(media_type="CAROUSEL", children=",".join(child_ids), caption=caption)

    def wait_until_ready(self, container_id, timeout=300):
        """Poll until Instagram has fetched and processed the media (it downloads our image URLs)."""
        deadline = time.time() + timeout
        while True:
            status = self._call("GET", container_id, fields="status_code,status").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                detail = self._call("GET", container_id, fields="status")
                raise InstagramError(f"Container {container_id} {status}: {detail.get('status')}")
            if time.time() > deadline:
                raise InstagramError(f"Container {container_id} still {status} after {timeout}s")
            time.sleep(5)

    def publish(self, container_id):
        return self._call("POST", f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def permalink(self, media_id):
        return self._call("GET", media_id, fields="permalink").get("permalink")

    def prepare(self, image_urls, caption, alt_text=None):
        """Create and process the container for a carousel (2+ images) or a single image, without
        publishing. Returns the container id, ready for publish()."""
        if len(image_urls) == 1:
            container = self.create_image(image_urls[0], caption=caption, alt_text=alt_text)
        else:
            children = [self.create_image(u, alt_text=alt_text, carousel_item=True) for u in image_urls]
            for child in children:
                self.wait_until_ready(child)
            container = self.create_carousel(children, caption)
        self.wait_until_ready(container)
        return container


def refresh_token(token):
    """Extends a long-lived token by another 60 days (it must be at least 24 hours old)."""
    resp = requests.get("https://graph.instagram.com/refresh_access_token", timeout=TIMEOUT,
                        params={"grant_type": "ig_refresh_token", "access_token": token})
    if not resp.ok:
        raise InstagramError(f"Token refresh failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["access_token"]
