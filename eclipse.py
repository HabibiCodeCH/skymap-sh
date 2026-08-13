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
import datetime as dt
import json
import math

import art
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


def _as_seen(u, v, ra_h, dec_d, lat, lon, when_utc):
    """A celestial direction turned into the drawing's frame: x right, y down.

    (u, v) is east and north, the way the Besselian fundamental plane and
    the Earth's shadow both give directions. What comes back is where that
    direction points for somebody standing at lat/lon at this instant,
    looking at it -- unit length, so the caller scales it by whatever
    separation it already trusts.

    This is the whole difference between a diagram and a picture. Celestial
    north is only up when the thing is on your meridian; on 12 August 2026
    the Sun sets over Ibiza 53 degrees from that, so the Moon took its first
    bite out of the bottom-right of the Sun while this page drew it top
    right. Two people compared the drawing to the sky and the sky won.

    Below the horizon the answer is still well defined (altaz does not stop
    at zero) and still the right one -- it is what you would see if the
    ground were not in the way, which is what an animation running past
    sunset is already showing.
    """
    jd = sky.julian(when_utc)
    lst = (sky.gmst_hours(jd) + lon / 15.0) % 24
    (ex, ey), (nx, ny) = sky.sky_basis(ra_h, dec_d, lat, lst)
    n = math.hypot(u, v) or 1.0
    e_hat, n_hat = u / n, v / n
    x = e_hat * ex + n_hat * nx
    y = e_hat * ey + n_hat * ny      # altitude, positive up
    m = math.hypot(x, y) or 1.0
    return x / m, -y / m             # y down, the way cell_centre counts rows


