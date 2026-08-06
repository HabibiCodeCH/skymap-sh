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
import lunar
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

# The Earth's first eccentricity squared, from the flattening besselian.py
# already works to, so the two cannot disagree about the shape of the planet.
_E2 = 1.0 - besselian._FLATTENING ** 2


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
    # A window over the date line runs past 180 rather than being cut in
    # two, so a place at -170 has to be looked for at 190 as well.
    if lon < lon_l and lon_r > 180:
        lon += 360
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
# Totality has to leave room for the corona, and the corona now reaches
# about 1.45 Moon-radii before its streamers, with the Moon up to 1.04
# Sun-radii. Eight rows of room above the centre divided by that is a Sun of
# about 5, which is what leaves the halo somewhere to be.
SUN_R_PARTIAL = 8.0
SUN_R_TOTAL = 5.0

# Bright core to dimmer limb. Not physics -- real limb darkening is slight --
# it is what stops a flat disc of one character reading as a hole rather
# than a light.
SUN_TONES = ((0.55, 231), (0.85, 227), (1.01, 220))
# --- the corona ------------------------------------------------------------
# It used to be a band of identical dots between two radii, with a gap of
# black between the Moon's edge and the first of them. That reads as a dotted
# circle, which is what it was. Five things make it read as a corona:
#
# 1. It touches the Moon. The inner corona is brightest right at the limb,
#    and the black gap was the loudest wrong thing in the picture.
# 2. It fades outward. Density falls off with radius rather than stopping at
#    an edge, so it is a glow and not an outline.
# 3. Streamers. A real corona has a handful of long spikes, and they are the
#    single feature that says "corona" rather than "halo".
# 4. A ragged edge. Dots on a perfect circle read as a circle however faint
#    they are, so the outer boundary wobbles.
# 5. Colour temperature. Near-white at the limb, warming outward. Three tones
#    rather than two: the real thing is pearl-white, but next to a Sun drawn
#    in 220/227 a grey ring read as a rendering artefact rather than light.
CORONA_LIMB = 1.01        # where it starts, in Moon radii: on the limb
CORONA_RIM = 1.18         # the bright inner ring, drawn solid
CORONA_REACH = 1.45       # how far the halo goes with no streamer
STREAMER_REACH = 0.70     # how much further along one
STREAMERS = 6
CORONA_TONES = ((1.20, 231), (1.42, 222), (99.0, 214))
CORONA_GLYPHS = ((1.24, "+"), (99.0, "·"))

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


def _corona_phase(key):
    """Where this eclipse's streamers point.

    Fixed per eclipse rather than random, so they are in the same place in
    every frame of the animation and on every reader's page. A corona whose
    spikes moved between frames would read as static.
    """
    # Mixed rather than summed. Summing the characters gave 12 August 2026
    # and 2 August 2027 the same answer, because the same digits are in both
    # dates -- and two eclipses with identical streamers is the one thing
    # this is meant to avoid.
    h = 0
    for ch in key:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return (h % 3600) / 3600.0 * 2 * math.pi


def _corona_reach(ang, phase, room):
    """How far out the corona goes at this angle, in Moon radii.

    Two sine terms wobble the boundary so it is not a circle, and a few
    narrow lobes make the streamers. `room` is how far the frame allows in
    this direction: streamers along the frame's long axis get to be long,
    the ones pointing at the top edge get cut short, which is also roughly
    what a real corona does near solar minimum.
    """
    reach = CORONA_REACH * (1.0 + 0.09 * math.sin(3 * ang + phase)
                            + 0.05 * math.sin(5 * ang - phase))
    for i in range(STREAMERS):
        lobe = math.cos(ang - (phase + 2 * math.pi * i / STREAMERS))
        if lobe > 0:
            reach += STREAMER_REACH * lobe ** 6
    return min(reach, room)


def _speckle(d, ang):
    """A stable 0..1 for a patch of sky around the Moon.

    Positioned in the Moon's own frame, not the picture's, so the texture
    travels with the Moon instead of the corona swimming through a fixed
    field of dots as the animation runs.
    """
    i = int(d * 34) * 1009 + int(ang * 38.2) * 9176
    return ((i * 1103515245 + 12345) >> 8 & 0xFFFF) / 65535.0


