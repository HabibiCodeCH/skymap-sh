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
import json
from urllib.parse import quote

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

    # The contacts and, if either falls inside them, sunrise or sunset --
    # in the order they actually happen. Zurich watches this eclipse reach
    # maximum, then loses the Sun 25 minutes before it ends, and a row
    # reading "starts / maximum / ends" with no sunset in it quietly implies
    # you can watch the whole thing.
    #
    # Nothing to lay out when the eclipse never reaches here: every contact
    # is None, and this used to walk straight into None % 24 and 500 the
    # page for everywhere on the night side of the planet.
    if circ["kind"] == "none" or circ["first"] is None or circ["last"] is None:
        out["timeline"] = []
        return out
    day = dt.datetime(when.year, when.month, when.day)
    ev = sky.sun_events(day, place.lat, place.lon)
    marks = []
    for label, key_ in (("starts", "first"), ("maximum", "maximum"),
                        ("ends", "last")):
        if circ[key_] is not None:
            marks.append({"label": label, "ut": circ[key_] % 24,
                          "clock": clock(circ[key_]), "kind": "contact"})
    lo, hi = circ["first"] % 24, circ["last"] % 24
    for label in ("sunrise", "sunset"):
        moment = ev.get(label)
        if moment is None:
            continue
        h = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
        if lo < h < hi:
            marks.append({"label": label, "ut": h, "clock": clock(h),
                          "kind": "horizon"})
    marks.sort(key=lambda m: m["ut"])
    # Anything after the Sun goes down is a time, not a sight.
    below = False
    for m in marks:
        if m["kind"] == "horizon":
            below = m["label"] == "sunset"
            continue
        m["below_horizon"] = below
    out["timeline"] = marks
    if circ.get("duration_s"):
        out["duration_s"] = circ["duration_s"]
    return out


def alongside(entry, tz=0.0):
    """What else is in the sky the same night, in local time.

    The night, not a window of hours either side. An eclipse on the evening
    of the 12th shares its night with the Perseids peaking at four the next
    morning, and shares nothing with a conjunction at lunchtime the day
    before -- which is what a plain plus-or-minus-36-hours turned up, and it
    read as a mistake because it was one.

    Local noon to local noon. An eclipse in the local morning belongs to the
    night that began the previous evening, so the window starts a day back.

    The eclipse itself is dropped, and so is the new moon that a solar
    eclipse always is: the Moon has to be new for the geometry to work, so
    listing it beside the eclipse is the same fact told twice.
    """
    when = dt.datetime.fromisoformat(entry["when_utc"])
    local = when + dt.timedelta(hours=tz)
    noon = local.replace(hour=12, minute=0, second=0, microsecond=0)
    if local < noon:
        noon -= dt.timedelta(days=1)
    lo = noon - dt.timedelta(hours=tz)
    near = events.scan_global(lo, days=1.0)
    out = []
    for e in near:
        at = e["when_utc"]
        if not (lo <= at <= lo + dt.timedelta(days=1)):
            continue
        if e["kind"] == "eclipse":
            continue
        if (e["kind"] == "moon_phase"
                and abs((at - when).total_seconds()) < 3600):
            continue
        out.append({"name": e["name"], "kind": e["kind"],
                    "when": at + dt.timedelta(hours=tz),
                    "href": _object_href(e)})
    return out


# Which events have a page of their own to send people to. A shower does; a
# conjunction is a geometry between two things rather than a thing.
def _object_href(e):
    import objects
    name = objects.resolve_name(e["name"])
    return f"/{name.replace(' ', '%20')}" if name else None


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


