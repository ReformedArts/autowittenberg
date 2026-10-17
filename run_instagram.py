"""Runs the Instagram poster once.

  .venv/bin/python run_instagram.py                      preview the next carousel (nothing is uploaded or posted)
  .venv/bin/python run_instagram.py --mode prepare       full test: upload the slides, have Instagram process them, do NOT publish
  .venv/bin/python run_instagram.py --mode live          publish the next carousel to your REAL Instagram
  .venv/bin/python run_instagram.py --listing 4595749006 work on one specific listing
"""
import argparse

from autowittenberg.instagram_runner import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry-run", "prepare", "live"], default="dry-run")
    parser.add_argument("--listing", default=None, help="Etsy listing id to use instead of the automatic pick")
    parser.add_argument("--slot", default=None)
    parser.add_argument("--slot-date", default=None)
    args = parser.parse_args()
    result = run(args.mode, args.listing, args.slot, args.slot_date)
    print("\nResult:", "posted" if result.get("posted") else ("ERROR: " + result["error"] if result.get("error") else "no post made"))


if __name__ == "__main__":
    main()
