"""Render animate() frames (see api.compose_frame) to an animated GIF.

Reuses the same xterm-256 palette lookup as ansi_to_html (api._xterm_hex) so
a GIF frame is colour-for-colour the same as what the terminal shows -- no
separate palette to keep in sync.
"""
import io, os, re
from PIL import Image, ImageDraw, ImageFont

import api
import brand

ANSI = re.compile(r"\033\[(?:38;5;(\d+)|0)m")

# JetBrains Mono is bundled in fonts/ (SIL Open Font License -- see
# fonts/OFL.txt -- free to embed and redistribute, no royalties, no
# attribution required in rendered output), so this looks the same on the
# production VPS as it does locally. The rest are OS fallbacks only, in case
# the bundled file is ever missing.
_FONT_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "fonts", "JetBrainsMono-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/Library/Fonts/Menlo.ttc",
]
FONT_SIZE = 16
BG = (0, 0, 0)
FG_DEFAULT = (204, 204, 204)

# One footer line on every image this module produces -- GIF frames and the
# static PNG export both go through frame_to_image, so both get it for free.
WATERMARK_TEXT = f"made with {brand.SITE} by {brand.AT_HANDLE}"
WATERMARK_SIZE = 11
WATERMARK_COLOR = (160, 168, 178)      # brighter than the site's own muted
                                        # ".t" label grey (#6e7681) -- still
                                        # subtle, just legible on a small GIF


def _load_font(size):
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


_font = _load_font(FONT_SIZE)
_wm_font = _load_font(WATERMARK_SIZE)

_CELL_W = _font.getlength("M") or FONT_SIZE * 0.6
# A bit more than the font's own line height -- the constellation lines are
# drawn as tight per-cell glyphs (- / | \), so this can't grow much further
# without visibly breaking them into dashes.
_CELL_H = int(FONT_SIZE * 1.45)
_WM_STRIP_H = int(WATERMARK_SIZE * 2.2)


_PROBE = FONT_SIZE * 3          # comfortably bigger than any glyph

# A font that has the glyphs JetBrains Mono does not, drawn from only for
# those. JetBrains Mono is missing the bright star, both quarter Moons, the
# Sun and three of the four deep-sky marks -- seven characters the chart
# emits regularly. A missing glyph does not fail loudly, it draws .notdef,
# an empty box, so every shared PNG has been showing tofu where the terminal
# showed the real thing and nothing anywhere said so.
#
# Substituting lookalikes was the first attempt and it was wrong twice over:
# the obvious replacements are missing from this font as well, and the ones
# that are present are not the thing -- a half-black square is not a Moon.
# DejaVu Sans Mono has every character the chart can produce, and at this
# size its advance width is identical (10.00), so the monospace grid the
# whole renderer depends on is unchanged.
_FALLBACK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "fonts", "DejaVuSansMono.ttf")
try:
    _fallback_font = ImageFont.truetype(_FALLBACK_PATH, FONT_SIZE)
except OSError:
    _fallback_font = None


# Exactly which characters each font lacks, read from their cmap tables
# rather than guessed from rendered bitmaps. Two earlier attempts guessed,
# and both shipped a fix that left the bug in place: a missing glyph draws
# .notdef, but .notdef is a visible box for some codepoints and blank for
# others, so "does this look like a box" is not a test.
#
# JetBrains Mono has 1,372 codepoints and DejaVu Sans Mono 3,359. These are
# the seven the chart draws that the bundled font has no glyph for.
_PRIMARY_GAPS = frozenset("★◐◑☀✺✳⁂")

# U+2042 ASTERISM is in neither font. It is the star-cluster mark, which is
# the commonest deep-sky type, so it alone filled a ?dso=1 export with boxes.
# U+2234 is in both and says the same thing -- three points close together,
# which is what a cluster is.
PNG_SUBSTITUTE = {"⁂": "∴"}


def font_for(ch):
    """The bundled font, unless it has no glyph for this and DejaVu does."""
    if _fallback_font is not None and ch in _PRIMARY_GAPS:
        return _fallback_font
    return _font


def _xterm_rgb(n):
    h = api._xterm_hex(n).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# frame_to_image used to call draw.text() once per same-colour run, which for
# a starfield means once per 1-2 characters (colour changes almost every
# dot) -- profiled at 44,221 calls to render a 96-frame GIF, 87% of it spent
# in FreeType rasterisation, even though only ~150 distinct (character,
# colour) pairs actually occur. Every one of those calls was re-rasterising
# a glyph this process had already drawn. Cached here instead: render each
# (char, colour) once into a small RGBA tile, then paste the cached tile for
# every repeat -- a plain compositing op, not a font call. Module-level and
# never evicted: the xterm palette is bounded to 256 colours and the
# character set (digits, chart symbols, city names) is small enough that
# even a few thousand entries is a few MB, not worth the complexity of a
# cache limit.
_glyph_cache = {}


def _glyph(ch, color):
    tile = _glyph_cache.get((ch, color))
    if tile is None:
        tile = Image.new("RGBA", (int(_CELL_W) + 1, _CELL_H), (0, 0, 0, 0))
        ch = PNG_SUBSTITUTE.get(ch, ch)
        ImageDraw.Draw(tile).text((0, 0), ch, font=font_for(ch), fill=color)
        _glyph_cache[(ch, color)] = tile
    return tile


