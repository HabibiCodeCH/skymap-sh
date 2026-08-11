#!/usr/bin/env python3
"""
sky.py — the night sky overhead, as text.

    curl skymap.sh/Zurich

Stars: Yale Bright Star Catalogue (BSC5, public domain), 2,887 stars to mag 5.5.
Asterism lines: hand-authored here from published Bayer designations.
Sun/Moon: Meeus low-precision series. Planets: JPL approximate elements
(Standish, valid 1800–2050). No ephemeris download, no API key.
"""
import json, math, datetime as dt, os

D = math.pi / 180
BASE = os.path.dirname(os.path.abspath(__file__))

_CACHE = {}
def _load(name):
    """Catalogue files never change at runtime. Parsing stars.json is 4.8 ms —
    28% of a cold render — so read each file exactly once per process."""
    if name not in _CACHE:
        _CACHE[name] = json.load(open(f"{BASE}/{name}"))
    return _CACHE[name]

# ---------------------------------------------------------------- palette
class C:
    OFF = "\033[0m"
    DIM = "\033[38;5;61m"       # constellation lines (indigo, not grey)
    CNAME = "\033[38;5;104m"    # constellation names
    HOR = "\033[38;5;239m"      # horizon
    CARD = "\033[38;5;244m"     # cardinal letters
    LABEL = "\033[38;5;250m"
    HEAD = "\033[38;5;255m"
    MUTE = "\033[38;5;242m"
    # Up, in the right place, and not yet pickable out by eye. Between
    # sunset and full dark the fade threshold admits almost nothing, so the
    # chart used to be an empty grid for the best part of two hours. Drawn
    # in this instead, the field arrives whole at sunset and lights up star
    # by star as the sky darkens -- nothing moves, nothing pops in, only the
    # colour changes.
    #
    # 237 (#3a3a3a) on the xterm greyscale ramp, where each step is +10 on
    # all three channels. Two steps under HOR (239) so a field of these
    # cannot be mistaken for the horizon rule, and three clear of the
    # background dots at 234 so it still reads as something rather than as
    # empty sky. It was 241 first, which was legible but not obviously
    # *unlit* -- the whole effect is the contrast against a lit star at
    # 252-255, and that wants most of the ramp between them.
    UNLIT = "\033[38;5;237m"
    PLANET = "\033[38;5;180m"
    MOON = "\033[38;5;253m"
    # Aircraft. Pale steel blue, and chosen to be none of the others: an
    # aircraft is the only thing on this chart that is not astronomical, and
    # the failure that matters is somebody taking one for a planet and going
    # to look it up. Clear of blue-white stars (117), planets (180), deep sky
    # (120), constellation names (104) and the ISS (48).
    PLANE = "\033[38;5;110m"
    # An aircraft whose route could not be resolved. Grey rather than a
    # duller blue: the difference between "I know where this one is going"
    # and "I do not" should be legible at a glance and not a shade nobody
    # can name. Charters, ferry legs and general aviation land here, and
    # they are exactly the ones with no schedule to look up.
    PLANE_DIM = "\033[38;5;245m"
    DSO = "\033[38;5;120m"      # deep-sky objects -- green, so they read
                                # apart from purple constellation names and
                                # white stars/Moon at a glance

# star colour by B-V index
def star_colour(ci):
    if ci is None:            return "\033[38;5;252m"
    if ci < -0.05:            return "\033[38;5;117m"   # blue-white
    if ci < 0.30:             return "\033[38;5;255m"   # white
    if ci < 0.60:             return "\033[38;5;230m"   # pale yellow
    if ci < 1.00:             return "\033[38;5;222m"   # yellow
    return "\033[38;5;216m"                              # orange-red


# Eight directions, starting at screen-right and going anticlockwise, which
# is what atan2 hands back. JetBrains Mono carries all eight, so the PNG
# export needs no special case -- unlike braille, and unlike the aircraft
# glyph the sphere uses, which is in neither bundled font.
PLANE_ARROWS = ("\u2192", "\u2197", "\u2191", "\u2196",
                "\u2190", "\u2199", "\u2193", "\u2198")


def plane_arrow(dx, dy):
    """The arrow for a movement of (dx, dy) *cells on the chart*.

    Cells, not degrees, and certainly not the compass track. An aircraft
    flying due north twenty kilometres to your east does not climb the
    panorama northwards, it slides across it, and only the change in its
    position on the drawing knows that. dy is positive downward, because
    that is how rows run.
    """
    if not dx and not dy:
        return None
    ang = math.atan2(-dy, dx)
    return PLANE_ARROWS[int(round(ang / (math.pi / 4))) % 8]


def plane_tip(p):
    """What hovering an aircraft's callsign says, or None.

    Full airport names rather than the three-letter codes on the sphere: a
    tooltip is read once, deliberately, with a pointer already on the word,
    so there is room for "London Heathrow Airport" and no reason to make
    somebody decode LHR.

    "likely", every time. ADS-B broadcasts no destination -- the aircraft
    sends a callsign and the route is matched against a schedule afterwards,
    which misses charters, ferry legs and anything unscheduled. A reader
    standing outside cannot check it, so the hedge is the whole difference
    between a good feature and a confident lie.
    """
    r = (p or {}).get("route")
    if not r:
        return None
    ends = r.get("names") or r.get("codes")
    if not ends or len(ends) != 2 or not all(ends):
        return None
    return f"likely {ends[0]} \u2192 {ends[1]}"


def paint(s, c, on=True):
    return f"{c}{s}{C.OFF}" if on else s


# Markers for a linked run of cells, in the C0 range so nothing a chart draws
# can collide with them. The chart is a character grid painted one cell at a
# time, so by the time it is a string a label like "PERSEIDS" is eight
# separate colour spans and there is nothing left to recognise -- these are
# put down while the row is assembled, when the label's extent is still
# known, and api.ansi_to_html turns them into an anchor.
#
# Only ever emitted when a caller asks for links. A terminal never sees one.
#
# \x11..\x13 and not \x01..\x03: api's layout slots are "\x00\x01\x00" through
# "\x00\x05\x00", so the low three would have matched inside every one of
# them and torn a ZENITH_SLOT in half on its way to the browser.
LINK_START, LINK_SEP, LINK_END = "\x11", "\x12", "\x13"

# A tooltip, carried inside the same head as the href and separated from it
# by this. Deliberately inside: _LINK_HREF strips everything between
# LINK_START and LINK_SEP, so a terminal cannot see a tooltip any more than
# it can see a URL, without that rule needing to learn about this one.
#
# A label may have a tooltip and no href -- an aircraft's route is worth
# reading and there is nothing to click through to -- in which case the head
# is empty before the separator and api emits a span rather than an anchor.
LINK_TIP = "\x14"


# ---------------------------------------------------------------- time
def julian(d):
    y, m = d.year, d.month
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    day = d.day + (d.hour + d.minute / 60 + d.second / 3600) / 24
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5

def gmst_hours(jd):
    t = (jd - 2451545.0) / 36525.0
    g = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t
    return (g % 360) / 15.0


# ---------------------------------------------------------------- frames
def precess(ra_h, dec_d, jd):
    """J2000 -> date. Removes the ~0.4 deg systematic; cheap rigorous-enough form."""
    T = (jd - 2451545.0) / 36525.0
    m = (3.07496 + 0.00186 * T) / 3600 * 15      # deg per year in RA
    n_ra = (1.33621 - 0.00057 * T) / 3600 * 15
    n_dec = (20.0431 - 0.0085 * T) / 3600
    yrs = T * 100
    ra, dec = ra_h * 15 * D, dec_d * D
    dra = (m + n_ra * math.sin(ra) * math.tan(dec)) * yrs
    ddec = (n_dec * math.cos(ra)) * yrs
    return (ra_h + dra / 15) % 24, dec_d + ddec

# The Milky Way, as a density grid (build_milkyway.py). Five nested
# brightness contours baked to half-degree cells, so drawing it is a lookup
# rather than a point-in-polygon test against thousands of edges.
#
# The ramp is the band's whole vocabulary. Deliberately dim: this sits in the
# soft layer, under everything, and its job is to be the thing stars are seen
# against rather than to compete with them.
MW_RAMP = " .:*#@"
MW_COLS = ["", "\033[38;5;236m", "\033[38;5;238m", "\033[38;5;60m",
           "\033[38;5;61m", "\033[38;5;103m"]


def mw_colour(level, floor):
    """The colour a contour is drawn in, dimmed for the sky it is under.

    Without this a light-polluted site came out *brighter* than a dark one:
    a high floor leaves only the inner contours, and those carry the top of
    the ramp, so the worse the sky the more vividly the little that survived
    was painted. Shifting the ramp down by the floor puts that right -- the
    same patch of sky is dimmer from a worse place, which is the whole point
    of knowing the Bortle number."""
    return MW_COLS[max(1, level - (int(floor) - 1))]


def milkyway_at(ra_h, dec_d):
    """Brightness 0 (nothing) to 5 (the core) at a J2000 position."""
    g = _load("milkyway.json")
    row = int((90.0 - dec_d) / g["dec_step"])
    if row < 0 or row >= g["rows"]:
        return 0
    col = int((ra_h * 15.0 % 360.0) / g["ra_step"]) % g["cols"]
    return ord(g["rows_data"][row][col]) - 48


def radec_from_altaz(alt, az, lat, lst_h):
    """alt/az -> RA hours, Dec. The exact inverse of altaz() below, needed
    because the Milky Way is a property of the sky rather than of an object:
    there is nothing to place, only a question to ask once per cell."""
    a, z, la = alt * D, az * D, lat * D
    sd = math.sin(a) * math.sin(la) + math.cos(a) * math.cos(la) * math.cos(z)
    dec = math.asin(max(-1, min(1, sd)))
    y = -math.sin(z) * math.cos(a)
    x = (math.sin(a) - math.sin(dec) * math.sin(la)) / max(math.cos(la), 1e-9)
    return (lst_h - math.atan2(y, x) / D / 15.0) % 24, dec / D


def unprecess(ra_h, dec_d, jd):
    """Date -> J2000, the way back from precess().

    The grid is J2000, like the star catalogue, but a chart works in
    coordinates of date. Mirroring the epoch about J2000 negates the elapsed
    years, which is the term that does the work -- the rate coefficients
    barely move over the decades this covers."""
    return precess(ra_h, dec_d, 2 * 2451545.0 - jd)


def altaz(ra_h, dec_d, lat, lst_h):
    """RA (hours), Dec (deg) -> altitude, azimuth (deg, az from N through E)."""
    ha = (lst_h - ra_h) * 15 * D
    dec, la = dec_d * D, lat * D
    sin_alt = math.sin(dec) * math.sin(la) + math.cos(dec) * math.cos(la) * math.cos(ha)
    alt = math.asin(max(-1, min(1, sin_alt)))
    az = math.atan2(-math.cos(dec) * math.sin(ha),
                    math.sin(dec) * math.cos(la) - math.cos(dec) * math.sin(la) * math.cos(ha))
    return alt / D, (az / D) % 360

def ecl_to_eq(lon, lat_ec, jd):
    eps = (23.439291 - 0.0000004 * (jd - 2451545.0)) * D
    lo, la = lon * D, lat_ec * D
    x = math.cos(la) * math.cos(lo)
    y = math.cos(eps) * math.cos(la) * math.sin(lo) - math.sin(eps) * math.sin(la)
    z = math.sin(eps) * math.cos(la) * math.sin(lo) + math.cos(eps) * math.sin(la)
    ra = math.atan2(y, x) / D / 15 % 24
    dec = math.asin(max(-1, min(1, z))) / D
    return ra, dec


# ---------------------------------------------------------------- sun & moon
def sun(jd):
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = ((357.528 + 0.9856003 * n) % 360) * D
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    ra, dec = ecl_to_eq(lam % 360, 0.0, jd)
    return dict(name="Sun", ra=ra, dec=dec, elon=lam % 360, mag=-26.7)

def moon(jd):
    T = (jd - 2451545.0) / 36525.0
    Lp = (218.316 + 481267.8813 * T) % 360
    M  = ((134.963 + 477198.8676 * T) % 360) * D      # moon anomaly
    Ms = ((357.529 + 35999.0503 * T) % 360) * D       # sun anomaly
    Dd = ((297.850 + 445267.1115 * T) % 360) * D      # elongation
    F  = ((93.272 + 483202.0175 * T) % 360) * D       # arg. latitude
    lon = (Lp + 6.289 * math.sin(M) + 1.274 * math.sin(2 * Dd - M)
           + 0.658 * math.sin(2 * Dd) + 0.214 * math.sin(2 * M)
           - 0.186 * math.sin(Ms) - 0.114 * math.sin(2 * F)) % 360
    lat = (5.128 * math.sin(F) + 0.281 * math.sin(M + F) - 0.278 * math.sin(F - M)
           - 0.173 * math.sin(F - 2 * Dd) + 0.055 * math.sin(2 * Dd - M + F)
           - 0.046 * math.sin(2 * Dd - M - F) + 0.033 * math.sin(2 * Dd + F))
    ra, dec = ecl_to_eq(lon, lat, jd)
    s = sun(jd)
    age = (lon - s["elon"]) % 360                     # 0 new, 180 full
    illum = (1 - math.cos(age * D)) / 2
    return dict(name="Moon", ra=ra, dec=dec, elon=lon, age=age, illum=illum, mag=-12.7)

PHASES = [(0, "new"), (45, "waxing crescent"), (90, "first quarter"),
          (135, "waxing gibbous"), (180, "full"), (225, "waning gibbous"),
          (270, "last quarter"), (315, "waning crescent"), (360, "new")]

def phase_name(age):
    best = min(PHASES, key=lambda p: min(abs(age - p[0]), 360 - abs(age - p[0])))
    return best[1]

def moon_glyph(age, lat=0.0):
    """Phase glyph for the given elongation (0-360 deg from the Sun).

    The two true quarter moons (age ~90 waxing, ~270 waning) get the real
    left/right-lit Unicode circle halves -- U+25D0/25D1 are the one pair
    that actually mirrors correctly, so waxing and waning no longer look
    identical there. For a northern-hemisphere observer waxing is lit on
    the right, waning on the left; southern-hemisphere observers see the
    opposite, so lat flips which glyph goes where.

    Crescent and gibbous stay symmetric either side of full (same glyph
    waxing and waning) -- Unicode's geometric-shapes block only defines an
    upper-right quadrant and its complement, not a matching mirrored pair,
    so there's no single character to flip there without a lopsided
    approximation."""
    i = int(((age % 360) / 45) + 0.5) % 8
    glyphs = ["○", "◔", "◑", "◕", "●", "◕", "◐", "◔"]   # i=2 waxing, i=6 waning
    if lat < 0:
        glyphs[2], glyphs[6] = glyphs[6], glyphs[2]
    return glyphs[i]


