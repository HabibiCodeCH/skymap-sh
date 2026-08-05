#!/usr/bin/env python3
"""
Build milkyway.json -- the density grid the Milky Way is drawn from.

Source: mw.json from d3-celestial (Olaf Frohn), BSD-3-Clause, derived from
the Milky Way Outline Catalog (Jose R. Vieira). Not committed; fetch it:

    curl -sSLO https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/mw.json
    python3 build_milkyway.py

Five nested contours, ol1 (faintest) to ol5 (the bright core), 15,337 points
between them. That maps onto a five-step density ramp almost too neatly.

Why a grid and not the polygons. Drawing asks the opposite question to the
one polygons answer: not "what shape is this contour" but "how bright is the
sky at this point", once per character cell, thousands of times per render.
Testing each cell against thousands of edges is the wrong way round. Baked
to a grid, the renderer does an array lookup and the topology below stops
being anyone else's problem. Same reasoning as build_worldmap.py.

Why a meridian ray and not a scanline fill. ol1's outer and inner rings each
encircle the sky -- their RA travel comes to exactly -360, because the Milky
Way is a closed band and its edges have to come back round. A horizontal
scanline has no "outside" to start counting parity from on a row the band
crosses everywhere. Counting crossings along a meridian to the pole does:
the pole is unambiguously outside every contour, and a ring that wraps in RA
is no longer a special case.

Coordinates come in as RA in -180..180 degrees; they go out as RA hours to
match stars.json, which is what sky.py's altaz() expects. J2000, like the
star catalogue, so the same precess() applies to both.

Output:

  {"ra_step": 0.5, "dec_step": 0.5, "cols": 720, "rows": 360,
   "rows_data": ["000012321000...", ...]}   # '0' empty .. '5' brightest,
                                            # row 0 is dec +90, col 0 is RA 0h
"""
import json
import sys

SRC, OUT = "mw.json", "milkyway.json"

# Half a degree. The widest chart is 220 columns over 360 degrees of azimuth,
# so a character cell is never finer than 1.6 degrees and this is comfortably
# under it; the 3D view can sample harder but the Milky Way has no edges
# sharp enough to reward it. Costs 259,200 cells, which gzip flattens to a
# few tens of KB because the sky is mostly empty and runs are long.
STEP = 0.5

LEVELS = ["ol1", "ol2", "ol3", "ol4", "ol5"]


def rings_of(feature):
    """Every ring in a MultiPolygon, flat. The nesting carries no information
    here -- holes and shells are told apart by the crossing count, not by
    which list they arrived in."""
    out = []
    geom = feature["geometry"]
    polys = geom["coordinates"]
    if geom["type"] == "Polygon":
        polys = [polys]
    for poly in polys:
        for ring in poly:
            if len(ring) >= 4:
                out.append(ring)
    return out


def crossings_by_column(rings, cols, step):
    """For each RA column, the declinations at which the boundary crosses
    that meridian.

    An edge is walked in the shortest direction round the sky, so a segment
    that steps across RA 0 is one crossing rather than a jump across the
    entire sky. Every column a segment spans gets the interpolated dec.
    """
    per_col = [[] for _ in range(cols)]
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            dx = x2 - x1
            if dx > 180:
                dx -= 360
            elif dx < -180:
                dx += 360
            if dx == 0:
                continue
            # Column indices this segment passes over, in the direction it
            # actually travels.
            a, b = x1, x1 + dx
            lo, hi = (a, b) if a < b else (b, a)
            c0 = int((lo % 360) / step)
            n = int((hi - lo) / step) + 2
            for k in range(n):
                col = (c0 + k) % cols
                # The middle of the column, matching how the row picks the
                # middle of its declination band -- sampling the edge
                # instead put column 360 exactly on RA 180, which is where
                # the source cuts its rings and leaves vertices sitting
                # precisely on the meridian being tested. A ray through a
                # vertex counts once instead of twice or not at all, and
                # that column's parity is wrong from there to the pole.
                mer = (col + 0.5) * step
                while mer < lo:
                    mer += 360
                while mer > hi:
                    mer -= 360
                if not (lo <= mer <= hi):
                    continue
                # Half-open on the lower side whichever way the edge runs.
                # Testing 0 <= t < 1 instead is half-open at the start going
                # east and at the end going west, so a vertex where the
                # boundary turns round in RA gets counted twice or not at
                # all -- and one missed crossing inverts that column's
                # parity all the way to the pole, which draws as a stripe
                # down the sky.
                if (a <= mer) == (b <= mer):
                    continue
                per_col[col].append(y1 + (y2 - y1) * (mer - a) / dx)
    return per_col


def level_mask(feature, cols, rows, step):
    """A bytearray of 0/1 per cell: is this point inside this contour.

    Inside means an odd number of boundary crossings on the way to the north
    celestial pole, which is outside everything.
    """
    per_col = crossings_by_column(rings_of(feature), cols, step)
    mask = bytearray(cols * rows)
    for col in range(cols):
        ys = sorted(per_col[col], reverse=True)      # north first
        if not ys:
            continue
        # Walking south, each crossing passed flips inside/outside. One sweep
        # per column rather than a count per cell, which is the difference
        # between a second and several minutes over 259,200 of them.
        i, inside = 0, False
        for row in range(rows):
            dec = 90.0 - (row + 0.5) * step
            while i < len(ys) and ys[i] > dec:
                inside = not inside
                i += 1
            if inside:
                mask[row * cols + col] = 1
    return mask


def main():
    try:
        data = json.load(open(SRC))
    except FileNotFoundError:
        sys.exit(f"{SRC} not found -- see the docstring for the curl line")

    cols = int(360 / STEP)
    rows = int(180 / STEP)
    by_id = {f.get("id"): f for f in data["features"]}
    missing = [k for k in LEVELS if k not in by_id]
    if missing:
        sys.exit(f"{SRC} is missing {missing}; expected {LEVELS}")

    density = bytearray(cols * rows)
    for depth, key in enumerate(LEVELS, start=1):
        mask = level_mask(by_id[key], cols, rows, STEP)
        for i, v in enumerate(mask):
            if v and density[i] < depth:
                density[i] = depth
        print(f"  {key}: {sum(mask):>7,} cells", file=sys.stderr)

    # Column 0 is already RA 0h: crossings_by_column indexes on x % 360, so
    # the source's -180..180 was folded into 0..360 on the way in. Rotating
    # again here put the galactic centre half a sky from where it belongs.
    rows_data = ["".join(chr(48 + v)
                         for v in density[row * cols:(row + 1) * cols])
                 for row in range(rows)]

    out = dict(ra_step=STEP, dec_step=STEP, cols=cols, rows=rows,
               rows_data=rows_data)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    filled = sum(1 for row in rows_data for c in row if c != "0")
    print(f"  {OUT}: {cols}x{rows}, {filled:,} lit cells "
          f"({100*filled/(cols*rows):.1f}% of sky)", file=sys.stderr)


if __name__ == "__main__":
    main()
