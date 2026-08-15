#!/usr/bin/env python3
"""Constellation figure review page. Re-run after any change.

APPROVED drops a figure out of the page entirely, so what is left on screen
is exactly what still needs looking at.
"""
import sys, os, json, html as H
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import art, api, sky, objects

APPROVED = {
    "Canes Venatici",
    "Canis Minor",
    "Aries",
    "Cepheus",
    "Canis Major",
    "Hydrus",
    "Capricornus",
    "Lepus",
    "Winter Triangle",
    "Winter Hexagon",
    "Corvus",
    "Libra",
    "Gemini",
    "Perseus",
    "Phoenix",
    "Vela",
    "Virgo",
    "Triangulum Australe",
    "Cetus",
    "Carina",
    "Columba",
    "Piscis Austrinus",
    "Draco",
    "Aquarius",
    "Centaurus",
    "Eridanus",
    "Hydra",
    "Serpens",
    "Puppis",
    "Ophiuchus",
    "Pavo",
}

S = os.path.dirname(os.path.abspath(__file__))
figs = json.load(open("/tmp/figs_resolved.json"))
new = {objects.CONSTELLATION_NAMES.get(c, c): r for c, r in figs.items()}
# APPROVED has to bite here too. The pre-existing figures live in this list,
# not in `new`, so approving one left it on the page and it read as ignored.
old = [a["name"] for a in sky._load("asterisms.json")
       if a["name"] not in new and a["name"] not in APPROVED]

# The count has to come from the file the art is drawn from. figs_resolved is
# the first draft and goes stale the moment a figure is corrected.
LIVE = {a["name"]: a for a in sky._load("asterisms.json")}


def card(name, conf=None, rec=None):
    body = "\n".join(api.ansi_to_html(l) for l in art.asterism_art(name))
    meta = "existing"
    if rec:
        n = len({h for L in LIVE[name]["lines"] for h in L})
        meta = f'{n} stars &middot; <span class="cf">{conf}</span>'
    return (f'<div class="card {conf or "old"}"><h3>{H.escape(name)}</h3>'
            f'<p class="meta">{meta}</p><pre>{body}</pre></div>')

def grp(k):
    return "".join(card(n, k, r) for n, r in sorted(new.items())
                   if r["conf"] == k and n not in APPROVED)

left = sum(1 for n in new if n not in APPROVED)
doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Constellation figures</title><style>
body{{margin:0;background:#04060a;color:#c9d1d9;padding:26px 18px 90px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;font-size:13px}}
.w{{max-width:1300px;margin:0 auto}} h1{{font-size:23px;color:#e6ebf2;margin:0 0 .2rem}}
.sub{{color:#7d8694;margin:0 0 1.4rem}}
h2{{font-family:ui-sans-serif,-apple-system,sans-serif;font-size:11px;
text-transform:uppercase;letter-spacing:.09em;color:#8fb6e0;margin:2.4rem 0 .7rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}}
.card{{border:1px solid #1c2027;border-radius:8px;background:#070a0e;padding:12px}}
.card.check{{border-color:#3d3320}} .card.old{{opacity:.7}}
h3{{font-size:14px;color:#e6ebf2;margin:0 0 .1rem}}
.meta{{color:#7d8694;font-size:11px;margin:0 0 .6rem}}
.cf{{color:#8b93a3}} .card.check .cf{{color:#c9a227}}
pre{{margin:0;font-size:9.5px;line-height:1.2;white-space:pre;overflow:visible;
font-variant-ligatures:none}}
</style></head><body><div class=w>
<h1>Constellation figures</h1>
<p class=sub>{left} still to review &middot; {len(APPROVED)} approved and hidden</p>
<h2>New &mdash; claimed sure</h2><div class=grid>{grp("sure")}</div>
<h2>New &mdash; check me</h2><div class=grid>{grp("check")}</div>
<h2>Existing, for comparison</h2><div class=grid>{"".join(card(n) for n in sorted(old))}</div>
</div></body></html>"""
open(f"{S}/constellations.html", "w").write(doc)
print(f"{left} to review, {len(APPROVED)} hidden")
