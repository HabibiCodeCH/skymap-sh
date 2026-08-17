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
import re
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


# Characters that need the fallback font. gif._PRIMARY_GAPS covers what the
# CHART draws; a card also marks meteor showers and asterisms, and neither of
# those two glyphs appears on a chart, so neither is in that set. Missing them
# here does not fail loudly -- it draws .notdef, an empty box, which is
# exactly the tofu this file shipped on every galaxy and cluster card.
#
# test_object_routes.py reads the fonts' cmaps and asserts every glyph
# api.object_glyph() can return is covered, so adding a new object type with
# a new mark fails a test rather than quietly rendering a box.
_GAPS = gif._PRIMARY_GAPS | frozenset("✧☄")


def _glyph_font(ch, size):
    """The font that actually has this character, at this size.

    JetBrains Mono is missing most of the deep-sky marks, and a missing glyph
    does not fail loudly -- it draws .notdef, an empty box. The galaxy,
    nebula and cluster cards were all showing tofu where the chart shows a
    symbol.

    gif.py already worked this out for the PNG export, down to reading which
    codepoints each font's cmap actually contains rather than guessing from
    rendered bitmaps. Reusing its tables rather than keeping a second list
    that can disagree with the first.
    """
    if ch and ch in _GAPS:
        try:
            return ImageFont.truetype(gif._FALLBACK_PATH, size)
        except OSError:
            pass
    return _font(size)


def _glyph_char(ch):
    """U+2042 ASTERISM, the cluster mark, is in neither bundled font. gif.py
    substitutes U+2234, which is in both and says the same thing: three
    points close together."""
    return gif.PNG_SUBSTITUTE.get(ch, ch)


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
    """What this object IS, in at most two lines.

    Nothing location-dependent, for the reason render() gives. Nothing
    time-of-night dependent either. What survives is the description a person
    would repeat: what kind of star it is, how big it looks, which way the
    rings are tilted.

    Two lines is a budget set by legibility, not taste -- at the size these
    have to be set to survive a phone unfurl, a third line runs into the
    wordmark.
    """
    out = []
    st, pl = facts.get("star", {}), facts.get("planet", {})

    gx = facts.get("galaxy") or {}
    if gx:
        # Not the Bortle line, however much it is the best fact on the page.
        # Whether the band shows depends on where the reader is standing,
        # and this image is fetched once and shown to everybody.
        # One line, not two. "just", because the number is meaningless
        # without a shrug next to it. The distance to the centre is on the
        # page; a card gets the one fact worth reading at thumbnail size.
        out.append(f"just {gx['diameter_ly']:,} light years across")

    if st.get("description"):
        out.append(st["description"])

    if facts.get("kind") == "planet":
        # Distance, and only distance, on every planet including Saturn. One
        # line, the same line, so the seven cards read as a set rather than
        # as six of a kind plus an exception. Saturn's ring angle is a better
        # fact than its distance and it still leads the planet's page -- but
        # a card is a set, and consistency across it beats the best line on
        # one member of it.
        if pl.get("light_minutes"):
            out.append(f"{pl['light_minutes']:.0f} light-minutes away")

    if facts.get("size_arcmin"):
        maj = facts["size_arcmin"]["maj"]
        moons = maj / 31.0
        out.append(f"{moons:.0f}\u00d7 the width of the full Moon" if moons >= 2
                   else f"{maj:g} arcminutes across")
    # What it takes to see it -- but only when that answer is the same
    # wherever the reader is standing. facts["need"] is not: the page asks
    # the reader's own Bortle, and this image is fetched once by a crawler
    # from its own datacentre and then shown to everybody. "Binoculars from
    # here" on Deneb's card meant here=Virginia, said to someone who could
    # be under a dark sky in Chile, about a star bright enough to see from
    # a lit street. Recomputing under the darkest and the brightest sky and
    # keeping only what does not change is the check rather than a list of
    # allowed phrases -- today that leaves the two telescope lines, and it
    # stays right if the thresholds move.
    # Gated on the page having produced a line at all, because that is where
    # the placeholder magnitudes get filtered out -- half the diffuse nebulae
    # in RNGC carry a made-up 11.0, and reading facts["mag"] on its own would
    # put "a small telescope" on a card for an object nobody ever measured.
    if facts.get("need") and facts.get("mag") is not None:
        import objects
        point = facts.get("kind") in objects.POINT_KINDS
        anywhere = objects.what_you_need(facts["mag"], None, point=point)
        if anywhere == objects.what_you_need(facts["mag"], 9, point=point):
            out.append(anywhere)

    if facts.get("star_count"):
        # Whether the whole shape is traceable, which is decided by its
        # faintest corner rather than by its brightest star.
        faint = facts.get("faintest")
        how = ("all naked-eye" if faint is not None and faint <= 4.0 else
               "faintest needs a dark sky" if faint is not None and faint <= 5.5 else
               "faintest needs binoculars" if faint is not None else None)
        out.append(f"{facts['star_count']} stars, {how}" if how
                   else f"{facts['star_count']} stars")

    if facts.get("kind") == "sun":
        out.append("8 light-minutes away")
    elif facts.get("kind") == "moon":
        out.append("1.3 light-seconds away")

    b = facts.get("best_this_year")
    if b and b.get("is_peak"):
        # A shower peaks on a date in the Earth's orbit -- the same date for
        # everyone on the planet, so this one is not location-dependent.
        out.insert(0, f"peaks {b['date']}")
        if b.get("zhr"):
            out.append(f"up to {b['zhr']} an hour at its best")

    return out[:2]


