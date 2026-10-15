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
        write_output(run="true", slot="manual", slot_date=now.date().isoformat())
        return
    if "summary" in sys.argv:  # the daily summary email goes out in the 11 PM Eastern hour
        write_output(run="true" if now.hour == 23 else "false", slot="", slot_date="")
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
