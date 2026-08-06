"""Constellations are temporary. This works out by how much.

    motion.panels("Big Dipper")      then, now and later, side by side
    motion.frames("Big Dipper")      the same thing as an animation
    motion.summary("Big Dipper")     the numbers under it

Proper motion only. Precession is a different effect entirely -- it changes
where a constellation appears and which star is the pole star, not what shape
it is -- and mixing the two is the standard error in popular writing about
this. Nothing here moves anything because the Earth wobbles.

The positions are propagated in three dimensions: Cartesian position plus
space velocity, straight line through space, converted back to a right
ascension and declination at the far end. The obvious alternative, adding
proper motion to RA and Dec for fifty thousand years, is a tangent-plane
approximation that breaks down over large angles, and it also ignores the
fact that a star's distance changes over that time, which changes how fast
it appears to move. A star coming toward us appears to speed up. That
perspective term is a large part of why the Big Dipper comes apart the way
it does, and dropping it would still have produced a plausible-looking
picture -- the worst kind of wrong.

Checked against two published close approaches rather than against itself
(test_motion.py): Alpha Centauri comes closest in about 27,800 years at
0.99 parsecs, against a published ~28,000 and ~0.95, and Sirius in about
61,000 years at 2.38, against ~60,000 and ~2.41. Both fall out of the same
propagation the panels use.

SPAN is 50,000 years each way and that is a deliberate ceiling. Past about
100,000 the straight line through space stops being true -- stars follow
curved orbits around the Galaxy and differential rotation shears the field
-- and it stops being a prediction. Over that long the stars themselves
change as well: several of these will have left the main sequence, and
Betelgeuse will very likely have gone supernova. This is geometry, not
stellar evolution.
"""
import math
import re

import sky

# km/s per (arcsec/yr x parsec), and parsecs per (km/s x year).
KAPPA = 4.74047
PC_PER_KMS_YR = 1.0 / 977792.0

SPAN = 50000
EPOCHS = (-SPAN, 0, SPAN)

# A character cell is twice as tall as it is wide (art.CELL), so a square
# patch of sky needs twice as many columns as rows.
COLS = 96
CELL = 2.0

# Stars keep the chart's own glyphs and its colour-by-temperature, so a panel
# reads as the same sky rather than as a diagram of it. See api.legend_text.
GLYPHS = ((0.8, "●"), (3.0, "•"), (99.0, "·"))

# The lines are drawn in braille rather than in the chart's ─ ╱ │ ╲. One
# braille character is 2 dots across and 4 down, and with a cell twice as
# tall as it is wide that makes every dot exactly square -- a 96x24 panel is
# really a 192x96 bitmap. Box glyphs at this size staircase badly, and these
# shapes are mostly diagonals. Still text, still pastes into a terminal.
BRAILLE = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
           (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}
BRAILLE_BASE = 0x2800

# Star names beside the stars. Dimmer than the stars themselves and warmer
# than the lines, so the panel reads as a drawing with labels on it rather
# than as three kinds of thing competing.
LABEL_COLOUR = "\033[38;5;246m"


def _motions():
    return sky._load("stars_motion.json")


def _stars():
    return {s["hr"]: s for s in sky._load("stars.json")}


def asterism(name):
    """The asterism by name, or None."""
    for a in sky._load("asterisms.json"):
        if a["name"] == name:
            return a
    return None


def members(a):
    """Every star the shape is drawn with, once each."""
    return sorted({hr for poly in a["lines"] for hr in poly})


def segments(a):
    """The pairs of stars a line is drawn between."""
    out = []
    for poly in a["lines"]:
        out += list(zip(poly, poly[1:]))
    return out