def frame_to_image(text):
    """One ANSI frame -> one RGB image, cell-aligned to a monospace grid,
    with a one-line watermark footer below the chart content."""
    lines = text.split("\n")
    cols = max((len(ANSI.sub("", l)) for l in lines), default=1)
    content_h = _CELL_H * len(lines)
    img = Image.new("RGB", (int(_CELL_W * cols) + 2, content_h + _WM_STRIP_H), BG)
    for row, line in enumerate(lines):
        col, pos, fg = 0, 0, FG_DEFAULT
        for m in ANSI.finditer(line):
            chunk = line[pos:m.start()]
            for ch in chunk:
                if ch != " ":
                    tile = _glyph(ch, fg)
                    img.paste(tile, (int(col * _CELL_W), row * _CELL_H), tile)
                col += 1
            pos = m.end()
            fg = _xterm_rgb(m.group(1)) if m.group(1) else FG_DEFAULT
        chunk = line[pos:]
        for ch in chunk:
            if ch != " ":
                tile = _glyph(ch, fg)
                img.paste(tile, (int(col * _CELL_W), row * _CELL_H), tile)
            col += 1
    wm_y = content_h + (_WM_STRIP_H - WATERMARK_SIZE) // 2
    ImageDraw.Draw(img).text((4, wm_y), WATERMARK_TEXT, font=_wm_font, fill=WATERMARK_COLOR)
    return img


def frame_to_png(text):
    """One ANSI frame -> PNG bytes. Used for the static horizon chart export."""
    buf = io.BytesIO()
    frame_to_image(text).save(buf, format="PNG")
    return buf.getvalue()


def _base_palette(frame_texts):
    """An explicit, exact palette -- every xterm-256 colour code that
    appears anywhere in the sequence, RGB-converted, each getting its own
    slot -- built from a regex scan over the already-in-memory ANSI
    strings, no image rendering needed, so this costs nothing extra.

    Replaces the old palette.convert("P", palette=Image.ADAPTIVE) derived
    from frame 0 alone: an *adaptive* palette only picks up colours that
    frame actually contains, and frame 0 is whatever moment the GIF starts
    at -- often "now", which can easily be daylight with zero stars drawn.
    Every later night frame's real star colours then had nothing to match
    in that palette but nearby greys, which is the whole "GIF stars are
    grey but the static PNG isn't" bug: frame_to_png (the PNG export)
    never quantises to an indexed palette at all, only this function did.
    Scanning every frame first means a colour that only shows up two-thirds
    of the way through the animation still gets an exact slot."""
    codes = {int(m) for t in frame_texts for m in ANSI.findall(t) if m}
    # BG and WATERMARK_COLOR are plain RGB fills, never routed through an
    # xterm code at all -- included explicitly so they don't fall back to
    # nearest-match either. FG_DEFAULT is also the fallback colour for any
    # char before the first ANSI code on a line, same reasoning.
    colors = [BG, FG_DEFAULT, WATERMARK_COLOR] + [_xterm_rgb(c) for c in sorted(codes)]
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette([channel for rgb in dict.fromkeys(colors) for channel in rgb])
    return pal_img


def frames_to_gif(frame_texts, frame_ms):
    """List of ANSI frame strings -> GIF bytes. One shared, explicit palette
    (see _base_palette) across every frame, so colours don't flicker or
    drift as the GIF plays -- per-frame adaptive palettes would each pick
    slightly different shades for the same xterm colour, and an adaptive
    palette derived from just one frame can miss colours entirely (see
    _base_palette's docstring). dither=Image.NONE: these are flat, single-
    colour text glyphs, not photographic gradients, and every colour a
    frame can contain already has an exact slot -- dithering would only
    blend pixels at glyph edges for no benefit.

    Quantises each frame right after rendering it and drops the full-size
    RGB copy before rendering the next -- building the whole RGB list first
    and only then quantising it (the original approach) held every frame
    twice at once, peaking at ~440 MB for a 96-frame render. That alone was
    enough to OOM a process capped at 512 MB.

    append_images gets a generator, not a list: Pillow's GIF writer
    (GifImagePlugin._write_multiple_frames) consumes it lazily via
    itertools.chain and copies each frame into its own internal structure
    as it goes, so materialising our own 96-frame list first just means
    both copies exist at once for no reason.

    palette=base is passed explicitly to save() too -- without it, Pillow's
    _save() can't tell we already gave every frame the same palette, so it
    defaults optimize=True (a real analysis pass) and embeds a full 256-
    colour table in *every single frame* instead of writing the shared one
    once in the global header. Measured on a 96-frame render: passing it
    explicitly took peak memory from 297MB to 183MB and render time from
    5.6s to 1.3s, for the same pixel-identical output."""
    base = _base_palette(frame_texts)

    def rest():
        for t in frame_texts[1:]:
            im = frame_to_image(t)
            q = im.quantize(palette=base, dither=Image.NONE)
            del im
            yield q

    first_q = frame_to_image(frame_texts[0]).quantize(palette=base, dither=Image.NONE)
    buf = io.BytesIO()
    first_q.save(buf, format="GIF", save_all=True, append_images=rest(),
                duration=frame_ms, loop=0, palette=base)
    return buf.getvalue()
