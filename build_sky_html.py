import re, subprocess, html
XT = {"117":"#87d7ff","255":"#eeeeee","231":"#ffffff","230":"#ffffd7","222":"#ffd787",
      "216":"#ffaf87","252":"#d0d0d0","253":"#dadada","250":"#bcbcbc","244":"#808080",
      "242":"#6c6c6c","239":"#4e4e4e","238":"#444444","236":"#303030","235":"#262626",
      "234":"#1c1c1c","227":"#ffff5f","180":"#d7af87","48":"#00ff87"}
TOK = re.compile(r"\033\[(?:38;5;(\d+)|0)m")

def conv(t):
    o, p, op = [], 0, False
    for m in TOK.finditer(t):
        o.append(html.escape(t[p:m.start()])); p = m.end()
        if op: o.append("</span>"); op = False
        if m.group(1):
            o.append(f'<span style="color:{XT.get(m.group(1),"#bbb")}">'); op = True
    o.append(html.escape(t[p:]))
    if op: o.append("</span>")
    return "".join(o)

def run(*a):
    return subprocess.run(["python3","sky.py",*a], capture_output=True, text=True).stdout

zur_lin = conv(run("zurich","2026-07-29T21:50","--linear","--iss"))
zur_face = conv(run("zurich","2026-07-29T21:50","--facing=NNW","--span=90"))
syd_lin = conv(run("sydney","2026-07-30T21:30","--linear"))
find_v  = conv(run("zurich","2026-07-29T21:50","--find=Venus"))
find_j  = conv(run("zurich","2026-07-29T21:50","--find=Jupiter"))


TERM = """<div class="term"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
<span class="t">{cmd}</span></div><pre>{body}</pre></div>"""

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skymap.sh - horizon view</title><style>
 body{{margin:0;background:#04060a;color:#c9d1d9;font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;padding:30px 16px 60px}}
 .wrap{{max-width:1180px;margin:0 auto}}
 h1{{font-size:19px;font-weight:600;margin:0 0 4px;color:#e6edf3;letter-spacing:-.01em}}
 .sub{{color:#8b949e;font-size:13.5px;margin:0 0 26px;line-height:1.6}}
 h2{{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:#8b949e;font-weight:600;margin:32px 0 10px}}
 h2 .n{{text-transform:none;letter-spacing:0;font-weight:400;color:#6e7681;margin-left:8px}}
 .term{{background:#080b11;border:1px solid #1b2027;border-radius:10px;overflow:hidden;box-shadow:0 10px 34px rgba(0,0,0,.6)}}
 .bar{{background:#12161d;padding:9px 14px;display:flex;align-items:center;gap:7px;border-bottom:1px solid #1b2027}}
 .dot{{width:11px;height:11px;border-radius:50%}}
 .bar .t{{margin-left:10px;font-size:11.5px;color:#8b949e;font-family:ui-monospace,Menlo,monospace}}
 pre{{margin:0;padding:14px 14px 16px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
      font-size:10px;line-height:1.22;font-variant-ligatures:none;-webkit-font-smoothing:antialiased}}
 code{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:#9fb4c7}}
 .cap{{color:#6e7681;font-size:12.5px;margin:9px 2px 0;line-height:1.55}}
 .key{{display:flex;gap:20px;flex-wrap:wrap;margin:14px 2px 0;font-size:12.5px;color:#8b949e}}
 .key b{{font-weight:400;font-family:ui-monospace,Menlo,monospace}}
</style></head><body><div class="wrap">
<h1>skymap.sh - horizon view</h1>
<p class="sub">Azimuth runs N to E to S to W to N along the bottom, altitude 0-90&deg; up the side,
gridlines every 10&deg;, zenith cap in the inset below. Figures are <b>asterisms</b> - the shapes people actually
know - with constellation outlines only filling sectors where no famous asterism is up.</p>

<h2>1 &middot; Z&uuml;rich, with an ISS pass <span class="n">curl skymap.sh/Zurich?view=horizon&amp;iss=1</span></h2>
{zur_lin}
<div class="key"><span><b style="color:#00ff87">&#9673; &bull; &#9673;</b> ISS track: rise, peak, set</span>
<span><b style="color:#d7af87">&#9670;</b> planet</span><span><b style="color:#ffffff">&#9733;</b> three brightest stars</span>
<span><b style="color:#dadada">&#9679;</b> Moon, glyph shows phase</span></div>
<p class="cap">The pass is real geometry - above 10&deg;, sunlit, observer in darkness - but propagated from a
<b>synthetic demo TLE</b>, not the live ISS. CelesTrak was unreachable from this sandbox; wire the real
element set and the same code gives the real pass.</p>

<h2>2 &middot; The Plough, actually looking like one <span class="n">curl skymap.sh/Zurich?facing=NNW&amp;span=90</span></h2>
{zur_face}
<p class="cap">A 90&deg; window instead of 360&deg;, with the row count derived from the span so the aspect
holds at 1.00. 90&deg; is the narrowest honest setting: below it the 46-row cap would start stretching shapes
sideways, so span is clamped to 90-344&deg; rather than quietly lying about the geometry.</p>

<h2>3 &middot; Find one thing <span class="n">curl skymap.sh/Zurich?find=Venus</span></h2>
{find_v}
<p class="cap">Naming an object picks the framing for you - window centred on it in both axes, crosshair on
the target, and instructions underneath in fists rather than degrees. Works for planets, the Moon, any named
star, and asterisms: <code>?find=Big+Dipper</code>. Darkness thresholds scale with magnitude - Venus is
fine in bright twilight, a mag-3 asterism needs nautical dark.</p>

<h2>4 &middot; ...and when you cannot <span class="n">curl skymap.sh/Zurich?find=Jupiter</span></h2>
{find_j}
<p class="cap">Jupiter is 0.7&deg; from the Sun tonight - deep in conjunction. Rather than draw an empty
chart it searches forward for the first moment the object clears 12&deg; in a sky dark enough for its
magnitude, and draws <em>that</em>: 27 August, low in the ENE before dawn. If there is no window at all
within 40 days it says so and gives the solar elongation as the reason.</p>

<h2>5 &middot; Sydney <span class="n">curl skymap.sh/Sydney?view=horizon</span></h2>
{syd_lin}
<p class="cap">Constellations are chosen per azimuth sector, so coverage follows you across hemispheres
without a hand-written list.</p>
</div></body></html>"""

open("sky_demo.html","w").write(PAGE.format(
    zur_lin=TERM.format(cmd="curl skymap.sh/Zurich?view=horizon&iss=1", body=zur_lin),
    syd_lin=TERM.format(cmd="curl skymap.sh/Sydney?view=horizon", body=syd_lin),
    zur_face=TERM.format(cmd="curl skymap.sh/Zurich?facing=NNW&span=90", body=zur_face),
    find_v=TERM.format(cmd="curl skymap.sh/Zurich?find=Venus", body=find_v),
    find_j=TERM.format(cmd="curl skymap.sh/Zurich?find=Jupiter", body=find_j)))
print("ok")
