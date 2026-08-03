# Spec: command bar as the search input

Replace the wordmark, the `$ curl skymap.sh/…` chip and the place input with a single
element: an inline-editable command line where everything up to and including the `/` is
fixed text and the rest is a text field.

Reference implementation: `skymap-command-bar.html` (working mock, self-contained).

---

## 1. DOM

```html
<form class="cmdbar" id="bar" method="get" action="/">
  <span class="prompt" aria-hidden="true">$</span>
  <span class="fixed" aria-hidden="true"><span class="curlword">curl </span>skymap.sh/</span>

  <span class="field">
    <input id="q" name="q" value="Geneva"
           aria-label="City, or lat,lon"
           spellcheck="false" autocapitalize="off" autocorrect="off"
           autocomplete="off" enterkeyhint="go">
    <span class="ghosttext" id="ghost" aria-hidden="true"></span>
    <span class="measure"  id="measure" aria-hidden="true"></span>
  </span>

  <span class="cursor" id="cur" aria-hidden="true"></span>
  <span class="grow"></span>
  <button type="button" class="copy" id="copy">⧉ copy</button>
</form>
```

Notes that matter:

- **It must be a real `<form>` with a real `action`.** With JS disabled or not yet loaded,
  pressing Enter must still navigate somewhere sensible. A curl-shaped product that requires
  JavaScript to accept a place name is an embarrassment. Server-side: accept `?q=<place>` on
  `/` and 302 to `/<place>`.
- **`.ghosttext` is a sibling, not an overlay.** Absolutely-positioned overlay text drifts
  out of alignment across fonts, zoom levels and subpixel rounding. As an inline sibling it
  is laid out by the same text engine as the input's own text and cannot desync.
- **`.measure` is the auto-size mechanism** (§3). It must inherit the exact same computed
  font as the input — same family, size, weight, letter-spacing, font-feature-settings.
- Everything decorative — `$`, the fixed path, the ghost, the cursor — is `aria-hidden`.
  The screen-reader experience is one labelled text input.

---

## 2. The cursor

```css
.cursor {
  display: inline-block;
  width: .55em; height: 1.15em;
  margin-left: 1px;
  background: var(--green-hi);
  vertical-align: -0.2em;
  animation: blink 1.06s step-end infinite;
}
.cmdbar.focused .cursor { visibility: hidden; animation: none; }

@keyframes blink { 0%, 50% { opacity: 1 } 50.01%, 100% { opacity: 0 } }

@media (prefers-reduced-motion: reduce) {
  .cursor { animation: none; opacity: .55; }
}
```

Requirements, in order of how much they matter:

1. **`step-end` timing function.** Not `ease`, not `linear`. A fade reads unmistakably as a
   CSS animation; a hard on/off reads as a terminal. This single property does most of the
   work of the effect.
2. **Block glyph, not a bar.** `.55em × 1.15em` filled rectangle. Terminals default to a
   block; a thin `|` is what an HTML text field renders and undoes the illusion.
3. **Hidden while focused.** The fake cursor exists only to advertise editability *before*
   first click. Once the field has focus the real caret is visible and two cursors on one
   line is confusing. Toggle via a `.focused` class on the container, set on `focus`/`blur`.
4. **Animate `opacity`, toggle `visibility` — never `display`.** `display` removes the box
   from flow, so surrounding text jitters horizontally once per second.
5. **Period ~1.06s, 50% duty cycle.** Matches the common terminal default closely enough.
6. **`prefers-reduced-motion: reduce` must stop the blink**, leaving a static dimmed cursor.
   Non-negotiable; blinking is a real accessibility concern.

---

## 3. Auto-sizing the input

`field-sizing: content` is not portable yet. Use the hidden-measure technique:

```js
function size() {
  measure.textContent = q.value || '';
  q.style.width = (measure.offsetWidth + 2) + 'px';
}
```

