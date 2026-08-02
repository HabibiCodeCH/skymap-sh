#!/usr/bin/env python3
"""Tests for the browser vs. terminal ?animate= handling in server.py.

Run:  python3 test_server.py
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

from starlette.testclient import TestClient

import server

BROWSER = {"accept": "text/html", "user-agent": "Mozilla/5.0"}
TERMINAL = {"user-agent": "curl/8.0"}
MOBILE = {"accept": "text/html",
         "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"}


def setUpModule():
    # Every test class's TestClient resolves to the same fake IP, and
    # _buckets is one shared module-level dict -- cumulative requests across
    # this whole file (120+ tests) can exceed the real per-IP rate limit
    # within the file's own run time, failing unrelated later tests with a
    # 429 that has nothing to do with what they're actually testing. Rate
    # limiting is a production concern, not something test correctness
    # should depend on, so it's effectively disabled for this process only.
    server.RATE = 1_000_000
    server.BURST = 1_000_000


class AnimateBrowserVsTerminal(unittest.TestCase):
    def setUp(self):
        # TestClient only runs the app's @app.on_event("startup") handler
        # (which sets app.state.tle, needed by every route) inside its own
        # context manager -- enter it here and clean up after each test.
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_terminal_gets_the_raw_ansi_stream(self):
        # curl (and friends) still get the live text/plain stream this
        # endpoint always served -- ?animate= must not change shape for them.
        resp = self.client.get("/Ibiza?animate=24", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))

    def test_browser_gets_html_not_a_raw_stream(self):
        # A browser opening the same URL used to get the literal ANSI escape
        # codes printed as page text, because the animate branch ran before
        # mode detection. It must get a normal HTML page instead.
        resp = self.client.get("/Ibiza?animate=24", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))
        self.assertNotIn("\x1b[2J", resp.text)

    def test_browser_page_autoplays_when_animate_is_in_the_url(self):
        resp = self.client.get("/Ibiza?animate=24", headers=BROWSER)
        self.assertIn('id="animate-btn"', resp.text)
        self.assertIn("skymapAnimate(b)", resp.text)

    def test_plain_page_does_not_autoplay(self):
        resp = self.client.get("/Ibiza", headers=BROWSER)
        self.assertIn('id="animate-btn"', resp.text)
        self.assertNotIn("skymapAnimate(b)", resp.text)

    def test_animate_button_carries_the_requested_time(self):
        # The button (and the auto-played preview) must start from the same
        # moment the static chart above it is showing, not from real "now" --
        # otherwise a future ?t= link shows one time in the chart and
        # animates from another.
        resp = self.client.get("/Ibiza?t=2026-08-12T18:00&animate=24", headers=BROWSER)
        m = re.search(r'data-live-url="([^"]+)"', resp.text)
        self.assertIsNotNone(m)
        self.assertIn("t=2026-08-12T18:00", m.group(1))

    def test_terminal_gif_followup_carries_the_requested_time(self):
        # The streamed preview's own "Want a shareable GIF? Run: ..." command
        # used to drop t= entirely, built from place.slug alone -- so
        # copy-pasting it rendered from the real current moment instead of
        # whatever the preview just played from, silently (no error, just
        # the wrong GIF). animate=1 keeps this fast (4 frames, ~0.6s).
        resp = self.client.get("/Ibiza?t=2026-08-12T18:00&animate=1", headers=TERMINAL)
        self.assertIn("/Ibiza/animate.gif?t=2026-08-12T18:00", resp.text)


class StatsPagesInBrowser(unittest.TestCase):
    """/stats and /stats/hourly both wrap their plain-text body in api.PAGE
    for a browser -- every api.PAGE.format() call site has to supply every
    placeholder the template defines, or str.format() raises. Adding
    quadrant_btn to the template broke /stats specifically: its call site
    wasn't updated, so a browser hit a 500 (KeyError: 'quadrant_btn') while
    curl's plain-text response kept working, which is exactly why this
    needs its own test rather than relying on the terminal-mode checks."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_stats_renders_in_a_browser(self):
        resp = self.client.get("/stats", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))

    def test_stats_hourly_renders_in_a_browser(self):
        resp = self.client.get("/stats/hourly", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))

    def test_stats_hourly_json_and_terminal_modes_still_work(self):
        # The new html branch must not have disturbed the two modes that
        # already worked.
        resp = self.client.get("/stats/hourly?format=json", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))
        resp = self.client.get("/stats/hourly", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))