# ---------------------------------------------------------------- planets
# JPL "Approximate Positions of the Planets" (Standish). a, e, I, L, wbar, Omega
# and per-century rates. Valid 1800-2050 to a few arcminutes.
PLANETS = {
 "Mercury": ([0.38709927,0.20563593,7.00497902,252.25032350,77.45779628,48.33076593],
             [0.00000037,0.00001906,-0.00594749,149472.67411175,0.16047689,-0.12534081], -0.36),
 "Venus":   ([0.72333566,0.00677672,3.39467605,181.97909950,131.60246718,76.67984255],
             [0.00000390,-0.00004107,-0.00078890,58517.81538729,0.00268329,-0.27769418], -4.34),
 "Earth":   ([1.00000261,0.01671123,-0.00001531,100.46457166,102.93768193,0.0],
             [0.00000562,-0.00004392,-0.01294668,35999.37244981,0.32327364,0.0], 0.0),
 "Mars":    ([1.52371034,0.09339410,1.84969142,-4.55343205,-23.94362959,49.55953891],
             [0.00001847,0.00007882,-0.00813131,19140.30268499,0.44441088,-0.29257343], -1.51),
 "Jupiter": ([5.20288700,0.04838624,1.30439695,34.39644051,14.72847983,100.47390909],
             [-0.00011607,-0.00013253,-0.00183714,3034.74612775,0.21252668,0.20469106], -9.40),
 "Saturn":  ([9.53667594,0.05386179,2.48599187,49.95424423,92.59887831,113.66242448],
             [-0.00125060,-0.00050991,0.00193609,1222.49362201,-0.41897216,-0.28867794], -8.88),
 "Uranus":  ([19.18916464,0.04725744,0.77263783,313.23810451,170.95427630,74.01692503],
             [-0.00196176,-0.00004397,-0.00242939,428.48202785,0.40805281,0.04240589], -7.19),
 "Neptune": ([30.06992276,0.00859048,1.77004347,-55.12002969,44.96476227,131.78422574],
             [0.00026291,0.00005105,0.00035372,218.45945325,-0.32241464,-0.00508664], -6.87),
}

def heliocentric(name, jd):
    (a0,e0,I0,L0,w0,O0), (da,de,dI,dL,dw,dO), _ = PLANETS[name]
    T = (jd - 2451545.0) / 36525.0
    a, e = a0 + da*T, e0 + de*T
    I, L = (I0 + dI*T), (L0 + dL*T)
    wbar, Om = w0 + dw*T, O0 + dO*T
    w = wbar - Om
    M = ((L - wbar + 180) % 360) - 180
    E = M
    for _ in range(12):                      # Kepler, Newton-Raphson
        E -= (E - (e/D) * math.sin(E*D) - M) / (1 - e * math.cos(E*D))
    xp = a * (math.cos(E*D) - e)
    yp = a * math.sqrt(1 - e*e) * math.sin(E*D)
    cw, sw = math.cos(w*D), math.sin(w*D)
    cO, sO = math.cos(Om*D), math.sin(Om*D)
    cI, sI = math.cos(I*D), math.sin(I*D)
    x = (cw*cO - sw*sO*cI)*xp + (-sw*cO - cw*sO*cI)*yp
    y = (cw*sO + sw*cO*cI)*xp + (-sw*sO + cw*cO*cI)*yp
    z = (sw*sI)*xp + (cw*sI)*yp
    return x, y, z

def planet(name, jd):
    x, y, z = heliocentric(name, jd)
    ex, ey, ez = heliocentric("Earth", jd)
    gx, gy, gz = x - ex, y - ey, z - ez
    lon = math.atan2(gy, gx) / D % 360
    lat = math.atan2(gz, math.hypot(gx, gy)) / D
    ra, dec = ecl_to_eq(lon, lat, jd)
    r = math.sqrt(x*x + y*y + z*z)           # heliocentric distance
    dist = math.sqrt(gx*gx + gy*gy + gz*gz)  # geocentric distance
    R = math.sqrt(ex*ex + ey*ey + ez*ez)     # Earth heliocentric distance
    # phase angle Sun-planet-Earth; without it Venus reads several magnitudes
    # too bright near closest approach, when it is really a thin crescent
    ci = (r*r + dist*dist - R*R) / (2 * r * dist)
    i = math.degrees(math.acos(max(-1.0, min(1.0, ci))))
    H = PLANETS[name][2]
    dV = {                                    # Meeus, Astronomical Algorithms ch.41
        "Mercury": 0.0380*i - 0.000273*i*i + 2.0e-6*i**3,
        "Venus":   0.0009*i + 0.000239*i*i - 6.5e-7*i**3,
        "Mars":    0.016*i,
        "Jupiter": 0.005*i,
        "Saturn":  0.044*abs(i),
    }.get(name, 0.0)
    mag = H + 5 * math.log10(max(r * dist, 1e-6)) + dV
    return dict(name=name, ra=ra, dec=dec, mag=mag, dist=dist, elon=lon, phase=i)


# ---------------------------------------------------------------- projection
def project(alt, az):
    """Equidistant azimuthal from the zenith. x,y in the unit disc; horizon = 1.
    East appears left, because you are looking up, not down at a map."""
    r = (90 - alt) / 90.0
    return -math.sin(az * D) * r, math.cos(az * D) * r


# ---------------------------------------------------------------- render
GLYPH = [(0.8, "●"), (1.8, "•"), (3.0, "•"), (4.2, "·"), (99, "·")]

def glyph_for(mag):
    for lim, g in GLYPH:
        if mag < lim:
            return g
    return "·"

# ------------------------------------------------------------- deep sky
# deepsky.json: Revised NGC (public domain, see build_deepsky.py),
# galaxies/clusters/nebulae to mag 11. One glyph+colour per category, kept
# off the star glyphs and moon-phase glyphs above so nothing collides.
DSO_GLYPH = {
    "gal": ("✺", C.DSO),              # galaxy -- green (too close to purple
                                       # constellation names otherwise)
    "clu": ("⁂", "\033[38;5;221m"),   # open/globular cluster -- gold
    "neb": ("✳", "\033[38;5;211m"),   # nebula -- pink
    "pln": ("◈", "\033[38;5;51m"),    # planetary nebula -- cyan
}
DSO_NAMES = {"gal": "galaxy", "clu": "cluster", "neb": "nebula", "pln": "planetary nebula"}

# The crosshair colour, used by the panorama and by the zenith inset, so the
# mark reads the same wherever the thing being looked for happens to be.
TARGET_C = "\033[38;5;213m"
DSO_LEGEND = ("deep sky:  " +
              "  ".join(f"{DSO_GLYPH[k][0]} {DSO_NAMES[k]}" for k in DSO_NAMES))

# The 88 IAU constellation abbreviations -- stars.json's "c" field -- mapped
# to their full names. Fixed since 1930, same "published astronomical fact"
# reasoning as COMMON_NAMES in build_deepsky.py.
CONSTELLATION_NAMES = {
    "And": "Andromeda", "Ant": "Antlia", "Aps": "Apus", "Aqr": "Aquarius",
    "Aql": "Aquila", "Ara": "Ara", "Ari": "Aries", "Aur": "Auriga",
    "Boo": "Bootes", "Cae": "Caelum", "Cam": "Camelopardalis", "Cnc": "Cancer",
    "CVn": "Canes Venatici", "CMa": "Canis Major", "CMi": "Canis Minor",
    "Cap": "Capricornus", "Car": "Carina", "Cas": "Cassiopeia",
    "Cen": "Centaurus", "Cep": "Cepheus", "Cet": "Cetus", "Cha": "Chamaeleon",
    "Cir": "Circinus", "Col": "Columba", "Com": "Coma Berenices",
    "CrA": "Corona Australis", "CrB": "Corona Borealis", "Crv": "Corvus",
    "Crt": "Crater", "Cru": "Crux", "Cyg": "Cygnus", "Del": "Delphinus",
    "Dor": "Dorado", "Dra": "Draco", "Equ": "Equuleus", "Eri": "Eridanus",
    "For": "Fornax", "Gem": "Gemini", "Gru": "Grus", "Her": "Hercules",
    "Hor": "Horologium", "Hya": "Hydra", "Hyi": "Hydrus", "Ind": "Indus",
    "Lac": "Lacerta", "Leo": "Leo", "LMi": "Leo Minor", "Lep": "Lepus",
    "Lib": "Libra", "Lup": "Lupus", "Lyn": "Lynx", "Lyr": "Lyra",
    "Men": "Mensa", "Mic": "Microscopium", "Mon": "Monoceros", "Mus": "Musca",
    "Nor": "Norma", "Oct": "Octans", "Oph": "Ophiuchus", "Ori": "Orion",
    "Pav": "Pavo", "Peg": "Pegasus", "Per": "Perseus", "Phe": "Phoenix",
    "Pic": "Pictor", "Psc": "Pisces", "PsA": "Piscis Austrinus",
    "Pup": "Puppis", "Pyx": "Pyxis", "Ret": "Reticulum", "Sge": "Sagitta",
    "Sgr": "Sagittarius", "Sco": "Scorpius", "Scl": "Sculptor", "Sct": "Scutum",
    "Ser": "Serpens", "Sex": "Sextans", "Tau": "Taurus", "Tel": "Telescopium",
    "Tri": "Triangulum", "TrA": "Triangulum Australe", "Tuc": "Tucana",
    "UMa": "Ursa Major", "UMi": "Ursa Minor", "Vel": "Vela", "Vir": "Virgo",
    "Vol": "Volans", "Vul": "Vulpecula",
}

def deepsky_visible(dso_limit, jd, lat, lst, above_horizon=True):
    """Deep-sky objects brighter than dso_limit (and, by default, above the
    horizon). dso_limit=None means the layer is off (the default -- most of
    these need binoculars, so they only show up when asked for).
    above_horizon=False is for the 3D sphere view's "full sphere" mode,
    which also shows what's below the horizon -- the far side of the sky,
    night for someone even when it's day here."""
    if dso_limit is None:
        return []
    out = []
    for o in _load("deepsky.json"):
        if o["m"] > dso_limit:
            continue
        ra, de = precess(o["ra"], o["de"], jd)
        a, z = altaz(ra, de, lat, lst)
        if a > 0 or not above_horizon:
            out.append((o, a, z))
    return out

def stars_visible(mag_limit, jd, lat, lst, above_horizon=True):
    """Stars brighter than mag_limit (and, by default, above the horizon),
    same filter as the star loop inside render() (kept separate so a data
    consumer -- the 3D sphere view -- doesn't have to draw ASCII to get
    positions). See deepsky_visible for what above_horizon=False means."""
    out = []
    for s in _load("stars.json"):
        if s["m"] > mag_limit:
            continue
        ra, de = precess(s["ra"], s["de"], jd)
        a, z = altaz(ra, de, lat, lst)
        if a > 0 or not above_horizon:
            out.append((s, a, z))
    return out

def asterism_lines_visible(jd, lat, lst, above_horizon=True):
    """Constellation line segments (by default, above the horizon), as
    (alt, az) point pairs -- the geometry half of render()'s
    constellation-lines block, without the ASCII-projection parts
    (project(), the on-screen-length guard, character-angle bucketing) that
    only matter when drawing glyphs into a flat grid. See deepsky_visible
    for what above_horizon=False means."""
    cpos = {t["hr"]: [t["ra"], t["de"]] for t in _load("stars.json")}
    out = []
    for con in _load("asterisms.json"):
        alts = []
        for poly in con["lines"]:
            for hip in poly:
                if hip in cpos:
                    ra, dec = cpos[hip]
                    ra, dec = precess(ra, dec, jd)
                    alts.append(altaz(ra, dec, lat, lst)[0])
        if above_horizon and (not alts or sum(1 for a in alts if a > 12) < 0.85 * len(alts)):
            continue                      # mostly below or grazing the horizon
        segments = []
        for poly in con["lines"]:
            pts = []
            for hip in poly:
                if hip not in cpos:
                    pts.append(None); continue
                ra, dec = cpos[hip]
                ra, dec = precess(ra, dec, jd)
                a, z = altaz(ra, dec, lat, lst)
                pts.append((a, z) if (a > 0 or not above_horizon) else None)
            for p, q in zip(pts, pts[1:]):
                if p and q:
                    segments.append([list(p), list(q)])
        if segments:
            out.append({"name": con["name"], "segments": segments})
    return out


# ---------------------------------------------------------------- text read
def sky_read(st, place, when_local, tzname, lat=0.0, wrap_width=76):
    mo, su = st["moon"], st["sun"]
    L = []
    L.append(f"{place} · {when_local:%a %d %b %Y %H:%M} {tzname}")
    if su["alt"] > 0:
        sky = "daylight, the sun is up"
    elif su["alt"] > -6:
        sky = "civil twilight"
    elif su["alt"] > -12:
        sky = "nautical twilight"
    elif su["alt"] > -18:
        sky = "astronomical twilight"
    else:
        sky = "full dark"
    L.append(f"{sky}. Sun {su['alt']:+.0f}° altitude.")
    mvis = "up" if mo["alt"] > 0 else "below the horizon"
    L.append(f"Moon {moon_glyph(mo['age'], lat)} {phase_name(mo['age'])}, "
             f"{mo['illum']*100:.0f}% lit, {mvis}"
             + (f" at {mo['alt']:.0f}° in the {compass(mo['az'])}." if mo["alt"] > 0 else "."))
    pl = [b for b in st["up"] if b["name"] not in ("Sun", "Moon")]
    pl.sort(key=lambda b: b["mag"])
    naked = [p for p in pl if p["mag"] < 6.0]
    if naked:
        L.append("Planets up: " + ", ".join(
            f"{p['name']} ({p['alt']:.0f}° {compass(p['az'])}, mag {p['mag']:.1f})" for p in naked) + ".")
    else:
        L.append("No naked-eye planets above the horizon.")
    bright = sorted(st["visible"], key=lambda v: v[0]["m"])[:4]
    if bright:
        L.append("Brightest stars: " + ", ".join(
            f"{s['n'] or s.get('b') or '?'} ({a:.0f}° {compass(z)})" for s, a, z in bright if s.get("n")) + ".")
    L.append(f"{len(st['visible'])} stars above the horizon.")
    import textwrap
    out = []
    for p in L:
        out.extend(textwrap.wrap(p, wrap_width) or [""])
    return "\n".join(out)

