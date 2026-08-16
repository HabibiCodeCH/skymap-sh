# Handover: content and copy

Written on branch `object-history`, merged into `main` on 16 Aug. The
worktree it was written in is gone; everything below refers to the repo.

---

## 1. Copy review: finished

Every hand-written word on the site has been read line by line and signed
off, 15 to 16 Aug.

| | | |
|---|---|---|
| paragraphs | 107 | 10,799 words |
| one-liners | 107 | 1,081 words |
| name origins | 84 | 808 words |

Nothing in `blurbs.py` or `etymology.py` is unreviewed. `DONE` and
`GLOSS_DONE` in [tools/build_review.py](tools/build_review.py) are the
record, and nothing else stores it.

### Still open, small

- **Rigil Kentaurus writes its Arabic the wrong way round.** Everywhere
  else the script comes first and the transliteration follows it. Regulus
  was fixed; this is the last one: "the Arabic Rijl Qanturis رجل قنطورس".
- **The Milky Way note names languages without their scripts**, Chinese
  yinhe and Sanskrit Akashaganga, where every other entry now carries 银河
  and आकाशगंगा equivalents.
- **The one-liners render nowhere.** They are written, reviewed and unused:
  `object_intro` prints the generated descriptor instead. See 2d.
- **Acrux and Arcturus rank by the book, not by `stars.json`.** The copy
  counts a multiple star as one object, as every reference does, so Acrux
  is the brightest of the Southern Cross (combined 0.76) while the star
  list on the same page shows α¹ Cru at 1.33 against Mimosa at 1.25.
  Arcturus is the same case against α¹ Cen. **Do not "fix" the words to
  match the catalogue.**

### What the review kept fixing, in case more copy is ever written

- **A paragraph opens on the name of the page it is on.** Not on a star
  inside it, not on "The V is", not on a pronoun. Job's Coffin opened on
  Delphinus, Lyra on Vega, the Great Square on a corner.
- **Nothing is assumed.** If the copy says Pegasus, Taurus or Bootes, the
  same sentence says what they are, because 31 of the 88 constellations
  have no page here to link to.
- **A source word is written in its own alphabet**, then transliterated,
  then glossed in quotes: `πέρθειν, perthein, "to destroy"`.
- **One fact, one sentence.** The rewrites that failed stacked a name, a
  nickname, a category and a definition behind one colon.
- **A one-liner carries one fact.** No "X, and Y", no jokes, no word the
  reader cannot use.

### The tools

```
cd tools/
python3 apply_copy.py "Vega" <<'TXT'      # one paragraph, approved
<the paragraph>
TXT
python3 set_glosses.py new.json           # {"Name": "the one-liner"}
python3 build_review.py 8912              # rebuild the checklist
python3.11 -m http.server 8914 --bind 127.0.0.1
```

`8912` is the port the site is running on, so the checklist's "open" links
point at live pages; the checklist itself is read at 127.0.0.1:8914.

`apply_copy.py` normalises curly quotes, refuses em dashes and double
hyphens, deletes the etymology `story` (whose words the paragraph has
absorbed, so leaving it prints them twice), keeps `unsure`, and ticks the
name off. `set_glosses.py` touches only the one-line gloss and is
deliberately narrower than `rewrite_blurbs.py`, which replaces whole
entries and would take the section comments with it.

**House rules, enforced by tests over every hand-written string**
(`test_no_dashes_anywhere_in_the_copy`, `test_quotes_in_the_copy_are_straight`):
no em dashes, no en dashes, no `--`, straight quotes only.

**Cross-links.** `[[Name]]` becomes a link in the browser and plain text in
a terminal; `[[Page|words]]` links a page under different words, page
first. First mention only, longest name first, never self-linking. `Earth`
has no page; the Sun, Moon, planets, named stars, deep-sky objects and all
57 figures do. [tools/audit_links.py](tools/audit_links.py) reports every
name that has a page and is not linked where it is mentioned, which is how
16 links silently dropped in a rewrite were found.

---

## 2. The 57 constellation figures: done

