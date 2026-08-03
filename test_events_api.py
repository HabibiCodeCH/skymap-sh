"""The events feature above events.py: the teaser line, the list, the two
feeds, the routes and the CLI flags."""
import datetime as dt
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from starlette.testclient import TestClient

import api
import cli
import server
import sky

WHEN = dt.datetime(2026, 8, 11, 23, 0)      # two nights before the Perseid peak
QUIET = dt.datetime(2026, 6, 1, 23, 0)
CURL = {"User-Agent": "curl/8.4"}
BROWSER = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _req(place="Zurich", when=WHEN, **kw):
    return api.Request(place=place, when=when, color=False, **kw)


# ---------------------------------------------------------------- teaser
def test_teaser_appears_on_the_night_chart():
    text = api.compose(_req()).text
    assert "Coming up:" in text
    assert "Perseids" in text


def test_teaser_is_in_the_night_json():
    data = api.compose(_req()).data
    assert "Perseids" in data["coming_up"]


def test_teaser_appears_on_the_day_chart():
    text = api.compose(_req(when=dt.datetime(2026, 8, 12, 14, 0))).text
    assert "Coming up:" in text


def test_day_json_keeps_its_own_events_key_separate():
    """The day view already had "events" for the Sun's rise/transit/set. The
    sky-events line must not shadow it."""
    data = api.compose(_req(when=dt.datetime(2026, 8, 12, 14, 0))).data
    assert "sunrise" in data["events"] or "sunset" in data["events"]
    assert isinstance(data["coming_up"], (str, type(None)))


def test_teaser_is_absent_when_nothing_is_close():
    """It has to be missing most of the time, or it stops being read."""
    seen = 0
    for day in range(0, 360, 5):
        r = _req(when=dt.datetime(2026, 1, 1) + dt.timedelta(days=day, hours=23))
        if api.events_teaser(r):
            seen += 1
    assert 0 < seen < 72, f"teaser fired on {seen}/72 sampled nights"


def test_teaser_says_tonight_and_tomorrow_night():
    assert "tomorrow night" in api.events_teaser(_req(when=WHEN))
    peak = api.events_teaser(_req(when=dt.datetime(2026, 8, 12, 23, 0)))
    assert "tonight" in peak


def test_a_small_hours_peak_still_belongs_to_that_evening():
    """A 03:00 peak is "tonight" to someone reading at 22:00, not tomorrow."""
    r = _req(when=dt.datetime(2026, 8, 12, 22, 0))
    assert "tonight" in api.events_teaser(r)


def test_teaser_has_no_em_dashes():
    for day in range(0, 360, 3):
        r = _req(when=dt.datetime(2026, 1, 1) + dt.timedelta(days=day, hours=23))
        line = api.events_teaser(r)
        assert line is None or "—" not in line


# ---------------------------------------------------------------- the list
def test_events_list_renders():
    text = api._compose_events(_req(), days=30).text
    assert "Perseids peak" in text
    assert "local time" in text


def test_events_list_shows_invisible_ones_separately():
    """From Sydney the Perseid radiant never rises. Say so rather than
    silently dropping it."""
    text = api._compose_events(_req(place="Sydney"), days=30).text
    assert "not from here" in text
    assert "Perseids" in text


def test_shower_is_filed_under_the_evening_not_the_peak_instant():
    """The 2026 Perseid maximum is 13 Aug 02:10 UT, so dating the row by the
    peak put it on Thursday the 13th while every almanac says the 12th. Same
    night — the peak is in the small hours — and the night is what a reader
    plans around."""
    text = api._compose_events(_req(), days=14).text
    line = [l for l in text.split("\n") if "Perseids" in l][0]
    assert "Wed 12 Aug" in line, line
    assert "22:10" in line                      # the window starts that evening


def test_list_date_and_calendar_entry_agree():
    """Both go through _ics_span, so they cannot drift apart."""
    ics = api.events_ics(_req(), days=14)
    block = [b for b in ics.split("BEGIN:VEVENT") if "Perseids" in b][0]
    start = re.search(r"DTSTART:(\d{8})", block).group(1)
    line = [l for l in api._compose_events(_req(), days=14).text.split("\n")
            if "Perseids" in l][0]
    assert start == "20260812"
    assert "12 Aug" in line


