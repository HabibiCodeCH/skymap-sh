#!/usr/bin/env python3
"""Render one deep-sky portrait many ways, side by side, for choosing.

The Sombrero's dust lane is drawn and then lost: the lane is 0.06 units
across, one output row is 0.068, so it straddles a row boundary, each row
keeps about half its light, and it sits exactly where the bulge is
brightest. Half of very bright is still bright.

Which numbers fix that is not something to reason about. It is something to
look at, so this renders the candidates on one page.
"""
import os, re, sys, html
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import art

HERE = os.path.dirname(os.path.abspath(__file__))
ANSI = re.compile(r"\x1b\[([0-9;]*)m")
TARGET, NAME = "NGC4594", "Sombrero Galaxy"
SHIPPED = dict(art.DSO_ART[TARGET])


def _xterm(n):
    """One xterm-256 index as a hex colour.

    16 to 231 is a 6x6x6 cube on the levels below, 232 upwards is a grey
    ramp, and the first 16 are the terminal's own palette, which nothing
    here uses.
    """
    if n >= 232:
        v = 8 + (n - 232) * 10
        return f"#{v:02x}{v:02x}{v:02x}"
    n -= 16
    lv = (0, 95, 135, 175, 215, 255)
    r, g, b = lv[n // 36], lv[(n // 6) % 6], lv[n % 6]
    return f"#{r:02x}{g:02x}{b:02x}"


def ansi_html(text):
    """The same line a terminal draws, as spans. The art is 256-colour
    foreground codes and resets, and nothing else, so this handles those two
    and drops anything it does not recognise rather than guessing."""
    out, pos, open_span = [], 0, False
    for m in ANSI.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        pos = m.end()
        parts = m.group(1).split(";")
        if parts[:2] == ["38", "5"] and len(parts) > 2:
            if open_span:
                out.append("</span>")
            out.append(f'<span style="color:{_xterm(int(parts[2]))}">')
            open_span = True
        elif m.group(1) in ("", "0"):
            if open_span:
                out.append("</span>")
                open_span = False
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    return "".join(out)


def render(rows=art.DSO_ROWS, **over):
    art.DSO_ART[TARGET] = dict(SHIPPED, **over)
    try:
        lines = art.dso_art(NAME, rows=rows)
    finally:
        art.DSO_ART[TARGET] = dict(SHIPPED)
    return "\n".join(ansi_html(str(l)) for l in lines)


CASES = [
    ("As shipped", "The lane is there in the model and invisible on the page.",
     {}, art.DSO_ROWS),
    ("Lane a little wider", "lane_w 0.030 to 0.042. Still under one row.",
     {"lane_w": 0.042}, art.DSO_ROWS),
    ("Lane one row deep", "lane_w 0.055, so it covers a full output row.",
     {"lane_w": 0.055}, art.DSO_ROWS),
    ("Lane wide and low", "Wider, and pushed below centre so the brim reads.",
     {"lane_w": 0.070, "lane_v": -0.050}, art.DSO_ROWS),
    ("Lane centred", "lane_v 0 exactly, cutting the bulge in half.",
     {"lane_w": 0.055, "lane_v": 0.0}, art.DSO_ROWS),
    ("Taller portrait, lane as shipped",
     "21 rows instead of 17. More rows means a thinner row, so the real lane "
     "width starts to register without touching the model.",
     {}, 21),
    ("Taller portrait, lane a little wider",
     "21 rows and lane_w 0.042.", {"lane_w": 0.042}, 21),
    ("Thinner disc, lane one row deep",
     "disc_q 0.20 to 0.15 as well, so the lens is flatter under the lane.",
     {"lane_w": 0.055, "disc_q": 0.15}, art.DSO_ROWS),
]

blocks = []
for title, why, over, rows in CASES:
    spec = dict(SHIPPED, **over)
    knobs = "  ".join(f"{k}={spec[k]}" for k in ("lane_v", "lane_w", "disc_q"))
    blocks.append(
        f'<section><h2>{html.escape(title)}</h2>'
        f'<p class=why>{html.escape(why)}</p>'
        f'<p class=knobs>{html.escape(knobs)}  ·  rows={rows}</p>'
        f'<pre>{render(rows, **over)}</pre></section>')

doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Sombrero: which lane</title><style>
body{{margin:0;background:#04060a;color:#c9d1d9;padding:28px 18px 90px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;font-size:13px}}
.w{{max-width:900px;margin:0 auto}} h1{{font-size:22px;color:#e6ebf2;margin:0 0 .3rem}}
.sub{{color:#7d8694;margin:0 0 2rem;line-height:1.6;max-width:70ch}}
section{{border:1px solid #1c2027;border-radius:8px;background:#070a0e;
padding:14px 16px;margin:0 0 14px}}
h2{{font-family:ui-sans-serif,-apple-system,sans-serif;font-size:12px;
text-transform:uppercase;letter-spacing:.09em;color:#8fb6e0;margin:0 0 .4rem}}
.why{{color:#8b93a3;margin:0 0 .5rem;line-height:1.5;max-width:70ch}}
.knobs{{color:#5c6570;margin:0 0 .8rem;font-size:11.5px}}
pre{{margin:0;line-height:1.15;white-space:pre;overflow-x:auto;color:#c9d1d9}}
</style></head><body><div class=w>
<h1>Sombrero: which dust lane</h1>
<p class=sub>The lane is what the galaxy is named for and it does not show.
It spans 0.06 vertical units; one output row is 0.068 and it straddles a row
boundary, so each row it touches keeps about half its light, and it sits
exactly where the bulge is brightest. These are the ways out, drawn in the
same colours the page and the terminal use.</p>
{''.join(blocks)}
</div></body></html>"""

open(f"{HERE}/sombrero-art.html", "w").write(doc)
print(f"wrote sombrero-art.html with {len(CASES)} options")