Was the largest gap in the site: 53 of the 57 drawn figures had no words at
all, so `/Perseus` rendered a map, a star list and nothing else. All 57 now
carry a blurb and a name-origin entry, and 12 first-magnitude stars that
had been missed got one too (Canopus, Rigil Kentaurus, Procyon, Achernar,
Hadar, Spica, Pollux, Fomalhaut, Mimosa, Acrux, Regulus, Adhara).

Both open questions were answered by doing it: a figure gets **both** a
blurb and an etymology entry, and `about_is_worth_reading` grew a fourth
condition, so a name origin alone now earns the about tab.

---

## 2b. Zodiac symbols in the left column: raised and dropped, 15 Aug

The idea was to put the sign against the constellation on the twelve zodiac
pages, in the data column on the left where Type, Constellation and Stars
already sit, the way the planets carry theirs.

**Dropped on the glyphs, not on the idea.** U+2648 to U+2653 carry emoji
presentation by default and rendered as colour emoji in the terminal the
moment they were pasted into one. `PLANET_SYMBOLS` in `api.py` gets away
with ♀ and ♂ because those two default to text; the zodiac dozen do not.
U+FE0E after each one is supposed to pin it to the text glyph, nothing in
the repo uses U+FE0E yet, and it is honoured unevenly enough that the wrong
result is invisible in one place and obvious in the next. A row of cartoons
in a monospace column is worse than no row at all.

Anyone reviving this should settle the glyph question first, on a real
terminal and a real phone, before touching the pages. The rest is easy:
`object_glyph` already picks a mark by kind, so it is another row rather
than a new mechanism. The second obstacle is that only seven of the twelve
signs have a page here (Aquarius, Aries, Capricornus, Gemini, Libra,
Scorpius, Virgo). Leo is filed under the Sickle, Sagittarius under the
Teapot, and Cancer, Taurus and Pisces have no page at all.

---

## 2c. Parked: Proxima Centauri has no page

The Centaurus paragraph names Proxima and cannot link it, because it is not
in `stars.json`. That file stops at magnitude 5.5 and Proxima is 11.1, some
250 times fainter, and it was never in the source either: `bsc5.dat` is the
Yale Bright Star Catalogue, which stops around 6.5, and the string
"Proxima" does not appear in it anywhere.

Worth fixing anyway, because Proxima is famous in a way nothing else at
magnitude 11 is: the nearest star to the Sun, with a planet in the
habitable zone, and the obvious thing to look up after reading about
Alpha Centauri. There is precedent in `LICENSES.md`, which records the
Pleiades being hand-added to the deep-sky file for the same reason.

Check before doing it: at magnitude 11 it can never be drawn, since the
chart's limit tops out near 6.5 in full darkness, so it should be invisible
everywhere but its own page. It would land in the catalogue star count,
which is a number the site quotes. Leave `stars_motion.json` alone, since
that only covers stars the asterism lines use.

---

## 2d. Parked: publish the one-liners as an index, not the review page

**The review page itself, no.** It would be the largest duplicate-content
page on the site, reproducing all 107 paragraphs on one URL and competing
with the 107 pages they belong to. `blurbs.py` opens by explaining that this
copy exists to give each object page a stable half a crawler can identify,
and `sitemap_names()` already withholds thin pages for exactly this reason.
It also shows working state and is built as a tool: the links point at
127.0.0.1 and the ticks live in browser storage.

**The one-liners are a different matter.** They are a real index: every
object, one line saying what it is, linking to its page. No duplication,
because a gloss appears nowhere else on the site. 107 genuine internal
links to pages currently reachable only through a chart. And it would give
the glosses somewhere to live, which matters because they are written,
reviewed and rendered nowhere at all: `object_intro` uses the generated
descriptor instead, and carries a comment saying blurbs.py is parked "if
the one-line gloss earns a place later".

`/catalog` is the nearest thing that exists and does a different job. It
lists objects by category with a designation and a magnitude, so it answers
"what is here" and not "what is it":

    /catalog       ◆ Saturn
    one-liners     Saturn is the planet with the rings

Worth deciding alongside 2c and 2e, since all three are about which pages
exist rather than what they say.

---

## 2e. Parked: draw Pegasus as well as the Great Square

The square is the body of the horse, but there is no Pegasus page, so the
paragraph has to introduce the horse from nothing and cannot link it. Same
for Bootes, Leo, Cygnus, Hercules and Sagittarius, which are filed under
the Kite, Sickle, Northern Cross, Keystone and Teapot.