def compass(az):
    return ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW",
            "W","WNW","NW","NNW"][int((az % 360) / 22.5 + 0.5) % 16]


# ---------------------------------------------------------------- cities
CITIES = {
 "zurich": ("Zürich", 47.3769, 8.5417, 2), "london": ("London", 51.5072, -0.1276, 1),
 "paris": ("Paris", 48.8566, 2.3522, 2),   "newyork": ("New York", 40.7128, -74.0060, -4),
 "tokyo": ("Tokyo", 35.6762, 139.6503, 9), "sydney": ("Sydney", -33.8688, 151.2093, 10),
 "nairobi": ("Nairobi", -1.2921, 36.8219, 3), "reykjavik": ("Reykjavík", 64.1466, -21.9426, 0),
 "santiago": ("Santiago", -33.4489, -70.6693, -4),
}



# ---------------------------------------------------------------- satellites
def iss_track(tle_path, when_utc, lat, lon, minutes=110, step=0.5):
    """Propagate a TLE with SGP4 and return the next visible pass as
    [(minutes_from_start, alt, az)]. A pass counts when the satellite is above
    10 deg, sunlit, and the observer is in darkness."""
    try:
        from sgp4.api import Satrec, jday
    except ImportError:
        return None, "sgp4 not installed"
    try:
        lines = [l.strip() for l in open(tle_path) if l.strip()]
        l1, l2 = [l for l in lines if l.startswith(("1 ", "2 "))][:2]
        sat = Satrec.twoline2rv(l1, l2)
    except Exception as e:
        return None, f"no TLE ({e})"

    R = 6378.137
    def observer_eci(t):
        jd = julian(t)
        gst = gmst_hours(jd) * 15 * D
        th = gst + lon * D
        c = math.cos(lat * D)
        return R * c * math.cos(th), R * c * math.sin(th), R * math.sin(lat * D), gst

    track, best = [], []
    n = int(minutes / step)
    for i in range(n):
        t = when_utc + dt.timedelta(minutes=i * step)
        jd_, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        e, r, _v = sat.sgp4(jd_, fr)
        if e != 0:
            continue
        ox, oy, oz, gst = observer_eci(t)
        # TEME -> ECEF-ish rotation by GST, good to well under a pixel here
        sx, sy, sz = r[0] * 1.0, r[1] * 1.0, r[2] * 1.0
        dx, dy, dz = sx - ox, sy - oy, sz - oz
        # local ENU
        slat, clat = math.sin(lat * D), math.cos(lat * D)
        th = gst + lon * D
        sth, cth = math.sin(th), math.cos(th)
        up = (clat * cth, clat * sth, slat)
        east = (-sth, cth, 0.0)
        north = (-slat * cth, -slat * sth, clat)
        de = dx*east[0] + dy*east[1] + dz*east[2]
        dn = dx*north[0] + dy*north[1] + dz*north[2]
        du = dx*up[0] + dy*up[1] + dz*up[2]
        rng = math.sqrt(de*de + dn*dn + du*du)
        alt = math.degrees(math.asin(du / rng))
        az = math.degrees(math.atan2(de, dn)) % 360
        # sunlit? shadow cylinder test against the Sun direction
        jd = julian(t)
        su = sun(jd)
        sra, sdec = su["ra"] * 15 * D, su["dec"] * D
        sv = (math.cos(sdec) * math.cos(sra), math.cos(sdec) * math.sin(sra), math.sin(sdec))
        dot = sx*sv[0] + sy*sv[1] + sz*sv[2]
        perp = math.sqrt(max(sx*sx + sy*sy + sz*sz - dot*dot, 0))
        sunlit = dot > 0 or perp > R
        # is the observer's own sky dark enough to see something this bright?
        # the ISS peaks around Venus-ish brightness, so borrow that threshold.
        lst = (gmst_hours(jd) + lon / 15.0) % 24
        obs_sun_alt, _ = altaz(su["ra"], su["dec"], lat, lst)
        if alt > 10 and sunlit and dark_enough(obs_sun_alt, -3.5):
            track.append((i * step, alt, az))
        elif track:
            best = best or track
            track = []
    best = best or track
    return (best or None), None


def zenith_xy(alt, az, alt_max, lat=0.0):
    """Where an (alt, az) falls on the zenith disc, in -1..1 either way.

    Pulled out of _zenith_inset so the aircraft arrows can be worked out in
    the disc's own geometry rather than the panorama's. The two projections
    disagree completely -- the strip is linear in azimuth, the disc is polar
    and turned half a circle in the south -- so an arrow computed for one and
    drawn on the other points somewhere the aircraft is not going.
    """
    span = 90.0 - alt_max
    turn = -1.0 if lat < 0 else 1.0
    r = (90.0 - alt) / span
    return turn * -math.sin(az * D) * r, turn * math.cos(az * D) * r


def _zenith_inset(items, alt_max, color, indent, IW=21, IH=11, lat=0.0,
                  target=None, link=None):
    """Small all-sky disc for the cap the panorama cannot honestly show.
    North up and east left, as the full disc has it -- turned half a circle
    south of the equator, so north sits at the bottom and south at the top.

    Not a correction of the maths: the disc was right either way round,
    since azimuth runs from north through east everywhere. It is to agree
    with the panorama underneath it, which already centres its sweep on
    south up north and on north down south (see render_linear) because that
    is where the ecliptic rides high. With the strip centred on north and
    the disc still drawn north-up, the two put the same piece of sky on
    opposite sides, and reading from one to the other meant turning the
    picture over in your head.

    A half turn, not a mirror: (x, y) -> (-x, -y) is the same picture with
    the page rotated, which keeps east where a reader looking up will find
    it. Mirroring would swap east and west and quietly make it wrong."""
    g = [[" "] * IW for _ in range(IH)]
    t = [[None] * IW for _ in range(IH)]
    cx, cy = (IW - 1) / 2, (IH - 1) / 2
    span = 90.0 - alt_max
    turn = -1.0 if lat < 0 else 1.0

    def put(x, y, ch, col, over=False):
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        if 0 <= r < IH and 0 <= c < IW and (over or g[r][c] == " "):
            g[r][c], t[r][c] = ch, col

    for i in range(500):                                  # rim = the cap altitude
        th = i * 2 * math.pi / 500
        put(math.sin(th), math.cos(th), "∙", C.HOR)
    for az, ch in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        put(turn * -math.sin(az * D), turn * math.cos(az * D), ch, C.CARD,
            over=True)
    put(0, 0, "+", "\033[38;5;238m")                       # the zenith itself

    # Anything with a name last, so it wins its cell.
    #
    # These are drawn with over=True, so the later item takes the cell -- and
    # sorted by altitude alone the Sun lost its own square to its own arc.
    # The Sun sits on the arc by definition, the arc runs a few degrees lower
    # either side of it, and lower means later: at Quito the ☀ appeared at
    # noon and one o'clock and simply vanished the rest of the time it was up
    # here, overwritten by the path it was travelling along.
    #
    # Named first within each group is still highest-first, which is the
    # order the name column beside the disc reads in.
    named = []
    for alt, az, ch, col, nm in sorted(items, key=lambda v: (bool(v[4]), -v[0])):
        x, y = zenith_xy(alt, az, alt_max, lat)
        put(x, y, ch, col, over=True)
        if nm:
            named.append((nm, col))

    # The crosshair, when the thing being looked for is inside this cap.
    #
    # The panorama stops at alt_max and marks its target there; anything
    # higher was drawn in here as an ordinary dot and marked nowhere. So a
    # find on a high object -- the Geminids radiant at 76 degrees, say --
    # produced a chart with the answer on it and nothing pointing at it.
    #
    # Drawn last so it sits over whatever shares its cell, and named first so
    # its label heads the list rather than appearing among the field stars.
    target_label = None
    if target is not None and target.get("alt", 0) > alt_max:
        r = (90.0 - target["alt"]) / span
        put(turn * -math.sin(target["az"] * D) * r,
            turn * math.cos(target["az"] * D) * r,
            "\u25ce", TARGET_C, over=True)
        # Its label goes UNDER the disc, not in the column of names beside
        # it. That column is sized by its longest entry, and a name like
        # "GEMINIDS RADIANT" widened the whole inset enough to push it out
        # across the panorama it is supposed to sit on top of.
        target_label = target["name"].upper()

    # Whatever cap the chart under it actually stopped at, not a fixed 70.
    # The inset is the rest of the sky above that chart, so on the Sun's arc
    # -- which stops wherever the Sun gets to -- it reads "zenith 58-90°".
    # :.0f because the caller's cap is a float and "zenith 58.0-90°" is not
    # something anybody writes.
    head = f"zenith {alt_max:.0f}-90°"
    lines = [" " * indent + paint(head, C.MUTE, color)]
    for r in range(IH):
        row = "".join(paint(g[r][c], t[r][c], color) if g[r][c] != " " and t[r][c]
                      else g[r][c] for c in range(IW))
        lines.append(" " * indent + row.rstrip())
    # Names under the disc, never beside it -- the same reason the target
    # label already went here. A column to the right is as wide as its
    # longest entry, so the inset's own width depended on what happened to
    # be overhead: "Andromeda Galaxy" made the whole box wider than the
    # panorama it floats on and shoved the disc left to make room. Under it,
    # the inset is IW wide whatever it is showing, and nothing moves.
    # Linked like the labels on the panorama. The inset names the same
    # things -- a planet, a bright star, a radiant -- and a reader who has
    # learnt that a name on the chart opens its page does not expect the
    # rule to stop at the top of the sky.
    for nm, col in named:
        href = link(nm) if link else None
        body = paint("  " + nm, col, color)
        if href:
            body = LINK_START + href + LINK_SEP + body + LINK_END
        lines.append(" " * indent + body)
    if target_label:
        # No glyph beside the label. The mark is already on the disc above
        # and the label carries the same colour, which is the legend.
        lines.append(" " * indent + paint("  " + target_label,
                                          TARGET_C, color))
    return lines


# ---------------------------------------------------------------- the Sun's day
def _sun_alt(jd, lat, lon):
    su = sun(jd)
    lst = (gmst_hours(jd) + lon / 15.0) % 24
    return altaz(su["ra"], su["dec"], lat, lst)


def sun_arc(day_start_utc, lat, lon, step_min=10, floor=-2.0):
    """The Sun's path across one day, sampled coarsely. 10 minutes moves it
    2.5 deg — about one cell — so a finer step buys nothing on this canvas and
    lets the response be cached for much longer."""
    pts = []
    n = int(24 * 60 / step_min)
    for i in range(n + 1):
        t = day_start_utc + dt.timedelta(minutes=i * step_min)
        a, z = _sun_alt(julian(t), lat, lon)
        if a >= floor:
            pts.append((i * step_min, a, z))
    return pts


# What "sunset" actually names: the moment the Sun's *upper limb* leaves the
# horizon, which with refraction thrown in is the centre at -0.833. The
# crossing an animation draws is longer than that instant at both ends -- it
# starts when the lower limb first touches, one solar diameter earlier.
#
# 0.533 is that diameter. It is the only extra number needed: sun_events
# already solves the far end.
SUN_DIAMETER = 0.533
SUNSET_ALT = -0.833


def sun_crossing(day_start_utc, lat, lon, rising=False, ev=None):
    """(first touch, last gleam) in UT for today's sunset or sunrise, or
    None where the Sun does not cross the horizon here today.

    The two moments the drawing spans: the limb first touching the horizon
    and the last of it going. Between them the Sun travels its own diameter,
    which takes about three minutes at Zurich and the better part of an hour
    inside the Arctic circle -- so this is solved rather than assumed, and it
    is what tells an animation which real times to put on its clock.

    Both come back in UT. Every clock this site shows is local, so whatever
    displays them has to shift them first; this returns UT because that is
    what the rest of sky.py speaks and a function returning a naive local
    time would be the trap that keeps catching this project.
    """
    ev = ev or sun_events(day_start_utc, lat, lon)
    if ev.get("polar_day") or ev.get("polar_night"):
        return None
    edge = ev.get("sunrise" if rising else "sunset")
    if edge is None:
        return None
    # The other edge is a solar diameter away in altitude. Bracket it either
    # side of the known one and bisect with the same solver sun_events uses,
    # rather than estimating from a rate that is wrong at high latitude --
    # near the poles the Sun can take an hour to cross its own width, and a
    # linear guess lands outside the bracket entirely.
    #
    # Which side to look is not the same for the two. Sunset names the last
    # gleam, so the first touch is *earlier*; sunrise names the first gleam,
    # so the disc clearing the horizon is *later*. The bracket and the order
    # of the pair both follow from that.
    span = dt.timedelta(hours=3)
    lo, hi = (edge, edge + span) if rising else (edge - span, edge)
    other = _cross(lat, lon, lo, hi, SUNSET_ALT + SUN_DIAMETER)
    if other is None:
        # No bracket, which this far north means the Sun grazes the horizon
        # without ever clearing its own width of it. Nothing to draw.
        return None
    return (edge, other) if rising else (other, edge)


def _cross(lat, lon, t0, t1, target, step=60):
    """Bisect for the moment the Sun's altitude crosses `target`."""
    a0 = _sun_alt(julian(t0), lat, lon)[0] - target
    a1 = _sun_alt(julian(t1), lat, lon)[0] - target
    if a0 * a1 > 0:
        return None
    for _ in range(28):
        mid = t0 + (t1 - t0) / 2
        am = _sun_alt(julian(mid), lat, lon)[0] - target
        if a0 * am <= 0:
            t1, a1 = mid, am
        else:
            t0, a0 = mid, am
    return t0 + (t1 - t0) / 2


# The golden hour band, in Sun altitude. Conventions differ -- some tools
# start golden hour at the horizon rather than 4 degrees below it -- so this
# is stated in the output rather than left for the reader to guess. -4/+6 is
# what PhotoPills and sunrisesunset.io use, and it is the more useful of the
# two: the warm light photographers are actually after starts before the Sun
# clears the horizon, not at it.
#
# Blue hour needs no levels of its own. It runs from civil twilight (-6) to
# the bottom of the golden band (-4), so both its edges are already computed.
GOLDEN_LO, GOLDEN_HI = -4.0, 6.0


