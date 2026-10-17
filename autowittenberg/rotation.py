"""Decides which listing, and which specific variation, to post next.

Three layers, in order:
  1. LAUNCH LANE: a listing noticed within the last NEW_LISTING_DAYS days gets the next slot, up to
     LAUNCH_QUOTA pins (max 2 per day, 3 hours apart), and no more than LAUNCH_SLOTS_PER_DAY of the
     day's slots go to launches, so older listings always keep most of the day. During a seasonal
     boost, only new listings that fit the boost qualify.
  0. SEASONAL EXCLUSIONS: listings in `excluded` (e.g. Reformation party decor, Nov 1 - Dec 31) never post.
  2. SEASONAL BOOST (when active): weighted turns for listings that fit the occasion.
  3. FAIR ROTATION: the listing with the fewest posts goes next (ties: posted longest ago).
Within a listing, each repeat uses a different combination of photo, crop, color, and headline.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from . import seasonal
from .images import CROP_STYLES, PALETTES

ET = ZoneInfo("America/New_York")
NEW_LISTING_DAYS = 14
LAUNCH_QUOTA = 8
LAUNCH_SLOTS_PER_DAY = 2
LAUNCH_PER_LISTING_PER_DAY = 2
LAUNCH_MIN_GAP = dt.timedelta(hours=3)


def _stats(posts):
    stats = {}
    for p in posts:
        s = stats.setdefault(str(p["listing_id"]), {"count": 0, "last": ""})
        s["count"] += 1
        s["last"] = max(s["last"], p["posted_at"])
    return stats


def _when(p):
    return dt.datetime.fromisoformat(p["posted_at"])


def _launch_pick(eligible, posts, now, boost):
    """The new listing that should get this slot, or None."""
    today = now.astimezone(ET).date()
    if sum(1 for p in posts if p.get("launch") and _when(p).astimezone(ET).date() == today) >= LAUNCH_SLOTS_PER_DAY:
        return None
    candidates = []
    for listing in eligible:
        first_seen = listing.get("first_seen")
        if not first_seen:
            continue
        seen = dt.date.fromisoformat(first_seen)
        if not 0 <= (today - seen).days <= NEW_LISTING_DAYS:
            continue
        if boost and seasonal.weight(listing, boost[0]) == 0:
            continue
        mine = [p for p in posts if str(p["listing_id"]) == str(listing["listing_id"]) and p["posted_at"][:10] >= first_seen]
        if len(mine) >= LAUNCH_QUOTA:
            continue
        if sum(1 for p in mine if _when(p).astimezone(ET).date() == today) >= LAUNCH_PER_LISTING_PER_DAY:
            continue
        if mine and now - max(_when(p) for p in mine) < LAUNCH_MIN_GAP:
            continue
        candidates.append((-seen.toordinal(), len(mine), listing["listing_id"], listing))
    return min(candidates, key=lambda c: c[:3])[3] if candidates else None


def choose_next(pool, posts, boost=None, now=None, excluded=frozenset()):
    """Returns (listing, variant) or None if nothing is eligible.

    boost = (config, headlines_by_listing_id) while a seasonal boost is active, else None.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    eligible = [l for l in pool if l["photos"] and l["listing_id"] not in excluded]
    if not eligible:
        return None

    stats = _stats(posts)
    seasonal_heads = boost[1] if boost else {}
    listing = _launch_pick(eligible, posts, now, boost)
    is_launch = listing is not None

    if listing is None and boost:
        cfg = boost[0]
        weights = {l["listing_id"]: seasonal.weight(l, cfg) for l in eligible}
        boosted = [l for l in eligible if weights[l["listing_id"]] > 0]
        if boosted:
            wstats = _stats([p for p in posts if p["posted_at"][:10] >= cfg["start"]])
            listing = min(
                boosted,
                key=lambda l: (
                    wstats.get(str(l["listing_id"]), {"count": 0})["count"] / weights[l["listing_id"]],
                    wstats.get(str(l["listing_id"]), {"last": ""})["last"],
                    l["listing_id"],
                ),
            )

    if listing is None:
        listing = min(
            eligible,
            key=lambda l: (
                stats.get(str(l["listing_id"]), {"count": 0})["count"],
                stats.get(str(l["listing_id"]), {"last": ""})["last"],
                l["listing_id"],
            ),
        )

    n = stats.get(str(listing["listing_id"]), {"count": 0})["count"]
    offset = int(listing["listing_id"]) % 7  # so different listings don't all start identically
    photos = listing["photos"]
    palette_keys = list(PALETTES.keys())
    headlines = seasonal_heads.get(str(listing["listing_id"])) or listing["overlay_headlines"]

    photo = photos[(n + offset) % len(photos)]
    variant = {
        "photo": photo,
        "crop_style": CROP_STYLES[(n + n // len(photos) + offset) % len(CROP_STYLES)],
        "palette": palette_keys[(n + n // len(CROP_STYLES) + offset) % len(palette_keys)],
        "headline": headlines[(n + offset) % len(headlines)],
        "launch": is_launch,
    }
    if photo.get("kind") == "text_heavy":
        # The photo already carries its own text: show it whole, with no headline box.
        variant["crop_style"] = "fit"
        variant["headline"] = None
    return listing, variant