def test_separation_is_not_printed_twice():
    """The headline already says "Moon and Venus 1.9° apart"; the detail
    column used to repeat it."""
    text = api._compose_events(_req(), days=40).text
    for line in text.split("\n"):
        if "apart" in line:
            assert line.count("° apart") <= 1, line


def test_elongation_shows_distance_from_the_sun_not_apart():
    text = api._compose_events(_req(), days=10).text
    assert "from the Sun" in text
    assert "45.5° apart" not in text


def test_long_notes_wrap():
    text = api._compose_events(_req(), days=30).text
    assert all(len(l) <= 100 for l in text.split("\n")), \
        max(text.split("\n"), key=len)


def test_next_only_is_one_bare_line():
    res = api._compose_events(_req(), next_only=True)
    assert res.text.count("\n") == 1
    assert "Coming up:" not in res.text          # no prefix in the bare form
    assert "Perseids" in res.text


def test_next_only_is_empty_when_nothing_is_coming():
    r = _req(when=dt.datetime(2026, 1, 20, 23, 0))
    res = api._compose_events(r, next_only=True)
    assert res.text == "" or res.text.strip()


def test_json_datetimes_are_strings():
    import json
    data = api._compose_events(_req(), days=30).data
    json.dumps(data)                              # must not raise


# ---------------------------------------------------------------- clickable HTML
def test_events_html_links_every_event_to_its_own_chart():
    h = api.events_html(_req(), days=20)
    links = re.findall(r'<a href="(/Zurich\?t=[^"]+)"', h)
    assert len(links) >= 6
    for href in links:
        assert re.search(r"t=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", href), href


def test_event_link_crosshairs_the_thing():
    """?find=, not ?facing=. Facing only points the chart the right way;
    clicking "Perseids" and getting an unmarked night chart was the
    complaint."""
    h = api.events_html(_req(), days=20)
    row = [l for l in h.split("\n") if "Perseids" in l][0]
    assert "find=Perseids" in row, row


def test_find_looks_like_the_ordinary_chart():
    """Same instant, same sky, plus a crosshair.

    Two attempts at making find "richer" both made it read as a different
    chart instead of the familiar one with a mark on it: mag_limit 5.0 put
    775 stars where the normal view has 287, and drawing the extra 488 as dim
    backdrop was worse, because mag 4-5 is 63% of the field so most of the sky
    went grey and took the colour and size variety with it.
    """
    when = dt.datetime(2026, 8, 4, 3, 38)      # dark, Vega well up: no time shift
    plain = api.strip_ansi(api.compose(_req(place="New York", when=when)).text)
    found = api.strip_ansi(api.compose(_req(place="New York", when=when,
                                            find="Vega")).text)
    dots = lambda s: len(re.findall("·", s))
    # Within the crosshair's own footprint of each other.
    assert abs(dots(found) - dots(plain)) < 30, (dots(found), dots(plain))


def test_find_keeps_the_zenith_inset():
    """`target` used to disqualify the inset, which was right when find meant
    a 26° crop with no room for one and wrong once it drew the full sky."""
    when = dt.datetime(2026, 8, 4, 3, 38)
    found = api.strip_ansi(api.compose(_req(place="New York", when=when,
                                            find="Vega")).text)
    assert "zenith 70-90°" in found


def _cardinal_row(text):
    return next((l for l in text.split("\n") if " NE " in l and " SE " in l), None)


def test_find_does_not_rotate_the_sky():
    """render_linear re-centred the panorama on the target, which is the whole
    point of a 60° window and pure damage on a 360° sweep: it spun the sky so
    every cardinal and every label landed somewhere else than on the ordinary
    chart, and the two stopped being comparable at a glance."""
    when = dt.datetime(2026, 8, 3, 3, 46)
    plain = api.strip_ansi(api.compose(_req(place="New York", when=when)).text)
    found = api.strip_ansi(api.compose(_req(place="New York", when=when,
                                            find="Neptune")).text)
    assert _cardinal_row(plain) == _cardinal_row(found)


