"""Short, narrated demo of the Pinterest API calls AutoWittenberg makes.
Used for the screen recording Pinterest asks for when upgrading to Standard access.
Prints no secrets.

Run with:   .venv/bin/python pinterest_demo.py
"""
import json
from pathlib import Path

from autowittenberg.pinterest import PinterestClient

ROOT = Path(__file__).parent


def main():
    print("\n=== AutoWittenberg: Pinterest API demo ===\n")

    print("1) Reading my boards (boards:read) using the OAuth token I just authorized...")
    for board in PinterestClient().list_boards():
        print(f"   - {board['name']}")

    pool = json.loads((ROOT / "data" / "rotation_pool.json").read_text())
    listing = next(p for p in pool if "Five Solas Poster Set" in p["title"])

    print("\n2) Creating a pin for one of my own Etsy products (pins:write)...")
    client = PinterestClient(sandbox=True)
    board = client.get_or_create_board("AutoWittenberg Sandbox Test")
    pin = client.create_pin(
        board_id=board["id"],
        image_path=ROOT / "data" / "pin_previews" / "final_4.jpg",
        title=listing["pin_title"],
        description=listing["pin_description"],
        link=listing["url"],
    )
    print(f"   Created pin {pin['id']}")
    print(f"   Title: {listing['pin_title']}")
    print(f"   Links to my Etsy listing: {listing['url']}")
    print("\nDone. The app only ever acts on my own account with permissions I granted.\n")


if __name__ == "__main__":
    main()
