"""What a wrong plane still looks like.

Aircraft are unlike everything else this site draws: there is no ephemeris to
check against, the answer changes every fifteen seconds, and nobody reading it
can verify it. A plane placed in the wrong half of the sky, at a plausible
altitude, with a real callsign on it, looks exactly like a plane placed
correctly. So the checks worth having are the ones a plausible wrong answer
cannot pass.

The strongest of them is free: adsb.lol computes its own distance and bearing
from the query point (`dst`, `dir`) and we ignore those and compute ours from
the observer. Two independent implementations of the same geometry over real
positions is a real oracle, so SAMPLE is a verbatim capture -- five aircraft
over Geneva at 18:27 local on 2026-08-10, fields trimmed, values untouched.
Do not tidy the numbers in it.
"""
import json
import math
import unittest
import urllib.error

import planes

# Where the capture was taken from, which is what `dst` and `dir` are
# measured against. Every comparison below depends on this being the exact
# query point, not the tile it rounds to.
LAT, LON = 46.20, 6.14

SAMPLE = [
    # Cruising, far out and west: the low-elevation end of the useful range.
    {"hex": "4081c0", "flight": "BAW530  ", "t": "A20N", "alt_baro": 39000,
     "alt_geom": 40850, "gs": 434.7, "track": 119.04, "true_heading": 122.72,
     "lat": 46.400803, "lon": 5.388928, "dst": 33.346, "dir": 291.4},
    # Low and close, on approach. Under the floor despite being the nearest
    # thing in the sky, which is the floor doing its job rather than failing.
    {"hex": "46b822", "flight": "AEE6SG  ", "t": "A21N", "alt_baro": 4750,
     "alt_geom": 5300, "gs": 195.9, "track": 45.62, "true_heading": 45.87,
     "lat": 46.096756, "lon": 5.90207, "dst": 11.663, "dir": 238.0},
    # On a taxiway at LSGG: alt_baro is the string "ground" and there is no
    # alt_geom at all. Two of the fifteen aircraft in the full capture were
    # like this, so it is the ordinary case, not a defensive one.
    {"hex": "502d44", "flight": "AUA156  ", "t": "BCS3", "alt_baro": "ground",
     "gs": 0.1, "true_heading": 225.0, "lat": 46.230958, "lon": 6.105549,
     "dst": 2.346, "dir": 322.4},
    # The highest thing up at the time, and the only one that would have
    # survived a 15-degree floor.
    {"hex": "4ca4f8", "flight": "RYR8XE  ", "t": "B738", "alt_baro": 37000,
     "alt_geom": 38750, "gs": 431.6, "track": 188.39, "true_heading": 191.99,
     "lat": 46.402771, "lon": 6.156564, "dst": 12.207, "dir": 3.2},
    {"hex": "39ceb0", "flight": "TVF60SE ", "t": "B738", "alt_baro": 38000,
     "alt_geom": 39850, "gs": 436.9, "track": 302.85, "true_heading": 300.33,
     "lat": 46.510483, "lon": 6.420504, "dst": 21.973, "dir": 31.8},
]

KM_PER_NM = 1.852


def fake_upstream(payload=None, fail=None):
    """A stand-in for _get. Records the URLs it was asked for, so a test can
    assert that a second call did not happen rather than only that the answer
    was the same -- which a cache and a re-fetch cannot be told apart by."""
    calls = []

    def _get(url, timeout):
        calls.append(url)
        if fail is not None:
            raise fail
        return payload

    _get.calls = calls
    return _get


class ClearCaches(unittest.TestCase):
    """Both caches are module-level and outlive a test. Without this the
    order tests run in decides whether they pass."""

    def setUp(self):
        planes._pos_cache.clear()
        planes._route_cache.clear()
        for k in planes.stats:
            planes.stats[k] = 0
        self._real_get = planes._get

    def tearDown(self):
        planes._get = self._real_get


