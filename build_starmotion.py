#!/usr/bin/env python3
"""Builds stars_motion.json: how the stars in our asterisms are moving.

    python3 build_starmotion.py

Everything here is already in the repo. bsc5.dat carries an annual proper
motion and a heliocentric radial velocity for essentially every star it
lists, and starinfo.json carries a Hipparcos distance. Together that is a
position and a velocity in three dimensions, which is all a constellation's
shape needs to be run forwards or backwards.

Only the stars our own asterisms.json actually draws with -- 130 of them --
because that is the only place a shape exists to deform. A full-sky version
would be four megabytes of stars nobody has connected with a line.

Two decisions worth knowing about.

**The distance comes from Hipparcos, not from BSC5's own parallax column.**
LICENSES.md already records why that column is ignored everywhere else here:
it is pre-Hipparcos and some of it is simply wrong. Alioth is the
demonstration -- BSC5 puts it at 111 parsecs and Hipparcos at 24.8. Coverage
is better too, 129 of our 130 against 120.

**BSC5's proper motion in right ascension already has cos(dec) applied.** It
is the one convention question that would quietly tilt every high-declination
star, and it is settled by measurement rather than by reading: 61 Cygni A
reads 4.136 here against a published 4.165 arcsec/yr, and Groombridge 1830
reads 4.003 and -5.813 against a published 4.004 and -5.813. Seconds of time
per year would have put 61 Cygni at 0.379. test_motion.py keeps that pinned.

Source: Yale Bright Star Catalogue 5th ed. (already shipped as bsc5.dat) and
the Hipparcos distances already in starinfo.json. Both public domain, same
provenance as stars.json.
"""
import json
import sys

import sky

BSC = "bsc5.dat"
OUT = "stars_motion.json"
LY_PER_PC = 3.261564


def column(row, a, b):
    s = row[a:b].strip()
    return float(s) if s else None


def read_bsc():
    """HR -> proper motion and radial velocity, by column position."""
    out = {}
    with open(BSC, encoding="latin-1") as f:
        for row in f:
            if not row[:4].strip():
                continue
            out[int(row[:4])] = {
                "pmra": column(row, 148, 154),   # arcsec/yr, cos(dec) applied
                "pmde": column(row, 154, 160),   # arcsec/yr
                "rv": column(row, 166, 170),     # km/s, positive receding
            }
    return out


def main():
    bsc = read_bsc()
    info = sky._load("starinfo.json")
    wanted = sorted({hr for a in sky._load("asterisms.json")
                     for poly in a["lines"] for hr in poly})

    out, no_distance, no_motion = {}, [], []
    for hr in wanted:
        m = bsc.get(hr)
        if not m or m["pmra"] is None or m["pmde"] is None:
            no_motion.append(hr)
            continue
        row = {"pmra": m["pmra"], "pmde": m["pmde"], "rv": m["rv"] or 0.0}
        ly = (info.get(str(hr)) or {}).get("ly")
        if ly:
            # Rounded to a tenth of a parsec. The distances themselves carry
            # a percent or two of error, and this file is read on every page
            # view of an asterism.
            row["d"] = round(ly / LY_PER_PC, 1)
        else:
            no_distance.append(hr)
        out[str(hr)] = row

    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)

    print(f"{OUT}: {len(out)} stars")
    if no_distance:
        print(f"  no Hipparcos distance ({len(no_distance)}): {no_distance}")
        print("  these fall back to flat angular extrapolation -- see motion.at")
    if no_motion:
        print(f"  NO PROPER MOTION ({len(no_motion)}): {no_motion}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
