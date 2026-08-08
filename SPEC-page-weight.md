# Spec: stop paying for the shared shell on every page view

Every HTML page inlines the same CSS and JS. None of that HTML is cached anywhere, so the
shell is re-sent on every single page view. The seven unpushed commits add **+31,010 raw
bytes to it, flat**, whether a page uses the new code or not.

Goal: the shared shell becomes a separately-cached asset, and the pages that don't use the
chart machinery stop carrying it.

Measured 2026-08-08. Prod = `origin/main` over Cloudflare, "new" = the seven unpushed
commits on localhost:8811. Raw byte counts are exact; compressed figures are local gzip,
within a few percent of the brotli Caddy actually serves.

---

## 0. The numbers this exists to fix

Shared shell, identical on every non-sphere page:

| | prod | unpushed | delta |
|---|---|---|---|
| CSS | 21,747 | 37,268 | **+15,521** |
| JS | 41,960 | 57,442 | **+15,482** |
| SVG | 3,050 | 3,050 | 0 |
| **total (raw)** | **66,757** | **97,760** | **+31,010** |

It is genuinely flat, not content-driven: `/help` and `/legend` grew by precisely 31,010
bytes each, and their CSS/JS blobs are byte-identical to one another in both builds.

| page | raw prod | raw new | ~gz prod | ~gz new |
|---|---|---|---|---|
| `/Geneva` | 568,326 | 670,250 | 35 KB | 47 KB |
| `/Geneva/Venus` | 214,673 | 280,197 | 33 KB | 44 KB |
| `/Geneva/eclipse/2026-08-12` | 172,350 | 203,368 | 39 KB | 49 KB |
| `/catalog` | 158,702 | 174,037 | 35 KB | 45 KB |
| `/help` | 75,473 | 106,483 | 26 KB | 36 KB |
| `/legend` | 74,414 | 105,424 | 26 KB | 36 KB |
| `/Geneva/sphere` | 92,650 | 92,651 | 31 KB | 31 KB |

`/help` ships 97,760 bytes of shell to deliver 8,723 bytes of help text. The sphere page is
the only one that escapes, because `SPHERE_PAGE` is a separate template.

**Server rendering is not the problem and is not in scope.** Local render times are 1.2 ms
(sphere), 2.7 ms (catalog), 7.9 ms (object), 29.5 ms (eclipse), 45 ms (chart). Prod TTFB of
65–230 ms is nearly all network.

---

## 1. Why external assets fix this on the current Cloudflare plan

No Cache Rules and no paid plan required. Verified on live assets — first request to a cold
edge is `MISS`, second is `HIT`:

```
/vendor/three/three.module.js    cf=HIT  age=15
/vendor/three/CSS2DRenderer.js   cf=HIT  age=15
/milkyway.json                   cf=HIT  age=15
```

Cloudflare caches these purely from the `public, max-age=31536000, immutable` header the
origin already sends. `/favicon.ico` and `/apple-touch-icon.png` were sitting at
`age=23528` when measured.

