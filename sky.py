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
    PLANET = "\033[38;5;180m"
    MOON = "\033[38;5;253m"
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

def paint(s, c, on=True):
    return f"{c}{s}{C.OFF}" if on else s


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

def render(when_utc, lat, lon, height=34, color=True, show_lines=True, mag_limit=4.2,
          width=None, dso_limit=None):
    if width is not None:
        height = max(30, min(110, int(width))) // 2   # disc is always W = 2*H
    W, H = height * 2, height
    jd = julian(when_utc)
    lst = (gmst_hours(jd) + lon / 15.0) % 24

    grid = [[" "] * W for _ in range(H)]
    tint = [[None] * W for _ in range(H)]
    cx, cy = (W - 1) / 2, (H - 1) / 2

    def place(x, y, ch, col, over=False):
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        if 0 <= r < H and 0 <= c < W:
            if over or grid[r][c] == " ":
                grid[r][c], tint[r][c] = ch, col

    stars = _load("stars.json")

    # --- constellation lines (drawn first, underneath everything)
    if show_lines:
        cpos = {t["hr"]: [t["ra"], t["de"], t["m"]]
                for t in _load("stars.json")}
        for con in _load("asterisms.json"):
            alts = []
            for poly in con["lines"]:
                for hip in poly:
                    if hip in cpos:
                        ra, dec, _ = cpos[hip]
                        ra, dec = precess(ra, dec, jd)
                        alts.append(altaz(ra, dec, lat, lst)[0])
            if not alts or sum(1 for a in alts if a > 12) < 0.85 * len(alts):
                continue                      # mostly below or grazing the horizon
            for poly in con["lines"]:
                pts = []
                for hip in poly:
                    if hip not in cpos:
                        pts.append(None); continue
                    ra, dec, _ = cpos[hip]
                    ra, dec = precess(ra, dec, jd)
                    a, z = altaz(ra, dec, lat, lst)
                    pts.append(project(a, z) if a > 8 else None)
                for p, q in zip(pts, pts[1:]):
                    if not p or not q:
                        continue
                    ddx, ddy = (q[0] - p[0]) * cx, (q[1] - p[1]) * cy
                    span = max(abs(ddx), abs(ddy))
                    if span > 26:            # horizon-stretched junk, not a real asterism
                        continue
                    ang = math.degrees(math.atan2(ddy, ddx)) % 180
                    ch = "─" if ang < 22.5 or ang >= 157.5 else "╱" if ang < 67.5 \
                         else "│" if ang < 112.5 else "╲"
                    steps = int(span * 1.3) + 1
                    for k in range(1, steps):          # endpoints belong to the stars
                        t = k / steps
                        x, y = p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t
                        if math.hypot(x, y) <= 0.99:
                            place(x, y, ch, C.DIM)

    # --- horizon ring + cardinals
    for i in range(720):
        th = i * math.pi / 360
        place(math.sin(th), math.cos(th), "∙", C.HOR)
    for az, ch in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        x, y = project(0, az)
        place(x * 1.0, y * 1.0, ch, C.CARD, over=True)

    # --- stars
    visible = []
    for s in stars:
        if s["m"] > mag_limit:
            continue
        ra, de = precess(s["ra"], s["de"], jd)
        a, z = altaz(ra, de, lat, lst)
        if a <= 0:
            continue
        visible.append((s, a, z))
        x, y = project(a, z)
        place(x, y, glyph_for(s["m"]), star_colour(s.get("ci")), over=s["m"] < 2.0)

    # --- deep sky
    dso = deepsky_visible(dso_limit, jd, lat, lst)
    for o, a, z in dso:
        x, y = project(a, z)
        gl, col = DSO_GLYPH[o["t"]]
        place(x, y, gl, col)

    # --- bodies
    bodies, jd_ = [], jd
    mo = moon(jd_); su = sun(jd_)
    for nm in ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"):
        bodies.append(planet(nm, jd_))
    bodies.append(mo); bodies.append(su)
    up = []
    for b in bodies:
        a, z = altaz(b["ra"], b["dec"], lat, lst)
        b["alt"], b["az"] = a, z
        if a > 0:
            up.append(b)
            x, y = project(a, z)
            if b["name"] == "Moon":
                place(x, y, moon_glyph(b["age"], lat), C.MOON, over=True)
            elif b["name"] == "Sun":
                place(x, y, "☀", "\033[38;5;227m", over=True)
            else:
                place(x, y, "◆", C.PLANET, over=True)

    # --- labels for the brightest things
    labelled = 0
    for s, a, z in sorted(visible, key=lambda v: v[0]["m"]):
        if labelled >= 9 or not s.get("n"):
            continue
        x, y = project(a, z)
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        nm = s["n"]
        start = c + 2 if c + 2 + len(nm) < W else c - len(nm) - 2
        if 0 <= r < H and start >= 0 and start + len(nm) <= W:
            if all(grid[r][start + k] == " " for k in range(len(nm))):
                for k, ch in enumerate(nm):
                    grid[r][start + k], tint[r][start + k] = ch, C.MUTE
                labelled += 1
    for b in up:
        if b["name"] == "Sun":
            continue
        x, y = project(b["alt"], b["az"])
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        nm = b["name"]
        start = c + 2 if c + 2 + len(nm) < W else c - len(nm) - 2
        if 0 <= r < H and start >= 0 and start + len(nm) <= W:
            if all(grid[r][start + k] == " " for k in range(len(nm))):
                col = C.MOON if nm == "Moon" else C.PLANET
                for k, ch in enumerate(nm):
                    grid[r][start + k], tint[r][start + k] = ch, col

    # deepsky.json's cn field is hand-curated to the ~30 well-known objects
    # (build_deepsky.py), so every one visible gets a label -- no brightness
    # cap needed, the curation already did that job.
    for o, a, z in dso:
        if not o.get("cn"):
            continue
        x, y = project(a, z)
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        nm = o["cn"]
        _gl, col = DSO_GLYPH[o["t"]]
        start = c + 2 if c + 2 + len(nm) < W else c - len(nm) - 2
        if 0 <= r < H and start >= 0 and start + len(nm) <= W:
            if all(grid[r][start + k] == " " for k in range(len(nm))):
                for k, ch in enumerate(nm):
                    grid[r][start + k], tint[r][start + k] = ch, col

    lines = []
    for r in range(H):
        row = []
        for c in range(W):
            ch = grid[r][c]
            row.append(paint(ch, tint[r][c], color) if ch != " " and tint[r][c] else ch)
        lines.append("".join(row).rstrip())
    return "\n".join(lines), dict(visible=visible, up=up, moon=mo, sun=su, lst=lst, jd=jd)


