"""Lunar eclipses: when they happen, how deep they go, and who can see one.

The counterpart to besselian.py, and much simpler, because a lunar eclipse
is simpler. The Moon goes into the Earth's shadow, and everybody on the
night side watches the same thing at the same instant. There is no path, no
per-place percentage and no thin band worth travelling to: what varies from
place to place is only whether the Moon is above your horizon.

So the two questions this answers are "when" and "is it up from here", and
both come out of NASA's published circumstances (lunar.json,
build_lunar.py) rather than out of any ephemeris of ours. sky.moon() is good
to about 12 arcmin and the umbra is 40 arcmin across, which is not close to
enough to say when the Moon enters it.

Contacts are exact: the catalogue gives each phase's duration in minutes
and every one of them is centred on greatest eclipse.
"""
import json
import math

import sky

# The Earth's equatorial radius in Moon radii, 6378.14 / 1738.1. gamma is
# published in Earth radii and the drawing works in Moon radii, and this is
# the only number in this file that is not NASA's.
EARTH_IN_MOON_RADII = 3.6697

# Typical shadow sizes at the Moon's distance, in Moon radii, for the two
# places that need a number before an eclipse is chosen. The real ones are
# computed per eclipse -- see geometry() -- because they vary by a good ten
# percent with the Moon's distance and the Earth's, and a constant 2.65 made
# the 26 June 2029 eclipse come out at magnitude 1.81 against NASA's 1.84.
UMBRA_R = 2.65
PENUMBRA_R = 4.60

# How fast the point the Moon stands over slides west, in degrees an hour.
# 360 divided by the mean lunar day of 24h 50m, not by 24: the Earth turns
# 15 degrees an hour and the Moon is moving the same way underneath it.
LUNAR_DEG_PER_HOUR = 14.4921

_ELEMENTS = None


def _load():
    global _ELEMENTS
    if _ELEMENTS is None:
        try:
            with open(f"{sky.BASE}/lunar.json") as fh:
                _ELEMENTS = json.load(fh)
        except (OSError, json.JSONDecodeError):
            # Survivable, like every other data file here: a page with no
            # computed circumstances beats a 500.
            _ELEMENTS = {}
    return _ELEMENTS


def has(key):
    return key in _load()


def elements(key):
    return _load().get(key)


def greatest_ut(el):
    """Hours UT of greatest eclipse. The catalogue publishes TD."""
    return el["td"] - el["dT"] / 3600.0


def contacts(key):
    """Every contact, in hours UT, as {name: hour}.

    P1/P4 are the penumbra, U1/U4 the umbra, U2/U3 totality. Each phase's
    duration is published and centred on greatest eclipse, so these are
    NASA's own numbers rearranged rather than anything solved for here.

    Hours may run past 24 or below 0 when an eclipse straddles midnight.
    Whoever formats them owns the wrap; keeping them monotonic is what lets
    a caller sort them and take differences without special cases.
    """
    el = elements(key)
    if not el:
        return {}
    mid = greatest_ut(el)
    out = {"greatest": mid}
    for name, key_ in (("P", "pen_min"), ("U", "par_min"), ("T", "tot_min")):
        half = el.get(key_)
        if half:
            out[name + "1"] = mid - half / 120.0
            out[name + "4"] = mid + half / 120.0
    # Totality's two contacts are the second and third, not the first and
    # fourth. Named the way the catalogue and every almanac name them.
    if "T1" in out:
        out["U2"], out["U3"] = out.pop("T1"), out.pop("T4")
    return out


def phases(key):
    """The contacts in the order they happen, as (label, hour) pairs.

    Labelled for a reader rather than for an almanac: "enters the shadow"
    beats "U1" on a page somebody has arrived at from a search engine.
    """
    c = contacts(key)
    order = (("P1", "penumbra starts"), ("U1", "partial starts"),
             ("U2", "totality starts"), ("greatest", "maximum"),
             ("U3", "totality ends"), ("U4", "partial ends"),
             ("P4", "penumbra ends"))
    return [(label, c[k]) for k, label in order if k in c]


def duration_seconds(key, phase="tot_min"):
    el = elements(key)
    minutes = el and el.get(phase)
    return minutes * 60.0 if minutes else None


