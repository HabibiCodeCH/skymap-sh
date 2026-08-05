#!/usr/bin/env python3
"""
Object pages: the facts about one thing in the sky, from one place on Earth.

sky.py answers "what does the sky look like". This answers "where is Saturn",
which needs a different set of numbers: rise and transit times, how far from
the Sun, which constellation, when in the year it is best seen.

Kept out of sky.py deliberately. sky.py is the render engine and every chart
on the site goes through it; this is a leaf that imports from it and is
imported by api.py, so nothing here can regress a chart.
"""
import datetime as dt
import math
import re
import unicodedata

import sky

D = math.pi / 180

# Standard refraction allowance at the horizon. A body is called "risen" when
# its centre is 34 arcminutes below the geometric horizon, because the
# atmosphere lifts it into view by about that much. The Sun and Moon get an
# extra half-diameter on top, since what people watch for is the upper limb
# clearing the horizon rather than the centre.
_REFRACTION = -0.5667
_HORIZON = {"sun": -0.8333, "moon": 0.125}


# ------------------------------------------------------- the namespace
# Which path segments are objects. The index exists so routing can answer
# "is /Venus a thing?" without running any ephemeris, and it is built from
# exactly the catalogues sky.resolve_target() scans, in exactly the order it
# scans them. Anything this says is an object, resolve_target() can resolve;
# anything it rejects, resolve_target() would reject too. Two lists that
# disagree would 404 pages that work and offer pages that do not.
#
# Paths already routed to something else. Reserved here as well as by route
# order, because a name colliding with one of these should never even be
# offered as an object.
RESERVED = frozenset("""
    stats help usage catalog legend demo about complete healthz robots.txt
    sitemap.xml llms.txt favicon.ico animate beacon events sphere gif-capacity
    milkyway.json apple-touch-icon.png vendor horizon.png animate.gif
""".split())

_index_cache = None


def _norm(s):
    """Fold to something a URL can carry: no accents, no case, no
    punctuation. This is what makes /venus, /VENUS and /Venus the same page,
    and it is why the accented forms resolve without a separate alias list."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _index():
    """normalised name -> canonical name to hand to resolve_target()."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache

    idx = {}

    def add(name, canonical=None):
        key = _norm(name)
        # First writer wins, matching resolve_target()'s own first-match
        # scan. Without this, a faint NGC object sharing a name with a bright
        # star would silently take the path off it.
        if key and key not in idx and key not in RESERVED:
            idx[key] = canonical or name

    for nm in ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
               "Saturn", "Uranus", "Neptune"):
        add(nm)
    for s in sky._load("stars.json"):
        if s.get("n"):
            add(s["n"])
    for a in sky._load("asterisms.json"):
        add(a["name"])
    for sh in sky._load("showers.json"):
        add(sh["name"])
        # "Perseid" and "Perseids radiant" as well, because people type all
        # three and resolve_target() already accepts them.
        add(sh["name"].rstrip("s"), sh["name"])
        add(sh["name"] + " radiant", sh["name"])
    # Deep sky last, and brightest first within it, so that when two entries
    # share a name the brighter one owns the path. deepsky.json is already
    # magnitude-sorted, but sorting here makes the guarantee explicit rather
    # than inherited -- it is what keeps /M31 on the Andromeda Galaxy rather
    # than on NGC205, which build_deepsky.py also labels M31.
    for o in sorted(sky._load("deepsky.json"), key=lambda o: o["m"]):
        add(o["n"])
        add(o["id"])
        if o.get("cn"):
            add(o["cn"])
    _index_cache = idx
    return idx


def resolve_name(segment):
    """A URL path segment -> the canonical object name, or None.

    Deliberately name-only: no position, no time, no observer. Routing needs
    to know whether a path is an object before it knows where the visitor is.
    """
    if not segment or len(segment) > 64:
        return None
    return _index().get(_norm(segment))


def all_names():
    """Every canonical object name, once each."""
    return sorted(set(_index().values()))


# Faintest a star can be and still deserve its own indexed page. Magnitude 3
# is roughly where a star stops being one somebody could point out and start
# being a catalogue entry, and a page nobody would ever search for is a page
# that dilutes the ones they would.
_SITEMAP_STAR_MAG = 3.0


