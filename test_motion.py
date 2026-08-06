"""Constellations are temporary, and this is what says so correctly.

The point of most of these is that a wrong propagation still draws a
plausible picture. A curve of the right length in the wrong place, a shape
that deforms by a believable amount in the wrong direction, a star that
speeds up when it should slow down -- none of it looks broken. So the checks
that matter here are the ones that cannot be satisfied by something merely
plausible: published close approaches, a published unit convention, and a
physical association that has to fall out of the data rather than be told to
it."""
import math
import unittest

from starlette.testclient import TestClient

import api
import motion
import objects
import server
import sky

BROWSER = {"accept": "text/html", "user-agent": "Mozilla/5.0"}
TERMINAL = {"user-agent": "curl/8.0"}


def distance_at(hr, years):
    """How far a star is at some epoch, straight from the shipped data."""
    m = motion._motions()[str(hr)]
    s = motion._stars()[hr]
    ra, de = math.radians(s["ra"] * 15.0), math.radians(s["de"])
    d = m["d"]
    ca, sa, cd, sd = math.cos(ra), math.sin(ra), math.cos(de), math.sin(de)
    r = (d * cd * ca, d * cd * sa, d * sd)
    e_ra, e_de = (-sa, ca, 0.0), (-sd * ca, -sd * sa, cd)
    r_hat = (cd * ca, cd * sa, sd)
    v_ra, v_de = motion.KAPPA * m["pmra"] * d, motion.KAPPA * m["pmde"] * d
    v = tuple((m["rv"] or 0.0) * r_hat[i] + v_ra * e_ra[i] + v_de * e_de[i]
              for i in range(3))
    p = tuple(r[i] + v[i] * years * motion.PC_PER_KMS_YR for i in range(3))
    return math.sqrt(sum(x * x for x in p))


class ThePropagationMatchesPublishedCloseApproaches(unittest.TestCase):
    """The one check a plausible-looking wrong answer cannot pass.

    Both of these are the perspective term on its own: a star's distance
    changing is exactly what a flat extrapolation of its proper motion knows
    nothing about, so getting the epoch of closest approach right is what
    says the three-dimensional propagation is real."""

    def closest(self, hr):
        best = min((distance_at(hr, t), t) for t in range(-200000, 200001, 200))
        return best[1], best[0]

    def test_alpha_centauri_is_closest_in_about_28000_years(self):
        # Published: about 28,000 years from now, about 0.95 parsecs.
        when, how_far = self.closest(5459)
        self.assertAlmostEqual(when / 1000.0, 28.0, delta=2.0)
        self.assertAlmostEqual(how_far, 0.95, delta=0.08)

    def test_sirius_is_closest_in_about_60000_years(self):
        # Published: about 60,000 years from now, 7.86 light years = 2.41 pc.
        when, how_far = self.closest(2491)
        self.assertAlmostEqual(when / 1000.0, 60.0, delta=3.0)
        self.assertAlmostEqual(how_far, 2.41, delta=0.08)


class TheProperMotionUnitsAreTheOnesWeThink(unittest.TestCase):
    """BSC5's RA proper motion could be arcsec/yr with cos(dec) applied, or
    seconds of time per year without it. Guessing wrong tilts every
    high-declination star by a factor of 15*cos(dec) and the result still
    looks like a constellation. Two stars with large, well-published motions
    settle it."""

    def test_61_cygni_and_groombridge_1830_read_as_published(self):
        # Through the builder rather than the shipped file: neither of these
        # is in an asterism, and the claim being tested is about which
        # columns of bsc5.dat get read and what they mean.
        import build_starmotion
        m = build_starmotion.read_bsc()
        # 61 Cygni A: mu_alpha* = 4.165, mu_delta = 3.249 arcsec/yr.
        a = m[8085]
        self.assertAlmostEqual(a["pmra"], 4.165, delta=0.05)
        self.assertAlmostEqual(a["pmde"], 3.249, delta=0.05)
        # Seconds of time per year would put it here instead.
        self.assertNotAlmostEqual(a["pmra"], 4.165 / 15.0 / math.cos(math.radians(38.7)),
                                  delta=0.2)
        # Groombridge 1830: 4.004 and -5.813.
        b = m[4550]
        self.assertAlmostEqual(b["pmra"], 4.004, delta=0.05)
        self.assertAlmostEqual(b["pmde"], -5.813, delta=0.05)