def sublunar(key, ut):
    """Where the Moon is overhead at this instant, as (lat, lon).

    The catalogue publishes it at greatest eclipse. Away from that moment
    the point moves the way the sky does, at the rate of the lunar day
    rather than the solar one: the Earth turns 15 degrees an hour, and the
    Moon is going the same way underneath, so the point it stands over
    slides west at about 14.49. Over a night that is the difference between
    getting moonrise right and getting it wrong by half an hour.

    The declination is held fixed, which is the approximation here. It moves
    by up to five degrees a day, so a couple of degrees over a long night --
    enough to matter for a rise time to the minute, not enough to matter for
    a picture of an arc.
    """
    el = elements(key)
    if not el:
        return None
    lon = el["zen_lon"] - LUNAR_DEG_PER_HOUR * (ut - greatest_ut(el))
    return el["zen_lat"], ((lon + 180) % 360) - 180


def moon_alt(key, lat, lon, ut):
    """The Moon's altitude in degrees, from the sublunar point.

    Angular distance from the point the Moon is overhead is the zenith
    distance, by definition. 90 minus it is the altitude, and no ephemeris
    is involved: the hard part was done by whoever published the sublunar
    point.
    """
    sub = sublunar(key, ut)
    if sub is None:
        return None
    slat, slon = sub
    a, b = math.radians(lat), math.radians(slat)
    d = math.radians(lon - slon)
    cos_z = (math.sin(a) * math.sin(b)
             + math.cos(a) * math.cos(b) * math.cos(d))
    return 90.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_z))))


def visibility(key, lat, lon):
    """What this place gets, as a dict.

    "up" is how many of the contacts happen with the Moon above the
    horizon, which is the only thing that varies from place to place. An
    eclipse looks identical to everybody who can see it at all.
    """
    el = elements(key)
    if not el:
        return None
    marks = phases(key)
    up = [(label, ut, moon_alt(key, lat, lon, ut)) for label, ut in marks]
    seen = [m for m in up if m[2] is not None and m[2] > 0]
    alt_max = moon_alt(key, lat, lon, greatest_ut(el))
    return dict(kind=el["kind"], um_mag=el["um_mag"], pen_mag=el["pen_mag"],
                marks=up, visible=bool(seen), all_of_it=len(seen) == len(up),
                alt_at_greatest=alt_max, greatest=greatest_ut(el))


def geometry(key):
    """(closest approach, umbra radius, penumbra radius) in Moon radii.

    Every one of the three is read off the catalogue rather than assumed,
    which is what makes the drawing agree with the published magnitudes
    instead of nearly agreeing.

    gamma is the least distance between the Moon's centre and the shadow's
    axis, in Earth radii, so the closest approach is gamma converted. And
    magnitude is the fraction of the Moon's diameter inside a shadow at that
    moment, m = (R + 1 - s) / 2, which run backwards gives that shadow's
    radius: R = 2m - 1 + s.

    The first version used one constant umbra for every eclipse. It is out by
    up to ten percent, which is invisible on a shallow eclipse and impossible
    on a deep one: 26 June 2029 has a published magnitude of 1.8436, and a
    2.65 umbra cannot produce a magnitude above 1.825 at all -- the closest
    approach came out negative and the drawing quietly used its absolute
    value.
    """
    el = elements(key)
    if not el:
        return None
    s_min = abs(el["gamma"]) * EARTH_IN_MOON_RADII
    return (s_min,
            2.0 * el["um_mag"] - 1.0 + s_min,
            2.0 * el["pen_mag"] - 1.0 + s_min)


def separation(key, ut):
    """Distance between the Moon's centre and the shadow's, in Moon radii.

    Reconstructed from the published circumstances rather than from an orbit.
    geometry() fixes the closest approach; the published first contact fixes
    the rate, because at U1 the two discs touch and the separation there is
    the umbra's radius plus the Moon's. Two knowns, one straight line.
    """
    el = elements(key)
    geo = geometry(key)
    if not el or geo is None:
        return None
    s_min, umbra_r, penumbra_r = geo
    mid = greatest_ut(el)
    c = contacts(key)
    edge = c.get("U1") or c.get("P1")
    if edge is None:
        return None
    s_edge = (umbra_r + 1.0) if "U1" in c else (penumbra_r + 1.0)
    dt_edge = mid - edge
    if dt_edge <= 0:
        return s_min
    # Straight line past the shadow's centre: s^2 = s_min^2 + (rate*dt)^2.
    rate = math.sqrt(max(0.0, s_edge ** 2 - s_min ** 2)) / dt_edge
    return math.hypot(s_min, rate * (ut - mid))


