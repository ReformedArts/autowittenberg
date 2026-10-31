"""Totals what Claude calls have cost, from data/claude_usage.jsonl.

  .venv/bin/python claude_cost.py          cost per day and per kind of work
"""
import collections
import json
from pathlib import Path

PATH = Path(__file__).parent / "data" / "claude_usage.jsonl"


def main():
    if not PATH.exists():
        print("No usage recorded yet.")
        return
    rows = [json.loads(line) for line in PATH.read_text().splitlines()]
    by_day, by_kind = collections.defaultdict(lambda: [0, 0.0]), collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        for bucket, key in ((by_day, r["time"][:10]), (by_kind, r["purpose"])):
            bucket[key][0] += 1
            bucket[key][1] += r["usd"]
    print("PER DAY (UTC)")
    for day, (n, usd) in sorted(by_day.items()):
        print(f"  {day}  {n:4d} calls  ${usd:.3f}")
    print("PER KIND OF WORK")
    for kind, (n, usd) in sorted(by_kind.items(), key=lambda x: -x[1][1]):
        print(f"  {kind:34s} {n:4d} calls  ${usd:.3f}")
    print(f"TOTAL  {len(rows)} calls  ${sum(r['usd'] for r in rows):.3f}  (since logging began)")


if __name__ == "__main__":
    main()
