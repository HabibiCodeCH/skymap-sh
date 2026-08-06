"""Local circumstances of a solar eclipse, from Besselian elements.

Why this file exists at all, rather than the obvious approach: `sky.moon()`
is a seven-term series that returns GEOCENTRIC coordinates, and there is no
topocentric parallax correction anywhere in sky.py. Its error runs to about
12 arcmin, lunar parallax reaches 57 arcmin, and the Moon is 31 arcmin
across. Working an eclipse out from it would produce a confident number
wrong by more than the quantity being measured, and no test would notice.

Besselian elements sidestep that completely. They are not an ephemeris.
They are the geometry of the Moon's shadow cone, already solved by NASA
from VSOP87/ELP2000-82 and published per eclipse as about two dozen
polynomial coefficients. The Moon never enters this calculation, so the
weakness of our lunar series is not in the path.

Method: Meeus, *Astronomical Algorithms*, chapter 54. The fundamental plane
passes through the Earth's centre, perpendicular to the shadow axis. x and y
locate the axis on that plane, l1 and l2 are the radii of the penumbral and
umbral circles there, d and mu give the axis direction and the Greenwich
hour angle, and the observer is projected onto the same plane as (xi, eta).
The eclipse is then two circles on a plane, which is a problem with an exact
answer.

What this file will NOT do is invent elements for an eclipse it does not
have. `local()` raises rather than guessing, because the whole point of
going this route was to stop guessing.

Sun altitude and azimuth deliberately come from `sky.sun_altaz()` instead of
being derived here. Solar position is the one part of our ephemeris that is
reliable (no parallax problem worth the name), it is already tested, and
"where do I look" and "how much is covered" are better answered by the code
that is right for each.
"""
import math
from collections import namedtuple

# Meeus 54: the Earth's flattening, as the ratio of polar to equatorial
# radius. Used to put the observer on the spheroid rather than a sphere --
# worth about 20 km of position, which is a real fraction of a 294 km path.
_FLATTENING = 0.99664719
_EARTH_RADIUS_KM = 6378.14

Elements = namedtuple("Elements", (
    "name",      # what NASA calls it, for error messages and the page
    "t0",        # decimal hours TDT the polynomials are referred to
    "x", "y", "d", "l1", "l2", "mu",   # coefficient tuples, ascending powers
    "tanf1", "tanf2",
    "dT",        # TDT - UT, seconds, at this eclipse
))

# Transcribed from NASA/GSFC's published Besselian elements
# (eclipse.gsfc.nasa.gov, SEsearch/SEdata.php?Ecl=20260812), which are US
# government work and public domain, the same provenance as the decade
# tables eclipses.json already draws on.
#
# Deliberately one eclipse rather than all 44. Each set is hand-transcribed
# and the transcription is the part that can go silently wrong, so they get
# added when there is a reason to trust each one, not in bulk.
ELEMENTS = {
    "2026-08-12": Elements(
        name="Total solar eclipse",
        t0=18.0,
        x=(0.4755140, 0.5189249, -0.0000773, -0.0000080),
        y=(0.7711830, -0.2301680, -0.0001246, 0.0000038),
        d=(14.7966700, -0.0120650, -0.0000030),
        l1=(0.5379550, 0.0000939, -0.0000121),
        l2=(-0.0081420, 0.0000935, -0.0000121),
        mu=(88.747787, 15.003090, 0.000000),
        tanf1=0.0046141,
        tanf2=0.0045911,
        dT=75.4,
    ),
}


def _poly(c, t):
    """Horner, ascending powers. Meeus writes these as a0 + a1 t + a2 t^2..."""
    out = 0.0
    for coef in reversed(c):
        out = out * t + coef
    return out


def _dpoly(c, t):
    """d/dt of the same polynomial, per hour."""
    out = 0.0
    for i in range(len(c) - 1, 0, -1):
        out = out * t + i * c[i]
    return out


def _observer(lat, lon, height_m=0.0):
    """The observer's geocentric coordinates, rho*sin(phi') and rho*cos(phi').

    Longitude is east-positive here, matching every other coordinate in this
    repo. Meeus works in west-positive, which is why the sign flips when
    theta is formed in `_state` -- a sign error here moves the observer to
    the wrong side of the planet and is the single easiest way to get a
    plausible-looking wrong answer, so it is asserted in the tests.
    """
    phi = math.radians(lat)
    u = math.atan(_FLATTENING * math.tan(phi))
    h = height_m / (_EARTH_RADIUS_KM * 1000.0)
    return (_FLATTENING * math.sin(u) + h * math.sin(phi),
            math.cos(u) + h * math.cos(phi))


