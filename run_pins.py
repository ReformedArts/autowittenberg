"""Runs AutoWittenberg once.

Examples:
  .venv/bin/python run_pins.py --count 10              preview 10 pins (dry run: nothing is posted)
  .venv/bin/python run_pins.py --mode sandbox          post 1 pin to Pinterest's practice environment
  .venv/bin/python run_pins.py --mode live             post 1 pin to your REAL Pinterest (needs Standard access)

To pause everything quickly, create an empty file named PAUSED in this folder
(delete it to resume).
"""
import argparse

from autowittenberg.runner import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1, help="how many pins to make this run")
    parser.add_argument("--mode", choices=["dry-run", "sandbox", "live"], default="dry-run")
    parser.add_argument("--sync", action="store_true", help="force a fresh Etsy check")
    parser.add_argument("--slot", default=None, help="scheduled posting time label, e.g. 20:00 (set by the cloud schedule)")
    parser.add_argument("--slot-date", default=None, help="local date of that posting time")
    args = parser.parse_args()
    summary = run(count=args.count, mode=args.mode, force_sync=args.sync, slot=args.slot, slot_date=args.slot_date)
    print(f"\nFinished: {len(summary['posted'])} pin(s) made, {len(summary['failed'])} failed.")


if __name__ == "__main__":
    main()