def _blurb(entry, f=None):
    """What this eclipse is and what it does here, in one paragraph.

    The first version read "Total solar eclipse on 12 August 2026, 17:47 UTC
    at greatest eclipse", which says almost nothing. "Greatest eclipse" is
    the instant the shadow axis passes closest to the Earth's centre: a term
    of art, not a fact anyone standing outside needs. And a UTC time with no
    place attached is not a time you can turn up at.

    This paragraph does carry the reader's own location, which the rest of
    the left column deliberately does not. That is a considered exception:
    the sentence is useless without it, and the canonical still points at
    the bare /eclipse/{date}, so the indexed page is one page rather than
    forty thousand.
    """
    when = dt.datetime.fromisoformat(entry["when_utc"])
    date = when.strftime("%d %B %Y").lstrip("0")
    verb = "crossing" if is_solar(entry) else "in view from"
    out = [f"{entry['name']} on {date} {verb} {entry['regions']}."]

    if not f or not f.get("computed"):
        return " ".join(out)
    place = f["place"]
    if f["kind"] == "none":
        out.append(f"Not visible from {place}: the Sun is already below the "
                   f"horizon by then.")
        return " ".join(out)
    if f["kind"] == "total" and not f.get("on_the_edge"):
        out.append(f"In {place}, the Sun is completely covered for "
                   f"{f['duration_s']:.0f} seconds at around {f['maximum']}.")
    elif f.get("on_the_edge"):
        out.append(f"{place} sits right on the edge of the path, too close "
                   f"to call.")
    else:
        out.append(f"In {place}, the eclipse reaches a maximum of "
                   f"{f['obscuration'] * 100:.0f}% at around {f['maximum']}.")
    if f.get("sun_alt") is not None:
        out.append(f"Look to the {f['compass']}, {f['sun_alt']:.0f}° above "
                   f"the horizon.")
    return " ".join(out)


