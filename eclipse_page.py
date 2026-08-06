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
import re
from urllib.parse import quote

import besselian
import eclipse as eclipse_map
import events
import lunar
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
    """The eclipses still ahead, soonest first. count=None for all of them."""
    ahead = [e for e in _entries()
             if dt.datetime.fromisoformat(e["when_utc"]) >= now_utc]
    return ahead if count is None else ahead[:count]


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


# Colour codes, so a row's width can be measured in characters somebody can
# actually see rather than in escape sequences.
_ANSI = re.compile(r"\033\[[0-9;]*m")


def is_solar(entry):
    return "solar" in entry["type"]


def _clock(h, tz):
    """Hours UT to a local HH:MM. Hours may be negative or past 24 when an
    eclipse straddles midnight; the modulo is what makes that a clock."""
    if h is None:
        return None
    s = round(((h + tz) % 24) * 3600)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}"


def lunar_facts(out, key, place, tz):
    """The same contract as the solar half, from lunar.py's numbers.

    The timeline is deliberately the same shape and the same three labels:
    starts, maximum, ends. A lunar eclipse has seven named contacts, and
    printing all of them puts the two nobody can see -- the penumbral ones,
    which are a faint grey nothing -- in the same row and the same size as
    the moment the Moon turns copper. Moonrise and moonset go in the row
    when they fall inside, exactly as sunset does on a solar page, because
    they are what decides whether any of this happens above your horizon.
    """
    if not lunar.has(key):
        return out
    el = lunar.elements(key)
    marks = lunar.contacts(key)
    vis = lunar.visibility(key, place.lat, place.lon)
    out["computed"] = True
    out["kind"] = el["kind"]
    out["um_mag"] = el["um_mag"]
    out["visible"] = vis["visible"]
    out["all_of_it"] = vis["all_of_it"]
    out["alt_at_greatest"] = round(vis["alt_at_greatest"], 1)
    out["maximum"] = _clock(marks["greatest"], tz)
    out["duration_s"] = lunar.duration_seconds(key, "tot_min")

    # The visible phase: the umbral one where there is an umbral one. A
    # penumbral eclipse has nothing else, so there it is all there is.
    lo = marks.get("U1", marks.get("P1"))
    hi = marks.get("U4", marks.get("P4"))
    out["first"], out["last"] = _clock(lo, tz), _clock(hi, tz)

    window = lunar.up_window(key, place.lat, place.lon)
    out["moon_up"] = None if window is None else (
        _clock(window[0], tz), _clock(window[1], tz))
    peak = lunar.peak_alt(key, place.lat, place.lon)
    out["peak_alt"] = None if peak is None else round(peak, 1)
    if not vis["visible"] or lo is None or hi is None:
        out["timeline"] = []
        return out

    rows = [{"label": "starts", "ut": lo, "kind": "contact"},
            {"label": "maximum", "ut": marks["greatest"], "kind": "contact"},
            {"label": "ends", "ut": hi, "kind": "contact"}]
    if window is not None:
        for label, moment in (("moonrise", window[0]), ("moonset", window[1])):
            if lo < moment < hi:
                rows.append({"label": label, "ut": moment, "kind": "horizon"})
    rows.sort(key=lambda m: m["ut"])
    below = (lunar.moon_alt(key, place.lat, place.lon, rows[0]["ut"]) or 0) <= 0
    for m in rows:
        m["clock"] = _clock(m["ut"], tz)
        if m["kind"] == "horizon":
            below = m["label"] == "moonset"
            continue
        m["below_horizon"] = below
    out["timeline"] = rows
    return out


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
    # elements are a solar construction. They have their own published
    # circumstances instead (lunar.py), and their own question -- not how
    # much of it you get, since everybody who can see one sees the same
    # thing, but whether the Moon is up for it at all.
    if not is_solar(entry):
        return lunar_facts(out, key, place, tz)
    if key not in besselian.ELEMENTS:
        return out

    circ = besselian.local(key, place.lat, place.lon)
    out["computed"] = True
    out["kind"] = circ["kind"]
    out["obscuration"] = circ["obscuration"]
    out["magnitude"] = circ["magnitude"]
    out["on_the_edge"] = besselian.on_the_edge(circ)
    out["sun_up"] = circ.get("sun_up", True)
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
    if not is_solar(f):
        return lunar_headline(f)
    if f["kind"] == "none":
        return f"{f['name']}: not visible from {place}"
    if f["kind"] == "total" and not f["on_the_edge"]:
        secs = f["duration_s"]
        return (f"{place} is in the path: {secs:.0f} seconds of totality"
                if secs else f"{place} is in the path")
    if f["on_the_edge"]:
        return f"{place} is right on the edge of the path"
    return f"{f['obscuration'] * 100:.0f}% of the Sun covered from {place}"