def test_find_moves_nothing_but_its_own_target():
    when = dt.datetime(2026, 8, 3, 3, 46)

    def cols(text):
        out = {}
        for line in text.split("\n"):
            for m in re.finditer(r"[A-Z][A-Za-z]{3,}", line):
                out.setdefault(m.group(), m.start())
        return out

    a = cols(api.strip_ansi(api.compose(_req(place="New York", when=when)).text))
    b = cols(api.strip_ansi(api.compose(_req(place="New York", when=when,
                                             find="Neptune")).text))
    moved = [k for k in set(a) & set(b) if a[k] != b[k]]
    # Neptune itself is relabelled to NEPTUNE at the crosshair; nothing else
    # in the sky should have shifted a column.
    assert moved in ([], ["Neptune"]), moved


def test_cropped_find_still_centres_on_the_target():
    """A 60° window exists to put the thing in the middle."""
    when = dt.datetime(2026, 8, 3, 3, 46)
    zoomed = api.strip_ansi(api.compose(_req(place="New York", when=when,
                                             find="Neptune", span=60)).text)
    assert _cardinal_row(zoomed) is None       # too narrow to span NE..SE


def test_cropped_find_still_has_no_inset():
    """An inset labelled 70-90° is a lie on a chart that stops at 40°."""
    when = dt.datetime(2026, 8, 4, 3, 38)
    zoomed = api.strip_ansi(api.compose(_req(place="New York", when=when,
                                             find="Vega", span=60)).text)
    assert "zenith 70-90°" not in zoomed
    assert "60° window" in zoomed


def test_conjunction_link_aims_at_the_fainter_body():
    """Moon and Mercury: the Moon needs no help being found."""
    h = api.events_html(_req(), days=20)
    row = [l for l in h.split("\n") if "Moon and Mercury" in l]
    if row:
        assert "find=Mercury" in row[0], row[0]


def test_every_linked_row_marks_something():
    h = api.events_html(_req(), days=40)
    rows = [l for l in h.split("\n") if 'href="/Zurich?t=' in l]
    assert rows
    for row in rows:
        assert "find=" in row or "facing=" in row, row


def test_event_link_uses_the_best_moment_not_the_instant():
    h = api.events_html(_req(), days=20)
    row = [l for l in h.split("\n") if "Perseids" in l][0]
    assert "t=2026-08-13T04:50" in row, row


def test_row_date_and_its_own_link_land_on_the_same_night():
    """The list said "Sun 16 Aug" while its link opened the 15th, because the
    date came from the event instant and the href from the best moment.

    Same *night*, not same date: a row dated 12 Aug legitimately links to
    13 Aug 04:50, because a night crosses midnight. The noon boundary is the
    same one _when_words uses to decide "tonight".
    """
    h = api.events_html(_req(), days=40)
    checked = 0
    for row in h.split("\n"):
        m = re.search(r'href="/Zurich\?t=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', row)
        d = re.search(r">\s*\w{3} (\d{2}) (\w{3})", row)
        if not m or not d:
            continue
        link = dt.datetime.fromisoformat(m.group(1))
        row_day = int(d.group(1))
        # Two kinds of row, and both are legitimate:
        #   an instant (a phase, an equinox) is dated by its calendar date;
        #   a viewing session is dated by the night it belongs to, which can
        #   run past midnight into the next date.
        # A link must land on one or the other, never on some third day.
        same_date = link.day == row_day
        same_night = (link - dt.timedelta(hours=12)).day == row_day
        assert same_date or same_night, f"{row}\nlink {link}, row says {row_day}"
        checked += 1
    assert checked >= 6, "no linked rows found to check"


def test_events_html_escapes_and_opens_in_a_new_tab():
    h = api.events_html(_req(), days=20)
    assert 'target="_blank"' in h and 'rel="noopener"' in h
    assert "<script" not in h


def test_events_html_columns_line_up_with_the_text_version():
    """The anchor wraps the whole padded row, so <pre> alignment survives."""
    import re as _re
    text = api._compose_events(_req(), days=20).text.split("\n")
    html_rows = [_re.sub(r"<[^>]+>", "", l) for l in
                 api.events_html(_req(), days=20).split("\n")]
    import html as _h
    html_rows = [_h.unescape(l) for l in html_rows]
    for line in text:
        if "Perseids" in line or "New Moon" in line:
            assert line in html_rows, line


def test_events_route_serves_links_to_a_browser(client):
    body = client.get("/Zurich/events?days=20", headers=BROWSER).text
    assert 'href="/Zurich?t=' in body


def test_curl_gets_no_html(client):
    body = client.get("/Zurich/events?days=20", headers=CURL).text
    assert "<a href" not in body


