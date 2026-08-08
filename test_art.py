"""The object-page portraits.

These are computed, not drawn, so they can be checked rather than eyeballed:
the geometry has right answers. The ones that matter are that every drawing
is the same box (or the page jumps between objects), that the tilt actually
comes from the real pole rather than being decorative, and that nothing but
plain ASCII ever reaches the page.
"""
import datetime as dt
import math
import re
import unittest

import api
import art
import objects
import sky


def visible(lines):
    return [api.strip_ansi(l) for l in lines]


def bbox(lines):
    """(x0, x1, y0, y1) of the non-blank cells."""
    cols, rows = [], []
    for r, l in enumerate(visible(lines)):
        idx = [c for c, ch in enumerate(l) if ch != " "]
        if idx:
            rows.append(r)
            cols += [min(idx), max(idx)]
    return min(cols), max(cols), min(rows), max(rows)


def planet(name, when=None):
    jd = sky.julian(when or dt.datetime(2026, 8, 6, 21, 0))
    ra, dec = objects._body_radec(name, jd)
    b, pa = objects.pole_geometry(name, {"ra": ra, "dec": dec})
    return art.planet_art(name, illuminated=art.STYLE_ILLUMINATED,
                          pole_b=b, pole_pa=pa)


class EveryDrawingIsTheSameBox(unittest.TestCase):
    """A fixed canvas is what lets the fact table below start on the same
    line whichever object you open, and what keeps a small star centred
    instead of sliding left as its own content shrinks."""

    def test_planets_all_fill_the_canvas_exactly(self):
        for name in art.PALETTES:
            lines = planet(name)
            self.assertEqual(len(lines), art.ROWS, name)
            for l in visible(lines):
                self.assertEqual(len(l), art.COLS, name)

    def test_stars_of_every_size_share_one_centre(self):
        centres = set()
        for cls, lum in (("B", "supergiant"), ("M", "supergiant"),
                         ("K", "giant"), ("A", "main-sequence star"),
                         ("G", "main-sequence star"), ("A", "white dwarf")):
            lines = art.star_art(cls, lum)
            x0, x1, y0, y1 = bbox(lines)
            centres.add(((x0 + x1) / 2, (y0 + y1) / 2))
        self.assertEqual(len(centres), 1, centres)

    def test_a_star_is_never_wider_than_the_canvas(self):
        for lum in art.STAR_SIZES:
            for l in visible(art.star_art("G", lum)):
                self.assertLessEqual(len(l), art.COLS, lum)

    def test_luminosity_orders_the_sizes(self):
        # Ordered, not to scale -- a supergiant is a thousand times a dwarf
        # and no canvas can show that -- but the sequence has to be right.
        widths = []
        for lum in ("white dwarf", "subdwarf", "main-sequence star",
                    "subgiant", "giant", "bright giant", "supergiant"):
            x0, x1, _y0, _y1 = bbox(art.star_art("G", lum))
            widths.append(x1 - x0)
        self.assertEqual(widths, sorted(widths))


class DrawnRound(unittest.TestCase):
    """A circle, not an ellipse. The art assumes a character cell exactly
    CELL times taller than it is wide, and OBJECT_CSS pins the line-height
    to match; if the two ever drift apart every planet turns into an egg."""

    def test_a_bare_disc_is_as_tall_as_it_is_wide(self):
        x0, x1, y0, y1 = bbox(planet("Venus"))
        width = x1 - x0 + 1
        height = (y1 - y0 + 1) * art.CELL
        self.assertLess(abs(width - height) / width, 0.12)

    def test_the_css_line_height_matches_the_cell_the_art_assumes(self):
        # Monospace glyphs run about 0.6em wide, so the line-height that
        # gives CELL is 0.6 * CELL. Hard-coded in OBJECT_CSS, checked here.
        self.assertIn(f"line-height:{0.6 * art.CELL:g}", api.OBJECT_CSS)


