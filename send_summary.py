"""Sends (or previews) the daily summary email.

  .venv/bin/python send_summary.py                 email today's summary
  .venv/bin/python send_summary.py --preview       build a sample email from a 5-pin dry run and
                                                   save it to data/summary_preview.html (sends nothing)
"""
import argparse
import datetime as dt
from pathlib import Path

from autowittenberg.analytics import collect as collect_analytics, fill_image_urls
from autowittenberg.instagram_stats import collect as collect_instagram
from autowittenberg.notify import LOCAL_TZ, build_summary, runs_for_date, send_email


def _safe_analytics():
    try:
        return collect_analytics()
    except Exception as e:  # missing stats must never stop the daily email
        print(f"Pinterest analytics unavailable: {e}")
        return None


def _safe_instagram():
    try:
        return collect_instagram()
    except Exception as e:  # missing Instagram stats must never stop the daily email
        print(f"Instagram stats unavailable: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--date", default="", help="Eastern date to summarize, YYYY-MM-DD (default: today)")
    parser.add_argument("--record-sent", action="store_true", help="remember that this day's summary went out")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(LOCAL_TZ).date()

    if args.preview:
        from autowittenberg.runner import run
        summary = run(count=5, mode="dry-run")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["time"] = now
        subject, plain, body, images = build_summary([summary], today, _safe_analytics(), _safe_instagram())
        out = Path(__file__).parent / "data" / "summary_preview.html"
        import base64
        from autowittenberg.notify import LOGO_PATH
        logo_uri = "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
        preview = body.replace("cid:logo", logo_uri)  # so it displays in a browser
        for cid, data in images.items():
            preview = preview.replace(f"cid:{cid}", "data:image/jpeg;base64," + base64.b64encode(data).decode())
        out.write_text(preview)
        print(subject, "\n\n" + plain, f"\n\nSaved preview to {out}")
        return

    runs = runs_for_date(today)
    try:
        fill_image_urls(runs)
    except Exception as e:  # a missing enlarge-link must never stop the email
        print(f"Full-size image links unavailable: {e}")
    subject, plain, body, images = build_summary(runs, today, _safe_analytics(), _safe_instagram())
    if not args.record_sent:  # a hand-triggered run (a test or a resend), not the scheduled nightly digest
        subject = f"[Manual run, day so far] {subject}"
        body = ("<div style='font-family:Helvetica,Arial,sans-serif;background:#fff4d6;padding:10px;border-radius:6px;"
                "max-width:640px;margin:10px auto;font-size:13px'><b>Manual run.</b> This was triggered by hand and covers "
                "the day so far. Your regular digest arrives each night.</div>") + body
        plain = "MANUAL RUN: covers the day so far. Your regular digest arrives each night.\n\n" + plain
    try:
        send_email(subject, plain, body, images)
    except Exception as e:  # an email problem must never break the run
        raise SystemExit(f"Summary email could not be sent: {e}")
    print("Summary email sent:", subject)
    if args.record_sent:
        import json
        path = Path(__file__).parent / "data" / "summary_sent.json"
        sent = json.loads(path.read_text()) if path.exists() else []
        path.write_text(json.dumps(sorted(set(sent + [today.isoformat()]))[-60:]) + "\n")


if __name__ == "__main__":
    main()
