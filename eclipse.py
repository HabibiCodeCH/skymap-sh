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
