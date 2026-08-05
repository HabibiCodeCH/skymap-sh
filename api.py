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

import sky
import objects
from sky import (C, paint, julian, gmst_hours, altaz, angsep, compass, moon_glyph,
                 phase_name, resolve_target, visibility, next_visible,
                 solar_elongation, find_text, find_marker, sky_read, render, render_linear,
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


def _cities():
    global _CITY_INDEX
    if _CITY_INDEX is None:
        try:
            with open(f"{sky.BASE}/cities.json", encoding="utf-8") as f:
                _CITY_INDEX = json.load(f)
        except (OSError, ValueError):
            _CITY_INDEX = {}
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


def complete_cities(prefix, n=8):
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
            out.append((-hits[0][6], hits[0][7]))
    out.sort()
    seen, res = set(), []
    for _pop, name in out:
        if name not in seen:
            seen.add(name); res.append(name)
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
    """One short clause for the chart's top line: how dark it is here. The
    estimate is crude and says so -- "est." is doing real work in that
    string. The nearest city is named only when it is the reason the Milky
    Way is absent, where it answers the obvious next question."""
    _mag, b = sky_brightness(lat, lon)
    near = _nearest_city(lat, lon, prefer_radius_deg=0.5, max_radius_deg=1.5)
    where = f" ({near[7]})" if near and not _BORTLE_FLOOR[b] else ""
    return f"Bortle {b} est.{where}"


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
                 nodso=False, panel=False, nogolden=False):
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
        self.tle = tle
        # clamped once, here, so it's already canonical by the time it ever
        # reaches a cache key -- otherwise every distinct raw ?w= value before
        # clamping would be its own cache entry even if they render identically
        self.width = max(60, min(220, int(width))) if width else None
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
        r2.width = max(60, min(220, int(width)))
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
            paint("@habibicode", "\033[38;5;117m", c) +
            paint(" for skymap.sh updates", C.MUTE, c))


def strip_footer_line(text):
    """Removes _footer's "Follow @habibicode..." line from an already-
    composed render -- used only by server.py's HTML branch. compose()'s
    output is cached once and reused for every output mode (plain-text,
    JSON, HTML, PNG -- see server.py's _cached docstring), so this can't
    live inside compose() itself without splitting that cache in two; doing
    it here, after the shared render, keeps curl/CLI output unchanged and
    only touches what the browser actually receives. The header's nav row
    carries the same invitation as icon links instead (see header_html)."""
    marker = _footer(None, False)
    lines = text.split("\n")
    out, skip_blank = [], False
    for line in lines:
        if strip_ansi(line) == marker:
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