def sitemap_names():
    """The objects worth submitting to a search engine.

    Not all 1,220. Most of the catalogue is bare NGC numbers whose pages can
    only ever say what type they are and where they sit -- generated text
    with nothing specific in it, which is exactly the thin programmatic
    content search engines demote a whole site for. The pages still exist and
    still work; they are simply not advertised.
    """
    out = {"Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
           "Uranus", "Neptune"}
    out |= {s["n"] for s in sky._load("stars.json")
            if s.get("n") and s["m"] <= _SITEMAP_STAR_MAG}
    out |= {a["name"] for a in sky._load("asterisms.json")}
    out |= {sh["name"] for sh in sky._load("showers.json")}
    # Deep sky only where it has a name people use, or a Messier number.
    for o in sky._load("deepsky.json"):
        if o.get("cn"):
            out.add(o["cn"])
        elif o["n"].startswith("M") and o["n"][1:].isdigit():
            out.add(o["n"])
    return sorted(out)


# ------------------------------------------------------- constellations
# Boundaries are defined in B1875, the equinox Delporte drew them for, so a
# position has to be precessed back before it can be compared against them.
#
# sky.py's own precess() is deliberately a cheap first-order form ("rigorous
# enough" for a chart, in its words) and is not usable here: it is a linear
# expansion with a tan(dec) term, and over the 125 years back to B1875 it
# drifts by arcminutes at mid-declinations and diverges near the poles --
# which is exactly where being slightly wrong hands back the wrong
# constellation. This is the standard rotation instead.
_JD_B1875 = 2405889.25855


def _precess_to_b1875(ra_h, dec_d):
    """J2000 -> B1875, rigorous. (hours, degrees) in and out."""
    T = (_JD_B1875 - 2451545.0) / 36525.0
    # IAU 1976 precession angles, arcseconds -> radians.
    a = math.pi / 180 / 3600
    zeta = (2306.2181 * T + 0.30188 * T ** 2 + 0.017998 * T ** 3) * a
    z = (2306.2181 * T + 1.09468 * T ** 2 + 0.018203 * T ** 3) * a
    theta = (2004.3109 * T - 0.42665 * T ** 2 - 0.041833 * T ** 3) * a
    ra, dec = ra_h * 15 * D, dec_d * D
    x = math.cos(dec) * math.sin(ra + zeta)
    y = (math.cos(theta) * math.cos(dec) * math.cos(ra + zeta)
         - math.sin(theta) * math.sin(dec))
    w = (math.sin(theta) * math.cos(dec) * math.cos(ra + zeta)
         + math.cos(theta) * math.sin(dec))
    return (math.degrees(math.atan2(x, y) + z) / 15.0) % 24, math.degrees(math.asin(w))


