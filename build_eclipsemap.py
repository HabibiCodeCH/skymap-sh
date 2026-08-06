#!/usr/bin/env python3
"""Builds eclipsemap.json: a land mask for the region an eclipse crosses.

Same polygons and the same point-in-ring test as build_worldmap.py, which
this imports rather than copies. The difference is the extent: worldmap.json
is the whole planet at 216x55 for the /stats heat map, and at 1.7 degrees per
column a 300 km eclipse track is thinner than one character. A page about
where the shadow lands needs to be zoomed in.

    curl -sSLO https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json
    python3 build_eclipsemap.py

The region is per eclipse and recorded in the file, because the next one
will cross somewhere else entirely. REGIONS below is keyed by the same date
string besselian.ELEMENTS uses, so a new eclipse means an entry here and a
regenerate, not new code.

Choosing the size is not free-form. A character cell is about twice as tall
as it is wide, and a degree of longitude shrinks with the cosine of the
latitude, so the two have to be picked together or the map comes out
visibly squashed. For 2026 August 12: 96 columns over 70 degrees of
longitude is about 50 km per column at 52N, and 50 rows over 45 degrees of
latitude is about 50 km per row once the cell's shape is taken into account.
Equal, which is what makes the track look like the shape it really is.
"""
import json
import sys

import build_worldmap as wm

OUT = "eclipsemap.json"

# date -> (lat_top, lat_bot, lon_left, lon_right, width, height)
#
# 2026 August 12 runs from Siberia across the pole to Greenland, Iceland and
# northern Spain. This window deliberately drops the polar leg: near the
# pole a lat/lon rectangle stops meaning anything, longitude collapses to
# nothing, and the whole of Europe would be squeezed into the bottom few
# rows. The page says the track starts over the Arctic rather than pretending
# this is all of it.
REGIONS = {
    "2026-08-12": (75.0, 30.0, -45.0, 25.0, 96, 50),
}


def build(key):
    lat_top, lat_bot, lon_left, lon_right, width, height = REGIONS[key]
    polys = wm.load_polygons(wm.SRC)
    rows, dots = [], 0
    for r in range(height):
        lat = lat_top - (r + 0.5) * (lat_top - lat_bot) / height
        line = []
        for c in range(width):
            lon = lon_left + (c + 0.5) * (lon_right - lon_left) / width
            land = wm.is_land(lon, lat, polys)
            dots += land
            line.append("#" if land else " ")
        rows.append("".join(line))
    return dict(key=key, lat_top=lat_top, lat_bot=lat_bot,
                lon_left=lon_left, lon_right=lon_right,
                width=width, height=height, rows=rows), dots, len(polys)


def main():
    try:
        open(wm.SRC).close()
    except OSError:
        print(f"missing {wm.SRC} -- see the docstring for the curl line")
        return 1
    out = {}
    for key in REGIONS:
        d, dots, npoly = build(key)
        out[key] = d
        print(f"{key}: {d['width']}x{d['height']}, {dots:,} land cells "
              f"({100 * dots / (d['width'] * d['height']):.0f}%) "
              f"from {npoly} polygons")
    with open(OUT, "w") as f:
        json.dump(out, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
