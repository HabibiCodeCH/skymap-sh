#!/usr/bin/env python3
"""
events.py — what's coming up in the sky, computed from sky.py's own ephemeris.

No new dependency and no network. Moon phases, equinoxes and solstices,
oppositions, greatest elongations and close approaches all fall out of
primitives sky.py already has (sun, moon, planet, angsep, altaz). Meteor
showers and eclipses can't be derived from an ephemeris, so those two come
from small checked-in tables (showers.json, eclipses.json).

Two layers, and the split is what keeps this cheap:

  scan_global(start, days)   every event that is true for the whole planet --
                             a moon phase happens at one instant everywhere.
                             Memoised per UTC day, so the whole site does this
                             work once a day, not once a request.

  localise(ev, lat, lon, tz) what that event looks like from one place: local
                             clock time, altitude and compass, whether it's
                             above the horizon in darkness at all. Cheap, and
                             the only part that depends on where you are.

  upcoming(lat, lon, days)   the two composed. This is the public entry point.

Accuracy. sky.py's Sun is a low-order series and its Moon is a seven-term one,
so a moon phase lands within about an hour of the published time and an equinox
within about twenty minutes. Conjunction separations are good to a few tenths
of a degree. That is the right precision for "which night do I go outside" and
the wrong precision for anything else, which is why nothing here prints seconds.
"""
import datetime as dt
import json
import math
import os
import re
from functools import lru_cache

import sky
from sky import (D, altaz, angsep, compass, gmst_hours, julian, moon,
                 moon_glyph, phase_name, planet, sun)

BASE = os.path.dirname(os.path.abspath(__file__))

# Naked-eye bodies only, and "naked-eye" is the whole filter.
#
# Uranus reaches mag 5.6 at opposition, which is genuinely visible from a dark
# site, so it earns a line. Neptune peaks at 7.8 and never does, so it doesn't
# -- an event you cannot go outside and see is padding, however real it is.
# Neither of them belongs in conjunctions either: Uranus 2° from Mars is not
# something anyone sets an alarm for.
CONJUNCTION_BODIES = ["Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"]
OPPOSITION_BODIES = ["Mars", "Jupiter", "Saturn", "Uranus"]
INFERIOR_BODIES = ["Mercury", "Venus"]

# How close two bodies have to get before it's worth a line. The Moon sweeps
# past something most weeks, so it needs the tighter cut or the list is all
# Moon and nothing else.
CONJ_MAX_SEP = 3.5          # planet-planet
CONJ_MAX_SEP_MOON = 2.5     # anything involving the Moon

# Below this elongation from the Sun a "conjunction" is a fact about geometry
# rather than something anyone can see, however close the two bodies get.
MIN_ELONGATION = 15.0

# "Dark enough to see it" is not one threshold -- Venus at magnitude -4 is
# obvious in bright twilight, a meteor shower needs the sky properly black.
# sky.py's dark_enough(sun_alt, mag) already encodes exactly that curve, so
# events are graded by an effective magnitude and handed to it rather than
# getting a blanket cut of their own. A single -12 rule here marked Venus at
# greatest elongation "not visible from Zürich", which is the opposite of true.
#
# Meteors have no magnitude of their own; 2.5 buys the nautical-dark answer,
# which is the standard condition rates are quoted under.
SHOWER_DARK_MAG = 2.5

# Showers are watched by lying back and taking in a wide field, so a radiant
# scraping the horizon is no good even though a planet there would be fine.
SHOWER_MIN_ALT = 15.0
DEFAULT_MIN_ALT = 8.0        # same floor sky.py's visibility() uses


# ---------------------------------------------------------------- time
def from_julian(jd):
    """Inverse of sky.julian(). Meeus ch.7, and the round trip is tested."""
    jd = jd + 0.5
    z, f = int(jd), jd - int(jd)
    if z >= 2299161:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    else:
        a = z
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    frac = day - int(day)
    secs = int(round(frac * 86400))
    # Rounding 23:59:59.7 up has to roll the date, not produce hour 24.
    return (dt.datetime(year, month, int(day)) + dt.timedelta(seconds=secs)).replace(microsecond=0)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def event_id(kind, name, when_utc):
    """Stable identity for one event, to the day.

    The same string is the ICS UID, the RSS GUID and the Bluesky bot's
    already-posted key, so a reader never re-flags an item it has seen and the
    bot can't double-post across a restart. Deliberately day-grained: refining
    the ephemeris later may move a peak by half an hour, and that must not
    mint a new id for an event people have already seen.
    """
    return f"{kind}-{_slug(name)}-{when_utc:%Y%m%d}"


