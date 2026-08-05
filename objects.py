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
import math

import sky

D = math.pi / 180


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
