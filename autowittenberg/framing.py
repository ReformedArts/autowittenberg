"""Where each photo can safely be cropped, shared by Instagram slides and Pinterest pins.

Claude marks the box that must stay visible (once per photo, remembered forever); each format then
checks whether its own shape can hold that box, and Claude inspects the actual crop before it is
trusted. Anything that fails or errors falls back to showing the whole photo over a blurred copy.
"""
from . import state
from .copy import locate_content, verify_crop
from .images import PIN_RATIO, crop_window, download_image

BOX_GROWTH = 0.02  # a small cushion; the visual check is the real safeguard


def get_box(photo, title):
    """Claude's must-keep box for a photo (fractions of width/height), asked for at most once."""
    key = str(photo["image_id"])
    boxes = state.load_boxes()
    if key not in boxes:
        saved = state.load_framing().get(key, {}).get("box")  # reuse what the Instagram work already found
        if saved:
            boxes[key] = {"box": saved, "reason": "from Instagram framing"}
        else:
            boxes[key] = locate_content(photo["url"], title)
        state.save_boxes(boxes)
    return boxes[key]["box"]


def frame_pin(photo, title):
    """Decide once, per photo, how a 2:3 Pinterest pin may show it.
    Returns {"can_crop": bool, "window": [l, t, r, b] | None, "why": str}; remembered forever."""
    key = str(photo["image_id"])
    cache = state.load_pin_framing()
    if key in cache:
        return cache[key]
    image = download_image(photo["url"])
    framing = {"can_crop": False, "window": None, "why": ""}
    if abs(image.width / image.height - PIN_RATIO) / PIN_RATIO < 0.08:
        framing = {"can_crop": True, "window": [0, 0, image.width, image.height], "why": "already the right shape"}
    else:
        x0, y0, x1, y1 = get_box(photo, title)
        grown = [max(0, x0 - BOX_GROWTH), max(0, y0 - BOX_GROWTH), min(1, x1 + BOX_GROWTH), min(1, y1 + BOX_GROWTH)]
        window = crop_window(image.width, image.height, grown, PIN_RATIO, margin=0.0)
        if window is None:
            framing["why"] = "content too large to crop safely"
        else:
            check = verify_crop(image.crop(window).resize((540, 810)))
            if check["cut_off"]:
                framing["why"] = f"crop vetoed: {check['what'][:80]}"
            else:
                framing = {"can_crop": True, "window": list(window), "why": "content fits"}
    cache[key] = framing
    state.save_pin_framing(cache)
    return framing