class TiltComesFromTheRealPole(unittest.TestCase):
    """The visible difference between the planets is not styling: it is the
    IAU pole direction of each one, and it has right answers."""

    def test_uranus_is_seen_almost_pole_on(self):
        # Tipped 98 degrees onto its side, and currently presenting a pole
        # to us -- which is why its rings read as a near-circle and its
        # bands as bullseyes rather than stripes.
        jd = sky.julian(dt.datetime(2026, 8, 6, 21, 0))
        ra, dec = objects._body_radec("Uranus", jd)
        b, _pa = objects.pole_geometry("Uranus", {"ra": ra, "dec": dec})
        self.assertGreater(abs(b), 60.0)

    def test_jupiter_is_seen_almost_equator_on(self):
        jd = sky.julian(dt.datetime(2026, 8, 6, 21, 0))
        ra, dec = objects._body_radec("Jupiter", jd)
        b, _pa = objects.pole_geometry("Jupiter", {"ra": ra, "dec": dec})
        self.assertLess(abs(b), 10.0)

    def test_rings_and_axis_are_the_same_measurement(self):
        # The rings sit in the equatorial plane, so any disagreement between
        # these two would be two copies of one calculation drifting apart.
        jd = sky.julian(dt.datetime(2026, 8, 6, 21, 0))
        for name in ("Saturn", "Uranus", "Neptune"):
            ra, dec = objects._body_radec(name, jd)
            b = {"ra": ra, "dec": dec}
            self.assertEqual(objects.ring_geometry(name, b),
                             objects.pole_geometry(name, b), name)

    def test_only_ringed_planets_report_ring_geometry(self):
        jd = sky.julian(dt.datetime(2026, 8, 6, 21, 0))
        ra, dec = objects._body_radec("Mars", jd)
        self.assertIsNone(objects.ring_geometry("Mars", {"ra": ra, "dec": dec}))

    def test_the_pole_tips_move_with_the_position_angle(self):
        # Same planet, same phase, two different pole angles: the bright
        # tips have to land somewhere different, or the tilt is decorative.
        a = art.planet_art("Jupiter", pole_b=0.0, pole_pa=0.0)
        b = art.planet_art("Jupiter", pole_b=0.0, pole_pa=60.0)
        self.assertNotEqual(a, b)


