#!/usr/bin/env python3
"""Tests for sky.py's ISS pass detection.

Run:  python3 test_sky.py
"""
import unittest
import datetime as dt
import sky


class SidePanelDefaultIsOff(unittest.TestCase):
    """render_linear's side_panel param defaults to False -- every caller
    that doesn't know about it (the CLI included) must keep drawing the
    zenith inset inline below the sweep, exactly as before this existed."""

    def test_default_appends_the_inset_inline_and_exposes_no_zenith_lines(self):
        art, st = sky.render_linear(dt.datetime(2026, 7, 30, 22, 0), 47.3769, 8.5417)
        self.assertIn("zenith 70-90", art)
        self.assertIsNone(st["zenith_lines"])

    def test_side_panel_true_pulls_the_inset_out_instead(self):
        art, st = sky.render_linear(dt.datetime(2026, 7, 30, 22, 0), 47.3769, 8.5417,
                                    side_panel=True)
        self.assertNotIn("zenith 70-90", art)
        self.assertIsNotNone(st["zenith_lines"])
        self.assertTrue(any("zenith 70-90" in l for l in st["zenith_lines"]))


class IssDarknessCheck(unittest.TestCase):
    def test_no_daylight_passes_reported(self):
        """Every point in every returned pass must have the observer's own sky
        dark enough to actually see something this bright. Guards against the
        bug where iss_track() checked the satellite was sunlit but never
        checked whether the observer was in darkness, so it reported passes
        as visible in broad daylight."""
        lat, lon = 47.3769, 8.5417
        now = dt.datetime.utcnow()
        checked_any = False
        for h in range(48):
            t = now + dt.timedelta(hours=h * 0.5)
            track, _err = sky.iss_track("demo.tle", t, lat, lon)
            if not track:
                continue
            checked_any = True
            for minutes_from_start, _alt, _az in track:
                point_t = t + dt.timedelta(minutes=minutes_from_start)
                jd = sky.julian(point_t)
                su = sky.sun(jd)
                lst = (sky.gmst_hours(jd) + lon / 15.0) % 24
                sun_alt, _ = sky.altaz(su["ra"], su["dec"], lat, lst)
                self.assertTrue(
                    sky.dark_enough(sun_alt, -3.5),
                    f"pass point at +{minutes_from_start}min from {t} has "
                    f"observer sun_alt={sun_alt:.1f}, not dark enough")
        self.assertTrue(checked_any,
                        "found no passes at all across 24h -- widen the scan")


class WidthParameter(unittest.TestCase):
    """render_linear/render's width= should rescale both dimensions by the
    same factor (aspect stays put) and clamp to a sane range."""

    def test_render_linear_hits_the_requested_width(self):
        # Lines carry a short altitude-label prefix (e.g. " 10° ") ahead of the
        # W-wide grid itself, so the printed width is W plus a few chars, not
        # exactly W -- allow for that rather than asserting an exact bound.
        t = dt.datetime(2026, 7, 30, 22, 0)
        art, _st = sky.render_linear(t, 47.3769, 8.5417, color=False, width=80)
        widths = [len(l) for l in art.split("\n") if l.strip()]
        self.assertLessEqual(max(widths), 90)
        self.assertGreater(max(widths), 60)   # not collapsed to nothing

    def test_render_linear_clamps_absurd_width(self):
        t = dt.datetime(2026, 7, 30, 22, 0)
        art, _st = sky.render_linear(t, 47.3769, 8.5417, color=False, width=99999)
        widths = [len(l) for l in art.split("\n") if l.strip()]
        # Off the constant rather than off a number, because the ceiling is a
        # budget that gets revisited and this test is about the clamp holding
        # at all, not about where it currently sits. The slack is the left
        # margin and a label or two reaching past the last column.
        self.assertLessEqual(max(widths), sky.CHART_WIDTH_MAX + 15)

    def test_render_linear_wider_request_gives_taller_output(self):
        # Both dimensions scale by the same factor to preserve aspect, so a
        # wider request should also mean more rows -- fixed overhead lines
        # (separator, compass labels) mean the ratio isn't exactly W_wide/W_narrow,
        # so this checks direction and sane bounds rather than a precise ratio.
        t = dt.datetime(2026, 7, 30, 22, 0)
        art_narrow, _st = sky.render_linear(t, 47.3769, 8.5417, color=False,
                                            width=80, inset=False)
        art_wide, _st = sky.render_linear(t, 47.3769, 8.5417, color=False,
                                          width=160, inset=False)
        rows_narrow = len([l for l in art_narrow.split("\n") if l.strip()])
        rows_wide = len([l for l in art_wide.split("\n") if l.strip()])
        self.assertGreater(rows_wide, rows_narrow)
        self.assertTrue(8 < rows_narrow < 20)
        self.assertTrue(16 < rows_wide < 30)