class BskyBotStatsOnStatsPage(unittest.TestCase):
    """bsky_bot.py runs as a separate process and hands off its tallies to
    /stats purely through the shared state file -- no shared memory, no HTTP
    call between them. This checks server.py's side of that handoff."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        self._orig = server.BSKY_STATE_FILE
        self.addCleanup(setattr, server, "BSKY_STATE_FILE", self._orig)
        fd, self._path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self._path) and os.remove(self._path))
        server.BSKY_STATE_FILE = self._path

    def _write_bsky_stats(self, stats):
        with open(self._path, "w") as f:
            json.dump({"last_seen": "2026-08-01T00:00:00.000Z", "stats": stats}, f)

    def test_missing_state_file_omits_the_section(self):
        os.remove(self._path)
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertNotIn("bluesky bot", resp.text)

    def test_present_stats_show_up_on_the_page(self):
        self._write_bsky_stats({"mentions": 5, "replies": 4, "unknown_place": 1})
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertIn("bluesky bot", resp.text)
        self.assertIn("mentions", resp.text)
        self.assertIn("5", resp.text)

    def test_present_stats_show_up_in_json(self):
        self._write_bsky_stats({"mentions": 2, "replies": 2})
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        self.assertEqual(resp.json()["bsky"], {"mentions": 2, "replies": 2})


class ParamCounters(unittest.TestCase):
    """Every request-shaping query parameter should show up in /stats, not
    just the handful that had counters from day one -- dso and quadrant
    shipped with none at all until this pass."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        # _stat is a module-level Counter shared across every test in the
        # process -- snapshot and restore so this test's assertions aren't
        # polluted by (or don't pollute) any other test's requests.
        self._orig_stat = server._stat.copy()
        server._stat.clear()
        self.addCleanup(lambda: (server._stat.clear(), server._stat.update(self._orig_stat)))

    def test_dso_and_quadrant_params_are_tallied(self):
        self.client.get("/Zurich?dso=1", headers=TERMINAL)
        self.client.get("/Zurich?quadrant=B", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        params = resp.json()["params"]
        self.assertEqual(params.get("dso"), 2)  # quadrant=B also switches dso on
        self.assertEqual(params.get("quadrant"), 1)

    def test_bare_quadrant_counts_as_quadrant_requested(self):
        self.client.get("/Zurich?quadrant", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        self.assertEqual(resp.json()["params"].get("quadrant"), 1)

    def test_night_nolines_and_width_params_are_tallied(self):
        self.client.get("/Zurich?night=1", headers=TERMINAL)
        self.client.get("/Zurich?nolines=1", headers=TERMINAL)
        self.client.get("/Zurich?w=100", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        params = resp.json()["params"]
        self.assertEqual(params.get("night"), 1)
        self.assertEqual(params.get("nolines"), 1)
        self.assertEqual(params.get("w"), 1)

    def test_plain_text_request_is_tallied(self):
        # ?plain= is what actually turns colour off for a terminal client --
        # curl gets ANSI colour by default even with Accept: text/plain.
        self.client.get("/Zurich?plain=1", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        self.assertEqual(resp.json()["params"].get("plain"), 1)

    def test_params_section_appears_on_the_text_page(self):
        self.client.get("/Zurich?dso=1", headers=TERMINAL)
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertIn("parameters", resp.text)
        self.assertIn("dso", resp.text)


class TopPlacesFormatting(unittest.TestCase):
    """The blank line above 'top places' must appear whether or not there's
    any bluesky-bot data yet -- it used to only be appended inside the
    `if bsky:` branch, so it silently vanished before the bot existed."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        self._orig_bsky = server.BSKY_STATE_FILE
        self.addCleanup(setattr, server, "BSKY_STATE_FILE", self._orig_bsky)
        server.BSKY_STATE_FILE = os.path.join(tempfile.mkdtemp(), "no_such_file.json")

    def test_blank_line_precedes_top_places_without_bsky_data(self):
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertNotIn("bluesky bot", resp.text)
        m = re.search(r"\n\ntop places", resp.text)
        self.assertIsNotNone(m)

    def test_default_shows_up_to_50_places(self):
        server._places.clear()
        self.addCleanup(server._places.clear)
        for i in range(60):
            server._places[f"City{i}"] = 60 - i
        resp = self.client.get("/stats", headers=TERMINAL)
        shown = resp.text.split("top places")[1]
        self.assertIn("City0", shown)
        self.assertIn("City49", shown)
        self.assertNotIn("City50", shown)


class ReferrerTracking(unittest.TestCase):
    """Referer header -> bare domain in /stats, so a share on Twitter or
    Bluesky is visible without pulling in IPs, user agents, or full URLs."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        self._orig_referrers = server._referrers.copy()
        self.addCleanup(self._restore)

    def _restore(self):
        server._referrers.clear()
        server._referrers.update(self._orig_referrers)

    def test_referer_header_shows_up_as_bare_domain(self):
        server._referrers.clear()
        self.client.get("/Zurich", headers={**TERMINAL, "referer": "https://twitter.com/some/status"})
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertIn("top referrers", resp.text)
        self.assertIn("twitter.com", resp.text)

    def test_www_prefix_is_stripped(self):
        server._referrers.clear()
        self.client.get("/Zurich", headers={**TERMINAL, "referer": "https://www.google.com/search?q=skymap"})
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertIn("google.com", resp.text)
        self.assertNotIn("www.google.com", resp.text)

    def test_no_referer_header_is_not_counted(self):
        server._referrers.clear()
        self.client.get("/Zurich", headers=TERMINAL)
        resp = self.client.get("/stats", headers=TERMINAL)
        self.assertNotIn("top referrers", resp.text)

    def test_self_referral_is_not_counted(self):
        server._referrers.clear()
        # TestClient's default Host is "testserver" -- match it, since the
        # self-referral check compares the Referer's host against whatever
        # Host header the request actually carried.
        self.client.get("/Zurich", headers={**TERMINAL, "referer": "http://testserver/"})
        self.assertEqual(len(server._referrers), 0)

    def test_json_mode_exposes_top_referrers(self):
        server._referrers.clear()
        self.client.get("/Zurich", headers={**TERMINAL, "referer": "https://bsky.app/profile/x"})
        resp = self.client.get("/stats?format=json")
        data = resp.json()
        self.assertEqual(data["top_referrers"].get("bsky.app"), 1)
        self.assertEqual(data["referrers_distinct"], 1)


class HourlyReferrers(unittest.TestCase):
    """/stats/hourly gets a per-hour top-domains breakdown alongside the
    existing requests/hit/day/night counts, so a spike from one platform is
    visible on the hourly trend, not just in the all-time /stats totals."""

    def setUp(self):
        self._orig_hour_stat = server._hour_stat.copy()
        self.addCleanup(self._restore)

    def _restore(self):
        server._hour_stat.clear()
        server._hour_stat.update(self._orig_hour_stat)

    def test_top_hour_referrers_sorts_and_caps(self):
        hstat = server.Counter()
        hstat.update({"ref:a.com": 3, "ref:b.com": 9, "ref:c.com": 1,
                      "ref:d.com": 5, "ref:e.com": 2, "ref:f.com": 7,
                      "requests": 27})
        top = server._top_hour_referrers(hstat, n=3)
        self.assertEqual(list(top.items()), [("b.com", 9), ("f.com", 7), ("d.com", 5)])

    def test_flush_hour_writes_top_referrers_to_the_log(self):
        orig_log = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig_log)
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd); os.remove(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        server.HOURLY_LOG = path

        hstat = server.Counter()
        hstat.update({"requests": 5, "hit": 4, "miss": 1, "day": 0, "night": 5,
                      "ref:twitter.com": 2})
        # Relative to now, not a fixed date: _read_hourly_history() only
        # returns rows inside its `days` window, so a hardcoded timestamp
        # passes until the real clock walks past it and then fails every
        # run after that, for no reason to do with the code under test.
        hour = (dt.datetime.utcnow() - dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:00")
        server._flush_hour(hour, hstat)

        rows = server._read_hourly_history(days=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["top_referrers"], {"twitter.com": 2})

    def test_referrer_grid_shows_each_domain_over_time(self):
        # The table's "top referrer" column only names each hour's winner,
        # so a domain that is second every hour is invisible, and no
        # domain's trend can be read at all. The grid puts hours down and
        # domains across so a column is one domain over time.
        rows = [
            dict(hour="2026-08-02T09:00", requests=40, hit=8, miss=32, day=30,
                 night=10, top_referrers={"news.ycombinator.com": 21, "bsky.app": 9}),
            dict(hour="2026-08-02T10:00", requests=55, hit=20, miss=35, day=40,
                 night=15, top_referrers={"news.ycombinator.com": 30, "reddit.com": 12}),
        ]
        out = "\n".join(server._referrer_grid(rows))
        for domain in ("news.ycombinator", "bsky.app", "reddit.com"):
            self.assertIn(domain, out)
        self.assertIn("21", out)
        self.assertIn("30", out)
        # bsky.app is absent from the 10:00 hour. That must not render as
        # 0: the log only keeps each hour's top few, so "not recorded" and
        # "no visits" are different claims and 0 would assert the stronger
        # one. Hence a dash.
        self.assertIn("-", out)
        self.assertIn("51", out)   # news.ycombinator.com total, 21 + 30

    def test_referrer_grid_is_empty_without_referrer_data(self):
        rows = [dict(hour="2026-08-02T09:00", requests=4, hit=1, miss=3,
                     day=4, night=0)]
        self.assertEqual(server._referrer_grid(rows), [])

    def test_hourly_page_includes_the_referrer_grid(self):
        server._hour_stat.clear()
        server._hour_stat.update({"requests": 3, "hit": 1, "miss": 2, "day": 1,
                                  "night": 2, "ref:bsky.app": 3})
        self.assertIn("visits per referrer per hour", server.stats_hourly_text())

    def test_current_hour_shows_up_in_text_and_json(self):
        server._hour_stat.clear()
        server._hour_stat.update({"requests": 1, "hit": 1, "miss": 0, "day": 0,
                                  "night": 1, "ref:bsky.app": 4})
        text = server.stats_hourly_text()
        self.assertIn("bsky.app (4)", text)

        data = server.stats_hourly_json()
        self.assertEqual(data["hours"][-1]["top_referrers"], {"bsky.app": 4})

    def test_hour_with_no_referrers_leaves_the_column_blank(self):
        server._hour_stat.clear()
        server._hour_stat.update({"requests": 1, "hit": 1, "miss": 0, "day": 0, "night": 1})
        data = server.stats_hourly_json()
        self.assertEqual(data["hours"][-1]["top_referrers"], {})


class StatsPersistence(unittest.TestCase):
    """_stat/_places/_finds are otherwise purely in-memory -- a restart
    (deploy, crash, systemd bounce) would silently zero them. This checks
    the save/load round-trip that keeps them alive across a restart."""

    def setUp(self):
        self._orig_file = server.STATS_STATE_FILE
        self.addCleanup(setattr, server, "STATS_STATE_FILE", self._orig_file)
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(path)  # _save_stats_state must create it, not require it pre-exist
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        server.STATS_STATE_FILE = path

        self._orig_stat = server._stat.copy()
        self._orig_places = server._places.copy()
        self._orig_finds = server._finds.copy()
        self._orig_referrers = server._referrers.copy()
        self._orig_started = server.STARTED
        self.addCleanup(self._restore)

    def _restore(self):
        server._stat.clear(); server._stat.update(self._orig_stat)
        server._places.clear(); server._places.update(self._orig_places)
        server._finds.clear(); server._finds.update(self._orig_finds)
        server._referrers.clear(); server._referrers.update(self._orig_referrers)
        server.STARTED = self._orig_started

    def test_save_then_load_restores_counters(self):
        server._stat.clear()
        server._stat.update({"requests": 42, "hit": 30})
        server._places.clear()
        server._places.update({"Zurich": 5})
        server._finds.clear()
        server._finds.update({"Venus": 3})
        server._referrers.clear()
        server._referrers.update({"twitter.com": 7})
        server.STARTED = 12345.0
        server._save_stats_state()

        server._stat.clear()
        server._places.clear()
        server._finds.clear()
        server._referrers.clear()
        server.STARTED = time.time()
        server._load_stats_state()

        self.assertEqual(server._stat["requests"], 42)
        self.assertEqual(server._stat["hit"], 30)
        self.assertEqual(server._places["Zurich"], 5)
        self.assertEqual(server._finds["Venus"], 3)
        self.assertEqual(server._referrers["twitter.com"], 7)
        self.assertEqual(server.STARTED, 12345.0)

    def test_missing_state_file_is_a_silent_noop(self):
        # No file was ever saved -- startup must not crash just because this
        # is the very first run.
        server._load_stats_state()

    def test_corrupt_state_file_is_a_silent_noop(self):
        with open(server.STATS_STATE_FILE, "w") as f:
            f.write("not json")
        server._load_stats_state()


class CatalogPage(unittest.TestCase):
    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_renders_in_terminal_mode(self):
        resp = self.client.get("/catalog", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        self.assertIn("Sirius", resp.text)

    def test_renders_in_a_browser(self):
        resp = self.client.get("/catalog", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))
        self.assertIn("Sirius", resp.text)

    def test_nav_links_to_the_catalog_page(self):
        resp = self.client.get("/legend", headers=BROWSER)
        self.assertIn('href="/catalog"', resp.text)

    def test_catalog_is_the_first_nav_link_after_home(self):
        resp = self.client.get("/legend", headers=BROWSER)
        nav = resp.text[resp.text.index('<b>skymap.sh</b>'):]
        self.assertLess(nav.index('href="/"'), nav.index('href="/catalog"'))
        self.assertLess(nav.index('href="/catalog"'), nav.index('href="/demo"'))


class HomeNavLink(unittest.TestCase):
    """Every page, including the home page itself, links to home -- a
    consistent nav position beats hiding the link on the one page where it
    would point at the current page."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_home_page_still_shows_the_home_link(self):
        resp = self.client.get("/", headers=BROWSER)
        self.assertIn('href="/"', resp.text)

    def test_a_place_page_links_home(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('href="/"', resp.text)

    def test_catalog_links_home(self):
        resp = self.client.get("/catalog", headers=BROWSER)
        self.assertIn('href="/"', resp.text)

    def test_legend_links_home(self):
        resp = self.client.get("/legend", headers=BROWSER)
        self.assertIn('href="/"', resp.text)


class StaticPageViewCounters(unittest.TestCase):
    """/help, /legend, /catalog and /demo previously had no view counter at
    all -- unlike the place-chart route (tallied via _tally()), nothing
    incremented for these, so they were invisible in /stats."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_each_static_page_increments_its_own_counter(self):
        self.client.get("/help", headers=TERMINAL)
        self.client.get("/legend", headers=TERMINAL)
        self.client.get("/catalog", headers=TERMINAL)
        self.client.get("/demo")
        pages = self.client.get("/stats?format=json").json()["pages"]
        for name in ("help", "legend", "catalog", "demo"):
            self.assertGreaterEqual(pages.get(name, 0), 1)


class SphereButtonGating(unittest.TestCase):
    """The "View in 3D" link is mobile-only, but there's no reliable
    server-side "is this a phone" signal (unlike TERMINALS, UA sniffing for
    phones misfires constantly -- iPadOS Safari's UA is indistinguishable
    from desktop Safari by design). So gating is CSS-only (a pointer:coarse
    media query): every browser gets the same markup, and these tests guard
    against that regressing into server-side UA branching."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_sphere_button_markup_is_identical_regardless_of_user_agent(self):
        # Real phones now redirect straight to /sphere before ever reaching
        # this page (see MobileRedirectsToSphere) -- what's left to guard is
        # every UA that DOES land here: desktop, and anything indistinguishable
        # from desktop (iPadOS Safari, by design). Both must get byte-identical
        # markup, gated by CSS (pointer:coarse) rather than server UA branching.
        desktop = self.client.get("/Zurich", headers=BROWSER)
        other = self.client.get("/Zurich", headers={
            "accept": "text/html",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        desktop_btn = re.search(r'<a class="animate-btn mobile-only"[^>]*>.*?</a>', desktop.text)
        other_btn = re.search(r'<a class="animate-btn mobile-only"[^>]*>.*?</a>', other.text)
        self.assertIsNotNone(desktop_btn)
        self.assertEqual(desktop_btn.group(0), other_btn.group(0))

    def test_mobile_ua_no_longer_reaches_this_page_at_all(self):
        # This client follows redirects, so a 200 here is the *sphere* page,
        # not the text one -- confirmed by its content, not just the status.
        resp = self.client.get("/Zurich", headers=MOBILE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Look around you", resp.text)
        self.assertNotIn("mobile-only", resp.text)

    def test_terminal_response_unchanged_by_sphere_feature(self):
        resp = self.client.get("/Zurich", headers=TERMINAL)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        self.assertNotIn("mobile-only", resp.text)
        self.assertNotIn("View in 3D", resp.text)


class SpherePage(unittest.TestCase):
    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_inline_script_is_syntactically_valid_javascript(self):
        # A f-string escaping mistake (a literal \n instead of an escaped
        # \\n, so Python turned it into a real newline inside a JS string
        # literal) once shipped a syntax error that broke the ENTIRE
        # inline script -- not just the feature being changed, the whole
        # page, including the "look around" button's click handler.
        # Python's own tests never caught it because they only ever check
        # that api.py itself parses, not that the JS it renders does.
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available to check JS syntax")
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        script = re.search(r'<script type="module">(.*?)</script>',
                           resp.text, re.DOTALL).group(1)
        with tempfile.NamedTemporaryFile(suffix=".mjs", mode="w", delete=False) as f:
            f.write(script)
            path = f.name
        try:
            result = subprocess.run([node, "--check", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            os.remove(path)

    def test_sphere_page_returns_html_with_three_js_and_json_fetch(self):
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))
        self.assertIn("three.module.js", resp.text)
        # The page's own JS builds the fetch URL as '/' + PLACE + '/sphere.json'
        # rather than a literal string -- check the pieces it's assembled from.
        self.assertIn('var PLACE = "Zurich";', resp.text)
        self.assertIn("/sphere.json", resp.text)

    def test_label_declutter_is_throttled_not_run_every_frame(self):
        # Regression guard: declutterLabels() sorts every labeled object
        # and does a pairwise overlap check against everything already
        # placed -- real, continuous GC pressure if it runs unthrottled at
        # 60fps for a whole session. It only needs to run as often as the
        # HUD heading readout (updateHeading(), already throttled to every
        # 4th frame) since it just nudges labels to avoid overlapping, not
        # their actual per-frame position.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("if (throttleTick) declutterLabels();", resp.text)

    def test_compass_uses_true_north_not_wherever_the_page_loaded_facing(self):
        # Regression guard: this used to zero the compass to "wherever
        # you're facing when you tap look around", which quietly worked
        # only for anyone who happened to test facing true north. Fixed
        # to read the phone's own compass instead (webkitCompassHeading on
        # iOS, deviceorientationabsolute elsewhere) -- there must be no
        # start-direction recentring left in the served page.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("webkitCompassHeading", resp.text)
        self.assertNotIn("yawOffset", resp.text)

    def test_no_screen_orientation_compensation(self):
        # Regression guard: this page never changes layout for landscape,
        # it's always read the same way regardless of how the phone is
        # tilted -- but iOS still tracks portrait/landscape internally off
        # the phone's raw angle, and normal use (tilting well off-vertical
        # to look up, or turning around) could cross that internal
        # threshold and snap the whole scene 90 degrees for no visible
        # reason. screenAngle()/screen.orientation.angle must not feed
        # into the camera rotation at all.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertNotIn("screenAngle", resp.text)
        self.assertNotIn("screen.orientation", resp.text)

    def test_heading_renders_from_fused_alpha_not_the_raw_compass(self):
        # The regression this exists to prevent: an earlier "fix the
        # compass to point at true north" change started rendering
        # straight off webkitCompassHeading. That reads true north, but
        # it's the raw magnetometer -- its tilt compensation falls apart
        # as the phone approaches vertical, which is exactly how this app
        # is held, so the view jumped tens of degrees whenever the phone
        # came up toward the horizon. alpha on the same event is
        # gyro-fused and smooth but has an arbitrary zero.
        #
        # So the compass must only ever feed the north OFFSET (slowly,
        # and barely at all near vertical), never the rendered heading
        # frame by frame.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("feedCompassOffset(", resp.text)
        self.assertIn("compassOffsetDeg()", resp.text)
        self.assertIn("var COMPASS_TRUST_BETA = 70;", resp.text)
        # The rendered angle is alpha plus the slow offset. If this ever
        # goes back to assigning webkitCompassHeading straight into the
        # rendered angle whenever it exists, the jumping comes back.
        self.assertIn("alphaDeg = ((e.alpha + compassOffsetDeg()) % 360 + 360) % 360;",
                      resp.text)

    def test_no_per_angle_dead_zone(self):
        # A dead zone was tried while the magnetometer still drove the
        # view, to damp its jitter. Rendering from the gyro-fused alpha
        # removed that jitter at the source, leaving the dead zone with
        # only its own artefact: it quantises slow pans into visible
        # steps, which reads on a real phone as the view snapping.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertNotIn("DEADZONE_DEG", resp.text)
        self.assertNotIn("function deadzone(", resp.text)

    def test_sphere_page_404s_for_unknown_place(self):
        resp = self.client.get("/Nowhereville/sphere", headers=BROWSER)
        self.assertEqual(resp.status_code, 404)

    def test_sphere_json_is_always_json_even_for_curl(self):
        resp = self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))

    def test_sphere_json_404s_for_unknown_place(self):
        resp = self.client.get("/Nowhereville/sphere.json", headers=TERMINAL)
        self.assertEqual(resp.status_code, 404)

    def test_sphere_json_has_expected_top_level_keys(self):
        resp = self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        data = resp.json()
        for key in ("stars", "asterisms", "deepsky", "bodies", "moon",
                   "sun_alt", "mag_limit"):
            self.assertIn(key, data)

    def test_sphere_json_stars_have_resolved_altaz_within_bounds(self):
        # Pinned to a real Zurich nighttime moment -- a bare "now" would make
        # this flaky (during daylight the fading mag_limit can legitimately
        # drop to zero stars).
        resp = self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        data = resp.json()
        self.assertTrue(data["stars"])
        for s in data["stars"]:
            self.assertIsInstance(s["alt"], float)
            self.assertIsInstance(s["az"], float)
            self.assertGreaterEqual(s["alt"], -90)
            self.assertLessEqual(s["alt"], 90)
            self.assertLessEqual(s["mag"], data["mag_limit"])

    def test_sphere_json_is_a_full_sphere_not_just_the_visible_dome(self):
        # The 3D view shows the whole celestial sphere, not just what's above
        # this observer's own horizon -- the far side is night for someone
        # even when it's day here, so below-horizon stars must be present.
        resp = self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        data = resp.json()
        below_horizon = [s for s in data["stars"] if s["alt"] < 0]
        self.assertTrue(below_horizon)

    def test_hours_to_dark_is_null_at_night(self):
        resp = self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        self.assertIsNone(resp.json()["hours_to_dark"])

    def test_hours_to_dark_counts_down_to_dusk_by_day(self):
        resp = self.client.get("/Zurich/sphere.json?t=2026-08-01T16:54", headers=TERMINAL)
        data = resp.json()
        self.assertGreater(data["sun_alt"], 0)
        self.assertIsNotNone(data["hours_to_dark"])
        self.assertGreater(data["hours_to_dark"], 0)
        self.assertLess(data["hours_to_dark"], 24)

    def test_sphere_stats_counters_increment(self):
        self.client.get("/Zurich/sphere", headers=BROWSER)
        self.client.get("/Zurich/sphere.json?t=2026-01-15T20:00", headers=TERMINAL)
        stats = self.client.get("/stats?format=json").json()
        self.assertGreaterEqual(stats["sphere"], 1)
        sphere_stats = self.client.get("/stats/sphere?format=json").json()
        self.assertGreaterEqual(sphere_stats["sphere_json"], 1)

    def test_sphere_views_tracked_separately_per_place(self):
        # /Zurich/sphere.json isn't a page view (no browser navigates there
        # on its own), only /Zurich/sphere should count toward this.
        self.client.get("/Tokyo/sphere", headers=BROWSER)
        stats = self.client.get("/stats/sphere?format=json").json()
        self.assertIn("Tokyo", stats["top_places"])
        self.assertGreaterEqual(stats["top_places"]["Tokyo"], 1)

    def test_sphere_places_are_separate_from_text_places(self):
        # A sphere-only view of a place shouldn't inflate the ASCII chart's
        # own top_places count, since sphere_page() never calls _tally().
        self.client.get("/Reykjavik/sphere", headers=BROWSER)
        sphere_stats = self.client.get("/stats/sphere?format=json").json()
        text_stats = self.client.get("/stats?format=json").json()
        self.assertIn("Reykjavík", sphere_stats["top_places"])
        self.assertNotIn("Reykjavík", text_stats["top_places"])

    def test_sphere_os_breakdown(self):
        self.client.get("/Osaka/sphere", headers={
            "accept": "text/html",
            "user-agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36"})
        stats = self.client.get("/stats/sphere?format=json").json()
        self.assertGreaterEqual(stats["by_os"].get("android", 0), 1)

    def test_stats_sphere_page_renders_in_a_browser(self):
        resp = self.client.get("/stats/sphere", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/html"))

    def test_stats_sphere_not_duplicated_in_main_stats(self):
        stats = self.client.get("/stats?format=json").json()
        self.assertNotIn("top_sphere_places", stats)
        self.assertNotIn("mobile_redirect", stats)


class MobileRedirectsToSphere(unittest.TestCase):
    """The text/ASCII view has no real value on a phone screen -- a mobile
    UA landing on the bare root or any named place is sent straight to that
    place's 3D sphere instead. Desktop browsers, curl, and unknown places
    are all unaffected."""

    def setUp(self):
        client_cm = TestClient(server.app, follow_redirects=False)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_mobile_root_redirects_to_sphere(self):
        resp = self.client.get("/", headers=MOBILE)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/sphere"))

    def test_mobile_named_place_redirects_to_its_own_sphere(self):
        resp = self.client.get("/Tokyo", headers=MOBILE)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Tokyo/sphere")

    def test_query_string_carries_over(self):
        resp = self.client.get("/Tokyo?t=2026-01-15T20:00", headers=MOBILE)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Tokyo/sphere?t=2026-01-15T20:00")

    def test_desktop_browser_is_unaffected(self):
        resp = self.client.get("/Tokyo", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)

    def test_terminal_is_unaffected_even_with_a_mobile_looking_ua(self):
        resp = self.client.get("/Tokyo", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)

    def test_unknown_place_falls_through_to_the_normal_404(self):
        resp = self.client.get("/Nowhereville", headers=MOBILE)
        self.assertEqual(resp.status_code, 404)

    def test_mobile_redirect_stats_counter_increments(self):
        self.client.get("/Tokyo", headers=MOBILE)
        stats = self.client.get("/stats/sphere?format=json").json()
        self.assertGreaterEqual(stats["mobile_redirect"], 1)

    def test_googlebot_mobile_crawler_is_not_redirected(self):
        # Googlebot's and Bingbot's mobile crawlers send an Android/iPhone
        # UA -- without an exemption they'd get the sphere page redirect
        # same as a real phone, and Google's mobile index (the primary one
        # today) would see a thin, JS-only page instead of the real text
        # content this site is actually about.
        resp = self.client.get("/Tokyo", headers={
            "accept": "text/html",
            "user-agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
                          "Mobile Safari/537.36 (compatible; Googlebot/2.1; "
                          "+http://www.google.com/bot.html)"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("three.module.js", resp.text)


class Favicon(unittest.TestCase):
    """Browsers request /favicon.ico and /apple-touch-icon.png on every visit
    regardless of whether the site has one -- unhandled, those were the
    single biggest chunk of /stats' non-200 count (see the log audit)."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_favicon_ico_serves(self):
        resp = self.client.get("/favicon.ico")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("image/"))

    def test_apple_touch_icon_serves(self):
        resp = self.client.get("/apple-touch-icon.png")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("image/"))

    def test_page_links_to_the_favicon(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('href="/favicon.ico"', resp.text)
        self.assertIn('href="/apple-touch-icon.png"', resp.text)


class SeoRoutes(unittest.TestCase):
    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_robots_points_at_the_sitemap(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Sitemap: https://skymap.sh/sitemap.xml", resp.text)

    def test_robots_disallows_the_sphere_view(self):
        # Thin, JS-dependent, one entry per place -- not worth indexing,
        # on top of the crawler exemption in _is_mobile() itself.
        resp = self.client.get("/robots.txt")
        self.assertIn("Disallow: /*/sphere\n", resp.text)
        self.assertIn("Disallow: /*/sphere.json\n", resp.text)

    def test_sitemap_is_valid_looking_xml_with_absolute_urls(self):
        resp = self.client.get("/sitemap.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("application/xml"))
        self.assertIn("<urlset", resp.text)
        self.assertIn("https://skymap.sh/demo", resp.text)
        # A multi-word city must be percent-encoded, not a literal space --
        # a raw space in <loc> is invalid XML/sitemap syntax.
        self.assertIn("New%20York", resp.text)
        self.assertNotIn("New York<", resp.text)

    def test_llms_txt_serves_plain_text(self):
        resp = self.client.get("/llms.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        self.assertIn("skymap.sh", resp.text)


if __name__ == "__main__":
    unittest.main()
