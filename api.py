#!/usr/bin/env python3
"""
One composition layer, three consumers: the CLI, curl, and an agent.

sky.py knows how to draw. This knows how to answer a request — resolve a place,
resolve a time, pick a view, assemble the text, and hand back a structured
version of the same facts for anyone who would rather have JSON.
"""
import datetime as dt, html, json, math, re, unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sky
from sky import (C, paint, julian, gmst_hours, altaz, compass, moon_glyph,
                 phase_name, resolve_target, visibility, next_visible,
                 solar_elongation, find_text, sky_read, render, render_linear,
                 sun, moon, planet, sun_arc, sun_events)

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
            return Place(f"{lat:.2f},{lon:.2f}", lat, lon)
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
                 tle=None, now=None, night=False, width=None):
        self.place = resolve_place(place, fallback)
        self.view, self.facing, self.span = view, facing, span
        self.find, self.iss, self.lines, self.color = find, iss, lines, color
        self.night = night
        self.tle = tle
        # clamped once, here, so it's already canonical by the time it ever
        # reaches a cache key -- otherwise every distinct raw ?w= value before
        # clamping would be its own cache entry even if they render identically
        self.width = max(60, min(220, int(width))) if width else None
        now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        when = quantise_time(when, now)
        if when:                                     # local wall clock at that place
            self.when_local = when
            self.when_utc = when - dt.timedelta(hours=self.place.offset(now))
        else:
            self.when_utc = now
            self.when_local = now + dt.timedelta(hours=self.place.offset(now))
        self.tz = self.place.offset(self.when_utc)


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
               f"  or an asterism (Big Dipper, Orion's Belt, Teapot).\n")
        return Result(txt, dict(error="unknown_target", query=r.find), 404)

    ok, why = visibility(tgt, jd, p.lat, lst)
    shown_utc, note = r.when_utc, None
    data = dict(place=p.name, lat=p.lat, lon=p.lon,
                target=tgt["name"], kind=tgt["kind"], visible=ok, reason=why)

    if not ok:
        w, a2, z2 = next_visible_cached(tgt, p.lat, p.lon, r.when_utc)
        if w is None:
            el = solar_elongation(tgt, jd, p.lat, lst)
            lines = [f"\n  {tgt['name']} is not visible from {p.name} — {why}."]
            lines.append(f"  It is only {el:.0f}° from the Sun: too deep in the glare, "
                         f"and it stays that way for weeks.\n" if el < 20 else
                         f"  No window in the next 40 days from this latitude.\n")
            data.update(next_visible=None, solar_elongation=round(el, 1))
            return Result("\n".join(paint(l, C.LABEL, c) for l in lines), data, 200)
        shown_utc = w
        wl = w + dt.timedelta(hours=p.offset(w))
        same = wl.date() == r.when_local.date()
        when_txt = f"{wl:%H:%M} tonight" if same else f"{wl:%a %d %b} at {wl:%H:%M}"
        note = (f"Not visible right now — {why}.",
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
                     f"{tgt['name']} — {int(sp)}° window", C.HEAD, c), ""]
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
def _compose_sky(r):
    p, c = r.place, r.color
    if r.view == "disc" and not r.facing:
        art, st = render(r.when_utc, p.lat, p.lon, height=34, color=c,
                         show_lines=r.lines, width=r.width)
        mode = "looking up, north at top"
    else:
        art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=r.lines,
                                tle=r.tle, facing=r.facing, span=r.span, width=r.width)
        mode = (f"facing {r.facing.upper()}, {int(round(st['span']))}° wide"
                f"{' (' + st['clamped'] + ')' if st['clamped'] else ''}, true shape"
                if r.facing else "horizon panorama, 0-70° + zenith inset")

    hemi = 'N' if p.lat >= 0 else 'S'
    ew = 'E' if p.lon >= 0 else 'W'
    near = f"  (near {p.near})" if p.near else ""
    head = (f"  {p.name}  {abs(p.lat):.2f}°{hemi} {abs(p.lon):.2f}°{ew}{near}"
            f"   {r.when_local:%d %b %Y %H:%M}   {mode}")
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
        prose=prose,
    )
    return Result("\n".join(out), data)


