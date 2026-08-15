#!/usr/bin/env python3
"""Rebuild the copy-review checklist. Re-run after any copy change.

DONE holds what has been signed off. It is seeded into the page's own
localStorage on load without clobbering ticks made in the browser, so the
two ways of marking something reviewed do not fight.
"""
import sys, os, json, html as H
from urllib.parse import quote
sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
import etymology as e, blurbs, facts, api

DONE = {
    "note-Messier",          # rewritten and approved 14 Aug
    "note-Dreyer",           # approved as written 14 Aug
    "note-Bayer",            # rewritten and approved 14 Aug
    "note-Yale",             # rewritten and approved 14 Aug
    "Aldebaran",             # blurb + etymology combined 14 Aug
    "Algol",                 # blurb + etymology combined 14 Aug
    "Altair",                # written fresh, inline script + link 14 Aug
    "Andromeda Galaxy",      # blurb + etymology combined 14 Aug
    "Antares",               # blurb + etymology combined 14 Aug
    "Arcturus",             # blurb + etymology combined 14 Aug
    "Betelgeuse",           # blurb + etymology combined 14 Aug
    "Big Dipper",           # blurb + etymology combined 14 Aug
    "Capella",              # blurb + etymology combined 14 Aug
    "Crab Nebula",          # blurb + etymology combined 14 Aug
    "Deneb",                # blurb + etymology combined 14 Aug
    "Double Cluster",       # blurb + etymology combined 14 Aug
    "Dumbbell Nebula",      # blurb + etymology combined 14 Aug
    "Geminids",             # blurb + etymology combined 14 Aug
    "Hercules Cluster",     # blurb + etymology combined 14 Aug
    "Lagoon Nebula",        # approved as written 14 Aug
    "Lyrids",               # approved as written 14 Aug
    "Jupiter",              # blurb + etymology combined 14 Aug
    # The 57 figures and the Milky Way, written 15 Aug. Signed off one at a
    # time from here on, so a name in this block was read on the page.
    "Andromeda",            # rewritten to name the family, approved 15 Aug
    "Aquila",               # opening sentence rewritten, approved 15 Aug
    "Aries",                # "first zodiac sign" spelled out, approved 15 Aug
    "Auriga",               # opens on the shape now, approved 15 Aug
    "Canes Venatici",       # reworded after a rejection, approved 15 Aug
    "Winter Hexagon",       # approved as written 15 Aug
    "Triangulum Galaxy",    # approved as written 15 Aug
    "Triangulum Australe",  # voyage sentence rewritten, approved 15 Aug
    "Whirlpool Galaxy",     # Rosse and the telescope rewritten, approved 15 Aug
    "Virgo",                # opening reworded, approved 15 Aug
    "Aquarius",             # first sentence rewritten, approved 15 Aug
    "Winter Triangle",      # rewritten, approved 15 Aug
}

PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"
S = os.path.dirname(os.path.abspath(__file__))
def esc(s): return H.escape(s or "")

names = sorted(set(blurbs.BLURBS) | set(e.ETYMOLOGY) | set(facts.FACTS))
rows = []
for n in names:
    _g, blurb = blurbs.BLURBS.get(n, ("", ""))
    ety, hist, fig = e.ETYMOLOGY.get(n, {}), facts.history_for(n), e.figure_rows(n)
    bits = []
    if blurb: bits.append(f'<div class="c"><span class="t">blurb</span>{esc(blurb)}</div>')
    if ety.get("story"): bits.append(f'<div class="c"><span class="t">etymology</span>{esc(ety["story"])}</div>')
    if ety.get("unsure"): bits.append(f'<div class="c u"><span class="t">not settled</span>{esc(ety["unsure"])}</div>')
    if ety:
        meta = " &middot; ".join(x for x in [esc(ety.get("from")), esc(ety.get("literal")),
               f'<span class="rd">{esc(ety.get("reading"))}</span>' if ety.get("reading") else ""] if x)
        bits.append(f'<div class="c"><span class="t">rows</span>{meta}</div>')
    if fig:
        art = "\n".join((f'<span class="run">{esc(t)}</span>' if s else esc(t)) for t, s in fig)
        bits.append(f'<div class="c"><span class="t">figure</span><pre>{art}</pre></div>')
    if hist:
        hs = "<br>".join(f'{esc(k)}: ' + (esc(str(v)) if not isinstance(v, list)
             else ", ".join(f"{a} {b}" for a, b in v)) for k, v in hist)
        bits.append(f'<div class="c"><span class="t">history</span>{hs}</div>')
    tags = "".join(f'<span class="tag">{t}</span>' for t, ok in
        [("blurb", blurb), ("etym", bool(ety)), ("figure", bool(fig)),
         ("unsure", bool(ety.get("unsure"))), ("history", bool(hist))] if ok)
    rows.append(f'''<li class="row"><label><input type="checkbox" data-k="{esc(n)}">
      <span class="nm">{esc(n)}</span></label><span class="tags">{tags}</span>
      <a class="go" href="http://127.0.0.1:{PORT}/{quote(n)}/about" target="_blank">open &rarr;</a>
      <div class="body">{"".join(bits)}</div></li>''')

notes = "".join(f'''<li class="row"><label><input type="checkbox" data-k="note-{k}">
    <span class="nm">{esc(k)}</span></label><span class="tags"><span class="tag">standing note</span></span>
    <div class="body"><div class="c">{esc(v)}</div></div></li>'''
    for k, v in api.CATALOGUE_NOTES.items())