# ---------------------------------------------------------------- root finding
def _wrap180(x):
    return ((x + 180.0) % 360.0) - 180.0


def _bisect(f, lo, hi, tol=1e-4):
    """f(lo) and f(hi) straddle zero. Returns the jd where f is zero.

    tol is in days: 1e-4 d is about 9 seconds, far finer than the underlying
    series is accurate, but bisection is cheap and it costs ~14 iterations.
    """
    flo = f(lo)
    for _ in range(60):
        if hi - lo < tol:
            break
        mid = (lo + hi) / 2
        fmid = f(mid)
        if (flo < 0) == (fmid < 0):
            lo, flo = mid, fmid
        else:
            hi = mid
    return (lo + hi) / 2


def _crossings(angle_of, target, jd0, jd1, step):
    """Every jd in [jd0, jd1] where a steadily changing angle passes through
    target degrees, in either direction.

    Both directions matter. The Moon's age and the Sun's longitude climb, so
    phases and equinoxes are rising crossings. A planet's longitude minus the
    Sun's *falls*, because the Sun laps the planet -- so every opposition is a
    falling one, and a rising-only test found none at all in a whole year.

    angle_of(jd) returns 0-360 and wraps. Working in _wrap180(angle - target)
    turns each crossing into a clean sign change, but it also introduces a
    fake one every cycle at the ±180 antipode. Both look identical to a sign
    test, so the jump size tells them apart: a real crossing moves the value
    by a few degrees between samples, the wrap moves it by ~360.
    """
    out = []
    t = jd0
    prev = _wrap180(angle_of(t) - target)
    while t < jd1:
        nxt = min(t + step, jd1)
        cur = _wrap180(angle_of(nxt) - target)
        if (prev < 0) != (cur < 0) and abs(cur - prev) < 90:
            out.append(_bisect(lambda j: _wrap180(angle_of(j) - target), t, nxt))
        t, prev = nxt, cur
    return out


def _ternary_min(f, lo, hi, iters=40):
    """jd of the minimum of a unimodal f on [lo, hi]."""
    for _ in range(iters):
        a = lo + (hi - lo) / 3
        b = hi - (hi - lo) / 3
        if f(a) < f(b):
            hi = b
        else:
            lo = a
    return (lo + hi) / 2


# ---------------------------------------------------------------- body helpers
def body_radec(name, jd):
    """(ra hours, dec deg) for the Moon, the Sun, or any planet."""
    if name == "Moon":
        b = moon(jd)
    elif name == "Sun":
        b = sun(jd)
    else:
        b = planet(name, jd)
    return b["ra"], b["dec"]


def _ecliptic_lon(name, jd):
    # "elon" is ecliptic longitude. He is not, in fact, everywhere.
    if name == "Moon":
        return moon(jd)["elon"]
    if name == "Sun":
        return sun(jd)["elon"]
    return planet(name, jd)["elon"]


def _elongation(name, jd):
    """Signed elongation from the Sun in ecliptic longitude. Positive is east
    of the Sun, which means it sets after the Sun and you look for it after
    sunset."""
    return _wrap180(_ecliptic_lon(name, jd) - sun(jd)["elon"])


def _separation(a, b, jd):
    ra1, de1 = body_radec(a, jd)
    ra2, de2 = body_radec(b, jd)
    return angsep(de1, ra1 * 15.0, de2, ra2 * 15.0)


def _magnitude(name, jd):
    if name == "Moon":
        return -12.7
    return round(planet(name, jd)["mag"], 1)


# ---------------------------------------------------------------- moon phases
PHASE_TARGETS = [(0.0, "New Moon"), (90.0, "First quarter Moon"),
                 (180.0, "Full Moon"), (270.0, "Last quarter Moon")]


