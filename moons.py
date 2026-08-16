#!/usr/bin/env python3
"""Where Jupiter's four big moons are, right now.

The one thing on this site that changes while you are looking at it. An
altitude moves a degree in four minutes and a rise time is fixed for the
night; Io swings a whole Jupiter radius in about three hours, and the
pattern is different every evening. Galileo watched it change over seven
nights in January 1610 and concluded the Earth was not the centre of
everything, so this is also the oldest observation on the site that anyone
can still repeat with their own binoculars.

Meeus, *Astronomical Algorithms*, chapter 44, low accuracy method. Good to
about 0.1 Jupiter radii, which is a tenth of what one character on the strip
below is worth, so the drawing runs out of resolution long before the
arithmetic does. No data file and no dependency: the whole theory is the
handful of sine terms below.

Positions come back in Jupiter radii, as seen from Earth:

    x   along the moons' orbital line, positive WEST
    y   towards or away from us, and only its sign is used here -- a moon
        with |x| < 1 is either crossing the disc or hidden behind it, and
        y says which

There is no elongation in degrees anywhere in this file on purpose. The
moons are drawn against the planet, not against the sky, and Jupiter's
apparent size changes by a factor of two over its orbit -- radii hold
still while arcseconds do not.
"""
import datetime as dt
import math

_S = lambda x: math.sin(math.radians(x))
_C = lambda x: math.cos(math.radians(x))

# Innermost first, which is the order they are always listed in and also
# the order of their periods: 1.8, 3.6, 7.2 and 16.7 days.
NAMES = ("Io", "Europa", "Ganymede", "Callisto")

# A dot and a short name. The dot is sized the way the charts size a star,
# but by the moon's real diameter rather than by brightness: Ganymede is
# 5,268 km across and Europa 3,122, and at this scale that is the only
# difference between them a reader could ever check.
#
# The name has to stay. Four dots alone leave somebody counting outwards
# from the planet to work out which is which, and they do not stay in
# order -- Callisto is inside Ganymede about as often as it is outside.
MARKS = ("Io", "Eu", "Gan", "Cal")

# Sized the way the charts size a star, but by the moon's real diameter
# rather than by brightness: Ganymede is 5,268 km across and Europa 3,122,
# and at this scale that is the only difference between the two that a
# reader could ever go and check.
DOTS = ("\u2022", "\u00b7", "\u2022", "\u2022")


def positions(when=None):
    """[(name, mark, x, y)] for the four moons, innermost first."""
    when = when or dt.datetime.utcnow()
    d = (when - dt.datetime(2000, 1, 1, 12)).total_seconds() / 86400.0
    V = 172.74 + 0.00111588 * d
    M = 357.529 + 0.9856003 * d
    N = 20.020 + 0.0830853 * d + 0.329 * _S(V)
    J = 66.115 + 0.9025179 * d - 0.329 * _S(V)
    A = 1.915 * _S(M) + 0.020 * _S(2 * M)
    B = 5.555 * _S(N) + 0.168 * _S(2 * N)
    K = J + A - B
    R = 1.00014 - 0.01671 * _C(M) - 0.00014 * _C(2 * M)
    r = 5.20872 - 0.25208 * _C(N) - 0.00611 * _C(2 * N)
    D = math.sqrt(r * r + R * R - 2 * r * R * _C(K))
    psi = math.degrees(math.asin(R / D * _S(K)))
    lam = 34.35 + 0.083091 * d + 0.329 * _S(V) + B
    DS = 3.12 * _S(lam + 42.8)
    DE = DS - 2.22 * _S(psi) * _C(lam + 22) - 1.30 * (r - D) / D * _S(lam - 100.5)
    # Light takes about 43 minutes to cross from Jupiter to here at mean
    # opposition distance, and Io moves a visible amount in that time.
    t = d - D / 173.0
    G = 331.18 + 50.310482 * t
    H = 87.40 - 21.569231 * t
    u = [163.8067 + 203.4058643 * t + psi - B,
         358.4108 + 101.2916334 * t + psi - B,
         5.7129 + 50.2345179 * t + psi - B,
         224.8151 + 21.4879801 * t + psi - B]
    # The three inner moons are locked 1:2:4, so each one's own position
    # depends on where the next one out is.
    u[0] += 0.473 * _S(2 * (u[0] - u[1]))
    u[1] += 1.065 * _S(2 * (u[1] - u[2]))
    u[2] += 0.165 * _S(G)
    u[3] += 0.843 * _S(H)
    rad = [5.9057 - 0.0244 * _C(2 * (u[0] - u[1])),
           9.3966 - 0.0882 * _C(2 * (u[1] - u[2])),
           14.9883 - 0.0216 * _C(G),
           26.3627 - 0.1939 * _C(H)]
    return [(n, m, dot, ri * _S(ui), ri * _C(ui) * _S(DE))
            for n, m, dot, ri, ui in zip(NAMES, MARKS, DOTS, rad, u)]


# Callisto reaches 26.6 radii at greatest elongation, so the strip has to be
# 54 wide to hold it. It was 30, which fits Ganymede and throws Callisto off
# the end for most of its 16.7-day orbit -- the moon that moves least was
# the one missing most often.
SPAN = 54.0


def strip(cols=57, when=None):
    """(names, dots, middle, hidden) -- two rows, name above dot.

    Side by side they crowd. "•Gan •Cal ·Eu" is three bodies and three
    words inside eleven characters and leaves the eye to do the pairing;
    stacked, each name sits over the thing it names.

    The planet's own cell is left blank on both rows so the caller can drop
    the chart's planet glyph in and colour it. This module knows about
    orbits and not about ANSI.

    A moon within one radius of the middle is crossing the disc or hidden
    behind it, and writing it there would claim a position the reader
    cannot check. Those come back to be named in words instead.
    """
    names = [" "] * cols
    dots = [" "] * cols
    mid = cols // 2
    hidden, want = [], []
    for name, mark, dot, x, y in positions(when):
        if abs(x) < 1.0:
            hidden.append((name, "in front of" if y < 0 else "behind"))
            continue
        want.append((mid + int(round(x / SPAN * (cols - 1))), mark, dot))
    # Nearest the planet first, so a moon close in keeps the place it earned
    # and one further out gives way. The alternative reads as a moon sitting
    # where it is not.
    for centre, mark, dot in sorted(want, key=lambda t: abs(t[0] - mid)):
        if not 0 <= centre < cols or centre == mid or dots[centre] != " ":
            continue
        dots[centre] = dot
        # The name is centred over its own dot and moved aside only far
        # enough to clear a neighbour, with a blank between: two names
        # touching read as one word.
        a = max(0, min(cols - len(mark), centre - len(mark) // 2))
        while any(names[i] != " " for i in range(max(0, a - 1),
                                                 min(cols, a + len(mark) + 1))) \
                or a - 1 <= mid < a + len(mark) + 1:
            a += 1 if centre >= mid else -1
            if a < 0 or a + len(mark) > cols:
                a = None
                break
        if a is not None:
            names[a:a + len(mark)] = list(mark)
    return "".join(names).rstrip(), "".join(dots).rstrip(), mid, hidden
