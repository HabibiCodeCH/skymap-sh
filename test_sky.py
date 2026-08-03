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
        self.assertLessEqual(max(widths), 235)   # 220 cap + a few label chars

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

    def test_disc_render_hits_the_requested_width(self):
        t = dt.datetime(2026, 7, 30, 22, 0)
        art, _st = sky.render(t, 47.3769, 8.5417, color=False, width=60)
        widths = [len(l) for l in art.split("\n") if l.strip()]
        self.assertLessEqual(max(widths), 60)


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
    """stars_visible() is the same star filter render() uses internally,
    pulled out as its own function so the mobile 3D sphere view can get
    positions without drawing ASCII -- these tests guard against the
    extraction drifting from what render() actually draws."""

    def test_respects_the_magnitude_cutoff(self):
        jd = sky.julian(dt.datetime(2026, 7, 30, 22, 0))
        lst = (sky.gmst_hours(jd) + 8.5417 / 15.0) % 24
        visible = sky.stars_visible(2.0, jd, 47.3769, lst)
        self.assertTrue(visible)
        self.assertTrue(all(s["m"] <= 2.0 for s, _a, _z in visible))
        self.assertTrue(all(a > 0 for _s, a, _z in visible))

    def test_matches_render_disc_star_count(self):
        when = dt.datetime(2026, 7, 30, 22, 0)
        lat, lon, mag_limit = 47.3769, 8.5417, 4.2
        _art, st = sky.render(when, lat, lon, mag_limit=mag_limit)
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


if __name__ == "__main__":
    unittest.main()