def moon_phases(jd0, jd1):
    """The four principal phases. moon()["age"] is already the elongation from
    the Sun in degrees, 0 new and 180 full, so each phase is one crossing."""
    out = []
    for target, label in PHASE_TARGETS:
        for jd in _crossings(lambda j: moon(j)["age"], target, jd0, jd1, 1.0):
            when = from_julian(jd)
            out.append(dict(
                kind="moon_phase", name=label, when_utc=when,
                id=event_id("moon-phase", label, when),
                glyph=moon_glyph(target), illum=round(moon(jd)["illum"] * 100),
                headline=label,
            ))
    return out


# ---------------------------------------------------------------- seasons
SEASON_TARGETS = [(0.0, "March equinox"), (90.0, "June solstice"),
                  (180.0, "September equinox"), (270.0, "December solstice")]


def seasons(jd0, jd1):
    out = []
    for target, label in SEASON_TARGETS:
        for jd in _crossings(lambda j: sun(j)["elon"], target, jd0, jd1, 1.0):
            when = from_julian(jd)
            out.append(dict(
                kind="season", name=label, when_utc=when,
                id=event_id("season", label, when), glyph="☉",
                headline=label,
            ))
    return out


# ---------------------------------------------------------------- oppositions
def oppositions(jd0, jd1):
    """An outer planet is at opposition when it sits 180° from the Sun: it
    rises at sunset, is highest at midnight, and is at its brightest and
    closest for the year. The single best night to look at it."""
    out = []
    for name in OPPOSITION_BODIES:
        for jd in _crossings(lambda j, n=name: (_ecliptic_lon(n, j) - sun(j)["elon"]) % 360,
                             180.0, jd0, jd1, 5.0):
            when = from_julian(jd)
            out.append(dict(
                kind="opposition", name=f"{name} at opposition", body=name,
                when_utc=when, id=event_id("opposition", name, when),
                mag=_magnitude(name, jd), glyph="✦",
                headline=f"{name} at opposition",
                note="up all night, brightest and closest of the year",
            ))
    return out


def elongations(jd0, jd1):
    """Mercury and Venus never stray far from the Sun; greatest elongation is
    the turning point, and the only time they're worth chasing. East means it
    sets after the Sun (evening), west means it rises before it (morning)."""
    out = []
    for name in INFERIOR_BODIES:
        step = 2.0
        jd = jd0
        prev2, prev1 = None, None
        while jd <= jd1:
            cur = _elongation(name, jd)
            if prev2 is not None and prev1 is not None:
                # A turning point in |elongation|, on one side of the Sun only:
                # a sign change between samples is the planet crossing the Sun,
                # not an extremum.
                if (prev1 > 0) == (cur > 0) == (prev2 > 0):
                    if abs(prev1) > abs(prev2) and abs(prev1) > abs(cur):
                        peak = _ternary_min(lambda j, n=name: -abs(_elongation(n, j)),
                                            jd - 2 * step, jd)
                        when = from_julian(peak)
                        side = "east" if _elongation(name, peak) > 0 else "west"
                        out.append(dict(
                            kind="elongation", name=f"{name} at greatest elongation",
                            body=name, when_utc=when,
                            id=event_id("elongation", f"{name}-{side}", when),
                            sep_deg=round(abs(_elongation(name, peak)), 1),
                            side=side, mag=_magnitude(name, peak), glyph="✦",
                            headline=f"{name} at greatest elongation {side}",
                            note=("highest in the evening sky after sunset" if side == "east"
                                  else "highest in the morning sky before sunrise"),
                        ))
            prev2, prev1 = prev1, cur
            jd += step
    return out


