"""Uses the Claude API to write Pinterest pin copy and to classify listing photos.

Kept deliberately small and cheap: one call per listing for copy (cached after that,
not regenerated on every post), and one call per photo the first time it's ever seen,
using a cost-efficient model since this is low-volume, low-complexity work.
"""
import base64
import html
import sys
from io import BytesIO

import anthropic
import requests
from PIL import Image

from . import config, usage

MODEL = "claude-haiku-4-5-20251001"

_client = None


class _LoggedMessages:
    """Same as the client's messages, but writes each call's cost to data/claude_usage.jsonl."""

    def __init__(self, messages):
        self._messages = messages

    def create(self, **kwargs):
        message = self._messages.create(**kwargs)
        usage.record(message, sys._getframe(1).f_code.co_name, kwargs.get("model", MODEL))
        return message


class _LoggedClient:
    def __init__(self, client):
        self.messages = _LoggedMessages(client.messages)


def _get_client():
    global _client
    if _client is None:
        _client = _LoggedClient(anthropic.Anthropic(api_key=config.require("ANTHROPIC_API_KEY")))
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


def _prepared_image_b64(image_url):
    """Download, downscale (classification doesn't need full resolution, and it keeps costs
    minimal) and base64-encode a photo for Claude's vision input."""
    resp = requests.get(image_url, timeout=20)
    resp.raise_for_status()
    image = Image.open(BytesIO(resp.content)).convert("RGB")
    image.thumbnail((1024, 1024), Image.LANCZOS)
    buf = BytesIO()
    image.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def classify_photo(image_url, listing_title):
    """One Claude vision call -> whether a photo is usable pin artwork."""
    b64 = _prepared_image_b64(image_url)

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


RELEVANCE_TOOL = {
    "name": "submit_relevance",
    "description": "Say how well one Etsy listing fits a seasonal occasion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevance": {
                "type": "string",
                "enum": ["priority", "related", "unrelated"],
                "description": (
                    "'priority': made for the occasion itself (party decor, banners, cards, or "
                    "items named for it). 'related': specifically about the occasion's subject. "
                    "For Reformation Day that means the Protestant Reformation itself: its "
                    "people (Luther, Calvin, Zwingli, Hus, Knox), events (the 95 Theses, Diet of "
                    "Worms), places (Wittenberg, Geneva, Zurich) or slogans (the five solas, "
                    "Post Tenebras Lux, Here I Stand). 'unrelated': everything else, including "
                    "general Christian or scripture art, creeds, classic literature such as "
                    "Pilgrim's Progress or Narnia, and Reformed-flavored items with no "
                    "specific Reformation connection."
                ),
            },
            "reason": {"type": "string", "description": "One short phrase."},
        },
        "required": ["relevance", "reason"],
    },
}


