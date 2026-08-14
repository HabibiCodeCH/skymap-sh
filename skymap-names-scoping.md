# skymap.sh — the durable half: names, figures and old descriptions

Scoping only. No code written. 13–14 Aug 2026.

## 1. What this actually is

It started as "a names tab". It is bigger than that, and naming the bigger
thing changes the decisions underneath it.

Every object page is already split in two: what the object *is* (left, same
for everyone, indexable) and what it is *doing tonight* (right, computed per
visitor). The left column is currently thin — a portrait, a sentence, a fact
table. The right column is where all the work has gone.

**The proposal is to make the left column into a real encyclopedia entry**:
where the name came from, what people called it before, and what the
observers who first catalogued it actually wrote down when they looked at it.

That is a positioning move, not a feature: *a small encyclopedia of the sky,
which also tells you where to look tonight.* Nothing else does both. The
planetarium apps compute and do not explain; the reference sites explain and
do not know where you are standing.

Three strands, and they reinforce each other:

| strand | where it comes from | covers |
|---|---|---|
| **Names** (§3–5) | hand-written, checked against IAU and Kunitzsch | ~90 written, 1,220 derived |
| **Figures** (§6) | drawn in ASCII, house-style | wherever a name has a shape |
| **Old descriptions** (§7) | public-domain catalogues, quoted | 109 Messier + up to 749 NGC |

The third is new since the first draft and is the cheapest of the three by a
wide margin, because **the writing is already done and out of copyright**.

## 2. Why it belongs on this site specifically

- It is the only content here that is durable in the strongest sense. A blurb
  is rewritable; an etymology was fixed in the 9th century and Messier's
  sentence was fixed in 1781.
- It is what people actually search. "What does Betelgeuse mean", "why is it
  called the Crab Nebula" are evergreen queries this site currently answers
  with nothing.
- It fits the existing split exactly. No new page architecture, no new
  computation, nothing that changes per visitor.
- It is the one kind of depth a solo project can have that a funded app
  cannot copy quickly, because it is writing rather than engineering.

## 3. Coverage tiers

Same pattern as `blurbs.py` (~40 hand-written, rest generated) and `facts.py`
(36 hand-written, rest empty), but with a far better floor, because **the
designation half is fully derivable from data already on disk**.

**Tier 0 — derived, all 1,220 objects, zero prose.**
`stars.json` carries `b` (Bayer letter, as a real Greek glyph) and `c`
(constellation) for all 2,887 stars. `deepsky.json` carries `id` (NGC) for
749 and `n` (Messier designation) for 109. So every object can say something
true and specific with nothing written by hand. See figure 06.

**Tier 1 — hand-written, ~90 entries.**
9 solar-system bodies · ~35 stars · 28 DSO common names · ~10 asterisms ·
12 showers (one shared rule covers all twelve).

**Tier 2 — later.** The remaining ~100 named stars at mag ≤ 3, the other 18
asterisms.

## 4. Stars are the strongest case, not the planets

Roughly two thirds of the 327 named stars carry Arabic names, and they are
one story told many times: Ptolemy's Greek positional descriptions →
translated into Arabic → clipped into single words → transliterated by
medieval Latin scribes who did not read Arabic → errors frozen in place.

- **Betelgeuse** — يد الجوزاء *Yad al-Jawzā'*, "hand of Jawzā". The ي was
  misread as ب, which differ only by where the dot sits, giving *Bat
  al-Jawzā'*, which means nothing.
- **Rigel** — رجل *rijl*, "foot", of the same figure. Orion's two brightest
  stars are the hand and the foot of one body, and the pages can link.
- **Aldebaran** — الدبران *al-Dabarān*, "the follower". It follows the
  Pleiades across the sky. A name that is an instruction.
- **Vega** and **Altair** — the falling eagle and the flying eagle. Two
  thirds of the Summer Triangle is one pair of birds.
- **Deneb** — ذنب *dhanab*, "tail", the most productive root in the sky:
  Deneb, Denebola, Deneb Algedi, Deneb Kaitos. One root, four pages.