def shadow_centre(key, ut):
    """Where the shadow's centre is, relative to the Moon's, in Moon radii.

    Screen coordinates: x to the right, y down, with north up and east left
    like every other drawing here. Two facts set the direction. The Moon
    overtakes the shadow moving east, so the shadow crosses the disc from
    east to west and bites the eastern limb first -- the left-hand side. And
    gamma is signed: positive means the Moon passes north of the shadow's
    axis, so the shadow sits south of it, which is downwards.
    """
    el = elements(key)
    s = separation(key, ut)
    geo = geometry(key)
    if el is None or s is None or geo is None:
        return None
    mid = greatest_ut(el)
    s_min = geo[0]
    along = math.sqrt(max(0.0, s * s - s_min * s_min))
    if ut < mid:
        along = -along
    return along, math.copysign(s_min, el["gamma"] or 1.0)


def shade_at(key, ut, px, py):
    """What is falling on this point of the Moon's disc: "sun", "penumbra"
    or "umbra".

    px, py are in Moon radii from the Moon's centre, same screen frame as
    shadow_centre. The umbra is where the Earth blocks the Sun completely,
    and it is where the Moon turns copper rather than black: what reaches it
    there is sunlight bent through the whole of the Earth's atmosphere, and
    the atmosphere scatters the blue out of it on the way.
    """
    c, geo = shadow_centre(key, ut), geometry(key)
    if c is None or geo is None:
        return "sun"
    _s_min, umbra_r, penumbra_r = geo
    d = math.hypot(px - c[0], py - c[1])
    if d <= umbra_r:
        return "umbra"
    if d <= penumbra_r:
        return "penumbra"
    return "sun"


def up_window(key, lat, lon, step_min=2.0, span_h=16.0):
    """When the Moon is above the horizon around this eclipse, as (rise,
    set) in hours UT. None when it never comes up while anything is
    happening.

    Found by walking the altitude rather than solving for it: the altitude
    comes from the published sublunar point (see sublunar), so walking it is
    walking NASA's own numbers, and a horizon crossing to the nearest couple
    of minutes is finer than the approximation underneath it deserves.

    Returned unclamped when the Moon never sets -- a summer eclipse inside
    the Arctic circle is a real case and cutting the arc at an arbitrary
    hour would draw a moonset that does not happen.
    """
    c = contacts(key)
    if not c:
        return None
    lo = min(c.values()) - span_h
    hi = max(c.values()) + span_h
    steps = int((hi - lo) / (step_min / 60.0)) + 1
    ts = [lo + i * step_min / 60.0 for i in range(steps)]
    alts = [moon_alt(key, lat, lon, t) for t in ts]
    if not any(a > 0 for a in alts):
        return None
    # The stretch of sky-time that overlaps the eclipse, not merely the
    # longest one: over 32 hours there are two nights in here.
    ecl_lo, ecl_hi = min(c.values()), max(c.values())
    best = None
    start = None
    for i, a in enumerate(alts):
        if a > 0 and start is None:
            start = ts[i]
        elif a <= 0 and start is not None:
            if start <= ecl_hi and ts[i] >= ecl_lo:
                best = (start, ts[i])
                break
            start = None
    if best is None and start is not None:
        best = (start, ts[-1])
    return best


def peak_alt(key, lat, lon, steps=60):
    """The highest the Moon gets while it is up, in degrees, or None.

    What the night arc is drawn to. Not the altitude at greatest eclipse:
    the two are often far apart, and labelling a picture with a number it
    was not scaled to is worse than not labelling it.
    """
    window = up_window(key, lat, lon)
    if window is None:
        return None
    t0, t1 = window
    return max(moon_alt(key, lat, lon, t0 + (t1 - t0) * i / steps) or 0.0
               for i in range(steps + 1))
