"""Stage 3 test: post exactly ONE pin to Pinterest, using a pin image generated earlier
and the cached Claude-written copy for that listing, so you can confirm it lands on the
right board with the right title, description, and link.

Run with:   .venv/bin/python post_test_pin.py
"""
import json
import sys
from pathlib import Path

from autowittenberg.copy import BOARD_THEMES
from autowittenberg.pinterest import PinterestClient, PinterestError

ROOT = Path(__file__).parent
IMAGE = ROOT / "data" / "pin_previews" / "final_4.jpg"
LISTING_FRAGMENT = "Five Solas Poster Set"
SANDBOX = "--live" not in sys.argv  # pass --live only once Standard access is approved


def main():
    pool = json.loads((ROOT / "data" / "rotation_pool.json").read_text())
    listing = next(p for p in pool if LISTING_FRAGMENT in p["title"])
    board_name = BOARD_THEMES[listing["board_theme"]]

    client = PinterestClient(sandbox=SANDBOX)
    if SANDBOX:
        # The practice environment starts empty, and Pinterest still rejects names that
        # match your real boards, so use a distinct test board name there.
        board_name = "AutoWittenberg Sandbox Test"
        board = client.get_or_create_board(board_name)
    else:
        board = client.find_board(board_name)
    if not board:
        raise SystemExit(f"Board '{board_name}' not found on your Pinterest account.")

    print(f"Posting 1 test pin ({'SANDBOX practice environment' if SANDBOX else 'LIVE'}) to board '{board['name']}'")
    print(f"  Title: {listing['pin_title']}")
    print(f"  Link:  {listing['url']}")
    try:
        pin = client.create_pin(
            board_id=board["id"],
            image_path=IMAGE,
            title=listing["pin_title"],
            description=listing["pin_description"],
            link=listing["url"],
        )
    except PinterestError as e:
        raise SystemExit(f"\nPin was NOT posted:\n  {e}\n")

    print(f"\nPosted. Pin id: {pin.get('id')}")
    if not SANDBOX:
        print(f"View it at: https://www.pinterest.com/pin/{pin.get('id')}/")


if __name__ == "__main__":
    main()