class TheGeometryAgreesWithTheSource(ClearCaches):
    """adsb.lol's own distance and bearing, against ours, over real
    positions. This is the check that a plane in the wrong place fails and
    nothing else here would catch."""

    def test_bearing_matches_upstream_to_a_tenth_of_a_degree(self):
        for ac in SAMPLE:
            p = planes.convert(ac, LAT, LON)
            if p is None:
                continue
            gap = abs((p["az"] - ac["dir"] + 180) % 360 - 180)
            self.assertLess(gap, 0.1, f"{ac['flight']}: az {p['az']} vs {ac['dir']}")

    def test_distance_matches_upstream_within_200_metres(self):
        # Not zero: they use a slightly different Earth radius. 200 m at 60 km
        # is under half a degree of elevation, and the tolerance is here to
        # catch a wrong formula, not to pin down a shared constant.
        for ac in SAMPLE:
            p = planes.convert(ac, LAT, LON)
            if p is None:
                continue
            gap = abs(p["dist_km"] - ac["dst"] * KM_PER_NM)
            self.assertLess(gap, 0.2, f"{ac['flight']}: {p['dist_km']} km")

    def test_a_plane_overhead_is_ninety_degrees_up(self):
        self.assertAlmostEqual(planes.elevation(11.0, 0.0), 90.0, places=6)

    def test_curvature_is_subtracted_not_added(self):
        """The Earth falls away underneath, so the honest elevation is always
        the lower of the two. A sign error here reads as a slightly generous
        chart rather than as a bug, which is why it is worth a test."""
        alt_km, dist_km = 11.0, 65.0
        naive = math.degrees(math.atan2(alt_km, dist_km))
        self.assertLess(planes.elevation(alt_km, dist_km), naive)
        self.assertAlmostEqual(planes.elevation(alt_km, dist_km), naive,
                               delta=0.5)


class AircraftThatCannotBeDrawnAreDropped(ClearCaches):

    def test_an_aircraft_on_the_ground_is_not_in_the_sky(self):
        ground = [a for a in SAMPLE if a["hex"] == "502d44"][0]
        self.assertIsNone(planes.convert(ground, LAT, LON))

    def test_a_position_less_aircraft_is_dropped_not_placed_at_zero(self):
        """Rendering these at 0,0 would put a plane due north on the horizon
        every time the transponder was reporting altitude and nothing else --
        a permanent phantom in one corner of the chart."""
        for missing in ({"lat": None}, {"lon": None}):
            ac = dict(SAMPLE[0])
            ac.update(missing)
            self.assertIsNone(planes.convert(ac, LAT, LON))

    def test_an_aircraft_with_no_altitude_at_all_is_dropped(self):
        ac = {k: v for k, v in SAMPLE[0].items()
              if k not in ("alt_geom", "alt_baro")}
        self.assertIsNone(planes.convert(ac, LAT, LON))


class AltitudeComesFromTheRightField(ClearCaches):

    def test_geometric_altitude_wins_when_present(self):
        p = planes.convert(SAMPLE[0], LAT, LON)
        self.assertEqual(p["alt_source"], "alt_geom")
        self.assertEqual(p["alt_ft"], 40850)

    def test_barometric_is_the_fallback_not_the_default(self):
        """About one aircraft in seven has no alt_geom, and the two fields
        disagree by a couple of thousand feet -- so silently preferring baro
        would be a systematic error, not a rounding one."""
        ac = {k: v for k, v in SAMPLE[0].items() if k != "alt_geom"}
        p = planes.convert(ac, LAT, LON)
        self.assertEqual(p["alt_source"], "alt_baro")
        self.assertEqual(p["alt_ft"], 39000)

    def test_track_falls_back_to_heading_but_prefers_track(self):
        p = planes.convert(SAMPLE[0], LAT, LON)
        self.assertEqual(p["track"], 119.0)
        ac = {k: v for k, v in SAMPLE[0].items() if k != "track"}
        self.assertEqual(planes.convert(ac, LAT, LON)["track"], 122.7)