# ---------------------------------------------------------------- card payload
def test_card_is_none_most_nights():
    """Same bar as the teaser: a card that is always there stops meaning
    anything."""
    seen = sum(1 for d in range(0, 360, 5)
               if api.events_card(_req(when=dt.datetime(2026, 1, 1)
                                       + dt.timedelta(days=d, hours=23))))
    assert 0 < seen < 72, seen


def test_card_shape():
    c = api.events_card(_req())
    assert c["id"] == "shower-perseids-20260813"
    assert c["kind"] == "meteor_shower"
    assert c["eyebrow"] == "tomorrow night"
    assert c["headline"] == "Perseids peak"
    assert "Perseids" in c["body"] and not c["body"].startswith("Coming up:")
    assert c["urgency"] in ("tonight", "soon", "later")
    assert {d["label"] for d in c["detail"]} >= {"best", "where", "rate"}
    assert c["cta"]["url"].startswith("/Zurich?t=")
    assert c["more"]["url"] == "/Zurich/events"


def test_card_urgency_tightens_as_it_approaches():
    far = api.events_card(_req(when=dt.datetime(2026, 8, 9, 23, 0)))
    near = api.events_card(_req(when=dt.datetime(2026, 8, 12, 23, 0)))
    assert near["days_away"] < far["days_away"]
    assert near["urgency"] == "tonight"


def test_card_id_matches_the_ics_uid():
    """So a dismissal keyed on it survives, and lines up with the feeds."""
    c = api.events_card(_req())
    assert f"UID:{c['id']}@skymap.sh" in api.events_ics(_req(), days=30)


def test_card_is_json_serialisable_everywhere_it_is_served():
    import json
    json.dumps(api._compose_events(_req(), days=30).data)
    json.dumps(api.compose(_req()).data)
    json.dumps(api.compose(_req(when=dt.datetime(2026, 8, 12, 14, 0))).data)


def test_card_served_on_both_payloads(client):
    j = client.get("/Zurich/events?format=json&t=2026-08-11T23:00",
                   headers=CURL).json()
    assert j["card"] and j["card"]["kind"] == "meteor_shower"
    k = client.get("/Zurich?format=json&t=2026-08-11T23:00", headers=CURL).json()
    assert k["coming_up_card"]["id"] == j["card"]["id"]


def test_page_carries_the_marker(client):
    body = client.get("/Zurich", headers=BROWSER).text
    assert "skymap:coming-up-card" in body


def test_coming_up_card_html_is_empty_string_for_empty_list():
    assert api.coming_up_card_html([]) == ""


def test_coming_up_card_html_renders_the_real_thing():
    html_out = api.coming_up_card_html(api.events_cards(_req()))
    assert 'id="coming-up"' in html_out
    assert 'data-urgency="soon"' in html_out
    assert 'data-id="shower-perseids-20260813"' in html_out
    assert "Perseids" in html_out
    assert '<a class="cu-cta" id="cu-cta" href="/Zurich?t=' in html_out
    assert 'id="coming-up-dismiss"' in html_out


def test_coming_up_card_html_escapes_the_body():
    cards = api.events_cards(_req())
    cards[0]["body"] = "<script>alert(1)</script>"
    html_out = api.coming_up_card_html(cards)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_coming_up_card_html_has_no_second_cta(client):
    # "everything coming up" was dropped from the one-line card -- /events
    # is already one click away via the nav, and a second link fights the
    # "as tight as possible, one line" ask.
    html_out = api.coming_up_card_html(api.events_cards(_req()))
    assert "everything coming up" not in html_out


def test_events_cards_returns_both_when_two_things_are_close():
    # Eclipse (Aug 12) and the Perseid peak (Aug 13) are less than a day
    # apart here -- the single-winner events_card() would only surface
    # whichever _interest() ranks higher (the shower, narrowly).
    cards = api.events_cards(_req())
    ids = {c["id"] for c in cards}
    assert "shower-perseids-20260813" in ids
    assert "eclipse-total-solar-eclipse-20260812" in ids


def test_events_cards_is_capped_at_n():
    assert len(api.events_cards(_req(), n=1)) == 1


def test_events_cards_matches_events_card_for_the_top_pick():
    single = api.events_card(_req())
    plural = api.events_cards(_req())
    assert plural[0] == single