def sidebar_html(entry, now_utc, disc=None, disc_html='',
                 disc_caption='', also=(), f=None,
                 escape=html.escape):
    """The left column: what this eclipse is, then the ones after it.

    Order matters here. The drawing goes directly under the heading, before
    the prose, because it is the thing that says what kind of eclipse this
    is faster than a sentence can. The caption sits OUTSIDE the frame:
    .obj-art-frame centres its children, and a caption inside it laid itself
    out beside the drawing and over the top of it.

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
    out = [f'<p class="ecl-sec">{label}</p>']

    if disc:
        out.append('<div class="obj-art-frame ecl-disc">'
                   '<pre class="obj-art" aria-hidden="true">'
                   + disc_html + '</pre></div>')
        # No caption. It read "At maximum, 90% covered around 20:17. North
        # up, east left" -- the percentage and the time are already in the
        # paragraph directly below and in the timeline opposite, and the
        # orientation note was defensive rather than useful. disc_caption()
        # stays for the terminal version, which has no paragraph beside the
        # drawing to carry any of it.

    out.append('<div class="ecl-intro">')
    out.append(f'<p class="obj-lede">{escape(_blurb(entry, f))}</p>')
    if key_of(entry) not in besselian.ELEMENTS:
        out.append('<p class="obj-src">No computed local circumstances for '
                   'this one yet, so this page gives the date and the '
                   'geography and stops there.</p>')
    out.append('</div>')

    if also:
        rows = []
        for a in also:
            when = a["when"].strftime("%d %b, %H:%M")
            label = escape(a["name"])
            body = (f'<a href="{a["href"]}">{label}</a>' if a["href"]
                    else label)
            rows.append(f'<dt class="ecl-when">{body}</dt>'
                        f'<dd class="ecl-what">{escape(when)}</dd>')
        out.append('<dl class="obj-facts ecl-list ecl-also">'
                   '<dt class="obj-sec" role="presentation">'
                   'The same night</dt><dd class="obj-sec"></dd>'
                   + "".join(rows) + '</dl>')

    return "".join(out)


def picker_html(entry, now_utc, place=None, escape=html.escape):
    """The eclipse list, as a disclosure under the heading.

    <details> rather than a <select>: it needs no script, it keeps every
    entry a real link that can be opened in a new tab or copied, and it
    shows the type and the computed/not marker beside each date, which a
    native dropdown cannot.

    Every link carries the place forward. Without that, picking a later
    eclipse from /Marbella/eclipse dropped you on /eclipse/2027-08-02 and
    silently relocated you to wherever your IP says you are -- on a page
    whose whole job is to answer "what happens where I am standing".
    """
    base = f"/{quote(place)}/eclipse" if place else "/eclipse"
    here = key_of(entry)
    rows = []
    for e in upcoming(now_utc):
        k = key_of(e)
        d = dt.datetime.fromisoformat(e["when_utc"])
        # The Sun and the Moon, the same glyphs the sky chart draws them
        # with, so the list says what kind of eclipse each one is at a
        # glance. That happens to be the same distinction the plain dots
        # used to make: a solar eclipse has Besselian elements and can
        # answer "what about from here", a lunar one has none and never
        # will, because the elements are a solar construction.
        solar = k in besselian.ELEMENTS
        precise = ('<span class="ecl-sun">&#9728;</span>' if solar
                   else '<span class="ecl-moon">&#9789;</span>')
        lbl = escape(d.strftime("%d %b %Y").lstrip("0"))
        body = (f'<b>{lbl}</b>' if k == here
                else f'<a href="{base}/{k}">{lbl}</a>')
        rows.append(f'<li>{precise} {body} '
                    f'<span class="ecl-what">{escape(e["type"])}</span></li>')
    shown = dt.datetime.fromisoformat(entry["when_utc"])
    return ('<details class="ecl-picker">'
            f'<summary>{escape(shown.strftime("%d %B %Y").lstrip("0"))} '
            f'&middot; {escape(entry["type"])}'
            '<span class="ecl-more">change</span></summary>'
            '<div class="ecl-panel">'
            '<ul>' + "".join(rows) + '</ul>'
            # One per line. Side by side they wrapped wherever the panel
            # happened to end, which put "date" on one line and "and regions
            # only" on the next and read as a third entry.
            '<p class="ecl-key">'
            '<span><span class="ecl-sun">&#9728;</span> solar, local times '
            'computed here</span>'
            '<span><span class="ecl-moon">&#9789;</span> lunar, date and '
            'regions only</span></p>'
            '</div></details>')


def picker_script():
    """Escape closes the eclipse list.

    <details> has no native close-on-escape, so a dropdown opened by accident
    stays open over the page until it is clicked again. Focus goes back to
    the summary, so escape leaves the keyboard where it found it.

    Separate from frames_script on purpose: that one only ships where there
    is an animation, and the list is on every eclipse page including the ones
    with nothing to draw.
    """
    return ("<script>\n(function(){\n"
            "  var d=document.querySelector('.ecl-picker');\n"
            "  if(!d)return;\n"
            "  document.addEventListener('keydown',function(e){\n"
            "    if(e.key!=='Escape'||!d.open)return;\n"
            "    e.preventDefault();d.open=false;\n"
            "    var s=d.querySelector('summary');if(s)s.focus();\n"
            "  });\n"
            "})();\n</script>")


ECLIPSE_CSS = """
<style>
/* The list of dates. Same two-column grid as .obj-facts so it lines up with
   the block above it, but the date needs to stay on one line -- a wrapped
   "12 Aug 2026" reads as two entries. */
/* Section label, matching the "COMING UP" heading below it -- that one is a
   <dt> inside .obj-facts and this one is not, so the rule is repeated
   rather than shared. */
/* The same face and size as the live column's heading opposite it, because
   the two are peers: one names the eclipse, the other says what it does
   from here, and setting one as a small blue label made it read as a
   caption for the drawing instead. */
.ecl-sec{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:16.5px;color:#e6ebf2;letter-spacing:0;text-transform:none;
  margin:0 0 .35rem}
/* No floor here any more. It existed to stop the list of dates jumping as
   the blurb changed length between eclipses, and that list is a dropdown by
   the heading now -- nothing below this moves when it changes, so reserving
   the height of the longest entry in the table just left a hole under the
   short ones. */
