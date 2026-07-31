"""Render animate() frames (see api.compose_frame) to an animated GIF.

Reuses the same xterm-256 palette lookup as ansi_to_html (api._xterm_hex) so
a GIF frame is colour-for-colour the same as what the terminal shows -- no
separate palette to keep in sync.
"""
import io, os, re
from PIL import Image, ImageDraw, ImageFont

import api

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
WATERMARK_TEXT = "made with skymap.sh by @habibicode"
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


def _xterm_rgb(n):
    h = api._xterm_hex(n).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def frame_to_image(text):
    """One ANSI frame -> one RGB image, cell-aligned to a monospace grid,
    with a one-line watermark footer below the chart content."""
    lines = text.split("\n")
    cols = max((len(ANSI.sub("", l)) for l in lines), default=1)
    content_h = _CELL_H * len(lines)
    img = Image.new("RGB", (int(_CELL_W * cols) + 2, content_h + _WM_STRIP_H), BG)
    draw = ImageDraw.Draw(img)
    for row, line in enumerate(lines):
        col, pos, fg = 0, 0, FG_DEFAULT
        for m in ANSI.finditer(line):
            chunk = line[pos:m.start()]
            if chunk:
                draw.text((col * _CELL_W, row * _CELL_H), chunk, font=_font, fill=fg)
                col += len(chunk)
            pos = m.end()
            fg = _xterm_rgb(m.group(1)) if m.group(1) else FG_DEFAULT
        chunk = line[pos:]
        if chunk:
            draw.text((col * _CELL_W, row * _CELL_H), chunk, font=_font, fill=fg)
    wm_y = content_h + (_WM_STRIP_H - WATERMARK_SIZE) // 2
    draw.text((4, wm_y), WATERMARK_TEXT, font=_wm_font, fill=WATERMARK_COLOR)
    return img


def frame_to_png(text):
    """One ANSI frame -> PNG bytes. Used for the static horizon chart export."""
    buf = io.BytesIO()
    frame_to_image(text).save(buf, format="PNG")
    return buf.getvalue()


def frames_to_gif(frame_texts, frame_ms):
    """List of ANSI frame strings -> GIF bytes. One shared palette (quantised
    from the first frame) across every frame, so colours don't flicker or
    drift as the GIF plays -- per-frame adaptive palettes would each pick
    slightly different shades for the same xterm colour."""
    images = [frame_to_image(t) for t in frame_texts]
    base = images[0].convert("P", palette=Image.ADAPTIVE, colors=256)
    quantized = [im.quantize(palette=base) for im in images]
    buf = io.BytesIO()
    quantized[0].save(buf, format="GIF", save_all=True,
                      append_images=quantized[1:], duration=frame_ms, loop=0)
    return buf.getvalue()
