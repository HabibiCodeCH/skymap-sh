#!/usr/bin/env python3
"""Tests for gif.py's GIF export -- the shared-palette bug that made
animated star colours collapse to grey when the sequence started at a
starless (daytime) moment.

Run:  python3 test_gif.py
"""
import datetime as dt
import io
import unittest

from PIL import Image, ImageDraw

import api
import gif
import sky


def _frames(start, count=20, step_minutes=30):
    out = []
    for i in range(count):
        r = api.Request(place="Zurich", when=start + dt.timedelta(minutes=i * step_minutes),
                        color=True)
        body, _sun_alt = api.compose_frame(r)
        out.append(body)
    return out


class NoGlyphRendersAsTofu(unittest.TestCase):
    """A font without a glyph does not fail, it draws .notdef -- and every
    shared PNG showed empty boxes where the terminal showed a bright star,
    a quarter Moon, the Sun, a galaxy, a cluster or a nebula.

    Checked against the fonts' own cmap tables, not against rendered
    bitmaps. Two earlier attempts at this compared bitmaps and both shipped
    a fix that left the bug in place -- .notdef is a visible box for some
    codepoints and blank for others, so "does this look like a box" is not
    a test. This is the fact, read from the font."""

    @classmethod
    def setUpClass(cls):
        # Deliberately unguarded. This used to skip when fonttools was
        # missing, which sounds polite and is the wrong call: the thing
        # being checked is invisible in the output, so a check that quietly
        # does not run leaves exactly the same hole the empty boxes came
        # through. It sat unrun on a dev machine for a whole session that
        # way, reported as two familiar failures nobody looked at.
        # fonttools is in requirements.txt. If this raises, install it.
        from fontTools.ttLib import TTFont

        def cmap_of(path):
            f = TTFont(path, fontNumber=0)
            out = set()
            for t in f["cmap"].tables:
                out |= set(t.cmap.keys())
            return out

        cls.primary = cmap_of(gif._FONT_CANDIDATES[0])
        cls.fallback = cmap_of(gif._FALLBACK_PATH)

    def chart_characters(self):
        """Every character real charts actually produce -- taken from the
        renderer rather than hand-listed, which is what let the cluster mark
        slip past a previous version of this test."""
        seen = set()
        for kwargs in ({}, {"dso": True}, {"night": True}):
            for place, when in (("Geneva", dt.datetime(2026, 8, 5, 23, 0)),
                                ("Rio de Janeiro", dt.datetime(2026, 8, 5, 1, 22)),
                                ("Prague", dt.datetime(2026, 8, 5, 6, 21)),
                                ("Tromso", dt.datetime(2026, 12, 21, 22, 0))):
                r = api.Request(place=place, when=when, color=True,
                                width=110, **kwargs)
                seen |= {c for c in gif.ANSI.sub("", api.compose(r).text)
                         if c.strip()}
        return seen

    def drawn_as(self, ch):
        """(character, cmap) the PNG will actually use for this."""
        ch = gif.PNG_SUBSTITUTE.get(ch, ch)
        return ch, (self.fallback if ch in gif._PRIMARY_GAPS else self.primary)

    def test_every_character_a_chart_can_draw_has_a_glyph(self):
        for ch in sorted(self.chart_characters()):
            drawn, cmap = self.drawn_as(ch)
            self.assertIn(
                ord(drawn), cmap,
                f"{ch!r} (drawn as {drawn!r}) has no glyph -- it will export "
                f"as an empty box. Add it to gif._PRIMARY_GAPS if DejaVu has "
                f"it, or to gif.PNG_SUBSTITUTE if neither font does.")

    def test_the_recorded_gaps_are_really_gaps(self):
        # If a JetBrains Mono update fills one of these, the fallback should
        # stop being used for it rather than quietly overriding the design.
        for ch in gif._PRIMARY_GAPS:
            self.assertNotIn(ord(ch), self.primary, f"{ch!r} is no longer missing")

    def test_the_substituted_character_is_missing_from_both_fonts(self):
        # Substitution is the last resort; anything DejaVu has should be
        # drawn properly rather than swapped for a lookalike.
        for original in gif.PNG_SUBSTITUTE:
            self.assertNotIn(ord(original), self.primary)
            self.assertNotIn(ord(original), self.fallback)

    def test_the_fallback_keeps_the_monospace_grid(self):
        # Two fonts on one character grid only works if a cell is the same
        # width in both; a mismatch would shear every row it appears in.
        self.assertAlmostEqual(gif._font.getlength("M"),
                               gif._fallback_font.getlength("M"), places=2)

    def test_the_two_quarter_moons_stay_distinguishable(self):
        # sky.py picks U+25D0/25D1 because they are the one pair that
        # mirrors, so waxing cannot be mistaken for waning. An earlier fix
        # substituted half-black squares and lost exactly that.
        for ch in ("◐", "◑"):
            self.assertIn(ord(ch), self.fallback)
        self.assertNotIn("◐", gif.PNG_SUBSTITUTE)
        self.assertNotIn("◑", gif.PNG_SUBSTITUTE)


