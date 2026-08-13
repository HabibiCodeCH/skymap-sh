"""The eclipse map.

Every cell is computed from the Besselian elements rather than traced from a
published picture, so what these check is that the picture agrees with the
numbers: the track lands on the right countries, it is the right width, and
nothing on the map contradicts what the page will print in words.
"""
import math
import unittest

import besselian
import eclipse
import eclipse_page
import sky

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
        # A lunar date, which will never have one: there is no shadow track
        # on the ground to draw. This used to name 2027-08-02, which has a
        # map now that every solar eclipse in the table gets one.
        self.assertFalse(eclipse.has_map("2026-08-28"))
        self.assertEqual(eclipse.render("2026-08-28"), [])
        self.assertIsNone(eclipse.region("2026-08-28"))

    def test_every_solar_eclipse_we_can_compute_has_a_map(self):
        """build_eclipsemap.py is a build step, and a build step that has not
        been re-run is invisible until somebody opens the page it was for."""
        for key in besselian.ELEMENTS:
            self.assertTrue(eclipse.has_map(key), key)
            self.assertTrue(eclipse.render(key, color=False), key)


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

    def test_the_corona_fills_the_frame_without_being_cut_by_it(self):
        """It is what sets the scale: drawn at the partial size the halo ran
        off the top and bottom and stopped reading as a ring at all.

        Not every row, because the edge is deliberately ragged and the
        streamers only point where they point. Most of them, and nothing
        touching the very edge, which would mean something was clipped."""
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        self.assertEqual(len(rows), eclipse.ART_ROWS)
        drawn = [i for i, r in enumerate(rows) if r.strip()]
        self.assertGreaterEqual(len(drawn), eclipse.ART_ROWS - 3)
        self.assertLessEqual(min(drawn), 2)
        self.assertGreaterEqual(max(drawn), eclipse.ART_ROWS - 3)

    def test_the_corona_touches_the_moon(self):
        """It used to start at 1.13 Moon-radii, leaving a ring of black
        between the disc and the first dot. The inner corona is the
        brightest part of the real thing and it is on the limb."""
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        mid = rows[len(rows) // 2]
        drawn = [i for i, ch in enumerate(mid) if ch != " "]
        # Walking in from the left: dots, then the solid rim, then the hole,
        # with nothing between the rim and the hole.
        rim = mid.index("+")
        hole = mid.index(" ", rim)
        self.assertTrue(set(mid[rim:hole]) == {"+"}, mid)
        self.assertGreater(hole - rim, 1, "the bright rim is a single cell")
        self.assertLess(rim, hole)
        self.assertIn(rim, drawn)

    def test_the_corona_is_not_a_circle(self):
        """Streamers and a ragged edge. Dots on a perfect circle read as a
        circle however faint they are."""
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        reach = [max((len(r) / 2 - i for i, ch in enumerate(r) if ch != " "),
                     default=0) for r in rows]
        wide = [x for x in reach if x]
        self.assertGreater(max(wide) - min(wide), 4,
                           "the outer edge is the same distance out all round")

    def test_the_corona_thins_out_with_distance(self):
        """A band of even dots reads as an outline. This one is a glow."""
        rows = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        mid = rows[len(rows) // 2]
        left = mid[:mid.index("+")]
        near = sum(ch != " " for ch in left[len(left) // 2:])
        far = sum(ch != " " for ch in left[:len(left) // 2])
        self.assertGreater(near, far, "the corona is as dense at the edge "
                                      "as it is at the limb")

    def test_the_streamers_do_not_move_between_frames(self):
        """They are placed from the eclipse's date, not at random: spikes
        that jumped every frame would read as static, not as a corona."""
        a = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        b = eclipse.disc_art(KEY, 43.3619, -5.8494, color=False)
        self.assertEqual(a, b)
        self.assertNotEqual(eclipse._corona_phase(KEY),
                            eclipse._corona_phase("2027-08-02"))

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

    def test_nothing_is_drawn_where_the_eclipse_never_reaches(self):
        """The other half of the same question, and the half that shipped
        wrong: the Sun is up in Honolulu for the 2028 eclipse and the shadow
        is over Australia. The guard only tested the horizon, so the page
        drew a full, uneclipsed Sun under a heading saying the eclipse was
        not visible from there."""
        self.assertEqual(eclipse.disc_art("2028-07-22", 21.3069, -157.8583), [])

    def test_an_eclipse_with_no_elements_draws_nothing(self):
        self.assertEqual(eclipse.disc_art("2026-08-28", 47.37, 8.54), [])


def _bite_corner(rows):
    """Which corner of the drawn Sun the Moon has taken, as (h, v).

    Reads the picture rather than the geometry, which is the point: the
    geometry was right all along and the drawing still came out in the
    wrong quadrant.
    """
    filled = [(r, c) for r, row in enumerate(rows)
              for c, ch in enumerate(row) if ch != " "]
    if not filled:
        return None
    r0, r1 = min(r for r, _ in filled), max(r for r, _ in filled)
    c0, c1 = min(c for _, c in filled), max(c for _, c in filled)
    mid_r, mid_c = (r0 + r1) / 2.0, (c0 + c1) / 2.0
    # Where the Sun is missing: inside its own bounding box and blank. The
    # bite is the only thing that can do that, the disc being otherwise
    # solid. The box's four corners are blank as well -- a circle does not
    # fill a rectangle -- but those are symmetric about the centre and the
    # bite is not, so a centre of mass still lands on the bite.
    gaps = [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)
            if rows[r][c] == " "]
    gr = sum(r for r, _ in gaps) / len(gaps)
    gc = sum(c for _, c in gaps) / len(gaps)
    return ("right" if gc > mid_c else "left",
            "bottom" if gr > mid_r else "top")


class TheSunIsDrawnTheWayYouSeeIt(unittest.TestCase):
    """The disc is rotated to the observer's sky rather than left in the
    celestial frame.

    This is the bug that shipped. 12 August 2026 was drawn celestial north
    up, so over Ibiza the Moon took its first bite out of the top right of
    the Sun; anybody standing there watched it start bottom right. The Sun
    is 13 degrees up in the west from there at first contact, which leaves
    celestial north 53 degrees off vertical -- more than enough to move the
    bite a whole quadrant.
    """

    IBIZA = (38.91, 1.43)
    # Everywhere the shadow crosses Spain, so a sign error cannot hide
    # behind one lucky place.
    LANDFALL = {"Ibiza": (38.91, 1.43), "Palma": (39.57, 2.65),
                "Castellon": (39.99, -0.04), "Reus": (41.15, 1.10),
                "Zaragoza": (41.65, -0.89)}

    def _early(self, lat, lon, frac=0.08):
        """A frame just after first contact, where the bite is a clear notch
        on one side rather than most of the Sun gone."""
        circ = besselian.local(KEY, lat, lon)
        t = circ["first"] + (circ["last"] - circ["first"]) * frac
        return eclipse.disc_art(KEY, lat, lon, at=t, color=False,
                                sun_r=eclipse.SUN_R_PARTIAL)

    def test_the_bite_starts_bottom_right_over_ibiza(self):
        self.assertEqual(_bite_corner(self._early(*self.IBIZA)),
                         ("right", "bottom"),
                         "the Moon comes in from the wrong corner")

    def test_the_whole_landfall_agrees_on_the_corner(self):
        for name, (lat, lon) in self.LANDFALL.items():
            self.assertEqual(_bite_corner(self._early(lat, lon)),
                             ("right", "bottom"), name)

    def test_the_rotation_is_measured_not_assumed(self):
        """The two frames really do differ here, by enough to matter.
        Without this a rotation that quietly did nothing would sail through
        every test above."""
        circ = besselian.local(KEY, *self.IBIZA)
        t = circ["first"]
        el = besselian.ELEMENTS[KEY]
        rho_sin, rho_cos = besselian._observer(*self.IBIZA)
        s = besselian._state(el, t + el.dT / 3600.0 - el.t0,
                             rho_sin, rho_cos, self.IBIZA[1])
        when = eclipse._utc_at(KEY, t)
        su = sky.sun(sky.julian(when))
        dx, dy = eclipse._as_seen(s["u"], s["v"], su["ra"], su["dec"],
                                  self.IBIZA[0], self.IBIZA[1], when)
        n = math.hypot(s["u"], s["v"])
        cx, cy = -s["u"] / n, -s["v"] / n        # what used to be drawn
        turned = math.degrees(
            math.acos(max(-1.0, min(1.0, dx * cx + dy * cy))))
        self.assertGreater(turned, 30, "the drawing is barely rotated")
        self.assertLess(turned, 80)
        # Same side, opposite half -- which is exactly the symptom reported.
        self.assertGreater(dx, 0)
        self.assertGreater(cx, 0)
        self.assertGreater(dy, 0)                # y counts down: bottom
        self.assertLess(cy, 0)                   # the old drawing said top

    def test_the_caption_no_longer_promises_celestial_north(self):
        """The caption was honest about the old frame. Left alone it would
        be honest about a frame the drawing has stopped using, which is
        worse than either."""
        cap = eclipse_page.disc_caption({"kind": "total", "maximum": "20:31"})
        self.assertNotIn("North up", cap)
        self.assertIn("zenith up", cap)


class TheMoonIsDrawnTheWayYouSeeItToo(unittest.TestCase):
    """A lunar eclipse has the same problem and the same fix: the Earth's
    shadow arrives from a different corner depending on where the Moon is in
    your sky. Without a place the drawing stays celestial, which is what the
    shared social card wants -- it is fetched once and shown to everybody,
    so there is no "you" to draw it for."""

    # The total on 3 March 2026, which lunar.json has full circumstances for.
    LUNAR = "2026-03-03"
    # Partway into the umbra, not greatest eclipse. At greatest the umbra is
    # 2.7 Moon radii across and swallows the disc whole, so every rotation
    # draws the same solid copper circle and the test could not fail.
    PARTIAL_UT = 10.4

    def test_a_place_changes_the_drawing(self):
        plain = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False)
        here = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False,
                                lat=48.85, lon=2.35)
        self.assertTrue(plain)
        self.assertNotEqual(plain, here)

    def test_two_places_at_once_see_it_differently(self):
        """Sydney and Cape Town watch the same shadow at the same instant
        with the Moon on opposite sides of their skies."""
        a = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False,
                             lat=-33.87, lon=151.21)
        b = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False,
                             lat=-33.92, lon=18.42)
        self.assertTrue(a)
        self.assertNotEqual(a, b)

    def test_the_shadow_keeps_its_size(self):
        """Rotation moves the shadow, it does not resize it. The same number
        of cells has to be in umbra either way, or the rotation has eaten
        the distance along with the direction."""
        def shaded(rows):
            return sum(ch == eclipse.SHADE_GLYPH["umbra"]
                       for r in rows for ch in r)
        plain = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False)
        here = eclipse.moon_art(self.LUNAR, at=self.PARTIAL_UT, color=False,
                                lat=48.85, lon=2.35)
        self.assertGreater(shaded(plain), 0)
        # Not exactly equal: the shadow's edge lands on different cells at a
        # different angle, and the grid is 17 rows. Within a few percent.
        self.assertLess(abs(shaded(plain) - shaded(here)),
                        0.15 * shaded(plain))

    def test_no_place_keeps_the_shared_card_as_it_was(self):
        """The card path passes no place and must keep working unchanged."""
        rows = eclipse.moon_art(self.LUNAR, color=False)
        self.assertEqual(len(rows), eclipse.ART_ROWS)