class DeepSkyOverlay(unittest.TestCase):
    """deepsky.json objects only appear when a dso_limit is explicitly
    passed -- most of them need binoculars, so the layer must stay off by
    default rather than cluttering the naked-eye chart."""

    def test_off_by_default(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        self.assertEqual(sky.deepsky_visible(None, jd, 47.3769, lst), [])

    def test_respects_the_magnitude_cutoff(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        visible = sky.deepsky_visible(11.0, jd, 47.3769, lst)
        self.assertTrue(visible)
        self.assertTrue(all(o["m"] <= 11.0 for o, _a, _z in visible))
        self.assertTrue(all(a > 0 for _o, a, _z in visible))

    def test_render_linear_draws_a_dso_glyph_when_enabled(self):
        t = dt.datetime(2026, 7, 30, 22, 0)
        off, _st = sky.render_linear(t, 47.3769, 8.5417, color=False)
        on, _st = sky.render_linear(t, 47.3769, 8.5417, color=False, dso_limit=11.0)
        dso_chars = set(sky.DSO_GLYPH[k][0] for k in sky.DSO_GLYPH)
        self.assertFalse(any(ch in off for ch in dso_chars))
        self.assertTrue(any(ch in on for ch in dso_chars))


class StarsVisible(unittest.TestCase):
    """stars_visible() is the same star filter the chart uses internally,
    pulled out as its own function so the mobile 3D sphere view can get
    positions without drawing ASCII -- these tests guard against the
    extraction drifting from what render_linear() actually draws."""

    def test_respects_the_magnitude_cutoff(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        visible = sky.stars_visible(2.0, jd, 47.3769, lst)
        self.assertTrue(visible)
        self.assertTrue(all(s["m"] <= 2.0 for s, _a, _z in visible))
        self.assertTrue(all(a > 0 for _s, a, _z in visible))

    def test_matches_the_star_count_the_chart_draws(self):
        """Against render_linear now that the disc view is gone. It is the
        same set either way -- checked before the swap, not assumed."""
        when = dt.datetime(2026, 7, 30, 22, 0)
        lat, lon, mag_limit = 47.3769, 8.5417, 4.2
        _art, st = sky.render_linear(when, lat, lon, mag_limit=mag_limit)
        jd = sky.julian(when)
        lst = (sky.gmst_hours(jd) + lon / 15.0) % 24
        visible = sky.stars_visible(mag_limit, jd, lat, lst)
        self.assertEqual({s["hr"] for s, _a, _z in visible},
                         {s["hr"] for s, _a, _z in st["visible"]})

    def test_above_horizon_false_includes_stars_below_the_horizon(self):
        # The 3D sphere view's "full sphere" mode -- the far side of the sky
        # is night for someone even when it's day here, so it isn't dropped.
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        visible = sky.stars_visible(4.2, jd, 47.3769, lst, above_horizon=False)
        self.assertTrue(any(a < 0 for _s, a, _z in visible))
        # Nothing brighter than the cutoff got dropped along the way either.
        above_only = sky.stars_visible(4.2, jd, 47.3769, lst, above_horizon=True)
        self.assertTrue({s["hr"] for s, _a, _z in above_only} <=
                        {s["hr"] for s, _a, _z in visible})


class AsterismLinesVisible(unittest.TestCase):
    """asterism_lines_visible() is the geometry half of render()'s
    constellation-lines block, without the ASCII-projection parts that only
    matter when drawing glyphs into a flat grid."""

    def test_segments_are_alt_az_pairs(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        lines = sky.asterism_lines_visible(jd, 47.3769, lst)
        self.assertTrue(lines)
        for con in lines:
            self.assertIn("name", con)
            self.assertTrue(con["segments"])
            for seg in con["segments"]:
                self.assertEqual(len(seg), 2)
                for alt, az in seg:
                    self.assertIsInstance(alt, float)
                    self.assertIsInstance(az, float)
                    self.assertGreater(alt, 0)

    def test_mostly_below_horizon_asterisms_are_omitted(self):
        # The Southern Cross never clears the horizon from Zurich's
        # latitude -- render()'s own "mostly below/grazing" gate must drop
        # it here exactly as it does for the ASCII chart.
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        lines = sky.asterism_lines_visible(jd, 47.3769, lst)
        names = {con["name"] for con in lines}
        self.assertNotIn("Southern Cross", names)

    def test_above_horizon_false_includes_the_southern_cross_too(self):
        # Full-sphere mode -- the same "mostly below the horizon" gate that
        # rightly hides it from the ASCII chart shouldn't apply here.
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        lines = sky.asterism_lines_visible(jd, 47.3769, lst, above_horizon=False)
        names = {con["name"] for con in lines}
        self.assertIn("Southern Cross", names)
        # And its points are allowed to sit below the horizon now.
        cross = next(c for c in lines if c["name"] == "Southern Cross")
        alts = [pt[0] for seg in cross["segments"] for pt in seg]
        self.assertTrue(any(a < 0 for a in alts))


class FindTextWrapWidth(unittest.TestCase):
    """find_text() used to hard-wrap at a fixed 76 columns regardless of
    how wide the chart it sits under actually is -- a sentence could break
    mid-way well short of the space available once ?panel=1 gave the
    ordinary view's own prose (sky_read) the full effective width."""

    def setUp(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 21, 10))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        self.target = sky.resolve_target("Venus", jd, 47.3769, lst)

    def test_default_wraps_at_76(self):
        text = sky.find_text(self.target, [], 47.3769)
        for line in text.split("\n"):
            self.assertLessEqual(len(line), 76)

    def test_wider_wrap_width_keeps_a_sentence_on_one_line(self):
        narrow = sky.find_text(self.target, [], 47.3769, wrap_width=76)
        wide = sky.find_text(self.target, [], 47.3769, wrap_width=160)
        self.assertGreater(narrow.count("\n"), wide.count("\n"))
        for line in wide.split("\n"):
            self.assertLessEqual(len(line), 160)


class FindResolvesDeepSkyObjects(unittest.TestCase):
    """resolve_target() used to only know planets/Sun/Moon/stars/asterisms --
    ?find=M31 or ?find=Andromeda+Galaxy fell through to "Don't know" even
    though the exact same object was already drawn on the chart under
    ?dso=1. It should answer to its Messier number, its hand-curated common
    name (build_deepsky.py's COMMON_NAMES), and its raw NGC id."""

    def setUp(self):
        self.jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        self.lst = (sky.gmst_hours(self.jd) + 8.5417 / 15.0) % 24

    def test_messier_number(self):
        t = sky.resolve_target("M31", self.jd, 47.3769, self.lst)
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "Andromeda Galaxy")
        self.assertEqual(t["kind"], "galaxy")

    def test_common_name_case_insensitive(self):
        t = sky.resolve_target("andromeda galaxy", self.jd, 47.3769, self.lst)
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "Andromeda Galaxy")

    def test_ngc_id_still_resolves_an_object_with_a_nicer_name(self):
        t = sky.resolve_target("NGC224", self.jd, 47.3769, self.lst)
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "Andromeda Galaxy")

    def test_object_with_no_common_name_answers_to_its_ngc_id(self):
        t = sky.resolve_target("NGC1980", self.jd, 47.3769, self.lst)
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "NGC1980")

    def test_unknown_deep_sky_query_still_returns_none(self):
        self.assertIsNone(sky.resolve_target("Not A Real Galaxy", self.jd, 47.3769, self.lst))


