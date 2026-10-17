"""Builds and sends the daily summary email (via a Gmail account + app password)."""
import datetime as dt
import html
import io
import json
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

HISTORY_PATH = Path(__file__).parent.parent / "data" / "run_history.jsonl"
LOCAL_TZ = ZoneInfo("America/New_York")
ROOT = Path(__file__).parent.parent
LOGO_PATH = ROOT / "assets" / "email-logo.png"
THUMB_WIDTH = 150
SENDER_NAME = "AutoWittenberg Report"  # the name shown in the From field


def runs_for_date(local_date, history_path=HISTORY_PATH):
    if not history_path.exists():
        return []
    runs = []
    for line in history_path.read_text().splitlines():
        run = json.loads(line)
        when = dt.datetime.fromisoformat(run["time"]).astimezone(LOCAL_TZ)
        if when.date() == local_date:
            runs.append(run)
    return runs


def _thumbnail(image_path):
    """Small JPEG of a generated pin, or None if the image file isn't available."""
    from PIL import Image
    path = Path(image_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return None
    im = Image.open(path).convert("RGB")
    im.thumbnail((THUMB_WIDTH * 2, THUMB_WIDTH * 3))  # 2x for sharp display on phones
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def build_summary(runs, local_date, analytics=None):
    """Returns (subject, plain_text, html, images); images maps content-id -> JPEG bytes."""
    posted = [p for r in runs for p in r["posted"]]
    failed = [f for r in runs for f in r["failed"]]
    paused = any(r.get("paused") for r in runs)
    syncs = [r["sync"] for r in runs if r.get("sync")]
    new_listings = [t for s in syncs for t in s["new_listings"]]
    removed = [t for s in syncs for t in s["removed_listings"]]
    no_photos = sorted({t for s in syncs for t in s["no_usable_photos"]})
    warnings = [e for s in syncs for e in s["errors"]]
    modes = {r.get("mode") for r in runs}
    label = " (SANDBOX TEST)" if modes == {"sandbox"} else ""

    if paused and not posted:
        status = "Paused: nothing was posted."
    elif failed and not posted:
        status = f"Problem: {len(failed)} failure(s), nothing posted."
    elif failed:
        status = f"{len(posted)} pin(s) posted, {len(failed)} failed."
    elif not runs:
        status = "No runs were recorded today. Check that the schedule is running."
    else:
        status = f"{len(posted)} pin(s) posted, no problems."

    day = f"{local_date:%a %b} {local_date.day}"
    subject = f"AutoWittenberg{label}: {status} ({day})"

    text = [f"AutoWittenberg daily summary{label} - {day}", status, ""]
    for p in posted:
        when = dt.datetime.fromisoformat(p["posted_at"]).astimezone(LOCAL_TZ).strftime("%-I:%M %p")
        text.append(f"  {when}  {p['title'][:70]}  ->  {p['board']}")
        if p.get("pin_id"):
            text.append(f"           Pin: https://www.pinterest.com/pin/{p['pin_id']}/")
        text.append(f"           Etsy: {p['url']}")
    if failed:
        text += ["", "Failures:"] + [f"  {f['title'][:60]}: {f['error'][:160]}" for f in failed]
    for heading, items in (("New listings found", new_listings), ("Listings removed (sold out or deactivated)", removed),
                           ("Listings skipped: no usable photos", no_photos), ("Warnings", warnings)):
        if items:
            text += ["", f"{heading}:"] + [f"  {i[:100]}" for i in items]
    text += _analytics_text(analytics)
    plain = "\n".join(text)

    images = {}
    for i, p in enumerate(posted):
        thumb = _thumbnail(p.get("thumb_path") or p.get("image_path") or "") if (p.get("thumb_path") or p.get("image_path")) else None
        if thumb:
            p["thumb_cid"] = f"pin{i}"
            images[p["thumb_cid"]] = thumb

    return subject, plain, _html(day, label, status, posted, failed, new_listings, removed, no_photos, warnings, bool(failed or paused or not runs), analytics), images


_ROWS = (("Impressions (times shown)", "IMPRESSION"), ("Pin clicks (opened)", "PIN_CLICK"),
         ("Clicks to Etsy", "OUTBOUND_CLICK"), ("Saves", "SAVE"), ("Pins by AutoWittenberg", "PINS"))


def _headers(a):
    latest = dt.date.fromisoformat(a["latest"]) if a.get("latest") else None
    return (f"{latest:%b} {latest.day}" if latest else "Yesterday"), "7 days", "All time"


def _fmt(a, period, key):
    if not a.get("latest"):
        if key == "PINS":  # our own count is always known; with no finished day yet, show the plain counts
            return f"{a['posted'][{'latest': 'yesterday'}.get(period, period)]:,}"
        return "pending"  # Pinterest hasn't finished counting any day yet
    return f"{a['totals'][period][key]:,}"


def _footnote(a):
    posted = a["posted"]
    if a.get("latest"):
        latest = dt.date.fromisoformat(a["latest"])
        span = (f"Pinterest finishes counting about 3 days late, so these columns cover days through "
                f"{latest:%b} {latest.day}; every number shown is final. ")
    else:
        span = "Pinterest finishes counting about 3 days late and hasn't finished any day yet. "
    return (span + f"Pins posted by AutoWittenberg: {posted['yesterday']} yesterday, {posted['week']} in the last 7 days, "
            f"{posted['all']} in total. Pinterest figures cover the {a['pins_measured']} pin(s) AutoWittenberg has posted.")


def _analytics_text(a):
    if not a:
        return []
    h1, h2, h3 = _headers(a)
    lines = ["", "PINTEREST PERFORMANCE", f"  {'':28s}{h1:>10s}{h2:>9s}{h3:>10s}"]
    for label, key in _ROWS:
        lines.append(f"  {label:28s}{_fmt(a, 'latest', key):>10s}{_fmt(a, 'week', key):>9s}{_fmt(a, 'all', key):>10s}")
    for pin in a["top"]:
        lines.append(f"  Top pin (7 days): {pin['title'][:60]} - {pin['week']['OUTBOUND_CLICK']} click(s) to Etsy")
    lines.append("  " + _footnote(a))
    return lines


def _analytics_html(a):
    if not a:
        return ""
    e = html.escape
    h1, h2, h3 = _headers(a)
    cell = "padding:5px 0;text-align:right;font-variant-numeric:tabular-nums"

    def row(label, key):
        bold = "font-weight:700;font-size:16px;" if key == "OUTBOUND_CLICK" else ""
        rule = "border-top:1px solid #ddd;" if key == "PINS" else ""  # our own count, set apart from Pinterest's
        return (f"<tr><td style='padding:5px 12px 5px 0;{bold}{rule}'>{e(label)}</td>"
                f"<td style='{cell};{bold}{rule}'>{_fmt(a, 'latest', key)}</td><td style='{cell};padding-left:18px;{bold}{rule}'>{_fmt(a, 'week', key)}</td>"
                f"<td style='{cell};padding-left:18px;{bold}{rule}'>{_fmt(a, 'all', key)}</td></tr>")

    rows = "".join(row(label, key) for label, key in _ROWS)
    top = "".join(
        f"<div style='font-size:13px;margin-top:6px'><a href='{e(p['url'])}' style='color:#1a5fb4'>{e(p['title'][:70])}</a>"
        f" <span style='color:#666'>&middot; {p['week']['OUTBOUND_CLICK']} click(s) to Etsy, {p['week']['IMPRESSION']:,} impressions</span></div>"
        for p in a["top"])
    top = f"<div style='margin-top:10px;font-size:13px;color:#666'>Top pins, last 7 finished days (by clicks to Etsy)</div>{top}" if top else ""
    note = _footnote(a)
    if a.get("pins_failed"):
        note += f" {a['pins_failed']} pin(s) could not be measured."
    return f"""<div style='margin:30px 0 8px;font-size:22px;font-weight:700'>Pinterest Performance</div>
<table style="border-collapse:collapse;font-size:14px;width:100%">
<tr style='color:#666;font-size:12px'><td></td><td style='text-align:right'>{e(h1)}</td><td style='text-align:right;padding-left:18px'>{e(h2)}</td><td style='text-align:right;padding-left:18px'>{e(h3)}</td></tr>{rows}</table>
{top}<div style='margin-top:10px;font-size:12px;color:#777'>{e(note)}</div>"""


def _html(day, label, status, posted, failed, new_listings, removed, no_photos, warnings, is_problem, analytics=None):
    e = html.escape
    color = "#b42318" if is_problem else "#1a7f37"
    rows = ""
    for p in posted:
        when = dt.datetime.fromisoformat(p["posted_at"]).astimezone(LOCAL_TZ).strftime("%-I:%M %p")
        pin_url = f"https://www.pinterest.com/pin/{p['pin_id']}/" if p.get("pin_id") else None
        thumb = (f"<img src='cid:{p['thumb_cid']}' width='{THUMB_WIDTH // 2 + 15}' alt='' style='display:block;border:0;border-radius:4px'>"
                 if p.get("thumb_cid") else "")
        if thumb and p.get("image_url"):
            # tapping the thumbnail opens the full-size pin image
            thumb = f"<a href='{e(p['image_url'])}' target='_blank'>{thumb}</a>"
        rows += (f"<tr><td style='padding:8px 12px 8px 0;vertical-align:top;width:{THUMB_WIDTH // 2 + 15}px'>{thumb}</td>"
                 f"<td style='padding:8px 0;vertical-align:top'>"
                 f"<div style='font-size:12px;color:#666'>{when} &middot; {e(p['board'])}</div>"
                 f"<span style='font-weight:600'>{e(p['title'][:80])}</span> "
                 f"<a href='{e(p['url'])}' style='color:#1a5fb4;white-space:nowrap'>(Etsy Link)</a> "
                 + (f"<a href='{e(pin_url)}' style='color:#1a5fb4;white-space:nowrap'>(Pin Link)</a>" if pin_url else "")
                 + "</td></tr>")

    def section(title, items, tone="#444"):
        if not items:
            return ""
        lis = "".join(f"<li style='margin:3px 0'>{e(i[:140])}</li>" for i in items)
        return f"<h3 style='margin:22px 0 6px;font-size:15px;color:{tone}'>{e(title)}</h3><ul style='margin:0;padding-left:20px;color:#333'>{lis}</ul>"

    fail_items = [f"{f['title'][:60]}: {f['error'][:160]}" for f in failed]
    return f"""<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#1a1a1a">
<img src="cid:logo" alt="Reformed Arts" width="190" style="display:block;margin:0 0 18px;border:0">
<div style="font-size:13px;color:#666">AutoWittenberg daily summary{e(label)} &middot; {e(day)}</div>
<div style="font-size:22px;font-weight:700;margin:6px 0 16px;color:{color}">{e(status)}</div>
<table style="border-collapse:collapse;font-size:14px;width:100%">{rows}</table>
{_analytics_html(analytics)}
{section("Failures", fail_items, "#b42318")}{section("New listings found", new_listings)}{section("Listings removed (sold out or deactivated)", removed)}{section("Listings skipped: no usable photos", no_photos, "#b54708")}{section("Warnings", warnings, "#b54708")}
</div>"""


def send_email(subject, plain, html_body, images=None):
    sender = config.require("GMAIL_SENDER")
    password = config.require("GMAIL_APP_PASSWORD").replace(" ", "")
    recipient = config.require("SUMMARY_RECIPIENT")
    msg = MIMEMultipart("related")
    msg["Subject"], msg["From"], msg["To"] = subject, formataddr((SENDER_NAME, sender)), recipient
    body = MIMEMultipart("alternative")
    body.attach(MIMEText(plain, "plain"))
    body.attach(MIMEText(html_body, "html"))
    msg.attach(body)
    if LOGO_PATH.exists() and "cid:logo" in html_body:
        logo = MIMEImage(LOGO_PATH.read_bytes(), "png")
        logo.add_header("Content-ID", "<logo>")
        logo.add_header("Content-Disposition", "inline", filename="logo.png")
        msg.attach(logo)
    for cid, data in (images or {}).items():
        part = MIMEImage(data, "jpeg")
        part.add_header("Content-ID", f"<{cid}>")
        part.add_header("Content-Disposition", "inline", filename=f"{cid}.jpg")
        msg.attach(part)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