def _minutes_words(secs):
    m = round(secs / 60.0)
    return f"{m} minute{'s' if m != 1 else ''}"


def lunar_headline(f):
    place = f["place"]
    if not f["visible"]:
        return f"{f['name']}: not visible from {place}"
    if f["kind"] == "total":
        secs = f["duration_s"]
        got = (f"the Moon is copper for {_minutes_words(secs)}"
               if secs else "the Moon goes copper")
        return (f"{place} sees all of it: {got}" if f["all_of_it"]
                else f"{place} sees part of it: {got}")
    if f["kind"] == "penumbral":
        return f"A faint shading of the Moon, seen from {place}"
    covered = f"{f['um_mag'] * 100:.0f}% of the Moon in shadow"
    return (f"{covered}, from {place}" if f["all_of_it"]
            else f"{covered}, and {place} sees part of it")


def _date_words(f):
    when = dt.datetime.fromisoformat(f["when_utc"].rstrip("Z"))
    return when.strftime("%d %B %Y").lstrip("0")


def lunar_prose(f):
    """The paragraphs for a lunar eclipse.

    A different set of facts from a solar one, and the difference is worth
    saying out loud on the page: there is no path, no percentage that
    depends on where you stand, and nothing to travel for. Half the world
    gets the same view at the same moment. What is worth knowing is whether
    the Moon is up here, how deep into the shadow it goes, and that this one
    is safe to look at with anything.
    """
    place, out = f["place"], []
    if not f["visible"]:
        out.append(f"The Moon is below the horizon from {place} for the whole "
                   f"of this eclipse, so there is nothing to see from here. "
                   f"It is visible from {f['regions']}.")
        return out

    if f["kind"] == "total":
        out.append(
            f"The Moon passes entirely into the Earth's shadow"
            + (f" for {_minutes_words(f['duration_s'])}" if f["duration_s"] else "")
            + f", around {f['maximum']}. It does not go dark: the only light "
              f"reaching it is sunlight bent through the whole depth of the "
              f"Earth's atmosphere, which is why it turns copper.")
    elif f["kind"] == "penumbral":
        out.append(
            f"The Moon misses the Earth's dark inner shadow and passes "
            f"through the outer one, so this is a subtle eclipse: a faint "
            f"grey shading across one side of the disc, deepest around "
            f"{f['maximum']}, and easy to miss if you do not know it is "
            f"happening.")
    else:
        out.append(
            f"{f['um_mag'] * 100:.0f}% of the Moon's diameter goes into the "
            f"Earth's dark shadow at maximum, around {f['maximum']}. The "
            f"shadowed part turns a dull copper rather than black, and the "
            f"edge of it is visibly curved: that curve is the shape of the "
            f"Earth, which is how the Greeks knew.")

    if f.get("alt_at_greatest") is not None and f["visible"]:
        alt = f["alt_at_greatest"]
        if alt < 12:
            out.append(f"It is low from {place}, {alt:.0f}° above the horizon "
                       f"at maximum, so you will want somewhere with a clear "
                       f"view in that direction.")
        else:
            out.append(f"From {place} the Moon is {alt:.0f}° above the "
                       f"horizon at maximum.")
    if not f["all_of_it"] and f.get("moon_up"):
        out.append(f"Part of it happens with the Moon below the horizon "
                   f"here: it is up from {f['moon_up'][0]} to "
                   f"{f['moon_up'][1]} local time.")

    out.append(
        "Everybody who can see a lunar eclipse sees the same thing at the "
        "same moment, so there is no path to travel to and no percentage "
        "that depends on where you stand. The only question is whether the "
        "Moon is up, and it is up for half the planet at once.")
    out.append("Safe to look at with anything: eyes, binoculars, a telescope. "
               "The Moon is only ever reflecting sunlight, and during an "
               "eclipse it is reflecting a great deal less of it than usual.")
    out.append(f"Visible from {f['regions']}.")
    return out


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

    if not is_solar(f):
        return lunar_prose(f)

    if f["kind"] == "none":
        # Which nothing this is. The Sun can be up here with the shadow on
        # the other side of the planet, and telling somebody in Honolulu
        # that the Sun had set at two in the afternoon was a small lie the
        # page had no need to tell.
        why = ("the Sun is below the horizon from "
               f"{f['place']} while this eclipse is happening"
               if not f.get("sun_up") else
               f"the shadow never reaches {f['place']}")
        out.append(f"Nothing to see from here: {why}. "
                   f"It crosses {f['regions']}.")
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
    if not is_solar(entry):
        if not f["visible"]:
            out.append(f"Not visible from {place}: the Moon is below the "
                       f"horizon throughout.")
        elif f["kind"] == "total":
            out.append(f"From {place} the Moon is fully in the Earth's "
                       f"shadow around {f['maximum']}, "
                       f"{f['alt_at_greatest']:.0f}° above the horizon.")
        elif f["kind"] == "penumbral":
            out.append(f"A faint shading, deepest around {f['maximum']} "
                       f"from {place}.")
        else:
            out.append(f"From {place}, {f['um_mag'] * 100:.0f}% of the Moon "
                       f"is in shadow around {f['maximum']}, "
                       f"{f['alt_at_greatest']:.0f}° above the horizon.")
        return " ".join(out)
    if f["kind"] == "none":
        out.append(f"Not visible from {place}: the Sun is already below the "
                   f"horizon by then." if not f.get("sun_up") else
                   f"Not visible from {place}: the shadow does not reach "
                   f"this far.")
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


