"""The eclipse page: what this eclipse does where you are standing.

Laid out like the object pages, and for the same reason their comments give.
The left column is the same for every reader on every day -- what the
eclipse is, when it happens, which eclipses come after it -- and is what a
search engine can index and what somebody arriving from a shared link needs
before a percentage means anything. The right column is computed from the
reader's own coordinates.

Each eclipse in the left column is a real link to its own URL rather than a
tab swapped in by script. They are pages: shareable, indexable, and they
work with the network off halfway through.

The honesty rule this page exists under, in one line: it prints a number
only where besselian.ELEMENTS has the coefficients to compute one. For every
other eclipse in the table it says what the table says -- a date, a type,
and the regions NASA lists -- and does not pretend to local circumstances it
cannot work out. Those two states have to look different on the page, or the
precise ones are worth nothing.
"""
import datetime as dt
import html

import besselian
import eclipse as eclipse_map
import events
import sky

# How many future eclipses the left column lists. Enough to show this is a
# table with a future in it, few enough that the column stays a sidebar.
LIST_COUNT = 8

SAFETY = (
    "Never look at a partial eclipse without a proper solar filter. "
    "Sunglasses, exposed film and smoked glass are not filters, and the "
    "damage is painless while it happens. Only during totality, and only "
    "inside the path, is it safe to look with the naked eye."
)

# Said on every page, not only the partial ones. Somebody reading Oviedo's
# page is standing in the path for about a hundred seconds and outside it
# for the two hours either side.
SAFETY_TOTALITY = (
    "Totality itself is safe to watch unaided, and it is the only part that "
    "is. The filter goes back on the moment the Sun's edge returns."
)


def _entries():
    """Eclipses from the table, oldest first, the comment row dropped."""
    return sorted(events._eclipses(), key=lambda e: e["when_utc"])


def key_of(entry):
    """The date string besselian.ELEMENTS and eclipsemap.json are keyed by."""
    return entry["when_utc"][:10]


def by_key(key):
    for e in _entries():
        if key_of(e) == key:
            return e
    return None


def upcoming(now_utc, count=LIST_COUNT):
    return [e for e in _entries()
            if dt.datetime.fromisoformat(e["when_utc"]) >= now_utc][:count]


def next_computable(now_utc):
    """The next eclipse we can actually work out, else the next one at all.

    /eclipse lands here. Preferring a computable one is the whole point of
    the page: a reader arriving with no date in mind should get the one that
    can tell them something about where they are standing.
    """
    ahead = [e for e in _entries()
             if dt.datetime.fromisoformat(e["when_utc"]) >= now_utc]
    for e in ahead:
        if key_of(e) in besselian.ELEMENTS:
            return e
    return ahead[0] if ahead else _entries()[-1]


def is_solar(entry):
    return "solar" in entry["type"]


def facts(entry, place, now_utc):
    """Everything the page knows, as data, so the prose and the JSON cannot
    drift apart. The same contract object_facts works to."""
    key = key_of(entry)
    when = dt.datetime.fromisoformat(entry["when_utc"])
    tz = place.offset(when)
    out = {
        "eclipse": key,
        "name": entry["name"],
        "type": entry["type"],
        "when_utc": entry["when_utc"] + "Z",
        "when_local": (when + dt.timedelta(hours=tz)).isoformat(),
        "regions": entry["regions"],
        "place": place.name, "lat": place.lat, "lon": place.lon,
        "days_away": (when - now_utc).days,
        "computed": False,
    }

    # Lunar eclipses are not in besselian.ELEMENTS and never will be: the
    # elements are a solar construction. A lunar eclipse looks the same from
    # every place it is visible at all, so the only local question is whether
    # the Moon is up, which sky.py answers well enough on its own.
    if not is_solar(entry) or key not in besselian.ELEMENTS:
        return out

    circ = besselian.local(key, place.lat, place.lon)
    out["computed"] = True
    out["kind"] = circ["kind"]
    out["obscuration"] = circ["obscuration"]
    out["magnitude"] = circ["magnitude"]
    out["on_the_edge"] = besselian.on_the_edge(circ)
    out["sun_set_during"] = circ.get("sun_set_during", False)

    def clock(h):
        if h is None:
            return None
        local_h = (h + tz) % 24
        s = round(local_h * 3600)
        return f"{s // 3600:02d}:{s // 60 % 60:02d}"

    out["first"] = clock(circ["first"])
    out["maximum"] = clock(circ["maximum"])
    out["last"] = clock(circ["last"])
    out["duration_s"] = besselian.duration_seconds(circ)

    if circ["maximum"] is not None:
        at = dt.datetime(when.year, when.month, when.day) + \
            dt.timedelta(hours=circ["maximum"] % 24)
        alt, az = sky.sun_altaz(at, place.lat, place.lon)
        out["sun_alt"] = round(alt, 1)
        out["sun_az"] = round(az, 1)
        out["compass"] = sky.compass(az)
    return out