- **Algol** — الغول *al-Ghūl*, "the ghoul", an eclipsing variable in
  Medusa's severed head. Whether anyone noticed the variability before
  Montanari in 1667 is genuinely disputed, and the page should say so.
- Non-Arabic for contrast: **Sirius** (Greek, "scorching"), **Arcturus**
  ("bear guard"), **Antares** ("rival of Ares", for the colour), **Procyon**
  ("before the dog").

Deep sky is a different flavour and shorter per object, but every one has a
name and a date: the **Crab** is Rosse's 1844 sketch, which looked like a
crab where the photographs never did; the **Whirlpool** is Rosse again, 1845,
the first spiral structure anyone saw. And the Messier list exists because
Messier hunted comets and needed a register of things that fool you — M1 is
the Crab because it fooled him first, in 1758.

**The Pleiades is the best page on the site for this**: Subaru, Krittika,
Matariki, al-Thurayyā, Seven Sisters, and six stars visible where nearly
every tradition counts seven.

## 5. Where it goes — `/{object}/history`

**Decided.** The object page you land on stays about *where to find it*. All
the deep durable material gets its own page at `/{object}/history`.

Precedent: `/{place}/events` and `/{object}/evolution.gif` are both
object-scoped sub-paths.

### 5.1 The split

| stays on `/Venus` | moves to `/Venus/history` |
|---|---|
| portrait, lede*, infobox | etymology, and the six figures |
| where it is tonight | Messier and Smyth quotations |
| a two-line teaser and a link | discovery narrative |
| | symbols (§7a) |
| | the infobox's "History" rows: `discovered`, `first_photo`, `first_visit`, `missions` |

That last row is a bonus rather than a cost. Those four rows currently pad an
infobox already carrying twenty, and they are the ones least related to
finding the thing tonight. Moving them declutters the object page and gives
`/history` a spine even before a word of etymology is written.

\* **The ledes are the user's to write**, not generated and not drafted here.
The object page's job is now sharper than when `blurbs.py` was written — it
is *where to find this thing* — so the ledes want revisiting against that,
and they are the one piece of copy that has to carry the page on its own.

### 5.2 The caveat that matters

**Do not strip all durable content off the object page.** `blurbs.py`'s
docstring is explicit about why the static half exists: *"A search engine
sees a different page every time it crawls: the altitude moves, the rise time
moves, the chart is redrawn. There is nothing stable for it to decide what
/Venus is about. This is the stable half."*

The lede and the infobox stay. What moves is the *deep* material, which was
never there in the first place. Undoing that decision by accident while
implementing this would be easy and would cost the site its indexability.

### 5.3 Why `history` is the right word

- Plain English, and it is what people search.
- It already exists as the infobox's own block heading, so the site is not
  learning a new word for a thing it already names.
- `names` is too narrow now that the page carries Messier quotations and
  discovery. `about` is vague and already in `RESERVED`. `lore` reads
  fannish and the sources warn against exactly that register.
- For a star, "the history of the name" is natural, so the word stretches
  over etymology without strain.

### 5.4 Properties

- `curl skymap.sh/Betelgeuse/history` works, which a tab cannot do.
- Its own title, description and card. "What does Betelgeuse mean" is a
  different query from "where is Betelgeuse tonight", and now they are
  different URLs.
- **No place segment, and none accepted** — same argument as
  `evolution.gif`. Where you stand does not change what a name means, which
  makes this the only fully cacheable page on the object routes.
- **`history` must be added to `RESERVED`** at `objects.py:42`, alongside
  `events` and `sphere`, so no object can ever claim the path.

Rejected: real tabs (need script, break the durable/live split, no terminal
equivalent) and a `<details>` block (cannot be linked to or indexed
properly).

## 6. The six figures

All six are in the rendered preview at
`scratchpad/names-ascii.html`, drawn at the site's real colours and font
stack. Widths are chosen against two real constraints: the static column is
390px (≈46 monospace columns at 11px) and `object_infobox()` already formats
the terminal to 76.