def table_span():
    """"44 eclipses tracked, 2026 to 2040" -- read off the table rather than
    typed, so it cannot describe a table we no longer have."""
    rows = _entries()
    if not rows:
        return ""
    first = dt.datetime.fromisoformat(rows[0]["when_utc"]).year
    last = dt.datetime.fromisoformat(rows[-1]["when_utc"]).year
    return f"{len(rows)} eclipses tracked, {first} to {last}"


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

    def row(e):
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
        return (f'<li>{precise} {body} '
                f'<span class="ecl-what">{escape(e["type"])}</span></li>')

    ahead = upcoming(now_utc, count=None)
    rows = [row(e) for e in ahead[:LIST_COUNT]]
    # Everything past the first handful, behind one more click. The table
    # runs to 2040 and a list that long as the first thing under the heading
    # buries the two or three anybody is actually planning around. Nested
    # <details>, so this needs no more script than the panel it sits in, and
    # every date in it is still a real link.
    later = ahead[LIST_COUNT:]
    if later:
        rows.append(
            '<li class="ecl-rest"><details class="ecl-more-list">'
            f'<summary>More eclipses '
            f'<span class="ecl-what">{len(later)} to 2040</span></summary>'
            '<div class="ecl-panel ecl-panel-side">'
            '<ul>' + "".join(row(e) for e in later) + '</ul>'
            '</div></details></li>')
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
            "    e.preventDefault();\n"
            # One level at a time, the way escape works anywhere else: the
            # list of later eclipses closes first and leaves the panel it
            # opened out of still open.
            "    var more=d.querySelector('.ecl-more-list[open]');\n"
            "    var box=more||d;\n"
            "    box.open=false;\n"
            "    var s=box.querySelector('summary');if(s)s.focus();\n"
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

   It is also a fixed number of characters wide whatever the window, and the
   two kinds are different: 96 columns of one region for a solar eclipse, 128
   of the whole world for a lunar one. At a fixed 11px either would scroll
   sideways inside its own box on a narrow column, with half the map off the
   right-hand edge and nothing to say so.

   So the width is measured in characters, not pixels. The markup carries
   --colf, which is 1 / (columns x 0.62em), and the font size is that many
   times the container's own width: a multiplication by a plain number,
   which every engine accepts. The first version divided by a parenthesised
   product -- calc(100cqw / (var(--cols) * 0.62)) -- and division by
   anything but a literal number is where calc() support actually stops, so
   the whole declaration was thrown away and the map went back to a fixed
   11px and a scrollbar.

   The clamp keeps it legible at the bottom and stops the 96-column map
   growing to fill a very wide screen at the top. Browsers with no container
   queries at all fall back to the 11px everything else here is drawn at,
   and keep the scrollbar as the safety net. */
