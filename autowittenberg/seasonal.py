"""Seasonal boost: for a window of dates each year, favor listings that fit an occasion.

Configured in data/seasonal_boost.json. start/end are MM-DD and repeat every year (US Eastern);
outside the window this does nothing and the normal even rotation applies.
  - a listing whose TITLE contains priority_keyword gets priority_weight times as many turns
  - other listings matching include_keywords (title) or priority_keyword (tags) get a normal share
  - anything the keywords miss is judged once by Claude (priority / related / unrelated) and
    remembered, so new Reformation-themed listings join automatically
  - everything else sits out until the window ends
"""
import datetime as dt
import json
from pathlib import Path

from .copy import classify_occasion_relevance, generate_seasonal_headlines

DATA = Path(__file__).parent.parent / "data"
CONFIG_PATH = DATA / "seasonal_boost.json"
HEADLINES_PATH = DATA / "seasonal_headlines.json"
RELEVANCE_PATH = DATA / "seasonal_relevance.json"

_relevance_cache = None


def _full_date(value, year):
    """'09-01' -> that day in `year`; a full 'YYYY-MM-DD' is used as is."""
    return dt.date.fromisoformat(value) if len(value) == 10 else dt.date.fromisoformat(f"{year}-{value}")


def active_config(today):
    """The boost config (with start/end resolved to full dates) if `today` is inside this
    year's window, else None."""
    if not CONFIG_PATH.exists():
        return None
    cfg = json.loads(CONFIG_PATH.read_text())
    start, end = _full_date(cfg["start"], today.year), _full_date(cfg["end"], today.year)
    if start <= today <= end:
        return {**cfg, "start": start.isoformat(), "end": end.isoformat()}
    return None


def _relevance():
    global _relevance_cache
    if _relevance_cache is None:
        _relevance_cache = json.loads(RELEVANCE_PATH.read_text()) if RELEVANCE_PATH.exists() else {}
    return _relevance_cache


def _keyword_weight(listing, cfg):
    title = listing["title"].lower()
    kw = cfg["priority_keyword"]
    if kw in title:
        return cfg["priority_weight"]
    tags = " ".join(listing.get("tags", [])).lower()
    if any(k in title for k in cfg["include_keywords"]) or kw in tags:
        return 1
    return 0


def weight(listing, cfg):
    w = _keyword_weight(listing, cfg)
    if w:
        return w
    verdict = _relevance().get(f"{cfg['name']}|{listing['listing_id']}", {}).get("relevance")
    return {"priority": cfg["priority_weight"], "related": 1}.get(verdict, 0)


def boosted_listings(pool, cfg):
    return [(l, weight(l, cfg)) for l in pool if weight(l, cfg) > 0]


def ensure_relevance(pool, cfg, log=print):
    """Asks Claude, once per listing, about listings the keywords did not catch."""
    cache = _relevance()
    changed = False
    for listing in pool:
        key = f"{cfg['name']}|{listing['listing_id']}"
        if key in cache or _keyword_weight(listing, cfg):
            continue
        try:
            cache[key] = classify_occasion_relevance(listing, cfg["theme"])
            changed = True
            log(f"Boost check: '{listing['title'][:50]}' -> {cache[key]['relevance']}")
        except Exception as e:  # leave it out of the boost; try again next run
            log(f"Warning: boost check failed for '{listing['title'][:50]}': {e}")
    if changed:
        RELEVANCE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def load_headlines():
    return json.loads(HEADLINES_PATH.read_text()) if HEADLINES_PATH.exists() else {}


def ensure_headlines(pool, cfg, log=print):
    """Writes occasion headlines for boosted listings that don't have them yet (once each)."""
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