| # | shape | for | cols |
|---|---|---|---|
| 01 | descent rail | one star, one line of transmission | 46 |
| 02 | descent, two-column | the same, for the terminal | 76 |
| 03 | transmission with a branch | the planets | 76 |
| 04 | root cluster | a shared root, doubling as navigation | 68 |
| 05 | convergence | independent names, no common ancestor | 62 |
| 06 | designation ladder | every object, derived | 74 |

**01 / 02 — the descent rail.** A continuous left rail rather than stacked
arrows, so it reads as one descent. The `✕` marks where the *meaning* was
lost, not merely where the spelling changed, which is the whole story for a
third of the star names.

**03 — transmission with a branch.** The planets are not a descent, they are
one Babylonian list translated four times. The branch is the payoff: Thursday
and *jeudi* are the same day named twice, once by translating the god and
once by keeping him. No other figure on the site can show that.

**04 — the root cluster, and the best value of the six.** One Arabic root,
four stars, four pages that already exist, every leaf a link. It turns an
etymology block into navigation. `dhanab` alone earns four pages;
`al-Jawzā'` ties Betelgeuse to Rigel.

**05 — convergence, and the one that keeps the feature honest.** The Pleiades
names share no ancestor. Drawing them as a descent would invent a
relationship, so the arrows point inward and the caption says there is no
shared root.

**06 — the designation ladder.** Free. Derived rows for all 1,220 objects,
optional hand-written gloss. A ladder rather than a tree, because these are
parallel registers, not descent.

### 6.1 The one hard rule

**Romanised inside a figure; original script parked at the end of a line or
on its own.** A non-Latin run inside an aligned column falls back to a
proportional system font and smears the columns after it. Section 07 of the
preview demonstrates the failure deliberately, next to the fix.

### 6.2 Fonts — corrected from the first draft

The first draft framed font coverage as a hard limit with three options. That
was wrong, because this project already built a fourth and shipped it.

Verified: there is **no `@font-face` anywhere in the repo** and no route
serves a `.ttf` or `.woff`, so the HTML page uses the system monospace stack
only. The two bundled TTFs are server-side, for the og.png cards
(`card.py:33`) and the GIFs (`gif.py:22`).

Measured from the cmap tables:

| | Greek | Arabic | Hebrew | Devanagari | CJK | braille | box |
|---|---|---|---|---|---|---|---|
| JetBrains Mono | yes | no | no | no | no | **no** | yes |
| DejaVu Sans Mono | yes | yes | no | no | no | **no** | yes |

Neither bundled font has a single braille glyph, so `gif.py:151` **draws
braille itself**, geometrically, eight dots on a 2×4 grid at 4×
supersampling. That is the precedent: when no font had the glyph, this
project drew it. It works for eight dots on a grid and does not scale to 参.

### 6.3 Original scripts — required, and solved

**Decided: the original scripts ship.** Transliteration alone was the easy
answer and it throws away most of the point. The solution is three separate
mechanisms for three surfaces, and each one already exists here.

**Web — scripts go in the markup layer, never inside a `<pre>`.**
This costs nothing, because the object page already has both layers on the
same column. `infobox_html()` at `api.py:2164` is a `<dl>` laid out as a
two-column grid, and its docstring says why: *"A `<pre>` can only scroll: a
long value like Saturn's moon count ran off the side of a 390px sidebar with
no way to read the rest."* Nothing in a `<dl>` has to align with anything, so
a proportional fallback for an Arabic or CJK run is harmless there.

So the rule from §6.1 stops being a limitation and becomes a layer
assignment:
- **Figures** stay in `<pre>`, transliteration only, box-drawing and Greek.
- **Script rows** are `<dl>` rows, with `lang` and `dir` attributes so the
  browser picks a sensible face and gets bidi right rather than guessing.

