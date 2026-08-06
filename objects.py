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
    objects eclipse
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
    # The galaxy we are inside. Added by hand because it is in none of the
    # catalogues -- deepsky.json lists things you point at, and this is the
    # one object that is behind you as well.
    add("Milky Way")
    add("Galactic Centre", "Milky Way")
    add("Galactic Center", "Milky Way")
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
           "Uranus", "Neptune", "Milky Way"}
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


def what_you_need(mag, bortle=None):
    """What it takes to see something this bright, in words.

    None when the magnitude is unknown -- see deepsky.json's "nomag" flag.
    The Revised NGC records no brightness at all for most diffuse nebulae,
    and build_deepsky.py substitutes the catalogue cutoff so they still get
    drawn, which means a magnitude of 11.0 is sometimes measured and
    sometimes a placeholder. Telling someone they need a telescope on the
    strength of a number nobody measured is worse than saying nothing: the
    Rosette and the Veil both carry that placeholder and both are binocular
    targets from a dark sky.

    Thresholds are for extended objects, which is what this is used on.
    They are dimmer to the eye than a star of the same integrated
    magnitude, because that light is spread out rather than concentrated
    into a point.
    """
    if mag is None:
        return None
    # The reader's own sky, when we know it. Offering "naked eye if it is
    # really dark" to somebody under Bortle 8 is not advice, it is the
    # reason people buy binoculars and still see nothing: the equipment was
    # never the limit.
    dark = bortle is None or bortle <= 4
    if mag <= 4.0:
        return "naked eye from a dark sky" if dark else "binoculars from here"
    if mag <= 6.5:
        return ("binoculars, or naked eye if it is really dark" if dark
                else "binoculars, and it will be faint")
    if mag <= 9.0:
        return "binoculars" if dark else "binoculars at least, from here"
    if mag <= 11.0:
        return "a small telescope"
    return "a telescope"


def dso_magnitude(name):
    """The measured magnitude of a deep-sky object, or None when the
    catalogue never recorded one."""
    for o in sky._load("deepsky.json"):
        if name in (o["n"], o.get("cn"), o["id"]):
            return None if o.get("nomag") else o["m"]
    return None


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
# How long a shower stays "this year's" after its peak. The peak is a
# moment; the shower is a night, and the night outlasts the moment.
SHOWER_GRACE_DAYS = 1.0

_MIN_USEFUL_ALT = 20.0
_ASTRO_DARK = -18.0


def best_tonight(tgt, lat, lon, start_utc, min_alt=8.0):
    """The best moment to look at this object tonight, or None.

    "Best" is when it is highest while the sky is genuinely dark, which is
    not the same question next_visible() answers. That one returns the FIRST
    moment an object clears the horizon in a dark sky, which for Saturn was
    13 degrees in the east while the same page said it reaches 46 at 05:19.
    A chart drawn at the first qualifying moment shows the least interesting
    view that qualifies.

    Cheap: the object's transit is a single calculation, the dark window is
    another, and the answer is the transit clamped into that window. An
    object that transits in daylight is best at whichever end of the night
    it is highest, which is the nearer edge of the window to its transit.
    """
    jd0 = sky.julian(start_utc)

    # Tonight's astronomical dark, centred on local midnight.
    s = sky.sun(jd0)
    half_dark = _half_day(s["dec"], lat, _ASTRO_DARK)
    if half_dark is math.inf:
        return None                      # the sun never sets far enough
    dark_half = 12.0 if half_dark is None else 12.0 - half_dark
    if dark_half <= 0:
        return None

    # Local midnight after start_utc, as a julian day.
    #
    # East longitude runs AHEAD of UTC, so local midnight falls EARLIER in
    # UTC -- minus lon/360 of a day, not plus. With the sign the wrong way
    # round the whole dark window shifted east by twice the offset, and
    # Andromeda's "best moment" came out at 03:00 UTC with the Sun 11 degrees
    # below the horizon: bright twilight, and 20 degrees of altitude worse
    # than the genuinely dark hour it should have picked.
    midnight = math.floor(jd0 + 0.5 + lon / 360.0) + 0.5 - lon / 360.0
    if midnight < jd0:
        midnight += 1.0
    dusk, dawn = midnight - dark_half / 24.0, midnight + dark_half / 24.0

    rts = rise_transit_set(tgt, lat, lon, _to_utc(midnight))
    transit = rts.get("transit")
    if transit is None:
        return None
    jd_t = sky.julian(transit)
    # The transit nearest this night, not one a half-day out.
    while jd_t < dusk - 0.5:
        jd_t += 1.0 / _SIDEREAL_RATE
    while jd_t > dawn + 0.5:
        jd_t -= 1.0 / _SIDEREAL_RATE

    best = min(max(jd_t, dusk), dawn)
    ra, dec = (sky.precess(tgt["ra"], tgt["dec"], best) if not tgt.get("body")
               else _body_radec(tgt["body"], best))
    alt = sky.altaz(ra, dec, lat, _lst(best, lon))[0]
    if alt < min_alt:
        return None
    return _to_utc(best)


