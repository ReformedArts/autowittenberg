"""Seasonal boost: for a date window, favor listings that fit an occasion.

Configured in data/seasonal_boost.json. Outside the start..end dates (US Eastern) this does
nothing and the normal even rotation applies, so the boost switches itself off.
  - listings whose TITLE contains priority_keyword get priority_weight times as many turns
  - other listings matching include_keywords (title) or priority_keyword (tags) get a normal share
  - everything else sits out until the window ends
"""
import datetime as dt
import json
from pathlib import Path

from .copy import generate_seasonal_headlines

CONFIG_PATH = Path(__file__).parent.parent / "data" / "seasonal_boost.json"
HEADLINES_PATH = Path(__file__).parent.parent / "data" / "seasonal_headlines.json"


def active_config(today):
    """The boost config if `today` (a date) falls inside its window, else None."""
    if not CONFIG_PATH.exists():
        return None
    cfg = json.loads(CONFIG_PATH.read_text())
    if dt.date.fromisoformat(cfg["start"]) <= today <= dt.date.fromisoformat(cfg["end"]):
        return cfg
    return None


def weight(listing, cfg):
    title = listing["title"].lower()
    kw = cfg["priority_keyword"]
    if kw in title:
        return cfg["priority_weight"]
    tags = " ".join(listing.get("tags", [])).lower()
    if any(k in title for k in cfg["include_keywords"]) or kw in tags:
        return 1
    return 0


def boosted_listings(pool, cfg):
    return [(l, weight(l, cfg)) for l in pool if weight(l, cfg) > 0]


def load_headlines():
    return json.loads(HEADLINES_PATH.read_text()) if HEADLINES_PATH.exists() else {}


def ensure_headlines(pool, cfg, log=print):
    """Writes seasonal headlines for boosted listings that don't have them yet (once each)."""
    cache = load_headlines()
    for listing, _ in boosted_listings(pool, cfg):
        key = str(listing["listing_id"])
        if key in cache:
            continue
        try:
            cache[key] = generate_seasonal_headlines(listing, cfg["theme"])
            HEADLINES_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        except Exception as e:  # fall back to the listing's normal headlines
            log(f"Warning: no seasonal headlines for '{listing['title'][:50]}': {e}")
    return cache