HTML, by contrast, comes back `cf-cache-status: DYNAMIC` on every page including `/catalog`
and `/help`, which declare `public, max-age=3600`. Cloudflare does not cache HTML by
default on any plan, and the chart pages send `private` on top of that (deliberately — see
`02c11db`, which stopped a shared cache handing one visitor's page to another).

So: **edge-caching the HTML is off the table and stays off the table.** The shell moves out
to `.css`/`.js` URLs, which the edge already caches for free.

---

## 2. Scope

In:

1. Inventory of what actually composes the shell (§3).
2. Split `PAGE` into a base shell and a chart shell (§4).
3. Hashed static asset routes for both (§5).
4. Critical CSS stays inline; the rest goes external (§6).
5. Collapse the sphere's four-hop waterfall with preload hints (§7).
6. Fold `/gif-capacity` into the rendered HTML (§8).

Out:

- Trimming `three.module.js` to the slice the sphere uses. Real prize (256 KB gzip, 81% of
  the sphere's first visit) but a much larger job with its own risks. Separate spec.
- Any change to what the pages *look like*. This is byte-shuffling only. If a page renders
  differently afterwards, that is a bug in this work.
- Server-side render cost. Already fast enough.
- Anything touching the stats counters' correctness. Four known bugs there are tracked
  separately and must not be folded into this.

---

## 3. Work item: inventory first

Do not start moving code until this is written down. The rendered shell (37,268 CSS +
57,442 JS) is larger than the constants it obviously comes from, so something is generating
the difference and it needs naming before it can be moved.

Known large literals in `api.py`:

| chars | line | kind | name |
|---|---|---|---|
| 93,331 | 10108 | mixed | `SPHERE_PAGE` (separate template, mostly out of scope) |
| 28,421 | 8136 | mixed | `PAGE` — one `<style>` of 26,192, one `<script>` of 855 |
| 12,956 | 9671 | JS | `CMDBAR_JS` |
| 11,120 | 2979 | CSS | `OBJECT_CSS` |
| 7,210 | 9556 | CSS | `CMDBAR_CSS` |

Assembled at import time by `PAGE.replace(...)` at api.py:9543–9983 for `/*LADDER*/`
(`chart_ladder_css`), `/*CMDBAR_CSS*/`, `/*CMDBAR_JS*/`, plus scalar substitutions
(`{BOX_GAP}`, `{DECK_TURN_MS}`, `{ANIM_WIDE_MS}`, `{BOTTOM_PAD}`).

**Deliverable:** a table of every fragment that reaches a rendered page, its size, and which
page types actually execute it. That table decides the §4 split; guessing it does not.

---

## 4. Work item: split `PAGE` into base and chart shells

Two thirds of the +31,010 is chart machinery — the new constants in the unpushed branch are
`DAY_PANEL_ARTS`, `DAY_PANEL_DAYS`, `DAY_PANEL_HEIGHT_FRAC`, `DAY_PANEL_SLIDES`,
`DAY_PLANET_SCALE`, `SUPER_DAY_MIN`, `DECK_TURN_MS`, `FULL_DARK_MAG`, `KBD_BAR_H`,
`SUMMARY_W`, `_LEAD_SPACE`. `/help`, `/legend` and `/catalog` never execute any of it.

Split into:

- **base** — the command bar, the header, the page chrome, the shared reset. Everything
  every page genuinely uses.
- **chart** — the ladder CSS, the day panel, the deck/animation code, the GIF button, the
  keyboard shortcut layer.

Pages taking base only: `/help`, `/legend`, `/catalog`, `/demo`, `/stats`.
Pages taking base + chart: `/{place}`, `/{place}/{obj}`, the eclipse pages, `/`.

**Acceptance:** `/help` and `/legend` compressed size is at or below their current *prod*
figure (~26 KB), not merely below the unpushed figure. If the split lands and they are still
36 KB, it did not work.

---

## 5. Work item: hashed asset routes

Follow the pattern already in the tree at server.py:2428, which serves
`/vendor/three/three.module.js` with `public, max-age=31536000, immutable`.

- Compute a short content hash of each bundle at import time.
- Serve `/app.<hash>.css`, `/app.<hash>.js`, `/chart.<hash>.css`, `/chart.<hash>.js` with
  those same headers.
- `PAGE` references the hashed URLs. The hash changing on edit is what makes `immutable`
  safe.

**Notes that matter:**

- **A deploy can strand a browser mid-visit, and the route must be built to survive it.**
  The hash lives inside the HTML, and that HTML sits in a browser cache for up to 225 s
  (`max-age=225`). So:

  ```
  12:00:00  browser loads /Geneva, stores HTML referencing /app.a3f9c1.css
  12:01:00  deploy lands; the new process only knows /app.b7e204.css
  12:02:00  browser, still inside its 225 s, requests /app.a3f9c1.css
            -> 404 -> the page renders with no CSS at all
  ```

  An unstyled page here is not "a bit ugly". The whole layout is ASCII art holding its shape
  in a monospace grid, so losing the stylesheet collapses it into scrambled text. The window
  is short but it lands squarely on whoever was using the site at deploy time, and deploys
  are frequent.

  **Decision: the hash is write-only. Match `/app.{hash}.css` as a path parameter and ignore
  the captured value — always serve the current bundle.** The hash exists solely to change
  the URL when the content changes, which is what makes `immutable` safe on the way out. It
  is not an identifier to look anything up by.

  Rejected alternative: retaining the previous build's bundles for one deploy cycle. More
  literally correct, but it means storing old bundles somewhere and deciding when to bin
  them, in exchange for preventing a mismatch that is only ever one version of your own CSS
  wide. Not worth the bookkeeping.

  Consequence to accept knowingly: a browser can receive CSS one deploy newer than the HTML
  it is styling. Across a single deploy of your own stylesheet that is nearly always
  invisible, and it is strictly better than no stylesheet. If a deploy ever makes a genuinely
  breaking CSS change, the 225 s exposure is the same one the inline version already has
  today.
- **Every new route needs a `/stats` counter in the same change.** Project rule, no
  exceptions. Four counters, and they belong in `_stat` under a `page:` or `asset:` prefix
  so they persist — note `_eclipse_keys` is the standing example of what happens when a
  counter is added outside the persisted set.
- Caddy already does `encode zstd gzip`, so the bundles compress on the way out with no
  extra work. Confirm the served `content-encoding` is not lost on the new routes.

---

## 6. Work item: keep first paint intact

Right now nothing blocks first paint, because the CSS is inline. Moving it out adds a
render-blocking request on a cold visit.

- Keep the chart's core monospace layout rules inline (enough that an unstyled flash is not
  visible), externalise the rest.
- Add `<link rel="preload" as="style">` so the fetch starts with the HTML rather than after
  it parses.

**Acceptance:** measured on localhost with a cold cache and throttling, first paint is no
later than today's. A flash of unstyled text is a blocker, not a nit — this is a site whose
entire visual identity is fixed-width text alignment.

---

## 7. Work item: sphere waterfall

Unchanged by the unpushed branch (+1 byte) but now four serial hops, not the three recorded
last time — `/milkyway.json` is new.

| asset | raw | gzip |
|---|---|---|
| `/Geneva/sphere` | 92,651 | 31,448 |
| `three.module.js` | 1,272,972 | **256,366** |
| `CSS2DRenderer.js` | 4,407 | 1,439 |
| `/Geneva/sphere.json` | 95,706 | 20,219 |
| `/milkyway.json` | 260,346 | 5,515 |
| **total** | **1,726,082** | **314,987** |

HTML → three.js → (`sphere.json`, `milkyway.json`), all serial, no preload of any kind.

Scope here is only the hints: `modulepreload` for three.js and `preload` for the two JSON
payloads, so all four start together instead of in sequence. That is a handful of lines and
turns four round trips into roughly two.

This is the page every phone gets — see the standing invariant that mobile always gets the
sphere — so it is the one where the round trips cost the most.

---

## 8. Work item: fold in `/gif-capacity`

One extra round trip per chart page load to fetch an 18-byte JSON body. The server already
knows the answer at render time. Inline the value into the HTML and delete the fetch.

The comment at api.py:9060 shows this was already cut down once, from polling every 4 s to
a single check. This is the last step of that same cleanup.

---

## 9. Tests

Written in the same commits as the changes, not after.

- Byte-size guards: assert the base shell stays under a stated ceiling, so the next feature
  that widens it fails a test rather than being noticed a month later on a Cloudflare graph.
  This is the single most valuable test here — it is what makes the fix hold.
- Every page type still renders identically. Compare rendered DOM before and after,
  ignoring the swapped `<style>`/`<script>` blocks.
- The hashed routes return the right `Cache-Control` and the right content type.
- **A stale or nonsense hash still returns 200 with the current bundle**, per the §5
  decision. Test the real case (`/app.deadbeef.css`) and the degenerate one, and assert the
  body matches what the live `PAGE` references. This is the test that stops a future
  refactor quietly reintroducing a lookup by hash.
- The hash actually changes when the bundle content changes. Without this, `immutable` goes
  from safe to a year-long stale-cache bug.
- `/help` and `/legend` do not reference the chart bundle at all.
- The four new `/stats` counters increment.

---

## 10. Rollout

1. Land the seven unpushed commits first. This work rebases on top of them; doing it the
   other way round means resolving the same conflict twice.
2. Run it on localhost and look at every page type by eye before anything is pushed —
   particularly first paint on a cold cache, per §6.
3. Deploy, then confirm on prod: `cf-cache-status` on the new asset URLs should be `MISS`
   then `HIT`, and the per-page compressed sizes should match the §4 acceptance figures.
4. Watch `/stats` for the new counters. Under the §5 decision an asset 404 should be
   impossible, so **any** 404 on `/app.*` or `/chart.*` means the route pattern is wrong and
   is worth treating as a rollback signal rather than a curiosity. Deploy once, then reload
   a page that was open beforehand — that is the exact case §5 exists for, and it takes ten
   seconds to check by hand.

---

## 11. Expected outcome

- Repeat page views drop by roughly 36 KB compressed, served from the edge rather than the
  origin.
- `/help`, `/legend` and `/catalog` stop growing when chart features are added.
- The sphere's first visit loses two round trips.
- Chart pages lose one round trip.
- Nothing looks different.
