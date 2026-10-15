"""Stage 1 test: connect to Etsy, pull every active listing, and save it to data/listings.json.

Run with:   .venv/bin/python fetch_listings.py
"""
import json
from pathlib import Path

from autowittenberg.etsy import EtsyError, fetch_shop_snapshot

OUTPUT = Path(__file__).parent / "data" / "listings.json"


def main():
    try:
        snapshot = fetch_shop_snapshot()
    except EtsyError as e:
        raise SystemExit(f"\nEtsy connection failed:\n  {e}\n")

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    listings = snapshot["listings"]
    print(f"\nConnected to Etsy shop: {snapshot['shop_name']} (id {snapshot['shop_id']})")
    print(f"Active listings found: {len(listings)}\n")
    for i, listing in enumerate(listings, 1):
        print(f"{i:>2}. {listing['title'][:80]}")
        print(f"    Link:   {listing['url']}")
        print(f"    Photos: {len(listing['images'])}")
        print(f"    Tags:   {', '.join(listing['tags'][:8])}{' ...' if len(listing['tags']) > 8 else ''}\n")
    print(f"Full details saved to {OUTPUT.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
