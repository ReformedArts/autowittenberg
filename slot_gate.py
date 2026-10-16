"""Decides whether this scheduled run should post, so pins go out at the chosen times in
US Eastern time all year (GitHub's scheduler only understands UTC, so the schedule fires
at both possible UTC hours and this check keeps whichever one matches).

Uses only the standard library so it runs in seconds, before anything is installed.
Writes run=true/false, slot and slot_date to $GITHUB_OUTPUT.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SLOTS = ["08:00", "12:00", "16:00", "20:00", "21:00"]
WINDOW = dt.timedelta(hours=2)  # GitHub can start scheduled runs late; accept up to 2 hours
HISTORY = Path(__file__).parent / "data" / "run_history.jsonl"
SUMMARY_SENT = Path(__file__).parent / "data" / "summary_sent.json"
SUMMARY_FROM = dt.time(22, 30)   # a day's summary is due from 10:30 PM...
SUMMARY_UNTIL = dt.time(2, 0)    # ...until 2 AM the next morning, so a late GitHub start still sends it


def slot_start(day, label):
    hour, minute = map(int, label.split(":"))
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET)


def current_slot(now):
    """Latest posting time that has started within the last WINDOW, as (label, date), or None."""
    candidates = []
    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for label in SLOTS:
            start = slot_start(day, label)
            if start <= now < start + WINDOW:
                candidates.append((start, label, day))
    if not candidates:
        return None
    _, label, day = max(candidates)
    return label, day


def already_done(label, day):
    if not HISTORY.exists():
        return False
    for line in HISTORY.read_text().splitlines():
        run = json.loads(line)
        if run.get("slot") == label and run.get("slot_date") == day.isoformat():
            return True
    return False


def summary_due(now):
    """The Eastern date whose summary email is due right now, or None."""
    for day in (now.date(), now.date() - dt.timedelta(days=1)):
        start = dt.datetime.combine(day, SUMMARY_FROM, tzinfo=ET)
        end = dt.datetime.combine(day + dt.timedelta(days=1), SUMMARY_UNTIL, tzinfo=ET)
        if start <= now < end:
            return day
    return None


def summary_already_sent(day):
    return SUMMARY_SENT.exists() and day.isoformat() in json.loads(SUMMARY_SENT.read_text())


def write_output(**values):
    path = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in values.items())
    if path:
        with open(path, "a") as f:
            f.write(lines)
    print(lines, end="")


def main():
    now = dt.datetime.now(ET)
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        write_output(run="true", slot="manual", slot_date=now.date().isoformat(), summary_date="")
        return
    if "summary" in sys.argv:
        day = summary_due(now)
        if day is None:
            print(f"{now:%a %H:%M} Eastern is outside the summary window. Skipping.")
            write_output(run="false", summary_date="")
        elif summary_already_sent(day):
            print(f"The summary for {day} was already sent. Skipping.")
            write_output(run="false", summary_date=day.isoformat())
        else:
            write_output(run="true", summary_date=day.isoformat())
        return
    found = current_slot(now)
    if found is None:
        print(f"{now:%a %H:%M} Eastern is not a posting time. Skipping.")
        write_output(run="false", slot="", slot_date="")
        return
    label, day = found
    if already_done(label, day):
        print(f"The {label} slot for {day} already ran. Skipping.")
        write_output(run="false", slot=label, slot_date=day.isoformat())
        return
    write_output(run="true", slot=label, slot_date=day.isoformat())


if __name__ == "__main__":
    sys.exit(main())