def headline(f):
    """The one sentence the page leads with, and the OG card repeats."""
    place = f["place"]
    if not f["computed"]:
        return f"{f['name']}, {_date_words(f)}"
    if f["kind"] == "none":
        return f"{f['name']}: not visible from {place}"
    if f["kind"] == "total" and not f["on_the_edge"]:
        secs = f["duration_s"]
        return (f"{place} is in the path: {secs:.0f} seconds of totality"
                if secs else f"{place} is in the path")
    if f["on_the_edge"]:
        return f"{place} is right on the edge of the path"
    return f"{f['obscuration'] * 100:.0f}% of the Sun covered from {place}"


def _date_words(f):
    when = dt.datetime.fromisoformat(f["when_utc"].rstrip("Z"))
    return when.strftime("%d %B %Y").lstrip("0")


def prose(f):
    """The paragraphs under the map, as plain sentences.

    Every branch here is a thing that is true of somewhere real on 12 August
    2026, which is why there are this many of them: the path crosses an
    ocean, a reader in Madrid is inside the prediction's own uncertainty,
    and most of Europe watches the Sun set partway through.
    """
    out = []
    if not f["computed"]:
        out.append(f"This one crosses {f['regions']}. There are no computed "
                   f"local circumstances for it here yet, so this page will "
                   f"not guess at what it does from {f['place']}.")
        return out

    if f["kind"] == "none":
        out.append(f"The Sun is below the horizon from {f['place']} while "
                   f"this eclipse is happening, so there is nothing to see "
                   f"from here. It crosses {f['regions']}.")
        return out

    if f["kind"] == "total" and not f["on_the_edge"]:
        out.append(f"{f['place']} is inside the path of totality. The Sun is "
                   f"completely covered for {f['duration_s']:.0f} seconds "
                   f"around {f['maximum']}.")
    elif f["on_the_edge"]:
        out.append(
            f"{f['place']} sits within a few kilometres of the edge of the "
            f"path, which is closer than the prediction itself can resolve. "
            f"Whether the Sun is completely covered here depends on the "
            f"profile of the Moon's edge, so this page will not tell you "
            f"either way. Check a detailed map before travelling on it.")
    else:
        out.append(f"From {f['place']} this is a partial eclipse: "
                   f"{f['obscuration'] * 100:.1f}% of the Sun is covered at "
                   f"maximum, around {f['maximum']}.")

    if f.get("sun_alt") is not None:
        # The compass point rather than a bearing in degrees, because this
        # is an instruction to somebody standing outside, and the same
        # reason the charts give fists rather than arcminutes.
        out.append(
            f"Face {f['compass']}: at maximum the Sun is "
            f"{f['sun_alt']:.0f}° above the horizon, about "
            f"{max(1, round(f['sun_alt'] / 10)):.0f} "
            f"{'fist' if round(f['sun_alt'] / 10) <= 1 else 'fists'} "
            f"held at arm's length. "
            + ("That is low enough for a building or a hill to hide it, so "
               "find somewhere with a clear western horizon in advance."
               if f["sun_alt"] < 12 else ""))

    if f["sun_set_during"]:
        out.append(f"The Sun sets from {f['place']} before the eclipse "
                   f"finishes, so the last part of it happens below the "
                   f"horizon.")

    out.append(f"The track crosses {f['regions']}.")
    return [s.strip() for s in out if s.strip()]