def sun_events(day_start_utc, lat, lon):
    """Rise, transit, set and the three twilights. These do not change over a
    day, which is what makes the daytime response cheap to serve."""
    step = dt.timedelta(minutes=10)
    samples = [(day_start_utc + i * step,
                _sun_alt(julian(day_start_utc + i * step), lat, lon)[0])
               for i in range(int(24 * 6) + 1)]
    ev = {}
    for name, level, rising in (("dawn_astro", -18, True), ("dawn_nautical", -12, True),
                                ("dawn_civil", -6, True),
                                ("gold_am_start", GOLDEN_LO, True),
                                ("sunrise", -0.833, True),
                                ("gold_am_end", GOLDEN_HI, True),
                                ("gold_pm_start", GOLDEN_HI, False),
                                ("sunset", -0.833, False),
                                ("gold_pm_end", GOLDEN_LO, False),
                                ("dusk_civil", -6, False),
                                ("dusk_nautical", -12, False), ("dusk_astro", -18, False)):
        for (ta, aa), (tb, ab) in zip(samples, samples[1:]):
            up = ab > aa
            if up != rising:
                continue
            if (aa - level) * (ab - level) <= 0:
                c = _cross(lat, lon, ta, tb, level)
                if c:
                    ev[name] = c
                break
    hi = max(samples, key=lambda p: p[1])
    ev["transit"] = hi[0]
    ev["max_alt"] = hi[1]
    ev["min_alt"] = min(a for _t, a in samples)
    ev["polar_day"] = ev["min_alt"] > -0.833
    ev["polar_night"] = hi[1] < -0.833
    return ev


def sun_altaz(when_utc, lat, lon):
    """The Sun's altitude and azimuth at one moment, in degrees."""
    return _sun_alt(julian(when_utc), lat, lon)


def shadow_ratio(alt_deg):
    """How many times its own height a vertical object's shadow runs: cot(h).

    None once the Sun is at or below the horizon, where the answer is not a
    large number but no number at all -- there is no shadow to measure. The
    ratio also runs away near the horizon (9.5x at the top of the golden
    band, 57x at half a degree), which is why callers cap what they print
    rather than quoting three significant figures of something the ground's
    own slope invalidates."""
    if alt_deg <= 0:
        return None
    return 1.0 / math.tan(alt_deg * D)


def sun_bands(day_start_utc, lat, lon, ev=None):
    """Golden and blue hour, morning and evening, for one local day.

    Each band comes back as a dict with start/end times and the Sun's azimuth
    at both edges, or None if that band does not happen here today. Azimuth is
    the point: the times are in every sunrise calculator on the web, but which
    way the light comes from is what actually decides where you stand, and it
    moves tens of degrees across the year.

    `note` names the cases where "morning band, evening band" stops being the
    right shape, which is most of the year once you go far enough north or
    south. Away from the tropics the Sun does not always cross both edges of
    the band, and when it fails to, two separate windows are the wrong answer
    rather than a slightly imprecise one:

      "all_day"    the Sun never climbs past +6, so it enters the golden band
                   in the morning and leaves it in the evening without ever
                   getting above it -- one long window, in golden_am, not two
      "all_night"  the Sun never drops to -4, so the evening band opens and
                   simply never closes; golden_pm carries open_end
      "always"     neither edge is ever crossed and the Sun sits inside the
                   band all day, which is what the weeks either side of a
                   high-Arctic winter look like
      "never"      polar night; the Sun stays below -4 and there is no golden
                   hour to report at all

    Pass `ev` to reuse a sun_events() dict the caller already has; the day
    view has one and there is no reason to solve the same crossings twice."""
    ev = sun_events(day_start_utc, lat, lon) if ev is None else ev
    lo, hi = ev["min_alt"], ev["max_alt"]

    def band(t0, t1):
        if t0 is None:
            return None
        return dict(start=t0, end=t1, open_end=t1 is None,
                    az_start=sun_altaz(t0, lat, lon)[1],
                    az_end=None if t1 is None else sun_altaz(t1, lat, lon)[1],
                    minutes=None if t1 is None else round((t1 - t0).total_seconds() / 60))

    none4 = dict(blue_am=None, golden_am=None, golden_pm=None, blue_pm=None)
    if lo >= GOLDEN_LO and hi <= GOLDEN_HI:
        return dict(none4, note="always")
    if hi < GOLDEN_LO:
        return dict(none4, note="never")
    if hi <= GOLDEN_HI:
        # Up through -4 in the morning, back down through it in the evening,
        # never above +6 in between: one window, not a morning and an evening
        # one with a hole punched in the middle that never happened.
        return dict(none4, note="all_day",
                    blue_am=band(ev.get("dawn_civil"), ev.get("gold_am_start")),
                    golden_am=band(ev.get("gold_am_start"), ev.get("gold_pm_end")),
                    blue_pm=band(ev.get("gold_pm_end"), ev.get("dusk_civil")))
    if lo >= GOLDEN_LO:
        # Down through +6 in the evening and back up through it in the
        # morning without ever reaching -4. The two crossings inside one
        # local day belong to different nights, so the evening one is left
        # open rather than closed against a morning that is not its own.
        return dict(none4, note="all_night",
                    golden_am=band(ev.get("gold_am_start"), ev.get("gold_am_end")),
                    golden_pm=band(ev.get("gold_pm_start"), None))
    return dict(
        # Morning runs upward through the bands, evening back down, so the
        # blue hour's edges are the civil boundary and the golden one either
        # way round -- named by time of day rather than by which is lower.
        note=None,
        blue_am=band(ev.get("dawn_civil"), ev.get("gold_am_start")),
        golden_am=band(ev.get("gold_am_start"), ev.get("gold_am_end")),
        golden_pm=band(ev.get("gold_pm_start"), ev.get("gold_pm_end")),
        blue_pm=band(ev.get("gold_pm_end"), ev.get("dusk_civil")),
    )


# ---------------------------------------------------------------- find a thing
def angsep(a1, z1, a2, z2):
    p1, p2 = a1 * D, a2 * D
    return math.degrees(math.acos(max(-1, min(1,
        math.sin(p1) * math.sin(p2) +
        math.cos(p1) * math.cos(p2) * math.cos((z1 - z2) * D)))))


def resolve_target(name, jd, lat, lst):
    """Name -> where it is right now. Planets, Sun, Moon, named stars, asterisms."""
    q = name.strip().lower()
    # A trailing parenthetical is a label, not part of the name. The find
    # dropdown used to hand back its own display string as the query, so
    # picking the Moon searched for "Moon (last quarter)" and found nothing
    # -- fixed at the source in complete_objects(), but the bad string is
    # already in people's history and in any link they shared, and nothing
    # findable has a bracket in its real name.
    if q.endswith(")") and "(" in q:
        q = q[:q.rindex("(")].strip() or q
    for nm in ("Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune"):
        if nm.lower() == q:
            b = planet(nm, jd)
            a, z = altaz(b["ra"], b["dec"], lat, lst)
            return dict(name=nm, alt=a, az=z, mag=b["mag"], kind="planet", body=nm)
    if q in ("moon", "the moon"):
        b = moon(jd); a, z = altaz(b["ra"], b["dec"], lat, lst)
        return dict(name="Moon", alt=a, az=z, mag=-12.7, kind="moon", body="Moon",
                    age=b["age"], illum=b["illum"])
    if q == "sun":
        b = sun(jd); a, z = altaz(b["ra"], b["dec"], lat, lst)
        return dict(name="Sun", alt=a, az=z, mag=-26.7, kind="sun", body="Sun")
    for st in _load("stars.json"):
        if st.get("n") and st["n"].lower() == q:
            ra, de = precess(st["ra"], st["de"], jd)
            a, z = altaz(ra, de, lat, lst)
            return dict(name=st["n"], alt=a, az=z, mag=st["m"], kind="star",
                        ra=st["ra"], dec=st["de"])
    cpos = {t["hr"]: [t["ra"], t["de"], t["m"]]
            for t in _load("stars.json")}
    for con in _load("asterisms.json"):
            if con["name"].lower() == q:
                pts = [cpos[h] for p in con["lines"] for h in p if h in cpos]
                if not pts:
                    continue
                vx = vy = vz = 0.0
                for ra, dec, _m in pts:                 # centroid on the sphere
                    r_, d_ = ra * 15 * D, dec * D
                    vx += math.cos(d_) * math.cos(r_)
                    vy += math.cos(d_) * math.sin(r_)
                    vz += math.sin(d_)
                cra = math.degrees(math.atan2(vy, vx)) % 360 / 15.0
                cdec = math.degrees(math.atan2(vz, math.hypot(vx, vy)))
                ra_, de_ = precess(cra, cdec, jd)
                a, z = altaz(ra_, de_, lat, lst)
                return dict(name=con["name"], alt=a, az=z, mag=None, kind="asterism",
                            ra=cra, dec=cdec,
                            lead=min(m for _r, _d, m in pts),
                            faint=max(m for _r, _d, m in pts))
    # The Milky Way, anchored on the galactic centre.
    #
    # The band crosses the whole sky, so "where is it" has no single answer
    # -- but "which way do I look" does, and it is Sagittarius. The core is
    # the bright part, the part worth waiting up for, and the part that
    # decides whether tonight is any good: when it is below the horizon
    # there is still a band overhead, and it is the faint outer arm.
    #
    # Sgr A* in J2000, which is the conventional centre and within a
    # fraction of a degree of the visual brightest point.
    if q in ("milky way", "the milky way", "galactic centre",
             "galactic center", "milkyway"):
        gc_ra, gc_dec = 17.7611, -29.0078
        ra, de = precess(gc_ra, gc_dec, jd)
        a, z = altaz(ra, de, lat, lst)
        return dict(name="Milky Way", alt=a, az=z,
                    # Not a magnitude anyone quotes for a whole galaxy seen
                    # from inside it. 2.0 asks dark_enough() for the
                    # nautical-dark answer, which is the honest threshold:
                    # the band needs a properly dark sky, not merely a set
                    # Sun.
                    mag=2.0, kind="milkyway", ra=gc_ra, dec=gc_dec)

    # Meteor radiants. Only the position lives here -- showers.json is static
    # RA/Dec, so this needs no import of events.py (which imports this module;
    # the other direction would be a cycle). When a shower peaks is events.py's
    # business; where to point is this one's.
    #
    # "Perseids", "Perseid" and "Perseids radiant" all resolve, because people
    # type all three.
    for sh in _load("showers.json"):
        nm = sh["name"].lower()
        if q in (nm, nm.rstrip("s"), nm + " radiant", nm.rstrip("s") + " radiant"):
            ra, de = precess(sh["ra"], sh["dec"], jd)
            a, z = altaz(ra, de, lat, lst)
            return dict(name=sh["name"] + " radiant", alt=a, az=z,
                        # A radiant is empty sky, so there is no magnitude to
                        # give. 2.5 buys the nautical-dark answer out of
                        # dark_enough(), which is the condition shower rates
                        # are quoted under anyway.
                        mag=2.5, kind="radiant", ra=sh["ra"], dec=sh["dec"],
                        zhr=sh["zhr"])

    for o in _load("deepsky.json"):
        # o["n"] is already the best short label (Messier number, else a
        # hand-picked common name, else the NGC number itself -- see
        # build_deepsky.py) -- o["id"] (always "NGC####") is matched too so
        # the catalogue number still works once an object has a nicer name.
        names = {o["n"].lower(), o["id"].lower()}
        if o.get("cn"):
            names.add(o["cn"].lower())
        if q in names:
            ra, de = precess(o["ra"], o["de"], jd)
            a, z = altaz(ra, de, lat, lst)
            return dict(name=o.get("cn") or o["n"], alt=a, az=z, mag=o["m"],
                        kind=DSO_NAMES.get(o["t"], o["t"]), ra=o["ra"], dec=o["de"])
    return None


def fists(deg):
    f = deg / 10.0
    if f < 0.4:  return "right down on the horizon"
    if f < 0.8:  return "about half a fist up"
    n = round(f)
    return f"about {'one' if n == 1 else n} fist{'s' if n != 1 else ''} up"


def find_marker(t, visible):
    """(name, degrees away, vertical, sideways) for the bright star nearest
    the target, or None when nothing bright is near enough to help.

    Its own function because two callers need the same answer worded two
    ways -- the prose sentence under a chart and the one-line summary above
    it -- and a second implementation of "which star is nearest" is a
    second thing to get wrong."""
    ref, near = None, 12 if t["kind"] == "asterism" else 6
    for s, a, z in sorted(visible, key=lambda v: v[0]["m"]):
        if not s.get("n") or s["m"] > 2.0 or s["n"] == t["name"]:
            continue
        d = angsep(t["alt"], t["az"], a, z)
        if near < d < 45 and (ref is None or d < ref[1]):
            ref = (s["n"], d, a, z)
    if not ref:
        return None
    nm, d, a, z = ref
    # Where the TARGET sits relative to the marker, not the reverse.
    vert = ("above" if t["alt"] > a + 3 else
            "below" if t["alt"] < a - 3 else "level")
    dz = ((t["az"] - z + 180) % 360) - 180
    side = "right" if dz > 3 else "left" if dz < -3 else None
    return nm, d, vert, side


def find_text(t, visible, lat, wrap_width=76):
    L = [f"{t['name']}: {t['alt']:.0f}\u00b0 above the horizon in the {compass(t['az'])} "
         f"(bearing {t['az']:.0f}\u00b0)."]
    L.append(f"Face {compass(t['az'])} and look {fists(t['alt'])} \u2014 a closed fist at "
             f"arm's length is about 10\u00b0.")
    if t.get("mag") is not None:
        # Radiants and the Milky Way carry a sentinel magnitude that buys a
        # darkness threshold out of dark_enough(); it is not a brightness
        # and printing it as one invents a fact. Asterisms have no single
        # one to give.
        L.append(f"Magnitude {t['mag']:.1f}."
                 if t["kind"] not in ("asterism", "radiant", "milkyway") else "")
    mark = find_marker(t, visible)
    if mark:
        nm, d, vert, side = mark
        if side and vert != "level":
            rel = f"{vert} it and to the {side}"
        elif side:
            rel = f"level with it, to the {side}"
        else:
            rel = f"directly {vert} it" if vert != "level" else "right beside it"
        L.append(f"Nearest bright marker: {nm}, {d:.0f}\u00b0 away \u2014 {t['name']} is "
                 f"{rel}.")
    if t.get("kind") == "moon":
        L.append(f"Phase {moon_glyph(t['age'], lat)} {phase_name(t['age'])}, "
                 f"{t['illum']*100:.0f}% lit.")
    import textwrap
    out = []
    for p in [x for x in L if x]:
        out.extend(textwrap.wrap(p, wrap_width))
    return "\n".join(out)


