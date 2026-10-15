"""Decides which listing, and which specific variation, to post next.

Fairness rule: the listing with the fewest posts goes next (ties broken by who was posted
longest ago), so every listing gets equal turns before anyone repeats. Within a listing,
each repeat uses a different combination of photo, crop, color, and headline.
"""
from .images import CROP_STYLES, PALETTES


def _stats(posts):
    stats = {}
    for p in posts:
        s = stats.setdefault(str(p["listing_id"]), {"count": 0, "last": ""})
        s["count"] += 1
        s["last"] = max(s["last"], p["posted_at"])
    return stats


def choose_next(pool, posts):
    """Returns (listing, variant) or None if nothing is eligible."""
    eligible = [l for l in pool if l["photos"]]
    if not eligible:
        return None

    stats = _stats(posts)
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
    headlines = listing["overlay_headlines"]

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
