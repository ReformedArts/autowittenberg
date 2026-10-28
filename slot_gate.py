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
WINDOW = dt.timedelta(hours=5)  # GitHub can start scheduled runs hours late (or drop them); a late run still fills a missed slot
HISTORY = Path(__file__).parent / "data" / "run_history.jsonl"
SUMMARY_SENT = Path(__file__).parent / "data" / "summary_sent.json"
IG_FROM = dt.time(19, 30)       # the Instagram carousel goes out at 7:30 PM Eastern...
IG_UNTIL = dt.time(1, 30)       # ...or, if GitHub starts late or drops runs, any time until 1:30 AM that night
IG_HISTORY = Path(__file__).parent / "data" / "instagram_history.jsonl"
SUMMARY_FROM = dt.time(22, 45)   # a day's summary is due from 10:45 PM...
SUMMARY_UNTIL = dt.time(10, 0)   # ...until 10 AM the next morning, so a late or dropped GitHub run still sends it


def slot_start(day, label):
    hour, minute = map(int, label.split(":"))
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET)


def next_unfilled_slot(now):
    """The earliest posting time that started within the last WINDOW and has not run yet, as
    (label, date), or None. Catching up the oldest missed slot first means a flaky scheduler
    still ends up filling the day, one pin per run."""
    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for label in SLOTS:
            start = slot_start(day, label)
            if start <= now < start + WINDOW and not already_done(label, day):
                return label, day
    return None


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


def instagram_due(now):
    """The date of the 7:30 PM slot that is currently open (until 1:30 AM that night), else None."""
    for day in (now.date(), now.date() - dt.timedelta(days=1)):
        start = dt.datetime.combine(day, IG_FROM, tzinfo=ET)
        end = dt.datetime.combine(day + dt.timedelta(days=1), IG_UNTIL, tzinfo=ET)
        if start <= now < end:
            return day
    return None


def instagram_already_done(day):
    """Any live attempt (success or failure) for this date counts, so a failure is never retried in a loop."""
    if not IG_HISTORY.exists():
        return False
    return any(json.loads(line).get("slot_date") == day.isoformat() for line in IG_HISTORY.read_text().splitlines())


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
    if "instagram" in sys.argv:
        day = instagram_due(now)
        if day is None:
            print(f"{now:%a %H:%M} Eastern is outside the Instagram window. Skipping.")
            write_output(run="false", slot_date="")
        elif instagram_already_done(day):
            print(f"Instagram already ran for {day}. Skipping.")
            write_output(run="false", slot_date=day.isoformat())
        else:
            write_output(run="true", slot_date=day.isoformat())
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
    found = next_unfilled_slot(now)
    if found is None:
        print(f"{now:%a %H:%M} Eastern: no posting slot is open and unfilled. Skipping.")
        write_output(run="false", slot="", slot_date="")
        return
    label, day = found
    write_output(run="true", slot=label, slot_date=day.isoformat())


if __name__ == "__main__":
    sys.exit(main())