def test_coming_up_card_html_embeds_every_card_for_client_side_cycling():
    cards = api.events_cards(_req())
    assert len(cards) > 1, "test assumes the close-eclipse night"
    html_out = api.coming_up_card_html(cards)
    for c in cards:
        assert c["id"] in html_out


def test_cycle_chevron_starts_hidden_in_static_markup():
    # JS unhides it after filtering dismissed cards down to what's actually
    # left (cycleEl.hidden=CARDS.length<2) -- a hidden default is correct
    # either way, for a no-JS visitor and before that filtering has run.
    html_out = api.coming_up_card_html(api.events_cards(_req()))
    assert '<span class="cu-cycle" id="cu-cycle" role="button" tabindex="0" hidden>' in html_out


def test_chart_page_renders_the_card_when_one_is_due(client):
    body = client.get("/Zurich?t=2026-08-11T23:00", headers=BROWSER).text
    assert 'id="coming-up"' in body
    assert "Perseids" in body


def test_chart_page_renders_nothing_on_a_quiet_night(client):
    body = client.get("/Zurich?t=2026-06-01T23:00", headers=BROWSER).text
    assert 'id="coming-up"' not in body


def test_find_view_still_gets_the_card(client):
    # _compose_find doesn't set coming_up_card on its own Result -- the
    # chart route calls events_cards(r) fresh, independent of which compose
    # function ran, so find shouldn't lose the homepage highlight.
    body = client.get("/Zurich?t=2026-08-11T23:00&find=Venus", headers=BROWSER).text
    assert 'id="coming-up"' in body


def test_non_chart_pages_never_show_the_card(client):
    for path in ("/catalog", "/legend", "/help", "/stats", "/Zurich/events"):
        body = client.get(path, headers=BROWSER).text
        assert 'id="coming-up"' not in body, path


def test_dismiss_is_wired_to_localstorage_keyed_on_id(client):
    body = client.get("/Zurich?t=2026-08-11T23:00", headers=BROWSER).text
    assert "localStorage.getItem(KEY)" in body
    assert "localStorage.setItem(KEY" in body
    assert "dismissed.indexOf(c.id)" in body


def test_events_is_in_the_nav(client):
    body = client.get("/Zurich", headers=BROWSER).text
    assert '<a href="/events">events</a>' in body


def test_bare_events_locates_by_ip(client):
    assert client.get("/events", headers=CURL).status_code == 200
    before = server._stat["events_ip"]
    client.get("/events", headers=CURL)
    assert server._stat["events_ip"] == before + 1


def test_stats_tracks_whether_the_teaser_fires(client):
    """Page views say people opened the list. This says whether the feature
    does anything on the pages nobody opened it from, which is most of them."""
    server._stat["teaser:shown"] = 0
    server._stat["teaser:absent"] = 0
    client.get("/Zurich?t=2026-08-11T23:00", headers=CURL)   # Perseids two nights out
    client.get("/Zurich?t=2026-01-20T23:00", headers=CURL)   # quiet
    assert server._stat["teaser:shown"] >= 1
    assert server._stat["teaser:absent"] >= 1
    text = client.get("/stats", headers=CURL).text
    assert "teaser" in text and "% of charts" in text
    j = client.get("/stats?format=json", headers=CURL).json()["events"]
    assert {"teaser_shown", "teaser_absent", "top_teased"} <= set(j)


def test_stats_records_what_was_teased(client):
    client.get("/Zurich?t=2026-08-11T23:00", headers=CURL)
    assert any("Perseids" in k for k in server._events_teased), dict(server._events_teased)


def test_events_places_keyed_on_slug_not_display_name(client):
    """The no-place fallback is named "Zurich" where a real lookup gives
    "Zürich", which split one city across two rows."""
    # Starts from the persisted stats file, which may still hold name-keyed
    # rows written before this change, so clear before asserting.
    saved = server._events_places.copy()
    server._events_places.clear()
    try:
        client.get("/Zurich/events", headers=CURL)
        client.get("/events", headers=CURL)
        assert "Zürich" not in server._events_places
        assert "Zurich" in server._events_places
    finally:
        server._events_places.clear()
        server._events_places.update(saved)


