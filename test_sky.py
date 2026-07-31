#!/usr/bin/env python3
"""Tests for sky.py's ISS pass detection.

Run:  python3 test_sky.py
"""
import unittest
import datetime as dt
import sky


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


if __name__ == "__main__":
    unittest.main()
