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

# The umbra and penumbra at the Moon's distance, in Moon radii. Both vary a
# little with the Moon's distance and the Earth's; these are the means, and
# they are used only to draw the picture -- every number the page states
# comes from the catalogue instead.
UMBRA_R = 2.65
PENUMBRA_R = 4.60

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
    the point moves the way the sky does: the Moon's declination barely
    changes over the few hours an eclipse lasts, and the Earth turns 15
    degrees an hour under it. Nothing here needs the Moon's own motion,
    which is the whole reason this is trustworthy without an ephemeris.
    """
    el = elements(key)
    if not el:
        return None
    lon = el["zen_lon"] - 15.0 * (ut - greatest_ut(el))
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


def separation(key, ut):
    """Distance between the Moon's centre and the shadow's, in Moon radii.

    Reconstructed from the published umbral magnitude rather than from an
    orbit. Magnitude is the fraction of the Moon's diameter inside the
    umbra, so at greatest eclipse

        m = (R_umbra + 1 - s) / 2        (in Moon radii)

    which fixes s there. The Moon crosses in what is very nearly a straight
    line at a steady rate, and the published first contact fixes that rate:
    at U1 the two discs touch, so s = R_umbra + 1. Two knowns, one line.
    """
    el = elements(key)
    if not el:
        return None
    mid = greatest_ut(el)
    s_min = UMBRA_R + 1.0 - 2.0 * el["um_mag"]
    c = contacts(key)
    edge = c.get("U1") or c.get("P1")
    if edge is None:
        return None
    s_edge = (UMBRA_R + 1.0) if "U1" in c else (PENUMBRA_R + 1.0)
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
    if el is None or s is None:
        return None
    mid = greatest_ut(el)
    s_min = UMBRA_R + 1.0 - 2.0 * el["um_mag"]
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
    c = shadow_centre(key, ut)
    if c is None:
        return "sun"
    d = math.hypot(px - c[0], py - c[1])
    if d <= UMBRA_R:
        return "umbra"
    if d <= PENUMBRA_R:
        return "penumbra"
    return "sun"