def sidebar_html(entry, now_utc, escape=html.escape):
    """The left column: what this eclipse is, then the ones after it.

    Real links, not script-swapped panels. Each eclipse is its own URL, so
    it can be shared, indexed, and read on a train.
    """
    when = dt.datetime.fromisoformat(entry["when_utc"])
    # "Next eclipse" only when it actually is the next one. /eclipse/2026-08-28
    # is a real URL somebody can land on, and calling a later eclipse the
    # next one there would be a small lie the reader has no way to catch.
    ahead = upcoming(now_utc, count=1)
    label = ("Next eclipse" if ahead and key_of(ahead[0]) == key_of(entry)
             else "This eclipse")
    out = ['<div class="ecl-intro">',
           f'<p class="ecl-sec">{label}</p>',
           f'<p class="obj-lede">{escape(entry["name"])} on '
           f'{escape(when.strftime("%d %B %Y").lstrip("0"))}, '
           f'{escape(when.strftime("%H:%M"))} UTC at greatest eclipse. '
           f'The track crosses {escape(entry["regions"])}.</p>']

    if key_of(entry) not in besselian.ELEMENTS:
        out.append('<p class="obj-src">No computed local circumstances for '
                   'this one yet, so this page gives the date and the '
                   'geography and stops there.</p>')
    out.append('</div>')

    rows = []
    for e in upcoming(now_utc):
        k = key_of(e)
        d = dt.datetime.fromisoformat(e["when_utc"])
        here = k == key_of(entry)
        # A mark for the ones that can answer "what about from here", so the
        # difference between a computed page and a listing is visible before
        # you click rather than after.
        precise = "&#9679;" if k in besselian.ELEMENTS else "&#9675;"
        label = escape(d.strftime("%d %b %Y").lstrip("0"))
        kind = escape(e["type"])
        link = (f'<b>{label}</b>' if here
                else f'<a href="/eclipse/{k}">{label}</a>')
        rows.append(f'<dt class="ecl-when">{precise} {link}</dt>'
                    f'<dd class="ecl-what">{kind}</dd>')
    out.append('<dl class="obj-facts ecl-list">'
               '<dt class="obj-sec" role="presentation">Coming up</dt>'
               '<dd class="obj-sec"></dd>' + "".join(rows) + '</dl>')
    out.append('<p class="obj-src">&#9679; local times computed here &nbsp; '
               '&#9675; date and regions only</p>')
    return "".join(out)


ECLIPSE_CSS = """
<style>
/* The list of dates. Same two-column grid as .obj-facts so it lines up with
   the block above it, but the date needs to stay on one line -- a wrapped
   "12 Aug 2026" reads as two entries. */
/* Section label, matching the "COMING UP" heading below it -- that one is a
   <dt> inside .obj-facts and this one is not, so the rule is repeated
   rather than shared. */
.ecl-sec{color:#8fb6e0;font-size:11px;letter-spacing:.09em;
  text-transform:uppercase;margin:0 0 .35rem}
/* A floor, not a fixed height. The blurb runs from two lines ("Antarctica")
   to six ("Nigeria, Cameroon, Chad, Sudan, Egypt, Saudi Arabia, Iran,
   Afghanistan, Pakistan, India and China"), and without this the list of
   dates underneath jumped up and down as you clicked between them -- the
   links moving out from under the cursor between one click and the next.
   Sized for the longest entry in the table plus the not-computed note.
   min-height rather than height so a longer one can still grow instead of
   being clipped. */
.ecl-intro{min-height:13rem}
@media (max-width:1000px){.ecl-intro{min-height:0}}
.ecl-disc{margin:0 0 16px}
.ecl-disc-cap{color:#6e7681;font-size:11.5px;margin:6px 0 0;
  font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.ecl-list .ecl-when{white-space:nowrap}
.ecl-list .ecl-what{color:#8b949e}
/* The map is the one thing on this page that must not reflow: it is a grid
   of characters and a changed line-height shears the track diagonally. Same
   reasoning as .obj-art, and the same fix. */
.ecl-map{line-height:1.0;font-variant-ligatures:none;overflow-x:auto;margin:0}
.ecl-safety{border-left:2px solid #d29922;padding:2px 0 2px 12px;margin:18px 0 0;
  color:#c9d1d9;font-size:12.5px;line-height:1.55;
  font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.ecl-safety b{color:#d29922;font-weight:600}
.ecl-times{display:flex;gap:22px;margin:0 0 14px;flex-wrap:wrap}
.ecl-times div{min-width:64px}
.ecl-times .k{display:block;color:#6e7681;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase}
.ecl-times .v{color:#e6edf3;font-size:15px}
</style>
"""


