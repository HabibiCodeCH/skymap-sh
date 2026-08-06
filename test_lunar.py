"""Lunar eclipses, checked against NASA's own published circumstances.

The same standard the solar half is held to, and for the same reason: a page
that states a time to the minute is making a promise the reader cannot check
until they are standing outside in the dark.

What makes this checkable is that almost nothing here is solved for. The
catalogue publishes greatest eclipse, the duration of each phase, the umbral
magnitude and the point the Moon stands over, and every number the page
prints is one of those rearranged. So these mostly assert that the
rearranging is right: that the contacts come out symmetric about greatest
eclipse and add up to the published durations, that the drawing reproduces
the published magnitude, and that the visibility map lands on the same
continents NASA names in prose.
"""
import unittest

import eclipse
import lunar

PARTIAL = "2026-08-28"       # umbral magnitude 0.9299, no totality
TOTAL = "2029-06-26"         # umbral magnitude 1.8436, very deep
SHALLOW = "2028-01-12"       # umbral magnitude 0.0662, barely happens


class TheCatalogueIsReadRight(unittest.TestCase):

    def test_the_eclipses_we_have_pages_for_have_circumstances(self):
        """build_lunar.py is a build step, and a build step that has not been
        re-run is invisible until somebody opens the page it was for."""
        import json
        rows = [e for e in json.load(open("eclipses.json")) if "when_utc" in e]
        for e in rows:
            if "lunar" in e["type"]:
                self.assertTrue(lunar.has(e["when_utc"][:10]), e["name"])

    def test_greatest_eclipse_matches_nasa(self):
        # 2026 Aug 28, 04:14:04 TD with delta-T 75 s.
        el = lunar.elements(PARTIAL)
        self.assertAlmostEqual(el["td"], 4 + 14 / 60 + 4 / 3600, places=4)
        self.assertEqual(el["dT"], 75)
        self.assertAlmostEqual(lunar.greatest_ut(el), 4.2136, places=3)

    def test_the_kinds_are_read_off_the_right_column(self):
        self.assertEqual(lunar.elements(PARTIAL)["kind"], "partial")
        self.assertEqual(lunar.elements(TOTAL)["kind"], "total")
        self.assertGreater(lunar.elements(TOTAL)["um_mag"], 1.0)
        self.assertLess(lunar.elements(PARTIAL)["um_mag"], 1.0)


class TheContactsAddUp(unittest.TestCase):
    """Every phase is published as a duration centred on greatest eclipse, so
    the contacts are exact -- but only if they are laid out symmetrically and
    the totality pair is named as the second and third contacts rather than
    the first and fourth."""

    def test_each_phase_lasts_as_long_as_nasa_says(self):
        for key in (PARTIAL, TOTAL, SHALLOW):
            el, c = lunar.elements(key), lunar.contacts(key)
            self.assertAlmostEqual((c["P4"] - c["P1"]) * 60, el["pen_min"],
                                   places=3, msg=key)
            self.assertAlmostEqual((c["U4"] - c["U1"]) * 60, el["par_min"],
                                   places=3, msg=key)
            if el["tot_min"]:
                self.assertAlmostEqual((c["U3"] - c["U2"]) * 60, el["tot_min"],
                                       places=3, msg=key)

    def test_they_are_centred_on_greatest_eclipse(self):
        for key in (PARTIAL, TOTAL):
            c = lunar.contacts(key)
            mid = c["greatest"]
            for a, b in (("P1", "P4"), ("U1", "U4")):
                self.assertAlmostEqual(mid - c[a], c[b] - mid, places=9)

    def test_they_nest_the_way_the_shadow_does(self):
        c = lunar.contacts(TOTAL)
        for a, b in (("P1", "U1"), ("U1", "U2"), ("U2", "greatest"),
                     ("greatest", "U3"), ("U3", "U4"), ("U4", "P4")):
            self.assertLess(c[a], c[b], f"{a} should come before {b}")

    def test_a_partial_eclipse_has_no_totality(self):
        self.assertNotIn("U2", lunar.contacts(PARTIAL))
        self.assertIsNone(lunar.duration_seconds(PARTIAL, "tot_min"))


