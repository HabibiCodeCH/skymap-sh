#!/usr/bin/env python3
"""
One composition layer, three consumers: the CLI, curl, and an agent.

sky.py knows how to draw. This knows how to answer a request — resolve a place,
resolve a time, pick a view, assemble the text, and hand back a structured
version of the same facts for anyone who would rather have JSON.
"""
import datetime as dt, html, json, math, re, unicodedata
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sky
from sky import (C, paint, julian, gmst_hours, altaz, angsep, compass, moon_glyph,
                 phase_name, resolve_target, visibility, next_visible,
                 solar_elongation, find_text, sky_read, render, render_linear,
                 sun, moon, planet, sun_arc, sun_events, dark_enough, DSO_LEGEND)

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
    cost a dict lookup, not a fresh scan."""
    key = (round(lat, 1), round(lon, 1))
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
                 tle=None, now=None, night=False, width=None, dso=False, quadrant=None):
        self.place = resolve_place(place, fallback)
        self.view, self.facing, self.span = view, facing, span
        self.find, self.iss, self.lines, self.color = find, iss, lines, color
        self.night = night
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
        # request should still switch dso on.
        self.dso = dso or (quadrant is not None)
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
        r2.quadrant_requested = self.quadrant_requested
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
        note = (f"Not visible right now, {why}.",
                f"Next chance: {when_txt}, {a2:.0f}° up in the {compass(z2)}. "
                f"Chart drawn for that moment.")
        data.update(next_visible=dict(when_utc=w.isoformat() + "Z",
                                      when_local=wl.isoformat(),
                                      alt=round(a2), compass=compass(z2)))
        jd = julian(shown_utc); lst = (gmst_hours(jd) + p.lon / 15.0) % 24
        tgt = resolve_target(r.find, jd, p.lat, lst)

    sp = r.span or 60.0
    rng = 26.0
    lo = max(0.0, min(90.0 - rng, tgt["alt"] - rng / 2))
    art, st = render_linear(shown_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                            tle=r.tle, span=sp, alt_lo=lo, alt_hi=lo + rng,
                            target=tgt, mag_limit=5.0, width=r.width)
    shown_local = shown_utc + dt.timedelta(hours=p.offset(shown_utc))
    guide = find_text(tgt, st["visible"], p.lat)

    out = ["", paint(f"  {p.name}   {shown_local:%d %b %Y %H:%M}   finding "
                     f"{tgt['name']}, {int(sp)}° window", C.HEAD, c), ""]
    if note:
        out += [paint("  " + note[0], C.MUTE, c),
                paint("  " + note[1], "\033[38;5;213m", c)]
    else:
        out.append(paint("  Visible now.", "\033[38;5;48m", c))
    out += ["", art, ""]
    out += [paint("  " + l, C.LABEL, c) for l in guide.split("\n")]
    out += ["", _footer(p, c), ""]

    data.update(alt=round(tgt["alt"], 1), az=round(tgt["az"], 1),
                compass=compass(tgt["az"]),
                mag=round(tgt["mag"], 2) if tgt.get("mag") is not None else None,
                shown_utc=shown_utc.isoformat() + "Z", guide=guide)
    return Result("\n".join(out), data)


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


def _horizon_height(r):
    return round(_effective_width(r) / HORIZON_COLS_PER_ROW)


def _sun_path_mode(r):
    """'the Sun's path today' only when when_local's date is the real
    current date at that place -- an explicit ?t= on another day isn't
    "today" just because it's daytime there."""
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    now_local = now + dt.timedelta(hours=r.place.offset(now))
    return "the Sun's path today" if r.when_local.date() == now_local.date() \
        else "the Sun's path"


def _fade_mag_limit(sun_alt):
    """Shared by compose_frame() (animation) and the static views, so a
    snapshot at a given moment always shows exactly what an animation
    frame at that same moment would -- no hard cut at sunset/sunrise, just
    this one continuous function of the Sun's altitude. Biased, not
    linear: stars stay suppressed through the brighter part of twilight
    and catch up fast near full dark -- late to appear at dusk, early to
    vanish at dawn, symmetrically, since this is a pure function of
    altitude with no notion of which direction time runs."""
    if sun_alt >= 0:
        return -5.0
    if sun_alt <= -18:
        return 4.0
    t = ((0 - sun_alt) / 18.0) ** 1.6
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


