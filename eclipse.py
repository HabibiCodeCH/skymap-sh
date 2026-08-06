"""The eclipse map: where the shadow falls, drawn from our own numbers.

Not traced from anyone's published map. Every cell here is `besselian.local`
evaluated at that cell's coordinates, so the track's position and width come
from the same arithmetic the page's times and percentages do. If one is
wrong they are all wrong together, which is the honest failure mode -- a map
traced from a picture would keep looking right while the numbers drifted.

The land mask underneath is `eclipsemap.json` (build_eclipsemap.py), a
region rather than the whole planet: at the /stats map's 1.7 degrees per
column a 300 km track is thinner than one character.
"""
import json
import math

import besselian
import sky

# xterm-256, the same palette sky.py's renderer uses, so api.ansi_to_html
# converts it for the browser with no extra work.
#
# Warm means more covered, which is the direction /stats already uses for
# its heat map, so anyone who has read that page can read this one. The
# tempting alternative -- darker means more eclipsed, since that is what an
# eclipse does -- fails on a black terminal for the one band that matters:
# the path of totality would be the least visible thing on the map.
LAND_DIM = 238
# Thresholds bunched at the top on purpose. Evenly spaced ones put almost
# the whole of Europe in a single shade for this eclipse, because almost the
# whole of Europe sees between 75 and 99 percent, and a band everything
# falls into says nothing. The interesting question near the track is not
# "half or three-quarters" but "how close to all of it".
BANDS = (
    (0.01, 238, "·"),      # land the eclipse never reaches
    (0.20, 231, "·"),
    (0.40, 230, "·"),
    (0.60, 228, "·"),
    (0.75, 222, "·"),
    (0.85, 220, "·"),
    (0.93, 214, "·"),
    (0.98, 208, "·"),
    (1.00, 202, "·"),      # a hair short of total, and still not total
)
TOTAL_COLOR = 196
TOTAL_DOT = "●"
# Totality gets drawn over water as well as land. Everything else does not.
# Without this the track breaks at every coastline and the one line the map
# exists to show arrives as three unconnected smudges: Greenland, Iceland,
# Spain. Drawn dimmer at sea, so the coast is still legible underneath it.
SEA_TOTAL_COLOR = 160
SEA = " "

_maps = None
_grids = {}


def _load():
    global _maps
    if _maps is None:
        try:
            with open(f"{sky.BASE}/eclipsemap.json") as f:
                _maps = json.load(f)
        except (OSError, json.JSONDecodeError):
            # Survivable, exactly as the /stats map is: the page is worth
            # more without a map than it is 500-ing over a missing file.
            _maps = {}
    return _maps


def has_map(key):
    return key in _load()


def region(key):
    """(lat_top, lat_bot, lon_left, lon_right, width, height) or None."""
    d = _load().get(key)
    if not d:
        return None
    return (d["lat_top"], d["lat_bot"], d["lon_left"], d["lon_right"],
            d["width"], d["height"])


def cell_of(key, lat, lon):
    """Grid cell for a position, or None when it is off this map."""
    r = region(key)
    if not r:
        return None
    lat_top, lat_bot, lon_l, lon_r, w, h = r
    lon = ((lon + 180) % 360) - 180
    if not (lat_bot <= lat <= lat_top and lon_l <= lon <= lon_r):
        return None
    row = int((lat_top - lat) / (lat_top - lat_bot) * h)
    col = int((lon - lon_l) / (lon_r - lon_l) * w)
    return (min(h - 1, max(0, row)), min(w - 1, max(0, col)))