/* Same small section label as "THE SAME NIGHT" in the left column, so the
   two columns mark their sections the same way. The space above it is what
   separates the map from the drawing over it; below it, almost none, because
   the label belongs to the map. */
.ecl-maptitle{color:#8fb6e0;font-size:11px;letter-spacing:.09em;
  text-transform:uppercase;margin:1.1rem 0 .45rem}
/* A little more air than the map's own label: what it separates is two
   blocks of text rather than a label from the thing it names. */
.ecl-prose-title{margin-top:1.4rem}
/* The column itself is the container. There was a wrapper div here doing
   nothing else, and a box inside a box is a box whose width you have to
   reason about twice -- the map was being sized against a width that was
   not quite the width it had to fit into. A container query cannot measure
   the element it sizes, so one ancestor has to volunteer, and the column is
   the honest choice: it is what the map has to fit inside. Safe to contain:
   it is a 1fr grid item, so its width comes from the grid rather than from
   what is in it. */
.obj-live{container-type:inline-size}
/* Written as ".obj-live pre.ecl-map", not ".ecl-map", and that is the whole
   fix. The div this map sits in carries

       .obj-static pre,.obj-live pre { overflow-x:auto }

   which is a class and an element, (0,1,1). A bare .ecl-map is (0,1,0) and
   loses, so every attempt to turn that overflow off from here was discarded
   before it reached the browser -- and the scrollbar it produces appears
   whenever a box is a hair narrower than what is inside it, which is what
   was under a map that looked perfectly complete.
   
   There is nothing to scroll: the map is sized to fit its column. So it
   takes the width of its own content and does not offer. */
.obj-live pre.ecl-map{line-height:1.0;font-variant-ligatures:none;
  overflow:visible;width:max-content;margin:0 0 2px;
  font-size:clamp(5.5px,calc(100cqw * var(--colf,0.0158)),12px)}
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
/* The rest of the table, opening to the right of the list it belongs to.
   A nested <details>, so it costs no script: the outer panel is already a
   disclosure and this is the same trick one level down. */