# Every kind string sky.resolve_target() can return, and what a card calls
# it. Audited against that function rather than written from memory: the map
# used to have "globular cluster" and "open cluster", which it never returns
# -- it returns plain "cluster" via sky.DSO_NAMES -- so every cluster card
# read "OBJECT IN HERCULES". A missing key does not fail, it silently falls
# back to "Object", which is why there is a test.
KIND_WORDS = {
    "planet": "Planet", "star": "Star", "moon": "Moon", "sun": "Sun",
    "asterism": "Asterism", "radiant": "Meteor shower",
    # The one galaxy nobody has ever seen from outside.
    "milkyway": "Our galaxy",
    "galaxy": "Galaxy", "cluster": "Cluster", "nebula": "Nebula",
    "planetary nebula": "Planetary nebula",
}

# Nothing reads this: _subtitle() takes its text from
# api.object_descriptor(), which is the single source the card and the page
# share. Left in place rather than removed, but do not add to it -- an entry
# here has no effect.
_FIXED_SUBTITLE = {"sun": "The star we orbit", "moon": "Earth's only moon"}

# Order from the Sun. Earth is third, which is why Mars is fourth and not
# third -- worth stating, since the gap is the question the line invites.
_PLANET_ORDER = {"Mercury": 1, "Venus": 2, "Mars": 4, "Jupiter": 5,
                 "Saturn": 6, "Uranus": 7, "Neptune": 8}


def _subtitle(facts):
    """The category line above the name.

    api.object_descriptor() is the single source for this and for the page's
    opening sentence, so a card and the page it links to can never describe
    the same object differently. Title-cased here because it sits above the
    name as a label rather than inside a sentence.
    """
    import api
    d = api.object_descriptor(facts)
    for lead in ("the ", "a ", "an "):
        if d.startswith(lead):
            d = d[len(lead):]
            break
    return d[0].upper() + d[1:]


# apple-touch-icon rather than favicon.png: the favicon is a 720x720 render
# of a terminal prompt, and scaled to wordmark height it reads as a grey
# smudge rather than a mark. The touch icon is drawn to survive being small.
_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "apple-touch-icon.png")