class TheBigDipperComesApartAtBothEnds(unittest.TestCase):
    """Five of its seven stars -- Merak, Phecda, Megrez, Alioth and Mizar --
    belong to the Ursa Major moving group, a real physical association with a
    shared space motion. Dubhe and Alkaid do not. Nothing in this repo is
    told that: it has to fall out of the proper motions."""

    def test_the_two_that_are_not_members_are_the_two_that_break_away(self):
        s = motion.summary("Big Dipper")
        names = {x["hr"]: x["n"] for x in sky._load("stars.json")}
        self.assertEqual(sorted(names[h] for h in s["apart"]),
                         ["Alkaid", "Dubhe"])
        self.assertEqual(sorted(names[h] for h in s["with_group"]),
                         ["Alioth", "Megrez", "Merak", "Mizar", "Phecda"])

    def test_it_is_a_direction_not_a_speed(self):
        """All seven move at a similar rate. What separates them is which
        way they are going, which is why a speed test would find nothing."""
        m = motion._motions()
        dipper = motion.members(motion.asterism("Big Dipper"))
        speeds = [math.hypot(m[str(h)]["pmra"], m[str(h)]["pmde"]) for h in dipper]
        self.assertLess(max(speeds) / min(speeds), 2.0)


class OrionIsTheContrast(unittest.TestCase):
    """Built from distant OB stars with tiny proper motions. If this ever
    starts moving, something has broken -- and a feature that showed every
    constellation falling apart would be telling a lie about the sky."""

    def test_orions_belt_barely_changes_in_fifty_thousand_years(self):
        s = motion.summary("Orion's Belt")
        self.assertLess(s["moved"], 0.5)
        self.assertLess(s["deform"], 5.0)

    def test_the_big_dipper_changes_more_than_orion(self):
        self.assertGreater(motion.summary("Big Dipper")["deform"],
                           motion.summary("Orion")["deform"] * 3)


class EveryShapeFitsItsOwnPanel(unittest.TestCase):
    """A star drawn outside the grid is silently dropped, and the panel then
    shows a constellation with a corner missing and no sign anything went
    wrong. This caught a capped field that had quietly discarded two thirds
    of the Spring Triangle."""

    def test_no_star_of_any_asterism_falls_outside_any_epoch(self):
        for a in sky._load("asterisms.json"):
            box = motion.field(a)
            _, _, rows = box
            for years in motion.EPOCHS:
                pos, _notes = motion.shape(a, years)
                px = motion.cells(pos, box)
                self.assertEqual(len(px), len(pos),
                                 f"{a['name']} at {years}: unprojectable star")
                for hr, (col, row) in px.items():
                    self.assertTrue(0 <= round(col) < motion.COLS,
                                    f"{a['name']} at {years}: col {col:.1f}")
                    self.assertTrue(0 <= round(row) < rows,
                                    f"{a['name']} at {years}: row {row:.1f}")

    def test_every_panel_is_the_same_shape_as_every_other_epoch(self):
        """Three panels of different sizes would make a shape look like it
        had grown when only the frame had."""
        for name in ("Big Dipper", "Scorpius", "Southern Cross"):
            a = motion.asterism(name)
            box = motion.field(a)
            sizes = {len(motion.panel(a, y, box, colour=False, trim=False))
                     for y in motion.EPOCHS}
            self.assertEqual(len(sizes), 1, name)


class TheDataIsComplete(unittest.TestCase):
    def test_every_asterism_star_has_a_motion(self):
        mots = motion._motions()
        for a in sky._load("asterisms.json"):
            for hr in motion.members(a):
                self.assertIn(str(hr), mots, f"{a['name']} HR {hr}")

    def test_almost_all_of_them_have_a_distance(self):
        """One star (Izar) has no Hipparcos distance and falls back to flat
        extrapolation. If that number ever grows, the fallback has stopped
        being an exception."""
        mots = motion._motions()
        without = [hr for hr, m in mots.items() if not m.get("d")]
        self.assertLessEqual(len(without), 1, without)

    def test_the_star_without_a_distance_is_named_on_the_page(self):
        """A silent fallback is the kind of thing that becomes a wrong
        number nobody ever questions."""
        a = motion.asterism("Kite")
        s = motion.summary("Kite")
        if s["flagged"]:
            caption = api.evolution_caption("Kite")
            self.assertIn("no measured distance", caption)