def _body_radec(body, jd):
    b = (sky.moon(jd) if body == "Moon" else
         sky.sun(jd) if body == "Sun" else sky.planet(body, jd))
    return b["ra"], b["dec"]


def _shower_peak(tgt, lat, lon, start_utc, days):
    """When this shower next peaks, with how well the radiant is placed and
    how much Moon there will be -- the two things that decide whether the
    peak is worth staying up for.

    events.py already computes peak dates from solar longitude, which is the
    right way round: a shower happens when the Earth reaches a point in its
    orbit, not when the radiant is convenient.
    """
    import events as ev_mod                     # local: events imports sky, not us
    # A shower stays "this year's shower" for a day after it peaks rather
    # than rolling to next year the instant the peak passes.
    #
    # The peak is a moment, but the shower is a night, and the night runs
    # past the moment -- a peak at 04:00 is still worth going out for that
    # evening, and someone reading about it over breakfast has not missed
    # it. Without the grace period a card shared hours before the peak, which
    # is exactly when people share it, flips to a date a year away while the
    # shower is still falling.
    #
    # One day, and not the shower's real activity period, because
    # showers.json does not carry one: it records the solar longitude of
    # maximum, the radiant and the rate, and nothing about how long the
    # stream lasts. A real end date would need that column added.
    jd0 = sky.julian(start_utc) - SHOWER_GRACE_DAYS
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
    effectively invisible; about 27 is as wide as they ever get."""
    return round(abs(ring_geometry("Saturn", b)[0]), 1)


# The IAU/WGCCRE north-pole direction of each body, J2000. One table, because
# a planet's rings lie in its equatorial plane and its cloud belts run along
# its parallels of latitude -- both are the same axis seen from here, so both
# come out of the same two numbers.
#
# This is what makes the planets look unlike each other rather than like one
# drawing recoloured: Saturn's pole sits near the ecliptic pole so its rings
# and belts run roughly across the sky's horizontal, while Uranus is tipped 98
# degrees onto its side and we are currently looking almost straight down its
# pole, so its rings show as a near-circle and its banding as bullseyes.
_POLES = {
    "Sun": (286.13, 63.87),
    "Mercury": (281.0103, 61.4155),
    "Venus": (272.76, 67.16),
    "Mars": (317.269, 54.432),
    "Jupiter": (268.057, 64.495),
    "Saturn": (40.589, 83.537),
    "Uranus": (257.311, -15.175),
    "Neptune": (299.36, 43.46),
    # The Moon's axis leans only 1.5 degrees off the ecliptic normal, so the
    # ecliptic pole is within a degree and a half of the truth -- far closer
    # than a 45-column drawing can show. The real lunar pole wanders with
    # the node and would need its own series for no visible gain.
    "Moon": (270.0, 66.56),
}


def pole_geometry(name, b):
    """(sub-Earth latitude, position angle) of a body's axis, in degrees.

    The sub-Earth latitude is which parallel is facing us: 0 means we see the
    equator edge-on and the belts cross as straight lines, 90 means we are
    over the pole and they close into circles. The position angle is where
    the north pole points on the sky, measured from north through east, so it
    is what tips the whole planet over on screen.

    A ring lies in the equatorial plane, so the same pair describes it: the
    ring opening is this latitude, and the ring's long axis lies 90 degrees
    from this position angle.
    """
    pole = _POLES.get(name)
    if pole is None:
        return None
    ra, dec = b["ra"] * 15 * D, b["dec"] * D
    pra, pdec = pole[0] * D, pole[1] * D
    sin_b = (math.sin(pdec) * math.sin(dec)
             + math.cos(pdec) * math.cos(dec) * math.cos(pra - ra))
    lat = math.degrees(math.asin(max(-1, min(1, sin_b))))
    pa = math.degrees(math.atan2(
        math.cos(pdec) * math.sin(pra - ra),
        math.sin(pdec) * math.cos(dec)
        - math.cos(pdec) * math.sin(dec) * math.cos(pra - ra)))
    return round(lat, 1), round(pa % 360, 1)


def ring_geometry(name, b):
    """(opening, position angle) of a planet's rings. The rings sit in the
    equatorial plane, so this is the axis by another name -- kept as its own
    function because "how far open are the rings" is the question the page
    actually asks."""
    if name not in ("Saturn", "Uranus", "Neptune"):
        return None
    return pole_geometry(name, b)


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


# ------------------------------------------------------------- the Moon
# Meeus chapter 47, the principal terms. sky.moon() computes the Moon's
# position and phase but not its distance, and distance is what makes the
# rest of a Moon page possible: how big it looks, whether tonight is a
# supermoon, how far the libration has turned.
_MOON_DIST_TERMS = (
    # (D, M, M', F, coefficient in km)
    (0, 0, 1, 0, -20905355), (2, 0, -1, 0, -3699111), (2, 0, 0, 0, -2955968),
    (0, 0, 2, 0, -569925), (0, 1, 0, 0, 48888), (0, 0, 0, 2, -3149),
    (2, 0, -2, 0, 246158), (2, -1, -1, 0, -152138), (2, 0, 1, 0, -170733),
    (2, -1, 0, 0, -204586), (0, 1, -1, 0, -129620), (1, 0, 0, 0, 108743),
    (0, 1, 1, 0, 104755), (0, 0, 1, -2, 10321), (2, 0, 0, -2, 79661),
    # The next dozen. Fifteen terms left the extremes about 1% short, which
    # is invisible in "384,000 km" but sat right on the perigee threshold
    # below -- the closest approach came out at 360,368 km and no full Moon
    # would ever have been called large.
    (4, 0, -1, 0, -34782), (4, 0, -2, 0, -21636), (2, 1, -1, 0, 24208),
    (2, 1, 0, 0, 30824), (1, 0, -1, 0, -8379), (1, 1, 0, 0, -16675),
    (2, -1, 1, 0, -12831), (2, 0, 2, 0, -10445), (4, 0, 0, 0, -11650),
    (2, 0, -3, 0, 14403), (0, 1, -2, 0, -7003), (2, -1, -2, 0, 10056),
)

# Mean radius in km, and the mean distance the "average" apparent size is
# quoted against.
_MOON_RADIUS_KM = 1737.4


def moon_distance_km(jd):
    """Earth to Moon, centre to centre.

    Accurate to a few hundred kilometres against the full Meeus series,
    which is a hundredth of a percent -- far inside what any sentence on
    these pages claims.
    """
    T = (jd - 2451545.0) / 36525.0
    D = (297.8501921 + 445267.1114034 * T - 0.0018819 * T ** 2) % 360
    M = (357.5291092 + 35999.0502909 * T - 0.0001536 * T ** 2) % 360
    Mp = (134.9633964 + 477198.8675055 * T + 0.0087414 * T ** 2) % 360
    F = (93.2720950 + 483202.0175233 * T - 0.0036539 * T ** 2) % 360
    total = 385000560.0
    for cd, cm, cmp_, cf, coef in _MOON_DIST_TERMS:
        arg = (cd * D + cm * M + cmp_ * Mp + cf * F) * math.pi / 180
        total += coef * math.cos(arg)
    return total / 1000.0


def moon_facts(jd):
    """Distance, apparent size, and whether this is an unusually big or
    small full Moon."""
    km = moon_distance_km(jd)
    # Apparent diameter from the true distance, in arcminutes.
    arcmin = math.degrees(2 * math.atan(_MOON_RADIUS_KM / km)) * 60
    out = {"distance_km": round(km),
           "light_seconds": round(km / 299792.458, 2),
           "apparent_arcmin": round(arcmin, 1)}
    # Perigee is about 356,500 km and apogee about 406,700. The popular
    # "supermoon" threshold is roughly 360,000, which is the top tenth of the
    # range; "micromoon" is the bottom tenth.
    if km < 360000:
        out["extreme"] = "near perigee, so it looks unusually large"
    elif km > 405000:
        out["extreme"] = "near apogee, so it looks unusually small"
    return out


# --------------------------------------------------------- Jupiter's moons
# Meeus chapter 44, the low-precision method: good to a few tenths of a
# Jupiter radius, which is far better than "which side is Io on tonight"
# needs and is the only question a pair of binoculars can ask.
_GALILEAN = (("Io", 1), ("Europa", 2), ("Ganymede", 3), ("Callisto", 4))


def galilean_moons(jd):
    """Where Jupiter's four big moons sit, east or west of the planet.

    This is the observation Galileo made in 1610 and the reason anyone
    points binoculars at Jupiter: four dots in a line that are somewhere
    else the following night.
    """
    d = jd - 2451545.0
    V = (172.65 + 0.00111588 * d) * D
    M = (357.529 + 0.9856003 * d) * D
    N = (20.020 + 0.0830853 * d + 0.329 * math.sin(V)) * D
    J = (66.115 + 0.9025179 * d - 0.329 * math.sin(V)) * D
    A = (1.915 * math.sin(M) + 0.020 * math.sin(2 * M)) * D
    B = (5.555 * math.sin(N) + 0.168 * math.sin(2 * N)) * D
    K = J + A - B
    R = 1.00014 - 0.01671 * math.cos(M) - 0.00014 * math.cos(2 * M)
    r = 5.20872 - 0.25208 * math.cos(N) - 0.00611 * math.cos(2 * N)
    delta = math.sqrt(r * r + R * R - 2 * r * R * math.cos(K))
    psi = math.asin(max(-1, min(1, R / delta * math.sin(K))))

    lam = (34.35 + 0.083091 * d + 0.329 * math.sin(V)) * D + B
    periods = (1.769138, 3.551810, 7.154553, 16.689018)
    us = []
    for i, per in enumerate(periods):
        base = (163.8067, 358.4108, 5.7129, 224.8151)[i]
        rate = (203.4058643, 101.2916334, 50.2345179, 21.4879801)[i]
        u = (base + rate * (d - delta / 173)) * D + psi - B
        us.append(u)
    # Distances from Jupiter's centre in planet radii.
    radii = (5.9057, 9.3966, 14.9883, 26.3627)
    out = []
    for (name, _n), u, rad in zip(_GALILEAN, us, radii):
        # Apparent offset along the line of the moons, which is what an
        # eyepiece shows: positive is west of the planet, negative east.
        x = rad * math.sin(u)
        out.append({"name": name, "offset": round(x, 2),
                    "side": "west" if x > 0 else "east",
                    # In front of or behind the planet, near enough to be
                    # invisible against it.
                    "hidden": abs(x) < 1.0})
    return out


def galilean_line(jd):
    """The four moons as one sentence, in the order an eyepiece shows them."""
    ms = galilean_moons(jd)
    visible = [m for m in ms if not m["hidden"]]
    if not visible:
        return "all four moons are in transit or eclipse tonight"
    west = sorted((m for m in visible if m["side"] == "west"),
                  key=lambda m: -m["offset"])
    east = sorted((m for m in visible if m["side"] == "east"),
                  key=lambda m: m["offset"])
    bits = []
    if west:
        bits.append(", ".join(m["name"] for m in west) + " west")
    if east:
        bits.append(", ".join(m["name"] for m in east) + " east")
    return " and ".join(bits)