class TheTrackIsWhereTheTotalityIs(unittest.TestCase):
    """track() walks the shadow axis and hands back the central line, and it
    is what chooses each eclipse's map window. It shipped with two signs
    flipped, which is the same as using -d: it produced a curve of the right
    shape, the right length and the right duration, mirrored onto the wrong
    part of the planet. Every point it returned was a partial eclipse and
    nothing said so, because nothing was checking.

    The check is the one that cannot be fooled by a plausible curve: ask the
    solver what each point sees."""

    def test_every_point_on_the_central_line_is_total(self):
        for key in ("2026-08-12", "2027-08-02", "2028-07-22"):
            pts = eclipse.track(key, step_minutes=1)
            self.assertGreater(len(pts), 20, key)
            for lat, lon, _t in pts:
                kind = besselian.local(key, lat, lon)["kind"]
                self.assertIn(kind, ("total", "annular"), f"{key} {lat},{lon}")

    def test_it_lands_where_nasa_puts_it(self):
        """Within 15 km of NASA's published central line. The path is 300 km
        wide, so this is a twentieth of it."""
        import math
        from test_besselian import NASA_PATH
        pts = eclipse.track("2026-08-12", step_minutes=0.25)
        for utc, lat, lon, _w, _d in NASA_PATH[3:]:      # away from the pole
            h, m = (int(v) for v in utc.split(":"))
            want = h + m / 60.0
            near = min(pts, key=lambda p: abs(p[2] % 24 - want))
            km = math.hypot(near[0] - lat,
                            (near[1] - lon) * math.cos(math.radians(lat))) * 111.2
            self.assertLess(km, 15.0, f"{utc}: {km:.1f} km out")