class QuadrantGrid(unittest.TestCase):
    """?quadrant= crops a request to one lettered cell of the same grid every
    time -- no server-side state, so the grid math itself has to be exact
    and deterministic."""

    def test_cells_tile_the_full_window_exactly(self):
        cells = sky.quadrant_grid(180.0, 360.0, 0.0, 70.0)
        self.assertEqual([c["letter"] for c in cells],
                         list(sky.LETTERS[:len(cells)]))
        total_az = sum(c["az_span"] for c in cells if c["alt_lo"] == cells[0]["alt_lo"])
        self.assertAlmostEqual(total_az, 360.0, places=6)
        alt_los = sorted({round(c["alt_lo"], 6) for c in cells})
        alt_his = sorted({round(c["alt_hi"], 6) for c in cells})
        self.assertAlmostEqual(min(alt_los), 0.0, places=6)
        self.assertAlmostEqual(max(alt_his), 70.0, places=6)

    def test_render_linear_crops_to_the_requested_cell(self):
        t = dt.datetime(2026, 7, 30, 22, 0)
        _art, base_st = sky.render_linear(t, 47.3769, 8.5417, color=False, quadrants=True)
        cell = base_st["quad_cells"][0]
        _art, crop_st = sky.render_linear(t, 47.3769, 8.5417, color=False, quadrants=True,
                                          quadrant=cell["letter"])
        self.assertEqual(crop_st["quad_applied"], cell["letter"])
        self.assertAlmostEqual(crop_st["span"], cell["az_span"], places=6)
        self.assertEqual(crop_st["quad_cells"], [])   # cropped: no overlay on itself

    def test_no_grid_without_opting_in(self):
        # render_linear's other callers (the daytime Sun's-arc view,
        # compose_frame) never pass quadrants=True, so quad_cells must stay
        # empty for them even though target is None -- regression test for
        # the grid overlay leaking into every horizon-linear render.
        t = dt.datetime(2026, 7, 30, 22, 0)
        _art, st = sky.render_linear(t, 47.3769, 8.5417, color=False)
        self.assertEqual(st["quad_cells"], [])

    def test_unknown_letter_falls_back_to_the_full_view(self):
        t = dt.datetime(2026, 7, 30, 22, 0)
        _art, st = sky.render_linear(t, 47.3769, 8.5417, color=False, quadrants=True,
                                     quadrant="ZZ")
        self.assertIsNone(st["quad_applied"])
        self.assertEqual(st["quad_error"], "ZZ")
        self.assertTrue(st["quad_cells"])   # still shows the base grid to pick from


class MoonPhaseGlyph(unittest.TestCase):
    """moon_glyph() picks a shape from the Moon's real elongation from the
    Sun -- the phase math itself, not just the character lookup."""

    def test_glyph_at_each_canonical_age_northern(self):
        expect = {0: "○", 45: "◔", 90: "◑", 135: "◕", 180: "●",
                  225: "◕", 270: "◐", 315: "◔"}
        for age, glyph in expect.items():
            self.assertEqual(sky.moon_glyph(age), glyph, f"age={age}")

    def test_quarter_moons_flip_for_the_southern_hemisphere(self):
        # The two true half-circle glyphs are the one pair that can be
        # mirrored exactly -- crescent/gibbous have no matching mirrored
        # quadrant character in Unicode, so those stay symmetric either way.
        self.assertEqual(sky.moon_glyph(90, lat=-30), "◐")
        self.assertEqual(sky.moon_glyph(270, lat=-30), "◑")

    def test_new_and_full_are_unaffected_by_hemisphere(self):
        self.assertEqual(sky.moon_glyph(0, lat=-30), "○")
        self.assertEqual(sky.moon_glyph(180, lat=-30), "●")

    def test_waxing_and_waning_quarters_are_now_visually_distinct(self):
        self.assertNotEqual(sky.moon_glyph(90), sky.moon_glyph(270))

    def test_real_first_and_last_quarter_dates_are_correctly_identified(self):
        # 2026-02-24 20:00 UTC is a real first-quarter moon (~90 deg
        # elongation) -- a live check against the actual ephemeris, not
        # just the glyph lookup table in isolation.
        jd = sky.julian(dt.datetime(2026, 2, 24, 20, 0))
        age = sky.moon(jd)["age"]
        self.assertAlmostEqual(age, 90, delta=5)
        self.assertEqual(sky.phase_name(age), "first quarter")

    def test_default_horizon_chart_draws_the_real_phase_not_a_fixed_circle(self):
        # Regression test: render_linear() used to hardcode a full circle
        # for the Moon regardless of its actual phase -- moon_glyph() was
        # only ever reached by the disc view and the text summary, not by
        # the default panorama chart everyone actually sees.
        # (Not asserting "●" is absent -- that's also the bright-star glyph,
        # so it could legitimately appear from a bright star sharing the sky.)
        t = dt.datetime(2026, 2, 24, 20, 0)
        art, _st = sky.render_linear(t, 47.3769, 8.5417, color=False)
        self.assertIn("◑", art)


