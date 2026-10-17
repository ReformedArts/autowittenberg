"""Builds one Instagram carousel per listing: slides (4:5 JPEGs) and the caption."""
from pathlib import Path

from .copy import locate_content, verify_crop
from .images import IG_SIZE, PALETTES, crop_window, download_image, render_slide

MAX_SLIDES = 10  # Instagram's carousel limit


def choose_slides(listing):
    """Up to 10 photos: clean artwork first (rank order), then photos that carry their own text."""
    photos = listing["photos"]
    ordered = [p for p in photos if p.get("kind") != "text_heavy"] + [p for p in photos if p.get("kind") == "text_heavy"]
    return ordered[:MAX_SLIDES]


def build_caption(listing, copy):
    """Claude's body, then the shop link as plain text (Instagram captions can't hold clickable
    links), then hashtags."""
    tags = " ".join(f"#{t}" for t in copy["hashtags"])
    return f"{copy['body'].strip()}\n\n\U0001F6D2 Shop: {listing['url']}\n(Link in bio)\n\n{tags}"


def render_carousel(listing, out_dir, headline=None):
    """Renders the slides; returns [(path, photo)] in carousel order. Needs at least 2 slides."""
    slides = choose_slides(listing)
    palette = list(PALETTES)[int(listing["listing_id"]) % len(PALETTES)]
    out = []
    for i, photo in enumerate(slides):
        path = Path(out_dir) / f"{listing['listing_id']}_slide{i + 1}.jpg"
        render_slide(photo["url"], photo.get("kind", "artwork"), path, palette,
                     headline=headline if i == 0 else None)
        out.append((path, photo))
    return out


BOX_GROWTH = 0.02  # a small cushion; the visual check below is the real safeguard


def frame_photo(photo, title, cache):
    """Decide once, per photo, whether it can be cropped to 4:5 or must be shown whole.
    1) Claude marks what must stay; 2) the code checks a 4:5 window can hold it with room to spare;
    3) if so, Claude inspects the actual cropped result and vetoes it if anything is cut off.
    Returns {"mode": "crop", "window": [l, t, r, b]} or {"mode": "fit"}; remembered forever."""
    key = str(photo["image_id"])
    if key in cache:
        return cache[key]
    target = IG_SIZE[0] / IG_SIZE[1]
    image = download_image(photo["url"])
    framing = {"mode": "fit"}
    if abs(image.width / image.height - target) / target < 0.08:
        framing = {"mode": "crop", "window": [0, 0, image.width, image.height], "why": "already the right shape"}
    else:
        info = locate_content(photo["url"], title)
        x0, y0, x1, y1 = info["box"]
        grown = [max(0, x0 - BOX_GROWTH), max(0, y0 - BOX_GROWTH), min(1, x1 + BOX_GROWTH), min(1, y1 + BOX_GROWTH)]
        window = crop_window(image.width, image.height, grown, target, margin=0.0)
        if window:
            check = verify_crop(image.crop(window).resize((540, 675)))
            if check["cut_off"]:
                framing = {"mode": "fit", "why": f"crop vetoed: {check['what'][:80]}", "box": [round(v, 2) for v in info["box"]]}
            else:
                framing = {"mode": "crop", "window": list(window), "why": info["reason"][:80], "box": [round(v, 2) for v in info["box"]]}
        else:
            framing = {"mode": "fit", "why": "content too large to crop safely", "box": [round(v, 2) for v in info["box"]]}
    cache[key] = framing
    return framing