def at(hr, years, stars=None, mots=None):
    """Where star `hr` is `years` from now, as (ra_deg, dec_deg, note).

    The note is None when the full three-dimensional propagation ran, and a
    reason when it could not.
    """
    stars = stars if stars is not None else _stars()
    mots = mots if mots is not None else _motions()
    s = stars.get(hr)
    if not s:
        return None
    ra = math.radians(s["ra"] * 15.0)
    de = math.radians(s["de"])
    m = mots.get(str(hr))
    if not m:
        return math.degrees(ra), math.degrees(de), "no proper motion"

    d = m.get("d")
    if not d:
        # No distance, so no space velocity and no perspective term. Fall
        # back to extrapolating the angle itself, which needs no distance.
        # Only ever reached for a star too far away to have had its parallax
        # measured, which is another way of saying its motion is small.
        ra2 = ra + math.radians(m["pmra"] * years / 3600.0) / math.cos(de)
        de2 = de + math.radians(m["pmde"] * years / 3600.0)
        return math.degrees(ra2) % 360.0, math.degrees(de2), "no distance"

    ca, sa, cd, sd = math.cos(ra), math.sin(ra), math.cos(de), math.sin(de)
    r = (d * cd * ca, d * cd * sa, d * sd)
    e_ra = (-sa, ca, 0.0)
    e_de = (-sd * ca, -sd * sa, cd)
    r_hat = (cd * ca, cd * sa, sd)

    v_ra = KAPPA * m["pmra"] * d
    v_de = KAPPA * m["pmde"] * d
    v_r = m.get("rv") or 0.0
    v = tuple(v_r * r_hat[i] + v_ra * e_ra[i] + v_de * e_de[i] for i in range(3))
    p = tuple(r[i] + v[i] * years * PC_PER_KMS_YR for i in range(3))

    ra2 = math.degrees(math.atan2(p[1], p[0])) % 360.0
    de2 = math.degrees(math.atan2(p[2], math.hypot(p[0], p[1])))
    return ra2, de2, None


def distance(hr, years, mots=None):
    """How far away that star is at that epoch, in parsecs. None when we
    never knew to begin with."""
    mots = mots if mots is not None else _motions()
    m = mots.get(str(hr))
    if not m or not m.get("d"):
        return None
    stars = _stars()
    ra0, de0, _ = at(hr, 0, stars, mots)
    ra, de, _ = at(hr, years, stars, mots)
    # Radial velocity is the whole of the distance change; the tangential
    # part only turns the direction.
    return m["d"] + (m.get("rv") or 0.0) * years * PC_PER_KMS_YR


def shape(a, years, stars=None, mots=None):
    """Every member of the asterism at one epoch: hr -> (ra, dec)."""
    stars = stars if stars is not None else _stars()
    mots = mots if mots is not None else _motions()
    out, notes = {}, {}
    for hr in members(a):
        p = at(hr, years, stars, mots)
        if not p:
            continue
        out[hr] = (p[0], p[1])
        if p[2]:
            notes[hr] = p[2]
    return out, notes


# ------------------------------------------------------------ geometry
def unit(ra_deg, de_deg):
    ra, de = math.radians(ra_deg), math.radians(de_deg)
    return (math.cos(de) * math.cos(ra), math.cos(de) * math.sin(ra), math.sin(de))


def separation(p, q):
    """Angle between two (ra, dec), in degrees."""
    a, b = unit(*p), unit(*q)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(a[i] * b[i] for i in range(3))))))


def centroid(points):
    """Mean direction of a set of (ra, dec)."""
    v = [0.0, 0.0, 0.0]
    for p in points:
        u = unit(*p)
        for i in range(3):
            v[i] += u[i]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    v = [x / n for x in v]
    return (math.degrees(math.atan2(v[1], v[0])) % 360.0,
            math.degrees(math.asin(max(-1.0, min(1.0, v[2])))))