**Terminal — emit both, and accept boxes.**
This is already the house position, set by `PLANET_SYMBOLS` at
`api.py:2241`: *"a terminal shows them if the reader's own font has them, and
a box if not, which is the same deal every other symbol on this site
offers."* Transliteration always sits adjacent, so the line still reads for
anyone whose font comes up short.

**Card and GIF — a fourth tier on the fallback ladder.**
The existing ladder is JetBrains Mono → DejaVu for seven known gaps → drawn
by hand for braille. Add: → **a subset font for the scripts**.

The trick is that this content is hand-written and bounded, so **the exact
set of codepoints is known at build time**. A `build_scriptfont.py` reads
`names.py`, collects every non-Latin codepoint in it, and subsets Noto down
to precisely those glyphs. Measured with `fontTools.subset`, which is already
a dependency:

| script | needed | subset |
|---|---|---|
| Arabic | — | **0 KB, already covered by bundled DejaVu** |
| Hebrew | 19 chars | 11.0 KB |
| Devanagari | 25 chars | 3.4 KB |
| CJK | 23 chars | 8.3 KB (from a 53 MB source) |
| | | **~23 KB total** |

Three things make this the right answer rather than a compromise:

1. **It is server-side only.** The card and GIF are rastered by `card.py` and
   `gif.py`; a browser never downloads any of it. `SPEC-page-weight.md`
   governs what the browser fetches, so this does not touch it. There is
   still no `@font-face` and no webfont, and the earlier "a webfont is the
   wrong answer" conclusion stands unchanged — this is not one.
2. **Arabic, the largest and most complex script here, is already done.**
   DejaVu is bundled and already wired as the fallback.
3. **`fontTools` is already in `requirements.txt`.** It moves from test-only
   to test-and-build, which keeps it out of the runtime path either way.

Caveats, honestly:
- Those numbers were measured against macOS system fonts, which cannot be
  bundled. The real build fetches Noto (OFL 1.1, the same licence as the
  JetBrains Mono already in `fonts/`). Same ballpark, not the same bytes.
- **The subset must be regenerated whenever an entry adds a character**, so
  it needs a test that fails when a codepoint in `names.py` is missing from
  the subset. `test_sky.py:1207` is already exactly this test for the plane
  arrows and is the model to copy.
- **Most scripts have no monospace equivalent**, so on the card the script
  must be drawn in the text furniture rather than in the chart's monospace
  grid. `gif.py` depends on DejaVu's advance width matching at 10.00; a Noto
  subset will not match and must not be asked to.

## 7. Old descriptions — the cheapest strand, and the encyclopedia feel

The idea: alongside what a thing is called, show **what the person who first
catalogued it wrote when they looked at it**. Quoted, dated, attributed.

This is the strand that makes the site read like an encyclopedia rather than
a database with prose bolted on, and the writing is already done.

### 7.1 Why quotation also solves the accuracy problem

Earlier the concern was avoiding claims. A dated quotation is not a claim
about the object, it is a fact about what someone said — true regardless of
whether they were right. Messier calling M1 "a whitish light, elongated like
a candle flame" is *correct as a quotation forever*, even though the object
is a supernova remnant and he thought it might be a comet. The hedge is built
into the form.

That also fixes the voice problem. Quoted 1781 French, visibly marked as
such, cannot be mistaken for the site talking, so it adds a second voice
rather than diluting the house one.

### 7.2 The sources, best first

Sourcing detail, URLs and licence reasoning live in `PD-source-urls.md` and
`SOURCES-object-lore.md`. Summary and the decisions that follow from them:

**Messier's catalogue, 1781** — *Connaissance des Temps* for 1784. Messier
died 1817; unambiguously public domain. 110 objects, of which **109 are
already in `deepsky.json`** (M25 and M40 absent, both for reasons
`LICENSES.md` already gives). The single best fit on this list.
- **Correction to the first draft, which was wrong.** There is **no
  public-domain English Messier.** Every English rendering in circulation is
  modern and in copyright, including the SEDS one that gets quietly copied
  everywhere. So the plan is not "quote the French *or* an old translation" —
  it is **translate the 1781 French ourselves**, which makes the translation
  our own work, ours to licence permissively, and worth citing as such.
