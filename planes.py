#!/usr/bin/env python3
"""Live aircraft overhead, as azimuth and elevation.

An aircraft is the same problem as a planet with different inputs: something
at a known position that has to come out as "how high, and which way". The
output is the pair every other object on this site is already described by,
so nothing downstream has to learn a new shape.

Two upstreams, and they are not the same kind of thing:

  position   adsb.lol, a community ADS-B aggregator. Stale in seconds, so it
             is cached for seconds. ODbL 1.0 -- attribution is required
             wherever the data is shown, and republishing a *database* built
             from it would make that database ODbL too. Nothing here stores
             anything past the micro-cache, which is deliberate.

  route      adsbdb.com, open source and free. ADS-B does not broadcast where
             a flight is going; the aircraft transmits a callsign and the
             route is a separate lookup fused in afterwards. Stable for hours,
             so it is cached for hours.

adsb.lol has a route endpoint of its own (POST /api/0/routeset). As of
2026-08-10 it answers 201 with an empty body for every callsign tried, while
/api/0/airport on the same namespace works -- so it is that service, not us.
ROUTE_URL is here so switching back is a config change.

The route is an inference, never a fact. Callsign-to-route mappings fail on
charters, ferry legs, general aviation and anything military, and a confident
wrong answer to somebody standing outside looking up is worse than no answer:
they cannot check it, and they will remember being told. Callers must render
it as "likely X to Y" or not at all -- see route_confident().
"""
import json
import math
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "skymap.sh/1.0 (+https://skymap.sh; contact: enquiries@habibicode.org)"

# Every aggregator in this family (airplanes.live, adsb.one, adsb.fi) speaks
# the same v2 response, so switching is a base URL and nothing else. Worth
# having from the first version rather than after the first outage.
BASE_URL = os.environ.get("SKY_ADSB_URL", "https://api.adsb.lol")
ROUTE_URL = os.environ.get("SKY_ROUTE_URL", "https://api.adsbdb.com")

# 35 nautical miles, not the 250 the endpoint allows. A plane at cruise is
# 45 degrees up at 11 km out and 10 degrees up at 62 km; past that it is a
# dot on the horizon, which is not what "overhead" promises. A wider radius
# costs upstream payload to fetch objects the floor below throws away.
RADIUS_NM = 35

# How far ahead to dead-reckon, purely so the icon knows which way to point.
# A minute is long enough that the shift is unambiguous at 60 km and short
# enough that a cruising aircraft is still flying the same straight line.
LOOKAHEAD_S = 60

# ODbL 1.0 is share-alike at the database level, and attribution is required
# on any surface that shows the data. Serving live query results is not what
# triggers the share-alike clause -- storing and republishing a derived
# database is -- which is the reason nothing here persists past a cache
# measured in seconds. adsbdb is MIT and asks for no credit; it is named
# anyway, because a route is the part a reader is most likely to doubt and
# saying where it came from is how they check it.
ATTRIBUTION = "Aircraft: adsb.lol (ODbL 1.0) · routes: adsbdb.com"

# The floor is the whole promise: somebody looks up and there is a plane
# where the chart said. Measured over Geneva on a weekday evening, 15 degrees
# left 2 aircraft of 13 and 10 left 8 -- and Geneva is dense airspace, so
# anywhere quieter at 15 would usually show nothing at all. Ten is the number
# that keeps the feature from reading as broken. Config, not constant: it
# wants tuning against real usage, which is Phase 3.
FLOOR_DEG = float(os.environ.get("SKY_PLANE_FLOOR", "10"))

# Same 0.1 degree grid the response cache already rounds to (~11 km), so two
# people in the same city share one upstream call. At scale the constraint is
# concurrent distinct tiles, not total requests: one tile costs at most 240
# calls an hour however many people are watching it.
TILE = 0.1
POS_TTL = 15        # seconds. A plane at 900 km/h moves 3.75 km in that.
ROUTE_TTL = 6 * 3600