def _state(el, t, rho_sin, rho_cos, lon):
    """Everything Meeus 54 needs at one instant t (hours TDT from t0)."""
    x, y = _poly(el.x, t), _poly(el.y, t)
    d = math.radians(_poly(el.d, t))
    mu = math.radians(_poly(el.mu, t))
    l1, l2 = _poly(el.l1, t), _poly(el.l2, t)

    dx, dy = _dpoly(el.x, t), _dpoly(el.y, t)
    dd = math.radians(_dpoly(el.d, t))
    dmu = math.radians(_dpoly(el.mu, t))

    # East-positive longitude, so the observer's hour angle relative to the
    # shadow axis ADDS. (Meeus, west-positive, subtracts.)
    theta = mu + math.radians(lon)

    xi = rho_cos * math.sin(theta)
    eta = rho_sin * math.cos(d) - rho_cos * math.cos(theta) * math.sin(d)
    zeta = rho_sin * math.sin(d) + rho_cos * math.cos(theta) * math.cos(d)

    dxi = dmu * rho_cos * math.cos(theta)
    deta = dmu * xi * math.sin(d) - zeta * dd

    u, v = x - xi, y - eta
    a, b = dx - dxi, dy - deta
    n = math.hypot(a, b)

    # The shadow radii shrink with the observer's height above the
    # fundamental plane. zeta is that height, hence the correction.
    big_l1 = l1 - zeta * el.tanf1
    big_l2 = l2 - zeta * el.tanf2

    return dict(u=u, v=v, a=a, b=b, n=n, m=math.hypot(u, v),
                L1=big_l1, L2=big_l2, zeta=zeta)


def _obscuration(m, big_l1, big_l2):
    """Fraction of the Sun's DISC AREA covered, which is not the magnitude.

    Magnitude is a ratio of diameters and is what almanacs quote; obscuration
    is the area and is what the sky actually does. At magnitude 0.5 only
    about 39% of the Sun is covered, which is why a deep partial eclipse
    looks like so much less than half.

    In fundamental-plane units the Moon's radius is (L1-L2)/2 and the Sun's
    is (L1+L2)/2. Check it at the contacts: at first contact m = L1 = the
    sum of the two, and at the start of totality m = |L2| = the Moon's
    radius minus the Sun's, which is positive only when the Moon is the
    larger disc. Getting these the wrong way round makes a total eclipse
    report as 93% covered, which is how this was caught.
    """
    r_moon = (big_l1 - big_l2) / 2.0
    r_sun = (big_l1 + big_l2) / 2.0
    if r_sun <= 0:
        return 0.0
    if m >= r_sun + r_moon:
        return 0.0
    if m <= r_moon - r_sun:
        return 1.0                                    # total
    if m <= r_sun - r_moon:
        return (r_moon / r_sun) ** 2                  # annular
    # Two overlapping circles, the standard lens area.
    a1 = math.acos(max(-1.0, min(1.0,
                  (m * m + r_sun ** 2 - r_moon ** 2) / (2 * m * r_sun))))
    a2 = math.acos(max(-1.0, min(1.0,
                  (m * m + r_moon ** 2 - r_sun ** 2) / (2 * m * r_moon))))
    area = (r_sun ** 2 * (a1 - math.sin(a1) * math.cos(a1))
            + r_moon ** 2 * (a2 - math.sin(a2) * math.cos(a2)))
    return area / (math.pi * r_sun ** 2)


def _solve_max(el, rho_sin, rho_cos, lon, t=0.0, rounds=8):
    """Iterate to the instant of maximum eclipse for this observer."""
    for _ in range(rounds):
        s = _state(el, t, rho_sin, rho_cos, lon)
        if s["n"] == 0:
            break
        tau = -(s["u"] * s["a"] + s["v"] * s["b"]) / (s["n"] ** 2)
        t += tau
        if abs(tau) < 1e-9:
            break
    return t, _state(el, t, rho_sin, rho_cos, lon)


def _solve_contact(el, rho_sin, rho_cos, lon, t, sign, radius, rounds=12):
    """A contact time: when m equals the penumbral (or umbral) radius.

    sign -1 gives the earlier contact, +1 the later. `radius` picks which
    circle: "L1" for first/last contact, "L2" for the totality boundary.
    Returns None when the circles never reach each other, which is the
    ordinary case for the umbra almost everywhere on Earth.
    """
    for _ in range(rounds):
        s = _state(el, t, rho_sin, rho_cos, lon)
        big = abs(s[radius])
        if s["n"] == 0 or big == 0:
            return None
        sin_psi = (s["u"] * s["b"] - s["v"] * s["a"]) / (s["n"] * big)
        if abs(sin_psi) > 1:
            return None
        cos_psi = math.sqrt(1 - sin_psi * sin_psi)
        tau = (-(s["u"] * s["a"] + s["v"] * s["b"]) / (s["n"] ** 2)
               + sign * big * cos_psi / s["n"])
        t += tau
        if abs(tau) < 1e-9:
            break
    return t