# The 88 IAU constellations by their standard three-letter abbreviation.
# Needed because the boundary file speaks in abbreviations and "you will find
# it in Psc" is not a sentence anyone wants to read.
CONSTELLATION_NAMES = {
    "And": "Andromeda", "Ant": "Antlia", "Aps": "Apus", "Aqr": "Aquarius",
    "Aql": "Aquila", "Ara": "Ara", "Ari": "Aries", "Aur": "Auriga",
    "Boo": "Bootes", "Cae": "Caelum", "Cam": "Camelopardalis",
    "Cnc": "Cancer", "CVn": "Canes Venatici", "CMa": "Canis Major",
    "CMi": "Canis Minor", "Cap": "Capricornus", "Car": "Carina",
    "Cas": "Cassiopeia", "Cen": "Centaurus", "Cep": "Cepheus",
    "Cet": "Cetus", "Cha": "Chamaeleon", "Cir": "Circinus",
    "Col": "Columba", "Com": "Coma Berenices", "CrA": "Corona Australis",
    "CrB": "Corona Borealis", "Crv": "Corvus", "Crt": "Crater",
    "Cru": "Crux", "Cyg": "Cygnus", "Del": "Delphinus", "Dor": "Dorado",
    "Dra": "Draco", "Equ": "Equuleus", "Eri": "Eridanus", "For": "Fornax",
    "Gem": "Gemini", "Gru": "Grus", "Her": "Hercules", "Hor": "Horologium",
    "Hya": "Hydra", "Hyi": "Hydrus", "Ind": "Indus", "Lac": "Lacerta",
    "Leo": "Leo", "LMi": "Leo Minor", "Lep": "Lepus", "Lib": "Libra",
    "Lup": "Lupus", "Lyn": "Lynx", "Lyr": "Lyra", "Men": "Mensa",
    "Mic": "Microscopium", "Mon": "Monoceros", "Mus": "Musca",
    "Nor": "Norma", "Oct": "Octans", "Oph": "Ophiuchus", "Ori": "Orion",
    "Pav": "Pavo", "Peg": "Pegasus", "Per": "Perseus", "Phe": "Phoenix",
    "Pic": "Pictor", "Psc": "Pisces", "PsA": "Piscis Austrinus",
    "Pup": "Puppis", "Pyx": "Pyxis", "Ret": "Reticulum", "Sge": "Sagitta",
    "Sgr": "Sagittarius", "Sco": "Scorpius", "Scl": "Sculptor",
    "Sct": "Scutum", "Ser": "Serpens", "Sex": "Sextans", "Tau": "Taurus",
    "Tel": "Telescopium", "Tri": "Triangulum", "TrA": "Triangulum Australe",
    "Tuc": "Tucana", "UMa": "Ursa Major", "UMi": "Ursa Minor",
    "Vel": "Vela", "Vir": "Virgo", "Vol": "Volans", "Vul": "Vulpecula",
}


def constellation_name(ra_h, dec_d):
    """The constellation as a word rather than a code. None if the position
    somehow falls outside every boundary, which it should not."""
    abbr = constellation(ra_h, dec_d)
    return CONSTELLATION_NAMES.get(abbr, abbr)


def constellation(ra_h, dec_d):
    """Which of the 88 constellations this J2000 position falls in, as the
    three-letter abbreviation. None only if the tables are missing a case,
    which they should not be -- the boundaries tile the whole sphere.

    Roman's arrangement is ordered north to south, and the FIRST row a
    position satisfies is the answer; build_constellations.py preserves that
    order for this reason and must not be sorted.
    """
    ra, dec = _precess_to_b1875(ra_h, dec_d)
    for ra_lo, ra_up, de_lo, con in sky._load("constellations.json"):
        if dec >= de_lo and ra_lo <= ra < ra_up:
            return con
    return None


# ------------------------------------------------------- catalogue extras
# Three side files, each keyed to a catalogue the chart already draws from and
# joined at read time. None of them is required: a missing file or a missing
# key means that line of the page does not print, never an error. That is the
# whole reason they are separate files rather than extra columns -- stars.json
# and deepsky.json are what every chart on the site reads, and nothing here
# can change what those contain.

def star_info(hr):
    """Spectral type, distance and duplicity for a star, by HR number.
    {} when we know nothing extra about it."""
    return sky._load("starinfo.json").get(str(hr), {})


def variable_info(hr):
    """Period, epoch and brightness range for a variable star, by HR number.
    {} when the star is not a known variable."""
    return sky._load("variables.json").get(str(hr), {})


def dso_size(dso_id):
    """Angular size in arcminutes for a deep-sky object, by catalogue id
    ("NGC224"). {} when we have no measured size for it.

    Only the well-known Messier objects have one -- see build_dsoinfo.py for
    why there is no catalogue behind this."""
    return sky._load("dsoinfo.json").get(dso_id, {})


# ------------------------------------------------------ rise, transit, set
# The sidereal day is shorter than the solar one, so local sidereal time runs
# fast against the clock by this much. Converting "the object is due south at
# sidereal time X" into "which is 21:47 tonight" is the whole job here.
_SIDEREAL_RATE = 1.00273790935


def _lst(jd, lon):
    return (sky.gmst_hours(jd) + lon / 15.0) % 24


def _horizon_alt(kind):
    return _HORIZON.get(kind, _REFRACTION)