class MilkyWayGrid(unittest.TestCase):
    """The band comes from a density grid baked by build_milkyway.py. These
    check it against the sky rather than against itself -- the galactic
    poles are the emptiest sky there is, and the brightest cells have to sit
    where the galactic centre actually is."""

    def test_both_galactic_poles_are_empty(self):
        # (192.86, +27.13) and its opposite. If the grid were rotated or
        # flipped, these are the first places it would show.
        self.assertEqual(sky.milkyway_at(192.86 / 15, 27.13), 0)
        self.assertEqual(sky.milkyway_at((192.86 + 180) / 15 % 24, -27.13), 0)

    def test_the_brightest_cells_sit_on_the_galactic_centre(self):
        g = sky._load("milkyway.json")
        pts = [(c * g["ra_step"] / 15, 90 - r * g["dec_step"])
               for r, row in enumerate(g["rows_data"])
               for c, ch in enumerate(row) if ch == "5"]
        self.assertTrue(pts)
        ra = sum(p[0] for p in pts) / len(pts)
        dec = sum(p[1] for p in pts) / len(pts)
        # Sgr A* is at RA 17.76h, Dec -29.0.
        self.assertAlmostEqual(ra, 17.76, delta=0.4)
        self.assertAlmostEqual(dec, -29.0, delta=3.0)

    def test_the_band_runs_through_the_constellations_it_must(self):
        # Cygnus, Cassiopeia and Sagittarius are in the Milky Way; the Big
        # Dipper and Bootes are at the north galactic pole and cannot be.
        for name, ra, dec in (("Deneb/Cygnus", 20.69, 45.28),
                              ("Cassiopeia", 0.95, 60.72),
                              ("Sagittarius", 18.4, -25.4)):
            self.assertGreater(sky.milkyway_at(ra, dec), 0, name)
        for name, ra, dec in (("Big Dipper", 12.9, 55.96),
                              ("Arcturus/Bootes", 14.26, 19.18)):
            self.assertEqual(sky.milkyway_at(ra, dec), 0, name)

    def test_altaz_round_trips_back_to_the_same_ra_dec(self):
        # radec_from_altaz is the inverse of altaz, and the band is looked
        # up once per cell through it -- a sign error would put the whole
        # Milky Way somewhere else entirely.
        jd = sky.julian(dt.datetime(2026, 8, 5, 22, 0))
        lst = (sky.gmst_hours(jd) + 6.15 / 15.0) % 24
        for ra, dec in ((17.76, -29.0), (5.0, 45.0), (12.0, -60.0)):
            alt, az = sky.altaz(ra, dec, 46.2, lst)
            ra2, dec2 = sky.radec_from_altaz(alt, az, 46.2, lst)
            self.assertAlmostEqual(dec2, dec, places=6)
            self.assertAlmostEqual((ra2 - ra + 12) % 24 - 12, 0, places=6)

    def test_unprecess_undoes_precess(self):
        jd = sky.julian(dt.datetime(2026, 8, 5, 22, 0))
        ra, dec = 17.76, -29.0
        r2, d2 = sky.unprecess(*sky.precess(ra, dec, jd), jd)
        # Within an arcsecond or two: mirroring the epoch negates the
        # elapsed years exactly but leaves the rate coefficients evaluated
        # at the mirrored date, so this is an inverse to well inside the
        # half-degree the grid is sampled at, not to machine precision.
        self.assertLess(abs(d2 - dec) * 3600, 10)
        self.assertLess(abs((r2 - ra + 12) % 24 - 12) * 15 * 3600, 10)


class MilkyWayOnTheChart(unittest.TestCase):
    """Drawn into the soft layer, so it can never take a cell a star, a
    planet or a label wanted."""

    WHEN = dt.datetime(2026, 8, 5, 3, 0)
    ATACAMA = (-24.63, -70.40)

    def band_cells(self, art):
        rows = art.split("\n")
        cut = next((i for i, l in enumerate(rows) if l.startswith("     \u2500")), len(rows))
        return sum(sum(1 for c in l[5:] if c in ":*#@") for l in rows[:cut])

    def test_a_dark_sky_gets_a_band(self):
        """The floor is well under what a band actually draws, because what
        it is guarding against is the band vanishing, not the exact count.

        Measured on this chart: 165 cells with the asterism lines turned off,
        152 with the old ─ ╱ │ ╲ ones over it and 140 with the braille ones.
        Lines have always been drawn on top of the band -- it is painted into
        the soft layer precisely so nothing else has to give way to it -- and
        a line that follows its real path crosses about twice as many cells
        as one snapped to four directions, so it covers twice as much of it.
        The band underneath is identical either way.
        """
        art, _st = sky.render_linear(self.WHEN, *self.ATACAMA, color=False,
                                     width=140, inset=False, milkyway=1)
        self.assertGreater(self.band_cells(art), 120)

    def test_a_floor_of_zero_draws_nothing(self):
        off, _ = sky.render_linear(self.WHEN, *self.ATACAMA, color=False,
                                   width=140, inset=False, milkyway=0)
        self.assertEqual(self.band_cells(off), 0)

    def test_a_higher_floor_draws_strictly_less(self):
        counts = [self.band_cells(sky.render_linear(
            self.WHEN, *self.ATACAMA, color=False, width=140,
            inset=False, milkyway=f)[0]) for f in (1, 2, 3, 4)]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreater(counts[0], counts[-1])

    def test_the_band_never_takes_a_cell_from_a_star(self):
        # The whole reason it goes in the soft layer. Every non-band glyph
        # on the plain chart must still be there with the band drawn.
        plain, _ = sky.render_linear(self.WHEN, *self.ATACAMA, color=False,
                                     width=140, inset=False)
        band, _ = sky.render_linear(self.WHEN, *self.ATACAMA, color=False,
                                    width=140, inset=False, milkyway=1)
        # U+00B7 is excluded because it is two things: the faint-star glyph
        # and the background gridline dot. The band deliberately replaces
        # the gridline (a band with a hole every sixth column reads as
        # damage) and deliberately does not replace a star, and from the
        # rendered text alone the two are the same character. Everything
        # with a glyph of its own is checked.
        for a, b in zip(plain.split("\n"), band.split("\n")):
            for i, ch in enumerate(a):
                if ch not in " .:*#@\u00b7" and i < len(b):
                    self.assertEqual(b[i], ch,
                                     f"the band overwrote {ch!r} at column {i}")

    def test_the_band_does_not_swallow_faint_stars(self):
        # The other half of the same promise, checked where the character
        # ambiguity does not apply: the number of stars the renderer reports
        # cannot change because a band was drawn behind them.
        _plain, st_plain = sky.render_linear(self.WHEN, *self.ATACAMA,
                                             color=False, width=140, inset=False)
        _band, st_band = sky.render_linear(self.WHEN, *self.ATACAMA, color=False,
                                           width=140, inset=False, milkyway=1)
        self.assertEqual(len(st_band["visible"]), len(st_plain["visible"]))


