"""Keeps the rotation pool in step with the live Etsy shop.

- New listing  -> Claude writes its pin copy and assigns a board (once, then cached).
- New photo    -> Claude classifies it as artwork / infographic / text_heavy (once, cached).
- Listing gone (deactivated, sold out, expired) -> simply absent from the pool, so it drops out of rotation.
If Etsy is unreachable, the last saved snapshot is used so posting can still continue.
"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from . import state
from .copy import BOARD_THEMES, get_listing_copy, get_photo_classification
from .etsy import EtsyError, fetch_shop_snapshot


def load_snapshot(log):
    try:
        snapshot = fetch_shop_snapshot()
        state.save_snapshot(snapshot)
        return snapshot
    except EtsyError as e:
        log(f"Etsy unavailable ({e}); using the last saved listing snapshot.")
        saved = state.load_snapshot()
        if not saved:
            raise
        return saved


def sync_pool(log=print):
    """Returns (pool, report). pool = one entry per listing that has copy and photos."""
    snapshot = load_snapshot(log)
    copy_cache = state.load_copy_cache()
    photo_cache = state.load_photo_cache()
    report = {"new_listings": [], "new_photos": 0, "removed_listings": [], "no_usable_photos": [], "errors": []}

    known_ids = set(state.load_known_listing_ids())
    active_ids = {str(l["listing_id"]) for l in snapshot["listings"]}
    report["removed_listings"] = sorted(known_ids - active_ids)

    first_seen = state.load_first_seen()
    today_et = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    pool = []
    for listing in snapshot["listings"]:
        lid = str(listing["listing_id"])
        try:
            is_new = lid not in copy_cache
            if is_new:
                report["new_listings"].append(listing["title"])
                first_seen.setdefault(lid, today_et)
            copy = get_listing_copy(listing, copy_cache)
            if is_new:
                state.save_copy_cache(copy_cache)  # save progress as we go
        except Exception as e:  # Claude down, etc. Skip this listing for now, keep going.
            report["errors"].append(f"Copy failed for '{listing['title'][:50]}': {e}")
            continue

        photos = []
        for img in listing["images"]:
            try:
                is_new_photo = str(img["image_id"]) not in photo_cache
                if is_new_photo:
                    report["new_photos"] += 1
                result = get_photo_classification(img, listing["title"], photo_cache)
                if is_new_photo:
                    state.save_photo_cache(photo_cache)
            except Exception as e:
                report["errors"].append(f"Photo {img['image_id']} not classified: {e}")
                continue
            if result["category"] in ("artwork", "text_heavy"):
                # text_heavy photos are used too, but without a headline box (see rotation.py)
                photos.append({"image_id": img["image_id"], "url": img["url"], "kind": result["category"]})

        if not photos:
            report["no_usable_photos"].append(listing["title"])
            continue

        pool.append({
            "listing_id": listing["listing_id"],
            "title": listing["title"],
            "tags": listing.get("tags", []),
            "first_seen": first_seen.get(lid),
            "url": listing["url"],
            "board_theme": copy["board_theme"],
            "board_name": BOARD_THEMES[copy["board_theme"]],
            "pin_title": copy["pin_title"],
            "pin_description": copy["pin_description"],
            "overlay_headlines": copy["overlay_headlines"],
            "photos": photos,
        })

    state.save_copy_cache(copy_cache)
    state.save_photo_cache(photo_cache)
    state.save_first_seen(first_seen)
    state.save_known_listing_ids(sorted(active_ids))
    return pool, report
