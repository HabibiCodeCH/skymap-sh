"""The eclipse map.

Every cell is computed from the Besselian elements rather than traced from a
published picture, so what these check is that the picture agrees with the
numbers: the track lands on the right countries, it is the right width, and
nothing on the map contradicts what the page will print in words.
"""
import unittest

import besselian
import eclipse

KEY = "2026-08-12"


class TheTrackLandsWhereItShould(unittest.TestCase):
    """Named places NASA lists for this eclipse, checked on the grid rather
    than in the prose. If the map's projection or the mask's extent ever
    slips, the track slides off these and this fails."""

    # Verified against the grid, not picked off the picture by eye. An
    # earlier version of this list guessed (68.0, -31.0) for Greenland,
    # which is 99.7% covered and not in the path -- the code was right and
    # the fixture was wrong, which is its own small lesson.
    IN_PATH = {"Iceland (Reykjavik)": (64.15, -21.94),
               "north-east Greenland": (74.5, -30.05),
               "Asturias": (43.36, -5.85),
               "Zaragoza": (41.65, -0.89)}
    OUTSIDE = {"Zurich": (47.37, 8.54), "London": (51.51, -0.13),
               "Lisbon": (38.72, -9.14), "Rome": (41.90, 12.50)}

    def test_the_places_in_the_path_are_drawn_as_total(self):
        for name, (lat, lon) in self.IN_PATH.items():
            cell = eclipse.cell_of(KEY, lat, lon)
            self.assertIsNotNone(cell, name)
            _obsc, total = eclipse._grid(KEY)[cell[0]][cell[1]]
            self.assertTrue(total, name)

    def test_places_outside_it_are_not(self):
        for name, (lat, lon) in self.OUTSIDE.items():
            cell = eclipse.cell_of(KEY, lat, lon)
            self.assertIsNotNone(cell, name)
            _obsc, total = eclipse._grid(KEY)[cell[0]][cell[1]]
            self.assertFalse(total, name)

    def test_the_map_agrees_with_the_page(self):
        """The map and the numbers come from one calculation, and this is
        what says so. A map built any other way could drift from the text
        beside it and look perfectly fine doing it."""
        for lat, lon in list(self.IN_PATH.values()) + list(self.OUTSIDE.values()):
            cell = eclipse.cell_of(KEY, lat, lon)
            obsc, total = eclipse._grid(KEY)[cell[0]][cell[1]]
            circ = besselian.local(KEY, lat, lon)
            self.assertEqual(total, circ["kind"] == "total", (lat, lon))
            # Same cell, not the same point: the grid samples the cell centre.
            self.assertLess(abs(obsc - circ["obscuration"]), 0.06, (lat, lon))


class TheTrackIsContinuous(unittest.TestCase):

    def test_it_is_not_broken_by_coastlines(self):
        """Totality is drawn over water as well as land. Without that the
        one line the map exists to show arrives as three disconnected
        smudges, because most of this track is over the north Atlantic."""
        rows = eclipse.render(KEY, color=False)
        with_track = [i for i, r in enumerate(rows) if eclipse.TOTAL_DOT in r]
        self.assertEqual(with_track, list(range(min(with_track),
                                                max(with_track) + 1)),
                         "the track skips a row")

    def test_it_crosses_most_of_the_map_top_to_bottom(self):
        rows = eclipse.render(KEY, color=False)
        hit = [i for i, r in enumerate(rows) if eclipse.TOTAL_DOT in r]
        self.assertGreater(len(hit), len(rows) * 0.7)


