# Handover: content and copy

Branch `object-history`, worktree `skymap-object-history`. Two commits landed
today (`aace37b`, `e9dd898`); everything after them is uncommitted.

---

## 1. Copy review: 18 of 44 approved, 26 left

The checklist is generated, not hand-kept:

```
cd tools/
python3 build_review.py 8912       # rebuilds tools/copy-review.html
python3 -m http.server 8907        # then open localhost:8907/copy-review.html
```

The `8912` is the port the site is running on, so the "open" links on the
checklist point at a live page.

`DONE` at the top of `build_review.py` is the record of what has been signed
off. Add a name there and rebuild.

### Approved (18)

Aldebaran, Algol, Altair, Andromeda Galaxy, Antares, Arcturus, Betelgeuse,
Big Dipper, Capella, Crab Nebula, Deneb, Double Cluster, Dumbbell Nebula,
Geminids, Hercules Cluster, Jupiter, Lagoon Nebula, Lyrids.

Plus four standing catalogue notes: Messier, Dreyer, Bayer, Yale.

### Left (26)

| | has | notes |
|---|---|---|
| Mars | blurb, story, unsure, figure | weekday branch cut from the figure |
| Mercury | blurb, story | |
| Milky Way | story, figure | no blurb |
| Moon | blurb, story | |
| Neptune | blurb, story, unsure | |
| Orion Nebula | blurb | |
| Orion's Belt | blurb | |
| Perseids | blurb | dash fixed to a colon, unreviewed |
| Pleiades | blurb, story, unsure, figure | |
| Polaris | blurb, story | |
| Procyon | story | no blurb |
| Quadrantids | blurb | |
| Regulus | story | no blurb |
| Rigel | blurb, story, figure | |
| Ring Nebula | blurb | |
| Saturn | blurb, story, unsure, figure | "and Saturday" cut from the figure |
| Sirius | blurb, story | |
| Sombrero Galaxy | blurb | |
| Southern Cross | blurb | |
| Summer Triangle | blurb | |
| Sun | blurb, story | |
| Triangulum Galaxy | blurb | |
| Uranus | blurb, story | |
| Vega | blurb, story, figure | |
| Venus | blurb, story | |
| Whirlpool Galaxy | blurb | |

### The approved shape, for consistency

One merged paragraph in `blurbs.py`, with `from` / `reading` / `literal` left
as rows in `etymology.py` and the `story` field **deleted** — otherwise the
page prints the same words twice.

Apply with the tool, which does all three steps and refuses bad copy:

```
cd tools/
python3 apply_copy.py "Vega" <<'TXT'
<the paragraph>
TXT
```

It normalises curly quotes to straight, refuses em dashes and double hyphens,
strips the etymology story, and adds the name to `DONE`.

**House rules, both now enforced by tests over every hand-written string**
(`test_no_dashes_anywhere_in_the_copy`, `test_quotes_in_the_copy_are_straight`):

- no em dashes, en dashes or `--`
- straight quotes only

**Cross-links.** `[[Name]]` in a paragraph becomes a link in the browser and
plain text in a terminal. 21 paragraphs were linked automatically; the rule
was first mention only, longest name first, never self-linking. Anything
written from here should carry them by hand. `Earth` has no page; `Sun`,
`Moon`, the planets, the named stars, the DSOs and all 57 figures do.

---

## 2. The 57 constellation figures have no copy at all

All 57 were drawn and approved. **53 have no blurb**, so pages like
`/Perseus` render a map, a star list, and nothing else. There is no `about`
tab on any of them either: `about_is_worth_reading` wants written history, a
second designation, or a catalogue note, and an asterism has none of the
three.

This is the largest single gap. Two decisions needed before writing:

1. Does a constellation get a blurb, an etymology entry, or both? The 57
   include real constellations (Perseus, Draco) and named asterisms
   (Big Dipper, Teapot), which want different things.
2. Should `about_is_worth_reading` learn a fourth condition so figures can
   have an about page?

---

## 2b. Parked: zodiac symbols in the left column