def project(ra_deg, de_deg, ra0, de0):
    """Stereographic projection about (ra0, de0). North up, east left.

    Stereographic and not gnomonic, because these shapes are not small: the
    Great Diamond spans more than 50 degrees and the Winter Hexagon more
    than 90. A tangent plane stretches badly past about 40 degrees from its
    centre and fails outright at 90, which drew two thirds of the Spring
    Triangle outside its own panel. Stereographic is conformal -- a shape
    still looks like itself -- and stays usable to nearly the whole sky.

    Returned in plane units, where a star an angle t from the centre lands
    at radius 2*tan(t/2). plane_to_deg turns that back into an angle.
    """
    ra, de = math.radians(ra_deg), math.radians(de_deg)
    r0, d0 = math.radians(ra0), math.radians(de0)
    denom = (1.0 + math.sin(d0) * math.sin(de)
             + math.cos(d0) * math.cos(de) * math.cos(ra - r0))
    if denom <= 1e-6:
        return None
    k = 2.0 / denom
    x = k * math.cos(de) * math.sin(ra - r0)
    y = k * (math.cos(d0) * math.sin(de)
             - math.sin(d0) * math.cos(de) * math.cos(ra - r0))
    return -x, y


def plane_to_deg(r):
    """A radius in the projection plane, back to an angle on the sky."""
    return 2.0 * math.degrees(math.atan(r / 2.0))


def field(a, epochs=EPOCHS, stars=None, mots=None, cols=COLS):
    """(half-width, half-height, rows) for this asterism's panels.

    One size for every epoch, because a shape that spreads out while its
    frame quietly zooms out looks like a shape that never moved.

    Width and height are measured separately and the row count follows from
    their ratio, rather than both being forced to the larger. The Big Dipper
    is twice as wide as it is tall, and a square field gave it six blank
    rows of sky above and below. The aspect stays honest: dividing by CELL
    is what keeps one degree across equal to one degree up when a character
    cell is twice as tall as it is wide.
    """
    stars = stars if stars is not None else _stars()
    mots = mots if mots is not None else _motions()
    wx = wy = 0.0
    for years in epochs:
        pos, _ = shape(a, years, stars, mots)
        for p in plane(pos).values():
            wx, wy = max(wx, abs(p[0])), max(wy, abs(p[1]))
    half_x = max(0.035, wx * 1.06)
    half_y = max(0.02, wy * 1.08)
    wanted = cols * (half_y / half_x) / CELL
    rows = max(5, min(21, int(round(wanted))))
    # Whichever side is binding keeps its size and the other one grows to
    # match. Doing this the other way round -- forcing the field to fit the
    # clamped row count -- shrinks the sky the panel covers, and Orion and
    # the Southern Cross are both taller than 21 rows would allow, so both
    # lost stars off the top edge.
    if rows < wanted:
        half_x = half_y * cols / (rows * CELL)
    else:
        half_y = half_x * rows * CELL / cols
    return half_x, half_y, rows


# ------------------------------------------------------------ drawing
def _glyph(mag):
    for limit, g in GLYPHS:
        if mag < limit:
            return g
    return GLYPHS[-1][1]


def plane(pos):
    """Every star projected about the shape's own centre, and re-centred on
    the middle of what that produced.

    Two different centres on purpose. The projection is about the centroid,
    which is a direction on the sky and keeps the picture's orientation
    steady from epoch to epoch. The framing is about the middle of the
    bounding box, because a lopsided shape sits to one side of its centroid
    -- the Big Dipper did, and reserved four blank rows under itself for sky
    that has nothing in it.
    """
    c = centroid(list(pos.values()))
    xy = {}
    for hr, p in pos.items():
        q = project(p[0], p[1], *c)
        if q is not None:
            xy[hr] = q
    if not xy:
        return {}
    xs = [p[0] for p in xy.values()]
    ys = [p[1] for p in xy.values()]
    mx, my = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    return {hr: (p[0] - mx, p[1] - my) for hr, p in xy.items()}