- Show the French, then our own translation under it. That is now the only
  correct route, and it happens to be the better-looking one.
- Bonus: Messier consistently calls galaxies nebulae, the distinction not
  existing yet. Free historical contrast on 40-odd pages.

**Smyth, *A Cycle of Celestial Objects*, 1844** — the Bedford Catalogue.
Smyth died 1865, public domain. ~850 objects including double stars, in
florid Victorian prose with unusually vivid colour descriptions. Highest
charm per line of anything available, and the natural source for the star
pages Messier never reaches.

**Peters & Knobel, *Ptolemy's Catalogue of Stars*, 1915** — Carnegie
Institution, public domain, free PDF and plain text. **This is the
public-domain English route into Ptolemy**, and the star-name work needs it,
because the whole Arabic transmission story starts with Ptolemy's positional
descriptions. Toomer's 1984 translation is fully in copyright: do not quote
it.

**Schjellerup, 1874** — al-Ṣūfī's *Book of Fixed Stars* in French, public
domain, and the only pre-modern complete-ish translation. This is the actual
primary source for Arabic star names, so it matters more to §4 than anything
else on this list. Modern translations (Hafez 2010, al-Ajaji 2021) are in
copyright. Availability needs chasing — HathiTrust, then archive.org.

**Dreyer's NGC, 1888** — public domain, covers all 749. Descriptions are a
compressed notation, not prose: `vB, L, vmE 155°, vsvmbM` is "very bright,
large, very much extended at 155°, very suddenly very much brighter in the
middle". Decoding is mechanical and Dreyer published the key himself.
- **Transcribe from the archive.org scan of the 1888 original. Never from
  VizieR VII/118 or HEASARC `ngc2000`.** Sinnott's 1988 machine-readable NGC
  carries Dreyer's description column under an explicit Sky Publishing
  restriction — *"for scientific research purposes only… not for commercial
  purposes"* — and it is the easiest file to download, which is exactly how
  projects get contaminated. This is a sharper reason than the one
  `LICENSES.md` currently records for avoiding the RNGC's description fields,
  and both should be written down.
- Honest assessment: decoded Dreyer is dry. It is the only option that scales
  to all 749, so it is tier-2 filler rather than a headline.

**Clerke 1902, Serviss, Proctor, Webb (pre-1885 editions only)** — Gutenberg
and archive.org, public domain, useful for discovery narrative. Webb's 1917
sixth edition was revised by Espin (d. 1934), so stick to the 4th (1881) or
earlier. Strip Gutenberg headers and footers, and do not use the Gutenberg
name in the product: the text is free, the trademark is not.

**Allen, *Star Names*, 1899** — public domain, comprehensive, and the origin
of most folk etymology in circulation. Kunitzsch, the leading authority on
Arabic star nomenclature, judged it *"generally unreliable with regard to
star names and their derivations"*; the non-Western material is the weakest
and the register is 19th-century diffusionist, which will read badly in 2026
regardless of copyright. Use for *"the name has been connected with…"*
colour, never as an assertion. A standing footer on any page drawing on it:

> *Historical name lore draws on 19th-century sources including R. H. Allen
> (1899), whose etymologies are often unreliable; modern scholarship
> supersedes it where they conflict.*

### 7.2b Attribution-only sources, newly usable

Two things the first draft missed, both CC BY 4.0 — attribution, no
share-alike, so both are compatible with this repo:

- **IAU Catalog of Star Names.** Modern, vetted by historians of astronomy,
  and the thing to prefer over Allen for actual etymology. The first draft
  listed it only as something to check against; it is directly usable.
- **ESA/Hubble and ESA/Webb web texts** (`esahubble.org`, `esawebb.org`) —
  CC BY 4.0 covering the *texts*, not just the images. A genuinely underused
  source of modern astrophysics prose that can be adapted with attribution.
  Note the trap: the main `esa.int` portal is CC BY-SA 3.0 IGO and must be
  avoided. The two look identical from outside.