def _wrap_fit(d, text, size, max_w, max_h, floor=64, leading=1.06):
    """(font, lines) at the largest size that fits the box, wrapped.

    _fit() only ever shrinks, which is right for a name that is a little too
    wide and wrong for one that is nowhere near fitting: cities.json has
    "Dolores Hidalgo Cuna de la Independencia Nacional" in it, and shrinking
    that to one line leaves a headline smaller than the caption under it.
    Wrapping keeps the type big enough to read at timeline size.

    Breaks after hyphens as well as at spaces, because the long names in the
    data are as often "Sainte-Catherine-de-la-Jacques-Cartier" as they are
    several words, and a hyphenated one is a single token to str.split().
    """
    parts = []
    for word in text.split():
        parts += [p for p in re.split(r"(?<=-)", word) if p]
    while size >= floor:
        f = _font(size)
        lines, cur = [], ""
        for part in parts:
            # No space after a hyphen: the break is already there.
            joiner = "" if cur.endswith("-") else " "
            trial = f"{cur}{joiner}{part}" if cur else part
            if cur and d.textlength(trial, font=f) > max_w:
                lines.append(cur)
                cur = part
            else:
                cur = trial
        if cur:
            lines.append(cur)
        widest = max((d.textlength(l, font=f) for l in lines), default=0)
        if widest <= max_w and len(lines) * size * leading <= max_h:
            return f, lines
        size -= 4
    return _font(floor), lines


def _hex_rgb(h):
    h = (h or "#ffffff").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _wordmark(img, d, size=56):
    """The icon and the name, bottom left. Sized to be read in a phone
    unfurl, where the whole card is about 350px wide -- a 3.4x reduction, so
    anything under about 48px here lands below 14px there and is decoration
    rather than a word."""
    f = _font(size)
    y = H - MARGIN - size
    icon_px = int(size * 1.15)
    x = MARGIN
    try:
        icon = Image.open(_ICON).convert("RGBA").resize(
            (icon_px, icon_px), Image.LANCZOS)
        img.paste(icon, (x, y - int(size * 0.12)), icon)
        x += icon_px + int(size * 0.35)
    except OSError:
        pass
    d.text((x, y), "skymap.sh", font=f, fill=ACCENT)


def render(facts, chart_text=None):
    """The card as PNG bytes.

    Deliberately carries nothing that depends on where the reader is. The
    image is fetched once by the unfurling platform's crawler, from its own
    datacentre, then cached and shown to everyone -- so an altitude or a
    compass bearing on here is computed for a machine in Virginia and served
    to someone in Tokyo, contradicting the page it links to. The page does
    the local half properly, per visitor. This does the half that is true
    for everybody.
    """
    img = _scrim(_background(chart_text))
    d = ImageDraw.Draw(img)
    name = facts.get("object", "skymap.sh")

    sub = _subtitle(facts).upper()
    f_sub = _fit(d, " ".join(sub), 44, W - MARGIN * 2, floor=30)
    d.text((MARGIN, MARGIN), " ".join(sub), font=f_sub, fill=ACCENT)

    # The glyph the chart draws this object with, in the colour the chart
    # draws it -- so the card and the map agree at a glance.
    glyph = _glyph_char(facts.get("glyph") or "")
    y = MARGIN + f_sub.size + 30
    f_name = _fit(d, f"{glyph} {name}" if glyph else name, 150,
                  W - MARGIN * 2, floor=56)
    x = MARGIN
    if glyph:
        # Drawn with whichever font actually has this character, and measured
        # with that same font -- measuring a fallback glyph against the
        # primary font puts the name in the wrong place.
        f_glyph = _glyph_font(glyph, f_name.size)
        d.text((x, y), glyph, font=f_glyph, fill=_hex_rgb(facts.get("glyph_color")))
        x += d.textlength(glyph, font=f_glyph) + d.textlength(" ", font=f_name)
    d.text((x, y), name, font=f_name, fill=INK)

    y += f_name.size + 34
    for line in _headline_facts(facts):
        f_fact = _fit(d, line, 58, W - MARGIN * 2, floor=40)
        d.text((MARGIN, y), line, font=f_fact, fill=INK)
        y += f_fact.size + 18

    _wordmark(img, d)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# -------------------------------------------------------- the place card
# The hour a place's card is drawn for. Not "now": this image is fetched once
# by a crawler from its own datacentre and then shown to everybody, so "now"
# means whatever the sky looked like when a bot happened to ask -- daylight
# about half the time, and a daylight chart is nearly empty. Ten at night,
# local to the place itself, is a sky worth looking at wherever it is.
PLACE_HOUR = 22