# ---------------------------------------------------------------- visibility
def target_altaz(t, jd, lat, lst):
    """Where the target is at an arbitrary time, cheaply enough to scan hours."""
    if t.get("body"):
        b = (moon(jd) if t["body"] == "Moon" else
             sun(jd) if t["body"] == "Sun" else planet(t["body"], jd))
        return altaz(b["ra"], b["dec"], lat, lst)
    ra, de = precess(t["ra"], t["dec"], jd)
    return altaz(ra, de, lat, lst)


def dark_enough(sun_alt, mag):
    """How far the Sun must be down before this thing is actually pickable out."""
    m = 2.0 if mag is None else mag
    if m < -3:   return sun_alt < -1     # Venus, the Moon: fine in bright twilight
    if m < 1.0:  return sun_alt < -6     # first-magnitude: civil dusk
    if m < 3.0:  return sun_alt < -12    # nautical
    return sun_alt < -15


def visibility(t, jd, lat, lst, min_alt=8.0):
    """(ok, reason) for right now."""
    sa, _ = altaz(*[sun(jd)[k] for k in ("ra", "dec")], lat, lst)
    mag = t["mag"] if t.get("mag") is not None else t.get("faint")
    if t["kind"] == "sun":
        # Both rules below are about picking a faint thing out of a bright
        # sky, and neither is a question you can ask about the Sun. It is
        # what makes the sky bright, so dark_enough() wants it below the
        # horizon before it will call it visible -- ?find=Sun answered "not
        # visible: the sky is still too bright", then "0° from the Sun: too
        # deep in the glare", and drew nothing at all. The low-altitude
        # warning doesn't fit either: when the question is which bit of the
        # horizon to look at, being low is the reason to draw the chart, not
        # to refuse it. A partial eclipse an hour before sunset is exactly
        # that.
        return (t["alt"] > 0, "visible now" if t["alt"] > 0 else "below the horizon")
    if t["alt"] < min_alt:
        return False, ("below the horizon" if t["alt"] <= 0 else
                       "too low, under 8°, so trees and buildings will be in the way")
    if not dark_enough(sa, mag):
        return False, ("the sky is still too bright" if sa > -6
                       else "the sky is not quite dark enough for it")
    return True, "visible now"


def next_visible(t, lat, lon, start_utc, days=40, step_min=10, min_alt=12.0):
    """First moment it clears min_alt in a sky dark enough for its brightness.

    Two conditions have to hold at once -- the thing high enough, the sky
    dark enough -- and for something rising into morning twilight they are
    closing on each other, so their overlap can be minutes wide. Sampling
    every step_min from start_utc, the coarse grid either landed inside that
    overlap or stepped clean over it, and which one it did was decided by
    the minute of the hour the caller happened to ask at:

        start 16:00 -> 2026-08-27 04:00   Jupiter over Zurich, 12.20 deg
        start 16:02 -> 2026-08-26 04:02                        12.06 deg
        start 16:10 -> 2026-08-27 04:00
        start 16:12 -> 2026-08-26 04:02

    So /Zurich/jupiter answered "Wed 26 Aug" or "Thu 27 Aug" depending on
    when in the hour you opened it, and the whole page moved with it -- the
    distance, the elongation and the chart are all drawn for whatever moment
    comes back from here.

    The grid stays, because forty days at one-minute resolution is 57,600
    solar positions and this is on the request path. What changes is that it
    is no longer trusted on its own: whenever either condition differs from
    the sample before, the ten minutes between them are walked a minute at a
    time. An overlap short enough to fall between two samples has to turn at
    least one of the two conditions on inside that gap, so it cannot hide
    from this -- and a sample that does qualify walks backwards the same way,
    to report the moment the window opened rather than the first tick that
    noticed.

    Minutes, not seconds: every caller renders this as HH:MM.
    """
    mag = t["mag"] if t.get("mag") is not None else t.get("faint")
    # Asked about the Sun at night, the answer is sunrise. Left to the rules
    # below it would search forty days for a dark sky with the Sun up, find
    # none, and report the Sun as permanently lost in its own glare.
    is_sun = t["kind"] == "sun"
    if is_sun:
        min_alt = 0.0

    def at(when):
        """(dark enough, altitude, azimuth) -- the two conditions and where."""
        jd = julian(when)
        lst = (gmst_hours(jd) + lon / 15.0) % 24
        su = sun(jd)
        sa, _ = altaz(su["ra"], su["dec"], lat, lst)
        a, z = target_altaz(t, jd, lat, lst)
        return (is_sun or dark_enough(sa, mag)), a, z

    # start_utc itself is not an answer -- the caller already knows it is not
    # visible now, which is why it is asking -- but it is the left-hand end
    # of the first gap, and a window opening inside that gap is as real as
    # any other.
    p_dark, p_alt, _pz = at(start_utc)
    n = int(days * 24 * 60 / step_min)
    for i in range(1, n):
        when = start_utc + dt.timedelta(minutes=i * step_min)
        dark, a, z = at(when)
        if dark and a >= min_alt:
            # Back to the start of the window, not the tick that spotted it.
            best = (when, a, z)
            for k in range(1, step_min):
                earlier = when - dt.timedelta(minutes=k)
                if earlier <= start_utc:
                    break
                d2, a2, z2 = at(earlier)
                if not (d2 and a2 >= min_alt):
                    break
                best = (earlier, a2, z2)
            return best
        # Nothing here, but if either condition turned over inside this gap
        # the two may have overlapped in between.
        if dark != p_dark or (a >= min_alt) != (p_alt >= min_alt):
            for k in range(step_min - 1, 0, -1):
                inside = when - dt.timedelta(minutes=k)
                d2, a2, z2 = at(inside)
                if d2 and a2 >= min_alt:
                    return inside, a2, z2
        p_dark, p_alt = dark, a
    return None, None, None


def solar_elongation(t, jd, lat, lst):
    su = sun(jd)
    sa, sz = altaz(su["ra"], su["dec"], lat, lst)
    return angsep(t["alt"], t["az"], sa, sz)


# ---------------------------------------------------------------- linear view
CARDINALS = {"N":0,"NNE":22.5,"NE":45,"ENE":67.5,"E":90,"ESE":112.5,"SE":135,"SSE":157.5,
             "S":180,"SSW":202.5,"SW":225,"WSW":247.5,"W":270,"WNW":292.5,"NW":315,"NNW":337.5}

# How wide a chart anyone is allowed to ask for. ?w= comes off the query
# string, so this is a limit rather than a preference: rows are derived from
# columns, which makes the work grow with the square of this number, and
# without a ceiling one request could ask for a million cells.
#
# Named here and used everywhere, because it was three separate literals and
# a ceiling you cannot find is a ceiling nobody raises.
# 300 costs about 26ms a render against 14ms at 220, and keeps 92% of the
# Milky Way band under the asterism lines against 89%. Past that it is
# diminishing returns on a curve that is still squaring: 440 columns is 53ms
# for another two points of band.
CHART_WIDTH_MIN, CHART_WIDTH_MAX = 60, 300

# One braille character is 2 dots across and 4 down, so a chart drawn in them
# is really four times the resolution down and twice across the one the eye
# counts in characters. A terminal cell is about twice as tall as it is wide,
# which makes each dot square. motion.py draws the constellation panels from
# this same table -- one encoding, in one place, because two copies of a bit
# table drift.
BRAILLE_DOTS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
                (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}
BRAILLE_BASE = 0x2800

def _walk(cells):
    """Given the ordered cells a segment passes through, pick a glyph per cell
    from the actual step taken there. One glyph for a whole segment staircases."""
    out = []
    for i, (c, r) in enumerate(cells):
        p = cells[max(i - 1, 0)]
        n = cells[min(i + 1, len(cells) - 1)]
        dc, dr = n[0] - p[0], n[1] - p[1]
        if dc == 0 and dr == 0:
            g = "·"
        else:
            ang = math.degrees(math.atan2(-dr, dc)) % 180
            g = "─" if ang < 22.5 or ang >= 157.5 else "╱" if ang < 67.5 \
                else "│" if ang < 112.5 else "╲"
        out.append((c, r, g))
    return out


# How much of the chart's width one segment of a figure may cross before it is
# treated as the projection tearing the shape apart rather than as a real line.
# A panorama puts the whole compass on one row, so two stars a few degrees
# apart overhead can land at opposite ends of it.
MAX_SEGMENT_FRAC = 0.35


def _all_joinable(con, cpos, jd, lat, lst, joinable):
    """True when every side of this figure is one the chart can draw.

    Endpoints below the horizon are not counted against it: a constellation
    half-risen is a normal thing to draw half of, and always has been. This is
    only about sides the projection would stretch across the page.
    """
    for poly in con["lines"]:
        seen = []
        for h in poly:
            if h not in cpos:
                seen.append(None)
                continue
            ra, dec, _m = cpos[h]
            ra, dec = precess(ra, dec, jd)
            a, z = altaz(ra, dec, lat, lst)
            seen.append(z if a > 3 else None)
        for z1, z2 in zip(seen, seen[1:]):
            if z1 is not None and z2 is not None and not joinable(z1, z2):
                return False
    return True


def pick_constellations(cpos, cons, jd, lat, lst, alt_max, sectors=6, extra=2,
                        in_view=None, joinable=None):
    """Brightest figure per azimuth sector, so the sky is covered evenly instead
    of clustering wherever tonight's bright ones happen to sit.

    joinable(az1, az2) rejects a figure this projection cannot draw whole, and
    is why the Summer Triangle no longer appears as a single long line. Near
    the zenith azimuth stops meaning much: from Los Angeles in August its three
    stars are 24, 34 and 38 degrees apart on the sky and sit at azimuth 298, 45
    and 167 -- right around the compass. A panorama has to draw that as three
    runs each about a third of the chart wide, the drawing guard drops the two
    widest as wrap-around junk, and what is left is one side of a triangle with
    the triangle's name against it.

    Rejected here rather than only at drawing time so the sector it would have
    taken goes to a figure that can actually be drawn.
    """
    scored = []
    for con in cons:
        pts = [cpos[h] for poly in con["lines"] for h in poly if h in cpos]
        if not pts:
            continue
        alts, azs, flux = [], [], 0.0
        lead = min(m for _ra, _dec, m in pts)
        if lead > 2.8 and not con.get("ast"):
            continue        # no anchor star: Lynx, Camelopardalis, Leo Minor et al.
        for ra, dec, m in pts:
            ra_, dec_ = precess(ra, dec, jd)
            a, z = altaz(ra_, dec_, lat, lst)
            alts.append(a); azs.append(z)
            if a > 0:
                flux += 10 ** (-0.4 * m)
        if min(alts) < 8 or max(alts) > alt_max:
            continue
        if in_view and sum(1 for z in azs if in_view(z)) < 0.8 * len(azs):
            continue        # mostly outside the window: one stray line, no shape
        if joinable and not _all_joinable(con, cpos, jd, lat, lst, joinable):
            continue        # overhead: the projection would tear it apart
        x = sum(math.cos(z * D) for z in azs); y = sum(math.sin(z * D) for z in azs)
        caz = math.degrees(math.atan2(y, x)) % 360
        scored.append(dict(con=con, flux=flux, caz=caz,
                           calt=sum(alts) / len(alts), ast=bool(con.get("ast"))))
    scored.sort(key=lambda s: (0 if s["con"].get("ast") else 1, -s["flux"]))
    def hips(entry):
        return {h for poly in entry["con"]["lines"] for h in poly}

    chosen, used, taken = [], set(), set()
    for s in scored:                                   # one winner per sector
        hs = hips(s)
        if hs and len(hs & taken) > 0.3 * len(hs):
            continue          # already covered: don't draw Ursa Major over the Plough
        k = int(s["caz"] / (360.0 / sectors))
        if k not in used:
            used.add(k); chosen.append(s); taken |= hs
    have = {id(s["con"]) for s in chosen}
    for s in scored:                                   # then top up by brightness
        if len(chosen) >= sectors + extra:
            break
        hs = hips(s)
        if id(s["con"]) in have or (hs and len(hs & taken) > 0.3 * len(hs)):
            continue
        chosen.append(s); have.add(id(s["con"])); taken |= hs
    return chosen


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# How faint the catalogue itself goes. A crop may ask for more stars than the
# full sweep draws; it may not ask for more than exist.
CATALOGUE_FAINTEST = 5.5

# What a quadrant crop adds to whatever limit the caller asked for.
#
# A crop of the full sweep is 118x15 cells over 90° of azimuth and 23° of
# altitude, where the sweep is 176x22 over 360°x70°: 1.19 square degrees per
# cell against 6.51, so 5.5x the room per patch of sky. Star counts here go up
# about 3.15x per magnitude (518 stars to mag 4.0, 1,630 to mag 5.0), so 1.5
# magnitudes is very nearly the exact number that fills the extra room without
# leaving the crop any denser than the sweep it was cut from. A crop of a
# facing= window is tighter still (about 16x), and would take 2.4 magnitudes --
# but the catalogue runs out first either way, so both land on 5.5 and one
# constant covers both.
#
# Why a crop should be deeper at all: mag 4.0 is a readability limit, not an
# honesty one. It is where the full sweep stops because mag 4-5 is 63% of the
# field and drawing it turns most of the sky grey (see api.py's find= notes).
# A crop has the room the sweep does not. find= already does exactly this on
# its own crop, at a flat mag_limit=5.0.
#
# Added to mag_limit rather than replacing it, which is what keeps the twilight
# ramp intact: _fade_mag_limit pins daylight at -5.0, and -3.5 still draws
# nothing at all (Sirius, the brightest thing in the catalogue, is -1.46). The
# crop deepens as the sky darkens, exactly as the chart it came from does, and
# only reaches 5.5 at full dark.
QUADRANT_MAG_GAIN = 1.5


def _deepen(limit):
    """A magnitude limit as a quadrant crop should draw it, or None unchanged
    (None means "no limit" for line_limit and "no unlit pass" for dim_limit --
    neither has anything for a deeper field to add).

    Never returns a limit shallower than the one it was given: a caller that
    already asked for something past the catalogue keeps what it asked for."""
    if limit is None:
        return None
    return max(limit, min(limit + QUADRANT_MAG_GAIN, CATALOGUE_FAINTEST))