class ThePanelsAreOnTheAsterismPages(unittest.TestCase):
    def setUp(self):
        cm = TestClient(server.app)
        self.client = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_the_terminal_gets_the_drawing_not_a_link_to_it(self):
        got = self.client.get("/Big Dipper", headers=TERMINAL)
        self.assertIn(api.evolution_title("Big Dipper"), got.text)
        self.assertIn("-50,000 years", got.text)
        self.assertIn("+50,000 years", got.text)
        # Braille, which is the drawing itself rather than a description.
        self.assertTrue(any(0x2800 <= ord(ch) <= 0x28FF for ch in got.text))

    def test_the_browser_gets_the_same_section(self):
        got = self.client.get("/Big Dipper", headers=BROWSER)
        self.assertIn("obj-evo", got.text)
        self.assertIn("evolution.gif", got.text)

    def test_the_two_say_the_same_thing_about_it(self):
        """One caption function, so the page and the terminal cannot end up
        describing the same picture differently."""
        caption = api.evolution_caption("Big Dipper")
        self.assertIn("Dubhe", caption)
        for headers in (TERMINAL, BROWSER):
            got = self.client.get("/Big Dipper", headers=headers)
            self.assertIn(caption.split(",")[0], api.strip_ansi(got.text))

    def test_things_that_are_not_asterisms_get_no_section(self):
        for name in ("Vega", "Saturn", "M31"):
            got = self.client.get(f"/{name}", headers=TERMINAL)
            self.assertNotIn("The evolution of", got.text, name)

    def test_the_gif_is_served_and_is_a_gif(self):
        got = self.client.get("/Big Dipper/evolution.gif")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers["content-type"], "image/gif")
        self.assertEqual(got.content[:6], b"GIF89a")

    def test_the_gif_route_wins_against_the_place_route(self):
        """/{place}/{obj} would read "Big Dipper" as a place and
        "evolution.gif" as an object, and a 404 from this handler does not
        fall through -- so registration order is the whole of the fix."""
        names = [r.path for r in server.app.routes if hasattr(r, "path")]
        self.assertLess(names.index("/{obj}/evolution.gif"),
                        names.index("/{place}/{obj}"))

    def test_asking_for_a_shapeless_thing_says_so(self):
        got = self.client.get("/Vega/evolution.gif")
        self.assertEqual(got.status_code, 404)
        self.assertIn("asterism", got.text)

    def test_the_gif_is_counted(self):
        before = server._stat["evolution_gif"]
        self.client.get("/Orion/evolution.gif")
        self.assertEqual(server._stat["evolution_gif"], before + 1)
        self.assertIn("constellation evolution", server.stats_text())


class TheStarsAreNamedAndClickable(unittest.TestCase):
    def test_nearly_every_named_star_gets_its_name_on_the_panel(self):
        """A label is skipped when there is nowhere to put it that does not
        cover the drawing, which is right, but it should be rare."""
        stars = {s["hr"]: s.get("n") for s in sky._load("stars.json")}
        wanted = labelled = 0
        for a in sky._load("asterisms.json"):
            names = {stars[h] for h in motion.members(a) if stars.get(h)}
            drawn = "\n".join(motion.panels(a["name"], colour=False))
            wanted += len(names)
            labelled += sum(1 for n in names if n in drawn)
        self.assertGreater(labelled / wanted, 0.95, f"{labelled}/{wanted}")

    def test_a_label_never_covers_a_star(self):
        """Names are written after the stars and only into blank cells, so
        the count of star glyphs must survive labelling."""
        for name in ("Big Dipper", "Orion", "Scorpius", "Teapot"):
            a = motion.asterism(name)
            box = motion.field(a)
            for years in motion.EPOCHS:
                bare = motion.panel(a, years, box, colour=False, labels=False)
                done = motion.panel(a, years, box, colour=False, labels=True)
                for glyph in ("●", "•"):
                    self.assertEqual(
                        sum(l.count(glyph) for l in bare),
                        sum(l.count(glyph) for l in done),
                        f"{name} at {years}: {glyph} lost to a label")

    def test_the_browser_links_them_to_their_own_pages(self):
        markup = api.evolution_html("Big Dipper")
        for star in ("Dubhe", "Alkaid", "Mizar"):
            self.assertIn(f'<a href="/{star}">{star}</a>', markup)

    def test_the_names_survive_as_whole_words(self):
        """Colouring each cell separately made "Dubhe" five separate spans,
        so no name existed as a string to link, and every line carried about
        a kilobyte of escape sequences."""
        line = [l for l in motion.panels("Big Dipper", colour=True)
                if "Dubhe" in l]
        self.assertTrue(line, "the name is not contiguous in the coloured text")

    def test_the_terminal_gets_names_and_no_markup(self):
        got = motion.panels("Big Dipper", colour=False)
        self.assertIn("Dubhe", "\n".join(got))
        self.assertNotIn("<a", "\n".join(got))


class ItIsProperMotionAndSaysSo(unittest.TestCase):
    """Precession moves where a constellation appears and which star is the
    pole star. Proper motion changes the shape. Popular writing conflates
    them constantly, and a page that showed one while implying the other
    would be doing the same thing."""

    def test_the_caption_rules_precession_out(self):
        caption = api.evolution_caption("Cassiopeia's W")
        self.assertIn("not the sky turning", caption)

    def test_nothing_here_precesses(self):
        """Same epoch in, same position out, whatever the date is: this
        calculation has no idea what day it is and must not acquire one."""
        first = motion.shape(motion.asterism("Orion"), 0)[0]
        second = motion.shape(motion.asterism("Orion"), 0)[0]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