def classify_occasion_relevance(listing, theme):
    prompt = (
        f"Occasion: {theme}\nEtsy listing title: {listing['title']}\n"
        f"Etsy SEO tags: {', '.join(listing.get('tags', []))}\n\n"
        "How well does this listing fit the occasion?"
    )
    message = _get_client().messages.create(
        model=MODEL, max_tokens=150, tools=[RELEVANCE_TOOL],
        tool_choice={"type": "tool", "name": "submit_relevance"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _tool_input(message)


CAPTION_TOOL = {
    "name": "submit_caption",
    "description": "Submit the Instagram caption pieces for one Etsy listing's carousel.",
    "input_schema": {
        "type": "object",
        "properties": {
            "body": {
                "type": "string",
                "description": (
                    "Caption text under 1,200 characters: a one-line hook, then 3-5 short lines on "
                    "where, how or why someone would use the piece (benefit/context driven, accurate "
                    "to whether it is a digital download or a physical item). Use line breaks and a "
                    "few tasteful emoji. No hashtags and no links."
                ),
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 8,
                "maxItems": 12,
                "description": "8-12 relevant hashtags without the # symbol, no spaces; mix broad and specific.",
            },
            "alt_text": {
                "type": "string",
                "description": "One factual sentence under 200 characters describing the product for screen readers.",
            },
        },
        "required": ["body", "hashtags", "alt_text"],
    },
}


def _valid_caption(c):
    tags = c.get("hashtags")
    return (
        isinstance(c.get("body"), str) and 80 <= len(c["body"]) <= 1500
        and isinstance(c.get("alt_text"), str) and 10 <= len(c["alt_text"]) <= 250
        and isinstance(tags, list) and 5 <= len(tags) <= 20
        and all(isinstance(t, str) and t.strip() and " " not in t.strip().lstrip("#") for t in tags)
    )


def generate_instagram_caption(listing):
    """Claude writes the caption body, hashtags and alt text; validated, one retry."""
    description = html.unescape(listing.get("description", ""))[:900]
    prompt = (
        f"Etsy listing title: {listing['title']}\n\nDescription (excerpt): {description}\n\n"
        f"Tags: {', '.join(listing.get('tags', []))}\n\n"
        "Write the Instagram caption pieces for this listing's carousel. This is a small Etsy shop "
        "selling Christian and classic-literature-themed art, mostly printable digital downloads."
    )
    for _ in range(2):
        message = _get_client().messages.create(
            model=MODEL, max_tokens=900, tools=[CAPTION_TOOL],
            tool_choice={"type": "tool", "name": "submit_caption"},
            messages=[{"role": "user", "content": prompt}],
        )
        result = _tool_input(message)
        if _valid_caption(result):
            result["hashtags"] = [h.strip().lstrip("#") for h in result["hashtags"]]
            return result
    raise RuntimeError(f"Claude returned a malformed caption twice for '{listing['title'][:50]}'")


def get_instagram_copy(listing, cache):
    """Cached: Claude is only ever called once per listing for its Instagram caption."""
    key = str(listing["listing_id"])
    if key not in cache:
        cache[key] = generate_instagram_caption(listing)
    return cache[key]


BOX_TOOL = {
    "name": "mark_content_box",
    "description": "Mark the part of a listing photo that must never be cropped away.",
    "input_schema": {
        "type": "object",
        "properties": {
            "x0": {"type": "number"}, "y0": {"type": "number"},
            "x1": {"type": "number"}, "y1": {"type": "number"},
            "reason": {"type": "string", "description": "One short phrase on what the box contains."},
        },
        "required": ["x0", "y0", "x1", "y1", "reason"],
    },
}


def locate_content(image_url, listing_title):
    """Claude marks the smallest box (fractions of width/height, origin top-left) that holds
    everything that must stay visible. The code, not Claude, then decides whether cropping is safe."""
    b64 = _prepared_image_b64(image_url)
    prompt = (
        f"This photo is from the Etsy listing '{listing_title}'. Mark the SMALLEST rectangle, as fractions of the "
        "image width and height with (0,0) at the top-left, that contains ALL of the following: every product or "
        "artwork shown (every piece in a set, every mug, shirt, frame or print), and every piece of text, "
        "lettering, logo, badge or watermark that is part of the image. Exclude only empty background such as "
        "blank walls, floors, tabletops, shadows, and decorative items that are not for sale. If the picture is a "
        "flat graphic that fills the whole frame, return the full frame (0, 0, 1, 1). When unsure, make the box "
        "larger, not smaller."
    )
    message = _get_client().messages.create(
        model=MODEL, max_tokens=200, tools=[BOX_TOOL],
        tool_choice={"type": "tool", "name": "mark_content_box"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    box = _tool_input(message)
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(box[k]))) for k in ("x0", "y0", "x1", "y1"))
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:  # nonsense box -> treat as "everything matters"
        x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    return {"box": [x0, y0, x1, y1], "reason": box.get("reason", "")}


CUTOFF_TOOL = {
    "name": "report_cutoff",
    "description": "Report whether a cropped product photo has anything important cut off.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cut_off": {"type": "boolean", "description": "True if any part of a product (a mug handle, a frame corner, a poster edge, a shirt sleeve) or any text, lettering, logo or badge is cut off or only partly visible at the image's edges."},
            "what": {"type": "string", "description": "What is cut off, or 'nothing'."},
        },
        "required": ["cut_off", "what"],
    },
}


def verify_crop(pil_image):
    """Claude looks at an already-cropped image and says whether anything important is cut off."""
    buf = BytesIO()
    pil_image.convert("RGB").save(buf, "JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    message = _get_client().messages.create(
        model=MODEL, max_tokens=150, tools=[CUTOFF_TOOL],
        tool_choice={"type": "tool", "name": "report_cutoff"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": "This product photo was just cropped. Look carefully at all four edges: is any part of a product (including handles, frame edges, corners, sleeves), or any text/lettering/logo/badge, cut off, clipped, or touching an edge so that it looks incomplete? Ignore plain background."},
        ]}],
    )
    return _tool_input(message)


EXCLUSION_TOOL = {
    "name": "submit_exclusion_check",
    "description": "Say whether one Etsy listing matches a seasonal exclusion description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean", "description": "True only if the listing clearly matches the description given."},
            "reason": {"type": "string", "description": "One short phrase."},
        },
        "required": ["matches", "reason"],
    },
}


def classify_exclusion(listing, description):
    prompt = (
        f"Etsy listing title: {listing['title']}\nTags: {', '.join(listing.get('tags', []))}\n\n"
        f"Is this listing {description}? Answer true only if it clearly is that kind of product; "
        "wall art, prints, mugs, shirts and stickers are not party supplies."
    )
    message = _get_client().messages.create(
        model=MODEL, max_tokens=120, tools=[EXCLUSION_TOOL],
        tool_choice={"type": "tool", "name": "submit_exclusion_check"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _tool_input(message)