class TheFloorIsThePromise(ClearCaches):

    def test_only_aircraft_above_the_floor_come_back(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        out, err = planes.overhead(LAT, LON, floor_deg=10.0, routes=False)
        self.assertIsNone(err)
        self.assertEqual([p["callsign"] for p in out],
                         ["RYR8XE", "TVF60SE", "BAW530"])

    def test_highest_first(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        out, _err = planes.overhead(LAT, LON, floor_deg=0.0, routes=False)
        self.assertEqual(out, sorted(out, key=lambda p: -p["elev"]))

    def test_a_higher_floor_is_a_subset_of_a_lower_one(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        low, _ = planes.overhead(LAT, LON, floor_deg=5.0, routes=False)
        planes._pos_cache.clear()
        high, _ = planes.overhead(LAT, LON, floor_deg=15.0, routes=False)
        self.assertTrue({p["hex"] for p in high} <= {p["hex"] for p in low})


class TheTileCacheSharesOneCallBetweenNeighbours(ClearCaches):

    def test_two_observers_in_the_same_city_cost_one_upstream_call(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        planes.overhead(LAT, LON, routes=False)
        planes.overhead(LAT + 0.02, LON - 0.02, routes=False)
        self.assertEqual(len(planes._get.calls), 1)
        self.assertEqual(planes.stats["pos_hit"], 1)
        self.assertEqual(planes.stats["pos_miss"], 1)

    def test_the_shared_answer_is_still_measured_from_each_observer(self):
        """The tile is only how the fetch is keyed. If the conversion ever
        used the tile centre instead of the caller's own position, two people
        10 km apart would be handed the same azimuths -- which would look
        entirely reasonable and be wrong by several degrees."""
        planes._get = fake_upstream({"ac": SAMPLE})
        a, _ = planes.overhead(LAT, LON, floor_deg=0.0, routes=False)
        b, _ = planes.overhead(LAT + 0.02, LON - 0.02, floor_deg=0.0,
                               routes=False)
        by_hex = {p["hex"]: p for p in b}
        self.assertTrue(any(p["az"] != by_hex[p["hex"]]["az"] for p in a))

    def test_a_far_away_observer_gets_their_own_call(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        planes.overhead(LAT, LON, routes=False)
        planes.overhead(LAT + 3.0, LON + 3.0, routes=False)
        self.assertEqual(len(planes._get.calls), 2)

    def test_an_expired_entry_is_refetched(self):
        planes._get = fake_upstream({"ac": SAMPLE})
        planes.overhead(LAT, LON, routes=False)
        for k in list(planes._pos_cache):
            exp, ac, err = planes._pos_cache[k]
            planes._pos_cache[k] = (exp - planes.POS_TTL - 1, ac, err)
        planes.overhead(LAT, LON, routes=False)
        self.assertEqual(len(planes._get.calls), 2)


class AnEmptySkyAndABrokenOneReadDifferently(ClearCaches):

    def test_no_aircraft_is_not_an_error(self):
        planes._get = fake_upstream({"ac": []})
        out, err = planes.overhead(LAT, LON, routes=False)
        self.assertEqual(out, [])
        self.assertIsNone(err)

    def test_an_upstream_failure_says_so(self):
        planes._get = fake_upstream(fail=urllib.error.URLError("down"))
        out, err = planes.overhead(LAT, LON, routes=False)
        self.assertEqual(out, [])
        self.assertIsNotNone(err)

    def test_a_failure_is_not_cached(self):
        """Caching it would turn one bad second upstream into fifteen seconds
        of an empty sky for everyone in the tile, and the recovery would look
        like the outage lasted longer than it did."""
        planes._get = fake_upstream(fail=urllib.error.URLError("down"))
        planes.overhead(LAT, LON, routes=False)
        self.assertEqual(planes._pos_cache, {})


class ARouteIsAnInferenceAndIsTreatedAsOne(ClearCaches):

    def route_payload(self, origin, dest):
        return {"response": {"flightroute": {
            "origin": {"municipality": origin},
            "destination": {"municipality": dest}}}}

    def test_a_complete_route_is_accepted(self):
        fr = self.route_payload("London", "Split")["response"]["flightroute"]
        self.assertEqual(planes.route_confident(fr), ("London", "Split"))

    def test_half_a_route_is_no_route(self):
        for bad in (("London", None), (None, "Split"), (None, None)):
            fr = self.route_payload(*bad)["response"]["flightroute"]
            self.assertIsNone(planes.route_confident(fr))

    def test_a_flight_from_a_place_to_itself_is_a_failed_lookup(self):
        fr = self.route_payload("Geneva", "Geneva")["response"]["flightroute"]
        self.assertIsNone(planes.route_confident(fr))

    def test_a_missing_route_is_cached_so_it_is_not_asked_for_again(self):
        """A business jet has no schedule and will not grow one mid-flight.
        Without this, a 15-second refresh re-asks somebody else's free
        service the same unanswerable question for as long as the aircraft
        is overhead."""
        planes._get = fake_upstream(fail=urllib.error.HTTPError(
            "u", 404, "Not Found", {}, None))
        self.assertIsNone(planes.route_for("FSE1D"))
        self.assertIsNone(planes.route_for("FSE1D"))
        self.assertEqual(len(planes._get.calls), 1)
        self.assertEqual(planes.stats["route_hit"], 1)

    def test_a_404_is_an_answer_not_an_error(self):
        planes._get = fake_upstream(fail=urllib.error.HTTPError(
            "u", 404, "Not Found", {}, None))
        planes.route_for("FSE1D")
        self.assertEqual(planes.stats["route_error"], 0)

    def test_a_real_failure_is_counted_as_one(self):
        planes._get = fake_upstream(fail=urllib.error.HTTPError(
            "u", 503, "Down", {}, None))
        planes.route_for("BAW530")
        self.assertEqual(planes.stats["route_error"], 1)

    def test_enrichment_attaches_the_route_and_leaves_misses_null(self):
        planes._get = fake_upstream(self.route_payload("London", "Split"))
        out = planes.enrich([{"callsign": "BAW530", "route": None},
                             {"callsign": None, "route": None}])
        self.assertEqual(out[0]["route"], ["London", "Split"])
        self.assertIsNone(out[1]["route"])

    def test_position_and_route_cache_statistics_stay_apart(self):
        """The position cache is meant to miss and the route cache is meant
        to hit. Blending them produces an average that describes neither, and
        the site-wide hit rate would inherit it."""
        planes._get = fake_upstream({"ac": SAMPLE})
        planes.overhead(LAT, LON, routes=False)
        planes.overhead(LAT, LON, routes=False)
        self.assertEqual(planes.stats["pos_hit"], 1)
        self.assertEqual(planes.stats["route_hit"], 0)
        self.assertEqual(planes.stats["route_miss"], 0)


class TheUpstreamIsSwappable(ClearCaches):
    """Four aggregators speak this response and the base URL is the only
    difference between them. If a literal host ever creeps into the request
    path, the fallback stops being a config change."""

    def test_the_position_url_is_built_from_the_configured_base(self):
        planes._get = fake_upstream({"ac": []})
        planes.overhead(LAT, LON, routes=False)
        self.assertTrue(planes._get.calls[0].startswith(planes.BASE_URL))

    def test_the_route_url_is_built_from_its_own_base(self):
        planes._get = fake_upstream({"response": {"flightroute": {}}})
        planes.route_for("BAW530")
        self.assertTrue(planes._get.calls[0].startswith(planes.ROUTE_URL))


if __name__ == "__main__":
    unittest.main()