class TheShadowIsWhereTheMagnitudeSaysItIs(unittest.TestCase):
    """The drawing is reconstructed from the published circumstances rather
    than from an orbit, so what has to hold is that it gives those
    circumstances back: the published magnitude at greatest eclipse, and the
    two discs touching at first contact."""

    def test_the_discs_touch_at_first_contact(self):
        for key in (PARTIAL, TOTAL):
            _s_min, umbra_r, _pen_r = lunar.geometry(key)
            s = lunar.separation(key, lunar.contacts(key)["U1"])
            self.assertAlmostEqual(s, umbra_r + 1.0, places=3, msg=key)

    def test_greatest_eclipse_reproduces_the_published_magnitude(self):
        for key in (PARTIAL, TOTAL, SHALLOW):
            el = lunar.elements(key)
            _s_min, umbra_r, _pen_r = lunar.geometry(key)
            s = lunar.separation(key, lunar.greatest_ut(el))
            mag = (umbra_r + 1.0 - s) / 2.0
            self.assertAlmostEqual(mag, el["um_mag"], places=3, msg=key)

    def test_the_shadow_is_sized_per_eclipse_and_stays_plausible(self):
        """A constant 2.65 umbra cannot produce a magnitude above 1.825, and
        26 June 2029 is published at 1.8436: the closest approach came out
        negative and the drawing used its absolute value. Sized from gamma
        and the two magnitudes instead, which the catalogue gives for every
        eclipse. The bounds here are the real range of the Earth's shadow at
        the Moon's distance, so a formula that drifted would trip them."""
        import json
        for key in json.load(open("lunar.json")):
            s_min, umbra_r, pen_r = lunar.geometry(key)
            self.assertGreaterEqual(s_min, 0.0, key)
            self.assertTrue(2.4 < umbra_r < 2.9, f"{key}: umbra {umbra_r:.2f}")
            self.assertTrue(4.3 < pen_r < 5.0, f"{key}: penumbra {pen_r:.2f}")
            self.assertGreater(pen_r, umbra_r, key)

    def test_the_shadow_crosses_from_one_side_to_the_other(self):
        c = lunar.contacts(TOTAL)
        self.assertLess(lunar.shadow_centre(TOTAL, c["U1"])[0], 0)
        self.assertGreater(lunar.shadow_centre(TOTAL, c["U4"])[0], 0)

    def test_a_deep_eclipse_swallows_the_moon_and_a_shallow_one_does_not(self):
        mid = lunar.contacts(TOTAL)["greatest"]
        self.assertEqual(lunar.shade_at(TOTAL, mid, 0, 0), "umbra")
        mid = lunar.contacts(SHALLOW)["greatest"]
        self.assertNotEqual(lunar.shade_at(SHALLOW, mid, 0, 0), "umbra")


class WhoCanSeeIt(unittest.TestCase):
    """NASA lists 2026 August 28 as visible from the east Pacific, the
    Americas, Europe and Africa. The map is computed from the published
    sublunar point, so it has to land on the same continents."""

    SEES_IT = {"New York": (40.71, -74.01), "Rio": (-22.91, -43.17),
               "London": (51.51, -0.13), "Lagos": (6.52, 3.38),
               "Reykjavik": (64.15, -21.94)}
    MISSES_IT = {"Tokyo": (35.68, 139.65), "Perth": (-31.95, 115.86),
                 "Beijing": (39.90, 116.41)}

    def test_the_places_nasa_lists_can_see_it(self):
        for name, (lat, lon) in self.SEES_IT.items():
            self.assertTrue(lunar.visibility(PARTIAL, lat, lon)["visible"], name)

    def test_the_far_side_of_the_world_cannot(self):
        for name, (lat, lon) in self.MISSES_IT.items():
            v = lunar.visibility(PARTIAL, lat, lon)
            self.assertFalse(v["visible"], name)
            self.assertLess(v["alt_at_greatest"], 0, name)

    def test_the_moon_is_overhead_where_the_catalogue_says(self):
        """The one place the whole visibility half rests on: if the sublunar
        point is read wrong, every altitude on the map is wrong with it."""
        el = lunar.elements(PARTIAL)
        alt = lunar.moon_alt(PARTIAL, el["zen_lat"], el["zen_lon"],
                             lunar.greatest_ut(el))
        self.assertAlmostEqual(alt, 90.0, places=6)

    def test_the_moon_sets_during_it_in_zurich(self):
        """Which is what the timeline has to say and what the arc has to
        draw: Europe loses this one partway through."""
        v = lunar.visibility(PARTIAL, 47.3769, 8.5417)
        self.assertTrue(v["visible"])
        self.assertFalse(v["all_of_it"])
        window = lunar.up_window(PARTIAL, 47.3769, 8.5417)
        self.assertIsNotNone(window)
        self.assertLess(window[1], lunar.contacts(PARTIAL)["P4"])

    def test_a_place_that_never_sees_it_gets_no_window(self):
        self.assertIsNone(lunar.up_window(PARTIAL, 35.68, 139.65))   # Tokyo

    def test_the_moon_climbs_and_falls_inside_its_window(self):
        peak = lunar.peak_alt(PARTIAL, 40.71, -74.01)                # New York
        t0, t1 = lunar.up_window(PARTIAL, 40.71, -74.01)
        self.assertGreater(peak, 0)
        for edge in (t0, t1):
            self.assertLess(abs(lunar.moon_alt(PARTIAL, 40.71, -74.01, edge)),
                            1.0, "the window should end at the horizon")


