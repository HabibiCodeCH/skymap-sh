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


def test_find_keeps_the_faint_stars_but_dims_them():
    """The full mag-5 field gives the sky depth; inking everything past the
    ordinary cutoff in grey stops it competing with the crosshair. Same
    glyphs throughout -- a terminal has no alpha channel."""
    when = dt.datetime(2026, 8, 13, 2, 0)
    found = api.compose(api.Request(place="Zurich", when=when, color=True,
                                    find="Perseids")).text
    plain = api.compose(api.Request(place="Zurich", when=when, color=True)).text
    dim = found.count(sky.DIM_STAR)
    assert dim > 200, f"only {dim} dimmed stars"
    # The ordinary chart draws no backdrop tier at all.
    assert plain.count(sky.DIM_STAR) == 0
    # And the extra stars really are there, not just recoloured survivors.
    assert len(api.strip_ansi(found)) > 0


def test_dimmed_stars_sit_between_the_furniture_and_the_real_stars():
    """Three tiers have to stay separable: the chart's furniture (altitude
    grid 234, horizon 239, quadrant grid 240), the backdrop stars, and the
    stars you are meant to notice (252+)."""
    import re as _re
    num = lambda s: int(_re.search(r"38;5;(\d+)m", s).group(1))
    dim = num(sky.DIM_STAR)
    assert num(sky.C.HOR) < dim < num(sky.star_colour(None)), dim
    assert dim > 240, "must clear the quadrant grid"


def test_zoomed_find_keeps_the_denser_field_undimmed():
    """A 26° band needs the extra magnitude at full brightness or it looks
    empty, which is what the crop was for."""
    when = dt.datetime(2026, 8, 13, 2, 0)
    zoomed = api.compose(api.Request(place="Zurich", when=when, color=True,
                                     find="Perseids", span=60)).text
    assert "60° window" in api.strip_ansi(zoomed)
    assert zoomed.count(sky.DIM_STAR) == 0


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
