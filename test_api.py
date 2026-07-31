#!/usr/bin/env python3
"""Tests for the nearest-city timezone fallback in api.py.

Run:  python3 test_api.py
"""
import datetime as dt
import unittest
import api


class Aliases(unittest.TestCase):
    def test_airport_code_aliases_resolve(self):
        expected = {
            "cph": "Copenhagen", "bcn": "Barcelona", "ams": "Amsterdam",
            "cdg": "Paris", "lhr": "London", "fra": "Frankfurt",
            "muc": "Munich", "dxb": "Dubai", "sin": "Singapore",
            "ist": "Istanbul",
        }
        for code, city in expected.items():
            p = api.lookup_place(code)
            self.assertIsNotNone(p, f"'{code}' did not resolve at all")
            self.assertEqual(p.name, city, f"'{code}' resolved to {p.name!r}")


class NearestCity(unittest.TestCase):
    def test_finds_a_city_near_geneva(self):
        # 46.20, 6.10 is near the Geneva/Lausanne area.
        near = api._nearest_city(46.20, 6.10)
        self.assertIsNotNone(near)
        _lat, _lon, zone, _iso2, country, *_rest = near
        self.assertIn(country, ("Switzerland", "France"))
        self.assertTrue(zone)

    def test_prefers_the_recognisable_city_over_a_closer_suburb(self):
        # Vernier (a Geneva suburb, near the airport) can be a touch closer to
        # these exact coordinates than Geneva itself -- the fix must still
        # surface Geneva, since nobody looks up a chart and expects "Vernier".
        near = api._nearest_city(46.20, 6.10)
        self.assertEqual(near[7], "Geneva")

    def test_none_in_the_middle_of_the_ocean(self):
        # South Pacific, nowhere near land.
        near = api._nearest_city(-30.0, -140.0)
        self.assertIsNone(near)

    def test_memoised_result_is_consistent(self):
        first = api._nearest_city(46.20, 6.10)
        second = api._nearest_city(46.20, 6.10)
        self.assertEqual(first, second)


class ResolvePlaceFallback(unittest.TestCase):
    def test_bare_coordinates_keep_the_coordinates_as_name(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        self.assertEqual(p.name, "46.20,6.10")

    def test_bare_coordinates_get_a_real_timezone_not_longitude_over_15(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        # longitude/15 for 6.10 rounds to 0 -- the bug. A real zone must not.
        self.assertNotEqual(p.zone, None)
        self.assertNotEqual(round(p.lon / 15.0), self._true_offset(p))

    def test_bare_coordinates_carry_a_near_city_hint(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        self.assertIsNotNone(p.near)

    def test_unresolvable_coordinates_fall_back_to_longitude(self):
        p = api.resolve_place(None, fallback=(-30.0, -140.0))
        self.assertIsNone(p.zone)
        self.assertIsNone(p.near)

    @staticmethod
    def _true_offset(p):
        import datetime as dt
        return p.offset(dt.datetime(2026, 7, 30, 8, 32))


class DsoAndQuadrantRequests(unittest.TestCase):
    """?dso= and ?quadrant= are off/unset by default and only take effect on
    the night chart -- covers the Request plumbing added alongside them."""

    def _night_request(self, **kw):
        return api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0),
                           night=True, **kw)

    def test_defaults_are_off(self):
        r = api.Request(place="Zurich")
        self.assertFalse(r.dso)
        self.assertIsNone(r.quadrant)

    def test_quadrant_letter_is_upper_cased(self):
        r = api.Request(place="Zurich", quadrant="b")
        self.assertEqual(r.quadrant, "B")

    def test_multi_char_garbage_is_dropped_before_it_can_reach_a_cache_key(self):
        # A single letter (or None) is the only shape ?quadrant= is allowed to
        # take by the time it reaches Request -- otherwise arbitrary garbage
        # values would each mint a fresh cache entry (server._cache_key keys
        # on r.quadrant), a free cache-busting surface.
        r = api.Request(place="Zurich", quadrant="ZZ")
        self.assertIsNone(r.quadrant)
        r = api.Request(place="Zurich", quadrant="7")
        self.assertIsNone(r.quadrant)

    def test_dso_flag_reaches_the_composed_output(self):
        r = self._night_request(dso=True)
        res = api.compose(r)
        self.assertTrue(res.data["dso"])
        self.assertIn("dso=1", res.text)

    def test_quadrant_reaches_the_composed_output(self):
        r = self._night_request(quadrant="A")
        res = api.compose(r)
        self.assertEqual(res.data["quadrant"]["applied"], "A")
        self.assertIn("quadrant A", res.text)

    def test_unknown_quadrant_is_reported_not_errored(self):
        # "Z" is a well-formed single letter, just not one the default grid
        # (A-F) generates -- this is the realistic typo case, distinct from
        # the malformed-input case covered above.
        r = self._night_request(quadrant="Z")
        res = api.compose(r)
        self.assertEqual(res.status, 200)
        self.assertEqual(res.data["quadrant"]["error"], "Z")
        self.assertIsNone(res.data["quadrant"]["applied"])

    def test_png_url_carries_both_params(self):
        r = self._night_request(dso=True, quadrant="C")
        url = api._png_url(r)
        self.assertIn("dso=1", url)
        self.assertIn("quadrant=C", url)


class NightOverrideDuringDaylight(unittest.TestCase):
    """?night=1 forces the star chart even while the Sun is up. The Moon
    used to be silently dropped from render_linear's bodies set whenever it
    wasn't bright enough to matter -- fine for what gets drawn, but
    sky_read() reads moon["alt"] unconditionally, so this crashed with a
    KeyError every time someone used --night in broad daylight."""

    def test_does_not_crash_and_reports_moon_altitude(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 13, 0), night=True)
        res = api.compose(r)
        self.assertEqual(res.status, 200)
        self.assertIn("alt", res.data["moon"])

    def test_chart_only_path_does_not_crash_either(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 13, 0), night=True)
        api.compose_chart_only(r)   # raises on failure; nothing to assert


if __name__ == "__main__":
    unittest.main()