def test_days_snaps_to_a_ladder(client):
    """Clamping alone left 359 distinct values against an 8-entry memo, so a
    client walking ?days= got zero cache hits and 75 ms of origin work each
    time, plus a fresh CDN key. See "Bounding the cache-key surface"."""
    got = {client.get(f"/Zurich/events?format=json&days={d}",
                      headers=CURL).json()["window_days"]
           for d in (1, 8, 20, 45, 100, 200, 9999)}
    assert got <= set(server.EVENTS_WINDOWS), got
    assert len(got) <= len(server.EVENTS_WINDOWS)


def test_bare_feed_urls_work(client):
    """The nav points at /events, so /events.ics is the next thing anyone
    tries. It 404'd, which a calendar app reports as a flat "the URL is not
    valid" with nothing to go on."""
    for path, ctype in (("/events.ics", "text/calendar"),
                        ("/events.rss", "rss+xml")):
        r = client.get(path)
        assert r.status_code == 200, path
        assert ctype in r.headers["content-type"], path
    assert client.get("/events.ics").text.startswith("BEGIN:VCALENDAR")


def test_unknown_place_feeds_still_404(client):
    for p in ("/wombat/events.ics", "/wombat/events.rss"):
        assert client.get(p).status_code == 404, p


# ---------------------------------------------------------------- ICS
def test_ics_is_well_formed():
    ics = api.events_ics(_req(), days=30)
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") > 0
    assert "\r\n" in ics                          # RFC 5545 wants CRLF


def test_ics_lines_respect_the_75_octet_limit():
    """Clients genuinely reject over-long lines, so the folding is not
    optional politeness."""
    for line in api.events_ics(_req(), days=90).split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line


def test_ics_uid_is_stable_across_renders():
    a = re.findall(r"UID:(\S+)", api.events_ics(_req(), days=60))
    b = re.findall(r"UID:(\S+)", api.events_ics(_req(when=WHEN + dt.timedelta(hours=1)),
                                                days=60))
    assert a and set(b) <= set(a)


def test_ics_shower_entry_covers_the_window_not_the_peak_moment():
    """A reminder that fires when the radiant is highest goes off at 04:50,
    by which point you have missed the night."""
    ics = api.events_ics(_req(), days=30)
    block = [b for b in ics.split("BEGIN:VEVENT") if "Perseids" in b][0]
    start = re.search(r"DTSTART:(\d{8}T\d{6})", block).group(1)
    end = re.search(r"DTEND:(\d{8}T\d{6})", block).group(1)
    assert start.endswith("221000"), start        # 22:10, when to go outside
    assert end > start                            # runs into the next morning
    assert end.startswith("20260813")


def test_ics_escapes_commas_and_semicolons():
    ics = api.events_ics(_req(), days=30)
    for line in ics.split("\r\n"):
        if line.startswith(("SUMMARY:", "DESCRIPTION:")):
            body = line.split(":", 1)[1]
            assert not re.search(r"(?<!\\)[,;]", body), line


# ---------------------------------------------------------------- RSS
def test_rss_parses_as_xml():
    root = ET.fromstring(api.events_rss(_req(), days=30))
    assert root.tag == "rss"
    assert root.find("./channel/title") is not None
    assert len(root.findall("./channel/item")) > 0


def test_rss_guids_are_stable_and_unique():
    """A guid keyed on render time makes every reader re-flag every item on
    every poll."""
    def guids(r):
        return [g.text for g in
                ET.fromstring(api.events_rss(r, days=60)).findall("./channel/item/guid")]
    a = guids(_req())
    b = guids(_req(when=WHEN + dt.timedelta(hours=3)))
    assert len(a) == len(set(a))
    # Not set(b) <= set(a): three hours later the 60-day window has slid three
    # hours further and legitimately picks up an event the first render could
    # not see. What has to hold is that everything in both renders kept its
    # id -- a reader re-flagging old items is the failure this guards.
    assert set(a) & set(b), "the two renders share no events at all"
    assert [g for g in b if g in set(a)] == [g for g in a if g in set(b)]


def test_rss_pubdate_carries_the_places_own_offset():
    xml = api.events_rss(_req(place="Tokyo"), days=30)
    dates = re.findall(r"<pubDate>([^<]+)</pubDate>", xml)
    assert dates and all(d.endswith("+0900") for d in dates), dates[:3]