def _utc_at(key, hours_ut):
    """The eclipse's own UT date plus hours, as a datetime.

    Not wrapped into 0..24: a contact can fall on the day either side of the
    date the eclipse is filed under, and hours of 25.4 has to stay 25.4 so
    it lands on the right day rather than on the right clock time of the
    wrong one.
    """
    return dt.datetime.strptime(key, "%Y-%m-%d") + dt.timedelta(hours=hours_ut)


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

    Orientation is what you see: up is up. The Moon goes where it goes for
    somebody standing at lat/lon and looking, not where it goes on a star
    chart -- see _as_seen for why that is not the same thing and what it
    cost when this drew the celestial frame instead.
    """
    el = besselian.ELEMENTS.get(key)
    if el is None:
        return []
    rho_sin, rho_cos = besselian._observer(lat, lon)
    if at is None:
        # _solve_max answers in the elements' own time (hours from t0, on a
        # clock that has already been given delta-T). Everything downstream
        # of here wants hours UT, which is what `at` means on the way in, so
        # the conversion happens once and immediately -- the same one track()
        # makes, and the inverse of the _state call in the other branch.
        t_el, s = besselian._solve_max(el, rho_sin, rho_cos, lon)
        at = el.t0 + t_el - el.dT / 3600.0
    else:
        s = besselian._state(el, at + el.dT / 3600.0 - el.t0,
                             rho_sin, rho_cos, lon)
    # Nothing to draw where the Sun is down (zeta <= 0), and nothing to draw
    # where the Moon is nowhere near it either (m >= L1). The second case
    # used to fall through and paint a full, uneclipsed Sun on a page whose
    # own heading said the eclipse was not visible from there.
    if s["zeta"] <= 0 or s["m"] >= s["L1"]:
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
    # Fundamental-plane x is celestial east, y is north. Direction only --
    # the distance comes from m, which is topocentric and already right,
    # where a direction taken from the Moon's own geocentric position would
    # be a degree of parallax out.
    when = _utc_at(key, at)
    su = sky.sun(sky.julian(when))
    dx, dy = _as_seen(s["u"], s["v"], su["ra"], su["dec"], lat, lon, when)
    mx, my = dx * sep, dy * sep
    # How much room the frame leaves, measured in the same units the drawing
    # is done in, so a streamer can be told to stop at the edge rather than
    # be clipped by it.
    x_max, y_max = (ART_COLS - 1) / 2.0 / CELL_X, (ART_ROWS - 1) / 2.0
    phase = _corona_phase(key)

    # The Sun, with the Moon taken out of it. Handed to art.coverage as a
    # shape rather than rasterised here: the subsampling, the cell aspect and
    # the coverage glyphs are the same rule the Sun going down behind the
    # horizon uses (art.sun_horizon_art), and two copies of it would be two
    # places for the same star to be drawn differently.
    def _inside(x, y):
        return (math.hypot(x, y) <= sun_r
                and math.hypot(x - mx, y - my) > moon_r)

    grid = []
    for r in range(ART_ROWS):
        row = []
        for c in range(ART_COLS):
            lit = art.coverage(c, r, _inside, ART_COLS, ART_ROWS, CELL_X)
            x0, y0 = art.cell_centre(c, r, ART_COLS, ART_ROWS, CELL_X)
            if lit:
                col = _disc_tone(math.hypot(x0, y0) / sun_r)
                ch = art.cover_glyph(lit / 9.0)
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
            row.append(None if col is None else (col, ch))
        grid.append(row)
    # NOT rstripped, unlike the map above -- see art.emit_cells, which is
    # where that rule now lives along with the reason for it.
    return art.emit_cells(grid, color)





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


def _umbra_tone(d, umbra_r):
    """Colour for a point d Moon-radii from the centre of the umbra."""
    for edge, col in UMBRA_TONES:
        if d / umbra_r <= edge:
            return col
    return UMBRA_TONES[-1][1]


def moon_art(key, at=None, color=True, lat=None, lon=None):
    """The Moon at a moment of a lunar eclipse, as lines.

    `at` is hours UT; the default is greatest eclipse. Empty when there are
    no published circumstances for this date, which the caller treats the
    same way it treats a solar eclipse with no elements: no picture, and the
    page says why rather than drawing a guess.

    Given a place, this is drawn the way you would see it from there: up is
    up, and the shadow comes in from wherever it actually comes in from,
    which depends on where the Moon is in your sky and is nowhere near
    constant over a night. Without a place it stays in the celestial frame
    (north up, east left, shadow entering from the left as the Moon
    overtakes it going east) -- that is the shared social card, which is
    fetched once by a crawler and shown to everybody, so there is no "you"
    to draw it for.
    """
    el = lunar.elements(key)
    if el is None:
        return []
    if at is None:
        at = lunar.greatest_ut(el)
    centre, geo = lunar.shadow_centre(key, at), lunar.geometry(key)
    if centre is None or geo is None:
        return []
    sx, sy = centre
    if lat is not None and lon is not None:
        # shadow_centre already answers in the celestial drawing frame (x
        # right, y down, north up, east left), so it is turned back into
        # east/north before being asked where it points from here. Length is
        # kept: it is a real distance in Moon radii and the rotation is only
        # ever about direction.
        d = math.hypot(sx, sy)
        when = _utc_at(key, at)
        mo = sky.moon(sky.julian(when))
        ux, uy = _as_seen(-sx, -sy, mo["ra"], mo["dec"], lat, lon, when)
        sx, sy = ux * d, uy * d
    # Per eclipse, not constants: the shadow is a good ten percent bigger at
    # apogee than at perigee, and the published magnitudes are what pin it.
    _s_min, umbra_r, penumbra_r = geo

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
            if d <= umbra_r:
                col, ch = _umbra_tone(d, umbra_r), SHADE_GLYPH["umbra"]
            else:
                col, ch = _moon_tone(rr), SHADE_GLYPH["sun"]
                if d <= penumbra_r:
                    deep = (penumbra_r - d) / (penumbra_r - umbra_r)
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


# There is no moon_frames, deliberately. It existed as the lunar mirror of
# disc_frames -- the Moon entering the shadow, frame by frame -- and never
# had a caller or a test: the lunar page animates arc_frames instead, the
# Moon's whole night as a curve, because how long it is up for is the
# question that page is answering.
#
# Removed rather than kept. The two functions this project keeps unused
# (api.coming_up_card_html, api.events_cards) are kept because they are
# still unit-tested and could plausibly come back; this one was neither, and
# it had just been given lat/lon parameters that made it look maintained.
#
# Everything it needs still exists if the lunar disc ever wants animating:
# moon_art(key, at=..., lat=..., lon=...) draws one frame at one instant,
# and disc_frames is the shape to copy. It is in the history at the commit
# that removed it.


# ------------------------------------------------------------ the night arc
# The lunar equivalent of the solar animation, and deliberately a different
# picture. A solar eclipse is over in minutes and the question is what the
# Sun looks like; a lunar one runs for hours and the question is whether the
# Moon is even up for it. So this draws the arc: the Moon rising, crossing,
# and setting, with the eclipse marked on the part of it where the eclipse
# happens, and the Moon itself somewhere along it.
ARC_COLS, ARC_ROWS = 90, 13
# Three glyphs sitting at the bottom, middle and top of a character cell.
# Altitude is a smooth curve and a row is 5 degrees of it, so rounding to
# whole rows drew the night as a pyramid: long straight flanks and a flat
# plateau over the hour either side of culmination, which is the one part of
# the shape that is not real. Reading the fraction of a row as well triples
# the vertical resolution without needing a taller frame.
ARC_GLYPH = (".", "-", "'")
HORIZON_COLOR = 240
ARC_COLOR = 238             # the path, before and after
ARC_PEN = 249               # the part in the penumbra
ARC_UMBRA = 130             # the part in the umbra
MOON_MARK = {"sun": (255, "●"), "penumbra": (250, "●"), "umbra": (173, "●")}


def _arc_shade(c, ut):
    """What the Moon looks like at this moment, as one of the shade names."""
    if not c:
        return "sun"
    if c.get("U2") is not None and c["U2"] <= ut <= c["U3"]:
        return "umbra"
    if c.get("U1") is not None and c["U1"] <= ut <= c["U4"]:
        return "umbra"
    if c.get("P1") is not None and c["P1"] <= ut <= c["P4"]:
        return "penumbra"
    return "sun"


def arc_art(key, lat, lon, at=None, color=True, tz=0.0):
    """The Moon's night, as lines: up over the horizon and down again.

    Height is altitude, width is time from moonrise to moonset, and the
    stretch of the arc where the eclipse happens is coloured. Scaled to the
    highest the Moon gets rather than to 90 degrees, because an eclipse that
    peaks at 12 degrees drawn on a 90-degree axis is a flat line and the
    point of the picture is the shape of the night.

    Empty when the Moon is not up at any point of the eclipse, which is the
    caller's cue to say so rather than to draw an empty box.
    """
    window = lunar.up_window(key, lat, lon)
    if window is None:
        return []
    t0, t1 = window
    marks = lunar.contacts(key)
    alts = []
    for c in range(ARC_COLS):
        t = t0 + (t1 - t0) * c / (ARC_COLS - 1)
        alts.append((t, lunar.moon_alt(key, lat, lon, t) or 0.0))
    peak = max(a for _t, a in alts) or 1.0

    rows = [[" "] * ARC_COLS for _ in range(ARC_ROWS)]
    cols = [[None] * ARC_COLS for _ in range(ARC_ROWS)]
    horizon = ARC_ROWS - 1
    for c, (t, alt) in enumerate(alts):
        rows[horizon][c] = "-"
        cols[horizon][c] = HORIZON_COLOR
        if alt <= 0:
            continue
        y = alt / peak * (ARC_ROWS - 2)
        r = max(0, min(horizon - 1, horizon - 1 - int(y)))
        shade = _arc_shade(marks, t)
        # Colour says which stretch is the eclipse, so the curve can stay one
        # continuous line. With colour off it cannot, and a heavier mark is
        # what carries it in a plain terminal instead.
        rows[r][c] = (ARC_GLYPH[min(2, int((y - int(y)) * 3))]
                      if color or shade == "sun" else "+")
        cols[r][c] = {"sun": ARC_COLOR, "penumbra": ARC_PEN,
                      "umbra": ARC_UMBRA}[shade]

    if at is not None and t0 <= at <= t1:
        c = int(round((at - t0) / (t1 - t0) * (ARC_COLS - 1)))
        alt = lunar.moon_alt(key, lat, lon, at) or 0.0
        r = horizon - 1 - int(round(max(0.0, alt) / peak * (ARC_ROWS - 2)))
        r = max(0, min(horizon - 1, r))
        col, glyph = MOON_MARK[_arc_shade(marks, at)]
        rows[r][c], cols[r][c] = glyph, col

    out = []
    for r in range(ARC_ROWS):
        line, pen = [], None
        for c in range(ARC_COLS):
            col = cols[r][c]
            if col is None:
                if pen is not None and color:
                    line.append("\033[0m")
                pen = None
                line.append(" ")
                continue
            if color and col != pen:
                line.append(f"\033[38;5;{col}m")
                pen = col
            line.append(rows[r][c])
        if pen is not None and color:
            line.append("\033[0m")
        out.append("".join(line))
    return out


def arc_frames(key, lat, lon, n=FRAMES, color=True, tz=0.0):
    """The night, frame by frame, the Moon moving along its own arc.

    Over the whole time the Moon is up rather than only the eclipse: how
    long it is up for is the thing this picture is answering.
    """
    window = lunar.up_window(key, lat, lon)
    if window is None:
        return [], []
    t0, t1 = window
    frames, labels = [], []
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        art = arc_art(key, lat, lon, at=t, color=color, tz=tz)
        if not art:
            continue
        frames.append(art)
        secs = round(((t + tz) % 24) * 3600)
        labels.append(f"{secs // 3600:02d}:{secs // 60 % 60:02d}")
    return frames, labels


# ------------------------------------------------------- who can see it
# A lunar eclipse has no path, so it gets the opposite map: not a thin band
# somebody might travel to, but the whole night side of the planet, shaded
# by how much of the eclipse happens with the Moon above the horizon.
#
# The land under it is worldmap.json, the same mask the /stats heat map
# already ships, sampled down to this width. No new build step and no second
# copy of the coastlines to keep in step with the first.
NIGHT_COLS, NIGHT_ROWS = 128, 26
# The copper of the eclipse itself, so the two pictures on the page are
# about the same thing: the same colour the Moon turns in the drawing above.
# The land that misses it goes light rather than dark -- on a black page two
# dim colours read as one, and what this map is for is the boundary between
# them.
NIGHT_ALL = 208             # the whole eclipse, from here
NIGHT_SOME = 172            # part of it: the Moon rises or sets partway
NIGHT_NONE = 249            # the Moon is down for all of it
_night_grids = {}


def _world_mask(cols, rows):
    """The /stats coastlines, sampled to this size. (mask, lat_top, lat_bot)."""
    try:
        with open(f"{sky.BASE}/worldmap.json") as f:
            w = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    src, sw, sh = w["rows"], w["width"], w["height"]
    out = []
    for r in range(rows):
        sr = min(sh - 1, int((r + 0.5) * sh / rows))
        line = src[sr]
        out.append("".join(line[min(sw - 1, int((c + 0.5) * sw / cols))]
                           for c in range(cols)))
    return out, w["lat_top"], w["lat_bot"]


def _night_grid(key):
    """Per cell: how many of the eclipse's contacts happen with the Moon up.

    Cached by eclipse, because it is the same for every reader -- a lunar
    eclipse looks identical to everybody who can see it, which is the whole
    reason this map answers "can you" rather than "how much".
    """
    if key in _night_grids:
        return _night_grids[key]
    mask = _world_mask(NIGHT_COLS, NIGHT_ROWS)
    marks = lunar.contacts(key)
    if mask is None or not marks:
        return None
    rows, lat_top, lat_bot = mask
    # The umbral phase where there is one, the penumbral otherwise: a
    # penumbral eclipse is all there is to see on those nights, and a
    # partial one is not worth being up for outside the umbral phase.
    span = [marks[k] for k in ("U1", "U4") if k in marks] or \
           [marks[k] for k in ("P1", "P4") if k in marks]
    when = [span[0], marks["greatest"], span[-1]]
    grid = []
    for r in range(NIGHT_ROWS):
        lat = lat_top - (r + 0.5) * (lat_top - lat_bot) / NIGHT_ROWS
        line = []
        for c in range(NIGHT_COLS):
            lon = -180.0 + (c + 0.5) * 360.0 / NIGHT_COLS
            up = sum(1 for t in when
                     if (lunar.moon_alt(key, lat, lon, t) or -1) > 0)
            line.append(up)
        grid.append(line)
    _night_grids[key] = (grid, rows, lat_top, lat_bot)
    return _night_grids[key]


def night_cell_of(key, lat, lon):
    got = _night_grid(key)
    if not got:
        return None
    _grid, _rows, lat_top, lat_bot = got
    if not lat_bot <= lat <= lat_top:
        return None
    lon = ((lon + 180) % 360) - 180
    r = int((lat_top - lat) / (lat_top - lat_bot) * NIGHT_ROWS)
    c = int((lon + 180.0) / 360.0 * NIGHT_COLS)
    return (min(NIGHT_ROWS - 1, max(0, r)), min(NIGHT_COLS - 1, max(0, c)))


def night_map(key, mark=None, color=True):
    """Where the Moon is up for this eclipse, as lines."""
    got = _night_grid(key)
    if not got:
        return []
    grid, land, _lat_top, _lat_bot = got
    at = night_cell_of(key, *mark) if mark else None
    out = []
    for r in range(NIGHT_ROWS):
        line, pen = [], None
        for c in range(NIGHT_COLS):
            up = grid[r][c]
            here = at == (r, c)
            if land[r][c] != "#" and not here:
                if pen is not None and color:
                    line.append("\033[0m")
                pen = None
                line.append(SEA)
                continue
            if here:
                col, glyph = 51, "✕"
            else:
                col = (NIGHT_ALL if up == 3 else
                       NIGHT_SOME if up else NIGHT_NONE)
                glyph = "·"
            if color and col != pen:
                line.append(f"\033[38;5;{col}m")
                pen = col
            line.append(glyph)
        if pen is not None and color:
            line.append("\033[0m")
        out.append("".join(line).rstrip())
    return out


def night_legend(color=True):
    parts = [(NIGHT_ALL, "· all of it"), (NIGHT_SOME, "· part of it"),
             (NIGHT_NONE, "· Moon down")]
    if not color:
        return "   ".join(t for _c, t in parts)
    return "   ".join(f"\033[38;5;{c}m{t}\033[0m" for c, t in parts)