def _grid(key):
    """Per cell: (obscuration, is_total). Computed once and kept.

    The same for every reader -- it is a map of an eclipse, not of them --
    so this is worth caching hard. About 5,000 solves, a fraction of a
    second, once per process.
    """
    if key in _grids:
        return _grids[key]
    reg = region(key)
    if not reg:
        return None
    lat_top, lat_bot, lon_l, lon_r, w, h = reg
    el = besselian.ELEMENTS[key]
    out = []
    for r in range(h):
        lat = lat_top - (r + 0.5) * (lat_top - lat_bot) / h
        line = []
        for c in range(w):
            lon = lon_l + (c + 0.5) * (lon_r - lon_l) / w
            rho_sin, rho_cos = besselian._observer(lat, lon)
            _t, s = besselian._solve_max(el, rho_sin, rho_cos, lon)
            # zeta <= 0 is the far side of the Earth, where the Sun is not
            # up. The same test besselian.local makes, and it has to be made
            # here too or the map draws an eclipse the page denies -- which
            # is what test_the_map_agrees_with_the_page caught, at Rome,
            # where the Sun sets a few minutes before maximum.
            if s["m"] >= s["L1"] or s["zeta"] <= 0:
                line.append((0.0, False))
                continue
            obsc = besselian._obscuration(s["m"], s["L1"], s["L2"])
            line.append((obsc, s["m"] < abs(s["L2"])))
        out.append(line)
    _grids[key] = out
    return out


def _band(obsc):
    for i, (ceiling, _col, _ch) in enumerate(BANDS):
        if obsc < ceiling:
            return i
    return len(BANDS) - 1


def render(key, mark=None, color=True):
    """The map, as lines. `mark` is an optional (lat, lon) drawn as a cross.

    Returns [] when there is no mask for this eclipse, which every caller
    treats as "no map on this page" rather than an error.
    """
    grid, reg = _grid(key), region(key)
    if not grid or not reg:
        return []
    rows = _load()[key]["rows"]
    at = cell_of(key, *mark) if mark else None

    out = []
    for r, land in enumerate(rows):
        line, pen = [], None
        for c, ch in enumerate(land):
            obsc, total = grid[r][c]
            here = at == (r, c)
            if ch != "#" and not here and not total:
                # Open water outside the track. Close the colour before a run
                # of it so the escape codes do not outnumber the dots.
                if pen is not None and color:
                    line.append("\033[0m")
                pen = None
                line.append(SEA)
                continue
            if here:
                col, glyph = 51, "✕"          # cyan cross: you are here
            elif total and ch != "#":
                col, glyph = SEA_TOTAL_COLOR, TOTAL_DOT
            elif total:
                col, glyph = TOTAL_COLOR, TOTAL_DOT
            else:
                i = _band(obsc)
                col, glyph = BANDS[i][1], BANDS[i][2]
            if color and col != pen:
                line.append(f"\033[38;5;{col}m")
                pen = col
            line.append(glyph)
        if pen is not None and color:
            line.append("\033[0m")
        out.append("".join(line).rstrip())
    return out


def legend(color=True):
    """One line, in the same colours as the map.

    Read off BANDS rather than written out beside it, so retuning the
    thresholds cannot leave the key describing the old ones.
    """
    parts = [(TOTAL_COLOR, TOTAL_DOT + " total")]
    for i in range(len(BANDS) - 1, 0, -1):
        floor = BANDS[i - 1][0]
        parts.append((BANDS[i][1], f"· {floor * 100:.0f}%"))
    parts.append((LAND_DIM, "· none"))
    if not color:
        return "   ".join(t for _c, t in parts)
    return "   ".join(f"\033[38;5;{c}m{t}\033[0m" for c, t in parts)


# The Sun's disc, drawn at the same cell aspect art.py uses so the CSS that
# already pins .obj-art's line-height keeps this circular too. Smaller than a
# planet portrait because the Moon has to have somewhere to be: at first
# contact the two discs together span twice the Sun's diameter.
ART_COLS, ART_ROWS = 45, 17      # art.py's frame, so .obj-art's CSS fits
CELL_X = 2.0                     # matches art.CELL; see its comment there
# Two sizes, because the two pictures have to fit different things.
#
# A partial eclipse is one disc and can fill the frame, which matters: at
# 90% covered the surviving crescent is a tenth of the diameter, so every
# cell of radius is a tenth of a cell of crescent. Drawn at the totality
# size it came out as a dotted line with gaps in it.
#
# Totality has to leave room for the corona, which reaches 1.28 Moon-radii
# and the Moon is up to 1.04 Sun-radii, so the Sun has to come down to
# about 6.2 or the halo runs off the top and bottom and stops reading as a
# ring at all.
SUN_R_PARTIAL = 8.0
SUN_R_TOTAL = 6.2