class ThePicturesFollowTheNumbers(unittest.TestCase):

    def test_the_moon_is_drawn_and_the_shadow_is_on_it(self):
        rows = eclipse.moon_art(PARTIAL, color=False)
        self.assertEqual(len(rows), eclipse.ART_ROWS)
        body = "".join(rows)
        self.assertIn("·", body)                    # in the umbra
        self.assertTrue(body.count("#") or body.count("+"))

    def test_a_deep_eclipse_leaves_nothing_in_sunlight(self):
        self.assertNotIn("#", "".join(eclipse.moon_art(TOTAL, color=False)))

    def test_a_shallow_one_leaves_most_of_it_lit(self):
        body = "".join(eclipse.moon_art(SHALLOW, color=False))
        self.assertGreater(body.count("#"), body.count("·"))

    def test_nothing_is_drawn_for_an_eclipse_with_no_circumstances(self):
        self.assertEqual(eclipse.moon_art("2026-08-12"), [])   # a solar one

    def test_the_arc_rises_and_sets(self):
        rows = eclipse.arc_art(PARTIAL, 40.71, -74.01, color=False)  # New York
        self.assertEqual(len(rows), eclipse.ARC_ROWS)
        self.assertEqual(set(rows[-1]), {"-"}, "the horizon is not a line")
        top = []
        for c in range(eclipse.ARC_COLS):
            hit = [r for r in range(eclipse.ARC_ROWS - 1)
                   if c < len(rows[r]) and rows[r][c] != " "]
            top.append(min(hit) if hit else eclipse.ARC_ROWS)
        middle, edges = min(top[35:55]), min(top[:5] + top[-5:])
        self.assertLess(middle, edges, "the Moon should be highest mid-night")

    def test_no_arc_where_the_moon_never_comes_up(self):
        self.assertEqual(eclipse.arc_art(PARTIAL, 35.68, 139.65), [])   # Tokyo

    def test_the_eclipse_is_marked_on_the_arc(self):
        rows = eclipse.arc_art(PARTIAL, 40.71, -74.01, color=False)
        body = "".join(rows)
        self.assertIn("+", body, "the eclipsed stretch is not marked")
        self.assertIn("·", body, "the rest of the night is not drawn")

    def test_the_night_map_agrees_with_the_page(self):
        """The same check the solar map gets, for the same reason: the
        picture and the prose come from one calculation, so they cannot
        disagree without something being broken."""
        grid, _land, lat_top, lat_bot = eclipse._night_grid(PARTIAL)
        both = dict(WhoCanSeeIt.SEES_IT, **WhoCanSeeIt.MISSES_IT)
        for name, (lat, lon) in both.items():
            if not lat_bot <= lat <= lat_top:
                continue
            r, c = eclipse.night_cell_of(PARTIAL, lat, lon)
            said = lunar.visibility(PARTIAL, lat, lon)["visible"]
            self.assertEqual(grid[r][c] > 0, said, name)


if __name__ == "__main__":
    unittest.main()