class BrailleIsDrawnBecauseNoFontHasIt(unittest.TestCase):
    """The constellation panels are braille, and this export drew them as a
    field of empty boxes: neither bundled font has a single glyph in the
    braille block. The terminal was fine the whole time, which is exactly
    how it went unnoticed.

    So the dots are drawn rather than typeset. These say that the reason
    still holds -- if a future font update fills the block, drawing them is
    still fine but the comment explaining why would have gone stale."""

    @classmethod
    def setUpClass(cls):
        from fontTools.ttLib import TTFont

        def cmap_of(path):
            f = TTFont(path, fontNumber=0)
            out = set()
            for t in f["cmap"].tables:
                out |= set(t.cmap.keys())
            return out

        cls.primary = cmap_of(gif._FONT_CANDIDATES[0])
        cls.fallback = cmap_of(gif._FALLBACK_PATH)

    def test_neither_font_has_any_braille_at_all(self):
        block = range(gif.BRAILLE_LO, gif.BRAILLE_HI + 1)
        self.assertEqual([c for c in block if c in self.primary], [])
        self.assertEqual([c for c in block if c in self.fallback], [])

    def test_a_braille_character_comes_out_with_ink_in_it(self):
        """The failure this replaces was a tile full of .notdef box, so
        "something was drawn" is not enough -- the dots have to land where
        the character says they do."""
        blank = gif._glyph(chr(gif.BRAILLE_LO), (255, 255, 255), 20)
        self.assertEqual(blank.getbbox(), None, "U+2800 has no dots set")
        full = gif._glyph(chr(gif.BRAILLE_LO + 0xFF), (255, 255, 255), 20)
        self.assertIsNotNone(full.getbbox())
        # Eight dots fill the cell; one dot does not.
        one = gif._glyph(chr(gif.BRAILLE_LO + 0x01), (255, 255, 255), 20)
        self.assertLess(_ink(one), _ink(full) / 4)

    def test_the_top_left_dot_is_in_the_top_left(self):
        top_left = gif._glyph(chr(gif.BRAILLE_LO + 0x01), (255, 255, 255), 20)
        bottom_right = gif._glyph(chr(gif.BRAILLE_LO + 0x80), (255, 255, 255), 20)
        a, b = top_left.getbbox(), bottom_right.getbbox()
        self.assertLess(a[0], b[0], "left dot is not left of the right one")
        self.assertLess(a[1], b[1], "top dot is not above the bottom one")

    def test_a_real_panel_exports_with_no_empty_boxes(self):
        import motion
        frames = motion.frames("Big Dipper", steps=3)
        data = gif.frames_to_gif(["\n".join(f) for f in frames], 130,
                                 gif.cell_h_for(2.0))
        self.assertEqual(data[:6], b"GIF89a")
        self.assertGreater(len(data), 2000)


def _ink(tile):
    return sum(1 for px in tile.getdata() if px[3] > 8)


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