def cells(pos, box, cols=COLS):
    """Where each star lands in the character grid: hr -> (col, row), as
    floats. Its own function so a test can ask whether every star of every
    asterism is actually inside its panel at every epoch, which is not a
    question you can answer by counting glyphs -- a faint star and a line
    are both drawn with a dot."""
    half_x, half_y, rows = box
    return {hr: (cols / 2.0 + p[0] / half_x * (cols / 2.0 - 1),
                 rows / 2.0 - p[1] / half_y * (rows / 2.0 - 0.5))
            for hr, p in plane(pos).items()}


def _room_for(grid, name, cx, cy, cols, rows):
    """Where a star's name can go without covering anything, as (col, row).

    Same search the star chart itself uses for its labels: the star's own row
    first, then one and two rows out, right side before left. Trying only the
    one row is what left six of the Big Dipper's seven stars unlabelled --
    braille lines run right up to a star, so the row it sits on is usually
    the one row with no space on it.

    None when there is genuinely nowhere. A name written over a line reads as
    damage, and a crowded figure is allowed to go unlabelled.
    """
    def clear(r, a, b):
        return all(grid[r][i] == " " for i in range(max(0, a), min(cols, b)))

    # Twice: once wanting a blank cell either side of the name so it does not
    # touch the drawing, and if nowhere will give that, again without. A name
    # jammed against a line is worth having; no name is not.
    for margin in (1, 0):
        for dr in (0, -1, 1, -2, 2):
            r = cy + dr
            if not 0 <= r < rows:
                continue
            for start in (cx + 2, cx - 1 - len(name)):
                if start < 0 or start + len(name) > cols:
                    continue
                if clear(r, start - margin, start + len(name) + margin):
                    return start, r
    return None


def panel(a, years, box, cols=COLS, colour=True, stars=None, mots=None,
          trim=True, labels=True):
    """One epoch of one asterism, as ASCII. `box` comes from field().

    trim=False keeps every line padded to the full width, which animation
    frames need: frames of different widths get re-centred by whatever
    displays them and the whole drawing shuffles sideways between frames.
    """
    half_x, half_y, rows = box
    stars = stars if stars is not None else _stars()
    mots = mots if mots is not None else _motions()
    pos, notes = shape(a, years, stars, mots)
    px = cells(pos, box, cols)
    grid = [[" "] * cols for _ in range(rows)]
    paint = [[None] * cols for _ in range(rows)]

    # The lines go into a subpixel bitmap first, 2 dots across and 4 down per
    # character, and only become characters at the end. Drawing straight into
    # cells is what makes ASCII diagonals staircase.
    dots = [[0] * (cols * 2) for _ in range(rows * 4)]
    for x, y in segments(a):
        if x not in px or y not in px:
            continue
        p = (px[x][0] * 2, px[x][1] * 4)
        q = (px[y][0] * 2, px[y][1] * 4)
        n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) * 1.5) + 1
        for k in range(n + 1):
            t = k / n
            sx = int(round(p[0] + (q[0] - p[0]) * t))
            sy = int(round(p[1] + (q[1] - p[1]) * t))
            if 0 <= sx < cols * 2 and 0 <= sy < rows * 4:
                dots[sy][sx] = 1

    for r in range(rows):
        for c_ in range(cols):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    if dots[r * 4 + dy][c_ * 2 + dx]:
                        bits |= BRAILLE[(dx, dy)]
            if bits:
                grid[r][c_] = chr(BRAILLE_BASE + bits)
                paint[r][c_] = sky.C.DIM

    placed = {}
    for hr, p in px.items():
        cx, cy = int(round(p[0])), int(round(p[1]))
        if not (0 <= cx < cols and 0 <= cy < rows):
            continue
        s = stars[hr]
        grid[cy][cx] = _glyph(s.get("m", 4.0))
        paint[cy][cx] = (sky.C.MUTE if hr in notes
                         else sky.star_colour(s.get("ci")))
        placed[hr] = (cx, cy)

    if labels:
        # After the stars, so a name can never be written over one, and in a
        # fixed order so the same panel comes out the same way twice.
        for hr, (cx, cy) in sorted(placed.items(),
                                   key=lambda kv: stars[kv[0]].get("m", 9)):
            name = (stars.get(hr) or {}).get("n")
            if not name:
                continue
            spot = _room_for(grid, name, cx, cy, cols, rows)
            if spot is None:
                continue
            at_col, at_row = spot
            for i, ch in enumerate(name):
                grid[at_row][at_col + i] = ch
                paint[at_row][at_col + i] = LABEL_COLOUR

    # One escape sequence per run of a colour, not per character. Painting
    # each cell separately made a 96-column line about a kilobyte of escapes,
    # and it also broke the browser's star links: a name came out as five
    # separately-coloured letters, so "Dubhe" never existed as a string for
    # anything downstream to find.
    out = []
    for r in range(rows):
        line, run, run_colour = "", "", None
        for c_ in range(cols):
            if paint[r][c_] != run_colour:
                if run:
                    line += sky.paint(run, run_colour, colour) if run_colour else run
                run, run_colour = "", paint[r][c_]
            run += grid[r][c_]
        if run:
            line += sky.paint(run, run_colour, colour) if run_colour else run
        out.append(line.rstrip() if trim else line)
    return out