# Bright core to dimmer limb. Not physics -- real limb darkening is slight --
# it is what stops a flat disc of one character reading as a hole rather
# than a light.
SUN_TONES = ((0.55, 231), (0.85, 227), (1.01, 220))
# Warm, not white. The real corona is pearl-white, but on this page it sits
# next to a Sun drawn in 220/227 and a track drawn in 196, and a grey ring
# read as a rendering artefact rather than as light. Two tones so it falls
# off outward instead of stopping at a hard edge.
CORONA_INNER = 221
CORONA_OUTER = 214

# Each cell sampled on a 3x3 grid instead of at its centre. At 90% covered
# the surviving crescent is about a tenth of the Sun's diameter, which is
# thinner than one character: sampling the centre alone drew it as four
# disconnected marks with gaps where the crescent passed between samples.
# Coverage also picks the glyph, so a barely-lit cell reads lighter than a
# full one and the crescent keeps a soft edge instead of a staircase.
_SUB = (-1 / 3.0, 0.0, 1 / 3.0)
_COVER_GLYPH = ((0.34, "."), (0.67, "+"), (1.01, "#"))


def _glyph_for(frac):
    for edge, ch in _COVER_GLYPH:
        if frac <= edge:
            return ch
    return "#"


def _disc_tone(rr):
    for edge, col in SUN_TONES:
        if rr <= edge:
            return col
    return SUN_TONES[-1][1]


def disc_art(key, lat, lon, at=None, color=True, sun_r=None):
    """The Sun as it looks from here, at maximum or at a given hour (UT).

    The Moon is not drawn, because you cannot see it: during a partial
    eclipse there is nothing up there but a Sun with a bite out of it, and
    a grey disc laid over it would be a diagram of the geometry rather than
    a picture of the sky. What the Moon does is take light away.

    Totality is the exception and gets the corona, which is the one time the
    Moon's edge is genuinely visible, as the hole in the middle of it.

    Orientation is celestial: north up, east left. Turning that into
    zenith-up needs the parallactic angle, and a drawing that silently got
    that wrong would be worse than one that says which way up it is.
    """
    el = besselian.ELEMENTS.get(key)
    if el is None:
        return []
    rho_sin, rho_cos = besselian._observer(lat, lon)
    if at is None:
        _t, s = besselian._solve_max(el, rho_sin, rho_cos, lon)
    else:
        s = besselian._state(el, at + el.dT / 3600.0 - el.t0,
                             rho_sin, rho_cos, lon)
    if s["zeta"] <= 0:
        return []

    big_l1, big_l2 = s["L1"], s["L2"]
    r_sun = (big_l1 + big_l2) / 2.0
    r_moon = (big_l1 - big_l2) / 2.0
    if r_sun <= 0:
        return []
    # Everything in units of the Sun's radius, so the Sun is the same size
    # on screen whatever the geometry is doing.
    total = s["m"] < abs(big_l2) and big_l2 < 0
    # An explicit scale is what keeps an animation still. Chosen per frame,
    # the Sun jumps between the two sizes at the instant totality starts and
    # again when it ends, in the middle of the sequence, which reads as the
    # picture breaking rather than as the eclipse happening.
    if sun_r is None:
        sun_r = SUN_R_TOTAL if total else SUN_R_PARTIAL
    moon_r = sun_r * (r_moon / r_sun)
    sep = sun_r * (s["m"] / r_sun)
    n = math.hypot(s["u"], s["v"]) or 1.0
    # Fundamental-plane x is celestial east, y is north. On screen north is
    # up and east is left, so both signs flip.
    mx, my = -s["u"] / n * sep, -s["v"] / n * sep

    out = []
    for r in range(ART_ROWS):
        line, pen = [], None
        for c in range(ART_COLS):
            lit = 0
            for dy in _SUB:
                y = r - (ART_ROWS - 1) / 2.0 + dy
                for dx in _SUB:
                    x = (c - (ART_COLS - 1) / 2.0 + dx) / CELL_X
                    if (math.hypot(x, y) <= sun_r
                            and math.hypot(x - mx, y - my) > moon_r):
                        lit += 1
            y0 = r - (ART_ROWS - 1) / 2.0
            x0 = (c - (ART_COLS - 1) / 2.0) / CELL_X
            if lit:
                frac = lit / 9.0
                col = _disc_tone(math.hypot(x0, y0) / sun_r)
                ch = _glyph_for(frac)
            elif total:
                # Corona, and only during totality, because that is the only
                # time it is visible at all. A thin halo just off the limb.
                d = math.hypot(x0 - mx, y0 - my) / moon_r
                if 1.0 <= d <= 1.13:
                    col, ch = CORONA_INNER, "\u00b7"
                elif 1.13 < d <= 1.28:
                    col, ch = CORONA_OUTER, "\u00b7"
                else:
                    # Inside the Moon as well as outside the halo. Without
                    # the lower bound this branch swallowed the hole and
                    # drew a solid disc of dots -- the eclipse with the
                    # eclipse painted in.
                    col, ch = None, " "
            else:
                col, ch = None, " "
            if col is None:
                if pen is not None and color:
                    line.append("\033[0m")
                pen = None
                line.append(ch)
                continue
            if color and col != pen:
                line.append(f"\033[38;5;{col}m")
                pen = col
            line.append(ch)
        if pen is not None and color:
            line.append("\033[0m")
        # NOT rstripped, unlike the map above. Every frame has to be exactly
        # ART_COLS wide, because the frame around it centres its content: a
        # trimmed line makes a narrower block, which gets re-centred, and the
        # Sun visibly shuffles sideways from frame to frame while the Moon
        # crosses it. The Sun is the one thing here that must not move.
        out.append("".join(line))
    return out