.ecl-rest{border-top:1px solid #21262d;margin-top:5px;padding-top:6px}
/* Deliberately NOT position:relative. The panel this opens has to be
   measured against the panel it comes out of, not against the row it hangs
   off: relative here made "100% of the width" mean the row's width, which
   is the panel minus its padding, so the second panel opened 17px inside
   the first one and covered its right-hand edge. */
.ecl-more-list summary{cursor:pointer;color:#c9d1d9;list-style:none;
  display:flex;align-items:baseline;gap:8px}
.ecl-more-list summary::-webkit-details-marker{display:none}
/* A plain > rather than a CSS escape. This block is a Python string, so
   "\\203a" was read as an octal escape and a letter a, and the arrow shipped
   as a stray control character followed by "a". */
.ecl-more-list summary::after{content:">";color:#6e7681;margin-left:auto}
.ecl-more-list summary:hover{color:#87d7ff}
/* Beside the first panel and level with its top, not hanging off the row
   that opens it: the list is long, and starting it at the bottom of the
   first panel put most of it below the fold. Clear of the first panel
   horizontally too, hence 100% of the panel rather than of the row. */
.ecl-panel-side{top:0;left:calc(100% + 7px);max-height:min(62vh,520px);
  overflow-y:auto}
/* Off the right of the screen on a narrow window, so it comes back to the
   near side there. */
@media (max-width:900px){
  .ecl-panel-side{left:auto;right:calc(100% + 7px)}
}
.ecl-picker ul{list-style:none;margin:0;padding:8px 12px}
.ecl-picker li{padding:3px 0;font-size:13px;white-space:nowrap}
.ecl-picker li a{color:#87d7ff}
.ecl-key{color:#6e7681;font-size:11px;margin:0;padding:5px 12px 9px;
  border-top:1px solid #21262d;line-height:1.6}
/* Direct children only. Without the >, the glyph inside each line is a
   block too and sits on a line of its own above the words it labels. */
.ecl-key > span{display:block;white-space:nowrap}
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
/* Top left, opposite the clock: what the height of the arc means. */
.ecl-scale{position:absolute;top:9px;left:12px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12px;color:#6e7681}
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
    # A lunar eclipse has no path at all. Its map answers the only question
    # that varies from place to place: is the Moon up for it.
    if "lunar" in kind:
        return "Where the Moon is up for it"
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
    elif not is_solar(f):
        # Minutes, not seconds: a total lunar eclipse runs for an hour or
        # more, where a total solar one is over in two.
        if f.get("kind") == "total" and f.get("duration_s"):
            cells.append('<div><span class="k">totality</span>'
                         f'<span class="v">{f["duration_s"] / 60:.0f}m</span>'
                         '</div>')
        elif f.get("um_mag", 0) > 0:
            cells.append('<div><span class="k">in shadow</span>'
                         f'<span class="v">{f["um_mag"] * 100:.0f}%</span></div>')
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
            # The arc is drawn to the height the Moon actually reaches that
            # night, not to 90 degrees: an eclipse peaking at 12 degrees on a
            # 90-degree axis is a flat line. That makes the height a shape
            # rather than a reading, so the scale is stated.
            + (f'<span class="ecl-scale">peaks at '
               f'{f["peak_alt"]:.0f}&deg;</span>'
               if not is_solar(f) and (f.get("peak_alt") or 0) > 0 else "")
            # Controls in the frame's bottom right, next to nothing else, so
            # they read as belonging to the picture. Plain text, no button
            # chrome: white rounded rectangles sitting on the drawing looked
            # like a video player had been dropped on top of it. Hidden until
            # the script runs -- without JS the frame is a still of first
            # contact and there is nothing for them to do.
            + '<span class="ecl-controls" id="ecl-controls" hidden>'
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
        # The column count goes into the markup, because the stylesheet
        # cannot count characters and the two maps are different widths: a
        # solar one is 96 columns of one region, a lunar one 128 of the whole
        # world. Hard-coding a font size for one of them made the other
        # either scroll sideways or sit in a third of its column.
        cols = max(len(_ANSI.sub("", r)) for r in map_rows)
        # 0.66em per glyph. The advance in the fonts on offer is 0.60 (SF
        # Mono), 0.602 (Menlo) or 0.55 (Consolas), so this is deliberately
        # generous: sized to exactly the column, the map came out a pixel or
        # two over and the box grew a scrollbar under a map that looked
        # perfectly complete.
        colf = 1.0 / (cols * 0.66)
        out.append(f'<pre class="ecl-map" style="--colf:{colf:.5f}">'
                   f'{ansi_to_html(chr(10).join(map_rows))}</pre>')
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
            body = "Sun" if is_solar(f) else "Moon"
            out.append(f"  * after the {body} has set from here")
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


def card_lines(entry, f=None):
    """(kicker, headline, detail) for the social card.

    Two versions, because a card is fetched once by a crawler in a
    datacentre and then shown to everybody. With a place it is that place's
    answer, which is the whole reason to click a link about an eclipse. With
    no place it says what the eclipse is and where it goes, and names nobody
    -- rather than quietly reporting what an unfurling bot in Virginia would
    have seen.
    """
    when = dt.datetime.fromisoformat(entry["when_utc"])
    date = when.strftime("%d %B %Y").lstrip("0")
    kicker = f"{entry['type']} eclipse".upper()
    if f is None or not f.get("computed"):
        # Not .capitalize(), which lowercases everything after the first
        # letter and turned "the Arctic, Greenland, Iceland and northern
        # Spain" into a sentence with no proper nouns left in it.
        regions = entry["regions"]
        return kicker, date, regions[:1].upper() + regions[1:]
    detail = "   ".join(f"{m['label']} {m['clock']}"
                        for m in f.get("timeline", []))
    return f"{kicker}  {date}".upper(), headline(f), detail


def card_art(f, disc, map_rows):
    """Which drawing the card leads with.

    The disc where there is one: a corona or a copper Moon is a picture, and
    it is the picture of the thing itself. Where the eclipse is not visible
    from here there is no disc to draw -- that is exactly what an empty disc
    means -- so the map takes over, because "not from here, but from there"
    is the useful thing to say instead.
    """
    return disc if disc else (map_rows or [])