class SunBands(unittest.TestCase):
    """Golden and blue hour as Sun-altitude windows. Away from the tropics
    the Sun does not cross both edges of the golden band every day, and the
    interesting part of this is what happens when it doesn't."""

    def day(self, lat, lon, off, when):
        return sky.sun_bands(when - dt.timedelta(hours=off), lat, lon)

    def test_an_ordinary_mid_latitude_day_gets_all_four_bands(self):
        b = self.day(46.20, 6.15, 2, dt.datetime(2026, 8, 4))
        self.assertIsNone(b["note"])
        for k in ("blue_am", "golden_am", "golden_pm", "blue_pm"):
            self.assertIsNotNone(b[k], k)
            self.assertFalse(b[k]["open_end"], k)

    def test_morning_and_evening_golden_are_about_an_hour_at_geneva(self):
        b = self.day(46.20, 6.15, 2, dt.datetime(2026, 8, 4))
        for k in ("golden_am", "golden_pm"):
            self.assertAlmostEqual(b[k]["minutes"], 64, delta=6, msg=k)

    def test_blue_hour_sits_between_civil_dusk_and_the_golden_band(self):
        # -6 to -4 in the morning, -4 to -6 in the evening: short, and it
        # must abut the golden band exactly rather than overlap it.
        b = self.day(46.20, 6.15, 2, dt.datetime(2026, 8, 4))
        self.assertEqual(b["blue_am"]["end"], b["golden_am"]["start"])
        self.assertEqual(b["blue_pm"]["start"], b["golden_pm"]["end"])
        self.assertLess(b["blue_am"]["minutes"], b["golden_am"]["minutes"])

    def test_azimuth_swings_across_the_window(self):
        # The whole point of the feature: the bearing moves while the band
        # runs, so the two edges are not the same direction.
        b = self.day(46.20, 6.15, 2, dt.datetime(2026, 8, 4))["golden_pm"]
        self.assertGreater(abs(b["az_end"] - b["az_start"]), 5)
        self.assertTrue(250 < b["az_start"] < 320)

    def test_the_sun_really_is_at_the_band_edges(self):
        # Times come from a bisection, so check them against the ephemeris
        # rather than against themselves.
        b = self.day(46.20, 6.15, 2, dt.datetime(2026, 8, 4))["golden_pm"]
        self.assertAlmostEqual(sky.sun_altaz(b["start"], 46.20, 6.15)[0],
                               sky.GOLDEN_HI, delta=0.05)
        self.assertAlmostEqual(sky.sun_altaz(b["end"], 46.20, 6.15)[0],
                               sky.GOLDEN_LO, delta=0.05)

    def test_high_summer_arctic_golden_light_never_closes(self):
        # Tromso on the solstice: the Sun drops through +6 and climbs back
        # out without ever reaching -4, so the evening band has no end. Two
        # separate windows would be a fiction here.
        b = self.day(69.65, 18.96, 2, dt.datetime(2026, 6, 21))
        self.assertEqual(b["note"], "all_night")
        self.assertTrue(b["golden_pm"]["open_end"])
        self.assertIsNone(b["golden_pm"]["end"])
        self.assertIsNone(b["golden_am"])

    def test_arctic_midwinter_is_one_long_window_not_two(self):
        # The Sun clears -4 but never +6, so it enters the band once and
        # leaves it once. Splitting that into a morning and an evening band
        # would invent a midday that never happened.
        b = self.day(69.65, 18.96, 1, dt.datetime(2026, 12, 21))
        self.assertEqual(b["note"], "all_day")
        self.assertIsNone(b["golden_pm"])
        self.assertGreater(b["golden_am"]["minutes"], 120)
        self.assertFalse(b["golden_am"]["open_end"])

    def test_polar_night_has_no_golden_hour_at_all(self):
        b = self.day(78.2, 15.6, 1, dt.datetime(2026, 12, 21))
        self.assertEqual(b["note"], "never")
        for k in ("blue_am", "golden_am", "golden_pm", "blue_pm"):
            self.assertIsNone(b[k], k)

    def test_southern_hemisphere_azimuths_run_the_other_way(self):
        # Ushuaia in winter: the Sun tracks through the north, and the
        # morning bearing decreases rather than increases.
        b = self.day(-54.8, -68.3, -3, dt.datetime(2026, 6, 21))["golden_am"]
        self.assertLess(b["az_end"], b["az_start"])

    def test_tropics_get_a_short_band_and_barely_moving_bearings(self):
        # Singapore: the Sun comes up steeply, so the band is short and the
        # azimuth hardly moves -- the opposite of the Arctic case.
        b = self.day(1.35, 103.8, 8, dt.datetime(2026, 8, 4))["golden_am"]
        self.assertLess(b["minutes"], 50)
        self.assertLess(abs(b["az_end"] - b["az_start"]), 3)


class ShadowRatio(unittest.TestCase):
    def test_no_shadow_once_the_sun_is_down(self):
        self.assertIsNone(sky.shadow_ratio(0))
        self.assertIsNone(sky.shadow_ratio(-4))

    def test_forty_five_degrees_casts_a_shadow_its_own_length(self):
        self.assertAlmostEqual(sky.shadow_ratio(45), 1.0, places=6)

    def test_the_top_of_the_golden_band_is_about_nine_and_a_half(self):
        self.assertAlmostEqual(sky.shadow_ratio(sky.GOLDEN_HI), 9.51, delta=0.02)

    def test_shadows_lengthen_as_the_sun_drops(self):
        self.assertGreater(sky.shadow_ratio(5), sky.shadow_ratio(30))


if __name__ == "__main__":
    unittest.main()