def track(key, step_minutes=2):
    """The central line as (lat, lon) points, for anything that wants the
    path itself rather than a picture of it.

    Found by walking the shadow axis: at each instant the axis meets the
    Earth at one point, and that point is the centre of the track.
    """
    el = besselian.ELEMENTS.get(key)
    if el is None:
        return []
    out = []
    t = -3.0
    while t <= 3.0:
        x, y = besselian._poly(el.x, t), besselian._poly(el.y, t)
        d = math.radians(besselian._poly(el.d, t))
        mu = math.radians(besselian._poly(el.mu, t))
        rho2 = x * x + y * y
        if rho2 < 1.0:
            zeta = math.sqrt(1.0 - rho2)
            # Rotate the fundamental-plane point back onto the globe.
            b1 = y * math.sin(d) + zeta * math.cos(d)
            lat = math.degrees(math.asin(
                y * math.cos(d) - zeta * math.sin(d)))
            lon = math.degrees(math.atan2(x, b1) - mu)
            out.append((lat, ((lon + 180) % 360) - 180,
                        el.t0 + t - el.dT / 3600.0))
        t += step_minutes / 60.0
    return out


# How many frames an eclipse animation gets between first and last contact.
# Enough that the Moon moves less than its own width between frames, few
# enough that the page does not ship a megabyte of pre-rendered grids.
FRAMES = 25


def disc_frames(key, lat, lon, n=FRAMES, color=True, tz=0.0):
    """The whole eclipse, first contact to last, as n drawings.

    Rendered here rather than in the browser because the geometry is
    Besselian and the browser has none of it. What ships is pictures.

    Returns (frames, labels): the labels are clock strings, shifted by tz, so
    whatever plays them can say what moment is on screen. Local by default
    from the page, because every other time on it is local and a clock in UT
    sitting next to a timeline in local time is a trap. Empty when this place
    sees nothing, which the caller treats as "no animation here".
    """
    if key not in besselian.ELEMENTS:
        return [], []
    circ = besselian.local(key, lat, lon)
    first, last = circ.get("first"), circ.get("last")
    if first is None or last is None or circ["kind"] == "none":
        return [], []
    # One scale for the whole sequence, decided by whether totality happens
    # here at all: if it does, every frame has to leave room for the corona.
    scale = SUN_R_TOTAL if circ["kind"] in ("total", "annular") else SUN_R_PARTIAL
    frames, labels = [], []
    for i in range(n):
        t = first + (last - first) * i / (n - 1)
        art = disc_art(key, lat, lon, at=t, color=color, sun_r=scale)
        if not art:
            continue
        frames.append(art)
        secs = round(((t + tz) % 24) * 3600)
        labels.append(f"{secs // 3600:02d}:{secs // 60 % 60:02d}")
    return frames, labels