def place_chart(place):
    """Tonight's sky over one place, at PLACE_HOUR local. Imported lazily
    for the same reason generic_chart() is: api imports card's caller."""
    import api
    import datetime as dt
    p = api.lookup_place(place)
    if p is None:
        return None
    # Local 22:00 turned into UTC by the place's own offset, so a card for
    # Tokyo and one for Lima are both drawn at their own late evening rather
    # than at one shared instant that is night in only one of them.
    today = dt.datetime.utcnow()
    local = dt.datetime(today.year, today.month, today.day, PLACE_HOUR, 0)
    when = local - dt.timedelta(hours=p.offset(local))
    r = api.Request(place=place, when=when, width=140)
    return api.compose_chart_only(r)


def render_place(place, chart_text=None, sub=None):
    """The card for a place page.

    Same furniture as the object card -- scrimmed chart, headline, wordmark
    -- because they unfurl side by side in a timeline and two different
    layouts would read as two different sites. What it does not carry is any
    number that depends on when you look: an altitude or a rise time here
    would be computed for a crawler in Virginia and then shown to everyone
    for a day. The name and the fact that this is that place's sky are true
    whenever the card is seen.
    """
    if chart_text is None:
        chart_text = place_chart(place)
    img = _scrim(_background(chart_text))
    d = ImageDraw.Draw(img)

    label = (sub or "the night sky above").upper()
    f_sub = _fit(d, " ".join(label), 44, W - MARGIN * 2, floor=30)
    d.text((MARGIN, MARGIN), " ".join(label), font=f_sub, fill=ACCENT)

    y = MARGIN + f_sub.size + 30
    # The height left once the command line and the wordmark have their
    # room: the headline may take as many lines as fit in it, and no more.
    head_room = H - y - 150
    f_name, name_lines = _wrap_fit(d, place, 150, W - MARGIN * 2, head_room)
    for line in name_lines:
        d.text((MARGIN, y), line, font=f_name, fill=INK)
        y += int(f_name.size * 1.06)

    # The command, because that is the thing this site is: a place page is
    # one curl away and the card should say which one.
    y += 24
    cmd = f"curl skymap.sh/{place.lower()}" if " " not in place else \
          f"curl 'skymap.sh/{place}'"
    f_cmd = _fit(d, cmd, 58, W - MARGIN * 2, floor=34)
    d.text((MARGIN, y), cmd, font=f_cmd, fill=MUTED)

    _wordmark(img, d)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------- the generic card
# For the home page and the place pages -- everything that is not about one
# object. An object card leads with the object; this has none, so it leads
# with the wordmark itself, with the icon beside it rather than repeated in
# a footer underneath.
#
# The sky behind it is fixed rather than live. Everywhere else on this site
# the picture is of the sky where you are, right now, and that is the whole
# point -- but this one image is fetched once by an unfurling crawler and
# then shown to everybody, so "live" means whatever Zurich happened to look
# like at the moment a bot asked. That is a daylight chart about half the
# time, and a daylight chart is nearly empty. This is the first thing anyone
# sees of the site, so it gets a night that is always worth looking at: the
# Atacama in July, Bortle 1, with the galactic core overhead.
GENERIC_PLACE = (-24.63, -70.40)
GENERIC_WHEN = (2026, 7, 15, 4, 0)      # UTC; local midnight in Chile

GENERIC_HEAD = "skymap.sh"
GENERIC_SUB = "the sky above you, as plain text"
GENERIC_TAIL = "curl skymap.sh"


def generic_chart():
    """The fixed night sky this card sits on. Imported lazily: api imports
    card's caller, not card, and reaching for it at module scope would make
    that a cycle."""
    import api
    import datetime as dt
    r = api.Request(place=f"{GENERIC_PLACE[0]},{GENERIC_PLACE[1]}",
                    when=dt.datetime(*GENERIC_WHEN), width=140)
    return api.compose_chart_only(r)