def local(key, lat, lon, height_m=0.0):
    """What this eclipse does at one place on the ground.

    Returns times in decimal hours UT (TDT minus dT), a magnitude, an
    obscuration, and the kind of eclipse seen there. `None` for a time means
    that contact does not happen here.

    Nothing in here knows about the horizon: an eclipse can be in progress
    with the Sun below it, and saying so is the caller's job (see
    sky.sun_altaz). Keeping the two apart is deliberate -- the geometry is
    exact and the horizon question is local, and merging them would hide
    which half a wrong answer came from.
    """
    el = ELEMENTS.get(key)
    if el is None:
        raise KeyError(f"no Besselian elements for {key!r}; "
                       f"have {sorted(ELEMENTS)}")

    rho_sin, rho_cos = _observer(lat, lon, height_m)
    t_max, s = _solve_max(el, rho_sin, rho_cos, lon)

    to_ut = lambda t: None if t is None else el.t0 + t - el.dT / 3600.0

    if s["m"] >= s["L1"]:
        return dict(kind="none", name=el.name, magnitude=0.0, obscuration=0.0,
                    maximum=None, first=None, last=None,
                    central_start=None, central_end=None)

    magnitude = (s["L1"] - s["m"]) / (s["L1"] + s["L2"])
    obsc = _obscuration(s["m"], s["L1"], s["L2"])

    # L2 negative means the umbra reaches the ground: inside it the eclipse
    # is total. Positive means the shadow cone closes short of the surface,
    # so the Moon cannot cover the disc and it is annular.
    central = s["m"] < abs(s["L2"])
    kind = ("total" if central and s["L2"] < 0 else
            "annular" if central else "partial")

    c1 = _solve_contact(el, rho_sin, rho_cos, lon, t_max, -1, "L1")
    c4 = _solve_contact(el, rho_sin, rho_cos, lon, t_max, +1, "L1")
    c2 = c3 = None
    if central:
        c2 = _solve_contact(el, rho_sin, rho_cos, lon, t_max, -1, "L2")
        c3 = _solve_contact(el, rho_sin, rho_cos, lon, t_max, +1, "L2")

    return dict(kind=kind, name=el.name,
                magnitude=magnitude, obscuration=obsc,
                maximum=to_ut(t_max), first=to_ut(c1), last=to_ut(c4),
                central_start=to_ut(c2), central_end=to_ut(c3))


def duration_seconds(circ):
    """Seconds of totality or annularity, or None if neither happens here."""
    a, b = circ.get("central_start"), circ.get("central_end")
    if a is None or b is None:
        return None
    return (b - a) * 3600.0


def diameter_ratio(key, lat, lon, height_m=0.0):
    """The Moon's apparent diameter over the Sun's, at maximum, from here.

    Not the same number as `magnitude`, and the difference is a real trap.
    `magnitude` is Meeus's (L1-m)/(L1+L2), the fraction of the Sun's
    DIAMETER covered, which is what almanacs quote for a partial eclipse.
    This is the ratio of the two discs, which is what NASA prints as
    "Eclipse Magnitude" in an eclipse's header block. At the greatest
    eclipse of 2026 August 12 the first is 1.0174 and the second 1.0386,
    and neither is wrong.

    Worth having because it is the number that says how comfortably total
    an eclipse is, and because matching NASA's published value for it is
    what proved this file's geometry (see test_besselian.py).
    """
    el = ELEMENTS[key]
    rho_sin, rho_cos = _observer(lat, lon, height_m)
    _t, s = _solve_max(el, rho_sin, rho_cos, lon)
    r_moon = (s["L1"] - s["L2"]) / 2.0
    r_sun = (s["L1"] + s["L2"]) / 2.0
    return r_moon / r_sun if r_sun else 0.0


# Under this many seconds of totality, do not promise anyone anything.
#
# NASA computes path limits for the Moon's centre of mass on a smooth
# spheroid. The real edge moves by a few kilometres with the lunar limb
# profile -- valleys at the Moon's edge let sunlight through where a smooth
# disc would not -- and by more with the observer's altitude. Our own path
# width agrees with NASA's to about 2 km, which is well inside that.
#
# 2026 August 12 has a city sitting exactly here: Madrid computes as total
# by roughly fifteen seconds, and most published maps put it just outside.
# Both answers are inside the uncertainty. A page that says "Madrid: 15
# seconds of totality" would be indefensible, and one that says "just
# outside" equally so. Say it is on the edge and link a detailed map.
EDGE_SECONDS = 30.0


def on_the_edge(circ):
    """True when this place is too near the path limit to make a promise."""
    d = duration_seconds(circ)
    if d is not None:
        return d < EDGE_SECONDS
    # The other side of the same line: a partial eclipse this deep is a
    # near miss, not a comfortable "you are outside the path".
    return circ.get("obscuration", 0.0) > 0.999
