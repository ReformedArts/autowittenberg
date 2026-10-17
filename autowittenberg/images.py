"""Turns one Etsy listing photo into a finished, Pinterest-ready pin image.

Canvas is a portrait 1000x1500 (2:3), since portrait pins outperform square/horizontal
ones. The Etsy photo is the hero and fills the frame; a small color-treated text box
carries a short, benefit-driven line, and the shop logo sits small in a bottom corner
(never the top, since Pinterest's preview crop tends to cut off the top of the image).
"""
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

CANVAS_W, CANVAS_H = 1000, 1500

ASSETS = Path(__file__).parent.parent / "assets"
FONTS = ASSETS / "fonts"
LOGO_PATH = ASSETS / "Logo - Reformed Arts.png"

HEADLINE_FONT_FILE = FONTS / "PlayfairDisplay-Variable.ttf"
BODY_FONT_FILE = FONTS / "Lato-Bold.ttf"

# Warm, saturated palettes for the text box. Each pin variation picks one of these
# so repeated postings of the same listing don't look identical.
PALETTES = {
    "terracotta": {"bg": (193, 80, 46, 235), "text": (255, 248, 236, 255)},
    "gold": {"bg": (201, 138, 30, 235), "text": (43, 27, 14, 255)},
    "oxblood": {"bg": (122, 31, 43, 235), "text": (244, 227, 193, 255)},
    "amber": {"bg": (217, 113, 60, 235), "text": (36, 16, 9, 255)},
}

# Different ways to crop the same source photo into the portrait canvas, so the same
# image can produce a few visually distinct pins.
CROP_STYLES = ("cover_center", "cover_top", "zoom_detail")


def _headline_font(size):
    font = ImageFont.truetype(str(HEADLINE_FONT_FILE), size)
    font.set_variation_by_name("Bold")
    return font


def download_image(url):
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGB")


def cover_crop(im, target_w, target_h, style="cover_center"):
    """Scale the image to fill target_w x target_h, cropping the overflow."""
    src_w, src_h = im.size
    zoom = 1.15 if style == "zoom_detail" else 1.0
    scale = max(target_w / src_w, target_h / src_h) * zoom
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    im = im.resize((new_w, new_h), Image.LANCZOS)

    x = (new_w - target_w) // 2
    if style == "cover_top":
        y = 0
    else:
        y = (new_h - target_h) // 2
    y = max(0, min(y, new_h - target_h))
    x = max(0, min(x, new_w - target_w))
    return im.crop((x, y, x + target_w, y + target_h))


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_text_box(canvas, headline, palette):
    """Rounded, warm-colored box carrying the short benefit-driven headline.

    Placed in the lower half of the canvas, well clear of the top (which Pinterest's
    preview crop tends to cut off) and clear of the bottom-corner logo.
    """
    draw = ImageDraw.Draw(canvas, "RGBA")
    cw, ch = canvas.size
    scale = cw / CANVAS_W
    box_margin = int(60 * scale)
    box_w = cw - 2 * box_margin
    font_size = int(58 * scale)
    font = _headline_font(font_size)

    lines = _wrap_text(draw, headline, font, box_w - 80)
    while len(lines) > 3 and font_size > int(36 * scale):
        font_size -= 4
        font = _headline_font(font_size)
        lines = _wrap_text(draw, headline, font, box_w - 80)

    line_height = int(font_size * 1.25)
    text_block_h = line_height * len(lines)
    pad_v = 44
    box_h = text_block_h + pad_v * 2

    box_bottom = ch - int(170 * scale)  # leave clear room below for the logo
    box_top = box_bottom - box_h
    box = (box_margin, box_top, cw - box_margin, box_bottom)

    draw.rounded_rectangle(box, radius=28, fill=palette["bg"])

    y = box_top + pad_v
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (cw - w) / 2
        draw.text((x, y), line, font=font, fill=palette["text"])
        y += line_height


def _paste_logo(canvas, corner="bottom_right"):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    cw, ch = canvas.size
    target_w = int(cw * 0.16)
    ratio = target_w / logo.width
    logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)

    padding = 40
    if corner == "bottom_right":
        pos = (cw - logo.width - padding, ch - logo.height - padding)
    else:
        pos = (padding, ch - logo.height - padding)

    # Soft translucent backing so the logo stays legible over busy photos.
    draw = ImageDraw.Draw(canvas, "RGBA")
    backing_pad = 16
    backing = (
        pos[0] - backing_pad, pos[1] - backing_pad,
        pos[0] + logo.width + backing_pad, pos[1] + logo.height + backing_pad,
    )
    draw.rounded_rectangle(backing, radius=18, fill=(255, 255, 255, 200))
    canvas.alpha_composite(logo, pos)