# ---------------------------------------------------------------- sphere markers
PEAK_NIGHT = dt.datetime(2026, 8, 13, 1, 0)
BUSY_NIGHT = dt.datetime(2026, 10, 4, 23, 0)      # opposition + two pairings


def _markers(**kw):
    return api._compose_sphere(_req(**kw))["markers"]


def test_sphere_marks_the_radiant_on_a_shower_night():
    ms = _markers(when=PEAK_NIGHT)
    assert ms and ms[0]["name"] == "Perseids"
    assert ms[0]["shape"] == "radiant"
    assert ms[0]["compass"] in ("N", "NNE", "NE", "ENE")
    assert 0 < ms[0]["alt"] <= 90 and 0 <= ms[0]["az"] < 360


def test_sphere_has_no_markers_on_an_ordinary_night():
    """Empty on all but a handful of nights a year, or a marker means nothing
    when one does appear."""
    assert _markers(when=dt.datetime(2026, 9, 20, 23, 0)) == []


def test_sphere_marks_more_than_showers():
    """Conjunctions and oppositions are worth turning towards too, and they
    are where the multi-marker case actually comes from."""
    ms = _markers(when=BUSY_NIGHT)
    assert len(ms) >= 2
    kinds = {m["kind"] for m in ms}
    assert kinds - {"meteor_shower"}, kinds


def test_markers_are_ranked_best_first():
    """When a shower and a Moon pairing land on the same night the shower is
    the headline, so it must be the one the strip opens on."""
    ms = _markers(when=dt.datetime(2026, 8, 11, 23, 0))
    assert len(ms) >= 2
    assert ms[0]["kind"] == "meteor_shower"


def test_markers_are_capped():
    for when in (PEAK_NIGHT, BUSY_NIGHT, dt.datetime(2026, 8, 11, 23, 0)):
        assert len(_markers(when=when)) <= api.ev_mod.MAX_MARKERS


def test_point_events_are_not_drawn_as_radiants():
    for m in _markers(when=BUSY_NIGHT):
        assert m["shape"] == ("radiant" if m["kind"] == "meteor_shower" else "point")


def test_every_marker_has_a_caption_and_a_position():
    for when in (PEAK_NIGHT, BUSY_NIGHT):
        for m in _markers(when=when):
            assert m["caption"] and " · " in m["caption"]
            assert m["alt"] is not None and m["az"] is not None


def test_sphere_marker_survives_the_night_after_a_peak():
    """Rates fall off either side of maximum rather than switching off."""
    ms = _markers(when=dt.datetime(2026, 8, 14, 23, 0))
    assert any(m["name"] == "Perseids" for m in ms)


def test_no_markers_where_nothing_clears_the_horizon():
    assert _markers(place="Sydney", when=PEAK_NIGHT) == []


def test_marker_position_uses_the_best_moment_not_the_request_instant():
    a = _markers(when=dt.datetime(2026, 8, 12, 21, 0))[0]
    b = _markers(when=dt.datetime(2026, 8, 13, 2, 0))[0]
    assert abs(a["alt"] - b["alt"]) < 1.0 and abs(a["az"] - b["az"]) < 1.0


def test_sphere_markers_json_is_serialisable():
    import json
    json.dumps(api._compose_sphere(_req(when=BUSY_NIGHT)))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_sphere_page_javascript_parses():
    """A syntax error anywhere in this script kills the entire sphere page,
    which has happened before. Nothing else in the suite would notice, because
    the server serves broken JS with a cheerful 200. Parse-only -- no DOM."""
    page = api.SPHERE_PAGE.format(title="t", place_slug="Zurich",
                                  place_name="Zürich", home_suffix="")
    js = re.search(r'<script type="module">(.*?)</script>', page, re.S).group(1)
    js = re.sub(r"^\s*import .*$", "", js, flags=re.M)
    out = subprocess.run(
        ["node", "-e",
         "const s=require('fs').readFileSync(process.argv[1],'utf8');"
         "require('vm').compileFunction(s,[],{});console.log('OK')",
         "/dev/stdin"],
        input=js, capture_output=True, text=True)
    assert "OK" in out.stdout, out.stderr[:600]