def next_visible_cached(tgt, lat, lon, start_utc):
    global _nv_hits, _nv_misses
    key = (tgt["name"], round(lat), round(lon), int(start_utc.timestamp() // 3600))
    hit = _nv.get(key)
    if hit is not None:
        w, a, z = hit
        if w is None or w > start_utc:          # still the first window ahead
            _nv_hits += 1
            return hit
    _nv_misses += 1
    out = next_visible(tgt, lat, lon, start_utc)
    if len(_nv) >= _NV_MAX:
        _nv.clear()
    _nv[key] = out
    return out


def nv_stats():
    t = _nv_hits + _nv_misses
    return dict(entries=len(_nv), hits=_nv_hits, misses=_nv_misses,
                hitrate=round(100 * _nv_hits / t, 1) if t else None)


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
            lines.append(f"  It is only {el:.0f}° from the Sun: too deep in the glare, "
                         f"and it stays that way for weeks.\n" if el < 20 else
                         f"  No window in the next 40 days from this latitude.\n")
            data.update(next_visible=None, solar_elongation=round(el, 1))
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
    out = {"object": canonical, "kind": tgt.get("kind"),
           "place": p.name, "lat": p.lat, "lon": p.lon,
           "shown_utc": when.isoformat() + "Z", "is_now": shown_utc is None}

    rts = objects.rise_transit_set(tgt, p.lat, p.lon, when)
    tz = p.offset(when)

    def local(x):
        return (x + dt.timedelta(hours=tz)).isoformat() if x else None

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

    best = objects.best_this_year(tgt, p.lat, p.lon, when)
    if best:
        entry = {
            "date": (best["when_utc"] + dt.timedelta(hours=tz)).date().isoformat(),
            "dark_hours": best.get("dark_hours"),
            "transit_alt": best["transit_alt"],
            "moon_illum": best["moon_illum"]}
        # A shower peaks rather than being "best"; it carries the radiant's
        # altitude on that night instead of a count of dark hours.
        if best.get("is_peak"):
            entry.update(is_peak=True, radiant_alt=best.get("radiant_alt"),
                         zhr=best.get("zhr"))
        out["best_this_year"] = entry

    collision = object_collision(canonical)
    if collision:
        out["also_a_place"] = {"city": collision[0], "url": f"/{collision[1]}"}
    return out


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
        L.append(f"{name} never rises from {facts['place']} — it stays below "
                 f"the horizon all year at this latitude.")

    if facts.get("never_sets"):
        L.append(f"It never sets from here, circling the pole and reaching "
                 f"{facts['transit_alt']:.0f}° at its highest.")
    elif facts.get("rise"):
        rise, st = facts["rise"][11:16], facts["set"][11:16]
        # A set time earlier than the rise means it sets the following
        # morning, which has to be said or the line reads as backwards.
        over = " the next morning" if facts["set"][:10] != facts["rise"][:10] else ""
        L.append(f"It rises at {rise} and sets at {st}{over}, highest at "
                 f"{facts['transit'][11:16]} when it reaches "
                 f"{facts['transit_alt']:.0f}°.")

    if facts.get("constellation"):
        L.append(f"You will find it in {facts['constellation']}.")

    st = facts.get("star", {})
    if st.get("description"):
        s = f"It is a {st['description']}"
        if st.get("light_years"):
            ly = st["light_years"]
            conf = st.get("distance_confidence")
            if conf == "good":
                s += f", {ly:.0f} light years away — the light you are seeing left it in {r.when_local.year - int(ly)}"
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
        L.append(f"It is {pl['distance_au']:.2f} AU away — {pl['light_minutes']:.0f} "
                 f"light-minutes, so you are seeing it as it was "
                 f"{pl['light_minutes']:.0f} minutes ago.")
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
            L.append(f"The rings are tilted {ra_:.0f}° towards us — {how}.")
        if pl.get("apparent_arcsec"):
            L.append(f"The disc is {pl['apparent_arcsec']:.0f} arcseconds across"
                     + (f", {pl['illuminated']:.0%} lit."
                        if pl["illuminated"] < 0.95 else "."))
        if pl.get("retrograde"):
            L.append("It is retrograde at the moment, drifting westwards "
                     "against the stars.")

    if facts.get("size_arcmin"):
        s = facts["size_arcmin"]
        moons = s["maj"] / 31.0
        rel = (f" — about {moons:.0f} times the width of the full Moon" if moons >= 2
               else f" — roughly {moons:.1f} Moon-widths" if moons >= 0.5 else "")
        L.append(f"It spans {s['maj']:g} arcminutes{rel}.")

    # Only worth saying when the Moon is both bright and actually near it.
    # A full Moon 145 degrees away is not what stops you seeing something.
    sep, illum = facts.get("moon_separation"), facts.get("moon_illum", 0)
    if sep is not None and illum > 0.4 and sep < 60:
        L.append(f"The Moon is {illum:.0%} lit and only {sep}° away, which will "
                 f"wash out anything faint nearby.")

    b = facts.get("best_this_year")
    if b and b.get("is_peak"):
        # A shower has a peak night rather than a best night, and the number
        # that matters is how high the radiant gets while it is happening --
        # not how much darkness the year can offer that patch of sky.
        moon = b.get("moon_illum", 0)
        s = (f"The peak is {b['date']}, with the radiant "
             f"{b['radiant_alt']:.0f}° up at midnight")
        if moon > 0.5:
            s += f" — but the Moon is {moon:.0%} lit that night and will drown most of it"
        elif moon < 0.15:
            s += ", and almost no Moon to spoil it"
        L.append(s + ".")
    elif b:
        L.append(f"Best this year: {b['date']}, when it reaches "
                 f"{b['transit_alt']:.0f}° with {b['dark_hours']:.1f} hours of "
                 f"darkness and the Moon {b['moon_illum']:.0%} lit.")

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


def compose_object(r, canonical):
    """The object page: the find view's chart and crosshair, with the object's
    own facts under it.

    Built on _compose_find deliberately rather than beside it. That view
    already solves the hard parts -- where the thing is, whether it is up,
    when it is next up if it is not, and a chart with a mark on it -- and a
    second implementation would be a second set of answers to drift apart.
    """
    r.find = canonical
    res = _compose_find(r)
    if res.status != 200:
        return res

    # The find view tells us which moment it actually drew. When the object
    # is below the horizon that is the next time it is up, not now, and the
    # prose has to agree with the picture above it.
    shown = None
    raw = res.data.get("shown_utc")
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(raw.rstrip("Z"))
            if abs((parsed - r.when_utc).total_seconds()) > 60:
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
    prose = object_prose(facts, tgt, r, width=_effective_width(r) - 4)
    body = "\n".join(paint("  " + l if l else "", C.LABEL, r.color)
                     for l in prose.split("\n"))

    text = strip_footer_line(res.text).rstrip() + "\n\n" + body + "\n\n" \
        + _footer(r.place, r.color) + "\n"
    data = dict(res.data)
    data.update(facts)
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
    where = f" from {facts['place']}" if facts.get("place") else ""
    return f"{name}: where to see {'the ' if kind in ('planet',) else ''}" \
           f"{name.lower() if kind == 'planet' else name}{where} tonight"


_KIND_WORD = {"planet": "planet", "star": "star", "moon": "moon", "sun": "sun",
              "asterism": "asterism", "galaxy": "galaxy", "radiant": "meteor shower"}


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


# The head of the shared page template, with the fixed description swapped
# for a slot. Derived from PAGE rather than copied, so the object pages keep
# every later change to the shell -- stylesheet, favicon, the width ladder --
# without a second copy to maintain, and without any of the six existing
# PAGE.format() call sites having to learn a new key.
def _object_page_template():
    return PAGE.replace(
        '<meta name="description" content="The night sky above you, as plain '
        'text. curl skymap.sh">', "{head_extra}", 1)


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
    url = f"https://skymap.sh/{quote(canonical)}"
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


def object_html(r, canonical, text, data, place=None, base_url=""):
    """The browser page: the same chart and prose everything else gets, in
    the shared shell, with the object's own head."""
    body = chart_pre(ansi_to_html(text))
    head = object_head(data, canonical, place, base_url)
    return _object_page_template().format(
        title=html.escape(object_title(data)),
        head_extra=head,
        header=header_html(r.place.name),
        controls="", wide_class="", coming_up_card="",
        kbd_urls="{}", shortcuts_hint="", body=body)


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
                (227, 220, True))


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


def strip_slots(text):
    """Drop the layout seams, leaving the pieces stacked in the order they
    were composed. What a terminal gets if it asks for ?panel=1: the seams
    are places for a browser to break the text apart, and a reader who
    cannot be handed three positioned boxes just gets the chart, the inset
    and the prose one after another, which is what they got before."""
    return text.replace(ZENITH_SLOT + "\n", "").replace(PROSE_SLOT + "\n", "") \
               .replace(ZENITH_SLOT, "").replace(PROSE_SLOT, "")


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


def chart_ladder(rungs):
    """`rungs` is [(cols, panel, html), ...] in CHART_LADDER order.

    No id on the individual rungs: there are several of them and an id has
    to be unique, which is the one thing a repeated <pre id="chart-pre">
    could not be. data-cols is read at click time by the animate button --
    the stream has to arrive at whatever width is actually on screen, and
    only CSS knows which rung that is."""
    blocks = "".join(
        '<pre class="chart-pre" data-cols="%d"%s>%s</pre>'
        % (cols, ' data-panel="1"' if panel else "", body)
        for cols, panel, body in rungs)
    return f'<div id="chart-ladder">{blocks}</div>'


def chart_layout(rungs, zenith, prose):
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
    return (f'<div id="chart-stage">{chart_ladder(rungs)}{inset}</div>{below}')


# One number for the chart, the inset and the prose under it. The ladder's
# breakpoints are in `ch`, which is the width of a "0" in this font -- so
# changing this changes how many rungs fit a given window without touching a
# single breakpoint, and the ladder picks a wider chart on its own.
CHART_FONT_PX = 12


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
    lines = [f" #chart-ladder{{container-type:inline-size;font-size:{CHART_FONT_PX}px}}",
             # Repeated on the rungs themselves rather than left to inherit:
             # the generic pre{} rule sets 11px explicitly, and an explicit
             # rule beats inheritance no matter how specific the ancestor.
             # It has to match the container's own size above or the ch
             # breakpoints measure against a different font than the chart
             # they are picking.
             f" #chart-ladder .chart-pre{{display:none;font-size:{CHART_FONT_PX}px}}",
             " #chart-ladder .chart-pre:nth-child(1){display:block}"]
    for i, (min_ch, _cols, _panel) in enumerate(CHART_LADDER):
        if min_ch is None:
            continue
        lines.append(f" @container (min-width:{min_ch}ch){{"
                     f"#chart-ladder .chart-pre:nth-child({i}){{display:none}}"
                     f"#chart-ladder .chart-pre:nth-child({i + 1}){{display:block}}}}")
    lines += [
        # The stage is the positioning context for the inset. Not the ladder
        # itself: that is the query container, and giving a query container
        # a positioned child it also has to size is asking for a loop.
        " #chart-stage{position:relative}",
        # Top right, over the panorama's highest rows. That corner holds
        # 55-70 degrees of altitude, the emptiest band of the chart on most
        # nights -- and when it isn't, "i" takes the inset away.
        f" #chart-zenith{{position:absolute;top:0;right:0;"
        f"font-size:{CHART_FONT_PX}px;margin:0;pointer-events:none;"
        # Sits on the sky, so it needs its own floor under it or the stars
        # it covers read as part of the drawing.
        "background:rgba(4,6,10,.82);padding:2px 6px;border-radius:4px}",
        " html.no-inset #chart-zenith{display:none}",
        # The prose keeps the chart's font but not its width: pinned above
        # the shortcut bar, where it stays put while the chart above it
        # changes rung, place or time.
        f" #chart-prose{{font-size:{CHART_FONT_PX}px;margin:6px 0 0}}",
    ]
    return "\n".join(lines)


def _horizon_height(r):
    return round(_effective_width(r) / HORIZON_COLS_PER_ROW)


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


def _sky_summary(st, lat, width, n_stars=0, note=""):
    """Trimmed to `width`, brightest-last. It sits above the chart, so a
    summary longer than the chart is one that decides how wide the page is
    -- which is exactly the job the prose used to do from below, and the
    reason the narrow rungs were 86ch for a 60-column chart. The Moon comes
    first and survives every trim; the star list is the first thing to go,
    then the planets, since both are in full in the chart itself."""
    mo, su = st["moon"], st["sun"]
    # Space after the glyph, always: the phase mark and the number are two
    # facts, and run together they read as one broken word.
    where = (f"{mo['alt']:.0f}°{compass(mo['az'])}" if mo["alt"] > 0
             else "below the horizon")
    pl = sorted((b for b in st["up"]
                 if b["name"] not in ("Sun", "Moon") and b["mag"] < 6.0),
                key=lambda b: b["mag"])
    alt = su["alt"]
    dark = ("daylight" if alt > 0 else "civil twilight" if alt > -6 else
            "nautical twilight" if alt > -12 else
            "astro twilight" if alt > -18 else "full dark")
    # (drop-order, text). Rendered in list order, but trimmed worst-first,
    # so a busy planet night loses the star count rather than whichever
    # happens to sit at the end. The Moon never goes: it decides how much
    # of the rest is worth looking for.
    parts = [(0, f"{moon_glyph(mo['age'], lat)} {mo['illum'] * 100:.0f}% {where}"),
             (2, ", ".join(f"{p['name']} {p['alt']:.0f}°{compass(p['az'])}"
                           for p in pl) if pl else "no planets"),
             (1, dark),
             # How dark it is *here*, which is the other half of how dark it
             # is tonight -- and the reason the Milky Way is or is not on the
             # chart. Ranks above the star count: the count is a number about
             # the catalogue, this is a fact about the sky you are under.
             (3, note),
             (4, f"{len(st['visible'])} stars")]
    # n_stars defaults to none: the bright stars are labelled on the chart a
    # few rows below this line, which is the one place they cannot be
    # misread as a list of somewhere else.
    bright = [(s, a, z) for s, a, z in
              sorted(st["visible"], key=lambda v: v[0]["m"])[:n_stars]
              if s.get("n")]
    if bright:
        parts.append((4, ", ".join(f"{s['n']} {a:.0f}°{compass(z)}"
                                   for s, a, z in bright)))
    parts = [pt for pt in parts if pt[1]]
    while len(parts) > 1 and len(" · ".join(t for _p, t in parts)) > width:
        parts.remove(max(parts, key=lambda pt: pt[0]))
    return " · ".join(t for _p, t in parts)


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
    if r.view == "disc": q.append("view=disc")
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
    if r.view == "disc" and not r.facing:
        art, st = render(r.when_utc, p.lat, p.lon, height=34, color=c,
                         show_lines=r.lines, width=r.width, mag_limit=mag_limit,
                         dso_limit=dso_limit)
        mode = "looking up, north at top"
    else:
        art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                                tle=r.tle, facing=r.facing, span=r.span,
                                width=r.width if r.facing else _effective_width(r),
                                height=None if r.facing else _horizon_height(r),
                                mag_limit=mag_limit, line_limit=mag_limit,
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
                                milkyway=mw_floor)
        quad_bit = f", quadrant {st['quad_applied']}" if st.get("quad_applied") else ""
        # a quadrant crop replaces the zenith inset (there's no room, and no
        # need -- the crop already narrows the view), so the header must stop
        # promising an inset that render_linear didn't actually draw.
        no_inset = st.get("quad_applied") is not None
        mode = (f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
                f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}, true shape{quad_bit}"
                if r.facing else
                f"horizon panorama, 0-70°{quad_bit}" if no_inset else
                f"horizon panorama, 0-70° + zenith inset{quad_bit}")
        # On the laddered page the default panorama says nothing the chart
        # is not already showing: the axis is labelled 0-70 down its left
        # edge and the inset is right there in the corner. A facing window
        # or a quadrant crop is different -- that one is not obvious from
        # looking, so it keeps its label.
        if r.panel and not r.facing and not quad_bit:
            mode = ""

    # One row on the browser page: place, moment, Moon and planets. The CLI
    # keeps its own two-part header and its own prose, untouched.
    #
    # The summary gets what is left of the chart's width after the place and
    # the moment, not the whole of it -- given the whole, a night with four
    # planets up wrote a top line wider than the chart underneath it, which
    # is the one thing a rung's breakpoint cannot survive.
    summary = ""
    if r.panel:
        spare = _effective_width(r) - len(_head_prefix(r)) - 3
        spare -= len(mode) + 3 if mode else 0
        summary = _sky_summary(st, p.lat, max(20, spare), note=sky_note(p.lat, p.lon))
    head = _horizon_head(r, mode, summary=summary)
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
        out = ["", paint(head, C.HEAD, c), "", art,
               ZENITH_SLOT] + zenith + [PROSE_SLOT] + right
    else:
        out = ["", paint(head, C.HEAD, c), "", art, ""]
        out += right
    out += ["", _footer(p, c), ""]

    mo, su = st["moon"], st["sun"]
    data = dict(
        place=p.name, near=p.near, lat=p.lat, lon=p.lon, tz_offset=r.tz,
        when_utc=r.when_utc.isoformat() + "Z", when_local=r.when_local.isoformat(),
        view="disc" if (r.view == "disc" and not r.facing) else "horizon",
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
    for e in ev_mod.locatable_tonight(r.place.lat, r.place.lon, r.tz,
                                      now_utc=r.when_utc):
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
    top = max((a for _t, a in ((x[0], x[1]) for x in arc)), default=10)
    alt_hi = max(DAY_ALT_HI_FLOOR, min(90.0, top + 8))
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
                            bodies=show, inset=False, width=_effective_width(r),
                            height=_horizon_height(r),
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
        dark_txt = f"first stars about {_hm(first, off)}, fully dark {_hm(dark, off)}"
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
    if r.facing or r.view == "disc":
        lines.append("The Sun's path is a whole-sky view, so facing and view were "
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
        parts = [(0, f"☀ {sa:.0f}°{compass(sz)}")]
        if ev["polar_day"]:
            parts.append((1, "the Sun does not set today"))
        else:
            t = [f"↑{_hm(ev.get('sunrise'), off)}", f"↓{_hm(ev.get('sunset'), off)}"]
            # dark is astronomical dusk or nothing, so a night with first
            # stars but no full darkness has to say so rather than print the
            # "--" _hm() gives a missing time.
            t.append(f"stars {_hm(first, off)} · dark {_hm(dark, off)}" if first and dark
                     else f"stars {_hm(first, off)} · no full dark" if first
                     else "never fully dark")
            parts.append((1, " · ".join(t)))
        if later:
            parts.append((2, "tonight: " + ", ".join(b["name"] for b in later)))
        prefix = _head_prefix(r)
        while len(parts) > 1 and (len(prefix) + 3 +
                                  len(" · ".join(x for _p, x in parts))
                                  > _effective_width(r)):
            parts.remove(max(parts, key=lambda pt: pt[0]))
        head = f"{prefix} · " + " · ".join(x for _p, x in parts)
        # body was filtered before wrapping, above. What is left is the
        # exceptional stuff: a facing/view request this page cannot honour,
        # and anything else worth a sentence of its own.
        out = ["", paint(head, C.HEAD, c), "", art, PROSE_SLOT]
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


def _event_line(e, r):
    """One event as a table row: when, glyph, what, and where to look."""
    when = f"{_event_date(e):%a %d %b}"
    head = f"{e.get('glyph', ' ')} {e['headline']}"
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
    return f"  {when:<11} {head:<34} {', '.join(tail)}".rstrip()


def _event_url(e, r):
    """The chart for the moment this event is worth looking at.

    Not the event's own instant: a shower peaking at 04:10 wants the chart for
    the middle of its window, and anything with a best moment wants that. The
    compass bearing rides along as ?facing= so the chart opens pointed at the
    thing rather than at a default panorama.
    """
    when = e.get("best_local") or e["when_local"]
    url = f"/{quote(r.place.slug)}?t={when:%Y-%m-%dT%H:%M}"
    # ?find= beats ?facing=: facing only points the chart the right way, find
    # actually puts a crosshair on the thing. Clicking "Perseids" and getting
    # an unmarked night chart was the whole complaint.
    target = _find_target_for(e)
    if target:
        url += f"&find={quote(target)}"
    elif e.get("compass"):
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
    moment it happens, in a new tab so the list stays put -- the same bargain
    catalog_html() makes.

    The row is wrapped whole, padding included, so the columns stay lined up
    inside <pre> exactly as they do in a terminal.
    """
    style = {"head": C.HEAD, "event": EVENT_COL, "mute": C.MUTE}
    rows, _ = _event_rows(r, days)
    out = []
    for kind, text, url in rows:
        if kind == "blank":
            out.append("")
            continue
        span = (f'<span style="color:{_ansi_hex(style[kind])}">'
                f"{html.escape(text)}</span>")
        if url:
            out.append(f'<a href="{html.escape(url)}" target="_blank" '
                       f'rel="noopener" title="Open the sky for this moment">'
                       f"{span}</a>")
        else:
            out.append(span)
    out.append("")
    out.append(f'<span style="color:{_ansi_hex(C.MUTE)}">  Follow </span>'
               f'<a href="https://bsky.app/profile/habibicode.bsky.social" '
               f'target="_blank" rel="noopener">@habibicode</a>'
               f'<span style="color:{_ansi_hex(C.MUTE)}"> for skymap.sh updates</span>')
    return "\n".join(out)


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
    style = {"head": C.HEAD, "event": EVENT_COL, "mute": C.MUTE}
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
    top = max((a for _t, a in ((x[0], x[1]) for x in arc)), default=45)
    alt_hi = max(DAY_ALT_HI_FLOOR, min(90.0, top + 8))

    # Below the horizon the Sun overlay disappears entirely, trail included --
    # otherwise the trail (coloured once, for the whole arc, by the *current*
    # frame's altitude) keeps showing as a lingering red line long after the
    # Sun has actually set, rather than genuinely vanishing.
    overlay = (arc, _sun_color(sun_alt), "SUN", (sun_alt, sun_az)) if sun_alt >= 0 else None
    # line_limit ties constellation lines/names to the same fading threshold as
    # the stars (see mag_limit above) -- they pop in/out star-by-star through
    # twilight instead of snapping on/off at a fixed show_lines boolean.
    art, _st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                             mag_limit=mag_limit, line_limit=mag_limit, tle=None,
                             inset=False, alt_lo=0.0, alt_hi=alt_hi,
                             width=_effective_width(r), height=_horizon_height(r),
                             overlay=overlay, bodies=visible_bodies,
                             # A frame ignored ?dso= entirely, so asking an
                             # animation for deep sky changed nothing at all
                             # -- byte-identical output. The paused-frame "d"
                             # in the browser refetches a single frame with
                             # it on, and that needs somewhere to land.
                             dso_limit=DSO_LIMIT if r.dso else None,
                             # An animation is the one place the band is
                             # worth the most: it appears as the sky darkens
                             # and goes again at dawn, which is exactly the
                             # thing a still chart cannot show.
                             milkyway=_milkyway_floor_now(p.lat, p.lon, sun_alt))

    if sun_alt >= -1:      mode = _sun_path_mode(r)
    elif sun_alt >= -6:    mode = "civil twilight"
    elif sun_alt >= -12:   mode = "nautical twilight"
    elif sun_alt >= -18:   mode = "astronomical twilight"
    else:                  mode = "horizon panorama"

    head = _horizon_head(r, mode)
    return paint(head, C.HEAD, c) + "\n\n" + art, sun_alt


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
    # inset=False like every other branch of compose_chart_only. render_linear
    # defaults it on, and this one call site never said otherwise, so the
    # shared PNG for a ?find= view carried a zenith inset under the horizon
    # that no other PNG has -- the one thing the export is meant to leave out.
    art, _st = render_linear(shown_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                             tle=r.tle, target=tgt, inset=False, **extra)
    shown_local = shown_utc + dt.timedelta(hours=p.offset(shown_utc))
    where = f"{int(sp)}° window" if zoomed else "full panorama"
    head = (f"  {p.name}   {shown_local:%d %b %Y %H:%M}   "
            f"finding {tgt['name']}, {where}")
    return paint(head, C.HEAD, c) + "\n\n" + art


def compose_chart_only(r):
    """Just the horizon chart itself -- no header, prose, footer, or zenith
    inset -- for the PNG export. Same day/night and facing logic as
    _compose_sky/_compose_day, minus everything that isn't the chart, so the
    PNG matches whatever the static view above it is actually showing."""
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
        top = max((a for _t, a in ((x[0], x[1]) for x in arc)), default=10)
        alt_hi = max(DAY_ALT_HI_FLOOR, min(90.0, top + 8))
        jd_now = julian(r.when_utc)
        lst_now = (gmst_hours(jd_now) + p.lon / 15.0) % 24
        su_now = sun(jd_now)
        sa_now, sz_now = altaz(su_now["ra"], su_now["dec"], p.lat, lst_now)
        mo_now = moon(jd_now)
        show = {"Moon"} if mo_now["illum"] > 0.4 or _near_sun(jd_now) else set()
        art, _st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=False,
                                 mag_limit=_fade_mag_limit(sa_now), alt_lo=0.0, alt_hi=alt_hi,
                                 overlay=(arc, SUN_COL, "SUN", (sa_now, sz_now)),
                                 bodies=show, inset=False, width=_png_export_width(r),
                                 height=_png_export_height(r))
        head = _horizon_head(r, _sun_path_mode(r))
        return paint(head, C.HEAD, c) + "\n\n" + art
    if r.view == "disc" and not r.facing:
        jd = julian(r.when_utc)
        lst = (gmst_hours(jd) + p.lon / 15.0) % 24
        su = sun(jd)
        sun_alt, _ = altaz(su["ra"], su["dec"], p.lat, lst)
        art, _st = render(r.when_utc, p.lat, p.lon, height=34, color=c,
                          show_lines=r.lines, width=r.width,
                          mag_limit=_fade_mag_limit(sun_alt),
                          dso_limit=DSO_LIMIT if r.dso else None)
        head = _horizon_head(r, "looking up, north at top")
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
                            quadrants=r.quadrant_requested, inset=False,
                            # The PNG is the shareable artefact, so it is the
                            # last place the band should be missing -- and it
                            # is a separate render from _compose_sky's, which
                            # is exactly how it got left off.
                            milkyway=_milkyway_floor_now(p.lat, p.lon, sun_alt))
    mode = (f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
            f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}, true shape"
            if r.facing else "horizon panorama")
    # The same one-row summary the browser puts above the chart -- Moon,
    # planets, how dark it is, the Bortle estimate, the star count. The
    # export used to carry the CLI's two-part header instead, so the
    # picture someone shared said less than the page they took it from,
    # and said it differently.
    # "horizon panorama" is dropped on the plain view for the same reason
    # the browser drops it: the axis is labelled 0-70 down the left edge and
    # says so already. A facing window or a quadrant crop is not obvious
    # from looking, so those keep their label.
    if not r.facing and not r.quadrant_requested:
        mode = ""
    # Untrimmed, unlike the page's. The trim exists because the browser
    # ships nine rungs and a top line longer than its own chart would set
    # the page width and break the breakpoints -- so each rung drops
    # whatever does not fit, and a narrow one says less than a wide one.
    # An export has no rung. It should carry what the widest view carries,
    # or the picture says less than the page it was taken from, which is
    # the whole complaint. The image is sized to its longest line anyway.
    summary = _sky_summary(st, p.lat, 10_000, note=sky_note(p.lat, p.lon))
    head = _horizon_head(r, mode, summary=summary)
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
  ?view=disc       whole sky as a circle, north up, east left
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

    return dict(solar_system=solar_system, asterisms=sorted(a["name"] for a in asterisms),
               named_stars=named_stars, named_dso=named_dso)


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
        "Everything below is findable by name, e.g.:",
        "  curl 'skymap.sh/Zurich?find=Vega'", "",
        head(f"SOLAR SYSTEM ({len(d['solar_system'])})"),
    ]
    for _nm, display, glyph, glyph_c in d["solar_system"]:
        L.append(f"  {P(glyph, glyph_c)} {display}")
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
    L.append(head(f"DEEP SKY ({len(d['named_dso'])}) -- ?dso=1, brightest first"))
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
    """Browser twin of catalog_text() -- every object links to /?find=<name>
    (bare place, so it resolves through the visitor's own geo-IP fallback,
    the same way a bare `curl skymap.sh` does) opened in a new tab, so
    browsing the catalog never navigates away from the chart on screen.
    DSOs additionally turn on ?dso=1&quadrant so the new tab shows the
    deep-sky layer and quadrant grid, not just a bare star chart."""
    def col(s, ansi):
        return f'<span style="color:{_ansi_hex(ansi)}">{html.escape(s)}</span>'

    def head(s):
        return col(s, C.HEAD)

    def link(name, extra=""):
        href = html.escape(f"/?find={quote(name)}{extra}")
        return f'<a href="{href}" target="_blank" rel="noopener">{html.escape(name)}</a>'

    def link_col(name, ansi, extra="", href_name=None):
        href = html.escape(f"/?find={quote(href_name or name)}{extra}")
        return (f'<a href="{href}" target="_blank" rel="noopener">'
                f'<span style="color:{_ansi_hex(ansi)}">{html.escape(name)}</span></a>')

    d = _catalog_data()

    L = [
        "skymap.sh -- object catalog", "",
        "Everything below opens the current sky with that object framed, in a new tab.", "",
        head(f"SOLAR SYSTEM ({len(d['solar_system'])})"),
    ]
    for nm, display, glyph, glyph_c in d["solar_system"]:
        L.append(f"  {col(glyph, glyph_c)} {link_col(display, glyph_c, href_name=nm)}")
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
    return "".join(out)


def strip_ansi(text):
    return ANSI.sub("", text)


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
    return ("<style>\n"
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
</script>""")


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
    + _social_icon("https://github.com/HabibiCodeCH/skymap-sh", "See the repo on GitHub", _GITHUB_PATH)
    + _social_icon("https://www.reddit.com/r/skymap/", "Join r/skymap on Reddit", _REDDIT_PATH)
    + _social_icon("https://bsky.app/profile/skymap.sh", "Follow on Bluesky", _BLUESKY_PATH)
    + _social_icon("https://x.com/habibicode", "Follow on X", _X_PATH)
    + '</span>'
)