# ---------------------------------------------------------------- conjunctions
def conjunctions(jd0, jd1, step=0.25):
    """Local minima of the angular separation between two naked-eye bodies.

    Step is six hours because the Moon covers 13° a day and a coarser grid
    walks straight past its closest approach. Planet-planet pairs would be
    happy with days, but one grid for both is simpler than two.
    """
    out = []
    pairs = [(a, b) for i, a in enumerate(CONJUNCTION_BODIES)
             for b in CONJUNCTION_BODIES[i + 1:]]
    for a, b in pairs:
        limit = CONJ_MAX_SEP_MOON if "Moon" in (a, b) else CONJ_MAX_SEP
        jd = jd0
        prev2 = prev1 = None
        while jd <= jd1:
            cur = _separation(a, b, jd)
            if prev2 is not None and prev1 < prev2 and prev1 <= cur:
                lo, hi = jd - 2 * step, jd
                peak = _ternary_min(lambda j: _separation(a, b, j), lo, hi)
                sep = _separation(a, b, peak)
                if sep <= limit and _visible_pair(a, b, peak):
                    when = from_julian(peak)
                    label = f"{a} meets {b}"
                    out.append(dict(
                        kind="conjunction", name=label, bodies=[a, b],
                        when_utc=when, id=event_id("conjunction", f"{a}-{b}", when),
                        sep_deg=round(sep, 1), glyph="●" if "Moon" in (a, b) else "✦",
                        mag=None if "Moon" in (a, b) else max(_magnitude(a, peak),
                                                              _magnitude(b, peak)),
                        headline=f"{a} and {b} {sep:.1f}° apart",
                    ))
            prev2, prev1 = prev1, cur
            jd += step
    return out


def _visible_pair(a, b, jd):
    """Both bodies far enough from the Sun to be seeable at all. Without this
    the list fills up with conjunctions that happen in broad daylight, which
    are true and useless."""
    return (abs(_elongation(a, jd)) >= MIN_ELONGATION
            and abs(_elongation(b, jd)) >= MIN_ELONGATION)


# ---------------------------------------------------------------- meteor showers
@lru_cache(maxsize=1)
def _showers():
    with open(f"{BASE}/showers.json") as fh:
        return json.load(fh)


def _precession_lon(jd):
    """General precession in ecliptic longitude since J2000, in degrees.

    The published solar longitudes are referenced to the equinox of J2000.0,
    but sky.py's sun()["elon"] is the longitude of date. The two drift apart
    by 1.4° a century, which sounds negligible and is not: by 2026 it is 0.36°,
    and the Sun covers that in nine hours. Comparing them directly put every
    shower peak most of a night early -- enough to send someone out on the
    wrong evening, which is the only thing this feature has to get right.
    """
    t = (jd - 2451545.0) / 36525.0
    return 1.396971 * t + 0.0003086 * t * t


def meteor_showers(jd0, jd1):
    """Peaks are fixed in solar longitude, not in the calendar -- the Perseids
    peak when Earth reaches the same point in its orbit, which drifts about a
    day against the date over four years. Storing the solar longitude and
    finding the crossing gives the right date in any year for free, and it's
    the same crossing-finder the equinoxes use."""
    out = []
    for sh in _showers():
        # The correction depends on when the crossing lands, so find it with a
        # correction taken from the middle of the window, then re-solve with
        # one taken from the answer. The second pass moves it by seconds.
        rough = (sh["solar_lon"] + _precession_lon((jd0 + jd1) / 2)) % 360
        for jd in _crossings(lambda j: sun(j)["elon"], rough, jd0, jd1, 1.0):
            target = (sh["solar_lon"] + _precession_lon(jd)) % 360
            jd = _bisect(lambda j: _wrap180(sun(j)["elon"] - target), jd - 1.0, jd + 1.0)
            when = from_julian(jd)
            mo = moon(jd)
            out.append(dict(
                kind="meteor_shower", name=sh["name"], when_utc=when,
                id=event_id("shower", sh["name"], when),
                zhr=sh["zhr"], radiant_ra=sh["ra"], radiant_dec=sh["dec"],
                glyph="☄", moon_illum=round(mo["illum"] * 100),
                headline=f"{sh['name']} peak",
                note=sh.get("note", ""),
            ))
    return out


# ---------------------------------------------------------------- eclipses
@lru_cache(maxsize=1)
def _eclipses():
    with open(f"{BASE}/eclipses.json") as fh:
        return json.load(fh)


