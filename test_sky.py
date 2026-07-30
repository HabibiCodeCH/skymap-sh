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


if __name__ == "__main__":
    unittest.main()
