#!/usr/bin/env python3
"""Builds sky_demo.html: six real renders showing off the range of views.

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
    ("ISS pass", "Sydney, marked automatically",
     dict(place="Sydney", when=dt.datetime(2026, 7, 31, 6, 25), tle=TLE),
     "No flag needed &mdash; if the ISS has a real pass overhead right now "
     "(above 10&deg;, sunlit, sky dark enough to see it), it's marked on "
     "the chart automatically. This one peaks at 52&deg;, rising SW and "
     "setting ENE."),
    ("Find one thing", "Zurich, find=Venus",
     dict(place="Zurich", when=dt.datetime(2026, 7, 30, 21, 30), find="Venus"),
     "Naming an object picks the framing for you: a window centred on it in "
     "both axes, a crosshair on the target, directions underneath in fists "
     "rather than degrees. Works for planets, the Moon, any named star, and "
     "asterisms."),
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
    qs = "&".join(q)
    return f"curl skymap.sh/{place}" + (f"?{qs}" if qs else "")


TERM = """<div class="term"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
<span class="t">{cmd}</span></div><pre>{body}</pre></div>"""

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skymap.sh -- demo</title><style>
 body{{margin:0;background:#04060a;color:#c9d1d9;font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;padding:30px 16px 60px}}
 .wrap{{max-width:1180px;margin:0 auto}}
 h1{{font-size:19px;font-weight:600;margin:0 0 4px;color:#e6edf3;letter-spacing:-.01em}}
 .sub{{color:#8b949e;font-size:13.5px;margin:0 0 26px;line-height:1.6}}
 .sub a{{color:#87d7ff}}
 h2{{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:#8b949e;font-weight:600;margin:32px 0 10px}}
 h2 .n{{text-transform:none;letter-spacing:0;font-weight:400;color:#6e7681;margin-left:8px;font-family:ui-monospace,Menlo,monospace}}
 .term{{background:#080b11;border:1px solid #1b2027;border-radius:10px;overflow:hidden;box-shadow:0 10px 34px rgba(0,0,0,.6)}}
 .bar{{background:#12161d;padding:9px 14px;display:flex;align-items:center;gap:7px;border-bottom:1px solid #1b2027}}
 .dot{{width:11px;height:11px;border-radius:50%}}
 .bar .t{{margin-left:10px;font-size:11.5px;color:#8b949e;font-family:ui-monospace,Menlo,monospace}}
 pre{{margin:0;padding:14px 14px 16px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
      font-size:10px;line-height:1.22;font-variant-ligatures:none;-webkit-font-smoothing:antialiased}}
 code{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:#9fb4c7}}
 .cap{{color:#6e7681;font-size:12.5px;margin:9px 2px 0;line-height:1.55}}
</style></head><body><div class="wrap">
<h1>skymap.sh -- demo</h1>
<p class="sub">Six real renders, one composition layer -- <code>api.py</code> is what
<code>cli.py</code>, <code>curl</code>, and this page all call, so none of these can drift
from what the live service actually does. <a href="/">home</a> &middot; <a href="/help">usage</a></p>
{sections}
</div></body></html>"""

sections = []
for i, (title, sub, kwargs, cap) in enumerate(CASES, 1):
    r = api.Request(color=True, **kwargs)
    res = api.compose(r)
    body = api.ansi_to_html(res.text)
    cmd = cmd_for(kwargs)
    sections.append(
        f'<h2>{i} &middot; {title} <span class="n">{cmd}</span></h2>\n'
        f'{TERM.format(cmd=cmd, body=body)}\n'
        f'<p class="cap">{cap}</p>')

open("sky_demo.html", "w").write(PAGE.format(sections="\n".join(sections)))
print("ok")
