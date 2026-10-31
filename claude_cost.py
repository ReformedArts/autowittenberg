"""Totals what Claude calls have cost, from data/claude_usage.jsonl.

  .venv/bin/python claude_cost.py          cost per day and per kind of work
"""
import collections
import json
from pathlib import Path

PATH = Path(__file__).parent / "data" / "claude_usage.jsonl"
HISTORY = Path(__file__).parent / "data" / "claude_usage_history.json"  # daily totals from before logging began


def main():
    history = json.loads(HISTORY.read_text())["days"] if HISTORY.exists() else []
    rows = [json.loads(line) for line in PATH.read_text().splitlines()] if PATH.exists() else []
    if not history and not rows:
        print("No usage recorded yet.")
        return
    by_day, by_kind = collections.defaultdict(lambda: [0, 0.0]), collections.defaultdict(lambda: [0, 0.0])
    for h in history:  # daily totals only, so no call counts or kinds of work
        by_day[h["date"]][1] += h["usd"]
    for r in rows:
        for bucket, key in ((by_day, r["time"][:10]), (by_kind, r["purpose"])):
            bucket[key][0] += 1
            bucket[key][1] += r["usd"]
    print("PER DAY (UTC; calls shown only for days with live logging)")
    for day, (n, usd) in sorted(by_day.items()):
        print(f"  {day}  {str(n) + ' calls' if n else '':>11}  ${usd:.3f}")
    if by_kind:
        print("PER KIND OF WORK (live logging only)")
        for kind, (n, usd) in sorted(by_kind.items(), key=lambda x: -x[1][1]):
            print(f"  {kind:34s} {n:4d} calls  ${usd:.3f}")
    print(f"BEFORE LOGGING (from console export): ${sum(h['usd'] for h in history):.3f}")
    print(f"LIVE LOGGING: {len(rows)} calls  ${sum(r['usd'] for r in rows):.3f}")
    print(f"TOTAL: ${sum(h['usd'] for h in history) + sum(r['usd'] for r in rows):.3f}")


if __name__ == "__main__":
    main()