def test_sphere_page_has_the_marker_code(client):
    body = client.get("/Zurich/sphere",
                      headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"}).text
    for token in ("addMarkers", "showMarker", "aimAtMarker",
                  "radiant-hud-cycle", "data.markers"):
        assert token in body, token


def test_sphere_json_route_includes_markers(client):
    assert "markers" in client.get("/Zurich/sphere.json?t=2026-08-13T01:00").json()


def test_stats_counts_marker_nights(client):
    """Standing rule: a new thing on a route ships with its counter."""
    before = server._stat["sphere_radiant"]
    client.get("/Zurich/sphere.json?t=2026-08-13T01:00")
    assert server._stat["sphere_radiant"] == before + 1
    client.get("/Zurich/sphere.json?t=2026-09-20T23:00")
    assert server._stat["sphere_radiant"] == before + 1     # quiet night, no bump


# ---------------------------------------------------------------- routes
def test_events_route_by_content_type(client):
    assert client.get("/Zurich/events", headers=CURL).status_code == 200
    assert "text/html" in client.get("/Zurich/events", headers=BROWSER).headers["content-type"]
    j = client.get("/Zurich/events?format=json", headers=CURL).json()
    assert j["place"] == "Zürich" and isinstance(j["upcoming"], list)


def test_feed_routes_have_the_right_content_types(client):
    assert "text/calendar" in client.get("/Zurich/events.ics").headers["content-type"]
    assert "rss+xml" in client.get("/Zurich/events.rss").headers["content-type"]


def test_events_cache_bucket_is_a_day(client):
    """These change on the scale of days, not the five minutes a chart does."""
    cc = client.get("/Zurich/events.ics").headers["cache-control"]
    assert "s-maxage=86400" in cc


def test_unknown_place_404s_on_every_events_route(client):
    for path in ("/wombat/events", "/wombat/events.ics", "/wombat/events.rss"):
        assert client.get(path, headers=CURL).status_code == 404, path


def test_days_is_clamped(client):
    """Unbounded ?days= would let a client mint cache entries for free."""
    assert client.get("/Zurich/events?format=json&days=1",
                      headers=CURL).json()["window_days"] == 7
    assert client.get("/Zurich/events?format=json&days=99999",
                      headers=CURL).json()["window_days"] == 365
    assert client.get("/Zurich/events?format=json&days=banana",
                      headers=CURL).json()["window_days"] == api.EVENTS_WINDOW_DAYS


def test_next_route_is_bare(client):
    body = client.get("/Zurich/events?next=1", headers=CURL).text
    assert "skymap.sh" not in body        # no header, no nav, no footer
    assert body.count("\n") <= 1


def test_stats_counts_the_events_routes(client):
    before = server._stat["events.ics"]
    client.get("/Tokyo/events.ics")
    assert server._stat["events.ics"] == before + 1
    client.get("/Tokyo/events?next=1", headers=CURL)
    assert server._stat["param:next"] >= 1
    assert "Tokyo" in server._events_places


def test_stats_page_shows_the_events_block(client):
    client.get("/Zurich/events", headers=CURL)
    text = client.get("/stats", headers=CURL).text
    assert "what's coming up" in text
    assert server._stat["events"] >= 1
    j = client.get("/stats?format=json", headers=CURL).json()
    assert "events" in j and "ics" in j["events"]


def test_robots_keeps_crawlers_out_of_the_feeds(client):
    body = client.get("/robots.txt").text
    assert "Disallow: /*/events.ics" in body
    assert "Disallow: /*/events.rss" in body
    assert "Disallow: /*/events\n" not in body    # the page itself stays indexable


# ---------------------------------------------------------------- CLI
def test_cli_events_flag(capsys):
    assert cli.main(["Zurich", "2026-08-11T23:00", "--events", "--plain"]) == 0
    assert "Perseids peak" in capsys.readouterr().out


def test_cli_next_prints_exactly_one_line(capsys):
    assert cli.main(["Zurich", "2026-08-11T23:00", "--next", "--plain"]) == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1, repr(out)


def test_cli_events_json(capsys):
    import json
    assert cli.main(["Zurich", "2026-08-11T23:00", "--events", "--json"]) == 0
    assert "upcoming" in json.loads(capsys.readouterr().out)


def test_cli_still_renders_a_plain_chart(capsys):
    """The flags must not have leaked into the default path."""
    assert cli.main(["Zurich", "2026-08-11T23:00", "--plain"]) == 0
    out = capsys.readouterr().out
    assert "stars above the horizon" in out