**Not usable:** Burnham's *Celestial Handbook* (protected to ~2064, and the
trap you walk into by accident since it is exactly the per-object essay we
want — it is Burnham quoting the PD sources above, so go to those directly),
Kunitzsch & Smart, VizieR VII/118, Stellarium descriptions, Corwin's notes,
SEDS English text, Sky & Telescope, anything on Wikipedia.

**On OpenNGC**, since `LICENSES.md` rejects it: it contains no prose
descriptions at all, only positional and photometric columns, so its CC BY-SA
has nothing to do with the lore problem either way. The existing decision not
to bundle it stands on its own terms and this feature does not reopen it.

### 7.3 What a page carries

Design intent, one block, clearly a second voice:

```
  Messier, 1781                                        catalogued 12 Sept
  "Nébuleuse au-dessus de la corne méridionale du Taureau,
   elle ne contient aucune étoile ; c'est une lumière
   blanchâtre, allongée en forme de flamme de bougie."

  A whitish light shaped like a candle flame. He was looking for
  comets, and logged it so he would stop mistaking it for one.
```

Quotation set apart and dated; the site's own sentence underneath doing the
explaining. The gloss is hand-written, so this is tier 1 work — but the
quotation itself is tier 0, and a page can carry the quote alone.

### 7.4 Effort

Transcribing 109 Messier entries is mechanical and bounded — an afternoon,
not a project, and it does not need judgement the way the etymologies do.
This is the highest content-per-hour item in the whole document, and it
should probably ship before the star names.

### 7.5 Working protocol for writing any of this

From `SOURCES-object-lore.md`, and worth restating here because it is the
part that actually gets forgotten under deadline:

1. **Read for facts, close the tab, write from notes.** Never draft with the
   source visible. This single habit does most of the work.
2. **Notes as bullets, not sentences.** `M31 · al-Ṣūfī 964 · "little cloud" ·
   earliest surviving record` — not a written-out sentence that then gets
   lightly edited, which is close paraphrase wearing a hat.
3. **Restructure, don't reword.** Copyright covers sequence and organisation,
   not only words. If the source runs chronologically, run thematically.
4. **Cite primary, not secondary.** Makes the prose independently derived
   *and* better, and it protects against the secondary source being wrong.
5. **Two-source anything that matters.** Errors propagate Allen → Burnham →
   Wikipedia → everyone. A claim appearing only in Allen gets hedged.
6. **Keep sources per object.** Cheap now, priceless if anyone asks. This is
   an argument for a `src` field in the schema (§9) rather than a side file.
7. **Watch for phrase fingerprints.** A turn of phrase that feels *too good*
   probably came from somewhere.

If any of this is drafted with an LLM: **ground it, never ask it to recall.**
Paste the public-domain text into context and instruct "write from this text
only". Regurgitation risk concentrates exactly where this project works —
short, famous, heavily-duplicated passages about well-known objects — so
"write 200 words on the history of M13" from nothing is the one prompt to
never use. Screen each paragraph by searching a quoted 8–12 word n-gram
before publishing; that is trivial to script and catches it reliably. A human
pass on top also catches hallucinated dates, which is a bigger practical risk
here than copyright.

## 7a. Symbols — a fourth strand, and nearly free

`PLANET_SYMBOLS` already exists at `api.py:2246` and the infobox already
renders a "Symbol" row. The font problem is already solved there too: neither
bundled font has them, DejaVu has all nine, so the PNG path picks them up
through the same fallback the deep-sky marks use, and a terminal shows a box
if the reader's font lacks them. **So this strand costs no new plumbing.**

The content, in order of interest:

**They are not planet symbols, they are metal symbols.** ☿ ♀ ♂ ♃ ♄ plus ☉
and ☾ are the alchemical glyphs for quicksilver, copper, iron, tin, lead,
gold and silver. Seven planets, seven metals, one set. That also closes a
loop with §4: Swahili calls Mercury *Zebaki*, from Arabic *zi'baq*,
quicksilver — the metal named the planet rather than the other way round.