TIMEOUT = 6         # position: the day view waits on this, so it is short
ROUTE_TIMEOUT = 3
ROUTE_WORKERS = 6

M_PER_FT = 0.3048
KM_PER_NM = 1.852
R_EARTH_KM = 6371.0

_pos_cache = {}     # tile -> (expires, planes, error)
_route_cache = {}   # callsign -> (expires, route or None)

# Reported separately from the sky cache on purpose. This one is *meant* to
# miss: a 15-second entry against traffic of a few requests an hour will
# almost never be warm, and folding that into the site-wide hit rate would
# drag a meaningful number down to a meaningless one. Routes go the other
# way -- a 6-hour entry on a callsign hits nearly always -- so they are
# counted apart from position too, or the two would cancel out and the
# average would describe neither.
stats = {"pos_hit": 0, "pos_miss": 0, "pos_error": 0,
         "route_hit": 0, "route_miss": 0, "route_error": 0}


def _tile(lat, lon):
    """The grid cell a position falls in. Rounding, not truncation, so the
    cell is centred on the query rather than hanging south-west of it."""
    return (round(lat / TILE) * TILE, round(lon / TILE) * TILE)


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def bearing(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing, degrees clockwise from true north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def ground_km(lat1, lon1, lat2, lon2):
    """Great-circle distance along the ground, kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def project(lat, lon, brg_deg, dist_km):
    """Where a great-circle course from here ends up, as (lat, lon)."""
    d = dist_km / R_EARTH_KM
    p1, l1, b = math.radians(lat), math.radians(lon), math.radians(brg_deg)
    sp = math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b)
    sp = max(-1.0, min(1.0, sp))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * sp)
    return math.degrees(math.asin(sp)), (math.degrees(l2) + 540) % 360 - 180


def elevation(alt_km, dist_km):
    """How high above the horizon something at that altitude and ground
    distance appears, in degrees.

    The curvature term is the Earth falling away underneath: about 330 m at
    65 km, against a cruise altitude of 11 km. It moves the answer by ~0.3
    degrees at the far edge, which is under one row of the horizon chart --
    but it is one line, it always has the same sign, and the alternative is a
    number that is quietly optimistic exactly where the floor cares most.

    Refraction is not modelled. It bends the light by about 0.1 degrees at
    ten degrees up, below both this chart's resolution and the honesty of a
    position that was itself broadcast a second or two ago.
    """
    if dist_km <= 0:
        return 90.0
    drop_km = dist_km * dist_km / (2 * R_EARTH_KM)
    return math.degrees(math.atan2(alt_km - drop_km, dist_km))


def _altitude_ft(ac):
    """(feet, which field it came from), or (None, None) if unusable.

    alt_geom is height above the ellipsoid and alt_baro is a pressure
    reading, and the two disagree by a couple of thousand feet in ordinary
    conditions -- so geometric first, always. It is absent on about one
    aircraft in seven (13 of 15, measured over Geneva), which is what the
    fallback is for.

    alt_baro is the string "ground" for anything not airborne. That is not a
    missing value and not a zero: it is an aircraft on a taxiway, which
    belongs on no sky chart. Two of fifteen in that same sample, so this is
    the common case rather than a defensive nicety.
    """
    for field in ("alt_geom", "alt_baro"):
        v = ac.get(field)
        if v is None or v == "ground":
            continue
        try:
            return float(v), field
        except (TypeError, ValueError):
            continue
    return None, None


def convert(ac, lat, lon):
    """One upstream aircraft as an object this site can draw, or None if it
    cannot be placed.

    Distance and bearing are computed from the observer's real position, not
    taken from the upstream `dst`/`dir` fields. Those are measured from the
    query point, and the query point is the rounded tile centre -- up to
    about 8 km away, which is worth several degrees of azimuth on something
    only 20 km off. They are still the right thing to check the maths
    against, and the tests do exactly that.
    """
    if ac.get("lat") is None or ac.get("lon") is None:
        return None
    alt_ft, source = _altitude_ft(ac)
    if alt_ft is None:
        return None
    dist_km = ground_km(lat, lon, ac["lat"], ac["lon"])
    el = elevation(alt_ft * M_PER_FT / 1000.0, dist_km)
    # track is the direction actually travelled over the ground; heading is
    # where the nose points, which differs by the wind. Track is what makes
    # an arrow on a chart correct, so prefer it and fall back rather than
    # silently drawing the wrong one.
    track = ac.get("track")
    if track is None:
        track = ac.get("true_heading")
    # Where it will be a minute from now, so the icon can point the way it is
    # actually going *across the sky* rather than along its compass track.
    # Those are different: an aircraft flying due north 20 km east of you does
    # not climb the sky northwards, it slides across it. Only the change in
    # (azimuth, elevation) knows that, and it costs one projection to get.
    az_next = elev_next = None
    speed_kt = ac.get("gs")
    if track is not None and speed_kt:
        run_km = speed_kt * KM_PER_NM * LOOKAHEAD_S / 3600.0
        nlat, nlon = project(ac["lat"], ac["lon"], track, run_km)
        # A climb or descent tilts the nose on screen too. geom_rate matches
        # alt_geom; baro_rate is the fallback, same order as the altitude.
        rate = ac.get("geom_rate")
        if rate is None:
            rate = ac.get("baro_rate")
        next_ft = alt_ft + (rate or 0) * LOOKAHEAD_S / 60.0
        az_next = round(bearing(lat, lon, nlat, nlon), 1)
        elev_next = round(elevation(next_ft * M_PER_FT / 1000.0,
                                    ground_km(lat, lon, nlat, nlon)), 1)
    return {
        "hex": ac.get("hex"),
        # Trailing spaces are in the wire format, not an accident here.
        "callsign": (ac.get("flight") or "").strip() or None,
        "type": ac.get("t"),
        "alt_ft": round(alt_ft),
        "alt_source": source,
        "alt_m": round(alt_ft * M_PER_FT),
        "elev": round(el, 1),
        "az": round(bearing(lat, lon, ac["lat"], ac["lon"]), 1),
        "dist_km": round(dist_km, 1),
        "track": round(track, 1) if track is not None else None,
        # Both None together or neither: the client draws an unturned icon
        # rather than guessing a direction it was not given.
        "az_next": az_next,
        "elev_next": elev_next,
        "speed_kt": speed_kt,
        # Filled in by enrich() when a route is known and trusted. Always
        # present as a key so a client never has to distinguish "no route"
        # from "this build has no routes".
        "route": None,
    }


def _ends(airport):
    """(short, long) for one end of a route, or (None, None).

    Two forms because the sphere shows a different one depending on how busy
    it is: with the celestial labels on there is no room for more than three
    letters, and with them off there is room for the airport's actual name.

    IATA first for the short form -- military fields and small strips often
    carry only the four-letter ICAO, so that is the fallback, and the town is
    the last resort. Each form falls back to the other rather than to nothing,
    so an airport with a name but no code still gets shown.
    """
    short = airport.get("iata_code") or airport.get("icao_code")
    long = airport.get("name") or airport.get("municipality")
    return short or long, long or short


def route_confident(fr):
    """A route worth showing, as {"codes": [...], "names": [...]}, or None.

    Anything short of both ends named is dropped rather than half-rendered.
    "likely LHR to somewhere" is not an answer, and a route whose two ends are
    the same airport is a lookup that has gone wrong rather than a flight that
    goes nowhere.
    """
    try:
        o = fr["origin"]
        d = fr["destination"]
    except (KeyError, TypeError):
        return None
    a, a_long = _ends(o)
    b, b_long = _ends(d)
    if not a or not b or a == b:
        return None
    return {"codes": [a, b], "names": [a_long, b_long]}


def route_for(callsign):
    """(origin, destination) for a callsign, or None. Cached for hours.

    A miss is cached too, as None. General aviation and charters have no
    schedule to find and never will within one flight, so without this every
    poll would re-ask the same unanswerable question for the whole time that
    aircraft is overhead -- which, at a 15-second refresh, is the loudest
    thing this feature could do to somebody else's free service.
    """
    now = time.time()
    hit = _route_cache.get(callsign)
    if hit and hit[0] > now:
        stats["route_hit"] += 1
        return hit[1]
    stats["route_miss"] += 1
    try:
        d = _get(f"{ROUTE_URL}/v0/callsign/{callsign}", ROUTE_TIMEOUT)
        found = route_confident(d["response"]["flightroute"])
    except urllib.error.HTTPError as e:
        # 404 is the honest answer for an unscheduled flight, not a failure.
        if e.code != 404:
            stats["route_error"] += 1
        found = None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        stats["route_error"] += 1
        found = None
    _route_cache[callsign] = (now + ROUTE_TTL, found)
    return found


def enrich(planes):
    """Attach routes in place, in parallel.

    Sequentially this is one HTTP round trip per aircraft against a service
    that is not ours, on a request somebody is waiting on -- eight planes at
    150ms each is over a second added to a page that otherwise answers
    instantly. In parallel it is one round trip, and after the first poll it
    is usually no round trip at all because the six-hour cache has them.
    """
    want = [p for p in planes if p["callsign"] and p["route"] is None]
    if not want:
        return planes
    with ThreadPoolExecutor(max_workers=ROUTE_WORKERS) as pool:
        for p, found in zip(want, pool.map(lambda x: route_for(x["callsign"]),
                                           want)):
            p["route"] = found or None
    return planes


def fetch_tile(tile_lat, tile_lon):
    """Raw aircraft for one grid cell. (list, error or None), micro-cached."""
    now = time.time()
    key = (round(tile_lat, 3), round(tile_lon, 3))
    hit = _pos_cache.get(key)
    if hit and hit[0] > now:
        stats["pos_hit"] += 1
        return hit[1], hit[2]
    stats["pos_miss"] += 1
    url = f"{BASE_URL}/v2/point/{tile_lat:.4f}/{tile_lon:.4f}/{RADIUS_NM}"
    try:
        d = _get(url, TIMEOUT)
        ac, err = d.get("ac") or [], None
    except (urllib.error.URLError, OSError, ValueError) as e:
        stats["pos_error"] += 1
        # Not cached. A failure is worth retrying in a second; caching it
        # would turn one bad moment upstream into fifteen seconds of an empty
        # sky for everybody in the tile.
        return [], f"{type(e).__name__}: {e}"
    _pos_cache[key] = (now + POS_TTL, ac, err)
    _sweep(now)
    return ac, err


def _sweep(now):
    """Drop expired entries. Both caches are small by construction -- one
    entry per active tile, one per callsign seen in the last six hours -- so
    this is a walk over tens of keys, not a data structure."""
    for k in [k for k, v in _pos_cache.items() if v[0] <= now]:
        del _pos_cache[k]
    for k in [k for k, v in _route_cache.items() if v[0] <= now]:
        del _route_cache[k]


def overhead(lat, lon, floor_deg=None, limit=None, routes=True):
    """Aircraft above the floor, highest first. (list, error or None).

    An empty list and an error are different answers and callers must render
    them differently: "nothing overhead right now" is a true statement about
    a quiet sky, while sparse feeder coverage -- most of the oceans, central
    Asia, much of Africa -- is a statement about this site, and showing the
    first when the second is true reads as a bug that will never be reported.
    """
    floor = FLOOR_DEG if floor_deg is None else floor_deg
    tile_lat, tile_lon = _tile(lat, lon)
    raw, err = fetch_tile(tile_lat, tile_lon)
    out = []
    for ac in raw:
        p = convert(ac, lat, lon)
        if p is not None and p["elev"] >= floor:
            out.append(p)
    out.sort(key=lambda p: -p["elev"])
    if limit:
        out = out[:limit]
    if routes:
        enrich(out)
    return out, err