def eclipses(jd0, jd1):
    """Static table, not computed.

    A lunar eclipse is tractable from what sky.py has, but a solar eclipse's
    local circumstances need Besselian elements -- a real chunk of work for
    two to four events a year that are published years ahead. So this table is
    dates, types and broad geography, and the honest thing it does is say
    "not visible from here" rather than invent a local prediction. See
    NOTES.md for what would have to change to compute them.
    """
    out = []
    for ec in _eclipses():
        when = dt.datetime.fromisoformat(ec["when_utc"])
        if not (jd0 <= julian(when) <= jd1):
            continue
        out.append(dict(
            kind="eclipse", name=ec["name"], when_utc=when,
            id=event_id("eclipse", ec["name"], when),
            eclipse_type=ec["type"], regions=ec["regions"],
            glyph="◐" if ec["type"].endswith("lunar") else "◉",
            headline=ec["name"], note=f"visible from {ec['regions']}",
        ))
    return out


# ---------------------------------------------------------------- the scan
def scan_global(start_utc, days=90):
    """Every event in the window that is true everywhere on Earth.

    Location-independent by construction: a moon phase, an opposition and a
    shower peak all happen at one instant for the whole planet. Only the
    localise() step below knows where you are, which is what lets this be
    computed once a day for the entire site.
    """
    jd0 = julian(start_utc)
    jd1 = jd0 + days
    evs = (moon_phases(jd0, jd1) + seasons(jd0, jd1) + oppositions(jd0, jd1)
           + elongations(jd0, jd1) + conjunctions(jd0, jd1)
           + meteor_showers(jd0, jd1) + eclipses(jd0, jd1))
    return sorted(evs, key=lambda e: e["when_utc"])


@lru_cache(maxsize=8)
def _scan_cached(day_ordinal, days):
    start = dt.datetime.fromordinal(day_ordinal)
    return tuple(scan_global(start, days))


def scan_cached(now_utc, days=90):
    """scan_global memoised on the UTC date. The whole site pays for one scan
    a day; every request after the first is a dict lookup."""
    return list(_scan_cached(now_utc.date().toordinal(), days))


# ---------------------------------------------------------------- localisation
def _sun_alt(jd, lat, lon):
    lst = (gmst_hours(jd) + lon / 15.0) % 24
    s = sun(jd)
    return altaz(s["ra"], s["dec"], lat, lst)[0]


def _alt_az(ra_h, dec_d, jd, lat, lon):
    lst = (gmst_hours(jd) + lon / 15.0) % 24
    return altaz(ra_h, dec_d, lat, lst)


def best_dark_moment(jd_event, ra_h, dec_d, lat, lon, mag, span_h=18, step_min=20):
    """When, in the usable sky around the event, that patch is highest.

    An event's exact instant is often local noon somewhere; what a person
    needs is the best moment that night. Returns (jd, alt, az) or None if the
    thing never clears the horizon in a dark enough sky -- which is the honest
    answer for the Geminids from Sydney, or for anything at all from Tromsø in
    August, where the Sun never gets more than 5° below the horizon.
    """
    best = None
    steps = int(span_h * 60 / step_min)
    for i in range(-steps, steps + 1):
        jd = jd_event + i * step_min / 1440.0
        if not sky.dark_enough(_sun_alt(jd, lat, lon), mag):
            continue
        alt, az = _alt_az(ra_h, dec_d, jd, lat, lon)
        if alt <= 0:
            continue
        if best is None or alt > best[1]:
            best = (jd, alt, az)
    return best


def _dark_window(jd_event, ra_h, dec_d, lat, lon, mag, min_alt, around_jd,
                 span_h=18, step_min=20):
    """The one unbroken stretch containing around_jd where the sky is dark
    enough and the point is at least min_alt up. This is the "best
    01:00-04:30" line.

    It has to be the contiguous run, not the outer bounds of everything that
    qualifies: an 18-hour scan either side of the event spans two evenings,
    and taking first-and-last across both produced a 24-hour "window" that
    printed as "best 20:45-20:45". Same clock time, because it was the same
    time on two different nights.
    """
    steps = int(span_h * 60 / step_min)
    runs, run = [], None
    for i in range(-steps, steps + 1):
        jd = jd_event + i * step_min / 1440.0
        ok = sky.dark_enough(_sun_alt(jd, lat, lon), mag)
        if ok:
            alt, _az = _alt_az(ra_h, dec_d, jd, lat, lon)
            ok = alt >= min_alt
        if ok:
            run = (jd, jd) if run is None else (run[0], jd)
        elif run is not None:
            runs.append(run)
            run = None
    if run is not None:
        runs.append(run)
    if not runs:
        return None
    slack = step_min / 1440.0
    for lo, hi in runs:
        if lo - slack <= around_jd <= hi + slack:
            return (lo, hi)
    return max(runs, key=lambda r: r[1] - r[0])