class TheAnimationIsClockedInLocalTime(unittest.TestCase):
    """Every other time on the page is local. A clock over the drawing that
    quietly ran in UT would be read as local by everyone, and in Zurich it is
    two hours out -- which is the difference between arriving in time and
    arriving after it finished."""

    ZURICH = (47.3769, 8.5417)

    def test_the_labels_shift_with_the_offset(self):
        _, ut = eclipse.disc_frames(KEY, *self.ZURICH)
        _, local = eclipse.disc_frames(KEY, *self.ZURICH, tz=2.0)
        self.assertTrue(ut and local)
        for a, b in zip(ut, local):
            ah, am = (int(x) for x in a.split(":"))
            bh, bm = (int(x) for x in b.split(":"))
            self.assertEqual(bh, (ah + 2) % 24)
            self.assertEqual(am, bm)

    def test_the_first_label_is_first_contact(self):
        # The clock and the "starts" cell in the heading are the same moment
        # read two ways, so they have to say the same thing.
        _, labels = eclipse.disc_frames(KEY, *self.ZURICH, tz=2.0)
        circ = besselian.local(KEY, *self.ZURICH)
        secs = round(((circ["first"] + 2.0) % 24) * 3600)
        self.assertEqual(labels[0], f"{secs // 3600:02d}:{secs // 60 % 60:02d}")


class TheExportIsDrawnOnTheSameGridAsThePage(unittest.TestCase):
    """The GIF renderer's default cell is 2.3 times as tall as it is wide,
    tuned for the chart's line glyphs. These discs are built for exactly 2.0
    (art.CELL), so exporting them on the default grid stretched every Sun 15%
    taller than the page it came from."""

    def test_the_cell_matches_the_art(self):
        import art
        import gif
        h = gif.cell_h_for(art.CELL)
        self.assertAlmostEqual(h / gif._CELL_W, art.CELL, delta=0.06)
        self.assertLess(h, gif._CELL_H)

    def test_an_exported_frame_is_as_tall_as_the_art_says(self):
        import art
        import gif
        frames, _ = eclipse.disc_frames(KEY, 38.91, 1.43)      # Ibiza
        img = gif.frame_to_image("\n".join(frames[0]), gif.cell_h_for(art.CELL))
        rows = len(frames[0])
        self.assertEqual(img.height - gif._WM_STRIP_H,
                         rows * gif.cell_h_for(art.CELL))


if __name__ == "__main__":
    unittest.main()