class AFigureOverheadIsNotDrawnAtAll(unittest.TestCase):
    """The Summer Triangle from Los Angeles in August is the case this exists
    for. Its stars are 24, 34 and 38 degrees apart on the sky -- a compact
    shape -- but they sit within 26 degrees of the zenith, where azimuth stops
    meaning much: 298, 45 and 167, right around the compass.

    A panorama has to draw that as three runs each about a third of the chart
    wide. The drawing guard reads the two widest as wrap-around junk and drops
    them, which used to leave one side of the triangle on the page with the
    triangle's name written against it."""

    LA = (34.05, -118.24)
    WHEN = dt.datetime(2026, 8, 7, 6, 20)      # 23:20 local

    def chart(self, **kw):
        art, _st = sky.render_linear(self.WHEN, *self.LA, color=False,
                                     width=300, **kw)
        return art

    def test_the_three_stars_really_are_spread_round_the_compass(self):
        """The premise, checked rather than assumed: if this stops being true
        the test below would pass for the wrong reason."""
        a = next(x for x in sky._load("asterisms.json")
                 if x["name"] == "Summer Triangle")
        stars = {s["hr"]: s for s in sky._load("stars.json")}
        jd = sky.julian(self.WHEN)
        lst = (sky.gmst_hours(jd) + self.LA[1] / 15.0) % 24
        azs, alts = [], []
        for hr in set(a["lines"][0]):
            s = stars[hr]
            ra, de = sky.precess(s["ra"], s["de"], jd)
            alt, az = sky.altaz(ra, de, self.LA[0], lst)
            azs.append(az); alts.append(alt)
        self.assertGreater(min(alts), 60)          # all of it overhead
        self.assertGreater(max(azs) - min(azs), 180)   # yet spread right round

    def test_it_is_not_drawn_as_one_long_line(self):
        self.assertNotIn("SUMMER TRIANGLE", self.chart())

    def test_the_sector_it_would_have_taken_is_used_by_something_else(self):
        """Rejected at selection rather than only at drawing time, so the
        azimuth sector goes to a figure the projection can carry whole."""
        shown = [n for n in ("KEYSTONE", "JOB'S COFFIN", "CORONA BOREALIS",
                             "AQUILA", "TEAPOT")
                 if n in self.chart()]
        self.assertGreaterEqual(len(shown), 2, shown)

    def test_a_figure_that_fits_is_still_drawn_whole(self):
        """The guard has to be about the projection tearing a shape apart, not
        about big shapes: the Big Dipper is 25 degrees long and stays."""
        self.assertIn("BIG DIPPER", self.chart())


class TheUnlitFieldThroughTwilight(unittest.TestCase):
    """Between sunset and full dark the fade threshold admits almost nothing,
    so the chart used to be a grid with a horizon on it. dim_limit draws the
    field the sky is heading for, unlit, and lets it colour in."""

    # Nautical twilight over Zurich: a handful of stars lit, most not.
    WHEN = dt.datetime(2026, 8, 7, 19, 40)
    LAT, LON = 47.38, 8.54

    def chart(self, **kw):
        return sky.render_linear(self.WHEN, self.LAT, self.LON, width=160, **kw)

    def test_omitting_it_draws_no_unlit_anything(self):
        """Every existing caller -- the CLI included -- is byte-identical."""
        art, _st = self.chart(mag_limit=0.11, line_limit=0.11)
        self.assertNotIn(sky.C.UNLIT, art)

    def test_passing_none_is_the_same_as_omitting_it(self):
        a, _ = self.chart(mag_limit=0.11, line_limit=0.11)
        b, _ = self.chart(mag_limit=0.11, line_limit=0.11, dim_limit=None)
        self.assertEqual(a, b)

    def test_the_field_arrives_before_it_lights_up(self):
        """The whole point: at nautical twilight three stars are genuinely
        pickable out, and the chart shows where the rest of them are."""
        art, st = self.chart(mag_limit=0.11, line_limit=0.11, dim_limit=4.0)
        self.assertLess(len(st["visible"]), 20)
        self.assertGreater(art.count(sky.C.UNLIT), 50)

    def test_the_star_count_stays_honest(self):
        """st['visible'] is what the line above the chart counts. An unlit
        star is one you cannot see, so it must not be in there."""
        _art, dim = self.chart(mag_limit=0.11, line_limit=0.11, dim_limit=4.0)
        _art, plain = self.chart(mag_limit=0.11, line_limit=0.11)
        self.assertEqual(len(dim["visible"]), len(plain["visible"]))

    def test_the_field_is_the_one_full_dark_will_show(self):
        """Composition does not change across twilight, only colour -- so
        nothing pops into existence while you are looking at it."""
        _art, dark = self.chart(mag_limit=4.0, line_limit=4.0)
        art, _ = self.chart(mag_limit=0.11, line_limit=0.11, dim_limit=4.0)
        # Every star full dark will light is already on the twilight chart,
        # in one colour or the other.
        drawn = art.count(sky.C.UNLIT) + art.count(sky.star_colour(None))
        self.assertGreater(drawn, 0)
        self.assertGreaterEqual(len(dark["visible"]), 100)

    def test_at_full_dark_there_is_nothing_left_unlit(self):
        """dim_limit and mag_limit have met, so the second pass adds nothing
        and the chart is the ordinary one."""
        art, _st = self.chart(mag_limit=4.0, line_limit=4.0, dim_limit=4.0)
        self.assertNotIn(sky.C.UNLIT, art)

    def test_a_deeper_field_than_the_sky_is_heading_for_is_not_cut_back(self):
        """find= draws to 5.0. A feature about twilight must not take stars
        away from a caller that asked for more of them."""
        deep, _ = self.chart(mag_limit=5.0, line_limit=None, dim_limit=4.0)
        plain, _ = self.chart(mag_limit=5.0, line_limit=None)
        self.assertEqual(deep, plain)

    def test_lines_are_sketched_in_too(self):
        """Asked for explicitly: the figure appears whole from sunset and
        colours in with its stars rather than assembling segment by segment."""
        art, _st = self.chart(mag_limit=0.11, line_limit=0.11, dim_limit=4.0)
        unlit_rows = [ln for ln in art.split("\n") if sky.C.UNLIT in ln]
        self.assertTrue(unlit_rows)

    def test_an_unnamed_figure_is_not_captioned_before_it_is_lit(self):
        """A constellation name over stars nobody can pick out yet is a
        caption for a picture that is not there.

        The names come off st['cons'] rather than a hand-written list: which
        figures this chart picks is a function of the date and the latitude,
        and a list written here goes stale the moment either moves."""
        # color=False: names are painted a character at a time, so with the
        # escapes in they are never a contiguous substring to search for.
        dim, dim_st = self.chart(mag_limit=-4.0, line_limit=-4.0,
                                 dim_limit=4.0, color=False)
        lit, lit_st = self.chart(mag_limit=4.0, line_limit=4.0, color=False)
        self.assertTrue(lit_st["cons"], "no figures chosen -- test proves nothing")
        self.assertGreater(sum(1 for n in lit_st["cons"] if n.upper() in lit), 0)
        # Nothing lit, so nothing captioned.
        self.assertEqual([n for n in dim_st["cons"] if n.upper() in dim], [])