def panels(name, colour=True, epochs=EPOCHS, cols=COLS):
    """The three epochs, stacked, as lines ready to print.

    Stacked rather than side by side. Three panels in a row have to be a
    third of the width each, and at 34 columns a degree of sky is one
    character -- the Big Dipper's whole 50,000-year change was two cells and
    the lines staircased. Full width and one under the other costs vertical
    space, which a page has, and buys three times the resolution, which it
    does not otherwise have.
    """
    a = asterism(name)
    if not a:
        return []
    stars, mots = _stars(), _motions()
    box = field(a, epochs, stars, mots, cols=cols)
    out = []
    for i, y in enumerate(epochs):
        if i:
            out.append("")
        out.append(sky.paint(_epoch_label(y), sky.C.MUTE, colour))
        out += panel(a, y, box, cols=cols, colour=colour, stars=stars, mots=mots)
    return out


_ANSI = re.compile(r"\033\[[0-9;]*m")


def _pad(line, width):
    """Pad a possibly-coloured line to `width` printed characters. Counting
    the escape sequences would put every panel after the first one further
    and further right."""
    return line + " " * max(0, width - len(_ANSI.sub("", line)))


def _epoch_label(years):
    if years == 0:
        return "now"
    return f"{years:+,} years".replace(",", ",")


# ------------------------------------------------------------ the numbers
def summary(name):
    """What changed, as facts rather than a picture.

    `deform` is the longest side of the shape then against now, as a
    percentage. `moved` is how far the furthest star travels. `together` is
    the moving-group finding: stars whose direction of travel agrees with
    the majority, against the ones that go their own way.
    """
    a = asterism(name)
    if not a:
        return None
    stars, mots = _stars(), _motions()
    now, notes = shape(a, 0, stars, mots)
    ends = [shape(a, y, stars, mots)[0] for y in (-SPAN, SPAN)]

    longest, pair = 0.0, None
    for x, y in segments(a):
        if x in now and y in now:
            d = separation(now[x], now[y])
            if d > longest:
                longest, pair = d, (x, y)

    deform = 0.0
    if pair and longest:
        for end in ends:
            if pair[0] in end and pair[1] in end:
                deform = max(deform, abs(separation(end[pair[0]], end[pair[1]])
                                         - longest) / longest * 100.0)

    moved, furthest = 0.0, None
    for hr in now:
        for end in ends:
            if hr in end:
                d = separation(now[hr], end[hr])
                if d > moved:
                    moved, furthest = d, hr

    # Which way each star is heading, and whether the shape is really one
    # group of stars travelling together. Five of the Big Dipper's seven are
    # members of the Ursa Major moving group and two are not, and that shows
    # up as a bearing, not as a speed.
    bearings = {}
    for hr in now:
        m = mots.get(str(hr))
        if m:
            bearings[hr] = (math.degrees(math.atan2(m["pmra"], m["pmde"])) % 360.0,
                            math.hypot(m["pmra"], m["pmde"]))
    with_group, apart = [], []
    if len(bearings) >= 3:
        mean = _mean_angle([b for b, _ in bearings.values()])
        for hr, (b, _speed) in bearings.items():
            (with_group if _angle_gap(b, mean) <= 45.0 else apart).append(hr)

    return {
        "name": name,
        "span": SPAN,
        "deform": deform,
        "moved": moved,
        "furthest": furthest,
        "with_group": sorted(with_group),
        "apart": sorted(apart),
        "flagged": sorted(notes),
        "field_deg": plane_to_deg(field(a, EPOCHS, stars, mots)[0]) * 2,
    }