# ---------------------------------------------------------------- daytime
SUN_COL = "\033[38;5;220m"
DAY_BUCKET = 10                     # minutes; the Sun moves ~2.5° in that time

def is_daytime(r):
    jd = julian(r.when_utc)
    su = sun(jd)
    lst = (gmst_hours(jd) + r.place.lon / 15.0) % 24
    return altaz(su["ra"], su["dec"], r.place.lat, lst)[0] > 0.0


def _hm(t, off):
    return (t + dt.timedelta(hours=off)).strftime("%H:%M") if t else "—"


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
    alt_hi = max(30.0, min(90.0, top + 8))

    jd_now = julian(r.when_utc)
    mo_now = moon(jd_now)
    # The Moon is genuinely visible by day when it is more than half lit;
    # the planets are not, so they are left off rather than drawn as a lie.
    # The Sun gets one marker, on where it actually is. Drawing it at the top of
    # the arc labels noon, which is not what anyone is asking.
    lst_now = (gmst_hours(jd_now) + p.lon / 15.0) % 24
    su_now = sun(jd_now)
    sa_now, sz_now = altaz(su_now["ra"], su_now["dec"], p.lat, lst_now)
    show = {"Moon"} if mo_now["illum"] > 0.4 else set()
    art, st = render_linear(r.when_utc, p.lat, p.lon, color=c, show_lines=False,
                            mag_limit=-5.0, alt_lo=0.0, alt_hi=alt_hi,
                            overlay=(arc, SUN_COL, "SUN", (sa_now, sz_now)),
                            bodies=show, inset=False, width=r.width)

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
        lines.append(f"See tonight's chart now:  "
                     f"curl skymap.sh/{p.slug}?t={tl:%Y-%m-%dT%H:%M}")

    import textwrap
    body = []
    for l in lines:
        body.extend(textwrap.wrap(l, 76))

    hemi = 'N' if p.lat >= 0 else 'S'
    ew = 'E' if p.lon >= 0 else 'W'
    near = f"  (near {p.near})" if p.near else ""
    head = (f"  {p.name}  {abs(p.lat):.2f}°{hemi} {abs(p.lon):.2f}°{ew}{near}"
            f"   {r.when_local:%d %b %Y %H:%M}   the Sun's path today")
    out = ["", paint(head, C.HEAD, c), "", art, ""]
    out += [paint("  " + l, C.LABEL, c) for l in body]
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
skymap.sh — the night sky above you, as text

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
  ?format=json          the same facts, structured
  ?plain=1              no ANSI colour
  ?w=100                render at N columns wide instead of the default

  10° is a closed fist at arm's length, so the gridlines are a ruler.

  Fit any terminal automatically, add to your shell profile:
    skymap() { curl "skymap.sh/${1:-}?w=$(tput cols)"; }

Stars: Yale Bright Star Catalogue. Planets: JPL approximate elements.
Sun and Moon: Meeus. Satellites: CelesTrak.
"""


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
</style></head><body><div class="w">
<pre class="cta">curl skymap.sh{path}</pre>
<p class="t"><b>skymap.sh</b> — this page is what that prints.
<a href="/demo">demo</a> · <a href="/help">help</a></p>
{explore}<pre>{body}</pre>
<p class="t" style="margin-top:18px">Created by <a href="https://x.com/habibicode">@habibicode</a>
· <a href="https://github.com/HabibiCodeCH/skymap-sh">see the repo</a></p>
</div></body></html>"""


EXPLORE = """<div class="ex">
<form id="explore" onsubmit="var p=document.getElementById('place').value.trim();
var f=document.getElementById('find').value.trim();
if(!p&&!f)return false;
location.href='/'+(p?encodeURIComponent(p):'')+(f?'?find='+encodeURIComponent(f):'');
return false;">
<input id="place" type="text" placeholder="city or lat,lon" autocomplete="off">
<input id="find" type="text" placeholder="find (Venus, Big Dipper...)" autocomplete="off">
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
