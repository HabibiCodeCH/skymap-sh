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

# {header} is the *real* header_html() output (command bar + nav + social
# icons), not a hand-copy -- that was the whole bug this once drifted into:
# a hand-copied header frozen from whatever api.py looked like on the day
# this was last generated, silently going stale (most recently: showing the
# old static "$ curl skymap.sh/demo" chip with no #q input at all, months
# after the live site grew an actual interactive command bar). The header
# CSS/JS below is still a literal copy, though, same reasoning as ever --
# this is a static build script, not a live request handler, so it can't
# just import api.PAGE's <style>/<script> wholesale without pulling in
# rules for things this page doesn't have (#chart-pre, #drawer, KBD...).
# Any command-bar style/behaviour change to api.py should be mirrored here
# too -- regenerate with `python3 build_sky_html.py` after.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>skymap.sh -- demo</title>
<script>
document.documentElement.classList.add('js');
</script>
<style>
 body{{margin:0;background:#04060a;color:#c9d1d9;font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;padding:24px 16px 48px;-webkit-font-smoothing:antialiased}}
 .wrap{{max-width:1180px;margin:0 auto}}
 .t{{color:#6e7681;font-size:12px;margin:0 0 18px}}
 a{{color:#87d7ff}}
 .header-row{{display:flex;justify-content:space-between;align-items:center;
             flex-wrap:wrap;gap:12px;margin:0 0 14px}}
 .nav-row{{display:flex;justify-content:flex-end;align-items:center;
          flex-wrap:wrap;gap:8px}}
 .header-row .nav-row{{margin:0;flex:1;min-width:0}}
 .social-icons{{display:inline-flex;gap:8px;margin-left:8px;vertical-align:middle}}
 .social-icons a{{color:#6e7681;display:inline-flex}}
 .social-icons a:hover{{color:#c9d1d9}}
 .social-icons svg{{display:block}}
 /* Drawer -- literal copy of api.py's rules (see its own comments for the
    no-JS-fallback reasoning). Holds the explore form (find another place)
    plus a reset link, same as /catalog, /help, /legend, /stats. */
 #drawer{{margin:0 0 14px}}
 .drawer-section{{margin:0 0 16px;padding:0 0 16px;border-bottom:1px solid #30363d}}
 .drawer-section:last-child{{margin:0;padding:0;border-bottom:0}}
 .drawer-section:empty{{display:none}}
 .drawer-trigger{{display:none}}
 .js .drawer-trigger{{display:inline-flex;align-items:center;justify-content:center;
                      background:#0d1117;border:1px solid #30363d;color:#ffd700;
                      border-radius:4px;width:28px;height:28px;margin-left:8px;
                      font-size:14px;line-height:1;cursor:pointer}}
 .js .drawer-trigger:hover{{border-color:#ffd700}}
 .drawer-close{{display:none}}
 .js .drawer-close{{display:block;position:absolute;top:16px;right:16px;
                    background:none;border:0;color:#ffd700;font-size:16px;
                    line-height:1;padding:6px;cursor:pointer}}
 .js .drawer-close:hover{{color:#fff}}
 .js #drawer{{position:fixed;top:0;right:0;bottom:0;width:320px;max-width:90vw;
             margin:0;padding:56px 16px 16px;background:#0d1117;
             border-left:1px solid #30363d;overflow-y:auto;z-index:20;
             transform:translateX(100%);transition:transform .2s ease}}
 .js #drawer.open{{transform:translateX(0)}}
 .ex{{display:block}}
 .ex form{{display:flex;flex-direction:column;gap:8px;margin:0}}
 .ex input{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
           padding:6px 10px;border-radius:4px;font:inherit;font-size:12px;
           width:100%;box-sizing:border-box}}
 .ex input#whenDate,.ex input#whenTime{{color-scheme:dark}}
 .ex button{{background:#238636;border:0;color:#fff;padding:8px 14px;
            border-radius:4px;font:inherit;font-size:12px;cursor:pointer;
            width:100%}}
 .ex button:hover{{background:#2ea043}}
 .tries{{color:#6e7681;font-size:12px;margin:0}}
 .tries a{{color:#87d7ff;text-decoration:none}}
 .tries a:hover{{text-decoration:underline}}
 .animate-btn{{background:#0d1117;border:1px solid #30363d;color:#ffd700;
              padding:8px 12px;border-radius:4px;font:inherit;font-size:12px;
              cursor:pointer;display:block;width:100%;box-sizing:border-box;
              text-align:center;text-decoration:none;margin:0 0 8px}}
 .animate-btn:hover{{border-color:#ffd700;text-decoration:none}}
 .cmdbar{{display:inline-flex;align-items:center;background:#0d1117;
         border:1px solid #30363d;border-radius:6px;padding:9px 12px;
         margin:0;color:#7ee787;font-size:13px;cursor:text;
         max-width:100%;min-width:min(560px,90vw)}}
 .cmdbar .prompt{{color:#6e7681;margin-right:6px}}
 .cmdbar .fixed{{white-space:pre}}
 .cmdbar .curlword{{color:#6e7681}}
 .cmdbar .field{{display:inline-flex;min-width:0;max-width:100%}}
 .cmdbar input{{background:transparent;border:0;color:#e6edf3;font:inherit;
               padding:0;margin:0;min-width:0;max-width:100%;outline:none}}
 .cmdbar .ghosttext{{color:#3d4451;white-space:pre;pointer-events:none}}
 .cmdbar .measure{{position:absolute;visibility:hidden;white-space:pre;left:-9999px}}
 .cmdbar .grow{{flex:1}}
 .cmdbar .copy{{background:none;border:1px solid #30363d;color:#6e7681;
               border-radius:4px;padding:4px 8px;margin-left:10px;
               font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}}
 .cmdbar .copy:hover{{border-color:#7ee787;color:#7ee787}}
 .cursor{{display:inline-block;width:.55em;height:1.15em;margin-left:1px;
         background:#7ee787;vertical-align:-0.2em;
         animation:blink 1.06s step-end infinite}}
 .cmdbar.focused .cursor{{visibility:hidden;animation:none}}
 @keyframes blink{{0%,50%{{opacity:1}}50.01%,100%{{opacity:0}}}}
 @media (prefers-reduced-motion: reduce){{
   .cursor{{animation:none;opacity:.55}}
 }}
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
</style></head><body>
{header}
<div class="wrap">
{controls}
<p class="t">{nav_row}</p>
{sections}
</div>
<script>
// Command bar: auto-size + click-anywhere-to-focus + ghost-text completion
// against the live GET /complete endpoint + copy button. Literal copy of
// api.py's command-bar IIFE (see its own comments there for the reasoning
// behind each piece).
(function(){{
  var bar=document.getElementById('bar');
  var q=document.getElementById('q');
  var measure=document.getElementById('measure');
  var ghost=document.getElementById('ghost');
  var copyBtn=document.getElementById('copy');
  if(bar&&q&&measure&&ghost){{
    var size=function(){{
      measure.textContent=q.value||'';
      q.style.width=(measure.offsetWidth+2)+'px';
    }};
    var matches=[];
    var fold=function(s){{return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();}};
    var complete=function(){{
      var v=q.value;
      if(!v){{ghost.textContent='';return;}}
      var hit=matches.find(function(c){{
        return fold(c).startsWith(fold(v))&&c.length>v.length;
      }});
      ghost.textContent=hit?hit.slice(v.length):'';
    }};
    var completeAbort=null, completeTimer=null;
    var fetchMatches=function(){{
      if(completeAbort)completeAbort.abort();
      var v=q.value.trim();
      if(v.length<2){{matches=[];complete();return;}}
      completeAbort=new AbortController();
      fetch('/complete?q='+encodeURIComponent(v.toLowerCase().slice(0,24)),
            {{signal:completeAbort.signal}})
        .then(function(r){{return r.json();}})
        .then(function(names){{matches=names;complete();}})
        .catch(function(){{}});
    }};
    size();
    q.addEventListener('input',function(e){{
      size();
      if(e.inputType==='deleteContentBackward'){{matches=[];ghost.textContent='';}}
      if(completeTimer)clearTimeout(completeTimer);
      completeTimer=setTimeout(fetchMatches,120);
    }});
    q.addEventListener('keydown',function(e){{
      if(!ghost.textContent)return;
      var atEnd=q.selectionStart===q.value.length;
      if(e.key==='Tab'||(e.key==='ArrowRight'&&atEnd)){{
        e.preventDefault();
        q.value+=ghost.textContent;
        ghost.textContent='';
        size();
        q.setSelectionRange(q.value.length,q.value.length);
      }}
    }});
    q.addEventListener('focus',function(){{bar.classList.add('focused');}});
    q.addEventListener('blur',function(){{bar.classList.remove('focused');}});
    bar.addEventListener('mousedown',function(e){{
      if(copyBtn&&(e.target===copyBtn||copyBtn.contains(e.target)))return;
      if(e.target!==q){{
        e.preventDefault();
        q.focus();
        q.setSelectionRange(q.value.length,q.value.length);
      }}
    }});
    bar.addEventListener('submit',function(e){{
      e.preventDefault();
      if(ghost.textContent){{
        q.value+=ghost.textContent;
        ghost.textContent='';
        size();
      }}
      var exploreForm=document.getElementById('explore');
      if(exploreForm){{
        if(exploreForm.requestSubmit)exploreForm.requestSubmit();
        else exploreForm.dispatchEvent(new Event('submit',{{cancelable:true}}));
        return;
      }}
      if(q.value)location.href='/'+encodeURIComponent(q.value);
    }});
    if(copyBtn){{
      if(!navigator.clipboard){{
        copyBtn.hidden=true;
      }}else{{
        var copyLabel=copyBtn.textContent;
        var copyResetTimer=null;
        copyBtn.addEventListener('click',function(){{
          var place=q.value+ghost.textContent;
          var path=place.includes(' ')?
            "'skymap.sh/"+place+"'":'skymap.sh/'+place;
          navigator.clipboard.writeText('curl '+path).then(function(){{
            if(copyResetTimer)clearTimeout(copyResetTimer);
            copyBtn.textContent='✓ copied';
            copyResetTimer=setTimeout(function(){{
              copyBtn.textContent=copyLabel;
              copyResetTimer=null;
            }},1400);
          }}).catch(function(){{}});
        }});
      }}
    }}
  }}
}})();
(function(){{
  // Drawer -- literal copy of api.py's IIFE (see its own comments there).
  var trigger=document.getElementById('drawer-trigger');
  var drawer=document.getElementById('drawer');
  var closeBtn=document.getElementById('drawer-close');
  if(!trigger||!drawer)return;
  window.skymapCloseDrawer=function(){{
    drawer.classList.remove('open');
    trigger.setAttribute('aria-expanded','false');
    trigger.textContent='☰';
  }};
  var openDrawer=function(){{
    drawer.classList.add('open');
    trigger.setAttribute('aria-expanded','true');
    trigger.textContent='✕';
  }};
  trigger.addEventListener('click',function(){{
    if(drawer.classList.contains('open'))window.skymapCloseDrawer();else openDrawer();
  }});
  if(closeBtn)closeBtn.addEventListener('click',window.skymapCloseDrawer);
  document.addEventListener('mousedown',function(e){{
    if(!drawer.classList.contains('open'))return;
    if(drawer.contains(e.target)||e.target===trigger)return;
    window.skymapCloseDrawer();
  }});
  var q=document.getElementById('q');
  if(q){{
    document.addEventListener('click',function(e){{
      if(drawer.classList.contains('open')||e.target===q)return;
      q.focus();
      q.select();
    }});
  }}
}})();
</script>
</body></html>"""

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
    PAGE.format(header=api.header_html("demo"), controls=api.controls_html(api.EXPLORE),
               nav_row=nav_row, sections="\n".join(sections)))
print("ok")