def _mean_angle(angles):
    x = sum(math.cos(math.radians(a)) for a in angles)
    y = sum(math.sin(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(y, x)) % 360.0


def _angle_gap(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


# ------------------------------------------------------------ animation
# The animation is drawn narrower than the panels above it, and that is
# arithmetic rather than taste. A character cell in the exported GIF is 10px
# wide; on the page the same drawing is set at 12px monospace, so 96 columns
# of panel occupy about 691px. A 96-column GIF is 962px, and the browser
# would squeeze it into the column -- resampling every letter of every star
# name, which is what made the text look blurry when the frames themselves
# were sharp. 68 columns is 680px, which lands under the panels at its own
# size with nothing resampled.
GIF_COLS = 68

# ...and rendered at twice that and shown at half, because it sits beside
# page text. The browser draws its own words at the screen's real
# resolution; a bitmap at half that is stretched by the display, and text
# inside a picture is exactly where anyone would notice.
GIF_SCALE = 2
GIF_CSS_WIDTH = GIF_COLS * 10          # gif._CELL_W is 10px at 1x

# How long each frame is held, in milliseconds. A thousand years a frame is
# not something to race through, and there is nothing here to track with the
# eye the way there is in a sky animation -- the reading of it is a slow
# drift, so it is paced for that.
STEP_MS = 210
# The two ends and the middle get held. Without this the first frame is
# 210ms like every other one and then the loop snaps back to it, so the
# -50,000 shape -- one of the three things the animation exists to show --
# goes past too fast to read. Twice a step, not the second and a half it
# was first set to: long enough to register as a pause, short enough that
# the loop does not feel like it has stopped.
END_MS = 420
NOW_MS = 420

# Bumped whenever the drawing itself changes. It rides on the image URL, so
# a reader whose browser cached last week's picture gets this week's instead
# of a week-old one -- the GIF is cached hard on purpose and there is
# otherwise nothing in the URL to say the picture is not the same picture.
RENDER_VERSION = 5


def frame_durations(count):
    """One duration per frame: a beat on each end and on the middle, and an
    even pace between them."""
    out = [STEP_MS] * count
    if count:
        out[0] = out[-1] = END_MS
        out[count // 2] = NOW_MS
    return out


def frames(name, steps=41, colour=True, cols=GIF_COLS):
    """The whole span as frames, for gif.py.

    Every frame is the same size and drawn at the same scale, both of which
    are load-bearing: frames of different widths get re-centred by whatever
    shows them and the shape visibly shuffles sideways, and a scale that
    followed each frame would hide the very spreading it exists to show.
    """
    a = asterism(name)
    if not a:
        return []
    stars, mots = _stars(), _motions()
    years = [round(-SPAN + 2 * SPAN * i / (steps - 1)) for i in range(steps)]
    box = field(a, years, stars, mots, cols=cols)
    out = []
    for y in years:
        body = panel(a, y, box, cols=cols, colour=colour, stars=stars,
                     mots=mots, trim=False)
        label = _epoch_label(y)
        out.append([sky.paint(label.ljust(cols), sky.C.MUTE, colour)] + body)
    return out