.ecl-intro{margin:0 0 .2rem}
.ecl-list .ecl-when{white-space:nowrap}
.ecl-also dt.obj-sec{margin-top:.45rem}
.ecl-list .ecl-what{color:#8b949e}
/* The map is the one thing on this page that must not reflow: it is a grid
   of characters and a changed line-height shears the track diagonally. Same
   reasoning as .obj-art, and the same fix.

   It is also a fixed 96 characters wide whatever the window, so at 11px it
   needs 634px and anything narrower than that pushed it into scrolling
   sideways inside its own box -- half of Europe off the right-hand edge,
   with nothing to say so. Sized against the column instead: 96 characters at
   0.6em each is 57.6em, so 1.6cqw keeps the whole track on screen with a
   little room, and the min() means it never grows past the 11px everything
   else on the page is drawn at. Browsers without container queries drop the
   line and keep 11px and the scrollbar. */
/* Same small section label as "THE SAME NIGHT" in the left column, so the
   two columns mark their sections the same way. The space above it is what
   separates the map from the drawing over it; below it, almost none, because
   the label belongs to the map. */
.ecl-maptitle{color:#8fb6e0;font-size:11px;letter-spacing:.09em;
  text-transform:uppercase;margin:1.1rem 0 .45rem}
/* A little more air than the map's own label: what it separates is two
   blocks of text rather than a label from the thing it names. */
.ecl-prose-title{margin-top:1.4rem}
.ecl-mapwrap{container-type:inline-size;margin:0 0 2px}
.ecl-map{line-height:1.0;font-variant-ligatures:none;overflow-x:auto;margin:0;
  font-size:min(11px,1.6cqw)}
.ecl-safety{border-left:2px solid #d29922;padding:2px 0 2px 12px;
  margin:4px 0 2px;color:#c9d1d9;font-size:12px;line-height:1.5;
  font-family:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.ecl-safety b{color:#d29922;font-weight:600}
/* The times are the heading of this column, not a row underneath it. The
   sentence that used to sit here said the same thing in words, one line
   above the numbers it was describing. */
.ecl-times{display:flex;gap:22px;flex-wrap:wrap}
.ecl-times div{min-width:64px}
/* Set like the label opposite it in the left column, and bottom-aligned with
   the numbers so the whole row sits on one line. */
.ecl-where{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:16.5px;color:#e6ebf2;white-space:nowrap}
.ecl-times .ecl-where{align-self:flex-end;line-height:1.15}
.ecl-times .k{display:block;color:#6e7681;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase}
.ecl-times .v{color:#e6edf3;font-size:15px}
/* Sunrise and sunset sit in the same row as the contacts because they
   happen in the same sequence, but they are a different kind of fact --
   the sky doing something rather than the eclipse. */
.ecl-times .ecl-horizon .k{color:#d29922}
.ecl-times .ecl-horizon .v{color:#d29922}
/* A contact that happens after the Sun is down is a time, not a sight. */
.ecl-times .ecl-unseen .k,.ecl-times .ecl-unseen .v{color:#545d68}
/* The eclipse selector beside the heading. This block was deleted by an
   unrelated edit that removed the intro's fixed height and took everything
   between two markers with it, which is what left the dropdown unstyled. */
.ecl-picker{position:relative;margin:0;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.ecl-picker summary{cursor:pointer;color:#c9d1d9;font-size:13px;
  list-style:none;display:inline-flex;align-items:center;gap:10px;
  border:1px solid #30363d;border-radius:6px;padding:6px 12px}
.ecl-picker summary::-webkit-details-marker{display:none}
.ecl-picker summary:hover,.ecl-picker[open] summary{border-color:#8fb6e0}
.ecl-more{color:#6e7681;font-size:11px;letter-spacing:.06em;
  text-transform:uppercase}
/* One panel holding both the list and the key. They used to be two boxes
   positioned at the same offset, so the key rendered on top of the dates. */
.ecl-panel{position:absolute;top:calc(100% + 6px);left:0;z-index:30;
  min-width:280px;background:#0d1117;border:1px solid #30363d;
  border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.7)}
/* The same colours the sky chart draws these two in: xterm 227 for the Sun
   (sky.C.SUN) and 253 for the Moon (sky.C.MOON). A glyph that is the Sun
   everywhere else on the site should not be grey here. */
.ecl-sun{color:#ffff5f}
.ecl-moon{color:#dadada}
.ecl-picker ul{list-style:none;margin:0;padding:8px 12px}
.ecl-picker li{padding:3px 0;font-size:13px;white-space:nowrap}
.ecl-picker li a{color:#87d7ff}
.ecl-key{color:#6e7681;font-size:11px;margin:0;padding:5px 12px 9px;
  border-top:1px solid #21262d;line-height:1.6}
.ecl-key span{display:block;white-space:nowrap}
.ecl-head-row{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  margin:1.5rem 0 14px}
.ecl-head-row .obj-title{margin:0}
/* The two drawings have to start on the same line, and what sits above them
   does not match: a short label on the left, a sentence that may wrap to two
   lines on the right. Same slot for both, content sitting at the bottom of
   it, so the frames stay level however the sentence breaks. Sized for two
   lines at 16.5px. */
.ecl-sec,.obj-live-head.ecl-head{min-height:3.3rem;margin:0 0 .35rem;
  display:flex;align-items:flex-end}
/* The animation frame. The clock and the transport sit on top of the
   drawing, so the frame is what they are positioned against. */
.ecl-anim{position:relative}
.ecl-clock,.ecl-controls{position:absolute;right:12px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px;color:#8b949e}
.ecl-clock{top:9px;letter-spacing:.04em}
/* Bottom right, out of the drawing's way. Plain text: these are four small
   words over a picture, and button chrome made them look like a video
   player had landed on it. */
.ecl-controls{bottom:9px;display:flex;align-items:baseline;gap:14px}
.ecl-btn{background:none;border:0;padding:0;margin:0;font:inherit;
  color:#8b949e;cursor:pointer;line-height:1}
.ecl-btn:hover{color:#e6edf3}
/* The word changes as it plays, and a row that shifts sideways every time
   you press it is a row you cannot press twice. */
#ecl-toggle{min-width:3.4em;text-align:center}
a.ecl-gif{color:#87d7ff;text-decoration:none}
a.ecl-gif:hover{text-decoration:underline}
</style>"""


def map_title(f):
    """What the map is of, which depends on what kind of eclipse this is.

    Only a total eclipse has a path of totality. An annular one has a path of
    annularity, and calling it totality on the page that draws it would be
    wrong in the one place a reader could check.
    """
    kind = (f.get("type") or "").lower()
    if "annular" in kind:
        return "Path of annularity"
    if "total" in kind:
        return "Path of totality"
    return "Where the eclipse is visible"


def live_head_html(f, escape=html.escape):
    """The right column's heading: where you are, then when it happens.

    The times used to sit in a row of their own below the drawing, under a
    sentence that said the same thing again in words. They are the answer
    this column exists to give, so they are the heading, and the sentence is
    gone rather than repeated. The headline still leads the <title> and the
    card, which are read without the page around them.

    Falls back to the sentence where there are no times to show: not visible
    from here, or an eclipse with no computed circumstances at all.
    """
    if not f.get("timeline"):
        return (f'<p class="obj-lede obj-live-head ecl-head">'
                f'{escape(headline(f))}</p>')
    cells = [f'<span class="ecl-where">In {escape(f["place"])}</span>']
    for m in f["timeline"]:
        cls = (" ecl-horizon" if m["kind"] == "horizon"
               else " ecl-unseen" if m.get("below_horizon") else "")
        cells.append(f'<div class="{cls.strip()}">'
                     f'<span class="k">{escape(m["label"])}</span>'
                     f'<span class="v">{escape(m["clock"])}</span></div>')
    # How much of the Sun goes, in the same row as when. On the edge of the
    # path this deliberately does not say 100%: the prediction cannot resolve
    # which side of the limit the place is on, and the prose below says so.
    if f.get("on_the_edge"):
        cells.append('<div><span class="k">totality</span>'
                     '<span class="v">on the edge</span></div>')
    elif f.get("kind") == "total" and f.get("duration_s"):
        cells.append('<div><span class="k">totality</span>'
                     f'<span class="v">{f["duration_s"]:.0f}s</span></div>')
    elif f.get("obscuration"):
        cells.append('<div><span class="k">covered</span>'
                     f'<span class="v">{f["obscuration"] * 100:.0f}%</span></div>')
    return ('<div class="obj-live-head ecl-head ecl-times">'
            + "".join(cells) + '</div>')


def live_html(f, map_rows, legend, ansi_to_html, chart_pre,
              frames_html=(), frame_labels=(), gif_href='',
              escape=html.escape):
    """The right column: the eclipse running, the numbers, the map, the
    prose, the warning."""
    out = []
    if frames_html:
        # The whole eclipse, first contact to last. Frames are rendered on
        # the server because the geometry is Besselian and the browser has
        # none of it -- what ships is pictures, not a solver.
        #
        # Frame 0 is in the markup, so with no JS this is simply the eclipse
        # beginning, drawn, rather than an empty box. The controls only
        # appear once the script has something to control.
        out.append(
            '<div class="obj-art-frame ecl-anim">'
            '<pre class="obj-art" id="ecl-play" aria-hidden="true">'
            + frames_html[0] + '</pre>'
            # In the frame, top right, so the time reads as part of the
            # picture rather than as a caption about it -- it is the one
            # number that changes while you watch. Local time, like every
            # other clock on the page.
            f'<span class="ecl-clock" id="ecl-clock">'
            f'{escape(frame_labels[0])}</span>'
            # Controls in the frame's bottom right, next to nothing else, so
            # they read as belonging to the picture. Plain text, no button
            # chrome: white rounded rectangles sitting on the drawing looked
            # like a video player had been dropped on top of it. Hidden until
            # the script runs -- without JS the frame is a still of first
            # contact and there is nothing for them to do.
            '<span class="ecl-controls" id="ecl-controls" hidden>'
            '<button type="button" id="ecl-prev" class="ecl-btn"'
            ' aria-label="previous frame">&lt;</button>'
            '<button type="button" id="ecl-toggle" class="ecl-btn"'
            ' aria-label="pause">pause</button>'
            '<button type="button" id="ecl-next" class="ecl-btn"'
            ' aria-label="next frame">&gt;</button>'
            f'<a class="ecl-btn ecl-gif" id="ecl-gif" href="{gif_href}">gif</a>'
            '</span>'
            '</div>')
    # No times row here: it is the column's heading now (see live_head_html).
    #
    # The warning sits between the drawing and the map: directly after the
    # thing that shows you what you would be looking at, and before the thing
    # that tells you where to go and look at it.
    out.append(safety_html(f, escape))
    if map_rows:
        # Named, because a band of red dots across northern Spain is not
        # self-explanatory, and the map answers a different question from
        # everything above it: not what happens here, but where to stand.
        out.append(f'<p class="ecl-maptitle">{escape(map_title(f))}</p>')
        # Wrapped, so the map can be sized against the width of the column
        # rather than against the page. It is a fixed 96 characters wide and
        # was scrolling sideways inside its own box; see .ecl-mapwrap.
        out.append(f'<div class="ecl-mapwrap"><pre class="ecl-map">'
                   f'{ansi_to_html(chr(10).join(map_rows))}</pre></div>')
        out.append(f'<p class="obj-src">{ansi_to_html(legend)}</p>')

    if prose(f):
        out.append('<p class="ecl-maptitle ecl-prose-title">'
                   'Additional information</p>')
    for p in prose(f):
        out.append(f'<p class="obj-prose">{escape(p)}</p>')


    # The warning is not down here any more. It sits beside the heading, at
    # the top of the page, because it is the one thing on it that can stop
    # somebody hurting themselves and the bottom of a column is where you get
    # to after you have already been outside. See safety_html.
    return "".join(out)


def safety_html(f, escape=html.escape):
    """The filter warning, for the top of the page.

    Solar only. A lunar eclipse is the Moon in the Earth's shadow and is
    completely safe to look at with anything you like, so a filter warning
    there is not merely redundant -- it teaches the reader that this box is
    boilerplate, on the pages where it is the most important sentence we
    print.
    """
    if "solar" not in f["type"]:
        return ""
    safety = SAFETY + (" " + SAFETY_TOTALITY if f.get("kind") == "total" else "")
    return f'<p class="ecl-safety"><b>Your eyes.</b> {escape(safety)}</p>'


def disc_caption(f):
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
    if f.get("timeline"):
        out.append("  " + "   ".join(
            f"{m['label']} {m['clock']}" + ("*" if m.get("below_horizon") else "")
            for m in f["timeline"]))
        if any(m.get("below_horizon") for m in f["timeline"]):
            out.append("  * after the Sun has set from here")
        out.append("")
    if disc:
        out += disc + ["", "  " + disc_caption(f), ""]
    if rows:
        out += ["  " + map_title(f), ""] + rows + ["", "  " + legend, ""]
    if prose(f):
        out += ["  Additional information", ""]
    for p in prose(f):
        out.append("  " + p)
    if "solar" in f["type"]:
        out += ["", "  " + SAFETY]
        if f.get("kind") == "total":
            out.append("  " + SAFETY_TOTALITY)
    return "\n".join(out)


def frames_script(frames_html, labels):
    """Plays the pre-rendered frames.

    No geometry in here: the browser is handed pictures and a list of clock
    times, because everything that decided what those pictures look like is
    Besselian and lives on the server.

    Honours prefers-reduced-motion by starting paused. An eclipse looping
    every four seconds is exactly the kind of thing that setting exists for,
    and the frames are still all there to step through.

    The keys are the ones the sky chart already uses for its animation:
    space plays and pauses, the arrows step, v takes the export. Somebody who
    has driven one of these on the front page should not have to learn a
    second set of them here.
    """
    if not frames_html:
        return ""
    return (
        "<script>\n(function(){\n"
        f"  var F={json.dumps(frames_html)},L={json.dumps(list(labels))};\n"
        "  var pre=document.getElementById('ecl-play'),"
        "clock=document.getElementById('ecl-clock'),"
        "btn=document.getElementById('ecl-toggle');\n"
        "  if(!pre||!F.length)return;\n"
        "  var i=0,timer=null;\n"
        "  var still=window.matchMedia&&"
        "window.matchMedia('(prefers-reduced-motion: reduce)').matches;\n"
        "  var show=function(){pre.innerHTML=F[i];"
        "if(clock)clock.textContent=L[i];};\n"
        "  var step=function(){i=(i+1)%F.length;show();};\n"
        "  var play=function(){if(timer)return;timer=setInterval(step,180);"
        "if(btn){btn.textContent='pause';btn.setAttribute('aria-label','pause');}};\n"
        "  var stop=function(){clearInterval(timer);timer=null;"
        "if(btn){btn.textContent='play';btn.setAttribute('aria-label','play');}};\n"
        "  var bar=document.getElementById('ecl-controls');\n"
        "  var prev=document.getElementById('ecl-prev'),"
        "next=document.getElementById('ecl-next');\n"
        "  var jump=function(d){stop();i=(i+d+F.length)%F.length;show();};\n"
        "  if(bar)bar.hidden=false;\n"
        "  if(prev)prev.addEventListener('click',function(){jump(-1);});\n"
        "  if(next)next.addEventListener('click',function(){jump(1);});\n"
        "  if(btn)btn.addEventListener('click',function(){timer?stop():play();});\n"
        # Never while something else owns the key: typing a place with a
        # space in it must still type a space, and space on a focused
        # <summary> has to keep opening the eclipse list.
        "  var busy=function(e){var t=e.target,n=t&&t.tagName;\n"
        "    return n==='INPUT'||n==='TEXTAREA'||n==='SELECT'||n==='SUMMARY'||"
        "n==='BUTTON'||n==='A'||(t&&t.isContentEditable);};\n"
        "  document.addEventListener('keydown',function(e){\n"
        "    if(busy(e)||e.metaKey||e.ctrlKey||e.altKey)return;\n"
        "    if(e.key===' '||e.key==='Spacebar'){e.preventDefault();"
        "timer?stop():play();return;}\n"
        "    if(e.key==='ArrowLeft'){e.preventDefault();jump(-1);return;}\n"
        "    if(e.key==='ArrowRight'){e.preventDefault();jump(1);return;}\n"
        "    if(e.key==='v'){var g=document.getElementById('ecl-gif');"
        "if(g){e.preventDefault();location.href=g.href;}}\n"
        "  });\n"
        "  if(still){stop();}else{play();}\n"
        "})();\n</script>")