def rise_transit_set(tgt, lat, lon, when_utc):
    """When the object crosses the horizon and when it is highest, for the
    day containing when_utc.

    Returns a dict with utc datetimes, or flags instead:

        {"transit": dt, "rise": dt, "set": dt, "transit_alt": deg}
        {"transit": dt, "transit_alt": deg, "circumpolar": True}
        {"transit": dt, "transit_alt": deg, "never_rises": True}

    Circumpolar and never-rising are not error cases -- at Tromso half the
    catalogue is one or the other for months, and "it never sets" is a more
    useful answer than a missing line.
    """
    kind = tgt.get("kind", "")
    jd0 = sky.julian(when_utc)

    # Declination is what decides the geometry, and for anything outside the
    # solar system it does not move at all over a day. For the Sun, Moon and
    # planets it does, so the position is re-read at the transit time found
    # from the first pass and the answer refined once -- one iteration is
    # enough for everything except the Moon, which gets two.
    def radec(jd):
        if tgt.get("body"):
            b = (sky.moon(jd) if tgt["body"] == "Moon" else
                 sky.sun(jd) if tgt["body"] == "Sun" else
                 sky.planet(tgt["body"], jd))
            return b["ra"], b["dec"]
        return sky.precess(tgt["ra"], tgt["dec"], jd)

    jd_t = jd0
    for _ in range(3 if kind == "moon" else 2):
        ra, dec = radec(jd_t)
        # Hours until the object is next due south, converted from sidereal
        # to solar time.
        delta = (ra - _lst(jd_t, lon)) % 24
        jd_t = jd_t + (delta / 24.0) / _SIDEREAL_RATE

    ra, dec = radec(jd_t)
    transit_alt = 90.0 - abs(lat - dec)
    out = {"transit": _to_utc(jd_t), "transit_alt": round(transit_alt, 1)}

    h0 = _horizon_alt(kind)
    denom = math.cos(lat * D) * math.cos(dec * D)
    if abs(denom) < 1e-9:
        out["circumpolar" if transit_alt > h0 else "never_rises"] = True
        return out
    cos_h = (math.sin(h0 * D) - math.sin(lat * D) * math.sin(dec * D)) / denom
    if cos_h < -1:
        out["circumpolar"] = True
        return out
    if cos_h > 1:
        out["never_rises"] = True
        return out

    # Half the time the object spends above the horizon, in solar hours.
    half = math.degrees(math.acos(cos_h)) / 15.0 / _SIDEREAL_RATE
    out["rise"] = _to_utc(jd_t - half / 24.0)
    out["set"] = _to_utc(jd_t + half / 24.0)
    out["up_hours"] = round(2 * half, 2)
    return out


def _to_utc(jd):
    """Julian day -> naive UTC datetime, matching what the rest of the
    codebase passes around."""
    return dt.datetime(2000, 1, 1, 12) + dt.timedelta(days=jd - 2451545.0)


def _half_day(dec, lat, h0):
    """Hours between an object at declination dec crossing altitude h0 and
    its transit. None when it never reaches h0; math.inf when it never drops
    below it."""
    denom = math.cos(lat * D) * math.cos(dec * D)
    if abs(denom) < 1e-9:
        return math.inf if 90.0 - abs(lat - dec) > h0 else None
    c = (math.sin(h0 * D) - math.sin(lat * D) * math.sin(dec * D)) / denom
    if c < -1:
        return math.inf
    if c > 1:
        return None
    return math.degrees(math.acos(c)) / 15.0 / _SIDEREAL_RATE


def _overlap(a0, a1, b0, b1):
    """Hours two time windows share. Plain numbers, both already in hours
    measured from the same origin."""
    return max(0.0, min(a1, b1) - max(a0, b0))


# ------------------------------------------------- best night of the year
# The inversion: not "where is it tonight" but "when this year should I look".
#
# Done as arithmetic per night rather than by sampling the sky. For anything
# outside the solar system declination is fixed, so the altitude it reaches
# is the same every night of the year -- 90 - |lat - dec|, one number, no
# search. What actually varies is WHEN it gets there relative to darkness,
# and where the Moon is. Both of those are closed form too.
#
# Sampling each night at ten-minute steps instead costs about 200 ms, roughly
# seven times the most expensive thing the service currently does, on every
# uncached object page. This costs a few milliseconds.
_MIN_USEFUL_ALT = 20.0
_ASTRO_DARK = -18.0