def header_html(value="", find_value=None, find_close_url=None):
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

    find_value=None (the default) omits the find field entirely -- every
    page except the chart view, which passes r.find or "" here instead of
    leaving it in the drawer (EXPLORE_DATETIME there has no #find of its
    own). /stats showed find as the second-most-viewed feature behind the
    chart itself, right after place -- worth the same prominence as place,
    not buried behind the drawer toggle.

    find_close_url, when given (server.py only sets it once r.find is
    actually set -- an active search, not just an empty/placeholder field),
    renders a small "return to the plain chart" X inside the field itself.
    Before this there was no direct way back to the ordinary view short of
    manually clearing the text and resubmitting, or "reset skymap" in the
    drawer, which also drops the place. Built with _toggle_qs(r), same as
    every other toggle link -- drops find= (and any span= that was find's
    own crop window, not facing's), keeps everything else on screen.

    The command bar and the nav row share one flex row (.header-row) so the
    nav sits inline with it instead of wrapping to a line of its own."""
    findbar = ""
    if find_value is not None:
        find_close = ""
        if find_value and find_close_url:
            find_close = (f'<a class="find-close" href="{html.escape(find_close_url)}" '
                         f'aria-label="Close find mode" title="Close find mode">✕</a>')
        findbar = (
            f'<div class="findbar" id="findbar">'
            f'<button type="button" class="find-trigger" id="find-trigger" '
            f'aria-label="Find an object" aria-expanded="false" aria-controls="find-field">⌕</button>'
            f'<span class="find-field" id="find-field">'
            f'<span class="find-icon" aria-hidden="true">⌕</span>'
            f'<input id="find" type="text" value="{html.escape(find_value)}" '
            f'placeholder="Find (Venus, Big Dipper…)" autocomplete="off" '
            f'role="combobox" aria-expanded="false" aria-controls="find-dropdown" '
            f'aria-label="Find an object by name">'
            f'<ul class="find-dropdown" id="find-dropdown" role="listbox" hidden></ul>'
            f'{find_close}'
            f'</span></div>')
    return (f'<div class="header-row">'
            f'<form class="cmdbar" id="bar" method="get" action="/">'
            f'<span class="prompt" aria-hidden="true">$</span>'
            f'<span class="fixed" aria-hidden="true">'
            f'<span class="curlword">curl </span>skymap.sh/</span>'
            f'<span class="field">'
            f'<input id="q" name="q" value="{html.escape(value)}" '
            f'aria-label="City, or lat,lon" spellcheck="false" autocapitalize="off" '
            f'autocorrect="off" autocomplete="off" enterkeyhint="go">'
            f'<span class="ghosttext" id="ghost" aria-hidden="true"></span>'
            f'<span class="measure" id="measure" aria-hidden="true"></span>'
            f'</span>'
            f'<span class="cursor" id="cur" aria-hidden="true"></span>'
            f'<span class="grow"></span>'
            f'<button type="button" class="copy" id="copy">⧉ copy</button>'
            f'</form>'
            f'{findbar}'
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
<meta name="description" content="The night sky above you, as plain text. curl skymap.sh">
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
      /* Bottom padding only needs to clear .kbd-hint's own fixed bar
         (~33px) plus a little breathing room -- it used to be 64px, nearly
         double that, which on a page short enough to not otherwise need
         scrolling was exactly enough overflow to force a few px of
         vertical scroll anyway. */
      padding:24px 16px 40px;-webkit-font-smoothing:antialiased}}
 .w{{max-width:1200px;margin:0 auto}}
 .w-wide{{max-width:none}}
 pre{{margin:0;font-size:11px;line-height:1.22;overflow-x:auto;font-variant-ligatures:none}}
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
             flex-wrap:wrap;gap:12px;margin:0 0 8px}}
 .header-row .nav-row{{margin:0;flex:1;min-width:0}}
 .social-icons{{display:inline-flex;gap:8px;margin-left:8px;vertical-align:middle}}
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
 /* Command bar -- an inline-editable "$ curl skymap.sh/<place>" line.
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
 .cmdbar .ghosttext{{color:#3d4451;white-space:pre;pointer-events:none}}
 .cmdbar .measure{{position:absolute;visibility:hidden;white-space:pre;left:-9999px}}
 .cmdbar .grow{{flex:1}}
 .cmdbar .copy{{background:none;border:1px solid #30363d;color:#6e7681;
               border-radius:4px;padding:4px 8px;margin-left:10px;
               font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}}
 .cmdbar .copy:hover{{border-color:#7ee787;color:#7ee787}}
 .cursor{{display:inline-block;width:.55em;height:1.15em;margin-left:1px;
         background:#7ee787;vertical-align:-0.2em;
         animation:blink 1.06s step-end infinite}}
 .cmdbar.focused .cursor{{visibility:hidden;animation:none}}
 @keyframes blink{{0%,50%{{opacity:1}}50.01%,100%{{opacity:0}}}}
 @media (prefers-reduced-motion: reduce){{
   .cursor{{animation:none;opacity:.55}}
 }}
 /* Find field -- promoted out of the drawer and next to the command bar on
    the chart page only (header_html's find_value param), since /stats
    showed find as the second-most-viewed feature after the chart itself.
    Same visual language as .cmdbar (dark box, monospace) but its own
    element, not fused into the "$ curl ..." line -- it isn't part of that
    curlable command. Below findbar-collapse-width, .find-field hides and
    .find-trigger (an icon button) takes its place; clicking it adds
    .expanded, same show/hide pattern as the drawer trigger. */
 .findbar{{display:inline-flex;align-items:center}}
 .find-trigger{{display:none}}
 /* Explicit height+box-sizing:border-box, matching .cmdbar exactly -- see
    its comment above. */
 .find-field{{display:inline-flex;align-items:center;position:relative;
             background:#0d1117;border:1px solid #30363d;border-radius:6px;
             padding:9px 12px;color:#8b949e;font-size:13px;
             box-sizing:border-box;height:45px}}
 .find-icon{{color:#6e7681;margin-right:6px}}
 .find-field input{{background:transparent;border:0;color:#e6edf3;font:inherit;
                    padding:0;margin:0;outline:none;width:210px;max-width:40vw}}
 .find-field input::placeholder{{color:#6e7681}}
 /* Only rendered once find_value is actually set (an active search, not
    just the empty/placeholder field) -- the one direct way back to the
    plain chart, same visual language as the coming-up card's own .cu-
    dismiss. */
 .find-close{{background:none;border:0;color:#6e7681;cursor:pointer;
             font-size:13px;line-height:1;padding:2px 4px;margin-left:4px;
             flex-shrink:0;text-decoration:none}}
 .find-close:hover{{color:#c9d1d9}}
 .find-dropdown{{position:absolute;top:100%;left:0;margin:4px 0 0;padding:4px;
                 background:#0d1117;border:1px solid #30363d;border-radius:6px;
                 min-width:220px;max-width:320px;max-height:280px;
                 overflow-y:auto;z-index:30;list-style:none}}
 .find-dropdown[hidden]{{display:none}}
 .find-option{{display:flex;align-items:center;gap:8px;padding:6px 8px;
              border-radius:4px;cursor:pointer;font-size:13px;color:#c9d1d9}}
 .find-option .glyph{{width:1.2em;text-align:center;flex-shrink:0}}
 .find-option:hover,.find-option.active{{background:#1c2128}}
 @media (max-width:700px){{
   .find-trigger{{display:inline-flex;align-items:center;justify-content:center;
                 background:#0d1117;border:1px solid #30363d;color:#8b949e;
                 border-radius:4px;width:28px;height:28px;margin-left:8px;
                 font-size:14px;line-height:1;cursor:pointer}}
   .find-trigger:hover{{border-color:#8b949e}}
   .find-field{{display:none;flex-basis:100%;margin-top:8px}}
   .findbar{{flex-wrap:wrap}}
   .findbar.expanded .find-field{{display:inline-flex}}
   .find-field input{{max-width:none;flex:1}}
 }}
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
</style></head><body>
{header}
<!-- skymap:coming-up-card
     api.coming_up_card_html(api.events_card(r)) -- "" (renders nothing) on
     most nights, see TEASER_DAYS in events.py. Above the drawer and the
     chart deliberately, so it reads before the sky rather than after it.
     Chart-page only; every other PAGE.format() call site passes "". -->
{coming_up_card}
<div class="w{wide_class}">
{controls}{shortcuts_hint}{body}
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
  return out;
}}
// Playback runs off a buffer rather than painting each frame as it lands.
// That is what space and the arrow keys need: frames keep arriving while
// paused, and once the stream has finished the whole night sits in memory
// (96 frames of ~7 KB) to step through or replay without asking the server
// for it again. The tick runs at the same interval the server streams at,
// handed over on the button as data-frame-ms so the two cannot drift.
function skymapAnimShow(i){{
  var A=window.skymapAnim;
  if(!A||!A.frames.length)return;
  A.at=Math.max(0,Math.min(A.frames.length-1,i));
  A.pre.innerHTML=ansiToHtml(A.frames[A.at]);
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
  var link=document.querySelector('.share-row a[href*="horizon.png"]');
  if(!A||!link)return;
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
function skymapAnimRestore(){{
  // Put the chart back the way it was found. The last frame is 24 hours
  // past the moment the page is actually about, so leaving it up ends the
  // animation on a chart that quietly disagrees with every heading, link
  // and time on the page around it. Stepping back with an arrow brings the
  // frames straight back.
  var A=window.skymapAnim;
  if(!A||A.base===null)return;
  A.pre.innerHTML=A.base;
  if(window.skymapSetHint)window.skymapSetHint(null);
}}
function skymapAnimPlay(on){{
  var A=window.skymapAnim;
  if(!A)return;
  A.playing=on;
  A.btn.textContent=on?'⏸ pause':(skymapAnimAtEnd(A)?'▶ replay':'▶ resume');
  if(on)skymapAnimTick();else clearTimeout(A.timer);
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
function skymapAnimFrameTime(i){{
  var A=window.skymapAnim;
  var qs=(A.btn.getAttribute('data-live-url')||'').split('?')[1]||'';
  var t=new URLSearchParams(qs).get('t');
  if(!t)return null;
  var d=new Date(t);
  if(isNaN(d.getTime()))return null;
  d.setMinutes(d.getMinutes()+i*A.stepMin);
  function p(n){{return (n<10?'0':'')+n;}}
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+
         'T'+p(d.getHours())+':'+p(d.getMinutes());
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
    A.dsoOn[at]=false;
    skymapAnimShow(at);
    if(done)done(true,false);
    return;
  }}
  if(A.dsoFrames[at]!==undefined){{
    A.plain[at]=A.frames[at];
    A.frames[at]=A.dsoFrames[at];
    A.dsoOn[at]=true;
    skymapAnimShow(at);
    if(done)done(true,true);
    return;
  }}
  var t=skymapAnimFrameTime(at);
  var live=A.btn.getAttribute('data-live-url');
  if(!t||!live)return;
  var url=live.replace(/([?&])t=[^&]*/,'$1t='+encodeURIComponent(t))
              .replace(/([?&])animate=[^&]*/,'$1animate=1')+'&dso=1';
  A.loadingDso=true;
  fetch(url).then(function(resp){{
    var reader=resp.body.getReader(),dec=new TextDecoder(),buf='';
    function pump(){{
      return reader.read().then(function(res){{
        buf+=res.value?dec.decode(res.value,{{stream:true}}):'';
        var parts=buf.split('\\x1b[2J\\x1b[H');
        // Frame one is whole once the next separator lands (or the stream
        // ends). Everything after it is thrown away unread.
        if(parts.length>2&&parts[1].trim()){{reader.cancel();return parts[1];}}
        if(res.done)return parts.length>1&&parts[1].trim()?parts[1]:null;
        return pump();
      }});
    }}
    return pump();
  }}).then(function(frame){{
    A.loadingDso=false;
    if(!frame)return;
    // Both kept: the stream's own frame to go back to, the deep-sky one to
    // return to without asking twice. The buffer holds whichever is showing,
    // so stepping away and back finds the frame as it was left.
    A.plain[at]=A.frames[at];
    A.dsoFrames[at]=frame;
    A.dsoOn[at]=true;
    A.frames[at]=frame;
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
  A=window.skymapAnim={{frames:[],at:-1,playing:true,done:false,timer:null,
                       btn:btn,pre:pre,base:pre.innerHTML,loadingDso:false,
                       plain:{{}},dsoFrames:{{}},dsoOn:{{}},
                       ms:parseInt(btn.getAttribute('data-frame-ms'),10)||150,
                       stepMin:parseInt(btn.getAttribute('data-step-min'),10)||15}};
  // Enabled throughout now: while the stream runs this button is the pause
  // control, so greying it out would take the mouse-only way to pause with
  // it.
  btn.disabled=false;btn.textContent='⏸ pause';
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
(function(){{
  // Command bar: auto-size (hidden-measure technique -- field-sizing:content
  // isn't portable yet) + click-anywhere-to-focus, so the whole bar reads as
  // one editable command line rather than decorative text bolted onto a
  // separate input box, plus ghost-text completion against GET /complete
  // (SPEC-command-bar.md #3-4). Present on every page (see header_html), so
  // no page-specific gating here -- only the element lookups are null-safe.
  var bar=document.getElementById('bar');
  var q=document.getElementById('q');
  var measure=document.getElementById('measure');
  var ghost=document.getElementById('ghost');
  var copyBtn=document.getElementById('copy');
  if(bar&&q&&measure&&ghost){{
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
    // Prefix match only, first (most populous) hit wins -- /complete
    // already returns candidates ranked and prefix-filtered, this re-check
    // is a staleness guard: a slow response for an earlier, shorter prefix
    // can still land after the user's kept typing, and showing it then
    // would ghost-suggest text that no longer applies. The user's own
    // casing (and accents) are always kept in what's displayed -- "zur" +
    // ghost "ich", never a correction to "Zürich".
    var complete=function(){{
      var v=q.value;
      if(!v){{ghost.textContent='';return;}}
      // Typing "London" in full used to still ghost-suggest "derry" -- the
      // exact match itself fails c.length>v.length (nothing left to add),
      // so the next-longest candidate sharing that prefix (Londonderry) won
      // instead, and Tab/-> turned a complete, correct search into the
      // wrong city. An exact match means the search is already done.
      if(matches.some(function(c){{return fold(c)===fold(v);}})){{
        ghost.textContent='';return;
      }}
      var hit=matches.find(function(c){{
        return fold(c).startsWith(fold(v))&&c.length>v.length;
      }});
      ghost.textContent=hit?hit.slice(v.length):'';
    }};
    var completeAbort=null, completeTimer=null;
    var fetchMatches=function(){{
      if(completeAbort)completeAbort.abort();
      var v=q.value.trim();
      if(v.length<2){{matches=[];complete();return;}}
      completeAbort=new AbortController();
      fetch('/complete?q='+encodeURIComponent(v.toLowerCase().slice(0,24)),
            {{signal:completeAbort.signal}})
        .then(function(r){{return r.json();}})
        .then(function(names){{matches=names;complete();}})
        .catch(function(){{}});
    }};
    size();
    q.addEventListener('input',function(e){{
      size();
      // Clear on Backspace before recomputing, so deleting never appears
      // to re-suggest what was just removed.
      if(e.inputType==='deleteContentBackward'){{matches=[];ghost.textContent='';}}
      if(completeTimer)clearTimeout(completeTimer);
      completeTimer=setTimeout(fetchMatches,120);
    }});
    q.addEventListener('keydown',function(e){{
      if(!ghost.textContent)return;
      var atEnd=q.selectionStart===q.value.length;
      if(e.key==='Tab'||(e.key==='ArrowRight'&&atEnd)){{
        e.preventDefault();
        q.value+=ghost.textContent;
        ghost.textContent='';
        size();
        q.setSelectionRange(q.value.length,q.value.length);
      }}
    }});
    q.addEventListener('focus',function(){{bar.classList.add('focused');}});
    q.addEventListener('blur',function(){{bar.classList.remove('focused');}});
    bar.addEventListener('mousedown',function(e){{
      if(copyBtn&&(e.target===copyBtn||copyBtn.contains(e.target)))return;
      if(e.target!==q){{
        e.preventDefault();
        q.focus();
        q.setSelectionRange(q.value.length,q.value.length);
      }}
    }});
    // Enter in the command bar does exactly what "go" in the explore form
    // does (SPEC-command-bar.md #7) -- rather than a second, separately
    // maintained "just navigate to place" path that could drift from it
    // (e.g. silently dropping find=/t= from the other fields), this
    // delegates to that form's own onsubmit, which already reads #q. A
    // visible ghost is accepted first: without this, pressing Enter on
    // "zur" would submit the literal text "zur" (a 404 -- lookup_place
    // does exact name matching, not prefix matching) even though the
    // ghost "ich" made it look like "Zürich" was already typed.
    bar.addEventListener('submit',function(e){{
      e.preventDefault();
      if(ghost.textContent){{
        q.value+=ghost.textContent;
        ghost.textContent='';
        size();
      }}
      var exploreForm=document.getElementById('explore');
      if(exploreForm){{
        if(exploreForm.requestSubmit)exploreForm.requestSubmit();
        else exploreForm.dispatchEvent(new Event('submit',{{cancelable:true}}));
        return;
      }}
      // No find/date/time form on this page (e.g. /demo) to delegate to --
      // still a real place to navigate to, so fall back to going there
      // directly rather than Enter silently doing nothing.
      if(q.value)location.href='/'+encodeURIComponent(q.value);
    }});
    // navigator.clipboard is HTTPS/localhost-only -- feature-detect and
    // hide the button entirely where it's unavailable rather than wiring
    // up a click that would just silently do nothing.
    if(copyBtn){{
      if(!navigator.clipboard){{
        copyBtn.hidden=true;
      }}else{{
        var copyLabel=copyBtn.textContent;
        var copyResetTimer=null;
        copyBtn.addEventListener('click',function(){{
          // Includes any accepted-but-not-yet-typed ghost completion --
          // copying should grab the resolved command, not just what's
          // literally been keyed in so far.
          var place=q.value+ghost.textContent;
          var path=place.includes(' ')?
            "'skymap.sh/"+place+"'":'skymap.sh/'+place;
          navigator.clipboard.writeText('curl '+path).then(function(){{
            if(copyResetTimer)clearTimeout(copyResetTimer);
            copyBtn.textContent='✓ copied';
            copyResetTimer=setTimeout(function(){{
              copyBtn.textContent=copyLabel;
              copyResetTimer=null;
            }},1400);
          }}).catch(function(){{}});
        }});
      }}
    }}
  }}
}})();
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
        skymapAnimStep(e.key==='ArrowLeft'?-1:1);
        var A=window.skymapAnim;
        flashHint('frame '+(A.at+1)+'/'+A.frames.length+
                  (A.done?'':', still loading'));
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
    if(e.key==='f'){{
      var find=document.getElementById('find');
      // Below findbar-collapse-width the field starts display:none behind
      // .find-trigger -- expand it first, or focus()/select() on a hidden
      // input would silently no-op.
      var findbar=document.getElementById('findbar');
      if(findbar)findbar.classList.add('expanded');
      if(find){{e.preventDefault();find.focus();find.select();}}
      return;
    }}
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
(function(){{
  // Find field -- live dropdown against GET /complete/objects, keyboard-
  // navigable (SPEC-command-bar.md's ghost-completion pattern, but a real
  // dropdown since object names aren't a simple continuation of what's
  // typed the way a place ghost-completion is). Only present on the chart
  // page (header_html's find_value param) -- null-safe so every other page
  // just skips this whole IIFE. Deliberately after the keyboard-shortcuts
  // IIFE above, not before it -- both handle 'Escape', and the global
  // handler's drawer-priority behaviour is what should win a plain text
  // search for "e.key==='Escape'" in the rendered page.
  var findInput=document.getElementById('find');
  var dropdown=document.getElementById('find-dropdown');
  if(!findInput||!dropdown)return;
  var trigger=document.getElementById('find-trigger');
  var findbar=document.getElementById('findbar');
  var items=[], active=-1, fetchAbort=null, fetchTimer=null;

  function renderDropdown(){{
    dropdown.innerHTML='';
    if(!items.length){{dropdown.hidden=true;return;}}
    items.forEach(function(it,i){{
      var li=document.createElement('li');
      li.className='find-option'+(i===active?' active':'');
      li.setAttribute('role','option');
      var glyph=document.createElement('span');
      glyph.className='glyph';
      glyph.style.color=it.color;
      glyph.textContent=it.glyph;
      var name=document.createElement('span');
      name.textContent=it.name;
      li.appendChild(glyph);
      li.appendChild(name);
      // mousedown (not click) fires before the input's blur, so selecting
      // with the mouse doesn't race the blur-closes-dropdown handler below.
      li.addEventListener('mousedown',function(e){{e.preventDefault();selectItem(it);}});
      dropdown.appendChild(li);
    }});
    dropdown.hidden=false;
  }}

  function closeDropdown(){{
    items=[];active=-1;
    dropdown.hidden=true;
    dropdown.innerHTML='';
    findInput.setAttribute('aria-expanded','false');
  }}

  function selectItem(it){{
    // it.q where the label and the searchable name differ (the Moon, whose
    // label carries its phase); it.name everywhere else.
    findInput.value=it.q||it.name;
    closeDropdown();
    var form=document.getElementById('explore');
    if(form){{
      if(form.requestSubmit)form.requestSubmit();
      else form.dispatchEvent(new Event('submit',{{cancelable:true}}));
    }}
  }}

  function fetchMatches(){{
    if(fetchAbort)fetchAbort.abort();
    var v=findInput.value.trim();
    if(v.length<2){{closeDropdown();return;}}
    fetchAbort=new AbortController();
    fetch('/complete/objects?q='+encodeURIComponent(v),{{signal:fetchAbort.signal}})
      .then(function(r){{return r.json();}})
      .then(function(res){{
        items=res;active=-1;
        findInput.setAttribute('aria-expanded',items.length?'true':'false');
        renderDropdown();
      }})
      .catch(function(){{}});
  }}

  findInput.addEventListener('input',function(){{
    if(fetchTimer)clearTimeout(fetchTimer);
    fetchTimer=setTimeout(fetchMatches,120);
  }});
  findInput.addEventListener('keydown',function(e){{
    if(e.key==='ArrowDown'){{
      if(!items.length)return;
      e.preventDefault();
      active=(active+1)%items.length;
      renderDropdown();
    }}else if(e.key==='ArrowUp'){{
      if(!items.length)return;
      e.preventDefault();
      active=(active-1+items.length)%items.length;
      renderDropdown();
    }}else if(e.key==='Enter'){{
      if(active>=0&&items[active]){{
        e.preventDefault();
        selectItem(items[active]);
      }}
      // No highlighted suggestion -- let the #explore form's own submit
      // handle whatever's literally typed (resolve_target does its own
      // case-insensitive matching server-side).
    }}else if(e.key==='Escape'){{
      // One press, fully out -- closes the dropdown, collapses the field
      // back to icon-only below findbar-collapse-width (letting the global
      // handler blur it instead used to leave .expanded on: the box stayed
      // visibly open, focus gone, with no obvious way to close it short of
      // clicking elsewhere), and blurs. stopPropagation so the global
      // handler doesn't also try to act on this same press.
      e.stopPropagation();
      closeDropdown();
      if(findbar)findbar.classList.remove('expanded');
      findInput.blur();
    }}
  }});
  // Delayed so a dropdown-option mousedown (which calls preventDefault, but
  // that doesn't stop the input from blurring) still gets its click handled
  // before the dropdown disappears out from under it.
  findInput.addEventListener('blur',function(){{setTimeout(closeDropdown,150);}});

  if(trigger&&findbar){{
    trigger.addEventListener('click',function(){{
      findbar.classList.add('expanded');
      findInput.focus();
    }});
    document.addEventListener('mousedown',function(e){{
      if(!findbar.classList.contains('expanded'))return;
      if(findbar.contains(e.target))return;
      findbar.classList.remove('expanded');
      closeDropdown();
    }});
  }}
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


# Only shown on an actual chart page (server.py passes "" everywhere else) --
# most of these keys are no-ops on /catalog, /legend etc. anyway, so a hint
# there would be more confusing than helpful.
# One line, and it has to stay one line -- it sits under the chart where a
# second row pushes the page taller. That is the budget the contents are
# chosen against: tab rather than p (both focus the place field, tab is the
# one people try), and no g, since "Share as a GIF" is a button sitting
# right there in the drawer with its own label.
SHORTCUTS_HINT = (
    '<p class="kbd-hint">Keyboard: <kbd>tab</kbd> place &middot; '
    '<kbd>f</kbd> find &middot; <kbd>m</kbd> my location &middot; '
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
var q=[];
if(f)q.push('find='+encodeURIComponent(f));
if(t)q.push('t='+t);
location.href='/'+(p?encodeURIComponent(p):'')+(q.length?'?'+q.join('&'):'');
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

# Chart-page twin of EXPLORE -- same onsubmit, but no #find input of its own
# since the chart page's find field lives in the header instead (see
# header_html's find_value param), right next to the place command bar.
EXPLORE_DATETIME = """<div class="ex">
<form id="explore" onsubmit="var qEl=document.getElementById('q');
var p=qEl?qEl.value.trim():'';
var f=document.getElementById('find').value.trim();
var wd=document.getElementById('whenDate').value;
var wt=document.getElementById('whenTime').value;
var t=(wd&&wt)?(wd+'T'+wt):'';
var q=[];
if(f)q.push('find='+encodeURIComponent(f));
if(t)q.push('t='+t);
location.href='/'+(p?encodeURIComponent(p):'')+(q.length?'?'+q.join('&'):'');
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
            color:#7ee787;font-size:11px;font-family:monospace;white-space:pre;
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
 .sky-label{{color:#c9d1d9;font-size:11px;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
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
            line-height:1.05}}
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
    least able to spare it. */
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
      : 'dark skies in about ' + (data.hours_to_dark < 1
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
