"""Uses the Claude API to write Pinterest pin copy and to classify listing photos.

Kept deliberately small and cheap: one call per listing for copy (cached after that,
not regenerated on every post), and one call per photo the first time it's ever seen,
using a cost-efficient model since this is low-volume, low-complexity work.
"""
import base64
import html
from io import BytesIO

import anthropic
import requests
from PIL import Image

from . import config

MODEL = "claude-haiku-4-5-20251001"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))
    return _client


def _tool_input(message):
    for block in message.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Claude did not call the expected tool.")


# Fixed set of themed Pinterest boards. Keys are what Claude picks between; values are
# the actual board names on Pinterest.
BOARD_THEMES = {
    "reformation_art": "Reformed Art",
    "reformation_95_theses": "95 Theses Art",
    "reformation_travel_posters": "Retro Travel Posters",
    "narnia_literary_art": "Narnia & Literary Art",
    "scripture_art": "Scripture Art",
    "gifts_and_merch": "Reformed Gifts",
}

COPY_TOOL = {
    "name": "submit_pin_copy",
    "description": "Submit the finished Pinterest pin copy for one Etsy listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "board_theme": {
                "type": "string",
                "enum": list(BOARD_THEMES.keys()),
                "description": (
                    "Which themed Pinterest board this listing belongs on. "
                    "'reformation_art': General Reformation history/theology art not "
                    "covered by a more specific category below (e.g. Luther quote "
                    "prints, Five Solas, Reformation Heroes portraits, Post Tenebras "
                    "Lux prints). 'reformation_95_theses': art specifically about "
                    "Martin Luther's 95 Theses. 'reformation_travel_posters': "
                    "retro/vintage-style travel poster sets depicting Reformation "
                    "cities or landmarks (e.g. Wittenberg, Geneva, Zurich, Worms). "
                    "'narnia_literary_art': Narnia or other classic-literature-themed "
                    "art. 'scripture_art': Bible verse or scripture-themed art not "
                    "specifically about the Reformation. 'gifts_and_merch': physical "
                    "items like mugs, stickers, apparel."
                ),
            },
            "pin_title": {
                "type": "string",
                "description": (
                    "SEO-friendly Pinterest pin title, 40-100 characters, using keywords "
                    "similar to the listing's own Etsy SEO tags."
                ),
            },
            "pin_description": {
                "type": "string",
                "description": (
                    "Pinterest pin description, 150-400 characters. Benefit/context driven, "
                    "natural keyword use (not keyword stuffing), ends with a soft call to "
                    "action. No hashtags."
                ),
            },
            "overlay_headlines": {
                "type": "array",
                "description": (
                    "5 distinct short overlay lines for pin images, each a different angle "
                    "(e.g. where to hang or use it, who it's a gift for, an occasion, an "
                    "aesthetic descriptor, a specific use-case). Each under 9 words, no "
                    "ending punctuation, benefit/context driven rather than generic "
                    "phrasing like 'beautiful wall art'."
                ),
                "items": {"type": "string"},
                "minItems": 5,
                "maxItems": 5,
            },
        },
        "required": ["board_theme", "pin_title", "pin_description", "overlay_headlines"],
    },
}

CLASSIFY_TOOL = {
    "name": "classify_photo",
    "description": "Classify one Etsy listing photo for Pinterest pin use.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["artwork", "infographic", "text_heavy", "watermarked"],
                "description": (
                    "'artwork': a clean photo or styled mockup of the actual piece, "
                    "suitable to use as a pin's hero image, with little or no text baked "
                    "into the photo itself. "
                    "'infographic': a size guide, printing/download instructions, or other "
                    "instructional graphic with no real product photo. "
                    "'text_heavy': a good-looking styled product photo that already has "
                    "significant promotional text baked into it (e.g. a 'DIGITAL DOWNLOAD' "
                    "banner or large title text overlaid on the photo), but NO tiled or "
                    "repeating watermark. It would clash with our own pin text overlay, so "
                    "it is used without one. "
                    "'watermarked': the image has a semi-transparent watermark (such as a "
                    "shop name) repeated or tiled across the picture, regardless of any "
                    "other text."
                ),
            },
            "reason": {"type": "string", "description": "One short phrase explaining the call."},
        },
        "required": ["category", "reason"],
    },
}


