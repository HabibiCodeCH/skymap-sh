#!/usr/bin/env python3
"""
Build worldmap.json -- the dotted world map /stats draws request locations on.

Source: countries.geo.json from johan/world.geo.json (public domain), the same
file NTag's dotted-map uses. Not committed; fetch it first:

    curl -sSLO https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json
    python3 build_worldmap.py

Why precompute. The polygons are 257 KB and testing 23,680 grid points against
292 rings takes half a second -- fine once, not on every /stats request. The
output is a flat land/sea mask, so the server only has to index into it.

An earlier attempt derived the mask from cities.json instead, on the theory
that cities outline the continents. They do, roughly, but the gaps between
them had to be closed by dilation, and any dilation wide enough to fill the
Sahara also welds Indonesia to Asia and seals the Mediterranean and the Gulf
of Mexico. Real coastlines have none of those problems.

Latitude is clipped to 83N..56S. The poles are ice and empty ocean, so cutting
them lets the same number of rows cover the inhabited world at better
resolution -- and Antarctica sends no requests.

Output:

  {"width": 296, "height": 80, "lat_top": 83.0, "lat_bot": -56.0,
   "rows": ["   ##   ...", ...]}    # one string per row, '#' is land
"""
import json
import sys

SRC, OUT = "countries.geo.json", "worldmap.json"
# Height follows from the aspect: a terminal cell is about twice as tall as
# it is wide, so a geographically honest map needs roughly a quarter as many
# rows as columns. Going much below this closes the Mediterranean and the
# Gulf of Mexico back up, which is the whole reason the mask comes from real
# coastlines rather than city positions.
WIDTH, HEIGHT = 185, 47
LAT_TOP, LAT_BOT = 83.0, -56.0
LAND, SEA = "#", " "


def load_polygons(path):
    """Flatten the FeatureCollection to (bbox, rings) so a bounding-box
    reject skips most polygons before any ray casting happens."""
    with open(path) as f:
        geo = json.load(f)
    polys = []
    for feat in geo["features"]:
        g = feat["geometry"]
        chunks = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in chunks:
            rings = [[(float(x), float(y)) for x, y in ring] for ring in poly]
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            polys.append(((min(xs), min(ys), max(xs), max(ys)), rings))
    return polys


def in_ring(x, y, ring):
    """Ray casting. Counts how many edges a ray to the right crosses."""
    inside, n = False, len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def is_land(lon, lat, polys):
    for (minx, miny, maxx, maxy), rings in polys:
        if lon < minx or lon > maxx or lat < miny or lat > maxy:
            continue
        # Rings after the first are holes -- the Caspian inside Kazakhstan,
        # Lesotho inside South Africa.
        if in_ring(lon, lat, rings[0]) and not any(in_ring(lon, lat, h)
                                                   for h in rings[1:]):
            return True
    return False


def main():
    try:
        polys = load_polygons(SRC)
    except OSError:
        print(f"missing {SRC} -- see the docstring for the curl line")
        return 1
    rows, dots = [], 0
    span = LAT_TOP - LAT_BOT
    for r in range(HEIGHT):
        lat = LAT_TOP - (r + 0.5) * span / HEIGHT
        row = []
        for c in range(WIDTH):
            # Sample cell centres, not corners: a corner on a coastline is
            # ambiguous and makes the shoreline jitter by a dot.
            lon = -180 + (c + 0.5) * 360 / WIDTH
            land = is_land(lon, lat, polys)
            dots += land
            row.append(LAND if land else SEA)
        rows.append("".join(row))
    with open(OUT, "w") as f:
        json.dump(dict(width=WIDTH, height=HEIGHT, lat_top=LAT_TOP,
                       lat_bot=LAT_BOT, rows=rows), f)
    print(f"{OUT}: {WIDTH}x{HEIGHT}, {dots:,} land dots "
          f"({100 * dots / (WIDTH * HEIGHT):.0f}%) from {len(polys)} polygons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