# ---------------------------------------------------------------- text read
def sky_read(st, place, when_local, tzname, lat=0.0):
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
        out.extend(textwrap.wrap(p, 76) or [""])
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


def _zenith_inset(items, alt_max, color, indent, IW=21, IH=11):
    """Small all-sky disc for the cap the panorama cannot honestly show.
    Same convention as the full disc: north up, east left."""
    g = [[" "] * IW for _ in range(IH)]
    t = [[None] * IW for _ in range(IH)]
    cx, cy = (IW - 1) / 2, (IH - 1) / 2
    span = 90.0 - alt_max

    def put(x, y, ch, col, over=False):
        c, r = int(round(cx + x * cx)), int(round(cy - y * cy))
        if 0 <= r < IH and 0 <= c < IW and (over or g[r][c] == " "):
            g[r][c], t[r][c] = ch, col

    for i in range(500):                                  # rim = the cap altitude
        th = i * 2 * math.pi / 500
        put(math.sin(th), math.cos(th), "∙", C.HOR)
    for az, ch in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        put(-math.sin(az * D), math.cos(az * D), ch, C.CARD, over=True)
    put(0, 0, "+", "\033[38;5;238m")                       # the zenith itself

    named = []
    for alt, az, ch, col, nm in sorted(items, key=lambda v: -v[0]):
        r = (90.0 - alt) / span
        put(-math.sin(az * D) * r, math.cos(az * D) * r, ch, col, over=True)
        if nm:
            named.append((nm, col))

    head = f"zenith {alt_max}-90°"
    lines = [" " * indent + paint(head, C.MUTE, color)]
    for r in range(IH):
        row = "".join(paint(g[r][c], t[r][c], color) if g[r][c] != " " and t[r][c]
                      else g[r][c] for c in range(IW))
        extra = ""
        if r - 1 < len(named) and r >= 1:
            nm, col = named[r - 1]
            extra = "   " + paint(nm, col, color)
        lines.append(" " * indent + row.rstrip() + extra)
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