**The precedent already exists.** Orion and Orion's Belt are both drawn,
and the Belt's three stars are the same segment drawn twice inside Orion's
own lines, so a constellation and an asterism inside it can coexist in
`asterisms.json` without anything special.

Pegasus needs the four square corners plus the neck and head, which is
where the horse becomes recognisable: Enif (ε Peg, HR 8308, mag 2.39) is
the nose and is brighter than two of the square's own corners, Algenib
(2.83) and Markab (2.49). Then a blurb, an etymology row, and the
`[[Great Square|Pegasus]]` alias stops being needed.

Two things to settle first:

**`build_asterisms.py` is no longer the source of the figures.** Its `A`
list still holds the original 28. The 29 added in `aace37b` on 14 Aug went
straight into `asterisms.json`, which is minified, so the file that reads
like the source is a commit behind. Either put the missing 29 back into the
builder or declare the JSON the source and say so in the docstring.

**Label crowding, which is section 3.** A Pegasus label lands on the same
stars as the Great Square's.

---

## 3. Known bugs, unfixed

**KEYSTONE lost its label on the horizon chart.** Adding 29 figures crowded
it out. `sky.py:1471` sorts `0 if ast else 1` to let named asterisms beat
constellations for a label slot, but **all 57 entries carry `ast: true`**,
including the original 28, so that tiebreak has never done anything. Fixing
it means deciding which entries are genuinely named asterisms and clearing
the flag on the rest, then checking what else moves on the charts.
`test_sky.py::test_it_still_breaks_for_text` is red because of this, and it
is the only red test that is a real defect.

**Messier's 103 descriptions are parked.** The 1781 catalogue is public
domain and would give every Messier object a period voice. OCR fetched
(54 kB, archive.org) but only 24 of 103 entries extract cleanly; a
sequential scan did worse at 9. Needs a corroboration document before any
of it goes on a page. The design for it is item 08 in `names-ascii.html`, a
bordered quote block with the source and date on the rule. **Not built.**

---

## 4. Test suite: 1,972 pass, 2 fail

- `test_sky.py::test_it_still_breaks_for_text` is the Keystone label bug
  above. Real.
- `test_sky.py::IssDarknessCheck::test_no_daylight_passes_reported` fails
  only when there is no TLE file on disk, which switches the ISS off at
  startup. Run `python tle.py` and it passes.

Three others were fixed on 16 Aug rather than tolerated: all three froze a
moving number into a string literal. Saturn's infobox asserted `8.78 AU`
and Saturn had moved; the eclipse catalogue asserted a date that has since
happened. Both now assert against the same source the page renders from.
**Do not write a date or an ephemeris value into a test.**

---

## Where things live

| | |
|---|---|
| paragraphs and one-liners | `blurbs.py` |
| name origins, figures | `etymology.py` |
| discovery, missions | `facts.py` (`HISTORY_ORDER`) |
| catalogue notes | `api.py`, `CATALOGUE_NOTES` |
| apply one approved paragraph | [tools/apply_copy.py](tools/apply_copy.py) |
| replace one-liners | [tools/set_glosses.py](tools/set_glosses.py) |
| replace whole entries | [tools/rewrite_blurbs.py](tools/rewrite_blurbs.py) |
| find unlinked names | [tools/audit_links.py](tools/audit_links.py) |
| try deep-sky art in colour | [tools/art_options.py](tools/art_options.py) |
| the review page builder | [tools/build_review.py](tools/build_review.py) |
| the review page itself | [tools/copy-review.html](tools/copy-review.html) |
| figure review builder | [tools/build_constellations.py](tools/build_constellations.py) |
| figure review page | [tools/constellations.html](tools/constellations.html) (all 57 approved, so it renders empty) |
| the figure design sketches | [tools/names-ascii.html](tools/names-ascii.html) |
| etymology layout sketches | [tools/etymology-artefacts.html](tools/etymology-artefacts.html) |

The quote-block design referenced in section 3 is item 08 in
[tools/names-ascii.html](tools/names-ascii.html); the root-cluster figure
that became Jupiter's tree is item 04 in the same file.
