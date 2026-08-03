#!/usr/bin/env python3
"""Tests for gif.py's GIF export -- the shared-palette bug that made
animated star colours collapse to grey when the sequence started at a
starless (daytime) moment.

Run:  python3 test_gif.py
"""
import datetime as dt
import io
import unittest

from PIL import Image

import api
import gif


def _frames(start, count=20, step_minutes=30):
    out = []
    for i in range(count):
        r = api.Request(place="Zurich", when=start + dt.timedelta(minutes=i * step_minutes),
                        color=True)
        body, _sun_alt = api.compose_frame(r)
        out.append(body)
    return out


class BasePalette(unittest.TestCase):
    """_base_palette scans every frame's ANSI codes, not just the first --
    the fix for the actual bug (an adaptive palette derived from frame 0
    alone misses colours that frame doesn't happen to contain)."""

    def test_includes_a_code_that_only_appears_in_a_later_frame(self):
        # Frame 0 (midday) has no stars at all; a later, dark frame does.
        frames = _frames(dt.datetime(2026, 7, 30, 12, 0), count=30)
        self.assertNotIn("38;5;117m", frames[0])
        self.assertTrue(any("38;5;117m" in t for t in frames[1:]))
        base = gif._base_palette(frames)
        palette_colors = set(tuple(base.getpalette()[i:i + 3])
                             for i in range(0, len(base.getpalette()), 3))
        self.assertIn(gif._xterm_rgb(117), palette_colors)

    def test_always_includes_bg_and_fg_default(self):
        base = gif._base_palette(["no ansi codes here"])
        palette_colors = set(tuple(base.getpalette()[i:i + 3])
                             for i in range(0, len(base.getpalette()), 3))
        self.assertIn(gif.BG, palette_colors)
        self.assertIn(gif.FG_DEFAULT, palette_colors)

    def test_no_duplicate_palette_entries_for_a_repeated_code(self):
        base = gif._base_palette(["\033[38;5;117mA\033[0m", "\033[38;5;117mB\033[0m"])
        n = len(base.getpalette()) // 3
        # BG + FG_DEFAULT + WATERMARK_COLOR + one star colour -- not more,
        # even though 117 appears in both frames.
        self.assertLessEqual(n, 4)


class FramesToGifColourFidelity(unittest.TestCase):
    """The actual regression: a GIF's night frames used to lose their real
    star colours to nearest-match grey whenever the animation started at a
    starless moment -- the exact scenario "Share as a GIF" hits whenever
    someone clicks it during the day."""

    def test_star_colours_survive_exactly_from_a_daylight_start(self):
        frames = _frames(dt.datetime(2026, 7, 30, 12, 0), count=48)
        star_codes = [117, 230, 222, 216]   # blue-white, pale-yellow, yellow, orange-red
        present = [c for c in star_codes if any(f"38;5;{c}m" in t for t in frames)]
        self.assertTrue(present, "test fixture must actually reach a night frame")

        data = gif.frames_to_gif(frames, 100)
        im = Image.open(io.BytesIO(data))
        for code in present:
            idx = next(i for i, t in enumerate(frames) if f"38;5;{code}m" in t)
            im.seek(idx)
            colors = {c[1] for c in im.convert("RGB").getcolors(maxcolors=100000)}
            self.assertIn(gif._xterm_rgb(code), colors,
                          f"xterm {code} did not survive quantisation at frame {idx}")

    def test_every_core_xterm_colour_in_the_frame_also_lands_in_the_gif(self):
        # Not a full pixel-set comparison: frame_to_png is plain RGB with
        # FreeType's anti-aliased glyph edges (hundreds of blended in-
        # between shades), while the GIF is necessarily quantised to a
        # fixed palette -- that's a lossless-vs-8-bit-indexed format
        # difference, not a bug, and no code change closes it. What has to
        # match is that every *named* xterm colour this frame actually
        # uses (the glyphs' true fill colour, not anti-aliasing) survives
        # into the GIF somewhere.
        frames = _frames(dt.datetime(2026, 7, 30, 22, 0), count=1)
        codes = {int(m) for m in gif.ANSI.findall(frames[0]) if m}
        self.assertTrue(codes, "test fixture must actually use some colour")
        data = gif.frames_to_gif(frames * 2, 100)   # GIF needs 2+ frames
        gif_im = Image.open(io.BytesIO(data))
        gif_im.seek(0)
        gif_colors = {c[1] for c in gif_im.convert("RGB").getcolors(maxcolors=100000)}
        for code in codes:
            self.assertIn(gif._xterm_rgb(code), gif_colors, f"xterm {code} missing")


if __name__ == "__main__":
    unittest.main()