def render_generic(chart_text=None):
    """The card for pages that are not about one object."""
    img = _scrim(_background(chart_text if chart_text is not None else generic_chart()))
    d = ImageDraw.Draw(img)

    # A shell prompt and the wordmark as the headline. No footer: the
    # headline is the wordmark, and printing it twice on one card reads as a
    # mistake.
    #
    # The prompt is drawn as type rather than pasted as the app icon. The
    # icon is itself a screenshot of a terminal with a chart in it, so
    # enlarged to headline height you can see the little chart inside it and
    # it reads as a thumbnail rather than a mark. Two characters in the same
    # font as everything else scale cleanly and say the same thing: this is
    # something you type.
    f_head = _fit(d, f">_ {GENERIC_HEAD}", 132, W - MARGIN * 2, floor=72)
    y = MARGIN + 46
    x = MARGIN
    d.text((x, y), ">_", font=f_head, fill=ACCENT)
    x += d.textlength(">_ ", font=f_head)
    d.text((x, y), GENERIC_HEAD, font=f_head, fill=INK)

    y += f_head.size + 52
    f_sub = _fit(d, GENERIC_SUB, 54, W - MARGIN * 2, floor=36)
    d.text((MARGIN, y), GENERIC_SUB, font=f_sub, fill=ACCENT)

    y += f_sub.size + 26
    f_tail = _fit(d, GENERIC_TAIL, 44, W - MARGIN * 2, floor=30)
    d.text((MARGIN, y), GENERIC_TAIL, font=f_tail, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------- the eclipse card
# The one card where the drawing IS the message. Everywhere else the chart
# is texture behind the type, because a star field at thumbnail size is grey
# noise -- but a Sun with a corona around it, or a Moon half in shadow, is a
# shape somebody recognises at 350px across. So it gets the left half of the
# card at full brightness, and the type takes the right.
ART_BOX = (520, 430)        # what the drawing is scaled to fit
ART_LEFT = 56


def _art_image(rows):
    """ANSI art to an RGB image, no watermark strip.

    Drawn on the grid the art was built for (art.CELL) rather than the
    chart's, for the same reason the eclipse GIF is: these discs are circles
    and the chart's cell would stretch them.
    """
    import art
    if not rows:
        return None
    img = gif.frame_to_image("\n".join(rows), gif.cell_h_for(art.CELL))
    if img.height > gif._WM_STRIP_H:
        img = img.crop((0, 0, img.width, img.height - gif._WM_STRIP_H))
    return img


def _fit_into(img, box):
    """Scale to fit inside the box, keeping the shape, never enlarging past
    what the source can carry: nearest-neighbour above 2x, because these are
    glyphs on a grid and LANCZOS turns them to mush."""
    if img is None:
        return None
    scale = min(box[0] / img.width, box[1] / img.height)
    method = Image.NEAREST if scale > 2.0 else Image.LANCZOS
    return img.resize((max(1, int(img.width * scale)),
                       max(1, int(img.height * scale))), method)


def render_eclipse(kicker, headline, detail, rows):
    """The card as PNG bytes: the drawing on the left, the answer on the
    right.

    Whether the drawing is a disc or a map is the caller's call (see
    eclipse_page.card_art), and it changes the shape of the picture but not
    of this layout: both are ANSI art on a grid, and both are scaled to fit
    the same box.
    """
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    picture = _fit_into(_art_image(rows), ART_BOX)
    text_left = MARGIN
    if picture is not None:
        img.paste(picture, (ART_LEFT + (ART_BOX[0] - picture.width) // 2,
                            (H - picture.height) // 2 - 24))
        text_left = ART_LEFT + ART_BOX[0] + 56

    max_w = W - text_left - MARGIN
    y = MARGIN + 40
    f_kick = _fit(d, kicker, 30, max_w, floor=20)
    d.text((text_left, y), kicker, font=f_kick, fill=ACCENT)
    y += f_kick.size + 26

    f_head, lines = _wrap_fit(d, headline, 62, max_w, 300, floor=32)
    for line in lines:
        d.text((text_left, y), line, font=f_head, fill=INK)
        y += int(f_head.size * 1.18)

    if detail:
        y += 18
        f_det, det_lines = _wrap_fit(d, detail, 30, max_w, 140, floor=20)
        for line in det_lines:
            d.text((text_left, y), line, font=f_det, fill=MUTED)
            y += int(f_det.size * 1.3)

    _wordmark(img, d)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