def _event_mag(ev, jd):
    """The magnitude that decides how dark the sky has to be.

    For a pairing it's the *fainter* of the two: Moon and Mercury 2° apart is
    only worth going out for once Mercury itself is pickable out, and the Moon
    being obvious in twilight doesn't help with that.
    """
    if ev["kind"] == "meteor_shower":
        return SHOWER_DARK_MAG
    if ev["kind"] == "conjunction":
        return max(_magnitude(b, jd) for b in ev["bodies"])
    return _magnitude(ev["body"], jd)


def _local(when_utc, tz_offset):
    return when_utc + dt.timedelta(hours=tz_offset)


def localise(ev, lat, lon, tz_offset):
    """One global event as seen from one place. Returns a new dict; the input
    is left alone so the memoised global scan is never mutated."""
    e = dict(ev)
    e["when_local"] = _local(ev["when_utc"], tz_offset)
    jd = julian(ev["when_utc"])
    kind = ev["kind"]

    # Phases, seasons and eclipses are moments, not viewing sessions: a full
    # Moon is full whatever the sky is doing over your head, so there is
    # nothing to localise beyond the clock.
    if kind in ("moon_phase", "season"):
        e["visible"] = True
        return e
    if kind == "eclipse":
        # We can't compute the path without Besselian elements, but we can
        # answer the necessary condition exactly: an eclipse is only visible
        # where the eclipsed body is above the horizon at that instant.
        #
        # For a lunar eclipse that's the whole answer -- the Moon looks the
        # same from everywhere on the night side. For a solar one it only
        # rules places out, so we say the Sun is up and let the regions line
        # say the rest, rather than promising totality nobody here will see.
        lunar = ev["eclipse_type"].endswith("lunar")
        ra, dec = body_radec("Moon" if lunar else "Sun", jd)
        alt, az = _alt_az(ra, dec, jd, lat, lon)
        e["alt"] = round(alt, 1)
        e["compass"] = compass(az)
        e["visible"] = alt > 0
        if not e["visible"]:
            e["reason"] = ("the Moon is below the horizon here at that moment"
                           if lunar else
                           "the Sun is below the horizon here, it's night")
        elif not lunar:
            # The Sun being up only means this place is *in range*, never that
            # it is on the centre line. Totality is a track ~100 km wide;
            # Zürich sees a deep partial on 12 Aug 2026 while Reykjavík is
            # inside the path, and nothing computable from here tells the two
            # apart. So say where totality runs and let the reader place
            # themselves, rather than promising them an eclipse they'll miss.
            # Quoting a local percentage would need Besselian elements — see
            # NOTES.md.
            e["in_range"] = True
            e["note"] = (f"the Sun is up here. {ev['eclipse_type'].split()[0].title()} "
                         f"only along a narrow track through {ev['regions']}; "
                         f"a partial eclipse either side of it")
        return e

    if kind == "meteor_shower":
        ra, dec = ev["radiant_ra"], ev["radiant_dec"]
    elif kind == "conjunction":
        ra, dec = body_radec(ev["bodies"][0], jd)
    else:
        ra, dec = body_radec(ev["body"], jd)

    mag = _event_mag(ev, jd)
    min_alt = SHOWER_MIN_ALT if kind == "meteor_shower" else DEFAULT_MIN_ALT

    best = best_dark_moment(jd, ra, dec, lat, lon, mag)
    if best is None:
        e["visible"] = False
        e["reason"] = "never above the horizon in a dark enough sky that night"
        return e

    bjd, alt, az = best
    e["visible"] = True
    e["best_local"] = _local(from_julian(bjd), tz_offset)
    e["alt"] = round(alt, 1)
    e["compass"] = compass(az)

    win = _dark_window(jd, ra, dec, lat, lon, mag, min_alt, bjd)
    # A run narrower than the sampling grain is a single sample; quoting
    # "best 21:05-21:05" reads like a bug and tells nobody anything.
    if win and win[1] - win[0] > 1.5 * 20 / 1440.0:
        e["window_local"] = [_local(from_julian(w), tz_offset).strftime("%H:%M")
                             for w in win]

    if kind == "meteor_shower":
        # The Moon is the single thing that decides whether a shower is worth
        # setting an alarm for, so it belongs on the event, not in a footnote.
        mo = moon(bjd)
        malt, _maz = _alt_az(mo["ra"], mo["dec"], bjd, lat, lon)
        e["moon_up"] = malt > 0
        e["moon_illum"] = round(mo["illum"] * 100)
        e["moon_verdict"] = _moon_verdict(e["moon_illum"], e["moon_up"])
    return e