- `.measure` is `position:absolute; visibility:hidden; white-space:pre; left:-9999px`.
- `white-space: pre` is required — otherwise trailing spaces collapse and the width is short.
- The `+2` absorbs subpixel rounding; without it the last glyph can clip.
- Call on `input`, and once on load, and after programmatic value changes.
- Cap with `max-width: 100%` on the input and `min-width: 0` on the flex parent, or a long
  value will overflow the bar instead of scrolling inside it.

---

## 4. Ghost completion

```js
function complete() {
  const v = q.value;
  if (!v) { ghost.textContent = ''; return; }
  const hit = matches.find(c => c.toLowerCase().startsWith(v.toLowerCase())
                             && c.length > v.length);
  ghost.textContent = hit ? hit.slice(v.length) : '';
}
```

- **Prefix match only, case-insensitive, first hit wins.** Rank candidates by population
  descending so `new` → `New York`, not `Newcastle upon Tyne`.
- **Preserve the user's own casing.** Render `zur` + ghost `ich`, never replace what they
  typed with `Zurich`. The completion is a suggestion, not a correction.
- **Accept with `Tab` or `ArrowRight`.** `ArrowRight` only when the caret is already at
  the end (`q.selectionStart === q.value.length`), otherwise it must move the caret
  normally. Both call `preventDefault()` on accept. `Tab` should be intercepted
  unconditionally while a completion is showing, and fall through to normal tab-out
  when it is not.
- **Clear the ghost on `Backspace`** before recomputing, so deleting never appears to
  re-suggest what was just removed.
- The ghost must be excluded from `.measure` — it is a separate element and is not part
  of the input's width.

### Data source — this is the part with a real constraint

`cities.json` is ~3.9 MB. **It must not be shipped to the browser.** Two options:

**(a) Server endpoint — preferred.**
`GET /complete?q=<prefix>` → JSON array of up to ~8 canonical names, ranked by population.
Prefix-only, case-folded, ASCII-folded (so `zur` matches `Zürich`). Constraints:
- Debounce client-side at ~120 ms; abort the in-flight request on each new keystroke.
- Cache-key surface is bounded: lowercase the prefix, cap length at ~24 chars, `s-maxage`
  it aggressively — completions are static data and should never reach origin twice.
- Reject or truncate prefixes over the cap rather than scanning.
- This endpoint is a new cache-key surface. Given the free-plan Cloudflare constraint, make
  sure it cannot be used to generate unbounded misses.

**(b) Small embedded list — acceptable fallback.**
Ship the top ~1,000 cities by population inline in the page (a few tens of KB), complete
locally, no network. Covers the overwhelming majority of real queries. Ship this first if
the endpoint is not ready; it is strictly less work and has no cache implications.

---

## 5. Click-to-focus

```js
bar.addEventListener('mousedown', e => {
  if (e.target === copyBtn || copyBtn.contains(e.target)) return;
  if (e.target !== q) {
    e.preventDefault();
    q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  }
});
```

- Clicking anywhere in the bar — the `$`, the fixed path, the ghost, the empty space —
  focuses the input with the caret at the **end**.
- `preventDefault()` on `mousedown` (not `click`) is what stops the browser from placing
  the caret wherever the pointer landed or starting a text selection on the fixed span.
- The copy button must be excluded, or it can never be clicked.
- `cursor: text` on the container so the whole bar advertises as editable.

---

## 6. Copy button

```js
const place = q.value + ghost.textContent;
const path  = place.includes(' ') ? "'skymap.sh/" + place + "'" : 'skymap.sh/' + place;
navigator.clipboard.writeText('curl ' + path);
```

- Copies the **resolved** command including any accepted completion.
- **Quotes the URL when it contains a space**, matching the real shell requirement and what
  `README.md` already documents (`curl 'skymap.sh/San Francisco, US'`).
- Feedback: swap label to `✓ copied` for ~1.4 s, then restore. No toast.
- `navigator.clipboard` is HTTPS/localhost-only — feature-detect and hide the button
  where unavailable rather than failing silently.