def _horizon_head(r, mode):
    p = r.place
    hemi = 'N' if p.lat >= 0 else 'S'
    ew = 'E' if p.lon >= 0 else 'W'
    near = f"  (near {p.near})" if p.near else ""
    return (f"  {p.name}  {abs(p.lat):.2f}°{hemi} {abs(p.lon):.2f}°{ew}{near}"
            f"   {r.when_local:%d %b %Y %H:%M}   {mode}")


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


def _quadrant_toggle_url(r):
    """Toggle URL for the quadrant grid button: adds a bare ?quadrant (no
    letter chosen yet) when it's not currently on, or drops it (and the dso
    it auto-enabled) when it is. facing/span/night/w carried over either
    way, same as _png_url, so toggling doesn't reset the rest of the view
    the visitor is already looking at. Relative: same-origin navigation, no
    base_url substitution needed."""
    q = []
    if r.facing: q.append(f"facing={r.facing}")
    if r.span: q.append(f"span={r.span:g}")
    if r.night: q.append("night=1")
    if r.width: q.append(f"w={int(r.width)}")
    if not r.quadrant_requested:
        q.append("quadrant")
    qs = ("?" + "&".join(q)) if q else ""
    return f"/{r.place.slug}{qs}"


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
                                quadrants=r.quadrant_requested)
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

    head = _horizon_head(r, mode)
    prose = sky_read(st, p.name, r.when_local, f"UTC{r.tz:+g}")

    out = ["", paint(head, C.HEAD, c), "", art, ""]
    out += [paint("  " + l, C.LABEL, c) for l in prose.split("\n")[1:]]
    tr = st.get("track")
    if tr:
        pk = max(tr, key=lambda x: x[1])
        out.append(paint(f"  Pass: rises {compass(tr[0][2])} +{tr[0][0]:.0f} min, "
                         f"peaks {pk[1]:.0f}° in the {compass(pk[2])}, "
                         f"sets {compass(tr[-1][2])} +{tr[-1][0]:.0f} min.",
                         "\033[38;5;48m", c))
    elif st.get("iss_err"):
        out.append(paint(f"  ISS: {st['iss_err']}", C.MUTE, c))
    if r.dso:
        out.append(paint(f"  {DSO_LEGEND}", C.MUTE, c))
    if st.get("quad_error"):
        out.append(paint(f"  Unknown quadrant '{st['quad_error']}' -- showing the full view.",
                         C.MUTE, c))
    if st.get("quad_cells"):
        letters = [cell["letter"] for cell in st["quad_cells"]]
        out.append(paint(f"  Quadrants {letters[0]}-{letters[-1]} are marked on the chart. "
                         f"To zoom in, rerun adding ?quadrant={letters[0]} "
                         f"(or --quadrant={letters[0]} on the CLI).", C.MUTE, c))
    # {base_url} is a literal placeholder -- api.py doesn't know its own
    # host, server.py substitutes the real one on the way out, on both
    # cache hits and misses, so a cached render never leaks whatever host
    # first produced it.
    out.append(paint(f"  Share as a PNG: {_png_url(r)}", SUN_COL, c))
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
        prose=prose,
    )
    return Result("\n".join(out), data)


# xterm-256 -> #rrggbb, matching PAGE's own client-side xtermHex() exactly --
# so the 3D view can be handed a ready-to-draw colour per object instead of
# duplicating this table in JS. Every colour sky.py's ASCII renderer uses is
# one of these codes (see star_colour, sky.C, DSO_GLYPH).
_XTERM_BASE16 = ["000000", "800000", "008000", "808000", "000080", "800080",
                "008080", "c0c0c0", "808080", "ff0000", "00ff00", "ffff00",
                "0000ff", "ff00ff", "00ffff", "ffffff"]
_XTERM_LEVELS = [0, 95, 135, 175, 215, 255]
_ANSI_256 = re.compile(r"\033\[38;5;(\d+)m")