def _moon_verdict(illum, up):
    if not up:
        return "the Moon is down, nothing washing it out"
    if illum < 25:
        return "a thin Moon, barely in the way"
    if illum < 60:
        return "a half-lit Moon will wash out the faint ones"
    return "a bright Moon will drown most of it"


def upcoming(lat, lon, tz_offset, now_utc=None, days=90, visible_only=False):
    """The public entry point: what's coming up, as seen from here.

    visible_only drops what never clears the horizon in darkness. The default
    keeps them, because "the Geminids peak on the 14th but the radiant never
    rises here" is worth saying out loud rather than silently omitting.
    """
    now_utc = now_utc or dt.datetime.utcnow().replace(microsecond=0)
    evs = [localise(e, lat, lon, tz_offset)
           for e in scan_cached(now_utc, days)
           if e["when_utc"] >= now_utc]
    if visible_only:
        evs = [e for e in evs if e["visible"] is not False]
    return evs


# How far ahead each kind of event is worth flagging on a page that is
# otherwise a star chart, in days. A kind missing from this map is never
# teased at all.
#
# The horizons differ because the events do. A meteor shower is worth knowing
# about a fortnight out, because you might arrange your week around it. The
# Moon passing Jupiter is worth knowing about the night before, and stale
# three days later.
#
# Moon phases and equinoxes are deliberately absent. There is a principal moon
# phase every 7.4 days, so including them at any horizon over a week means the
# line is on screen permanently -- which is exactly what a first version did,
# firing on 72 of 72 sampled nights. A line that is always there stops being
# read, and then the Perseids scroll past in it unnoticed.
TEASER_HORIZON = {
    "eclipse": 14,
    "meteor_shower": 14,
    "opposition": 10,
    "elongation": 7,
    "conjunction": 3,
}


def next_event(lat, lon, tz_offset, now_utc=None, within_days=14,
               horizons=TEASER_HORIZON):
    """The single most interesting thing coming up, or None.

    Not simply the nearest: a first-quarter Moon three days out should not
    bury a meteor shower peaking in four. Rank by how much someone would
    actually want to know, then break ties by date.

    horizons=None considers everything inside within_days, which is what the
    full list wants; the default applies the per-kind cutoffs above, which is
    what the one-line teaser wants.
    """
    now = now_utc or dt.datetime.utcnow().replace(microsecond=0)
    evs = upcoming(lat, lon, tz_offset, now, days=within_days, visible_only=True)
    if horizons is not None:
        evs = [e for e in evs
               if e["kind"] in horizons
               and (e["when_utc"] - now).total_seconds() / 86400 <= horizons[e["kind"]]]
    if not evs:
        return None
    return max(evs, key=lambda e: (_interest(e), -e["when_utc"].timestamp()))


# How much a given event earns its place on a page that is mostly a star
# chart. Showers and eclipses are the reason people look up on a given night;
# a first-quarter Moon happens every month and nobody sets an alarm for it.
INTEREST = {"eclipse": 100, "meteor_shower": 90, "opposition": 60,
            "conjunction": 50, "elongation": 40, "season": 30, "moon_phase": 10}


def _interest(e):
    score = INTEREST.get(e["kind"], 0)
    if e["kind"] == "meteor_shower":
        score += min(20, e.get("zhr", 0) / 10)
        if not e.get("moon_up", True):
            score += 10
    if e["kind"] == "conjunction":
        score += max(0, 10 - e.get("sep_deg", 10) * 3)
    if e["kind"] == "moon_phase" and e["name"] in ("Full Moon", "New Moon"):
        score += 5
    return score