def _shower_peak(tgt, lat, lon, start_utc, days):
    """When this shower next peaks, with how well the radiant is placed and
    how much Moon there will be -- the two things that decide whether the
    peak is worth staying up for.

    events.py already computes peak dates from solar longitude, which is the
    right way round: a shower happens when the Earth reaches a point in its
    orbit, not when the radiant is convenient.
    """
    import events as ev_mod                     # local: events imports sky, not us
    jd0 = sky.julian(start_utc)
    name = tgt["name"].replace(" radiant", "")
    for e in ev_mod.meteor_showers(jd0, jd0 + days):
        if not e.get("name", "").lower().startswith(name.lower()[:6]):
            continue
        when = e["when_utc"]
        jd = sky.julian(when)
        ra, dec = sky.precess(tgt["ra"], tgt["dec"], jd)
        # Radiant altitude at local midnight, which is when a shower is
        # normally watched and when the rate quoted for it applies.
        #
        # Local midnight of the peak DATE, not the peak moment offset by the
        # longitude -- the peak can fall at any hour, and measuring from it
        # put the Geminids radiant 10 degrees below the horizon from Zurich
        # on a night when Gemini is nearly overhead.
        local_midnight = sky.julian(dt.datetime(when.year, when.month, when.day)) \
            - lon / 360.0
        alt = sky.altaz(ra, dec, lat, _lst(local_midnight, lon))[0]
        return {"when_utc": when, "transit_alt": round(90.0 - abs(lat - dec), 1),
                "radiant_alt": round(alt, 1),
                "moon_illum": round(sky.moon(jd)["illum"], 2),
                "dark_hours": None, "is_peak": True,
                "zhr": tgt.get("zhr")}
    return None


def best_this_year(tgt, lat, lon, start_utc, days=365):
    """The night in the next year when this object is best placed.

    "Best" is the hours it spends both usefully high and in a genuinely dark
    sky, discounted by moonlight. Returns None for something that never gets
    high enough from this latitude, which is a real answer rather than a
    failure -- plenty of the catalogue never clears 20 degrees from Zurich.
    """
    if tgt.get("kind") in ("sun", "moon"):
        return None                     # neither has a "best night"; they have phases

    # A meteor shower's best night is the night it peaks, and nothing else.
    # Scoring the radiant like an ordinary target finds when that patch of
    # sky is highest in the dark, which for the Perseids is December -- four
    # months after the only night anyone should be out for them. The radiant
    # being well placed matters only once the Earth is actually in the debris.
    if tgt.get("kind") == "radiant":
        return _shower_peak(tgt, lat, lon, start_utc, days)

    fixed = not tgt.get("body")
    best = None
    for n in range(days):
        # Local midnight, near enough: the dark window is centred on it, and
        # working from there keeps a night in one piece instead of split
        # across two calendar dates.
        jd = sky.julian(start_utc) + n - lon / 360.0

        if fixed:
            ra, dec = sky.precess(tgt["ra"], tgt["dec"], jd)
        else:
            b = sky.planet(tgt["body"], jd)
            ra, dec = b["ra"], b["dec"]

        half_up = _half_day(dec, lat, _MIN_USEFUL_ALT)
        if half_up is None:
            continue                    # never gets high enough on this night

        s = sky.sun(jd)
        half_dark = _half_day(s["dec"], lat, _ASTRO_DARK)
        if half_dark is math.inf:
            continue                    # sun never sets far enough: no dark at all
        # Sun's transit is noon; darkness is centred on midnight, half a day
        # away, and runs half_dark either side of it. None means the sun
        # never climbs to -18, so the whole night is astronomically dark.
        dark_half = 12.0 if half_dark is None else 12.0 - half_dark

        # Both windows measured in hours from this jd, via each body's transit.
        obj_transit = ((ra - _lst(jd, lon)) % 24) / _SIDEREAL_RATE
        sun_transit = ((s["ra"] - _lst(jd, lon)) % 24) / _SIDEREAL_RATE
        midnight = sun_transit + 12.0

        hours = 0.0
        for shift in (-24.0, 0.0, 24.0):    # the object may transit either side
            hours += _overlap(obj_transit + shift - (half_up if half_up is not math.inf else 12.0),
                              obj_transit + shift + (half_up if half_up is not math.inf else 12.0),
                              midnight - dark_half, midnight + dark_half)
        if hours <= 0:
            continue

        # Moonlight. Illumination alone, not whether the Moon is up: a full
        # Moon anywhere in the sky washes out a faint galaxy, and computing
        # its rise time per night for a factor this soft is not worth it.
        illum = sky.moon(jd)["illum"]
        transit_alt = 90.0 - abs(lat - dec)
        score = hours * (transit_alt / 90.0) * (1.0 - 0.75 * illum)
        if best is None or score > best["score"]:
            best = {"score": score, "jd": jd, "dark_hours": round(hours, 2),
                    "transit_alt": round(transit_alt, 1),
                    "moon_illum": round(illum, 2),
                    "when_utc": _to_utc(jd)}
    if best:
        best.pop("score")
    return best


