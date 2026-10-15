"""Decides which listing, and which specific variation, to post next.

Fairness rule: the listing with the fewest posts goes next (ties broken by who was posted
longest ago), so every listing gets equal turns before anyone repeats. Within a listing,
each repeat uses a different combination of photo, crop, color, and headline.
"""
from . import seasonal
from .images import CROP_STYLES, PALETTES


def _stats(posts):
    stats = {}
    for p in posts:
        s = stats.setdefault(str(p["listing_id"]), {"count": 0, "last": ""})
        s["count"] += 1
        s["last"] = max(s["last"], p["posted_at"])
    return stats


def choose_next(pool, posts, boost=None):
    """Returns (listing, variant) or None if nothing is eligible.

    boost = (config, headlines_by_listing_id) while a seasonal boost is active, else None.
    """
    eligible = [l for l in pool if l["photos"]]
    if not eligible:
        return None

    stats = _stats(posts)
    seasonal_heads = {}
    if boost:
        cfg, seasonal_heads = boost
        weights = {l["listing_id"]: seasonal.weight(l, cfg) for l in eligible}
        boosted = [l for l in eligible if weights[l["listing_id"]] > 0]
        if boosted:
            eligible = boosted
            window = [p for p in posts if p["posted_at"][:10] >= cfg["start"]]
            wstats = _stats(window)
            listing = min(
                eligible,
                key=lambda l: (
                    wstats.get(str(l["listing_id"]), {"count": 0})["count"] / weights[l["listing_id"]],
                    wstats.get(str(l["listing_id"]), {"last": ""})["last"],
                    l["listing_id"],
                ),
            )
        else:
            boost = None

    if not boost:
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
    }
    if photo.get("kind") == "text_heavy":
        # The photo already carries its own text: show it whole, with no headline box.
        variant["crop_style"] = "fit"
        variant["headline"] = None
    return listing, variant
