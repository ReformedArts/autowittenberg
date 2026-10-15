"""Sends (or previews) the daily summary email.

  .venv/bin/python send_summary.py                 email today's summary
  .venv/bin/python send_summary.py --preview       build a sample email from a 5-pin dry run and
                                                   save it to data/summary_preview.html (sends nothing)
"""
import argparse
import datetime as dt
from pathlib import Path

from autowittenberg.notify import LOCAL_TZ, build_summary, runs_for_date, send_email


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    today = dt.datetime.now(LOCAL_TZ).date()

    if args.preview:
        from autowittenberg.runner import run
        summary = run(count=5, mode="dry-run")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["time"] = now
        subject, plain, body, images = build_summary([summary], today)
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

    subject, plain, body, images = build_summary(runs_for_date(today), today)
    try:
        send_email(subject, plain, body, images)
    except Exception as e:  # an email problem must never break the run
        raise SystemExit(f"Summary email could not be sent: {e}")
    print("Summary email sent:", subject)


if __name__ == "__main__":
    main()