def live_html(f, map_rows, legend, ansi_to_html, chart_pre, disc=None,
              escape=html.escape):
    """The right column: the Sun, the numbers, the map, the prose, the warning."""
    out = []
    if disc:
        # .obj-art-frame and .obj-art are the planet portraits' own classes,
        # reused rather than reinvented: that CSS pins the line-height the
        # drawing is built for, and any other value squashes the disc back
        # into an ellipse. Same reason art.py's comment gives.
        out.append('<div class="obj-art-frame ecl-disc">'
                   '<pre class="obj-art" aria-hidden="true">'
                   + ansi_to_html(chr(10).join(disc)) + '</pre>'
                   f'<p class="ecl-disc-cap">{escape(_disc_caption(f))}</p>'
                   '</div>')
    if f["computed"] and f["kind"] != "none":
        cells = [("starts", f["first"]), ("maximum", f["maximum"]),
                 ("ends", f["last"])]
        if f.get("duration_s"):
            cells.append(("totality", f"{f['duration_s']:.0f}s"))
        out.append('<div class="ecl-times">' + "".join(
            f'<div><span class="k">{escape(k)}</span>'
            f'<span class="v">{escape(str(v))}</span></div>'
            for k, v in cells if v) + '</div>')

    if map_rows:
        out.append(f'<pre class="ecl-map">'
                   f'{ansi_to_html(chr(10).join(map_rows))}</pre>')
        out.append(f'<p class="obj-src">{ansi_to_html(legend)}</p>')

    for p in prose(f):
        out.append(f'<p class="obj-prose">{escape(p)}</p>')

    # Solar only. A lunar eclipse is the Moon in the Earth's shadow and is
    # completely safe to look at with anything you like, so a filter warning
    # there is not merely redundant -- it teaches the reader that this box
    # is boilerplate, on the pages where it is the most important sentence
    # we print.
    if "solar" in f["type"]:
        safety = SAFETY + (" " + SAFETY_TOTALITY if f.get("kind") == "total" else "")
        out.append(f'<p class="ecl-safety"><b>Your eyes.</b> {escape(safety)}</p>')
    return "".join(out)


def _disc_caption(f):
    """What the drawing shows, in one line.

    Names the moment and the orientation. The picture is drawn with
    celestial north up and east left, which is not the same as what you see
    standing outside -- turning it into zenith-up needs the parallactic
    angle -- and a drawing that quietly implied the wrong one would be worse
    than one that says.
    """
    when = f.get("maximum")
    if f.get("kind") == "total":
        what = "At totality, with the corona"
    elif f.get("obscuration"):
        what = f"At maximum, {f['obscuration'] * 100:.0f}% covered"
    else:
        what = "At maximum"
    return f"{what}{' around ' + when if when else ''}. North up, east left."


def text(f, rows, legend, disc=None, color=True):
    """The terminal version. Same facts, no markup."""
    out = [f"  {headline(f)}", ""]
    if f["computed"] and f["kind"] != "none":
        bits = [("starts", f["first"]), ("maximum", f["maximum"]),
                ("ends", f["last"])]
        out.append("  " + "   ".join(f"{k} {v}" for k, v in bits if v))
        out.append("")
    if disc:
        out += disc + ["", "  " + _disc_caption(f), ""]
    if rows:
        out += rows + ["", "  " + legend, ""]
    for p in prose(f):
        out.append("  " + p)
    if "solar" in f["type"]:
        out += ["", "  " + SAFETY]
        if f.get("kind") == "total":
            out.append("  " + SAFETY_TOTALITY)
    return "\n".join(out)