class TheQuadrantGridIsFollowable(unittest.TestCase):
    """It is drawn last and over the sky, not first and around it. A grid you
    turned on in order to pick a quadrant out of is the one thing on the page
    that has to be traceable end to end."""

    WHEN = dt.datetime(2026, 8, 8, 0, 0)
    V = "┊"

    def _chart(self, **kw):
        art, _st = sky.render_linear(self.WHEN, 47.38, 8.54, width=220,
                                     quadrants=True, color=False, **kw)
        return art

    def _body(self, art):
        return [l for l in art.split("\n") if len(l) > 170]

    def test_each_divider_runs_the_height_of_the_chart(self):
        """Four fifths of every row, on the busiest chart the site draws.

        Not every row: the horizon rule wins its own, being the one line that
        means more than the grid does, and a divider that happens to pass
        through a constellation name gives up a cell per letter. Before this
        was drawn last, a divider through a crowded stretch of sky kept
        barely half its cells."""
        art = self._chart(dso_limit=6.0)
        body = self._body(art)
        cols = sorted({c for l in body for c, ch in enumerate(l) if ch == self.V})
        self.assertGreaterEqual(len(cols), 3)
        for c in cols:
            drawn = sum(1 for l in body if len(l) > c and l[c] == self.V)
            self.assertGreaterEqual(drawn, len(body) * 0.8, (c, drawn, len(body)))

    def test_a_skyful_of_labels_barely_dents_it(self):
        """Drawn first, into empty cells only, it lost a cell to every star,
        label and asterism line it passed behind."""
        dense = self._chart(dso_limit=6.0).count(self.V)
        plain = self._chart().count(self.V)
        self.assertGreater(dense, plain * 0.9, (dense, plain))

    def test_it_still_breaks_for_text(self):
        """The one exception, and the only one: a divider through the middle
        of a word costs more than the cell of grid it buys."""
        self.assertIn("KEYSTONE", self._chart(dso_limit=6.0))

    def test_it_is_yellow_like_the_letters_it_belongs_to(self):
        """Two steps down from the letters' 226: the letters are what you
        read, the grid is what you follow."""
        art, _st = sky.render_linear(self.WHEN, 47.38, 8.54, width=220,
                                     quadrants=True, dso_limit=6.0)
        self.assertIn("38;5;178", art)          # the grid
        self.assertIn("38;5;226", art)          # the A-L letters, brighter
        self.assertNotIn("38;5;240m" + self.V, art)   # not the old grey


class TheDimLimitWindow(unittest.TestCase):
    """api._dim_limit decides when the sketch is on at all."""

    def test_off_in_daylight(self):
        """Drawing a star field into a bright sky would be a lie."""
        import api
        self.assertIsNone(api._dim_limit(10.0))
        self.assertIsNone(api._dim_limit(0.0))

    def test_on_through_twilight(self):
        import api
        for alt in (-0.5, -6.0, -12.0, -17.9):
            self.assertEqual(api._dim_limit(alt), api.FULL_DARK_MAG)

    def test_off_once_the_sky_is_actually_dark(self):
        """The fade has reached the same number by then, so every star is
        lit and there is nothing left to sketch."""
        import api
        self.assertIsNone(api._dim_limit(-18.0))
        self.assertIsNone(api._dim_limit(-30.0))

    def test_it_is_the_limit_the_fade_ends_on(self):
        """Derived, not a second hand-written 4.0."""
        import api
        self.assertEqual(api.FULL_DARK_MAG, api._fade_mag_limit(-18))


class NextVisibleDoesNotDependOnWhenYouAsk(unittest.TestCase):
    """Two conditions have to hold at once -- the thing high enough, the sky
    dark enough -- and for something rising into morning twilight their
    overlap can be minutes wide. Sampled every ten minutes from the moment
    asked, the grid either landed inside that overlap or stepped over it,
    decided by the minute of the hour the caller happened to ask at."""

    LAT, LON = 47.38, 8.54          # Zurich
    DAY = dt.datetime(2026, 8, 7)

    def _target(self, name, when):
        import api
        jd = sky.julian(when)
        lst = (sky.gmst_hours(jd) + self.LON / 15.0) % 24
        return api.resolve_target(name, jd, self.LAT, lst)

    def _answers(self, name, hour=16, minutes=(0, 1, 2, 3, 5, 7, 12, 22, 32, 47, 59)):
        out = set()
        for m in minutes:
            when = self.DAY.replace(hour=hour, minute=m)
            tgt = self._target(name, when)
            self.assertIsNotNone(tgt, name)
            w, _a, _z = sky.next_visible(tgt, self.LAT, self.LON, when)
            out.add(w)
        return out

    def test_jupiter_gives_one_answer_whatever_minute_you_ask(self):
        """The case this was found on. It used to answer Thu 27 Aug from
        :00, :10, :20 and Wed 26 Aug from :02, :12, :22 -- a whole day
        apart, and the page is drawn for whichever came back, so its
        distance, elongation and chart all moved with it."""
        self.assertEqual(len(self._answers("jupiter")), 1)

    def test_it_finds_the_earlier_window_not_the_one_after_it(self):
        """The overlap on 26 August is real; two thirds of the grid phases
        simply stepped over it and reported the next morning."""
        w = self._answers("jupiter").pop()
        self.assertEqual(w.date(), dt.date(2026, 8, 26))

    def test_the_answer_is_the_moment_the_window_opens(self):
        """Not the first tick that noticed it. A sample that qualifies walks
        back a minute at a time to the start of its own window."""
        when = self.DAY.replace(hour=16, minute=0)
        tgt = self._target("jupiter", when)
        w, a, _z = sky.next_visible(tgt, self.LAT, self.LON, when)
        before = w - dt.timedelta(minutes=1)
        jd = sky.julian(before)
        lst = (sky.gmst_hours(jd) + self.LON / 15.0) % 24
        alt, _az = sky.target_altaz(tgt, jd, self.LAT, lst)
        # The minute before is not yet good enough -- either too low or the
        # sky has not caught up.
        su = sky.sun(jd)
        sa, _ = sky.altaz(su["ra"], su["dec"], self.LAT, lst)
        mag = tgt["mag"] if tgt.get("mag") is not None else tgt.get("faint")
        self.assertFalse(alt >= 12.0 and sky.dark_enough(sa, mag))
        self.assertGreaterEqual(a, 12.0)

    def test_other_targets_are_stable_too(self):
        for name in ("saturn", "vega", "m31", "neptune"):
            self.assertEqual(len(self._answers(name)), 1, name)

    def test_something_never_up_still_comes_back_empty(self):
        """The forty-day give-up path is untouched."""
        when = self.DAY.replace(hour=16, minute=0)
        tgt = self._target("canopus", when)
        w, a, z = sky.next_visible(tgt, self.LAT, self.LON, when)
        self.assertIsNone(w)
        self.assertIsNone(a)
        self.assertIsNone(z)