class TheMapIsTheRightShape(unittest.TestCase):

    def test_a_cell_is_about_as_wide_as_it_is_tall_on_screen(self):
        """A character cell is roughly twice as tall as it is wide, and a
        degree of longitude shrinks with latitude. Get those wrong together
        and the track is drawn at the wrong angle, which is the kind of
        error that looks like a design choice."""
        lat_top, lat_bot, lon_l, lon_r, w, h = eclipse.region(KEY)
        import math
        mid = math.radians((lat_top + lat_bot) / 2)
        km_per_col = (lon_r - lon_l) / w * 111.195 * math.cos(mid)
        km_per_row = (lat_top - lat_bot) / h * 111.195 / 2.0   # cell is 2:1
        self.assertLess(abs(km_per_col - km_per_row) / km_per_row, 0.15)

    def test_you_are_here_is_drawn_where_you_are(self):
        rows = eclipse.render(KEY, mark=(47.37, 8.54), color=False)
        row, col = eclipse.cell_of(KEY, 47.37, 8.54)
        self.assertEqual(rows[row][col], "✕")

    def test_a_place_off_the_map_is_simply_not_marked(self):
        # Sydney. Not an error, just outside the window this eclipse needs.
        self.assertIsNone(eclipse.cell_of(KEY, -33.87, 151.21))
        self.assertNotIn("✕", "".join(eclipse.render(KEY, mark=(-33.87, 151.21),
                                                     color=False)))


class ItDegradesRatherThanBreaks(unittest.TestCase):

    def test_an_eclipse_with_no_mask_draws_nothing(self):
        # Same policy as the /stats map: a page with no map beats a 500.
        self.assertFalse(eclipse.has_map("2027-08-02"))
        self.assertEqual(eclipse.render("2027-08-02"), [])
        self.assertIsNone(eclipse.region("2027-08-02"))


class TheLegendDescribesTheMapItIsUnder(unittest.TestCase):

    def test_it_is_read_off_the_bands_not_written_beside_them(self):
        text = eclipse.legend(color=False)
        for ceiling, _col, _ch in eclipse.BANDS[:-1]:
            self.assertIn(f"{ceiling * 100:.0f}%", text)
        self.assertIn("total", text)


class TheSunIsDrawnAsItLooks(unittest.TestCase):
    """The disc above the map. The Moon is deliberately not drawn: during a
    partial eclipse there is nothing up there but a Sun with a bite out of
    it, and a grey disc laid over it would be a diagram rather than a
    picture."""

    def test_a_partial_leaves_a_crescent_and_no_corona(self):
        rows = eclipse.disc_art(KEY, 47.3769, 8.5417, color=False)   # Zurich
        body = "".join(rows)
        self.assertIn("#", body)
        self.assertNotIn("·", body)

    def test_totality_is_a_hole_with_a_ring_round_it(self):
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)  # Oviedo
        body = "".join(rows)
        self.assertIn("·", body)          # corona
        self.assertNotIn("#", body)       # no Sun left to see
        # The middle has to be empty, or it is not a total eclipse.
        mid = rows[len(rows) // 2]
        self.assertEqual(mid[len(mid) // 2], " ")

    def test_the_corona_stays_inside_the_frame(self):
        """It is what sets the scale: drawn at the partial size the halo ran
        off the top and bottom and stopped reading as a ring."""
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        self.assertEqual(len(rows), eclipse.ART_ROWS)
        self.assertTrue(rows[0].strip(), "top row empty, corona is too small")
        self.assertTrue(rows[-1].strip(), "corona clipped at the bottom")

    def test_the_crescent_is_thicker_than_a_single_cell(self):
        """At 90% covered the surviving crescent is a tenth of the diameter.
        Drawn at the totality scale it came out as a dotted line with gaps,
        which is why the two sizes exist."""
        rows = eclipse.disc_art(KEY, 47.3769, 8.5417, color=False)
        widest = max(len(r) - len(r.lstrip()) and 0 or
                     sum(1 for ch in r if ch != " ") for r in rows)
        self.assertGreater(widest, 6)

    def test_nothing_is_drawn_where_the_sun_is_down(self):
        self.assertEqual(eclipse.disc_art(KEY, 35.6762, 139.6503), [])  # Tokyo

    def test_an_eclipse_with_no_elements_draws_nothing(self):
        self.assertEqual(eclipse.disc_art("2026-08-28", 47.37, 8.54), [])


if __name__ == "__main__":
    unittest.main()
