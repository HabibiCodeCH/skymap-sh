#!/usr/bin/env python3
"""Builds sky_demo.html: ten real renders showing off the range of views.

Uses api.compose() directly, in-process -- the same composition layer cli.py
and server.py call, so this can't drift from what the live service actually
does. Run from /srv/sky on the server so the ISS case sees the real element
set, not the synthetic demo.tle:

    python3 build_sky_html.py
"""
import datetime as dt
import api, tle

TLE = tle.current() or f"{api.sky.BASE}/demo.tle"

CASES = [
    ("Night", "Zurich, star chart",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0)),
     "The default view once the Sun is down: horizon panorama, N-E-S-W-N, "
     "0-70&deg; altitude with a zenith inset for what's directly overhead. "
     "Asterisms &mdash; the shapes people actually recognise &mdash; are "
     "picked per azimuth sector, not a fixed list, so coverage follows you "
     "to any latitude."),
    ("Day", "Zurich, the Sun's path",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 13, 0)),
     "There's no star chart worth drawing while the Sun is up, so daylight "
     "gets a different answer entirely: the Sun's arc across today, rise to "
     "set, with the current position marked and what's worth waiting up "
     "for once it's dark."),
    ("ISS pass", "Cape Town, marked automatically",
     dict(place="Cape Town", when=dt.datetime(2026, 8, 1, 5, 11), tle=TLE),
     "No flag needed &mdash; if the ISS has a real pass overhead right now "
     "(above 10&deg;, sunlit, sky dark enough to see it), it's marked on "
     "the chart automatically. This one peaks at 73&deg;, rising SW and "
     "setting SE."),
    ("Find one thing", "Zurich, find=Venus",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 21, 30), find="Venus"),
     "Naming an object picks the framing for you: a window centred on it in "
     "both axes, a crosshair on the target, directions underneath in fists "
     "rather than degrees. Works for planets, the Moon, any named star, and "
     "asterisms."),
    ("Animate", "Zurich, ?animate",
     dict(place="Zurich", animate=True),
     "The whole night streamed live, frame by frame, right in the terminal "
     "or the page itself &mdash; stars and planets fade in and out with "
     "real twilight, no hard cut at sunset. This GIF is a saved copy of "
     "that same stream, exactly what --animate, ?animate, and the page's "
     "own &#9654; animate button all produce."),
    ("Quadrants", "Zurich, ?quadrant",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0), quadrant=""),
     "The horizon view splits into a fixed 4x3 grid, A through L, letters "
     "marked right on the chart. Asking for a quadrant at all switches the "
     "deep-sky layer on too &mdash; a single cell of stars alone is often "
     "near-empty, and the point of zooming in is to reveal more."),
    ("Quadrant zoom", "Zurich, quadrant=B",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0), quadrant="B"),
     "?quadrant=B crops to that one lettered cell instead of the whole sky. "
     "No server-side state &mdash; the same letter means the same patch of "
     "sky on every request, recomputed fresh from facing/span each time."),
    ("Deep sky", "Zurich, ?dso=1",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0), dso=True),
     "739 galaxies, clusters, nebulae and planetary nebulae from the "
     "Revised NGC (public domain), pre-filtered to magnitude 11. About 30 "
     "well-known ones &mdash; Andromeda Galaxy, Whirlpool Galaxy, the Double "
     "Cluster among them &mdash; are labelled by name, the same way stars "
     "and planets are."),
    ("A narrower width", "Zurich, ?w=90",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0), width=90),
     "?w= rescales the render to fit any terminal &mdash; both dimensions "
     "scale together so the aspect ratio stays honest, just clamped to a "
     "sane range. Same sky as the first panel, fit to 90 columns instead "
     "of the default."),
    ("Facing a direction", "Zurich, facing=NNW",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 23, 0), facing="NNW", span=90),
     "A 90&deg; window instead of the full 360&deg; sweep, with the row "
     "count derived from the span so the shapes stay undistorted &mdash; "
     "this is the Plough actually looking like one, not stretched across "
     "a wide panorama."),
]


