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
from .pinterest import PinterestClient
from .tokens import load_access_token

HISTORY_PATH = Path(__file__).parent.parent / "data" / "run_history.jsonl"
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
    total = {"yesterday": zero(), "week": zero(), "all": zero()}
    per_pin, failures = [], 0
    for pin_id, info in pins.items():
        try:
            days = client.pin_analytics(pin_id, info["created"], today)
        except Exception as e:
            failures += 1
            log(f"Warning: analytics unavailable for pin {pin_id}: {str(e)[:120]}")
            continue
        week = zero()
        for d in days:
            date = dt.date.fromisoformat(d["date"])
            for m in METRICS:
                v = int(d["metrics"].get(m) or 0)
                total["all"][m] += v
                if date == yesterday:
                    total["yesterday"][m] += v
                if week_start <= date <= yesterday:
                    total["week"][m] += v
                    week[m] += v
        per_pin.append({"title": info["title"], "url": info["url"], "week": week})
        time.sleep(0.2)  # be gentle with Pinterest's rate limits

    top = sorted(per_pin, key=lambda p: (p["week"]["OUTBOUND_CLICK"], p["week"]["IMPRESSION"]), reverse=True)[:5]
    top = [p for p in top if p["week"]["IMPRESSION"] > 0]
    return {"totals": total, "top": top, "pins_measured": len(per_pin), "pins_failed": failures,
            "yesterday": yesterday.isoformat()}