def fit_on_color(im, palette, size=(CANVAS_W, CANVAS_H)):
    """For photos that already carry their own text: show the whole photo, uncropped,
    on a warm color background, leaving clear space below for the logo."""
    bg = palette["bg"][:3] + (255,)
    cw, ch = size
    canvas = Image.new("RGBA", size, bg)
    max_h = int(ch * 0.853)
    scale = min(cw / im.width, max_h / im.height)
    new_size = (round(im.width * scale), round(im.height * scale))
    im = im.resize(new_size, Image.LANCZOS).convert("RGBA")
    x = (cw - new_size[0]) // 2
    y = (int(ch * 0.92) - new_size[1]) // 2
    canvas.alpha_composite(im, (x, y))
    return canvas


def render_pin(photo_url, headline, palette_key, crop_style, out_path, logo_corner="bottom_right"):
    """Builds one finished pin image and saves it as a JPEG to out_path.

    With headline=None the photo is shown whole on a color background and no headline
    box is added (used for photos that already have text baked in).
    """
    palette = PALETTES[palette_key]
    source = download_image(photo_url)
    if headline is None:
        canvas = fit_on_color(source, palette)
    else:
        canvas = cover_crop(source, CANVAS_W, CANVAS_H, crop_style).convert("RGBA")
        _draw_text_box(canvas, headline, palette)
    _paste_logo(canvas, logo_corner)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path


def make_thumbnail(src_path, dst_path, max_size=(300, 450)):
    """Small JPEG copy of a finished pin, used by the daily summary email."""
    im = Image.open(src_path).convert("RGB")
    im.thumbnail(max_size, Image.LANCZOS)
    dst_path = Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst_path, "JPEG", quality=78)
    return dst_path


# ---- Instagram carousel slides: 4:5 (1080x1350), the tallest shape Instagram's feed shows uncropped
IG_SIZE = (1080, 1350)


def render_slide(photo_url, kind, out_path, palette_key="gold", headline=None):
    """One carousel slide. Clean artwork fills the frame; photos that already carry their own
    text are shown whole on a warm color. Only the first slide gets a headline box."""
    palette = PALETTES[palette_key]
    source = download_image(photo_url)
    if kind == "text_heavy":
        canvas = fit_on_color(source, palette, IG_SIZE)
    else:
        canvas = cover_crop(source, IG_SIZE[0], IG_SIZE[1], "cover_center").convert("RGBA")
        if headline:
            _draw_text_box(canvas, headline, palette)
    _paste_logo(canvas, "bottom_right")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "JPEG", quality=90)  # Instagram only accepts JPEG
    return out_path


def crop_window(width, height, box, target_ratio, margin=0.03):
    """If a window of the target shape can hold the marked content box with a little breathing
    room, return that window (left, top, right, bottom) in pixels, else None."""
    x0, y0, x1, y1 = box
    if width / height > target_ratio:       # too wide: would trim left/right
        win_w, win_h = height * target_ratio, height
        need = (x1 - x0) * width
        if need > win_w * (1 - 2 * margin):
            return None
        center = (x0 + x1) / 2 * width
        left = min(max(center - win_w / 2, 0), width - win_w)
        return (round(left), 0, round(left + win_w), height)
    win_w, win_h = width, width / target_ratio  # too tall: would trim top/bottom
    need = (y1 - y0) * height
    if need > win_h * (1 - 2 * margin):
        return None
    center = (y0 + y1) / 2 * height
    top = min(max(center - win_h / 2, 0), height - win_h)
    return (0, round(top), width, round(top + win_h))


def render_faithful_slide(photo_url, out_path, framing, size=IG_SIZE):
    """The Etsy photo as listed: no text, no logo. `framing` (from carousel.frame_photo) says whether
    it was proven safe to crop to the frame or must be shown whole over a soft blurred copy."""
    cw, ch = size
    im = download_image(photo_url)
    if framing["mode"] == "crop":
        canvas = im.crop(tuple(framing["window"])).resize(size, Image.LANCZOS)
    else:
        canvas = cover_crop(im, cw, ch, "cover_center").filter(ImageFilter.GaussianBlur(36))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.85)
        scale = min(cw / im.width, ch / im.height)
        fitted = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        canvas.paste(fitted, ((cw - fitted.width) // 2, (ch - fitted.height) // 2))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path
