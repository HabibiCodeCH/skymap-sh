"""The dark-sky sites.

Hand-authored coordinates are the kind of data that rots quietly: a typo in
a longitude puts a Namibian reserve in the Atlantic and nothing crashes, the
page just draws the wrong sky. So these check the file against the world
rather than against itself.

What is deliberately NOT checked is how dark each one is. The Bortle figure
comes from the light-pollution model at those coordinates, never from this
file, and asserting a class here would turn a measurement into a promise --
the file's own comment says nothing in it may claim a darkness it does not
have. Several of the European reserves genuinely read Bortle 4: they are
small protected areas surrounded by lit country, and that is the honest
answer rather than a bug to tune away.
"""
import json
import unittest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import api
import sky

SITES = json.load(open(f"{sky.BASE}/darksky.json"))["sites"]


class TheFileIsWellFormed(unittest.TestCase):

    def test_every_site_has_what_a_place_needs(self):
        for s in SITES:
            for key in ("name", "lat", "lon", "tz", "note"):
                self.assertIn(key, s, s.get("name"))

    def test_coordinates_are_on_the_planet(self):
        for s in SITES:
            self.assertTrue(-90 <= s["lat"] <= 90, s["name"])
            self.assertTrue(-180 <= s["lon"] <= 180, s["name"])

    def test_no_two_sites_share_a_name(self):
        names = [api.norm_name(s["name"]) for s in SITES]
        self.assertEqual(len(names), len(set(names)))

    def test_every_timezone_is_a_real_iana_zone(self):
        # A bad zone does not raise here, it silently falls back to
        # longitude/15 -- so the clock would be quietly wrong rather than
        # visibly broken.
        for s in SITES:
            try:
                ZoneInfo(s["tz"])
            except (ZoneInfoNotFoundError, ValueError):
                self.fail(f"{s['name']}: {s['tz']} is not an IANA zone")

    def test_the_timezone_matches_the_longitude(self):
        """A zone pasted from the wrong line is the easy mistake, and it
        survives every other check in here. Real offsets vary with DST and
        with political borders, so this only catches a site being in the
        wrong part of the world -- four hours out, not one."""
        import datetime as dt
        when = dt.datetime(2026, 1, 15, 12, 0)
        for s in SITES:
            zone = ZoneInfo(s["tz"])
            actual = when.replace(tzinfo=dt.timezone.utc).astimezone(zone)
            offset = actual.utcoffset().total_seconds() / 3600
            expected = s["lon"] / 15.0
            self.assertLess(abs(offset - expected), 4.0,
                            f"{s['name']}: {s['tz']} is {offset:+g}h but "
                            f"longitude {s['lon']} suggests {expected:+.1f}h")


class TheySitInThePlaceIndex(unittest.TestCase):
    """Folded into the city index rather than kept beside it, so every path
    a place name already travels works on them unchanged."""

    def test_every_site_resolves(self):
        for s in SITES:
            self.assertIsNotNone(api.lookup_place(s["name"]), s["name"])

    def test_none_is_hijacked_by_a_town_of_the_same_name(self):
        """Two were, before they were renamed: /Jasper is a town in Indiana
        and /La Palma is one in Cuba, and both won on population. A site
        that silently resolves somewhere else is worse than one missing."""
        for s in SITES:
            p = api.lookup_place(s["name"])
            self.assertLess(abs(p.lat - s["lat"]), 0.5, s["name"])
            self.assertLess(abs(p.lon - s["lon"]), 0.5, s["name"])

    def test_a_real_town_still_wins_its_own_name(self):
        # Population zero and appended, so anywhere people actually live
        # keeps the path.
        for town in ("Jasper", "La Palma"):
            p = api.lookup_place(town)
            self.assertIsNotNone(p)
            self.assertNotIn(town, [s["name"] for s in SITES])

    def test_they_carry_no_population(self):
        for s in SITES:
            rows = api._cities()[api.norm_name(s["name"])]
            mine = [r for r in rows if abs(r[0] - s["lat"]) < 0.01]
            self.assertTrue(mine, s["name"])
            self.assertEqual(mine[0][6], 0, s["name"])

    def test_they_complete_in_the_search_bar(self):
        for prefix, want in (("atac", "Atacama"), ("death", "Death Valley"),
                             ("namib", "NamibRand"), ("cherry", "Cherry Springs")):
            names = [r["name"] if isinstance(r, dict) else r
                     for r in api.complete_cities(prefix, with_pop=True)]
            self.assertIn(want, names, prefix)


class TheyAnswerTheQuestionTheyExistFor(unittest.TestCase):

    def test_the_darkest_of_them_beats_any_city(self):
        """Not a claim about a specific class, which the model owns -- a
        comparison, which is the whole point of being able to type them."""
        atacama = api.lookup_place("Atacama")
        zurich = api.lookup_place("Zurich")
        self.assertLess(api.sky_brightness(atacama.lat, atacama.lon)[1],
                        api.sky_brightness(zurich.lat, zurich.lon)[1])

    def test_most_of_them_are_genuinely_dark(self):
        # Loose on purpose: several European reserves read Bortle 4 because
        # they are small and surrounded by lit country. A file of famous
        # dark skies where the majority were not dark would mean the
        # coordinates were wrong.
        dark = sum(1 for s in SITES
                   if api.sky_brightness(s["lat"], s["lon"])[1] <= 3)
        self.assertGreater(dark, len(SITES) // 2)


if __name__ == "__main__":
    unittest.main()