def _corona_cell(d, ang, phase, room):
    """(colour, glyph) for one cell of corona, or None where there is none."""
    if d < CORONA_LIMB:
        return None
    if d <= CORONA_RIM:
        # The bright rim, drawn solid. It is what gives the black disc a
        # crisp edge instead of fading into sparse dots.
        return CORONA_TONES[0][1], "+"
    reach = _corona_reach(ang, phase, room)
    if d > reach:
        return None
    # Thinning out with distance, so it ends by running out rather than by
    # stopping.
    density = (1.0 - (d - CORONA_RIM) / max(1e-6, reach - CORONA_RIM)) ** 0.7
    if _speckle(d, ang) > density:
        return None
    col = next(c for edge, c in CORONA_TONES if d <= edge)
    ch = next(g for edge, g in CORONA_GLYPHS if d <= edge)
    return col, ch


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
    # How much room the frame leaves, measured in the same units the drawing
    # is done in, so a streamer can be told to stop at the edge rather than
    # be clipped by it.
    x_max, y_max = (ART_COLS - 1) / 2.0 / CELL_X, (ART_ROWS - 1) / 2.0
    phase = _corona_phase(key)

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
                # time it is visible at all. Nothing inside the Moon: without
                # a lower bound this branch swallowed the hole and drew a
                # solid disc of dots, the eclipse with the eclipse painted in.
                ex, ey = x0 - mx, y0 - my
                d = math.hypot(ex, ey) / moon_r
                cell = None
                if d >= CORONA_LIMB:
                    ang = math.atan2(ey, ex)
                    room = min(
                        (x_max - abs(mx)) / max(1e-6, abs(math.cos(ang))),
                        (y_max - abs(my)) / max(1e-6, abs(math.sin(ang)))
                    ) / moon_r
                    cell = _corona_cell(d, ang, phase, room)
                col, ch = cell if cell else (None, " ")
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

    This is besselian._state's transform run backwards. Forwards it takes a
    place to the fundamental plane:

        xi   = rho_cos sin(theta)
        eta  = rho_sin cos(d) - rho_cos cos(theta) sin(d)
        zeta = rho_sin sin(d) + rho_cos cos(theta) cos(d)

    so given (x, y) on the plane and the near-side zeta, sin(phi') is
    y cos d + zeta sin d and theta is atan2(x, zeta cos d - y sin d). The
    first version of this had both of those signs flipped, which is the same
    as using -d: it produced a curve of exactly the right shape, the right
    length and the right duration, mirrored onto the wrong part of the
    planet. Every point it returned computed as a partial eclipse, which is
    what test_the_track_is_where_the_totality_is now checks.
    """
    el = besselian.ELEMENTS.get(key)
    if el is None:
        return []
    out = []
    t = -4.0
    while t <= 4.0:
        x, y = besselian._poly(el.x, t), besselian._poly(el.y, t)
        d = math.radians(besselian._poly(el.d, t))
        mu = math.radians(besselian._poly(el.mu, t))
        # On the ellipsoid, not a sphere. Meeus 54 flattens the fundamental
        # plane's y and the shadow's declination first (rho1, d1) and the
        # geometry is then the same as the spherical case. Doing it on a
        # sphere and converting the latitude afterwards put the track 85 km
        # west of NASA's -- a quarter of the width of the path, which is
        # exactly the size of error a map cannot show and a reader cannot
        # catch.
        rho1 = math.sqrt(1.0 - _E2 * math.cos(d) ** 2)
        sin_d1 = math.sin(d) / rho1
        cos_d1 = besselian._FLATTENING * math.cos(d) / rho1
        y1 = y / rho1
        rho2 = x * x + y1 * y1
        if rho2 < 1.0:
            b = math.sqrt(1.0 - rho2)
            sin_phi1 = b * sin_d1 + y1 * cos_d1
            cos_phi1 = math.sqrt(max(0.0, 1.0 - sin_phi1 * sin_phi1))
            theta = math.atan2(x, b * cos_d1 - y1 * sin_d1)
            # phi1 comes out geocentric; the map wants the latitude people
            # use. tan(phi) = tan(phi1) / (1 - e^2), and 1 - e^2 is exactly
            # the flattening constant squared. Measured against NASA's table:
            # without this every point sits 20 km south of the central line.
            lat = math.degrees(math.atan2(
                sin_phi1, besselian._FLATTENING ** 2 * cos_phi1))
            # mu is Greenwich's hour angle at TDT, but the point is being
            # named on a planet that has turned for delta-T seconds longer
            # than UT says. Without this the whole track sits 0.29 degrees
            # west for this eclipse, which is 20 km and is exactly delta-T
            # (70 s) written as an angle.
            lon = (math.degrees(theta - mu)
                   + 1.002738 * el.dT * 15.0 / 3600.0)
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


# ---------------------------------------------------------------- the Moon
# A lunar eclipse gets a drawing too, and it is the same machinery: a disc
# on the same grid, supersampled the same way, so both kinds of eclipse page
# put a picture in the same place at the same size.
#
# What differs is that this one is coloured rather than cut away. The Moon
# does not lose a bite out of it -- the whole disc stays where it is, and
# the part inside the Earth's shadow turns copper. That colour is the point:
# the only light reaching it there has been bent through the whole depth of
# the Earth's atmosphere, which takes the blue out of it. Drawing the
# shadowed part as missing would be drawing a solar eclipse.
MOON_R = 8.0
MOON_TONES = ((0.55, 255), (0.85, 251), (1.01, 247))
# The penumbra graded rather than flat. It is 4.6 Moon radii across, so on a
# shallow eclipse it covers the whole disc, and drawing all of it in one
# shade turned the Moon into a uniform grey blob on the nights when the real
# thing looks very nearly normal. In reality the outer half of the penumbra
# is imperceptible; only the part close to the umbra is visibly dimmer.
# Fraction of the way from the penumbra's outer edge to the umbra, and what
# to draw there -- None means "no different from full sunlight".
PENUMBRA_STEPS = ((0.45, None), (0.80, 249), (99.0, 243))
# Copper, brightening towards the edge of the umbra, which is what the real
# thing does: the deepest part of the shadow is the darkest and the reddest.
UMBRA_TONES = ((0.45, 88), (0.78, 130), (99.0, 173))
# Monochrome has to carry the same information, so the glyph changes as well
# as the colour. Denser means brighter here, the same direction as the Sun.
SHADE_GLYPH = {"sun": "#", "penumbra": "+", "umbra": "·"}


def _moon_tone(rr):
    for edge, col in MOON_TONES:
        if rr <= edge:
            return col
    return MOON_TONES[-1][1]


def _umbra_tone(d):
    """Colour for a point d Moon-radii from the centre of the umbra."""
    for edge, col in UMBRA_TONES:
        if d / lunar.UMBRA_R <= edge:
            return col
    return UMBRA_TONES[-1][1]


def moon_art(key, at=None, color=True):
    """The Moon at a moment of a lunar eclipse, as lines.

    `at` is hours UT; the default is greatest eclipse. Empty when there are
    no published circumstances for this date, which the caller treats the
    same way it treats a solar eclipse with no elements: no picture, and the
    page says why rather than drawing a guess.

    North up, east left, like everything else here. The shadow crosses from
    the east, which is the left-hand side, because the Moon overtakes it
    going east.
    """
    el = lunar.elements(key)
    if el is None:
        return []
    if at is None:
        at = lunar.greatest_ut(el)
    centre = lunar.shadow_centre(key, at)
    if centre is None:
        return []
    sx, sy = centre

    out = []
    for r in range(ART_ROWS):
        line, pen = [], None
        for c in range(ART_COLS):
            y = r - (ART_ROWS - 1) / 2.0
            x = (c - (ART_COLS - 1) / 2.0) / CELL_X
            rr = math.hypot(x, y) / MOON_R
            if rr > 1.0:
                if pen is not None and color:
                    line.append("\033[0m")
                pen = None
                line.append(" ")
                continue
            # The disc is drawn in Moon radii, which is also the unit the
            # shadow's position comes in, so the two are directly comparable
            # once the pixel is divided by the Moon's drawn radius.
            px, py = x / MOON_R, y / MOON_R
            d = math.hypot(px - sx, py - sy)
            if d <= lunar.UMBRA_R:
                col, ch = _umbra_tone(d), SHADE_GLYPH["umbra"]
            else:
                col, ch = _moon_tone(rr), SHADE_GLYPH["sun"]
                if d <= lunar.PENUMBRA_R:
                    deep = ((lunar.PENUMBRA_R - d)
                            / (lunar.PENUMBRA_R - lunar.UMBRA_R))
                    shade = next(c for edge, c in PENUMBRA_STEPS if deep <= edge)
                    if shade is not None:
                        col, ch = shade, SHADE_GLYPH["penumbra"]
            if color and col != pen:
                line.append(f"\033[38;5;{col}m")
                pen = col
            line.append(ch)
        if pen is not None and color:
            line.append("\033[0m")
        # Not rstripped, for the same reason the solar frames are not: the
        # frame centres its content and a trimmed line moves the drawing.
        out.append("".join(line))
    return out


def moon_frames(key, n=FRAMES, color=True, tz=0.0):
    """The whole lunar eclipse, first contact to last, as n drawings."""
    c = lunar.contacts(key)
    if not c:
        return [], []
    first = c.get("P1") or c.get("U1")
    last = c.get("P4") or c.get("U4")
    if first is None or last is None:
        return [], []
    frames, labels = [], []
    for i in range(n):
        t = first + (last - first) * i / (n - 1)
        art = moon_art(key, at=t, color=color)
        if not art:
            continue
        frames.append(art)
        secs = round(((t + tz) % 24) * 3600)
        labels.append(f"{secs // 3600:02d}:{secs // 60 % 60:02d}")
    return frames, labels