class TheShowerRadiantIsMarkedOnTheChart(unittest.TestCase):
    """The chart said nothing about a shower at all. events.active_shower()
    was written for this and never called by anything, so the page could
    print "the Perseids are running, radiant 51 deg NE" in prose over a
    drawing that gave no hint where that was."""

    WHEN = dt.datetime(2026, 8, 8, 21, 0)
    LAT, LON = 47.38, 8.54

    def _chart(self, **kw):
        art, _st = sky.render_linear(self.WHEN, self.LAT, self.LON,
                                     width=220, color=False, **kw)
        return art

    def test_no_radiant_asked_for_draws_nothing(self):
        """Every existing caller, the CLI included, is untouched."""
        self.assertNotIn("PERSEIDS", self._chart())

    def test_it_marks_the_spot_and_names_it(self):
        art = self._chart(radiant=dict(name="Perseids", alt=40.0, az=45.0))
        self.assertIn("PERSEIDS", art)

    def test_the_mark_is_one_a_font_actually_has(self):
        """test_gif's tofu check is the real guard; this is the reason. The
        events list uses a comet for the row and neither bundled font has a
        glyph for it, so the chart uses the cross art.py already puts at the
        radiant of its shower portraits."""
        art = self._chart(radiant=dict(name="Perseids", alt=40.0, az=45.0))
        self.assertNotIn("☄", art)
        self.assertIn("+", art)

    def test_a_radiant_below_the_horizon_is_not_drawn(self):
        self.assertNotIn("PERSEIDS",
                         self._chart(radiant=dict(name="Perseids", alt=-20.0,
                                                  az=45.0)))


class ChartLabelsLinkToTheirPages(unittest.TestCase):
    """A label with a page behind it is a link to it. The chart is painted a
    cell at a time, so by the time it is a string a label is a run of
    separate colour spans with nothing left to match on -- sky.py marks the
    run while the row is assembled and api turns the markers into anchors."""

    WHEN = dt.datetime(2026, 8, 8, 23, 0)
    LAT, LON = 47.38, 8.54

    def _chart(self, link=None):
        art, _st = sky.render_linear(self.WHEN, self.LAT, self.LON,
                                     width=220, color=False, link=link)
        return art

    def test_no_link_asked_for_emits_no_markers(self):
        """A terminal never sees one -- it would print as a control code."""
        art = self._chart()
        for mark in (sky.LINK_START, sky.LINK_SEP, sky.LINK_END):
            self.assertNotIn(mark, art)

    def test_a_named_label_is_wrapped(self):
        art = self._chart(link=lambda n: f"/Zurich/{n}")
        self.assertIn(sky.LINK_START, art)
        self.assertIn(sky.LINK_SEP, art)
        self.assertIn(sky.LINK_END, art)

    def test_a_label_with_no_page_is_left_alone(self):
        """link returning None is how "this one has no page" is said."""
        art = self._chart(link=lambda n: None)
        self.assertNotIn(sky.LINK_START, art)

    def test_every_open_marker_is_closed(self):
        art = self._chart(link=lambda n: f"/Zurich/{n}")
        self.assertEqual(art.count(sky.LINK_START), art.count(sky.LINK_END))
        self.assertEqual(art.count(sky.LINK_START), art.count(sky.LINK_SEP))

    def test_the_drawing_is_otherwise_identical(self):
        """Character for character, once the markers come out: a link must
        not move anything or change what is drawn."""
        plain = self._chart()
        linked = self._chart(link=lambda n: f"/Zurich/{n}")
        for mark in (sky.LINK_END, sky.LINK_SEP):
            linked = linked.replace(mark, "")
        import re as _re
        linked = _re.sub(f"{sky.LINK_START}[^\n]*?(?=[A-Za-z0-9])", "", linked, count=0)
        self.assertEqual(len(plain.split("\n")), len(linked.split("\n")))


class TheRadiantGoesToTheInsetWhenItClimbsOut(unittest.TestCase):
    """The Perseid radiant reaches 79 degrees from Zurich, so it climbed off
    the top of the panorama at about 04:00 and the chart stopped mentioning
    the shower for the rest of the night -- the part of the night it is best
    in. A planet or a bright star has always moved to the zenith inset there;
    this one simply vanished."""

    LAT, LON = 47.38, 8.54

    def _chart(self, hour, alt, az=0.0):
        art, _st = sky.render_linear(dt.datetime(2026, 8, 9, hour, 0),
                                     self.LAT, self.LON, width=220, color=False,
                                     radiant=dict(name="Perseids", alt=alt, az=az))
        return art

    def _where(self, art):
        rows = art.split("\n")
        label = [i for i, l in enumerate(rows) if "PERSEIDS" in l]
        inset = [i for i, l in enumerate(rows) if "zenith" in l]
        if not label:
            return "missing"
        return "inset" if inset and label[0] > inset[0] else "chart"

    def test_below_the_cap_it_is_on_the_panorama(self):
        self.assertEqual(self._where(self._chart(3, 65.7, 40.0)), "chart")

    def test_above_the_cap_it_is_in_the_inset(self):
        for hour, alt in ((4, 73.2), (5, 78.6), (6, 78.3)):
            self.assertEqual(self._where(self._chart(hour, alt, 40.0)), "inset",
                             (hour, alt))

    def test_it_never_simply_disappears(self):
        """The bug, stated as the property: at no altitude it can reach is
        the radiant absent from both."""
        for alt in range(5, 90, 5):
            self.assertNotEqual(self._where(self._chart(3, float(alt), 40.0)),
                                "missing", alt)