# ------------------------------------------------------------ the planets
# Equatorial radii in km. Apparent diameter is the one planet number people
# can act on -- it decides whether a telescope will show a disc or a dot.
_RADIUS_KM = {"Mercury": 2439.7, "Venus": 6051.8, "Mars": 3396.2,
              "Jupiter": 71492.0, "Saturn": 60268.0,
              "Uranus": 25559.0, "Neptune": 24764.0}
_AU_KM = 149597870.7
_AU_LIGHT_MIN = 8.3167

_INNER = ("Mercury", "Venus")

# Saturn's north pole, J2000. Drifts by a few arcminutes per century, far
# below anything that changes how open the rings look.
_SATURN_POLE_RA, _SATURN_POLE_DEC = 40.589, 83.537


def planet_facts(name, jd, lat, lst):
    """The numbers a planet page turns into sentences."""
    b = sky.planet(name, jd)
    out = {"distance_au": round(b["dist"], 3),
           "light_minutes": round(b["dist"] * _AU_LIGHT_MIN, 1),
           "magnitude": round(b["mag"], 2)}

    # Illuminated fraction from the phase angle Sun-planet-Earth. Matters for
    # the inner planets, where Venus can be a thin crescent, and barely at all
    # for the outer ones, which never show us much of a phase.
    out["illuminated"] = round((1 + math.cos(b["phase"] * D)) / 2, 3)
    out["phase_angle"] = round(b["phase"], 1)

    r_km = _RADIUS_KM.get(name)
    if r_km:
        out["apparent_arcsec"] = round(
            2 * math.degrees(math.atan(r_km / (b["dist"] * _AU_KM))) * 3600, 1)

    # How far from the Sun, in the sky. sky.solar_elongation() answers this
    # too but works in the horizontal frame and so needs an observer; the
    # Sun-Earth-planet angle does not depend on where you are standing, so it
    # is computed straight from the equatorial coordinates instead. Same
    # angsep(), given declinations and right ascensions rather than
    # altitudes and azimuths.
    s = sky.sun(jd)
    elong = sky.angsep(b["dec"], b["ra"] * 15, s["dec"], s["ra"] * 15)
    out["elongation"] = round(elong, 1)

    # Which side of the Sun, which is what "morning star" and "evening star"
    # actually mean: east of the Sun sets after it, west of it rises before.
    dra = ((b["ra"] - s["ra"] + 12) % 24) - 12
    out["side"] = "evening" if dra > 0 else "morning"
    if name in _INNER:
        out["lost_in_glare"] = elong < 12

    # Retrograde: is the planet's right ascension decreasing? Measured over a
    # day, which is long enough to beat the noise in the approximate elements
    # and short enough that a stationary point is not smeared over.
    ra_then = sky.planet(name, jd + 1.0)["ra"]
    out["retrograde"] = (((ra_then - b["ra"] + 12) % 24) - 12) < 0

    if name == "Saturn":
        out["ring_angle"] = _saturn_ring_angle(b)
    return out


def _saturn_ring_angle(b):
    """How far the rings are tilted open, in degrees. Zero is edge-on and
    effectively invisible; about 27 is as wide as they ever get.

    This is the Saturnicentric latitude of the Earth -- the angle between our
    line of sight and Saturn's ring plane -- which falls straight out of the
    angle between Saturn's pole and the direction we see the planet from.
    """
    ra, dec = b["ra"] * 15 * D, b["dec"] * D
    pra, pdec = _SATURN_POLE_RA * D, _SATURN_POLE_DEC * D
    sin_b = (math.sin(pdec) * math.sin(dec)
             + math.cos(pdec) * math.cos(dec) * math.cos(pra - ra))
    return round(abs(math.degrees(math.asin(max(-1, min(1, sin_b))))), 1)


