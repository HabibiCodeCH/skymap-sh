#!/usr/bin/env python3
"""Builds eclipsemap.json: a land mask for the region an eclipse crosses.

Same polygons and the same point-in-ring test as build_worldmap.py, which
this imports rather than copies. The difference is the extent: worldmap.json
is the whole planet at 216x55 for the /stats heat map, and at 1.7 degrees per
column a 300 km eclipse track is thinner than one character. A page about
where the shadow lands needs to be zoomed in.

    curl -sSLO https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json
    python3 build_eclipsemap.py

The region is per eclipse, because the next one crosses somewhere else
entirely, and it is read off the eclipse itself rather than chosen by hand.
eclipse.track() walks the shadow axis and says where the centre of the
shadow lands minute by minute. Twenty-two eclipses is twenty-two windows,
and hand-picking them would have been twenty-two chances to put Spain off
the edge of its own map.

The window is a fixed size on the ground rather than the box the whole track
needs. A real track runs right round the daylit half of the planet, 150
degrees of longitude and more; a map wide enough to hold all of it is a map
where a 250 km path is thinner than one character, which is the same reason
the /stats world map cannot be used here. So it zooms: 5,200 km across, 96
columns, about 60 km per column, centred on the part of the track that
crosses land. The prose names the regions the map does not reach.

Choosing the height is not free-form. A character cell is about twice as
tall as it is wide, and a degree of longitude shrinks with the cosine of the
latitude, so the two have to be picked together or the track comes out
sheared. 44 rows at this width is a cell about as tall on the ground as it
is wide.

Near the pole none of this means anything -- longitude collapses, and a
lat/lon rectangle holding the polar leg would squeeze the whole of Europe
into the bottom few rows. Track points above 78 degrees are left out of the
centring, and an eclipse whose whole track is up there gets no map at all
rather than a misleading one. The page says which regions it crosses either
way.
"""
import json
import math
import sys

import build_worldmap as wm
import besselian
import eclipse

OUT = "eclipsemap.json"

WIDTH, HEIGHT = 96, 44     # columns the page's live column fits, and rows
WIDTH_KM = 5200.0          # how much ground the map covers left to right
POLAR_LIMIT = 78.0         # degrees; above this a lat/lon box is a lie
CELL_ASPECT = 2.0          # a character is twice as tall as it is wide
MAX_LON_SPAN = 150.0       # degrees, for tracks near the pole
LAT_LIMIT = 88.0

# The window this eclipse gets, when the rule below would pick a worse one.
# 2026 August 12 is the one people are reading this week: the automatic
# window clips southern Spain and the Balearics, which is exactly where the
# edge of the path runs and the only part of Europe where the answer is
# interesting. Reviewed and kept as it is.
OVERRIDES = {
    "2026-08-12": (75.0, 30.0, -45.0, 25.0, 96, 50),
}


def _unwrapped(points):
    """Longitudes made continuous, so a track over the date line is one run
    of numbers rather than two clumps at opposite ends of the world."""
    out = []
    prev = None
    for lat, lon, _t in points:
        if prev is not None:
            while lon - prev > 180:
                lon -= 360
            while prev - lon > 180:
                lon += 360
        prev = lon
        out.append((lat, lon))
    return out


def region_for(key, polys=None):
    """(lat_top, lat_bot, lon_left, lon_right, width, height), or None when
    the track never comes far enough from the pole to draw.

    The window is a fixed size on the ground -- about 5,200 km across, 60 km
    per column -- rather than whatever the track needs. A real track runs
    right round the daylit half of the planet, 150 degrees of longitude and
    more, and a map wide enough to hold all of it is a map where a 250 km
    path is thinner than one character. So this zooms, and the prose names
    the regions the map does not reach.

    Centred on the part of the track that crosses land, because that is the
    part somebody could stand on. Sea-only tracks fall back to their own
    midpoint.
    """
    if key in OVERRIDES:
        return OVERRIDES[key]
    pts = [p for p in _unwrapped(eclipse.track(key, step_minutes=0.5))
           if abs(p[0]) <= POLAR_LIMIT]
    if len(pts) < 4:
        return None
    on_land = [p for p in pts if polys and wm.is_land(p[1], p[0], polys)]
    use = on_land or pts
    lat_c = (min(p[0] for p in use) + max(p[0] for p in use)) / 2
    lon_c = (min(p[1] for p in use) + max(p[1] for p in use)) / 2

    lat_span = CELL_ASPECT * HEIGHT * WIDTH_KM / WIDTH / 111.2
    cos_c = max(0.05, math.cos(math.radians(lat_c)))
    lon_span = min(MAX_LON_SPAN, WIDTH_KM / (111.2 * cos_c))
    # Slide, never shrink, when the window runs off the top or bottom of the
    # world: a shorter map would be a different scale from every other one.
    lat_top = min(LAT_LIMIT, lat_c + lat_span / 2)
    lat_bot = max(-LAT_LIMIT, lat_top - lat_span)
    lat_top = min(LAT_LIMIT, lat_bot + lat_span)
    # Longitude stays continuous rather than being cut at the date line:
    # lon_right may run past 180, and eclipse.cell_of knows to look for a
    # place there. The left edge is normalised so the numbers stay readable.
    lon_left = ((lon_c - lon_span / 2 + 180) % 360) - 180
    return (round(lat_top, 2), round(lat_bot, 2), round(lon_left, 2),
            round(lon_left + lon_span, 2), WIDTH, HEIGHT)


def build(key, region, polys):
    lat_top, lat_bot, lon_left, lon_right, width, height = region
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
                width=width, height=height, rows=rows), dots


def main():
    try:
        open(wm.SRC).close()
    except OSError:
        print(f"missing {wm.SRC} -- see the docstring for the curl line")
        return 1
    polys = wm.load_polygons(wm.SRC)
    out, skipped = {}, []
    for key in sorted(besselian.ELEMENTS):
        region = region_for(key, polys)
        if region is None:
            # A partial eclipse, whose axis misses the Earth entirely, or one
            # that only ever crosses the polar cap. Neither has a track to
            # draw, and eclipse.has_map() returning False is what the page
            # already handles.
            skipped.append(key)
            continue
        d, dots = build(key, region, polys)
        out[key] = d
        print(f"{key}: {d['width']}x{d['height']} "
              f"lat {d['lat_bot']:.0f}..{d['lat_top']:.0f} "
              f"lon {d['lon_left']:.0f}..{d['lon_right']:.0f}  "
              f"{dots:,} land cells "
              f"({100 * dots / (d['width'] * d['height']):.0f}%)")
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"\n{OUT}: {len(out)} maps from {len(polys)} polygons")
    for key in skipped:
        print(f"  no map for {key}: no track outside the polar cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