def sun_events(day_start_utc, lat, lon):
    """Rise, transit, set and the three twilights. These do not change over a
    day, which is what makes the daytime response cheap to serve."""
    step = dt.timedelta(minutes=10)
    samples = [(day_start_utc + i * step,
                _sun_alt(julian(day_start_utc + i * step), lat, lon)[0])
               for i in range(int(24 * 6) + 1)]
    ev = {}
    for name, level, rising in (("dawn_astro", -18, True), ("dawn_nautical", -12, True),
                                ("dawn_civil", -6, True), ("sunrise", -0.833, True),
                                ("sunset", -0.833, False), ("dusk_civil", -6, False),
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
    ev["polar_day"] = min(a for _t, a in samples) > -0.833
    ev["polar_night"] = hi[1] < -0.833
    return ev


# ---------------------------------------------------------------- find a thing
def angsep(a1, z1, a2, z2):
    p1, p2 = a1 * D, a2 * D
    return math.degrees(math.acos(max(-1, min(1,
        math.sin(p1) * math.sin(p2) +
        math.cos(p1) * math.cos(p2) * math.cos((z1 - z2) * D)))))


def resolve_target(name, jd, lat, lst):
    """Name -> where it is right now. Planets, Sun, Moon, named stars, asterisms."""
    q = name.strip().lower()
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


def find_text(t, visible, lat):
    L = [f"{t['name']}: {t['alt']:.0f}\u00b0 above the horizon in the {compass(t['az'])} "
         f"(bearing {t['az']:.0f}\u00b0)."]
    L.append(f"Face {compass(t['az'])} and look {fists(t['alt'])} \u2014 a closed fist at "
             f"arm's length is about 10\u00b0.")
    if t.get("mag") is not None:
        L.append(f"Magnitude {t['mag']:.1f}." if t["kind"] != "asterism" else "")
    ref, near = None, 12 if t["kind"] == "asterism" else 6
    for s, a, z in sorted(visible, key=lambda v: v[0]["m"]):
        if not s.get("n") or s["m"] > 2.0 or s["n"] == t["name"]:
            continue
        d = angsep(t["alt"], t["az"], a, z)
        if near < d < 45 and (ref is None or d < ref[1]):
            ref = (s["n"], d, a, z)
    if ref:
        nm, d, a, z = ref
        # describe where the TARGET sits relative to the marker, not the reverse
        vert = ("above" if t["alt"] > a + 3 else
                "below" if t["alt"] < a - 3 else "level with")
        dz = ((t["az"] - z + 180) % 360) - 180
        side = "right" if dz > 3 else "left" if dz < -3 else None
        if side and vert != "level with":
            rel = f"{vert} it and to the {side}"
        elif side:
            rel = f"level with it, to the {side}"
        else:
            rel = f"directly {vert} it" if vert != "level with" else "right beside it"
        L.append(f"Nearest bright marker: {nm}, {d:.0f}\u00b0 away \u2014 {t['name']} is "
                 f"{rel}.")
    if t.get("kind") == "moon":
        L.append(f"Phase {moon_glyph(t['age'], lat)} {phase_name(t['age'])}, "
                 f"{t['illum']*100:.0f}% lit.")
    import textwrap
    out = []
    for p in [x for x in L if x]:
        out.extend(textwrap.wrap(p, 76))
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
    if t["alt"] < min_alt:
        return False, ("below the horizon" if t["alt"] <= 0 else
                       "too low, under 8°, so trees and buildings will be in the way")
    if not dark_enough(sa, mag):
        return False, ("the sky is still too bright" if sa > -6
                       else "the sky is not quite dark enough for it")
    return True, "visible now"


def next_visible(t, lat, lon, start_utc, days=40, step_min=10, min_alt=12.0):
    """First moment it clears min_alt in a sky dark enough for its brightness."""
    mag = t["mag"] if t.get("mag") is not None else t.get("faint")
    n = int(days * 24 * 60 / step_min)
    for i in range(1, n):
        when = start_utc + dt.timedelta(minutes=i * step_min)
        jd = julian(when)
        lst = (gmst_hours(jd) + lon / 15.0) % 24
        su = sun(jd)
        sa, _ = altaz(su["ra"], su["dec"], lat, lst)
        if not dark_enough(sa, mag):
            continue
        a, z = target_altaz(t, jd, lat, lst)
        if a >= min_alt:
            return when, a, z
    return None, None, None


def solar_elongation(t, jd, lat, lst):
    su = sun(jd)
    sa, sz = altaz(su["ra"], su["dec"], lat, lst)
    return angsep(t["alt"], t["az"], sa, sz)


# ---------------------------------------------------------------- linear view
CARDINALS = {"N":0,"NNE":22.5,"NE":45,"ENE":67.5,"E":90,"ESE":112.5,"SE":135,"SSE":157.5,
             "S":180,"SSW":202.5,"SW":225,"WSW":247.5,"W":270,"WNW":292.5,"NW":315,"NNW":337.5}

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


def pick_constellations(cpos, cons, jd, lat, lst, alt_max, sectors=6, extra=2,
                        in_view=None):
    """Brightest figure per azimuth sector, so the sky is covered evenly instead
    of clustering wherever tonight's bright ones happen to sit."""
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
                  quadrant=None, quadrants=False):
    """Horizon panorama. facing=None gives the full 360 deg sweep; facing='SW'
    gives a window centred there, which is narrow enough to be undistorted."""
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

    alt_lo = 0.0 if alt_lo is None else float(alt_lo)
    alt_hi = float(alt_max) if alt_hi is None else float(alt_hi)
    alt_rng = alt_hi - alt_lo

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

    if target is not None:                       # frame chosen by the object itself
        W = 118
        span = float(req_span or 60.0)
        centre = float(target["az"])
        H = max(8, int(round(W * alt_rng / (2 * span))))
        clamped = ""
    if width is not None:
        # Rescale both dimensions by the same factor so aspect stays exactly
        # what it was -- this only changes how many terminal columns the same
        # honest render is spread across, not the geometry itself.
        width = max(60, min(220, int(width)))
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
    inset_items = []                # (alt, az, glyph, colour, name|None)

    def free(r, c):
        return (grid[r][c] == " " or soft[r][c]) and not lock[r][c]

    def col_of(az):
        d = ((az - centre + 180) % 360) - 180
        if abs(d) > span / 2:
            return None
        return int(round((d + span / 2) / span * (W - 1)))

    def row_of(alt):
        if alt < alt_lo - 1e-9 or alt > alt_hi + 1e-9:
            return None
        return H - 1 - int(round((alt - alt_lo) / alt_rng * (H - 1)))

    def place(az, alt, ch, col, over=False):
        c, r = col_of(az), row_of(alt)
        if c is None or r is None:
            return
        if 0 <= r < H and not lock[r][c] and (over or free(r, c)):
            grid[r][c], tint[r][c], soft[r][c] = ch, col, False

    def _try(r, c, s, colr, dx):
        start = c + dx if dx > 0 else c - len(s) + dx
        if not (0 <= r < H and 0 <= start and start + len(s) <= W):
            return False
        if any(not free(r, start + k) for k in range(len(s))):
            return False
        for k, ch in enumerate(s):
            grid[r][start + k], tint[r][start + k] = ch, colr
            soft[r][start + k], lock[r][start + k] = False, True
        return True

    def text(az, alt, s, colr):
        c, r = col_of(az), row_of(alt)
        if c is None or r is None:
            return False
        for dr in (0, -1, 1, -2, 2, -3, 3):
            for dx in (2, -2, 5, -5, 9, -9):
                if _try(r + dr, c, s, colr, dx):
                    return True
        return False

    for a in range(int(alt_lo // 10) * 10, int(alt_hi) + 1, 10):
        r = row_of(a)
        if r is None or a <= alt_lo:
            continue
        for c in range(0, W, 6):
            if grid[r][c] == " ":
                grid[r][c], tint[r][c], soft[r][c] = "·", "\033[38;5;234m", True

    if quad_cells:                      # dotted cell boundaries, letters follow later
        QC = "\033[38;5;240m"
        az_bounds = sorted({round(c["az_centre"] - c["az_span"] / 2, 4) for c in quad_cells}
                           | {round(c["az_centre"] + c["az_span"] / 2, 4) for c in quad_cells})
        alt_bounds = sorted({round(c["alt_lo"], 4) for c in quad_cells}
                            | {round(c["alt_hi"], 4) for c in quad_cells})
        for az in az_bounds:
            c = col_of(az)
            if c is None:
                continue
            for r in range(H):
                if grid[r][c] == " ":
                    grid[r][c], tint[r][c], soft[r][c] = "┊", QC, True
        for a in alt_bounds:
            r = row_of(a)
            if r is None:
                continue
            for c in range(0, W, 2):
                if grid[r][c] == " ":
                    grid[r][c], tint[r][c], soft[r][c] = "┈", QC, True

    chosen = []
    if show_lines:
        # Asterisms only. The full IAU figure for Ursa Major is a 25-star bear
        # that nobody recognises; what people see is the 7-star Plough. These
        # line lists are hand-authored from Bayer designations (build_asterisms.py)
        # and resolved against BSC5, so no third-party line file is involved.
        cpos = {t["hr"]: [t["ra"], t["de"], t["m"]]
                for t in _load("stars.json")}
        cons = _load("asterisms.json")
        chosen = pick_constellations(cpos, cons, jd, lat, lst, alt_hi,
                                     sectors=6 if target is None else 3,
                                     in_view=lambda z: col_of(z) is not None)
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
                    if hip not in cpos or (line_limit is not None and cpos[hip][2] > line_limit):
                        pts.append(None); continue
                    ra, dec, _m = cpos[hip]
                    ra, dec = precess(ra, dec, jd)
                    a, z = altaz(ra, dec, lat, lst)
                    cc = col_of(z)
                    rr = row_of(a) if cc is not None else None
                    pts.append((cc, rr) if rr is not None and a > 3 else None)
                for p, q in zip(pts, pts[1:]):
                    if not p or not q or abs(q[0] - p[0]) > W * 0.35:
                        continue
                    n = max(abs(q[0] - p[0]), abs(q[1] - p[1]))
                    if n == 0:
                        continue
                    cells, seen = [], set()
                    for k in range(n + 1):
                        t = k / n
                        cell = (int(round(p[0] + (q[0]-p[0])*t)),
                                int(round(p[1] + (q[1]-p[1])*t)))
                        if cell not in seen:
                            seen.add(cell); cells.append(cell)
                    for c, r, g in _walk(cells)[1:-1]:
                        if 0 <= r < H and 0 <= c < W and not lock[r][c] and free(r, c):
                            grid[r][c], tint[r][c], soft[r][c] = g, C.DIM, False
                    item["visible"] = True
                # the pattern's own vertex stars, so the nodes read clearly
                for hip in poly:
                    if hip in cpos:
                        ra, dec, m = cpos[hip]
                        if line_limit is not None and m > line_limit:
                            continue
                        ra, dec = precess(ra, dec, jd)
                        a, z = altaz(ra, dec, lat, lst)
                        if a > 0:
                            place(z, a, "●" if m < 3.2 else "•",
                                  star_colour(None), over=True)

    stars = _load("stars.json")
    visible = []
    for s in stars:
        if s["m"] > mag_limit:
            continue
        ra, de = precess(s["ra"], s["de"], jd)
        a, z = altaz(ra, de, lat, lst)
        if a <= 0:
            continue
        visible.append((s, a, z))
        if a > alt_hi:
            inset_items.append((a, z, glyph_for(s["m"]), star_colour(s.get("ci")), None))
        else:
            place(z, a, glyph_for(s["m"]), star_colour(s.get("ci")), over=s["m"] < 2.0)

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

    if overlay:                            # Sun: thin path, marker on where it IS
        over_pts, over_col, over_lbl, over_mark = overlay
        for _t, a, z in over_pts or ():
            place(z, a, "·", over_col, over=True)
        if over_mark:
            ma, mz = over_mark
            place(mz, ma, "◉", over_col, over=True)
            if over_lbl:
                text(mz, ma, over_lbl, over_col)

    for b in sorted(up, key=lambda x: -x["alt"]):
        if b["name"] == "Sun":
            place(b["az"], b["alt"], "☀", "\033[38;5;227m", over=True); continue
        # The default horizon/panorama chart used to hardcode a full circle
        # for the Moon here regardless of its actual phase -- moon_glyph()
        # was only ever reached by the disc view and the text summary.
        gl, colr = (moon_glyph(b["age"], lat), C.MOON) if b["name"] == "Moon" else ("◆", C.PLANET)
        if b["alt"] > alt_hi:
            inset_items.append((b["alt"], b["az"], gl, colr, b["name"])); continue
        place(b["az"], b["alt"], gl, colr, over=True)
        if not (target and target["name"] == b["name"]):
            text(b["az"], b["alt"], b["name"], colr)

    top3 = [v for v in sorted(visible, key=lambda v: v[0]["m"]) if v[0].get("n")][:3]
    for s, a, z in top3:
        if a > alt_hi:
            inset_items.append((a, z, "★", "\033[38;5;231m", s["n"])); continue
        place(z, a, "★", "\033[38;5;231m", over=True)
        if not (target and target["name"] == s["n"]):
            text(z, a, s["n"], C.HEAD)

    # deepsky.json's cn field is hand-curated to the ~30 well-known objects
    # (build_deepsky.py), so every one visible gets a label -- no brightness
    # cap needed, the curation already did that job.
    for o, a, z in dso:
        if not o.get("cn") or a > alt_hi:
            continue
        _gl, col = DSO_GLYPH[o["t"]]
        text(z, a, o["cn"], col)

    if target is not None:
        TC = "\033[38;5;213m"
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
             item["con"]["name"].upper(), C.CNAME)

    # label the row nearest each 10 deg step, so the ticks survive any H
    ticks10 = {}
    for a in range(int(alt_lo // 10) * 10, int(alt_hi) + 2, 10):
        r = row_of(a)
        if r is not None:
            ticks10.setdefault(r, a)
    out = []
    for r in range(H):
        lab = f"{ticks10[r]:>3}°" if r in ticks10 else "    "
        row = "".join(paint(grid[r][c], tint[r][c], color)
                      if grid[r][c] != " " and tint[r][c] else grid[r][c] for c in range(W))
        out.append(paint(f"{lab:<4} ", C.MUTE, color) + row.rstrip())
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
    if facing is None and target is None and quad_applied is None and inset:
        out.append("")
        out.extend(_zenith_inset(inset_items, alt_max, color, LM))
    st = dict(visible=visible, up=up, moon=mo, sun=su, lst=lst, jd=jd,
              track=track, iss_err=iss_err, top3=top3, span=span, clamped=clamped,
              cons=[c["con"]["name"] for c in chosen],
              quad_cells=quad_cells, quad_applied=quad_applied, quad_error=quad_error)
    return "\n".join(out), st



if __name__ == "__main__":
    print("sky.py is the drawing engine. Use the CLI:  python3 cli.py --help")
