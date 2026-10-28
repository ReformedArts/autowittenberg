"""One automation run: sync with Etsy (once a day), pick the next pin(s), render, and post.

Modes:
  dry run (default)  render the images only; nothing is posted and rotation history is not changed
  sandbox            post to Pinterest's practice environment (what Trial access allows)
  live               post to your real Pinterest account (needs Standard access)

A single failed pin is logged and skipped; it never stops the run, is never retried
aggressively, and a broken or partial pin is never posted.
"""
import datetime as dt
import json
import shutil
from pathlib import Path

from zoneinfo import ZoneInfo

from . import alerts, seasonal, state
from .framing import frame_pin
from .images import make_thumbnail, render_pin
from .pinterest import PinterestClient, pin_image_url
from .rotation import choose_next
from .sync import sync_pool
from .tokens import ensure_fresh_tokens

ROOT = Path(__file__).parent.parent
PINS_DIR = ROOT / "data" / "generated_pins"
LOG_PATH = ROOT / "data" / "run_log.jsonl"
HISTORY_PATH = ROOT / "data" / "run_history.jsonl"
THUMBS_DIR = ROOT / "data" / "thumbs"
PAUSE_FILE = ROOT / "PAUSED"
KEEP_DAYS = 2


def log(message):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(message)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"time": stamp, "message": message}) + "\n")


def cleanup_old_pins(today):
    """Rolling window: keep only today's and yesterday's generated pin images and thumbnails."""
    keep = {(today - dt.timedelta(days=i)).isoformat() for i in range(KEEP_DAYS)}
    for base in (PINS_DIR, THUMBS_DIR):
        if not base.exists():
            continue
        for folder in base.iterdir():
            if folder.is_dir() and folder.name not in keep:
                shutil.rmtree(folder)
                log(f"Deleted old pin images: {folder.name}")


def run(count=1, mode="dry-run", force_sync=False, slot=None, slot_date=None):
    """Runs once and records the outcome for the daily summary email (real posts only).
    slot/slot_date say which scheduled posting time this run belongs to."""
    summary = _run(count, mode, force_sync)
    if mode != "dry-run":
        summary["slot"], summary["slot_date"] = slot, slot_date
        summary["time"] = dt.datetime.now(dt.timezone.utc).isoformat()
        with HISTORY_PATH.open("a") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