Put the sign against the constellation on the twelve zodiac pages, in the
data column on the left where Type, Constellation and Stars already sit.

**The plain glyph, never the emoji.** ♈ to ♓ are U+2648 to U+2653, and
several of them carry emoji presentation by default, so a phone renders a
colour picture where the page wants a monochrome mark. `PLANET_SYMBOLS` in
`api.py` gets away with ♀ and ♂ because those two default to text; the
zodiac dozen do not, and each one needs U+FE0E after it to pin it down.
Nothing in the repo uses U+FE0E yet, so this is the first place that
matters, and the wrong result is invisible on a Mac and obvious on iOS.

The symbols themselves are the easy half: `PLANET_SYMBOLS` in `api.py` does
the same job for the planets, and `object_glyph` already picks a mark by
kind, so this is another row or another glyph rather than a new mechanism.
Ten of the twelve are among the 57 drawn figures (Aquarius, Aries,
Capricornus, Gemini, Libra, Scorpius, Virgo), and Leo, Sagittarius, Cancer,
Taurus and Pisces are filed under an asterism or have no page at all, which
is the same gap the `[[Sickle|Leo]]` link form works around. Worth settling
that first: a sign with no page to put it on is the harder half.

---

## 3. Known content bugs, unfixed

**KEYSTONE lost its label on the horizon chart.** Adding 29 figures crowded
it out. `sky.py:1471` sorts `0 if ast else 1` to let named asterisms beat
constellations for a label slot, but **all 57 entries carry `ast: true`**,
including the original 28, so that tiebreak has never done anything. Fixing
it means deciding which entries are genuinely named asterisms and clearing
the flag on the rest, then checking what else moves on the charts.
`test_sky.py::test_it_still_breaks_for_text` is red because of this.

**Messier's 103 descriptions are parked.** The 1781 catalogue is public
domain and would give every Messier object a period voice. OCR fetched
(54 kB, archive.org) but only 24 of 103 entries extract cleanly; a
sequential scan did worse at 9. Needs a corroboration document before any
of it goes on a page. The design for it is item 08 in
`names-ascii.html` — a bordered quote block with the source and date on the
rule, e.g. `Smyth, 1844 —— the Bedford Catalogue`. **Not built.**

---

## 4. Two pre-existing test failures, not content

- `test_eclipse_routes.py` ×2 — hardcoded `SOLAR = "2026-08-12"`, now past.
- `test_object_routes.py::test_an_ordinary_night_gets_no_sentence` — Venus's
  greatest elongation came into range.

Both predate this branch and fail on `main` too.

---

## Where things live

| | |
|---|---|
| paragraphs | `blurbs.py` |
| name origins, figures | `etymology.py` |
| discovery, missions | `facts.py` (`HISTORY_ORDER`) |
| catalogue notes | `api.py`, `CATALOGUE_NOTES` |
| the copy tool | [tools/apply_copy.py](tools/apply_copy.py) |
| the review page builder | [tools/build_review.py](tools/build_review.py) |
| the review page itself | [tools/copy-review.html](tools/copy-review.html) |
| figure review builder | [tools/build_constellations.py](tools/build_constellations.py) |
| figure review page | [tools/constellations.html](tools/constellations.html) (all 57 approved, so it renders empty) |
| the figure design sketches | [tools/names-ascii.html](tools/names-ascii.html) |
| etymology layout sketches | [tools/etymology-artefacts.html](tools/etymology-artefacts.html) |

### These were in a temp directory and are now in the repo

They lived in
`/private/tmp/claude-501/…/scratchpad/`, which is session-scoped and is
deleted when the session ends. That directory held the only record of which
copy had been approved, so all seven files were copied into `tools/` and the
three scripts were changed to find the repo from `__file__` instead of an
absolute path, so they run from anywhere.

**`DONE` in [tools/build_review.py](tools/build_review.py) is the record of
what has been signed off.** Nothing else stores it. It is worth committing
before anything else.

The quote-block design referenced above is item 08 in
[tools/names-ascii.html](tools/names-ascii.html); the root-cluster figure that
became Jupiter's tree is item 04 in the same file.
