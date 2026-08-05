#!/usr/bin/env python3
"""
The social card for an object page: 1200x630, type first.

Most people meet this at thumbnail size, in a Slack unfurl or a timeline,
where a chart rendered as monospace text is illegible -- the glyphs are two
pixels tall and the whole thing reads as grey noise. So the chart becomes the
background texture and the type carries the message: what it is, where it is,
and the one number worth knowing.

The chart is still there, and still real. It is this object's actual sky from
this actual place, dimmed rather than decorated, so the card is a picture of
the page rather than an illustration of one.
"""
import io
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

import gif

W, H = 1200, 630
BG = (0, 0, 0)

# The chart underneath, pulled down until it reads as texture. Any brighter
# and the star field competes with the headline; any darker and the card
# looks like a mistake.
CHART_DIM = 0.42

MARGIN = 64
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_MONO = os.path.join(FONT_DIR, "JetBrainsMono-Regular.ttf")

INK = (255, 255, 255)
MUTED = (150, 156, 170)
ACCENT = (128, 190, 255)


def _font(size):
    try:
        return ImageFont.truetype(_MONO, size)
    except OSError:
        return ImageFont.load_default()


def _fit(draw, text, size, max_w, floor=34):
    """Shrink until it fits. Object names run from "M13" to "Christmas Tree
    Cluster", so a single fixed size is either tiny for the short ones or
    overflowing for the long ones."""
    while size > floor:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(floor)


def _background(chart_text):
    """The object's own chart, dimmed, cropped to fill and never stretched."""
    if not chart_text:
        return Image.new("RGB", (W, H), BG)
    img = gif.frame_to_image(chart_text).convert("RGB")
    # Trim the chart's own furniture off both ends: the header line at the
    # top ("Zurich 05 Aug 2026, finding Perseids radiant") and the compass
    # row plus watermark strip at the bottom. Scaled into a 1200x630 crop
    # they land as bands of half-height clipped text along the edges, which
    # reads as a rendering fault rather than as part of the picture. Only
    # the sky itself belongs back here.
    top_trim = gif._CELL_H * 2
    bottom_trim = gif._WM_STRIP_H + gif._CELL_H
    if img.height > top_trim + bottom_trim + 40:
        img = img.crop((0, top_trim, img.width, img.height - bottom_trim))
    # Cover, not fit: scale so the shorter side fills, then crop, so the
    # aspect ratio is never distorted.
    scale = max(W / img.width, H / img.height)
    img = img.resize((max(W, int(img.width * scale)),
                      max(H, int(img.height * scale))), Image.LANCZOS)
    left = (img.width - W) // 2
    # Biased above centre: the horizon and its labels sit low in the frame,
    # and the sky above it is the part that looks like anything at this size.
    top = int((img.height - H) * 0.35)
    img = img.crop((left, top, left + W, top + H))
    return ImageEnhance.Brightness(img).enhance(CHART_DIM)


def _scrim(img):
    """A gradient down the left, so the type sits on something dark whatever
    the chart happens to be doing behind it. Without it a headline lands on a
    bright star field about one time in five and becomes unreadable."""
    scrim = Image.new("L", (W, 1))
    for x in range(W):
        # Opaque at the left edge, gone by two-thirds across.
        t = min(1.0, x / (W * 0.66))
        scrim.putpixel((x, 0), int(232 * (1 - t) ** 1.6))
    mask = scrim.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), BG), img, mask)


def _headline_facts(facts):
    """Two or three short facts. Chosen for what stays true longest and what
    a person would actually repeat -- the ring angle, the distance, the size
    -- rather than whatever is numerically largest."""
    out = []
    st, pl = facts.get("star", {}), facts.get("planet", {})
    if facts.get("kind") == "planet":
        if pl.get("ring_angle") is not None:
            out.append(f"rings {pl['ring_angle']:.0f}° open")
        if pl.get("light_minutes"):
            out.append(f"{pl['light_minutes']:.0f} light-minutes away")
        if pl.get("apparent_arcsec"):
            out.append(f"{pl['apparent_arcsec']:.0f}″ across")
    if st.get("description"):
        out.append(st["description"])
    if st.get("light_years") and st.get("distance_confidence") == "good":
        out.append(f"{st['light_years']:.0f} light years away")
    if st.get("next_minimum"):
        out.append(f"next minimum {st['next_minimum'][11:16]}")
    if facts.get("size_arcmin"):
        out.append(f"{facts['size_arcmin']['maj']:g}′ across")
    b = facts.get("best_this_year")
    if b and b.get("is_peak"):
        out.append(f"peaks {b['date']}")
        if b.get("zhr"):
            out.append(f"up to {b['zhr']}/hour at best")
        if b.get("moon_illum", 0) > 0.5:
            out.append(f"moon {b['moon_illum']:.0%} that night")
    elif b and len(out) < 3:
        out.append(f"best on {b['date']}")
    return out[:3]


def _subtitle(facts):
    kind = {"planet": "Planet", "star": "Star", "moon": "Moon", "sun": "Sun",
            "asterism": "Asterism", "radiant": "Meteor shower",
            "galaxy": "Galaxy", "globular cluster": "Globular cluster",
            "open cluster": "Open cluster",
            "planetary nebula": "Planetary nebula",
            "nebula": "Nebula"}.get(facts.get("kind"), "Object")
    con = facts.get("constellation")
    return f"{kind} in {con}" if con else kind


def render(facts, chart_text=None):
    """The card as PNG bytes."""
    img = _scrim(_background(chart_text))
    d = ImageDraw.Draw(img)
    name = facts.get("object", "skymap.sh")

    # Subtitle above the name, spaced out and quiet -- it is the category,
    # not the headline.
    sub = _subtitle(facts).upper()
    f_sub = _font(26)
    d.text((MARGIN, MARGIN + 6), " ".join(sub), font=f_sub, fill=ACCENT)

    f_name = _fit(d, name, 132, W - MARGIN * 2 - 40)
    name_y = MARGIN + 62
    d.text((MARGIN, name_y), name, font=f_name, fill=INK)

    # Where it is, in the same words the page uses.
    y = name_y + f_name.size + 34
    where = facts.get("where_line")
    if where:
        f_where = _fit(d, where, 38, W - MARGIN * 2, floor=26)
        d.text((MARGIN, y), where, font=f_where, fill=INK)
        y += f_where.size + 26

    f_fact = _font(29)
    for line in _headline_facts(facts):
        d.text((MARGIN, y), line, font=f_fact, fill=MUTED)
        y += 42

    # Wordmark, bottom left, where the eye lands last.
    f_mark = _font(28)
    d.text((MARGIN, H - MARGIN - 12), "skymap.sh", font=f_mark, fill=ACCENT)
    place = facts.get("place")
    if place:
        f_place = _font(24)
        t = f"from {place}"
        d.text((W - MARGIN - d.textlength(t, font=f_place), H - MARGIN - 10),
               t, font=f_place, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