class RingsCrossTheGlobe(unittest.TestCase):
    """Front half over the planet, far half behind it. Without that a ring
    is a line struck through a disc rather than a ring around a ball."""

    def test_saturn_draws_ring_characters_on_both_sides_of_the_globe(self):
        rows = visible(planet("Saturn"))
        self.assertTrue(any("=" in r for r in rows))
        # The ring runs wider than the globe on the row through the middle.
        mid = rows[len(rows) // 2]
        self.assertIn("=", mid)

    def test_a_planet_with_no_rings_draws_none(self):
        for name in ("Venus", "Mars", "Jupiter", "Moon"):
            self.assertNotIn("=", "".join(visible(planet(name))), name)


class PrintableAsciiOnly(unittest.TestCase):
    """gif.py keeps a substitution table for characters the PNG font lacks
    (PNG_SUBSTITUTE). Art that is only ever plain ASCII cannot land in that
    trap, in a terminal, a browser, a PNG or a social card."""

    def test_nothing_exotic_reaches_the_page(self):
        blocks = [planet(n) for n in art.PALETTES]
        blocks += [art.star_art("G", "giant")]
        for lines in blocks:
            for ch in "".join(visible(lines)):
                self.assertTrue(32 <= ord(ch) < 127, repr(ch))


class TheMoonShowsItsRealPhase(unittest.TestCase):
    """The one body drawn from live data rather than a fixed light angle,
    because it is the one whose phase anyone watches."""

    def _lit(self, when):
        jd = sky.julian(when)
        mo = sky.moon(jd)
        lines = art.planet_art("Moon", illuminated=mo["illum"], pole_b=0.0,
                               pole_pa=20.0, lit_from_left=mo["age"] > 180)
        return sum(l.count("#") for l in visible(lines)), mo["illum"]

    def test_a_crescent_is_drawn_smaller_than_a_full_moon(self):
        # Same disc either way; what changes is how much of it is lit, and
        # the shadowed side is drawn in the shadow tone rather than dropped.
        new = dt.datetime(2026, 8, 6, 12, 0)
        # Walk a month and check the lit fraction actually moves the drawing.
        seen = set()
        for d in range(0, 29, 4):
            _cells, illum = self._lit(new + dt.timedelta(days=d))
            seen.add(round(illum, 2))
        self.assertGreater(len(seen), 4)

    def test_waxing_and_waning_are_mirror_images(self):
        left = art.planet_art("Moon", illuminated=0.35, pole_b=0.0,
                              pole_pa=0.0, lit_from_left=True)
        right = art.planet_art("Moon", illuminated=0.35, pole_b=0.0,
                               pole_pa=0.0, lit_from_left=False)
        # The silhouette is the same disc either way; what mirrors is which
        # side carries the shadow tone, so this has to compare the coloured
        # strings rather than the stripped ones.
        self.assertEqual(visible(left), visible(right))
        self.assertNotEqual(left, right)


class OnlyWhereThereIsSomethingToDraw(unittest.TestCase):

    def test_a_galaxy_gets_nothing_yet(self):
        self.assertEqual(art.art_for({"object": "Andromeda Galaxy",
                                      "kind": "galaxy"}), [])

    def test_a_star_is_drawn_from_its_spectral_type(self):
        lines = art.art_for({"object": "Betelgeuse", "kind": "star",
                             "star": {"spectral_type": "M1-2Ia-Iab",
                                      "description": "red supergiant"}})
        self.assertTrue(lines)
        self.assertEqual(len(lines), art.ROWS)

    def test_a_star_with_no_spectral_type_gets_nothing(self):
        self.assertEqual(art.art_for({"object": "x", "kind": "star",
                                      "star": {}}), [])

    def test_the_prefixed_spectral_types_still_find_their_class(self):
        # Catalogue entries like "gK5" and "sgB2" carry a prefix before the
        # class letter; taking the first character blindly would colour them
        # by "g" and "s", which are not classes at all.
        for sp, want in (("gK5", "K"), ("sgB2", "B"), ("K5III", "K")):
            self.assertTrue(art.star_art_for(sp, "giant"))


if __name__ == "__main__":
    unittest.main()


class AsterismPortraits(unittest.TestCase):
    """An asterism has no disc to light, so what gets drawn is its shape --
    which is the whole reason the thing has a name. On the horizon chart the
    Plough is seven stars among two hundred at whatever angle tonight holds
    it; on its own page it is a saucepan.

    Same source as the chart's own figures: asterisms.json for the chains,
    stars.json for the positions. Nothing hand-drawn."""

    def _names(self):
        import json
        return [c["name"] for c in json.load(open("asterisms.json"))]

    def _plain(self, lines):
        return [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines]

    def test_every_asterism_has_one(self):
        """28 of them, and a page with a picture-shaped hole is worse than a
        page that never promised one."""
        for name in self._names():
            self.assertTrue(art.asterism_art(name), name)

    def test_an_unknown_name_draws_nothing(self):
        self.assertEqual(art.asterism_art("Nonesuch"), [])
        self.assertEqual(art.asterism_art(""), [])
        self.assertEqual(art.asterism_art(None), [])

    def test_it_is_stars_joined_by_lines(self):
        for name in self._names():
            plain = self._plain(art.asterism_art(name))
            stars = sum(l.count("●") + l.count("•") + l.count("·") for l in plain)
            braille = sum(1 for l in plain for ch in l if 0x2800 <= ord(ch) <= 0x28FF)
            self.assertGreaterEqual(stars, 2, f"{name}: no stars drawn")
            self.assertGreaterEqual(braille, 3, f"{name}: no lines drawn")

    def test_the_two_star_pointers_are_drawn_rather_than_skipped(self):
        """The Pointers is Rigil Kentaurus, Hadar and the line between them.
        That line is the entire content of the name -- it points at the
        Southern Cross -- so a minimum of three stars would have thrown away
        the one asterism whose picture is only a line."""
        plain = self._plain(art.asterism_art("The Pointers"))
        self.assertTrue(plain)
        self.assertEqual(sum(l.count("●") for l in plain), 2)

    def test_it_fits_the_box(self):
        for name in self._names():
            plain = self._plain(art.asterism_art(name))
            self.assertLessEqual(len(plain), art.AST_ROWS, name)
            for l in plain:
                self.assertLessEqual(len(l), art.AST_COLS, f"{name}: {l!r}")

    def test_no_blank_row_at_the_top_or_bottom(self):
        """The margin is there to keep stars off the edge, not to pad the
        frame out with empty lines."""
        for name in self._names():
            plain = self._plain(art.asterism_art(name))
            self.assertTrue(plain[0].strip(), name)
            self.assertTrue(plain[-1].strip(), name)

    def test_the_shape_is_not_squashed(self):
        """A braille dot is half a cell wide and half a cell tall, so the
        sub-pixel grid is already square and must NOT get the CELL
        correction the planets need. With it, Cassiopeia's W came out as a
        shallow V.

        Measured on Orion's Belt, which is three stars in a near-straight
        line about 3 degrees long: on a square grid its drawn length is many
        times its drawn thickness, and halving the vertical scale would tilt
        and shorten it."""
        plain = self._plain(art.asterism_art("Orion's Belt"))
        rows = len(plain)
        cols = max(len(l) for l in plain)
        # The belt is a long thin thing however it is rotated; if the aspect
        # were halved it would fit in the box with room to spare instead of
        # filling one axis of it.
        self.assertGreaterEqual(max(cols / art.AST_COLS, rows / art.AST_ROWS), 0.8)

    def test_it_reaches_the_object_page_through_art_for(self):
        self.assertTrue(art.art_for(dict(object="Big Dipper", kind="asterism")))
        self.assertEqual(art.art_for(dict(object="Big Dipper", kind="star",
                                          star={})), [])

    def test_a_planet_is_unaffected(self):
        """The asterism branch sits above the PALETTES lookup, so this is the
        check that it did not swallow anything on the way past."""
        self.assertTrue(art.art_for(dict(object="Saturn", kind="planet")))
        self.assertEqual(art.art_for(dict(object="Nowhere", kind="planet")), [])


class ShowerPortraits(unittest.TestCase):
    """A radiant is a point in empty sky, so the drawing is of the shower
    coming out of it, over the real stars around it. The Perseids are the one
    event of the year a lot of people go outside for and the page had no
    picture at all."""

    def _showers(self):
        import json
        return json.load(open("showers.json"))

    def _plain(self, lines):
        return [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines]

    def test_every_shower_has_one(self):
        for sh in self._showers():
            self.assertTrue(art.shower_art(sh["name"]), sh["name"])

    def test_the_names_people_type_all_resolve(self):
        """"Perseids", "Perseid" and the canonical "Perseids radiant" are the
        three forms sky.py already accepts, and the object pages hand over the
        third one."""
        first = art.shower_art("Perseids")
        for alias in ("Perseid", "Perseids radiant", "PERSEIDS", " perseids "):
            self.assertEqual(art.shower_art(alias), first, alias)

    def test_an_unknown_name_draws_nothing(self):
        self.assertEqual(art.shower_art("Nonesuch"), [])
        self.assertEqual(art.shower_art(""), [])
        self.assertEqual(art.shower_art(None), [])

    def test_the_radiant_is_marked_and_nothing_covers_it(self):
        """It is the one thing in the frame that is not a star. Drawn before
        the stars, a star wins the cell and hides the subject."""
        for sh in self._showers():
            plain = self._plain(art.shower_art(sh["name"]))
            self.assertEqual(sum(l.count("+") for l in plain), 1, sh["name"])

    def test_it_is_stars_and_trails(self):
        for sh in self._showers():
            plain = self._plain(art.shower_art(sh["name"]))
            stars = sum(l.count("●") + l.count("•") + l.count("·") for l in plain)
            braille = sum(1 for l in plain for ch in l
                          if 0x2800 <= ord(ch) <= 0x28FF)
            self.assertGreaterEqual(stars, 10, f"{sh['name']}: empty sky")
            self.assertGreaterEqual(braille, 15, f"{sh['name']}: no meteors")

    def test_a_sparse_patch_of_sky_still_gets_its_stars(self):
        """Some radiants sit in genuinely empty sky. The magnitude limit opens
        a step at a time rather than leaving a portrait with four stars in
        it, which is why the Orionids and the Taurids look like anything."""
        for name in ("Orionids", "Northern Taurids", "Southern Taurids"):
            plain = self._plain(art.shower_art(name))
            stars = sum(l.count("●") + l.count("•") + l.count("·") for l in plain)
            self.assertGreaterEqual(stars, art.SHOWER_MIN_STARS - 2, name)

    def test_a_busier_shower_gets_more_meteors(self):
        """The count carries the rate. Not the rate itself -- 150 streaks in a
        45-column box is a smear -- but a reader comparing two pages should
        see the ordering."""
        def trails(name):
            return sum(1 for l in self._plain(art.shower_art(name))
                       for ch in l if 0x2800 <= ord(ch) <= 0x28FF)
        self.assertGreater(trails("Geminids"), trails("Draconids"))
        self.assertGreater(trails("Perseids"), trails("Ursids"))

    def test_it_fits_the_box(self):
        for sh in self._showers():
            plain = self._plain(art.shower_art(sh["name"]))
            self.assertLessEqual(len(plain), art.SHOWER_ROWS, sh["name"])
            for l in plain:
                self.assertLessEqual(len(l), art.SHOWER_COLS, sh["name"])

    def test_it_is_the_same_picture_every_time(self):
        """Seeded off the shower's own name, not the global generator, so the
        terminal, the browser and the PNG export agree -- and so a page does
        not redraw itself differently on every reload."""
        for sh in self._showers()[:4]:
            self.assertEqual(art.shower_art(sh["name"]),
                             art.shower_art(sh["name"]), sh["name"])

    def test_it_reaches_the_object_page_through_art_for(self):
        self.assertTrue(art.art_for(dict(object="Perseids radiant",
                                         kind="radiant")))


class TheGalaxyFromOutside(unittest.TestCase):
    """The one drawing here that is not computed from a catalogue: there is no
    photograph of the Milky Way from outside it, so the shape is a model. Two
    major arms off the ends of the bar, after the Spitzer star counts."""

    def _plain(self, lines):
        return [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines]

    def test_it_draws(self):
        self.assertTrue(art.milkyway_art())

    def test_the_sun_is_marked(self):
        """The one measured thing in the frame, and the only reason to draw
        the Galaxy from a viewpoint nobody has ever had."""
        plain = self._plain(art.milkyway_art())
        self.assertEqual(sum(l.count("☉") for l in plain), 1)
        self.assertEqual(sum(l.count("☉")
                             for l in self._plain(art.milkyway_art(sun=False))), 0)

    def test_the_sun_sits_off_centre_by_its_real_distance(self):
        """8.2 kpc out of a 16 kpc disc, so it is about halfway to the rim --
        not at the centre, which is the single most common thing people get
        wrong about where we live."""
        plain = self._plain(art.milkyway_art())
        row = next(i for i, l in enumerate(plain) if "☉" in l)
        # Drawn below the centre, as in the NASA rendering the structure
        # follows. Blank rows are trimmed off the top, so measure against the
        # drawn extent rather than against MW_ROWS.
        self.assertGreater(row, len(plain) * 0.55)

    def test_it_fits_the_box(self):
        plain = self._plain(art.milkyway_art())
        self.assertLessEqual(len(plain), art.MW_ROWS)
        for l in plain:
            self.assertLessEqual(len(l), art.MW_COLS)

    def test_the_arms_are_continuous(self):
        """Drawn as scattered points an arm reads as noise. The ridge is laid
        down unconditionally and the scatter goes round it, which is the
        difference between the third attempt at this and the fourth."""
        plain = self._plain(art.milkyway_art())
        braille = sum(1 for l in plain for ch in l if 0x2800 <= ord(ch) <= 0x28FF)
        self.assertGreater(braille, 120)

    def test_it_is_the_same_picture_every_time(self):
        self.assertEqual(art.milkyway_art(), art.milkyway_art())

    def test_it_reaches_the_object_page_through_art_for(self):
        self.assertTrue(art.art_for(dict(object="Milky Way", kind="milkyway")))