def cmd_for(kwargs):
    place = kwargs.get("place", "").replace(" ", "%20")
    q = []
    if "when" in kwargs:
        q.append(f"t={kwargs['when']:%Y-%m-%dT%H:%M}")
    if kwargs.get("find"):
        q.append(f"find={kwargs['find']}")
    if kwargs.get("width"):
        q.append(f"w={kwargs['width']}")
    if kwargs.get("facing"):
        q.append(f"facing={kwargs['facing']}")
    if kwargs.get("span"):
        q.append(f"span={int(kwargs['span'])}")
    if "quadrant" in kwargs:
        q.append(f"quadrant={kwargs['quadrant']}" if kwargs["quadrant"] else "quadrant")
    if kwargs.get("dso"):
        q.append("dso=1")
    if kwargs.get("animate"):
        q.append("animate")
    qs = "&".join(q)
    url = f"skymap.sh/{place}" + (f"?{qs}" if qs else "")
    # Quoted: zsh (the default shell on macOS) treats a bare ? as a glob
    # character and errors instead of running an unquoted URL like this.
    return f"curl '{url}'" if qs else f"curl {url}"


TERM = """<div class="term"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
<span class="t">{cmd}</span></div><pre>{body}</pre></div>"""

# Same bar chrome as TERM, but the body is the actual saved GIF (see
# demo_animate.gif, produced by /Zurich/animate.gif) instead of a rendered
# <pre> -- there's no static text equivalent of "the whole night streamed
# live", so this is the one panel that isn't api.compose() output.
IMG_TERM = """<div class="term"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
<span class="t">{cmd}</span></div><img src="demo_animate.gif" alt="Animated night sky over Zurich, stars and planets fading in with twilight" style="display:block;width:100%"></div>"""

# .cta and .t match api.PAGE exactly (same header on every page, demo included).
# Kept as a literal copy rather than an import because this is a static build
# script generating a standalone file, not a live request handler -- but any
# header style change to api.PAGE should be mirrored here too.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skymap.sh -- demo</title><style>
 body{{margin:0;background:#04060a;color:#c9d1d9;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;padding:24px 16px 48px;-webkit-font-smoothing:antialiased}}
 .wrap{{max-width:1180px;margin:0 auto}}
 .t{{color:#6e7681;font-size:12px;margin:0 0 18px}}
 .t b{{color:#c9d1d9;font-weight:600}}
 a{{color:#87d7ff}}
 .cta{{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px 14px;margin:0 0 14px;color:#7ee787;font-size:13px;display:inline-block;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}}
 .cta::before{{content:"$ ";color:#6e7681}}
 h2{{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:#8b949e;font-weight:600;margin:32px 0 10px;font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
 h2 .n{{text-transform:none;letter-spacing:0;font-weight:400;color:#6e7681;margin-left:8px;font-family:ui-monospace,Menlo,monospace}}
 .term{{background:#080b11;border:1px solid #1b2027;border-radius:10px;overflow:hidden;box-shadow:0 10px 34px rgba(0,0,0,.6)}}
 .bar{{background:#12161d;padding:9px 14px;display:flex;align-items:center;gap:7px;border-bottom:1px solid #1b2027}}
 .dot{{width:11px;height:11px;border-radius:50%}}
 .bar .t{{margin:0 0 0 10px;font-size:11.5px;color:#8b949e}}
 pre{{margin:0;padding:14px 14px 16px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
      font-size:10px;line-height:1.22;font-variant-ligatures:none;-webkit-font-smoothing:antialiased}}
 code{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:#9fb4c7}}
 .cap{{color:#6e7681;font-size:12.5px;margin:9px 2px 0;line-height:1.55;font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
</style></head><body><div class="wrap">
<pre class="cta">curl skymap.sh/demo</pre>
<p class="t"><b>skymap.sh</b>
<a href="/">home</a> · <a href="/demo">demo</a> · <a href="/help">help</a> · <a href="/legend">legend</a></p>
<p class="t">{nav_row}</p>
{sections}
</div></body></html>"""

nav_row = " &middot; ".join(
    f'<a href="#section-{i}">{i}. {title}</a>' for i, (title, _sub, _kwargs, _cap) in enumerate(CASES, 1))

sections = []
for i, (title, sub, kwargs, cap) in enumerate(CASES, 1):
    cmd = cmd_for(kwargs)
    if kwargs.get("animate"):
        # No static-text equivalent of "the whole night streamed live" --
        # demo_animate.gif is a saved copy of the real /animate.gif stream,
        # not api.compose() output like every other panel here.
        term_html = IMG_TERM.format(cmd=cmd)
    else:
        r = api.Request(color=True, **kwargs)
        res = api.compose(r)
        body = api.ansi_to_html(res.text)
        term_html = TERM.format(cmd=cmd, body=body)
    sections.append(
        f'<h2 id="section-{i}">{i} &middot; {title} <span class="n">{cmd}</span></h2>\n'
        f'{term_html}\n'
        f'<p class="cap">{cap}</p>')

open("sky_demo.html", "w").write(
    PAGE.format(nav_row=nav_row, sections="\n".join(sections)))
print("ok")