def _xterm_hex(n):
    if n < 16:
        return "#" + _XTERM_BASE16[n]
    if n < 232:
        n -= 16
        r, g, b = _XTERM_LEVELS[n // 36], _XTERM_LEVELS[(n // 6) % 6], _XTERM_LEVELS[n % 6]
        return f"#{r:02x}{g:02x}{b:02x}"
    v = 8 + (n - 232) * 10
    return f"#{v:02x}{v:02x}{v:02x}"

def _ansi_hex(ansi):
    m = _ANSI_256.search(ansi)
    return _xterm_hex(int(m.group(1))) if m else "#ffffff"

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
        dark = ev.get("dusk_astro") or ev.get("dusk_nautical")
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
    )


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
    arc = sun_arc(day0, p.lat, p.lon, step_min=DAY_BUCKET)
    top = max((a for _t, a in ((x[0], x[1]) for x in arc)), default=10)
    alt_hi = max(DAY_ALT_HI_FLOOR, min(90.0, top + 8))

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
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=False,
                            mag_limit=_fade_mag_limit(sa_now), alt_lo=0.0, alt_hi=alt_hi,
                            overlay=(arc, SUN_COL, "SUN", (sa_now, sz_now)),
                            bodies=show, inset=False, width=_effective_width(r),
                            height=_horizon_height(r))

    jd = julian(r.when_utc)
    lst = (gmst_hours(jd) + p.lon / 15.0) % 24
    sa, sz = altaz(sun(jd)["ra"], sun(jd)["dec"], p.lat, lst)
    mo = moon(jd)
    first = ev.get("dusk_civil") or ev.get("dusk_nautical")
    dark = ev.get("dusk_astro") or ev.get("dusk_nautical") or first
    dark_txt = (f"first stars about {_hm(first, off)}, fully dark {_hm(dark, off)}"
                if first else "the sky never gets fully dark today")

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
    if first:
        tl = first + dt.timedelta(hours=off)
        # Quoted: zsh (the default shell on macOS) treats a bare ? as a glob
        # character and errors with "no matches found" on an unquoted URL.
        lines.append(f"See tonight's chart now:  "
                     f"curl 'skymap.sh/{p.slug}?t={tl:%Y-%m-%dT%H:%M}'")

    import textwrap
    body = []
    for l in lines:
        body.extend(textwrap.wrap(l, 76))

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
                dark_from=(dark + dt.timedelta(hours=off)).isoformat() if dark else None,
                visible_tonight=[b["name"] for b in later],
                moon=dict(phase=phase_name(mo["age"]),
                          illum=round(mo["illum"] * 100)),
                prose="\n".join(body))
    return Result("\n".join(out), data)


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
                             overlay=overlay, bodies=visible_bodies)

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
    sp = r.span or 60.0
    rng = 26.0
    lo = max(0.0, min(90.0 - rng, tgt["alt"] - rng / 2))
    art, _st = render_linear(shown_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                             tle=r.tle, span=sp, alt_lo=lo, alt_hi=lo + rng,
                             target=tgt, mag_limit=5.0, width=r.width)
    shown_local = shown_utc + dt.timedelta(hours=p.offset(shown_utc))
    head = (f"  {p.name}   {shown_local:%d %b %Y %H:%M}   "
            f"finding {tgt['name']}, {int(sp)}° window")
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
                                 bodies=show, inset=False, width=_effective_width(r),
                                 height=_horizon_height(r))
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
                            width=r.width if r.facing else _effective_width(r),
                            height=None if r.facing else _horizon_height(r),
                            mag_limit=mag_limit, line_limit=mag_limit,
                            # Same "Sun"+"Moon" forcing as _compose_sky above,
                            # for consistency -- this path doesn't call
                            # sky_read() so it can't hit the KeyError, but
                            # without "Moon" here the PNG export would still
                            # silently drop the Moon glyph the main view kept.
                            bodies=_fade_visible_bodies(sun_alt, jd) | {"Sun", "Moon"},
                            dso_limit=DSO_LIMIT if r.dso else None, quadrant=r.quadrant,
                            quadrants=r.quadrant_requested, inset=False)
    mode = (f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
            f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}, true shape"
            if r.facing else "horizon panorama")
    head = _horizon_head(r, mode)
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
  ?find=Big+Dipper works for planets, Sun, Moon, named stars, asterisms
                   tells you if you can see it, and if not, when you can

