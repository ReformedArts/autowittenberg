"""Pinterest performance numbers for the daily email.

Covers pins AutoWittenberg posted live in the last 90 days (Pinterest's analytics window).
Pinterest's numbers lag by up to a day or two, so recent days can read low.
"""
import datetime as dt
import json
import os
import time
from pathlib import Path

from . import config
from zoneinfo import ZoneInfo

from .pinterest import PinterestClient, pin_image_url
from .tokens import load_access_token

HISTORY_PATH = Path(__file__).parent.parent / "data" / "run_history.jsonl"
ET = ZoneInfo("America/New_York")
WINDOW_DAYS = 90
METRICS = ("IMPRESSION", "PIN_CLICK", "OUTBOUND_CLICK", "SAVE")


def _live_pins(today):
    pins = {}
    if not HISTORY_PATH.exists():
        return pins
    for line in HISTORY_PATH.read_text().splitlines():
        run = json.loads(line)
        if run.get("mode") != "live":
            continue
        for p in run["posted"]:
            if p.get("pin_id"):
                created = dt.datetime.fromisoformat(p["posted_at"]).date()
                if (today - created).days <= WINDOW_DAYS:
                    pins[p["pin_id"]] = {"title": p["title"], "url": p["url"], "created": created}
    return pins


def _pin_days():
    """Eastern date of every live pin AutoWittenberg has posted."""
    days = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text().splitlines():
            run = json.loads(line)
            if run.get("mode") != "live":
                continue
            for p in run["posted"]:
                days.append(dt.datetime.fromisoformat(p["posted_at"]).astimezone(ET).date())
    return days


def _posted_recent(days):
    """Pins posted: yesterday, the last 7 complete days, and all time (Eastern days)."""
    et_today = dt.datetime.now(ET).date()
    yesterday = et_today - dt.timedelta(days=1)
    week_start = et_today - dt.timedelta(days=7)
    return {"yesterday": sum(d == yesterday for d in days),
            "week": sum(week_start <= d <= yesterday for d in days), "all": len(days)}


def fill_image_urls(runs, log=print):
    """Adds the public full-size image URL to posted pins that don't have one saved yet."""
    missing = [p for r in runs for p in r["posted"] if p.get("pin_id") and not p.get("image_url") and r.get("mode") == "live"]
    if not missing:
        return
    token = load_access_token() or config.optional("PINTEREST_ACCESS_TOKEN")
    if not token:
        return
    client = PinterestClient(access_token=token)
    for p in missing:
        try:
            p["image_url"] = pin_image_url(client._request("GET", f"/pins/{p['pin_id']}"))
        except Exception as e:
            log(f"Warning: no full-size image link for pin {p['pin_id']}: {str(e)[:100]}")


def collect(today=None, log=print):
    """Returns None if analytics are unavailable, else a dict of totals and top pins."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    token = load_access_token() or config.optional("PINTEREST_ACCESS_TOKEN")
    pins = _live_pins(today)
    if not token or not pins:
        return None
    client = PinterestClient(access_token=token)
    yesterday = today - dt.timedelta(days=1)
    week_start = today - dt.timedelta(days=7)

    zero = lambda: {m: 0 for m in METRICS}
    per_pin_days, failures = [], 0
    for pin_id, info in pins.items():
        try:
            days = client.pin_analytics(pin_id, info["created"], today)
        except Exception as e:
            failures += 1
            log(f"Warning: analytics unavailable for pin {pin_id}: {str(e)[:120]}")
            continue
        per_pin_days.append((info, days))
        time.sleep(0.2)  # be gentle with Pinterest's rate limits

    # Pinterest finishes counting a day about 3 days late. Only finished (READY) days are reported,
    # so every number shown is final; the columns end on the latest finished day.
    ready = {dt.date.fromisoformat(d["date"]) for _, days in per_pin_days for d in days if d.get("data_status") == "READY"}
    latest = max(ready) if ready else None
    week_start = latest - dt.timedelta(days=6) if latest else None

    total = {"latest": zero(), "week": zero(), "all": zero()}
    per_pin = []
    for info, days in per_pin_days:
        week = zero()
        for d in days:
            date = dt.date.fromisoformat(d["date"])
            if d.get("data_status") != "READY":
                continue
            for m in METRICS:
                v = int(d["metrics"].get(m) or 0)
                total["all"][m] += v
                if date == latest:
                    total["latest"][m] += v
                if week_start <= date <= latest:
                    total["week"][m] += v
                    week[m] += v
        per_pin.append({"title": info["title"], "url": info["url"], "week": week})

    our_days = _pin_days()
    if latest:
        total["latest"]["PINS"] = sum(d == latest for d in our_days)
        total["week"]["PINS"] = sum(week_start <= d <= latest for d in our_days)
        total["all"]["PINS"] = sum(d <= latest for d in our_days)

    top = sorted(per_pin, key=lambda p: (p["week"]["OUTBOUND_CLICK"], p["week"]["IMPRESSION"]), reverse=True)[:5]
    top = [p for p in top if p["week"]["IMPRESSION"] > 0]
    return {"totals": total, "latest": latest.isoformat() if latest else None, "top": top,
            "posted": _posted_recent(our_days), "pins_measured": len(per_pin), "pins_failed": failures}