# --------------------------------------------------------------- the stars
# Harvard class -> the colour someone actually sees. Deliberately the colour
# and not the temperature: "orange" is what you check against the sky, 4,000 K
# is not.
_CLASS_COLOUR = {"O": "blue", "B": "blue-white", "A": "white",
                 "F": "yellow-white", "G": "yellow", "K": "orange",
                 "M": "red", "C": "deep red", "S": "deep red",
                 "R": "deep red", "N": "deep red", "W": "blue"}

# Yerkes luminosity class -> what kind of star it is. Longest codes first:
# "Iab" and "Ia" both start with "I", and testing "I" first would call every
# supergiant a plain one and every giant a supergiant.
_LUMINOSITY = [("Iab", "supergiant"), ("Ia", "supergiant"), ("Ib", "supergiant"),
               ("VII", "white dwarf"), ("VI", "subdwarf"),
               ("IV", "subgiant"), ("III", "giant"), ("II", "bright giant"),
               ("V", "main-sequence star"), ("I", "supergiant")]

# The older prefix notation BSC5 still uses for a few dozen stars.
_PREFIX = {"sg": "subgiant", "g": "giant", "d": "main-sequence star",
           "c": "supergiant"}


def describe_spectrum(sp):
    """A spectral type as words. "M1-2Ia-Iab" -> "red supergiant".

    None when the string is too odd to read confidently, which is the right
    answer -- a wrong description of a star is worse than no description.
    """
    if not sp:
        return None
    kind = None
    for pre in ("sg", "g", "d", "c"):          # sg before g, same reason as above
        if sp.startswith(pre) and len(sp) > len(pre) and sp[len(pre)] in _CLASS_COLOUR:
            kind = _PREFIX[pre]
            sp = sp[len(pre):]
            break
    colour = _CLASS_COLOUR.get(sp[:1])
    if not colour:
        return None
    if kind is None:
        # Luminosity class is whatever roman numerals appear after the
        # temperature digits, and plenty of entries carry none at all.
        tail = sp[1:]
        for code, word in _LUMINOSITY:
            if code in tail:
                kind = word
                break
    if kind is None:
        return colour + " star"
    return f"{colour} {kind}"


def next_minimum(hr, when_utc):
    """When an eclipsing variable next dims, as a UTC datetime. None unless
    the star is an eclipser with both a period and an epoch on file.

    This is the most satisfying line an object page can carry, because it is
    a real prediction: Algol drops by more than a magnitude every 2.87 days,
    on a schedule fixed since before anyone alive was watching.

    Only eclipsing types (the E family) are handled. For pulsating variables
    the GCVS epoch marks maximum light rather than minimum, and quietly
    reporting one as the other would be wrong in a way nobody would catch.
    """
    rec = variable_info(hr)
    period, epoch = rec.get("period"), rec.get("epoch")
    if not period or not epoch or not str(rec.get("type", "")).startswith("E"):
        return None
    jd = sky.julian(when_utc)
    # GCVS epochs are given as JD - 2400000 in this export.
    epoch_jd = epoch + 2400000.0 if epoch < 100000 else epoch
    n = math.ceil((jd - epoch_jd) / period)
    return _to_utc(epoch_jd + n * period)


def distance_ly(hr):
    """(light years, how confident) or None.

    Confidence is what makes this printable at all. Hipparcos parallaxes are
    good to a fraction of a percent for nearby stars and hopeless for distant
    ones -- Deneb's carries a 56% error -- so the page has to be able to say
    "25 light years", "roughly 600 light years", or nothing, rather than
    stating all three with the same false precision.
    """
    rec = star_info(hr)
    ly, err = rec.get("ly"), rec.get("ly_err")
    if ly is None or err is None:
        return None
    if err <= 10:
        return ly, "good"
    if err <= 35:
        return ly, "rough"
    return ly, "poor"
