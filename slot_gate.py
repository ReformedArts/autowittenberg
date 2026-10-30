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
WINDOW = dt.timedelta(hours=14)  # GitHub starts only a few scheduled runs a day; a late run still fills any slot missed in the last 14 hours
MAX_PER_RUN = 3                  # catch up at most this many pins in one run, so a long gap is not posted as one big burst
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


def unfilled_slots(now):
    """Every posting time that started within the last WINDOW and has not run yet, oldest first,
    as [(label, date), ...], at most MAX_PER_RUN. A flaky scheduler may start only a few runs a day,
    so each run posts everything that is due rather than a single pin."""
    due = []
    for day in (now.date() - dt.timedelta(days=1), now.date()):
        for label in SLOTS:
            start = slot_start(day, label)
            if start <= now < start + WINDOW and not already_done(label, day):
                due.append((label, day))
    return due[:MAX_PER_RUN]


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
        write_output(run="true", slot="manual", slot_date=now.date().isoformat(), slots=f"manual@{now.date().isoformat()}", summary_date="")
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
    due = unfilled_slots(now)
    if not due:
        print(f"{now:%a %H:%M} Eastern: no posting slot is open and unfilled. Skipping.")
        write_output(run="false", slot="", slot_date="", slots="")
        return
    print(f"{now:%a %H:%M} Eastern: {len(due)} pin(s) due.")
    write_output(run="true", slot=due[0][0], slot_date=due[0][1].isoformat(),
                 slots=" ".join(f"{label}@{day.isoformat()}" for label, day in due))


if __name__ == "__main__":
    sys.exit(main())