**The popular reading is folk etymology.** ♀ as a hand mirror and ♂ as a
shield and spear is the version everyone knows and it is not what the
scholarship says: they are contractions of the Greek god-names, found in
Byzantine papyri. This is precisely what the `unsure` field is for, and it is
a better fact than the myth it replaces.

**Uranus has two symbols, ⛢ and ♅** — Herschel's H-with-a-globe against
Lalande's. An 18th-century argument that never resolved and is now frozen
into Unicode with both codepoints.

**And there is no cross-cultural symbol system to tabulate.** China, Japan,
Korea and Vietnam have no glyph set, because the character *is* the name:
水星 is "water star", so symbol and name are the same object. The Navagraha
have iconography and chart positions rather than compact glyphs. The
tradition is specifically Greco-Egyptian → Latin → alchemical and is not
universal.

That last point makes this a figure 05 case. A "symbols across cultures"
table would invent parallels that do not exist, and the honest figure says so
on its face — which is the same discipline §6 applies to the Pleiades.

## 8. Licensing and accuracy

**Settled: the site's own copy is written fresh here**, same as `facts.py`
and `blurbs.py`. That resolves copyright for everything the site says in its
own voice.

Quotations are a separate mechanism and are fine on their own terms, provided
the source is genuinely public domain and is named with its date. Every
source in §7.2 is pre-1900 and its author long dead.

What neither fixes: **a rephrased wrong etymology is still wrong, and
rephrasing removes the hedge.** Allen 1899 is the trap — public domain,
comprehensive, and unreliable. Kunitzsch & Smart is the modern correction and
is in copyright, so it is a thing to check against rather than draw from.
Where they disagree, Kunitzsch wins and the entry says so if the disagreement
is interesting.

## 9. Data model

New module `names.py`, sibling to `blurbs.py` and `facts.py`, keyed on the
canonical name `objects.resolve_name()` returns.

```
"Betelgeuse": {
    "literal":  "hand of Jawzā",            # teaser line
    "from":     "Arabic",                   # teaser line
    "reading":  "يد الجوزاء  Yad al-Jawzā'", # script + transliteration
    "figure":   "descent",                  # which of the six to draw
    "stages":   [...],                      # rows for the figure
    "root":     "dhanab",                   # joins a cluster, see fig 04
    "also":     [("Chinese", "参宿四", "the fourth of Three Stars")],
    "unsure":   "",                         # names the disagreement, or ""
}
```

Descriptions are a separate table, probably `descriptions.py` or a generated
JSON, keyed the same way, because they have a different shape and a different
provenance:

```
"M1": [{"who": "Messier", "year": 1781, "lang": "fr",
        "text": "Nébuleuse au-dessus de la corne…",
        "gloss": "A whitish light shaped like a candle flame…"}]
```

A list, because an object can carry both Messier and Smyth, and the page
shows them in date order — which is itself the content, since you can watch
the same object get better understood.

`unsure` is a string rather than a bool so the page can say *what* is
contested. `figure` picks the ASCII shape, so the renderer stays a switch
over six known forms rather than free-form layout per entry.

**Lock the schema before writing.** These field names are the contract ~90
entries get written into. Worth doing one star, one DSO and one planet by
hand and rendering all three before fixing it.

## 10. Obligations this project imposes

- A **`/stats` counter ships in the same change** as the route. House rule.
- **Tests in the same turn.** Natural ones: every `names.py` key resolves
  through `objects.resolve_name()` (catches a typo'd key rendering silently
  nothing, which is how `facts.py` would fail); tier 0 produces a line for
  all 1,220; terminal and HTML carry the same rows; every figure fits its
  stated column width.
- **`history` goes into `RESERVED`** at `objects.py:42`, alongside `events`
  and `sphere`, before the route exists. Otherwise a catalogue object could
  in principle claim the path.
- **Sitemap:** tier-1 objects get `/{name}/history`. Tier-0-only objects do
  not — "entry 6543 in Dreyer's catalogue" is exactly the thin generated
  content `sitemap_names()` exists to keep out.
