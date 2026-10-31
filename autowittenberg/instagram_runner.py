"""One Instagram run: pick the next listing, build its carousel, and post (or preview) it.

Modes:
  dry-run   build the slides and caption only; nothing leaves this computer
  prepare   also upload the slides to the temporary public branch and have Instagram fetch and
            process them (creates the post container) but do NOT publish -- a full end-to-end test
  live      publish to the real Instagram account

Order: a listing noticed in the last 14 days goes first (newest first); everything else is the
gradual backfill, one a day. During the Reformation Day boost only boosted listings go; listings in
a seasonal exclusion (e.g. Reformation party decor, Nov 1 - Dec 31) never go.
"""
import datetime as dt
import json
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

from . import alerts, seasonal, state
from .carousel import build_caption, choose_slides, frame_photo
from .copy import get_instagram_copy
from .hosting import publish_images
from .images import render_faithful_slide
from .instagram import InstagramClient
from .sync import sync_pool
from .tokens import ensure_fresh_instagram_token

ROOT = Path(__file__).parent.parent
SLIDES_DIR = ROOT / "data" / "ig_slides"
HISTORY_PATH = ROOT / "data" / "instagram_history.jsonl"
ET = ZoneInfo("America/New_York")
NEW_LISTING_DAYS = 14
MAX_FAILURES = 3
KEEP_DAYS = 2


def choose_listing(pool, ig_state, today, excluded=frozenset(), boost_cfg=None):
    posted, failures = ig_state["posted"], ig_state.get("failures", {})
    cands = [l for l in pool if l["photos"] and l["listing_id"] not in excluded
             and str(l["listing_id"]) not in posted and failures.get(str(l["listing_id"]), 0) < MAX_FAILURES]
    if boost_cfg:
        boosted = [l for l in cands if seasonal.weight(l, boost_cfg) > 0]
        cands = boosted or cands

    def age(l):
        return (today - dt.date.fromisoformat(l["first_seen"])).days if l.get("first_seen") else None

    new = [l for l in cands if age(l) is not None and 0 <= age(l) <= NEW_LISTING_DAYS]
    if new:
        return max(new, key=lambda l: (l["first_seen"], l["listing_id"])), "new listing"
    if not cands:
        return None, None
    weight = (lambda l: seasonal.weight(l, boost_cfg)) if boost_cfg else (lambda l: 0)
    return max(cands, key=lambda l: (weight(l), l["listing_id"])), "backfill"


def _log_history(record):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _cleanup(today):
    keep = {(today - dt.timedelta(days=i)).isoformat() for i in range(KEEP_DAYS)}
    if SLIDES_DIR.exists():
        for folder in SLIDES_DIR.iterdir():
            if folder.is_dir() and folder.name not in keep:
                shutil.rmtree(folder)


def build_post(listing, out_dir, log=print):
    """Slides + caption for one listing. Photo framing decisions and the caption are cached."""
    framing_cache = state.load_framing()
    copy_cache = state.load_instagram_copy()
    slides = choose_slides(listing)
    paths = []
    for i, photo in enumerate(slides):
        framing = frame_photo(photo, listing["title"], framing_cache)
        state.save_framing(framing_cache)
        path = Path(out_dir) / f"{listing['listing_id']}_slide{i + 1}.jpg"
        render_faithful_slide(photo["url"], path, framing)
        paths.append(path)
    copy = get_instagram_copy(listing, copy_cache)
    state.save_instagram_copy(copy_cache)
    return paths, build_caption(listing, copy), copy["alt_text"]


def run(mode="dry-run", listing_id=None, slot=None, slot_date=None, log=print):
    """Returns a result dict; never raises for a single failed post (it is logged and skipped)."""
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ET).date()
    result = {"mode": mode, "time": now.isoformat(), "posted": None, "error": None, "slot": slot, "slot_date": slot_date}
    if (ROOT / "PAUSED").exists():
        log("Paused: a PAUSED file exists, so nothing was posted.")
        result["paused"] = True
        return result
    try:
        pool, _ = sync_pool(log)
        excluded = seasonal.excluded_ids(pool, today, log)
        boost_cfg = seasonal.active_config(today)
        if boost_cfg:
            seasonal.ensure_relevance(pool, boost_cfg, log)
        ig_state = state.load_instagram_state()
        first_seen = state.load_first_seen()
        for l in pool:
            l["first_seen"] = first_seen.get(str(l["listing_id"]))
        if listing_id:
            listing, why = next((l for l in pool if str(l["listing_id"]) == str(listing_id)), None), "chosen by hand"
        else:
            listing, why = choose_listing(pool, ig_state, today, excluded, boost_cfg)
        if listing is None:
            log("Nothing left to post on Instagram.")
            return result
        log(f"Instagram pick ({why}): {listing['title'][:70]}")

        out_dir = SLIDES_DIR / today.isoformat()
        _cleanup(today)
        paths, caption, alt_text = build_post(listing, out_dir, log)
        result.update({"listing_id": listing["listing_id"], "title": listing["title"], "url": listing["url"], "why": why,
                       "slides": [str(p) for p in paths], "caption": caption, "alt_text": alt_text})
        if mode == "dry-run":
            log(f"Built {len(paths)} slide(s); not uploaded or posted (dry run).")
            return result

        ensure_fresh_instagram_token(log)
        client = InstagramClient()
        urls = publish_images(paths)
        container = client.prepare(urls, caption, alt_text)
        result["container_id"] = container
        if mode == "prepare":
            log(f"Prepared (not published): Instagram accepted all {len(paths)} slide(s); container {container}.")
            return result

        media_id = client.publish(container, caption)
        permalink = client.permalink(media_id)
        result.update({"posted": True, "media_id": media_id, "permalink": permalink})
        ig_state["posted"][str(listing["listing_id"])] = {"media_id": media_id, "permalink": permalink,
                                                           "posted_at": now.isoformat(), "slides": len(paths), "why": why}
        state.save_instagram_state(ig_state)
        log(f"Posted to Instagram: {permalink}")
    except Exception as e:  # skip this one, log it clearly, never crash the whole run
        result["error"] = str(e)
        log(f"INSTAGRAM FAILED: {e}")
        if mode == "live" and alerts.is_auth_failure(e):
            alerts.alert("Instagram", e, log)
        if result.get("listing_id") and mode == "live":
            ig_state = state.load_instagram_state()
            fails = ig_state.setdefault("failures", {})
            fails[str(result["listing_id"])] = fails.get(str(result["listing_id"]), 0) + 1
            state.save_instagram_state(ig_state)
    finally:
        if mode == "live":
            _log_history({k: v for k, v in result.items() if k not in ("slides", "caption")})
    return result
