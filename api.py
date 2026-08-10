#!/usr/bin/env python3
"""
One composition layer, three consumers: the CLI, curl, and an agent.

sky.py knows how to draw. This knows how to answer a request — resolve a place,
resolve a time, pick a view, assemble the text, and hand back a structured
version of the same facts for anyone who would rather have JSON.
"""
import copy, datetime as dt, html, json, math, re, unicodedata
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import art
import eclipse as eclipse_map
import minify
import eclipse_page
import sky
import brand
import facts as facts_table
import motion
import objects
from sky import (C, paint, julian, gmst_hours, altaz, angsep, compass, moon_glyph,
                 phase_name, resolve_target, visibility, next_visible,
                 solar_elongation, find_text, find_marker, sky_read, render_linear,
                 sun, moon, planet, sun_arc, sun_events, dark_enough, DSO_LEGEND)
import events as ev_mod

# deepsky.json is pre-filtered to mag 11 at build time (build_deepsky.py), so
# ?dso=1 is a plain on/off toggle rather than a tunable cutoff -- the catalog
# itself is already the curated set.
DSO_LIMIT = 11.0

# 10,567 cities in 155 countries, timezone baked in at build time
# (build_cities.py). Names are normalised, and where a name repeats the most
# prominent city wins — Paris, France before Paris, Texas. Add a country to be
# explicit: "paris,texas" or "springfield,united".
_CITY_INDEX = None

# two-letter US state codes, so "Paris, TX" works like "Paris, Texas"
US_STATES = {
 "al":"alabama","ak":"alaska","az":"arizona","ar":"arkansas","ca":"california",
 "co":"colorado","ct":"connecticut","de":"delaware","fl":"florida","ga":"georgia",
 "hi":"hawaii","id":"idaho","il":"illinois","in":"indiana","ia":"iowa",
 "ks":"kansas","ky":"kentucky","la":"louisiana","me":"maine","md":"maryland",
 "ma":"massachusetts","mi":"michigan","mn":"minnesota","ms":"mississippi",
 "mo":"missouri","mt":"montana","ne":"nebraska","nv":"nevada",
 "nh":"newhampshire","nj":"newjersey","nm":"newmexico","ny":"newyork",
 "nc":"northcarolina","nd":"northdakota","oh":"ohio","ok":"oklahoma",
 "or":"oregon","pa":"pennsylvania","ri":"rhodeisland","sc":"southcarolina",
 "sd":"southdakota","tn":"tennessee","tx":"texas","ut":"utah","vt":"vermont",
 "va":"virginia","wa":"washington","wv":"westvirginia","wi":"wisconsin",
 "wy":"wyoming","dc":"districtofcolumbia",
}

ALIASES = {
    "nyc": "new york", "sf": "san francisco", "la": "los angeles",
    "hk": "hong kong", "cdmx": "mexico city", "sp": "sao paulo",
    "rio": "rio de janeiro", "blr": "bangalore", "bombay": "mumbai",
    "peking": "beijing", "saigon": "ho chi minh city",
    # IATA airport codes people reach for out of habit
    "cph": "copenhagen", "bcn": "barcelona", "ams": "amsterdam",
    "cdg": "paris", "lhr": "london", "fra": "frankfurt",
    "muc": "munich", "dxb": "dubai", "sin": "singapore",
    "ist": "istanbul",
}


# Dark-sky sites are folded into the city index rather than kept beside it,
# so every path a place name already travels -- lookup, "did you mean",
# completion, the coordinate redirect, /stats -- works on them without
# knowing they exist. One shape in, one shape out.
#
# Population zero, which is true and also does the right thing twice: the
# index is ranked most-populous-first, so a real town sharing a name always
# wins the path, and the search dropdown draws them with its smallest dot.
_DARKSKY_POP = 0

# Where a named site sorts in the search bar, as if it were a town of this
# size. Big enough to beat the hamlets it would otherwise lose to, small
# enough that any city somebody would name first still wins.
SPECIAL_PLACE_RANK = 50_000


# Which of the index's entries are places you travel to rather than live in.
# Kept beside the index instead of as a ninth column: a row is unpacked
# strictly into eight names in lookup_place, so widening it breaks that at a
# distance for a flag only the search bar cares about.
_SPECIAL_PLACES = {}


def _place_rows(filename):
    """A hand-authored place file in cities.json's own row shape."""
    try:
        with open(f"{sky.BASE}/{filename}", encoding="utf-8") as f:
            sites = json.load(f).get("sites", [])
    except (OSError, ValueError):
        return []
    return [(s["name"], [s["lat"], s["lon"], s["tz"], "", s.get("country", ""),
                         "", _DARKSKY_POP, s["name"]])
            for s in sites]


def _cities():
    global _CITY_INDEX
    if _CITY_INDEX is None:
        try:
            with open(f"{sky.BASE}/cities.json", encoding="utf-8") as f:
                _CITY_INDEX = json.load(f)
        except (OSError, ValueError):
            _CITY_INDEX = {}
        # Appended, never inserted first: a name that is both a town and a
        # dark-sky site resolves to the town, which is what somebody typing
        # it almost always meant.
        for filename, kind in (("darksky.json", "dark"),
                               ("unesco.json", "unesco")):
            for name, row in _place_rows(filename):
                key = norm_name(name)
                # First file wins a shared name, and dark sky comes first:
                # Mesa Verde is both, and the sky is what this site is for.
                if key in _SPECIAL_PLACES:
                    continue
                _CITY_INDEX.setdefault(key, []).append(row)
                _SPECIAL_PLACES[key] = kind
    return _CITY_INDEX


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def city_matches(spec):
    """Every city answering to this name, most populous first.

    After a comma you can give a country code, a country name, or a state:
        San Francisco, US        San Francisco, United States
        Paris, TX                Paris, Texas
    """
    if not spec:
        return []
    part = [p.strip() for p in spec.split(",")]
    name, where = part[0], (part[1] if len(part) > 1 else None)
    key = norm_name(ALIASES.get(norm_name(name), name))
    hits = _cities().get(key, [])
    if not where:
        return hits
    w = norm_name(where)
    exact, loose = [], []
    for h in hits:
        _lat, _lon, _z, iso2, country, admin, _pop, _disp = h
        if w == iso2 or w == norm_name(admin) or w == norm_name(country):
            exact.append(h)
        elif norm_name(country).startswith(w) or norm_name(admin).startswith(w):
            loose.append(h)
        elif w in US_STATES and US_STATES[w] == norm_name(admin):
            exact.append(h)
    return exact or loose


def label(h):
    """'San Francisco, California, United States' - enough to tell them apart.

    TODO: the admin/city duplicate check only catches exact matches, so a city
    whose admin region shares its name in another language slips through --
    e.g. "Geneva, Genève, Switzerland" (city name is English, canton name is
    French). Worth a looser match here at some point."""
    _lat, _lon, _z, _iso2, country, admin, _pop, disp = h
    bits = [disp]
    if admin and norm_name(admin) != norm_name(disp):
        bits.append(admin)
    bits.append(country)
    return ", ".join(bits)


def suggest(spec, n=6):
    """Near misses, most populous first, for the "don't know that" message."""
    key = norm_name((spec or "").split(",")[0])
    if len(key) < 3:
        return []
    out = []
    for k, v in _cities().items():
        if k.startswith(key) or key in k:
            out.append((-v[0][6], label(v[0])))
    out.sort()
    seen, res = set(), []
    for _pop, lab in out:
        if lab not in seen:
            seen.add(lab); res.append(lab)
        if len(res) >= n:
            break
    return res


COMPLETE_PREFIX_CAP = 24    # matches the client's own cap (SPEC-command-bar.md
                            # #4) -- enforced again here since this is a public
                            # endpoint, not just called from our own JS.


# Population bands for the dropdown's dot. Three, not a continuous scale: the
# dot is 8px across and nobody reads a size ramp at that size, but "one of
# these is the big one" lands instantly. The thresholds are the ordinary
# meanings of the words -- a million is a major city, a hundred thousand is a
# city, below that is a town -- rather than percentiles of the file, which
# would shift every time cities.json is rebuilt.
CITY_BANDS = ((1_000_000, 3), (100_000, 2))


def city_size(pop):
    """1, 2 or 3 for a population: town, city, major city."""
    for floor, band in CITY_BANDS:
        if pop >= floor:
            return band
    return 1


def complete_cities(prefix, n=8, with_pop=False):
    """Up to n canonical city names whose normalized form starts with
    prefix's normalized form, most populous first -- the command bar's
    ghost-completion data source (GET /complete, SPEC-command-bar.md #4).

    Deliberately narrower than suggest(): prefix-only (not suggest()'s
    looser startswith-or-contains "did you mean" matching), and returns the
    bare display name ("New York") rather than suggest()'s disambiguated
    label ("New York, New York, United States") -- a ghost completion is a
    plain continuation of what's already been typed, not a fresh answer.
    Each _cities() bucket is already population-sorted (hits[0] is always
    the most populous), so no per-candidate sort is needed, only across
    buckets."""
    key = norm_name(prefix)[:COMPLETE_PREFIX_CAP]
    if len(key) < 2:
        return []
    out = []
    for k, hits in _cities().items():
        if k.startswith(key):
            # A named site has no population, so ranking on the real number
            # buried it: "Cherry Springs" lost its own name to eight
            # villages called Cherry-something and never appeared at all.
            # Ranking them first was worse -- "new" then offered Newgrange
            # before New York.
            #
            # So they sort as though they were a small city: above the
            # hamlets, below anywhere anyone would name first. This is a
            # sort key and nothing else; the dot the dropdown draws still
            # comes from the real population, which is zero.
            pop = hits[0][6]
            rank = SPECIAL_PLACE_RANK if _SPECIAL_PLACES.get(k) else pop
            out.append((-rank, -pop, hits[0][7]))
    out.sort()
    seen, res = set(), []
    for _rank, negpop, name in out:
        if name not in seen:
            seen.add(name)
            res.append({"name": name, "size": city_size(-negpop),
                        "kind": _SPECIAL_PLACES.get(norm_name(name))}
                       if with_pop else name)
        if len(res) >= n:
            break
    return res

def _nearest_city(lat, lon, prefer_radius_deg=0.5, max_radius_deg=5):
    """The well-known city near (lat, lon), or None beyond max_radius_deg (open
    ocean, poles). Used to give bare coordinates a real IANA timezone instead
    of the DST-blind longitude/15 fallback, and a "near X" hint.

    Within prefer_radius_deg (~55 km) this picks the most populous candidate,
    not the literal closest point -- otherwise a point on the edge of a city
    resolves to whichever small suburb happens to be a few hundred metres
    closer, instead of the city anyone would actually recognise. Both radii
    are small enough that a same-timezone pick is effectively guaranteed.
    Beyond prefer_radius_deg it falls back to strict nearest-point, since at
    that range "most populous" could jump somewhere no longer actually nearby.

    Memoised per 0.1-degree cell: CF-IPLatitude/Longitude are already rounded
    that coarsely before this is called, so repeat visitors from the same area
    cost a dict lookup, not a fresh scan. Keyed on the radii too, not just the
    cell -- every caller used the same defaults until _confident_nearby_city
    started passing a tighter pair, and a bare (lat, lon) key would have
    silently handed that call whichever radii happened to be cached first."""
    key = (round(lat, 1), round(lon, 1), prefer_radius_deg, max_radius_deg)
    hit = _NEAREST_CACHE.get(key)
    if hit is not None:
        return hit or None
    closest, closest_d2 = None, None
    biggest, biggest_pop = None, -1
    cutoff2 = max_radius_deg * max_radius_deg
    prefer2 = prefer_radius_deg * prefer_radius_deg
    coslat = math.cos(math.radians(lat))
    for hits in _cities().values():
        for h in hits:
            hlat, hlon = h[0], h[1]
            dy, dx = hlat - lat, (hlon - lon) * coslat
            d2 = dy * dy + dx * dx
            if d2 <= cutoff2 and (closest_d2 is None or d2 < closest_d2):
                closest, closest_d2 = h, d2
            if d2 <= prefer2 and h[6] > biggest_pop:
                biggest, biggest_pop = h, h[6]
    best = biggest or closest
    if len(_NEAREST_CACHE) >= _NEAREST_MAX:
        _NEAREST_CACHE.clear()
    _NEAREST_CACHE[key] = best
    return best


# Sky brightness from the city list, by Walker's Law in the National Park
# Service form: a city of P people contributes 1.13e7 * P * r^-2.5 nanolamberts
# at r metres. Crude -- plus or minus a Bortle class or two -- but it needs no
# new data, no new licence and no runtime dependency, and it is the model the
# NPS itself used before satellite measurements existed.
#
# The floor is not optional. r^-2.5 runs away as you approach a city, so the
# bare formula puts central Geneva at 14.1 mag/arcsec2 and London at 9.9,
# against a real 17.5-18. Clamping r to the city's own radius -- what you get
# from its population at a plausible density -- fixes exactly the case most
# requests come from, which is somebody standing in a city.
_WALKER_K = 1.13e7
_CITY_DENSITY = 2000.0          # people per square km, for the radius floor
_NATURAL_NL = 60.0              # a genuinely dark sky, about 21.9 mag/arcsec2
_LP_RADIUS_KM = 300.0           # past this a city contributes ~nothing
_BORTLE_MAG = [(21.75, 1), (21.6, 2), (21.3, 3), (20.8, 4),
               (20.1, 5), (19.1, 6), (18.0, 7), (17.5, 8)]
_BORTLE_CACHE = {}


def sky_brightness(lat, lon):
    """(mag/arcsec2, Bortle) for a place, estimated. Memoised per 0.1-degree
    cell, the same grain the geo headers already round to."""
    # Computed at the cell centre, not at the caller's exact point. The
    # memo is per 0.1 degree, and Walker's Law varies enough over that --
    # 2 km is 0.5 mag near a town -- that whoever asked first was deciding
    # the answer for everyone else in the cell. /46.42,5.90 reported Bortle
    # 5 and /46.40,5.90 reported 6, for the same place, depending only on
    # which had been looked up first since the process started.
    key = (round(lat, 1), round(lon, 1))
    hit = _BORTLE_CACHE.get(key)
    if hit:
        return hit
    lat, lon = key
    total = 0.0
    coslat = math.cos(math.radians(lat))
    for hits in _cities().values():
        for h in hits:
            pop = h[6]
            if not pop:
                continue
            dy = (h[0] - lat) * 111.32
            dx = (h[1] - lon) * 111.32 * coslat
            r = math.hypot(dy, dx)
            if r > _LP_RADIUS_KM:
                continue
            own = math.sqrt(pop / _CITY_DENSITY / math.pi)   # its own radius
            total += _WALKER_K * pop * (max(r, own) * 1000.0) ** -2.5
    mag = 21.9 - 2.5 * math.log10((total + _NATURAL_NL) / _NATURAL_NL)
    bortle = next((b for lim, b in _BORTLE_MAG if mag >= lim), 9)
    if len(_BORTLE_CACHE) >= _NEAREST_MAX:
        _BORTLE_CACHE.clear()
    _BORTLE_CACHE[key] = (mag, bortle)
    return mag, bortle


# The faintest contour still visible under a given sky, or 0 for none at
# all. A floor rather than a count, because the contours are nested and
# wildly unequal in area: the outer one covers 15% of the sky and the
# brightest 0.09%, so "show the top two levels" shows essentially nothing.
# Expressed this way the mapping says what it means -- how far down into the
# faint outer band you can still see.
#
#   floor 1  the whole band, 15% of the sky
#   floor 2  3.7%      floor 3  1.4%      floor 4  0.35%
#
# Roughly: obvious and structured to Bortle 3, clearly there at 4, washed
# out at 5, a faint patch near the zenith at 6, essentially gone by 7.
_BORTLE_FLOOR = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 4, 8: 0, 9: 0}


# What each contour floor means in words. The band is drawn from a density
# grid with five levels, so "how much of it you get" is the honest answer to
# whether you can see it -- not a yes or no, and not an altitude.
_MILKYWAY_SHOWS = {
    0: "too bright, the band does not show",
    1: "the whole band, structure and all",
    2: "most of the band, the faintest parts washed out",
    3: "the brighter parts only",
    4: "the core only, and faintly",
    5: "the core only, and faintly",
}


def milkyway_floor(lat, lon):
    return _BORTLE_FLOOR[sky_brightness(lat, lon)[1]]


def _milkyway_floor_now(lat, lon, sun_alt):
    """The same, with twilight raising the floor. A dark site still shows
    nothing while the sky is bright, and the band comes up through the last
    of the twilight rather than switching on at a threshold."""
    if sun_alt > -12:
        return 0
    floor = milkyway_floor(lat, lon)
    if not floor:
        return 0
    if sun_alt > -15:
        floor += 2
    elif sun_alt > -18:
        floor += 1
    return 0 if floor > 5 else floor


def sky_note(lat, lon):
    """One short clause for the chart's top line: how dark it is here.

    "Bortle ~8", not "Bortle 8 est. (Zürich)". The estimate is crude and has
    to say so, but the tilde says it in one character where "est." spent
    four, and the city that spent twelve more was answering a question
    nobody had asked on this line -- it is the reader's own place, and the
    prose below the chart still names the city when the Milky Way is
    missing because of it."""
    _mag, b = sky_brightness(lat, lon)
    return f"Bortle ~{b}"


# How far out a city can still honestly be called "here". Derived from its
# own population rather than fixed, because cities are not one size: a flat
# 55 km claimed Geneva for a spot 31 km up in the Jura, which is a different
# town, a different valley and -- now that the chart says so -- a sky three
# and a half magnitudes darker, Bortle 5 against Geneva's 9. The same 55 km
# is entirely fair for London, which really is that big.
#
# sqrt(pop / density / pi) is the radius of a disc holding that many people
# at _CITY_DENSITY, the same figure the light-pollution estimate uses. 1.4x
# for the suburbs the population count tends to miss, and a 4 km floor so a
# village does not shrink to a point.
_CITY_CLAIM_MARGIN = 1.4
_CITY_CLAIM_MIN_KM = 4.0


def _city_radius_km(pop):
    return math.sqrt(max(pop, 1) / _CITY_DENSITY / math.pi)


def place_words(p):
    """The place as a phrase, for a title or a sentence.

    A named place is simply its name. A bare pair of coordinates is not a
    phrase -- "what's coming up over 46.00,8.90" reads as a spreadsheet cell
    dropped into a sentence -- so it gets the degrees the terminal header
    already prints for the same place, and the "near X" hint, which is the
    only thing identifying a bare pair of numbers to a person.

    This is the case a browser cannot be redirected out of: /46.00,8.90 sits
    in a valley that is not inside any city, and _confident_nearby_city
    rightly refuses to claim it is Lugano. So the page has to say something
    sensible about coordinates rather than assume it never sees any.
    """
    if not LATLON.match(p.name):
        return p.name
    words = (f"{abs(p.lat):.2f}\u00b0{'N' if p.lat >= 0 else 'S'} "
             f"{abs(p.lon):.2f}\u00b0{'E' if p.lon >= 0 else 'W'}")
    near = getattr(p, "near", None)
    # The city, not the whole administrative path. The terminal header has
    # room for "near Monza, Lombardy, Italy"; a page title read in a browser
    # tab does not, and the province adds nothing to somebody trying to work
    # out roughly where this is.
    return f"{words}, near {near.split(',')[0]}" if near else words


def _confident_nearby_city(lat, lon):
    """The city these coordinates are actually *in*, or None.

    Distinct from _nearest_city's own up-to-550 km fallback, which only ever
    backs a soft "near X" hint -- this one replaces the coordinates in the
    URL and in everything computed from them, so it has to be a claim worth
    making rather than the closest thing on the list."""
    hit = _nearest_city(lat, lon, prefer_radius_deg=0.5, max_radius_deg=1.0)
    if not hit:
        return None
    dy = (hit[0] - lat) * 111.32
    dx = (hit[1] - lon) * 111.32 * math.cos(math.radians(lat))
    reach = max(_city_radius_km(hit[6]) * _CITY_CLAIM_MARGIN, _CITY_CLAIM_MIN_KM)
    return hit[7] if math.hypot(dy, dx) <= reach else None


_NEAREST_CACHE = {}
_NEAREST_MAX = 4000

LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

TIME_GRAIN = 300          # seconds; matches the night render bucket
TIME_WINDOW_DAYS = 730    # +/- 2 years is generous for "what will the sky do"


def quantise_time(when, now=None):
    """?t= is the one parameter a client can vary without limit, which made it a
    free cache-miss generator. Snap to the render grain and clamp to a window:
    the key space goes from unbounded to about 420k moments, and every request
    inside a 5-minute grain shares an entry. Returns None if out of range."""
    if when is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if abs((when - now).days) > TIME_WINDOW_DAYS:
        return None
    epoch = dt.datetime(2000, 1, 1)
    secs = (when - epoch).total_seconds()
    return epoch + dt.timedelta(seconds=(secs // TIME_GRAIN) * TIME_GRAIN)


class Place:
    def __init__(self, name, lat, lon, zone=None, near=None):
        self.name, self.lat, self.lon, self.zone = name, lat, lon, zone
        self.near = near   # "Geneva, Switzerland" if this is bare coordinates
                            # resolved to a nearby known city, else None

    def offset(self, when_utc):
        """Hours east of UTC at that instant. Real DST for named zones;
        longitude/15 as an honest approximation for bare coordinates."""
        if self.zone:
            try:
                off = when_utc.replace(tzinfo=dt.timezone.utc)\
                              .astimezone(ZoneInfo(self.zone)).utcoffset()
                return off.total_seconds() / 3600
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return round(self.lon / 15.0)

    @property
    def slug(self):
        import unicodedata
        s = unicodedata.normalize("NFKD", self.name)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return s.replace(" ", "")


def lookup_place(spec):
    """A city name or 'lat,lon' -> Place. None if we simply do not know it,
    so callers can 404 instead of silently showing somebody else's sky."""
    if not spec:
        return None
    m = LATLON.match(spec)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            # Snap to 0.1 deg (~11 km). Nobody can tell 11 km of parallax apart on
            # a text chart, and it turns 648 million reachable cache keys into
            # 6.5 million — so coordinates stop being a cache-busting surface.
            lat, lon = round(lat, 1), round(lon, 1)
            # Same nearest-city lookup resolve_place's fallback branch uses --
            # bare coordinates get a real IANA timezone and a "near X" hint
            # whether they arrived by typing lat,lon directly or by IP
            # fallback. Without this, re-navigating through a coordinate
            # place's own slug (e.g. the animate button's live-preview URL)
            # silently lost the hint on the second request.
            near = _nearest_city(lat, lon)
            zone = near[2] if near else None
            return Place(f"{lat:.2f},{lon:.2f}", lat, lon, zone,
                        label(near) if near else None)
        return None
    hits = city_matches(spec)
    if hits:
        lat, lon, zone, _iso2, _country, _admin, _pop, display = hits[0]
        return Place(display, lat, lon, zone)
    return None


def resolve_place(spec, fallback=None):
    """As above, but always yields something: spec, then CDN geo, then Zurich.

    Fallback coordinates keep the coordinates as the displayed name — this is
    still "47.38,8.54", not silently swapped for a city — but borrow the
    nearest known city's real timezone so the clock shown is actually right,
    and carry that city's name along as a "near X" hint."""
    p = lookup_place(spec)
    if p:
        return p
    if fallback:
        lat, lon = fallback
        near = _nearest_city(lat, lon)
        zone = near[2] if near else None
        return Place(f"{lat:.2f},{lon:.2f}", lat, lon, zone,
                     label(near) if near else None)
    return Place("Zurich", 47.3769, 8.5417, "Europe/Zurich")


class Request:
    def __init__(self, place=None, when=None, view="horizon", facing=None, span=None,
                 find=None, iss=False, lines=True, color=True, fallback=None,
                 tle=None, now=None, night=False, width=None, dso=False, quadrant=None,
                 nodso=False, panel=False, nogolden=False, links=False):
        self.place = resolve_place(place, fallback)
        self.view, self.facing, self.span = view, facing, span
        self.find, self.iss, self.lines, self.color = find, iss, lines, color
        self.night = night
        # ?panel=1 -- put the zenith inset + prose text beside the horizon
        # chart instead of below it. Never inferred from width: the browser
        # auto-fit JS is the only thing that ever sets this, so a CLI/curl
        # request at any width renders exactly as it always has unless
        # someone explicitly asks for it too.
        self.panel = panel
        # Bounded to a single letter (or None) here, before it ever reaches a
        # cache key -- otherwise arbitrary ?quadrant= garbage would each mint
        # its own cache entry, the same free-cache-miss surface ?w= and ?t=
        # are already guarded against elsewhere in this class.
        raw_quadrant = (quadrant or "").strip().upper()
        self.quadrant = raw_quadrant if re.fullmatch(r"[A-Z]", raw_quadrant) else None
        # Whether the grid overlay itself should be drawn at all -- distinct
        # from self.quadrant (which stays None until a real letter validates)
        # so a bare ?quadrant (asking to see the grid, no letter chosen yet)
        # still turns the overlay on. Without this, every plain view (the
        # home page, a bare `curl skymap.sh/Tokyo`) drew the lettered grid
        # unconditionally, whether anyone asked for it or not.
        self.quadrant_requested = quadrant is not None
        # A quadrant crop with nothing but stars is often near-empty -- the
        # whole point of zooming in is to reveal more, so asking for a
        # quadrant turns the deep-sky layer on too, even before a specific
        # letter is picked (bare ?quadrant, showing the grid to choose from).
        # That's why this checks the *raw* argument (quadrant is not None)
        # rather than self.quadrant -- a blank or not-yet-chosen quadrant
        # request should still switch dso on. ?nodso=1 is the explicit
        # opt-out of that implication -- crop to the quadrant grid without
        # the deep-sky overlay, used by the 'd' keyboard shortcut to stay
        # independently toggleable even while the grid is up.
        self.nodso = nodso
        self.dso = (dso or (quadrant is not None)) and not nodso
        # The golden-hour layer on the day view: the band across the chart,
        # its times, and the light/shadow prose. On by default -- it is the
        # reason to look at a daylight chart at all -- so the parameter is
        # the opt-out, which also keeps the plain URL free of it and every
        # existing link rendering the fuller view rather than the older one.
        self.golden = not nogolden
        # Anchors on an animation frame's labels. Off by default and asked
        # for one frame at a time, because a run is 144 frames and every
        # label in every one of them would be an anchor -- markup the page
        # rebuilds six times a second and nobody can click while it moves.
        # The page turns it on for the frame it has paused on, which is the
        # only frame anybody can reach. The still chart is unaffected: it has
        # had links all along and never asks for this.
        self.links = links
        self.tle = tle
        # clamped once, here, so it's already canonical by the time it ever
        # reaches a cache key -- otherwise every distinct raw ?w= value before
        # clamping would be its own cache entry even if they render identically
        self.width = (max(sky.CHART_WIDTH_MIN,
                          min(sky.CHART_WIDTH_MAX, int(width)))
                      if width else None)
        now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        when = quantise_time(when, now)
        # Distinct from when_local/when_utc themselves (which always hold a
        # real moment, "now" by default) -- this is what _png_url uses to
        # decide whether a picked ?t= needs to travel with the "Share as a
        # PNG" link at all, or whether the link should keep tracking
        # whatever's actually current.
        self.when_explicit = when is not None
        if when:                                     # local wall clock at that place
            self.when_local = when
            self.when_utc = when - dt.timedelta(hours=self.place.offset(now))
        else:
            self.when_utc = now
            self.when_local = now + dt.timedelta(hours=self.place.offset(now))
        self.tz = self.place.offset(self.when_utc)

    def sized(self, width, panel):
        """A copy of this Request at a different chart width.

        at() below is the other cheap-copy helper, but it exists for
        animation and deliberately drops find/iss. The width ladder needs
        the opposite: the same view, the same target, the same moment, only
        rendered at another column count. Shallow -- place and tle are
        resolved, read-only data and are meant to be shared, not re-derived
        once per rung."""
        r2 = copy.copy(self)
        r2.width = max(sky.CHART_WIDTH_MIN, min(sky.CHART_WIDTH_MAX, int(width)))
        r2.panel = panel
        return r2

    def at(self, when_utc):
        """A cheap copy of this Request at a different instant, reusing the
        already-resolved place instead of re-running geo/nearest-city lookup.
        Used by animation, which needs the same place at ~100 different times."""
        r2 = Request.__new__(Request)
        r2.place = self.place
        r2.view, r2.facing, r2.span = self.view, self.facing, self.span
        r2.find, r2.iss, r2.lines, r2.color = None, False, self.lines, self.color
        r2.night, r2.tle, r2.width = self.night, None, self.width
        r2.dso, r2.quadrant = self.dso, self.quadrant
        r2.quadrant_requested, r2.nodso = self.quadrant_requested, self.nodso
        r2.panel, r2.golden = self.panel, self.golden
        r2.links = self.links
        r2.when_utc = when_utc
        r2.when_local = when_utc + dt.timedelta(hours=self.place.offset(when_utc))
        r2.tz = self.place.offset(when_utc)
        r2.when_explicit = True
        return r2


class Result:
    def __init__(self, text, data, status=200):
        self.text, self.data, self.status = text, data, status


# ---------------------------------------------------------------- helpers
def _footer(p, c):
    return (paint("  Follow ", C.MUTE, c) +
            paint(brand.AT_HANDLE, "\033[38;5;117m", c) +
            paint(f" for {brand.SITE} updates", C.MUTE, c))


def strip_footer_line(text):
    """Removes _footer's "Follow @skymapsh..." line from an already-
    composed render -- used only by server.py's HTML branch. compose()'s
    output is cached once and reused for every output mode (plain-text,
    JSON, HTML, PNG -- see server.py's _cached docstring), so this can't
    live inside compose() itself without splitting that cache in two; doing
    it here, after the shared render, keeps curl/CLI output unchanged and
    only touches what the browser actually receives. The header's nav row
    carries the same invitation as icon links instead (see header_html)."""
    # Compared with the indentation stripped off both sides, not exactly.
    # _footer writes the line with the chart's two-space left margin, and
    # this used to match on that whole string -- so once the object page
    # started taking that margin off its prose (strip_prose_indent, which
    # runs before this on that one route) the marker silently stopped
    # matching and the footer reappeared at the bottom of every object page.
    # The indent is layout; the sentence is the thing being matched.
    marker = _footer(None, False).strip()
    lines = text.split("\n")
    out, skip_blank = [], False
    for line in lines:
        if strip_ansi(line).strip() == marker:
            skip_blank = True
            continue
        if skip_blank and line == "":
            skip_blank = False
            continue
        out.append(line)
    return "\n".join(out)


def _strip_prose_block(text, raw_sentence, wrap_width=76, prefix="  "):
    """Removes one logical sentence from an already-composed render, even
    though textwrap.wrap() may have split it across several physical lines
    with no blank line in between (unlike strip_footer_line's target, this
    can run right up against the next sentence) -- reconstructs the same
    wrap independently to know exactly how many lines to drop, then matches
    on strip_ansi'd content so colour doesn't matter. raw_sentence already
    including its own "  " prefix (never wrapped, e.g. the PNG share line)
    should pass prefix="" -- wrap_width is irrelevant there since
    textwrap.wrap on a string with no spaces to break at just returns it
    whole either way, but skipping it avoids the pretence. No-op (returns
    text unchanged) if raw_sentence is falsy or the block isn't present --
    find/disc views don't have every line every other view does."""
    if not raw_sentence:
        return text
    import textwrap
    target = [prefix + w for w in textwrap.wrap(raw_sentence, wrap_width)] \
        if prefix else [raw_sentence]
    if not target:
        return text
    lines = text.split("\n")
    n = len(target)
    for i in range(len(lines) - n + 1):
        if all(strip_ansi(lines[i + j]) == target[j] for j in range(n)):
            return "\n".join(lines[:i] + lines[i + n:])
    return text


def strip_duplicate_ui_lines(text, r, res, base_url):
    """Removes prose lines that duplicate a real UI element elsewhere on
    the browser page -- used only by server.py's HTML branch, same "post-
    process after the shared compose()" reasoning as strip_footer_line
    (see its docstring), for the same reason: curl/JSON/PNG output must
    keep every line, only the browser page has the duplicate.

    - "Coming up: ..." duplicates the coming-up card at the top of the page.
    - "Share as a PNG: <url>" duplicates the drawer's own share button.
    - "See tonight's chart now: curl '...'" (daytime view only) hands a
      browser reader a shell command to run themselves, when they can just
      click through instead -- useful on a terminal, odd on a page.

    res.data carries everything needed to reconstruct each one exactly as
    composed: "coming_up" is the already-built teaser sentence, and
    "first_stars" (present only on the daytime view) is first's local ISO
    timestamp with the same tz offset baked in that built the original
    line, so re-parsing it reproduces tl without recomputing sun_events.
    base_url must be the same real host text already substituted into
    text's own {base_url} placeholders (server.py's page_text) -- _png_url
    on its own still has the bare placeholder in it, which would never
    match the already-substituted line actually sitting in text."""
    text = _strip_prose_block(text, res.data.get("coming_up"))
    png_url = _png_url(r).replace("{base_url}", base_url)
    text = _strip_prose_block(text, f"  Share as a PNG: {png_url}", prefix="")
    first_stars = res.data.get("first_stars")
    if first_stars:
        tl = dt.datetime.fromisoformat(first_stars)
        text = _strip_prose_block(
            text, f"See tonight's chart now:  "
                  f"curl 'skymap.sh/{r.place.slug}?t={tl:%Y-%m-%dT%H:%M}'")
    return text


def _bodies_json(st):
    out = []
    for b in st["up"]:
        out.append(dict(name=b["name"], alt=round(b["alt"], 1),
                        az=round(b["az"], 1), compass=compass(b["az"]),
                        mag=round(b["mag"], 2) if b.get("mag") is not None else None))
    return sorted(out, key=lambda x: -x["alt"])


def _pass_json(track):
    if not track:
        return None
    pk = max(track, key=lambda p: p[1])
    return dict(rise_min=round(track[0][0], 1), rise_az=round(track[0][2]),
                rise_compass=compass(track[0][2]), peak_alt=round(pk[1]),
                peak_compass=compass(pk[2]), set_min=round(track[-1][0], 1),
                set_compass=compass(track[-1][2]))


# --- next_visible memo -------------------------------------------------------
# next_visible() scans up to 40 days at 10-minute steps: 68 ms, the most
# expensive thing the service does, and trivially repeatable by a client.
#
# It is safe to share across nearby requests because of one property: the search
# returns the FIRST window after its start time. If a result computed from an
# earlier start is still in the future, then nothing opened between that earlier
# start and it — so it is also the first window after *now*. If it has already
# passed, we recompute. That makes the cache provably correct rather than
# merely close enough.
#
# Location is part of the key at 1 deg (~111 km), which shifts rise times by a
# couple of minutes at most — inside the rounding we already print.
_NV_MAX = 4000
_nv = {}
_nv_hits = _nv_misses = 0


def next_visible_cached(tgt, lat, lon, start_utc, days=40):
    global _nv_hits, _nv_misses
    # days is in the key: "is it up tonight" and "is it up within forty
    # nights" are different questions with different answers, and a cache
    # that confused them would answer one with the other.
    key = (tgt["name"], round(lat), round(lon),
           int(start_utc.timestamp() // 3600), days)
    hit = _nv.get(key)
    if hit is not None:
        w, a, z = hit
        if w is None or w > start_utc:          # still the first window ahead
            _nv_hits += 1
            return hit
    _nv_misses += 1
    out = next_visible(tgt, lat, lon, start_utc, days=days)
    if len(_nv) >= _NV_MAX:
        _nv.clear()
    _nv[key] = out
    return out


def nv_stats():
    t = _nv_hits + _nv_misses
    return dict(entries=len(_nv), hits=_nv_hits, misses=_nv_misses,
                hitrate=round(100 * _nv_hits / t, 1) if t else None)


_NAMED_PLACES = None


def named_places():
    """The two hand-authored place files, as (name, lat, lon).

    Eighty-odd between them, which is why every one of them can be asked
    rather than a few picked by latitude and hoped about.
    """
    global _NAMED_PLACES
    if _NAMED_PLACES is None:
        _NAMED_PLACES = [(name, row[0], row[1])
                         for f in ("darksky.json", "unesco.json")
                         for name, row in _place_rows(f)]
    return _NAMED_PLACES


def _km_apart(lat1, lon1, lat2, lon2):
    """Flat-earth kilometres. Good to a percent or so at these distances,
    and this is deciding which of two deserts to name."""
    dy = (lat2 - lat1) * 111.32
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


# How the sentence opens. Shared with link_clears_places, which finds it
# again in the rendered chart to know where the place names start.
CLEARS_LEAD = "It clears the horizon"

WHERE_SWEEP = 10                # degrees of latitude in the coarse pass
WHERE_REFINE = 3                # and in the pass that backs up over the edge
WHERE_LIMIT = 80                # no answer worth giving past here
WHERE_SHOWN = 2                 # places named
WHERE_NIGHT = 1                 # days: this night, not the next forty


def _lat_label(lat):
    return f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'}"


def where_it_clears(tgt, p, start_utc):
    """Where this is up on the night the page is about, when it is not up
    here.

    The night is the whole point, and getting it wrong is how this first
    shipped: it asked whether each candidate had a window within forty
    nights, which is the question the line above it answers about the
    reader's own latitude. Cevennes passed on a window thirty-nine nights
    later, so a page about a conjunction in May recommended somewhere the
    conjunction had long finished. Somewhere you cannot see it tonight is
    not somewhere to go tonight.

    Nor is the answer a half of the meridian. Saturn on that May night was
    up between 10 and 40 degrees south and nowhere else: too far north and
    it never rises into darkness, too far south and it never rises at all.
    So the sweep reads the whole meridian and returns the band the reader is
    nearest, open only where it really does run to the pole.

    Then a place or two to put a name to it, inside the band, nearest first,
    and each one asked the same question rather than assumed from its
    latitude -- a site's longitude decides whether the window lands in its
    night or its afternoon.

    Returns {"near", "far", "open", "south", "places"}, or None on a night
    when there is nowhere on Earth to send anybody.
    """
    def works(lat):
        return next_visible_cached(tgt, lat, p.lon, start_utc,
                                   days=WHERE_NIGHT)[0] is not None

    lats = list(range(WHERE_LIMIT, -WHERE_LIMIT - 1, -WHERE_SWEEP))
    runs, cur = [], []
    for l in lats:
        if works(l):
            cur.append(l)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return None

    run = min(runs, key=lambda r: min(abs(l - p.lat) for l in r))
    near = min(run, key=lambda l: abs(l - p.lat))
    far = max(run, key=lambda l: abs(l - p.lat))
    south = near < p.lat
    # The sweep overshoots the near edge by up to ten degrees, which is
    # Zurich to Sicily. Walk back over the ground it skipped, keeping the
    # last latitude that still works, so the number quoted is one the search
    # actually returned rather than one it stepped over.
    step = WHERE_REFINE if south else -WHERE_REFINE
    probe = near + step
    while abs(probe - near) < WHERE_SWEEP and abs(probe) <= WHERE_LIMIT:
        if not works(probe):
            break
        near = probe
        probe += step
    # Open only where the run really does reach the end of the sweep. near is
    # the edge facing the reader, far the one behind it, so going south the
    # band runs down from near and going north it runs up from it.
    open_far = abs(far) >= WHERE_LIMIT
    if south:
        lo, hi = (-90.0 if open_far else far), near
    else:
        lo, hi = near, (90.0 if open_far else far)

    places = []
    for name, slat, slon in sorted(
            named_places(), key=lambda s: _km_apart(p.lat, p.lon, s[1], s[2])):
        if not lo <= slat <= hi:
            continue
        if next_visible_cached(tgt, slat, slon, start_utc,
                               days=WHERE_NIGHT)[0] is None:
            continue
        places.append(name)
        if len(places) == WHERE_SHOWN:
            break
    return dict(near=near, far=far, open=open_far, south=south, places=places)


def where_it_clears_line(got):
    """That, as the sentence the page prints. "" when there is nowhere to
    point at, so the caller can simply not print a line."""
    if not got:
        return ""
    # "About", and meant: the sweep lands within three degrees of the near
    # edge, and the far one is the last latitude tried rather than the last
    # that works. Both are inside the band, so the claim errs small.
    if got["open"]:
        where = (f"{'south' if got['south'] else 'north'} of about "
                 f"{_lat_label(got['near'])}")
    else:
        where = (f"between about {_lat_label(got['near'])} and "
                 f"{_lat_label(got['far'])}")
    line = f"{CLEARS_LEAD} {where}"
    return line + (f": {' or '.join(got['places'])}." if got["places"]
                   else " that night.")


# ---------------------------------------------------------------- find view
def _compose_find(r):
    p, c = r.place, r.color
    jd = julian(r.when_utc); lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    tgt = resolve_target(r.find, jd, p.lat, lst)
    if tgt is None:
        txt = (f"\n  Don't know '{r.find}'.\n"
               f"  Try a planet, the Sun, the Moon, a named star (Vega, Altair),\n"
               f"  an asterism (Big Dipper, Orion's Belt, Teapot), or a deep-sky\n"
               f"  object (M31, Andromeda Galaxy, Ring Nebula).\n")
        return Result(txt, dict(error="unknown_target", query=r.find), 404)

    ok, why = visibility(tgt, jd, p.lat, lst)
    shown_utc, note = r.when_utc, None
    data = dict(place=p.name, lat=p.lat, lon=p.lon,
                target=tgt["name"], kind=tgt["kind"], visible=ok, reason=why)

    # now or then, by whether a time was picked -- a chart headed 12 Aug
    # cannot claim the present tense for next week.
    when_word = "then" if r.when_explicit else "now"
    status = f"visible {when_word}"
    if not ok:
        w, a2, z2 = next_visible_cached(tgt, p.lat, p.lon, r.when_utc)
        if w is None:
            el = solar_elongation(tgt, jd, p.lat, lst)
            lines = [f"\n  {tgt['name']} is not visible from {p.name}: {why}."]
            data.update(next_visible=None, solar_elongation=round(el, 1))
            if el < 20:
                lines.append(f"  It is only {el:.0f}° from the Sun: too deep "
                             f"in the glare, and it stays that way for "
                             f"weeks.\n")
            else:
                # Deep in the glare there is nowhere to send anybody, so the
                # sentence above is the whole answer. Merely below this
                # horizon is a different matter: somewhere else it is up.
                import textwrap
                lines.append("  No window in the next 40 days from this "
                             "latitude.")
                got = where_it_clears(tgt, p, r.when_utc)
                far = where_it_clears_line(got)
                if far:
                    cols = max(40, _effective_width(r) - 4)
                    lines += [f"  {l}" for l in textwrap.wrap(far, cols - 2)]
                    data.update(clears_at=dict(
                        near=got["near"], far=got["far"], open=got["open"],
                        toward="south" if got["south"] else "north",
                        places=got["places"]))
                lines.append("")
            return Result("\n".join(paint(l, C.LABEL, c) for l in lines), data, 200)
        shown_utc = w
        wl = w + dt.timedelta(hours=p.offset(w))
        same = wl.date() == r.when_local.date()
        when_txt = f"{wl:%H:%M} tonight" if same else f"{wl:%a %d %b} at {wl:%H:%M}"
        # "right now" only when the chart is actually about now. Both this
        # and the "Visible now." below used to say it whatever ?t= asked
        # for, so a chart drawn for an eclipse next Wednesday announced its
        # visibility in the present tense.
        note = (f"Not visible {'then' if r.when_explicit else 'right now'}, {why}.",
                f"Next chance: {when_txt}, {a2:.0f}° up in the {compass(z2)}. "
                f"Chart drawn for that moment.")
        # The same two facts for the browser's one-line header. "(shown)"
        # carries what "Chart drawn for that moment" spells out: the sky
        # below is that later moment, not the one asked for.
        status = (f"not visible {when_word}, {SHORT_WHY.get(why, why)} · next "
                  f"{when_txt}, {a2:.0f}°{compass(z2)} (shown)")
        data.update(next_visible=dict(when_utc=w.isoformat() + "Z",
                                      when_local=wl.isoformat(),
                                      alt=round(a2), compass=compass(z2)))
        jd = julian(shown_utc); lst = (gmst_hours(jd) + p.lon / 15.0) % 24
        tgt = resolve_target(r.find, jd, p.lat, lst)

    # Full panorama with the thing crosshaired on it, not a 60° crop.
    #
    # The crop answered "what does this corner of the sky look like" when the
    # question people actually ask is "where do I look" -- and a window with
    # no horizon, no cardinal points either side and no familiar shapes in it
    # is a worse answer to that than the whole sky with a mark on it.
    # render_linear draws the crosshair at any span, so the zoom was never
    # what made the marker work.
    #
    # ?span= (--span=) still crops, so the old view is one parameter away for
    # something low in a crowded field.
    zoomed = r.span is not None
    if zoomed:
        rng = 26.0
        lo = max(0.0, min(90.0 - rng, tgt["alt"] - rng / 2))
        extra = dict(span=r.span, alt_lo=lo, alt_hi=lo + rng, width=r.width,
                     mag_limit=5.0)
    else:
        # Exactly what the ordinary chart draws, plus a crosshair. Nothing
        # else: two passes at making find "richer" both made it read as a
        # different chart rather than the familiar one with a mark on it.
        # mag_limit 5.0 put 775 stars where the normal view has 287; drawing
        # the extra 488 as dim backdrop was worse still, because mag 4-5 is
        # 63% of the whole field, so most of the sky went grey and the colour
        # and size variety that makes the chart readable disappeared with it.
        jd_shown = julian(shown_utc)
        sun_alt = altaz(*[sun(jd_shown)[k] for k in ("ra", "dec")],
                        p.lat, (gmst_hours(jd_shown) + p.lon / 15.0) % 24)[0]
        # line_limit and bodies as well as mag_limit -- the same three
        # _compose_sky passes. mag_limit alone fades the star field but not
        # the constellation lines drawn through it, nor the planets, which
        # nothing ever noticed because find in daylight always ended at "not
        # visible" rather than at a chart. ?find=Sun reaches it now, and a
        # partial eclipse an hour before sunset was drawing Lyra, the
        # Northern Cross and three planets into a bright sky.
        extra = dict(span=360.0, height=_horizon_height(r),
                     width=_effective_width(r),
                     mag_limit=_fade_mag_limit(sun_alt),
                     line_limit=_fade_mag_limit(sun_alt),
                     bodies=_fade_visible_bodies(sun_alt, jd_shown) | {"Sun", "Moon"})
    sp = extra["span"]
    # side_panel=r.panel: find draws the full panorama now (see the comment
    # above), so it earns the same zenith-inset-beside-the-chart treatment
    # as the ordinary view (see _compose_sky) -- without this, the inset
    # always rendered below regardless of ?panel=1, since render_linear's
    # side_panel default is False.
    art, st = render_linear(shown_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                            tle=r.tle, target=tgt, side_panel=r.panel, **extra)
    shown_local = shown_utc + dt.timedelta(hours=p.offset(shown_utc))
    # Same wrap_width choice sky_read() makes for the ordinary view's prose
    # -- the guide text used to be stuck at a fixed 76 columns even once
    # ?panel=1 gave the chart itself the full effective width, wrapping
    # mid-sentence well short of the space actually available.
    guide = find_text(tgt, st["visible"], p.lat,
                      wrap_width=_effective_width(r) if r.panel else 76)

    where = f"{int(sp)}° window" if zoomed else "full panorama"
    if r.panel:
        # One row, the same shape the ordinary chart's header has: place,
        # moment, what is being looked for, and whether it is up. "full
        # panorama" goes -- it is what every find view draws unless ?span=
        # says otherwise, and a zoomed one still says so.
        head_line = paint(f"{_head_prefix(r, shown_local)} · finding "
                          f"{tgt['name']} · {status}"
                          + (f" · {where}" if zoomed else ""), C.HEAD, c)
    else:
        head_line = paint(f"  {p.name}   {shown_local:%d %b %Y %H:%M}   finding "
                          f"{tgt['name']}, {where}", C.HEAD, c)
    if note:
        notice = [paint("  " + note[0], C.MUTE, c),
                  paint("  " + note[1], "\033[38;5;213m", c)]
    else:
        notice = [paint("  Visible then." if r.when_explicit else "  Visible now.",
                        "\033[38;5;48m", c)]
    guide_lines = [paint("  " + l, C.LABEL, c) for l in guide.split("\n")]
    if r.panel:
        # Same three-part split as _compose_sky: chart, then the inset, then
        # the prose. The notice is in the header line already, and the guide
        # is one line rather than four.
        zenith = st.get("zenith_lines") or []
        summary = _find_summary(tgt, st, p.lat, _effective_width(r) - 2)
        out = ["", head_line, "", art,
               ZENITH_SLOT] + zenith + [PROSE_SLOT, paint("  " + summary,
                                                          C.LABEL, c)]
    else:
        out = ["", head_line, ""] + notice + ["", art, ""] + guide_lines
    out += ["", _footer(p, c), ""]

    data.update(alt=round(tgt["alt"], 1), az=round(tgt["az"], 1),
                compass=compass(tgt["az"]),
                mag=round(tgt["mag"], 2) if tgt.get("mag") is not None else None,
                shown_utc=shown_utc.isoformat() + "Z", guide=guide)
    return Result("\n".join(out), data)


# ---------------------------------------------------------------- object pages
def object_collision(canonical):
    """The city that shares this object's path, as (display, escape url), or
    None when nothing collides.

    Objects win every collision -- always, whatever the city's population.
    The rule is worth stating plainly because the alternative is worse: a
    population threshold would send /Jupiter to a planet and /Heze to a town
    with no way to explain which way any given path resolves. A closed,
    curated namespace that always wins is predictable, and predictable is
    what a URL someone types from memory has to be.

    The cost is real and this function is how it is paid back: whoever loses
    the path gets a working link to the other thing, printed on the page.
    """
    hits = city_matches(canonical)
    if not hits:
        return None
    lat, lon, _zone, iso2, _country, admin, _pop, display = hits[0]
    # A US state disambiguates better than "US" does, and it is what the
    # documented syntax already accepts.
    where = admin if iso2 == "us" and admin else iso2.upper()
    return display, f"{display},{where}"


def _fists_line(alt):
    """Reuses sky.fists() so the object page says the same thing the find
    view says, in the same words."""
    return sky.fists(alt)


def object_glyph(tgt, jd):
    """(character, ansi colour code) -- the same mark and colour the chart
    draws this object with. Callers that need a hex colour (the social card)
    convert with _ansi_hex; the page paints the ANSI directly.

    Taken from the tables the chart and /catalog already share rather than a
    second set, so a card can never show a symbol the map does not use.
    """
    kind = tgt.get("kind")
    if kind == "star":
        s = next((x for x in sky._load("stars.json") if x.get("n") == tgt["name"]), None)
        mag = s["m"] if s else tgt.get("mag") or 3.0
        return sky.glyph_for(mag), sky.star_colour(s.get("ci") if s else None)
    if kind == "planet":
        return "◆", PLANET_COLORS.get(tgt["name"], C.LABEL)
    if kind == "moon":
        # The full Moon, always, rather than tonight's phase.
        #
        # This mark is the only thing on any card computed from a moment
        # short enough to matter. The phase glyph runs the whole cycle in
        # under two weeks -- across eight days it goes last quarter, waning
        # crescent, new, waxing crescent, first quarter -- and a social card
        # sits in Twitter's cache for about a week and in Facebook's until
        # somebody re-scrapes it. A Moon card shared at last quarter would
        # still be showing a half Moon on the night of the new Moon, and the
        # phase is the entire content of a Moon card.
        #
        # The page keeps the real phase, recomputed per visitor, which is
        # where a changing fact belongs. Same rule that took the altitude
        # off these cards: nothing survives here that changes faster than
        # the cache holding it.
        return "●", C.MOON
    if kind == "sun":
        return "☀", _SUN_C
    if kind == "asterism":
        return _ASTERISM_GLYPH[0], "\033[38;5;246m"
    if kind == "radiant":
        return "☄", C.LABEL
    o = next((x for x in sky._load("deepsky.json")
              if tgt["name"] in (x["n"], x.get("cn"), x["id"])), None)
    if o:
        g, c = sky.DSO_GLYPH[o["t"]]
        return g, c
    return "", C.LABEL


def _night_of(x):
    """Which night a local moment belongs to.

    A night starts at noon, which is why a 02:11 conjunction and a 22:00 one
    on the same date can be the same night as each other and a 13:00 one is
    not. Both the night list and the year list go through here, or they
    disagree: the events list files a window that starts at 02:11 under that
    morning's date, while the page it opens is drawn for 04:11.
    """
    return (x - dt.timedelta(hours=12)).date()


def object_night_events(canonical, p, when_utc, tz):
    """What is happening to this object on the night the page is drawn for.

    Through the same localiser and the same _event_date the events list
    uses, so the two cannot disagree about which night something belongs
    to. Working straight off the global scan instead put Saturn's
    opposition on the wrong night: it peaks at 07:53 local, which a plain
    noon-to-noon bracket files under the night before, while the list files
    it -- correctly -- under the evening you would actually go out.

    The scan starts a day and a half back because the page is often opened
    at the event, and an event a few hours old is not in a list of what is
    coming.

    A conjunction counts for both of its bodies: /Mars gets "Moon meets
    Mars" and so does /Moon. That is not what _find_target_for answers --
    it picks the one body worth crosshairing, deliberately not the Moon.
    """
    night = _night_of(when_utc + dt.timedelta(hours=tz))
    out = []
    for e in ev_mod.upcoming(p.lat, p.lon, tz, days=4,
                             now_utc=when_utc - dt.timedelta(days=1.5),
                             visible_only=False):
        if _night_of(_event_date(e)) != night:
            continue
        bodies = e.get("bodies") or ([e["body"]] if e.get("body") else [])
        if _find_target_for(e) != canonical and canonical not in bodies:
            continue
        out.append({"name": e.get("headline") or e["name"], "kind": e["kind"],
                    "short": _event_short(e.get("headline") or e["name"],
                                          canonical),
                    # The date the events list files it under, so a title
                    # built from this says the same day the row did.
                    "date_local": _event_date(e).isoformat(),
                    # And the same viewing window the row quotes, rather
                    # than the bare best moment: an opposition filed under
                    # the 4th whose best minute is 01:13 on the 5th put two
                    # different dates on one page all over again.
                    "window_local": e.get("window_local"),
                    "when_local": (e.get("best_local")
                                   or e["when_local"]).isoformat()})
    return out


OBJECT_EVENTS_DAYS = 365
OBJECT_EVENTS_SHOWN = 12


def object_events_list(canonical, p, now_utc, tz, days=OBJECT_EVENTS_DAYS):
    """This object's next twelve events, counted from today.

    The same list /events builds, filtered to one object: its oppositions
    and elongations, the nights the Moon passes it, its shower's peak. So
    an object page can offer the year the way an eclipse page offers the
    other eclipses, instead of only ever knowing about the one moment it
    happens to be drawn for.

    Counted from now, and not from the moment the page is drawn for, which
    is the whole of it. Every row here is a link to this same page at
    another moment, so a list measured from the page's own moment got
    shorter every time somebody used it: opening the October opposition
    dropped the conjunction in August, which had not happened yet. The
    twelve are the same wherever the reader has navigated to, and they move
    only as time does -- one falls off the top as the next arrives at the
    bottom.
    """
    out = []
    tonight = _night_of(now_utc + dt.timedelta(hours=tz))
    # A day and a half back, because an event belonging to tonight can fall
    # in the small hours and so already be behind us. Which night it belongs
    # to is what actually decides, just below.
    for e in ev_mod.upcoming(p.lat, p.lon, tz, days=days,
                             now_utc=now_utc - dt.timedelta(days=1.5),
                             visible_only=False):
        bodies = e.get("bodies") or ([e["body"]] if e.get("body") else [])
        if _find_target_for(e) != canonical and canonical not in bodies:
            continue
        # Tonight's event has not been missed: the night it belongs to is
        # still running. Only the nights before this one drop off.
        if _night_of(_event_date(e)) < tonight:
            continue
        when = e.get("best_local") or e["when_local"]
        # An eclipse has a page of its own that answers far more about it
        # than the Moon's page can, and the events list already sends people
        # there. The picker was the one place still opening the Moon at a
        # timestamp instead.
        href = None
        if e["kind"] == "eclipse":
            key = _event_date(e).strftime("%Y-%m-%d")
            if eclipse_page.by_key(key):
                href = f"/{quote(p.slug)}/eclipse/{key}"
        out.append({"name": e.get("headline") or e["name"],
                    "short": _event_short(e.get("headline") or e["name"],
                                          canonical),
                    "kind": e["kind"],
                    "date_local": _event_date(e).isoformat(),
                    "window_local": e.get("window_local"),
                    "when_local": when.isoformat(),
                    "href": href,
                    "t": when.strftime("%Y-%m-%dT%H:%M")})
    return out[:OBJECT_EVENTS_SHOWN]


def _event_short(name, canonical):
    """The event without the object's own name on the front, since the name
    is already the word beside it: "Saturn at opposition" next to "Saturn"
    says it twice. A conjunction keeps both bodies, which are the fact."""
    for prefix in (f"{canonical} at ", f"{canonical} "):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            # Not when what is left starts with a connective: "Moon and
            # Mercury 2.0 degrees apart" became "and Mercury 2.0 degrees
            # apart", which is a sentence fragment, not a shorter name.
            if rest.split()[0] in ("and", "meets", "near"):
                return name
            return rest
    return name


def object_facts(tgt, r, canonical, shown_utc=None):
    """Everything the object page knows, as data. The prose and the JSON are
    both rendered from this, so they cannot drift apart.

    shown_utc is the moment the chart above was actually drawn for, which is
    not always now: when the object is below the horizon the find view draws
    the next time it is up instead. The prose has to describe that same
    moment or the page contradicts itself -- it read "Face NE, 2 fists up" on
    the chart and "Face WNW, 3 fists up" in the sentence underneath.
    """
    p = r.place
    when = shown_utc or r.when_utc
    jd = julian(when)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    glyph, glyph_ansi = object_glyph(tgt, jd)
    out = {"object": canonical, "kind": tgt.get("kind"),
           "place": p.name, "lat": p.lat, "lon": p.lon,
           "glyph": glyph, "glyph_color": _ansi_hex(glyph_ansi),
           "glyph_ansi": glyph_ansi,
           "shown_utc": when.isoformat() + "Z", "is_now": shown_utc is None,
           # Whether a moment was asked for, which is a different question
           # from whether the chart was shifted off it. Everything that
           # words the page -- the heading, the <title> -- needs the first
           # one, and only had the second.
           "when_explicit": r.when_explicit}

    rts = objects.rise_transit_set(tgt, p.lat, p.lon, when)
    tz = p.offset(when)

    def local(x):
        return (x + dt.timedelta(hours=tz)).isoformat() if x else None

    # The same moment as shown_utc, on the clock of the place it is about.
    # The title read it straight out of shown_utc and called 23:10 UTC the
    # 4th, on a page whose own heading said 5 October 01:10.
    out["shown_local"] = local(when)
    # Against the moment asked for, not the moment the chart settled on. A
    # new Moon is not up in the evening, so the find view moves the chart to
    # when it is -- and looking for events around *that* lost the very event
    # the reader clicked to get here.
    out["tonight_events"] = object_night_events(
        canonical, p, r.when_utc, p.offset(r.when_utc))
    # Counted from now, unlike the line above it: tonight_events is about the
    # night being drawn, while this is the standing list of what is coming,
    # and every row in it opens this page at another moment. Measured from
    # the page's own moment it lost an event every time one was followed.
    _now = dt.datetime.utcnow()
    out["object_events"] = object_events_list(
        canonical, p, _now, p.offset(_now))
    out["transit"] = local(rts.get("transit"))
    out["transit_alt"] = rts.get("transit_alt")
    if rts.get("circumpolar"):
        out["never_sets"] = True
    elif rts.get("never_rises"):
        out["never_rises"] = True
    else:
        out["rise"] = local(rts.get("rise"))
        out["set"] = local(rts.get("set"))
        out["hours_up"] = rts.get("up_hours")

    # Which constellation, for anything with a fixed position and for the
    # planets alike -- the boundaries do not care what kind of object it is.
    ra, dec = tgt.get("ra"), tgt.get("dec")
    if ra is None and tgt.get("body"):
        b = (sky.moon(jd) if tgt["body"] == "Moon" else
             sky.sun(jd) if tgt["body"] == "Sun" else sky.planet(tgt["body"], jd))
        ra, dec = b["ra"], b["dec"]
    if ra is not None:
        out["constellation"] = objects.constellation_name(ra, dec)

    # How far the Moon is from it, and how lit -- the two facts that decide
    # whether tonight is worth the trip for anything faint.
    if tgt.get("kind") not in ("moon", "sun"):
        mo = sky.moon(jd)
        ma, mz = altaz(mo["ra"], mo["dec"], p.lat, lst)
        out["moon_separation"] = round(angsep(tgt["alt"], tgt["az"], ma, mz))
        out["moon_illum"] = round(mo["illum"], 2)

    if tgt.get("kind") == "planet":
        out["planet"] = objects.planet_facts(tgt["name"], jd, p.lat, lst)
        # The four dots in a line that are somewhere else the next night.
        if tgt["name"] == "Jupiter":
            out["moons_tonight"] = objects.galilean_line(jd)

    if tgt.get("kind") == "milkyway":
        # Round numbers on purpose. The distance to the centre is measured
        # to about 26,700 +/- 100 ly and the diameter is argued over between
        # 90,000 and 120,000 depending on where you decide the disc stops,
        # so quoting either to four figures would be a false precision the
        # rest of this page does not have.
        out["galaxy"] = {
            "centre_ly": 26_000,
            "diameter_ly": 100_000,
            "stars": "100 to 400 billion",
            "kind": "barred spiral",
        }
        # The whole question for this object, and the one thing a chart
        # cannot answer: from most of Europe the band is simply not there.
        # milkyway_floor returns the altitude above which it is drawn, and
        # zero means the sky where you are standing is too bright for it at
        # any altitude.
        try:
            # A CONTOUR level, not an altitude. milkyway_at() returns 0 to 5
            # across the band and the floor is the faintest contour still
            # above the light pollution here: 1 is a dark sky showing the
            # whole thing, 4 is a bad one where only the core survives, 0 is
            # a city where drawing any of it would be a lie. This was being
            # printed as "visible above 3 degrees", which is not what the
            # number means and not a fact about anything.
            floor = milkyway_floor(p.lat, p.lon)
            out["galaxy"]["floor"] = floor
            out["galaxy"]["visible_here"] = bool(floor)
            out["galaxy"]["shows"] = _MILKYWAY_SHOWS.get(floor)
        except Exception:                                   # noqa: BLE001
            pass

    if tgt.get("kind") == "moon":
        out["moon"] = objects.moon_facts(jd)
        mo = sky.moon(jd)
        out["illuminated"] = round(mo["illum"], 3)
        # Which limb the Sun is on. Past full the Moon is lit from the other
        # side, and a drawing that ignores that shows a waning Moon as a
        # waxing one -- a mirror image of the thing in the sky.
        out["waning"] = mo["age"] > 180

    # Where the body's axis points, for the drawing. Both numbers come from
    # the same IAU pole table: how far the pole leans towards us (which tips
    # the belts and opens the rings) and where it points on the sky (which
    # turns the whole planet on screen).
    if tgt.get("kind") in ("planet", "sun", "moon"):
        try:
            ra, dec = objects._body_radec(tgt["name"], jd)
            geo = objects.pole_geometry(tgt["name"], {"ra": ra, "dec": dec})
            if geo:
                out["pole_b"], out["pole_pa"] = geo
        except Exception:                                   # noqa: BLE001
            pass

    # How dark it is where the reader is standing, which is the other half of
    # whether a faint thing is findable at all. sky_brightness() already
    # estimates it from the light-pollution model the chart uses.
    if tgt.get("kind") not in ("sun", "moon", "planet"):
        try:
            out["bortle"] = sky_brightness(p.lat, p.lon)[1]
        except Exception:                                   # noqa: BLE001
            pass

    if tgt.get("kind") == "star":
        hr = next((s["hr"] for s in sky._load("stars.json")
                   if s.get("n") == tgt["name"]), None)
        if hr is not None:
            info = objects.star_info(hr)
            star = {}
            desc = objects.describe_spectrum(info.get("sp"))
            if desc:
                star["description"] = desc
            if info.get("sp"):
                star["spectral_type"] = info["sp"]
            d = objects.distance_ly(hr)
            if d:
                star["light_years"], star["distance_confidence"] = d[0], d[1]
            if info.get("sep"):
                star["double_separation"] = info["sep"]
            nm = objects.next_minimum(hr, r.when_utc)
            if nm:
                star["next_minimum"] = local(nm)
                star["period_days"] = objects.variable_info(hr).get("period")
            if star:
                out["star"] = star

    size = objects.dso_size(tgt.get("id") or "")
    if not size and tgt.get("kind") not in ("planet", "star", "moon", "sun"):
        # Deep-sky targets arrive named rather than keyed, so the catalogue
        # id has to be looked back up.
        oid = next((o["id"] for o in sky._load("deepsky.json")
                    if tgt["name"] in (o["n"], o.get("cn"), o["id"])), None)
        if oid:
            size = objects.dso_size(oid)
    if size:
        out["size_arcmin"] = size

    # An asterism is a shape, not a point: no magnitude, no distance, no
    # angular size. What it does have is a star count and the magnitude of
    # its faintest member, which together answer the only question that
    # matters -- can you actually trace the whole figure, or does one corner
    # of it disappear unless the sky is properly dark.
    if tgt.get("kind") == "asterism":
        a = next((x for x in sky._load("asterisms.json")
                  if x["name"] == tgt["name"]), None)
        if a:
            out["star_count"] = len({h for pair in a["lines"] for h in pair})
            out["faintest"] = a["faint"]

    # What it takes to see it -- only when the catalogue actually measured a
    # brightness. deepsky.json carries the cutoff as a placeholder for the
    # many diffuse nebulae RNGC never measured, so a magnitude alone cannot
    # be trusted to mean anything. See objects.what_you_need().
    if tgt.get("kind") not in ("planet", "moon", "sun", "radiant"):
        point = tgt.get("kind") in objects.POINT_KINDS
        mag = tgt.get("mag") if point else objects.dso_magnitude(tgt["name"])
        need = objects.what_you_need(mag, out.get("bortle"), point=point)
        if need:
            out["need"] = need

    best = objects.best_this_year(tgt, p.lat, p.lon, when)
    if best:
        # The hour worth being outside on that night, not just the date. For
        # a shower that is the peak itself; for anything else it is the same
        # calculation the chart above already uses, run for that night.
        # The best HOUR of that night, for showers as much as anything else.
        # A shower's peak instant is a point in Earth's orbit and lands in
        # daylight about half the time -- the Geminids peak at 13:51 local,
        # which put "14:51 on the 14th" in the calendar when the night worth
        # setting an alarm for is 02:20 on the 15th.
        best_at = objects.best_tonight(tgt, p.lat, p.lon,
                                       best["when_utc"] - dt.timedelta(hours=12))
        at_local = (best_at + dt.timedelta(hours=p.offset(best_at))
                    if best_at else None)
        entry = {
            # One date, everywhere: the day the viewing hour falls on. The
            # night a shower peaks and the hour worth being outside for it
            # are usually different dates -- the Geminids peak on the 14th
            # and the sky is best at 02:20 on the 15th -- and having the
            # headline, the calendar entry and this line each pick their own
            # meant the page named two different days for one event.
            "date": (at_local.date().isoformat() if at_local
                     else (best["when_utc"] + dt.timedelta(hours=tz)).date().isoformat()),
            "at": at_local.isoformat() if at_local else None,
            "dark_hours": best.get("dark_hours"),
            "transit_alt": best["transit_alt"],
            "moon_illum": best["moon_illum"]}
        # A shower peaks rather than being "best"; it carries the radiant's
        # altitude on that night instead of a count of dark hours.
        if best.get("is_peak"):
            # The radiant's altitude at the hour the page is built around,
            # not at local midnight. _shower_peak quotes midnight because
            # that is the convention rates are published under, but the
            # headline names 02:20 and the prose then said 63 degrees for
            # midnight while the headline said 76 for 02:20 -- two correct
            # numbers reading as a contradiction.
            alt_at = best.get("radiant_alt")
            if at_local:
                jd_b = julian(best_at)
                ra_b, de_b = sky.precess(tgt["ra"], tgt["dec"], jd_b)
                alt_at = round(altaz(ra_b, de_b, p.lat,
                                     (gmst_hours(jd_b) + p.lon / 15.0) % 24)[0], 1)
            entry.update(is_peak=True, radiant_alt=alt_at,
                         zhr=best.get("zhr"))
        out["best_this_year"] = entry

    collision = object_collision(canonical)
    if collision:
        out["also_a_place"] = {"city": collision[0], "url": f"/{collision[1]}"}
    return out


def object_timing(facts):
    """Rise, set and transit as one condensed line.

    Sits above the chart, where "is it worth going out" gets answered before
    the picture rather than after it. Arrows instead of a sentence because
    this is a row of times, not a paragraph: up for rise, down for set, and
    a caret for the high point, which is the one that decides the evening.
    Both arrows and the caret are in the bundled font, so no fallback.
    """
    if facts.get("never_rises"):
        return "never rises from here"
    if facts.get("never_sets"):
        return f"never sets \u00b7 \u2303 {facts['transit_alt']:.0f}\u00b0 at its highest"
    if not facts.get("rise"):
        return ""
    rise, st = facts["rise"][11:16], facts["set"][11:16]
    # A set earlier than the rise is the following morning, which has to be
    # marked or the line reads backwards.
    over = "+1" if facts["set"][:10] != facts["rise"][:10] else ""
    return (f"\u2191 {rise}  \u2193 {st}{over}  "
            f"\u2303 {facts['transit'][11:16]}")


def object_prose(facts, tgt, r, width=76):
    """The facts as sentences. House style: plain statements, the numbers
    carried inside them rather than listed beside them."""
    L = []
    tz_name = ""
    kind = facts.get("kind")
    name = facts["object"]

    # Deliberately no "face this way and look that high" line here: the find
    # view directly above already says it, in the same words, and printing
    # it twice on one page reads as a mistake. This block picks up where
    # that leaves off.
    if facts.get("never_rises"):
        L.append(f"{name} never rises from {facts['place']}. It stays below "
                 f"the horizon all year at this latitude.")

    if facts.get("constellation"):
        if _MOVES_AGAINST_THE_SKY(facts):
            L.append(f"It is currently crossing {facts['constellation']}.")
        else:
            L.append(f"You will find it in {facts['constellation']}.")

    st = facts.get("star", {})
    if st.get("description"):
        s = f"It is a {st['description']}"
        if st.get("light_years"):
            ly = st["light_years"]
            conf = st.get("distance_confidence")
            if conf == "good":
                s += (f", {ly:.0f} light years away, so the light reaching you "
                      f"left it in {r.when_local.year - int(ly)}")
            elif conf == "rough":
                s += f", roughly {ly:.0f} light years away"
            else:
                s += ", at a distance that is genuinely uncertain"
        L.append(s + ".")
    if st.get("next_minimum"):
        L.append(f"It is an eclipsing variable: it next dims at "
                 f"{st['next_minimum'][11:16]} on {st['next_minimum'][:10]}, "
                 f"and again every {st['period_days']:.4g} days.")

    pl = facts.get("planet", {})
    if pl:
        L.append(f"It is {pl['distance_au']:.2f} AU away, which is "
                 f"{pl['light_minutes']:.0f} light-minutes, so you are seeing it "
                 f"as it was {pl['light_minutes']:.0f} minutes ago.")
        if pl.get("lost_in_glare"):
            L.append(f"It is only {pl['elongation']:.0f}° from the Sun and lost in "
                     f"the glare.")
        else:
            article = "an" if pl["side"][0] in "aeiou" else "a"
            L.append(f"It sits {pl['elongation']:.0f}° from the Sun, so it is "
                     f"{article} {pl['side']} object.")
        if pl.get("ring_angle") is not None:
            ra_ = pl["ring_angle"]
            how = ("almost edge-on, and very hard to pick out" if ra_ < 5 else
                   "a narrow ellipse in a small telescope" if ra_ < 12 else
                   "clearly open" if ra_ < 22 else
                   "as wide as they ever get")
            L.append(f"The rings are tilted {ra_:.0f}° towards us, {how}.")
        if pl.get("apparent_arcsec"):
            L.append(f"The disc is {pl['apparent_arcsec']:.0f} arcseconds across"
                     + (f", {pl['illuminated']:.0%} lit."
                        if pl["illuminated"] < 0.95 else "."))
        if pl.get("retrograde"):
            L.append("It is retrograde at the moment, drifting westwards "
                     "against the stars.")

    if facts.get("moons_tonight"):
        L.append(f"Its four big moons tonight: {facts['moons_tonight']}. "
                 f"Binoculars will show them, and they will have moved by "
                 f"tomorrow night.")

    mo_f = facts.get("moon") or {}
    if mo_f.get("distance_km"):
        s2 = (f"It is {mo_f['distance_km']:,} km away, "
              f"{mo_f['light_seconds']} light-seconds, and "
              f"{mo_f['apparent_arcmin']:.0f} arcminutes across")
        if mo_f.get("extreme"):
            s2 += f", {mo_f['extreme']}"
        L.append(s2 + ".")

    if facts.get("size_arcmin"):
        s = facts["size_arcmin"]
        moons = s["maj"] / 31.0
        rel = (f", about {moons:.0f} times the width of the full Moon" if moons >= 2
               else f", roughly {moons:.1f} Moon-widths" if moons >= 0.5 else "")
        L.append(f"It spans {s['maj']:g} arcminutes{rel}.")

    b_here = facts.get("bortle")
    if b_here and facts.get("need"):
        # "You need binoculars" is half an answer without "and your sky is
        # Bortle 8", which is why people buy binoculars and still see
        # nothing. The estimate comes from the same light-pollution model the
        # chart dims the Milky Way with.
        how = ("genuinely dark" if b_here <= 3 else
               "suburban" if b_here <= 5 else
               "bright" if b_here <= 7 else "inner-city")
        # "So for this you want naked eye" is not a sentence. When the answer
        # is that no equipment is needed, the Bortle number stops being a
        # warning and becomes the reason the answer is worth hearing.
        L.append(f"Your sky here is about Bortle {b_here}, {how}, "
                 + ("and this is still bright enough to see with the naked eye."
                    if facts["need"].startswith("naked eye")
                    else f"so for this you want {facts['need']}."))

    # Only worth saying when the Moon is both bright and actually near it.
    # A full Moon 145 degrees away is not what stops you seeing something.
    sep, illum = facts.get("moon_separation"), facts.get("moon_illum", 0)
    if sep is not None and illum > 0.4 and sep < 60:
        L.append(f"The Moon is {illum:.0%} lit and only {sep}° away, which will "
                 f"wash out anything faint nearby.")

    b = facts.get("best_this_year")
    if b and b.get("is_peak"):
        # The peak date, the hour and the radiant's altitude are all in the
        # heading and the line under it now, so repeating them here was the
        # same sentence three times. Only the Moon is left, and only when it
        # is worth mentioning: a full Moon on the peak night is the one thing
        # that can write the night off, and a dark one is worth knowing.
        moon = b.get("moon_illum", 0)
        if moon > 0.5:
            L.append(f"The Moon is {moon:.0%} lit that night and will drown "
                     f"most of it.")
        elif moon < 0.15:
            L.append("Almost no Moon that night to spoil it.")
    elif b:
        L.append(f"Best in the next 12 months: {b['date']}, when it reaches "
                 f"{b['transit_alt']:.0f}° with {b['dark_hours']:.1f} hours of "
                 f"darkness and the Moon {b['moon_illum']:.0%} lit.")
        # Why that date and not this one, when the reader is standing on an
        # event night and being pointed a year away. It reads as a
        # contradiction otherwise: you clicked "Saturn at opposition,
        # closest and brightest of the year" and the page answered with next
        # autumn. Both are right and they are answers to different
        # questions, so the page had better say which.
        here_moon = facts.get("moon_illum")
        ev = (facts.get("tonight_events") or [None])[0]
        if ev and here_moon is not None and here_moon - b["moon_illum"] > 0.2:
            night = dt.datetime.fromisoformat(ev["date_local"])
            L.append(f"That ranking counts dark hours, altitude and "
                     f"moonlight, not how close a planet is: the Moon is "
                     f"{here_moon:.0%} lit on {night:%-d %B} and "
                     f"{b['moon_illum']:.0%} on {b['date']}, and the sky is "
                     f"otherwise the same on both nights.")

    also = facts.get("also_a_place")
    if also:
        L.append(f"{name} is also a place. For the sky above the town, use "
                 f"skymap.sh{also['url']}.")

    import textwrap
    out = []
    for para in L:
        out.extend(textwrap.wrap(para, width))
        out.append("")
    return "\n".join(out).rstrip()


def object_infobox(facts, tgt, width=76):
    """The stats block, as aligned rows.

    A browser gets this as a card floated beside the text, the way an
    encyclopedia entry does. A terminal gets the same rows in the same order
    as an aligned table, because the alternative is a second set of facts
    written for a second audience, and two sets drift.

    Only durable rows belong here. Where the object is tonight lives in the
    live block further down, under a heading that says so.
    """
    rows = []

    def add(label, value):
        if value:
            rows.append((label, str(value)))

    # For a star, the words rather than the bare kind: "Red supergiant" says
    # something, "Star" says only what the page already said in its heading.
    # This is the same sentence the social card leads with, which is where it
    # was already earning its place -- it just never made it onto the page
    # the card links to.
    # The most specific words available: "Red supergiant" over "Star",
    # "Barred spiral galaxy" over "Galaxy". One row either way -- the
    # generic kind is the fallback, not a second line.
    star_kind = (facts.get("star") or {}).get("description")
    gal_kind = (facts.get("galaxy") or {}).get("kind")
    add("Type", (star_kind.capitalize() if star_kind else
                 f"{gal_kind.capitalize()} galaxy" if gal_kind else
                 _KIND_WORD.get(facts.get("kind"), "").capitalize() or None))
    add("Symbol", PLANET_SYMBOLS.get(facts.get("object")))
    # Same reasoning as the intro line: durable for a star, live for a planet.
    if not _MOVES_AGAINST_THE_SKY(facts):
        add("Constellation", facts.get("constellation"))
    # Not for asterisms (a shape has no single brightness) and not for
    # meteor radiants, whose "magnitude" is a stand-in resolve_target sets so
    # dark_enough() picks the nautical-dark threshold. It is not a brightness
    # and printing it as one invents a fact.
    if tgt.get("mag") is not None and tgt.get("kind") not in ("asterism", "radiant", "milkyway"):
        add("Magnitude", f"{tgt['mag']:.1f}")

    st, pl = facts.get("star", {}), facts.get("planet", {})
    add("Spectral type", st.get("spectral_type"))
    if st.get("light_years"):
        conf = st.get("distance_confidence")
        ly = f"{st['light_years']:,.0f} light years"
        add("Distance", ly if conf == "good" else f"about {ly}")
    if st.get("double_separation"):
        add("Double star", f"components {st['double_separation']:.1f}″ apart")
    if st.get("period_days"):
        add("Variable", f"eclipses every {st['period_days']:.4g} days")

    gx = facts.get("galaxy") or {}
    if gx:
        add("Diameter", f"{gx['diameter_ly']:,} light years")
        add("Centre", f"{gx['centre_ly']:,} light years away, in Sagittarius")
        add("Stars", gx["stars"])
        # The row that decides whether any of the others matter tonight.
        add("From here", gx.get("shows"))

    if pl:
        add("Distance", f"{pl['distance_au']:.2f} AU, "
                        f"{pl['light_minutes']:.0f} light-minutes")
        if pl.get("apparent_arcsec"):
            add("Apparent size", f"{pl['apparent_arcsec']:.0f}″")
        if pl.get("illuminated") is not None and pl["illuminated"] < 0.95:
            add("Illuminated", f"{pl['illuminated']:.0%}")
        if pl.get("ring_angle") is not None:
            add("Rings", f"tilted {pl['ring_angle']:.0f}° to us")

    size = facts.get("size_arcmin")
    if size:
        s = f"{size['maj']:g}′"
        if size.get("min"):
            s += f" × {size['min']:g}′"
        moons = size["maj"] / 31.0
        if moons >= 1:
            s += f" ({moons:.0f}× the full Moon)" if moons >= 2 else " (a Moon-width)"
        add("Apparent size", s)

    if facts.get("star_count"):
        add("Stars", facts["star_count"])
    add("You need", facts.get("need"))

    # The hand-written half: radius, moons, who found it, what we have sent
    # to look at it. None of it is in any catalogue this repo ships, and none
    # of it ever changes, which is exactly why it belongs on a page whose
    # other half is redrawn every five minutes.
    #
    # Appended rather than merged, so a computed row and a written one can
    # never quietly contradict each other -- where both exist, "Distance"
    # from a parallax and "Distance" as a round published figure, only one is
    # emitted (see the guard below).
    b = facts.get("best_this_year")
    if b and b.get("is_peak"):
        add("Peak", b["date"])
        if b.get("zhr"):
            add("Rate at peak", f"up to {b['zhr']} an hour")

    # Measured values from JPL Horizons, then the hand-written history.
    # Each skipped where an earlier block already answered the same question,
    # so an object never carries two answers to one label.
    have = {k for k, _v in rows}
    measured = [(k, v) for k, v in facts_table.measured(facts["object"])
                if k not in have]
    have |= {k for k, _v in measured}
    written = [(k, v) for k, v in facts_table.for_object(facts["object"])
               if k not in have]

    # Grouped, because a planet now carries twenty rows and an
    # undifferentiated wall of them is a table nobody reads. The headings are
    # the ones an encyclopedia uses, for the same reason: what it looks like
    # from here, what it physically is, and what we know about it are three
    # different questions.
    # What is happening to this object on the night the page is drawn for.
    # Same heading, same placement and the same dl the eclipse page marks its
    # concurrent events with, because it is the same idea: the reason you
    # opened this page, said once, where a reader looks for facts about the
    # thing rather than buried in a sentence under the chart.
    # Everything except the one already named in the heading and the picker
    # above it. The eclipse page drops the eclipse from its own "same night"
    # list for the same reason: a block headed "the same night" that leads
    # with the thing the page is about is telling you what you just read.
    tonight = [(e["name"], _event_stamp(e))
               for e in (facts.get("tonight_events") or [])[1:]]

    blocks = [(None, rows), (TONIGHT_BLOCK, tonight),
              ("Physical", measured), ("History", written)]
    return [(t, r) for t, r in blocks if r]


TONIGHT_BLOCK = "The same night"

# The picker's first row, and what the summary reads when the page is not
# pinned to a night. Not "now": the page is drawn for a moment but it is
# about a night, and the chart moves to when the thing is actually up.
PICK_NOW = "Tonight · where it is now"


def object_picker_html(data, canonical, place, escape=html.escape):
    """This object's events, as the same disclosure the eclipse page uses
    for the other eclipses.

    <details> and not a <select>, for the reasons picker_html gives: no
    script, every entry a real link that can be opened in a tab or copied,
    and room to show the date and what kind of event it is.

    The place travels with every link. Without it, picking a date from
    /Zurich/Saturn would drop the reader on /Saturn and quietly relocate
    them to wherever their IP says they are.
    """
    evs = data.get("object_events") or []
    if not evs:
        return ""
    here = (data.get("tonight_events") or [None])[0]
    base = f"/{quote(place)}/{quote(canonical)}" if place else f"/{quote(canonical)}"

    def label(e):
        day = dt.datetime.fromisoformat(e["date_local"])
        return f"{day:%-d %b %Y} · {e['short']}"

    # The list starts at the next event that has not happened yet, so the
    # summary is simply its head -- unless the night being drawn has one of
    # its own, which is the one the reader came for, or the page is not
    # about a night at all, which is what it says instead.
    plain = not here and not data.get("when_explicit")
    now = (label(here) if here else PICK_NOW if plain
           else f"Next: {label(evs[0])}")
    # The way back, and the only row in here that carries no moment. Every
    # other one pins a night, so following any of them left the reader with
    # no link on the page that dropped it again: the bare URL existed only
    # inside the share box, and only if they thought to open it.
    now_cls = ' class="obj-pick-here"' if plain else ""
    rows = [f'<li{now_cls}><a href="{base}">{escape(PICK_NOW)}</a></li>']
    for e in evs:
        current = bool(here) and e["date_local"] == here["date_local"]
        cls = ' class="obj-pick-here"' if current else ""
        href = e.get("href") or f'{base}?t={e["t"]}'
        rows.append(f'<li{cls}><a href="{href}">'
                    f'{escape(label(e))}</a></li>')
    return (f'<details class="obj-picker"><summary>'
            f'<span>{escape(now)}</span>'
            f'<span class="obj-more">change</span></summary>'
            f'<div class="obj-panel"><ul>{"".join(rows)}</ul></div>'
            f'</details>')


def object_share_html(r, canonical):
    """The two links to this page, behind a button.

    The same control the eclipse page carries, for the same reason. Opening
    /Saturn bounces you to /Zurich/Saturn so the page can say Zurich rather
    than 47.38,8.54, and from that moment the only URL there is to copy has
    your own location baked into it. The bare one follows whoever opens it;
    the one with the place in it stays put. Both are legitimate.

    The place is named here because this is behind a click, by a person. It
    is the meta tags and the social card that must never report a crawler's
    datacentre as the reader's home town.

    The moment travels along when one was actually asked for. A link to the
    night of the opposition that quietly resolves to tonight is not the page
    that was shared.
    """
    q = f"?t={r.when_local:%Y-%m-%dT%H:%M}" if r.when_explicit else ""
    obj = quote(canonical)
    return eclipse_page.share_html(
        canonical_url("/" + obj) + q,
        canonical_url(f"/{quote(r.place.name)}/{obj}") + q,
        r.place.name,
        title=f"Share {canonical}",
        noun=canonical,
        # The third one only where there is a moment to drop. An object is
        # up most nights, so a link with no date on it is the useful thing
        # to send somebody -- and while the page is pinned to a night, every
        # other URL in this box has that night baked into it.
        plain_url=canonical_url("/" + obj) if q else None)


def _event_subhead(facts, canonical):
    """"Opposition Sun Oct 4" -- the event beside the object's name.

    The object's own name comes off the front, because it is already the
    word to the left of it: "Saturn / Saturn at opposition" says it twice.
    Nothing comes off a conjunction, where both bodies are the fact.

    The date is the one the events list files it under, which is the one the
    <title> and the block in the sidebar carry too. The chart above may well
    be drawn for the small hours of the following morning -- the same night,
    the next date -- and putting that date here would start the page
    disagreeing with itself again.
    """
    ev = (facts.get("tonight_events") or [None])[0]
    if not ev:
        return ""
    name = ev["name"]
    for prefix in (f"{canonical} at ", f"{canonical} "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    when = dt.datetime.fromisoformat(ev["date_local"])
    return f"{name[0].upper()}{name[1:]} {when:%a %b %-d}"


# What each kind of event actually is, in one line. The picker beside the
# heading names a thing -- "at opposition", "greatest elongation east" --
# and until now the page nowhere said what that meant. Written per kind
# rather than per event, because the answer is the same every time.
EVENT_KIND_NOTE = {
    "opposition":
        "Opposition is when a planet sits opposite the Sun: it rises at "
        "sunset, is up all night, and is the closest and brightest it gets "
        "all year.",
    "elongation":
        "Greatest elongation is the furthest from the Sun this planet ever "
        "appears, and the short window when it clears the twilight.",
    "conjunction":
        "A conjunction is two bodies passing close together as we see them, "
        "near enough to hold both in one binocular view. In space they are "
        "nowhere near each other.",
    "moon_phase":
        "The phase is how much of the Moon's lit half faces us. The craters "
        "show best along the line between light and dark, where the shadows "
        "are longest.",
    "meteor_shower":
        "A shower peaks on the night Earth crosses the thickest part of the "
        "dust a comet left behind. The meteors appear all over the sky, but "
        "their trails all point back to one spot.",
    "eclipse":
        "An eclipse is the Sun, Earth and Moon lined up closely enough for "
        "one of them to throw a shadow on another.",
}


def event_note(facts):
    """The sentence explaining the event this page is drawn for.

    Only that one. It used to fall through to the next event coming, which
    meant a page opened on an ordinary night to find out where the thing is
    led with a paragraph about an opposition ten weeks away: every object
    page read as an event page, including the ones nobody had asked an event
    of. Nothing here for an ordinary night, and nothing ever for an object
    with no events at all -- every star, as it happens, since conjunctions
    are only computed between solar-system bodies.
    """
    ev = (facts.get("tonight_events") or [None])[0]
    return EVENT_KIND_NOTE.get((ev or {}).get("kind"), "")


def _event_stamp(e):
    """The date the events list files it under, and the same window that
    list quotes. One page had better not carry two dates for one event."""
    day = dt.datetime.fromisoformat(e["date_local"])
    win = e.get("window_local")
    if win:
        return f"{day:%-d %b}, best {win[0]}-{win[1]}"
    when = dt.datetime.fromisoformat(e["when_local"])
    return f"{day:%-d %b}, {when:%H:%M}"


def infobox_text(blocks, indent="  "):
    """The blocks as an aligned table, for a terminal.

    A terminal can only align on a character grid, so the key column is
    padded to the widest key and long values simply run on. The browser gets
    the same rows as real markup instead, where they can wrap."""
    if not blocks:
        return ""
    pad = max(len(k) for _t, r in blocks for k, _v in r)
    out = []
    for title, rws in blocks:
        if title:
            out += ["", f"{indent}{title}"]
        out += [f"{indent}{k.ljust(pad)}   {v}" for k, v in rws]
    return "\n".join(out)


def infobox_html(blocks):
    """The same rows as a description list, so values wrap instead of
    scrolling.

    A <pre> can only scroll: a long value like Saturn's moon count ran off
    the side of a 390px sidebar with no way to read the rest. A <dl> laid out
    as a two-column grid wraps the value and keeps the key on the first line
    of it, which is what makes a wrapped row still read as one fact."""
    if not blocks:
        return ""
    out = ['<dl class="obj-facts">']
    boxed = False
    for title, rows in blocks:
        if title == TONIGHT_BLOCK:
            # Its own list, so it can be boxed. The rest of the infobox is
            # one grid and a section inside it is only a heading row -- there
            # is nothing to draw a border around without closing the list
            # and opening another.
            out.append('</dl><dl class="obj-facts obj-tonight">')
            boxed = True
        elif boxed:
            # And closed again at the next section, or the border runs on
            # around Physical and History as well -- everything after it,
            # in fact, since nothing else ever ended the list.
            out.append('</dl><dl class="obj-facts">')
            boxed = False
        if title:
            out.append(f'<dt class="obj-sec" role="presentation">'
                       f'{html.escape(title)}</dt><dd class="obj-sec"></dd>')
        for k, v in rows:
            # Everything after the first comma is a conversion or a gloss on
            # the number before it -- "9 Earths across", "1.06x Earth's",
            # "-139 C". Set smaller and dimmer so the measurement itself
            # carries the row and the restatement supports it.
            head, sep, tail = str(v).partition(", ")
            val = html.escape(head)
            if sep:
                val += f'<span class="sec">{html.escape(tail)}</span>'
            out.append(f"<dt>{html.escape(str(k))}</dt><dd>{val}</dd>")
    out.append("</dl>")
    return "".join(out)



# Names that take a plural verb. Every meteor shower does, by kind; these are
# the ones that do without being one.
_PLURAL_NAMES = frozenset({"Pleiades", "Hyades V", "The Pointers"})

# Names that read wrong without a definite article. The Sun, the Moon and
# every meteor shower take one by kind; these are the rest.
_TAKES_THE = frozenset({"Pleiades", "Big Dipper", "Little Dipper",
                        "Summer Triangle", "Winter Triangle", "Spring Triangle",
                        "Northern Cross", "Southern Cross", "False Cross",
                        "Great Square", "Winter Hexagon", "Great Diamond",
                        "Double Cluster", "Teapot", "Sickle", "Keystone",
                        "Hyades V", "Kite", "Milky Way"})

# Everything in the solar system drifts against the background stars, so
# anything derived from where it currently sits is a live fact rather than a
# durable one. Everything else is fixed: Sirius has been in Canis Major for
# the whole of recorded history and will be for the rest of it.
_SOLAR_SYSTEM_KINDS = frozenset({"planet", "moon", "sun"})


def _MOVES_AGAINST_THE_SKY(facts):
    return facts.get("kind") in _SOLAR_SYSTEM_KINDS


# Order from the Sun. Earth is third, which is why Mars is fourth.
_PLANET_ORDER = {"Mercury": 1, "Venus": 2, "Mars": 4, "Jupiter": 5,
                 "Saturn": 6, "Uranus": 7, "Neptune": 8}
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th",
             6: "6th", 7: "7th", 8: "8th"}

# What kind of planet, which is the thing the ordinal alone does not say.
# "The 6th planet in the solar system" is a position in a list; "a gas giant"
# is what you are actually looking at.
# The astronomical symbols. Neither bundled font has any of them and DejaVu
# has all of them, so the PNG path picks them up through the same fallback
# the deep-sky marks use; a terminal shows them if the reader's own font has
# them, and a box if not, which is the same deal every other symbol on this
# site offers.
PLANET_SYMBOLS = {
    "Sun": "\u2609", "Moon": "\u263e", "Mercury": "\u263f", "Venus": "\u2640",
    "Mars": "\u2642", "Jupiter": "\u2643", "Saturn": "\u2644",
    "Uranus": "\u2645", "Neptune": "\u2646",
}

_PLANET_CLASS = {
    "Mercury": "a rocky world", "Venus": "a rocky world",
    "Mars": "a rocky world",
    "Jupiter": "a gas giant", "Saturn": "a gas giant",
    "Uranus": "an ice giant", "Neptune": "an ice giant",
}


def object_descriptor(facts):
    """What this object is, in a phrase that completes "X is ...".

    One source for the page's opening line and the social card's subtitle, so
    the two can never say different things about the same object.

    Nothing here may depend on where the reader is or on the date. A planet
    gets its place from the Sun rather than the constellation it is currently
    crossing: the order never changes, and the constellation changes every
    few months for a planet and every two or three days for the Moon.
    """
    kind = facts.get("kind")
    if kind == "planet":
        name = facts.get("object")
        n = _PLANET_ORDER.get(name)
        cls = _PLANET_CLASS.get(name)
        if n and cls:
            return f"the {_ORDINALS[n]} planet in the solar system, {cls}"
        return (f"the {_ORDINALS[n]} planet in the solar system" if n
                else "a planet in the solar system")
    if kind == "sun":
        return "the star we orbit"
    if kind == "moon":
        return "Earth's only moon"
    if kind == "milkyway":
        # Not "a galaxy in Sagittarius". That is where its centre happens to
        # lie, and it reads as though we were looking at the thing from
        # outside it. The constellation is still a row in the fact table,
        # where it answers "which way do I look" rather than "what is it".
        return "our home galaxy"
    word = _KIND_WORD.get(kind, "object")
    article = "an" if word[0] in "aeiou" else "a"
    con = facts.get("constellation")
    if con and not _MOVES_AGAINST_THE_SKY(facts):
        return f"{article} {word} in {con}"
    return f"{article} {word}"


def evolution_lines(tgt, canonical, c=True):
    """The shape of an asterism at -50,000 years, now and +50,000, with what
    changed underneath it. [] for anything that is not an asterism.

    Only asterisms, because a shape is the only thing here that can deform:
    one star moving is a fact for its own page, not a picture. It sits at the
    bottom of the page because it is the least perishable thing on it -- the
    chart above changes every few minutes and this changes never.
    """
    if tgt.get("kind") != "asterism":
        return []
    s = motion.summary(canonical)
    if not s:
        return []
    body = motion.panels(canonical, colour=c)
    if not body:
        return []

    stars = {x["hr"]: x for x in sky._load("stars.json")}
    def name_of(hr):
        return (stars.get(hr) or {}).get("n") or f"HR {hr}"

    L = [paint("  " + evolution_title(canonical), C.HEAD, c), ""]
    L += ["  " + l for l in body]
    L.append("")
    import textwrap
    for line in textwrap.wrap(evolution_caption(canonical), 94):
        L.append(paint("  " + line, C.LABEL, c))
    L.append("")
    L.append(paint(f"  curl '{brand.SITE}/{quote(canonical)}/evolution.gif'",
                   C.MUTE, c))
    return L


def evolution_title(canonical):
    return f"The evolution of {canonical} over time"


def evolution_caption(canonical):
    """The sentence under the panels. One function, because the terminal and
    the browser must not be able to say different things about the same
    picture."""
    s = motion.summary(canonical)
    if not s:
        return ""
    stars = {x["hr"]: x for x in sky._load("stars.json")}

    def name_of(hr):
        return (stars.get(hr) or {}).get("n") or f"HR {hr}"

    out = [f"Over {s['span']:,} years either way the longest side of this "
           f"figure changes by {s['deform']:.0f}%, and the furthest any of "
           f"its stars travels is {s['moved']:.1f} degrees."]
    # Which way they are heading, not how fast. The Big Dipper's five middle
    # stars share a direction because they really are one physical group and
    # its two ends are not members of it -- but that is a fact about those
    # seven stars, and what gets said here is only what the proper motions
    # themselves show.
    if s["apart"] and len(s["with_group"]) >= 2:
        out.append(f"{_and_list([name_of(h) for h in s['apart']])} "
                   f"{'drifts' if len(s['apart']) == 1 else 'drift'} the "
                   f"opposite way to the other {len(s['with_group'])}, which "
                   f"travel together.")
    if s["flagged"]:
        out.append(f"{_and_list([name_of(h) for h in s['flagged']])} has no "
                   f"measured distance, so its path is extrapolated flat.")
    out.append("Proper motion only: this is the shape changing, not the sky "
               "turning or the pole moving.")
    return " ".join(out)


def evolution_gif_html(canonical, escape=html.escape):
    """The animation, under the panels it belongs to.

    Drawn at twice the width given here and shown at this one, which is the
    only way a bitmap sits beside page text without looking soft: the
    browser renders its own words at whatever the screen really is, and a
    1x image next to them gets stretched by the display. 680px is also
    about what 96 columns of 12px monospace occupy, so it lines up with the
    panels above it.

    ?v= is the render version, because the image is cached for a week and
    nothing else in the URL changes when the drawing does.
    """
    if not motion.asterism(canonical):
        return ""
    src = f"/{quote(canonical)}/evolution.gif?v={motion.RENDER_VERSION}"
    return (f'<img class="obj-evo-gif" src="{src}" alt="'
            f'{escape(canonical)} over {motion.SPAN * 2:,} years" '
            f'loading="lazy" width="{motion.GIF_CSS_WIDTH}">')


def style_evolution_title(markup, canonical, _re=re):
    """Give the section's title its own class inside the rendered <pre>.

    The panels reach the browser as part of the live column's text, so the
    title arrives as one more coloured span in a block of preformatted
    output and there is nothing for a stylesheet to aim at. This puts a
    class on that span and nothing else, which is what lets it be set like
    the eclipse page's section labels rather than like chart text.
    """
    title = evolution_title(canonical)
    pattern = (r'<span[^>]*>(\s*)' + _re.escape(title) + r'</span>')
    return _re.sub(pattern,
                   lambda m: f'<span class="obj-evo-title">{m.group(1)}'
                             f'{title}</span>', markup, count=1)


def link_star_labels(markup, canonical):
    """Turn the names drawn beside the stars into links to their own pages.

    Done on the rendered markup rather than while drawing, because the panel
    has to stay plain text for the terminal, where a link is not a thing that
    exists. Only the names this asterism actually drew are looked for, and
    the longest first so "Alkaid" inside a longer name cannot be matched
    first and leave a fragment behind.
    """
    a = motion.asterism(canonical)
    if not a:
        return markup
    stars = {s["hr"]: s for s in sky._load("stars.json")}
    names = sorted({(stars.get(hr) or {}).get("n") for hr in motion.members(a)}
                   - {None}, key=len, reverse=True)
    for name in names:
        if name in markup:
            markup = markup.replace(
                name, f'<a href="/{quote(name)}">{name}</a>')
    return markup


def _and_list(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def object_sources(facts):
    """Where the numbers on this page came from.

    Per object, not a fixed footer: a star page draws on BSC5 and Hipparcos,
    a planet page on JPL, a deep-sky page on the Revised NGC, and listing all
    of them everywhere would credit sources that had nothing to do with the
    page you are reading. Every entry here is also in LICENSES.md, which is
    where the licensing reasoning lives; this is attribution, not a licence
    notice.
    """
    kind = facts.get("kind")
    out = []
    if kind == "milkyway":
        # It is in no catalogue of things to point at, so the deep-sky
        # credit that used to appear here was simply wrong: the Revised NGC
        # has nothing to say about the galaxy it was compiled from inside.
        out.append("Galactic centre position (Sgr A*) from the IAU "
                   "galactic coordinate definition")
        out.append("sky brightness from the World Atlas of Artificial Night "
                   "Sky Brightness")
    elif kind in ("planet", "moon", "sun"):
        out.append("Physical data from NASA/JPL Horizons")
        out.append("positions from JPL approximate elements")
    elif kind == "star":
        st = facts.get("star", {})
        bits = []
        if st.get("spectral_type"):
            bits.append("spectrum")
        if bits or True:
            out.append("Position"
                       + (" and " + " and ".join(bits) if bits else "")
                       + " from the Yale Bright Star Catalogue")
        if st.get("light_years"):
            out.append("distance from Hipparcos (ESA 1997)")
        if st.get("next_minimum"):
            out.append("variability from the General Catalogue of "
                       "Variable Stars")
    elif kind == "radiant":
        out.append("Shower timing and rates cross-checked against the IMO "
                   "Meteor Shower Calendar")
    elif kind:
        out.append("Position from the Revised NGC (Sulentic & Tifft 1973), "
                   "after Dreyer 1888")
        if facts.get("size_arcmin"):
            out.append("apparent size from published visual dimensions")
        # Only where there is a drawing, and only the figures that drawing
        # actually used -- art.dso_art_basis answers per object, because a
        # galaxy has no concentration class and a globular has no angle. The
        # portrait is a model rather than a photograph, and what it is built on
        # is measured: LICENSES.md has where each figure came from, and why
        # reading them one at a time is a different act from extracting a
        # catalogue.
        out += art.dso_art_basis(facts.get("object"))
    if facts.get("constellation"):
        out.append("constellation boundaries after Delporte (1930)")
    if not out:
        return ""
    # Semicolons, not full stops: these are clauses of one credit, and
    # joining them with periods left every clause after the first starting
    # in lower case.
    return "; ".join(out) + "."


def object_intro(facts, canonical, width=76):
    """Title, one-line gloss and the paragraph under it.

    Hand-written where we have one, generated from the catalogue where we do
    not. The generated version is deliberately thin: it can only restate what
    the infobox already says, and dressing that up as prose is the
    programmatic filler that costs a site its standing rather than earning
    it any.
    """
    import textwrap
    # blurbs.py is parked, not deleted: the paragraphs read as generic
    # astronomy filler next to the facts, which are specific to the object by
    # construction. The file is still there if the one-line gloss earns a
    # place later.
    # blurbs.py is parked: the paragraphs read as generic astronomy filler
    # next to facts that are specific to the object by construction. The
    # opening line is the descriptor the social card uses as its subtitle,
    # so the page and the card say the same thing.
    gloss, blurb = object_descriptor(facts), None

    # Meteor showers and a few clusters carry plural names, and "Perseids is
    # the most reliable shower of the year" reads as a typo.
    verb = "are" if (facts.get("kind") == "radiant"
                     or canonical in _PLURAL_NAMES) else "is"
    # Some names carry a definite article in ordinary use and read as a
    # telegram without it: "Sun is the star we orbit", "Perseids are a
    # meteor shower". Meteor showers all take one, by kind.
    subject = (f"The {canonical}"
               if (facts.get("kind") in ("sun", "moon", "radiant")
                   or canonical in _TAKES_THE) else canonical)
    out = [f"{subject} {verb} {gloss}."]
    if blurb:
        out.append("")
        out.extend(textwrap.wrap(blurb, width))
    return "\n".join(out)


def compose_object(r, canonical):
    """The object page: the find view's chart and crosshair, with the object's
    own facts under it.

    Built on _compose_find deliberately rather than beside it. That view
    already solves the hard parts -- where the thing is, whether it is up,
    when it is next up if it is not, and a chart with a mark on it -- and a
    second implementation would be a second set of answers to drift apart.
    """
    # Work on a copy. This function moves the clock to the best moment, and
    # the caller reuses its Request to build every rung of the width ladder
    # -- so mutating it in place meant each rung was composed from an
    # already-shifted clock, decided the object was up "now", and produced a
    # page that said "Zurich now" on first load and the real moment on
    # refresh depending on which pass had populated the cache.
    r = copy.copy(r)
    r.find = canonical
    # Now if it is up, the best moment tonight otherwise.
    #
    # _compose_find falls back to next_visible(), which returns the FIRST
    # moment an object clears the horizon in a dark sky. For an object page
    # that is the wrong question: it drew Saturn at 13 degrees in the east
    # while the same page said it reaches 46 at 05:19, so the chart showed
    # the least interesting view that qualified and disagreed with the line
    # underneath it. When it is genuinely up now, now is still right.
    #
    # The shift has to be remembered. _compose_find reports whether IT moved
    # the clock, and once the clock is moved before calling it, it sees a
    # request for that moment and truthfully answers "now" -- so the page
    # said "Right now from Zurich" at half past two in the afternoon with
    # Saturn nowhere near the sky. shifted_to carries what actually happened.
    shifted_to = None
    real_now = r.when_utc
    jd_now = julian(r.when_utc)
    lst_now = (gmst_hours(jd_now) + r.place.lon / 15.0) % 24
    tgt_now = resolve_target(canonical, jd_now, r.place.lat, lst_now)
    if tgt_now is not None and not r.when_explicit:
        # A meteor shower is a date, not a tonight. Its radiant clears the
        # horizon on most nights of the year, so drawing tonight's sky put
        # the Geminids on a page headed "Zurich tonight" in August, four
        # months from anything falling. The peak is the only night that
        # matters, so that is the night to draw.
        if tgt_now.get("kind") == "radiant":
            peak = objects.best_this_year(tgt_now, r.place.lat, r.place.lon,
                                          r.when_utc)
            at = peak and objects.best_tonight(
                tgt_now, r.place.lat, r.place.lon,
                peak["when_utc"] - dt.timedelta(hours=12))
            if at:
                shifted_to = at
                r.when_utc = at
                r.when_local = at + dt.timedelta(hours=r.place.offset(at))
                r.find = canonical
        up_now, _why = visibility(tgt_now, jd_now, r.place.lat, lst_now)
        if shifted_to is None and not up_now:
            best = objects.best_tonight(tgt_now, r.place.lat, r.place.lon,
                                        r.when_utc)
            if best:
                shifted_to = best
                r.when_utc = best
                r.when_local = best + dt.timedelta(hours=r.place.offset(best))
                r.find = canonical
    res = _compose_find(r)
    if res.status != 200:
        return res

    # The find view tells us which moment it actually drew. When the object
    # is below the horizon that is the next time it is up, not now, and the
    # prose has to agree with the picture above it.
    shown = shifted_to
    raw = res.data.get("shown_utc")
    if raw and shown is None:
        try:
            parsed = dt.datetime.fromisoformat(raw.rstrip("Z"))
            if abs((parsed - real_now).total_seconds()) > 60:
                shown = parsed
        except ValueError:
            pass

    when = shown or r.when_utc
    jd = julian(when)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    tgt = resolve_target(canonical, jd, r.place.lat, lst)
    if tgt is None:
        return res

    facts = object_facts(tgt, r, canonical, shown_utc=shown)
    width = _effective_width(r) - 4
    c = r.color

    # Evergreen first, live second. Deliberately this way round.
    #
    # A crawler sees a different page every time it visits: the altitude has
    # moved, the chart is redrawn, the rise time is an hour later. There is
    # nothing for it to decide what /Venus is *about*. And a person arriving
    # from a shared link is being told an azimuth before they have been told
    # what they are looking at, which is an answer to a question they have
    # not asked. What the object is does not change; where it is tonight
    # depends entirely on the reader. So the first belongs on top, and the
    # second belongs under a heading that says whose sky it is.
    # The glyph in the chart's own colour for this object, not the heading's.
    # Painting the whole line C.HEAD made every mark white, so Saturn's gold
    # diamond and M31's green spiral both came out looking like plain text.
    # Glyph AND name in the object's own colour, the way /catalog lists them.
    # The catalog is where people first see these marks, so a page that
    # colours the glyph and then prints the name in plain white reads as a
    # different object than the row they clicked.
    g = facts.get("glyph") or ""
    gc = facts.get("glyph_ansi") or C.HEAD
    head = ("  " + (paint(g, gc, c) + " " if g else "") + paint(canonical, gc, c))
    # The event, when the page was opened for one, after the object's own
    # name and set quieter than it. This line is the <h1>: a page reached by
    # clicking "Saturn at opposition" said only "Saturn" in the one place a
    # reader and a search engine both look for what a page is about.
    tail = _event_subhead(facts, canonical)
    if tail:
        head += paint(f"  /  {tail}", C.MUTE, c)
    intro = "\n".join(paint("  " + l if l else "", C.LABEL, c)
                      for l in object_intro(facts, canonical, width).split("\n"))
    blocks = object_infobox(facts, tgt, width)
    box = infobox_text(blocks)
    box = "\n".join(paint(l, C.MUTE, c) for l in box.split("\n")) if box else ""

    # The heading names the moment the chart is actually drawn for.
    #
    # "Tonight from Zurich" was true and useless: the chart below it is drawn
    # for one specific minute, chosen as the best of the night, and not
    # saying which minute left the reader to find it in the timing line.
    # Naming it makes the heading the answer to "when do I go outside".
    #
    # One space, not two, so the heading sits in the same column as the
    # chart's altitude labels beneath it and the live half has one left edge.
    # One line above the chart, not three.
    #
    # The heading, the timing row and the find view's summary all described
    # the same moment and repeated each other: the object's name (the title
    # already says it), its altitude (twice), and nine words of "next optimal
    # sighting window from" wrapped around a timestamp. What is left is the
    # when, the where to look, the brightness, and the shape of the night.
    shown_local = facts.get("shown_utc")
    # is_now means the chart was drawn for the moment asked for rather than
    # shifted to the next time the thing is up. That is not the same as the
    # moment being the present one, and reading it as such is how a page
    # opened from an event -- /Zurich/Saturn?t=2026-10-05T01:13, a date
    # eight weeks out -- announced itself as "Zurich now".
    if facts.get("is_now") and not r.when_explicit:
        stamp = "now"
    elif shown_local:
        when = dt.datetime.fromisoformat(shown_local.rstrip("Z"))
        when += dt.timedelta(hours=r.place.offset(when))
        # Always the date, never "tonight". A page can be drawn for a moment
        # months away, and a reader who scrolls to it later has no idea when
        # "tonight" was written. The date is never wrong.
        stamp = f"{when:%a %-d %b} {when:%H:%M}"
    else:
        stamp = "tonight"

    bits = [f"{r.place.name} {stamp}"]
    if tgt.get("alt") is not None and tgt["alt"] > 0:
        what = "radiant " if tgt.get("kind") == "radiant" else ""
        bits.append(f"{what}{tgt['alt']:.0f}\u00b0 up in the {compass(tgt['az'])}")
    if tgt.get("mag") is not None and tgt.get("kind") not in ("asterism", "radiant", "milkyway"):
        bits.append(f"mag {tgt['mag']:.1f}")
    timing = object_timing(facts)
    if timing:
        bits.append(timing)
    # Two spaces, like every other line the page draws. These three lines are
    # lifted out of the <pre> into real HTML for the browser, and being the
    # only ones written by hand they were the only ones a character short of
    # the margin everything else keeps.
    live_head = paint("  " + "  \u00b7  ".join(bits), C.HEAD, c)

    # And under it, quietly, what the line above actually is and when the
    # year's best night falls. The condensed line answers "tonight"; this
    # answers "is tonight worth it, or should I wait".
    sub_bits = []
    b = facts.get("best_this_year")
    is_shower = bool(b and b.get("is_peak"))
    # Some things are up and still not there. The band needs a dark sky, not
    # merely a set Sun, so from a city the honest line is that it never
    # shows -- "next best sighting opportunity" promised one that will not
    # come, on the same page that had just said the sky is too bright.
    never = (facts.get("galaxy") or {}).get("visible_here") is False
    if never:
        sub_bits.append(f"Never shows in {facts.get('place', 'this sky')}")
    elif is_shower:
        sub_bits.append("The chart is drawn for the peak night")
    elif not facts.get("is_now"):
        sub_bits.append("Next best sighting opportunity")
    if b and not never:
        when = dt.datetime.fromisoformat(b["date"])
        # "this year" was wrong: best_this_year searches 365 days from
        # today, not to the end of December. In August it was routinely
        # naming a date the following February and calling it this year.
        label = "peaks" if is_shower else "best in the next 12 months"
        line = f"{label} on {when:%-d %B %Y}"
        # And why that date, right here rather than in a paragraph under the
        # chart where nobody found it. A reader on an event night is being
        # pointed a year away and the reason is one clause long.
        here_moon = facts.get("moon_illum")
        ev = (facts.get("tonight_events") or [None])[0]
        if (ev and here_moon is not None and b.get("moon_illum") is not None
                and here_moon - b["moon_illum"] > 0.2):
            # Both dates named. "Tonight" is a word for a page about
            # tonight; this one can be opened in August for a night in
            # October, and it was saying "34% lit tonight" about neither.
            night = dt.datetime.fromisoformat(ev["date_local"])
            line += (f", when the Moon is out of the way "
                     f"({here_moon:.0%} lit on {night:%-d %b}, "
                     f"{b['moon_illum']:.0%} on {when:%-d %b %Y})")
        sub_bits.append(line)
    # Each part is its own sentence, so each starts with a capital.
    sub_bits = [b[0].upper() + b[1:] for b in sub_bits]
    live_sub = paint("  " + ". ".join(sub_bits) + ".", C.MUTE, c) if sub_bits else ""

    # And under that, what the event beside the heading actually is. One
    # line, the same for everybody, and only where there is an event to
    # explain.
    note = event_note(facts)
    # Wrapped to the render width like every other paragraph on the page,
    # less the margin it is indented by. The browser gets it as one <p>
    # either way, since a newline inside one is just a space; the terminal is
    # the half that cannot reflow.
    # In the planet tan rather than the muted grey the two lines above it
    # use. Those are readings off the sky and this is a note about it, and
    # in the same grey it read as a third one.
    import textwrap
    live_what = "\n".join(paint("  " + l, C.PLANET, c)
                          for l in textwrap.wrap(note, width - 2)) if note else ""

    prose = object_prose(facts, tgt, r, width=width)
    body = "\n".join(paint("  " + l if l else "", C.LABEL, c)
                     for l in prose.split("\n"))

    # The portrait, between the one-line description and the fact table.
    # Emitted into the shared text rather than only into the markup, so the
    # terminal gets it too -- it is characters, which is the whole reason it
    # is drawn rather than photographed.
    picture = art.art_for(facts) if c else []
    parts = ["", head, "", intro]
    if picture:
        parts += [""] + ["  " + l for l in picture]
    if box:
        parts += ["", box]
    # The find view opens with its own header line ("Zurich 06 Aug 2026,
    # finding Saturn, full panorama"), which directly under "Tonight from
    # Zurich" says the place and the object twice in two lines.
    live = strip_footer_line(res.text).rstrip()
    live_lines = live.split("\n")
    for i, l in enumerate(live_lines[:4]):
        if "finding" in l and canonical.split()[0] in l:
            live_lines.pop(i)
            break
    live = "\n".join(live_lines).strip("\n")

    # Only the timing line goes above the chart. Everything else -- what it
    # is crossing, how far, the rings, the best night this year -- reads
    # after the picture, because it is context rather than a reason to go
    # outside in the next hour.
    # Last on the page, under everything the reader came for. It is the one
    # block here that is the same for every visitor on every night, which is
    # also why the browser lifts it out into its own full-width section
    # rather than squeezing it into either column.
    evo = evolution_lines(tgt, canonical, c)
    parts += [OBJECT_SLOT, live_head, live_sub]
    # Only when there is one. An empty seam would leave a blank line in the
    # terminal on every page that has no event, which is most of them.
    if live_what:
        parts += [OBJWHAT_SLOT, live_what]
    parts += [OBJPROSE_SLOT, live, "", body, ""]
    if evo:
        parts += evo + [""]
    parts += [_footer(r.place, c), ""]
    text = "\n".join(parts)
    data = dict(res.data)
    data.update(facts)
    if picture:
        data["art"] = picture
    if evo:
        data["evolution"] = evo
    # Carried so the browser can lay the same rows out as real markup rather
    # than re-deriving them, and so ?format=json exposes them too.
    data["infobox"] = [[t, [list(x) for x in r]] for t, r in blocks]
    return Result(text, data, 200)


def object_where_line(facts):
    """"12° above the eastern horizon" -- the one line the social card leads
    with, and the only thing on it that changes hour to hour."""
    alt, az = facts.get("alt"), facts.get("az")
    if alt is None or az is None:
        return None
    if facts.get("never_rises"):
        return "never rises from here"
    if alt <= 0:
        rise = facts.get("rise")
        return f"below the horizon, rises {rise[11:16]}" if rise else "below the horizon"
    return f"{alt:.0f}° above the horizon in the {compass(az)}"


def object_title(facts):
    """The <title>, which is also what a search result shows as its heading.
    Front-loaded with the object because that is the word someone searched
    for, and no site name padding -- it costs characters that the useful part
    needs."""
    name = facts["object"]
    kind = _KIND_WORD.get(facts.get("kind"), "")
    # No place in here. This is the <title> and the twitter:title, and both
    # are read by an unfurler once and then shown to everybody who sees the
    # post -- so "from Zurich" on a link somebody shared in Tokyo is wrong
    # for every reader but the one who posted it, and on a crawler it names
    # whichever city its datacentre sits in. The page says where you are,
    # per visitor, further down.
    #
    # "the" only for the two that take it. Planets are proper nouns and were
    # coming out as "where to see the venus tonight", article, lowercase and
    # all.
    article = "the " if kind in ("moon", "sun") else ""
    # "tonight" is only true for a page about tonight. Opened from an event
    # -- ?t=2026-10-05T01:13, eight weeks out -- the title said tonight
    # while the page underneath it described October, and the title is the
    # line a search result and a shared link both show.
    if facts.get("when_explicit") and facts.get("shown_local"):
        when = dt.datetime.fromisoformat(facts["shown_local"])
        # The reason the page was opened, when there is one. Somebody who
        # clicked "Saturn at opposition" in a list of events should land on
        # a page whose title says that, rather than one offering to show
        # them Saturn on a date with no indication of why that date.
        tonight = facts.get("tonight_events") or []
        if tonight:
            # The event's own date, not the moment the chart is drawn for.
            # The two differ by a night boundary and the list said the 4th
            # while this said the 5th.
            day = dt.datetime.fromisoformat(tonight[0]["date_local"])
            return f"{tonight[0]['name']}, {day:%-d %B %Y}"
        return f"{name}: where to see {article}{name} on {when:%-d %B %Y}"
    return f"{name}: where to see {article}{name} tonight"


# Every kind sky.resolve_target() can return. Missing keys do not fail, they
# fall through to "object" and print "a object in Ophiuchus", which is how
# the cluster, nebula and planetary-nebula pages read before this. There is a
# test walking the whole namespace so a new type cannot slip through.
_KIND_WORD = {"planet": "planet", "star": "star", "moon": "moon", "sun": "sun",
              "milkyway": "galaxy",
              "asterism": "asterism", "radiant": "meteor shower",
              "galaxy": "galaxy", "cluster": "star cluster", "nebula": "nebula",
              "planetary nebula": "planetary nebula"}


def object_description(facts):
    """The meta description. One sentence of the most durable facts, because
    a crawler may see this page months apart and a description that changed
    every visit is a description that ranks for nothing."""
    name, bits = facts["object"], []
    if facts.get("constellation"):
        bits.append(f"in {facts['constellation']}")
    st = facts.get("star", {})
    if st.get("description"):
        bits.append(f"a {st['description']}")
        if st.get("light_years") and st.get("distance_confidence") == "good":
            bits.append(f"{st['light_years']:.0f} light years away")
    if facts.get("size_arcmin"):
        bits.append(f"{facts['size_arcmin']['maj']:g} arcminutes across")
    b = facts.get("best_this_year")
    lead = f"{name}, {', '.join(bits)}." if bits else f"{name}."
    tail = (f" Best seen around {b['date']}." if b else "")
    return (lead + tail + " Rise and set times, altitude and a chart for "
            "wherever you are.").strip()


# The generic social-card block every non-object page carries. Object pages
# replace this wholesale with their own head rather than adding to it, so a
# page never ends up advertising two different cards.
_GENERIC_HEAD_BLOCK = """\
<link rel="canonical" href="{canonical}">
<meta name="description" content="The night sky above you, as plain text. curl skymap.sh">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="The night sky above you, as plain text. No signup, no API key.">
<meta property="og:image" content="https://skymap.sh/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="skymap.sh">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://skymap.sh/og.png">"""


# The head of the shared page template, with the generic card block swapped
# for a slot. Derived from PAGE rather than copied, so the object pages keep
# every later change to the shell -- stylesheet, favicon, the width ladder --
# without a second copy to maintain, and without any of the six existing
# PAGE.format() call sites having to learn a new key.
def _object_page_template():
    return PAGE.replace(_GENERIC_HEAD_BLOCK, "{head_extra}", 1)


# Every canonical on the site points at the apex. www.skymap.sh serves the
# site directly rather than redirecting, so every page exists at two
# hostnames; this is what tells a crawler which of the two is the page.
# A redirect at the edge would be tidier still, but this needs no DNS.
CANONICAL_HOST = "https://skymap.sh"


def canonical_url(path):
    """The apex form of a path, for the page's rel="canonical".

    Two jobs, and both matter on this site. It names the host, since
    www.skymap.sh serves every page a second time. And it names the page
    without its query string, so /stats/daily?days=30 and a link someone
    shared with ?utm_source= on the end count as the page they are, not as
    a new one each.

    Pass the path the page wants to be known by, which is not always the
    path it was reached at -- /usage answers as /help, and every
    /{place}/{object} answers as the bare /{object}.
    """
    return CANONICAL_HOST + path


def home_head():
    """The generic card tags, plus a canonical at the apex."""
    return _GENERIC_HEAD_BLOCK.format(title="skymap.sh",
                                      canonical=canonical_url("/"))


def place_head(place, base_url):
    """The same head as an object page, for a place page.

    Place pages used to fall back to the generic card, so every city anyone
    shared unfurled as the same picture with the same words -- which says
    the site exists but not that the link is about Paris. This gives each
    one its own, and nothing on it depends on when the crawler asked.

    The canonical is the apex form of this same page. It is not collapsing
    two paths the way the object pages' one does -- a place page is the only
    path for that place -- it is naming the host, since www.skymap.sh serves
    every page a second time.
    """
    name = html.escape(place.name)
    title = f"skymap.sh: {name}"
    desc = html.escape(f"The night sky above {place.name}, as plain text. "
                       f"curl skymap.sh/{place.slug}")
    og = f"{base_url}/{quote(place.name)}/og.png"
    url = canonical_url("/" + quote(place.name))
    return "\n".join([
        f'<meta name="description" content="{desc}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{desc}">',
        f'<meta property="og:image" content="{og}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:site_name" content="skymap.sh">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{desc}">',
        f'<meta name="twitter:image" content="{og}">',
    ])


def object_head(facts, canonical, place, base_url):
    """Title, description, canonical and the social card tags.

    The canonical is the load-bearing one. /{place}/{object} is the same page
    with the location spelled out, and there are 40,803 cities times 1,220
    objects of those. Pointing every one at the bare /{object} keeps a
    crawler on roughly 1,200 real pages instead of fifty million
    near-identical ones, which is the difference between a namespace and a
    doorway farm.
    """
    title = html.escape(object_title(facts))
    desc = html.escape(object_description(facts))
    url = canonical_url("/" + quote(canonical))
    og = f"{base_url}/{quote(canonical)}/og.png"
    return "\n".join([
        f'<meta name="description" content="{desc}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="article">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{desc}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{og}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:site_name" content="skymap.sh">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{desc}">',
        f'<meta name="twitter:image" content="{og}">',
    ])


# The heading keeps the monospace face -- it is the same object name the
# chart and the catalog draw, and switching to a proportional font for one
# line makes it read as a different thing. Just bigger, and with the colour
# the ANSI already carries.
OBJECT_CSS = """
<style>
/* Aligned with the text block below it, not with the page margin.
   Every body line starts with two monospace spaces, so the heading needs
   the same two-character indent -- but `ch` resolves against the element's
   OWN font-size, and a 30px heading's `ch` is nearly three times the body's.
   So the h1 keeps the body's 11px for measurement and the span inside it
   carries the size. 2ch then means two body characters, exactly. */
.obj-title{display:flex;align-items:center;gap:.26em;
  font-size:30px;font-weight:600;letter-spacing:-.01em;
  line-height:1.15;margin:1.5rem 0 .35rem}
/* No left padding. It used to carry a two-character indent to line up with
   a <pre> underneath it; the static column is a description list now and
   starts at the column edge, so the heading does too.
   Flex rather than vertical-align: the glyph is a geometric mark and the
   name is lettering, so they share no baseline worth aligning on. Centring
   the two boxes on each other works whatever mark the object carries. */
.obj-title span{display:block}
@media (max-width:600px){.obj-title{font-size:23px}}

/* The static half and the live half, side by side. Sized off the chart: 110
   monospace columns at 11px is about 726px, so the sidebar takes what is
   left of the 1200px page cap. minmax keeps it from collapsing when the
   chart happens to be narrower. */
.obj-cols{display:grid;grid-template-columns:minmax(250px,390px) 1fr;
  gap:0 30px;align-items:start;margin-top:2px}
.obj-static{border-right:1px solid #1c2027;padding-right:24px}
.obj-static pre,.obj-live pre{overflow-x:auto}
/* The portrait is an .art-plate in an .art-frame (in PAGE, shared with the
   modal's frames): the cell ratio, the refusal to wrap and the centring are
   all there. This is only how big it is here. */
.obj-art{font-size:11px}
/* And this is only the plate it sits on, so the portrait reads as a picture
   rather than as loose characters that happened to land above the text. */
.obj-art-frame{border:1px solid #1c2027;border-radius:8px;background:#070a0e;
  padding:16px 10px;margin:.1rem 0 1.15rem;
  /* ROWS lines at 11px on a 1.2 line-height, so the plate is the same size
     for every object even before its drawing loads or if one ever comes
     back short. Without it the frame takes its height from the art and a
     shorter drawing would shift everything below it up the page. */
  min-height:225px;box-sizing:content-box}

/* The star names drawn beside the stars in the evolution panels, which are
   in the live column with everything else. Dimmer than a star, so a name
   reads as a label rather than as another thing in the sky, and underlined
   only on hover so seven of them do not turn a drawing into a list of
   links. */
.obj-live a[href^="/"]{color:#9aa7b4;text-decoration:none}
.obj-live a[href^="/"]:hover{color:#87d7ff;text-decoration:underline}
/* The section's own title, lifted out of the preformatted text by
   style_evolution_title so it can be set like the eclipse page's section
   labels (.ecl-maptitle) rather than like chart output. inline-block is
   what lets it take the space above it: a plain inline span inside a <pre>
   ignores vertical margin. */
.obj-live .obj-evo-title{display:inline-block;color:#8fb6e0;font-size:11px;
  letter-spacing:.09em;text-transform:uppercase;margin:1.5rem 0 .35rem;
  line-height:1.2}
/* The animation, hung off the bottom of the panels it belongs to. The width
   attribute on the <img> is half what the file really is -- see
   evolution_gif_html. margin-left is the two spaces every line of the
   preformatted block above it is indented by, which is 2 characters of
   12px monospace: without it the picture starts two characters to the left
   of the drawing it belongs to. */
.obj-evo-gif{display:block;max-width:100%;height:auto;
  margin:.9rem 0 1.2rem 14.4px;border-radius:8px;background:#070a0e}

/* The lede sentence and the fact rows. Proportional text, not monospace:
   these are sentences and numbers to read, not a drawing to preserve. */
.obj-lede{color:#c9d1d9;font-size:15px;line-height:1.5;margin:.1rem 0 1.1rem}
/* The live column's heading is the same sentence-sized text as the lede
   opposite it, and both sit at the top of their column so the two halves
   start on one line rather than a few pixels apart. */
.obj-live-head{margin:.1rem 0 .2rem;font-size:16.5px;color:#e6ebf2}
.obj-subhead{font-size:12.5px;line-height:1.4;color:#7d8694;margin:0 0 .8rem}
.obj-subhead a.ics{color:#8fb6e0;text-decoration:none;
  border-bottom:1px dotted #4b5568}
.obj-subhead a.ics:hover{color:#b7d4f5;border-bottom-color:#7f93ad}
.ics-i{width:1em;height:1em;vertical-align:-.14em;margin-right:.35em}
/* What the event named beside the heading actually is. The same monospace
   the title and the two readings above it are set in: one page, one
   typeface, and a sans-serif paragraph dropped into the middle of a
   terminal was the one thing up here that did not belong to the chart.
   Full width, with no measure of its own -- holding it to 62 characters
   while everything around it ran the whole width made it look like a stray
   column. Told apart by colour instead: the tan is xterm 180, the same the
   terminal paints it, because it is a note about the sky rather than a
   reading off it. */
.obj-what{font-size:12.5px;line-height:1.5;color:#d7af87;margin:-.4rem 0 .9rem}
/* The live column's text margin, in the browser. Every line under these
   three sits two characters in, because the chart's <pre> keeps them and a
   <pre> prints what it is given. These three are lifted out into real HTML,
   where a leading space is thrown away, so they alone started hard against
   the edge. 14.4px is those two characters -- CHART_FONT_PX at the 0.6
   advance every monospace in the stack uses.
   The heading is not in here: it lines up with the frame at the top of the
   static column, not with the chart's text. Nor is the eclipse page's head,
   which shares .obj-live-head and lays its times out its own way. */
.obj-live .obj-lede:not(.ecl-head),
.obj-live .obj-subhead,.obj-live .obj-what{padding-left:14.4px}
.obj-cols>*{margin-top:0}
.obj-facts{display:grid;grid-template-columns:auto 1fr;gap:.42rem .95rem;
  margin:0;font-size:13.5px;line-height:1.45}
.obj-facts dt{color:#7d8694;white-space:nowrap;align-self:start}
.obj-facts dd{color:#c9d1d9;margin:0;overflow-wrap:anywhere}
/* The conversion after the number, not the number. */
.obj-facts .sec{display:block;color:#8b93a3;font-size:12px;line-height:1.35;
  margin-top:.05rem}
/* Where the numbers came from. Quiet on purpose: it is a credit, and a
   reader who wants it will look for it at the foot of the facts. */


.obj-src{font-style:italic;font-size:11px;line-height:1.45;color:#666e7d;
  margin:1.4rem 0 0;padding-top:.7rem;border-top:1px solid #1c2027}
/* The live half's prose, above its chart, in the chart's own face and size
   so the two read as one block. */
.obj-prose{font-size:12px;line-height:1.45;color:#adb6c4;margin:0 0 .7rem;
  white-space:pre-wrap}
/* This object's events, beside its name. Same shape as the eclipse page's
   picker (.ecl-picker), because it is the same control doing the same job:
   what this page is showing, and the others you could switch to. Repeated
   rather than shared -- those rules live in ECLIPSE_CSS, which an object
   page does not load. */
/* Same 1.5rem above it as .ecl-head-row, and as a bare .obj-title on a page
   with no picker -- wrapping the heading in a row zeroed its own margin and
   took the space with it, so the name sat tight under the command bar on
   exactly the pages that had gained something to put beside it. */
/* No left padding here either, for the reason .obj-title gives above: the
   heading starts at the column edge because the frame under it does.
   Room underneath, because the row is a heading and a control side by side
   and 14px let the frame crowd both. */
.obj-head-row{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  margin:1.5rem 0 26px}
.obj-head-row .obj-title{margin:0}
.obj-picker{position:relative;margin:0}
.obj-picker summary{cursor:pointer;color:#c9d1d9;font-size:13px;
  list-style:none;display:inline-flex;align-items:center;gap:10px;
  border:1px solid #8fb6e0;border-radius:6px;padding:6px 12px}
.obj-picker summary::-webkit-details-marker{display:none}
.obj-picker summary:hover,.obj-picker[open] summary{border-color:#c9d1d9}
.obj-more{color:#6e7681;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase}
.obj-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:30;
  min-width:280px;background:#0d1117;border:1px solid #30363d;
  border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.7)}
.obj-panel ul{list-style:none;margin:0;padding:8px 12px}
.obj-panel li{padding:3px 0;font-size:13px;white-space:nowrap}
.obj-panel li a{color:#87d7ff;text-decoration:none}
.obj-panel li a:hover{text-decoration:underline}
/* The one you are looking at, marked rather than linked away from. */
.obj-pick-here a{color:#c9d1d9}

/* What is happening tonight, boxed. It is the one block on this column
   that is not a durable fact about the object, and the reason the page was
   opened at all when it arrives from an event list, so it reads as a note
   pinned to the page rather than as two more rows of the table. The border
   is the same blue the section headings are set in. */
.obj-tonight{border:1px solid #2c4a6b;border-radius:7px;
  padding:.55rem .75rem .7rem;margin:.9rem 0 1.1rem;background:#0b1119}
.obj-tonight dt.obj-sec{margin-top:0}
/* Section headings span the pair and sit above their rows. */
.obj-facts dt.obj-sec{grid-column:1 / -1;color:#8fb6e0;font-size:11px;
  letter-spacing:.09em;text-transform:uppercase;margin:.85rem 0 .1rem}
.obj-facts dd.obj-sec{display:none}
@media (max-width:1000px){
  .obj-cols{grid-template-columns:1fr;gap:0}
  .obj-static{border-right:0;padding-right:0;border-bottom:1px solid #1c2027;
    padding-bottom:12px;margin-bottom:14px}
}
</style>"""


def _link_best_date(sub_html, canonical, data):
    """Turn the best-night date into a calendar download.

    A date on a page is a thing to forget; the same date in a calendar is a
    thing that happens. The link is only added where the date actually
    appears, so nothing changes for an object that has no best night."""
    b = (data or {}).get("best_this_year")
    if not b:
        return sub_html
    try:
        when = dt.datetime.fromisoformat(b["date"])
    except (ValueError, KeyError):
        return sub_html
    shown = f"{when:%-d %B %Y}"
    if shown not in sub_html:
        return sub_html
    href = html.escape(f"/{quote(canonical)}/best.ics")
    # Drawn as an SVG rather than set as an emoji: this line is monospace
    # and a colour emoji lands in it as a different typeface at a different
    # size. The mark inherits the link colour and scales with the text.
    icon = ('<svg class="ics-i" viewBox="0 0 16 16" aria-hidden="true">'
            '<rect x="1.5" y="3" width="13" height="11.5" rx="1.5" '
            'fill="none" stroke="currentColor" stroke-width="1.3"/>'
            '<path d="M1.5 6.5h13M5 1.5v3M11 1.5v3" stroke="currentColor" '
            'stroke-width="1.3" stroke-linecap="round"/></svg>')
    link = (f'<a class="ics" href="{href}" download '
            f'title="add to calendar">{icon}{shown}</a>')
    return sub_html.replace(shown, link, 1)


def link_clears_places(chart_html, canonical, data, q=""):
    """The places in "it clears the horizon south of about 44°N: Cevennes or
    Carcassonne", as links to this same object seen from there.

    Naming them and leaving them as words is a tease: the page has just told
    somebody where to go and then made them type it. It knows exactly which
    names it printed -- they came back from where_it_clears, and each was put
    through the forty-day search before being printed at all -- so nothing
    here has to guess at which words in the chart are places.

    The night travels with the link. The sentence is about the night this
    page is drawn for, so dropping the moment would land the reader on
    tonight somewhere else -- a different question from the one they were
    reading. Read as a wall clock at the place being opened rather than
    converted, which is the same evening either way and is what ?t means
    everywhere else on the site.

    A plain replace, the way the calendar link on the line above is done.
    Only in the tail after the sentence starts, so a name that is also a word
    in the prose higher up is not the one that gets linked. A name broken
    over a line end simply keeps its link: the check below misses it, which
    leaves the text exactly as it was.
    """
    head, sep, tail = chart_html.partition(CLEARS_LEAD)
    if not sep:
        return chart_html
    for name in ((data or {}).get("clears_at") or {}).get("places") or []:
        esc = html.escape(name)
        if esc not in tail:
            continue
        href = html.escape(f"/{quote(name)}/{quote(canonical)}{q}")
        tail = tail.replace(esc, f'<a href="{href}">{esc}</a>', 1)
    return head + sep + tail


def _first_para(text):
    """The descriptor sentence, which is the SECOND non-empty line: the first
    is the title, and that is emitted separately as the h1."""
    seen = 0
    for l in text.split("\n"):
        if l.strip():
            seen += 1
            if seen == 2:
                return l
    return ""


def _strip_title(text):
    """Drop the heading line, which is emitted as an <h1> above the columns
    rather than left at the top of the static block."""
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if l.strip():
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return text


# Every fact on these pages comes from a catalogue, a hand-written table or
# a calculation, and any of the three can be wrong about one object without
# being wrong in general. A reader who knows Saturn has 274 moons and not 82
# is the cheapest correction mechanism there is, and the only thing standing
# between them and telling us is knowing where to say it.
ISSUE_URL = brand.ISSUES

# Two states in the markup, one shown at a time by CSS. Collapsed it is a
# chip small enough to sit in the corner without landing on a paragraph;
# hovered or tabbed to, it says what it is for. The flag is drawn rather
# than typed: a glyph here would be at the mercy of whichever font the
# reader's browser reaches for, and the ones that look right on a Mac are
# the ones that come out as an empty box elsewhere.
_FLAG_SVG = ('<svg class="obj-feedback-i" viewBox="0 0 16 16" '
             'aria-hidden="true"><path d="M4 14.5V2M4 2.6h7.4l-1.7 2.6 1.7 '
             '2.6H4" fill="none" stroke="currentColor" stroke-width="1.3" '
             'stroke-linejoin="round" stroke-linecap="round"/></svg>')

FEEDBACK_BOX = (
    f'<a class="obj-feedback" href="{ISSUE_URL}" target="_blank" rel="noopener"'
    ' title="Wrong or missing information? Open an issue on GitHub">'
    f'<span class="obj-feedback-chip">{_FLAG_SVG}Bug?</span>'
    '<span class="obj-feedback-full">'
    '<span class="obj-feedback-q">Wrong or missing information? Bug?</span>'
    '<span class="obj-feedback-a">Open an issue on GitHub</span></span></a>')


def object_html(r, canonical, text, data, place=None, base_url="",
                rungs=None, zenith="", prose="", static="", live_head="",
                live_sub="", live_what=""):
    """The browser page: the same chart and prose everything else gets, in
    the shared shell, with the object's own head."""
    # Lift the title out of the <pre> and set it as a real heading.
    #
    # Inside the block it is locked to the monospace body size, and a page
    # about one object should say which object at a glance. It also gives
    # these pages the <h1> they had none of, which is the element a search
    # engine reads as the subject of the page -- the <title> tag said Saturn
    # and the document itself never did.
    #
    # The terminal keeps it in the text: there is nothing there to make
    # bigger, and the coloured line is already the loudest thing on screen.
    lines = text.split("\n")
    heading, rest = "", text
    for i, l in enumerate(lines):
        if l.strip():
            # The event tail belongs to the terminal's heading, where there
            # is no room for anything but text. The browser gets it as the
            # picker beside the name instead, so it is not said twice on
            # one line. Split before the markup, not after: by then it is a
            # coloured span and the seam is gone.
            heading = ansi_to_html(l.split("  /  ")[0]).strip()
            rest = "\n".join(lines[i + 1:]).lstrip("\n")
            break
    # Two columns: what the object is, and what it is doing tonight.
    #
    # The split is not decoration. The left half is identical for every
    # visitor on every day, which is what a search engine can index and what
    # somebody arriving from a shared link needs before an altitude means
    # anything to them. The right half is computed from the reader's own
    # location and is redrawn every few minutes. Stacked, the durable facts
    # and the perishable ones looked alike.
    #
    # The chart sets the geometry: 110 monospace columns at 11px is about
    # 726px, so the sidebar takes what is left of the 1200px page cap. Below
    # 1000px they stack, static first, because on a phone you scroll and the
    # orientation should arrive before the numbers.
    title_html = f'<h1 class="obj-title">{heading}</h1>' if heading else ""
    picker = object_picker_html(data, canonical, place)
    # The same two links the eclipse page offers, for the same reason. /Saturn
    # sends every reader to their own sky; /Zurich/Saturn pins Zurich. Both
    # are right and they do opposite things, so the reader picks rather than
    # being handed whichever one the address bar happens to be showing.
    # The moment travels with them when one was actually asked for: a link to
    # the night of the opposition that quietly resolves to tonight is not the
    # page that was shared.
    share = object_share_html(r, canonical)
    if title_html and (picker or share):
        title_html = (f'<div class="obj-head-row">'
                      f'{title_html}{picker}{share}</div>')
    fallback_static, _, live = rest.partition(OBJECT_SLOT)
    if rungs:
        # The live half through the same ladder the place page uses: every
        # width in the markup, CSS picks one, the zenith inset floated over
        # it and the prose pinned below.
        #
        # The static half is markup rather than preformatted text, because a
        # <pre> can only scroll and this column has to wrap: Saturn's moon
        # count ran off the side of the sidebar with no way to read the rest
        # of it.
        intro_txt = strip_ansi(_first_para(static)).strip()
        src = object_sources(data)
        # The portrait gets its own <pre> rather than riding along in the
        # static text, because it is the one thing on this column that must
        # not reflow: .obj-art pins the line-height the drawing is built for
        # (see art.CELL), and text set at any other line-height would squash
        # every circle back into an ellipse.
        picture = data.get("art") or []
        art_html = (art_plate(picture, frame_cls="obj-art-frame",
                              plate_cls="obj-art", centre_ink=True)
                    if picture else "")
        static_html = (art_html
                       + (f'<p class="obj-lede">{html.escape(intro_txt)}</p>'
                          if intro_txt else "")
                       + infobox_html(data.get("infobox"))
                       + (f'<p class="obj-src">{html.escape(src)}</p>'
                          if src else ""))
        live_html = ((f'<p class="obj-lede obj-live-head">{live_head}</p>'
                      if live_head else "")
                     + (f'<p class="obj-subhead">{_link_best_date(live_sub, canonical, data)}</p>'
                        if live_sub.strip() else "")
                     # What kind of event the picker is pointing at, in one
                     # sentence. Under the timing line rather than beside
                     # the picker: it is an explanation, not a control, and
                     # it is the same for everybody who ever reads it.
                     + (f'<p class="obj-what">{live_what}</p>'
                        if live_what.strip() else "")
                     # prose still renders BELOW the chart. Only the summary
                     # line moved up into the heading; everything else --
                     # which constellation it is crossing, how far away, the
                     # ring angle, the best night this year -- reads after
                     # the picture, and passing "" here silently dropped all
                     # of it.
                     + chart_layout(rungs, zenith, prose))
        if data.get("evolution"):
            # The panels are already here, in the column, under the chart --
            # they arrive as part of the prose text. Two jobs left: make the
            # names beside the stars clickable, and hang the animation off
            # the bottom of them. It was a full-width section under both
            # columns for a while and that was worse: narrower drawing, and
            # it read as a separate page rather than the end of this one.
            live_html = style_evolution_title(
                link_star_labels(live_html, canonical), canonical)
            live_html += evolution_gif_html(canonical)
    elif live.strip():
        static_html = chart_pre(ansi_to_html(fallback_static))
        live_html = chart_pre(ansi_to_html(live))
    else:
        return title_html + chart_pre(ansi_to_html(rest)), None

    body = title_html + ('<div class="obj-cols">'
                         f'<aside class="obj-static">{static_html}</aside>'
                         f'<div class="obj-live">{live_html}</div>'
                         '</div>')
    head = (object_head(data, canonical, place, base_url) + OBJECT_CSS
            + eclipse_page.SHARE_CSS)
    # controls_html carries the drawer trigger as well as the explore row, so
    # passing "" here gave the object pages a page with no way to open the
    # drawer at all -- every other route builds it, and this one silently
    # did not. /help and /legend pass exactly this.
    return _object_page_template().format(
        title=html.escape(object_title(data)),
        head_extra=head,
        # The path of this very page, which is the object on its own or the
        # object seen from a named place. It used to show r.place.name, so
        # /Venus read "Zurich" -- the bar named the reader's location on a
        # page that was not about their location at all.
        header=header_html(f"{place}/{canonical}" if place else canonical),
        controls=controls_html(EXPLORE),
        wide_class=" w-wide", coming_up_card="",
        # The event picker is the eclipse page's picker, so it gets that
        # page's script: escape closes it, and so does a click anywhere
        # else. Only shipped where there is one to close.
        kbd_urls="{}", shortcuts_hint="",
        body=body + (eclipse_page.picker_script() if picker else "")
        + (eclipse_page.share_script() if share else ""))


def eclipse_head(f, key, place, base_url):
    """Title, description, canonical and the card tags for an eclipse page.

    The canonical drops the place, exactly as an object page's does: there
    are 40,803 cities and this is one eclipse, and /{city}/eclipse is the
    same event described from somewhere else, not a different page.
    """
    title = html.escape(eclipse_title(f))
    desc = html.escape(eclipse_description(f, place))
    url = canonical_url(f"/eclipse/{key}")
    # The canonical drops the place; the card does not. They answer different
    # questions: the canonical says which page this is, and there is one page
    # per eclipse, while the card is what somebody sees before they click,
    # and "Ibiza is in the path" is a reason to click where "Total solar
    # eclipse" is a link to an encyclopaedia.
    og = (f"{base_url}/{quote(place)}/eclipse/{key}/og.png" if place
          else f"{base_url}/eclipse/{key}/og.png")
    return "\n".join([
        f'<meta name="description" content="{desc}">',
        f'<link rel="canonical" href="{url}">',
        '<meta property="og:type" content="article">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{desc}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{og}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:site_name" content="skymap.sh">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{desc}">',
        f'<meta name="twitter:image" content="{og}">',
    ])


def eclipse_title(f):
    when = dt.datetime.fromisoformat(f["when_utc"].rstrip("Z"))
    return f"{f['name']}, {when.strftime('%d %B %Y').lstrip('0')}"


def eclipse_description(f, place=None):
    """One sentence, and it must survive being read on its own.

    Named place: that place's answer, because "90% covered" with nobody
    attached to it is worse than useless and a link about an eclipse is
    worth clicking for the local number.

    No place: nobody is named. The same rule the card follows, and for the
    same reason -- this text is fetched once by an unfurling crawler in a
    datacentre and then shown to everyone who sees the link, so a place on
    it is that machine's location presented as the reader's. The image was
    already careful about this and the sentence beside it was not, which is
    the worse half: a wrong picture is a wrong picture, a wrong sentence
    reads as a fact.
    """
    if place is None:
        entry = eclipse_page.by_key(f["eclipse"])
        return (f"{eclipse_page.headline_of(entry)}. "
                f"curl skymap.sh/eclipse")
    return eclipse_page.headline(f) + ". curl skymap.sh/eclipse"


def eclipse_html(r, f, key, entry, map_rows, legend, disc=None,
                 frames=None, labels=(), place=None, base_url=""):
    """The browser page. Same two columns and the same shell as an object
    page, because it is the same shape of thing: a durable half that every
    reader shares, and a half computed from where they are standing."""
    # The h1 names the page, not the reader's circumstances. What happens
    # from Zurich is a property of the right-hand column -- the half that is
    # computed per visitor -- so it heads that column instead, the same way
    # an object page puts its live summary above the chart rather than in
    # the title. The <title> and the card still lead with the local result,
    # because those are read without the page around them.
    disc_html = ansi_to_html("\n".join(disc)) if disc else ""
    cap = eclipse_page.disc_caption(f)
    frames_html = [ansi_to_html("\n".join(fr)) for fr in (frames or [])]
    also = eclipse_page.alongside(entry, r.tz)
    gif_href = (f"/{quote(place)}/eclipse/{key}/animate.gif" if place
                else f"/eclipse/{key}/animate.gif")
    body = ('<div class="ecl-head-row">'
            '<h1 class="obj-title"><span>Upcoming eclipses</span></h1>'
            + eclipse_page.picker_html(entry, r.when_utc, place)
            # Both links, and what each one does. The bare one is the
            # canonical: it sends each reader to their own city and unfurls
            # as the card that names nobody. The other one pins the place,
            # which is what you want when the point is "come and stand
            # here". Neither is the right default for everybody.
            # The second link uses the place this page resolved to, whether
            # it was asked for by name or worked out from the reader's IP.
            # Through a tunnel or anywhere the CDN sends no coordinates
            # there is no bounce to a city URL, so keying this off the route
            # parameter meant the modal offered one link and no way to pin
            # the place. Safe to name somebody here: this is behind a click,
            # by a person, and it is the meta tags and the card that must
            # never report a crawler's location as the reader's.
            + eclipse_page.share_html(
                canonical_url(f"/eclipse/{key}"),
                canonical_url(f"/{quote(r.place.name)}/eclipse/{key}"),
                r.place.name)
            + '</div>'
            + '<div class="obj-cols">'
            f'<aside class="obj-static">'
            f'{eclipse_page.sidebar_html(entry, r.when_utc, disc, disc_html, cap, also, f)}'
            f'</aside>'
            f'<div class="obj-live">'
            f'{eclipse_page.live_head_html(f)}'
            f'{eclipse_page.live_html(f, map_rows, legend, ansi_to_html, chart_pre, frames_html, labels, gif_href)}'
            f'</div></div>'
            + eclipse_page.frames_script(frames_html, labels)
            + eclipse_page.picker_script()
            + eclipse_page.share_script())
    head = (eclipse_head(f, key, place, base_url) + OBJECT_CSS
            + eclipse_page.ECLIPSE_CSS + eclipse_page.SHARE_CSS)
    return _object_page_template().format(
        title=html.escape(eclipse_title(f)),
        head_extra=head,
        header=header_html(f"{place}/eclipse" if place else "eclipse"),
        controls=controls_html(EXPLORE),
        wide_class=" w-wide", coming_up_card="",
        kbd_urls="{}", shortcuts_hint="", body=body)


def compose_eclipse_card(r, key, place=None):
    """What the social card for an eclipse needs: (kicker, headline, detail,
    art rows). None when there is no eclipse on that date.

    Composed here and drawn in card.py, the same split every other card
    uses. `place` of None means the card is the eclipse's own: what it is,
    when, and where it goes, naming nobody. That is not a shortcut -- a card
    is fetched once by a crawler in a datacentre and then shown to everyone,
    so a card that said "not visible from Ashburn, Virginia" would be
    telling the truth about a machine and a lie about the reader.
    """
    entry = eclipse_page.by_key(key)
    if entry is None:
        return None
    solar = eclipse_page.is_solar(entry)
    if place is None:
        rows = (eclipse_map.render(key) if solar and eclipse_map.has_map(key)
                else [] if solar else eclipse_map.night_map(key))
        return eclipse_page.card_lines(entry) + (rows,)
    f = eclipse_page.facts(entry, r.place, r.when_utc)
    here = (r.place.lat, r.place.lon)
    if solar:
        disc = eclipse_map.disc_art(key, *here)
        rows = (eclipse_map.render(key, mark=here)
                if eclipse_map.has_map(key) else [])
    else:
        disc = eclipse_map.moon_art(key)
        rows = eclipse_map.night_map(key, mark=here)
    return eclipse_page.card_lines(entry, f) + (eclipse_page.card_art(f, disc, rows),)


def compose_eclipse(r, key):
    """The eclipse page as text and data, for every output this serves."""
    entry = eclipse_page.by_key(key)
    if entry is None:
        return None
    f = eclipse_page.facts(entry, r.place, r.when_utc)
    here = (r.place.lat, r.place.lon)
    # Two kinds of eclipse, two of every picture, and the same slots. A
    # lunar eclipse has no path to draw, so its map answers the only
    # question that varies -- whether the Moon is up here -- and its
    # animation is the Moon's night rather than a disc being covered.
    #
    # Local labels either way: the clock over the animation is read next to
    # a timeline that is already local, and two time zones in one column is
    # a trap rather than a detail.
    if eclipse_page.is_solar(entry):
        rows = (eclipse_map.render(key, mark=here, color=r.color)
                if eclipse_map.has_map(key) else [])
        legend = eclipse_map.legend(color=r.color) if rows else ""
        # Empty when the Sun is down here, which is right: there is nothing
        # to draw a picture of, and the prose already says so.
        disc = eclipse_map.disc_art(key, *here, color=r.color)
        frames, labels = eclipse_map.disc_frames(key, *here, color=r.color,
                                                 tz=r.tz)
    else:
        rows = eclipse_map.night_map(key, mark=here, color=r.color)
        legend = eclipse_map.night_legend(color=r.color) if rows else ""
        disc = eclipse_map.moon_art(key, color=r.color)
        frames, labels = eclipse_map.arc_frames(key, *here, color=r.color,
                                                tz=r.tz)
    return (Result(eclipse_page.text(f, rows, legend, disc, r.color), f),
            entry, rows, legend, disc, frames, labels)


# ---------------------------------------------------------------- sky views
# The full 360 deg sweep's default shape -- narrower than render_linear's
# own 176-col default, which was wide enough to need horizontal scrolling
# in a normal terminal window and made a huge PNG/GIF export. 110/24 is the
# same size already measured close to X's 16:9 recommendation for the GIF
# export; reusing it here means the live terminal view, the static page,
# and both image exports are all the same shape and scale by default, not
# a patchwork of different sizes for different output modes. An explicit
# ?w= still overrides it. Only applies to the full sweep; a facing= window
# already has its own aspect-locked "true shape" formula and shouldn't be
# second-guessed by this.
DEFAULT_HORIZON_WIDTH = 110
HORIZON_COLS_PER_ROW = 110 / 24


def _effective_width(r):
    return r.width or DEFAULT_HORIZON_WIDTH


# The PNG and the Bluesky image are rasters, not terminals: nothing has to
# fit anyone's window, and the extra columns are what make the chart legible
# at a glance rather than a thin strip. 140 renders 1452x829, against 1152x668
# at the terminal default -- an explicit ?w= still wins.
PNG_WIDTH = 140


def _png_export_width(r):
    return r.width or PNG_WIDTH


# --- the width ladder ----------------------------------------------------------
# A browser gets every rung of this in one response and CSS picks exactly one.
# Nothing measures anything, nothing reloads, and the chart is right on first
# paint. It replaces an auto-fit script that measured the font with a hidden
# probe and then called location.replace() with a ?w= -- a second full page
# request per visit, which also meant every browser view was counted twice in
# /stats (_tally ran once per request, and there were two).
#
# Each rung is (minimum container width in ch, chart columns, zenith panel).
# `ch` is the width of a "0" in the container's own font, which is exactly
# what the probe used to compute by hand -- except the browser does it at
# layout time, for free, and re-does it on resize with no request at all.
# The chart font is a system monospace stack (no webfont, see PAGE's CSS), so
# `ch` is already correct on the very first paint rather than after a font
# load.
#
# Each breakpoint is the rung's OWN measured width, not a nominal
# columns-plus-panel figure. Those two are not the same number and assuming
# they were is what made the first version of this switch ~10ch late at
# every step:
#
#   - without the panel, the prose under the chart wraps at a fixed 76
#     characters (see _compose_sky's wrap_width), which is wider than a
#     60-column chart -- so the narrowest rung renders 85ch wide, not 60ch
#   - with the panel, the inset and its gap add 33ch, not the 43ch the
#     reserving arithmetic starts from
#
# So the numbers below are what each rung actually occupies. WidthLadder's
# test_each_rung_fits_its_own_breakpoint renders every one and checks it,
# which is what keeps this honest if the prose wrap or the inset changes.
#
# Nine rungs: each one is a real render server-side (~4 ms) and a real <pre>
# in the response (~10 KB raw, but only ~120 B gzipped, since the rungs are
# near-identical text). Measured against 4 rungs that buys 8/9 common
# desktop sizes fitting instead of 4/9, and mean wasted width across the
# range drops from 28.9ch to 11.3ch, for +4 ms LCP and +1.1 KB gzipped.
#
# The top rung is 220 columns because Request.__init__ clamps there, so
# 253ch is the widest thing this can render at all -- a maximised 2560
# screen (323ch) keeps ~70ch of empty space no matter what is done here.
# Raising that clamp is a separate change; add rungs above 220 here when it
# lands. Retune in this tuple and nowhere else -- the CSS and the server
# both read it.
# Each figure is the widest that rung rendered across 32 place/time
# combinations, plus 2ch of headroom. A rung's width is not fixed by its
# column count alone -- the prose and the labels beside the inset vary by a
# character or two with the sky being described, so a breakpoint set from a
# single sample is an off-by-one waiting to happen (measuring only Zurich in
# August put the 60+panel rung at 93ch; the same rung is 96ch over Tokyo in
# January).
# Retuned once the inset stopped taking width from the chart (it floats over
# the top-right corner now) and the prose moved out of the ladder entirely.
# Both used to set a rung's width: the inset added 33ch and the prose's fixed
# 76-character wrap put a floor under the narrow end. Neither does now, so a
# rung is its chart plus the y-axis gutter -- except at the narrow end, where
# the header line ("Zurich 47.38N 8.54E ... horizon panorama", ~89ch) is the
# floor instead, which is why there is no rung below 80 columns any more: 60
# and 80 render the same width, so 60 could never be the better fit.
#
# panel is True on every rung now. It no longer means "there is room beside
# the chart" -- it means the inset comes out as its own block for the page to
# position, which is wanted at every width.
#
# Measured over six place/date combinations through the real HTTP path, plus
# 2ch. Mostly columns plus the y-axis gutter, but not always: at 140 the
# widest sample runs 149ch, because a body label beside the chart can hang
# past its right edge. That overhang is what the old reserving arithmetic was
# really paying for, and it is still real -- it just no longer costs the
# inset's 33ch as well.
CHART_LADDER = ((None, 80, True),    # 94ch rendered at its widest
                (107, 100, True),
                (127, 120, True),
                (151, 140, True),
                (167, 160, True),
                # 1470px of laptop is ~184ch, which reached the 160 rung and
                # left 19ch of it empty; the next one up needed 199. 170 is
                # the widest that fits there -- 175 renders 184ch at its
                # worst and would overflow the window it was picked for.
                (181, 170, True),
                (199, 190, True),
                (227, 220, True),
                # The two widest exist because the chart is set at 8px: a ch
                # is 4.8px there, so a 1920px window is worth 400 of them and
                # stopping at 220 would have drawn a 1056px chart in it and
                # left the rest of the screen empty. The px figures in the
                # notes above are from when this was set at 12px -- the
                # breakpoints themselves are in ch and so are unaffected, but
                # the window sizes they used to correspond to are not.
                # 20-column steps from here rather than 40. The top of the
                # ladder used to go 220, 260, 300, so a window that reached
                # 266ch was served a 220-column chart and left the other 46
                # empty. That was invisible until the day page put a border
                # round the chart, at which point the gap read as a hole in
                # the box rather than as page margin. Two more rungs cost two
                # more renders per cold page (~4 ms each, cache hits after)
                # and halve the worst case.
                #
                # Every breakpoint here is its rung + 7, the same headroom the
                # measured rungs below 220 settled on -- a chart is selected
                # slightly before the window is exactly wide enough for it,
                # because `ch` is the width of a "0" and the drawing contains
                # characters that are not zeroes.
                (247, 240, True),
                (267, 260, True),
                (287, 280, True),
                (307, 300, True))


# Seams in the composed text, so the browser can lay the three pieces out
# itself instead of taking the server's one-column stack. Only ever emitted
# on the panel path, which is the ladder's and nothing else's -- r.panel is
# part of the cache key (server._cache_key), so a CLI reader cannot be
# served a marked-up entry. Control characters for the same reason MAP_SLOT
# uses one: they cannot collide with real content, and they survive
# ansi_to_html untouched.
# Control characters only, no readable word inside them: a marker spelling
# "zenith" made `"zenith" not in text` true of a chart that had no inset and
# false of the marker announcing one, which is exactly the kind of check
# callers and tests write.
ZENITH_SLOT = "\x00\x01\x00"
PROSE_SLOT = "\x00\x02\x00"
# Where an object page divides: everything above it is true wherever you are,
# everything below it is your sky tonight. A terminal drops the marker and
# reads straight down; a browser splits on it and sets the two halves side by
# side. Same mechanism the two slots above already use for the chart layout.
OBJECT_SLOT = "\x00\x03\x00"
# And where the live half's own prose ends and its chart begins. The prose
# reads above the chart, not under it: "it rises at 23:03 and sets at 11:36,
# highest at 05:19 when it reaches 46 degrees" is the sentence that tells you
# whether to bother looking, so it belongs before the picture rather than
# after it.
OBJPROSE_SLOT = "\x00\x04\x00"
# And between the timing line and what that line is: one sentence saying what
# kind of event the picker is pointing at. Its own seam rather than another
# line inside the timing block, because the browser sets it as a separate
# paragraph and a newline inside a <p> is just a space.
OBJWHAT_SLOT = "\x00\x05\x00"
# And where an animation frame's header ends and its chart begins. Browser
# frames only: a terminal and a GIF both want the header inside the drawing,
# which is the only header they have, while the page has a headline box the
# still line already lives in, and two headers disagreeing about the time is
# what this replaces.
HEAD_SLOT = "\x00\x06\x00"


def strip_slots(text):
    """Drop the layout seams, leaving the pieces stacked in the order they
    were composed. What a terminal gets if it asks for ?panel=1: the seams
    are places for a browser to break the text apart, and a reader who
    cannot be handed three positioned boxes just gets the chart, the inset
    and the prose one after another, which is what they got before."""
    return text.replace(ZENITH_SLOT + "\n", "").replace(PROSE_SLOT + "\n", "") \
               .replace(ZENITH_SLOT, "").replace(PROSE_SLOT, "") \
               .replace(HEAD_SLOT, "\n\n")


def split_chart_parts(text):
    """(chart, zenith, prose) out of a panel-mode render.

    The zenith inset is the same 21-column drawing at every width, and with
    the chart no longer wrapped around it the prose is identical across
    rungs too -- so both come out once and the ladder carries only the part
    that actually differs. Anything without the markers (every non-panel
    render) comes back as (text, "", ""), which is what the callers that
    predate this expect."""
    chart, zsep, rest = text.partition(ZENITH_SLOT)
    if zsep:
        zenith, _psep, prose = rest.partition(PROSE_SLOT)
    else:
        # The Sun's-path view has prose to lift out but no inset to lift --
        # it draws no zenith disc at all. Looking for the prose seam only
        # after finding a zenith seam left its marker in the text, where it
        # rendered as a missing-glyph box.
        zenith = ""
        chart, _psep, prose = text.partition(PROSE_SLOT)
    return chart.rstrip("\n"), zenith.strip("\n"), prose.strip("\n")


def chart_pre(inner):
    """The plain, single-width chart/text block every non-chart page uses.

    Carries both the id (what the rest of the JS and CSS has always keyed
    off) and the class the ladder uses, so skymapChartPre() finds the right
    element on a laddered chart page and an ordinary help/legend/stats page
    alike, without either of them special-casing the other."""
    return f'<pre id="chart-pre" class="chart-pre">{inner}</pre>'


def size_chart_head(body):
    """Set the chart's first line at reading size rather than the chart's.

    That line is a sentence about the sky -- the place, the time, the Moon,
    how dark it is, how many stars -- and not part of the drawing, so it has
    no business shrinking every time the drawing gets denser.

    Wrapped where it sits rather than lifted out of the <pre>, because it is
    not the same line at every rung: the summary drops parts to fit the width
    it is given, and there are nine widths on a page. The span is safe to put
    round it because ansi_to_html closes its colour spans at the end of the
    line -- it never straddles the newline.
    """
    lines = body.split("\n")
    for i, l in enumerate(lines):
        if l.strip():
            lines[i] = f'<span class="chart-head">{l}</span>'
            break
    return "\n".join(lines)


def chart_ladder(rungs, head=False):
    """`rungs` is [(cols, panel, html), ...] in CHART_LADDER order.

    No id on the individual rungs: there are several of them and an id has
    to be unique, which is the one thing a repeated <pre id="chart-pre">
    could not be. data-cols is read at click time by the animate button --
    the stream has to arrive at whatever width is actually on screen, and
    only CSS knows which rung that is.

    head is off by default because the object pages lift their first line out
    of the <pre> entirely, into the lede beside the object's name. Asking for
    it there would put a reading-size span round the top row of the drawing.
    """
    blocks = "".join(
        '<pre class="chart-pre" data-cols="%d"%s>%s</pre>'
        % (cols, ' data-panel="1"' if panel else "",
           size_chart_head(body) if head else body)
        for cols, panel, body in rungs)
    return f'<div id="chart-ladder">{blocks}</div>'


# A line's leading spaces sit after its colour code, not before it:
# "\x1b[38;5;250m  It is currently crossing Cancer." -- so the escapes have
# to be matched and put back, or the whole paragraph loses its colour.
_PROSE_INDENT = re.compile(r"(?m)^((?:\x1b\[[0-9;]*m)*)[ ]{1,2}")


def strip_prose_indent(text):
    """Take the chart's left margin out of the prose text.

    Every prose line is written with the same two-space margin the chart
    has, which is right in a terminal: the block is one drawing there and
    nothing reflows. In a browser it wraps, and a wrapped line gets no
    leading spaces of its own, so the second line of a paragraph sat two
    characters left of the first. Removing the spaces here and setting the
    same distance as padding on the box (see chart_ladder_css) gives every
    line, wrapped or not, one left edge.

    Terminal output does not come through here and is unchanged."""
    return _PROSE_INDENT.sub(r"\1", text)


def chart_layout(rungs, zenith, prose, head=False):
    """The ladder with the inset floated over it and the prose pinned below.

    zenith and prose come out of any one rung (see split_chart_parts) rather
    than per rung: the inset is the same 21-column drawing at every width,
    and with the chart no longer wrapped around it the prose wraps the same
    at every width too. Emitting them once keeps the ladder to the one thing
    that genuinely differs between rungs.

    Both are plain <pre> so they keep the chart's own font and spacing --
    the inset is a drawing made of characters and would fall apart in a
    proportional font."""
    inset = (f'<pre id="chart-zenith" aria-label="zenith inset">{zenith}</pre>'
             if zenith.strip() else "")
    below = (f'<pre id="chart-prose">{prose}</pre>' if prose.strip() else "")
    return (f'<div id="chart-stage">{chart_ladder(rungs, head)}'
            f'{inset}</div>{below}')


# One number for the chart, the inset and the prose under it. The ladder's
# breakpoints are in `ch`, which is the width of a "0" in this font -- so
# changing this changes how many rungs fit a given window without touching a
# single breakpoint, and the ladder picks a wider chart on its own.
# The drawing's own size. Smaller than it reads, on purpose: the ladder's
# breakpoints are in ch, so a smaller character means a given window is worth
# more of them and the chart that gets picked for it is a wider one. Ten
# rather than twelve takes a 1200px page from a 140-column chart to a 190,
# and a phone from 80 to 120 -- finer asterism lines, and less of the Milky
# Way lost under them (80% of the band survives the lines on a narrow chart,
# 92% on a wide one).
#
# Eight was tried and is worse, which is only obvious once CHART_WIDTH_MAX
# went up: on a 1920px screen both sizes reach the same 300-column ceiling,
# so eight buys no extra sky there and draws it in 1440px instead of 1800px.
# It wins only in the middle -- 260 columns against 220 on a 1440px laptop --
# and it pays for that everywhere by shrinking the labels, which are
# characters in this same grid and cannot be set larger without lifting them
# out of the <pre> and positioning them. Ten is the balance.
#
# Astronomically this is free. render_linear derives its rows from its
# columns as W * alt_rng / (2 * span), where the 2 is a character cell being
# twice as tall as it is wide, and the generic pre{} rule sets line-height as
# a bare 1.22 -- a multiplier, so the cell keeps its proportions at any size
# and the sky keeps its shape.
CHART_FONT_PX = 10
# The caption under it is sentences, and sentences do not want to be 10px.
CHART_PROSE_PX = 12
# The day page's summary line, once it is out of the drawing and in a box of
# its own. Set like "In Zürich" at the top of an eclipse page, which is the
# same job: the one line that says where and when, above everything that
# depends on it. At 12px in a box of its own it read as a caption for a
# picture that was no longer above it.
#
# The ladder's breakpoints are scaled by CHART_FONT_PX/this before they are
# written out (see _ladder_rules). They have to be. CHART_LADDER's thresholds
# are in ch at the chart's 10px, and ch resolves against each query
# container's own font -- so the same 1222px box counts as 203ch to the chart
# and 123ch to this line. Left unscaled it cleared one threshold instead of
# six and sat on rung 2 of 12 all the way up to a 4K display: no planets, no
# star count, and a padded gap where the planets should have been.
#
# The summary's own budget was already scaled for this (see the `room` line in
# _compose_sky), which is what made the bug survive so long -- the text in each
# rung was the right length, and only the choice of rung was wrong.
DAY_HEAD_PX = 16.5

# How long the page takes to open out into theatre mode and fold back, in ms.
# One number for every property that moves, which is what makes it read as a
# single movement rather than as several things happening at once. Long
# enough to follow, short enough that space still feels like a button.
ANIM_WIDE_MS = 320

# The one gap between anything and anything else on the day page: under the
# command bar, under the summary line, between the chart and the list, and
# across to the panel. It was 8 under the command bar and 14 everywhere
# else, which on a page made entirely of identical frames reads as a
# misalignment rather than as two intentional distances.
BOX_GAP = 14

# The shortcut bar's own height. It is position:fixed, so it is out of the
# flow and nothing below it reserves room automatically -- the page has to
# hand that room back as padding or the last box on it ends underneath the
# bar. 9px of padding top and bottom around a 15px line.
#
# One line's worth. On a window narrow enough to wrap the bar this
# under-reserves, which is the safe direction to be wrong in: the bar is
# translucent over the page background and a chart that ends a few pixels
# late reads as a tight margin rather than as a chart cut in half.
KBD_BAR_H = 33


def _ladder_rules(container, child, font_px):
    """Show one rung of CHART_LADDER at a time, inside `container`.

    Written once and called for both ladders on the page, so the chart and
    the summary line above it can never end up keyed to different
    breakpoints. Each container measures its own width, which is the whole
    point: they are different widths and should pick different rungs.

    Font size is pinned on the container and repeated on the children rather
    than left to inherit: `ch` in a container query resolves against the
    query container's own font, and the generic pre{} rule sets 11px
    explicitly, which beats inheritance from any ancestor.

    That same resolution is why the breakpoints are scaled. CHART_LADDER's
    thresholds are in ch at CHART_FONT_PX, and a ladder set larger fits fewer
    characters in the same box -- so the raw numbers would ask a 16.5px line
    to be 227 of its own wide characters before showing rung 8, which is a
    box no display has. Scaling by CHART_FONT_PX/font_px puts both ladders on
    the same physical widths, which is the point: they sit in boxes of the
    same pixel width and should pick the same rung. The chart's own call
    passes font_px=CHART_FONT_PX, so its rules come out unchanged.

    Every rung rule is :nth-child(k), including the first, which reads more
    naturally as :first-child and must not be. @container contributes nothing
    to specificity, so a (1,2,0) :first-child{display:block} outside the
    queries outranks a (1,1,0) rule inside them and the narrowest rung stays
    on screen at every width with the wider ones stacked underneath.
    Identical specificity throughout means source order decides, which is the
    mechanism: each breakpoint hides the rung below it and shows its own.
    """
    out = [f" {container}{{container-type:inline-size;font-size:{font_px}px}}",
           f" {container} {child}{{display:none;font-size:{font_px}px}}",
           f" {container} {child}:nth-child(1){{display:block}}"]
    scale = CHART_FONT_PX / font_px
    for i, (min_ch, _cols, _panel) in enumerate(CHART_LADDER):
        if min_ch is None:
            continue
        # Rounded, not truncated: these are thresholds either side of which a
        # different amount of sky is on the page, and a rung that appears one
        # pixel early is a better failure than one that never appears.
        #
        # An unscaled ladder writes the number it was given -- "107ch", not
        # "107.0ch" -- so the chart's rules come out byte-identical to what
        # they were before this scaling existed.
        at = round(min_ch * scale, 1)
        at = int(at) if at == int(at) else at
        out.append(f" @container (min-width:{at}ch){{"
                   f"{container} {child}:nth-child({i}){{display:none}}"
                   f"{container} {child}:nth-child({i + 1}){{display:block}}}}")
    return out


def chart_ladder_css():
    """Container queries, generated from CHART_LADDER so the breakpoints
    cannot drift from the widths actually rendered into the page.

    container-type:inline-size makes #chart-ladder a query container whose
    width comes from its parent rather than its contents -- which matters,
    because its contents are several charts of different widths and one of
    them is always wider than the window.

    Font size is pinned here rather than inherited: `ch` in a container
    query resolves against the *query container's* font, so the container
    has to be the same size as the <pre> it is picking, or every breakpoint
    lands in the wrong place. 13px matches the .kbd-hint ~ rule below.

    Every rung rule is written as :nth-child(k) -- including the first,
    which reads more naturally as :first-child and must not be. @container
    contributes nothing to specificity, so a (1,2,0) :first-child{display:
    block} outside the queries outranks a (1,1,0) .chart-pre{display:none}
    inside them, and the narrow rung stays on screen at every width with the
    wider one stacked underneath it. Identical specificity throughout means
    source order decides, which is the whole mechanism: each breakpoint
    hides the rung below it and shows its own, in ascending order.

    A browser too old for container queries applies none of the @container
    blocks and keeps the first rung, so it gets the narrowest chart rather
    than a broken page."""
    lines = _ladder_rules("#chart-ladder", ".chart-pre", CHART_FONT_PX)
    # The same mechanism a second time, for the summary line the day page
    # lifts out of the drawing (lift_chart_head). It is one line per rung
    # because the summary drops pieces to fit, and its box is the full page
    # rather than the chart column, so it measures itself and usually lands
    # a rung or two wider than the chart below it.
    lines += _ladder_rules("#day-head-ladder", ".dh", DAY_HEAD_PX)
    lines += [
        # The stage is the positioning context for the inset. Not the ladder
        # itself: that is the query container, and giving a query container
        # a positioned child it also has to size is asking for a loop.
        # The flash, softened rather than hidden.
        #
        # It was hidden once -- the ladder held at visibility:hidden until
        # the fit had run -- and that cost a chart: anything that stopped
        # the fit from running left the page with no drawing on it at all.
        # A mechanism for a cosmetic problem must not be able to fail
        # closed, and that one could.
        #
        # This one cannot. The fit still lands a frame or two after first
        # paint; all this does is make the size change take 140ms instead of
        # happening between two frames, so it reads as the chart settling
        # rather than as the sky jumping. If the transition never applies,
        # the chart is still there, at the right size, a frame sooner.
        #
        # Theatre mode is unaffected: skymapFlip sets transition:none on the
        # element before it changes the font and puts its own transform
        # transition on afterwards, so the FLIP still animates on the
        # compositor rather than through this.
        " #chart-ladder .chart-pre{transition:font-size 140ms ease}",
        " @media (prefers-reduced-motion:reduce){"
        "#chart-ladder .chart-pre{transition:none}}",
        " #chart-stage{position:relative}",
        # Never width:max-content over #chart-ladder, whatever is pinned.
        #
        # It was, gated on the pinned states, on the reasoning that a pinned
        # rung leaves the ladder nothing to choose and so no loop can form.
        # The loop was never the problem. container-type:inline-size does not
        # only stop the ladder sizing from its contents -- it *contains* the
        # inline axis, so the ladder contributes nothing to any parent asking
        # for an intrinsic width. max-content therefore resolved to 0px, and
        # theatre mode on the day page grew a container 614px tall and 0px
        # wide with a 1281px chart inside it, invisible.
        #
        # It is the same collapse the fit used to cause, from the same two
        # rules meeting; fit-on came off this line and anim-wide was left on
        # it. Nothing needs it: the day page has no zenith inset to pin to a
        # right edge, and the night page never enters theatre mode at all --
        # its chart already fills the width, so skymapAnimZoom's k lands
        # under 1.05 and it returns before adding the class.
        " html.anim-wide #chart-stage{max-width:100%}",
        # Theatre mode, driven by one class on the root. Nothing is inserted
        # into or removed from the page to enter or leave it, so a stream
        # that dies halfway cannot strand an overlay on screen.
        #
        # Everything animates over the same 320ms, which is what makes it
        # read as one movement -- the chart growing into room the other
        # boxes are giving up -- rather than as several things happening at
        # once.
        # The headline stays up through an animation.
        #
        # It used to fold away (html.anim-on #day-head), because the frame
        # brings a header of its own and the box beside it was frozen at the
        # moment the page was built -- two headers disagreeing about the
        # time. But the headline is where and when you are, and an animation
        # is exactly when "when" is changing: taking it off screen at that
        # moment removes the one line the movement is about.
        #
        # It is not wired to the frames yet, so it still reads the page's own
        # moment while the chart runs. That is the next piece of work, not a
        # reason to hide it.
        # The rung the animation is writing into, pinned on whatever the
        # ladder would pick for the width it now has. Placed after the
        # @container rules on purpose: same specificity, so source order
        # decides, and these have to win.
        " html.fit-on #chart-ladder .chart-pre{display:none}",
        " html.fit-on #chart-ladder .fit-rung{display:block}",
        " html.anim-wide #chart-ladder .chart-pre{display:none}",
        " html.anim-wide #chart-ladder .anim-rung{display:block}",
        " @media (prefers-reduced-motion:reduce){"
        "#chart-ladder .chart-pre{transition:none}}",
        # Top right, over the panorama's highest rows. That corner holds
        # 55-70 degrees of altitude, the emptiest band of the chart on most
        # nights -- and when it isn't, "i" takes the inset away.
        f" #chart-zenith{{position:absolute;top:0;right:0;"
        f"font-size:{CHART_FONT_PX}px;margin:0;pointer-events:none;"
        # Sits on the sky, so it needs its own floor under it or the stars
        # it covers read as part of the drawing.
        "background:rgba(4,6,10,.82);padding:2px 6px;border-radius:4px}",
        # pointer-events back on for the names under the disc. The box itself
        # keeps none of it -- it floats over the top rows of the panorama and
        # would otherwise swallow clicks meant for the labels underneath --
        # but the labels in it are links, and a link the mouse cannot reach
        # is not one. This is why they looked unlinked: the markup was right
        # the whole time and the cursor never changed over it.
        " #chart-zenith a{pointer-events:auto}",
        " html.no-inset #chart-zenith{display:none}",
        # The prose keeps the chart's font but not its width: pinned above
        # the shortcut bar, where it stays put while the chart above it
        # changes rung, place or time.
        # The prose keeps the chart's font on a chart page, where it reads as
        # a caption to the drawing. An object page sets it in the page's own
        # face instead: there it is sentences among other sentences, sitting
        # under a lede and a fact list that are already set that way, and a
        # second typeface for one block read as a different document.
        f" #chart-prose{{font-size:{CHART_PROSE_PX}px;margin:6px 0 0}}",
        # The chart's first line, at reading size like the prose under it
        # rather than at the drawing's. pre-wrap because it is now wider than
        # the chart it sits above: 120 characters at 12px is 864px against a
        # 720px chart on a small laptop, and a line that cannot wrap would
        # take the whole <pre> into a horizontal scroll.
        f" #chart-ladder .chart-head{{font-size:{CHART_PROSE_PX}px;"
        f"white-space:pre-wrap}}",
        # The indent is padding, not two spaces of text (see
        # strip_prose_indent). A wrapped line has no leading spaces of its
        # own, so with the margin inside the text the first line of a
        # paragraph started at column 2 and every line under it restarted at
        # column 0. As padding it applies to the whole box, so all lines
        # share one left edge. 2ch is the width of two characters in this
        # element's own font, which is exactly what the spaces were.
        " .obj-live #chart-prose{font-size:13.5px;line-height:1.5;"
        "color:#adb6c4;margin:10px 0 0;white-space:pre-wrap;padding-left:2ch}",
    ]
    return "\n".join(lines)


def _horizon_height(r):
    return round(_effective_width(r) / HORIZON_COLS_PER_ROW)



def _day_height(r):
    """Rows for the Sun's arc. The same as the night chart's, now.

    It used to be 72% of them in a browser, because the arc shared its row
    with a panel of tonight and a list of events and the room was worth more
    than the resolution. Both of those live in the drawer now and the chart
    has the page to itself, so the reason is gone -- and a day chart drawn
    shorter than the night one is the two views disagreeing about their own
    axis again, which is the thing this layout exists to stop.
    """
    return _horizon_height(r)


def _png_export_height(r):
    """Rows to match _png_export_width's columns. Height follows width here
    or the wider export comes out as a letterbox -- the aspect is the whole
    reason the two are computed from one number."""
    return round(_png_export_width(r) / HORIZON_COLS_PER_ROW)


def _sun_path_mode(r):
    """'the Sun's path today' only when when_local's date is the real
    current date at that place -- an explicit ?t= on another day isn't
    "today" just because it's daytime there."""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    now_local = now + dt.timedelta(hours=r.place.offset(now))
    return "the Sun's path today" if r.when_local.date() == now_local.date() \
        else "the Sun's path"


# Was 1.6, which held the stars back far longer than a real sky does: with
# the Sun 11 degrees down -- late nautical twilight, when Vega, Arcturus,
# Altair and Deneb are all easy naked-eye -- it allowed magnitude -0.91,
# and exactly one star in the catalogue is that bright. Charts drawn in the
# hour after dusk came out empty but for a planet or two, which is not what
# anyone standing outside at that hour can see. Arcturus needed the Sun 12.4
# degrees down to appear; at 0.7 it arrives at 7.7, which is about when it
# really does. Below 1.0 the curve bends the other way -- stars arrive
# earlier in twilight rather than later -- and the two endpoints are
# unchanged, so nothing shows while the Sun is up and full dark still lands
# on magnitude 4.
FADE_BIAS = 0.7


def _fade_mag_limit(sun_alt):
    """Shared by compose_frame() (animation) and the static views, so a
    snapshot at a given moment always shows exactly what an animation
    frame at that same moment would -- no hard cut at sunset/sunrise, just
    this one continuous function of the Sun's altitude. Biased, not
    linear: stars arrive through the brighter part of twilight rather than
    all at once near full dark -- and symmetrically at dawn, since this is
    a pure function of altitude with no notion of which direction time
    runs."""
    if sun_alt >= 0:
        return -5.0
    if sun_alt <= -18:
        return 4.0
    t = ((0 - sun_alt) / 18.0) ** FADE_BIAS
    return -5.0 + t * 9.0


# What the fade is heading for: the limit at the bottom of its own ramp.
# Derived rather than written as 4.0 a second time, so the unlit field and
# the lit one can never be drawn against different tables.
FULL_DARK_MAG = _fade_mag_limit(-18)


def _dim_limit(sun_alt):
    """The magnitude to sketch the sky in, unlit, or None for no sketch.

    Only between sunset and full dark. Above the horizon the sky is genuinely
    empty and drawing a star field into daylight would be a lie; below -18
    the fade has already reached this same number, so every star is lit and
    the unlit pass has nothing left to add. It is the two hours in between
    that this exists for -- the stretch where the chart used to be a grid
    with a horizon on it and nothing else."""
    return FULL_DARK_MAG if -18 < sun_alt < 0 else None


# How close the Moon has to be to the Sun, in the sky, before it's shown
# regardless of phase brightness -- a new moon reflects ~0% of the Sun's
# light, so the normal dark_enough() check (built for reflected moonlight)
# never fires near an eclipse. This is a separate, real reason to be
# visible: it's right there next to (or over) the Sun. A few degrees of
# margin around exact conjunction, generous enough to cover the hour or
# so either side of an eclipse, without lighting up for a merely-ordinary
# new moon that isn't anywhere near the Sun's apparent path.
ECLIPSE_MATE_DEG = 8.0


def _near_sun(jd):
    su, mo = sun(jd), moon(jd)
    return angsep(su["dec"], su["ra"] * 15, mo["dec"], mo["ra"] * 15) <= ECLIPSE_MATE_DEG


def _fade_visible_bodies(sun_alt, jd):
    visible = {n for n in ("Mercury", "Venus", "Mars", "Jupiter",
                           "Saturn", "Uranus", "Neptune")
              if dark_enough(sun_alt, planet(n, jd)["mag"])}
    if dark_enough(sun_alt, -12.7) or _near_sun(jd):    # Moon's rough peak
        visible.add("Moon")                             # brightness, or an
    return visible                                       # eclipse mate


# What the Moon/planets/brightest-stars lines say, on one line above the
# chart instead of three below it. The header row is nearly all empty space
# on a wide screen, and these are the three lines someone reads before
# looking up -- so they go where the eye already is, and the page keeps
# three rows it was spending on them.
#
# Browser only (r.panel): curl's layout is a separate question and a
# separate review. Built from st rather than by matching sky_read's
# sentences, so a reworded sentence there cannot silently empty this.
SUMMARY_DROP = ("Moon ", "Planets up:", "No naked-eye planets",
                "Brightest stars:",
                # The twilight label is the Sun's altitude said in words,
                # and it rides on the top line now too.
                "daylight, the sun is up.", "civil twilight.",
                "nautical twilight.", "astronomical twilight.", "full dark.")


def _moved_to_summary(line):
    """Lines the top line now carries. The star count is matched on its tail
    because it begins with the number, which is the part that varies."""
    s = line.strip()
    return s.startswith(SUMMARY_DROP) or s.endswith("stars above the horizon.")


# visibility()'s reasons are written as prose for the terminal, where they
# sit in a sentence of their own. On the browser's one-line header they are
# most of the line -- "too low, under 8°, so trees and buildings will be in
# the way" is 59 characters explaining a number that is right there. Missing
# keys fall through unchanged; a test checks each one still exists in sky.py,
# so rewording there fails loudly rather than quietly restoring the long
# version.
SHORT_WHY = {
    "too low, under 8°, so trees and buildings will be in the way": "too low",
    "the sky is still too bright": "sky too bright",
    "the sky is not quite dark enough for it": "not quite dark",
}


def _find_summary(tgt, st, lat, width):
    """The find view's four lines as one: where it is, how bright, and what
    bright thing it sits next to.

    The fist instruction goes. "A closed fist at arm's length is about 10°"
    is worth reading once and is printed on every find chart forever; the
    altitude in degrees says the same thing to anyone who has read it, and
    help is where the explanation belongs. Trimmed like the sky summary --
    the marker first, since it is the one part the chart itself shows."""
    bits = [f"{tgt['name']} · {tgt['alt']:.0f}° up · "
            f"{compass(tgt['az'])} {tgt['az']:.0f}°"]
    if tgt.get("kind") == "moon":
        bits.append(f"{moon_glyph(tgt['age'], lat)} {tgt['illum'] * 100:.0f}%")
    elif tgt.get("mag") is not None and tgt["kind"] != "asterism":
        bits.append(f"mag {tgt['mag']:.1f}")
    mark = find_marker(tgt, st["visible"])
    if mark:
        nm, d, vert, side = mark
        rel = " and ".join(x for x in (vert if vert != "level" else "level with",
                                       side) if x)
        bits.append(f"{d:.0f}° from {nm}, {rel}")
    while len(bits) > 1 and len(" · ".join(bits)) > width:
        bits.pop()
    return " · ".join(bits)


def _head_when(r, when_local=None):
    """The moment, with the year only when it isn't this one. A chart of
    tonight does not need to say 2026; a ?t= link two years out does, and
    dropping it there would quietly read as today.

    when_local overrides r's own: a find view can be drawn for the next time
    the thing is up rather than for the moment asked about."""
    w = when_local or r.when_local
    now_year = dt.datetime.now(dt.timezone.utc).year
    return f"{w:{'%d %b %H:%M' if w.year == now_year else '%d %b %Y %H:%M'}}"


# How wide each block of the night summary is held open, in characters.
# Sized for the realistic worst case rather than for what is there now:
# "below the horizon" is the longest thing the Moon block says, four
# planets with heights and compass points is about sixty characters, and
# "nautical twilight" is the longest twilight label. A block that fits its
# own content exactly is a block that moves the moment the content changes.
#
# The line is three characters per position longer since the heights gained
# their "up" (see where_up), which is enough that the padded version no
# longer fits the widest rung on a twilight night -- the Sun's own block is
# there as well as everything else. render() falls back to unpadded when
# that happens, so those nights get a line that shifts as its numbers do.
# A full-dark night, which is most of them, still pads.
# The planets block is deliberately 0, meaning "do not pad". Padding is
# here to absorb a digit changing -- the Moon climbing from 9 to 10 degrees
# used to shunt the whole line sideways -- and this block does not change by
# a digit, it changes by a whole planet setting. Held open at its
# four-planet width it left a 47-character hole on an evening with one
# planet up, which is a worse fault than the shift it was preventing.
SUMMARY_W = {"sun": 15, "moon": 17, "planets": 0, "dark": 17, "note": 10,
             "stars": 9}


def where_up(alt, az):
    """`55° up SSW` -- how high, then which way, with a word between them
    saying which is which.

    It used to be `55°SSW`, and that reads as a bearing: azimuth is the
    quantity conventionally measured in degrees from north, so a degree sign
    against a compass point says "bearing 55, i.e. SSW" -- which is not only
    the wrong fact but an impossible one, 55 being ENE. Every observing
    source writes it the long way for exactly this reason ("an altitude of
    10 degrees above your eastern horizon"), and this app's own prose
    already does: "55 degrees up in the SSW".

    Three characters per block, spent so that one shape on the page means
    one thing: a degree is a height, letters are a direction."""
    return f"{alt:.0f}\N{DEGREE SIGN} up {compass(az)}"

# Where the day line hands over to the night line, in Sun altitude. Civil
# twilight at both ends: the Sun arrives on the line at civil dawn and
# leaves it at civil dusk, which is also the moment the page calls "stars".
CIVIL_ALT = -6.0

# And where the sky is finally dark. The Bortle estimate and the star count
# both wait for it: the estimate describes a fully dark sky, and a star
# count taken through twilight is a number in freefall -- 114 at
# astronomical dawn, 40 twenty minutes later. Neither is worth the room
# while the answer is still changing.
ASTRO_ALT = -18.0

# How wide each of the Sun's day blocks is held open when the line is
# padded, same reasoning as SUMMARY_W: a block sized to its own content is
# a block that moves the moment the content changes.
DAY_BLOCK_W = {"rise": 13, "high": 10, "set": 13, "stars": 12, "dark": 15,
               "golden": 18, "shadow": 17}


def _day0(r):
    """Local midnight of the day this request is about, as a UTC instant --
    what sun_events wants. Three composers were each rebuilding it inline
    from when_local and the offset."""
    off = r.place.offset(r.when_utc)
    return (r.when_local.replace(hour=0, minute=0, second=0, microsecond=0)
            - dt.timedelta(hours=off))


# One day's Sun events, remembered. sun_events walks the day in ten-minute
# steps -- 145 positions, about a millisecond -- and the answer is the same
# for every moment in that day from that place. An animation asks for it
# ninety-six times over one day and one place, which is ninety-five walks
# whose answer was already known.
#
# Small and bounded: an animation touches one day, a page one or two. Old
# entries are dropped wholesale rather than by age, which is all a cache
# this shape needs -- the cost of a miss is a millisecond.
_SUN_EVENTS_MEMO = {}
_SUN_EVENTS_MAX = 256


def sun_events_cached(day0, lat, lon):
    """sun_events, memoised on the day and the place. Rounded to four
    decimals, about ten metres -- two requests that far apart cannot differ
    in a time printed to the minute."""
    key = (day0, round(lat, 4), round(lon, 4))
    got = _SUN_EVENTS_MEMO.get(key)
    if got is None:
        if len(_SUN_EVENTS_MEMO) >= _SUN_EVENTS_MAX:
            _SUN_EVENTS_MEMO.clear()
        got = _SUN_EVENTS_MEMO[key] = sun_events(day0, lat, lon)
    return got


def _golden_block(bands, off, when_utc):
    """`golden 19:48`, or `golden → 20:50` while you are standing in one.
    The next golden window, not both of them -- the morning one is over by
    the time anybody reads an afternoon line, and this block exists to
    answer "when should I be outside", which has one answer.

    The arrow rather than the word "until": the line already reads arrows as
    the Sun's own marks, and it is one cell against five.

    One of the three facts that used to live only in the chart's own header
    (with the blue hour and the shadow), where a browser had to read the
    drawing to find them and an animation dropped them entirely."""
    for key in ("golden_am", "golden_pm"):
        b = bands.get(key)
        if not b:
            continue
        if when_utc < b["start"]:
            return f"golden {_hm(b['start'], off)}"
        if when_utc <= b["end"]:
            return f"golden \N{RIGHTWARDS ARROW} {_hm(b['end'], off)}"
    return ""


def _shadow_block(sun_alt, sun_az):
    """`shadows 0.7x NNE` -- how long yours is and which way it falls.

    The one block on the day line that is different in every frame of an
    animation rather than a time that sits still all afternoon, which is
    most of why it is worth its room.

    Capped: cot(h) is 9.5x at the top of the golden band and 57x half a
    degree above the horizon, and somewhere in there the slope of the ground
    you are standing on matters more than the arithmetic does."""
    ratio = sky.shadow_ratio(sun_alt)
    if ratio is None:
        return ""
    size = f">{SHADOW_CAP:.0f}x" if ratio > SHADOW_CAP else f"{ratio:.1f}x"
    return f"shadows {size} {compass((sun_az + 180) % 360)}"


def _head_day_blocks(ev, p, off, when_utc, sun_alt, sun_az=None, bands=None):
    """The Sun's own day, staged: (rank, text, width) for whichever of
    sunrise, high point, sunset, first stars and darkest is worth carrying
    at this moment.

    The rule is one line long: a block is on the headline while the thing it
    names is still ahead, and goes once it has passed. That is what lets the
    line cross sunset without being replaced -- at every boundary through
    the day one or two blocks change and the rest hold their place, where
    before the whole line was swapped at the horizon.

    Reading down a day: the deep night carries none of it; from
    astronomical dawn the sunrise appears alone; from civil dawn the rest of
    the day arrives at once and then empties out block by block as each
    thing happens -- the sunrise at sunrise, the high point at the high
    point, the sunset at sunset, the first stars when they come out. After
    civil dusk the night line owns the line again.

    Nothing here is bounded by "today". Every block is guarded on its own
    event being present, so a polar day (no sunrise, no sunset) and a polar
    night (no transit above the horizon, no dusk) each come out with only
    the blocks that are true there rather than with "--:--"."""
    rise, transit, sset = ev.get("sunrise"), ev.get("transit"), ev.get("sunset")
    first = ev.get("dusk_civil") or ev.get("dusk_nautical")
    dark = ev.get("dusk_astro")
    dawn = ev.get("dawn_astro")

    def _mark(ch, t, key, sun=False):
        """`↓20:30 WNW`, or `☀↓20:30 WNW` where the arrow alone could be
        read as belonging to whatever sits beside it. A bare down arrow next
        to a list of planets is a mark with no subject; the glyph names the
        subject in one cell, and dim_directions sets it small and grey so it
        labels the block rather than competing with the time."""
        az = sky.sun_altaz(t, p.lat, p.lon)[1]
        glyph = "\N{BLACK SUN WITH RAYS}" if sun else ""
        return (2 if ch != "^" else 3,
                f"{glyph}{ch}{_hm(t, off)} {compass(az)}",
                DAY_BLOCK_W[key] + len(glyph))

    # Which half of the day this is. The transit is the turn, not the
    # horizon: everything before it is still on its way up even when the Sun
    # is under the horizon, which is exactly the stage that wants a sunrise
    # on the line.
    rising = transit is None or when_utc < transit

    # The two ends of the day the line is awake for. Before astronomical
    # dawn it says nothing about the Sun: the night is simply the night, and
    # a sunrise five hours off is not what somebody standing under a dark
    # sky is reading for.
    if rising:
        if dawn is not None and when_utc < dawn:
            return []
    elif sun_alt <= CIVIL_ALT:
        # The evening end keeps one block past civil dusk. From there to
        # astronomical dusk the sky is emptying of light and filling with
        # stars, but the count is still four or five and falling short of
        # what is actually coming -- so the line says when they will all be
        # out, and hands over to the count at full dark. Without it there
        # was an hour and a half with neither: no time to wait for and no
        # number to read.
        if dark and when_utc < dark:
            return [(1, f"darkest {_hm(dark, off)}", DAY_BLOCK_W["dark"])]
        return []

    out = []
    # Only while it is still ahead, and only once the sky is light enough
    # for it to be worth planning around.
    if rise and when_utc < rise:
        out.append(_mark("\N{UPWARDS ARROW}", rise, "rise"))
    # Between astronomical and civil dawn the sunrise is the whole story.
    # The rest of the day is a day that has not started.
    if rising and sun_alt <= CIVIL_ALT:
        return out
    if transit and when_utc < transit:
        out.append(_mark("^", transit, "high"))
    # Where the light is and what it is doing to the ground, which the
    # chart's own header used to be the only place to find. Both are about
    # the Sun being up, so neither outlives it.
    if sun_az is not None and sun_alt > 0:
        shadow = _shadow_block(sun_alt, sun_az)
        if shadow:
            out.append((4, shadow, DAY_BLOCK_W["shadow"]))
    if bands:
        golden = _golden_block(bands, off, when_utc)
        if golden:
            out.append((3, golden, DAY_BLOCK_W["golden"]))
    if ev.get("polar_day"):
        out.append((1, "the Sun does not set today", 0))
        return out
    if sset and when_utc < sset:
        out.append(_mark("\N{DOWNWARDS ARROW}", sset, "set", sun=True))
    # "darkest", not "dark": the time is astronomical dusk, a fact about
    # where the Sun is rather than about whether you can see anything. In
    # central London the sky never gets astronomically dark at all, because
    # the light dome sets a floor the Sun going further down does nothing
    # about. "Darkest" is true at both ends without knowing the Bortle.
    if not first:
        out.append((1, "never fully dark", DAY_BLOCK_W["dark"]))
        return out
    if when_utc < first:
        out.append((1, f"stars {_hm(first, off)}", DAY_BLOCK_W["stars"]))
    out.append((1, f"darkest {_hm(dark, off)}" if dark else "no full dark",
                DAY_BLOCK_W["dark"]))
    return out


def _sun_head_block(alt, az):
    """`☀ 55° up SSW` above the horizon, `☀ 3° down WNW` under it.

    The Moon's block says only "down" -- the Moon being under the horizon is
    the whole fact and its depth changes nothing -- but the Sun's depth is
    exactly what the reader is waiting on between sunset and full dark, so
    it gets a number.

    "down", the same word the Moon uses, rather than "below" or a minus
    sign. Two words for one idea is one too many on a line this tight, and
    `-3° up` is a contradiction the eye has to unpick before it can read a
    sign that is easy to lose in a row of numbers. Up or down, then how far,
    then which way.

    Rounding is applied before the direction is chosen, so a Sun at -0.4
    comes out as `0° up` rather than `-0° down`."""
    deg = round(alt)
    if deg >= 0:
        return f"\N{BLACK SUN WITH RAYS} {where_up(deg, az)}"
    return (f"\N{BLACK SUN WITH RAYS} {-deg}\N{DEGREE SIGN} down "
            f"{compass(az)}")


def _sky_summary(st, lat, width, n_stars=0, note="", pad=False,
                 day_blocks=()):
    """Trimmed to `width`, brightest-last. It sits above the chart, so a
    summary longer than the chart is one that decides how wide the page is
    -- which is exactly the job the prose used to do from below, and the
    reason the narrow rungs were 86ch for a 60-column chart. The Moon comes
    first and survives every trim; the star list is the first thing to go,
    then the planets, since both are in full in the chart itself.

    day_blocks are whatever _head_day_blocks says the Sun's own day is still
    owed at this moment -- a sunrise before dawn, tonight's two times after
    sunset. They sit after the planets, so the line reads as what is up,
    then what is coming.

    How much of the night tail is carried is decided here, from the Sun's
    own altitude, because every block in it is an answer about a dark sky
    and the sky is only dark for part of the night."""
    mo, su = st["moon"], st["sun"]
    # "down", not "below the horizon". Seventeen characters spent on the one
    # block that has nothing to report, on a line where everything else is
    # competing for room -- and it pairs with the "up SSW" the rest of the
    # line uses, so the two read as one system rather than as a phrase and
    # a sentence.
    # Space after the glyph, always: the phase mark and the number are two
    # facts, and run together they read as one broken word.
    where = where_up(mo["alt"], mo["az"]) if mo["alt"] > 0 else "down"
    pl = sorted((b for b in st["up"]
                 if b["name"] not in ("Sun", "Moon") and b["mag"] < 6.0),
                key=lambda b: b["mag"])
    alt = su["alt"]
    dark = ("daylight" if alt > 0 else "civil twilight" if alt > -6 else
            "nautical twilight" if alt > -12 else
            "astro twilight" if alt > ASTRO_ALT else "full dark")
    # The two thresholds the whole line is staged around. Above CIVIL_ALT
    # the Sun is what the sky is doing and the line is about the Sun; below
    # ASTRO_ALT the sky is finally dark and the answers about darkness are
    # worth printing. Between them it is neither, and says so.
    civil = alt > CIVIL_ALT
    full_dark = alt <= ASTRO_ALT
    # (drop-order, text). Rendered in list order, but trimmed worst-first,
    # so a busy planet night loses the least useful block rather than
    # whichever happens to sit at the end. The Moon never goes: it decides
    # how much of the rest is worth looking for.
    #
    # The Sun comes first, and it is here at all because the line used to
    # delete it the instant it set. A day headline carried the Sun's
    # position and a night headline carried no Sun at all, so at sunset
    # every block on the line was replaced at once -- one frame of an
    # animation, at the exact moment somebody is watching. It holds its
    # place through civil twilight at either end, and hands over at
    # CIVIL_ALT, the same threshold the page already calls "stars".
    parts = []
    if civil:
        parts.append((0, _sun_head_block(alt, su["az"]), SUMMARY_W["sun"]))
    # While the Sun is on the line the Moon and the planets only appear if
    # they are actually there. On a dark night "down" and "no planets" are
    # worth saying -- they answer what somebody came outside to ask -- but
    # beside a Sun that is the whole reason the sky looks like that, they
    # are two blocks reporting nothing.
    if mo["alt"] > 0 or not civil:
        parts.append((0, f"{moon_glyph(mo['age'], lat)} "
                         f"{mo['illum'] * 100:.0f}% {where}", SUMMARY_W["moon"]))
    if pl or not civil:
        parts.append((2, ", ".join(f"{p['name']} {where_up(p['alt'], p['az'])}"
                                   for p in pl) if pl else "no planets",
                      SUMMARY_W["planets"]))
    parts += list(day_blocks)
    # Not while the Sun is on the line: between civil dawn and sunrise, or
    # sunset and civil dusk, "civil twilight" is a fact about where the Sun
    # is, said next to the Sun.
    if not civil:
        parts.append((1, dark, SUMMARY_W["dark"]))
    if full_dark:
        # The star count outranks the Bortle note. It used to be the other
        # way round, on the argument that the count is a number about the
        # catalogue while the note is a fact about the sky you are under.
        # True, and beside the point: the count is how much is up *right
        # now* and it moves all evening, where the note is the same sentence
        # every night from the same place. The one that changes is the one
        # worth the characters.
        parts += [(4, note, SUMMARY_W["note"]),
                  (3, f"{len(st['visible'])} stars", SUMMARY_W["stars"])]
    # n_stars defaults to none: the bright stars are labelled on the chart a
    # few rows below this line, which is the one place they cannot be
    # misread as a list of somewhere else.
    bright = [(s, a, z) for s, a, z in
              sorted(st["visible"], key=lambda v: v[0]["m"])[:n_stars]
              if s.get("n")]
    # 5, so it drops before anything else: it is the longest block on the
    # line and the only one whose contents are already labelled on the chart
    # a few rows down. It shared 4 with the note until the note moved there,
    # and two blocks on the same rank leave the trim picking between them by
    # list position, which is not a decision anybody wrote down.
    if bright and full_dark:
        parts.append((5, ", ".join(f"{s['n']} {where_up(a, z)}"
                                   for s, a, z in bright), 0))
    parts = [pt for pt in parts if pt[1]]

    # Each block padded out to its own fixed width, so the line stops
    # rearranging itself as the sky moves. Every number in it changes -- the
    # Moon climbs, planets set, the star count runs from two to four hundred
    # over an evening -- and unpadded, one digit more in the Moon's altitude
    # shunted everything after it sideways. Widths are the realistic worst
    # case per block, not the current content, which is the whole point: a
    # block has to hold its place when its own value is short.
    #
    # The last block is not padded. Trailing spaces at the end of a line are
    # invisible, and padding the tail would only ever cost room.
    def render(pad):
        if len(parts) == 1:
            return parts[0][1]
        if not pad:
            return " · ".join(t for _p, t, _w in parts)
        return (" · ".join(t.ljust(w) if w else t for _p, t, w in parts[:-1])
                + " · " + parts[-1][1])

    # Trimmed on the unpadded length, then padded only if the result still
    # fits. Which way round this goes is not a detail: the head line decides
    # how wide the page is (see this function's own docstring), so a padded
    # summary that overruns does not merely look loose -- it drags the
    # chart, the PNG export and the ladder out with it.
    #
    # pad is asked for rather than inferred from `width`, because one caller
    # passes 10,000 to mean "no limit" (the PNG export, which lays the line
    # out itself). Inferring, the padding always "fitted" there and the
    # export came out with a 191-character header over a 144-column chart.
    while len(parts) > 1 and len(render(False)) > width:
        parts.remove(max(parts, key=lambda pt: pt[0]))
    if not pad:
        return render(False)
    padded = render(True)
    return padded if len(padded) <= width else render(False)


def _head_prefix(r, when_local=None):
    """`  Geneva · 19 Aug 22:00`, the fixed part of the browser's top line.
    Its own function so the summary that follows can be given the width
    that is actually left over, rather than the whole chart's."""
    near = f" · near {r.place.near}" if r.place.near else ""
    return f"  {r.place.name}{near} · {_head_when(r, when_local)}"


def _horizon_head(r, mode, summary=""):
    """The CLI's header, or -- given a summary -- the browser's single top
    line: place, moment, and what is up, in one row.

    The coordinates go on the browser line. Asked for by name they say
    nothing the name doesn't, and asked for by coordinates the *name* is
    already the coordinates, so printing both said it twice. The "near X"
    hint stays either way: it is the only thing identifying a bare pair of
    numbers."""
    p = r.place
    hemi = 'N' if p.lat >= 0 else 'S'
    ew = 'E' if p.lon >= 0 else 'W'
    if summary:
        tail = f" · {mode}" if mode else ""
        return f"{_head_prefix(r)} · {summary}{tail}"
    near = f"  (near {p.near})" if p.near else ""
    return (f"  {p.name}  {abs(p.lat):.2f}°{hemi} {abs(p.lon):.2f}°{ew}{near}"
            f"   {r.when_local:%d %b %Y %H:%M}"
            + (f"   {mode}" if mode else ""))


def _png_url(r):
    """The horizon.png link matching this exact view -- every parameter that
    changes which chart /{place}/horizon.png renders has to travel with the
    link, or it'd silently show something other than whatever's actually on
    screen (this is exactly the bug ?find= and ?t= both had: the page showed
    one thing, "Share as a PNG" quietly linked to another).

    ?t= only travels when it was actually picked (r.when_explicit) -- the
    default link keeps tracking whatever's current instead of freezing to
    the moment it was generated, same reasoning _animate_gif_url's docstring
    gives for always including it (animate has no "current" to track)."""
    q = []
    if r.facing: q.append(f"facing={r.facing}")
    if r.span: q.append(f"span={r.span:g}")
    if r.night: q.append("night=1")
    if r.width: q.append(f"w={int(r.width)}")
    if r.dso: q.append("dso=1")
    if r.quadrant: q.append(f"quadrant={r.quadrant}")
    if r.find: q.append(f"find={quote(r.find)}")
    if not r.lines: q.append("nolines=1")
    if r.when_explicit: q.append(f"t={r.when_local:%Y-%m-%dT%H:%M}")
    qs = ("?" + "&".join(q)) if q else ""
    return f"{{base_url}}/{r.place.slug}/horizon.png{qs}"


def _toggle_qs(r, night=None, nolines=None, dso=None, quadrant_requested=None,
                force_dso_off=False, golden=None):
    """Query string for the current view with one or more flags overridden --
    shared basis for every toggle link (the quadrant button, and the d/l
    keyboard shortcuts). facing/span/w/panel/t always carry over, same
    reasoning as _png_url: toggling one thing shouldn't reset the rest of
    the view already on screen -- panel in particular, since dropping it
    silently moved the zenith inset from beside the chart to below it the
    instant any of these shortcuts fired on an auto-fit-widened page. t=
    only when it was actually picked (r.when_explicit), same as _png_url,
    so the default link keeps tracking whatever's current. Doesn't carry
    find=, matching the quadrant button's existing behaviour these
    shortcuts extend.

    force_dso_off writes an explicit ?nodso=1 alongside ?quadrant -- not used
    by any keyboard shortcut ('d' controls dso and the grid together now),
    but kept as a manual/CLI-only escape hatch: crop to a quadrant without
    the deep-sky overlay. Plain `dso` being false isn't enough to trigger it:
    that's also the ordinary resolved state of a fresh quadrant toggle, which
    should keep the normal implied-on default, not silently opt out of it."""
    night = r.night if night is None else night
    nolines = (not r.lines) if nolines is None else nolines
    dso = r.dso if dso is None else dso
    quadrant_requested = r.quadrant_requested if quadrant_requested is None else quadrant_requested
    golden = r.golden if golden is None else golden
    q = []
    if r.facing: q.append(f"facing={r.facing}")
    if r.span: q.append(f"span={r.span:g}")
    if night: q.append("night=1")
    if r.width: q.append(f"w={int(r.width)}")
    if r.panel: q.append("panel=1")
    if r.when_explicit: q.append(f"t={r.when_local:%Y-%m-%dT%H:%M}")
    # After t=, where the other view-shaping flags sit, so a toggled link
    # reads the same way the quadrant and dso ones already do. Only the off
    # state travels: on is the default, so writing it would put a parameter
    # on every link for no change in what renders, and mint a second cache
    # entry for an identical page.
    if not golden: q.append("nogolden=1")
    if quadrant_requested:
        q.append("quadrant")
        if force_dso_off: q.append("nodso=1")
    elif dso:
        q.append("dso=1")
    if nolines: q.append("nolines=1")
    return ("?" + "&".join(q)) if q else ""


def _quadrant_toggle_url(r):
    """Toggle URL for the 'd' keyboard shortcut (and the quadrant button):
    adds a bare ?quadrant (no letter chosen yet) when it's not currently on,
    or drops it (and the dso it auto-enabled) when it is -- quadrant and dso
    move together as one unit, there's no independent dso-only toggle in the
    keyboard layer (see _dso_toggle_url for the manual/CLI-only escape
    hatch). dso is forced False here either way -- this link never writes an
    explicit dso=1 of its own, whether turning the grid on (quadrant alone
    auto-enables dso server-side, no need to spell it out) or off (dropping
    the grid should drop the dso it implied, not carry over r.dso's still-
    true resolved value from before the toggle). Never writes nodso=1
    either -- toggling the grid itself always resets to the normal
    implied-dso default."""
    qs = _toggle_qs(r, quadrant_requested=not r.quadrant_requested, dso=False)
    return f"/{r.place.slug}{qs}"


def _quadrant_grid_url(r):
    """URL that always lands on the bare lettered grid (?quadrant, no
    specific cell), regardless of the current state -- used by the 'z'
    (zoom) shortcut to get there from anywhere (grid off, or already zoomed
    into one cell) before the arrow-key/enter cell picker takes over
    client-side. Unlike _quadrant_toggle_url this never turns the grid off:
    it's a "go here" link, not a toggle."""
    return f"/{r.place.slug}{_toggle_qs(r, quadrant_requested=True)}"


def _golden_toggle_url(r):
    """Toggle URL for the 'g' key: the golden-hour layer on the day view.

    Only meaningful while the Sun is up -- the caller gates it on that, the
    same way the quadrant/grid links are gated on the star chart -- so the
    key does nothing rather than something confusing on a night chart."""
    return f"/{r.place.slug}{_toggle_qs(r, golden=not r.golden)}"


def _dso_toggle_url(r):
    """Independent dso-only toggle -- no longer bound to a keyboard
    shortcut ('d' now controls dso and the quadrant grid together, see
    _quadrant_toggle_url), kept for manual/CLI use via ?nodso=1. With the
    grid up, dso is force-implied True by default, so turning it off has to
    write ?nodso=1 to actually stick (see _toggle_qs); turning it back on
    just drops that override."""
    new_dso = not r.dso
    return f"/{r.place.slug}{_toggle_qs(r, dso=new_dso, force_dso_off=r.quadrant_requested and not new_dso)}"



def _animate_gif_url(r):
    """Relative -- fetched same-origin by the page's own JS, so no base_url
    substitution needed. facing/night/width from the static view don't
    apply and would be silently ignored -- compose_frame always renders the
    full 360 sweep, continuous day/night blend -- so those are left off
    rather than implying they'd change anything. t= does apply though (both
    /animate.gif and ?animate= start their sequence from base_r.when_utc),
    so it's carried over: without it, animating from a date/time picked on
    the static view silently jumped back to the real current moment instead."""
    return f"/{r.place.slug}/animate.gif?t={r.when_local:%Y-%m-%dT%H:%M}"


def _compose_sky(r):
    p, c = r.place, r.color
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    su = sun(jd)
    sun_alt, _ = altaz(su["ra"], su["dec"], p.lat, lst)
    mag_limit = _fade_mag_limit(sun_alt)
    dso_limit = DSO_LIMIT if r.dso else None
    mw_floor = _milkyway_floor_now(p.lat, p.lon, sun_alt)
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                            tle=r.tle, facing=r.facing, span=r.span,
                            width=r.width if r.facing else _effective_width(r),
                            height=None if r.facing else _horizon_height(r),
                            mag_limit=mag_limit, line_limit=mag_limit,
                            dim_limit=_dim_limit(sun_alt),
                            # "Sun" and "Moon" must stay in the set even
                            # when neither is bright enough to be
                            # "visible" here -- render_linear only
                            # computes alt/az for bodies that survive
                            # this filter, and sky_read() below needs
                            # st["sun"]["alt"] and st["moon"]["alt"]
                            # unconditionally. Missing "Moon" here is
                            # what let ?night=1 during actual daylight
                            # crash with a KeyError.
                            bodies=_fade_visible_bodies(sun_alt, jd) | {"Sun", "Moon"},
                            dso_limit=dso_limit, quadrant=r.quadrant,
                            quadrants=r.quadrant_requested, side_panel=r.panel,
                            milkyway=mw_floor, radiant=_chart_radiant(r),
                            link=_chart_link(r))
    # "horizon panorama, 0-70°" is gone from every view, browser and
    # terminal alike. It described the default, and the default needs no
    # describing: the axis is labelled 0-70 down the left edge and the inset
    # is captioned in the corner, so the words were a caption for something
    # already captioned. The browser had dropped them for that reason and
    # kept them the moment anything else joined them, which is how zooming
    # into one twelfth of the sky produced "horizon panorama, 0-70°,
    # quadrant K" -- a panorama being the one thing that view is not.
    #
    # What is left is only what the drawing cannot say for itself: which way
    # a facing window points and how wide it is, and which quadrant a crop
    # is of. Both are absent from the default view, so most pages carry no
    # mode line at all.
    bits = []
    if r.facing:
        bits.append(f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
                    f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}"
                    f", true shape")
    if st.get("quad_applied"):
        bits.append(f"quadrant {st['quad_applied']}")
    mode = ", ".join(bits)

    # One row on the browser page: place, moment, Moon and planets. The CLI
    # keeps its own two-part header and its own prose, untouched.
    #
    # The summary gets what is left of the chart's width after the place and
    # the moment, not the whole of it -- given the whole, a night with four
    # planets up wrote a top line wider than the chart underneath it, which
    # is the one thing a rung's breakpoint cannot survive.
    summary = ""
    if r.panel:
        # In the browser this row is set at reading size while the chart under
        # it is set smaller, so a character of header is wider than a column
        # of chart and the two cannot be counted in the same units. Scale the
        # whole line's budget by the ratio first, then take the fixed parts
        # off it -- the place and the moment are set in that size too.
        # Budgeted against the size the line is actually set at. It used to
        # divide by CHART_PROSE_PX, which was right when the line sat above
        # the chart at reading size; in its own box at DAY_HEAD_PX it is
        # half again as wide per character, so the old budget let it overrun
        # its box and wrap on a narrow window.
        room = int(_effective_width(r) * CHART_FONT_PX / DAY_HEAD_PX)
        spare = room - len(_head_prefix(r)) - 3
        spare -= len(mode) + 3 if mode else 0
        # The Sun's day, staged. This view runs whenever the Sun is under
        # the horizon, which includes both civil twilights -- the half hour
        # either side of the horizon when the thing worth saying is when the
        # Sun goes or comes, not how many stars are out.
        day_blocks = _head_day_blocks(sun_events_cached(_day0(r), p.lat, p.lon), p,
                                      p.offset(r.when_utc), r.when_utc,
                                      st["sun"]["alt"])
        # Unpadded. Holding each block open at its widest possible content
        # was worth the characters while the line was a fixed set of blocks
        # whose numbers moved -- it stopped the Moon climbing from 9 to 10
        # degrees shunting everything after it. It is not worth them now:
        # blocks arrive and leave at every boundary of the day, so what
        # follows them moves regardless, and the padding only shows up as a
        # hole. "◑ 39% down" in a slot sized for "◑ 47% 15° up SSW" left
        # seven spaces in the middle of the line; "full dark" in one sized
        # for "nautical twilight" left eight more.
        #
        # It would not line up even if it did hold: the directions are set
        # smaller than the rest of the line (see dim_directions), so a
        # column counted in characters is not a column on screen.
        summary = _sky_summary(st, p.lat, max(20, spare),
                               note=sky_note(p.lat, p.lon),
                               day_blocks=day_blocks)
    head = _horizon_head(r, mode, summary=summary)
    # Two colours in the browser, one in a terminal. They arrive as two
    # spans, which is what lets CSS bold the first -- see the day head, same
    # trade for the same reason. Where you are and when is the answer to
    # "what am I looking at"; the rest of the line is what it is doing.
    head_painted = (paint(_head_prefix(r), C.HEAD, c)
                    + paint(head[len(_head_prefix(r)):], C.LABEL, c)
                    if r.panel and summary else paint(head, C.HEAD, c))
    # The Sun is on this line through twilight now, and it is the one glyph
    # here that means something by its colour.
    head_painted = paint_sun_glyph(head_painted, st["sun"]["alt"], C.LABEL, c)
    # Panel mode still wraps wide -- prose sits in its own full-width block
    # below the chart+zenith row (see the side_panel branch below), not
    # squeezed into the zenith's ~30-column-wide column, so there's no
    # reason to wrap it any narrower than the chart itself.
    prose = sky_read(st, p.name, r.when_local, f"UTC{r.tz:+g}", p.lat,
                     wrap_width=_effective_width(r) if r.panel else 76)

    lines = prose.split("\n")[1:]
    if r.panel:
        # Everything the top line now says.
        lines = [l for l in lines if not _moved_to_summary(l)]
    right = [paint("  " + l, C.LABEL, c) for l in lines]
    tr = st.get("track")
    if tr:
        pk = max(tr, key=lambda x: x[1])
        right.append(paint(f"  Pass: rises {compass(tr[0][2])} +{tr[0][0]:.0f} min, "
                           f"peaks {pk[1]:.0f}° in the {compass(pk[2])}, "
                           f"sets {compass(tr[-1][2])} +{tr[-1][0]:.0f} min.",
                           "\033[38;5;48m", c))
    elif st.get("iss_err"):
        right.append(paint(f"  ISS: {st['iss_err']}", C.MUTE, c))
    if r.dso:
        right.append(paint(f"  {DSO_LEGEND}", C.MUTE, c))
    if st.get("quad_error"):
        right.append(paint(f"  Unknown quadrant '{st['quad_error']}' -- showing the full view.",
                           C.MUTE, c))
    if st.get("quad_cells"):
        letters = [cell["letter"] for cell in st["quad_cells"]]
        # Both halves of the long sentence are instructions for editing a
        # URL by hand, which is how it works in a terminal and not how it
        # works in a browser -- there, z opens the arrow-key picker and
        # Enter crops, and the picker prints its own hint while it is up.
        right.append(paint(
            f"  Quadrants {letters[0]}-{letters[-1]} · z to pick" if r.panel else
            f"  Quadrants {letters[0]}-{letters[-1]} are marked on the chart. "
            f"To zoom in, rerun adding ?quadrant={letters[0]} "
            f"(or --quadrant={letters[0]} on the CLI).", C.MUTE, c))
    teaser = events_teaser(r)
    if teaser:
        import textwrap
        right += [paint("  " + l, EVENT_COL, c) for l in textwrap.wrap(teaser, 76)]
    # {base_url} is a literal placeholder -- api.py doesn't know its own
    # host, server.py substitutes the real one on the way out, on both
    # cache hits and misses, so a cached render never leaks whatever host
    # first produced it.
    right.append(paint(f"  Share as a PNG: {_png_url(r)}", SUN_COL, c))

    if r.panel:
        # zenith_lines is None when this view has no inset at all (facing=,
        # target=, or a quadrant crop already applied) -- st.get, not
        # st[...], since disc view's own st dict never has this key.
        #
        # The three pieces go out separated rather than stacked: the browser
        # floats the inset over the chart's top corner and pins the prose
        # above the shortcut bar, which gives the panorama the inset's 33ch
        # back and the prose's rows with it. Laid out here as one column,
        # the chart could only ever be as wide as the window minus the
        # inset.
        zenith = st.get("zenith_lines") or []
        out = ["", head_painted, "", art,
               ZENITH_SLOT] + zenith + [PROSE_SLOT] + right
    else:
        out = ["", head_painted, "", art, ""]
        out += right
    out += ["", _footer(p, c), ""]

    mo, su = st["moon"], st["sun"]
    data = dict(
        place=p.name, near=p.near, lat=p.lat, lon=p.lon, tz_offset=r.tz,
        when_utc=r.when_utc.isoformat() + "Z", when_local=r.when_local.isoformat(),
        view="horizon",
        facing=r.facing, span=round(st.get("span", 360), 1),
        sun_alt=round(altaz(su["ra"], su["dec"], p.lat, st["lst"])[0], 1),
        moon=dict(phase=phase_name(mo["age"]), illum=round(mo["illum"] * 100),
                  alt=round(mo["alt"], 1), compass=compass(mo["az"])),
        bodies=_bodies_json(st),
        brightest=[dict(name=s["n"], mag=s["m"], alt=round(a, 1), compass=compass(z))
                   for s, a, z in sorted(st["visible"], key=lambda v: v[0]["m"])[:5]
                   if s.get("n")],
        asterisms=st.get("cons", []),
        stars_up=len(st["visible"]),
        iss_pass=_pass_json(st.get("track")),
        dso=r.dso,
        quadrant=dict(cells=[cell["letter"] for cell in st.get("quad_cells", [])],
                     applied=st.get("quad_applied"), error=st.get("quad_error")),
        coming_up=teaser,
        # Structured twin of coming_up, for the web UI's card. See the
        # <!-- skymap:coming-up-card --> marker in PAGE.
        coming_up_card=events_card(r),
        prose=prose,
    )
    return Result("\n".join(out), data)


# _ansi_hex()/_xterm_hex() (defined later in this file, for catalog_html())
# give the 3D view a ready-to-draw colour per object -- same xterm-256 table
# sky.py's ASCII renderer uses (star_colour, sky.C, DSO_GLYPH), so the sphere
# is a faithful re-skin, not a reinvention.

# The Sun's glyph colour is inlined in render() rather than a named C.
# constant (sky.py's render(), the "-- bodies --" block) -- kept in sync here
# by hand since there's nothing to import.
_SUN_ANSI = "\033[38;5;227m"



# A fixed naked-eye cutoff, not _fade_mag_limit(sun_alt) -- the sphere shows
# the FULL celestial sphere, not just the local dome, so there's no single
# "is it day or night" to fade against: the far side is always night for
# someone even when it's daytime here. Same default render() itself uses.
SPHERE_MAG_LIMIT = 4.2

def _compose_sphere(r):
    """The current sky as data, not ASCII -- everything /{place}/sphere's 3D
    view needs to place stars, constellation lines, deep-sky objects and
    bodies on a full sphere around the viewer (not just the visible dome --
    above_horizon=False below includes what's below the horizon too, the
    far side of the sky). No text/ANSI form of this exists, so (unlike every
    other _compose_*) this returns a plain dict, not a Result. Each object
    carries the same glyph and colour sky.py's ASCII renderer would draw for
    it, so the 3D view is a faithful re-skin, not a reinvention."""
    p = r.place
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    su = sun(jd)
    sun_alt, _ = altaz(su["ra"], su["dec"], p.lat, lst)
    dso_limit = DSO_LIMIT if r.dso else None

    # How long until it's actually dark, for the daytime "come back later"
    # message -- same dusk computation _compose_day already uses for its
    # own "first stars about ..., fully dark ..." line, not a second copy
    # of the twilight math.
    hours_to_dark = None
    if sun_alt > 0:
        off = p.offset(r.when_utc)
        day0 = r.when_local.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(hours=off)
        ev = sun_events(day0, p.lat, p.lon)
        # Astronomical dusk only. Falling back to nautical here counted down
        # to a darkness that never arrives at high summer latitudes, and the
        # page already has the right words for null ("the sky won't get fully
        # dark today") -- it just never reached them.
        dark = ev.get("dusk_astro")
        if dark and dark > r.when_utc:
            hours_to_dark = round((dark - r.when_utc).total_seconds() / 3600, 1)

    bodies = [planet(nm, jd) for nm in
              ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune")]
    mo = moon(jd)
    bodies += [mo, su]
    for b in bodies:
        a, z = altaz(b["ra"], b["dec"], p.lat, lst)
        b["alt"], b["az"] = a, z   # every body, not just ones above the
                                    # horizon -- full sphere, same as stars/dso

    bodies_json = _bodies_json(dict(up=bodies))
    for item in bodies_json:
        if item["name"] == "Moon":
            item["glyph"], item["color"] = sky.moon_glyph(mo["age"]), _ansi_hex(sky.C.MOON)
        elif item["name"] == "Sun":
            item["glyph"], item["color"] = "☀", _ansi_hex(_SUN_ANSI)
        else:
            item["glyph"], item["color"] = "◆", _ansi_hex(sky.C.PLANET)

    return dict(
        place=p.name, lat=p.lat, lon=p.lon, tz_offset=r.tz,
        when_utc=r.when_utc.isoformat() + "Z", when_local=r.when_local.isoformat(),
        sun_alt=round(sun_alt, 1), mag_limit=SPHERE_MAG_LIMIT, dso=r.dso,
        hours_to_dark=hours_to_dark,
        stars=[dict(hr=s["hr"], name=s.get("n"), bayer=s.get("b"), con=s.get("c"),
                    mag=s["m"], ci=s.get("ci"), alt=round(a, 1), az=round(z, 1),
                    glyph=sky.glyph_for(s["m"]), color=_ansi_hex(sky.star_colour(s.get("ci"))))
               for s, a, z in sky.stars_visible(SPHERE_MAG_LIMIT, jd, p.lat, lst, above_horizon=False)],
        asterisms=sky.asterism_lines_visible(jd, p.lat, lst, above_horizon=False),
        deepsky=[dict(id=o["id"], name=o.get("n"), common_name=o.get("cn"),
                     type=o["t"], mag=o["m"], alt=round(a, 1), az=round(z, 1),
                     glyph=sky.DSO_GLYPH[o["t"]][0], color=_ansi_hex(sky.DSO_GLYPH[o["t"]][1]))
                for o, a, z in sky.deepsky_visible(dso_limit, jd, p.lat, lst, above_horizon=False)],
        bodies=bodies_json,
        moon=dict(phase=phase_name(mo["age"]), illum=round(mo["illum"] * 100),
                  alt=round(mo["alt"], 1), az=round(mo["az"], 1), compass=compass(mo["az"])),
        # The one thing this view can do that no chart can: point your actual
        # body at the thing. Empty on all but a handful of nights a year.
        markers=_markers_json(r),
        golden=_sphere_golden(r),
        # How faint a contour is still worth drawing here, or 0 for a sky
        # too bright for any of it. The grid itself is a static asset the
        # page fetches once (/milkyway.json) -- the sky's structure is the
        # same everywhere, only how much of it you can see is local.
        milkyway_floor=_milkyway_floor_now(p.lat, p.lon, sun_alt),
        # Local sidereal time, so the page can turn the Milky Way's
        # RA/Dec grid into the same alt/az everything else arrives in
        # without a second copy of the sidereal-time maths in JS.
        lst_hours=round(lst, 6),
        bortle=sky_brightness(p.lat, p.lon)[1],
    )


# One point per this many minutes along the Sun's day. The scrubber reads
# between them, so this is the resolution of the *track*, not of the answer:
# ten minutes moves the Sun about 2.5 degrees, which is smooth enough to
# drag along and costs 145 points of three numbers each -- a couple of KB
# before gzip, against the 110 KB the star list already spends.
SPHERE_TRACK_STEP = 10


def _sphere_golden(r):
    """The golden-hour model for the 3D view: the Sun's whole track for the
    day, the band edges, and where it is right now.

    The flat chart can only draw the half of the golden band that is above
    the horizon. A sphere has no such problem -- there is a below to draw in
    -- so this carries the real -4 to +6 window and the blue hour under it,
    which is the first time blue hour gets to be a band rather than a
    sentence.

    Times are minutes from local midnight rather than clock strings: the
    scrubber does arithmetic on them, and a client that wants to display one
    already has tz_offset."""
    p = r.place
    off = p.offset(r.when_utc)
    day0 = r.when_local.replace(hour=0, minute=0, second=0,
                                microsecond=0) - dt.timedelta(hours=off)
    ev = sun_events(day0, p.lat, p.lon)
    bands = sky.sun_bands(day0, p.lat, p.lon, ev)

    def mins(t):
        return None if t is None else round((t - day0).total_seconds() / 60)

    def band(b):
        if not b:
            return None
        return dict(start=mins(b["start"]), end=mins(b["end"]),
                    open_end=b["open_end"])

    # floor=-90 keeps the whole day including the night half: the band edges
    # this view can draw run to -6, and a track that stopped at the horizon
    # would leave the blue hour hanging off the end of it.
    track = [[round(t), round(a, 2), round(z, 2)]
             for t, a, z in sun_arc(day0, p.lat, p.lon,
                                    step_min=SPHERE_TRACK_STEP, floor=-90.0)]
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    sa, sz = altaz(sun(jd)["ra"], sun(jd)["dec"], p.lat, lst)
    ratio = sky.shadow_ratio(sa)
    return dict(
        step_min=SPHERE_TRACK_STEP, track=track,
        now_min=round((r.when_utc - day0).total_seconds() / 60),
        sun=dict(alt=round(sa, 2), az=round(sz, 2)),
        # The band edges as altitudes, so the client draws the rings itself
        # rather than being sent geometry it can derive.
        edges=dict(golden_lo=sky.GOLDEN_LO, golden_hi=sky.GOLDEN_HI,
                   blue_lo=-6.0, blue_hi=sky.GOLDEN_LO, horizon=-0.833),
        note=bands["note"],
        golden_am=band(bands["golden_am"]), golden_pm=band(bands["golden_pm"]),
        blue_am=band(bands["blue_am"]), blue_pm=band(bands["blue_pm"]),
        sunrise=mins(ev.get("sunrise")), sunset=mins(ev.get("sunset")),
        shadow=None if ratio is None else round(min(ratio, 999), 2),
    )


def _marker_caption(e):
    """The one line the sphere's strip shows for this marker. Short: it has a
    single line on a phone, and the chevron eats the end of it."""
    bits = []
    if e["kind"] == "meteor_shower":
        bits.append(f"{e['name']} radiant")
        if e.get("window_local"):
            bits.append(f"best {e['window_local'][0]}-{e['window_local'][1]}")
        if e.get("zhr"):
            bits.append(f"up to {e['zhr']}/hr")
        if e.get("moon_verdict"):
            bits.append(e["moon_verdict"])
    else:
        bits.append(e["headline"])
        if e.get("alt") is not None and e.get("compass"):
            bits.append(f"{e['alt']:.0f}° {e['compass']}")
        if e.get("window_local"):
            bits.append(f"best {e['window_local'][0]}-{e['window_local'][1]}")
    return " · ".join(bits)


def _markers_json(r):
    """Everything worth turning to face tonight, best first.

    Positions are taken at the BEST moment tonight, not at the instant of the
    request: things climb through the night, and where to look when you
    actually go outside is the useful answer. That makes these fixed markers
    rather than live positions, which is why nothing re-computes them on a
    timer.
    """
    out = []
    # The reader's own sky, which decides whether a shower merely running --
    # as against peaking -- is worth pointing at from here. A five-an-hour
    # Ursid night is a real thing under Bortle 2 and nothing at all under 8.
    _mag, bortle = sky_brightness(r.place.lat, r.place.lon)
    for e in ev_mod.locatable_tonight(r.place.lat, r.place.lon, r.tz,
                                      now_utc=r.when_utc, bortle=bortle):
        out.append(dict(
            kind=e["kind"], name=e["name"], headline=e["headline"],
            alt=e["alt"], az=e["az"], compass=e.get("compass"),
            zhr=e.get("zhr"), sep_deg=e.get("sep_deg"),
            when_local=e["when_local"].isoformat(),
            best_local=(e["best_local"].isoformat() if e.get("best_local") else None),
            window_local=e.get("window_local"),
            moon_verdict=e.get("moon_verdict"),
            caption=_marker_caption(e),
            # A radiant is a direction with nothing at it; everything else is
            # an object sitting at a point. The client draws them differently.
            shape="radiant" if e["kind"] == "meteor_shower" else "point",
            glyph=e.get("glyph", "✦"),
        ))
    return out


# ---------------------------------------------------------------- daytime
SUN_COL = "\033[38;5;220m"
DAY_BUCKET = 10                     # minutes; the Sun moves ~2.5° in that time
# Shared by every day-arc chart (static day view, its PNG mirror, and the
# animation) so the vertical scale never jumps between them -- it used to
# be 30 here and 70 in compose_frame, which meant clicking "animate" (which
# replaces the static chart in place) visibly snapped the y-axis taller.
DAY_ALT_HI_FLOOR = 70.0

def is_daytime(r):
    jd = julian(r.when_utc)
    su = sun(jd)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    return altaz(su["ra"], su["dec"], r.place.lat, lst)[0] > 0.0


def _hm(t, off):
    return (t + dt.timedelta(hours=off)).strftime("%H:%M") if t else "--"


# Past this the ratio stops being a usable number: cot(h) is 9.5x at the top
# of the golden band, 57x at half a degree, and somewhere in there the slope
# of the ground you are standing on matters more than the arithmetic does.
SHADOW_CAP = 20.0


# The band fill is a step darker than the arc so the Sun still reads on top
# of it; the label takes the arc's own gold. Blue hour gets a real blue --
# it happens entirely below the horizon at these latitudes, so it never gets
# a band of its own and the colour is the only thing marking it as a
# different kind of light.
GOLD_BAND_COL = "\033[38;5;136m"
BLUE_HOUR_COL = "\033[38;5;75m"


def _golden_layer(r, bands, ev, off, sa, sz, alt_hi, width):
    """The golden-hour layer for the day chart: the band itself, and the
    lines of text that sit above it.

    The band is drawn full width because that is what it is -- a range of Sun
    altitudes, which the Sun crosses twice a day. Only the part above the
    horizon can appear, so the stripe is the top 6 degrees of a window that
    really starts 4 degrees lower, and the times printed on it are the whole
    window rather than the visible slice of it.

    Blue hour never gets a stripe. It runs from -6 to -4, entirely under the
    horizon line, so it is a line of text in blue rather than a band that
    would have to be drawn somewhere it does not belong."""
    if not r.golden:
        return None, None

    def win(b):
        return f"{_hm(b['start'], off)}-{_hm(b['end'], off)}"

    note, g_am, g_pm = bands["note"], bands["golden_am"], bands["golden_pm"]
    if note == "all_night" and g_pm:
        gold_txt = f"golden from {_hm(g_pm['start'], off)} all night"
    elif note == "all_day" and g_am:
        gold_txt = f"golden all day {win(g_am)}"
    elif g_am and g_pm:
        gold_txt = f"golden {win(g_am)} · {win(g_pm)}"
    elif g_am or g_pm:
        gold_txt = f"golden {win(g_am or g_pm)}"
    else:
        gold_txt = ""

    # Right now, not just today. The whole line is a schedule until the
    # moment it is an instruction, and this is the difference -- the arrows
    # only appear while the Sun is actually inside the band, which on a
    # daylight chart means the visible half of it, 0 to +6.
    if gold_txt and sky.GOLDEN_LO <= sa <= sky.GOLDEN_HI:
        gold_txt = f">> {gold_txt} <<"

    b_am, b_pm = bands["blue_am"], bands["blue_pm"]
    if b_am and b_pm:
        blue_txt = f"blue {win(b_am)} · {win(b_pm)}"
    elif b_am or b_pm:
        blue_txt = f"blue {win(b_am or b_pm)}"
    else:
        blue_txt = ""

    # Where the light comes from, which is the half of this nobody else
    # prints, and how long it makes things -- on the chart rather than in a
    # paragraph under it, because a daylight chart has nothing else up there.
    # Ranked, then trimmed from the least important end until the line fits
    # the chart it has to sit inside -- the narrowest ladder rung is 80
    # columns and the full line does not fit there. Same approach the panel
    # head takes, and it keeps the bearings (the point) over the shadow.
    head = []
    for name, word in (("sunrise", "sunrise"), ("sunset", "sunset")):
        t = ev.get(name)
        if t:
            az = sky.sun_altaz(t, r.place.lat, r.place.lon)[1]
            head.append((1, f"{word} {_hm(t, off)}  {az:.0f}° {compass(az)}"))
    ratio = sky.shadow_ratio(sa)
    if ratio is not None:
        size = f">{SHADOW_CAP:.0f}x" if ratio > SHADOW_CAP else f"{ratio:.1f}x"
        head.append((2, f"shadows {size} toward {compass((sz + 180) % 360)}"))
    # width - 2 leaves room for the space either side that the renderer pads
    # a note with; without that allowance the full line comes out exactly two
    # columns too wide for the narrowest rung and is dropped rather than
    # trimmed.
    sep = "   ·   "
    while head and len(sep.join(t for _p, t in head)) > width - 2:
        head.remove(max(head, key=lambda pt: pt[0]))
    head_txt = sep.join(t for _p, t in head)

    alt_bands = [dict(lo=0.0, hi=sky.GOLDEN_HI, ch=":", col=GOLD_BAND_COL)]
    # Anchored a little above the band, in that order, so the gold line sits
    # nearest the stripe it names. notes places each one upward from its
    # anchor into the first row that is actually free, so a low Sun pushes
    # them clear of the arc rather than overwriting it.
    step = max(2.0, alt_hi * 0.045)
    notes = [dict(text=head_txt, col=SUN_COL, alt=alt_hi * 0.96)]
    if gold_txt:
        notes.append(dict(text=gold_txt, col=SUN_COL, alt=sky.GOLDEN_HI + step))
    if blue_txt:
        notes.append(dict(text=blue_txt, col=BLUE_HOUR_COL,
                          alt=sky.GOLDEN_HI + step * 2))
    return alt_bands, [n for n in notes if n["text"]]


def _golden_json(bands, ev, off, sa, sz, lat, lon):
    """The golden-hour facts, structured.

    Bearings are rounded to a degree and lengths to a tenth. Neither is
    accurate past that: the Sun's position here is a low-precision series good
    to about an arcminute, and a shadow on real ground is at the mercy of the
    slope long before the second decimal matters."""
    def local(t):
        # Whole seconds. These come out of a bisection, so they carry a tail
        # of microseconds that reads like precision the Sun's position does
        # not have -- the series behind it is good to about an arcminute.
        return (t + dt.timedelta(hours=off)).replace(microsecond=0).isoformat()

    def band(b):
        if not b:
            return None
        return dict(
            start=local(b["start"]),
            end=None if b["end"] is None else local(b["end"]),
            minutes=b["minutes"], open_end=b["open_end"],
            az_start=round(b["az_start"]),
            az_end=None if b["az_end"] is None else round(b["az_end"]),
            compass_start=compass(b["az_start"]),
            compass_end=None if b["az_end"] is None else compass(b["az_end"]))

    ratio = sky.shadow_ratio(sa)
    rise_az = sky.sun_altaz(ev["sunrise"], lat, lon)[1] if ev.get("sunrise") else None
    set_az = sky.sun_altaz(ev["sunset"], lat, lon)[1] if ev.get("sunset") else None
    return dict(
        # Stated, not implied. Tools disagree about where golden hour starts
        # and a client comparing two of them needs to know which one this is.
        convention=dict(lo_alt=sky.GOLDEN_LO, hi_alt=sky.GOLDEN_HI,
                        blue_lo_alt=-6.0, blue_hi_alt=sky.GOLDEN_LO),
        note=bands["note"],
        golden_am=band(bands["golden_am"]), golden_pm=band(bands["golden_pm"]),
        blue_am=band(bands["blue_am"]), blue_pm=band(bands["blue_pm"]),
        sunrise_az=None if rise_az is None else round(rise_az),
        sunrise_compass=None if rise_az is None else compass(rise_az),
        sunset_az=None if set_az is None else round(set_az),
        sunset_compass=None if set_az is None else compass(set_az),
        shadow=None if ratio is None else dict(
            ratio=round(ratio, 1), capped=ratio > SHADOW_CAP,
            az=round((sz + 180) % 360), compass=compass((sz + 180) % 360)),
    )


def _compose_day(r):
    """No star chart worth drawing while the Sun is up, so draw the Sun instead:
    its arc across today, with rise, transit and set marked. Everything here is
    stable for the whole day except the 'now' marker, which is quantised to
    """ + f"{DAY_BUCKET}" + """ minutes — so this response caches for hours, not seconds."""
    p, c = r.place, r.color
    off = p.offset(r.when_utc)
    day0_local = r.when_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day0 = day0_local - dt.timedelta(hours=off)

    ev = sun_events(day0, p.lat, p.lon)
    bands = sky.sun_bands(day0, p.lat, p.lon, ev)
    arc = sun_arc(day0, p.lat, p.lon, step_min=DAY_BUCKET)
    # The same cap the night chart uses, so both have the same axis and a
    # reader moving between them is not silently rescaled. It used to be the
    # Sun's own peak plus 8, which meant the arc always fitted and the Sun
    # could never reach the inset -- the box was empty by construction rather
    # than because nothing was overhead. Above the cap the arc and the Sun
    # both go into the inset now (see render_linear's overlay block).
    alt_hi = DAY_ALT_HI_FLOOR
    # The golden band is a range of Sun altitudes, so the arc can colour
    # itself: no time lookup, no second pass, and the marked stretch lands
    # exactly where the arc crosses those altitudes. Only the part above the
    # horizon can show -- this chart starts at 0 deg -- so the arc carries the
    # last few degrees of the window and the prose carries all of it.
    arc = [(t, a, z, "•", _sun_color(a)) if sky.GOLDEN_LO <= a <= sky.GOLDEN_HI
           else (t, a, z) for t, a, z in arc]

    jd_now = julian(r.when_utc)
    mo_now = moon(jd_now)
    # The Moon is genuinely visible by day when it is more than half lit;
    # the planets are not, so they are left off rather than drawn as a lie.
    # The Sun gets one marker, on where it actually is. Drawing it at the top of
    # the arc labels noon, which is not what anyone is asking.
    lst_now = (gmst_hours(jd_now) + p.lon / 15.0) % 24
    su_now = sun(jd_now)
    sa_now, sz_now = altaz(su_now["ra"], su_now["dec"], p.lat, lst_now)
    # ...or right next to the Sun, an eclipse mate -- a new moon reflects
    # ~0% sunlight, so the illum>0.4 rule alone would never show it then.
    show = {"Moon"} if mo_now["illum"] > 0.4 or _near_sun(jd_now) else set()
    # mag_limit is always -5.0 here in practice (this branch only runs while
    # sun_alt >= 0, is_daytime()'s gate), but computed via the same shared
    # formula _compose_sky uses rather than a second hardcoded copy of it.
    alt_bands, notes = _golden_layer(r, bands, ev, off, sa_now, sz_now, alt_hi,
                                     _effective_width(r))
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=False,
                            mag_limit=_fade_mag_limit(sa_now), alt_lo=0.0, alt_hi=alt_hi,
                            overlay=(arc, SUN_COL, "SUN", (sa_now, sz_now)),
                            bodies=show, width=_effective_width(r),
                            side_panel=r.panel,
                            height=_day_height(r),
                            alt_bands=alt_bands, notes=notes)

    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    sa, sz = altaz(sun(jd)["ra"], sun(jd)["dec"], p.lat, lst)
    mo = moon(jd)
    first = ev.get("dusk_civil") or ev.get("dusk_nautical")
    # "fully dark" means astronomical dusk and nothing else. This used to fall
    # back to nautical when the Sun never reached -18 deg, which quietly
    # printed a real-looking time for a darkness that never arrives -- London
    # on the solstice said "fully dark 23:23" on a night that never gets
    # there at all. Between ~48.5 deg and the Arctic circle that is every
    # midsummer night, so the fallback was wrong for London, Amsterdam,
    # Berlin, Warsaw, Vancouver and Calgary for months at a time.
    dark = ev.get("dusk_astro")
    if not first:
        dark_txt = "the sky never gets fully dark today"
    elif dark:
        # "darkest", not "fully dark". The time is astronomical dusk, which
        # says where the Sun is and not whether you can see anything: in a
        # city the light dome sets a floor the Sun going further down does
        # nothing about, so the sky never gets fully dark there at all.
        # "Darkest" is true at both ends -- when the sky finishes getting
        # dark at a dark site, and as dark as the night is going to get in
        # town -- and needs no Bortle to be honest.
        dark_txt = f"first stars about {_hm(first, off)}, darkest {_hm(dark, off)}"
    else:
        dark_txt = (f"first stars about {_hm(first, off)}, but it never gets "
                    f"fully dark tonight")

    lines = [
        f"Daylight. The Sun is {sa:.0f}° up in the {compass(sz)}, and no stars are "
        f"visible until it sets.",
        f"Sunrise {_hm(ev.get('sunrise'), off)} · highest {ev['max_alt']:.0f}° at "
        f"{_hm(ev.get('transit'), off)} · sunset {_hm(ev.get('sunset'), off)} · "
        f"{dark_txt}.",
    ]
    if ev["polar_day"]:
        lines.append("The Sun does not set here today.")
    if r.facing:
        lines.append("The Sun's path is a whole-sky view, so facing was "
                     "ignored here. Add --night (or ?night=1) to force a star "
                     "chart in daylight.")
    # only promise what will actually be above the horizon once it is dark
    later = []
    if first:
        jd_d = julian(first)
        lst_d = (gmst_hours(jd_d) + p.lon / 15.0) % 24
        for n in ("Mercury", "Venus", "Mars", "Jupiter", "Saturn"):
            b = planet(n, jd_d)
            if b["mag"] < 2.0 and altaz(b["ra"], b["dec"], p.lat, lst_d)[0] > 8:
                later.append(b)
    if first and later:
        lines.append("Waiting for you tonight: " +
                     ", ".join(b["name"] for b in later) +
                     f", and a {phase_name(mo['age'])} Moon "
                     f"({mo['illum']*100:.0f}% lit).")
    teaser = events_teaser(r)
    if teaser:
        lines.append(teaser)
    if first:
        tl = first + dt.timedelta(hours=off)
        # Quoted: zsh (the default shell on macOS) treats a bare ? as a glob
        # character and errors with "no matches found" on an unquoted URL.
        lines.append(f"See tonight's chart now:  "
                     f"curl 'skymap.sh/{p.slug}?t={tl:%Y-%m-%dT%H:%M}'")

    if r.panel:
        # Before the wrap, not after: these sentences run past 76 characters
        # and wrap into two rows each, so dropping them by their opening
        # words left the tail behind -- the browser showed a lone "sets."
        # under the chart.
        lines = [l for l in lines
                 if not l.startswith(("Daylight. The Sun is", "Sunrise ",
                                      "The Sun does not set here today",
                                      "Waiting for you tonight:"))]

    import textwrap
    body = []
    for l in lines:
        body.extend(textwrap.wrap(l, 76))

    if r.panel:
        # Same one row the night chart gets: where the Sun is, the day's
        # turning points, and what will be up once it is dark. The two
        # sentences below said this in 96 and 76 characters, wrapping to
        # four rows between them.
        # In the order the day happens, which is the order somebody reads a
        # line like this: it is here now, it gets that high, it goes down
        # over there, then the stars, then the dark. Grouped by kind instead
        # -- times together, angles together -- it read as a table that had
        # lost its headings.
        #
        # Which of those blocks is on the line is _head_day_blocks' job, and
        # the same call serves the night view: a block is carried while what
        # it names is still ahead and goes once it has passed, so sunrise is
        # not still on the line at teatime and sunset is not on it at dawn.
        # That is what makes the two views one line rather than two -- see
        # the docstring there.
        #
        # Priorities are what gets dropped first on a narrow window, highest
        # first. Where the Sun is *now* is the one thing the page is about,
        # so it never goes, and it leads the line straight after the moment
        # rather than sitting in time order between sunrise and sunset: it
        # is the one block that has to survive the crossing into night, and
        # a block that moves as the Sun sets is a block the eye has to find
        # again.
        parts = [(0, _sun_head_block(sa, sz))]
        # The Moon, but only when it is actually up. By day it is the one
        # other thing genuinely worth looking at -- and on the afternoons it
        # is under the horizon, "below the horizon" would spend
        # twenty-four characters saying there is nothing to see.
        mo_a, mo_z = altaz(mo["ra"], mo["dec"], p.lat, lst)
        if mo_a > 0:
            parts.append((2, f"{moon_glyph(mo['age'], p.lat)} "
                             f"{mo['illum'] * 100:.0f}% {where_up(mo_a, mo_z)}"))
        parts += [(rank, text) for rank, text, _w
                  in _head_day_blocks(ev, p, off, r.when_utc, sa, sz, bands)]
        # No "tonight: Venus" here any more. The panel beside the chart
        # cycles the planets that are up, one at a time and drawn, which is
        # both more use and more room than a comma-separated tail on a line
        # that is already the longest thing on the page.
        prefix = _head_prefix(r)
        while len(parts) > 1 and (len(prefix) + 3 +
                                  len(" · ".join(x for _p, x in parts))
                                  > _effective_width(r)):
            parts.remove(max(parts, key=lambda pt: pt[0]))
        # Two colours, not one, and they become two spans in the browser --
        # which is what lets CSS make the first of them bold. Where you are
        # and when is the answer to "what am I looking at"; the rest of the
        # line is the answer to "and what is it doing", and it should not
        # shout as loudly. C.LABEL against C.HEAD is five steps of grey.
        rest = " · ".join(x for _p, x in parts)
        head = f"{prefix} · {rest}"
        # body was filtered before wrapping, above. What is left is the
        # exceptional stuff: a facing/view request this page cannot honour,
        # and anything else worth a sentence of its own.
        # The inset, same slot the night chart uses. side_panel takes it out
        # of `art` and hands it back through st, so a page that does not emit
        # it here simply loses it -- which is why the day chart had none in a
        # browser while a terminal got one inline.
        zenith = st.get("zenith_lines") or []
        out = (["", paint_sun_glyph(paint(prefix, C.HEAD, c)
                                    + paint(f" · {rest}", C.LABEL, c),
                                    sa, C.LABEL, c),
                "", art]
               + ([ZENITH_SLOT] + zenith if zenith else [])
               + [PROSE_SLOT])
    else:
        head = _horizon_head(r, _sun_path_mode(r))
        out = ["", paint(head, C.HEAD, c), "", art, ""]
    out += [paint("  " + l, C.LABEL, c) for l in body]
    out.append(paint(f"  Share as a PNG: {_png_url(r)}", SUN_COL, c))
    out += ["", _footer(p, c), ""]

    data = dict(place=p.name, near=p.near, lat=p.lat, lon=p.lon, tz_offset=off,
                when_utc=r.when_utc.isoformat() + "Z",
                when_local=r.when_local.isoformat(),
                view="day", daytime=True,
                sun=dict(alt=round(sa, 1), az=round(sz, 1), compass=compass(sz)),
                events={k: (v + dt.timedelta(hours=off)).isoformat()
                        for k, v in ev.items() if isinstance(v, dt.datetime)},
                max_alt=round(ev["max_alt"], 1),
                polar_day=ev["polar_day"], polar_night=ev["polar_night"],
                first_stars=(first + dt.timedelta(hours=off)).isoformat() if first else None,
                # null whenever the Sun never reaches -18 deg, which is a
                # real answer and not a missing one. never_fully_dark says
                # which it is, so a client does not have to guess from a
                # null: with polar_day it means the Sun never sets at all,
                # without it the ordinary high-latitude midsummer case where
                # twilight simply never deepens into darkness.
                dark_from=(dark + dt.timedelta(hours=off)).isoformat() if dark else None,
                never_fully_dark=dark is None,
                golden=(_golden_json(bands, ev, off, sa, sz, p.lat, p.lon)
                        if r.golden else None),
                visible_tonight=[b["name"] for b in later],
                moon=dict(phase=phase_name(mo["age"]),
                          illum=round(mo["illum"] * 100)),
                # "events" was already taken by the Sun's own rise/transit/set
                # above, so the sky-events list is "coming_up" rather than
                # shadowing a key clients already read.
                coming_up=teaser,
                coming_up_card=events_card(r),
                prose="\n".join(body))
    return Result("\n".join(out), data)


# ---------------------------------------------------------------- what's coming up
EVENT_COL = "\033[38;5;213m"    # orchid: not the sun's yellow, not the DSO green
# What is running right now, as against what is on the calendar. The dated
# rows are a plan; this is the sky as it is at this minute, which is a
# different kind of claim and reads better as a different colour. Green
# because that is already what live means on this site -- the pill uses it --
# and far enough from the orchid that nobody has to compare two rows to tell
# which group they are looking at.
NOW_COL = "\033[38;5;120m"

# How near an event has to be before it earns a line on a page that is
# otherwise a star chart. Two weeks is long enough to plan a night out and
# short enough that the line is absent most of the time -- which is what
# keeps it worth reading when it does appear.
TEASER_DAYS = 14

# Beyond this the list is padding. Ninety days covers a season, which is the
# horizon people actually plan on.
EVENTS_WINDOW_DAYS = 90


def _events_for(r, days=EVENTS_WINDOW_DAYS, visible_only=True):
    p = r.place
    return ev_mod.upcoming(p.lat, p.lon, r.tz, now_utc=r.when_utc, days=days,
                           visible_only=visible_only)


def _chart_link(r):
    """name -> the object's page here, or None if it has no page.

    Browser only. A terminal cannot click a star, and the markers this
    produces would print as control characters if they ever reached one.
    """
    if not r.panel:
        return None
    place = quote(r.place.slug)

    def link(name):
        canonical = objects.resolve_name(name)
        if not canonical:
            return None
        return f"/{place}/{quote(canonical)}{_chart_link_when(r)}"
    return link


def _chart_link_when(r):
    """Carry the moment through, so a label opens the sky it was drawn in."""
    return f"?t={r.when_local:%Y-%m-%dT%H:%M}" if r.when_explicit else ""


def _chart_radiant(r):
    """The shower radiant to mark on the chart, at the chart's own moment.

    Not the alt/az the event carries: that is where the radiant sits at the
    *best* moment of the night, which is the right answer for a list row and
    the wrong one for a drawing of 22:00. Recomputed here from the radiant's
    coordinates so the glyph lands where the sky actually has it.

    Peaks count as well as merely-running nights -- on the peak the chart is
    the one place a reader most wants to be shown where to look.
    """
    if r.facing or r.quadrant:
        return None                      # a crop has its own subject
    _mag, bortle = sky_brightness(r.place.lat, r.place.lon)
    sh = ev_mod.radiant_tonight(r.when_utc, r.tz, bortle)
    if sh is None:
        return None
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    alt, az = altaz(sh["ra"], sh["dec"], r.place.lat, lst)
    if alt <= 0:
        return None
    return dict(name=sh["name"], alt=alt, az=az)


def _running_now(r, visible_only=True):
    """Showers running tonight, for the group above the dated rows.

    Separate from _events_for on purpose: these are dated now, so mixing them
    into a chronological list puts them ahead of everything and costs the
    rows that list exists to show. See events.running_now.
    """
    p = r.place
    _mag, bortle = sky_brightness(p.lat, p.lon)
    return ev_mod.running_now(p.lat, p.lon, r.tz, now_utc=r.when_utc,
                              bortle=bortle, visible_only=visible_only)


def _days_away(e, now_utc):
    return (e["when_utc"] - now_utc).total_seconds() / 86400


def _when_words(e, r):
    """"tonight", "tomorrow night", or a weekday. People plan in those words,
    not in dates, and a shower peaking after midnight still belongs to the
    evening you have to go outside on."""
    watch = e.get("best_local") or e["when_local"]
    # A 03:00 peak is "tonight" to someone reading this at 22:00, so the night
    # an event belongs to starts at noon, not at midnight.
    night = (watch - dt.timedelta(hours=12)).date()
    today = (r.when_local - dt.timedelta(hours=12)).date()
    delta = (night - today).days
    if delta <= 0:
        return "tonight"
    if delta == 1:
        return "tomorrow night"
    if delta < 7:
        return f"on {watch:%A}"
    return f"on {watch:%a %d %b}"


def _event_teaser_text(e, r):
    """One sentence for a single event -- shared by events_teaser() (the
    single top event) and _event_card_from() (any event in events_cards()'s
    list, not necessarily the top-ranked one)."""
    when = _when_words(e, r)
    if e["kind"] == "meteor_shower":
        # "peak" is the wrong word for a shower merely running, and it used
        # to be written here regardless: the span event that says the
        # Perseids are up on 20 July came out as "Perseids peak tonight",
        # three weeks early and flatly wrong.
        #
        # And "Coming up" is the wrong tense for it too. A shower running
        # tonight is not coming up, it is on.
        if not e.get("at_peak", True):
            phase = e.get("phase", "ongoing")
            # No "tonight" in any of these -- the sentence already opens with
            # it, and "Tonight: Perseids start tonight" says it twice.
            lead = {"start": f"the {e['name']} start",
                    "end": f"last night of the {e['name']}",
                    }.get(phase, f"the {e['name']} are running")
            bits = [lead]
            if e.get("compass") and e.get("alt"):
                bits.append(f"radiant {e['alt']:.0f}° {e['compass']}")
            if e.get("moon_verdict"):
                bits.append(e["moon_verdict"])
            # No rate. See events.active_showers: zhr is the maximum under a
            # perfect sky, and this is not that night.
            out = "Tonight: " + ", ".join(bits) + "."
            if e.get("peak_utc") and phase != "end":
                pk = e["peak_utc"] + dt.timedelta(hours=r.tz)
                if pk.date() > r.when_local.date():
                    out += f" Best on {pk:%a %d %b}."
            return out
        bits = [f"{e['name']} peak {when}"]
        if e.get("zhr"):
            bits.append(f"up to {e['zhr']} an hour")
        if e.get("compass") and e.get("alt"):
            bits.append(f"radiant {e['alt']:.0f}° {e['compass']}")
        if e.get("moon_verdict"):
            bits.append(e["moon_verdict"])
        return "Coming up: " + ", ".join(bits) + "."
    if e["kind"] == "conjunction":
        a, b = e["bodies"]
        where = f", {e['alt']:.0f}° {e['compass']}" if e.get("compass") else ""
        return f"Coming up: {a} and {b} pass {e['sep_deg']}° apart {when}{where}."
    if e["kind"] == "eclipse":
        # headline, not name: name is the eclipse's global type ("Total solar
        # eclipse") and localise() rewrites headline to what *this* place
        # actually gets, which for almost everywhere is a partial.
        note = e.get("note", "")
        if note:
            note = " " + note[0].upper() + note[1:] + "."
        return f"Coming up: {e['headline'].lower()} {when}.{note}"
    if e["kind"] == "opposition":
        return (f"Coming up: {e['body']} at opposition {when}, "
                f"up all night, brightest of the year.")
    if e["kind"] == "elongation":
        return f"Coming up: {e['headline']} {when}, {e['note']}."
    return f"Coming up: {e['headline']} {when}."


def events_teaser(r):
    """One line for the bottom of a chart, or None if nothing is close.

    Absent most of the time on purpose. A line that is always there stops
    being read; a line that shows up only when the Perseids are two nights
    out is the reason someone comes back.
    """
    e = ev_mod.next_event(r.place.lat, r.place.lon, r.tz, now_utc=r.when_utc,
                          within_days=TEASER_DAYS)
    if e is None:
        return None
    return _event_teaser_text(e, r)


def _event_date(e):
    """The date to file an event under: the evening you go outside, not the
    instant it peaks.

    The 2026 Perseid maximum is 13 Aug 02:10 UT, so dating the row by the peak
    put it on Thursday the 13th while every almanac says the 12th. Both are
    describing the same night -- the peak falls in the small hours -- and the
    night is what a reader is planning around. Where there's a viewing window,
    _ics_span already works out which evening it starts on, so the list and
    the calendar entry agree by construction.
    """
    if e.get("window_local"):
        return _ics_span(e)[0]
    # Same rule without a window: a conjunction whose closest approach falls
    # at 08:05 is watched the evening before, and _event_url sends you to that
    # evening's chart. The row has to be dated the same, or the list says the
    # 16th while its own link opens the 15th.
    return e.get("best_local") or e["when_local"]


# ---------------------------------------------------------------- card payload
# Data for the prominent "Coming up" card on a place page. events_card()
# itself stays data-only (also served as "card" on /{place}/events?
# format=json and "coming_up_card" on /{place}?format=json) -- the actual
# markup is coming_up_card_html() below, rendered at the
# <!-- skymap:coming-up-card --> marker in PAGE.
#
# events_card() returns None on most nights, which is the point: the card is
# meant to mean something when it appears. See TEASER_HORIZON in events.py for
# how far ahead each kind of event earns a mention.

# Urgency buckets, for the UI to colour from. Anything sooner than the next
# threshold takes that bucket, so ordering matters.
CARD_URGENCY = (("tonight", 0.6), ("soon", 3.0), ("later", 999.0))


def _card_urgency(days_away):
    for name, cutoff in CARD_URGENCY:
        if days_away <= cutoff:
            return name
    return "later"


def _event_card_from(e, r):
    """A flat dict, ready to hand to a template, for one event -- shared by
    events_card() (the single top event) and events_cards() (any event in
    its ranked list). Everything the card might want is precomputed here
    rather than left as raw event fields, so the UI never has to reimplement
    the "which night does this belong to" or "is the Moon in the way"
    reasoning that the text views already do."""
    watch = e.get("best_local") or e["when_local"]
    days_away = (e["when_utc"] - r.when_utc).total_seconds() / 86400

    detail = []
    if e.get("window_local"):
        detail.append(dict(label="best", value=f"{e['window_local'][0]}–{e['window_local'][1]}"))
    if e.get("alt") is not None and e.get("compass"):
        detail.append(dict(label="where", value=f"{e['alt']:.0f}° {e['compass']}"))
    if e.get("zhr"):
        detail.append(dict(label="rate", value=f"up to {e['zhr']}/hr"))
    if e.get("sep_deg") is not None and e["kind"] == "conjunction":
        detail.append(dict(label="apart", value=f"{e['sep_deg']}°"))
    if e.get("mag") is not None:
        detail.append(dict(label="magnitude", value=f"{e['mag']}"))

    return dict(
        # Stable across renders and shared with the ICS UID and RSS GUID, so
        # the UI can key a dismissal on it and have it stay dismissed.
        id=e["id"],
        kind=e["kind"],
        glyph=e.get("glyph", "✦"),
        # "TOMORROW NIGHT", "TONIGHT", "ON FRIDAY" -- already phrased for the
        # eyebrow, uppercase left to CSS.
        eyebrow=_when_words(e, r),
        headline=e["headline"],
        # One sentence, the same wording the terminal views use.
        body=_event_teaser_text(e, r).replace("Coming up: ", ""),
        detail=detail,
        moon_verdict=e.get("moon_verdict"),
        note=e.get("note"),
        urgency=_card_urgency(days_away),
        days_away=round(days_away, 2),
        when_local=e["when_local"].isoformat(),
        watch_local=watch.isoformat(),
        window_local=e.get("window_local"),
        # Where the buttons go. cta opens the chart for the moment, framed on
        # the thing; more opens the full list.
        cta=dict(label="show me that sky", url=_event_url(e, r)),
        more=dict(label="everything coming up",
                  url=f"/{quote(r.place.slug)}/events"),
    )


def events_card(r):
    """The next thing worth a card on this place's page, or None."""
    e = ev_mod.next_event(r.place.lat, r.place.lon, r.tz, now_utc=r.when_utc,
                          within_days=TEASER_DAYS)
    return _event_card_from(e, r) if e is not None else None


def events_cards(r, n=3):
    """Up to n cards, most interesting first -- the coming-up card's
    cycling data source for the (rare, maybe ten nights a year) case where
    more than one thing is genuinely close, e.g. a partial eclipse and a
    meteor shower peak a day apart. [] on a quiet night, same as
    events_card() returning None."""
    evs = ev_mod.next_events(r.place.lat, r.place.lon, r.tz, now_utc=r.when_utc,
                             within_days=TEASER_DAYS, n=n)
    return [_event_card_from(e, r) for e in evs]


def coming_up_card_html(cards):
    """The homepage highlight at the <!-- skymap:coming-up-card --> marker
    in PAGE -- "" when cards is empty (most nights), which the marker's own
    placement in PAGE just renders as nothing.

    One line, deliberately tight: glyph, the same one-sentence body the CLI
    teaser uses (already reads as "<headline> <eyebrow phrase>, <facts>", so
    a separate headline would just repeat itself), a single CTA (straight to
    the framed chart -- "everything coming up" is one click away via the nav
    now anyway), and a dismiss button. Color rides entirely on --cu-accent,
    set per data-urgency in CSS -- retune the three hex values there, not
    here.

    cards can hold more than one (events_cards()'s ranked list, capped) for
    the rare night two things are both genuinely close -- a partial eclipse
    and a meteor shower peak a day apart, say. A "›" chevron cycles between
    them client-side, same pattern as the 3D sphere's radiant HUD
    (#radiant-hud-cycle): hidden entirely at one card, "1/2 ›" otherwise.
    cards[0] renders server-side so a no-JS visitor still sees the top one
    (just can't cycle or dismiss it -- both are inherently client-only
    state); the rest ride along as inline JSON for the cycle handler.

    Dismiss is real, not just decorative: keyed on each card's own id
    (stable across renders, shared with the ICS UID/RSS GUID) in
    localStorage, so dismissing "Perseids peak" doesn't come back on
    refresh, but a different event next week does, and dismissing it while
    cycled to it doesn't take a still-relevant eclipse with it. No server
    round-trip -- there's nothing here a signed-out visitor's browser can't
    remember on its own. The inline <script> right after the div (not
    PAGE's big shared one) is deliberate: it runs the instant it's parsed,
    before anything below it paints, so an already-dismissed top card is
    gone before it would otherwise flash on screen -- same reasoning as the
    .js-class script at the top of <head>."""
    if not cards:
        return ""
    first = cards[0]
    payload = json.dumps([
        dict(id=c["id"], glyph=c["glyph"], body=c["body"], urgency=c["urgency"],
             cta=c["cta"]) for c in cards
    ]).replace("</", "<\\/")   # a body/label can't smuggle a </script> close
    return (
        f'<div class="coming-up" id="coming-up" data-urgency="{html.escape(first["urgency"])}" '
        f'data-id="{html.escape(first["id"])}">'
        f'<span class="cu-glyph" id="cu-glyph" aria-hidden="true">{first["glyph"]}</span>'
        f'<span class="cu-body" id="cu-body">{html.escape(first["body"])}</span>'
        f'<a class="cu-cta" id="cu-cta" href="{html.escape(first["cta"]["url"])}">'
        f'{html.escape(first["cta"]["label"])}</a>'
        f'<span class="cu-cycle" id="cu-cycle" role="button" tabindex="0" hidden></span>'
        f'<button type="button" class="cu-dismiss" id="coming-up-dismiss" '
        f'aria-label="Dismiss">✕</button>'
        f'</div>'
        f'<script>(function(){{'
        f"var el=document.getElementById('coming-up');"
        f"if(!el)return;"
        f"var CARDS={payload};"
        f"var KEY='skymap-cu-dismissed';"
        f"var dismissed;"
        f"try{{dismissed=JSON.parse(localStorage.getItem(KEY)||'[]');}}catch(e){{dismissed=[];}}"
        f"CARDS=CARDS.filter(function(c){{return dismissed.indexOf(c.id)===-1;}});"
        f"if(!CARDS.length){{el.remove();return;}}"
        f"var idx=0;"
        f"var glyphEl=document.getElementById('cu-glyph');"
        f"var bodyEl=document.getElementById('cu-body');"
        f"var ctaEl=document.getElementById('cu-cta');"
        f"var cycleEl=document.getElementById('cu-cycle');"
        f"function render(){{"
        f"var c=CARDS[idx];"
        f"el.dataset.urgency=c.urgency;"
        f"el.dataset.id=c.id;"
        f"glyphEl.textContent=c.glyph;"
        f"bodyEl.textContent=c.body;"
        f"ctaEl.textContent=c.cta.label;"
        f"ctaEl.href=c.cta.url;"
        # Hidden at one card, same "a 1/1 that does nothing is worse than
        # no control" reasoning as the sphere's own chevron.
        f"cycleEl.hidden=CARDS.length<2;"
        f"cycleEl.textContent=(idx+1)+'/'+CARDS.length+' \\u203a';"
        f"}}"
        f"render();"
        f"cycleEl.addEventListener('click',function(){{"
        f"idx=(idx+1)%CARDS.length;"
        f"render();"
        f"}});"
        f"var btn=document.getElementById('coming-up-dismiss');"
        f"if(btn)btn.addEventListener('click',function(){{"
        f"dismissed.push(CARDS[idx].id);"
        f"try{{localStorage.setItem(KEY,JSON.stringify(dismissed));}}catch(e){{}}"
        f"CARDS.splice(idx,1);"
        f"if(!CARDS.length){{el.remove();return;}}"
        f"idx=idx%CARDS.length;"
        f"render();"
        f"}});"
        f'}})();</script>'
    )


def _event_tail(e):
    """Where to look and when, as the pieces that follow an event's headline.

    Its own function because two lists render it: the full one at
    /{place}/events (through _event_line below) and the short one on the day
    modal (_drawer_rows). Written once so the two cannot end up disagreeing
    about whether a shower says its rate or a conjunction says its altitude.
    """
    tail = []
    if e.get("alt") is not None and e.get("compass"):
        tail.append(f"{e['alt']:.0f}° {e['compass']}")
    if e.get("window_local"):
        tail.append(f"best {e['window_local'][0]}-{e['window_local'][1]}")
    if e.get("zhr"):
        tail.append(f"up to {e['zhr']}/hr")
    # sep_deg means two different things: how far apart a pair is (already in
    # the headline, so repeating it gave "Moon and Venus 1.9° apart ... 1.9°
    # apart") and how far an inner planet strays from the Sun, which the
    # headline doesn't say and which is the whole point of the event.
    if e["kind"] == "elongation" and e.get("sep_deg") is not None:
        tail.append(f"{e['sep_deg']}° from the Sun")
    return tail


def _event_line(e, r, when=None):
    """One event as a table row: when, glyph, what, and where to look.

    when overrides the date column. The running-shower group passes an empty
    one: those rows sit under a heading that already says "on now", and a
    shower is not a date -- printing today's under it read as a claim that
    the Perseids happen on the 8th.
    """
    if when is None:
        when = f"{_event_date(e):%a %d %b}"
    head = f"{e.get('glyph', ' ')} {e['headline']}"
    return f"  {when:<11} {head:<34} {', '.join(_event_tail(e))}".rstrip()


def _event_url(e, r):
    """Where this event opens, at the moment it is worth looking at.

    Not the event's own instant: a shower peaking at 04:10 wants the middle
    of its window, and anything with a best moment wants that.

    The thing itself, when the event is about a thing. An event names a
    body -- Perseids, Venus at opposition, the full Moon -- and that body
    has a page with its own chart, a crosshair already on it, its rise and
    set times and what it is. Sending a reader to a bare chart with a
    ?find= on it gave them the crosshair and none of the rest, on a page
    that was not about what they clicked.

    Eclipses go to their own page rather than to the Sun's or the Moon's,
    when it is one of the eclipses that page can compute.
    """
    when = e.get("best_local") or e["when_local"]
    stamp = f"?t={when:%Y-%m-%dT%H:%M}"
    place = quote(r.place.slug)

    if e["kind"] == "eclipse":
        key = _event_date(e).strftime("%Y-%m-%d")
        if eclipse_page.by_key(key):
            return f"/{place}/eclipse/{key}"

    target = _find_target_for(e)
    if target:
        return f"/{place}/{quote(target)}{stamp}"
    # Nothing to open a page for -- an equinox, a solstice. The chart for
    # that moment, pointed the right way if the event knows a direction.
    url = f"/{place}{stamp}"
    if e.get("compass"):
        url += f"&facing={e['compass']}"
    return url


def _find_target_for(e):
    """What ?find= should aim at for this event, or None.

    A conjunction names two bodies; the fainter one is the one you need help
    spotting, and framing it frames the pair anyway since they are within a
    couple of degrees by definition.
    """
    kind = e["kind"]
    if kind == "meteor_shower":
        return e["name"]                     # resolve_target knows radiants
    if kind in ("opposition", "elongation"):
        return e.get("body")
    if kind == "conjunction":
        bodies = e.get("bodies") or []
        return next((b for b in bodies if b != "Moon"), bodies[0] if bodies else None)
    if kind == "moon_phase":
        return "Moon"
    if kind == "eclipse":
        return "Moon" if "lunar" in e.get("eclipse_type", "") else "Sun"
    return None


def _event_rows(r, days, colour_free=False):
    """Every line of the events view, once, as structured rows.

    The text and HTML renderers both consume this, so the terminal list and
    the clickable browser list cannot drift apart -- the same reason api.py
    exists at all rather than the CLI and the server each composing their own.

    Each row is (style, text, url). url is None for anything that isn't an
    event you could open a chart for.
    """
    import textwrap
    p = r.place
    every = _events_for(r, days=days, visible_only=False)
    here = [e for e in every if e["visible"] is not False]
    not_here = [e for e in every if e["visible"] is False]

    rows = [("blank", "", None)]
    rows.append(("head",
                 f"  {p.name}  {abs(p.lat):.2f}°{'N' if p.lat >= 0 else 'S'} "
                 f"{abs(p.lon):.2f}°{'E' if p.lon >= 0 else 'W'}  ·  "
                 f"next {days} days  ·  local time", None))
    rows.append(("blank", "", None))

    # On now, above the dated rows. A shower is not a date -- the Perseids
    # run from 17 July to 24 August -- so it has no row in a list ordered by
    # when things happen, and without this the list said nothing about them
    # on any of the thirty-seven nights that are not the peak.
    #
    # Its own group rather than a row among them: dated "today" it would sort
    # to the top of the list every day and read as an event happening today,
    # which is not the same claim.
    running = _running_now(r)
    if running:
        rows.append(("mute", "  On now:", None))
        for e in running:
            rows.append(("now", _event_line(e, r, when=""), _event_url(e, r)))
            note = e.get("moon_verdict") or e.get("note")
            if note:
                for l in textwrap.wrap(note, 62):
                    rows.append(("mute", f"  {'':<11} {l}", None))
        rows.append(("blank", "", None))

    if not here:
        rows.append(("mute", "  Nothing above the horizon here in the next "
                             f"{days} days.", None))
    for e in here:
        rows.append(("event", _event_line(e, r), _event_url(e, r)))
        note = e.get("moon_verdict") or e.get("note")
        if note:
            for l in textwrap.wrap(note, 62):
                rows.append(("mute", f"  {'':<11} {l}", None))

    if not_here:
        rows.append(("blank", "", None))
        rows.append(("mute", "  Happening, but not from here:", None))
        for e in not_here:
            txt = (f"{_event_date(e):%a %d %b}  {e['headline']}: "
                   f"{e.get('reason', 'not visible')}")
            for i, l in enumerate(textwrap.wrap(txt, 74)):
                rows.append(("mute", ("  " if i == 0 else "  " + " " * 12) + l, None))

    rows.append(("blank", "", None))
    # Bare /events.ics defaults away from p (Zurich, or whoever's IP hits it
    # next) -- carrying the slug is what makes "subscribe" actually mean
    # "subscribe to events here" rather than "subscribe to events wherever
    # this URL happens to resolve to later."
    rows.append(("mute", f"  Subscribe: add /{p.slug}/events.ics to your "
                         f"calendar, or /{p.slug}/events.rss to a reader.", None))
    return rows, every


def events_html(r, days=EVENTS_WINDOW_DAYS):
    """Browser twin of the text list: every event opens the chart for the
    moment it happens.

    In the same tab. It used to open a new one, on the reasoning that the
    list should stay put -- but the list is a page you arrive at, look down,
    and leave from, not a workbench you keep open beside the sky. Every other
    link on the site navigates, back returns you to the list with the scroll
    position intact, and a tab per event is a tab the reader has to close.

    The row is wrapped whole, padding included, so the columns stay lined up
    inside <pre> exactly as they do in a terminal.
    """
    style = {"head": C.HEAD, "event": EVENT_COL, "now": NOW_COL,
             "mute": C.MUTE}
    rows, _ = _event_rows(r, days)
    out = []
    for kind, text, url in rows:
        if kind == "blank":
            out.append("")
            continue
        span = (f'<span style="color:{_ansi_hex(style[kind])}">'
                f"{html.escape(text)}</span>")
        if url:
            out.append(f'<a href="{html.escape(url)}" '
                       f'title="Open the sky for this moment">'
                       f"{span}</a>")
        else:
            out.append(span)
    out.append("")
    # The linked twin of _footer, for the events page. Same handle, and the
    # same Bluesky profile the header's icon row points at: the old one was
    # a personal account, which reads oddly under a sentence that now names
    # the project's.
    out.append(f'<span style="color:{_ansi_hex(C.MUTE)}">  Follow </span>'
               f'<a href="{brand.BLUESKY}" '
               f'target="_blank" rel="noopener">{brand.AT_HANDLE}</a>'
               f'<span style="color:{_ansi_hex(C.MUTE)}">'
               f' for {brand.SITE} updates</span>')
    return "\n".join(out)


# ------------------------------------------------------------- the day page
# How far ahead a solar eclipse claims the top of the panel. A week is long
# enough to travel for one, which is the only decision this page can help
# with, and short enough that the box is absent almost all the time -- which
# is what stops it becoming furniture people stop seeing.
DAY_ECLIPSE_LEAD_DAYS = 7

# How many events get a drawing in the panel. One: the column is 280px and
# already carries five rows of facts, and a second picture pushes the whole
# thing past the arc it is meant to sit beside. Raising it is one number.
DAY_PANEL_ARTS = 1

# How far ahead the panel asks for events. Two days, and then only tonight's
# are kept -- the two is so a conjunction at 02:00 tomorrow, which belongs to
# tonight, is in the answer at all.
#
# It was 14, which is what the box's own heading was wrong about. A reader on
# 8 August was shown "Perseids peak, Wed 12 Aug" and "Venus at greatest
# elongation east, Fri 14 Aug" under the word TONIGHT -- and both of those
# rows were already on the page, in the upcoming-events list directly under
# the arc. The deck was a second copy of that list with a heading that
# contradicted it.
#
# What is left is what the heading always claimed: tonight. On a night with
# nothing on it the deck falls through to the planets that are up and then
# to the brightest star, which it already did, so the box never empties.
DAY_PANEL_DAYS = 2


def _iso_hm(s):
    """"21:25" out of an ISO local timestamp, "" if there isn't one. The day
    view's times are already offset to local when they go into the payload,
    so there is no timezone arithmetic left to get wrong here."""
    return s[11:16] if s else ""


def _days_until(when_local, now_local):
    """Whole days between two local times, counted by calendar date.

    By date and not by elapsed hours, because "tomorrow" is a date and not
    24 hours: an eclipse at 09:00 tomorrow is tomorrow's eclipse even though
    it is fifteen hours away, and calling it "today" at 18:00 tonight would
    send somebody out with the wrong morning.
    """
    return (when_local.date() - now_local.date()).days


def _countdown(days):
    """"today", "tomorrow", "in 5 days"."""
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def _event_moment_utc(e, r):
    """When an event's drawing should be posed for, in UTC.

    An event carries local wall clocks. A planet's axis barely moves in a
    day, so this only has to be near enough -- but "near enough" is not the
    same as "whatever moment the page was requested at", and an event a
    fortnight out is a fortnight of drift."""
    when = e.get("best_local") or e.get("when_local") or r.when_local
    return when - dt.timedelta(hours=r.tz)


def _pole_kw(name, when_utc):
    """{pole_b, pole_pa} for a body at a moment, or {} if it has no axis on
    file.

    planet_art has taken these since it was written -- "pole_b and pole_pa
    come from objects.pole_geometry" is in its own docstring -- and every
    caller left them at the defaults, which are `pole_b=26, pole_pa=90`: a
    planet tipped a quarter turn onto its side.

    On a bare disc that costs nothing, which is why it went unnoticed. On
    Saturn it is the whole picture. A ring lies in the equatorial plane, so
    its long axis runs 90 degrees from the pole, and a pole at position
    angle 90 puts the rings *vertical* -- Saturn came out as a ball inside
    an upright hoop, which is not a thing anybody has ever seen through a
    telescope.

    With the real numbers each planet gets its own axis: Saturn's rings are
    nearly edge-on in 2026 and lie flat, and Uranus -- tipped 98 degrees, so
    we are looking almost straight down its pole -- gets the wide open ring
    circle that is the whole reason its picture is worth drawing.
    """
    jd = sky.julian(when_utc)
    if name == "Moon":
        b = sky.moon(jd)
    elif name == "Sun":
        b = sky.sun(jd)
    elif name in sky.PLANETS:
        b = sky.planet(name, jd)
    else:
        return {}
    g = objects.pole_geometry(name, b)
    if g is None:
        return {}
    return {"pole_b": g[0], "pole_pa": g[1]}


def _moon_art_for(illum, waning, when_utc):
    """The Moon at a given illumination, or [] for a new one.

    A new Moon drawn honestly is a black disc, which is a picture of nothing
    -- correct, and useless in a panel whose job is to give somebody a reason
    to go outside. So it draws nothing and the next candidate gets the slot.
    """
    if illum is None or illum < 0.02:
        return []
    return art.planet_art("Moon", illuminated=illum, lit_from_left=waning,
                          scale=DAY_PLANET_SCALE, **_pole_kw("Moon", when_utc))


def _eclipse_facts(e, r):
    """The solved local circumstances for an eclipse event, or None.

    The event's own fields come out of the global scan, which answers "could
    anyone here see any of this" with a coarse test and stops. The eclipse
    page solves the real geometry for this exact spot. Where the two
    disagree, the page is right -- so anything on this page that talks about
    an eclipse asks the page, and the drawing and the sentence beside it
    come from one source.
    """
    key = _event_date(e).strftime("%Y-%m-%d")
    entry = eclipse_page.by_key(key)
    if not entry:
        return None
    try:
        return eclipse_page.facts(entry, r.place, r.when_utc)
    except Exception:
        return None


def _event_headline(e, r):
    """What to call an event in a caption.

    Everything but an eclipse says the same thing everywhere and uses its
    own headline. An eclipse does not: the scan called 12 Aug 2026 a
    "Partial solar eclipse here" from Ibiza, which gets 71 seconds of
    totality, because the scan's visibility test cannot tell the middle of
    the path from the edge of it. The drawing beside the caption was already
    right, having come from the solver, so the caption was the odd one out.
    """
    if e["kind"] == "eclipse":
        f = _eclipse_facts(e, r)
        if f:
            return eclipse_page.headline(f)
    return e["headline"]


def _event_art(e, r):
    """The drawing for one event, or [].

    Every branch hands off to the same function the object or eclipse page
    for that thing uses, so the small picture in the panel and the big one
    behind the link are the same drawing of the same moment.
    """
    kind = e["kind"]
    if kind == "eclipse":
        key = _event_date(e).strftime("%Y-%m-%d")
        if "lunar" in (e.get("eclipse_type") or ""):
            return eclipse_map.moon_art(key)
        # Solar: drawn for here, not in general. The whole content of a
        # partial eclipse is how much of the Sun this place loses.
        return eclipse_map.disc_art(key, r.place.lat, r.place.lon)
    if kind == "meteor_shower":
        return art.shower_art(e["name"])
    if kind == "moon_phase":
        # illum is already a percentage in the event; art wants a fraction.
        # "Last quarter" is the waning one, which is which side is lit.
        return _moon_art_for((e.get("illum") or 0) / 100.0,
                             "last" in e["name"].lower(),
                             _event_moment_utc(e, r))
    target = _find_target_for(e)
    if target and art.has_art(target):
        return art.planet_art(target, illuminated=art.STYLE_ILLUMINATED,
                              scale=DAY_PLANET_SCALE,
                              **_pole_kw(target, _event_moment_utc(e, r)))
    return []


def _brightest_star_tonight(r, when_local):
    """The brightest named star above the horizon at a given local time.

    The last resort, and it earns the cost it carries: this walks the star
    catalogue rather than reading a payload, which is why it is reached only
    when there is no event worth drawing and no planet up either. In practice
    that is a nearly empty branch -- but "nearly" is not "never", and a panel
    with a hole in it is worse than one that took two milliseconds longer.
    """
    when_utc = when_local - dt.timedelta(hours=r.tz)
    jd = julian(when_utc)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    best = None
    for s in sky._load("stars.json"):
        if not s.get("n") or s["m"] > 2.0:
            continue
        ra, de = sky.precess(s["ra"], s["de"], jd)
        alt, _az = altaz(ra, de, r.place.lat, lst)
        if alt <= 10:                 # low enough to be in the trees
            continue
        if best is None or s["m"] < best["m"]:
            best = s
    return best


# How much of the deck's frame a planet is allowed to fill. Every drawing in
# the deck sits in the same DAY_ART_ROWS-tall box, and a planet drawn at full
# size touches all four sides of it while a meteor shower next to it leaves a
# row of margin all round. Side by side that read as two different sizes of
# picture rather than as two objects. 0.86 gives the planet the same margin
# the others have. On its own object page a planet still gets the full box --
# there it is the subject, not one card in a deck.
DAY_PLANET_SCALE = 0.86

# Every drawing in the panel is set in a box this many rows tall, whatever
# it actually draws. The drawings do not agree on height and cannot be made
# to: a bright star is 9 rows, a meteor shower 15, a planet 17, and a solar
# eclipse is 12 rows from Zurich and 15 from Madrid because the disc is
# drawn where the Sun is, not where a layout would like it.
#
# Left alone, the box was a different height on every page and a different
# height for the same eclipse seen from two towns, which moved everything
# under it and decided on its own whether the page fitted on a screen. So
# the trimmed drawing is centred in a fixed frame instead: same box every
# time, and the picture sits in the middle of it rather than hanging from
# the top. 17 is the tallest thing that goes in it.
DAY_ART_ROWS = 17


def _slice_visible(line, a, b):
    """Visible columns a..b of a line, colours intact.

    Counted in visible characters rather than in string positions, because a
    row of art is a run of escape sequences with characters between them and
    slicing the string would cut one in half and paint the rest of the page
    orange."""
    out, seen, i = [], 0, 0
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            out.append(m.group(0)); i = m.end(); continue
        if a <= seen < b:
            out.append(line[i])
        seen += 1
        i += 1
    return "".join(out)


BRAILLE_CELL = re.compile(r"[⠀-⣿]")


def _mixes_braille(text):
    """True when a drawing is drawn in braille *and* in ordinary characters."""
    braille = other = False
    for ch in text:
        if ch.isspace():
            continue
        if "⠀" <= ch <= "⣿":
            braille = True
        else:
            other = True
        if braille and other:
            return True
    return False


def _art_ink_trim(lines):
    """Every line cut to the drawing's own leftmost and rightmost ink.

    .art-frame centres the <pre>, and the <pre> is as wide as its widest line
    -- so what gets centred is the canvas, not the picture on it. Cutting to
    the ink makes those the same thing.

    The old rule here took the same count off each side, on the reasoning that
    a symmetric cut keeps a disc in the middle. True, but only for a drawing
    whose ink was already centred on its canvas, which is every planet (they
    are padded both sides) and not the ones built by art._emit, which strips
    each row's trailing spaces and keeps its leading ones. M31 was drawn 11
    columns in from the left and flush with the ink on the right, so the plate
    centred a box with 11 blank columns down one edge and put Andromeda five
    and a half cells right of the middle.
    """
    vis = [strip_ansi(l) for l in lines]
    inked = [v for v in vis if v.strip()]
    if not inked:
        return list(lines)
    a = min(len(v) - len(v.lstrip(" ")) for v in inked)
    b = max(len(v.rstrip(" ")) for v in inked)
    return [_slice_visible(l, a, b) for l in lines]


def _pin_braille(markup, text):
    """Wrap braille cells so CSS can hold them to one character width.

    Only on a drawing that mixes them with ordinary characters. A plate that
    is all braille -- every asterism, every shower, the Galaxy -- comes out
    uniformly wider and keeps its own grid, which is why this went unnoticed
    for so long; it is left alone and pays nothing. A plate that mixes shears
    instead. The fallback font's cell is 1.135 times as wide, so every braille
    cell pushes the rest of its row right, and on a deep-sky cluster that
    reached 1.35 cells of drift between the mesh and the stars it links.

    A span per cell rather than per run. A run in a fixed-width box would sit
    in the right place and still space its own cells wrongly inside it, which
    is the same bug one level down. Only the mixed plates pay for it, and what
    they pay is the same short string over and over, which is what gzip is
    for.
    """
    if not _mixes_braille(text):
        return markup
    return BRAILLE_CELL.sub(lambda m: f'<span class="br">{m.group()}</span>',
                            markup)


def art_plate(lines, frame_cls="", plate_cls="", style="", centre_ink=False):
    """A drawing centred in a plate. Everywhere characters become a picture.

    The object pages had this first and the modal frames grew their own copy
    of it, which is two places to get art.CELL wrong. One component now: the
    frame centres the block both ways, the plate pins the line height the
    drawing is built for and refuses to wrap, and each caller adds only what
    is different about its own -- a border and a minimum height on an object
    page, a type size in frame-widths in the modal.

    Centring the block and never the line. With white-space:pre each line is
    its own line box, so text-align:center would centre every line by its own
    width and shear the drawing apart down the middle.

    centre_ink cuts the blank columns off both sides, so what the frame
    centres is the drawing rather than the canvas it was drawn on. The object
    pages ask for it: a portrait is alone in its frame and belongs in the
    middle of it. The modal frames do not, because they sit in a row and would
    rather agree with each other than each be centred -- see _art_block, which
    trims by the smaller margin for that reason.
    """
    frame = f"art-frame {frame_cls}".strip()
    plate = f"art-plate {plate_cls}".strip()
    text = chr(10).join(_art_ink_trim(lines) if centre_ink else lines)
    body = _pin_braille(ansi_to_html(text), strip_ansi(text))
    return (f'<div class="{frame}">'
            f'<pre class="{plate}"{style} aria-hidden="true">{body}</pre>'
            f'</div>')


# How tall a drawing is allowed to be, as a fraction of the frame it sits in.
# A 45-column canvas 14 rows deep comes out at 0.74 of its own width, which
# is what every frame looked like before any of this, so nothing that was
# already filling its box changes size. It is only the cap that stops a
# narrow drawing -- Neptune is 19 columns of a 45-column canvas -- from
# growing until it is taller than the modal.
ART_HEIGHT_FRAC = 0.74
# A monospace "0" in this stack measures 0.602em. The extra is what keeps a
# rounding error from clipping the last column of Saturn's rings.
ART_ADVANCE_EM = 0.612
# Braille is not in any font we bundle, so the browser falls back to one that
# has it and those cells come out wider -- 10.938px against 9.633 when this
# was measured for the quadrant grid, which is 1.135 times. A shower is drawn
# in braille and its widest row was running four pixels out of the frame,
# because counting characters counted every cell as the narrow kind.
BRAILLE_ADVANCE_EM = ART_ADVANCE_EM * 1.135


def _art_em_width(line, pinned=False):
    """How wide a row of art is, in em, counting braille as the wider cell.

    Unless the plate is one of the mixed ones, where _pin_braille has held
    every braille cell to a single character width and the wide cell is no
    longer what the browser draws. The measurement has to agree with the
    rendering or the sizing it feeds is answering about a different picture.
    """
    if pinned:
        return len(line) * ART_ADVANCE_EM
    return sum(BRAILLE_ADVANCE_EM if "\u2800" <= c <= "\u28ff"
               else ART_ADVANCE_EM for c in line)


def _art_block(lines, caption, url, cls="dt-art", rows=DAY_ART_ROWS):
    """A drawing, its caption and the link they both sit inside.

    Blank rows come off and then go back on evenly, top and bottom. Both
    halves matter: eclipse.disc_art always returns 17 rows with the disc
    wherever the geometry puts it, so trimming is what stops five dead rows
    sitting between a picture and its caption, and padding is what stops the
    box changing height from one town to the next.

    Blank *columns* come off too, and only symmetrically. art.py draws every
    body on the same 45-column canvas, so a bare planet is about twenty
    columns of picture with thirteen of margin either side -- and since the
    type is sized to fit the canvas rather than the drawing, Neptune came out
    less than half the size its frame could hold. Taking the same number off
    each side is what keeps the disc in the middle while the box closes in
    around it.

    The type size goes on the element, because only here is the drawing's own
    width known. It is in cqw -- hundredths of the frame -- so the art fits
    whatever the frame turns out to be, and the second term is the height cap
    that stops a narrow drawing growing past ART_HEIGHT_FRAC of its box.
    """
    body = list(lines)
    while body and not strip_ansi(body[0]).strip():
        body.pop(0)
    while body and not strip_ansi(body[-1]).strip():
        body.pop()
    inked = [strip_ansi(l) for l in body if strip_ansi(l).strip()]
    cols = 0
    if inked:
        canvas = max(len(l) for l in inked)
        left = min(len(l) - len(l.lstrip(" ")) for l in inked)
        right = canvas - max(len(l.rstrip(" ")) for l in inked)
        cut = max(0, min(left, right))
        # Trailing spaces are invisible but not free: they widen the <pre>
        # past its own ink, and .art-frame centres the <pre>. A shower whose
        # rows ended in a dozen spaces sat that far left of the middle.
        #
        # The smaller of the two margins on purpose, so a drawing that is not
        # centred on its own canvas keeps the offset it had. The object pages
        # ask art_plate for the other rule -- see centre_ink there -- because
        # a portrait is alone in its frame and wants to be in the middle of
        # it, where these sit in a row and want to agree with each other.
        body = [_slice_visible(l, cut, len(strip_ansi(l).rstrip()) or cut)
                for l in body]
        pinned = _mixes_braille(strip_ansi("\n".join(body)))
        cols = max((_art_em_width(strip_ansi(l), pinned) for l in body),
                   default=0)
    if body and rows and len(body) < rows:
        pad = rows - len(body)
        body = [""] * (pad // 2) + body + [""] * (pad - pad // 2)
    size = ""
    if cols and body:
        # cols is already in em (see _art_em_width), not in characters.
        wide = 100.0 / cols
        tall = ART_HEIGHT_FRAC * 100.0 / (len(body) * 1.2)
        size = f' style="font-size:min({wide:.3f}cqw,{tall:.3f}cqw)"'
    # art-fill is the modifier: it takes the slack over the caption, so the
    # drawing has something to be centred in. Without it the caption's
    # margin-top:auto swallowed every spare pixel and the picture sat pinned
    # to the ceiling of its frame.
    pre = art_plate(body, frame_cls="art-fill", plate_cls=cls, style=size)
    cap = f'<span class="dt-cap">{html.escape(caption)}</span>'
    if not url:
        return f'<div class="dt-art-box">{pre}{cap}</div>'
    return (f'<a class="dt-art-box" href="{html.escape(url)}">{pre}{cap}</a>')


# The summary line's own left margin, as it arrives from _compose_day: two
# spaces, matching the indent every prose line in the composed text carries.
# In a box of its own that is wrong twice over -- the spaces are set at the
# box's font size while the chart beside them is at CHART_FONT_PX, so they
# are not even the same distance as the drawing's own gutter, and the line
# ended up further right than both the title above it and the 70° below it.
#
# Taken off here and put back as padding in CSS, which is the same trade
# strip_prose_indent already makes for the paragraph under a chart, and for
# the same reason: a margin made of characters cannot line up with anything
# set in a different size.
#
# Anchored at the start of the line, which is all it can match because
# lift_chart_head hands it exactly one line. The spaces can land either side
# of the colour span ansi_to_html opens -- which side depends on whether the
# composed line was painted before or after it was indented -- so both are
# taken, and the span itself is kept.
_LEAD_SPACE = re.compile(r'^ *((?:<span[^>]*>)?) *')


# Which way to look, in the two shapes the headline has for it: hung off one
# of the Sun's three moments (rise, peak, set), or hung off a height on
# either line -- the Moon's, a planet's, a named star's, the Sun's own.
#
# Both are anchored to what owns them, a time or a number of degrees, rather
# than matched loose. A bare run of NSEW letters appears inside ordinary
# words ("SSE" does not, but "S" and "E" do), and a rule that matched those
# would set a letter of somebody's prose in a different size.
_HEAD_BEARING = re.compile(r'([↑↓^]\d{2}:\d{2}) ([NSEW]{1,3})\b')
_HEAD_WHERE = re.compile(r'(\d+°) (up|down) ([NSEW]{1,3})\b')
# The Moon with nothing to report. Same treatment as the "up SSW" it stands
# in for -- it answers the same question, so it should not be the one thing
# on the line set louder than the rest.
_HEAD_DOWN = re.compile(r'(\d+%) (down)\b')
# The glyph that labels one of the Sun's own moments, as opposed to the one
# that opens the block saying where the Sun is now -- that one is followed
# by a space and a number, and keeps its full size and its own colour.
_HEAD_SUNMARK = re.compile(r'☀(?=[↑↓^]\d{2}:\d{2})')
# Which way your shadow falls. Same shape as the rest: the number is the
# fact, the letters are the direction.
_HEAD_SHADOW = re.compile(r'(shadows [^ ]+) ([NSEW]{1,3})\b')


def dim_directions(head_html):
    """Set every "which way to look" on the line smaller and greyer than the
    fact it belongs to.

    The fact you act on is the time or the height: when to set an alarm, how
    far up to look. The direction is the detail that says which window to
    stand at. Same line, two weights, so the line can be read at a glance
    for the first and still carries the second.

    Browser only, and after the line is HTML, for the reason pin_near gives:
    every width decision is made on the text, and the text is what a
    terminal and a PNG still get. A smaller font does break the monospace
    grid the rest of the line sits on, which is the trade -- it is spent
    only on these tails, never on a number that has to line up with the
    block above or below it.
    """
    if not head_html:
        return head_html
    out = _HEAD_BEARING.sub(r'\1 <span class="dir">\2</span>', head_html)
    out = _HEAD_WHERE.sub(r'\1 <span class="dir">\2 \3</span>', out)
    out = _HEAD_DOWN.sub(r'\1 <span class="dir">\2</span>', out)
    out = _HEAD_SHADOW.sub(r'\1 <span class="dir">\2</span>', out)
    return _HEAD_SUNMARK.sub('<span class="dir">☀</span>', out)


def pin_near(head_html, near):
    """Swap the "near X" hint for a map pin carrying it as a tooltip.

    Browser only, and after the line is HTML rather than before, on purpose.
    The hint is the longest thing on the line that can never be dropped --
    it is the only thing identifying a bare pair of coordinates, so a trim
    is not allowed to take it -- and "near Lausanne, Vaud, Switzerland" is
    32 characters spent before the headline has said anything about the sky.

    Doing it here rather than in _head_prefix keeps the arithmetic honest:
    every width decision on this line is made on the text, and the text is
    what a terminal and a PNG still get. Only the page trades the words for
    a pin, and only the page has somewhere to put them back.

    The prefix is painted as one colour run, so the hint is a contiguous
    stretch of one span and a plain replace cannot land in the middle of
    markup. A <span> inside a <span> is fine; nothing has to be reopened.

    U+2691 and not the map-pin emoji. The emoji is a text character too, but
    it is rendered from the system's colour-emoji font -- so it arrived in
    colour, as the only picture on a page made of characters, and at an
    advance that is not the monospace cell. This one is in the site's own
    font, measures exactly one cell, and takes the line's colour like every
    other glyph on it.
    """
    if not near or not head_html:
        return head_html
    words = f" \u00b7 near {html.escape(near)}"
    if words not in head_html:
        return head_html
    pin = (f'<span class="pin" tabindex="0" role="img" '
           f'aria-label="near {html.escape(near)}" '
           f'title="near {html.escape(near)}">\u2691</span>')
    return head_html.replace(words, " " + pin)


def lift_chart_head(rungs, near=None):
    """Take the summary line out of the drawing, into a ladder of its own.

    Returns (head_html, rungs) with the line gone from every rung.

    It is not one line but one per rung: the summary drops pieces to fit the
    width it is given, and there are twelve widths in the page. So the box
    gets the same show-one-rung-at-a-time treatment the chart gets, keyed to
    its own width -- which is the full page rather than the chart column, so
    it usually shows a longer version of the line than the chart beneath it
    would have carried. That is the point of moving it: the sentence about
    where and when you are stops being rationed by how wide the picture is.

    The rungs come in as (cols, panel, html); the html is a rendered block
    whose first non-blank line is the summary, put there by _compose_day.
    """
    heads, rest = [], []
    for cols, panel, body in rungs:
        lines = body.split("\n")
        cut = next((i for i, l in enumerate(lines) if l.strip()), None)
        if cut is None:
            heads.append("")
            rest.append((cols, panel, body))
            continue
        heads.append(_LEAD_SPACE.sub(r"\1", lines[cut]))
        # The blank line under it goes too: it was the gap between the
        # sentence and the drawing, and the drawing now starts the box.
        tail = lines[cut + 1:]
        while tail and not tail[0].strip():
            tail.pop(0)
        rest.append((cols, panel, "\n".join(tail)))
    if not any(heads):
        return "", rungs
    spans = "".join(f'<span class="dh">{h}</span>' for h in heads)
    # An empty box beside the ladder for the animation to write into. The
    # ladder cannot be reused: its twelve rungs are shown and hidden by
    # container queries on :nth-child, so a single replacement line would be
    # displayed at one width and hidden at every other. The live box is one
    # element with no query on it, and html.anim-on swaps which of the two
    # is on screen -- so the headline goes on saying where and when through
    # an animation instead of sitting frozen at the moment the page loaded.
    #
    # data-near carries the "near X" hint to the script, which has to make
    # the same swap for a pin that pin_near makes here (see skymapPinNear).
    # Handed over rather than parsed out of the line: this is the server's
    # own r.place.near, already escaped, and finding where the name ends by
    # looking at the text would be a guess.
    nr = f' data-near="{html.escape(near)}"' if near else ""
    return (f'<header id="day-head" class="day-box" aria-label="where and when">'
            f'<div id="day-head-ladder">{spans}</div>'
            f'<div id="day-head-live" aria-live="off"{nr}></div></header>'), rest


def chart_page(head_html, chart_html, drawer_html=""):
    """The whole page: a line saying where and when, then the chart.

    Day and night alike. The day page used to be a different shape -- the
    Sun's arc in a narrow column with a panel of tonight beside it and a list
    of events beneath -- and the chart paid for all of it in width and rows.
    Now that both views share one axis and one set of pieces, there is no
    reason for two layouts, and the chart is the thing worth the room.

    Everything the panel and the list carried moves into the drawer, which
    slides up over the chart rather than displacing it: the chart is sized to
    the window, so anything that reflows it rescales it.
    """
    return (head_html
            + f'<section id="night-chart" class="day-box" '
              f'aria-label="the sky above you now">'
              f'<h2 class="box-head">the sky above you now</h2>{chart_html}'
              f'</section>' + drawer_html)


# Kept under its old name for the object pages, which call it directly.
night_layout = chart_page


def _drawer_split(r):
    """(today, tonight) -- the two lists the drawer shows and counts.

    Today is what happens while the Sun is still up: in practice a solar
    eclipse, which is the one thing on the list somebody could walk outside
    and watch this afternoon. Tonight is the rest -- what is running now, and
    what this coming night holds.

    Split because the page is about that split, and because "2 today, 3
    tonight" answers a different question from "5 things": the first number
    is about the next few hours and the second is about whether to set an
    alarm.
    """
    tonight_night = _night_of(r.when_local)
    today, tonight = [], []
    for e in _events_for(r, days=EVENTS_WINDOW_DAYS, visible_only=True):
        night = _night_of(_event_date(e))
        if night != tonight_night:
            continue
        # Daylight events are today's; everything else belongs to the night.
        when = e.get("best_local") or e["when_local"]
        (today if is_daytime(r.at(when - dt.timedelta(hours=r.tz)))
         else tonight).append(e)
    tonight = _running_now(r) + tonight
    return today, tonight


def drawer_badge(today, tonight):
    """The closed drawer's one line. Empty when there is nothing at all, so
    a quiet night gets a quiet page rather than a "0 tonight"."""
    bits = []
    if today:
        bits.append(f"{len(today)} today")
    if tonight:
        bits.append(f"{len(tonight)} tonight")
    return ", ".join(bits)


def _drawer_rows(evs, r):
    out = []
    for e in evs:
        when = "" if not e.get("at_peak", True) else f"{_event_date(e):%a %d %b}"
        # No date means it is running now rather than happening on a day, and
        # the row says so in green -- the same distinction the terminal list
        # draws with NOW_COL.
        cls = "nu-row" if when else "nu-row nu-now"
        out.append(
            f'<a class="{cls}" href="{html.escape(_event_url(e, r))}">'
            f'<span class="nu-when">{html.escape(when or "on now")}</span>'
            f'<span class="nu-glyph">{html.escape(e.get("glyph", "·"))}</span>'
            f'<span class="nu-what">{html.escape(e["headline"])}</span>'
            f'<span class="nu-where">{html.escape(", ".join(_event_tail(e)))}</span>'
            f'</a>')
    return "".join(out)


# How much of a find each body is, rarest first. Not brightness: Venus is the
# brightest thing up and also the one nobody needs telling about, where
# Mercury is the planet people go years without ever catching. Uranus and
# Neptune need optics, so they sit behind the naked-eye ones a reader could
# actually walk outside and find.
BODY_RARITY = ("Mercury", "Mars", "Saturn", "Jupiter", "Uranus", "Neptune",
               "Venus", "Moon")


def _bodies_up(data):
    """The bodies up tonight, most worth a trip first.

    Two sources because the two views carry different payloads: the day page
    knows what *will* be up (visible_tonight, computed for first dark) and
    the night page knows what *is* (bodies, the ones actually above the
    horizon now). Reading only the first meant the night page found nothing
    and the modal came out empty on exactly the quiet nights this is for.
    """
    up = list(data.get("visible_tonight") or
              [b["name"] for b in (data.get("bodies") or []) if b.get("name")])
    up = [n for n in up if art.has_art(n)]
    return sorted(up, key=lambda n: (BODY_RARITY.index(n)
                                     if n in BODY_RARITY else 99))


def _frame(inner):
    return f'<div class="mf-frame">{inner}</div>'


def _body_tile(r, name, scale):
    lines = art.planet_art(name, illuminated=art.STYLE_ILLUMINATED, scale=scale,
                           **_pole_kw(name, r.when_utc))
    when = _chart_link_when(r)
    url = f"/{quote(r.place.slug)}/{quote(name)}{when}"
    return _art_block(lines, name, url, cls="mf-art", rows=MODAL_TILE_ROWS)


# No padding to a fixed row count. It was 14, to hold the frames' height
# steady whatever went in them -- but they are grid siblings and already
# stretch to each other, so the row count was buying nothing and costing the
# thing it looked like it was helping. The blank rows go inside the <pre>,
# and the <pre> is what gets centred, so a drawing 13 rows deep in a 14-row
# box sat half a row high and its bottom row ran into the caption. Trimmed to
# its own ink and centred as itself, it has the same space above as below.
MODAL_ART_ROWS = 0
# The cells draw the *same* art as the big frame and set it smaller, rather
# than asking planet_art for a smaller drawing. A scaled-down disc is not a
# smaller picture of Saturn, it is a picture of fewer characters: the rings
# go first, and what is left is a blob that could be any planet. Same
# characters, smaller type, and the shape survives -- which is the whole
# reason these are drawings and not names.
MODAL_TILE_SCALE = DAY_PLANET_SCALE
MODAL_TILE_ROWS = MODAL_ART_ROWS


def _modal_frames(r, data):
    """The two bordered frames at the top of the modal.

    Always two, and always in this order:

      eclipse today   -> the eclipse, then the best thing tonight
      no eclipse      -> the best thing tonight, then the second best
      only one event  -> that event, then a grid of what is up
      nothing at all  -> the rarest body up, large, then a grid of four more

    An eclipse takes the first frame whatever else is on, because it is the
    one thing on the list that happens in daylight and the one a reader could
    walk outside and watch this afternoon.
    """
    today, tonight = _drawer_split(r)
    ecl = next((e for e in today if e["kind"] == "eclipse"), None)
    rest = [e for e in today + tonight if e is not ecl]
    rest.sort(key=lambda e: -ev_mod._interest(e))
    picks = ([ecl] if ecl else []) + rest

    frames = []
    for e in picks:
        if len(frames) == 2:
            break
        lines = _event_art(e, r)
        if not lines:
            continue
        frames.append(_frame(_art_block(lines, _event_headline(e, r),
                                        _event_url(e, r), cls="mf-art",
                                        rows=MODAL_ART_ROWS)))

    up = _bodies_up(data)
    if not frames and up:
        # Nothing on at all. The rarest thing up gets the big frame -- on an
        # empty night that is the answer to "is it worth going out".
        frames.append(_frame(_art_block(
            art.planet_art(up[0], illuminated=art.STYLE_ILLUMINATED,
                           scale=DAY_PLANET_SCALE,
                           **_pole_kw(up[0], r.when_utc)),
            f"{up[0]}, up tonight",
            f"/{quote(r.place.slug)}/{quote(up[0])}{_chart_link_when(r)}",
            cls="mf-art", rows=MODAL_ART_ROWS)))
        up = up[1:]
    if len(frames) == 1 and up:
        # Four small frames rather than four drawings loose in one big one.
        # Loose, each tile sat in a fifth of the box it was given and the
        # rest was dead space; a frame each gives every body the same border
        # the events get and fills the same footprint.
        tiles = "".join(f'<div class="mf-frame mf-cell">'
                        f'{_body_tile(r, n, MODAL_TILE_SCALE)}</div>'
                        for n in up[:4])
        frames.append(f'<div class="mf-quad">{tiles}</div>')
    return "".join(frames)


def sky_pill_html(r, data):
    """(pill, modal) -- what is on, as a chip beside the search bar.

    It lived under the chart first, as a drawer docked above the shortcut
    bar. That was still competing with the chart for the one thing the chart
    needs, which is height: room had to be reserved for its closed tab, and
    the reserved room came off the drawing. Beside the bar it costs nothing,
    and the chart is the only thing on the page.

    One drawing, not a carousel. The deck cycled six of them on a timer,
    which is a lot of movement beside a chart that is itself the point, and
    every drawing in it was already a link to a page carrying the same
    picture bigger.

    Both halves are empty on a quiet night. A pill reading "0 tonight" is a
    notification about nothing.
    """
    today, tonight = _drawer_split(r)
    badge = drawer_badge(today, tonight)
    frames = _modal_frames(r, data)
    if not badge and not frames:
        return "", ""
    # Nothing on is not nothing to say. "Events: 0" is a notification about
    # an absence; a quiet night is a fact about the sky, and the frames
    # behind it still answer "is it worth going out" with whatever is up.
    label = f"Events: {badge}" if badge else "A lovely night"
    body = f'<div class="mf-row">{frames}</div>' if frames else ""
    if today:
        body += f'<h3 class="dw-head">today</h3>{_drawer_rows(today, r)}'
    if tonight:
        body += f'<h3 class="dw-head">tonight</h3>{_drawer_rows(tonight, r)}'
    body += (f'<a class="nu-more" href="/{quote(r.place.slug)}/events">'
             f'everything coming up &rarr;</a>')
    # Labelled, not just counted. "2 today, 1 tonight" beside a search bar
    # is a number without a noun -- two of what?
    pill = (f'<button type="button" class="barpill" id="on-pill" '
            f'aria-expanded="false" aria-controls="on-modal">'
            f'{html.escape(label)}</button>')
    # A title, so the close button has a row of its own to sit at the end of
    # rather than floating over the first frame's top corner.
    modal = (f'<div id="on-modal" class="modal" hidden>'
             f'<div class="modal-card" role="dialog" aria-modal="true" '
             f'aria-labelledby="on-title">'
             f'<div class="modal-bar">'
             f'<h2 class="modal-title" id="on-title">Events today and tonight</h2>'
             f'<button type="button" class="modal-close" id="on-close" '
             f'aria-label="Close">✕</button></div>{body}</div></div>')
    return pill, modal


def _compose_events(r, next_only=False, days=EVENTS_WINDOW_DAYS):
    """The full list for /{place}/events.

    Events nobody here can see are kept, at the bottom, rather than dropped:
    "the Geminids peak on the 14th but the radiant never rises here" is worth
    saying out loud, and silently omitting it just looks like a gap.
    """
    p, c = r.place, r.color

    if next_only:
        # One line, nothing else, for a shell prompt or a MOTD. Empty output
        # and exit 0 when there is nothing, so it composes into scripts.
        line = events_teaser(r)
        return Result((line.replace("Coming up: ", "") + "\n") if line else "",
                      dict(place=p.name, next=line))

    rows, every = _event_rows(r, days)
    style = {"head": C.HEAD, "event": EVENT_COL, "now": NOW_COL,
             "mute": C.MUTE}
    out = ["" if kind == "blank" else paint(text, style[kind], c)
           for kind, text, _url in rows]
    out += ["", _footer(p, c), ""]

    data = dict(place=p.name, lat=p.lat, lon=p.lon, tz_offset=r.tz,
                when_utc=r.when_utc.isoformat() + "Z", window_days=days,
                card=events_card(r),
                upcoming=[_event_json(e) for e in every])
    return Result("\n".join(out), data)


def _event_json(e):
    """One event as plain JSON. Datetimes become ISO strings; everything else
    is already a string, number or list."""
    out = {}
    for k, v in e.items():
        out[k] = v.isoformat() if isinstance(v, dt.datetime) else v
    return out


# ---------------------------------------------------------------- feeds
def _ics_escape(s):
    return (s.replace("\\", "\\\\").replace(";", r"\;")
             .replace(",", r"\,").replace("\n", r"\n"))


def _ics_fold(line):
    """RFC 5545 caps a content line at 75 octets and continues with a leading
    space. Calendar clients genuinely reject over-long lines, so this is not
    optional politeness."""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > 73:
            out.append(chunk.decode("utf-8"))
            chunk = b" " + b
        else:
            chunk += b
    out.append(chunk.decode("utf-8"))
    return "\r\n".join(out)


def events_ics(r, base_url="https://skymap.sh", days=EVENTS_WINDOW_DAYS):
    """An iCalendar feed. This is what "subscribe" means to most people: it
    lands in the calendar app they already look at, at the right local time."""
    p = r.place
    L = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//skymap.sh//events//EN", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", f"X-WR-CALNAME:Sky events: {p.name}",
         "X-WR-CALDESC:What's coming up in the sky above "
         f"{p.name}, from skymap.sh"]
    for e in _events_for(r, days=days, visible_only=True):
        start, end = _ics_span(e)
        # Floating local time (no Z, no TZID): the event is quoted in the
        # place's own clock, and a floating time shows at that wall-clock
        # reading whatever timezone the reader's device is in. Someone
        # subscribed to Tokyo's feed wants Tokyo's hours.
        L += ["BEGIN:VEVENT",
              f"UID:{e['id']}@skymap.sh",
              f"DTSTAMP:{r.when_utc:%Y%m%dT%H%M%S}Z",
              f"DTSTART:{start:%Y%m%dT%H%M%S}",
              f"DTEND:{end:%Y%m%dT%H%M%S}",
              f"SUMMARY:{_ics_escape(_ics_summary(e))}",
              f"DESCRIPTION:{_ics_escape(_ics_description(e, p, base_url))}",
              f"URL:{base_url}/{quote(p.slug)}/events",
              "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in L) + "\r\n"


def object_best_ics(r, canonical, facts, base_url="https://skymap.sh"):
    """One calendar entry for this object's best night of the year.

    A date on a page is a thing to forget. The same date in a calendar is a
    thing that happens. Reuses the escaping and folding the events feed
    already does, so a reader who subscribes to both gets consistent
    entries.
    """
    b = facts.get("best_this_year")
    if not b:
        return None
    p = r.place
    # The calendar day is whichever day the viewing hour falls on. For a
    # night that runs past midnight those differ, and the entry belongs on
    # the day somebody would actually be outside.
    day = (dt.datetime.fromisoformat(b["at"]).date() if b.get("at")
           else dt.date.fromisoformat(b["date"]))
    peak = bool(b.get("is_peak"))

    # A timed window where we know the hour, an all-day entry where we do
    # not. The good hours run past midnight, so the entry starts at the best
    # moment and runs two hours, rather than claiming a whole calendar day
    # that is mostly daylight.
    at = b.get("at")
    timed = bool(at)
    if timed:
        start_dt = dt.datetime.fromisoformat(at)
        end_dt = start_dt + dt.timedelta(hours=2)
    else:
        start = day
        end = day + dt.timedelta(days=1)
    if peak:
        summary = f"{canonical} peak"
        detail = (f"The {canonical} peak tonight."
                  + (f" Radiant {b['radiant_alt']:.0f} degrees up at midnight."
                     if b.get("radiant_alt") is not None else "")
                  + (f" Up to {b['zhr']} an hour at best." if b.get("zhr") else ""))
    else:
        summary = f"{canonical}: best night of the year"
        detail = (f"{canonical} is best placed tonight from {p.name}: "
                  f"{b['transit_alt']:.0f} degrees up"
                  + (f", {b['dark_hours']:.1f} hours of darkness"
                     if b.get("dark_hours") else "")
                  + f", moon {b['moon_illum']:.0%} lit.")
    url = f"{base_url}/{quote(canonical)}"
    uid = f"best-{_norm_uid(canonical)}-{day:%Y%m%d}@skymap.sh"
    L = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//skymap.sh//object//EN", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH",
         "BEGIN:VEVENT",
         f"UID:{uid}",
         f"DTSTAMP:{r.when_utc:%Y%m%dT%H%M%S}Z",
         # Floating local time, no Z and no TZID -- the same choice the
         # events feed makes. The hour is quoted in the place's own clock,
         # and a floating time shows at that wall reading wherever the
         # reader's device happens to be.
         (f"DTSTART:{start_dt:%Y%m%dT%H%M%S}" if timed
          else f"DTSTART;VALUE=DATE:{start:%Y%m%d}"),
         (f"DTEND:{end_dt:%Y%m%dT%H%M%S}" if timed
          else f"DTEND;VALUE=DATE:{end:%Y%m%d}"),
         f"SUMMARY:{_ics_escape(summary)}",
         f"DESCRIPTION:{_ics_escape(detail + ' ' + url)}",
         f"URL:{url}",
         "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_ics_fold(x) for x in L) + "\r\n"


def _norm_uid(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _ics_span(e):
    """(start, end) for a calendar entry.

    Where there's a viewing window, the entry covers it: a reminder that fires
    when the Perseid radiant is *highest* goes off at 04:50, by which point
    you have missed most of the night. The window start is when to go outside.
    Windows that run past midnight are already absolute datetimes, so an end
    before the start just means the run crossed into the next day.
    """
    win = e.get("window_local")
    best = e.get("best_local") or e["when_local"]
    if not win:
        return best, best + dt.timedelta(hours=1)
    day = best.date()
    start = dt.datetime.combine(day, dt.time.fromisoformat(win[0]))
    end = dt.datetime.combine(day, dt.time.fromisoformat(win[1]))
    # The window is quoted as two wall-clock times; if the second is earlier
    # it belongs to the following morning.
    if end <= start:
        end += dt.timedelta(days=1)
    # best_local sits inside the window by construction, so if the clock
    # times put it outside, the whole run belongs to the previous evening.
    if best < start:
        start -= dt.timedelta(days=1)
        end -= dt.timedelta(days=1)
    return start, end


def _ics_summary(e):
    s = e["headline"]
    if e.get("alt") is not None and e.get("compass"):
        s += f", {e['alt']:.0f}° {e['compass']}"
    return s


def _ics_description(e, p, base_url):
    bits = []
    if e.get("window_local"):
        bits.append(f"Best {e['window_local'][0]}–{e['window_local'][1]} local.")
    if e.get("moon_verdict"):
        bits.append(e["moon_verdict"][0].upper() + e["moon_verdict"][1:] + ".")
    if e.get("note"):
        bits.append(e["note"][0].upper() + e["note"][1:] + ".")
    when = e.get("best_local") or e["when_local"]
    bits.append(f"{base_url}/{quote(p.slug)}?t={when:%Y-%m-%dT%H:%M}")
    return " ".join(bits)


def events_rss(r, base_url="https://skymap.sh", days=EVENTS_WINDOW_DAYS):
    """RSS 2.0. The one thing that has to be right is the guid: keyed on the
    event, never on render time, or every reader re-flags every item on every
    poll."""
    p = r.place
    esc = html.escape
    items = []
    for e in _events_for(r, days=days, visible_only=True):
        when = e.get("best_local") or e["when_local"]
        link = f"{base_url}/{quote(p.slug)}?t={when:%Y-%m-%dT%H:%M}"
        desc = _ics_description(e, p, base_url)
        # RFC 822 date, in the place's own offset rather than pretending UTC.
        off = f"{'+' if r.tz >= 0 else '-'}{int(abs(r.tz)):02d}{int(abs(r.tz) % 1 * 60):02d}"
        items.append(
            "<item>"
            f"<title>{esc(_ics_summary(e))}</title>"
            f"<link>{esc(link)}</link>"
            f"<guid isPermaLink=\"false\">{esc(e['id'])}</guid>"
            f"<pubDate>{when:%a, %d %b %Y %H:%M:%S} {off}</pubDate>"
            f"<description>{esc(desc)}</description>"
            "</item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>'
            f"<title>Sky events: {esc(p.name)}</title>"
            f"<link>{esc(base_url)}/{quote(p.slug)}/events</link>"
            f"<description>What's coming up in the sky above {esc(p.name)}."
            "</description>"
            f"<language>en</language>{''.join(items)}"
            "</channel></rss>")


# ---------------------------------------------------------------- animation
_SUN_GRADIENT = ["\033[38;5;220m", "\033[38;5;214m", "\033[38;5;208m",
                 "\033[38;5;202m", "\033[38;5;196m"]   # yellow -> red


def _sun_color(alt):
    """Yellow high in the sky, stepping through orange to red near the
    horizon -- real atmospheric reddening (the same reason real sunsets look
    like this), computed fresh from altitude each frame so it naturally
    reverses on the way back up. Standard xterm-256 palette, same as every
    other colour in the app -- a first version used true 24-bit colour for a
    smoother gradient, but that silently fails to plain white on terminals
    without full truecolour support, which is worse than a few visible steps."""
    if alt >= 25:
        return _SUN_GRADIENT[0]
    if alt <= -12:
        return _SUN_GRADIENT[-1]
    t = 1 - max(0.0, min(1.0, (alt + 12) / 37.0))   # 25 -> 0, -12 -> 1
    return _SUN_GRADIENT[round(t * (len(_SUN_GRADIENT) - 1))]


# Below the horizon, where _SUN_GRADIENT has nothing left to say: blue at
# the horizon, desaturating to grey by CIVIL_ALT. It is the blue hour
# and then the end of it, which is what the sky over your head actually
# does, and it lands the block on a grey that is already the line's own
# colour just as the block is about to go.
_SUN_DOWN_GRADIENT = ["\033[38;5;75m", "\033[38;5;68m", "\033[38;5;67m",
                      "\033[38;5;103m", "\033[38;5;244m"]   # blue -> grey


def _sun_head_color(alt):
    """The headline glyph's colour: the chart's own reddening ramp while the
    Sun is up, the blue hour fading to grey once it is down.

    Shares _sun_color above the horizon on purpose -- the marker on the
    chart and the glyph on the line are the same Sun, and two ramps that
    drift apart would put a yellow glyph over a red marker."""
    if alt >= 0:
        return _sun_color(alt)
    t = max(0.0, min(1.0, alt / CIVIL_ALT))          # 0 -> 0, -6 -> 1
    return _SUN_DOWN_GRADIENT[round(t * (len(_SUN_DOWN_GRADIENT) - 1))]


def paint_sun_glyph(painted, alt, restore, c):
    """Colour the ☀ on an already-painted headline, and hand the line back
    to the colour it was in.

    After painting rather than inside the composer, for the reason pin_near
    gives: every width decision on this line is made on the text, and an
    escape sequence in the middle of it would be counted as characters by
    the trim. `restore` is the run's own colour, not C.OFF -- a reset here
    would strip the rest of the line back to the terminal's default."""
    glyph = "\N{BLACK SUN WITH RAYS}"
    if not c or glyph not in painted:
        return painted
    # Only the block that says where the Sun is *now*, which is the one the
    # colour is about. The sunset block carries the same glyph as a label
    # (`☀↓20:30`), and colouring that one by the current altitude would say
    # something untrue about a time hours away -- so this anchors on the
    # space and digit that only the position block has.
    return re.sub(glyph + r"(?= \d)",
                  _sun_head_color(alt) + glyph + restore, painted, count=1)


def compose_frame(r, dusk_lead_minutes=0, dawn_lag_minutes=0):
    """Header + chart only, no prose/footer/ISS/zenith inset -- for animation
    frames, which are on screen for a fraction of a second and can't be read
    as text anyway.

    One unified render for both day and night rather than switching between
    two differently-shaped views: stars and planets fade in smoothly as the
    sky actually darkens (mag_limit ramps from -5 at sunset to 4.0 by
    astronomical twilight, the same threshold band dark_enough() already uses
    for single-object visibility), and the Sun's own marker is always drawn,
    reddening as it approaches the horizon. No hard cut at sunrise/sunset --
    the transition is the same real physics the rest of the app already
    models, just shown continuously instead of as a single before/after.

    dusk_lead_minutes and dawn_lag_minutes each nudge, purely for the star/
    constellation fade threshold below, which moment's Sun altitude gets
    used -- the Sun marker itself always tracks its real position. A tiny
    epsilon sample tells whether the Sun is currently setting or rising:
    while setting, dusk_lead_minutes samples *ahead*, so the fade reads as
    darker than the moment actually is and the night sky starts showing a
    few frames early; while rising, dawn_lag_minutes samples *behind*, so
    the fade reads as darker than the moment actually is right through
    dawn too, and the stars last longer instead of cutting off early."""
    p, c = r.place, r.color
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    su = sun(jd)
    sun_alt, sun_az = altaz(su["ra"], su["dec"], p.lat, lst)

    fade_minutes = 0
    if dusk_lead_minutes or dawn_lag_minutes:
        eps_jd = julian(r.when_utc + dt.timedelta(minutes=1))
        eps_lst = (gmst_hours(eps_jd) + p.lon / 15.0) % 24
        eps_su = sun(eps_jd)
        eps_alt, _ = altaz(eps_su["ra"], eps_su["dec"], p.lat, eps_lst)
        setting = eps_alt < sun_alt
        fade_minutes = dusk_lead_minutes if setting else -dawn_lag_minutes

    if fade_minutes:
        fade_jd = julian(r.when_utc + dt.timedelta(minutes=fade_minutes))
        fade_lst = (gmst_hours(fade_jd) + p.lon / 15.0) % 24
        fade_su = sun(fade_jd)
        fade_alt, _ = altaz(fade_su["ra"], fade_su["dec"], p.lat, fade_lst)
    else:
        fade_alt = sun_alt

    mag_limit = _fade_mag_limit(fade_alt)
    # Moon/planets use the real sun_alt, not fade_alt -- the dusk/dawn lead
    # was tuned by eye for the star field fading in a few frames early, a
    # subtle effect. Applying that same shift to the Moon meant it could
    # appear up to ~75 minutes before actual sunset, in plain daylight --
    # a much more jarring error for one big, clearly labelled object than
    # for background stars.
    visible_bodies = _fade_visible_bodies(sun_alt, jd)

    off = p.offset(r.when_utc)
    day0_local = r.when_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day0 = day0_local - dt.timedelta(hours=off)
    arc = sun_arc(day0, p.lat, p.lon, step_min=DAY_BUCKET)
    # The same cap the night chart uses, so both have the same axis and a
    # reader moving between them is not silently rescaled. It used to be the
    # Sun's own peak plus 8, which meant the arc always fitted and the Sun
    # could never reach the inset -- the box was empty by construction rather
    # than because nothing was overhead. Above the cap the arc and the Sun
    # both go into the inset now (see render_linear's overlay block).
    alt_hi = DAY_ALT_HI_FLOOR

    # Below the horizon the Sun overlay disappears entirely, trail included --
    # otherwise the trail (coloured once, for the whole arc, by the *current*
    # frame's altitude) keeps showing as a lingering red line long after the
    # Sun has actually set, rather than genuinely vanishing.
    overlay = (arc, _sun_color(sun_alt), "SUN", (sun_alt, sun_az)) if sun_alt >= 0 else None
    # line_limit ties constellation lines/names to the same fading threshold as
    # the stars (see mag_limit above) -- they pop in/out star-by-star through
    # twilight instead of snapping on/off at a fixed show_lines boolean.
    # fade_alt, matching mag_limit above rather than the true sun_alt: the
    # unlit field and the lit one have to agree about which frame they are
    # in, or a star lights up a few frames before the sketch admits it is
    # there.
    # Per frame, so the radiant travels with the sky it belongs to. Cheap by
    # construction -- see events.radiant_tonight, which is why this is not
    # the same call the still chart makes.
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                             mag_limit=mag_limit, line_limit=mag_limit, tle=None,
                             dim_limit=_dim_limit(fade_alt),
                             radiant=_chart_radiant(r),
                             side_panel=r.panel, alt_lo=0.0, alt_hi=alt_hi,
                             width=_effective_width(r), height=_horizon_height(r),
                             overlay=overlay, bodies=visible_bodies,
                             # A frame ignored ?dso= entirely, so asking an
                             # animation for deep sky changed nothing at all
                             # -- byte-identical output. The paused-frame "d"
                             # in the browser refetches a single frame with
                             # it on, and that needs somewhere to land.
                             dso_limit=DSO_LIMIT if r.dso else None,
                             # Labels as links, on request only. A frame is
                             # normally plain text: every label an anchor,
                             # 144 times a run, is markup nobody can click
                             # while it is moving. The page asks for it on
                             # the frame it has paused on, which is the only
                             # frame anybody can reach -- see r.links.
                             link=_chart_link(r) if r.links else None,
                             # An animation is the one place the band is
                             # worth the most: it appears as the sky darkens
                             # and goes again at dawn, which is exactly the
                             # thing a still chart cannot show.
                             milkyway=_milkyway_floor_now(p.lat, p.lon, sun_alt))

    # Which stage of twilight this frame is in, which is the one thing an
    # animation's header is for -- it is the same chart every frame and the
    # light is what changes. Past astronomical twilight there is no stage
    # left to name, so it says nothing rather than "horizon panorama": the
    # night frames are the default view and the default needs no caption.
    if sun_alt >= -1:      mode = _sun_path_mode(r)
    elif sun_alt >= -6:    mode = "civil twilight"
    elif sun_alt >= -12:   mode = "nautical twilight"
    elif sun_alt >= -18:   mode = "astronomical twilight"
    else:                  mode = ""

    head = _export_head(r, st, mode)
    # The frame's own header. The glyph tracks the real Sun either way, so
    # the colour crosses the horizon over the length of the animation.
    #
    # Where it goes depends on who is watching. A terminal and a GIF have
    # nowhere else to put it, so it stays two rows above the drawing, which
    # is what it has always done. The page has a headline box of its own and
    # a still line already sitting in it -- so the frame hands its header
    # over separately and the box shows this one instead, rather than the
    # page carrying two headers that disagree about the time.
    #
    # Two colour runs on the page, one in a terminal: the place and the
    # moment arrive as their own span, which is the only way CSS can bold
    # part of a line that reaches the browser as pre-rendered ANSI. Same
    # trade the still page makes, for the same reason.
    if r.panel:
        pre = _head_prefix(r)
        painted = paint(pre, C.HEAD, c) + paint(head[len(pre):], C.LABEL, c)
        body = (paint_sun_glyph(painted, sun_alt, C.LABEL, c)
                + HEAD_SLOT + art)
    else:
        body = (paint_sun_glyph(paint(head, C.HEAD, c), sun_alt, C.HEAD, c)
                + "\n\n" + art)
    # The inset travels with the frame rather than being dropped.
    #
    # side_panel takes it out of `art` and hands it back through st, which is
    # what the browser wants -- the page floats it over the chart's corner
    # instead of stacking it underneath, so it costs no rows. But a frame is
    # one string, and until now compose_frame simply discarded st's copy: the
    # terminal got an inset inline and the browser silently got none at all.
    #
    # Through the same ZENITH_SLOT the still page uses, so the two are one
    # mechanism. skymapAnimShow splits on it and updates #chart-zenith, which
    # also stops the inset sitting there stale at the page's own moment while
    # the chart runs through the night.
    # No newline after the marker: the inset's first row follows it directly,
    # so the JS side is a plain split with nothing to trim. It had a strip
    # there and the regex was written /^\n/ inside a Python string, where the
    # \n is a real newline -- the literal ran across two lines, the script
    # died on it, and every button on the page stopped working.
    if r.panel and st.get("zenith_lines"):
        body += "\n" + ZENITH_SLOT + "\n".join(st["zenith_lines"])
    return body, sun_alt


def _find_chart_only(r):
    """The PNG export's version of ?find= -- same resolve/visibility/
    next-window logic _compose_find uses for the prose page, minus the
    header and explanatory text, so a shared link (page + its own "Share as
    a PNG") draws the same crosshair. Returns None if the name doesn't
    resolve, so the caller falls back to the plain chart instead of a blank
    image -- compose_chart_only used to skip this entirely, so ?find= was
    silently dropped from every PNG regardless of whether it resolved."""
    p, c = r.place, r.color
    jd = julian(r.when_utc); lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    tgt = resolve_target(r.find, jd, p.lat, lst)
    if tgt is None:
        return None
    ok, _why = visibility(tgt, jd, p.lat, lst)
    shown_utc = r.when_utc
    if not ok:
        w, _a2, _z2 = next_visible_cached(tgt, p.lat, p.lon, r.when_utc)
        if w is not None:
            shown_utc = w
            jd = julian(shown_utc); lst = (gmst_hours(jd) + p.lon / 15.0) % 24
            tgt = resolve_target(r.find, jd, p.lat, lst)
    # Same full-panorama-by-default framing as _compose_find, so a page and
    # the PNG it links to never disagree about what the chart shows.
    zoomed = r.span is not None
    if zoomed:
        rng = 26.0
        lo = max(0.0, min(90.0 - rng, tgt["alt"] - rng / 2))
        extra = dict(span=r.span, alt_lo=lo, alt_hi=lo + rng, width=r.width,
                     mag_limit=5.0)
    else:
        jd_shown = julian(shown_utc)
        sun_alt = altaz(*[sun(jd_shown)[k] for k in ("ra", "dec")],
                        p.lat, (gmst_hours(jd_shown) + p.lon / 15.0) % 24)[0]
        # line_limit and bodies as well as mag_limit -- the same three
        # _compose_sky passes. mag_limit alone fades the star field but not
        # the constellation lines drawn through it, nor the planets, which
        # nothing ever noticed because find in daylight always ended at "not
        # visible" rather than at a chart. ?find=Sun reaches it now, and a
        # partial eclipse an hour before sunset was drawing Lyra, the
        # Northern Cross and three planets into a bright sky.
        extra = dict(span=360.0, height=_png_export_height(r),
                     width=_png_export_width(r),
                     mag_limit=_fade_mag_limit(sun_alt),
                     line_limit=_fade_mag_limit(sun_alt),
                     bodies=_fade_visible_bodies(sun_alt, jd_shown) | {"Sun", "Moon"})
    sp = extra["span"]
    # The inset is on here as everywhere. It used to be off across the whole
    # export, on the reasoning that a PNG is "just the chart" -- but the cap
    # of sky above the panorama is part of the chart, and leaving it out gave
    # the shared picture less than the page it was shared from.
    art, _st = render_linear(shown_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                             tle=r.tle, target=tgt, **extra)
    shown_local = shown_utc + dt.timedelta(hours=p.offset(shown_utc))
    where = f"{int(sp)}° window" if zoomed else "full panorama"
    head = (f"  {p.name}   {shown_local:%d %b %Y %H:%M}   "
            f"finding {tgt['name']}, {where}")
    return paint(head, C.HEAD, c) + "\n\n" + art


def _export_head(r, st, mode):
    """The header a picture carries: the same one-row summary the browser
    puts above its chart.

    Shared because it has now drifted twice. The still export and the
    animation frames are two renders on purpose -- an animation ramps the
    magnitude limit so stars fade in as the sky darkens, which a still has
    no need for -- but the line above the chart is one idea, and each time
    it changed only one of them learned about it. The Milky Way band was
    left off the still; the summary was left off the frames, so a shared GIF
    carried the old two-part CLI header while the page it came from carried
    the Moon, the planets, the twilight state and the Bortle estimate.

    "horizon panorama" is dropped on the plain view for the reason the
    browser drops it: the axis is labelled 0-70 down the left edge and says
    so already. A facing window or a quadrant crop is not obvious from
    looking, so those keep their label.
    """
    if not r.facing and not r.quadrant_requested:
        mode = ""
    # The summary needs the Sun's altitude to say how dark it is, and an
    # animation frame does not always ask the renderer to draw the Sun --
    # so its stats can come back without one. Computed here rather than
    # taken on trust, which also means this cannot break again the next
    # time a caller changes which bodies it draws. Copied, not mutated: the
    # caller's stats are its own.
    # The Sun's altitude decides how dark the summary says it is, and the
    # Moon's decides whether it says "below the horizon" -- but a frame only
    # asks the renderer for the bodies it is actually drawing, so at midday
    # there is no Moon in its stats and at night no Sun. Filled in here from
    # the ephemeris rather than taken on trust, so this cannot break again
    # the next time a caller changes which bodies it draws.
    #
    # Copied, never mutated: the caller's stats belong to the caller, and
    # compose_frame is called once per animation frame.
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    fixed = {}
    for key, ephem in (("sun", sun), ("moon", sky.moon)):
        have = st.get(key) or {}
        if "alt" not in have:
            real = ephem(jd)
            alt, az = altaz(real["ra"], real["dec"], r.place.lat, lst)
            fixed[key] = dict(real, **have, alt=alt, az=az)
    if fixed:
        st = dict(st, **fixed)
    # The same staging the page's own line uses, so a frame's header and the
    # headline above it are one sentence rather than two that agree by
    # accident. It matters most here: a frame is one moment of an animation
    # running through a whole day, and the blocks arriving and leaving one
    # at a time is the thing being animated.
    #
    # The day view is composed elsewhere, so this only ever sees a Sun under
    # the horizon -- but _head_day_blocks is written from the events and the
    # altitude rather than from which composer called it, so it answers for
    # a frame at noon as readily as one at midnight.
    p = r.place
    st_alt, st_az = st["sun"]["alt"], st["sun"].get("az")
    day0 = _day0(r)
    ev = sun_events_cached(day0, p.lat, p.lon)
    # The golden window costs a second pass over the day, so it is only
    # asked for while the Sun is up -- which is also the only time the
    # block it feeds can appear.
    bands = sky.sun_bands(day0, p.lat, p.lon, ev) if st_alt > 0 else None
    day_blocks = _head_day_blocks(ev, p, p.offset(r.when_utc), r.when_utc,
                                  st_alt, st_az, bands)
    # A picture is untrimmed (10_000): the browser trims per rung because
    # twelve of them share one page width, but a picture has no rung and
    # should carry what the widest view carries.
    #
    # A browser frame does have a width, and it is the headline box's rather
    # than the chart's -- the same sum the still page does, so the line a
    # frame writes into that box is trimmed exactly like the line it
    # replaces. Untrimmed it overran the box on any window narrower than the
    # widest rung, which is most of them.
    if r.panel:
        room = int(_effective_width(r) * CHART_FONT_PX / DAY_HEAD_PX)
        width = max(20, room - len(_head_prefix(r)) - 3 -
                    (len(mode) + 3 if mode else 0))
    else:
        width = 10_000
    summary = _sky_summary(st, p.lat, width,
                           note=sky_note(p.lat, p.lon),
                           day_blocks=day_blocks)
    return _horizon_head(r, mode, summary=summary)


def compose_chart_only(r):
    """Just the horizon chart itself -- no header, prose or footer -- for the
    PNG and GIF exports. Same day/night and facing logic as
    _compose_sky/_compose_day, minus everything that isn't the chart, so the
    export matches whatever the static view above it is actually showing.

    The zenith inset is part of the chart and is drawn here too. It was off
    across the whole export on the reasoning that a PNG is "just the chart",
    which left the shared picture showing less sky than the page it came
    from -- and made this the one view of the four with a different idea of
    where the chart stops."""
    p, c = r.place, r.color
    if r.find:
        found = _find_chart_only(r)
        if found is not None:
            return found
    if not r.night and is_daytime(r):
        off = p.offset(r.when_utc)
        day0_local = r.when_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day0 = day0_local - dt.timedelta(hours=off)
        arc = sun_arc(day0, p.lat, p.lon, step_min=DAY_BUCKET)
        # The same cap the night chart uses, so both have the same axis and a
        # reader moving between them is not silently rescaled. It used to be the
        # Sun's own peak plus 8, which meant the arc always fitted and the Sun
        # could never reach the inset -- the box was empty by construction rather
        # than because nothing was overhead. Above the cap the arc and the Sun
        # both go into the inset now (see render_linear's overlay block).
        alt_hi = DAY_ALT_HI_FLOOR
        jd_now = julian(r.when_utc)
        lst_now = (gmst_hours(jd_now) + p.lon / 15.0) % 24
        su_now = sun(jd_now)
        sa_now, sz_now = altaz(su_now["ra"], su_now["dec"], p.lat, lst_now)
        mo_now = moon(jd_now)
        show = {"Moon"} if mo_now["illum"] > 0.4 or _near_sun(jd_now) else set()
        art, _st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=False,
                                 mag_limit=_fade_mag_limit(sa_now), alt_lo=0.0, alt_hi=alt_hi,
                                 overlay=(arc, SUN_COL, "SUN", (sa_now, sz_now)),
                                 bodies=show, width=_png_export_width(r),
                                 height=_png_export_height(r))
        head = _horizon_head(r, _sun_path_mode(r))
        return paint(head, C.HEAD, c) + "\n\n" + art
    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    su = sun(jd)
    sun_alt, _ = altaz(su["ra"], su["dec"], p.lat, lst)
    mag_limit = _fade_mag_limit(sun_alt)
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                            tle=r.tle, facing=r.facing, span=r.span,
                            width=r.width if r.facing else _png_export_width(r),
                            height=None if r.facing else _png_export_height(r),
                            mag_limit=mag_limit, line_limit=mag_limit,
                            # Same "Sun"+"Moon" forcing as _compose_sky above,
                            # for consistency -- this path doesn't call
                            # sky_read() so it can't hit the KeyError, but
                            # without "Moon" here the PNG export would still
                            # silently drop the Moon glyph the main view kept.
                            bodies=_fade_visible_bodies(sun_alt, jd) | {"Sun", "Moon"},
                            dso_limit=DSO_LIMIT if r.dso else None, quadrant=r.quadrant,
                            quadrants=r.quadrant_requested,
                            # The PNG is the shareable artefact, so it is the
                            # last place the band should be missing -- and it
                            # is a separate render from _compose_sky's, which
                            # is exactly how it got left off.
                            milkyway=_milkyway_floor_now(p.lat, p.lon, sun_alt))
    # The same one-row summary the browser puts above the chart -- Moon,
    # planets, how dark it is, the Bortle estimate, the star count. The
    # export used to carry the CLI's two-part header instead, so the
    # picture someone shared said less than the page they took it from,
    # and said it differently.
    #
    # Built the same way _compose_sky builds it, and with "horizon panorama"
    # gone for the same reason: it named the default, and the default is
    # already labelled by the drawing. Only what the picture cannot say for
    # itself is left.
    bits = []
    if r.facing:
        bits.append(f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
                    f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}"
                    f", true shape")
    if st.get("quad_applied"):
        bits.append(f"quadrant {st['quad_applied']}")
    mode = ", ".join(bits)
    head = _export_head(r, st, mode)
    return paint(head, C.HEAD, c) + "\n\n" + art


def compose(r):
    """Daylight wins. facing and disc used to slip past this check and draw stars
    at midday, which is just wrong — if the Sun is up there is nothing to see, so
    the Sun's path is the answer whatever framing was asked for. --night / ?night=1
    overrides, and find still works because it answers "when will I see this"."""
    if r.find:
        return _compose_find(r)
    if not r.night and is_daytime(r):
        return _compose_day(r)
    return _compose_sky(r)


# ---------------------------------------------------------------- help
HELP = """\
skymap.sh: the night sky above you, as text

  curl skymap.sh                      your sky now, located by IP
  curl skymap.sh/Zurich               a named city
  curl skymap.sh/47.38,8.54           any coordinates

If the ISS has a real pass overhead right now, it's marked on the chart
automatically -- no flag needed.

VIEWS
  ?view=horizon    panorama, N-E-S-W-N, altitude 0-70° + zenith inset (default)
  ?facing=NW       140° window centred on a bearing, shapes undistorted
  ?span=90         window width, 90-344° (only with facing)

FIND
  ?find=Venus      frame one object, with directions in fists
  ?find=M31        planets, Sun, Moon, named stars, asterisms, deep-sky
                   objects (M31, Andromeda Galaxy...), or a meteor shower's
                   radiant (Perseids) -- and whether you can see it right
                   now, or when you next can
  ?find=X&span=90  crop to a window around it instead of the full sky

EVENTS -- meteor showers, eclipses, oppositions, conjunctions, elongations
  curl skymap.sh/Zurich/events            what's coming up, next 90 days
  curl skymap.sh/Zurich/events?next=1     one line, for a shell prompt
  curl skymap.sh/Zurich/events?days=30    a different window, 7-365
                                           .ics and .rss feeds too, for a
                                           calendar app or a feed reader

OPTIONS
  ?t=2026-08-12T23:00   local time at that place (default: now)
  ?night=1              force the star chart even while the Sun is up
  ?nolines=1            stars only, no asterism lines
  ?dso=1                overlay galaxies, nebulae and clusters to mag 11 (Revised NGC)
  ?quadrant=A           crop to one lettered cell of the horizon view --
                        letters are marked on the chart, rerun adding the
                        one you want to zoom in (horizon view only, also
                        turns on ?dso=1 unless ?nodso=1 is added too)
  ?format=json          the same facts, structured
  ?plain=1              no ANSI colour
  ?w=100                render at N columns wide instead of the default

  10° is a closed fist at arm's length, so the gridlines are a ruler.

  Fit any terminal automatically, add to your shell profile:
    skymap() { curl "skymap.sh/${1:-}?w=$(tput cols)"; }

KEYBOARD (in a browser, on a chart page)
  tab    focus the place search      space  start the animation
  f      focus the find field        v      share as a GIF
  m      jump to my location         d      toggle quadrant grid + dso
  g      toggle golden hour (daylight charts: the band, times and bearings)
  esc    cancel/exit find mode, drawer
  z      zoom: pick a quadrant cell with arrow keys, enter to crop to it
  once it is running, space plays/pauses, left/right step a frame at a time
  (15 simulated minutes each), and d loads deep sky into the frame on screen

Stars: Yale Bright Star Catalogue. Planets: JPL approximate elements.
Sun and Moon: Meeus. Satellites: CelesTrak.
"""


def legend_text(color=True):
    """Every character and colour a chart can draw, in one place -- so "what's
    that dot" has an answer without reading sky.py. Colours come from the
    same constants/functions the renderer itself calls (sky.C, star_colour,
    DSO_GLYPH, moon_glyph's own phase glyphs), so this can't drift from what
    a chart actually draws."""
    SUN_C, ISS_C = "\033[38;5;227m", "\033[38;5;48m"
    STARLABEL_C, QUAD_C, BOUND_C = "\033[38;5;231m", "\033[38;5;226m", "\033[38;5;240m"
    starcol = sky.star_colour(None)
    bluewhite, white = sky.star_colour(-0.1), sky.star_colour(0.1)
    yellow, orangered = sky.star_colour(0.8), sky.star_colour(1.5)
    gal_gl, gal_c = sky.DSO_GLYPH["gal"]
    clu_gl, clu_c = sky.DSO_GLYPH["clu"]
    neb_gl, neb_c = sky.DSO_GLYPH["neb"]
    pln_gl, pln_c = sky.DSO_GLYPH["pln"]

    def P(s, c):
        return paint(s, c, color)

    def head(s):
        return paint(s, C.HEAD, color)

    L = [
        "skymap.sh -- legend", "",
        head("STARS"),
        f"  {P('●', starcol)}  bright, mag < 0.8      {P('•', starcol)}  ordinary, mag < 3.0"
        f"      {P('·', starcol)}  faint, mag < 4.2 (5.5 once fully dark)",
        f"  colour by temperature:  {P('blue-white', bluewhite)} -> {P('white', white)}"
        f" -> {P('yellow', yellow)} -> {P('orange-red', orangered)}",
        f"  {P('★', STARLABEL_C)}  the 3 brightest named stars, always labelled",
        "",
        head("CONSTELLATIONS"),
        f"  {P('─ ╱ │ ╲', C.DIM)}  asterism lines        {P('NAME', C.CNAME)}  asterism name",
        "",
        head("SOLAR SYSTEM"),
        f"  {P('☀', SUN_C)}  Sun        {P('◆', C.PLANET)}  planet",
        # Built from moon_glyph() itself, not typed out separately, so this
        # can't silently drift from what the chart actually draws. Left to
        # right: new -> waxing -> full -> waning -> new -- the words for each
        # step aren't spelled out here since phase_name() already gives the
        # exact one for whatever the chart is showing right now.
        f"  {P(' '.join(sky.moon_glyph(a) for a in range(0, 360, 45)), C.MOON)}"
        "  Moon, by phase (new -> full -> new)",
        "",
        head("DEEP SKY  --  ?dso=1"),
        f"  {P(gal_gl, gal_c)}  galaxy      {P(clu_gl, clu_c)}  open/globular cluster"
        f"      {P(neb_gl, neb_c)}  nebula      {P(pln_gl, pln_c)}  planetary nebula",
        "  about 30 well-known ones (Andromeda Galaxy, Orion Nebula, Whirlpool"
        " Galaxy...) are labelled by name",
        "",
        head("SATELLITE"),
        f"  {P('Ξ', ISS_C)}  ISS, marked automatically whenever a real pass is up",
        "",
        head("QUADRANTS  --  ?quadrant=A"),
        f"  {P('A B C D...', QUAD_C)}  lettered cells       {P('┊ ┈', BOUND_C)}  cell boundaries",
        "",
        head("HORIZON"),
        f"  {P('─', C.HOR)}  horizon line      {P('∙', C.HOR)}  degree ticks      "
        f"{P('N E S W', C.CARD)}  cardinal points",
        "",
    ]
    return "\n".join(L)


def _columns(items, col_width, per_row):
    L = []
    for i in range(0, len(items), per_row):
        row = items[i:i + per_row]
        L.append("  " + "".join(f"{s:{col_width}}" for s in row).rstrip())
    return L


# Real visual colour of each planet, not the generic C.PLANET diamond every
# planet shares on the actual chart -- this page is a reference list, not a
# rendering of the sky at a moment, so distinguishing them here is useful in
# a way it wouldn't be on the chart itself (too small, too briefly on screen).
_SUN_C = "\033[38;5;227m"
PLANET_COLORS = {
    "Mercury": "\033[38;5;246m",   # grey rock
    "Venus":   "\033[38;5;230m",   # pale cream cloud deck
    "Mars":    "\033[38;5;209m",   # rust
    "Jupiter": "\033[38;5;180m",   # tan bands -- same as C.PLANET
    "Saturn":  "\033[38;5;222m",   # pale gold
    "Uranus":  "\033[38;5;123m",   # pale cyan
    "Neptune": "\033[38;5;69m",    # deep blue
}


def _catalog_data():
    """Single source of truth for /catalog: which objects, in what order.
    Both catalog_text() (terminal) and catalog_html() (browser) render this
    same data, so they can't drift into listing different things."""
    stars = sky._load("stars.json")
    asterisms = sky._load("asterisms.json")
    dso = sky._load("deepsky.json")

    named_stars = sorted((s for s in stars if s.get("n")), key=lambda s: s["m"])
    # o["n"] is already the best label build_deepsky.py could give it (a
    # Messier number, else a hand-picked common name) -- a bare NGC number
    # there just means no traditional name exists, so those aren't "named".
    named_dso = sorted((o for o in dso if o["n"] != o["id"]), key=lambda o: o["m"])
    # Real current phase, not a fixed glyph -- this page reflects "right now"
    # for the Moon specifically, same as the chart itself does since the
    # render_linear()/moon_glyph() fix. Everything else here is a static
    # reference list, but the Moon's phase is too central to its identity to
    # leave generic.
    moon_age = sky.moon(sky.julian(dt.datetime.utcnow()))["age"]
    moon_display = f"Moon ({sky.phase_name(moon_age)})"
    solar_system = [("Sun", "Sun", "☀", _SUN_C),
                    ("Moon", moon_display, sky.moon_glyph(moon_age), C.MOON)]
    solar_system += [(nm, nm, "◆", PLANET_COLORS[nm]) for nm in
                     ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune")]

    # Meteor showers. Every one has had its own page since the object
    # namespace shipped; the catalogue simply never listed them, so the only
    # way to find /Perseids was to already know it existed.
    showers = sorted(sky._load("showers.json"), key=lambda x: -x["zhr"])
    # Its own group rather than an entry in the deep sky, which is sorted
    # brightest-first and prints a magnitude per row. There is no honest
    # magnitude for the whole band -- that is why the page suppresses it --
    # so putting it there would have meant inventing a number to fill a
    # column, on the one page whose job is to be a list of true things.
    ours = [("Milky Way", "barred spiral, centre in Sagittarius",
             sky.DSO_GLYPH["gal"][0], sky.DSO_GLYPH["gal"][1])]
    # Eclipses. They are not objects and they do not live in the object
    # namespace -- /eclipse is a page about a date, not about a thing in the
    # sky -- but the catalogue's promise is "everything below has its own
    # page", and these had pages nothing on the site linked to. Anybody who
    # did not already know the URL could not get there.
    #
    # The next few, not all forty-two: this is the shape of a table with a
    # future in it, and the page itself lists the rest.
    eclipses = eclipse_page.upcoming(dt.datetime.utcnow(), count=6)
    return dict(ours=ours,
               solar_system=solar_system, asterisms=sorted(a["name"] for a in asterisms),
               showers=showers, named_stars=named_stars, named_dso=named_dso,
               eclipses=eclipses)


# The Sun and the Moon, the same glyphs the chart draws them with and the
# same pair the eclipse page's own list uses.
ECLIPSE_GLYPH = {True: ("☀", _SUN_C), False: ("☾", C.MOON)}


def _eclipse_row(entry):
    """(glyph, colour, label, when, regions) for one catalogue row."""
    solar = eclipse_page.is_solar(entry)
    glyph, colour = ECLIPSE_GLYPH[solar]
    when = dt.datetime.fromisoformat(entry["when_utc"])
    return (glyph, colour, entry["type"],
            when.strftime("%d %b %Y").lstrip("0"), entry["regions"])


def catalog_text(color=True):
    """Every object findable by name via ?find= -- pulled live from the same
    catalogues resolve_target() reads, so this can't list something that
    isn't actually findable, or miss one that is."""
    def P(s, c):
        return paint(s, c, color)

    def head(s):
        return paint(s, C.HEAD, color)

    d = _catalog_data()

    L = [
        "skymap.sh -- object catalog", "",
        "Everything below has its own page:",
        "  curl skymap.sh/Vega",
        "  curl skymap.sh/M31            aliases work: NGC224, Andromeda Galaxy",
        "  curl skymap.sh/Zurich/Saturn  or name the place yourself", "",
        head("OUR GALAXY"),
    ] + [
        f"  {P(g, gc)} {P(f'{nm:22}', C.HEAD)} {note}"
        for nm, note, g, gc in d["ours"]
    ] + [
        "",
        head(f"SOLAR SYSTEM ({len(d['solar_system'])})"),
    ]
    for _nm, display, glyph, glyph_c in d["solar_system"]:
        L.append(f"  {P(glyph, glyph_c)} {display}")
    L.append("")
    L.append(head(f"METEOR SHOWERS ({len(d['showers'])}) -- strongest first"))
    for sh in d["showers"]:
        L.append(f"  {P(_SHOWER_GLYPH, C.LABEL)} {sh['name']:<27} "
                 f"up to {sh['zhr']:>3}/hour")
    L.append("")
    L.append(head("ECLIPSES -- soonest first"))
    for e in d["eclipses"]:
        glyph, colour, kind, when, regions = _eclipse_row(e)
        L.append(f"  {P(glyph, colour)} {P(f'{when:12}', C.HEAD)} "
                 f"{kind:14} {regions}")
    L.append(f"  {'':2} {eclipse_page.table_span()}")
    L.append(f"  {'':2} curl skymap.sh/eclipse for the next one")
    L.append("")
    L.append(head(f"CONSTELLATIONS ({len(d['asterisms'])})"))
    L += _columns(d["asterisms"], 18, 5)
    L.append("")
    L.append(head(f"NAMED STARS ({len(d['named_stars'])}) -- brightest first"))
    for s in d["named_stars"]:
        starcol = sky.star_colour(s.get("ci"))
        glyph = sky.glyph_for(s["m"])
        name = f"{s['n']:22}"
        con = sky.CONSTELLATION_NAMES.get(s["c"], s["c"]) if s.get("c") else ""
        L.append(f"  {P(glyph, starcol)} {P(name, starcol)} mag {s['m']:>5.2f}  {con}")
    L.append("")
    L.append(head(f"DEEP SKY ({len(d['named_dso'])}) -- brightest first"))
    for o in d["named_dso"]:
        glyph, glyph_c = sky.DSO_GLYPH[o["t"]]
        label = _dso_label(o)
        label = f"{label:34}"
        L.append(f"  {P(glyph, glyph_c)} {P(label, C.HEAD)} mag {o['m']:>5.2f}  {sky.DSO_NAMES[o['t']]}")
    L.append("")
    return "\n".join(L)


def _dso_label(o):
    label = o["n"]
    if o.get("cn") and o["cn"] != label:
        label = f"{label} ({o['cn']})"
    return label


_ANSI_NUM = re.compile(r"38;5;(\d+)")


def _ansi_hex(ansi):
    m = _ANSI_NUM.search(ansi)
    return _xterm_hex(m.group(1)) if m else "#c9d1d9"


def _pad_html(visible_len, width):
    return " " * max(1, width - visible_len)


def catalog_html():
    """Browser twin of catalog_text() -- every object links to its own page.

    These used to point at /?find=<name>, which framed the object on a chart
    of the current sky. Every one of them now has a page of its own, and a
    page is the better destination: it carries what the object is as well as
    where it is tonight, it has a stable URL somebody can share, and it is
    what a search engine indexes. All 486 catalog entries resolve, so nothing
    here links into a 404.

    In the same tab. These used to open a new one so that browsing the
    catalog never navigated away from the chart on screen, but the catalog is
    a place you go to pick something, not a panel you keep beside the sky --
    and a list of 486 links that each spawn a tab is a list that leaves the
    reader with a browser to tidy up. Back returns you to the catalog."""
    def col(s, ansi):
        return f'<span style="color:{_ansi_hex(ansi)}">{html.escape(s)}</span>'

    def head(s):
        return col(s, C.HEAD)

    def _href(name):
        return html.escape("/" + quote(name))

    def link(name, extra=""):
        return f'<a href="{_href(name)}">{html.escape(name)}</a>'

    def link_col(name, ansi, extra="", href_name=None):
        # href_name matters for the deep sky, where the label reads
        # "M31 (Andromeda Galaxy)" and only the bare designation resolves.
        return (f'<a href="{_href(href_name or name)}">'
                f'<span style="color:{_ansi_hex(ansi)}">{html.escape(name)}</span></a>')

    d = _catalog_data()

    L = [
        "skymap.sh -- object catalog", "",
        "Everything below has its own page.", "",
        head("OUR GALAXY"),
    ] + [
        f"  {col(g, gc)} {link_col(nm, C.HEAD)}{_pad_html(len(nm), 22)} "
        f"{html.escape(note)}"
        for nm, note, g, gc in d["ours"]
    ] + [
        "",
        head(f"SOLAR SYSTEM ({len(d['solar_system'])})"),
    ]
    for nm, display, glyph, glyph_c in d["solar_system"]:
        L.append(f"  {col(glyph, glyph_c)} {link_col(display, glyph_c, href_name=nm)}")
    L.append("")
    L.append(head(f"METEOR SHOWERS ({len(d['showers'])}) -- strongest first"))
    for sh in d["showers"]:
        nm = sh["name"]
        L.append(f"  {col(_SHOWER_GLYPH, C.LABEL)} "
                 f"{link_col(nm, C.LABEL) + _pad_html(len(nm), 27)}"
                 f" up to {sh['zhr']:>3}/hour")
    L.append("")
    L.append(head("ECLIPSES -- soonest first"))
    for e in d["eclipses"]:
        glyph, colour, kind, when, regions = _eclipse_row(e)
        key = eclipse_page.key_of(e)
        link_html = (f'<a href="/eclipse/{key}">'
                     f'<span style="color:{_ansi_hex(C.HEAD)}">{html.escape(when)}'
                     f'</span></a>' + _pad_html(len(when), 12))
        L.append(f"  {col(glyph, colour)} {link_html} "
                 f"{html.escape(kind)}{_pad_html(len(kind), 14)} "
                 f"{html.escape(regions)}")
    L.append(f"    {col(eclipse_page.table_span(), C.LABEL)}")
    L.append("")
    L.append(head(f"CONSTELLATIONS ({len(d['asterisms'])})"))
    for i in range(0, len(d["asterisms"]), 5):
        row = d["asterisms"][i:i + 5]
        line = "  " + "".join(link(nm) + _pad_html(len(nm), 18) for nm in row)
        L.append(line.rstrip())
    L.append("")
    L.append(head(f"NAMED STARS ({len(d['named_stars'])}) -- brightest first"))
    for s in d["named_stars"]:
        starcol = sky.star_colour(s.get("ci"))
        glyph = sky.glyph_for(s["m"])
        con = sky.CONSTELLATION_NAMES.get(s["c"], s["c"]) if s.get("c") else ""
        name_html = link_col(s["n"], starcol) + _pad_html(len(s["n"]), 22)
        L.append(f"  {col(glyph, starcol)} {name_html} mag {s['m']:>5.2f}  {html.escape(con)}")
    L.append("")
    L.append(head(f"DEEP SKY ({len(d['named_dso'])}) -- ?dso=1, brightest first"))
    for o in d["named_dso"]:
        glyph, glyph_c = sky.DSO_GLYPH[o["t"]]
        label = _dso_label(o)
        name_html = (link_col(label, C.HEAD, "&dso=1&quadrant", href_name=o["n"])
                    + _pad_html(len(label), 34))
        L.append(f"  {col(glyph, glyph_c)} {name_html} mag {o['m']:>5.2f}  {sky.DSO_NAMES[o['t']]}")
    L.append("")
    return "\n".join(L)


# A generic outline-star for constellations -- the only _catalog_data()
# group with no glyph of its own (catalog_text/catalog_html don't give them
# one either), kept visually distinct from a named star's filled/magnitude
# glyph and a planet's solid diamond.
_ASTERISM_GLYPH = ("✧", "#8b949e")
# The same mark api.object_glyph() gives a meteor radiant, so the catalogue
# row and the page it links to show the same symbol.
_SHOWER_GLYPH = "☄"

COMPLETE_OBJECT_CAP = 24   # same reasoning as COMPLETE_PREFIX_CAP


def complete_objects(prefix, n=8):
    """Up to n findable objects (solar system, named stars, deep sky,
    constellations) matching prefix -- the find field's dropdown data
    source (GET /complete/objects). Pulled from the same _catalog_data()
    catalog_html() renders from, so a suggestion can't drift from what's
    actually findable.

    Matches the start of any word in the name, not just the whole string
    (city-style prefix-only matching would miss "Big Dipper" on "dip"), and
    is ranked solar system first, then brightest named star, then brightest
    deep-sky object, then constellations alphabetically -- the order
    _catalog_data() already returns each group in, concatenated."""
    key = norm_name(prefix)[:COMPLETE_OBJECT_CAP]
    if len(key) < 2:
        return []

    def word_match(name):
        return any(norm_name(w).startswith(key) for w in name.split())

    d = _catalog_data()
    out = []
    # "name" is what the dropdown shows, "q" is what it searches for. They
    # are the same for everything except the Moon, whose label carries its
    # current phase -- and the dropdown used to submit the label, so picking
    # the Moon searched for "Moon (last quarter)" and found nothing.
    for nm, _note, glyph, glyph_c in d["ours"]:
        if word_match(nm):
            out.append({"name": nm, "glyph": glyph,
                       "color": _ansi_hex(glyph_c)})
    for nm, display, glyph, glyph_c in d["solar_system"]:
        if word_match(display):
            out.append({"name": display, "q": nm, "glyph": glyph,
                       "color": _ansi_hex(glyph_c)})
    for s in d["named_stars"]:
        if word_match(s["n"]):
            out.append({"name": s["n"], "glyph": sky.glyph_for(s["m"]),
                       "color": _ansi_hex(sky.star_colour(s.get("ci")))})
    for o in d["named_dso"]:
        if word_match(_dso_label(o)):
            glyph, glyph_c = sky.DSO_GLYPH[o["t"]]
            out.append({"name": o["n"], "glyph": glyph, "color": _ansi_hex(glyph_c)})
    # Before the constellations, matching the order the catalog lists them
    # in. Missing entirely until now: _catalog_data() has always returned
    # them and every one of them has a working page, so /Perseids resolved
    # and the search bar simply never offered it -- the one group of objects
    # that is only worth looking up in the few weeks around its peak.
    for sh in d["showers"]:
        if word_match(sh["name"]):
            out.append({"name": sh["name"], "glyph": _SHOWER_GLYPH,
                       "color": _ansi_hex(C.LABEL)})
    for nm in d["asterisms"]:
        if word_match(nm):
            out.append({"name": nm, "glyph": _ASTERISM_GLYPH[0], "color": _ASTERISM_GLYPH[1]})
    return out[:n]


# ---------------------------------------------------------------- ansi -> html
ANSI = re.compile(r"\033\[(?:38;5;(\d+)|0)m")


def _xterm_hex(n):
    n = int(n)
    if n < 16:
        base = ["000000","800000","008000","808000","000080","800080","008080","c0c0c0",
                "808080","ff0000","00ff00","ffff00","0000ff","ff00ff","00ffff","ffffff"]
        return "#" + base[n]
    if n < 232:
        n -= 16
        lv = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    v = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (v, v, v)


def _anchor_markers(s):
    """sky.LINK_START/SEP/END -> <a>/</a>, on already-escaped HTML.

    The chart is painted one cell at a time, so a label is a run of separate
    colour spans by the time it is a string and there is nothing left to
    match on. sky.py puts these markers down while the row is assembled, when
    the label's extent is still known, and this is where they become links.

    The anchor goes outside the spans, so the colours inside it are untouched
    and a linked label is character-for-character what it was.
    """
    out = []
    for i, chunk in enumerate(s.split(sky.LINK_START)):
        if i == 0:
            out.append(chunk)
            continue
        href, _, rest = chunk.partition(sky.LINK_SEP)
        body, _, tail = rest.partition(sky.LINK_END)
        out.append(f'<a class="sky-link" href="{href}">{body}</a>{tail}')
    return "".join(out)


def ansi_to_html(text):
    out, pos, open_span = [], 0, False
    for m in ANSI.finditer(text):
        out.append(html.escape(text[pos:m.start()])); pos = m.end()
        if open_span:
            out.append("</span>"); open_span = False
        if m.group(1):
            out.append(f'<span style="color:{_xterm_hex(m.group(1))}">'); open_span = True
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    # After escaping, so a label's own characters can never be read as
    # markup, and the href is one we built rather than anything from a page.
    return _anchor_markers("".join(out))


# The link markers as well as the escapes. Nothing but the browser ever wants
# either, and a terminal printing a stray \x01 would be a visible bug.
_MARKERS = re.compile(f"[{sky.LINK_START}{sky.LINK_SEP}{sky.LINK_END}]")


def strip_ansi(text):
    return _MARKERS.sub("", ANSI.sub("", text))


# Live map for /stats, injected through PAGE's {extra} slot rather than into
# PAGE itself -- every other page shares that template and none of them has a
# map to animate.
#
# Polls /stats/live for cells that saw a request since the last poll, flashes
# each one white-hot, then lets the transition carry it back to whatever the
# heat ramp says its running total deserves. The flash says "just now"; the
# resting colour still says "in total", so neither lies about the other.
#
# The same poll refreshes the two lines that go stale fastest -- the request
# count at the top and the location tally under the map. The charts and the
# counters below them don't move: they are text the server drew, and redrawing
# them means shipping the whole block again for numbers that mostly crawl.
def stats_live_html(ramp_hex, sizes, dot, flash_dot, tick_ms=3000):
    """The live map's style and script.

    ramp_hex is the heat ramp as hex and sizes is the matching scale per
    step, both in order, and the two glyphs come from the caller too --
    server.py owns MAP_RAMP, MAP_SIZES and MAP_DOT, and a second copy of any
    of them here is a second thing to keep in sync.

    Every dot is an inline-block exactly 1ch wide. That is what makes the
    glyph swap safe: a bullet is a wider glyph than a middle dot in most
    fonts, and without a pinned advance width one flashing dot would shove
    the rest of its row sideways. Both scales on top of that -- the resting
    one for how busy the cell is, and the flash -- are transforms, which by
    definition take no part in layout.

    The two multiply rather than one replacing the other, so a flash is
    always a jump up from wherever that dot sits. Capped, because 1.9x on
    top of the busiest resting size is a blob rather than a dot."""
    levels = "\n".join(f" .h{i}{{color:{c}}}" for i, c in enumerate(ramp_hex))
    steps = "\n".join(f" .s{i}{{--s:{s:g}}}" for i, s in enumerate(sizes))
    # Stripped here rather than at import: this block is built per call from
    # the ramp it is given, so there is no constant to strip. See minify.py.
    return minify.strip_page("<style>\n"
            " .d{display:inline-block;width:1ch;vertical-align:baseline;"
            "text-align:center;font-style:normal;\n"
            "     transform:scale(min(var(--s,1) * var(--f,1), 2.9));\n"
            "     transition:color 1.4s ease-out,text-shadow 1.4s ease-out,"
            "transform 1.4s ease-out}\n"
            f"{levels}\n"
            f"{steps}\n"
            " .d.hot{color:#fff !important;"
            "text-shadow:0 0 7px #fff,0 0 14px #ffc400,0 0 22px #ff6d00;\n"
            "        --f:1.9;transition:none}\n"
            " @media (prefers-reduced-motion:reduce){\n"
            # The size ramp stays: it says how busy a cell is, and holding
            # still at a size is not motion. Only the flash's jump goes.
            "   .d,.d.hot{transition:none;text-shadow:none}\n"
            "   .d.hot{--f:1}\n"
            " }\n"
            "</style>\n"
            "<script>\n(function(){\n"
            f"  var tick = {int(tick_ms)};\n"
            # ensure_ascii=False so the glyphs read as themselves rather than
            # as \u escapes. The page is utf-8 and declares it.
            f"  var DOT = {json.dumps(dot, ensure_ascii=False)}, "
            f"FLASH = {json.dumps(flash_dot, ensure_ascii=False)};\n"
            """  var since = 0, dead = 0;
  function paint(cells){
    for (var i = 0; i < cells.length; i++){
      var el = document.getElementById('d' + cells[i][0] + '_' + cells[i][1]);
      if (!el) continue;
      var lvl = cells[i][2] || 0;
      // Drop the class and force a reflow before re-adding it. Without that
      // gap a cell that keeps getting hits never restarts its animation --
      // the class is already there, so nothing changes.
      el.classList.remove('hot');
      void el.offsetWidth;
      el.textContent = FLASH;
      el.classList.add('hot');
      (function(e, l){
        setTimeout(function(){
          // Both level classes at once, which drops 'hot' with them: the
          // transition then carries colour and size together back to
          // whatever the running total now deserves.
          e.className = 'd h' + l + ' s' + l;
          e.textContent = DOT;
        }, 400);
      })(el, lvl);
    }
  }
  // The two lines the poll can keep current: the count at the top of the
  // page and the tally under the map. The server sends them finished, so
  // this only swaps text -- everything else on /stats (the charts, the
  // counters, the tables) stays the snapshot the page was built from.
  function retext(id, s){
    var el = document.getElementById(id);
    if (el && s && el.textContent !== s) el.textContent = s;
  }
  function relabel(d){
    retext('live-head', d.head);
    retext('live-legend', d.legend);
  }
  function poll(){
    if (document.hidden){ setTimeout(poll, tick); return; }
    fetch('/stats/live?since=' + since, {cache: 'no-store'})
      .then(function(r){ return r.json(); })
      .then(function(d){ since = d.now; dead = 0; paint(d.flash || []);
                         relabel(d); })
      .catch(function(){
        // Back off rather than keep hammering a server already unhappy.
        dead++;
        if (dead > 5) tick = 30000;
      })
      .then(function(){ setTimeout(poll, tick); });
  }
  function start(){
    if (!document.querySelector('.d')) return;
    // First poll asks for everything still in the buffer, which would flash
    // the whole backlog at once. Take that answer only to learn the server's
    // clock, then start showing flashes from there.
    fetch('/stats/live?since=0', {cache: 'no-store'})
      .then(function(r){ return r.json(); })
      .then(function(d){ since = d.now; relabel(d); })
      .catch(function(){})
      .then(function(){ setTimeout(poll, tick); });
  }
  // This script is injected into the toolbar, which the parser reaches
  // before the <pre> holding the map -- so at this point there are no dots
  // to find yet and querySelector would come back empty.
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', start);
  else start();
})();
</script>""" )


def _side_by_side(left_lines, right_lines, gap=3):
    """Zip two blocks of (possibly ANSI-coloured) text lines into one,
    left padded to its own widest *visible* line (ANSI colour codes add
    invisible characters, so padding on raw string length would misalign
    the right column). Uneven heights are fine -- the shorter block just
    leaves blank space in its column past its own last line."""
    left_width = max((len(strip_ansi(l)) for l in left_lines), default=0)
    out = []
    for i in range(max(len(left_lines), len(right_lines))):
        l = left_lines[i] if i < len(left_lines) else ""
        r = right_lines[i] if i < len(right_lines) else ""
        if r:
            pad = left_width - len(strip_ansi(l))
            out.append(l + " " * (pad + gap) + r)
        else:
            out.append(l)
    return out


# Official brand marks (GitHub, Reddit, Bluesky, X), inline so this stays a
# dependency-free single file -- no icon package, no external request. Same
# links the old "Created by @habibicode · see the repo" footer line pointed
# at, plus the community's new Reddit and Bluesky homes; that line only ever
# existed on the web page (never part of the shared chart text CLI/curl
# see), so any of this moving/changing doesn't touch CLI output.
# Path data fetched verbatim from Simple Icons (cdn.jsdelivr.net/npm/simple-
# icons/icons/{name}.svg) -- hand-transcribing SVG path data from memory is
# exactly how you get a silently-corrupted icon (two numbers running
# together at a line break, missing a separator), so every path here was
# copied from the real file, not retyped.
_GITHUB_PATH = "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"
_REDDIT_PATH = "M12 0C5.373 0 0 5.373 0 12c0 3.314 1.343 6.314 3.515 8.485l-2.286 2.286C.775 23.225 1.097 24 1.738 24H12c6.627 0 12-5.373 12-12S18.627 0 12 0Zm4.388 3.199c1.104 0 1.999.895 1.999 1.999 0 1.105-.895 2-1.999 2-.946 0-1.739-.657-1.947-1.539v.002c-1.147.162-2.032 1.15-2.032 2.341v.007c1.776.067 3.4.567 4.686 1.363.473-.363 1.064-.58 1.707-.58 1.547 0 2.802 1.254 2.802 2.802 0 1.117-.655 2.081-1.601 2.531-.088 3.256-3.637 5.876-7.997 5.876-4.361 0-7.905-2.617-7.998-5.87-.954-.447-1.614-1.415-1.614-2.538 0-1.548 1.255-2.802 2.803-2.802.645 0 1.239.218 1.712.585 1.275-.79 2.881-1.291 4.64-1.365v-.01c0-1.663 1.263-3.034 2.88-3.207.188-.911.993-1.595 1.959-1.595Zm-8.085 8.376c-.784 0-1.459.78-1.506 1.797-.047 1.016.64 1.429 1.426 1.429.786 0 1.371-.369 1.418-1.385.047-1.017-.553-1.841-1.338-1.841Zm7.406 0c-.786 0-1.385.824-1.338 1.841.047 1.017.634 1.385 1.418 1.385.785 0 1.473-.413 1.426-1.429-.046-1.017-.721-1.797-1.506-1.797Zm-3.703 4.013c-.974 0-1.907.048-2.77.135-.147.015-.241.168-.183.305.483 1.154 1.622 1.964 2.953 1.964 1.33 0 2.47-.81 2.953-1.964.057-.137-.037-.29-.184-.305-.863-.087-1.795-.135-2.769-.135Z"
_BLUESKY_PATH = "M5.202 2.857C7.954 4.922 10.913 9.11 12 11.358c1.087-2.247 4.046-6.436 6.798-8.501C20.783 1.366 24 .213 24 3.883c0 .732-.42 6.156-.667 7.037-.856 3.061-3.978 3.842-6.755 3.37 4.854.826 6.089 3.562 3.422 6.299-5.065 5.196-7.28-1.304-7.847-2.97-.104-.305-.152-.448-.153-.327 0-.121-.05.022-.153.327-.568 1.666-2.782 8.166-7.847 2.97-2.667-2.737-1.432-5.473 3.422-6.3-2.777.473-5.899-.308-6.755-3.369C.42 10.04 0 4.615 0 3.883c0-3.67 3.217-2.517 5.202-1.026"
_X_PATH = "M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"


def _social_icon(href, label, path):
    return (f'<a href="{href}" aria-label="{label}" title="{label}">'
            f'<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">'
            f'<path d="{path}"/></svg></a>')


SOCIAL_ICONS = (
    '<span class="social-icons">'
    + _social_icon(brand.GITHUB, "See the repo on GitHub", _GITHUB_PATH)
    + _social_icon(brand.REDDIT, "Join r/skymap on Reddit", _REDDIT_PATH)
    + _social_icon(brand.BLUESKY, "Follow on Bluesky", _BLUESKY_PATH)
    + _social_icon(brand.X, "Follow on X", _X_PATH)
    + '</span>'
)


# What the one bar accepts, spelled out. The bar has always taken all three
# (a bare ?q= redirect means "catalog" and "Venus" have worked as long as
# "Zurich" has), but nothing on the page ever said so, and the separate find
# field implied the opposite: that places went in one box and objects in the
# other. Two boxes were also two different reaches, and the find one only
# existed on chart pages, so on /events there was no way to look up an
# object at all.
# stats is deliberately absent: typing it still works, it is just not
# advertised until the page itself is worth pointing at.
SEARCH_PAGES = ("catalog", "eclipse", "events", "help", "legend")

SEARCH_HELP = (
    '<div class="search-help" id="search-help" hidden role="dialog" '
    'aria-label="What you can search for">'
    '<dl>'
    '<dt>Locations</dt>'
    '<dd>cities or coordinates'
    '<span class="eg">Zurich &middot; 47.37,8.55</span></dd>'
    '<dt>Objects</dt>'
    '<dd>planets, stars, deep sky, showers'
    '<span class="eg">Venus &middot; Vega &middot; M31 &middot; Perseids</span></dd>'
    '<dt>Pages</dt>'
    '<dd>' + " &middot; ".join(SEARCH_PAGES) + '</dd>'
    '</dl>'
    # The one thing the three rows above cannot show, because it is about
    # how they combine rather than what any of them is. Written as the path
    # it produces, since that is literally what the bar will say.
    '<p class="search-help-slash">A slash puts them together: type '
    '<b>Tokyo/</b> and then an object to see it from there, like '
    '<b>Tokyo/Venus</b>.</p>'
    '<a class="search-help-more" href="/catalog">Browse everything in the '
    'catalog</a></div>')


def header_html(value="", pill=""):
    """The command bar + nav, identical on every page -- one function so the
    nav can never drift or reorder between routes the way six separate
    PAGE.format() call sites each re-deciding it independently did. "home"
    stays onscreen even on the home page itself -- consistent nav position
    beats not linking to the page you're already on. Social icons (GitHub,
    Reddit, Bluesky, X) sit right after "legend" -- the GitHub/X pair used
    to be a separate "Created by ... see the repo" line below the chart;
    folding them into the nav row keeps the same links without spending a
    whole extra row on them.

    value is whatever belongs after "skymap.sh/" -- the current place's
    display name on a chart page, or the bare page name ("catalog", "help",
    ...) elsewhere, same as the old static "$ curl skymap.sh/<path>" chip
    always showed. Keeping that on every page (rather than leaving it blank
    off the chart view) is deliberate: it's still "curl skymap.sh/help", it
    reads as editable and *curlable* everywhere, not just for places.
    Real <input>, not decoration -- see PAGE's script for the auto-size/
    click-to-focus/ghost-completion behaviour and _respond's ?q= handling
    for the plain-HTML-forms fallback this degrades to without JS.

    One bar, not two. There used to be a second "find" field beside this one
    for objects, which split a single question ("where do I type Venus?")
    across two boxes and only ever appeared on chart pages, so on /events or
    /catalog there was nowhere to type an object at all.

    The bar is the path, and the slash is the whole mechanism. value is
    always exactly what follows skymap.sh/ for the page being rendered:
    "Tokyo/" on a chart (the trailing slash is the invitation to name an
    object), "Tokyo/Venus" on that object seen from there, "catalog" on the
    catalog. Type after the slash and the suggestions are objects, because
    that is what a second segment means; type over the whole thing and they
    are places, objects and pages again.

    That is why there is no separate "which place am I on" state to carry
    around. An earlier attempt sent the place along beside the query so the
    server could recombine them, which meant the bar could read
    "skymap.sh/venus" while the click went to /Tokyo/Venus -- a command bar
    that shows one command and runs another. Here the text and the
    destination are the same string.

    ?find= is untouched and still renders a crosshair chart, so links shared
    before the merge keep working.

    The command bar and the nav row share one flex row (.header-row) so the
    nav sits inline with it instead of wrapping to a line of its own."""
    return (f'<div class="header-row">'
            f'<div class="bar-wrap">'
            f'<form class="cmdbar" id="bar" method="get" action="/">'
            f'<span class="prompt" aria-hidden="true">$</span>'
            f'<span class="fixed" aria-hidden="true">'
            f'<span class="curlword">curl </span>skymap.sh/</span>'
            f'<span class="field">'
            f'<input id="q" name="q" value="{html.escape(value)}" '
            f'aria-label="A place, an object, or a page" spellcheck="false" '
            f'autocapitalize="off" role="combobox" aria-expanded="false" '
            f'aria-controls="bar-dropdown" '
            f'autocorrect="off" autocomplete="off" enterkeyhint="go">'
            f'<span class="measure" id="measure" aria-hidden="true"></span>'
            f'</span>'
            f'<span class="cursor" id="cur" aria-hidden="true"></span>'
            f'<span class="grow"></span>'
            f'<button type="button" class="barpill" id="help-pill" '
            f'aria-expanded="false" aria-controls="search-help">? help</button>'
            f'</form>'
            f'<ul class="bar-dropdown" id="bar-dropdown" role="listbox" hidden></ul>'
            f'{SEARCH_HELP}'
            f'</div>'
            # What is on, beside the bar rather than under the chart. It
            # opens a modal: the chart is the page now, and anything docked
            # to the bottom of the window is competing with it for the one
            # thing it needs, which is height.
            f'{pill}'
            f'<p class="t nav-row"><span>'
            f'<a href="/">home</a> · '
            # Bare /events, not /{place}/events: the nav is the same on every
            # page, so it cannot carry a place. The route locates by IP the
            # way a bare `curl skymap.sh` does.
            f'<a href="/events">events</a> · '
            # catalog/demo/legend moved into the drawer (see
            # DRAWER_LINKS_HTML) -- less-used than events/help, and the nav
            # row was the one thing on every page that couldn't collapse.
            f'<a href="/help">help</a> {SOCIAL_ICONS}'
            f'<button type="button" class="drawer-trigger" id="drawer-trigger" '
            f'aria-expanded="false" aria-controls="drawer">☰</button>'
            f'</span></p></div>')


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="canonical" href="{canonical}">
<meta name="description" content="The night sky above you, as plain text. curl skymap.sh">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="The night sky above you, as plain text. No signup, no API key.">
<meta property="og:image" content="https://skymap.sh/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="skymap.sh">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://skymap.sh/og.png">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<script>
// Feature-detection class, not a capability check -- the drawer's CSS (see
// below) only turns into an off-canvas panel once this is present, so a
// page with JS disabled falls back to every control simply being visible
// inline, not hidden behind a trigger that does nothing. Deliberately up
// here, before the page body exists to paint anything, not down with the rest of
// the script by #chart-pre: on a real full-page navigation (e.g. clicking
// "show quadrants", a plain link) the browser paints whatever HTML it's
// parsed so far as it goes -- if this ran down there instead, the drawer's
// un-enhanced, full-width, always-open state (including its full-width
// "go" button) would flash on screen for a frame before the class landed
// and CSS collapsed it back into the narrow hidden panel.
document.documentElement.classList.add('js');
</script>
<style>
 body{{margin:0;background:#04060a;color:#c9d1d9;
      font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
      /* Bottom padding clears .kbd-hint's own fixed bar and then leaves the
         page's one gap under it, so the last box ends the same distance
         above the bar as every other box on the page sits from its
         neighbour. It was a flat 40, which cleared the 33px bar with 7px
         to spare -- half the gap everything else gets, and visibly tight
         under a chart that had scrolled to the bottom of the window. */
      padding:24px 16px {BOTTOM_PAD}px;
      -webkit-font-smoothing:antialiased}}
 .w{{max-width:1200px;margin:0 auto}}
/* Bottom right, out of the way until wanted. Fixed rather than in the flow
   so it does not move with the chart, and quiet enough not to compete with
   it. Hidden when printing, and it steps aside on a narrow screen where a
   floating box would sit on top of the content. */
.obj-feedback{{position:fixed;right:18px;bottom:18px;z-index:20;
  display:block;max-width:none;padding:10px 13px;border-radius:8px;
  white-space:nowrap;
  background:rgba(18,21,26,.94);border:1px solid #262c35;
  font-size:11.5px;line-height:1.4;color:#8b93a3;text-decoration:none;
  box-shadow:0 3px 14px rgba(0,0,0,.45)}}
.obj-feedback:hover{{border-color:#3d4757;color:#c9d1d9}}
.obj-feedback-q{{display:block}}
.obj-feedback-a{{display:block;color:#8fb6e0;margin-top:2px}}
.obj-feedback:hover .obj-feedback-a{{color:#b7d4f5}}
/* Collapsed by default, opened on hover. Gated on a device that HAS a
   pointer: on a touchscreen the first tap would spend itself opening the
   box instead of following the link, and the second tap is the one nobody
   makes. Those get the full box, which they have room for. */
.obj-feedback-chip{{display:none}}
@media (hover:hover) and (min-width:901px){{
  .obj-feedback{{padding:7px 11px}}
  .obj-feedback-chip{{display:flex;align-items:center;gap:.45em}}
  .obj-feedback-full{{display:none}}
  .obj-feedback:hover .obj-feedback-chip,
  .obj-feedback:focus-visible .obj-feedback-chip{{display:none}}
  .obj-feedback:hover .obj-feedback-full,
  .obj-feedback:focus-visible .obj-feedback-full{{display:block}}
}}
.obj-feedback-i{{width:11px;height:11px;flex:none;opacity:.85}}
@media (max-width:900px){{
  .obj-feedback{{position:static;max-width:none;margin:1.6rem 0 0;
    box-shadow:none;background:transparent}}
}}
@media print{{.obj-feedback{{display:none}}}}
 .w-wide{{max-width:none}}
/* font-family:inherit is what makes the body rule above actually global. A
   <pre> otherwise takes the browser's own default monospace whatever the
   page says, so the charts were set in a different face from every sentence
   around them -- Courier against SF Mono on this machine -- and the page had
   two typefaces nobody had chosen. It is declared in one place now, on body,
   and everything including the drawing follows it. */
 pre{{margin:0;font-size:11px;line-height:1.22;overflow-x:auto;
     font-variant-ligatures:none;font-family:inherit}}
/* A label on the chart that has a page behind it. Character-for-character
   what it was: the colour comes from the spans inside the anchor and is left
   alone, and there is no underline, no weight change and no hover colour.
   The chart is a drawing and a blue underlined star name would be a hole in
   it. The pointer is the whole affordance, which is what a reader gets
   anyway the moment they move the mouse across it. */
 a.sky-link{{color:inherit;text-decoration:none}}
 /* Bigger than the generic pre{{}} above -- meant to be scoped to the chart
    page only, but #chart-pre is the *same id* every page's <pre> uses, so
    a bare #chart-pre selector here was never actually scoped at all --
    it silently bumped catalog/help/legend/stats too (the /stats live map
    included, whose ASCII grid is a fixed character count: a bigger font
    made it wider in pixels, which is what pushed it past the 1200px .w
    cap into a horizontal scroll that didn't exist at 11px).
    .kbd-hint ~ #chart-pre instead: SHORTCUTS_HINT (the "Keyboard: ..."
    bar, .kbd-hint) is only ever non-empty on the chart route, so this
    selector is what "chart page only" actually meant to say. Chart height
    is invariant to this: the row count is always cols/HORIZON_COLS_PER_ROW,
    so a bigger font just means fewer, taller cells -- same total pixel
    height either way. Only the fixed-line-count prose below the chart
    actually grows, which is the whole point.
    The laddered chart page carries its own copy of this size (see
    chart_ladder_css) -- there the number is load-bearing rather than
    cosmetic, since the ch breakpoints are measured in it. */
 .kbd-hint ~ #chart-pre{{font-size:13px}}
/*LADDER*/
 .t{{color:#6e7681;font-size:12px;margin:0 0 18px}}
 .nav-row{{display:flex;justify-content:flex-end;align-items:center;
          flex-wrap:wrap;gap:8px}}
 .header-row{{display:flex;justify-content:space-between;align-items:center;
             flex-wrap:wrap;gap:12px;margin:0 0 14px}}
 .header-row .nav-row{{margin:0;flex:1;min-width:0}}
 .social-icons{{display:inline-flex;gap:8px;margin-left:8px;vertical-align:middle}}
 /* On a phone the header row is the command bar and one button. Everything
    else it carried -- home, events, help, the four social icons -- is in
    the drawer, which is what the drawer is for, and none of it was worth a
    second line at the top of every page. The bar loses the word "curl" and
    the help pill to make room, so the trigger sits beside it rather than
    under it. */
 @media (max-width:700px){{
   /* The trigger is pinned to the corner rather than laid out beside the
      bar. Asking flex to keep them on one line means asking the bar to
      shrink below its content, and the bar is a form with a prompt, a
      fixed "skymap.sh/" and an input the script sizes to its own text --
      it does not shrink, so the button wrapped underneath it and left the
      only way into the drawer somewhere nobody looks. Out of the flow it
      cannot wrap, and the bar simply reserves the corner it sits in. */
   .header-row{{position:relative;display:block;gap:0}}
   /* .header-row in front of every one of these on purpose. CMDBAR_CSS is
      spliced in further down this same sheet, and a media query adds no
      specificity -- a bare .cmdbar rule here ties with the one down there
      and loses on order, which is why the bar kept its min-width of 90vw
      and ran under the drawer button however much padding the wrapper
      reserved. */
   .header-row .bar-wrap{{display:flex;max-width:100%;padding-right:44px}}
   /* No floor: on a phone the bar is as wide as what it says, and the
      dropdown under it is the same width as the bar. 90vw was a desktop
      number that left no room for anything beside it. */
   .header-row .cmdbar{{min-width:0;max-width:100%}}
   .header-row .cmdbar .curlword,
   .header-row .cmdbar .barpill{{display:none}}
   .header-row .cmdbar .field,.header-row .cmdbar #q{{min-width:0}}
   .header-row .nav-row{{position:absolute;top:50%;right:0;margin:0;
                        transform:translateY(-50%);z-index:5}}
   /* The " · " between the nav links are bare text nodes, so hiding the
      links left two floating dots beside the bar. The trigger sets its own
      font-size, so zeroing the span's takes the separators and nothing
      else. */
   .nav-row>span{{font-size:0}}
   .nav-row>span>a,.nav-row .social-icons{{display:none}}
 }}
 .social-icons a{{color:#6e7681;display:inline-flex}}
 .social-icons a:hover{{color:#c9d1d9}}
 .social-icons svg{{display:block}}
 a{{color:#87d7ff}}
 .chart-pre a{{color:#87d7ff;text-decoration:none}}
 .chart-pre a:hover{{text-decoration:underline}}
 /* Drawer (SPEC-command-bar.md #9, adapted: slide in from the right, no
    backdrop, opened via header_html's #drawer-trigger next to the social
    icons). The base rules here are deliberately just a plain, always-
    visible block section -- see controls_html's docstring. Only once
    PAGE's script adds .js to <html> do the fixed/off-canvas/hidden rules
    below apply, so every control stays reachable with no JS at all. */
 #drawer{{margin:0 0 14px}}
 .drawer-section{{margin:0 0 16px;padding:0 0 16px;border-bottom:1px solid #30363d}}
 .drawer-section:last-child{{margin:0;padding:0;border-bottom:0}}
 .drawer-section:empty{{display:none}}
 .drawer-trigger{{display:none}}
 .js .drawer-trigger{{display:inline-flex;align-items:center;justify-content:center;
                      background:#0d1117;border:1px solid #30363d;color:#ffd700;
                      border-radius:4px;width:28px;height:28px;margin-left:8px;
                      font-size:14px;line-height:1;cursor:pointer}}
 .js .drawer-trigger:hover{{border-color:#ffd700}}
 .drawer-close{{display:none}}
 .js .drawer-close{{display:block;position:absolute;top:16px;right:16px;
                    background:none;border:0;color:#ffd700;font-size:16px;
                    line-height:1;padding:6px;cursor:pointer}}
 .js .drawer-close:hover{{color:#fff}}
 .js #drawer{{position:fixed;top:0;right:0;bottom:0;width:320px;max-width:90vw;
             margin:0;padding:56px 16px 16px;background:#0d1117;
             border-left:1px solid #30363d;overflow-y:auto;z-index:20;
             transform:translateX(100%);transition:transform .2s ease}}
 .js #drawer.open{{transform:translateX(0)}}
 .ex{{display:block}}
 .ex form{{display:flex;flex-direction:column;gap:8px;margin:0}}
 .ex input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
           padding:6px 10px;border-radius:4px;font:inherit;font-size:12px;
           width:100%;box-sizing:border-box}}
 .ex input#whenDate,.ex input#whenTime{{color-scheme:dark}}
 .ex-row{{display:flex;gap:8px}}
 .ex-row input{{width:auto;flex:1;min-width:0}}
 .ex button{{background:#238636;border:0;color:#fff;padding:8px 14px;
            border-radius:4px;font:inherit;font-size:12px;cursor:pointer;
            width:100%}}
 .ex button:hover{{background:#2ea043}}
 .tries{{color:#6e7681;font-size:12px;margin:0}}
 .tries a{{color:#87d7ff;text-decoration:none}}
 .tries a:hover{{text-decoration:underline}}
/*CMDBAR_CSS*/
 .animate-controls{{display:block;margin:0 0 8px}}
 .animate-btn{{background:#0d1117;border:1px solid #30363d;color:#ffd700;
              padding:8px 12px;border-radius:4px;font:inherit;font-size:12px;
              cursor:pointer;display:block;width:100%;box-sizing:border-box;
              text-align:center;text-decoration:none;margin:0 0 8px}}
 .animate-btn:hover{{border-color:#ffd700;text-decoration:none}}
 .animate-btn:disabled{{opacity:.6;cursor:default}}
 .share-row{{display:flex;gap:8px;margin:0 0 8px}}
 .share-row .gif-group{{flex:1;margin:0}}
 .share-row>.animate-btn{{flex:1;margin:0}}
 .gif-group{{display:flex;flex-direction:column;gap:4px;margin:0 0 8px}}
 .gif-group .animate-btn{{margin:0}}
 .gif-status{{color:#6e7681;font-size:12px}}
 .gif-status a{{color:#ffd700;text-decoration:none}}
 .gif-status a:hover{{text-decoration:underline}}
 .mobile-only{{display:none}}
 @media (pointer:coarse) and (max-width:900px){{.mobile-only{{display:inline-block}}}}
 .kbd-hint{{position:fixed;left:0;right:0;bottom:0;margin:0;padding:9px 16px;
           text-align:center;background:#0d1117;border-top:1px solid #30363d;
           color:#6e7681;font-size:11.5px;z-index:10}}
 .kbd-hint kbd{{background:#04060a;border:1px solid #30363d;border-radius:3px;
              padding:0 5px;font-family:inherit;font-size:11px;color:#c9d1d9}}
 .quad-pick{{background:#ffff00;color:#000 !important;border-radius:2px}}
 /* Coming-up card -- one line, full width, colour entirely from
    --cu-accent so retuning per urgency is a one-line change per bucket,
    not a rule rewrite. .cu-body ellipsizes rather than wraps: "tight,
    one line" holds at any viewport width instead of degrading to two. */
 .coming-up{{display:flex;align-items:center;gap:10px;padding:8px 14px;
            margin:0 0 12px;background:#0d1117;border:1px solid #30363d;
            border-left:3px solid var(--cu-accent,#ff87ff);border-radius:6px;
            font-size:12.5px}}
 /* Two variables per bucket: the accent, and how bright the sentence
    itself is. The nearer the event, the whiter the text -- so the strip
    says "this is close" before anything has been read, and a month-away
    opposition sits back at the muted grey the rest of the chrome uses.
    later's grey is the one this started with, so the ramp is built by
    lifting the two nearer buckets, not by dimming what was there. */
 .coming-up[data-urgency="tonight"]{{--cu-accent:#ffd700;--cu-text:#e6edf3}}
 .coming-up[data-urgency="soon"]{{--cu-accent:#ff87ff;--cu-text:#b8c2cc}}
 .coming-up[data-urgency="later"]{{--cu-accent:#a186a6;--cu-text:#8b949e}}
 .cu-glyph{{color:var(--cu-accent,#ff87ff);flex-shrink:0}}
 .cu-body{{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
          white-space:nowrap;color:var(--cu-text,#8b949e)}}
 .cu-cta{{color:var(--cu-accent,#ff87ff);text-decoration:none;
         white-space:nowrap;flex-shrink:0}}
 .cu-cta:hover{{text-decoration:underline}}
 /* Same chevron the sphere's radiant HUD cycles multiple markers with
    (#radiant-hud-cycle) -- one pattern for "more than one thing, one
    line of room". [hidden] (not display:none) since JS is what decides
    whether more than one dismissal-filtered card is actually left. */
 .cu-cycle{{border:1px solid var(--cu-accent,#ff87ff);border-radius:4px;
           padding:1px 6px;font-size:11px;color:var(--cu-accent,#ff87ff);
           cursor:pointer;white-space:nowrap;flex-shrink:0;opacity:.75}}
 .cu-cycle:hover{{opacity:1}}
 .cu-cycle[hidden]{{display:none}}
 .cu-dismiss{{background:none;border:0;color:#6e7681;cursor:pointer;
             font-size:13px;line-height:1;padding:2px 4px;flex-shrink:0}}
 .cu-dismiss:hover{{color:#c9d1d9}}
 /* The day page. The Sun's arc is drawn at half height here (api._day_height)
    and everything below is what goes in the room that frees up.

    minmax(0,1fr) and not 1fr: a grid track sized 1fr refuses to go below the
    min-content of what is in it, and what is in this one is a stack of
    <pre> blocks one of which is always wider than the window. With a plain
    1fr the chart column pushed the panel off the right edge instead of the
    ladder picking a narrower rung. */
 /* 300px, and it is the drawing that sets it now rather than the text. The
    art is 45 characters wide (art.COLS, and the shower and eclipse discs
    match it) at 10px in a monospace face, where a character is 0.6em: 270px,
    plus 12px of padding either side. At the old 280px the last two columns
    of every planet were clipped off. The longest fact row -- "sun highest"
    against "last quarter · 36%" -- fits inside that with room to spare. */
 /* Every piece of the day page is the same object: a titled box. Where you
    are, the sky above you now, what tonight holds, what is coming up. The
    frame is what says they are four readings of one thing rather than a
    drawing with things stuck around it.

    A class and not a list of ids, because the list was already four long and
    the eclipse box made it five. Scoped under the day page's own ids all the
    same -- .day-box appears nowhere else, and #chart-stage is deliberately
    left alone: every chart on the site shares it, and the night chart, the
    object pages and /events would all have picked up a frame with no
    "tonight" box to match it. */
 .day-box{{background:#0d1117;border:1px solid #30363d;
          border-radius:6px;padding:12px}}
 /* min-width:0 is what lets the grid track go narrower than the widest rung
    stacked inside it; see the minmax note above. */
 /* The chart's own box is the deep black the page is, not the lighter grey
    the other boxes use. It is a window rather than a card: the drawing
    inside it is a night sky, and #0d1117 behind it both washed the faintest
    stars out and left the zenith inset -- which sits on rgba(4,6,10,.82) --
    looking like a darker patch stuck on top. Day and night alike, because
    the Sun's arc is drawn on the same sky. */
 #night-chart{{min-width:0;background:#04060a}}
 /* The chart keeps its frame -- it was borderless for a while, to buy back
    the 47px the border, the padding and the title cost on a page whose rows
    are chosen from its width with no idea how tall the window is -- but not
    its title. The headline directly above already says where and when, and
    "the sky above you now" over it said it a second time in smaller grey. */
 #night-chart>.box-head{{display:none}}
 /* Full width above the split: it is the one line that describes the whole
    page, and rationing it to the chart column was what put it inside the
    drawing in the first place. */
 #day-head{{margin:0 0 {BOX_GAP}px}}
 /* pre-wrap because the line is a rendered chart line: the dots between its
    parts are real spaces and collapsing them would close the gaps up. Wrap
    rather than scroll, because the box is picked to fit but a long place
    name can still push one rung over. */
 #day-head .dh{{white-space:pre-wrap;line-height:1.3;color:#e6ebf2}}
 /* The place and the moment, in bold. _compose_day paints them in their own
    colour precisely so they arrive as their own span and this rule has
    something to hold on to -- there is no other way to bold part of a line
    that reaches the page as pre-rendered ANSI. */
 #day-head .dh>span:first-child{{font-weight:700}}
 /* The animation's own copy of the line. Same type as the ladder's rungs,
    and the two swap places on html.anim-on so only ever one is on screen.
    Its own element rather than a thirteenth rung because the rungs are
    chosen by container queries on :nth-child -- a replacement line living
    among them would be shown at one width and hidden at all the others. */
 /* One line, never two, and its height is fixed rather than derived from
    what is in it. The rungs wrap (pre-wrap) because a long place name can
    push one over and a still page can afford to grow a row. A frame cannot:
    its line changes ninety-six times in fourteen seconds, and a line that
    wraps on some of them and not others moves the chart underneath it every
    time it does. The chart is the tallest thing on the page, so that is a
    full relayout per frame -- which is what an animation cannot pay for.
    The server already trims this line to the box, so there is nothing to
    wrap in the normal case, and overflow:hidden is the guard for the rest. */
 #day-head-live{{display:none;white-space:pre;overflow:hidden;
                 height:1.3em;line-height:1.3;
                 color:#e6ebf2;font-size:{DAY_HEAD_PX}px}}
 #day-head-live>span:first-child{{font-weight:700}}
 html.anim-on #day-head-ladder{{display:none}}
 html.anim-on #day-head-live{{display:block}}
 /* The "near X" hint, as a pin. It is the only thing identifying a bare
    pair of coordinates so it can never be dropped, and spelled out it is
    32 characters ahead of anything about the sky. The words are still
    there, in the tooltip and in the accessible name -- and still on the
    line itself in a terminal and in a PNG, neither of which has anywhere
    to hover. tabindex so it is reachable without a mouse.

    font-variant-emoji:text so a browser that has an emoji form of U+2691
    does not reach for it: this is a character on a line of characters, not
    a picture, and a colour glyph here would be the only one on the site. */
 .pin{{cursor:help;opacity:.75;font-variant-emoji:text}}
 .pin:hover,.pin:focus{{opacity:1;outline:none}}
 /* Which way to look -- see dim_directions. It sits inside the headline's
    own colour span, so the colour has to be set here to beat it. */
 .dir{{font-size:.82em;color:#9a9a9a}}
 /* The drawing in the panel. Its own <pre> for the same reason the object
    pages give theirs one: the line-height is what makes a character cell
    twice as tall as it is wide (art.CELL), and a planet set at any other
    line-height comes back as an ellipse. */
 .dt-art{{margin:0;font-size:10px;line-height:1.2em;white-space:pre;
         overflow:hidden}}
 .dt-art-box{{display:block;margin:0 0 12px;text-decoration:none;
             color:inherit}}
 a.dt-art-box:hover .dt-cap{{color:#c9d1d9;text-decoration:underline}}
 /* Clamped at two lines. "Venus, up tonight" is one and "Ibiza is in the
    path: 71 seconds of totality" is two, and a third would push a drawing
    out of its box. The two lines are only *reserved* where a caption can
    change under a box that has to keep its height -- the modal's frames
    take theirs from the grid instead and turn the reservation off, see
    .mf-frame .dt-cap. */
 .dt-cap{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
         overflow:hidden;margin-top:6px;min-height:2.7em;
         font-size:11.5px;line-height:1.35;color:#8b949e}}
 .box-head{{margin:0 0 8px;font-size:11px;font-weight:normal;
           letter-spacing:.08em;text-transform:uppercase;color:#6e7681}}
 /* One left edge for the box titles and the altitude axis under them.
    render_linear right-aligns the axis labels in a 5-column gutter, so "70°"
    starts exactly one character in and there is nothing to be done about
    that without breaking the ° signs out of their column. So the titles are
    moved to meet it instead.

    In px, not ch: a ch is the width of a "0" in the element's own font, and
    a title is 11px against the chart's 10px -- 1ch would be a different
    distance in each. The chart is CHART_FONT_PX and a monospace "0" is
    0.6em, so its gutter is 6px, and that is what the title needs. */
 #night-chart>.box-head,#day-head>.box-head,
 #day-head .dh{{padding-left:6px}}
 /* Grid on the row, not on the section, so the columns line up across rows
    while each row stays one <a> -- the whole row is the click target, which
    a grid of loose spans could not give without a link per cell. */
 /* The transparent left border is not decoration: a super-day row carries a
    2px accent one, and without a matching border here every ordinary row sat
    two pixels to the left of the highlighted ones -- so the dates, the
    glyphs and the names all stepped sideways at the edge of a group. */
 .nu-row{{display:grid;grid-template-columns:6.5em 1.2em minmax(0,1fr) auto;
         gap:0 10px;align-items:baseline;padding:4px 6px;
         border-left:2px solid transparent;border-radius:4px;
         text-decoration:none;font-size:12.5px;color:#c9d1d9}}
 .nu-row:hover{{background:#0d1117}}
 /* On now, against the dated rows around it. Green because it is the one
    line in the box that is about this minute rather than about a plan -- the
    same reason the terminal list paints it NOW_COL. */
 .nu-row.nu-now .nu-when,.nu-row.nu-now .nu-what{{color:#7ee787}}
/* What is on. A chip beside the search bar, opening a modal.
   Nothing is docked to the window: the chart is the page, and anything
   sitting at the bottom edge has to have room reserved for it, which comes
   straight off the drawing. */
/* Styled in full rather than leaning on .barpill: those rules are scoped to
   .cmdbar .barpill and this sits outside the form, so it inherited none of
   them and came out as the browser's default grey button. Border and text
   the same colour on the page's own black -- it is a notification, and the
   colour is the whole of the signal. */
 #on-pill{{margin-left:10px;flex:0 0 auto;background:#04060a;
           border:1px solid #7ee787;color:#7ee787;border-radius:4px;
           padding:4px 8px;font:inherit;font-size:12px;cursor:pointer;
           white-space:nowrap;line-height:1.2}}
 #on-pill:hover,#on-pill[aria-expanded="true"]{{border-color:#9ef2ab;
                                                color:#9ef2ab}}
 .modal{{position:fixed;inset:0;z-index:60;display:flex;
         align-items:flex-start;justify-content:center;
         padding:64px 16px 16px;background:rgba(4,6,10,.72)}}
 .modal[hidden]{{display:none}}
 /* Wide enough for the drawings. The frames sit two across, so the art gets
    a bit under half of this, and the art is art.COLS = 45 characters wide
    whatever it is showing -- at 560 that worked out at 8.6px a character,
    which is a Saturn you have to lean in to read. Width was always the
    binding constraint here and never height: the frames had room to spare
    underneath at every size tried. */
 .modal-card{{position:relative;width:100%;max-width:860px;
              background:#0d1117;border:1px solid #30363d;border-radius:8px;
              padding:16px 18px 18px;max-height:calc(100vh - 96px);
              overflow-y:auto}}
 .modal-bar{{display:flex;align-items:baseline;justify-content:space-between;
             gap:12px;margin:0 0 .7rem}}
 .modal-title{{margin:0;font-size:11px;font-weight:normal;letter-spacing:.08em;
               text-transform:uppercase;color:#6e7681}}
 .modal-close{{background:none;border:0;color:#6e7681;font:inherit;
               font-size:14px;cursor:pointer;padding:0 2px;line-height:1}}
 .modal-close:hover{{color:#c9d1d9}}
 /* Two frames, always two, always the same height. A modal that is a
    different shape on a quiet night than on the night of an eclipse is one
    the reader has to re-read every time. */
 .mf-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;
          margin:.2rem 0 .9rem}}
 /* A query container, so the drawing inside can be sized from the frame
    rather than from a number typed here. One rule then fits the art to the
    big frame and to a quad cell alike, and neither can drift out of the
    other's reach when the modal changes width. */
 .mf-frame{{border:1px solid #30363d;border-radius:6px;padding:10px;
            background:#04060a;min-width:0;display:flex;
            flex-direction:column;container-type:inline-size}}
 /* The drawing takes the room, the caption sits on the floor of the frame.
    Centred art over a bottom-left caption: the picture is the subject and
    wants the middle, the caption is a label and labels start at the left
    margin like every other line of text on the site. */
 /* margin-bottom:0 undoes the 12px .dt-art-box carries for the stack it
    used to live in. Here it is the only thing in the frame, and 12px under
    the caption is 12px the caption is not sitting on the floor -- which is
    the whole of what "bottom left" means. */
 .mf-frame>.dt-art-box{{display:flex;flex-direction:column;flex:1 1 auto;
                        min-height:0;margin-bottom:0;
                        text-decoration:none;color:inherit}}
 /* One plate, wherever characters are a picture: the object pages, the
    eclipse pages and the modal's frames. art.CELL lives in one rule instead
    of three, which is the point of it -- a drawing is built for a cell
    exactly twice as tall as it is wide, monospace glyphs run about 0.6em, so
    1.2em is that ratio and anything else turns every planet into an ellipse.

    The frame centres the block, never the line. With white-space:pre each
    line is its own line box, so text-align:center centres every line by its
    own width and shears the drawing apart down the middle. And never
    display:flex on the <pre>: its contents are the colour spans ansi_to_html
    emits, so flex makes a flex item of each and stacks them down the page --
    fifteen lines of shower came out 859px tall instead of 155.

    Callers add only what differs: a border and a floor height on an object
    page (.obj-art-frame), a size in frame-widths in the modal (.mf-art). */
 .art-frame{{display:flex;align-items:center;justify-content:center;
             min-width:0}}
 .art-plate{{margin:0;line-height:1.2em;white-space:pre;overflow:hidden;
             font-variant-ligatures:none;-webkit-font-smoothing:none}}
 /* Braille pinned to one cell. Nothing we bundle has U+2800, so the browser
    falls back to a font that does and those cells come out 1.135 times wider
    (BRAILLE_ADVANCE_EM). A drawing that is all braille only ends up uniformly
    wider, which is why this went unnoticed for so long -- but one that mixes
    braille with characters shears, because every cell after a braille cell
    slides right. On a deep-sky cluster plate that reached 1.35 cells, which
    is a mesh line no longer touching the star it links.

    1ch is the advance of "0" in whatever font the plate is actually using, so
    this is the ASCII cell width by definition rather than a number that has
    to be kept in step with one. Emitted by art_plate, and only on the
    drawings that mix -- see _pin_braille. */
 .art-plate .br{{display:inline-block;width:1ch}}
 /* The modal's own modifier: takes the slack over the caption, so the
    drawing has something to be centred in and the caption keeps the floor. */
 .art-fill{{flex:1 1 auto;min-height:0}}
 /* Same recipe as .obj-art on the object pages, and for the same reason:
    the wrapper centres the block and the <pre> is left alone.

    No text-align. With white-space:pre every line is its own line box, so
    text-align:center centres each line by *its own* width -- which is fine
    for a symmetric disc and wrong for everything else, and left the drawing
    reading as if it had been shoved against the left margin. .art-fill
    centres it as one block, the way .obj-art-frame does.

    Never display:flex on the <pre> either. Its contents are the colour spans
    ansi_to_html emits, so flex makes every one of them a flex item and
    stacks them down the page: fifteen lines of shower came out 859px tall
    instead of 155. */
 /* Only the size; the rest of what makes a drawing a drawing is .art-plate.
    A fallback in frame-widths for anything that reaches here without a size
    of its own: the art is at most art.COLS = 45 characters and a monospace
    "0" is a shade over 0.6em, so 45 x 0.612 = 27.5 frame-widths per em.
    _art_block overrides it per drawing, from the columns that drawing
    actually uses. */
 .mf-art{{font-size:calc(100cqw / 27.5)}}
 /* min-height:0 undoes the two lines .dt-cap reserves. That reservation was
    for the deck, whose caption changed every seven seconds and would have
    changed the box's height with it; these frames take their height from the
    grid instead, so the two lines bought nothing and cost a line of dead
    space under every caption -- the text sat at the top of a box a line and a
    half taller than itself, which is what "not at the bottom" was. Hugging
    its text, it sits on the floor and the drawing gets the room back. */
 .mf-frame .dt-cap{{margin-top:auto;padding-top:8px;text-align:left;
                    align-self:stretch;font-size:12px;line-height:1.3;
                    min-height:0;color:#c9d1d9}}
 /* Four bodies as four small frames, not four drawings loose in one big
    one. No border on the quad itself -- it is a 2x2 of the normal frame
    scaled down, occupying the footprint one frame would have had, and an
    outer border round them would be a fifth box nobody asked for. Same gap
    as .mf-row so the two halves line up. */
 /* Two rows always, not auto: with only two bodies up, auto rows gave each
    cell the full height of the frame beside it and put a tiny disc in the
    middle of a tall empty box. Pinned, a cell is half a frame whether there
    are two of them or four. */
 .mf-quad{{display:grid;grid-template-columns:1fr 1fr;
           grid-template-rows:1fr 1fr;gap:10px;min-width:0}}
 /* The cell clips, not the drawing. planet_art returns a 45-column canvas
    with the disc centred in it and _art_block trims blank rows but never
    columns, so the <pre> is always wider than a cell. Clipped by the <pre>
    itself it lost its right-hand side and the disc sat off to one side;
    centred as a whole block and clipped by the cell, the empty margins come
    off evenly and the disc lands in the middle. */
 .mf-cell{{padding:4px;overflow:hidden}}
 /* No size of its own any more: .mf-art is in frame-widths and a cell is a
    frame, so it fits itself. It was 5.5px, which was right for one modal
    width and wrong the moment that changed. */
 .mf-cell .mf-art{{overflow:visible}}
 /* Centred under a centred drawing. The big frame's caption is bottom-left
    because it is a sentence about an event; these are one word naming the
    picture above them. */
 .mf-cell .dt-cap{{padding-top:4px;font-size:10px;color:#8b949e;
                   text-align:center}}
 @media (max-width:520px){{.mf-row{{grid-template-columns:1fr}}}}
 .dw-head{{margin:.6rem 0 .3rem;font-size:11px;font-weight:normal;
           letter-spacing:.08em;text-transform:uppercase;color:#6e7681}}
 .dw-head:first-child{{margin-top:0}}
 .dw-art{{display:block;text-decoration:none;color:inherit;margin:0 0 .4rem}}
 @media (prefers-reduced-motion:reduce){{.dw-caret{{transition:none}}}}
 .nu-when{{color:#6e7681}}
 /* Centred in its own column. The glyphs are different widths -- a filled
    disc, a ring, a meteor, a four-pointed star -- so left-aligned they sat
    at four different distances from the name beside them. */
 .nu-glyph{{color:#ff87ff;text-align:center}}
 .nu-what{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
 .nu-where{{color:#6e7681;white-space:nowrap}}
 @media (max-width:640px){{.nu-where{{display:none}}}}
 .nu-more{{display:inline-block;margin:8px 0 0 6px;font-size:12px;
          color:#ffd700;text-decoration:none}}
 .nu-more:hover{{text-decoration:underline}}
/*WHATSNEW_CSS*/
</style></head><body>
{header}
<!-- skymap:coming-up-card
     api.coming_up_card_html(api.events_card(r)) -- "" (renders nothing) on
     most nights, see TEASER_DAYS in events.py. Above the drawer and the
     chart deliberately, so it reads before the sky rather than after it.
     Chart-page only; every other PAGE.format() call site passes "". -->
{coming_up_card}
<!-- skymap:whats-new
     api.whats_new_html(), spliced in at import (see the PAGE.replace below
     the template). Hidden until its own script opens it, which it does once
     a visitor and then never again unless WHATS_NEW_RELEASE changes. Up here
     rather than at the foot of the body on purpose: it is fixed over
     everything, so where it sits changes no layout, but its script has to
     register its keydown handler before the shared one at the bottom does or
     the arrow keys step the animation underneath an open dialog. -->
<!--WHATSNEW-->
<div class="w{wide_class}">
{controls}{shortcuts_hint}{body}
""" + FEEDBACK_BOX + """
<script>
// Which <pre> is "the chart" right now.
//
// On a chart page the body is a ladder of pre-rendered widths (api.py's
// CHART_LADDER) and CSS picks one, so there is no single element the rest
// of this script can hold onto -- and no id either, since an id has to be
// unique and there are several rungs. offsetParent is null for anything
// display:none'd, which is exactly the "did CSS pick this one" test, and it
// is a plain layout read with no measuring or reloading behind it.
//
// Every other page still emits a single block carrying both the id and the
// class (api.chart_pre), so the same call works there without either side
// knowing about the other.
window.skymapChartPre=function(){{
  var all=document.querySelectorAll('.chart-pre');
  for(var i=0;i<all.length;i++)if(all[i].offsetParent!==null)return all[i];
  return all[0]||null;
}};
function xtermHex(n){{
  n=parseInt(n,10);
  if(n<16){{
    var base=["000000","800000","008000","808000","000080","800080","008080","c0c0c0",
              "808080","ff0000","00ff00","ffff00","0000ff","ff00ff","00ffff","ffffff"];
    return "#"+base[n];
  }}
  if(n<232){{
    n-=16;
    var lv=[0,95,135,175,215,255];
    var r=lv[Math.floor(n/36)],g=lv[Math.floor(n/6)%6],b=lv[n%6];
    return "#"+[r,g,b].map(function(x){{return x.toString(16).padStart(2,'0');}}).join('');
  }}
  var v=8+(n-232)*10,h=v.toString(16).padStart(2,'0');
  return "#"+h+h+h;
}}
function escapeHtml(s){{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
// The browser half of api._anchor_markers. A chart is painted one cell at a
// time, so by the time a label is a string it is a row of separate colour
// spans with nothing left to match on -- sky.py puts these markers down
// while the row is being assembled and the label's extent is still known,
// and this is where they become anchors.
//
// It has to exist twice for the same reason skymapDimDirections does: a
// still chart is converted to HTML by Python and a frame by this, so
// anything Python does on the way out has to be done here too. Without it
// the markers arrived as literal text and a paused frame printed its own
// hrefs across the sky.
//
// After escaping, so a label's own characters can never be read as markup,
// and the anchor goes outside the colour spans so a linked label is
// character-for-character what it was.
function anchorMarkers(s){{
  var parts=s.split('\\x11'),out=parts[0];
  for(var i=1;i<parts.length;i++){{
    var chunk=parts[i],a=chunk.indexOf('\\x12');
    if(a<0){{out+=chunk;continue;}}
    var href=chunk.slice(0,a),rest=chunk.slice(a+1),b=rest.indexOf('\\x13');
    if(b<0){{out+=rest;continue;}}
    out+='<a class="sky-link" href="'+href+'">'+rest.slice(0,b)+'</a>'+
         rest.slice(b+1);
  }}
  return out;
}}

function ansiToHtml(text){{
  var re=/\\x1b\\[(?:38;5;(\\d+)|0)m/g;
  var out='',pos=0,open=false,m;
  while((m=re.exec(text))!==null){{
    out+=escapeHtml(text.slice(pos,m.index));
    pos=re.lastIndex;
    if(open){{out+='</span>';open=false;}}
    if(m[1]){{out+='<span style="color:'+xtermHex(m[1])+'">';open=true;}}
  }}
  out+=escapeHtml(text.slice(pos));
  if(open)out+='</span>';
  return anchorMarkers(out);
}}
// Playback runs off a buffer rather than painting each frame as it lands.
// That is what space and the arrow keys need: frames keep arriving while
// paused, and once the stream has finished the whole night sits in memory
// (96 frames of ~7 KB) to step through or replay without asking the server
// for it again. The tick's interval is handed over on the button as
// data-frame-ms so nothing here has to guess at it, and it is deliberately
// a little longer than the stream's own: playing slower than the frames
// arrive is what keeps the buffer ahead, so a frame is always ready when
// the tick comes and the browser is never waiting on the network to draw.
// The browser half of api.dim_directions. A frame arrives as ANSI and is
// turned into HTML here, so the server never sees the markup this works on
// and cannot add the spans itself.
//
// The patterns are the same four, deliberately: if one changes, change it
// in both places or the headline will look different while an animation is
// running than it does either side of one. Anchored the same way too --
// every match hangs off the fact it belongs to (a time, a height, a
// percentage, a shadow) so none of them can reach a stray compass letter in
// a place name.
function skymapDimDirections(h){{
  return h
    .replace(/([↑↓^]\\d{{2}}:\\d{{2}}) ([NSEW]{{1,3}})\\b/g,
             '$1 <span class="dir">$2</span>')
    .replace(/(\\d+°) (up|down) ([NSEW]{{1,3}})\\b/g,
             '$1 <span class="dir">$2 $3</span>')
    .replace(/(\\d+%) (down)\\b/g,'$1 <span class="dir">$2</span>')
    .replace(/(shadows [^ ]+) ([NSEW]{{1,3}})\\b/g,
             '$1 <span class="dir">$2</span>')
    .replace(/☀(?=[↑↓^]\\d{{2}}:\\d{{2}})/g,'<span class="dir">☀</span>');
}}

// One frame, split on its two markers and turned into the three pieces the
// page shows: the headline, the chart, and the zenith inset. Done once per
// frame and remembered, because the ANSI-to-HTML pass is the expensive part
// of showing one and a replay or a step backwards would otherwise pay for
// it again.
// The browser half of api.pin_near. The still page swaps "· near Lausanne,
// Vaud, Switzerland" for a pin carrying the words in its tooltip, because
// the hint is the longest thing on the line that can never be dropped -- it
// is the only thing identifying a bare pair of coordinates -- and spelled
// out it is 32 characters spent before the line has said anything about the
// sky. A frame's line is built the same way and has to be swapped the same
// way, or the hint would spring back into words the moment an animation
// started.
//
// The place name comes off the box rather than out of the line: it is the
// server's own r.place.near, already escaped, and matching it as text would
// mean guessing where the name ends.
function skymapPinNear(h){{
  var live=document.getElementById('day-head-live');
  var near=live&&live.getAttribute('data-near');
  if(!near)return h;
  var words=' \\u00b7 near '+near;
  if(h.indexOf(words)<0)return h;
  return h.replace(words,' <span class="pin" tabindex="0" role="img" '+
                   'aria-label="near '+near+'" title="near '+near+'">\\u2691</span>');
}}

function skymapAnimCook(raw){{
  var parts=raw.split({ZENITH_SLOT_JS});
  var body=parts[0],head='';
  var cut=body.indexOf({HEAD_SLOT_JS});
  if(cut>=0){{head=body.slice(0,cut);body=body.slice(cut+{HEAD_SLOT_JS}.length);}}
  return {{head:head?skymapPinNear(skymapDimDirections(ansiToHtml(head))):'',
          body:ansiToHtml(body),
          zen:parts.length>1?ansiToHtml(parts[1]):''}};
}}

// One frame onto the page: the three pieces a cooked frame has, into the
// three places they go. Every path that shows a frame comes through here --
// playing, stepping through the buffer, stepping to a moment the buffer
// does not hold -- so none of them can quietly grow a difference from the
// others. The elements are looked up rather than taken off the animation
// state, because stepping can happen before any animation exists.
function skymapPaintFrame(cooked){{
  var pre=window.skymapChartPre();
  if(!pre||!cooked)return;
  // anim-on is what swaps the headline's rung ladder for the live line. A
  // frame on screen without it means the chart moves and the headline above
  // it stays at the page's own moment, which is the disagreement this whole
  // rework was about.
  document.documentElement.classList.add('anim-on');
  var live=document.getElementById('day-head-live');
  if(live&&cooked.head)live.innerHTML=cooked.head;
  pre.innerHTML=cooked.body;
  var zen=document.getElementById('chart-zenith');
  if(zen&&cooked.zen)zen.innerHTML=cooked.zen;
}}

// The view has come to rest on a frame, so that frame gets its labels as
// links. Called from everywhere the movement stops -- pausing, stepping,
// arriving at the end of a run -- rather than from the pause alone, which
// is how stepping ended up showing plain labels on every frame but the one
// somebody happened to pause on.
function skymapSettle(){{
  if(window.skymapAnim&&window.skymapAnim.frames.length)skymapAnimLinks();
}}

function skymapAnimShow(i){{
  var A=window.skymapAnim;
  if(!A||!A.frames.length)return;
  A.at=Math.max(0,Math.min(A.frames.length-1,i));
  // The frame carries its own zenith inset after a marker (compose_frame),
  // because the page floats the inset over the chart's corner rather than
  // stacking it underneath -- so it arrives as a second piece rather than as
  // more rows. Without this the inset sat frozen at the moment the page was
  // built while the chart ran through the whole night under it.
  // Converted once and kept. A frame is about 37KB of markup and 800-odd
  // spans, and the ANSI-to-HTML pass over it is repeated work the moment
  // anybody steps back a frame, replays, or lets a 24-hour run loop -- and
  // it is the most expensive thing in this function. The cache is per
  // stream and dies with it.
  var cooked=A.cooked[A.at];
  if(!cooked)cooked=A.cooked[A.at]=skymapAnimCook(A.frames[A.at]);
  // The header goes to the headline box rather than into the drawing. The
  // frame carries it ahead of a marker of its own (compose_frame, browser
  // frames only) so the page can put it where the still page keeps its
  // line. It is the part of the page an animation is actually about: the
  // moment moves, the Sun crosses the horizon, blocks arrive and leave.
  skymapPaintFrame(cooked);
  // Entering theatre mode happens here, on the first frame to actually
  // reach the page, and not back when the button was pressed.
  //
  // A frame used to be two rows taller than the still chart -- it carried
  // its own header and the blank line under it -- and it arrives a fetch
  // later, about 250ms. Done at the press, the summary box collapsed
  // immediately and the chart jumped up 61px, then the frame landed and
  // pushed it back down 25. Two movements a quarter second apart, which on
  // the night page is the whole of what entering an animation looks like.
  // The day page had the same 429 -> 451 -> 641 stagger and got away with
  // it only because its zoom was animating over the top.
  //
  // The two rows are gone now: a browser frame hands its header to the
  // headline box instead of drawing it, so the frame and the still it
  // replaces are exactly the same height. The rest still holds -- both
  // changes land in one task, so the browser lays out once, and the zoom
  // measures a pre that already holds the frame it is about to show.
  if(!A.entered){{
    A.entered=true;
    document.documentElement.classList.add('anim-on');
    skymapAnimZoom(true);
  }}
  skymapAnimSyncPng();
}}

// "Share as a PNG" points at whatever frame is on screen. The link is
// written once when the page renders, so pausing on hour eleven of a run
// and sharing it exported the moment the animation *started* from -- the
// picture and the thing you were looking at were different skies, silently.
// skymapAnimFrameTime already works the moment out for the deep-sky
// refetch; this is the same answer put on the anchor.
function skymapAnimSyncPng(){{
  var A=window.skymapAnim;
  if(!A)return;
  // Looked up once per stream, not once per frame. This runs on every one
  // of ninety-six frames and the element it wants never changes; a document
  // query in that loop is work done ninety-five times for nothing.
  if(A.pngLink===undefined)
    A.pngLink=document.querySelector('.share-row a[href*="horizon.png"]');
  var link=A.pngLink;
  if(!link)return;
  var t=skymapAnimFrameTime(A.at);
  if(!t)return;
  if(!link.dataset.baseHref)link.dataset.baseHref=link.getAttribute('href');
  var u=link.dataset.baseHref.split('?');
  var qs=new URLSearchParams(u[1]||'');
  qs.set('t',t);
  link.setAttribute('href',u[0]+'?'+qs.toString());
}}
function skymapAnimAtEnd(A){{
  return A.done&&A.at>=A.frames.length-1;
}}
// What the hint line says while an animation is up. No "while animating"
// prefix -- it only appears while one is running, so saying so is redundant.
var SKYMAP_ANIM_HINT='<kbd>space</kbd> play/pause &middot; '+
  '<kbd>&larr;</kbd><kbd>&rarr;</kbd> step a frame &middot; '+
  '<kbd>d</kbd> deep sky';
// Theatre mode. While an animation runs the chart grows to fill the room
// between the command bar and the shortcut bar, and every other box on the
// page collapses out of its way at the same time -- one motion, the chart
// expanding into space the others are giving up, the way a video goes to
// theatre mode. Not a full-screen overlay: the two bars stay where they
// are, because they are how you stop it and how you know where you are.
//
// Twenty-four hours of sky is the one thing here worth looking at rather
// than reading, and at the rung a two-column day page picks, it was playing
// in about a third of the screen.
//
// Two things have to be true for this to work at all.
//
// The rung must not change. The animation writes its frames into one
// specific <pre>, and #chart-ladder picks which <pre> is visible from its
// own width -- which is about to change a lot. So the animating rung is
// tagged and CSS pins it on, regardless of what the ladder would otherwise
// choose. Without that the frames keep arriving into an element that is now
// display:none and the chart simply stops.
//
// It grows by font size, because that is real layout: the <pre> gets
// bigger, the stage round it gets bigger, and the box round that grows to
// contain it. A plain transform is drawn after layout, so the box keeps its
// old height and the enlarged chart hangs out of the bottom of its own
// border -- which is what the first version did.
//
// But animating font size is what made the second version stagger. Every
// frame of it re-lays out eight thousand characters on the main thread,
// which no amount of easing will smooth out.
//
// So both, in the order FLIP does it: put the final size on instantly, and
// then use a transform to *undo* that jump and animate back to nothing. The
// layout reflows exactly once, at the start; what actually animates is a
// transform, which the compositor can do on its own. Position is in there
// too, not just scale -- the chart moves up and left as the boxes round it
// go, and animating only the scale would make it jump there first.
//
// Not re-rendered at that size: the frames are already buffered as text at
// one width, and asking the server for the whole run again would throw that
// away and cost 96 more renders to show the same sky.
// The day page, fitted to the window it is actually in.
//
// The server picks the chart's row count (api._day_height) with no idea how
// tall anybody's window is, and the drawing is text at a fixed size rather
// than something that can flex -- so out of the box the page leaves a hand's
// width of black under it on a big monitor and scrolls on a small laptop.
// This measures the room left between the chart and the shortcut bar and
// scales the chart's font until it fills it, which pulls the boxes down to
// the bottom of the page at any size.
//
// The rung is pinned while it does, for the same reason theatre mode pins
// it: #chart-ladder chooses which <pre> to show from its width in `ch`, and
// `ch` is a multiple of the font size this function is about to change --
// left alone they chase each other. Unpinned first on every run, so a real
// resize still lets CSS choose a rung for the new width before this scales
// whatever it chose.
// First, Last, Invert, Play. `change` puts the page in its final state with
// no transition at all; everything before and after it is measurement and a
// transform. The element ends the run with no inline transform or transition
// of its own, so nothing here can leave a style behind that a later resize
// then has to fight.
function skymapFlip(el,change){{
  var first=el.getBoundingClientRect();
  el.style.transition='none';
  el.style.transform='';
  change();
  var last=el.getBoundingClientRect();
  if(!last.width||!last.height){{el.style.transition='';return;}}
  var sx=first.width/last.width,sy=first.height/last.height;
  el.style.transformOrigin='top left';
  el.style.transform='translate('+(first.left-last.left)+'px,'+
                     (first.top-last.top)+'px) scale('+sx+','+sy+')';
  // Force the browser to take that in before the transition is armed,
  // otherwise it coalesces both styles and there is nothing to animate.
  void el.offsetWidth;
  el.style.transition='transform '+SKYMAP_ANIM_MS+'ms cubic-bezier(.22,.61,.36,1)';
  el.style.transform='';
  setTimeout(function(){{el.style.transition='';el.style.transformOrigin='';}},
             SKYMAP_ANIM_MS+40);
}}
var SKYMAP_ANIM_MS = {ANIM_WIDE_MS};
// The chart's fitted state, stashed while theatre mode has it.
var SKYMAP_BEFORE_ANIM = null;
var SKYMAP_FIT_MIN = 0.8, SKYMAP_FIT_MAX = 2.2;
function skymapFitChart(){{
  var root=document.documentElement;
  var ladder=document.getElementById('chart-ladder');
  // The column the chart lives in. One page shape now, day and night alike:
  // where does the chart's own box currently end, and how much room is left
  // under it.
  var main=document.getElementById('night-chart');
  // Day page only, and never while theatre mode owns the chart.
  //
  // The test is the class, not window.skymapAnim. That object outlives the
  // run on purpose -- the arrow keys step back into the buffered frames
  // after it ends -- so gating on it meant the fit never ran again once an
  // animation had been played, and the page stayed at the un-fitted size
  // until a reload.
  // anim-on rather than anim-wide, for the same reason Escape uses it: the
  // question is whether an animation owns the chart, not whether the chart
  // happened to grow. (Unreferenced while the fit is switched off -- see the
  // note at the bottom of this script -- but wrong is wrong either way, and
  // this is the gate that would let it measure a chart mid-animation.)
  if(!ladder||!main||root.classList.contains('anim-on'))return;
  var was=ladder.querySelector('.fit-rung');
  if(was){{was.classList.remove('fit-rung');was.style.fontSize='';}}
  root.classList.remove('fit-on');
  var pres=ladder.querySelectorAll('.chart-pre'),pre=null;
  for(var i=0;i<pres.length;i++){{if(pres[i].offsetParent!==null){{pre=pres[i];break;}}}}
  if(!pre)return;
  var base=parseFloat(getComputedStyle(pre).fontSize)||10;
  if(!base)return;
  var foot=document.querySelector('.kbd-hint');
  var limit=(foot?foot.getBoundingClientRect().top:window.innerHeight)-{BOX_GAP};

  // Measured, not derived. The first version worked out the room from the
  // shortcut bar minus the events box minus a padding it had been told
  // about, and got it wrong in both directions -- the chart grew through
  // the bar, and after an animation it came back too small. There are a
  // title, two borders, two paddings, a gap and a caption between the
  // <pre> and the bottom of the column, and any of them changing puts an
  // arithmetic version out again.
  //
  // So: ask the column where it currently ends, ask how much room is left
  // under it, and scale the chart by however much of itself that is.
  function span(){{return main.getBoundingClientRect().bottom;}}
  function scale(k){{
    pre.classList.add('fit-rung');
    root.classList.add('fit-on');
    pre.style.fontSize=(base*k)+'px';
  }}
  var rh=pre.getBoundingClientRect().height;
  var rw=pre.getBoundingClientRect().width;
  if(!rh||!rw)return;
  var k=(rh+(limit-span()))/rh;
  // Never wider than the column it sits in, whatever the height says.
  k=Math.min(k,main.getBoundingClientRect().width/rw);
  k=Math.max(SKYMAP_FIT_MIN,Math.min(SKYMAP_FIT_MAX,k));
  if(Math.abs(k-1)<0.02)return;
  scale(k);

  // Then check the answer rather than trusting it. One correction is
  // enough: the relationship is linear in everything except the wrapping
  // of the events box, which does not wrap.
  var over=span()-limit;
  if(over>0.5){{
    var h=pre.getBoundingClientRect().height;
    var fix=Math.max(SKYMAP_FIT_MIN/k,(h-over)/h);
    scale(k*fix);
    // If even the floor overflows, the window is too short for this page
    // and the honest answer is to let it scroll rather than shrink the
    // chart into illegibility.
    if(span()-limit>0.5&&k*fix<=SKYMAP_FIT_MIN+0.001){{
      pre.classList.remove('fit-rung');
      root.classList.remove('fit-on');
      pre.style.fontSize='';
    }}
  }}
}}
function skymapFitLater(){{
  clearTimeout(window.skymapFitT);
  window.skymapFitT=setTimeout(skymapFitChart,120);
}}
function skymapAnimZoom(on){{
  var root=document.documentElement;
  var A=window.skymapAnim;
  var pre=A&&A.pre;
  if(!pre)return;
  if(!on){{
    if(!root.classList.contains('anim-wide'))return;
    skymapFlip(pre,function(){{
      root.classList.remove('anim-wide');
      pre.classList.remove('anim-rung');
      // Exactly what was on the page before, put back. Not a fresh
      // measurement: three attempts at recomputing the fit here all failed
      // for the same reason, which is that this runs in the worst possible
      // moment to measure anything -- mid-transition, with the chart's own
      // text being swapped back around it and three classes moving. The
      // page was already right before theatre mode started, so the only
      // thing that has to survive is a note of what "right" was.
      if(SKYMAP_BEFORE_ANIM){{
        pre.style.fontSize=SKYMAP_BEFORE_ANIM.font;
        if(SKYMAP_BEFORE_ANIM.rung)pre.classList.add('fit-rung');
        if(SKYMAP_BEFORE_ANIM.on)root.classList.add('fit-on');
        SKYMAP_BEFORE_ANIM=null;
      }}else{{
        pre.style.fontSize='';
      }}
    }});
    return;
  }}
  var rw=pre.scrollWidth,rh=pre.scrollHeight;
  var base=parseFloat(getComputedStyle(pre).fontSize)||10;
  if(!rw||!rh||!base)return;
  var head=document.querySelector('.header-row');
  var foot=document.querySelector('.kbd-hint');
  // The gutter the page already uses down its left edge, read off the
  // header rather than hardcoded, so this follows the layout instead of
  // duplicating a number from it.
  var gut=head?head.getBoundingClientRect().left:16;
  var top=head?head.getBoundingClientRect().bottom:0;
  var bot=foot?foot.getBoundingClientRect().top:window.innerHeight;
  // Room above and below, plus the chart box's own padding and the title
  // line inside it. Under-filling slightly is the safe direction: a chart
  // one row too tall would put the shortcut bar across its horizon.
  var availW=window.innerWidth-gut*2-30;
  var availH=(bot-top)-30-52;
  var k=Math.min(availW/rw,availH/rh);
  // Nothing to gain under a few percent, and on a phone the chart is
  // already the width of the screen -- collapsing the whole page to grow it
  // by a hair is a worse trade than leaving it alone.
  if(k<1.05)return;
  // What the page looked like a moment ago, which is what it goes back to.
  SKYMAP_BEFORE_ANIM={{font:pre.style.fontSize,
                      rung:pre.classList.contains('fit-rung'),
                      on:root.classList.contains('fit-on')}};
  skymapFlip(pre,function(){{
    pre.classList.add('anim-rung');
    root.classList.add('anim-wide');
    pre.style.fontSize=(base*k)+'px';
  }});
}}
function skymapScrubRestore(){{
  // The stepped chart, put back. Its own baseline, because stepping can
  // happen with no animation ever having started and A.base only exists
  // once one has.
  var S=window.skymapScrub;
  S.off=0;
  if(S.base===null)return;
  var pre=window.skymapChartPre();
  if(pre)pre.innerHTML=S.base;
  S.base=null;
}}

function skymapAnimRestore(){{
  // Put the chart back the way it was found. The last frame is 24 hours
  // past the moment the page is actually about, so leaving it up ends the
  // animation on a chart that quietly disagrees with every heading, link
  // and time on the page around it. Stepping back with an arrow brings the
  // frames straight back.
  //
  // Before the early return below, and outside skymapAnimZoom: that one
  // bails immediately unless the chart was actually zoomed, so anything
  // left to it never runs on the night page. Every way out of an animation
  // comes through here, so this is the one place the class reliably comes
  // off again.
  document.documentElement.classList.remove('anim-on');
  skymapAnimZoom(false);
  if(window.skymapSetHint)window.skymapSetHint(null);
  var A=window.skymapAnim;
  // A stepped chart with no animation behind it has its own baseline, and
  // it is the only one there is on that path -- an arrow can be the first
  // thing anybody presses.
  if(!A||A.base===null){{skymapScrubRestore();return;}}
  A.pre.innerHTML=A.base;
  skymapScrubRestore();
}}
function skymapAnimPlay(on){{
  var A=window.skymapAnim;
  if(!A)return;
  A.playing=on;
  A.btn.textContent=on?'⏸ pause':(skymapAnimAtEnd(A)?'▶ replay':'▶ resume');
  if(on)skymapAnimTick();else{{clearTimeout(A.timer);skymapSettle();}}
}}

// The paused frame's labels, as links to the object pages. Asked for on
// pause and never during playback: the still chart has had them all along,
// but a running animation replaces the whole chart six times a second and
// an anchor in a frame nobody can click is markup for its own sake -- 144
// frames of it.
//
// The same shape the deep-sky key uses: ask the stream for one frame at
// this moment, take the first whole one, cancel the rest. Kept once fetched
// (A.linked), so pausing on the same frame twice costs one request. The
// plain frame stays in A.plain for the same reason it does there.
function skymapAnimLinks(){{
  var A=window.skymapAnim;
  if(!A||!A.frames.length||A.loadingLinks)return;
  // Never while it is moving. This is the invariant that lets the chase at
  // the bottom of this function call back into it from anywhere: a frame
  // gets links because the view has come to rest on it, not because
  // playback happened to pass through.
  if(A.playing)return;
  var at=A.at;
  if(A.linked[at])return;
  var t=skymapAnimFrameTime(at);
  var live=A.url;
  if(!t||!live)return;
  var url=live.replace(/([?&])t=[^&]*/,'$1t='+encodeURIComponent(t))
              .replace(/([?&])animate=[^&]*/,'$1animate=1')+'&links=1'+
              (A.dsoOn[at]?'&dso=1':'');
  A.loadingLinks=true;
  skymapFetchFrame(url).then(function(frame){{
    A.loadingLinks=false;
    // Only if it is still the frame on screen and still paused. The reply
    // can land after somebody has stepped on or pressed play again, and
    // swapping a frame in underneath them would be a visible jump.
    if(frame&&!A.playing&&A.at===at){{
      A.linked[at]=true;
      A.frames[at]=frame;
      delete A.cooked[at];
      skymapAnimShow(at);
    }}
    // And then chase wherever the view actually is. Three quick presses of
    // an arrow used to leave the last of them plain: the first started a
    // request, the second and third were turned away by the busy flag, and
    // by the time the first landed it was answering a frame nobody was
    // looking at any more. Asking again from here is the only place that
    // knows the request has finished.
    skymapSettle();
  }}).catch(function(){{A.loadingLinks=false;}});
}}
function skymapAnimTick(){{
  var A=window.skymapAnim;
  if(!A)return;
  clearTimeout(A.timer);
  if(!A.playing)return;
  if(A.at<A.frames.length-1)skymapAnimShow(A.at+1);
  else if(A.done){{skymapAnimPlay(false);skymapAnimRestore();return;}}
  // Caught up with a stream still arriving: keep the timer alive and wait
  // rather than stopping, or playback would end at whatever had landed.
  A.timer=setTimeout(skymapAnimTick,A.ms);
}}
// The wall-clock time a frame is drawn for: the stream's own t= plus the
// step it is along. Formatted by hand rather than through toISOString,
// which would convert to UTC -- t= is local time at the place, and the
// arithmetic here is pure wall clock. (A place crossing a DST boundary
// mid-animation would be shifted by the reader's own rules rather than its
// own, an hour out for one frame of a 24-hour run.)
// The moment `i` steps from the page's own, as the local wall clock the
// server wants. Works with or without a running animation: the base moment
// and the step are both on the animate button, which is there from the
// moment the page loads. That is what lets an arrow work on arrival.
function skymapFrameTime(i){{
  var btn=document.getElementById('animate-btn');
  if(!btn)return null;
  var qs=(btn.getAttribute('data-live-url')||'').split('?')[1]||'';
  var t=new URLSearchParams(qs).get('t');
  if(!t)return null;
  var d=new Date(t);
  if(isNaN(d.getTime()))return null;
  var step=parseInt(btn.getAttribute('data-step-min'),10)||10;
  d.setMinutes(d.getMinutes()+i*step);
  function p(n){{return (n<10?'0':'')+n;}}
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+
         'T'+p(d.getHours())+':'+p(d.getMinutes());
}}
function skymapAnimFrameTime(i){{return skymapFrameTime(i);}}

// One frame out of a stream, and then stop reading. Three callers want
// exactly this -- deep sky on the paused frame, its labels as links, and
// stepping to a moment the buffer does not hold -- and they each had their
// own copy of the pump. A one-hour request is the smallest the server will
// take, so it would keep sending; cancelling as soon as the first frame is
// whole means it renders one or two rather than the six that hour is.
function skymapFetchFrame(url){{
  return fetch(url).then(function(resp){{
    var reader=resp.body.getReader(),dec=new TextDecoder(),buf='';
    function pump(){{
      return reader.read().then(function(res){{
        buf+=res.value?dec.decode(res.value,{{stream:true}}):'';
        var parts=buf.split('\\x1b[2J\\x1b[H');
        if(parts.length>2&&parts[1].trim()){{reader.cancel();return parts[1];}}
        if(res.done)return parts.length>1&&parts[1].trim()?parts[1]:null;
        return pump();
      }});
    }}
    return pump();
  }});
}}

// The URL for one frame at `t`, at the width CSS actually chose. The width
// is not in data-live-url -- the ladder picks it and only this element
// knows which rung won -- so anything asking for a frame has to add it or
// get a chart two thirds the size of the one on screen.
function skymapFrameUrl(t,extra){{
  var btn=document.getElementById('animate-btn');
  if(!btn||!t)return null;
  var url=btn.getAttribute('data-live-url');
  if(!url)return null;
  var pre=window.skymapChartPre();
  var cols=pre&&pre.getAttribute('data-cols');
  if(cols&&!/[?&]w=/.test(url))url+='&w='+cols;
  return url.replace(/([?&])t=[^&]*/,'$1t='+encodeURIComponent(t))
            .replace(/([?&])animate=[^&]*/,'$1animate=1')+(extra||'');
}}
// Deep sky for the frame on screen. One frame, not the whole run: "d" here
// means "show me more of what I am looking at", and the run is 96 frames of
// server work. The stream is asked for the paused moment and cancelled as
// soon as its first frame is whole, so the server renders one or two rather
// than the four its one-hour minimum would otherwise produce.
function skymapAnimDeepSky(done){{
  var A=window.skymapAnim;
  if(!A||!A.frames.length||A.loadingDso)return;
  if(A.playing)skymapAnimPlay(false);
  var at=A.at;
  // A toggle, not a one-way switch. Both versions of the frame are kept --
  // the stream's own and the deep-sky one -- so pressing d again puts the
  // plain frame back, and a third press costs no request at all.
  if(A.dsoOn[at]){{
    A.frames[at]=A.plain[at];
    // The cooked copy is keyed by index and this index now holds different
    // text, so it has to go with it -- otherwise pressing d showed the
    // frame that was cached rather than the one just swapped in.
    delete A.cooked[at];
    A.dsoOn[at]=false;
    skymapAnimShow(at);
    if(done)done(true,false);
    return;
  }}
  if(A.dsoFrames[at]!==undefined){{
    A.plain[at]=A.frames[at];
    A.frames[at]=A.dsoFrames[at];
    delete A.cooked[at];
    A.dsoOn[at]=true;
    skymapAnimShow(at);
    if(done)done(true,true);
    return;
  }}
  var t=skymapAnimFrameTime(at);
  var live=A.url;
  if(!t||!live)return;
  var url=live.replace(/([?&])t=[^&]*/,'$1t='+encodeURIComponent(t))
              .replace(/([?&])animate=[^&]*/,'$1animate=1')+'&dso=1';
  A.loadingDso=true;
  skymapFetchFrame(url).then(function(frame){{
    A.loadingDso=false;
    if(!frame)return;
    // Both kept: the stream's own frame to go back to, the deep-sky one to
    // return to without asking twice. The buffer holds whichever is showing,
    // so stepping away and back finds the frame as it was left.
    A.plain[at]=A.frames[at];
    A.dsoFrames[at]=frame;
    A.dsoOn[at]=true;
    A.frames[at]=frame;
    delete A.cooked[at];
    if(A.at===at)skymapAnimShow(at);
    if(done)done(true,true);
  }}).catch(function(){{
    A.loadingDso=false;
    if(done)done(false);
  }});
}}
// Stepping only -- the "frame 12/96" hint is raised by the key handler,
// which is where flashHint actually lives (it is local to that IIFE, not a
// global, so calling it from here threw ReferenceError on every arrow).
function skymapAnimStep(d){{
  var A=window.skymapAnim;
  if(!A||!A.frames.length)return;
  if(A.playing)skymapAnimPlay(false);
  skymapAnimShow(A.at+d);
}}

// Stepping by time rather than through a buffer, which is what an arrow
// has to mean in the two places the buffer cannot answer: before an
// animation has been started at all, and earlier than the moment it starts
// from. A stream only ever runs forward from the page's own moment, so
// without this the left arrow had nothing behind it and both arrows did
// nothing until somebody had pressed space.
//
// One request per press, for one frame. The alternative -- starting a
// whole day's stream because somebody pressed an arrow -- is 144 frames of
// server work to show one.
window.skymapScrub={{off:0,busy:false,base:null}};

function skymapScrubTo(off){{
  var S=window.skymapScrub;
  if(S.busy)return;
  var url=skymapFrameUrl(skymapFrameTime(off),'&links=1');
  if(!url)return;
  var pre=window.skymapChartPre();
  if(!pre)return;
  // The chart as it was found, kept once, so Escape has something to put
  // back. Taken before the first frame lands rather than after, or the
  // baseline would be a frame.
  if(S.base===null)S.base=pre.innerHTML;
  S.busy=true;
  skymapFetchFrame(url).then(function(frame){{
    S.busy=false;
    if(!frame)return;
    S.off=off;
    skymapPaintFrame(skymapAnimCook(frame));
    // skymapSetHint and not flashHint: the latter is local to the keyboard
    // handler's own closure and calling it from out here throws.
    if(window.skymapSetHint)
      window.skymapSetHint(skymapFrameTime(off).replace('T',' ')+
                           '  ·  [←][→] step  ·  [space] play  ·  [esc] back');
  }}).catch(function(){{S.busy=false;}});
}}

// One arrow, whichever state the page is in. Inside a running stream the
// buffer already holds what is ahead and stepping through it costs
// nothing; everything else -- no stream yet, or a step back past its first
// frame -- is a moment the buffer does not have, and gets asked for.
function skymapStepFrame(d){{
  var A=window.skymapAnim;
  if(A&&A.frames.length&&A.at+d>=0){{
    skymapAnimStep(d);
    window.skymapScrub.off=A.at;
    // Stopped on this one, so it gets its labels as links -- the same way
    // pausing does. Without this, stepping through a buffer showed plain
    // labels on every frame except whichever one somebody paused on.
    skymapSettle();
    return true;
  }}
  skymapScrubTo(window.skymapScrub.off+d);
  return false;
}}
function skymapAnimate(btn){{
  // Live preview plays right in the chart itself from the same streaming
  // ?animate= text the CLI uses. "Share as a GIF" is visible the whole
  // time (see skymapPollGifCapacity, kicked off on page load) -- rendering
  // only actually happens if it's clicked -- see skymapRenderGif -- since
  // that's real Pillow work, not free to do for every single viewer.
  var A=window.skymapAnim;
  if(A){{
    // Second press is play/pause, and replay once it has run out -- from
    // the buffer, so a rewatch costs the server nothing at all. Before the
    // first frame has landed there is nothing to toggle yet, and this must
    // not fall through to starting a second stream -- easy to trigger now
    // that space starts it, since space is a key people tap twice.
    if(!A.frames.length)return;
    if(skymapAnimAtEnd(A)&&!A.playing)skymapAnimShow(0);
    skymapAnimPlay(!A.playing);
    return;
  }}
  var liveUrl=btn.getAttribute('data-live-url');
  var pre=window.skymapChartPre();
  // Which width the stream should come at. The server can't put it in
  // data-live-url any more: on a laddered page it didn't choose the width,
  // CSS did, and only this element knows which rung won. Without it the
  // frames arrive at DEFAULT_HORIZON_WIDTH and the chart visibly shrinks
  // the moment animate starts on any window wider than the first rung.
  // An explicit ?w= page is not laddered and already has its width in the
  // URL, so data-cols is absent there and this leaves the URL alone.
  var cols=pre&&pre.getAttribute('data-cols');
  if(cols&&!/[?&]w=/.test(liveUrl))liveUrl+='&w='+cols;
  // cooked: converted frames, keyed by index (see skymapAnimCook). live and
  // zen: the two boxes a frame writes into besides the chart, resolved once
  // here rather than looked up on every frame.
  //
  // url: this URL, width and all, and not the button's data-live-url. The
  // width is worked out here from whichever ladder rung CSS chose and was
  // only ever added to the local copy -- so anything that later re-read the
  // attribute asked for a frame at the default width and got a chart half
  // the size of the one it was replacing. Both refetches (deep sky, and the
  // links on a paused frame) read this instead.
  A=window.skymapAnim={{frames:[],cooked:{{}},at:-1,playing:true,done:false,
                       timer:null,entered:false,url:liveUrl,
                       live:document.getElementById('day-head-live'),
                       zen:document.getElementById('chart-zenith'),
                       btn:btn,pre:pre,base:pre.innerHTML,loadingDso:false,
                       loadingLinks:false,linked:{{}},
                       plain:{{}},dsoFrames:{{}},dsoOn:{{}},
                       ms:parseInt(btn.getAttribute('data-frame-ms'),10)||250,
                       stepMin:parseInt(btn.getAttribute('data-step-min'),10)||15}};
  // Enabled throughout now: while the stream runs this button is the pause
  // control, so greying it out would take the mouse-only way to pause with
  // it.
  btn.disabled=false;btn.textContent='⏸ pause';
  // Entering theatre mode -- folding the summary box away and giving the
  // chart the room -- is deliberately not done here. It waits for the first
  // frame, in skymapAnimShow, so the box going and the frame's own header
  // arriving are one movement rather than two a fetch apart. Both paths in
  // still meet there: the button and the space bar call this same function,
  // so they cannot start two different things.
  if(window.skymapSetHint)window.skymapSetHint(SKYMAP_ANIM_HINT);
  fetch(liveUrl).then(function(resp){{
    var reader=resp.body.getReader();
    var decoder=new TextDecoder();
    var buf='';
    function pump(){{
      return reader.read().then(function(res){{
        if(res.done){{
          // The tail is the last frame -- nothing follows it to split on.
          if(buf.trim())A.frames.push(buf);
          return;
        }}
        buf+=decoder.decode(res.value,{{stream:true}});
        var parts=buf.split('\\x1b[2J\\x1b[H');
        buf=parts.pop();
        for(var i=0;i<parts.length;i++){{
          if(parts[i].trim())A.frames.push(parts[i]);
        }}
        return pump();
      }});
    }}
    skymapAnimTick();
    return pump();
  }}).then(function(){{
    A.done=true;
    if(!A.playing)A.btn.textContent=skymapAnimAtEnd(A)?'▶ replay':'▶ resume';
  }}).catch(function(){{
    A.done=true;clearTimeout(A.timer);
    // Same restore as a clean finish -- a stream that dies halfway leaves a
    // half-played chart that is even less about now than the last frame is.
    skymapAnimRestore();
    window.skymapAnim=null;
    btn.disabled=false;btn.textContent='animate failed, try again';
  }});
}}

function skymapPollGifCapacity(gifBtn){{
  // Greys the button out before a click would just 503, rather than only
  // finding out after. One check on page load is enough for that -- a
  // stale read is harmless, since skymapRenderGif already catches a 503
  // on click and shows "render failed, try again" re-enabling the button.
  // This used to also re-poll every 4s for as long as the tab stayed open,
  // which cost every visitor ~15 rate-limited requests a minute just for
  // having a chart page open, with no correctness benefit over a single
  // check (capacity opening back up mid-visit is already covered by the
  // click-time catch above).
  var status=document.getElementById('gif-status');
  if(gifBtn.dataset.rendering==='1'||gifBtn.dataset.ready==='1')return;
  fetch('/gif-capacity').then(function(r){{return r.json();}}).then(function(d){{
    if(gifBtn.dataset.rendering==='1'||gifBtn.dataset.ready==='1')return;
    gifBtn.disabled=!d.available;
    if(status)status.textContent=d.available?'':
      'Too many GIFs rendering right now, please wait a few seconds';
  }}).catch(function(){{}});
}}

function skymapRenderGif(btn){{
  // Rendering is fast enough now (on-demand, not pre-built for every
  // viewer) that a plain status line is enough -- no spinner or facts
  // needed to fill the wait. window.open() here used to silently get
  // popup-blocked: it ran inside the fetch's .then(), well after the click
  // that triggered it, so browsers no longer treated it as user-initiated.
  // A real <a> the visitor clicks themselves never has that problem.
  var gifUrl=btn.getAttribute('data-gif-url');
  var status=document.getElementById('gif-status');
  btn.dataset.rendering='1';
  btn.disabled=true;
  if(status)status.textContent='Rendering…';
  fetch(gifUrl).then(function(r){{
    if(!r.ok)throw new Error('render failed');
    return r.headers.get('X-Gif-Id');
  }}).then(function(gifId){{
    btn.dataset.rendering='0';
    btn.disabled=false;
    if(gifId&&status){{
      btn.dataset.ready='1';
      status.innerHTML='<a href="/animate/'+gifId+'.gif" target="_blank" rel="noopener">View GIF</a>';
    }}else if(status){{
      status.textContent='render failed, try again';
    }}
  }}).catch(function(){{
    if(status)status.textContent='render failed, try again';
    btn.dataset.rendering='0';
    btn.disabled=false;
  }});
}}
// Fit the chart to the window on arrival and whenever it changes size.
// Debounced, because a drag-resize fires this dozens of times a second and
// each run measures layout. Both hooks are no-ops on any page with no chart
// column -- skymapFitChart returns immediately without one.
//
// Two frames before the first run, and it matters: the fit reads whichever
// rung is visible and *pins* it. Called straight through, that is the
// ladder's first rung -- the narrowest chart there is -- because the
// container queries that pick a wider one have not been evaluated yet. It
// then scaled eighty columns of sky up to fill the window, which is what
// "the chart is broken" looked like.
// NOT CALLED. skymapFitChart works by pinning whichever rung is visible and
// scaling its font, and pinning is the part that keeps going wrong: three
// times now it has left the page with the ladder hidden, or a zero-width
// stage with the zenith inset stranded at the far left, and none of it
// reproduces from the server -- the markup is correct every time.
//
// A chart that is sometimes missing is a worse page than a chart that
// sometimes leaves room at the bottom, so it stays off until it can be
// watched in a real browser rather than reasoned about. The function and
// its CSS are left in place, unreferenced, because the measuring half of
// it is sound and it is the wiring that needs the work.
//
//   requestAnimationFrame(function(){{requestAnimationFrame(skymapFitChart);}});
//   window.addEventListener('resize', skymapFitLater);
//   window.addEventListener('orientationchange', skymapFitLater);

// The "what is on" pill and its modal. Open and shut, and nothing else --
// the modal is fixed over everything, so opening it moves no layout and
// there is none to restore.
(function(){{
  var pill=document.getElementById('on-pill'),m=document.getElementById('on-modal');
  if(!pill||!m)return;
  function set(on){{
    m.hidden=!on;
    pill.setAttribute('aria-expanded',on?'true':'false');
    if(on){{var c=document.getElementById('on-close');if(c)c.focus();}}
    else pill.focus();
  }}
  pill.addEventListener('click',function(){{set(m.hidden);}});
  var close=document.getElementById('on-close');
  if(close)close.addEventListener('click',function(){{set(false);}});
  // The backdrop, but only the backdrop: a click that started inside the
  // card and ended outside it is a drag, not a dismissal.
  m.addEventListener('click',function(e){{if(e.target===m)set(false);}});
  document.addEventListener('keydown',function(e){{
    if(e.key!=='Escape'||m.hidden)return;
    // Not while an animation owns the page -- that Escape is for leaving it.
    if(document.documentElement.classList.contains('anim-on'))return;
    e.stopPropagation();set(false);
  }});
}})();
/*CMDBAR_JS*/
(function(){{
  // Drawer (SPEC-command-bar.md #9) -- present on every page (see
  // header_html/controls_html), so no page-specific gating, only the
  // element lookups are null-safe.
  var trigger=document.getElementById('drawer-trigger');
  var drawer=document.getElementById('drawer');
  var closeBtn=document.getElementById('drawer-close');
  if(!trigger||!drawer)return;
  window.skymapCloseDrawer=function(){{
    drawer.classList.remove('open');
    trigger.setAttribute('aria-expanded','false');
    trigger.textContent='☰';
  }};
  var openDrawer=function(){{
    drawer.classList.add('open');
    trigger.setAttribute('aria-expanded','true');
    trigger.textContent='✕';
  }};
  trigger.addEventListener('click',function(){{
    if(drawer.classList.contains('open'))window.skymapCloseDrawer();else openDrawer();
  }});
  if(closeBtn)closeBtn.addEventListener('click',window.skymapCloseDrawer);
  // No backdrop (a deliberate choice -- the chart stays fully visible while
  // the drawer is open), so a click anywhere outside it is what closes it
  // instead.
  document.addEventListener('mousedown',function(e){{
    if(!drawer.classList.contains('open'))return;
    if(drawer.contains(e.target)||e.target===trigger)return;
    window.skymapCloseDrawer();
  }});
  // A click on the page used to hand focus straight back to the command
  // bar, ready to type. It was removed: the keyboard shortcuts are ignored
  // while a text field has focus (they must be, or typing a place with a
  // space in it would pause the animation), so parking focus in #q after
  // every click meant the shortcuts were dead most of the time and the way
  // to revive them was to click something excluded from the rule. It also
  // needed an exception per element that wanted to keep its own focus --
  // #q itself, the drawer, #findbar, #animate-btn -- and each new control
  // was another exception waiting to be found the hard way.
  //
  // Focusing the command bar is still one Tab away (handled by the shortcut
  // block below), and clicking the field itself obviously still works. Both
  // are deliberate, rather than a side effect of clicking somewhere else
  // entirely.
}})();
(function(){{
  // Keyboard shortcuts -- ignored while typing in a field (except Escape,
  // which exists precisely to get you out of one), and while a modifier is
  // held, so this can't hijack a real browser/OS shortcut. KBD's keys are
  // only ever set by server.py where the corresponding toggle is actually
  // meaningful for the current view (e.g. all of them are omitted on the
  // Sun's-arc day view, where dso/nolines/quadrant don't apply) -- a
  // missing key here is exactly what makes the shortcut silently no-op
  // rather than needing every page to special-case which keys apply.
  var KBD={kbd_urls};
  // Fixed 4x3 layout, matches sky.py's quadrant_grid() -- always these 12
  // cells in this order, regardless of facing/span, so no server round trip
  // is needed to know the picker's shape.
  var GRID=[['A','B','C','D'],['E','F','G','H'],['I','J','K','L']];
  var pick={{active:false,row:0,col:0}};
  var hintEl=document.querySelector('.kbd-hint');
  var hintHTML=hintEl?hintEl.innerHTML:null;
  var baseHint=hintHTML;
  var hintRestoreTimer=null;
  // Swaps what the hint line says at rest, which is how the animation puts
  // its own transport keys there while it runs and takes them away again
  // when it stops -- space and the arrows only do anything while there are
  // frames, so advertising them the rest of the time is noise on a line
  // with room for one row. Global because the animation code lives outside
  // this IIFE. Passing null restores the page's own hint.
  window.skymapSetHint=function(html){{
    if(!hintEl)return;
    hintHTML=(html===null?baseHint:html);
    // Not while a flash is up -- its own restore timer will land on the
    // new baseline in a moment.
    if(!hintRestoreTimer)hintEl.innerHTML=hintHTML;
  }};
  // Transient status in the same spot as the keyboard hint itself (e.g.
  // "Locating..." / a geolocation error) instead of an alert() -- restores
  // the real hint text after ms, clearing any earlier pending restore so
  // two flashes in quick succession don't stomp on each other.
  function flashHint(msg,ms){{
    if(!hintEl)return;
    if(hintRestoreTimer)clearTimeout(hintRestoreTimer);
    hintEl.innerHTML=msg;
    hintRestoreTimer=setTimeout(function(){{
      if(hintHTML!==null)hintEl.innerHTML=hintHTML;
      hintRestoreTimer=null;
    }},ms||4000);
  }}
  // Share as a GIF is visible from the start now (not just after clicking
  // animate) -- greys itself out here the same way it always has whenever
  // the server's at its concurrent-render cap. Null-safe: only present on
  // chart pages.
  var gifBtn=document.getElementById('gif-btn');
  if(gifBtn)skymapPollGifCapacity(gifBtn);
  // color:#ffff00 is the one ANSI colour (sky.py's QL / api.py's QUAD_C,
  // 256-colour 226) used exclusively for quadrant-grid letters -- nothing
  // else in the chart ever renders with it, so it doubles as a reliable way
  // to find the 12 grid-letter glyphs without the server tagging them.
  function quadSpans(){{
    // Scoped to the rung on screen rather than every .chart-pre on the
    // page: the hidden rungs carry the same grid letters in the same
    // colour, and picking one of those would paint the highlight onto an
    // element nobody can see.
    var pre=window.skymapChartPre();
    var spans={{}}, all=pre?pre.querySelectorAll('span'):[];
    for(var i=0;i<all.length;i++){{
      var s=all[i];
      if(s.style.color==='rgb(255, 255, 0)'&&/^[A-L]$/.test(s.textContent))spans[s.textContent]=s;
    }}
    return spans;
  }}
  function paintPick(){{
    var spans=quadSpans(), old=document.querySelector('.quad-pick');
    if(old)old.classList.remove('quad-pick');
    var span=spans[GRID[pick.row][pick.col]];
    if(span)span.classList.add('quad-pick');
  }}
  function startPick(){{
    pick.active=true;pick.row=0;pick.col=0;
    paintPick();
    if(hintEl)hintEl.innerHTML='Pick a quadrant: ←↑→↓ move &middot; '+
      '<kbd>enter</kbd> zoom in &middot; <kbd>esc</kbd> cancel';
  }}
  function stopPick(){{
    pick.active=false;
    var old=document.querySelector('.quad-pick');
    if(old)old.classList.remove('quad-pick');
    if(hintEl&&hintHTML!==null)hintEl.innerHTML=hintHTML;
  }}
  if(location.hash==='#pick'&&Object.keys(quadSpans()).length>0){{
    startPick();
    history.replaceState(null,'',location.pathname+location.search);
  }}
  document.addEventListener('keydown', function(e){{
    if(e.metaKey||e.ctrlKey||e.altKey)return;
    var tag=(document.activeElement&&document.activeElement.tagName)||'';
    if(e.key==='Escape'){{
      // Out of the animation first, and it takes the animation with it. It
      // is the only state on the page that covers everything else, so
      // anything else Escape might have meant is behind it.
      //
      // anim-on, not anim-wide. anim-wide is only set when the chart had
      // room to grow into, which the night chart never does -- so Escape
      // fell straight through to the drawer and there was no way to leave a
      // night animation with the keyboard at all.
      if(document.documentElement.classList.contains('anim-on')){{
        if(window.skymapAnim)skymapAnimPlay(false);
        skymapAnimRestore();
        window.skymapAnim=null;
        var abx=document.getElementById('animate-btn');
        if(abx){{abx.disabled=false;abx.textContent='▶ animate';}}
        return;
      }}
      // Closing the drawer takes priority over blurring whatever's
      // focused inside it -- one Escape dismisses the whole panel, not
      // just whichever field happened to have focus.
      var drawerEl=document.getElementById('drawer');
      if(drawerEl&&drawerEl.classList.contains('open')&&window.skymapCloseDrawer){{
        window.skymapCloseDrawer();
        return;
      }}
      var ae=document.activeElement;
      if(ae&&ae!==document.body){{ae.blur();return;}}
      if(pick.active){{stopPick();return;}}
      var q=new URLSearchParams(location.search).get('quadrant');
      if(q&&KBD.grid){{location.href=KBD.grid;return;}}
      return;
    }}
    if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT')return;
    if(pick.active){{
      if(e.key==='ArrowLeft'){{e.preventDefault();pick.col=Math.max(0,pick.col-1);paintPick();return;}}
      if(e.key==='ArrowRight'){{e.preventDefault();pick.col=Math.min(3,pick.col+1);paintPick();return;}}
      if(e.key==='ArrowUp'){{e.preventDefault();pick.row=Math.max(0,pick.row-1);paintPick();return;}}
      if(e.key==='ArrowDown'){{e.preventDefault();pick.row=Math.min(2,pick.row+1);paintPick();return;}}
      if(e.key==='Enter'){{
        e.preventDefault();
        var params=new URLSearchParams(location.search);
        params.set('quadrant', GRID[pick.row][pick.col]);
        location.href=location.pathname+'?'+params.toString();
        return;
      }}
    }}
    // Animation transport. Only bound while there is an animation to
    // control, so space and the arrows keep scrolling the page everywhere
    // else -- and after the quadrant picker above, which owns the arrows
    // whenever it is up.
    if(window.skymapAnim&&window.skymapAnim.frames.length){{
      if(e.key===' '||e.key==='Spacebar'){{
        e.preventDefault();
        var ab=document.getElementById('animate-btn');
        if(ab)ab.click();
        return;
      }}
      if(e.key==='ArrowLeft'||e.key==='ArrowRight'){{
        e.preventDefault();
        if(skymapStepFrame(e.key==='ArrowLeft'?-1:1)){{
          var A=window.skymapAnim;
          flashHint('frame '+(A.at+1)+'/'+A.frames.length+
                    (A.done?'':', still loading'));
        }}
        return;
      }}
      // d normally navigates to the quadrant+dso view, which would take the
      // buffer and the paused position with it. While there are frames, it
      // loads deep sky into the frame on screen instead.
      if(e.key==='d'){{
        e.preventDefault();
        flashHint('Deep sky…',10000);
        skymapAnimDeepSky(function(ok,on){{
          var A=window.skymapAnim;
          flashHint(ok?'Deep sky '+(on?'on':'off')+' &middot; frame '+
                       (A.at+1)+'/'+A.frames.length
                     :'Deep sky failed for this frame');
        }});
        return;
      }}
    }}
    // Arrows with no animation running. They used to do nothing until
    // somebody had pressed space, which made the one obvious way to look at
    // a different moment invisible -- and even then a stream only runs
    // forward from the page's own moment, so the left arrow had nothing
    // behind it at all. Both directions ask for a single frame now; see
    // skymapStepFrame.
    //
    // Bound only where there is an animate button, so arrows keep scrolling
    // the page on every view that has no frames to step through.
    if(e.key==='ArrowLeft'||e.key==='ArrowRight'){{
      if(document.getElementById('animate-btn')){{
        e.preventDefault();
        skymapStepFrame(e.key==='ArrowLeft'?-1:1);
        return;
      }}
    }}
    if(e.key==='Tab'){{
      // Tab only. "p" used to do this too and was dropped: a single letter
      // that jumps focus into a text field is exactly the thing that leaves
      // every key after it going to the field instead of the page, and Tab
      // is what people already reach for.
      //
      // Tab reaches here at all only because of the guard just above --
      // once focus is actually in #q (an INPUT), this whole branch is
      // skipped and #q's own keydown handler owns Tab instead (accepting a
      // ghost completion). Outside of an input/textarea/select, though,
      // this does take over Tab's normal "move to the next focusable
      // element" job -- pressing it while a button or link is focused jumps
      // back into the command bar instead of advancing, same tradeoff the
      // single-letter shortcuts (f/a/g/...) already accept everywhere else
      // on this page.
      var place=document.getElementById('q');
      if(place){{e.preventDefault();place.focus();place.select();}}
      return;
    }}
    // No 'f'. It meant "jump to the find field", and there is no longer a
    // find field for it to jump to -- tab reaches the one bar that replaced
    // it. Keeping f as a second key for the same input would have spent a
    // single letter on a duplicate, and single letters are scarce here.
    if(e.key==='m'){{
      e.preventDefault();
      if(!navigator.geolocation){{
        flashHint('Geolocation is not available in this browser.');
        return;
      }}
      flashHint('Locating…',15000);
      navigator.geolocation.getCurrentPosition(function(pos){{
        var lat=pos.coords.latitude.toFixed(4);
        var lon=pos.coords.longitude.toFixed(4);
        location.href='/'+lat+','+lon;
      }},function(err){{
        flashHint('Could not get your location'+(err&&err.message?': '+err.message:'')+'.');
      }},{{timeout:10000}});
      return;
    }}
    // Space starts it. Once it is running the block further up owns space
    // for play/pause, so one key covers the whole thing the way it does in
    // any video player. Only where there is an animate button to press --
    // every other page keeps space for scrolling -- and never while a field
    // has focus, which the INPUT guard above already handles, so typing a
    // place with a space in it still types a space.
    if(e.key===' '||e.key==='Spacebar'){{
      var ab=document.getElementById('animate-btn');
      if(ab&&!ab.disabled){{e.preventDefault();ab.click();}}
      return;
    }}
    // g is the golden-hour layer on the day chart. It used to share as a
    // GIF; that moved to v when golden hour arrived, since g is the letter
    // people reach for and the GIF button is right there on screen anyway.
    if(e.key==='g'&&KBD.golden){{location.href=KBD.golden;return;}}
    if(e.key==='v'){{
      var gb=document.getElementById('gif-btn');
      if(gb&&!gb.disabled)gb.click();
      return;
    }}
    if(e.key==='z'){{
      if(pick.active)return;
      if(Object.keys(quadSpans()).length>0){{startPick();return;}}
      if(KBD.grid){{location.href=KBD.grid+'#pick';}}
      return;
    }}
    if(e.key==='d'&&KBD.quadrant){{location.href=KBD.quadrant;return;}}
    // i hides the zenith inset. It floats over the chart's top-right
    // corner, which is the emptiest band of sky most nights and not all of
    // them -- so this is how you get the stars underneath it back. Kept in
    // localStorage: someone who does not want it never wants it, and making
    // them press i on every chart would be the annoying half of a toggle.
    if(e.key==='i'){{
      if(!document.getElementById('chart-zenith'))return;
      var off=document.documentElement.classList.toggle('no-inset');
      try{{localStorage.setItem('skymap.inset',off?'0':'1');}}catch(err){{}}
      flashHint(off?'Zenith inset hidden &middot; <kbd>i</kbd> to bring it back'
                  :'Zenith inset shown');
      return;
    }}
  }});
}})();
(function(){{
  // Applied before first paint (this script runs in <head>, see PAGE) so a
  // reader who turned the inset off never sees it flash on and disappear.
  try{{
    if(localStorage.getItem('skymap.inset')==='0')
      document.documentElement.classList.add('no-inset');
  }}catch(e){{}}
}})();
</script>
</div></body></html>"""

# Spliced in rather than written out by hand, so the ch breakpoints and the
# widths actually rendered into the page can only ever come from the one
# CHART_LADDER tuple. Braces are doubled on the way in because PAGE is a
# .format() template and the generated CSS is full of real ones -- this runs
# once at import, so the escaping costs nothing per request.
PAGE = PAGE.replace("/*LADDER*/",
                    chart_ladder_css().replace("{", "{{").replace("}", "}}"))

# The command bar's CSS and script, kept out here rather than inline in PAGE
# so build_sky_html.py can splice the same text into the static demo page.
# That script used to keep its own hand copy of both, with a comment asking
# whoever changed one to remember the other. Nobody did: the copy pill and
# the ghost-text field were replaced by the help pill and the dropdown, and
# the demo went on wiring up elements that no longer existed, so its search
# bar quietly did nothing at all. The header markup was un-copied for this
# same reason once already; this is the rest of it.
#
# Braces stay doubled, because both consumers are .format() templates.
CMDBAR_CSS = """ /* Command bar -- an inline-editable "$ curl skymap.sh/<place>" line.
    Everything up to and including the "/" is fixed, decorative text; #q is
    a real input laid out inline with it via the same monospace text
    engine, so it never has to be kept in sync with an overlay. min-width:0
    on .field/input (not this element -- see below) is required for flex
    children to shrink/scroll instead of blowing out the row -- the default
    flex min-width is auto, not 0. */
 /* This is the page's main CTA -- it shouldn't visibly grow and shrink on
    every keystroke (or every time a ghost completion of a different length
    pops in or out from under the debounced /complete fetch). The min-width
    floor absorbs that: .grow (a flex:1 spacer between the cursor and the
    copy button) eats the slack whenever content is narrower than the
    floor, pinning "copy" to the bar's right edge instead of letting the
    whole bar visibly resize. min(560px,90vw) so it still fits a narrow
    viewport instead of forcing horizontal overflow. */
 /* height+box-sizing:border-box (not just matching padding) is what
    actually guarantees .find-field below renders exactly this tall --
    letting it emerge from padding+content, the original approach, is at
    the mercy of font-metric/nested-element quirks that can differ by a
    pixel or two between browsers. An explicit shared number on both
    can't drift apart. */
 .cmdbar{{display:inline-flex;align-items:center;background:#0d1117;
         border:1px solid #30363d;border-radius:6px;padding:9px 12px;
         margin:0;color:#7ee787;font-size:13px;cursor:text;
         max-width:100%;min-width:min(560px,90vw);
         box-sizing:border-box;height:45px}}
 .cmdbar .prompt{{color:#6e7681;margin-right:6px}}
 .cmdbar .fixed{{white-space:pre}}
 .cmdbar .curlword{{color:#6e7681}}
 .cmdbar .field{{display:inline-flex;min-width:0;max-width:100%}}
 .cmdbar input{{background:transparent;border:0;color:#e6edf3;font:inherit;
               padding:0;margin:0;min-width:0;max-width:100%;outline:none}}
 .cmdbar .measure{{position:absolute;visibility:hidden;white-space:pre;left:-9999px}}
 .cmdbar .grow{{flex:1}}
 .cmdbar .barpill{{background:none;border:1px solid #30363d;color:#6e7681;
               border-radius:4px;padding:4px 8px;margin-left:10px;
               font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}}
 .cmdbar .barpill:hover,.cmdbar .barpill[aria-expanded="true"]{{
               border-color:#7ee787;color:#7ee787}}
 /* The bar, its dropdown and its help panel are one stack: both panels hang
    off the bottom edge of the bar, so they need a positioning parent that is
    the bar's width and nothing else's. .header-row cannot be it -- it also
    holds the nav row, and "100% of that" is the whole page. */
 .bar-wrap{{position:relative;display:inline-flex;flex-direction:column;
           min-width:0;max-width:100%}}
 .cursor{{display:inline-block;width:.55em;height:1.15em;margin-left:1px;
         background:#7ee787;vertical-align:-0.2em;
         animation:blink 1.06s step-end infinite}}
 .cmdbar.focused .cursor{{visibility:hidden;animation:none}}
 @keyframes blink{{0%,50%{{opacity:1}}50.01%,100%{{opacity:0}}}}
 @media (prefers-reduced-motion: reduce){{
   .cursor{{animation:none;opacity:.55}}
 }}
 /* Suggestions under the bar, grouped by kind. The list is the merge of two
    completion endpoints plus the page names, so a row can be a city, an
    object or a page and the group heading is the only thing telling them
    apart -- worth a real heading rather than an icon, since "Venus the
    planet" and "Venus, Texas" are otherwise the same word twice. */
 .bar-dropdown{{position:absolute;top:100%;left:0;margin:4px 0 0;padding:4px;
                 background:#0d1117;border:1px solid #30363d;border-radius:6px;
                 min-width:min(320px,100%);max-width:100%;max-height:300px;
                 overflow-y:auto;z-index:30;list-style:none}}
 .bar-dropdown[hidden]{{display:none}}
 .bar-group{{padding:6px 8px 2px;font-size:10.5px;letter-spacing:.09em;
            text-transform:uppercase;color:#6e7681}}
 .bar-option{{display:flex;align-items:center;gap:8px;padding:6px 8px;
              border-radius:4px;cursor:pointer;font-size:13px;color:#c9d1d9}}
 /* One box for every mark in the list, whatever it is. font-size and
    line-height are pinned HERE rather than only on the size classes: a
    crescent or a triangle carries no size class, so it was inheriting the
    row's 13px and an unpinned line-height, which put it on a different
    baseline and in a taller row than the dots above and below it.
    inline-flex centres it in both directions instead of relying on the
    text baseline, which the three dot sizes and the two marks do not
    share. */
 /* Fixed pixels, not em. The size classes below change this element's own
    font-size, and 1.2em is measured against THAT -- so the box was 8px wide
    for a village and 13px for a dark-sky site, and every name in the list
    started at a slightly different x. A mark is a fixed slot; only what
    sits inside it changes size. */
 .bar-option .glyph{{width:16px;height:16px;flex-shrink:0;color:#6e7681;
                    display:inline-flex;align-items:center;
                    justify-content:center;font-size:11px;line-height:1}}
 /* Town, city, major city. Only the size changes; the box does not. */
 .bar-option .glyph.sz1{{font-size:7px}}
 .bar-option .glyph.sz2{{font-size:10px}}
 .bar-option .glyph.sz3{{font-size:13px;color:#8b949e}}
 .bar-option:hover,.bar-option.active{{background:#1c2128}}
 /* Opens under the bar, in the same stack as the dropdown and never at the
    same time as it. Not a centred overlay: it answers a question about the
    box directly above it, and covering the page to do that would be a
    bigger interruption than the question deserves. */
 .search-help{{position:absolute;top:100%;left:0;margin:4px 0 0;
              padding:14px 16px;background:#0d1117;border:1px solid #30363d;
              border-radius:6px;min-width:min(420px,100%);max-width:100%;
              z-index:31;font-size:12.5px;line-height:1.5}}
 .search-help[hidden]{{display:none}}
 .search-help dl{{display:grid;grid-template-columns:auto 1fr;
                 gap:.5rem .9rem;margin:0}}
 .search-help dt{{color:#7ee787;white-space:nowrap}}
 .search-help dd{{margin:0;color:#c9d1d9}}
 /* The examples are the useful part for somebody who does not know what to
    type, but they are not the answer -- quieter, and on their own line so
    the four category names still read as a list. */
 .search-help .eg{{display:block;color:#6e7681;font-size:11.5px;
                  margin-top:.1rem}}
 .search-help-slash{{margin:.9rem 0 0;padding-top:.75rem;
                    border-top:1px solid #21262d;color:#8b949e;
                    font-size:12px;line-height:1.55}}
 .search-help-slash b{{color:#7ee787;font-weight:normal}}
 .search-help-more{{display:inline-block;margin-top:.75rem;padding-top:.7rem;
                   border-top:1px solid #21262d;width:100%;
                   color:#58a6ff;text-decoration:none;font-size:12px}}
 .search-help-more:hover{{text-decoration:underline}}"""

CMDBAR_JS = """(function(){{
  // Command bar: auto-size (hidden-measure technique -- field-sizing:content
  // isn't portable yet) + click-anywhere-to-focus, so the whole bar reads as
  // one editable command line rather than decorative text bolted onto a
  // separate input box, plus ghost-text completion against GET /complete
  // (SPEC-command-bar.md #3-4). Present on every page (see header_html), so
  // no page-specific gating here -- only the element lookups are null-safe.
  var bar=document.getElementById('bar');
  var q=document.getElementById('q');
  var measure=document.getElementById('measure');
  var dropdown=document.getElementById('bar-dropdown');
  var helpPill=document.getElementById('help-pill');
  var helpPanel=document.getElementById('search-help');
  if(bar&&q&&measure){{
    var size=function(){{
      measure.textContent=q.value||'';
      q.style.width=(measure.offsetWidth+2)+'px';
    }};
    var matches=[];
    // Strips accents the same way api.py's norm_name does server-side --
    // without this, plain toLowerCase() rejects the server's own correctly
    // accent-folded matches: 'zürich'.startsWith('zur') is false in JS
    // (ü !== u as characters), so typing the ASCII "zur" would never show
    // the "ich" ghost for "Zürich" at all.
    var fold=function(s){{return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();}};
    var PAGES=/*PAGES*/;
    var active=-1;

    // The bar holds a path, so "/" splits it: everything up to the last
    // slash is settled, and only the tail is being typed. On "Tokyo/ven"
    // the prefix is "Tokyo/" and the tail is "ven".
    var prefixOf=function(v){{
      var i=v.lastIndexOf('/');
      return i<0?'':v.slice(0,i+1);
    }};
    var tailOf=function(v){{
      var i=v.lastIndexOf('/');
      return i<0?v:v.slice(i+1);
    }};
    // Each segment encoded on its own, so the slashes that separate them
    // survive. encodeURIComponent on the whole string would turn the one
    // character doing the work into %2F.
    var toPath=function(v){{
      return '/'+v.split('/').map(encodeURIComponent).join('/');
    }};

    // Two endpoints rather than one merged one, deliberately: /complete is
    // static city data cached for a week at the edge, /complete/objects has
    // to expire hourly because the Moon's glyph tracks its real phase.
    // Merging them server-side would drag the cities down to the Moon's
    // cache lifetime for no gain -- the browser can hold two promises.
    // "47.37,8.55" and "-24.63, -70.4" -- the same thing the place resolver
    // accepts, checked here only so the dropdown can say "yes, that is a
    // usable answer" instead of going silent because no city is spelled
    // like a number. Range-checked, so 91,0 is not offered as a place.
    var COORD=/^(-?\\d{{1,3}}(?:\\.\\d+)?)\\s*,\\s*(-?\\d{{1,3}}(?:\\.\\d+)?)$/;
    var asCoords=function(v){{
      var m=COORD.exec(v.trim());
      if(!m)return null;
      var la=parseFloat(m[1]), lo=parseFloat(m[2]);
      if(!(Math.abs(la)<=90&&Math.abs(lo)<=180))return null;
      return la+','+lo;
    }};

    // After a slash the answer can only be an object: the second segment of
    // a path is what you are looking at, never where you are standing. So
    // "Tokyo/ven" offers Venus and no cities at all, which is also why the
    // place suggestions are not merely ranked lower there -- a city would
    // build /Tokyo/Paris, and there is no such page.
    // A crescent for somewhere you go at night, a silhouette for a
    // monument, a dot for somewhere people live. Both are plain BMP
    // characters present in the two bundled fonts as well as every system
    // one, so neither needs a PNG_SUBSTITUTE entry.
    var PLACE_MARK={{dark:'\\u263e', unesco:'\\u25b2'}};

    var buildItems=function(cities,objects,v){{
      var out=[],pre=prefixOf(v),tail=tailOf(v),f=fold(tail);
      // Names, not paths. The prefix is already sitting in the bar a few
      // pixels above the list, so repeating it on every row says nothing
      // and makes the names harder to scan.
      objects.forEach(function(o){{
        var name=o.q||o.name;
        out.push({{group:'Objects',label:name,glyph:o.glyph,color:o.color,
                  href:toPath(pre+name)}});
      }});
      if(pre)return out;
      var coords=asCoords(v);
      if(coords){{
        out.push({{group:'Places',label:coords+'  (coordinates)',
                  glyph:'\\u25ce',color:'',size:0,href:toPath(coords)}});
      }}
      cities.forEach(function(c){{
        // Either shape: {{name,size}} from the current server, or a bare
        // string from a week-old cached response (see /complete's docstring).
        var name=(typeof c==='string')?c:c.name;
        var size=(typeof c==='string')?0:(c.size||0);
        var mark=(typeof c==='string')?null:PLACE_MARK[c.kind];
        // The row reads "Tokyo"; the slash only appears once it is chosen,
        // in the bar, where it is an invitation to name an object. Landing
        // on /Tokyo/ rather than /Tokyo is free: they are one page.
        //
        // A named site keeps its mark at full size; only the city dot is
        // scaled by population, and a scaled crescent would read as a phase
        // rather than as a category.
        out.push({{group:'Places',label:name,glyph:mark||'\\u25cf',color:'',
                  size:mark?0:size,href:toPath(name)+'/'}});
      }});
      PAGES.forEach(function(p){{
        if(fold(p).startsWith(f))
          out.push({{group:'Pages',label:p,glyph:'\\u2192',color:'',href:'/'+p}});
      }});
      return out;
    }};

    var renderDropdown=function(){{
      if(!dropdown)return;
      dropdown.innerHTML='';
      if(!matches.length){{
        dropdown.hidden=true;
        q.setAttribute('aria-expanded','false');
        return;
      }}
      var seen='';
      matches.forEach(function(it,i){{
        if(it.group!==seen){{
          seen=it.group;
          var h=document.createElement('li');
          h.className='bar-group';
          h.setAttribute('role','presentation');
          h.textContent=it.group;
          dropdown.appendChild(h);
        }}
        var li=document.createElement('li');
        li.className='bar-option'+(i===active?' active':'');
        li.setAttribute('role','option');
        var g=document.createElement('span');
        // The dot is one character at three CSS sizes rather than three
        // different characters. Picking bullet/circle/large-circle by
        // population would put the size at the mercy of whichever font the
        // browser reaches for, and they are not drawn to a consistent scale
        // across families; scaling one glyph is exact everywhere.
        g.className='glyph'+(it.size?' sz'+it.size:'');
        if(it.color)g.style.color=it.color;
        g.textContent=it.glyph||'';
        var n=document.createElement('span');
        n.textContent=it.label;
        li.appendChild(g);
        li.appendChild(n);
        // mousedown, not click: it fires before the input's blur, so a
        // mouse pick doesn't race the blur-closes-dropdown handler.
        li.addEventListener('mousedown',function(e){{
          e.preventDefault();
          location.href=it.href;
        }});
        dropdown.appendChild(li);
      }});
      dropdown.hidden=false;
      q.setAttribute('aria-expanded','true');
    }};

    var closeDropdown=function(){{
      matches=[];active=-1;
      if(dropdown){{dropdown.hidden=true;dropdown.innerHTML='';}}
      q.setAttribute('aria-expanded','false');
    }};

    var completeAbort=null, completeTimer=null;
    var fetchMatches=function(){{
      if(completeAbort)completeAbort.abort();
      var v=q.value.trim();
      // Matched on the tail, not the whole path: "Tokyo/ven" is a two-letter
      // search for "ven", not a nine-letter one for a city called
      // "Tokyo/ven". Without this the dropdown went blank the moment a
      // slash was typed, which looked exactly like the bar giving up.
      var pre=prefixOf(v), tail=tailOf(v).trim();
      if(tail.length<2){{closeDropdown();return;}}
      completeAbort=new AbortController();
      var sig=completeAbort.signal;
      var enc=encodeURIComponent(tail.slice(0,24));
      // Either endpoint failing leaves the other's results usable rather
      // than emptying the list -- an aborted fetch is the normal case here,
      // one per keystroke. Past a slash the city half is not asked for at
      // all: nothing would be done with the answer.
      Promise.all([
        pre?Promise.resolve([]):
        fetch('/complete?q='+encodeURIComponent(tail.toLowerCase().slice(0,24)),
              {{signal:sig}}).then(function(r){{return r.json();}})
              .catch(function(){{return [];}}),
        fetch('/complete/objects?q='+enc,{{signal:sig}})
              .then(function(r){{return r.json();}})
              .catch(function(){{return [];}})
      ]).then(function(res){{
        // Guard against a slow response for an earlier, shorter prefix
        // landing after the reader has kept typing.
        if(q.value.trim()!==v)return;
        matches=buildItems(res[0]||[],res[1]||[],v);
        active=-1;
        renderDropdown();
      }}).catch(function(){{}});
    }};
    size();
    q.addEventListener('input',function(){{
      size();
      if(completeTimer)clearTimeout(completeTimer);
      completeTimer=setTimeout(fetchMatches,120);
    }});
    q.addEventListener('keydown',function(e){{
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){{
        if(!matches.length)return;
        e.preventDefault();
        active+=(e.key==='ArrowDown'?1:-1);
        if(active<-1)active=matches.length-1;
        if(active>=matches.length)active=-1;
        renderDropdown();
        return;
      }}
      if(e.key==='Escape'&&matches.length){{
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
      }}
    }});
    q.addEventListener('focus',function(){{bar.classList.add('focused');}});
    q.addEventListener('blur',function(){{
      bar.classList.remove('focused');
      setTimeout(closeDropdown,150);
    }});
    bar.addEventListener('mousedown',function(e){{
      if(helpPill&&(e.target===helpPill||helpPill.contains(e.target)))return;
      if(e.target!==q){{
        e.preventDefault();
        q.focus();
        q.setSelectionRange(q.value.length,q.value.length);
      }}
    }});
    // Enter. A highlighted row wins, because the reader arrowed to it on
    // purpose and it is the only path that knows an object should keep the
    // place (/Tokyo/Venus, not /Venus). With nothing highlighted this falls
    // through to the explore form's own onsubmit, which already reads #q
    // and carries the date/time fields with it -- rather than a second
    // "just navigate" path that could drift from it.
    bar.addEventListener('submit',function(e){{
      e.preventDefault();
      if(active>=0&&matches[active]){{
        location.href=matches[active].href;
        return;
      }}
      closeDropdown();
      // The bar holds a path, so Enter goes to that path. It used to hand
      // the text to the explore form, which rebuilt a URL out of #q and the
      // old find field -- that form now only contributes the date and time,
      // and rebuilding a path it never saw the slashes in is how "Tokyo/"
      // plus "Venus" turned back into plain /Venus.
      var v=q.value.trim();
      if(!v){{location.href='/';return;}}
      var wd=document.getElementById('whenDate');
      var wt=document.getElementById('whenTime');
      var t=(wd&&wt&&wd.value&&wt.value)?(wd.value+'T'+wt.value):'';
      location.href=toPath(v)+(t?'?t='+encodeURIComponent(t):'');
    }});

    // The help panel. One bar that takes places, objects and page names is
    // only obvious once somebody tells you, and there is nowhere in a
    // single-line prompt to write three examples.
    if(helpPill&&helpPanel){{
      var setHelp=function(open){{
        helpPanel.hidden=!open;
        helpPill.setAttribute('aria-expanded',open?'true':'false');
        if(open)closeDropdown();
      }};
      helpPill.addEventListener('click',function(e){{
        e.preventDefault();
        e.stopPropagation();
        setHelp(helpPanel.hidden);
      }});
      document.addEventListener('mousedown',function(e){{
        if(helpPanel.hidden)return;
        if(helpPanel.contains(e.target)||helpPill.contains(e.target))return;
        setHelp(false);
      }});
      document.addEventListener('keydown',function(e){{
        if(e.key==='Escape'&&!helpPanel.hidden){{setHelp(false);helpPill.focus();}}
      }});
      // Typing is the reader answering the question the panel asks, so it
      // has served its purpose and should get out of the way of the
      // suggestions about to appear underneath it.
      q.addEventListener('input',function(){{if(!helpPanel.hidden)setHelp(false);}});
    }}
  }}
}})();"""

# The page-name list the dropdown offers has to be the one SEARCH_HELP
# advertises, and a second hand-typed copy inside a string template is
# exactly how those two drift apart. json.dumps rather than a join, so the
# quoting is something's job rather than mine. Substituted into the script
# itself, not into PAGE, so anything splicing CMDBAR_JS gets it complete.
CMDBAR_JS = CMDBAR_JS.replace("/*PAGES*/", json.dumps(list(SEARCH_PAGES)))


# ---------------------------------------------------------------------------
# What's new: a gallery of cards, shown once and then not again.
#
# Bump this when there is something new to say. It is the whole of the "have
# they seen it" test: the browser remembers the release it was last shown and
# compares strings, so changing this shows the gallery to everybody again and
# leaving it alone shows it to nobody twice. Any string will do -- it is never
# parsed, only compared -- but a date is the one that reads.
WHATS_NEW_RELEASE = "2026-08"

# The cards, in the order they are paged through.
#
# Each is a title, a body, and optionally a drawing and one link:
#
#   title  one line, the thing that is new
#   body   two or three sentences of plain text
#   art    a drawing, ANSI or plain -- art.planet_art(...) and friends both
#          work, ansi_to_html handles the escaping either way
#   cta    dict(label=..., url=...), one link and no more
#
# The URLs have to work from any page, because the gallery is built once at
# import and the same markup goes out on every one of them. Nothing here can
# know which place the reader is looking at, so /paris/sphere is out and
# /catalog is fine.
#
# DRAFT COPY. The features are real and the links resolve, but the wording is
# a first pass to have something to look at.
WHATS_NEW = (
    dict(title="The chart is the page",
         body="Day and night share one layout now. The line above the chart "
              "says where you are, what time it is and what is up, and it "
              "follows the animation frame by frame as the night runs."),
    dict(title="Every eclipse, from where you are standing",
         body="Not the eclipse in the abstract: how much of the Sun goes "
              "from your own back garden, when it starts, when it peaks, and "
              "how far you would have to travel to stand in the shadow.",
         cta=dict(label="What is coming →", url="/eclipse")),
    dict(title="The same sky, turned",
         body="Add /sphere to any place and the chart becomes a globe you "
              "can drag. Same stars, same names, same links, one drawn flat "
              "and one drawn round."),
    dict(title="The deep sky, drawn",
         body="Clusters, nebulae and galaxies have their own pages and their "
              "own drawings now, beside the planets. Each one says what it "
              "is, where to look tonight, and whether your sky is dark "
              "enough for it.",
         cta=dict(label="Browse the catalog →", url="/catalog")),
)

# Rides on .modal, .modal-card, .modal-bar and .modal-close from the "what is
# on" modal further up: same box, same border, same close button, because it
# is the same kind of thing and two dialogs that look unalike on one site read
# as two sites. Only the gallery inside is new.
WHATS_NEW_CSS = """ /* What's new -- a gallery of cards over everything, once a visitor. */
 .wn-card{max-width:620px}
 /* The arrows keep their columns whether they are usable or not. Hiding one
    at either end moves the card sideways underneath the reader's eye as they
    page through it, which is the one thing a gallery must not do. */
 .wn-stage{display:grid;grid-template-columns:auto 1fr auto;
           align-items:center;gap:4px}
 /* A container, so a drawing can be sized from the card rather than from a
    number typed here -- the same arrangement .mf-frame uses for the event
    frames. min-height so that paging from a long card to a short one does
    not resize the dialog around the reader. */
 .wn-slide{min-width:0;min-height:150px;container-type:inline-size}
 /* [hidden] loses to any display rule, and there is one above. */
 .wn-slide[hidden]{display:none}
 .wn-art-frame{margin:0 0 12px}
 /* art.COLS = 45 characters at ART_ADVANCE_EM per character, as hundredths
    of the card: the same 27.5 .mf-art is sized by, and for the same reason. */
 .wn-art{font-size:calc(100cqw / 27.5)}
 .wn-title{margin:0 0 .5rem;font-size:15px;font-weight:normal;color:#c9d1d9}
 .wn-body{margin:0;font-size:13px;line-height:1.55;color:#8b949e}
 .wn-cta{display:inline-block;margin-top:.8rem;font-size:12.5px;
         color:#ffd700;text-decoration:none}
 .wn-cta:hover{text-decoration:underline}
 .wn-arrow{background:none;border:0;color:#6e7681;font:inherit;font-size:22px;
           line-height:1;cursor:pointer;padding:8px 4px}
 .wn-arrow:hover:not(:disabled){color:#c9d1d9}
 .wn-arrow:disabled{color:#21262d;cursor:default}
 .wn-foot{display:flex;align-items:center;justify-content:space-between;
          gap:12px;margin-top:1.1rem}
 .wn-dots{display:flex;gap:7px}
 .wn-dot{width:7px;height:7px;padding:0;border:0;border-radius:50%;
         background:#30363d;cursor:pointer}
 .wn-dot:hover{background:#6e7681}
 /* Green, like #on-pill: the one mark on the page saying "you are here". */
 .wn-dot[aria-current="true"]{background:#7ee787}
 .wn-done{background:#04060a;border:1px solid #7ee787;color:#7ee787;
          font:inherit;font-size:12px;border-radius:4px;padding:5px 12px;
          cursor:pointer;white-space:nowrap}
 .wn-done:hover{border-color:#9ef2ab;color:#9ef2ab}
 @media (max-width:520px){.wn-arrow{font-size:18px;padding:6px 0}}
"""


def whats_new_html(cards=WHATS_NEW, release=WHATS_NEW_RELEASE, auto=True,
                   key="skymap.whatsnew"):
    """The what's-new gallery: markup and the script that drives it.

    Self-contained, the way coming_up_card_html is. Everything it needs is in
    the string it returns except the CSS, which is WHATS_NEW_CSS and is
    spliced into the page's one stylesheet rather than shipped per instance.
    Drop the return value anywhere in a page that carries that stylesheet and
    it works; there is nothing to wire up at the call site.

    Three ways in, and only the first happens on its own:

      auto        once a visitor, on whatever page they land on first. The
                  browser stores `release` under `key` the moment it opens,
                  so "once" means once and not once per page.
      on demand   window.skymapWhatsNew(), or a click on anything carrying a
                  data-whats-new attribute. Neither consults storage: asking
                  for it is asking for it, whether or not it has been seen.
      #whats-new  the URL fragment, for looking at it after it has been
                  dismissed. A fragment rather than a query parameter on
                  purpose -- it never reaches the server, so there is no new
                  parameter to count and no cache key to split.

    Storage is written on open rather than on close. The other way round, a
    reader who glanced at it and navigated away would meet it again on the
    next page and the one after, which is the failure mode that makes people
    hate these things.

    A single card gets no arrows and no dots. A "1/1" control that cannot go
    anywhere is worse than no control, the same call the sphere's radiant HUD
    and the coming-up card's chevron both make.

    Returns "" for no cards, so turning the gallery off is emptying the list
    rather than unpicking the splice.
    """
    if not cards:
        return ""
    many = len(cards) > 1

    slides = []
    for i, c in enumerate(cards):
        art_html = ""
        if c.get("art"):
            # ansi_to_html either way: it escapes what it does not recognise,
            # so a plain drawing comes through intact and a coloured one keeps
            # its colours, and neither can carry markup into the page.
            art_html = (f'<div class="art-frame wn-art-frame">'
                        f'<pre class="art-plate wn-art">'
                        f'{ansi_to_html(c["art"])}</pre></div>')
        cta_html = ""
        if c.get("cta"):
            cta_html = (f'<a class="wn-cta" href="{html.escape(c["cta"]["url"])}">'
                        f'{html.escape(c["cta"]["label"])}</a>')
        slides.append(
            f'<article class="wn-slide"{"" if i == 0 else " hidden"}>'
            f'{art_html}'
            f'<h3 class="wn-title">{html.escape(c["title"])}</h3>'
            f'<p class="wn-body">{html.escape(c["body"])}</p>'
            f'{cta_html}</article>')

    arrows = ('<button type="button" class="wn-arrow" id="wn-prev" '
              'aria-label="Previous">‹</button>',
              '<button type="button" class="wn-arrow" id="wn-next" '
              'aria-label="Next">›</button>') if many else ("", "")
    dots = ""
    if many:
        dots = "".join(
            f'<button type="button" class="wn-dot" data-i="{i}" '
            f'aria-label="Card {i + 1} of {len(cards)}" '
            f'aria-current="{"true" if i == 0 else "false"}"></button>'
            for i in range(len(cards)))

    markup = (
        f'<div id="whats-new" class="modal" hidden>'
        f'<div class="modal-card wn-card" role="dialog" aria-modal="true" '
        f'aria-labelledby="wn-heading">'
        f'<div class="modal-bar">'
        f'<h2 class="modal-title" id="wn-heading">What’s new</h2>'
        f'<button type="button" class="modal-close" id="wn-close" '
        f'aria-label="Close">✕</button></div>'
        f'<div class="wn-stage">{arrows[0]}'
        f'<div class="wn-slides">{"".join(slides)}</div>{arrows[1]}</div>'
        f'<div class="wn-foot"><div class="wn-dots">{dots}</div>'
        f'<button type="button" class="wn-done" id="wn-done">'
        f'Got it</button></div></div></div>')

    script = (
        f'<script>(function(){{'
        f"var m=document.getElementById('whats-new');"
        f"if(!m)return;"
        f"var KEY={json.dumps(key)},REL={json.dumps(release)},"
        f"AUTO={'true' if auto else 'false'};"
        f"var card=m.querySelector('.modal-card'),"
        f"slides=m.querySelectorAll('.wn-slide'),"
        f"dots=m.querySelectorAll('.wn-dot'),"
        f"prev=document.getElementById('wn-prev'),"
        f"next=document.getElementById('wn-next'),"
        f"idx=0,opener=null;"
        f"function show(i){{"
        f"idx=Math.max(0,Math.min(slides.length-1,i));"
        f"for(var j=0;j<slides.length;j++){{"
        f"slides[j].hidden=j!==idx;"
        f"if(dots[j])dots[j].setAttribute('aria-current',j===idx?'true':'false');"
        f"}}"
        # Disabled rather than hidden: the arrow keeps its column, so the card
        # beside it does not shift when you reach either end.
        f"if(prev)prev.disabled=idx===0;"
        f"if(next)next.disabled=idx===slides.length-1;"
        f"}}"
        # Written the moment it opens, not when it closes. Closing is
        # optional -- navigating away is not -- and a gallery that only counts
        # as seen once it has been dismissed follows the reader around the
        # site.
        f"function seen(){{try{{localStorage.setItem(KEY,REL);}}catch(e){{}}}}"
        f"function openIt(){{"
        f"if(!m.hidden)return;"
        f"opener=document.activeElement;"
        f"m.hidden=false;show(0);seen();"
        f"var c=document.getElementById('wn-close');if(c)c.focus();"
        f"}}"
        f"function shut(){{"
        f"if(m.hidden)return;"
        f"m.hidden=true;"
        f"if(opener&&opener.focus)opener.focus();"
        f"opener=null;"
        f"}}"
        # The handle for everything else: a menu item, a footer link, the
        # console. Neither this nor data-whats-new asks storage first, because
        # asking to see it is not the same as not having seen it.
        f"window.skymapWhatsNew=openIt;"
        f"document.addEventListener('click',function(e){{"
        f"var t=e.target&&e.target.closest?e.target.closest('[data-whats-new]'):null;"
        f"if(!t)return;"
        f"e.preventDefault();openIt();"
        f"}});"
        f"if(prev)prev.addEventListener('click',function(){{show(idx-1);}});"
        f"if(next)next.addEventListener('click',function(){{show(idx+1);}});"
        f"for(var d=0;d<dots.length;d++)dots[d].addEventListener('click',function(e){{"
        f"show(parseInt(e.currentTarget.dataset.i,10));"
        f"}});"
        f"var closeBtn=document.getElementById('wn-close');"
        f"if(closeBtn)closeBtn.addEventListener('click',shut);"
        f"var doneBtn=document.getElementById('wn-done');"
        f"if(doneBtn)doneBtn.addEventListener('click',shut);"
        # The backdrop, but only the backdrop: a click that started on the
        # card and ended outside it is a drag, not a dismissal. Same rule as
        # the events modal.
        f"m.addEventListener('click',function(e){{if(e.target===m)shut();}});"
        # This listener is registered while the page is still being parsed,
        # which is before the shared script at the foot of the body registers
        # the site-wide shortcuts -- so it runs first, and gets to decide
        # whether that one runs at all.
        #
        # stopImmediatePropagation, not stopPropagation. Both handlers are on
        # document, and stopPropagation only stops an event reaching the *next
        # node*; every other listener already on this one still runs. So the
        # arrow keys paged the gallery and started the chart animation behind
        # it, and Escape then found anim-on set and stood down for an
        # animation the reader never asked for.
        f"document.addEventListener('keydown',function(e){{"
        f"if(m.hidden||e.metaKey||e.ctrlKey||e.altKey)return;"
        f"if(e.key==='Escape'){{"
        # Not while an animation owns the page -- that Escape is for leaving
        # it, and it is the state that covers everything else.
        f"if(document.documentElement.classList.contains('anim-on'))return;"
        f"e.stopImmediatePropagation();shut();return;"
        f"}}"
        f"if(e.key==='ArrowLeft'){{e.stopImmediatePropagation();e.preventDefault();show(idx-1);return;}}"
        f"if(e.key==='ArrowRight'){{e.stopImmediatePropagation();e.preventDefault();show(idx+1);return;}}"
        # Tab stays inside the dialog. It opens by itself, over a page full of
        # links nobody asked to tab through, so the one thing on screen should
        # be the one thing reachable.
        f"if(e.key==='Tab'){{"
        f"var all=card.querySelectorAll('button:not([disabled]),a[href]'),vis=[];"
        f"for(var k=0;k<all.length;k++)if(all[k].offsetParent!==null)vis.push(all[k]);"
        f"if(!vis.length)return;"
        f"var first=vis[0],last=vis[vis.length-1];"
        f"if(e.shiftKey&&document.activeElement===first){{e.preventDefault();last.focus();}}"
        f"else if(!e.shiftKey&&document.activeElement===last){{e.preventDefault();first.focus();}}"
        f"}}"
        f"}});"
        # A fragment, not a query parameter: it never reaches the server, so
        # there is no new parameter to count and no second cache key for the
        # same page. Taken back out of the URL once used, so a copied link
        # does not reopen it for whoever it is sent to.
        f"if(location.hash==='#whats-new'){{"
        f"history.replaceState(null,'',location.pathname+location.search);"
        f"openIt();"
        f"}}else if(AUTO){{"
        f"var last=null;try{{last=localStorage.getItem(KEY);}}catch(e){{}}"
        f"if(last!==REL)openIt();"
        f"}}"
        f'}})();</script>')
    return markup + script


PAGE = PAGE.replace("/*CMDBAR_CSS*/", CMDBAR_CSS)
PAGE = PAGE.replace("/*CMDBAR_JS*/", CMDBAR_JS)
# The gallery is the same on every page and on every night, so it is built
# once here rather than per request. Braces are doubled on the way in for the
# reason the ladder's are: PAGE is a .format() template and the script is full
# of real ones. That doubling is why whats_new_html itself writes single
# braces -- its output is a working component anywhere, and only this splice
# has to care that its destination is a template.
PAGE = PAGE.replace("<!--WHATSNEW-->",
                    whats_new_html().replace("{", "{{").replace("}", "}}"))
PAGE = PAGE.replace("/*WHATSNEW_CSS*/",
                    WHATS_NEW_CSS.replace("{", "{{").replace("}", "}}"))
# Substituted here rather than left as a format field: PAGE is .format()ed
# per request with named arguments, and a stray {BOX_GAP} would be looked up
# among them and raise. Done once at import, so every gap on the page comes
# from the one constant without costing a lookup per render.
PAGE = PAGE.replace("{BOX_GAP}", str(BOX_GAP))
# The animated headline is set at the same size as the ladder's rungs, which
# _ladder_rules writes from the same constant. Substituted here rather than
# left as a format key: the page is .format()ed per request with a fixed set
# of keys, and an unknown one is a 500 rather than a wrong pixel.
PAGE = PAGE.replace("{DAY_HEAD_PX}", str(DAY_HEAD_PX))
PAGE = PAGE.replace("{ANIM_WIDE_MS}", str(ANIM_WIDE_MS))
# The room the fixed shortcut bar needs, plus the page's one gap under it, so
# the last box ends the same distance above the bar as any two boxes sit
# apart. Arithmetic, so it cannot be one of the plain swaps above -- but the
# same reason applies: leaving it for .format() would look it up among the
# per-request arguments and raise.
PAGE = PAGE.replace("{BOTTOM_PAD}", str(KBD_BAR_H + BOX_GAP))
PAGE = PAGE.replace("{KBD_BAR}", str(KBD_BAR_H))
# The zenith marker as a JS string literal, so the animation splits a frame on
# exactly the bytes compose_frame joined it with. json.dumps escapes the
# control characters, which is the whole point -- writing them into the script
# raw would put unprintables in the page source.
PAGE = PAGE.replace("{ZENITH_SLOT_JS}", json.dumps(ZENITH_SLOT))
PAGE = PAGE.replace("{HEAD_SLOT_JS}", json.dumps(HEAD_SLOT))


# Only shown on an actual chart page (server.py passes "" everywhere else) --
# most of these keys are no-ops on /catalog, /legend etc. anyway, so a hint
# there would be more confusing than helpful.
# One line, and it has to stay one line -- it sits under the chart where a
# second row pushes the page taller. That is the budget the contents are
# chosen against: tab rather than p (both focus the place field, tab is the
# one people try), and no g, since "Share as a GIF" is a button sitting
# right there in the drawer with its own label.
SHORTCUTS_HINT = (
    # "tab place / f find" described two fields. There is one now, and both
    # keys still reach it, so it is listed once under the name of the thing
    # it actually is. That buys back a slot on a line with a hard one-row
    # budget, which is where "esc cancel" earns its place.
    '<p class="kbd-hint">Keyboard: <kbd>tab</kbd> search &middot; '
    '<kbd>m</kbd> my location &middot; '
    '<kbd>space</kbd> animate &middot; <kbd>d</kbd> deep sky &middot; '
    '<kbd>i</kbd> inset &middot; '
    '<kbd>z</kbd> zoom &middot; '
    '<kbd>esc</kbd> cancel</p>'
)

# find/date/time/go, in the drawer -- used on every page except the chart
# view, which instead gets EXPLORE_DATETIME below (find is promoted out of
# the drawer and onto the header there, see header_html's find_value param).
# document.getElementById('find') resolves to whichever #find happens to
# exist on the page -- the drawer's own (here) or the header's promoted one
# -- so this onsubmit logic never needs to know which one it is.
#
# All three (p/f/t) empty used to return false and silently do nothing --
# meant to guard against an accidental blank submit, but the real effect
# was that clearing the command bar and pressing Enter (or "go" with
# nothing else filled) looked broken: nothing happened at all instead of
# going home. An empty p already means "/" here (bare skymap.sh, located
# by IP), so there was never actually an empty case worth guarding against.
EXPLORE = """<div class="ex">
<form id="explore" onsubmit="var qEl=document.getElementById('q');
var p=qEl?qEl.value.trim():'';
var f=document.getElementById('find').value.trim();
var wd=document.getElementById('whenDate').value;
var wt=document.getElementById('whenTime').value;
var t=(wd&&wt)?(wd+'T'+wt):'';
var path=f?('/'+(p?encodeURIComponent(p)+'/':'')+encodeURIComponent(f))
          :('/'+(p?encodeURIComponent(p):''));
location.href=path+(t?'?t='+t:'');
return false;">
<input id="find" type="text" placeholder="Find (Venus, Big Dipper...)" autocomplete="off">
<div class="ex-row">
<input id="whenDate" type="date" title="local date at that place (default: today)">
<input id="whenTime" type="time" title="local time at that place (default: now)">
</div>
<button type="submit">go</button>
</form>
</div>
"""

# Chart-page twin of EXPLORE -- same onsubmit, no #find input of its own.
#
# #find is read null-safely here, exactly like #q above it. It used to be
# read straight, because the chart page was guaranteed a #find in the header
# next to the command bar; merging that field into the one search bar took
# the guarantee away, and an unguarded .value on a missing element throws
# before location.href is ever reached -- which would have made "go" (and
# Enter in the command bar, which delegates here) do nothing at all on the
# one page type with a chart on it.
EXPLORE_DATETIME = """<div class="ex">
<form id="explore" onsubmit="var qEl=document.getElementById('q');
var p=qEl?qEl.value.trim():'';
var fEl=document.getElementById('find');
var f=fEl?fEl.value.trim():'';
var wd=document.getElementById('whenDate').value;
var wt=document.getElementById('whenTime').value;
var t=(wd&&wt)?(wd+'T'+wt):'';
var path=f?('/'+(p?encodeURIComponent(p)+'/':'')+encodeURIComponent(f))
          :('/'+(p?encodeURIComponent(p):''));
location.href=path+(t?'?t='+t:'');
return false;">
<div class="ex-row">
<input id="whenDate" type="date" title="local date at that place (default: today)">
<input id="whenTime" type="time" title="local time at that place (default: now)">
</div>
<button type="submit">go</button>
</form>
</div>
"""

# Moved out of the header's nav row and into the drawer, at the top --
# catalog/demo/legend are less-used than events/help (which stayed in the
# nav), and this was the one thing on every page that couldn't collapse.
DRAWER_LINKS_HTML = """<p class="tries">
<a href="/">home</a> ·
<a href="/events">events</a> ·
<a href="/help">help</a> ·
<a href="/catalog">catalog</a> ·
<a href="/demo">demo</a> ·
<a href="/legend">legend</a>
</p>
"""

EXAMPLES_HTML = """<p class="tries">Examples:
<a href="/Nairobi">Nairobi</a> ·
<a href="/Tokyo">Tokyo</a> ·
<a href="/London">London</a> ·
<a href="/New%20York">New York</a> ·
<a href="/Buenos%20Aires">Buenos Aires</a> ·
<a href="/Sydney">Sydney</a> ·
<a href="/90,0">North Pole</a> ·
<a href="/-90,0">South Pole</a>
</p>
"""

# A plain, static link -- no per-request state, unlike animate_btn/sphere_btn
# (which depend on r), so this doesn't need server.py plumbing at all. Lives
# in the drawer's actions section on every page, not just the chart view --
# "start over" is just as meaningful from /catalog or /help.
RESET_HTML = '<a class="animate-btn" href="/">↺ reset skymap</a>'


# Mobile-only, additive 3D view of the current sky -- reached from PAGE's
# {{sphere_btn}} link, never linked from curl/terminal output. The only
# external script tag anywhere in this codebase: hand-rolling perspective-
# correct WebGL for a rotating starfield is a much bigger surface than one
# pinned CDN import, scoped to this one opt-in page.
SPHERE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>{title}</title>
<link rel="canonical" href="{canonical}">
<meta name="description" content="The night sky above you, in 3D -- look around by tilting your phone.">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
 /* Pinned rather than merely full-height. A pinch-zoom on this page scaled
    the whole document and left the scene sitting in a black margin, which
    on a view whose entire job is to be looked at is worse than useless.
    position:fixed with inset:0 also kills iOS rubber-band scrolling, and
    touch-action:none stops the browser claiming the gestures before the
    scene ever sees them. maximum-scale in the viewport meta is the other
    half; iOS ignores it on its own, hence the gesturestart handler in the
    script and this belt as well as those braces. */
 html,body{{margin:0;padding:0;position:fixed;inset:0;background:#000;
           overflow:hidden;touch-action:none;overscroll-behavior:none;
           -webkit-text-size-adjust:100%;
           font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
           -webkit-font-smoothing:antialiased}}
 canvas{{display:block;touch-action:none}}
 #hud{{position:fixed;top:0;left:0;right:0;padding:10px 14px;color:#6e7681;font-size:12px;
      display:flex;justify-content:space-between;pointer-events:none;z-index:1000}}
 #hud a{{color:#87d7ff;pointer-events:auto;text-decoration:none}}
 #heading{{color:#8b949e;letter-spacing:.02em}}
 /* ?debug=1 only -- raw sensor values, not for real visitors. Diagnosing
    live orientation issues needs to see what the phone's sensors are
    actually reporting, not just the computed result. */
 #debug-hud{{position:fixed;top:34px;left:0;right:0;padding:6px 14px;
            color:#7ee787;font-size:11px;white-space:pre;
            background:rgba(0,0,0,.6);pointer-events:none;z-index:1000;display:none}}
 /* The existing light grey/blue HUD text is tuned for a black night sky --
    unreadable against the daytime dome's light blue. Rather than picking a
    second set of colours (which wouldn't generalise to a future twilight
    gradient in between), a translucent dark bar behind the HUD row keeps
    the same text readable against any background -- shown only in
    daytime, since the night view doesn't need it. */
 body.daytime #hud{{background:rgba(4,6,10,.55)}}
 #overlay{{position:fixed;inset:0;background:rgba(4,6,10,.92);display:flex;
          flex-direction:column;align-items:center;justify-content:center;
          gap:14px;z-index:1001;text-align:center;padding:0 24px}}
 #overlay[hidden]{{display:none}}
 #enable{{background:#238636;border:0;color:#fff;padding:14px 22px;border-radius:8px;
         font:inherit;font-size:15px;cursor:pointer}}
 #enable:hover{{background:#2ea043}}
 #status{{color:#8b949e;font-size:12.5px;max-width:340px;line-height:1.5;margin:0}}
 #place-form{{display:flex;gap:6px}}
 #place-form[hidden]{{display:none}}
 #place-input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
              padding:8px 10px;border-radius:4px;font:inherit;font-size:16px;width:170px}}
 #place-form button{{background:#238636;border:0;color:#fff;padding:8px 14px;
                     border-radius:4px;font:inherit;font-size:13px;cursor:pointer}}
 .sky-label{{color:#c9d1d9;font-size:11px;
            white-space:nowrap;pointer-events:none}}
 .sky-label span{{display:inline-block;text-shadow:0 0 4px #000,0 0 4px #000}}
 /* The glow-shadow above exists for contrast against a black night sky --
    against the daytime dome's light blue it just looks like a smudge, so
    daytime plain-colours every label instead (higher specificity than
    .con-label/.dso-label/.body-label's own colours, so this wins outright). */
 body.daytime .sky-label span{{color:#2b2b2b;text-shadow:none}}
 .con-label span{{color:#8fa3c9;font-size:12px;letter-spacing:.03em}}
 .dso-label span{{color:#8fe6ae}}
 .body-label span{{color:#ffd77a;font-weight:600}}
 /* Stops short of the mode switch, which owns the bottom-right corner in
    both modes. Without this the toolbar's last row ran underneath it. */
 #toolbar{{position:fixed;left:0;right:72px;bottom:0;z-index:1000;padding:10px 12px;
         display:flex;gap:8px;flex-wrap:wrap;align-items:center;
         background:linear-gradient(rgba(4,6,10,0),rgba(4,6,10,.85) 65%)}}
 .toggle-btn{{background:#0d1117;border:1px solid #30363d;color:#6e7681;
             padding:6px 12px;border-radius:4px;font:inherit;font-size:12px;
             cursor:pointer}}
 .toggle-btn.on{{color:#7ee787;border-color:#2b5f3d}}
 .toggle-btn:disabled{{opacity:.6;cursor:default}}
 #find-form{{display:flex;gap:6px;align-items:center}}
 /* font-size:16px, not the usual 12px -- iOS Safari auto-zooms the page on
    focusing any input smaller than that. Fixing the cause beats trying to
    zoom back out again after the fact, which is jumpy and not reliable
    across browsers. */
 /* Both the field and its button are pinned to one height. The field
    carries font-size:16px (see above) and the button 12px, so left to
    their own padding the button came out visibly shorter than the thing
    it sits beside. */
 #find-form{{align-items:stretch}}
 #find-input,#find-form button{{height:34px;box-sizing:border-box;line-height:1}}
 #find-input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
             padding:6px 10px;border-radius:4px;font:inherit;font-size:16px;width:190px}}
 #find-form button{{background:#238636;border:0;color:#fff;padding:0 14px;
                    border-radius:4px;font:inherit;font-size:12px;cursor:pointer}}
 #find-cancel{{background:#7a1f1f !important}}
 #find-msg{{position:fixed;left:0;right:0;top:38px;text-align:center;color:#ffd700;
           font-size:12px;padding:0 12px;pointer-events:none;z-index:1000;margin:0}}
 /* Mode switch: a vertical pair in the bottom-right corner, thumb-reachable
    on a phone held up in front of you. Two cells rather than one cycling
    button, so both modes are visible and neither is a surprise. The second
    cell only exists where there is a sunrise or sunset to talk about -- at
    a pole in winter there is no golden hour, and offering it would be an
    empty promise. Sized to the 44px touch target. */
 #mode-switch{{position:fixed;right:12px;bottom:10px;z-index:1002;
              display:flex;flex-direction:column;
              border:1px solid #30363d;border-radius:10px;overflow:hidden;
              background:rgba(4,6,10,.86);backdrop-filter:blur(4px)}}
 .mode-cell{{appearance:none;border:0;background:transparent;color:#8b949e;
            font:inherit;cursor:pointer;width:52px;padding:8px 0 6px;
            display:flex;flex-direction:column;align-items:center;gap:2px;
            line-height:1.05;text-decoration:none}}
 /* A link, not a mode, so it never takes the "on" state the two below it
    share. */
 #mode-catalog:hover{{color:#87d7ff}}
 .mode-cell+.mode-cell{{border-top:1px solid #30363d}}
 .mode-ico{{font-size:15px}}
 .mode-lab{{font-size:9px;letter-spacing:.04em}}
 .mode-cell.on{{color:#f0f6fc;background:rgba(255,194,77,.10)}}
 #mode-golden.on{{color:#ffc24d}}
 .mode-cell:hover{{color:#f0f6fc}}
 /* The golden-hour panel. Pinned to the bottom because in this mode the
    phone is held up and turned, so the bottom of the screen is the one
    place a thumb can reach without the whole model swinging. */
 /* Stops short of the mode switch rather than running under it: the switch
    keeps the corner it starts in, in both modes, and the readout and
    scrubber take the space left of it. Moving the switch up when this
    opened meant the one control that is always there was the one control
    that moved. */
 /* Full width so the gradient carries on behind the mode switch instead
    of stopping in a hard edge beside it; the content is held off the
    corner by padding rather than by the box ending early. Generous bottom
    padding -- the scrubber sat right on the edge of the screen, which on a
    phone is where the home indicator lives. */
 #golden-panel{{position:fixed;left:0;right:0;bottom:0;z-index:1001;
               background:linear-gradient(transparent,rgba(4,6,10,.93) 26%);
               padding:24px 74px 30px 12px;text-align:center;
               padding-bottom:calc(30px + env(safe-area-inset-bottom))}}
 #golden-readout{{margin:0 0 8px;font-size:12px;color:#c9d1d9;
                 font-variant-numeric:tabular-nums;line-height:1.4}}
 /* The star view's controls have nothing to say here, and the find field
    was showing through from behind the panel. */
 body.golden-mode #toolbar,body.golden-mode #find-msg,
 body.golden-mode #radiant-hud{{display:none}}
 #golden-readout.in-band{{color:#ffc24d}}
 /* Up top, directly under the HUD's place and bearing line: these are the
    day's fixed facts, so they belong with the other things that do not
    change as you scrub, not next to the control that does. Its own
    gradient, because the sky behind it is bright in this mode. */
 /* 999, under the HUD rather than over it: this sits at top:0 and comes
    later in the DOM, so at equal z-index its gradient would have painted
    across the place and bearing line. Behind, the same gradient instead
    gives that line something to read against on a bright sky. */
 #golden-times{{position:fixed;top:0;left:0;right:0;z-index:999;
               margin:0;padding:42px 14px 12px;
               font-size:11px;color:#000;pointer-events:none;
               font-variant-numeric:tabular-nums;
               display:flex;flex-direction:column;gap:3px;align-items:center}}
 /* Black on the daylight sky, no panel behind it. Scrubbing the Sun under
    the blue band takes the sky to night, though, and black on that is
    nothing at all -- so the one case where the rule cannot hold flips it.
    setSunAt sets the class. */
 body.golden-dark #golden-times{{color:#c9d1d9}}
 /* An author display: rule outranks the browser's own [hidden]{{display:none}},
    so without this the times stayed on screen in the star view no matter
    what the attribute said. Same trap on the light cell, which sets
    display:flex through .mode-cell. */
 #golden-times[hidden],.mode-cell[hidden]{{display:none}}
 #golden-times span{{white-space:nowrap}}
 #golden-times b{{font-weight:600;display:inline-block;min-width:44px;text-align:right}}
 /* Deeper than the band colours themselves: gold and sky blue are picked to
    glow against black, and against a bright daylight sky they wash out. */
 #golden-times b.g{{color:#b8791a}}
 #golden-times b.b{{color:#1f5fa8}}
 body.golden-dark #golden-times b.g{{color:#ffc24d}}
 body.golden-dark #golden-times b.b{{color:#5aa9ff}}
 #golden-scrub{{width:100%;max-width:520px;accent-color:#ffc24d;
               height:26px;cursor:pointer;margin:0;display:block}}
 /* Every sky label goes: this is a model of the ground in daylight, and
    Orion sitting over the shadow says nothing useful. The compass points
    are on .ground-label precisely so they survive this. */
 body.golden-mode .star-label,body.golden-mode .body-label,
 body.golden-mode .dso-label,body.golden-mode .con-label,
 body.golden-mode .radiant-label{{display:none}}
 .ground-label span{{color:#3d3833;font-size:12px;font-weight:600;
                    letter-spacing:.06em;text-shadow:0 0 3px rgba(255,255,255,.7)}}
 .ground-label{{display:none}}
 body.golden-mode .ground-label{{display:block}}
 #find-arrow{{position:fixed;color:#ffd700;font-size:22px;font-weight:700;
             letter-spacing:-2px;pointer-events:none;z-index:1000;display:none;
             text-shadow:0 0 6px #000}}
 /* Four ticks that close in from outside toward the centre as you get
    closer -- becomes a solid cross right at the edge of "found", at which
    point a permanent purple circle + bold name takes over instead (see
    .found-label below) and the reticle stops appearing entirely. */
 #find-reticle{{position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;
               z-index:1000;display:none}}
 #find-reticle .tick{{position:absolute;background:#ff87ff;box-shadow:0 0 4px #000}}
 #find-reticle .tick-top,#find-reticle .tick-bottom{{width:2px;height:14px;left:-1px}}
 #find-reticle .tick-left,#find-reticle .tick-right{{height:2px;width:14px;top:-1px}}
 .found-label span{{color:#ff87ff;font-weight:700}}
 /* Orchid, matching the "Coming up:" line the text views use, so the two
    read as the same feature. Only ever on screen for the handful of nights
    a year a shower is actually running. */
 .radiant-label span{{color:#ff9ae6;font-weight:700}}
 /* bottom is set from JS to sit clear of #toolbar, whose height changes when
    its buttons wrap to a second row on a narrow phone -- a fixed offset here
    put this straight through the Labels/Deep sky row. */
 #radiant-hud{{position:fixed;left:0;right:0;bottom:64px;text-align:center;
              color:#ff9ae6;font-size:12px;padding:0 14px;pointer-events:none;
              z-index:999;margin:0;text-shadow:0 0 6px #000,0 0 6px #000;
              display:none}}
 /* Only the text takes taps, not the full-width strip -- the strip sits over
    the canvas, and swallowing drags there would break panning near the
    bottom of the screen. */
 #radiant-hud span{{pointer-events:auto;cursor:pointer;display:inline-block;
                   border-bottom:1px dashed rgba(255,154,230,.55);
                   padding-bottom:1px}}
 #radiant-hud span:active{{color:#ffd0f4}}
 #radiant-hud-cycle{{margin-left:8px;border:1px solid rgba(255,154,230,.5);
                    border-radius:4px;padding:1px 6px;font-size:11px;
                    white-space:nowrap}}
 #radiant-hud-cycle[hidden]{{display:none}}
 body.daytime #radiant-hud{{color:#8a2f74}}
 body.daytime #radiant-hud span{{border-bottom-color:rgba(138,47,116,.55)}}
 /* Red mode (the Red button). This page is meant to be held up at the sky
    outdoors, where its normal white-and-blue undoes the dark adaptation
    that takes about 20 minutes of standing outside to build. Rods, the
    cells night vision actually runs on, barely respond to long
    wavelengths, so deep red at low intensity costs far less of it -- the
    same reason observatories and cockpits are lit red.
    Deliberately last in this stylesheet: these share specificity with the
    body.daytime rules above and need to win against them, since red mode
    stays on if someone opens the page again in daylight.
    The 3D scene is recoloured object by object in JS instead (paintScene
    below), not with a CSS filter over the canvas -- a filter is one line
    but costs a full-screen composite every frame on exactly the hardware
    least able to spare it.
    Everything painted straight onto the sky is :not(.daytime) below. Red
    mode dulls the daytime dome but doesn't get rid of it, and red text on
    that broad red field is unreadable at any weight -- worse with the
    glow, which only ever existed for contrast against a black sky. In
    daylight these rules stand down and the black-on-bright treatment
    body.daytime already uses takes over, refined just below. The chrome
    with its own dark background (toolbar, inputs, overlay) is unaffected
    by the dome and stays red in both. */
 body.night:not(.daytime) #hud{{color:#8c2a20;background:none}}
 body.night:not(.daytime) #hud a{{color:#c9382a}}
 body.night:not(.daytime) #heading{{color:#a83224}}
 body.night #debug-hud{{color:#c9382a}}
 body.night:not(.daytime) .sky-label span{{color:#c0362a;text-shadow:0 0 4px #000,0 0 4px #000}}
 body.night:not(.daytime) .con-label span{{color:#8f2b20}}
 body.night:not(.daytime) .dso-label span{{color:#a8352a}}
 body.night:not(.daytime) .body-label span{{color:#e0533a}}
 body.night:not(.daytime) .found-label span{{color:#e0533a}}
 body.night:not(.daytime) .radiant-label span{{color:#c9382a}}
 /* Red mode in daylight. Two body classes beats the one in the plain
    body.daytime rules above, so this wins without depending on source
    order. Black and greys, ranked the way the night palette ranks them:
    planets darkest and boldest, then stars, then the fainter deep-sky and
    constellation labels. No glow anywhere -- a black halo on a red field
    just smears. */
 body.night.daytime .sky-label span{{color:#1c1c1c;text-shadow:none}}
 body.night.daytime .con-label span{{color:#4a4a4a}}
 body.night.daytime .dso-label span{{color:#3d3d3d}}
 body.night.daytime .body-label span{{color:#0a0a0a}}
 body.night.daytime .found-label span{{color:#000}}
 body.night.daytime .radiant-label span{{color:#1c1c1c}}
 body.night.daytime #radiant-hud{{color:#1c1c1c;text-shadow:none}}
 body.night.daytime #radiant-hud span{{border-bottom-color:rgba(28,28,28,.55)}}
 body.night.daytime #find-msg,body.night.daytime #find-arrow{{color:#111;
              text-shadow:none}}
 body.night.daytime #find-reticle .tick{{background:#111;box-shadow:none}}
 body.night #toolbar{{background:linear-gradient(rgba(6,2,2,0),rgba(6,2,2,.85) 65%)}}
 body.night .toggle-btn{{background:#0d0505;border-color:#4d140f;color:#8c2a20}}
 body.night .toggle-btn.on{{color:#e0533a;border-color:#7a1f14}}
 body.night #find-input,body.night #place-input{{background:#0d0505;
              border-color:#4d140f;color:#c0362a}}
 body.night #find-input::placeholder,body.night #place-input::placeholder{{color:#6b1d13}}
 body.night #find-form button,body.night #place-form button{{background:#7a1f14;color:#f0a08f}}
 body.night #find-cancel{{background:#4d140f !important}}
 body.night #find-msg,body.night #find-arrow{{color:#d1452f}}
 body.night #find-reticle .tick{{background:#e0533a}}
 body.night #radiant-hud{{color:#c9382a}}
 body.night #radiant-hud span{{border-bottom-color:rgba(201,56,42,.55)}}
 body.night #radiant-hud span:active{{color:#f0a08f}}
 body.night #overlay{{background:rgba(6,2,2,.94)}}
 body.night #enable{{background:#7a1f14;color:#f0a08f}}
 body.night #enable:hover{{background:#8f2619}}
 body.night #status{{color:#8c2a20}}
</style></head><body>
<div id="hud"><a href="/">&larr; {place_name}{home_suffix}</a><span id="heading"></span><span id="mode-label"></span></div>
<div id="debug-hud"></div>
<div id="overlay"><button id="enable">&#9678; Look around you</button>
<p id="status">{place_name} &mdash; the current sky, in 3D. On a phone this follows the way
you're holding it; anywhere else, drag to look around.</p>
</div>
<div id="toolbar">
<form id="place-form" autocomplete="off" hidden>
<input id="place-input" type="text" placeholder="city or lat,lon">
<button type="submit">Go</button>
</form>
<button id="labels-toggle" class="toggle-btn on">Labels</button>
<button id="dso-toggle" class="toggle-btn">Deep sky</button>
<button id="night-toggle" class="toggle-btn" title="Red light: keeps your night vision">Red</button>
<form id="find-form" autocomplete="off">
<input id="find-input" type="text" placeholder="Find (Venus, Vega...)">
<button type="submit">Find</button>
<button type="button" id="find-cancel" hidden>Cancel</button>
</form>
</div>
<div id="mode-switch">
<!-- The way out. On a phone the home page IS this view, so without a link
     off it the sphere is where you arrive and where you stay: every other
     page on the site is reachable only by typing a URL. The catalogue is
     the right destination because it is the one page that lists everything
     that has a page of its own. First in the stack, so it reads as leaving
     rather than as a third mode. -->
<a id="mode-catalog" class="mode-cell" href="/catalog">
<span class="mode-ico">&#9776;</span><span class="mode-lab">browse</span></a>
<button type="button" id="mode-sky" class="mode-cell on" aria-pressed="true">
<span class="mode-ico">&#9673;</span><span class="mode-lab">sky</span></button>
<button type="button" id="mode-golden" class="mode-cell" aria-pressed="false" hidden>
<span class="mode-ico">&#9728;</span><span class="mode-lab">light</span></button>
</div>
<p id="golden-times" hidden></p>
<div id="golden-panel" hidden>
<p id="golden-readout"></p>
<input id="golden-scrub" type="range" min="0" max="1440" step="1" value="720"
       aria-label="Time of day">
</div>
<p id="find-msg"></p>
<div id="find-arrow">&gt;&gt;&gt;</div>
<p id="radiant-hud"><span id="radiant-hud-text" role="button" tabindex="0"></span><span id="radiant-hud-cycle" role="button" tabindex="0" hidden></span></p>
<div id="find-reticle">
<div class="tick tick-top"></div>
<div class="tick tick-bottom"></div>
<div class="tick tick-left"></div>
<div class="tick tick-right"></div>
</div>
<script type="importmap">{{"imports":{{"three":"/vendor/three/three.module.js"}}}}</script>
<script type="module">
import * as THREE from "three";
import {{ CSS2DRenderer, CSS2DObject }} from "/vendor/three/CSS2DRenderer.js";

var PLACE = "{place_slug}";
var statusEl = document.getElementById('status');
var overlay = document.getElementById('overlay');
var enableBtn = document.getElementById('enable');
var modeLabel = document.getElementById('mode-label');
var headingEl = document.getElementById('heading');

// ?debug=1 -- raw sensor readout for diagnosing live orientation issues
// without needing a cabled Web Inspector session, see #debug-hud above.
var DEBUG = new URLSearchParams(window.location.search).get('debug') === '1';
var debugEl = document.getElementById('debug-hud');
if (DEBUG) debugEl.style.display = 'block';
var _fps = 0, _fpsFrames = 0, _fpsLast = 0;

// Same 16-point bucketing as sky.py's compass() -- kept in sync by hand
// since there's no shared source between Python and this page's JS.
var COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
function compass16(az) {{
  return COMPASS16[Math.floor(((az % 360) + 360) % 360 / 22.5 + 0.5) % 16];
}}

var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 200);
var renderer = new THREE.WebGLRenderer({{antialias: true}});
renderer.setPixelRatio(window.devicePixelRatio || 1);
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

// Text labels are real DOM elements positioned by CSS2DRenderer from each
// object's 3D position every frame -- crisp at any zoom, and (unlike the
// ASCII chart, where a label eats character cells other glyphs need) free
// to put on every named object without anything fighting for space.
var labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(window.innerWidth, window.innerHeight);
labelRenderer.domElement.style.position = 'absolute';
labelRenderer.domElement.style.top = '0';
labelRenderer.domElement.style.left = '0';
labelRenderer.domElement.style.pointerEvents = 'none';
document.body.appendChild(labelRenderer.domElement);

// Every label the declutter pass below knows about -- priority 0 (bodies)
// gets first pick of its preferred spot, priority 3 (stars, by far the most
// numerous) yields to everything placed before it.
var LABELS = [];

function addLabel(text, pos, cls, priority) {{
  var el = document.createElement('div');
  el.className = 'sky-label' + (cls ? ' ' + cls : '');
  var inner = document.createElement('span');
  inner.textContent = text;
  el.appendChild(inner);
  var obj = new CSS2DObject(el);
  obj.position.copy(pos);
  scene.add(obj);
  // Estimated pixel width from character count (monospace-ish font) --
  // avoids a layout-forcing getBoundingClientRect() read on every label,
  // every frame, just to find out how wide its own text box is.
  var fontPx = cls === 'con-label' ? 12 : 11;
  var entry = {{obj: obj, inner: inner, cls: cls, priority: priority || 3,
               w: text.length * fontPx * 0.62 + 16, h: fontPx + 8}};
  LABELS.push(entry);
  return entry;
}}

function removeLabel(entry) {{
  scene.remove(entry.obj);
  var idx = LABELS.indexOf(entry);
  if (idx !== -1) LABELS.splice(idx, 1);
}}

function boxOverlap(a, b) {{
  var x = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
  var y = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  return x * y;
}}

// A handful of candidate spots around the label's true position (right,
// left, further below, further above, ...), tried in order and scored by
// how much they'd overlap what's already been placed this frame -- not a
// full solver, just enough to pull most collisions apart cheaply.
function candidateOffsets(w, h) {{
  return [[8, -6], [-w - 8, -6], [8, h + 6], [8, -(h + 12)],
         [8, 2 * h + 10], [-w - 8, h + 6], [-w - 8, -(h + 12)], [8, -(2 * h + 16)]];
}}

var _camSpace = new THREE.Vector3();
var _projected = new THREE.Vector3();

function declutterLabels() {{
  camera.updateMatrixWorld(true);
  var placed = [];
  var ordered = LABELS.slice().sort(function(a, b) {{ return a.priority - b.priority; }});
  ordered.forEach(function(L) {{
    _camSpace.copy(L.obj.position).applyMatrix4(camera.matrixWorldInverse);
    if (_camSpace.z > 0) return;   // behind the camera -- CSS2DRenderer already hides it
    _projected.copy(L.obj.position).project(camera);
    var sx = (_projected.x * 0.5 + 0.5) * window.innerWidth;
    var sy = (1 - (_projected.y * 0.5 + 0.5)) * window.innerHeight;
    var cands = candidateOffsets(L.w, L.h);
    var chosen = cands[0], bestOverlap = Infinity;
    for (var i = 0; i < cands.length; i++) {{
      var box = {{x: sx + cands[i][0], y: sy + cands[i][1], w: L.w, h: L.h}};
      var overlap = 0;
      for (var j = 0; j < placed.length && overlap === 0; j++) {{
        overlap += boxOverlap(box, placed[j]);
      }}
      if (overlap < bestOverlap) {{ bestOverlap = overlap; chosen = cands[i]; }}
      if (overlap === 0) break;
    }}
    placed.push({{x: sx + chosen[0], y: sy + chosen[1], w: L.w, h: L.h}});
    L.inner.style.transform = 'translate(' + chosen[0] + 'px,' + chosen[1] + 'px)';
  }});
}}

window.addEventListener('resize', function() {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelRenderer.setSize(window.innerWidth, window.innerHeight);
}});

// NOT sky.py's project() convention ("east appears left") -- that's built
// for a flat chart you look UP at from a fixed vantage, where the mirroring
// is intentional. This is a first-person view where you physically turn
// your own body, so it needs ordinary compass/map handedness instead: face
// north and east is on your right, like reality. alt/az in degrees, camera
// default (no rotation) looks toward -Z, i.e. north.
var RADIUS = 50;
function toVec(alt, az) {{
  var a = alt * Math.PI / 180, z = az * Math.PI / 180;
  var x = Math.sin(z) * Math.cos(a);
  var y = Math.sin(a);
  var zc = -Math.cos(z) * Math.cos(a);
  return new THREE.Vector3(x, y, zc).multiplyScalar(RADIUS);
}}

// ---- golden hour -------------------------------------------------------
// The star view stands you at the centre looking out. This is the opposite,
// and it has to be: where the light comes from, which way the shadow falls
// and how both move are relationships between the Sun, the ground and you,
// and a relationship is hard to read from inside it.
//
// The flip costs two lines in animate() rather than a control of its own.
// deviceQ already says which way you are facing; stepping the camera back
// along that same axis turns "look out from here" into "look in at this"
// with the identical quaternion and the identical compass filter. Turning
// your body walks the camera around the model.
// How far out the camera stands, and the range a pinch can move it through.
// Close in, the pole and the near end of its shadow fill the screen, which
// is what you want when you are reading a bearing off the ground; far out
// you see the whole day's arc over the whole disc. The far end is bounded
// by the camera's own far plane (raised below, since 200 was cut for a view
// that never left the origin).
var ORBIT_R = RADIUS * 2.15;
var orbitR = ORBIT_R;
var ORBIT_MIN = RADIUS * 0.35, ORBIT_MAX = RADIUS * 3.2;
camera.far = 400;
camera.updateProjectionMatrix();
// Deliberately small against the ground disc. A vertical thing's shadow is
// cot(altitude) times its height, which is 9.5x at the top of the golden
// band and past 30x near the horizon -- a taller pole would throw its
// shadow off the edge of the world for most of the window this exists to
// show. No metres anywhere: the ratio and the bearing are the honest
// answer, and the flat ground this assumes is doing enough work already.
var POLE_H = RADIUS * 0.035;
// Stockier than a person (who is about 0.11 of their height across) so it
// still reads as an object rather than a scratch when the whole disc is on
// screen. The shadow takes the same width, because a shadow the width of a
// hair cast by something with body looks like a bug.
var POLE_R = POLE_H * 0.17;
// Broad daylight, because that is when this is used. The star view is dark
// for night vision; a photographer standing outside at six in the evening
// is not dark-adapted and is looking at a bright world. The ground is a
// warm neutral so a real shadow -- dark, not glowing -- reads across it,
// and the sky behind is a flat daylight blue rather than the black the rest
// of the page uses.
var GOLD_HEX = 0xffb020, BLUE_HEX = 0x3d7fd0, GROUND_HEX = 0xbfb6a6;
var SKY_DAY_HEX = 0x8ec5ea, SHADOW_HEX = 0x2f2a24;
var GROUND_LINE_HEX = 0x6e675c, GROUND_SPOKE_HEX = 0x9a9083;

var goldenOn = false, goldenGroup = null, goldenData = null;
var sunDot = null, shadowLine = null, poleTop = null, groundDisc = null;
var _look = new THREE.Vector3();     // reused every frame, not allocated

// The lights go out as the Sun goes down, because they do. Scrubbing past
// the bottom of the blue band and having the scene stay in broad daylight
// was the one thing on screen that contradicted what the bands were saying.
//
// Stops in Sun altitude, interpolated between: full daylight overhead, warm
// through the golden band, deep blue through the blue one, and properly
// dark below it. Nothing here is a measurement -- it is the same reddening
// idea the flat chart's arc already uses, in colour rather than in glyphs.
var SKY_STOPS = [[15, 0x8ec5ea], [6, 0xa9c6e2], [2, 0xd8a878], [0, 0xe0a56a],
                 [-4, 0x3f5580], [-6, 0x1b2540], [-12, 0x05070d]];

function _mixHex(a, b, t) {{
  var ar = (a >> 16) & 255, ag = (a >> 8) & 255, ab = a & 255;
  var br = (b >> 16) & 255, bg = (b >> 8) & 255, bb = b & 255;
  return ((Math.round(ar + (br - ar) * t) << 16)
        | (Math.round(ag + (bg - ag) * t) << 8)
        | Math.round(ab + (bb - ab) * t));
}}

function skyColourFor(alt) {{
  if (alt >= SKY_STOPS[0][0]) return SKY_STOPS[0][1];
  var last = SKY_STOPS[SKY_STOPS.length - 1];
  if (alt <= last[0]) return last[1];
  for (var i = 0; i < SKY_STOPS.length - 1; i++) {{
    var hi = SKY_STOPS[i], lo = SKY_STOPS[i + 1];
    if (alt <= hi[0] && alt >= lo[0]) {{
      return _mixHex(hi[1], lo[1], (hi[0] - alt) / (hi[0] - lo[0]));
    }}
  }}
  return last[1];
}}

// The ground is lit by the Sun too. Same curve, as a plain brightness
// scale, so the disc does not stay glowing under a night sky.
function groundLightFor(alt) {{
  return Math.max(0.10, Math.min(1, (alt + 10) / 16));
}}

function _altAzVec(alt, az, radius) {{
  var v = toVec(alt, az);
  return radius ? v.normalize().multiplyScalar(radius) : v;
}}

// A band of sky between two altitudes, as a zone of the sphere. theta runs
// from the +Y pole, so an altitude of a degrees sits at 90 - a.
function _bandMesh(altLo, altHi, hex, opacity) {{
  var t0 = (90 - altHi) * Math.PI / 180, t1 = (90 - altLo) * Math.PI / 180;
  var geo = new THREE.SphereGeometry(RADIUS, 64, 8, 0, Math.PI * 2, t0, t1 - t0);
  var mat = new THREE.MeshBasicMaterial({{
    color: hex, transparent: true, opacity: opacity,
    side: THREE.DoubleSide, depthWrite: false}});
  return new THREE.Mesh(geo, mat);
}}

function _line(points, hex, opacity) {{
  var geo = new THREE.BufferGeometry().setFromPoints(points);
  var mat = new THREE.LineBasicMaterial({{
    color: hex, transparent: opacity < 1, opacity: opacity}});
  return new THREE.Line(geo, mat);
}}

function buildGolden(g) {{
  if (goldenGroup || !g) return;
  goldenData = g;
  goldenGroup = new THREE.Group();
  goldenGroup.visible = false;

  // The ground, out to the horizon circle -- the disc's rim IS the sphere's
  // alt=0, so the compass ring lands exactly where the horizon is rather
  // than at an arbitrary radius that only looks about right.
  var disc = new THREE.Mesh(
    new THREE.CircleGeometry(RADIUS, 64),
    new THREE.MeshBasicMaterial({{color: GROUND_HEX,
                                 side: THREE.DoubleSide}}));
  disc.rotation.x = -Math.PI / 2;
  disc.position.y = -0.05;          // just under the rings, so they read on top
  goldenGroup.add(disc);
  groundDisc = disc;

  var ring = [];
  for (var i = 0; i <= 128; i++) ring.push(_altAzVec(0, i * 360 / 128));
  goldenGroup.add(_line(ring, GROUND_LINE_HEX, 1));

  // Radial spokes and the eight compass points: the bearing is half the
  // answer this view gives, so the ground has to be readable as a compass
  // and not just as a floor.
  var NAMES = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  for (var k = 0; k < 8; k++) {{
    var az = k * 45;
    goldenGroup.add(_line([new THREE.Vector3(0, 0, 0), _altAzVec(0, az)],
                          GROUND_SPOKE_HEX, 1));
    // Its own class, not con-label: golden mode hides every sky label, and
    // the compass points are the one set of labels that belong to the
    // ground rather than to the sky.
    var lab = addLabel(NAMES[k], _altAzVec(0, az).multiplyScalar(1.04),
                       'ground-label', 1);
    if (lab) goldenGroup.add(lab);
  }}

  // You. A plain vertical mark -- the shadow is what carries the meaning,
  // and drawing a person would put a height on it that this does not know.
  // Solid, not a hairline. It was a one-pixel line, which vanished at any
  // useful zoom -- and the thing casting the shadow is half of what the
  // shadow means, so it has to have some body to it. Stockier than a real
  // person for the same reason: this reads at a glance rather than being
  // measured.
  var pole = new THREE.Mesh(
    new THREE.CylinderGeometry(POLE_R, POLE_R, POLE_H, 16),
    new THREE.MeshBasicMaterial({{color: 0x241f1a}}));
  pole.position.y = POLE_H / 2;
  goldenGroup.add(pole);
  // A soft cap, so the top reads as an end rather than a cut-off.
  var cap = new THREE.Mesh(
    new THREE.SphereGeometry(POLE_R, 16, 10),
    new THREE.MeshBasicMaterial({{color: 0x241f1a}}));
  cap.position.y = POLE_H;
  goldenGroup.add(cap);
  poleTop = new THREE.Vector3(0, POLE_H, 0);

  goldenGroup.add(_bandMesh(g.edges.golden_lo, g.edges.golden_hi, GOLD_HEX, 0.42));
  goldenGroup.add(_bandMesh(g.edges.blue_lo, g.edges.blue_hi, BLUE_HEX, 0.42));

  // Today's whole path. Cut at -8 rather than at the horizon: the bands run
  // to -6, and a track that stopped at 0 would leave the blue hour hanging
  // off the end of the line that is supposed to explain it.
  var seg = [];
  for (var j = 0; j < g.track.length; j++) {{
    var p = g.track[j];
    if (p[1] < -8) {{
      if (seg.length > 1) goldenGroup.add(_line(seg, 0x4a443c, 0.75));
      seg = [];
      continue;
    }}
    seg.push(_altAzVec(p[1], p[2]));
  }}
  if (seg.length > 1) goldenGroup.add(_line(seg, 0x4a443c, 0.75));

  sunDot = new THREE.Mesh(
    new THREE.SphereGeometry(RADIUS * 0.022, 16, 12),
    new THREE.MeshBasicMaterial({{color: 0xffd700}}));
  goldenGroup.add(sunDot);

  // A quad lying on the ground, the same width as the pole, rebuilt each
  // time the Sun moves. Two triangles is cheap enough to redo on every
  // frame of a scrub, and far easier to reason about than rotating and
  // scaling a shared plane into place.
  shadowLine = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshBasicMaterial({{color: SHADOW_HEX, transparent: true,
                                 opacity: 0.55, side: THREE.DoubleSide,
                                 depthWrite: false}}));
  goldenGroup.add(shadowLine);

  scene.add(goldenGroup);
  setSunAt(g.now_min);
}}

// Where the Sun is at a given minute past local midnight, read off the
// track by straight interpolation between the two points either side. The
// track is sampled every ten minutes; the Sun moves about 2.5 degrees in
// that time and its path is very nearly straight over so short a span, so
// this is smooth to drag and honest to read.
function sunAtMinute(m) {{
  var t = goldenData.track;
  if (t.length < 2) return null;
  var i = Math.max(0, Math.min(t.length - 2,
                               Math.floor(m / goldenData.step_min)));
  var a = t[i], b = t[i + 1];
  var span = b[0] - a[0];
  var f = span ? Math.max(0, Math.min(1, (m - a[0]) / span)) : 0;
  // Azimuth is a compass bearing, so it wraps. Interpolating 359 to 1 the
  // long way round would swing the Sun most of the way across the sky
  // between two samples ten minutes apart.
  var dz = ((b[2] - a[2] + 540) % 360) - 180;
  return {{alt: a[1] + (b[1] - a[1]) * f, az: (a[2] + dz * f + 360) % 360}};
}}

// Put the Sun at a minute past local midnight and redraw everything that
// follows from it: the marker, the shadow, and the readout.
function setSunAt(m) {{
  if (!goldenData || !sunDot) return;
  var s = sunAtMinute(m);
  if (!s) return;
  sunDot.position.copy(_altAzVec(s.alt, s.az));
  // A shadow falls directly away from the Sun and runs cot(altitude) times
  // the height of what casts it. Below the horizon there is no shadow at
  // all -- not a very long one -- so the line simply goes away.
  var lit = s.alt > 0;
  shadowLine.visible = lit;
  var ratio = null;
  if (lit) {{
    ratio = 1 / Math.tan(s.alt * Math.PI / 180);
    var len = Math.min(ratio * POLE_H, RADIUS * 0.97);
    var back = (s.az + 180) * Math.PI / 180;
    var dx = Math.sin(back), dz = -Math.cos(back);      // along the shadow
    var px = Math.cos(back) * POLE_R, pz = Math.sin(back) * POLE_R;   // across it
    var y = 0.04;
    var v = new Float32Array([
      -px, y, -pz,   px, y, pz,   dx * len + px, y, dz * len + pz,
      -px, y, -pz,   dx * len + px, y, dz * len + pz,
      dx * len - px, y, dz * len - pz]);
    shadowLine.geometry.dispose();
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(v, 3));
    shadowLine.geometry = geo;
  }}
  var inBand = s.alt >= goldenData.edges.golden_lo
            && s.alt <= goldenData.edges.golden_hi;
  sunDot.material.color.setHex(inBand ? 0xffb238 : 0xffd700);
  // Drag the Sun down and the lights go with it.
  if (goldenOn) scene.background = new THREE.Color(skyColourFor(s.alt));
  var lit = groundLightFor(s.alt);
  if (groundDisc) groundDisc.material.color.setHex(GROUND_HEX).multiplyScalar(lit);
  sunDot.visible = s.alt > goldenData.edges.blue_lo - 4;
  document.body.classList.toggle('golden-dark', s.alt < goldenData.edges.blue_lo);
  updateGoldenHud(m, s, ratio, inBand);
}}

var COMPASS16 = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
function compassOf(az) {{
  return COMPASS16[Math.round(((az % 360) + 360) % 360 / 22.5) % 16];
}}
function hhmm(m) {{
  var t = ((Math.round(m) % 1440) + 1440) % 1440;
  return String(Math.floor(t / 60)).padStart(2, '0') + ':'
       + String(t % 60).padStart(2, '0');
}}

function updateGoldenHud(m, s, ratio, inBand) {{
  var out = document.getElementById('golden-readout');
  var bits = [hhmm(m), 'sun ' + s.alt.toFixed(1) + '\\u00b0 ' + compassOf(s.az)];
  if (ratio === null) {{
    bits.push('below the horizon');
  }} else {{
    // Past 20x the ground's own slope matters more than the arithmetic, so
    // the number stops pretending to be one.
    bits.push('shadow ' + (ratio > 20 ? '>20x' : ratio.toFixed(1) + 'x')
              + ' toward ' + compassOf(s.az + 180));
  }}
  out.textContent = (inBand ? '\\u25b8 golden \\u25c2  ' : '') + bits.join('  \\u00b7  ');
  out.classList.toggle('in-band', !!inBand);
}}

function goldenWindowText(g) {{
  function win(b) {{
    if (!b) return null;
    return b.open_end ? hhmm(b.start) + ' onward' : hhmm(b.start) + '-' + hhmm(b.end);
  }}
  var gold = [win(g.golden_am), win(g.golden_pm)].filter(Boolean).join('  \\u00b7  ');
  var blue = [win(g.blue_am), win(g.blue_pm)].filter(Boolean).join('  \\u00b7  ');
  // One band per line. Side by side, four times and two labels ran past the
  // width of a phone and wrapped mid-time, which is the one place a break
  // is unreadable.
  var out = [];
  if (gold) out.push('<span><b class="g">golden</b> ' + gold + '</span>');
  if (blue) out.push('<span><b class="b">blue</b> ' + blue + '</span>');
  return out.join('');
}}

// Everything that belongs to looking outward at stars, hidden while looking
// inward at a model of the ground. It is daylight in this mode by
// definition, so none of it was visible anyway -- and seen from outside the
// sphere the star field sits between the camera and the thing it is meant
// to be looking at.
function setGolden(on) {{
  if (!goldenData) return;
  goldenOn = on;
  goldenGroup.visible = on;
  if (skyDome) skyDome.visible = !on;
  // Daylight, unconditionally. The star view's black backdrop is there for
  // night vision; this is a tool for standing outside in the late afternoon
  // and it should look like it, whatever the clock says -- someone planning
  // tomorrow's shoot at midnight still wants to see the scene lit.
  scene.background = on ? new THREE.Color(SKY_DAY_HEX) : null;
  scene.children.forEach(function(o) {{
    if (o === goldenGroup || o === skyDome) return;
    if (o.isPoints || o.isLineSegments) o.visible = !on;
  }});
  document.getElementById('golden-panel').hidden = !on;
  document.getElementById('golden-times').hidden = !on;
  var sky = document.getElementById('mode-sky');
  var gold = document.getElementById('mode-golden');
  sky.classList.toggle('on', !on);
  sky.setAttribute('aria-pressed', String(!on));
  gold.classList.toggle('on', on);
  gold.setAttribute('aria-pressed', String(on));
  document.body.classList.toggle('golden-mode', on);
  var times = document.getElementById('golden-times');
  if (on) times.innerHTML = goldenWindowText(goldenData);
  // Keep the address honest. Without this the mode was unshareable, lost on
  // reload, and invisible to the server -- which is also why nobody could
  // tell whether anyone used it. replaceState rather than pushState: the
  // back button should leave the page, not step through mode changes.
  try {{
    var u = new URL(window.location.href);
    if (on) u.searchParams.set('golden', '1'); else u.searchParams.delete('golden');
    window.history.replaceState(null, '', u.pathname + u.search + u.hash);
  }} catch (e) {{}}
  updateLabelVisibility();
}}

// ---- the Milky Way ------------------------------------------------------
// Drawn from the same density grid the flat chart uses, fetched once as a
// static asset: the sky's own structure is the same wherever you stand, so
// it does not belong in a per-place payload. 6 KB gzipped, cached for a
// year, shared across every place anyone ever looks at.
//
// Points rather than a texture or a mesh. The band has no edges -- it is a
// gradient with a dark rift through it -- and a cloud of small dots at the
// dome radius reads as exactly that, while a mapped texture would need an
// image and a sphere to paint it on.
var MW_COLOURS = [0x000000, 0x1c2233, 0x252d42, 0x323c56, 0x46536f, 0x5d6d8c];
var mwPoints = null, MW_LST = 0, MW_LAT = 0;

function addMilkyWay(grid, floor) {{
  if (mwPoints || !floor) return;
  var pos = [], col = [], c = new THREE.Color();
  // Every other cell in each direction: the grid is half a degree and the
  // band is diffuse, so drawing all 259,200 would cost four times as much
  // for a difference nobody can see on a phone.
  // Every cell, not every other one. Sampling coarsely and drawing big
  // points to cover the gaps is what made the band look like brickwork; a
  // dense cloud of small points is what a diffuse glow actually is.
  for (var r = 0; r < grid.rows; r++) {{
    var row = grid.rows_data[r];
    var dec = 90 - (r + 0.5) * grid.dec_step;
    for (var i = 0; i < grid.cols; i++) {{
      var v = row.charCodeAt(i) - 48;
      if (v < floor) continue;
      var ra = (i + 0.5) * grid.ra_step / 15;
      // The grid is J2000 and the payload's alt/az are of date, but this is
      // a diffuse band and precession over a few decades is a fraction of
      // one cell -- far below anything visible here.
      // Just outside the shell everything else sits on, so it is behind
      // the stars in depth as well as in draw order.
      var p = raDecToVec(ra, dec).multiplyScalar(1.06);
      pos.push(p.x, p.y, p.z);
      // Shifted down by the floor, so a worse sky paints the little that
      // survives it more faintly rather than more vividly.
      c.setHex(MW_COLOURS[Math.max(1, v - (floor - 1))]);
      col.push(c.r, c.g, c.b);
    }}
  }}
  if (!pos.length) return;
  var geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pos), 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(col), 3));
  mwPoints = new THREE.Points(geo, new THREE.PointsMaterial({{
    size: RADIUS * 0.011, vertexColors: true, transparent: true,
    opacity: 0.5, depthWrite: false, depthTest: false,
    blending: THREE.AdditiveBlending, sizeAttenuation: true}}));
  // Painted first and never into the depth buffer, so it is background in
  // the strict sense: the horizon, the ground, every star and every label
  // draws over it. It was sitting on top of the horizon line before, which
  // is the one thing a backdrop must never do.
  mwPoints.renderOrder = -10;
  scene.add(mwPoints);
}}

// RA/Dec -> the same dome position toVec() puts alt/az on. The payload
// already carries every object in alt/az, so this is the one place the
// page needs to go the other way.
function raDecToVec(raH, dec) {{
  var lst = MW_LST, lat = MW_LAT * Math.PI / 180;
  var ha = (lst - raH) * 15 * Math.PI / 180, d = dec * Math.PI / 180;
  var sinAlt = Math.sin(d) * Math.sin(lat) + Math.cos(d) * Math.cos(lat) * Math.cos(ha);
  var alt = Math.asin(Math.max(-1, Math.min(1, sinAlt)));
  var az = Math.atan2(-Math.cos(d) * Math.sin(ha),
                      Math.sin(d) * Math.cos(lat) - Math.cos(d) * Math.sin(lat) * Math.cos(ha));
  return toVec(alt * 180 / Math.PI, ((az * 180 / Math.PI) % 360 + 360) % 360);
}}

// A meteor shower's radiant: the one thing this view can do that no flat
// chart can, which is let you physically turn and face it. Drawn as a ring
// rather than a glyph because a radiant is not an object -- there is nothing
// at that point to see, it is the direction the meteors appear to come from,
// and a ring around empty sky says that better than a dot would.
//
// Placed at the radiant's alt/az at the BEST moment tonight, not at this
// instant: the radiant climbs through the night, and where to look when you
// actually go outside is the useful answer. It is therefore a fixed marker,
// not a live position, which is why nothing re-computes it on a timer.
var RADIANT_RING_SEGMENTS = 64;
var MARKER_COLOUR = 0xff9ae6;

// A ring lying flat against the sphere at the given direction. Built in a
// local frame around that direction so it reads as a circle from the middle
// rather than an ellipse seen edge-on.
function markerRing(centre, ringR, spokes) {{
  var normal = centre.clone().normalize();
  var up = Math.abs(normal.y) > 0.95 ? new THREE.Vector3(1, 0, 0)
                                     : new THREE.Vector3(0, 1, 0);
  var e1 = new THREE.Vector3().crossVectors(up, normal).normalize();
  var e2 = new THREE.Vector3().crossVectors(normal, e1).normalize();
  var pts = [];
  for (var i = 0; i <= RADIANT_RING_SEGMENTS; i++) {{
    var t = i / RADIANT_RING_SEGMENTS * Math.PI * 2;
    pts.push(centre.clone()
      .addScaledVector(e1, Math.cos(t) * ringR)
      .addScaledVector(e2, Math.sin(t) * ringR));
  }}
  scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
                           new THREE.LineBasicMaterial({{color: MARKER_COLOUR}})));
  if (!spokes) return;
  // Four short ticks pointing outward, the way meteors actually streak.
  var segs = [];
  for (var k = 0; k < 4; k++) {{
    var t2 = k / 4 * Math.PI * 2 + Math.PI / 4;
    var dir = e1.clone().multiplyScalar(Math.cos(t2))
               .addScaledVector(e2, Math.sin(t2));
    segs.push(centre.clone().addScaledVector(dir, ringR * 1.35),
              centre.clone().addScaledVector(dir, ringR * 2.1));
  }}
  scene.add(new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(segs),
    new THREE.LineBasicMaterial({{color: MARKER_COLOUR}})));
}}

var MARKERS = [];
var markerIndex = 0;

function addMarkers(list) {{
  if (!list || !list.length) return;
  MARKERS = list;
  list.forEach(function(m) {{
    var centre = toVec(m.alt, m.az);
    // A radiant is a direction with nothing at it, so it gets the big ring
    // and the outward ticks. Everything else is an object already drawn on
    // the sphere, so it gets a small ring around it: a highlight, not a
    // second copy of the thing.
    if (m.shape === 'radiant') markerRing(centre, RADIUS * 0.09, true);
    else markerRing(centre, RADIUS * 0.045, false);
    addLabel(m.glyph + ' ' + m.name, centre, 'radiant-label', 0);
  }});
  showMarker(0);
  var hud = document.getElementById('radiant-hud');
  if (hud) hud.style.display = 'block';
  liftRadiantHud();
}}

function showMarker(i) {{
  if (!MARKERS.length) return;
  markerIndex = ((i % MARKERS.length) + MARKERS.length) % MARKERS.length;
  var m = MARKERS[markerIndex];
  var text = document.getElementById('radiant-hud-text');
  var cyc = document.getElementById('radiant-hud-cycle');
  if (text) text.textContent = m.caption + ' · tap to point me at it';
  if (cyc) {{
    // Hidden entirely at one marker -- a "1/1 ›" that does nothing is worse
    // than no control. Two or more happens about ten nights a year.
    cyc.hidden = MARKERS.length < 2;
    cyc.textContent = (markerIndex + 1) + '/' + MARKERS.length + ' ›';
  }}
}}

// Reuse the find machinery rather than a second kind of pointer: same arrow
// while it's off screen, same reticle as it comes into view, same cancel
// button. Nothing to look up -- we already know exactly where it is.
function aimAtMarker() {{
  var m = MARKERS[markerIndex];
  if (!m) return;
  findMsg.textContent = '';
  findTarget = {{alt: m.alt, az: m.az,
                name: m.shape === 'radiant' ? m.name + ' radiant' : m.name}};
  findCancelBtn.hidden = false;
}}

(function() {{
  var text = document.getElementById('radiant-hud-text');
  var cyc = document.getElementById('radiant-hud-cycle');
  if (text) {{
    text.addEventListener('click', function(ev) {{ ev.preventDefault(); aimAtMarker(); }});
    text.addEventListener('keydown', function(ev) {{
      if (ev.key === 'Enter' || ev.key === ' ') {{ ev.preventDefault(); aimAtMarker(); }}
    }});
  }}
  if (cyc) {{
    cyc.addEventListener('click', function(ev) {{
      ev.preventDefault();
      ev.stopPropagation();      // cycling is not aiming
      showMarker(markerIndex + 1);
      liftRadiantHud();          // the caption length changes the wrap
    }});
  }}
}})();

// #toolbar wraps to a second row on a narrow phone, so its height is not
// knowable from CSS -- measure it and sit the HUD above whatever it actually
// is. Re-run on resize because rotating re-wraps it.
function liftRadiantHud() {{
  var hud = document.getElementById('radiant-hud');
  var bar = document.getElementById('toolbar');
  if (!hud || !bar || hud.style.display === 'none') return;
  hud.style.bottom = (bar.offsetHeight + 12) + 'px';
}}
window.addEventListener('resize', liftRadiantHud);
window.addEventListener('orientationchange', function() {{
  setTimeout(liftRadiantHud, 200);
}});

// The horizon itself, alt=0 all the way round -- doesn't depend on the
// fetch, so it's there immediately, marking where "up" (this observer's
// own visible sky) meets "down" (the full sphere's far side, added below).
(function() {{
  var pts = [];
  for (var i = 0; i <= 360; i += 2) pts.push(toVec(0, i));
  var hg = new THREE.BufferGeometry().setFromPoints(pts);
  var hm = new THREE.LineBasicMaterial({{color: 0x7ee787}});
  scene.add(new THREE.LineLoop(hg, hm));
}})();

// Each star/DSO/body carries the exact glyph + colour sky.py's ASCII
// renderer draws it with (server-computed in _compose_sphere, from the same
// glyph_for/star_colour/DSO_GLYPH functions render() itself calls) -- this
// draws that glyph onto a small canvas as a sprite texture, in solid white,
// so PointsMaterial's per-vertex vertexColors (stars, which vary star to
// star) or a flat material colour (DSOs/bodies, one colour per group) can
// tint it correctly. One texture per distinct glyph, cached and reused.
var _glyphTex = {{}};
function glyphTexture(ch) {{
  if (_glyphTex[ch]) return _glyphTex[ch];
  var px = 64;
  var canvas = document.createElement('canvas');
  canvas.width = canvas.height = px;
  var ctx = canvas.getContext('2d');
  ctx.font = Math.round(px * 0.82) + 'px "SF Mono", Menlo, monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffffff';
  ctx.fillText(ch, px / 2, px / 2 + px * 0.04);
  var tex = new THREE.CanvasTexture(canvas);
  _glyphTex[ch] = tex;
  return tex;
}}

function groupBy(items, keyFn) {{
  var m = {{}};
  items.forEach(function(it) {{ (m[keyFn(it)] = m[keyFn(it)] || []).push(it); }});
  return m;
}}

// One glyph = one star size on the ASCII chart too (glyph_for: brighter
// stars get a bigger dot) -- carried over here as pixel size per glyph.
var STAR_GLYPH_SIZE = {{'●': 13, '•': 9, '·': 5}};

function starPoints(items) {{
  var g = new THREE.BufferGeometry();
  var pos = new Float32Array(items.length * 3);
  var col = new Float32Array(items.length * 3);
  var c = new THREE.Color();
  items.forEach(function(it, i) {{
    var v = toVec(it.alt, it.az);
    pos[i * 3] = v.x; pos[i * 3 + 1] = v.y; pos[i * 3 + 2] = v.z;
    c.set(it.color);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
  }});
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  var glyph = items[0].glyph;
  var m = new THREE.PointsMaterial({{
    size: STAR_GLYPH_SIZE[glyph] || 9, map: glyphTexture(glyph), vertexColors: true,
    transparent: true, depthWrite: false, sizeAttenuation: false}});
  return new THREE.Points(g, m);
}}

function flatColourPoints(items, size) {{
  var v = items.map(function(it) {{ return toVec(it.alt, it.az); }});
  var g = new THREE.BufferGeometry().setFromPoints(v);
  var m = new THREE.PointsMaterial({{
    size: size, map: glyphTexture(items[0].glyph), color: items[0].color,
    transparent: true, depthWrite: false, sizeAttenuation: false}});
  return new THREE.Points(g, m);
}}

// Forwards the page's own query string (e.g. ?t=... for a specific
// moment) straight through to the data fetch -- otherwise a shared/
// deep-linked /sphere?t=... URL would silently render "now" instead.
// Deep-sky objects come either bundled in the initial fetch (?dso=1 was
// already in the URL) or from the DSO toggle's own on-demand refetch --
// either way they land here, tracked in dsoGroupObjs so the toggle can
// show/hide them (and their labels) instantly afterwards without touching
// the network again.
var dsoGroupObjs = [];
function addDeepSky(deepsky) {{
  var dsoGroups = groupBy(deepsky, function(o) {{ return o.type; }});
  Object.keys(dsoGroups).forEach(function(k) {{
    var pts = flatColourPoints(dsoGroups[k], 12);
    scene.add(pts);
    dsoGroupObjs.push(pts);
  }});
  // Same as render()'s ASCII chart: only the ~26 objects with a
  // hand-curated common name get a label, not all 739 -- most of the
  // catalogue only has an NGC id, and labelling every single one would be
  // both unreadable clutter and a real per-frame cost (each label runs
  // through declutterLabels()'s overlap checks every frame).
  deepsky.forEach(function(o) {{
    if (o.common_name) addLabel(o.common_name, toVec(o.alt, o.az), 'dso-label', 2);
  }});
}}

var labelsOn = true;
var dsoOn = false;
var dsoLoaded = false;

function updateLabelVisibility() {{
  LABELS.forEach(function(L) {{
    // CSS2DRenderer recomputes element.style.display from object.visible
    // every frame (see its renderObject()) -- setting style.display
    // directly here would just get silently overwritten on the next
    // labelRenderer.render() call, which is why the toggle looked like it
    // did nothing.
    L.obj.visible = labelsOn && (L.cls !== 'dso-label' || dsoOn);
  }});
}}

// Kept around so the find box can resolve a search directly against
// what's already loaded (see findInLoadedData below) instead of always
// asking the server.
var lastData = null;

// Daytime here doesn't mean daytime everywhere -- sun_alt is this observer's
// own local sky, so only the above-horizon half (the sky dome) gets tinted;
// the far side (full-sphere mode) is night for someone regardless and stays
// black. Real stars/planets/DSOs aren't actually visible against a bright
// sky, so they're dulled to grey rather than removed entirely -- the Sun
// and Moon are the two things genuinely visible in daylight, so they alone
// keep their real colour.
var DAY_DULL_COLOR = '#888888';
function dullForDaylight(data) {{
  if (data.sun_alt <= 0) return;
  data.stars.forEach(function(s) {{ s.color = DAY_DULL_COLOR; }});
  data.deepsky.forEach(function(o) {{ o.color = DAY_DULL_COLOR; }});
  data.bodies.forEach(function(b) {{
    if (b.name !== 'Sun' && b.name !== 'Moon') b.color = DAY_DULL_COLOR;
  }});
}}

var skyDome = null;
function updateSkyDome(sunAlt) {{
  document.body.classList.toggle('daytime', sunAlt > 0);
  if (skyDome) {{
    scene.remove(skyDome);
    skyDome.geometry.dispose();
    skyDome.material.dispose();
    skyDome = null;
  }}
  if (sunAlt <= 0) return;   // night (or the far side) -- plain black backdrop
  // Upper hemisphere only (thetaStart=0 at the +Y pole, thetaLength=PI/2
  // down to the horizon) -- covers exactly the alt>0 half toVec() places
  // objects in. Bigger than RADIUS and depthTest/depthWrite off so it
  // always paints as a backdrop, never occluding or fighting with the
  // actual stars/points drawn at RADIUS.
  var geo = new THREE.SphereGeometry(RADIUS + 10, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2);
  var mat = new THREE.MeshBasicMaterial({{
    color: 0x8ecbff, side: THREE.BackSide, depthTest: false, depthWrite: false}});
  skyDome = new THREE.Mesh(geo, mat);
  skyDome.renderOrder = -1;
  scene.add(skyDome);
}}

// Red mode. See the body.night rules in the stylesheet for why red, and
// for why the DOM half is done there while the scene is done here.
//
// Remembered across visits: someone who turned this on is outside in the
// dark, and making them find the button again every time they reopen the
// page defeats the point of it. localStorage throws outright in Safari's
// private mode rather than failing soft, hence the try/catch on both ends.
var nightOn = false;
try {{ nightOn = localStorage.getItem('skymap.red') === '1'; }} catch (e) {{}}

// Red mode is darker as well as redder -- dark adaptation is spent on
// total light too, not only on wavelength.
var NIGHT_DIM = 0.85;
function redify(c) {{
  var lum = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
  c.setRGB(lum * NIGHT_DIM, lum * NIGHT_DIM * 0.09, lum * NIGHT_DIM * 0.03);
}}

// Red mode is a filter over the real colours, never a replacement for
// them: whatever an object would be in normal mode is remembered the
// first time it's seen, and every repaint maps from that. Mapping from
// whatever was last drawn would compound red on red on every toggle.
function setTrueColor(mat, hex) {{
  mat.userData.trueColor = hex;
  mat.color.setHex(hex);
  if (nightOn) redify(mat.color);
}}

function paintScene() {{
  scene.traverse(function(o) {{
    var mat = o.material;
    // A vertexColors material keeps material.color at plain white, as a
    // multiplier over the per-star colours handled just below -- mapping
    // that white to red as well would apply the filter twice.
    if (mat && mat.color && !mat.vertexColors) {{
      if (mat.userData.trueColor === undefined) mat.userData.trueColor = mat.color.getHex();
      mat.color.setHex(mat.userData.trueColor);
      if (nightOn) redify(mat.color);
    }}
    var geo = o.geometry;
    var attr = geo && geo.getAttribute ? geo.getAttribute('color') : null;
    if (!attr) return;
    if (!geo.userData.trueColor) geo.userData.trueColor = attr.array.slice();
    var src = geo.userData.trueColor, arr = attr.array;
    for (var i = 0; i < arr.length; i += 3) {{
      if (nightOn) {{
        var lum = 0.2126 * src[i] + 0.7152 * src[i + 1] + 0.0722 * src[i + 2];
        arr[i] = lum * NIGHT_DIM;
        arr[i + 1] = lum * NIGHT_DIM * 0.09;
        arr[i + 2] = lum * NIGHT_DIM * 0.03;
      }} else {{
        arr[i] = src[i]; arr[i + 1] = src[i + 1]; arr[i + 2] = src[i + 2];
      }}
    }}
    attr.needsUpdate = true;
  }});
  document.body.classList.toggle('night', nightOn);
  _paintedChildren = scene.children.length;
}}

// Scene objects arrive at four unrelated moments: the first fetch, the
// deep sky toggle's own fetch, a find marker landing, and a time-scrub
// reload. Watching the child count in animate() catches all of them for
// one integer compare per frame, which beats threading a repaint call
// through every call site that ever adds something and quietly missing
// the one added next year.
var _paintedChildren = -1;

var nightBtn = document.getElementById('night-toggle');
nightBtn.classList.toggle('on', nightOn);
nightBtn.addEventListener('click', function() {{
  nightOn = !nightOn;
  this.classList.toggle('on', nightOn);
  try {{ localStorage.setItem('skymap.red', nightOn ? '1' : '0'); }} catch (e) {{}}
  paintScene();
}});
paintScene();   // sets body.night now, before any of the sky has loaded

// The phone locking itself every 30 seconds while you hold it up at the
// sky is the single most annoying thing it can do to this page. Chrome on
// Android and Safari 16.4+ have the Wake Lock API; everywhere else the
// request rejects and the page carries on exactly as before.
var _wakeLock = null;
function requestWakeLock() {{
  if (!('wakeLock' in navigator) || _wakeLock) return;
  navigator.wakeLock.request('screen').then(function(wl) {{
    _wakeLock = wl;
    wl.addEventListener('release', function() {{ _wakeLock = null; }});
  }}).catch(function() {{}});
}}
// A lock is dropped, not paused, the moment the page stops being visible,
// and is never restored on its own -- without this it would survive
// exactly one tab switch and then silently stop working for the rest of
// the session.
document.addEventListener('visibilitychange', function() {{
  if (document.visibilityState === 'visible') requestWakeLock();
}});
enableBtn.addEventListener('click', requestWakeLock);
requestWakeLock();

fetch('/' + PLACE + '/sphere.json' + window.location.search).then(function(r) {{
  if (!r.ok) throw new Error('sphere.json ' + r.status);
  return r.json();
}}).then(function(data) {{
  lastData = data;
  dullForDaylight(data);
  updateSkyDome(data.sun_alt);
  var starGroups = groupBy(data.stars, function(s) {{ return s.glyph; }});
  Object.keys(starGroups).forEach(function(k) {{ scene.add(starPoints(starGroups[k])); }});
  // Every named star gets a label -- the ASCII chart caps this at the 9
  // brightest since a label there eats character cells other stars need;
  // nothing here competes for space, so there's no reason to cap it.
  data.stars.forEach(function(s) {{
    if (s.name) addLabel(s.name, toVec(s.alt, s.az), 'star-label', 3);
  }});

  if (data.deepsky.length) {{
    addDeepSky(data.deepsky);
    dsoLoaded = true; dsoOn = true;
    var dsoBtn = document.getElementById('dso-toggle');
    if (dsoBtn) dsoBtn.classList.add('on');
  }}

  // Bodies are few (0-9) and each can have its own glyph (Moon's phase
  // glyph varies night to night) -- one Points per body rather than
  // grouping, simplicity costs nothing at this count.
  data.bodies.forEach(function(b) {{
    scene.add(flatColourPoints([b], b.name === 'Moon' ? 26 : 18));
    addLabel(b.name, toVec(b.alt, b.az), 'body-label', 0);
  }});

  addMarkers(data.markers);
  // The band, if this sky is dark enough for any of it. Fetched separately
  // and never blocking: the sphere is already on screen by the time this
  // lands, and a sky without it is the sky you had a moment ago rather than
  // a broken one.
  MW_LST = data.lst_hours;
  MW_LAT = data.lat;
  if (data.milkyway_floor) {{
    fetch('/milkyway.json')
      .then(function(r) {{ return r.json(); }})
      .then(function(grid) {{ addMilkyWay(grid, data.milkyway_floor); }})
      .catch(function() {{}});
  }}
  // Built once, up front, and left hidden. The whole layer is ~1.5 KB
  // gzipped on top of a payload that already carries 630 stars, so paying
  // for it eagerly buys an instant toggle with no second round trip -- the
  // deep-sky button lazy-loads because its data is genuinely large, which
  // this is not.
  if (data.golden) {{
    buildGolden(data.golden);
    var scrub = document.getElementById('golden-scrub');
    scrub.value = data.golden.now_min;
    // The second cell only earns its place where there is a golden hour to
    // show. At a pole in winter the Sun never climbs into the band at all,
    // and offering the mode there would be an empty promise.
    if (data.golden.note !== 'never') {{
      document.getElementById('mode-golden').hidden = false;
      // ?golden=1 lands you straight in the mode, so a shared link opens on
      // what the sender was looking at rather than on the star sphere.
      try {{
        if (new URL(window.location.href).searchParams.get('golden')) setGolden(true);
      }} catch (e) {{}}
    }}
  }}

  var linePts = [];
  data.asterisms.forEach(function(con) {{
    var conPts = [];
    con.segments.forEach(function(seg) {{
      var p1 = toVec(seg[0][0], seg[0][1]), p2 = toVec(seg[1][0], seg[1][1]);
      linePts.push(p1, p2);
      conPts.push(p1, p2);
    }});
    // Labelled at the centroid of its own lines, re-projected onto the same
    // dome radius -- there's no single "right" spot the way a star has one,
    // but the middle of the shape reads better than any single endpoint.
    var centroid = new THREE.Vector3();
    conPts.forEach(function(p) {{ centroid.add(p); }});
    centroid.divideScalar(conPts.length).normalize().multiplyScalar(RADIUS);
    addLabel(con.name, centroid, 'con-label', 1);
  }});
  if (linePts.length) {{
    var lg = new THREE.BufferGeometry().setFromPoints(linePts);
    var lm = new THREE.LineBasicMaterial({{color: 0x3b4a6b}});
    scene.add(new THREE.LineSegments(lg, lm));
  }}
  // data.stars.length is the full-sphere total (above AND below the
  // horizon, since full-sphere mode keeps both) -- "stars up" specifically
  // means above the horizon, so it's counted separately here rather than
  // just using the raw total, which would overstate what's actually visible.
  var starsUp = data.stars.filter(function(s) {{ return s.alt > 0; }}).length;
  if (data.sun_alt > 0) {{
    var when = data.hours_to_dark == null ? "the sky won't get fully dark today"
      : 'darkest sky in about ' + (data.hours_to_dark < 1
          ? Math.round(data.hours_to_dark * 60) + ' min'
          : (Math.round(data.hours_to_dark * 10) / 10) + 'h');
    statusEl.textContent = data.place + ': ' + starsUp + ' stars visible (or would ' +
      'be, without the Sun in the way), ' + when + '. Look around you.';
  }} else {{
    statusEl.textContent = data.place + ': ' + starsUp + ' stars up. Look around you.';
  }}
}}).catch(function(err) {{
  statusEl.textContent = "Couldn't load the sky (" + err.message + "), tap to retry.";
}});

var mode = null;
var gotOrientation = false;
var gyroTimer = null;
var lastEvent = null;

// Standard device-orientation-to-camera-quaternion conversion (the same
// math three.js's own DeviceOrientationControls example uses) -- this is
// "look around from where you're standing", not an orbit-around-an-object
// control, so OrbitControls doesn't fit and isn't imported.
var euler = new THREE.Euler();
var q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));
var deviceQ = new THREE.Quaternion();
// True compass heading, not wherever the phone happened to be facing when
// the page loaded. Two wrinkles: iOS never puts a real compass value in
// plain `alpha` (the standard leaves it unreferenced there -- Safari's own
// fix is the non-standard webkitCompassHeading field, clockwise from true
// north, so it's converted back to the standard's counterclockwise-from-
// north convention below). Everywhere else, deviceorientationabsolute
// (used in preference to deviceorientation when the browser supports it)
// guarantees alpha is north-referenced, which plain deviceorientation does
// not always promise.
var _orientEvent = 'ondeviceorientationabsolute' in window
  ? 'deviceorientationabsolute' : 'deviceorientation';

// No jitter filtering here on purpose. An earlier version dead-zoned each
// angle, but the jitter it was built for was the magnetometer's, back when
// the magnetometer drove the view directly -- alpha is gyro-fused and
// steady enough on its own. All a dead zone adds now is its own artefact:
// slow pans quantise into visible steps instead of moving smoothly.
//
// webkitCompassHeading is the only true-north reference iOS offers, but
// it's magnetometer-derived: its tilt compensation degrades badly as the
// phone approaches vertical -- which is exactly how this app gets held,
// pointing at the sky. `alpha` on the same event is gyro-fused: smooth and
// steady moment to moment, but its zero point is arbitrary (it's whatever
// the phone decided at page load, which is why the very first version of
// this view needed a manual "recentre" and never showed true north).
//
// So use both for what each is actually good at, the standard
// complementary-filter split: render from alpha, and let the compass only
// teach us the constant offset between alpha's arbitrary zero and true
// north -- applied slowly, not trusted frame by frame. A brief compass
// glitch then barely moves the view; only sustained disagreement pulls the
// heading back. The gain drops near vertical, where the compass is known
// to be unreliable, so the gyro carries the heading through exactly the
// poses that used to make it jump.
var OFFSET_GAIN_GOOD = 0.05;    // phone well off vertical: trust the compass
var OFFSET_GAIN_POOR = 0.002;   // near vertical: coast on the gyro instead
var COMPASS_TRUST_BETA = 70;    // degrees from flat where that switch happens
var _offCos = null, _offSin = null;

function feedCompassOffset(offsetDeg, beta) {{
  var r = offsetDeg * Math.PI / 180;
  var c = Math.cos(r), s = Math.sin(r);
  // First reading snaps, so north is right immediately rather than
  // easing in from wherever the phone happened to start.
  if (_offCos === null) {{ _offCos = c; _offSin = s; return; }}
  var g = Math.abs(beta) < COMPASS_TRUST_BETA ? OFFSET_GAIN_GOOD : OFFSET_GAIN_POOR;
  // Averaged as a unit vector, not raw degrees, so 359 -> 0 wraps cleanly.
  _offCos += (c - _offCos) * g;
  _offSin += (s - _offSin) * g;
}}

function compassOffsetDeg() {{
  return _offCos === null ? 0 : Math.atan2(_offSin, _offCos) * 180 / Math.PI;
}}

function applyOrientation(e) {{
  if (e.beta === null || e.gamma === null) return;
  var alphaDeg;
  var hasCompass = typeof e.webkitCompassHeading === 'number' && !isNaN(e.webkitCompassHeading);
  if (hasCompass && e.alpha !== null) {{
    // (360 - heading) converts the compass's clockwise-from-north reading
    // into the same counterclockwise-from-north convention alpha uses, so
    // the two are directly comparable and their difference is the offset.
    feedCompassOffset((360 - e.webkitCompassHeading) % 360 - e.alpha, e.beta);
    alphaDeg = ((e.alpha + compassOffsetDeg()) % 360 + 360) % 360;
  }} else if (hasCompass) {{
    alphaDeg = (360 - e.webkitCompassHeading) % 360;
  }} else if (e.alpha !== null) {{
    // deviceorientationabsolute (Android and friends) already gives a
    // north-referenced, fused alpha -- nothing to correct.
    alphaDeg = e.alpha;
  }} else {{
    return;
  }}
  var alpha = alphaDeg * Math.PI / 180, beta = e.beta * Math.PI / 180, gamma = e.gamma * Math.PI / 180;
  euler.set(beta, alpha, -gamma, 'YXZ');
  deviceQ.setFromEuler(euler);
  deviceQ.multiply(q1);
  // No screen-orientation (portrait/landscape) compensation -- this page
  // never actually changes layout for landscape, it's always meant to be
  // read the same way regardless of how the phone is currently tilted.
  // iOS still tracks portrait/landscape internally off the phone's raw
  // angle though, and that compensation used to be applied here too -- so
  // normal use (tilting well off-vertical to look up, or turning around)
  // could cross iOS's internal orientation threshold and suddenly rotate
  // the whole scene 90 degrees for no visible reason.
  camera.quaternion.copy(deviceQ);
  if (DEBUG) {{
    debugEl.textContent =
      'raw alpha: ' + (e.alpha === null ? 'null' : e.alpha.toFixed(1)) +
        '  ->  rendered: ' + alphaDeg.toFixed(1) + '\\n' +
      'webkitCompassHeading: ' + (typeof e.webkitCompassHeading === 'number' ? e.webkitCompassHeading.toFixed(1) : 'n/a') + '\\n' +
      'raw beta: ' + (e.beta === null ? 'null' : e.beta.toFixed(1)) + '\\n' +
      'raw gamma: ' + (e.gamma === null ? 'null' : e.gamma.toFixed(1)) + '\\n' +
      'north offset: ' + compassOffsetDeg().toFixed(1) +
        '  (compass ' + (Math.abs(e.beta) < COMPASS_TRUST_BETA ? 'TRUSTED' : 'coasting') + ')\\n' +
      'event type: ' + _orientEvent + ' / absolute: ' + e.absolute + '\\n' +
      'fps: ' + _fps;
  }}
}}

function onOrientation(e) {{
  gotOrientation = true;
  if (gyroTimer) {{ clearTimeout(gyroTimer); gyroTimer = null; }}
  lastEvent = e;
}}

function startGyro() {{
  mode = 'gyro';
  modeLabel.textContent = 'gyroscope';
  window.addEventListener(_orientEvent, onOrientation);
  gyroTimer = setTimeout(function() {{ if (!gotOrientation) startDrag(); }}, 1500);
  overlay.hidden = true;
}}

var yaw = 0, pitch = 0, dragging = false, lastX = 0, lastY = 0;
function startDrag() {{
  if (mode === 'drag') return;
  mode = 'drag';
  modeLabel.textContent = 'drag';
  window.removeEventListener(_orientEvent, onOrientation);
  overlay.hidden = true;
  var el = renderer.domElement;
  el.addEventListener('pointerdown', function(ev) {{ dragging = true; lastX = ev.clientX; lastY = ev.clientY; }});
  window.addEventListener('pointerup', function() {{ dragging = false; }});
  window.addEventListener('pointermove', function(ev) {{
    if (!dragging) return;
    yaw -= (ev.clientX - lastX) * 0.005;
    pitch -= (ev.clientY - lastY) * 0.005;
    pitch = Math.max(-1.5, Math.min(1.5, pitch));
    lastX = ev.clientX; lastY = ev.clientY;
  }});
}}

// Now that mobile lands here directly (the text page's own place search
// is effectively unreachable -- visiting it just redirects straight back),
// this is the only way left to jump to a different place from a phone.
document.getElementById('place-form').addEventListener('submit', function(ev) {{
  ev.preventDefault();
  var val = document.getElementById('place-input').value.trim();
  if (!val) return;
  location.href = '/' + encodeURIComponent(val) + '/sphere';
}});

// iOS Safari's DeviceOrientationEvent.requestPermission() only works when
// called directly inside a real user gesture on THIS document -- a tap
// elsewhere (e.g. the place-search "Go" button, which navigates here) does
// not count once the page has reloaded, so iOS genuinely cannot skip this
// tap. Nothing else needs it: Android grants motion access silently, and
// the drag fallback needs no permission at all -- both start immediately
// on load instead of waiting for a click that serves no purpose there.
if (typeof DeviceOrientationEvent !== 'undefined' &&
    typeof DeviceOrientationEvent.requestPermission === 'function') {{
  enableBtn.addEventListener('click', function() {{
    DeviceOrientationEvent.requestPermission().then(function(state) {{
      if (state === 'granted') startGyro(); else startDrag();
    }}).catch(function() {{ startDrag(); }});
  }});
}} else if (typeof DeviceOrientationEvent !== 'undefined') {{
  startGyro();
}} else {{
  startDrag();
}}

document.getElementById('labels-toggle').addEventListener('click', function() {{
  labelsOn = !labelsOn;
  this.classList.toggle('on', labelsOn);
  updateLabelVisibility();
}});

// Pinch and wheel move the camera, not the page. The page used to be the
// only thing that zoomed, which meant getting close enough to read the
// shadow scaled the whole document and left the scene in a black margin --
// so this replaces a browser gesture that was actively unhelpful with the
// control it was standing in for. Only in golden mode: the star view puts
// you at the centre, where there is nothing to move closer to.
function _clampOrbit(v) {{
  return Math.max(ORBIT_MIN, Math.min(ORBIT_MAX, v));
}}
function _touchSpan(e) {{
  var dx = e.touches[0].clientX - e.touches[1].clientX;
  var dy = e.touches[0].clientY - e.touches[1].clientY;
  return Math.hypot(dx, dy);
}}
var _pinchSpan = 0;
window.addEventListener('touchstart', function(e) {{
  if (e.touches.length === 2) _pinchSpan = _touchSpan(e);
}}, {{passive: true}});
window.addEventListener('touchmove', function(e) {{
  if (!goldenOn || e.touches.length !== 2) return;
  e.preventDefault();
  var span = _touchSpan(e);
  if (_pinchSpan > 0 && span > 0) orbitR = _clampOrbit(orbitR * _pinchSpan / span);
  _pinchSpan = span;
}}, {{passive: false}});
window.addEventListener('touchend', function() {{ _pinchSpan = 0; }}, {{passive: true}});
window.addEventListener('wheel', function(e) {{
  if (!goldenOn) return;
  e.preventDefault();
  orbitR = _clampOrbit(orbitR * (1 + e.deltaY * 0.0015));
}}, {{passive: false}});
// iOS Safari ignores maximum-scale, and these are the events it zooms the
// document with. Blocked outright: nothing on this page wants them.
['gesturestart', 'gesturechange', 'gestureend'].forEach(function(g) {{
  document.addEventListener(g, function(e) {{ e.preventDefault(); }}, {{passive: false}});
}});

// Fired only for a switch someone actually made, never for a page that
// arrived already in the mode -- ?golden=1 counts those, and beaconing them
// too would count one visitor twice.
function beaconGolden() {{
  try {{
    if (navigator.sendBeacon) navigator.sendBeacon('/beacon/golden');
    else fetch('/beacon/golden', {{keepalive: true}});
  }} catch (e) {{}}
}}

document.getElementById('mode-sky').addEventListener('click', function() {{
  setGolden(false);
}});
document.getElementById('mode-golden').addEventListener('click', function() {{
  if (!goldenOn) beaconGolden();
  setGolden(true);
}});

document.getElementById('golden-scrub').addEventListener('input', function() {{
  setSunAt(Number(this.value));
}});

// Same letter the flat chart uses for the same layer.
window.addEventListener('keydown', function(e) {{
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  var t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
  if (e.key === 'g') {{
    e.preventDefault();
    if (!goldenOn) beaconGolden();
    setGolden(!goldenOn);
  }}
}});

document.getElementById('dso-toggle').addEventListener('click', function() {{
  var btn = this;
  if (!dsoLoaded) {{
    // Off by default (most deep-sky objects need binoculars) -- fetched
    // fresh, once, only when actually asked for; cached in dsoGroupObjs
    // afterwards so toggling again is instant, no repeat network call.
    btn.disabled = true; btn.textContent = 'Deep sky…';
    var qs = window.location.search
      ? window.location.search + '&dso=1' : '?dso=1';
    fetch('/' + PLACE + '/sphere.json' + qs).then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        dullForDaylight(data);
        addDeepSky(data.deepsky);
        if (lastData) lastData.deepsky = data.deepsky;
        dsoLoaded = true; dsoOn = true;
        btn.disabled = false; btn.textContent = 'Deep sky';
        btn.classList.add('on');
        updateLabelVisibility();
      }}).catch(function() {{
        btn.disabled = false; btn.textContent = 'Deep sky (failed, retry)';
      }});
    return;
  }}
  dsoOn = !dsoOn;
  btn.classList.toggle('on', dsoOn);
  dsoGroupObjs.forEach(function(o) {{ o.visible = dsoOn; }});
  updateLabelVisibility();
}});

// The arrow/crosshair guide. Resolved two ways: first against whatever's
// already loaded (stars/deepsky/bodies/asterisms) -- which, in full-sphere
// mode, already includes everything regardless of altitude sign or how
// bright the sky background is right now, so Venus (lost in solar glare)
// or a below-horizon star are just as findable as anything overhead. Only
// falls back to the server's /{{place}}?find=...&format=json (api.py's
// _compose_find, unchanged) for names not already loaded -- a fainter
// named star below the sphere's magnitude cutoff, or a deep-sky object
// before the DSO toggle has ever been switched on.
var findTarget = null;
var CROSSHAIR_THRESHOLD_DEG = 10;   // roughly "on screen" -- switch from arrow to reticle
var CENTERED_THRESHOLD_DEG = 3;     // a real tolerance, not pixel-perfect aim
var FIND_COLOR_ARROW = '#ffd700';
var FIND_COLOR_RETICLE = '#ff87ff';
var FIND_COLOR_FOUND = '#7ee787';
var findMsg = document.getElementById('find-msg');
var findArrow = document.getElementById('find-arrow');
var findCancelBtn = document.getElementById('find-cancel');
var findReticle = document.getElementById('find-reticle');
var reticleTicks = {{
  top: findReticle.querySelector('.tick-top'),
  bottom: findReticle.querySelector('.tick-bottom'),
  left: findReticle.querySelector('.tick-left'),
  right: findReticle.querySelector('.tick-right')
}};

function findInLoadedData(name) {{
  if (!lastData) return null;
  var q = name.trim().toLowerCase();
  var b = lastData.bodies.find(function(x) {{ return x.name.toLowerCase() === q; }});
  if (b) return {{alt: b.alt, az: b.az, name: b.name}};
  var s = lastData.stars.find(function(x) {{ return x.name && x.name.toLowerCase() === q; }});
  if (s) return {{alt: s.alt, az: s.az, name: s.name}};
  var o = lastData.deepsky.find(function(x) {{
    return (x.common_name && x.common_name.toLowerCase() === q) ||
          (x.name && x.name.toLowerCase() === q) || x.id.toLowerCase() === q;
  }});
  if (o) return {{alt: o.alt, az: o.az, name: o.common_name || o.name}};
  var con = lastData.asterisms.find(function(x) {{ return x.name.toLowerCase() === q; }});
  if (con) {{
    var pts = [];
    con.segments.forEach(function(seg) {{ pts.push(toVec(seg[0][0], seg[0][1]), toVec(seg[1][0], seg[1][1])); }});
    var c = new THREE.Vector3();
    pts.forEach(function(p) {{ c.add(p); }});
    c.divideScalar(pts.length).normalize();
    var alt = Math.asin(c.y) * 180 / Math.PI;
    var az = (Math.atan2(c.x, -c.z) * 180 / Math.PI + 360) % 360;
    return {{alt: alt, az: az, name: con.name}};
  }}
  return null;
}}

document.getElementById('find-form').addEventListener('submit', function(ev) {{
  ev.preventDefault();
  var input = document.getElementById('find-input');
  var name = input.value.trim();
  if (!name) return;
  input.blur();   // dismiss the keyboard
  findTarget = null;
  findArrow.style.display = 'none';
  findReticle.style.display = 'none';
  findMsg.textContent = '';
  var local = findInLoadedData(name);
  if (local) {{
    findTarget = local;
    findCancelBtn.hidden = false;
    return;
  }}
  findMsg.textContent = 'Looking for ' + name + '…';
  findMsg.style.color = FIND_COLOR_ARROW;
  findCancelBtn.hidden = false;
  var qs = 'find=' + encodeURIComponent(name) + '&format=json';
  var t = new URLSearchParams(window.location.search).get('t');
  if (t) qs += '&t=' + encodeURIComponent(t);
  fetch('/' + PLACE + '?' + qs).then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.error) {{
        findMsg.textContent = "Don't know \\"" + name + '"';
        findCancelBtn.hidden = true;
        return;
      }}
      if (d.alt != null && d.az != null) {{
        // A real position exists -- point at it regardless of d.visible,
        // which is really "could a human eye pick this out right now"
        // (glare, twilight brightness), not "does it have a location".
        findTarget = {{alt: d.alt, az: d.az, name: d.target}};
        return;
      }}
      if (d.next_visible) {{
        findMsg.textContent = d.target + ' is not up right now, next visible ' +
          d.next_visible.when_local.replace('T', ' ') + ', ' + d.next_visible.compass + '.';
        findCancelBtn.hidden = true;
        return;
      }}
      // No position at all was computed (e.g. Venus buried in the Sun's
      // glare with no window in the next 40 days) -- nothing to point at.
      findMsg.textContent = d.target + ' is not visible from ' + d.place + ': ' +
        (d.solar_elongation != null && d.solar_elongation < 20
          ? 'only ' + Math.round(d.solar_elongation) + '° from the Sun, too deep in the glare for weeks.'
          : 'no window in the next 40 days from here.');
      findCancelBtn.hidden = true;
    }}).catch(function() {{
      findMsg.textContent = 'Search failed, try again.';
      findCancelBtn.hidden = true;
    }});
}});

findCancelBtn.addEventListener('click', function() {{
  findTarget = null;
  findArrow.style.display = 'none';
  findReticle.style.display = 'none';
  findMsg.textContent = '';
  findCancelBtn.hidden = true;
}});

function updateFindArrow() {{
  if (!findTarget) {{ findArrow.style.display = 'none'; findReticle.style.display = 'none'; return; }}
  camera.updateMatrixWorld(true);   // animate() hasn't rendered yet this frame
  var v = toVec(findTarget.alt, findTarget.az);
  _forward.set(0, 0, -1).applyQuaternion(camera.quaternion);
  var angularDist = _forward.angleTo(v) * 180 / Math.PI;

  if (angularDist < CENTERED_THRESHOLD_DEG) {{
    // Found -- not pixel-perfect aim, just within a real tolerance. Drop a
    // marker on the object itself (an ordinary scene object, so it tracks
    // the real star/planet like everything else already does) and stop
    // running any of this per-frame guidance from here on -- findTarget =
    // null makes every future call a no-op above. The purple highlight is
    // transient -- five seconds is enough to register it, then the label
    // clears and the marker itself fades to a plain white dot, a quieter
    // trace rather than permanent purple clutter.
    var foundPoint = flatColourPoints(
      [{{alt: findTarget.alt, az: findTarget.az, glyph: '●', color: '#ff87ff'}}], 16);
    scene.add(foundPoint);
    var foundLabel = addLabel(findTarget.name, v, 'found-label', 0);
    var foundName = findTarget.name;
    setTimeout(function() {{
      // Via setTrueColor, not material.color directly: in red mode a raw
      // white here would be the one bright white dot on an otherwise red
      // screen, five seconds after every successful find.
      setTrueColor(foundPoint.material, 0xffffff);
      removeLabel(foundLabel);
      if (findMsg.textContent === '✓ Found: ' + foundName + '!') findMsg.textContent = '';
    }}, 5000);
    findMsg.textContent = '✓ Found: ' + findTarget.name + '!';
    findMsg.style.color = FIND_COLOR_FOUND;
    findArrow.style.display = 'none';
    findReticle.style.display = 'none';
    findCancelBtn.hidden = true;
    findTarget = null;
    return;
  }}

  _camSpace.copy(v).applyMatrix4(camera.matrixWorldInverse);
  var behind = _camSpace.z > 0;
  _projected.copy(v).project(camera);
  var cx = window.innerWidth / 2, cy = window.innerHeight / 2;
  var sx = (_projected.x * 0.5 + 0.5) * window.innerWidth;
  var sy = (1 - (_projected.y * 0.5 + 0.5)) * window.innerHeight;

  if (!behind && angularDist < CROSSHAIR_THRESHOLD_DEG) {{
    // On screen but not centred yet -- four ticks closing in from outside
    // toward the object as angularDist shrinks, forming a solid cross
    // right at the edge of the tolerance above. The arrow disappears the
    // moment this reticle appears, not after.
    findArrow.style.display = 'none';
    findReticle.style.left = sx + 'px';
    findReticle.style.top = sy + 'px';
    findReticle.style.display = 'block';
    var t = (angularDist - CENTERED_THRESHOLD_DEG) / (CROSSHAIR_THRESHOLD_DEG - CENTERED_THRESHOLD_DEG);
    var gap = 3 + t * 34;
    reticleTicks.top.style.transform = 'translate(-1px,' + (-gap - 14) + 'px)';
    reticleTicks.bottom.style.transform = 'translate(-1px,' + gap + 'px)';
    reticleTicks.left.style.transform = 'translate(' + (-gap - 14) + 'px,-1px)';
    reticleTicks.right.style.transform = 'translate(' + gap + 'px,-1px)';
    findMsg.textContent = 'Almost there, ' + findTarget.name;
    findMsg.style.color = FIND_COLOR_RETICLE;
    return;
  }}

  findReticle.style.display = 'none';
  // When it's behind the camera, the raw screen projection points the
  // wrong way (perspective divide by a negative w flips it) -- flipping
  // both axes is the standard correction, close enough for "which way to
  // turn" even though a single 2D arrow can't fully capture a behind-you
  // direction.
  var dx = behind ? -(sx - cx) : (sx - cx);
  var dy = behind ? -(sy - cy) : (sy - cy);
  var angle = Math.atan2(dy, dx);
  var r = Math.min(cx, cy) - 40;
  findArrow.style.left = (cx + Math.cos(angle) * r) + 'px';
  findArrow.style.top = (cy + Math.sin(angle) * r) + 'px';
  // ">>>" points right by default (angle 0), so -- unlike the old ▲ glyph,
  // which needed a +90 degree correction to go from "points up" to
  // "points along angle" -- this rotates directly by the raw angle.
  findArrow.style.transform = 'translate(-50%,-50%) rotate(' + (angle * 180 / Math.PI) + 'deg)';
  findArrow.style.display = 'block';
  findMsg.textContent = 'Looking for ' + findTarget.name + '…';
  findMsg.style.color = FIND_COLOR_ARROW;
}}

// Inverse of toVec() -- camera forward direction back to alt/az degrees,
// for the HUD heading/tilt readout. y = sin(alt); x,z give az via atan2
// (dividing both by cos(alt) before atan2 would be a no-op on the angle).
var _forward = new THREE.Vector3();
var _frame = 0;
function updateHeading() {{
  _forward.set(0, 0, -1).applyQuaternion(camera.quaternion);
  var alt = Math.asin(Math.max(-1, Math.min(1, _forward.y))) * 180 / Math.PI;
  var az = (Math.atan2(_forward.x, -_forward.z) * 180 / Math.PI + 360) % 360;
  headingEl.textContent = Math.round(az) + '° ' + compass16(az) +
    ' · ' + (alt >= 0 ? '+' : '') + Math.round(alt) + '°';
}}

function animate() {{
  requestAnimationFrame(animate);
  if (DEBUG) {{
    _fpsFrames++;
    var _now = performance.now();
    if (_now - _fpsLast >= 1000) {{
      _fps = Math.round(_fpsFrames * 1000 / (_now - _fpsLast));
      _fpsFrames = 0;
      _fpsLast = _now;
    }}
  }}
  if (mode === 'gyro' && lastEvent) {{
    applyOrientation(lastEvent);
  }} else if (mode === 'drag') {{
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  }}
  // The whole of the outside-in view. Both control paths above have already
  // said which way you are facing; a camera at -R along its own view axis
  // looks straight back through the origin, so the same quaternion that
  // aimed you at a patch of sky now walks you around the model instead.
  // Nothing else about the orientation code changes, compass filter
  // included, and drag orbits on a desktop for free.
  if (goldenOn) {{
    _look.set(0, 0, -1).applyQuaternion(camera.quaternion);
    camera.position.copy(_look).multiplyScalar(-orbitR);
  }} else if (camera.position.lengthSq() !== 0) {{
    camera.position.set(0, 0, 0);
  }}
  // Both run at ~15fps instead of every frame: updateHeading() is just a
  // text readout, no need for 60fps; declutterLabels() only adjusts each
  // label's overlap-avoidance nudge (the label itself still tracks the
  // camera every frame via labelRenderer.render() below), and its sort +
  // per-pair overlap check over every labeled object was real, continuous
  // GC pressure that added up over a long session.
  if (scene.children.length !== _paintedChildren) paintScene();
  var throttleTick = mode && ++_frame % 4 === 0;
  if (throttleTick) updateHeading();
  updateFindArrow();
  renderer.render(scene, camera);
  if (throttleTick) declutterLabels();
  labelRenderer.render(scene, camera);
}}
animate();
</script>
</body></html>"""


# The comments come out of the CSS and the script here, once, at import --
# not out of this file, which keeps every one of them. See minify.py for why
# it is a tokeniser and not a regular expression.
#
# Last thing in the module on purpose. Everything that assembles these
# strings has already run: the ladder rules, the command bar's CSS and
# script, and the slot markers are all baked into PAGE by now, so one pass
# over it covers all four. Run any earlier and whatever was spliced in
# afterwards would keep its comments.
#
# Safe to run before .format(): only comment text is removed, and a format
# field inside a comment was never going to be read.
PAGE = minify.strip_page(PAGE)
SPHERE_PAGE = minify.strip_page(SPHERE_PAGE)
OBJECT_CSS = minify.strip_page(OBJECT_CSS)


def _controls_inner(explore, animate_btn, quadrant_btn, sphere_btn, extra):
    # Block layout, one section per group -- a ~320px drawer has no room
    # for the old controls-row's inline flex-wrap, and grouped sections read
    # far better stacked than crammed into one wrapping row anyway.
    # sphere_btn (mobile-only "View in 3D" link) sits before extra, same
    # order it's always been in; RESET_HTML comes last in the actions
    # section, after the page-specific stuff, on every page -- which also
    # means that section is never actually empty any more, so the old
    # :empty-collapses-it behaviour for non-chart pages no longer applies
    # (there's now always at least "reset" to show there).
    return (f'<div class="drawer-section">{DRAWER_LINKS_HTML}</div>'
            f'<div class="drawer-section">{explore}</div>'
            f'<div class="drawer-section">{animate_btn}{quadrant_btn}{sphere_btn}{extra}'
            f'{RESET_HTML}</div>'
            f'<div class="drawer-section">{EXAMPLES_HTML}</div>')


def controls_html(explore, animate_btn="", quadrant_btn="", sphere_btn="", extra=""):
    """The drawer's content -- explore form, toolbar, examples -- identical
    on every page including the chart view (animate_btn/quadrant_btn/
    sphere_btn/extra are "" on every page except the chart, which is the
    only one that has anything to put there).

    No-JS fallback is load-bearing, not decoration: without PAGE's script
    adding the .js class to <html>, #drawer's CSS never applies the fixed/
    off-canvas/hidden styling at all, so this just renders as a normal
    visible block on the page -- every control still reachable, just not as
    a slide-in panel. header_html's trigger button is hidden by the same
    means (it would do nothing without the JS that drives it, and the
    content it'd reveal is already on the page). #drawer-close (top-right,
    inside the panel itself) is hidden the same way too -- it's a second,
    more discoverable way to close it once open, not the only one (the
    trigger itself, clicking outside, and Escape all already do it)."""
    return (f'<div id="drawer">'
            f'<button type="button" class="drawer-close" id="drawer-close" '
            f'aria-label="Close">✕</button>'
            f'{_controls_inner(explore, animate_btn, quadrant_btn, sphere_btn, extra)}'
            f'</div>')
