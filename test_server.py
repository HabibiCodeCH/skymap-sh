#!/usr/bin/env python3
"""Tests for the browser vs. terminal ?animate= handling in server.py.

Run:  python3 test_server.py
"""
import json
import os
import re
import tempfile
import time
import unittest

from starlette.testclient import TestClient

import server

BROWSER = {"accept": "text/html", "user-agent": "Mozilla/5.0"}
TERMINAL = {"user-agent": "curl/8.0"}


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
        self._orig_started = server.STARTED
        self.addCleanup(self._restore)

    def _restore(self):
        server._stat.clear(); server._stat.update(self._orig_stat)
        server._places.clear(); server._places.update(self._orig_places)
        server._finds.clear(); server._finds.update(self._orig_finds)
        server.STARTED = self._orig_started

    def test_save_then_load_restores_counters(self):
        server._stat.clear()
        server._stat.update({"requests": 42, "hit": 30})
        server._places.clear()
        server._places.update({"Zurich": 5})
        server._finds.clear()
        server._finds.update({"Venus": 3})
        server.STARTED = 12345.0
        server._save_stats_state()

        server._stat.clear()
        server._places.clear()
        server._finds.clear()
        server.STARTED = time.time()
        server._load_stats_state()

        self.assertEqual(server._stat["requests"], 42)
        self.assertEqual(server._stat["hit"], 30)
        self.assertEqual(server._places["Zurich"], 5)
        self.assertEqual(server._finds["Venus"], 3)
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