def _run(count, mode, force_sync):
    """Returns a summary dict: {posted: [...], failed: [...], sync: {...}, paused: bool}."""
    summary = {"mode": mode, "posted": [], "failed": [], "sync": None, "paused": False}

    if PAUSE_FILE.exists():
        log("Paused: a PAUSED file exists in the project folder, so nothing was posted.")
        summary["paused"] = True
        return summary

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    rotation = state.load_rotation()
    posts = list(rotation["posts"])

    pool = None
    if force_sync or rotation.get("last_sync_date") != today.isoformat() or mode == "dry-run":
        try:
            pool, report = sync_pool(log)
        except Exception as e:
            log(f"Could not build the listing pool: {e}")
            summary["failed"].append({"title": "(whole run)", "error": str(e)})
            return summary
        summary["sync"] = report
        rotation["last_sync_date"] = today.isoformat()
        log(
            f"Sync: {len(pool)} listings in rotation, {len(report['new_listings'])} new listing(s), "
            f"{report['new_photos']} new photo(s), {len(report['removed_listings'])} removed."
        )
        for title in report["no_usable_photos"]:
            log(f"Skipping '{title[:60]}': no usable artwork photos.")
        for err in report["errors"]:
            log(f"Warning: {err}")
    else:
        pool = _pool_from_last_sync()
        if pool is None:
            return _run(count, mode, force_sync=True)

    client = None
    if mode in ("sandbox", "live"):
        try:
            if mode == "live":
                ensure_fresh_tokens(log)
            client = PinterestClient(sandbox=(mode == "sandbox"))
        except (SystemExit, Exception) as e:
            log(f"Could not sign in to Pinterest: {e}")
            summary["failed"].append({"title": "(whole run)", "error": str(e)})
            if mode == "live":
                alerts.alert("Pinterest", e, log)
            return summary

    # first-seen dates live in their own file, so apply them to whichever pool we have (a pool saved
    # earlier the same day may predate them)
    first_seen = state.load_first_seen()
    for listing in pool:
        listing["first_seen"] = first_seen.get(str(listing["listing_id"]))

    et_today = now.astimezone(ZoneInfo("America/New_York")).date()
    excluded = set()
    try:
        excluded = seasonal.excluded_ids(pool, et_today, log)
        if excluded:
            log(f"Seasonal exclusion active: {len(excluded)} listing(s) sit out today.")
    except Exception as e:
        log(f"Warning: seasonal exclusion skipped: {e}")

    boost = None
    cfg = seasonal.active_config(now.astimezone(ZoneInfo("America/New_York")).date())
    if cfg:
        try:
            seasonal.ensure_relevance(pool, cfg, log)
            boost = (cfg, seasonal.ensure_headlines(pool, cfg, log))
            n_boosted = len(seasonal.boosted_listings(pool, cfg))
            log(f"Seasonal boost active: {cfg['name']} (through {cfg['end']}); {n_boosted} listings in the boost.")
        except Exception as e:
            log(f"Warning: seasonal boost skipped: {e}")

    out_dir = PINS_DIR / today.isoformat()
    cleanup_old_pins(today)

    for _ in range(count):
        choice = choose_next(pool, posts, boost, now, excluded)
        if choice is None:
            log("Nothing eligible to post.")
            break
        listing, variant = choice
        title = listing["title"]
        stamp = now.strftime("%H%M%S")
        image_path = out_dir / f"{listing['listing_id']}_{stamp}_{len(posts)}.jpg"
        try:
            try:
                framing = frame_pin(variant["photo"], title)
            except Exception as e:  # never crop blindly: if the check can't run, show the whole photo
                log(f"Warning: photo framing check unavailable ({str(e)[:80]}); showing the whole photo.")
                framing = {"can_crop": False, "window": None, "why": "framing unavailable"}
            render_pin(
                photo_url=variant["photo"]["url"],
                headline=variant["headline"],
                palette_key=variant["palette"],
                crop_style=variant["crop_style"],
                out_path=image_path,
                framing=framing,
                kind=variant["photo"].get("kind", "artwork"),
            )
            pin_id = image_url = None
            board_name = listing["board_name"]
            if client is not None:
                if mode == "sandbox":
                    board_name = "AutoWittenberg Sandbox Test"
                board = client.get_or_create_board(board_name)
                pin = client.create_pin(board["id"], image_path, listing["pin_title"], listing["pin_description"], listing["url"])
                pin_id = pin.get("id")
                image_url = pin_image_url(pin)
        except Exception as e:
            image_path.unlink(missing_ok=True)  # never leave a broken/partial pin behind
            log(f"FAILED '{title[:60]}': {e}")
            summary["failed"].append({"title": title, "error": str(e)})
            if mode == "live" and alerts.is_auth_failure(e):
                alerts.alert("Pinterest", e, log)
            # Count the attempt so one bad listing can't block the whole rotation.
            posts.append({"listing_id": listing["listing_id"], "posted_at": now.isoformat(), "failed": True})
            continue

        record = {
            "listing_id": listing["listing_id"],
            "image_id": variant["photo"]["image_id"],
            "palette": variant["palette"],
            "crop_style": variant["crop_style"],
            "headline": variant["headline"],
            "board": board_name,
            "pin_id": pin_id,
            "image_url": image_url,
            "launch": bool(variant.get("launch")),
            "posted_at": now.isoformat(),
        }
        posts.append(record)
        thumb_path = None
        try:  # a thumbnail problem must never undo or hide a pin that was already posted
            thumb_path = make_thumbnail(image_path, THUMBS_DIR / today.isoformat() / image_path.name)
        except Exception as e:
            log(f"Warning: could not make a thumbnail: {e}")
        summary["posted"].append({
            **record, "title": title, "url": listing["url"],
            "image_path": str(image_path.relative_to(ROOT)),
            "thumb_path": str(thumb_path.relative_to(ROOT)) if thumb_path else None,
        })
        verb = {"dry-run": "Rendered (not posted)", "sandbox": "Posted to sandbox", "live": "Posted"}[mode]
        log(f"{verb}{' [new-listing launch]' if variant.get('launch') else ''}: '{title[:60]}' -> {board_name} | {variant['palette']}, {variant['crop_style']} | \"{variant['headline'] or '(no headline box)'}\"")

    if mode != "dry-run":
        rotation["posts"] = posts
        state.save_rotation(rotation)
        _save_pool(pool)
    return summary


def _save_pool(pool):
    (ROOT / "data" / "rotation_pool.json").write_text(json.dumps(pool, indent=2, ensure_ascii=False))


def _pool_from_last_sync():
    path = ROOT / "data" / "rotation_pool.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data if data and "photos" in data[0] and "tags" in data[0] else None