- This button is load-bearing. It replaces the affordance the old static chip had, and
  the copy-into-a-terminal path is how the product spreads.

---

## 7. Submit and URL encoding

- `Enter` submits. Navigate to `/` + the place, encoded.
- Spaces: the server already accepts both. Pick one and normalise consistently.
- **After the response resolves, rewrite the field to the canonical resolved name** returned
  by the server — so someone who typed `geneva` sees `Geneva` and someone who typed a bare
  `46.1958,6.1568` sees the snapped `46.20,6.20`. The field then always displays a path that
  is literally valid, which is the entire point of the design.
- Keep the raw coordinates in the meta line under the chart; the field shows the human name.

---

## 8. Responsive

```css
@media (max-width: 620px) {
  .fixed .curlword { display: none; }   /* "curl " goes, "skymap.sh/" stays */
  .icons { display: none; }             /* socials into the ? panel */
}
```

`skymap.sh/` alone still teaches the URL scheme and leaves room for a long city name plus
an on-screen keyboard. Verify at 390 px with `Buenos Aires` in the field.

`enterkeyhint="go"` puts a Go key on the mobile keyboard.
`autocapitalize="off"` and `autocorrect="off"` are mandatory — iOS otherwise rewrites a
meaningful fraction of the 40,803 city names.

---

## 9. Drawer anchoring (the other fix)

The `?` button and the `more` link currently both toggle one panel that renders at the
bottom of the page — so `?` at the top appears to do nothing, because what it opened is
below a ~600 px chart.

Anchor the panel **directly beneath the command bar**, above the chart. Both triggers open
the same panel in the same place. Opening it pushes the chart down, which is correct for a
deliberate action.

Panel contents, in order: find · date & time · view (animate, deep sky, quadrants, zoom,
lines) · share (PNG, GIF) · example places · keyboard shortcuts · about links
(catalog, demo, help, legend).

That removes the nav row, the examples row, the second control row and the pinned keyboard
bar from the default view — 26 interactive elements down to about 8.

---

## 10. Other changes in the same pass

- **Never render a disabled control.** "show quadrants" currently ships greyed out on the
  day view with tooltip "Only available on the night chart". Omit it entirely when
  unavailable.
- **Share appears once.** Remove the `Share as a PNG: <url>` line under the chart; it
  duplicates the drawer entry and the `g` shortcut.
- **Promote the tonight line.** `Waiting for you tonight: …` / `See tonight's chart now:`
  currently sits in small grey text at the bottom of the day view. It is the day view's
  only conversion path. Give it a bordered block directly under the summary with a real
  link — and on the web surface make it a link, not a `curl` string (keep the `curl` form
  for the terminal response).
- **Bug, unrelated to layout:** a state exists where the horizon panorama renders with
  `0 stars above the horizon` — an empty grid — instead of falling through to the Sun's-path
  view. The fall-through works at `/46.1958,6.1568?w=170&panel=1`; it did not in an earlier
  capture at 06:18. Find the trigger and make the rule unconditional: if the chart would be
  empty, never draw the empty chart.

---

## 11. Acceptance criteria

- Command bar is the only place-input on the page; wordmark and old search field are gone.
- Cursor blinks with hard on/off while unfocused, disappears on focus, is static under
  `prefers-reduced-motion`, and causes no horizontal layout shift.
- Typing `zur` shows `zur` + dim `ich`; `Tab` and `ArrowRight`-at-end accept it.
- Bar auto-sizes to content and does not overflow at any viewport ≥ 320 px.
- Clicking any part of the bar focuses the input with the caret at the end.
- Copy produces `curl skymap.sh/Geneva`, and `curl 'skymap.sh/New York'` when a space
  is present.
- `Enter` navigates correctly **with JavaScript disabled**.
- No more than ~8 interactive elements visible in the default state.
- `?` and `more` open the same panel, directly under the bar, visible without scrolling.
- `cities.json` is not shipped to the client.
- No new unbounded cache-key surface.
