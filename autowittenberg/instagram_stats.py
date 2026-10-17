"""Instagram numbers for the daily email: our own activity plus Instagram's insights."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import state
from .tokens import load_instagram_token

ET = ZoneInfo("America/New_York")
GRAPH = "https://graph.instagram.com/v26.0"
SEED_DATE = "2026-09-26"  # listings known on this day were already in the shop before AutoWittenberg
METRICS = (("Accounts reached", "reach"), ("Views", "views"), ("Profile visits", "profile_views"),
           ("Taps on your link", "profile_links_taps"), ("Likes", "likes"), ("Comments", "comments"),
           ("Saves", "saves"), ("Shares", "shares"))


def _get(path, token, **params):
    r = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json()


def _value(ig, token, metric, start, end):
    """Total of one account metric over [start, end), or None if Instagram has no data for it."""
    body = _get(f"{ig}/insights", token, metric=metric, period="day", metric_type="total_value",
                since=int(start.timestamp()), until=int(end.timestamp()))
    data = body.get("data") or []
    return data[0].get("total_value", {}).get("value") if data else None


def collect(log=print):
    """Returns None if Instagram isn't connected or can't be reached."""
    token = load_instagram_token()
    if not token:
        return None
    now = dt.datetime.now(ET)
    midnight = dt.datetime.combine(now.date(), dt.time(), tzinfo=ET)
    windows = {"today": (midnight, now),
               "week": (midnight - dt.timedelta(days=6), now),      # the last 7 calendar days, today included
               "month": (midnight - dt.timedelta(days=29), now)}
    me = _get("me", token, fields="user_id,username,followers_count,media_count")
    ig = me["user_id"]

    numbers = {key: {} for key in windows}
    for _, metric in METRICS:
        for key, (start, end) in windows.items():
            try:
                numbers[key][metric] = _value(ig, token, metric, start, end)
            except Exception as e:
                log(f"Warning: Instagram {metric} unavailable: {str(e)[:100]}")
                numbers[key][metric] = None

    # our own activity, from our records
    ig_state = state.load_instagram_state()
    posted_days = [dt.datetime.fromisoformat(v["posted_at"]).astimezone(ET).date() for v in ig_state["posted"].values()]
    first_seen = [dt.date.fromisoformat(d) for d in state.load_first_seen().values() if d > SEED_DATE]

    def count(days, a, b):
        return sum(a <= d < b for d in days)

    today = now.date()
    tomorrow = today + dt.timedelta(days=1)
    spans = {"today": (today, tomorrow), "week": (today - dt.timedelta(days=6), tomorrow),
             "month": (today - dt.timedelta(days=29), tomorrow)}
    activity = {"posted": {k: count(posted_days, *v) for k, v in spans.items()},
                "listings": {k: count(first_seen, *v) for k, v in spans.items()}}

    # best carousels of the last 30 days
    titles = {str(l["listing_id"]): l["title"] for l in (state.load_snapshot() or {}).get("listings", [])}
    top = []
    for listing_id, post in ig_state["posted"].items():
        if dt.datetime.fromisoformat(post["posted_at"]) < now - dt.timedelta(days=30):
            continue
        try:
            got = {}
            for metric in ("reach", "total_interactions"):
                d = _get(f"{post['media_id']}/insights", token, metric=metric).get("data") or []
                got[metric] = d[0]["values"][0]["value"] if d else 0
        except Exception:
            continue
        if got["reach"] > 0:
            top.append({"title": titles.get(listing_id, "Carousel"), "url": post["permalink"], **got})
    top = sorted(top, key=lambda p: (p["reach"], p["total_interactions"]), reverse=True)[:3]
    return {"numbers": numbers, "activity": activity, "followers": me.get("followers_count", 0),
            "posts_total": len(ig_state["posted"]), "top": top, "username": me.get("username")}