- **UAT on localhost before deploy.** The deploy command is printed, never
  run.
- **`LICENSES.md` gets a row per new source.** Three rows need specific
  wording: Dreyer must say the 1888 archive.org original and explicitly
  **not** VizieR VII/118 (Sky Publishing restriction); Messier must record
  that the English is our own translation of the 1781 French, since no
  public-domain English exists; and the IAU Catalog of Star Names and
  ESA/Hubble texts are CC BY 4.0, which is attribution-only and therefore
  compatible, unlike `esa.int` at CC BY-SA 3.0 IGO.
- **A `src` field per entry**, per §7.5 item 6 — which public-domain file
  each paragraph was written from. Cheap now, priceless if anyone asks.

## 11. Risks

- **Alignment.** §6.1. Demonstrated in the preview rather than asserted.
- **Card rendering.** og.png silently drops CJK/Hebrew/Devanagari. Must fall
  back to transliteration, not emit boxes — `gif.py`'s comment records that
  this exact bug shipped once already and nothing said so.
- **Padding.** 28 asterisms is 18 too many. "The Kite is called the Kite
  because it looks like a kite" in three sentences would be the first filler
  on the site. 10 good ones, the rest fall to tier 0.
- **Scale of writing.** ~90 etymology entries is more than `blurbs.py` and
  `facts.py` combined. The descriptions strand is far cheaper and should not
  be held hostage to it.
- **Voice drift.** Two voices on a page is the point, but only if the
  quotation is unmistakably set apart. If it blends, the site sounds like it
  is writing 18th-century French.

## 12. Phasing

Reordered from the first draft: descriptions moved ahead of star names,
because they are cheaper per page and land on 109 pages at once.

1. **Plumbing.** `/{object}/history` route, `history` into `RESERVED`, the
   four History rows moved off the infobox, tier-0 figure 06 for all 1,220,
   both renderings, stats counter, tests. A working page with no prose
   written — it already carries discovery, first visit and missions for the
   36 objects `facts.py` covers.
2. **Messier's 109.** Transcribe the French, translate it ourselves, quote
   both. Highest content-per-hour on the list, and bounded mechanical work
   rather than judgement. Glosses can follow; the quotations stand alone.
3. **The 9 solar-system bodies**, with figure 03 and the symbols strand
   (§7a). Hardest layout, fewest objects, and the symbols are nearly free
   since `PLANET_SYMBOLS` already exists.
4. **28 DSO common names and 12 showers**, with figures 01 and 06.
5. **~35 stars**, with figures 01/02/04. The big writing block, and the one
   that needs Peters & Knobel for Ptolemy and Schjellerup for al-Ṣūfī.
6. **Smyth 1844** across the double stars and brighter deep sky.
7. **10 asterisms**, figure 05. Stop there.

Phase 1 is worth emphasising: it ships a real page before any writing,
because moving `discovered` / `first_photo` / `first_visit` / `missions` off
the infobox gives 36 objects a populated history page on day one.

## 13. Open questions

1. ~~Is `/{object}/names` the right path?~~ **Resolved: `/{object}/history`,
   see §5.** The object page stays about where to find the thing; everything
   durable and deep moves to its own page.
2. ~~Do the original scripts appear at all?~~ **Resolved: yes, they ship.
   See §6.3** — markup layer on the web, both forms in the terminal, and a
   ~23 KB build-time subset for the card and GIF.
3. Constellations: 88 Latin names with Greek and Babylonian ancestry, and
   `constellation()` already exists — but they are not currently objects with
   pages, so this is a bigger change than it looks.
4. `Milky Way` — Greek "milky circle" → Latin *via lactea* → English, against
   Chinese 銀河 "silver river" and Sanskrit *Ākāśagaṅgā* "the Ganges of the
   sky". Several traditions call it a road or a river. It is already a
   hand-added object with a page, and it is a natural figure 05.
5. Does any of this surface on the homepage, or stay on object pages?