OPTIONS
  ?t=2026-08-12T23:00   local time at that place (default: now)
  ?night=1              force the star chart even while the Sun is up
  ?nolines=1            stars only, no asterism lines
  ?dso=1                overlay galaxies, nebulae and clusters to mag 11 (Revised NGC)
  ?quadrant=A           crop to one lettered cell of the horizon view --
                        letters are marked on the chart, rerun adding the
                        one you want to zoom in (horizon view only)
  ?format=json          the same facts, structured
  ?plain=1              no ANSI colour
  ?w=100                render at N columns wide instead of the default

  10° is a closed fist at arm's length, so the gridlines are a ruler.

  Fit any terminal automatically, add to your shell profile:
    skymap() { curl "skymap.sh/${1:-}?w=$(tput cols)"; }

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
        f"  {P('○ ◔ ◐ ◕ ● ◕ ◐ ◔', C.MOON)}  Moon, by phase (new, first quarter, full, last quarter, new)",
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


def catalog_text(color=True):
    """Every object findable by name via ?find= -- pulled live from the same
    catalogues resolve_target() reads, so this can't list something that
    isn't actually findable, or miss one that is."""
    def P(s, c):
        return paint(s, c, color)

    def head(s):
        return paint(s, C.HEAD, color)

    stars = sky._load("stars.json")
    asterisms = sky._load("asterisms.json")
    dso = sky._load("deepsky.json")

    named_stars = sorted((s for s in stars if s.get("n")), key=lambda s: s["m"])
    # o["n"] is already the best label build_deepsky.py could give it (a
    # Messier number, else a hand-picked common name) -- a bare NGC number
    # there just means no traditional name exists, so those aren't "named".
    named_dso = sorted((o for o in dso if o["n"] != o["id"]), key=lambda o: o["m"])
    solar_system = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
                    "Saturn", "Uranus", "Neptune"]

    L = [
        "skymap.sh -- object catalog", "",
        "Everything below is findable by name, e.g.:",
        "  curl 'skymap.sh/Zurich?find=Vega'", "",
        head(f"SOLAR SYSTEM ({len(solar_system)})"),
    ]
    L += _columns(solar_system, 12, 6)
    L.append("")
    L.append(head(f"CONSTELLATIONS ({len(asterisms)})"))
    L += _columns(sorted(a["name"] for a in asterisms), 18, 5)
    L.append("")
    L.append(head(f"NAMED STARS ({len(named_stars)}) -- brightest first"))
    for s in named_stars:
        starcol = sky.star_colour(s.get("ci"))
        name = f"{s['n']:22}"
        L.append(f"  {P(name, starcol)} mag {s['m']:>5.2f}  {s['c']}")
    L.append("")
    L.append(head(f"DEEP SKY ({len(named_dso)}) -- ?dso=1, brightest first"))
    for o in named_dso:
        glyph, glyph_c = sky.DSO_GLYPH[o["t"]]
        label = o["n"]
        if o.get("cn") and o["cn"] != label:
            label = f"{label} ({o['cn']})"
        label = f"{label:34}"
        L.append(f"  {P(glyph, glyph_c)} {P(label, C.HEAD)} mag {o['m']:>5.2f}  {sky.DSO_NAMES[o['t']]}")
    L.append("")
    return "\n".join(L)


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


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="The night sky above you, as plain text. curl skymap.sh">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
 body{{margin:0;background:#04060a;color:#c9d1d9;
      font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
      padding:24px 16px 48px;-webkit-font-smoothing:antialiased}}
 .w{{max-width:1200px;margin:0 auto}}
 pre{{margin:0;font-size:11px;line-height:1.22;overflow-x:auto;font-variant-ligatures:none}}
 .t{{color:#6e7681;font-size:12px;margin:0 0 18px}}
 .t b{{color:#c9d1d9;font-weight:600}}
 a{{color:#87d7ff}}
 .ex{{margin:0 0 18px}}
 .ex form{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px}}
 .ex input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
           padding:6px 10px;border-radius:4px;font:inherit;font-size:12px}}
 .ex input#place{{width:170px}}
 .ex input#find{{width:190px}}
 .ex input#whenDate{{width:140px;color-scheme:dark}}
 .ex input#whenTime{{width:100px;color-scheme:dark}}
 .ex button{{background:#238636;border:0;color:#fff;padding:6px 14px;
            border-radius:4px;font:inherit;font-size:12px;cursor:pointer}}
 .ex button:hover{{background:#2ea043}}
 .ex .tries{{color:#6e7681;font-size:12px;margin:0}}
 .ex .tries a{{color:#87d7ff;text-decoration:none}}
 .ex .tries a:hover{{text-decoration:underline}}
 .cta{{background:#0d1117;border:1px solid #30363d;border-radius:6px;
      padding:10px 14px;margin:0 0 14px;color:#7ee787;font-size:13px;
      display:inline-block}}
 .cta::before{{content:"$ ";color:#6e7681}}
 .toolbar{{display:flex;justify-content:space-between;align-items:center;
          flex-wrap:wrap;gap:10px;margin:0 0 14px}}
 .toolbar-left{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
 .toolbar-right{{display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap;
                padding-top:6px}}
 .toolbar-right a{{color:#ffd700;font-size:12px;text-decoration:none;white-space:nowrap}}
 .toolbar-right a:hover{{text-decoration:underline}}
 .animate-controls{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
 .animate-btn{{background:#0d1117;border:1px solid #30363d;color:#ffd700;
              padding:6px 12px;border-radius:4px;font:inherit;font-size:12px;
              cursor:pointer;display:inline-block;text-decoration:none}}
 .animate-btn:hover{{border-color:#ffd700;text-decoration:none}}
 .animate-btn:disabled{{opacity:.6;cursor:default}}
 .animate-btn[hidden]{{display:none}}
 .gif-group{{display:flex;flex-direction:column;gap:4px;align-items:flex-start}}
 .gif-status{{color:#6e7681;font-size:12px;white-space:nowrap}}
 .mobile-only{{display:none}}
 @media (pointer:coarse) and (max-width:900px){{.mobile-only{{display:inline-block}}}}
</style></head><body><div class="w">
<pre class="cta">curl skymap.sh{path}</pre>
<p class="t"><b>skymap.sh</b>
<a href="/demo">demo</a> · <a href="/help">help</a> · <a href="/legend">legend</a> · <a href="/catalog">catalog</a></p>
{explore}<div class="toolbar"><div class="toolbar-left">{animate_btn}{quadrant_btn}</div><div class="toolbar-right">{sphere_btn}{extra}</div></div><pre id="chart-pre">{body}</pre>
<p class="t" style="margin-top:18px">Created by <a href="https://x.com/habibicode">@habibicode</a>
· <a href="https://github.com/HabibiCodeCH/skymap-sh">see the repo</a></p>
<script>
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
function skymapAnimate(btn){{
  // Live preview plays right in the chart itself from the same streaming
  // ?animate= text the CLI uses. The "Share as a GIF" button appears the
  // moment the preview starts, but rendering only actually happens if it's
  // clicked -- see skymapRenderGif -- since that's real Pillow work, not
  // free to do for every single viewer.
  var liveUrl=btn.getAttribute('data-live-url');
  var gifBtn=document.getElementById('gif-btn');
  var pre=document.getElementById('chart-pre');
  btn.disabled=true;btn.textContent='animating…';
  if(gifBtn){{gifBtn.hidden=false;skymapPollGifCapacity(gifBtn);}}
  fetch(liveUrl).then(function(resp){{
    var reader=resp.body.getReader();
    var decoder=new TextDecoder();
    var buf='';
    function pump(){{
      return reader.read().then(function(res){{
        if(res.done){{
          if(buf.trim())pre.innerHTML=ansiToHtml(buf);
          return;
        }}
        buf+=decoder.decode(res.value,{{stream:true}});
        var parts=buf.split('\\x1b[2J\\x1b[H');
        buf=parts.pop();
        for(var i=0;i<parts.length;i++){{
          if(parts[i].trim())pre.innerHTML=ansiToHtml(parts[i]);
        }}
        return pump();
      }});
    }}
    return pump();
  }}).then(function(){{
    btn.disabled=false;btn.textContent='▶ animate';
  }}).catch(function(){{
    btn.disabled=false;btn.textContent='animate failed, try again';
  }});
}}

function skymapPollGifCapacity(gifBtn){{
  // Greys the button out before a click would just 503, rather than only
  // finding out after. A stale read is harmless -- the render endpoint
  // still enforces the real cap itself, this is only ever a UX hint. Skips
  // a tick entirely while this button's own render is in flight, or once
  // it's done and showing the "View GIF" link (dataset.ready) -- otherwise
  // this loop would overwrite that link with '' the next time it ticks,
  // since it doesn't otherwise know the status line is in use for that now.
  var status=document.getElementById('gif-status');
  function poll(){{
    if(gifBtn.dataset.rendering==='1'||gifBtn.dataset.ready==='1')return;
    fetch('/gif-capacity').then(function(r){{return r.json();}}).then(function(d){{
      if(gifBtn.dataset.rendering==='1'||gifBtn.dataset.ready==='1')return;
      gifBtn.disabled=!d.available;
      if(status)status.textContent=d.available?'':
        'Too many GIFs rendering right now, please wait a few seconds';
    }}).catch(function(){{}});
  }}
  poll();
  setInterval(poll,4000);
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
</script>
</div></body></html>"""


EXPLORE = """<div class="ex">
<form id="explore" onsubmit="var p=document.getElementById('place').value.trim();
var f=document.getElementById('find').value.trim();
var wd=document.getElementById('whenDate').value;
var wt=document.getElementById('whenTime').value;
var t=(wd&&wt)?(wd+'T'+wt):'';
if(!p&&!f&&!t)return false;
var q=[];
if(f)q.push('find='+encodeURIComponent(f));
if(t)q.push('t='+t);
location.href='/'+(p?encodeURIComponent(p):'')+(q.length?'?'+q.join('&'):'');
return false;">
<input id="place" type="text" placeholder="city or lat,lon" autocomplete="off" value="{place}">
<input id="find" type="text" placeholder="find (Venus, Big Dipper...)" autocomplete="off">
<input id="whenDate" type="date" title="local date at that place (default: today)">
<input id="whenTime" type="time" title="local time at that place (default: now)">
<button type="submit">go</button>
</form>
<p class="tries">Examples:
<a href="/Nairobi">Nairobi</a> ·
<a href="/Tokyo">Tokyo</a> ·
<a href="/London">London</a> ·
<a href="/New%20York">New York</a> ·
<a href="/Buenos%20Aires">Buenos Aires</a> ·
<a href="/Sydney">Sydney</a> ·
<a href="/90,0">North Pole</a> ·
<a href="/-90,0">South Pole</a>
</p>
</div>
"""


# Mobile-only, additive 3D view of the current sky -- reached from PAGE's
# {{sphere_btn}} link, never linked from curl/terminal output. The only
# external script tag anywhere in this codebase: hand-rolling perspective-
# correct WebGL for a rotating starfield is a much bigger surface than one
# pinned CDN import, scoped to this one opt-in page.
SPHERE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="The night sky above you, in 3D -- look around by tilting your phone.">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
 html,body{{margin:0;height:100%;background:#000;overflow:hidden;
           font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
           -webkit-font-smoothing:antialiased}}
 canvas{{display:block}}
 #hud{{position:fixed;top:0;left:0;right:0;padding:10px 14px;color:#6e7681;font-size:12px;
      display:flex;justify-content:space-between;pointer-events:none;z-index:1000}}
 #hud a{{color:#87d7ff;pointer-events:auto;text-decoration:none}}
 #heading{{color:#8b949e;letter-spacing:.02em}}
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
 #toolbar{{position:fixed;left:0;right:0;bottom:0;z-index:1000;padding:10px 12px;
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
 #find-input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
             padding:6px 10px;border-radius:4px;font:inherit;font-size:16px;width:190px}}
 #find-form button{{background:#238636;border:0;color:#fff;padding:6px 12px;
                    border-radius:4px;font:inherit;font-size:12px;cursor:pointer}}
 #find-cancel{{background:#7a1f1f !important}}
 #find-msg{{position:fixed;left:0;right:0;top:38px;text-align:center;color:#ffd700;
           font-size:12px;padding:0 12px;pointer-events:none;z-index:1000;margin:0}}
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
</style></head><body>
<div id="hud"><a href="/">&larr; {place_name}{home_suffix}</a><span id="heading"></span><span id="mode-label"></span></div>
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
<form id="find-form" autocomplete="off">
<input id="find-input" type="text" placeholder="Find (Venus, Vega...)">
<button type="submit">Find</button>
<button type="button" id="find-cancel" hidden>Cancel</button>
</form>
</div>
<p id="find-msg"></p>
<div id="find-arrow">&gt;&gt;&gt;</div>
<div id="find-reticle">
<div class="tick tick-top"></div>
<div class="tick tick-bottom"></div>
<div class="tick tick-left"></div>
<div class="tick tick-right"></div>
</div>
<script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.160.0/build/three.module.js"}}}}</script>
<script type="module">
import * as THREE from "three";
import {{ CSS2DRenderer, CSS2DObject }} from "https://unpkg.com/three@0.160.0/examples/jsm/renderers/CSS2DRenderer.js";

var PLACE = "{place_slug}";
var statusEl = document.getElementById('status');
var overlay = document.getElementById('overlay');
var enableBtn = document.getElementById('enable');
var modeLabel = document.getElementById('mode-label');
var headingEl = document.getElementById('heading');

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
var zee = new THREE.Vector3(0, 0, 1);
var euler = new THREE.Euler();
var q0 = new THREE.Quaternion();
var q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));
var deviceQ = new THREE.Quaternion();
// Azimuth (compass heading, device alpha) drifts and miscalibrates
// differently on every phone, so it's recentred: wherever you're actually
// facing the moment you tap "look around" becomes dead ahead, 0 degrees.
// Altitude is NOT recentred the same way -- it comes straight from
// gravity via the accelerometer, which doesn't have that drift problem, and
// forcing it to 0 at an arbitrary starting tilt would make the tilt
// readout (and the horizon line/star positions) lie about true altitude.
var yawOffset = 0;
var yawOffsetSet = false;
var _rawForward = new THREE.Vector3();
var _yAxis = new THREE.Vector3(0, 1, 0);
var _yawCorrection = new THREE.Quaternion();

function screenAngle() {{
  if (screen.orientation && typeof screen.orientation.angle === 'number')
    return screen.orientation.angle * Math.PI / 180;
  if (typeof window.orientation === 'number') return window.orientation * Math.PI / 180;
  return 0;
}}

function applyOrientation(e) {{
  if (e.alpha === null || e.beta === null || e.gamma === null) return;
  var alpha = e.alpha * Math.PI / 180, beta = e.beta * Math.PI / 180, gamma = e.gamma * Math.PI / 180;
  euler.set(beta, alpha, -gamma, 'YXZ');
  deviceQ.setFromEuler(euler);
  deviceQ.multiply(q1);
  deviceQ.multiply(q0.setFromAxisAngle(zee, -screenAngle()));
  if (!yawOffsetSet) {{
    _rawForward.set(0, 0, -1).applyQuaternion(deviceQ);
    // Deliberately the same atan2(-x,-z) as before the toVec handedness
    // fix below -- this recovers the device's own raw alpha for a pure
    // Y-axis calibration rotation, which is independent of which world-
    // space azimuth convention toVec renders with.
    yawOffset = Math.atan2(-_rawForward.x, -_rawForward.z);
    yawOffsetSet = true;
  }}
  // A world-space (extrinsic) rotation about the vertical axis only ever
  // shifts azimuth -- it can't tilt anything, so altitude stays exactly
  // what gravity actually measured.
  camera.quaternion.copy(deviceQ);
  camera.quaternion.premultiply(_yawCorrection.setFromAxisAngle(_yAxis, -yawOffset));
}}

function onOrientation(e) {{
  gotOrientation = true;
  if (gyroTimer) {{ clearTimeout(gyroTimer); gyroTimer = null; }}
  lastEvent = e;
}}

function startGyro() {{
  mode = 'gyro';
  modeLabel.textContent = 'gyroscope';
  window.addEventListener('deviceorientation', onOrientation);
  gyroTimer = setTimeout(function() {{ if (!gotOrientation) startDrag(); }}, 1500);
  overlay.hidden = true;
}}

var yaw = 0, pitch = 0, dragging = false, lastX = 0, lastY = 0;
function startDrag() {{
  if (mode === 'drag') return;
  mode = 'drag';
  modeLabel.textContent = 'drag';
  window.removeEventListener('deviceorientation', onOrientation);
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
      foundPoint.material.color.set('#ffffff');
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
  if (mode === 'gyro' && lastEvent) {{
    applyOrientation(lastEvent);
  }} else if (mode === 'drag') {{
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, 'YXZ'));
  }}
  if (mode && ++_frame % 4 === 0) updateHeading();
  updateFindArrow();
  renderer.render(scene, camera);
  declutterLabels();
  labelRenderer.render(scene, camera);
}}
animate();
</script>
</body></html>"""