def quadrant_grid(centre, span, alt_lo, alt_hi, cols=4, rows=3):
    """Split an az/alt window into a fixed 4x3 grid, labelled A, B, C... in
    reading order (left to right, top to bottom). More, smaller cells means
    a crop zooms in further. Backs ?quadrant=: a request crops itself to one
    cell instead of the whole window, computed fresh from the same rule
    every time rather than any server-side state -- ?quadrant=A means the
    same patch of sky whichever request asks for it."""
    alt_rng = alt_hi - alt_lo
    az_w, alt_h = span / cols, alt_rng / rows
    cells = []
    i = 0
    for row in range(rows):
        for col in range(cols):
            az_lo = centre - span / 2 + col * az_w
            a_hi = alt_hi - row * alt_h
            cells.append(dict(letter=LETTERS[i], az_centre=(az_lo + az_w / 2) % 360,
                              az_span=az_w, alt_lo=a_hi - alt_h, alt_hi=a_hi))
            i += 1
    return cells


def render_linear(when_utc, lat, lon, W=176, H=22, color=True, show_lines=True,
                  mag_limit=4.0, line_limit=None, tle=None, alt_max=70, facing=None, span=None,
                  alt_lo=None, alt_hi=None, target=None, overlay=None,
                  bodies=None, inset=True, width=None, height=None, dso_limit=None,
                  quadrant=None, quadrants=False, side_panel=False,
                  alt_bands=None, notes=None, milkyway=False, dim_limit=None,
                  radiant=None, link=None, planes=None, plane_labels=True,
                  plane_tips=False):
    """Horizon panorama. facing=None gives the full 360 deg sweep; facing='SW'
    gives a window centred there, which is narrow enough to be undistorted.

    side_panel=True pulls the zenith inset out of the returned text (nothing
    appended below the sweep) and hands its lines back via st['zenith_lines']
    instead, for a caller that wants to lay it out beside the chart rather
    than under it. Default False keeps every existing caller (the CLI
    included) byte-identical.

    dim_limit draws the sky twice over. Stars down to mag_limit are lit and
    take their real colour; stars between mag_limit and dim_limit are up but
    not yet pickable out by eye, and are drawn in C.UNLIT. Asterism lines
    follow the same rule against line_limit. The point is that dim_limit is
    the limit the sky is *heading for*, so the field the chart draws at
    sunset is the field it will still be drawing at full dark -- what changes
    over those two hours is colour, not composition, and nothing pops into
    existence. st['visible'] keeps counting only the lit ones, so the star
    count above the chart stays an honest answer to "what can I see".

    None (the default) means no second pass and no unlit anything, which is
    every existing caller byte-for-byte."""
    req_span = span                    # the else-branch below clobbers `span`
    if facing is not None:
        # Rows are capped at 46 so output stays a sane height. Below ~90 deg of
        # span that cap starts stretching shapes sideways, so span is clamped to
        # the range where the aspect stays honest rather than silently lying.
        # Going narrower would need an altitude window too - a different view.
        W, H_MAX, H_MIN = 118, 46, 12
        lo = alt_max * W / (2.0 * H_MAX)
        hi = alt_max * W / (2.0 * H_MIN)
        want = float(span or 140)
        span = max(lo, min(hi, want))
        clamped = "min" if span > want + 0.5 else "max" if span < want - 0.5 else ""
        H = int(round(W * alt_max / (2 * span)))
        centre = CARDINALS.get(str(facing).upper(), None)
        if centre is None:
            centre = float(facing)
    else:
        # South is the "interesting" direction for a Northern Hemisphere
        # observer -- the ecliptic (Sun, Moon, planets) arcs highest there.
        # South of the equator that same peak is toward the North instead,
        # so the default sweep centres on whichever hemisphere's own zenith
        # crossing this is, rather than always defaulting to South.
        span, centre, clamped = 360.0, (0.0 if lat < 0 else 180.0), ""

    # Whether the CALLER cropped the altitude range, recorded before the
    # defaults below overwrite the Nones -- the zenith inset needs to know,
    # and by the time it is drawn these are always numbers.
    alt_cropped = alt_lo is not None or alt_hi is not None
    alt_lo = 0.0 if alt_lo is None else float(alt_lo)
    alt_hi = float(alt_max) if alt_hi is None else float(alt_hi)
    alt_rng = alt_hi - alt_lo

    # The limit the star COUNT is taken against, fixed here before a quadrant
    # crop deepens the drawing limits below. "N stars above the horizon" is a
    # fact about the place and the hour, not about which corner of the sky is
    # on screen, so it has to read the same whether or not a crop is applied --
    # and st['visible'] is a whole-sky list (every lit star above the horizon,
    # not only those inside the window), which feeds stars_up in the JSON and
    # the brightest-few line. Deepening this too would have taken a Geneva
    # night from "287 stars" to "1,632 stars" on nothing but a zoom.
    count_limit = mag_limit

    quad_cells, quad_error, quad_applied = [], None, None
    if quadrants and target is None:
        quad_cells = quadrant_grid(centre, span, alt_lo, alt_hi)
        if quadrant is not None:
            letter = str(quadrant).upper()
            cell = next((c for c in quad_cells if c["letter"] == letter), None)
            if cell is None:
                quad_error = letter
            else:
                quad_applied = letter
                W = 118
                centre, span = cell["az_centre"], cell["az_span"]
                alt_lo, alt_hi = cell["alt_lo"], cell["alt_hi"]
                alt_rng = alt_hi - alt_lo
                H = max(8, int(round(W * alt_rng / (2 * span))))
                clamped = ""
                quad_cells = []          # cropped -- no overlay grid on itself
                # More sky, in more detail. Until now a crop was the same 518
                # stars drawn larger, across cells that were mostly empty --
                # the one zoom in the product that promised detail and handed
                # back none. Same reasoning that already turns the deep-sky
                # layer on for a quadrant: the point of zooming in is to
                # reveal more. line_limit follows so constellation lines
                # cannot run to stars that are not drawn, and dim_limit
                # follows so the twilight sketch is the field the crop is
                # heading for rather than the sweep's.
                mag_limit = _deepen(mag_limit)
                line_limit = _deepen(line_limit)
                dim_limit = _deepen(dim_limit)

    # Frame chosen by the object itself -- but only when the caller actually
    # asked for a crop. Re-centring a 60° window on the target is the whole
    # point of a window; re-centring a full 360° sweep just rotates the sky,
    # so every cardinal and every label lands somewhere different from the
    # ordinary chart and the two stop being comparable. On a full panorama the
    # crosshair marks the spot perfectly well without moving the horizon under
    # it.
    if target is not None and alt_cropped:
        W = 118
        span = float(req_span or 60.0)
        centre = float(target["az"])
        H = max(8, int(round(W * alt_rng / (2 * span))))
        clamped = ""
    if width is not None:
        # Rescale both dimensions by the same factor so aspect stays exactly
        # what it was -- this only changes how many terminal columns the same
        # honest render is spread across, not the geometry itself.
        width = max(CHART_WIDTH_MIN, min(CHART_WIDTH_MAX, int(width)))
        scale = width / W
        W = width
        H = max(6, int(round(H * scale)))
    if height is not None:
        # Independent of width -- same alt_lo/alt_hi vertical slice, just
        # more (or fewer) rows of resolution across it, so the two axes can
        # be tuned separately (e.g. a narrower, taller GIF export) without
        # this being a different or cropped view of the sky.
        H = max(6, min(90, int(height)))
    jd = julian(when_utc)
    lst = (gmst_hours(jd) + lon / 15.0) % 24
    LM = 5
    grid = [[" "] * W for _ in range(H)]
    tint = [[None] * W for _ in range(H)]
    soft = [[False] * W for _ in range(H)]
    lock = [[False] * W for _ in range(H)]
    # row -> [(start_col, end_col, href)] for labels that have a page behind
    # them. Empty unless the caller passed link=, which only the browser does.
    anchors = {}

    def href_for(name):
        return link(name) if link and name else None
    inset_items = []                # (alt, az, glyph, colour, name|None)

    def free(r, c):
        return (grid[r][c] == " " or soft[r][c]) and not lock[r][c]

    # The float forms are what the asterism lines are drawn from: a line
    # rounded to whole cells before it is drawn is a line that staircases,
    # whatever glyph you pick for it. Everything else on the chart is a thing
    # at a place rather than a path between two, so it rounds as it always did.
    def colf_of(az):
        d = ((az - centre + 180) % 360) - 180
        if abs(d) > span / 2:
            return None
        return (d + span / 2) / span * (W - 1)

    def rowf_of(alt):
        if alt < alt_lo - 1e-9 or alt > alt_hi + 1e-9:
            return None
        return (H - 1) - (alt - alt_lo) / alt_rng * (H - 1)

    def col_of(az):
        c = colf_of(az)
        return None if c is None else int(round(c))

    def row_of(alt):
        r = rowf_of(alt)
        return None if r is None else int(round(r))

    def place(az, alt, ch, col, over=False):
        """True if the glyph actually landed.

        It often does not: lock[][] belongs to labels already written and is
        never overridden, because an arrow dropped into the middle of
        "Cassiopeia" corrupts the word. Callers that need to know -- the
        aircraft layer, which must not print a callsign beside a mark that
        was never drawn -- read the result."""
        c, r = col_of(az), row_of(alt)
        if c is None or r is None:
            return False
        if 0 <= r < H and not lock[r][c] and (over or free(r, c)):
            grid[r][c], tint[r][c], soft[r][c] = ch, col, False
            return True
        return False

    def _try(r, c, s, colr, dx, href=None, tip=None):
        start = c + dx if dx > 0 else c - len(s) + dx
        if not (0 <= r < H and 0 <= start and start + len(s) <= W):
            return False
        if any(not free(r, start + k) for k in range(len(s))):
            return False
        for k, ch in enumerate(s):
            grid[r][start + k], tint[r][start + k] = ch, colr
            soft[r][start + k], lock[r][start + k] = False, True
        if href or tip:
            # Where the label ended up, so the row assembly can wrap it. The
            # placement search tries seven rows and six offsets before it
            # settles, so this is the only point that knows.
            #
            # href and tooltip travel as one string so the assembly and the
            # strippers stay a three-tuple and never learn there are two
            # things in here.
            head = (href or "") + (LINK_TIP + tip if tip else "")
            anchors.setdefault(r, []).append((start, start + len(s), head))
        return True

    def text(az, alt, s, colr, href=None, tip=None):
        c, r = col_of(az), row_of(alt)
        if c is None or r is None:
            return False
        for dr in (0, -1, 1, -2, 2, -3, 3):
            for dx in (2, -2, 5, -5, 9, -9):
                if _try(r + dr, c, s, colr, dx, href, tip):
                    return True
        return False

    for a in range(int(alt_lo // 10) * 10, int(alt_hi) + 1, 10):
        r = row_of(a)
        if r is None or a <= alt_lo:
            continue
        for c in range(0, W, 6):
            if grid[r][c] == " ":
                grid[r][c], tint[r][c], soft[r][c] = "·", "\033[38;5;234m", True

    # The Milky Way. Painted after the gridline dots and before everything
    # else, into the soft layer, so every star, planet, line and label still
    # lands on top of it -- free() counts a soft cell as available, which is
    # what stops a band across the sky from costing anything its real estate.
    # It replaces the gridline dots where it covers them: a band with a hole
    # every sixth column reads as damage rather than as sky, and the altitude
    # labels down the left still carry the scale.
    #
    # One inverse transform per cell rather than one per catalogue entry.
    # The Milky Way is a property of the sky, not a list of objects, so the
    # question runs the other way round from everything else here.
    # milkyway is the faintest contour worth drawing here, or 0 for none:
    # 1 is a dark sky showing the whole band, 4 is a bad one where only the
    # core is above the light pollution, and 0 is a city where none of it
    # would be visible and drawing it would be a lie about the sky.
    if milkyway:
        floor = int(milkyway)
        for r in range(H):
            a = alt_lo + (H - 1 - r) * alt_rng / (H - 1) if H > 1 else alt_lo
            if a < -2:
                continue
            for c in range(W):
                if grid[r][c] != " " and not soft[r][c]:
                    continue
                az = (centre + (c / (W - 1) * span - span / 2)) % 360 if W > 1 else centre
                ra, de = radec_from_altaz(a, az, lat, lst)
                v = milkyway_at(*unprecess(ra, de, jd))
                if v >= floor:
                    grid[r][c], tint[r][c] = MW_RAMP[v], mw_colour(v, floor)
                    soft[r][c] = True

    # Altitude bands: a stripe of the sky called out by how high the Sun is
    # in it, drawn full width because that is what the band actually is -- a
    # range of altitudes, not a range of bearings. Soft, so the Sun's arc and
    # everything else still draws over the top. Only the part inside the
    # chart's own altitude window can show; a band that lies entirely below
    # the horizon has no rows here and the caller says so in words instead.
    row_deg = alt_rng / (H - 1) if H > 1 else alt_rng
    for bnd in alt_bands or ():
        for r in range(H):
            a = alt_lo + (H - 1 - r) * alt_rng / (H - 1)
            # Half a row of slack at each edge. A row stands for a range of
            # altitudes, not a single one, so a band whose top lands a
            # fraction of a degree under a row's nominal value still belongs
            # on it -- without this the 0-6 degree golden band lost its top
            # row to a row sitting at 6.09.
            if not (bnd["lo"] - row_deg / 2 <= a <= bnd["hi"] + row_deg / 2):
                continue
            for c in range(W):
                if grid[r][c] == " " or soft[r][c]:
                    grid[r][c], tint[r][c], soft[r][c] = bnd["ch"], bnd["col"], True

    # Free-standing text pinned to an altitude rather than to an object --
    # the band's own times, and the day view's prose, which has acres of
    # empty chart to live in and reads better beside the thing it describes
    # than in a paragraph underneath it. Nudged upward when the row it wants
    # is already occupied, so it never lands on the arc.
    for note in notes or ():
        # Padded, so the text never abuts the background gridline dots or the
        # band's own colons -- without the spaces a dot one column along
        # reads as part of the label. The padding is a nicety, not a
        # requirement: a line that fits the chart exactly keeps its text and
        # loses the spaces rather than being dropped for being two columns
        # too wide.
        s = note["text"]
        if not s:
            continue
        s = f" {s} " if len(s) + 2 <= W else s
        if len(s) > W:
            continue
        r0 = row_of(note["alt"])
        if r0 is None:
            continue
        start = 0 if note.get("align") == "left" else (W - len(s)) // 2
        start = max(0, min(W - len(s), start + note.get("indent", 0)))
        for r in range(r0, -1, -1):
            if all(free(r, start + k) for k in range(len(s))):
                for k, ch in enumerate(s):
                    grid[r][start + k], tint[r][start + k] = ch, note["col"]
                    soft[r][start + k], lock[r][start + k] = False, True
                break

    # The two thresholds everything below is drawn against: what appears at
    # all, and what appears lit. Equal unless dim_limit was asked for, which
    # is what makes the default path identical to the one that had no notion
    # of an unlit star.
    #
    # max(), not dim_limit outright: a caller that already asks for a deeper
    # field than the sky is heading for (find= draws to 5.0) must not have it
    # cut back to 4.0 by a feature about twilight.
    star_draw_limit = mag_limit if dim_limit is None else max(mag_limit, dim_limit)
    # line_limit None means "draw every line", so there is nothing for a
    # second threshold to add and the unlit pass stays off.
    line_draw_limit = (line_limit if line_limit is None or dim_limit is None
                       else max(line_limit, dim_limit))

    chosen = []
    if show_lines:
        # Asterisms only. The full IAU figure for Ursa Major is a 25-star bear
        # that nobody recognises; what people see is the 7-star Plough. These
        # line lists are hand-authored from Bayer designations (build_asterisms.py)
        # and resolved against BSC5, so no third-party line file is involved.
        cpos = {t["hr"]: [t["ra"], t["de"], t["m"]]
                for t in _load("stars.json")}
        cons = _load("asterisms.json")
        def joinable(z1, z2):
            """Whether these two stars can be joined without the line being
            stretched across the page. Outside the window is not this
            function's business -- in_view already judges those."""
            c1, c2 = col_of(z1), col_of(z2)
            if c1 is None or c2 is None:
                return True
            return abs(c2 - c1) <= W * MAX_SEGMENT_FRAC

        chosen = pick_constellations(cpos, cons, jd, lat, lst, alt_hi,
                                     sectors=6 if target is None else 3,
                                     in_view=lambda z: col_of(z) is not None,
                                     joinable=joinable)

        # Every line goes into a subpixel bitmap first and only becomes
        # characters once they are all in. Two reasons. A segment rounded to
        # whole cells before it is drawn can only ever run in the four
        # directions a box glyph has, which is what made these shapes
        # staircase; and two segments crossing the same cell merge into one
        # glyph here rather than the second overwriting the first.
        dots = [[0] * (W * 2) for _ in range(H * 4)]
        # A second bitmap for the segments that are up but not yet lit. Two
        # bitmaps rather than one with a flag per dot, because the merging is
        # the whole reason the bitmap exists: two lit segments crossing a cell
        # have to become one glyph, and so do two unlit ones, but a lit and an
        # unlit crossing must not average into some third colour. Kept apart,
        # flushed in order, lit wins the cell.
        dim_dots = [[0] * (W * 2) for _ in range(H * 4)]

        def dot_line(p, q, lit=True):
            """One segment into the bitmap. True if any of it landed."""
            grid_ = dots if lit else dim_dots
            px, py = p[0] * 2, p[1] * 4
            qx, qy = q[0] * 2, q[1] * 4
            n = int(max(abs(qx - px), abs(qy - py))) + 1
            hit = False
            for k in range(n + 1):
                t = k / n
                sx, sy = int(round(px + (qx - px) * t)), int(round(py + (qy - py) * t))
                if 0 <= sx < W * 2 and 0 <= sy < H * 4:
                    grid_[sy][sx] = 1
                    hit = True
            return hit

        for item in chosen:
            con = item["con"]
            item["visible"] = False
            for poly in con["lines"]:
                pts = []
                for hip in poly:
                    # line_limit, when set (animate frames), gates each segment
                    # endpoint by the same fading threshold as the star field
                    # itself, so lines and names fade in/out in step with the
                    # stars they connect. Ordinary requests leave it unset and
                    # keep the existing all-or-nothing show_lines behaviour.
                    #
                    # Gated on line_draw_limit, then each endpoint remembers
                    # whether it is lit: an unlit endpoint still gets a point,
                    # so the shape is complete from sunset, and it is the
                    # colour of the segment that changes as its ends come on.
                    if hip not in cpos or (line_draw_limit is not None
                                           and cpos[hip][2] > line_draw_limit):
                        pts.append(None); continue
                    ra, dec, _m = cpos[hip]
                    ra, dec = precess(ra, dec, jd)
                    a, z = altaz(ra, dec, lat, lst)
                    cc = colf_of(z)
                    rr = rowf_of(a) if cc is not None else None
                    end_lit = line_limit is None or _m <= line_limit
                    pts.append((cc, rr, end_lit) if rr is not None and a > 3 else None)
                # All of this shape or none of it. Dropping only the sides the
                # projection cannot carry leaves the ones it can, and a single
                # line with SUMMER TRIANGLE written against it is worse than
                # no triangle at all. pick_constellations has usually caught
                # this already and given the sector to something else; this is
                # the backstop for the paths that choose their own figures.
                segs = [(p, q) for p, q in zip(pts, pts[1:]) if p and q]
                if any(abs(q[0] - p[0]) > W * MAX_SEGMENT_FRAC
                       for p, q in segs):
                    continue
                for p, q in segs:
                    # Right up to the vertex, unlike the glyph version, which
                    # dropped the end cell of every segment to keep a line off
                    # its own star. A cell holds one character either way, and
                    # the stars are placed over these below.
                    #
                    # Both ends, not either: a segment running from a star you
                    # can see to one you cannot is not yet a line you could
                    # trace, so it stays unlit until the fainter end arrives.
                    seg_lit = p[2] and q[2]
                    if dot_line(p, q, lit=seg_lit) and seg_lit:
                        # Only a lit segment marks the figure visible. The
                        # name rides on this flag, and a constellation named
                        # over stars nobody can pick out yet is a caption for
                        # a picture that is not there.
                        item["visible"] = True
                # the pattern's own vertex stars, so the nodes read clearly
                for hip in poly:
                    if hip in cpos:
                        ra, dec, m = cpos[hip]
                        if line_draw_limit is not None and m > line_draw_limit:
                            continue
                        ra, dec = precess(ra, dec, jd)
                        a, z = altaz(ra, dec, lat, lst)
                        if a > 0:
                            node_lit = line_limit is None or m <= line_limit
                            place(z, a, "●" if m < 3.2 else "•",
                                  star_colour(None) if node_lit else C.UNLIT,
                                  over=node_lit)

    stars = _load("stars.json")
    visible = []
    for s in stars:
        if s["m"] > star_draw_limit:
            continue
        ra, de = precess(s["ra"], s["de"], jd)
        a, z = altaz(ra, de, lat, lst)
        if a <= 0:
            continue
        lit = s["m"] <= mag_limit
        # Only the lit ones. `visible` is what the star count and the
        # brightest-few list are built from, and an unlit star is one you
        # cannot see -- counting it would make the line above the chart say
        # 287 stars over a sky showing none.
        #
        # count_limit, not mag_limit: they are the same number everywhere
        # except inside a quadrant crop, which draws deeper than the sweep it
        # came from. The extra stars are genuinely drawn and genuinely lit --
        # they just do not change the answer to "how many stars are up",
        # which is about the sky and not about the zoom.
        if s["m"] <= count_limit:
            visible.append((s, a, z))
        col = star_colour(s.get("ci")) if lit else C.UNLIT
        # The glyph is chosen by magnitude either way, so a star keeps its
        # size when it lights up and only its colour moves.
        if a > alt_hi:
            inset_items.append((a, z, glyph_for(s["m"]), col, None))
        else:
            # An unlit star never wins a cell from a lit one: over= stays
            # false for it whatever its magnitude, so a bright star that has
            # not come on yet cannot displace a fainter one that has.
            place(z, a, glyph_for(s["m"]), col, over=lit and s["m"] < 2.0)

    dso = deepsky_visible(dso_limit, jd, lat, lst)
    for o, a, z in dso:
        gl, col = DSO_GLYPH[o["t"]]
        if a > alt_hi:
            inset_items.append((a, z, gl, col, None))
        else:
            place(z, a, gl, col)

    mo, su = moon(jd), sun(jd)
    cands = [planet(n, jd) for n in
             ("Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune")] + [mo, su]
    if bodies is not None:                 # daylight: most of these are invisible
        cands = [b for b in cands if b["name"] in bodies]
    up = []
    for b in cands:
        a, z = altaz(b["ra"], b["dec"], lat, lst)
        b["alt"], b["az"] = a, z
        if a > 0:
            up.append(b)

    track, iss_err = (None, None)
    if tle:
        track, iss_err = iss_track(tle, when_utc, lat, lon)
    if track:                              # ISS: dotted path, one marker + label
        ISS = "\033[38;5;48m"
        for _t, a, z in track:
            place(z, a, "•", ISS, over=True)
        pk = max(track, key=lambda p: p[1])
        # Prefer the peak -- but a high pass can crest above alt_hi (off the
        # main chart, in the zenith inset's territory), in which case both
        # the marker and its label would silently fail to place at all.
        # Fall back to rise, then set, so there's always exactly one Xi
        # (never three) and it's always somewhere the label can attach.
        for mk in (pk, track[0], track[-1]):
            if row_of(mk[1]) is not None and col_of(mk[2]) is not None:
                place(mk[2], mk[1], "Ξ", ISS, over=True)
                text(mk[2], mk[1], "ISS", ISS)
                break

    # Aircraft overhead, if the caller fetched any. Same shape as the ISS
    # above -- a mark and a name -- with three differences it does not need.
    #
    # The mark is an arrow, not a fixed glyph, because direction is the one
    # thing about an aircraft that is free to know and useful to be told:
    # it says which way to look next. It is worked out from where the plane
    # will be a minute on, converted to chart cells, so it points the way the
    # thing moves *across the drawing*. The compass track would be wrong for
    # most of the sky -- see plane_arrow.
    #
    # Names by day, none by night. The day chart is nearly empty and the
    # callsign is most of what there is to read; the night chart is the
    # thing somebody came outside for, and six-character callsigns laid
    # across it in the crowded low band would be text over the stars. The
    # arrows stay either way, and they are what answers "where do I look".
    #
    # Nothing here says where they are going. That belongs in the prose under
    # the chart, where there is room for "likely LHR to SPU" without it
    # having to survive being one glyph wide.
    if planes:
        # Highest first, so where they do collide the ones nearest overhead
        # win the room -- text() gives up rather than overwrite.
        marks = []
        for p in sorted(planes, key=lambda x: -x["elev"]):
            name = p.get("callsign") or p.get("type")
            has_next = (p.get("az_next") is not None
                        and p.get("elev_next") is not None)
            # The cap first, before any panorama test. rowf_of returns None
            # above alt_hi, so asking it first threw away exactly the
            # aircraft this branch exists for -- the one nearly overhead,
            # which is the one somebody is most likely to be looking at.
            if p["elev"] > alt_hi:
                cap = "\u00b7"
                if has_next:
                    x0, y0 = zenith_xy(p["elev"], p["az"], alt_hi, lat)
                    x1, y1 = zenith_xy(p["elev_next"], p["az_next"], alt_hi, lat)
                    # y is up on the disc and rows run down, hence the flip,
                    # so this reads the same way the panorama's does.
                    cap = plane_arrow(x1 - x0, -(y1 - y0)) or cap
                inset_items.append(
                    (p["elev"], p["az"], cap,
                     C.PLANE if plane_tip(p) else C.PLANE_DIM,
                     name if plane_labels else None))
                continue
            c0, r0 = colf_of(p["az"]), rowf_of(p["elev"])
            if c0 is None or r0 is None:
                continue
            mark = "\u00b7"
            if has_next:
                c1, r1 = colf_of(p["az_next"]), rowf_of(p["elev_next"])
                if c1 is not None and r1 is not None:
                    # Wrapped: a plane crossing due north goes from column
                    # 109 to column 0, which as a raw subtraction is a hard
                    # left turn across the whole sky.
                    dc = c1 - c0
                    if abs(dc) > (W - 1) / 2.0:
                        dc -= math.copysign(W - 1, dc)
                    mark = plane_arrow(dc, r1 - r0) or mark
            # Tooltips only where the caller says a browser is reading.
            # A tooltip goes through the same marker machinery an href does,
            # and _chart_link says why that is browser-only: the markers
            # print as control characters if they reach a terminal. Without
            # this gate, "likely Tunis Carthage International Airport" and
            # three control bytes landed in the middle of a curl user's
            # chart -- which is exactly the leak the href had once.
            # Colour on whether the route is known, not on whether a
            # tooltip is being drawn: a terminal has no tooltips at all and
            # the distinction is just as worth seeing there.
            tip = plane_tip(p)
            marks.append((p["az"], p["elev"], mark, name,
                          tip if plane_tips else None,
                          C.PLANE if tip else C.PLANE_DIM))

        # Every mark first, then every name. place() refuses a cell that
        # lock[][] has claimed and labels are what claim them, so drawing
        # each aircraft's arrow and name in turn let the first one's label
        # swallow the second one's arrow -- silently, leaving a callsign
        # floating beside a faint star, which is the same "\u00b7" character.
        # Three of eighteen went that way over Geneva.
        # over=False, so an aircraft never takes a cell something real is
        # already in. free() allows an empty cell or a background gridline
        # dot and refuses a star, which is the rule that matters: the stars
        # are what somebody came outside for and an aircraft is passing
        # through. With over=True an arrow simply replaced whatever was
        # underneath it, and a star that had been there was gone -- which
        # reads as the chart having moved it.
        #
        # The cost is that an aircraft sitting exactly on a star is not
        # drawn. That is the right way round: one arrow missing from a
        # transient overlay against one star missing from the sky.
        drawn = [(az, alt, name, tip, col)
                 for az, alt, mark, name, tip, col in marks
                 if place(az, alt, mark, col)]
        # Only what actually got a mark gets a name. A callsign floating
        # beside a faint star -- the same "\u00b7" character an arrow would
        # have replaced -- reads as a plane drawn wrong rather than as one
        # the chart had no room for.
        if plane_labels:
            for az, alt, name, tip, col in drawn:
                if name:
                    text(az, alt, name, col, tip=tip)

    # The radiant of whatever shower is running, marked where the meteors
    # come from. Same shape as the ISS marker above: one glyph and a name.
    #
    # The chart had nothing on it about a shower at all -- events.
    # active_shower() was written for this and never called by anything --
    # so the page could say "the Perseids are running, radiant 51 deg NE" in
    # prose over a drawing that gave no hint where that was.
    #
    # Orchid, the colour the events strip and the shower portraits already
    # use, so a reader who has seen one recognises the other.
    #
    # Above alt_hi it goes to the zenith inset, the way a planet or a bright
    # star does. Without that it simply vanished: the Perseid radiant reaches
    # 79 degrees from Zurich, so it climbed off the top of the panorama at
    # about 04:00 and the chart stopped mentioning the shower for the rest of
    # the night -- the part of the night the shower is best in.
    if radiant and radiant["alt"] > alt_hi:
        inset_items.append((radiant["alt"], radiant["az"], "+",
                            "\033[38;5;213m", radiant["name"].upper()))
    elif radiant and row_of(radiant["alt"]) is not None \
            and col_of(radiant["az"]) is not None:
        # "+", the same mark art.py puts at the radiant of its shower
        # portraits, rather than the "☄" the events list uses for the row.
        # Neither bundled font has a glyph for that one -- test_gif's tofu
        # check catches it -- and a chart that exports as an empty box is
        # worse than one that marks the spot with a cross.
        RAD = "\033[38;5;213m"
        place(radiant["az"], radiant["alt"], "+", RAD, over=True)
        text(radiant["az"], radiant["alt"], radiant["name"].upper(), RAD,
             href_for(radiant["name"]))

    if overlay:                            # Sun: thin path, marker on where it IS
        over_pts, over_col, over_lbl, over_mark = overlay
        # A path point is (minutes, alt, az), and may carry its own glyph and
        # colour after that. The Sun's arc uses the extra pair to draw the
        # golden-hour stretch differently from the rest of the day without
        # needing a second overlay slot and a second pass over the same arc.
        # The stretch of arc above the cap goes into the inset rather than
        # off the top of the chart. The inset already draws points at an
        # alt/az, and an arc is a series of points, so this is the same
        # mechanism rather than a second one: in the tropics the top fifth of
        # the day used to simply not be drawn anywhere.
        for pt in over_pts or ():
            a, z = pt[1], pt[2]
            ch = pt[3] if len(pt) > 3 else "·"
            col = pt[4] if len(pt) > 4 else over_col
            if a > alt_hi:
                inset_items.append((a, z, ch, col, None))
            else:
                place(z, a, ch, col, over=True)
        # The marker goes up with its arc. This is the only thing that puts
        # the Sun in the inset, and it has to be: the day chart's `bodies`
        # does not include the Sun -- the animation's is
        # _fade_visible_bodies, which is about what is visible in a dark sky
        # -- so the body loop below never sees it. Adding it there instead
        # worked but cost the panorama its own marker, because a body's ☀ is
        # drawn over the overlay's ◉ and quietly replaced it.
        if over_mark:
            ma, mz = over_mark
            if ma > alt_hi:
                inset_items.append((ma, mz, "☀", over_col, over_lbl))
            else:
                place(mz, ma, "◉", over_col, over=True)
                if over_lbl:
                    text(mz, ma, over_lbl, over_col)

    for b in sorted(up, key=lambda x: -x["alt"]):
        if b["name"] == "Sun":
            # Overhead in the tropics, and the inset is where overhead lives.
            if b["alt"] > alt_hi:
                inset_items.append((b["alt"], b["az"], "☀",
                                    "\033[38;5;227m", b["name"]))
            else:
                place(b["az"], b["alt"], "☀", "\033[38;5;227m", over=True)
            continue
        # The default horizon/panorama chart used to hardcode a full circle
        # for the Moon here regardless of its actual phase -- moon_glyph()
        # was only ever reached by the disc view and the text summary.
        gl, colr = (moon_glyph(b["age"], lat), C.MOON) if b["name"] == "Moon" else ("◆", C.PLANET)
        if b["alt"] > alt_hi:
            inset_items.append((b["alt"], b["az"], gl, colr, b["name"])); continue
        place(b["az"], b["alt"], gl, colr, over=True)
        if not (target and target["name"] == b["name"]):
            text(b["az"], b["alt"], b["name"], colr, href_for(b["name"]))

    top3 = [v for v in sorted(visible, key=lambda v: v[0]["m"]) if v[0].get("n")][:3]
    for s, a, z in top3:
        if a > alt_hi:
            inset_items.append((a, z, "★", "\033[38;5;231m", s["n"])); continue
        place(z, a, "★", "\033[38;5;231m", over=True)
        if not (target and target["name"] == s["n"]):
            text(z, a, s["n"], C.HEAD, href_for(s["n"]))

    # deepsky.json's cn field is hand-curated to the ~30 well-known objects
    # (build_deepsky.py), so every one visible gets a label -- no brightness
    # cap needed, the curation already did that job.
    for o, a, z in dso:
        if not o.get("cn") or a > alt_hi:
            continue
        _gl, col = DSO_GLYPH[o["t"]]
        text(z, a, o["cn"], col, href_for(o["cn"]))

    if target is not None:
        TC = TARGET_C
        place(target["az"], target["alt"], "◎", TC, over=True)
        c0, r0 = col_of(target["az"]), row_of(target["alt"])
        if c0 is not None and r0 is not None:            # crosshair arms
            for dc in (-3, -2, 3, 2):
                if 0 <= c0 + dc < W and free(r0, c0 + dc):
                    grid[r0][c0+dc], tint[r0][c0+dc], soft[r0][c0+dc] = "─", TC, False
            for dr in (-1, 1):
                if 0 <= r0 + dr < H and free(r0 + dr, c0):
                    grid[r0+dr][c0], tint[r0+dr][c0], soft[r0+dr][c0] = "│", TC, False
        text(target["az"], target["alt"], target["name"].upper(), TC)

    QL = "\033[38;5;226m"   # plain 38;5;N, matching every other colour here --
                            # ansi_to_html's regex doesn't parse a bold prefix
    for cell in quad_cells:
        text(cell["az_centre"], (cell["alt_lo"] + cell["alt_hi"]) / 2, cell["letter"], QL)

    for item in chosen:                       # names last, so they win the space
        if line_limit is not None and not item.get("visible", False):
            continue                           # animate frames: fully faded out
        text(item["caz"], min(max(item["calt"], alt_lo), alt_hi),
             item["con"]["name"].upper(), C.CNAME,
             href_for(item["con"]["name"]))

    # And only now the asterism lines, from the bitmap every segment went
    # into, filling whatever cells nothing else claimed.
    #
    # Last rather than first, which is where they used to go. A line drawn
    # first owns its cells, and a subpixel line owns about twice as many as
    # the old ─ ╱ │ ╲ did: two faint stars over Lima stopped being drawn
    # because a line got to their cells before the star field did, and a
    # constellation name jumped sixteen columns between /Zurich and
    # /Zurich?find=, having been pushed off the spot it wanted. Drawn last,
    # a line can no longer cost the sky an object or move a label: it breaks
    # around them instead, which is the right way round for the thing that
    # was always meant to be underneath.
    if show_lines:
        for r in range(H):
            row = grid[r]
            for c in range(W):
                bits = dim_bits = 0
                for dy in range(4):
                    for dx in range(2):
                        if dots[r * 4 + dy][c * 2 + dx]:
                            bits |= BRAILLE_DOTS[(dx, dy)]
                        if dim_dots[r * 4 + dy][c * 2 + dx]:
                            dim_bits |= BRAILLE_DOTS[(dx, dy)]
                # Lit first and on its own: a cell carrying any lit dot is a
                # lit cell, and its unlit dots are dropped rather than mixed
                # in. Merging the two bitmaps would put a grey glyph where a
                # figure crosses itself, which is the one place the eye is
                # most likely to be looking.
                if bits and free(r, c):
                    row[c], tint[r][c], soft[r][c] = (
                        chr(BRAILLE_BASE + bits), C.DIM, False)
                # Genuinely empty, not merely free(). free() counts a soft
                # cell as available, which is how a lit line gets to draw
                # over a quadrant divider or the Milky Way -- fine for a
                # line you can actually trace, wrong for one that is not lit
                # yet. An unlit line is the faintest thing on the chart and
                # displaces nothing: it cost seven divider cells before this
                # was qualified, on a view whose whole purpose is the grid.
                elif dim_bits and grid[r][c] == " " and not lock[r][c]:
                    row[c], tint[r][c], soft[r][c] = (
                        chr(BRAILLE_BASE + dim_bits), C.UNLIT, False)

    # The quadrant grid, last of everything that draws into the chart.
    #
    # It used to go first, into empty cells only, which made it a grid in
    # name and a scatter of tick marks in practice: every star, label and
    # asterism line it passed behind punched a hole in it, and on a busy
    # chart barely a hundred cells of four full-height dividers survived.
    # A grid you turned on to pick a quadrant out of is the one thing on
    # the page that has to be followable end to end, so it now draws over
    # the sky rather than around it.
    #
    # Locked cells are the exception, and the only one: those are text --
    # object names, constellation labels, the quadrant letters themselves,
    # all placed above -- and a divider through the middle of a word costs
    # more than the pixel of grid it buys.
    #
    # Yellow, matching the A-L letters it belongs to, but two steps down
    # from their 226: the letters are what you read and the grid is what
    # you follow, and at the same brightness a full-height rule every
    # fifty-odd columns shouted over the sky it is drawn on.
    if quad_cells:
        QC = "\033[38;5;178m"
        az_bounds = sorted({round(c["az_centre"] - c["az_span"] / 2, 4) for c in quad_cells}
                           | {round(c["az_centre"] + c["az_span"] / 2, 4) for c in quad_cells})
        alt_bounds = sorted({round(c["alt_lo"], 4) for c in quad_cells}
                            | {round(c["alt_hi"], 4) for c in quad_cells})
        # Horizontals first, so the verticals win every crossing. The
        # verticals are the full height of the chart and the ones an eye
        # actually follows from a letter down to the horizon; the
        # horizontals are dashes every other column and read as a band
        # either way. Drawn the other way round, each vertical came out with
        # a gap at every altitude boundary it passed.
        for a in alt_bounds:
            r = row_of(a)
            if r is None:
                continue
            for c in range(0, W, 2):
                if not lock[r][c]:
                    grid[r][c], tint[r][c], soft[r][c] = "┈", QC, True
        for az in az_bounds:
            c = col_of(az)
            if c is None:
                continue
            for r in range(H):
                if not lock[r][c]:
                    grid[r][c], tint[r][c], soft[r][c] = "┊", QC, True

    # label the row nearest each 10 deg step, so the ticks survive any H
    ticks10 = {}
    for a in range(int(alt_lo // 10) * 10, int(alt_hi) + 2, 10):
        r = row_of(a)
        if r is not None:
            ticks10.setdefault(r, a)
    out = []
    for r in range(H):
        lab = f"{ticks10[r]:>3}°" if r in ticks10 else "    "
        opens = {a: (b, u) for a, b, u in anchors.get(r, ())}
        closes = {b for _a, b, _u in anchors.get(r, ())}
        cells = []
        for c in range(W):
            if c in closes:
                cells.append(LINK_END)
            if c in opens:
                cells.append(LINK_START + opens[c][1] + LINK_SEP)
            cells.append(paint(grid[r][c], tint[r][c], color)
                         if grid[r][c] != " " and tint[r][c] else grid[r][c])
        if W in closes:
            cells.append(LINK_END)
        row = "".join(cells)
        # rstrip would eat a trailing LINK_END and leave an anchor open, so
        # the tail is trimmed of spaces only.
        out.append(paint(f"{lab:<4} ", C.MUTE, color) + row.rstrip(" "))
    if alt_lo <= 0.5:
        out.append(paint(" " * LM + "─" * W, C.HOR, color))
    else:
        out.append(paint(" " * LM + "┄" * W, C.HOR, color))
    ticks = [" "] * W
    for nm, az in CARDINALS.items():
        if span >= 359 and len(nm) > 2:
            continue
        c = col_of(az)
        if c is None:
            continue
        st = min(max(c - len(nm)//2, 0), W - len(nm))
        if all(ticks[st+k] == " " for k in range(len(nm))):
            for k, ch in enumerate(nm):
                ticks[st + k] = ch
    if span >= 359:
        # The wrap-around point is whatever's opposite centre, not always
        # North -- centre itself now flips between N and S with hemisphere.
        ticks[W - 1] = "S" if centre == 0 else "N"
    out.append(paint(" " * LM + "".join(ticks).rstrip(), C.CARD, color))
    # `target` used to disqualify the inset because find meant a 26° crop
    # with no room for one. find now draws the full panorama, so that went.
    # A cropped altitude range used to disqualify it too, because an inset
    # labelled 70-90° is a lie on a chart that stops at 40° -- but the lie
    # was in the label, not in the inset. It is handed the chart's own cap
    # now and says so, and inset_items has always been "everything above
    # alt_hi", so the two agreed all along.
    #
    # That is what lets every chart have the same structure: the panorama,
    # then the rest of the sky above it. The Sun's arc gets one, so does an
    # animation frame, and neither has to special-case it.
    #
    # Nothing left to show above 88° -- the chart already goes to the top of
    # the sky, and 90 minus that is a disc with no radius.
    # Always, empty or not. Every chart has the same structure -- the
    # panorama, and the cap of sky above it -- and a box that comes and goes
    # depending on whether anything happens to be overhead is a layout that
    # moves for reasons the reader cannot see. Empty, it still says what it
    # is: this is the part of the sky the panorama cannot show, and there is
    # nothing in it.
    zenith_lines = None
    if facing is None and quad_applied is None and inset and alt_hi < 88:
        zenith_lines = _zenith_inset(inset_items, alt_hi, color,
                                     0 if side_panel else LM, lat=lat,
                                     target=target, link=link)
        if not side_panel:
            out.append("")
            out.extend(zenith_lines)
    st = dict(visible=visible, up=up, moon=mo, sun=su, lst=lst, jd=jd,
              track=track, iss_err=iss_err, top3=top3, span=span, clamped=clamped,
              cons=[c["con"]["name"] for c in chosen],
              # What was actually drawn to, after any quadrant deepening --
              # not necessarily the mag_limit the caller passed in.
              mag_limit=mag_limit, count_limit=count_limit,
              quad_cells=quad_cells, quad_applied=quad_applied, quad_error=quad_error,
              zenith_lines=zenith_lines if side_panel else None)
    return "\n".join(out), st



if __name__ == "__main__":
    print("sky.py is the drawing engine. Use the CLI:  python3 cli.py --help")