# The one-liners, all of them together at the bottom.
#
# They are their own pass on purpose. A gloss completes "X is ..." in a
# handful of words, and the only way to tell whether ninety of them are
# pulling in one direction is to read them one after another rather than
# one per paragraph, forty rows apart. Same reason a proof-reader reads all
# the headings before reading the article.
#
# Own checkbox keys and own count, so ticking a paragraph never ticks its
# one-liner and the number at the top keeps meaning what it meant.
one_liners = "".join(f'''<li class="row gl"><label>
    <input type="checkbox" data-k="gloss-{esc(n)}" data-g="1">
    <span class="nm">{esc(n)}</span></label>
    <span class="gv">is {esc(g)}</span></li>'''
    for n, (g, _b) in sorted(blurbs.BLURBS.items()) if g)

doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Copy review checklist</title><style>
body{{margin:0;background:#04060a;color:#c9d1d9;padding:28px 18px 90px;
font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;font-size:13px}}
.w{{max-width:1000px;margin:0 auto}} h1{{font-size:24px;color:#e6ebf2;margin:0 0 .2rem}}
.sub{{color:#7d8694;margin:0 0 1.4rem}}
.bar{{position:sticky;top:0;background:#04060a;padding:10px 0 14px;
border-bottom:1px solid #1c2027;margin-bottom:18px;z-index:5}}
h2{{font-family:ui-sans-serif,-apple-system,sans-serif;font-size:11px;
text-transform:uppercase;letter-spacing:.09em;color:#8fb6e0;margin:2.4rem 0 .6rem}}
ul{{list-style:none;padding:0;margin:0}}
.row{{border:1px solid #1c2027;border-radius:8px;background:#070a0e;padding:12px 14px;margin:0 0 10px}}
.row.done{{opacity:.38}} label{{cursor:pointer;display:inline-flex;align-items:center;gap:9px}}
input{{width:15px;height:15px;accent-color:#87d7ff;cursor:pointer}}
.nm{{font-size:15px;color:#e6ebf2}} .tags{{margin-left:10px}}
.tag{{display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:.07em;
color:#8b93a3;border:1px solid #262c35;border-radius:4px;padding:1px 6px;margin-right:4px}}
.go{{float:right;color:#9aa7b4;text-decoration:none;font-size:12px}} .go:hover{{color:#87d7ff}}
.body{{margin-top:10px;padding-left:24px}}
.c{{margin:0 0 9px;line-height:1.55;color:#c9d1d9;max-width:78ch}} .c.u{{color:#c9a227}}
.t{{display:inline-block;min-width:82px;color:#7d8694;font-size:11px;
text-transform:uppercase;letter-spacing:.07em;vertical-align:top}}
.rd{{color:#e6ebf2}}
pre{{display:inline-block;margin:4px 0 0;font-size:12px;line-height:1.35;white-space:pre;vertical-align:top}}
.run{{white-space:nowrap;unicode-bidi:isolate}}
.gl{{padding:8px 14px}} .gl label{{align-items:baseline}}
.gl .nm{{font-size:13px;min-width:20ch;color:#8fb6e0}}
.gv{{color:#c9d1d9;line-height:1.5}}
</style></head><body><div class=w>
<h1>Copy review</h1><p class=sub>Every page carrying hand-written words. Ticks are remembered.</p>
<div class=bar><span id=count></span> &nbsp; <a href="#" id=reset style="color:#9aa7b4">reset</a></div>
<h2>Standing notes &mdash; each appears on many pages, review once</h2><ul>{notes}</ul>
<h2>Objects</h2><ul>{''.join(rows)}</ul>
<h2>One-liners &mdash; read together, they are one voice or they are not</h2>
<p class=sub>Each completes &ldquo;X is &hellip;&rdquo;. Written to run beside the
title and not on any page yet, so this list is the only place they can be
judged against each other. Counted separately: <span id=gcount></span>.</p>
<ul>{one_liners}</ul></div><script>
var K='skymap.copyreview', SEED={json.dumps(sorted(DONE))};
function load(){{try{{return JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{return {{}}}}}}
var st=load();
SEED.forEach(function(k){{ if(st[k]===undefined) st[k]=true; }});
localStorage.setItem(K,JSON.stringify(st));
function paint(){{var n=0,t=0,gn=0,gt=0;
  document.querySelectorAll('input[data-k]').forEach(function(i){{
    var g=i.dataset.g; if(g){{gt++}}else{{t++}}
    i.checked=!!st[i.dataset.k];
    i.closest('.row').classList.toggle('done',i.checked);
    if(i.checked){{ if(g){{gn++}}else{{n++}} }}}});
  document.getElementById('count').textContent=n+' of '+t+' reviewed';
  document.getElementById('gcount').textContent=gn+' of '+gt+' read';}}
document.addEventListener('change',function(ev){{var i=ev.target;
  if(!i.dataset||!i.dataset.k)return; st[i.dataset.k]=i.checked;
  localStorage.setItem(K,JSON.stringify(st)); paint();}});
document.getElementById('reset').onclick=function(e){{e.preventDefault();
  st={{}}; localStorage.setItem(K,'{{}}'); paint();}};
paint();
</script></body></html>"""
open(f"{S}/copy-review.html", "w").write(doc)
print("rebuilt with", len(DONE), "marked done")