def _valid_copy(copy):
    headlines = copy.get("overlay_headlines")
    return (
        copy.get("board_theme") in BOARD_THEMES
        and isinstance(copy.get("pin_title"), str) and copy["pin_title"].strip()
        and isinstance(copy.get("pin_description"), str) and copy["pin_description"].strip()
        and isinstance(headlines, list) and len(headlines) >= 3
        and all(isinstance(h, str) and 8 <= len(h) <= 80 for h in headlines)
    )


def generate_listing_copy(listing):
    """Asks Claude for pin copy; checks it is well-formed and retries once if not,
    so a garbled answer can never end up on a pin."""
    for _ in range(2):
        copy = _generate_listing_copy_once(listing)
        if _valid_copy(copy):
            return copy
    raise RuntimeError(f"Claude returned malformed copy twice for '{listing['title'][:50]}'")


def _generate_listing_copy_once(listing):
    """One Claude call -> pin title, pin description, and 5 overlay headline options."""
    description = html.unescape(listing.get("description", ""))[:600]
    tags = ", ".join(listing.get("tags", []))

    prompt = (
        f"Etsy listing title: {listing['title']}\n\n"
        f"Etsy listing description (excerpt): {description}\n\n"
        f"Etsy SEO tags: {tags}\n\n"
        "Write Pinterest pin copy for this listing. This is a small Etsy shop selling "
        "Christian and classic-literature-themed wall art, mostly printable digital "
        "downloads with a few physical items. Match the tone and keywords the shop "
        "already uses in its own Etsy SEO."
    )

    message = _get_client().messages.create(
        model=MODEL,
        max_tokens=600,
        tools=[COPY_TOOL],
        tool_choice={"type": "tool", "name": "submit_pin_copy"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _tool_input(message)


def classify_photo(image_url, listing_title):
    """One Claude vision call -> whether a photo is usable pin artwork."""
    resp = requests.get(image_url, timeout=20)
    resp.raise_for_status()

    # Downscale before sending -- classification doesn't need full resolution, and
    # this keeps token usage (and cost) minimal.
    image = Image.open(BytesIO(resp.content)).convert("RGB")
    image.thumbnail((1024, 1024), Image.LANCZOS)
    buf = BytesIO()
    image.save(buf, "JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    message = _get_client().messages.create(
        model=MODEL,
        max_tokens=200,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_photo"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": f"This photo is from the Etsy listing '{listing_title}'. Classify it."},
            ],
        }],
    )
    return _tool_input(message)


def get_listing_copy(listing, cache):
    """Cached wrapper around generate_listing_copy -- only ever calls Claude once per
    listing_id; `cache` is a plain dict you load/save with autowittenberg.state."""
    key = str(listing["listing_id"])
    if key not in cache:
        cache[key] = generate_listing_copy(listing)
    return cache[key]


def get_photo_classification(image, listing_title, cache):
    """Cached wrapper around classify_photo -- only ever calls Claude once per
    image_id, ever, matching the "classify once, the first time it's seen" rule."""
    key = str(image["image_id"])
    if key not in cache:
        cache[key] = classify_photo(image["url"], listing_title)
    return cache[key]


HEADLINES_TOOL = {
    "name": "submit_headlines",
    "description": "Submit short seasonal overlay headlines for one Etsy listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headlines": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 4,
                "maxItems": 4,
                "description": (
                    "4 distinct overlay lines for pin images, each under 9 words, no ending "
                    "punctuation, tying the product to the given occasion through a benefit or "
                    "use (party, gift, home or church display, wearing it). Be accurate to the "
                    "product type (digital download vs physical item). No prices."
                ),
            },
        },
        "required": ["headlines"],
    },
}


def generate_seasonal_headlines(listing, theme):
    """4 occasion-specific overlay headlines for one listing (one small Claude call)."""
    prompt = (
        f"Occasion: {theme}\n"
        f"Etsy listing title: {listing['title']}\n"
        f"Etsy SEO tags: {', '.join(listing.get('tags', []))}\n\n"
        "Write 4 short pin overlay headlines connecting this product to the occasion."
    )
    for _ in range(2):
        message = _get_client().messages.create(
            model=MODEL, max_tokens=300, tools=[HEADLINES_TOOL],
            tool_choice={"type": "tool", "name": "submit_headlines"},
            messages=[{"role": "user", "content": prompt}],
        )
        heads = _tool_input(message).get("headlines")
        if isinstance(heads, list) and len(heads) >= 3 and all(isinstance(h, str) and 8 <= len(h) <= 80 for h in heads):
            return heads
    raise RuntimeError(f"Claude returned malformed headlines twice for '{listing['title'][:50]}'")
