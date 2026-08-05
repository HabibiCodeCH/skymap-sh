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

import pytest
from starlette.testclient import TestClient

import api
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
    # The /stats family draws on its own bucket, so it needs lifting too --
    # otherwise the stats tests throttle each other instead.
    server.RATE = 1_000_000
    server.BURST = 1_000_000
    server.STATS_RATE = 1_000_000
    server.STATS_BURST = 1_000_000


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # server.ratelimit shares one token bucket per client IP across the
    # whole process -- TestClient requests all land on the same synthetic
    # IP, so without this the bucket drains as the suite grows and later
    # tests start failing with 429s that have nothing to do with what
    # they're actually testing.
    server._buckets.clear()
    yield


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

    def test_animate_button_carries_the_current_chart_width(self):
        # Without this, clicking animate on an auto-fit-widened page (say
        # ?w=220) replaces the chart with frames rendered at the narrower
        # DEFAULT_HORIZON_WIDTH fallback -- a visible shrink the instant the
        # preview starts.
        resp = self.client.get("/Ibiza?w=220&animate=24", headers=BROWSER)
        m = re.search(r'data-live-url="([^"]+)"', resp.text)
        self.assertIsNotNone(m)
        self.assertIn("w=220", m.group(1))

    def test_animate_button_omits_width_when_view_has_no_explicit_one(self):
        resp = self.client.get("/Ibiza?animate=24", headers=BROWSER)
        m = re.search(r'data-live-url="([^"]+)"', resp.text)
        self.assertIsNotNone(m)
        self.assertNotIn("w=", m.group(1))

    def test_playback_runs_at_the_speed_the_server_streams_at(self):
        # The page's tick reads this rather than hardcoding a matching
        # number. Retune ANIMATE_FRAME_DELAY alone and playback would drift
        # behind the stream, then catch up in jumps.
        resp = self.client.get("/Ibiza?animate=24", headers=BROWSER)
        m = re.search(r'data-frame-ms="(\d+)"', resp.text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)),
                         int(server.ANIMATE_FRAME_DELAY * 1000))

    def test_frames_are_buffered_rather_than_painted_as_they_land(self):
        # Painting straight off the stream leaves nothing to pause on or
        # step back to -- each frame was drawn once and dropped. Shallow
        # presence check, the same style the other JS-behaviour tests use.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("A.frames.push", body)
        self.assertIn("function skymapAnimTick", body)
        self.assertIn("function skymapAnimStep", body)

    def test_the_chart_goes_back_to_where_it_started_when_the_run_ends(self):
        # The last frame is 24 hours past the moment the page is about, so
        # leaving it up ends the animation on a chart that disagrees with
        # every heading and link around it.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("base:pre.innerHTML", body)          # captured up front
        self.assertIn("function skymapAnimRestore", body)
        self.assertIn("A.pre.innerHTML=A.base", body)
        # Called on a clean finish and on a stream that dies halfway. The
        # trailing semicolon keeps the definition itself out of the count.
        self.assertEqual(body.count("skymapAnimRestore();"), 2)

    def test_space_pauses_and_the_arrows_step_while_animating(self):
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("e.key==='ArrowLeft'||e.key==='ArrowRight'", body)
        self.assertIn("skymapAnimStep(e.key==='ArrowLeft'?-1:1)", body)
        # Gated on there being an animation, so space and the arrows keep
        # scrolling the page everywhere else.
        self.assertIn("window.skymapAnim&&window.skymapAnim.frames.length", body)

    def test_a_frame_can_carry_deep_sky_at_all(self):
        # compose_frame never passed dso_limit, so an animation asked for
        # deep sky rendered byte-identical output -- there was nothing for
        # the paused-frame "d" to reveal.
        def frame(dso):
            qs = "&dso=1" if dso else ""
            body = self.client.get(f"/Geneva?animate=1&t=2026-08-19T23:00&ui=1{qs}",
                                   headers=TERMINAL).text
            first = [f for f in body.split("\x1b[2J\x1b[H") if f.strip()][0]
            return server.api.strip_ansi(first)
        plain, deep = frame(False), frame(True)
        self.assertNotEqual(plain, deep)
        self.assertIn("Nebula", deep)
        self.assertNotIn("Nebula", plain)

    def test_the_page_knows_how_far_apart_frames_are(self):
        # Needed to work out which moment the paused frame is showing, so it
        # can be asked for again with deep sky on.
        resp = self.client.get("/Ibiza?animate=24", headers=BROWSER)
        m = re.search(r'data-step-min="(\d+)"', resp.text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), server.ANIMATE_STEP_MIN)

    def test_d_loads_deep_sky_into_the_paused_frame_instead_of_navigating(self):
        # Plain "d" is location.href to the quadrant+dso view, which would
        # take the frame buffer and the paused position with it.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("function skymapAnimDeepSky", body)
        self.assertIn("skymapAnimDeepSky(function(ok,on)", body)
        # One frame, not the whole run: the stream is cancelled as soon as
        # its first frame is whole.
        self.assertIn("reader.cancel();return parts[1];", body)
        # Written back into the buffer, so stepping away and returning keeps it.
        self.assertIn("A.frames[at]=frame;", body)

    def test_d_is_a_toggle_not_a_one_way_switch(self):
        # Both versions of the frame are kept -- the stream's own and the
        # deep-sky one -- so a second press puts the plain frame back and a
        # third costs no request.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("A.frames[at]=A.plain[at];", body)     # back to plain
        self.assertIn("A.dsoFrames[at]!==undefined", body)   # cached, no refetch
        self.assertIn("plain:{},dsoFrames:{},dsoOn:{},", body.replace("\n", ""))
        self.assertIn("'Deep sky '+(on?'on':'off')", body)

    def test_space_starts_the_animation_and_a_no_longer_does(self):
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertNotIn("if(e.key==='a')", body)
        # Guarded on the button existing, so space keeps scrolling every
        # page that has nothing to animate.
        self.assertIn("var ab=document.getElementById('animate-btn');", body)
        help_text = self.client.get("/help", headers=TERMINAL).text
        self.assertIn("space  start the animation", help_text)
        self.assertNotIn("a   toggle animate", help_text)

    def test_a_second_press_before_the_first_frame_does_not_restart_it(self):
        # window.skymapAnim exists the moment the fetch is kicked off, but
        # with no frames yet -- falling through from there would open a
        # second stream. Space makes that easy to hit; it is a key people
        # tap twice.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertIn("if(!A.frames.length)return;", body)

    def test_starting_the_animation_does_not_park_focus_in_a_text_field(self):
        # Pressing "a" works by clicking the animate button. While a
        # document-level click listener refocused the place search on every
        # click, that synthetic click sent every key after it to the input,
        # where the handler rightly returns early, so space and the arrows
        # did nothing. That listener is gone, along with the animate-btn
        # exception it needed -- nothing puts focus in a field now unless
        # the reader asks for it.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        self.assertNotIn("document.addEventListener('click',function(e){", body)
        self.assertNotIn("id==='animate-btn')return;", body)

    def test_the_transport_hint_only_shows_while_something_is_animating(self):
        # The hint line has room for one row, and space/arrows/d do nothing
        # until there are frames -- so they take the line over while the
        # animation runs and hand it back when it stops.
        body = self.client.get("/Ibiza?animate=24", headers=BROWSER).text
        hint = re.search(r'<p class="kbd-hint">(.*?)</p>', body, re.S).group(1)
        self.assertNotIn("<br>", hint)                    # stays one line
        # Space is what starts it, so it is named at rest -- the stepping
        # keys are not, since they do nothing until there are frames.
        self.assertIn("<kbd>space</kbd> animate", hint)
        self.assertNotIn("&larr;", hint)
        self.assertNotIn("play/pause", hint)
        self.assertIn("<kbd>space</kbd> play/pause", body)   # in the JS
        self.assertIn("window.skymapSetHint(SKYMAP_ANIM_HINT)", body)
        self.assertIn("window.skymapSetHint(null)", body)
        help_text = self.client.get("/help", headers=TERMINAL).text
        self.assertIn("space plays/pauses", help_text)

    def test_the_resting_hint_says_tab_and_leaves_out_gif(self):
        body = self.client.get("/Ibiza", headers=BROWSER).text
        hint = re.search(r'<p class="kbd-hint">(.*?)</p>', body, re.S).group(1)
        self.assertIn("<kbd>tab</kbd> search", hint)
        # p still focuses the place field, it just isn't the one advertised.
        self.assertNotIn("<kbd>p</kbd>", hint)
        # Share as a GIF is a labelled button in the drawer already.
        self.assertNotIn("<kbd>g</kbd>", hint)

    def test_terminal_gif_followup_carries_the_requested_time(self):
        # The streamed preview's own "Want a shareable GIF? Run: ..." command
        # used to drop t= entirely, built from place.slug alone -- so
        # copy-pasting it rendered from the real current moment instead of
        # whatever the preview just played from, silently (no error, just
        # the wrong GIF). animate=1 keeps this fast (4 frames, ~0.6s).
        resp = self.client.get("/Ibiza?t=2026-08-12T18:00&animate=1", headers=TERMINAL)
        self.assertIn("/Ibiza/animate.gif?t=2026-08-12T18:00", resp.text)


class GifButtonAlwaysVisible(unittest.TestCase):
    """'Share as a GIF' used to render with a hidden attribute and only
    become visible once animate had actually been clicked -- rendering
    itself (data-gif-url) never depended on that, so it's always visible
    now, greyed out only by the real constraint (skymapPollGifCapacity,
    kicked off on page load rather than from inside skymapAnimate)."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_gif_button_has_no_hidden_attribute(self):
        resp = self.client.get("/Ibiza", headers=BROWSER)
        m = re.search(r'<button id="gif-btn"[^>]*>', resp.text)
        self.assertIsNotNone(m)
        self.assertNotIn("hidden", m.group(0))

    def test_capacity_poll_starts_on_page_load(self):
        resp = self.client.get("/Ibiza", headers=BROWSER)
        self.assertIn("if(gifBtn)skymapPollGifCapacity(gifBtn);", resp.text)

    def test_animate_no_longer_kicks_off_the_poll_itself(self):
        # Regression guard against double-polling (two poll calls on one
        # button) if this ever gets called from both places again.
        resp = self.client.get("/Ibiza", headers=BROWSER)
        animate_fn = resp.text.split("function skymapAnimate(btn){")[1]
        animate_fn = animate_fn.split("\nfunction skymapPollGifCapacity")[0]
        self.assertNotIn("skymapPollGifCapacity(gifBtn)", animate_fn)

    def test_capacity_poll_is_a_single_check_not_a_repeating_timer(self):
        # Used to also setInterval(poll,4000) for as long as the tab stayed
        # open, which cost every visitor ~15 rate-limited requests a minute
        # just for having a chart page open -- a real contributor to normal
        # visitors ("land, click, refresh") hitting the rate limit. A stale
        # capacity read is harmless (skymapRenderGif already catches a 503
        # on click), so one check on page load is enough.
        resp = self.client.get("/Ibiza", headers=BROWSER)
        poll_fn = resp.text.split("function skymapPollGifCapacity(gifBtn){")[1]
        poll_fn = poll_fn.split("\nfunction skymapRenderGif")[0]
        self.assertNotIn("setInterval", poll_fn)


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

    def test_nodso_param_is_tallied_and_keeps_dso_off_the_tally(self):
        self.client.get("/Zurich?quadrant=A&nodso=1", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        params = resp.json()["params"]
        self.assertEqual(params.get("nodso"), 1)
        self.assertIsNone(params.get("dso"))

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
        # An empty log of its own. These tests seed the hour in progress and
        # assert on the exact counts they seeded; same-hour rows are summed
        # now, so anything another test left in the shared log would be added
        # to theirs and the numbers would depend on test order.
        orig_log = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig_log)
        server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(), "hourly.jsonl")

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

    def test_referrer_grid_skips_hours_with_no_referred_visits(self):
        # Referrer tracking is newer than the hourly log and most traffic
        # is direct or CLI, so in practice most hours carry nothing. Those
        # rows are all dashes and bury the few that have data.
        rows = [dict(hour=f"2026-08-02T{h:02d}:00", requests=4, hit=1, miss=3,
                     day=4, night=0) for h in range(20)]
        rows.append(dict(hour="2026-08-02T21:00", requests=9, hit=2, miss=7,
                         day=5, night=4, top_referrers={"reddit.com": 6}))
        out = "\n".join(server._referrer_grid(rows))
        self.assertIn("2026-08-02T21:00", out)
        self.assertNotIn("2026-08-02T05:00", out)
        self.assertIn("20 hour(s) with no referred visits not shown", out)

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


class ClientMixAndFinds(unittest.TestCase):
    """Who asked (CLI/Web/Mobile/JSON) and how many were looking for
    something, per hour. _wants' three modes already cover every request,
    but a phone is html -- so mobile is split back out of web rather than
    counted twice, which is what makes the four add up to the whole."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        self._hour = server._hour_stat.copy()
        self._key = server._hour_key
        # These tests make real requests to exercise _tally, which lands in
        # the geo bins and the place leaderboard as well -- snapshot them or
        # a later test that pins "2 distinct locations" fails depending on
        # what ran before it.
        self._snap = {name: getattr(server, name).copy()
                      for name in ("_stat", "_places", "_geo_hits")}
        self.addCleanup(self._restore)
        server._hour_stat.clear()
        server._hour_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")

    def _restore(self):
        server._hour_stat.clear()
        server._hour_stat.update(self._hour)
        server._hour_key = self._key
        for name, snap in self._snap.items():
            counter = getattr(server, name)
            counter.clear()
            counter.update(snap)

    def _mix(self):
        return {k: server._hour_stat[k] for k in server.CLIENTS}

    def test_every_request_lands_in_exactly_one_bucket(self):
        for headers in (TERMINAL, BROWSER, MOBILE):
            self.client.get("/Zurich", headers=headers)
        self.client.get("/Zurich?format=json", headers=TERMINAL)
        mix = self._mix()
        self.assertEqual(sum(mix.values()), server._hour_stat["requests"])
        # And each went where it belongs, rather than all landing in one.
        self.assertEqual(mix["cli"], 1)
        self.assertEqual(mix["json"], 1)
        self.assertEqual(mix["mobile"], 1)
        self.assertEqual(mix["web"], 1)

    def test_a_phone_is_not_also_counted_as_web(self):
        # The whole reason the four can add up: html is the mode a phone
        # arrives as, so counting both would double it.
        self.client.get("/Zurich", headers=MOBILE)
        self.assertEqual(self._mix()["mobile"], 1)
        self.assertEqual(self._mix()["web"], 0)

    def test_object_lookups_are_counted_per_hour_not_just_by_name(self):
        # The leaderboard says which object, never whether anyone is still
        # using it over time.
        before = server._hour_stat["object"]
        self.client.get("/Vega", headers=TERMINAL)
        self.client.get("/Tokyo/Altair", headers=TERMINAL)
        self.client.get("/Zurich", headers=TERMINAL)
        self.assertEqual(server._hour_stat["object"] - before, 2)

    def test_a_legacy_find_chart_is_a_chart_not_an_object_lookup(self):
        # ?find= still renders, but it is a horizon chart with a crosshair
        # on it. Object pages set r.find to draw that same crosshair, which
        # is why "has a find" stopped meaning "is a find".
        before = server._hour_stat["object"], server._stat["view:horizon"]
        self.client.get("/Zurich?find=Vega", headers=TERMINAL)
        after = server._hour_stat["object"], server._stat["view:horizon"]
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (0, 1))

    def test_the_new_fields_reach_the_log_only_when_there_is_something(self):
        orig = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig)
        server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(), "hourly.jsonl")
        hour = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._flush_hour(hour, server.Counter({"requests": 3, "cli": 2,
                                                 "web": 1, "object": 4}))
        row = server._read_hourly_history(days=1)[0]
        self.assertEqual((row["cli"], row["web"], row["object"]), (2, 1, 4))
        for empty in ("mobile", "json"):
            self.assertNotIn(empty, row)      # never written as a zero
        # but a reader still gets a number for them
        dense = server._dense_hours([row], 1)[-1]
        self.assertEqual(dense["mobile"], 0)

    def test_stats_shows_both_blocks_and_the_drilldowns_do_not(self):
        # /stats is the overview and stacks them; the drill-down pages
        # answer one question each and keep the chart they are named after.
        stats = self.client.get("/stats", headers=TERMINAL).text
        for label in ("cli", "web", "mobile", "json"):
            self.assertIn(label, stats)
        self.assertIn("share of requests by client", stats)
        self.assertIn("OBJECT LOOKUPS PER HOUR", stats)
        self.assertIn("OBJECT LOOKUPS PER DAY", stats)
        for path in ("/stats/hourly", "/stats/daily"):
            body = self.client.get(path, headers=TERMINAL).text
            self.assertNotIn("share of requests by client", body, path)
            self.assertNotIn("OBJECT LOOKUPS PER", body, path)

    def test_the_day_charts_all_start_at_the_same_column(self):
        # Each _side_by_side used to pad to its own block's widest line, so
        # the day column began a few characters further left under the short
        # finds chart than under the tall requests one.
        text = server.api.strip_ansi(self.client.get("/stats",
                                                     headers=TERMINAL).text)
        cols = {}
        for line in text.splitlines():
            for marker in ("REQUESTS PER DAY", "OBJECT LOOKUPS PER DAY"):
                if marker in line:
                    cols[marker] = line.index(marker)
        self.assertEqual(len(cols), 2, cols)
        self.assertEqual(len(set(cols.values())), 1, cols)

    def test_the_tail_percentages_add_up_even_with_unrecorded_hours(self):
        # The four fields only exist from the day they shipped, so most of a
        # 48h window has requests and no mix at all. Counted in the
        # denominator those hours dragged every tail to 0-1%, which is the
        # one thing this block says it will never do.
        hour = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        before = (dt.datetime.utcnow() - dt.timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:00")
        rows = [
            # an hour from before the fields existed: traffic, no mix
            dict(hour=before, requests=500, hit=250, miss=250, day=500, night=0),
            dict(hour=hour, requests=10, hit=5, miss=5, day=10, night=0,
                 cli=4, web=3, mobile=2, json=1),
        ]
        plain = server.api.strip_ansi(
            "\n".join(server._client_mix_block(server._dense_hours(rows, 2),
                                               cols=2)))
        tails = [int(p) for p in re.findall(r"(\d+)%", plain)]
        self.assertEqual(len(tails), 4, plain)
        self.assertEqual(sum(tails), 100, plain)
        self.assertEqual(tails, [40, 30, 20, 10], plain)

    def test_the_four_shares_are_taken_against_the_same_bucket(self):
        # Each sparkline is that client's share of the same hour, so the
        # four bars at any column stack to the whole -- not four separate
        # scales that happen to sit under each other.
        # The current hour: _dense_hours zero-fills relative to now, so a
        # row dated elsewhere lands outside the window and reads as empty.
        hour = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        rows = [dict(hour=hour, requests=10, hit=5, miss=5,
                     day=10, night=0, cli=4, web=3, mobile=2, json=1, find=0)]
        entries = server._dense_hours(rows, 1)
        block = "\n".join(server._client_mix_block(entries, cols=1))
        plain = server.api.strip_ansi(block)
        self.assertIn("40%", plain)      # cli
        self.assertIn("30%", plain)      # web
        self.assertIn("20%", plain)      # mobile
        self.assertIn("10%", plain)      # json


class HourlyLogLosesNothing(unittest.TestCase):
    """/stats' header counts every request; the charts count what reached the
    hourly log. They used to disagree by a wide margin -- 730 against 544 over
    the same 51 h on production -- because two things never got written."""

    def setUp(self):
        self._log = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", self._log)
        server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(), "hourly.jsonl")
        self._stat = server._stat.copy()
        self._hour_stat = server._hour_stat.copy()
        self._hour_key = server._hour_key
        self.addCleanup(self._restore)
        server._hour_stat.clear()

    def _restore(self):
        server._hour_stat.clear()
        server._hour_stat.update(self._hour_stat)
        server._stat.clear()
        server._stat.update(self._stat)
        server._hour_key = self._hour_key

    def _rows(self):
        return server._read_hourly_history(days=1)

    def test_shutdown_writes_the_hour_in_progress(self):
        # A deploy is `systemctl restart`, which is a SIGTERM and a shutdown
        # handler. Only _roll_hour used to write, so everything tallied since
        # the last o'clock went in the bin -- and a day of several deploys
        # threw away several part-hours of real traffic.
        server._hour_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._hour_stat.update({"requests": 7, "hit": 3, "miss": 4,
                                  "day": 2, "night": 5})
        server._save_on_exit()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requests"], 7)
        self.assertEqual(rows[0]["hour"], server._hour_key)

    def test_shutting_down_twice_does_not_write_the_hour_twice(self):
        # One process shuts down once, but two TestClient context managers in
        # one pytest run are two shutdowns, and a doubled hour is worse than
        # a missing one -- it reads as real traffic.
        server._hour_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._hour_stat.update({"requests": 4, "hit": 4, "miss": 0,
                                  "day": 4, "night": 0})
        server._save_on_exit()
        server._save_on_exit()
        self.assertEqual(len(self._rows()), 1)

    def test_the_table_shows_a_restarted_hour_once(self):
        # Two log lines for one hour is now the normal shape of a deploy.
        # Listed line by line the table showed that hour twice, each with a
        # slice of its traffic and a hit% taken against the slice.
        hour = "2026-08-02T09:00"
        rows = [dict(hour=hour, requests=6, hit=6, miss=0, day=6, night=0,
                     top_referrers={"bsky.app": 4}),
                dict(hour=hour, requests=4, hit=1, miss=3, day=4, night=0,
                     top_referrers={"bsky.app": 1, "reddit.com": 2}),
                dict(hour="2026-08-02T10:00", requests=2, hit=1, miss=1,
                     day=2, night=0)]
        merged = server._merge_hour_rows(rows)
        self.assertEqual([m["hour"] for m in merged], [hour, "2026-08-02T10:00"])
        self.assertEqual(merged[0]["requests"], 10)
        self.assertEqual(merged[0]["hit"], 7)
        self.assertEqual(merged[0]["top_referrers"], {"bsky.app": 5, "reddit.com": 2})

    def test_the_two_halves_of_a_restarted_hour_add_up(self):
        # The restart splits one hour across two rows. _dense_hours has always
        # summed same-hour rows for exactly this case; this is the half that
        # was missing.
        hour = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._hour_key = hour
        server._hour_stat.update({"requests": 6, "hit": 6, "miss": 0,
                                  "day": 6, "night": 0})
        server._save_on_exit()                      # first process goes down
        server._hour_stat.update({"requests": 5, "hit": 5, "miss": 0,
                                  "day": 5, "night": 0})
        server._save_on_exit()                      # the next one finishes it
        dense = server._dense_hours(self._rows(), 2)
        self.assertEqual(sum(h["requests"] for h in dense), 11)


class NotFoundsAreCountedSeparately(unittest.TestCase):
    """A request for a place that doesn't exist bypasses _tally, so it landed
    in the header's total and in no chart, ever. It gets its own field rather
    than being folded into `requests`: it is neither a cache hit nor a miss
    and happens neither by day nor by night, so counting it as a request
    would skew every ratio taken against one."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        self._hour_stat = server._hour_stat.copy()
        self._hour_key = server._hour_key
        self.addCleanup(self._restore)
        server._hour_stat.clear()

    def _restore(self):
        server._hour_stat.clear()
        server._hour_stat.update(self._hour_stat)
        server._hour_key = self._hour_key

    def test_an_unknown_place_lands_in_notfound_not_in_requests(self):
        before = server._stat["requests"]
        resp = self.client.get("/Nowhereville", headers=TERMINAL)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(server._hour_stat["notfound"], 1)
        self.assertEqual(server._hour_stat["requests"], 0)
        # Still in the running total, which is what makes the two
        # reconcilable: header requests == log requests + log notfounds.
        self.assertEqual(server._stat["requests"], before + 1)

    def test_a_404_advances_the_hour_before_counting_itself(self):
        # This path never goes through _tally, so nothing else here rolls the
        # hour. Without the roll a 404 arriving in a quiet stretch is filed
        # under whatever hour the last real request was in.
        stale = (dt.datetime.utcnow() - dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:00")
        server._hour_key = stale
        self.client.get("/Nowhereville", headers=TERMINAL)
        self.assertNotEqual(server._hour_key, stale)
        self.assertEqual(server._hour_key,
                         dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00"))

    def test_notfound_reaches_the_log_the_charts_and_the_tables(self):
        server._hour_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._hour_stat.update({"requests": 2, "hit": 2, "miss": 0,
                                  "day": 2, "night": 0, "notfound": 3})
        self.assertEqual(server.stats_hourly_json()["hours"][-1]["notfound"], 3)
        self.assertIn("404", server.stats_hourly_text())
        self.assertIn("404", server.stats_daily_text())
        self.assertEqual(server.stats_daily_json()["days"][-1]["notfound"], 3)

    def test_an_hour_with_no_404s_keeps_the_key_out_of_the_log(self):
        # The log is never trimmed, so a key on every line of it is a cost
        # paid forever for a field most hours have nothing to say about.
        orig = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig)
        server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(), "hourly.jsonl")
        hour = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
        server._flush_hour(hour, server.Counter({"requests": 1, "hit": 1}))
        rows = server._read_hourly_history(days=1)
        self.assertNotIn("notfound", rows[0])
        # and a reader still gets a number for it
        self.assertEqual(server._dense_hours(rows, 1)[-1]["notfound"], 0)


class PlaintextCharts(unittest.TestCase):
    """The counters on /stats are a running total with no time axis, so they
    cannot answer "is it growing". These charts add one, drawn out of the
    hourly log -- which has holes in it, and that is the whole difficulty."""

    def _hours(self, spec, end):
        """spec: {hours-ago: requests}. Everything else is absent from the
        log entirely, the way a real idle hour is."""
        return [dict(hour=(end - dt.timedelta(hours=ago)).strftime("%Y-%m-%dT%H:00"),
                     requests=n, hit=n // 2, miss=n - n // 2, day=0, night=n)
                for ago, n in sorted(spec.items(), reverse=True)]

    def test_missing_hours_are_zero_filled_not_skipped(self):
        # _flush_hour writes nothing for an hour with no traffic and
        # _roll_hour only fires on a request, so an idle stretch leaves no
        # line at all. Read straight off the log the x-axis would be "rows
        # in the file", and two neighbouring columns could be a night apart.
        end = dt.datetime(2026, 8, 3, 12, 0)
        rows = self._hours({5: 10, 1: 4}, end)
        dense = server._dense_hours(rows, 6, end=end)
        self.assertEqual([e["requests"] for e in dense], [10, 0, 0, 0, 4, 0])
        self.assertEqual([e["recorded"] for e in dense],
                         [True, False, False, False, True, False])
        # The axis spans elapsed time, so its length is the window, not the
        # number of rows that happened to be in the log.
        self.assertEqual(len(dense), 6)

    def test_a_zero_hour_draws_blank_never_a_stub(self):
        # An hour with no requests and an hour with one request must not
        # look the same, which a minimum-one-pixel bar would do to them.
        lines = server._bar_chart([0, 1, 0, 8], lambda i: "", tick=1)
        bottom = lines[server.CHART_ROWS - 1]
        body = bottom[server.CHART_PAD + 2:]
        self.assertEqual(body[0], " ")
        self.assertNotEqual(body[1], " ")
        self.assertEqual(body[2], " ")
        self.assertNotEqual(body[3], " ")

    def test_chart_of_an_entirely_idle_window_says_so(self):
        end = dt.datetime(2026, 8, 3, 12, 0)
        dense = server._dense_hours([], 6, end=end)
        out = "\n".join(server._chart_block(dense, server._hour_tick, "hour", "6 h"))
        self.assertIn("no requests recorded in this window", out)
        self.assertIn("6 idle hour(s), shown blank", out)

    def test_the_block_is_the_same_height_whatever_the_data(self):
        # A page that jumps by eight lines depending on how quiet the window
        # was is worse than one with an empty chart in it, and the two charts
        # on /stats have to sit at the same height as each other.
        end = dt.datetime(2026, 8, 3, 12, 0)
        empty = server._dense_hours([], 12, end=end)
        busy = server._dense_hours(self._hours({i: i * 3 for i in range(12)}, end),
                                   12, end=end)
        one = server._dense_hours(self._hours({4: 1}, end), 12, end=end)
        heights = {len(server._chart_block(d, server._hour_tick, "hour", "12 h"))
                   for d in (empty, busy, one)}
        self.assertEqual(len(heights), 1)
        # And the chart itself is CHART_ROWS tall plus an axis, not collapsed.
        self.assertEqual(sum(1 for l in server._bar_chart([0] * 6, lambda i: "")
                             if l.endswith("┤" + " " * 6)), server.CHART_ROWS)

    def test_idle_hours_are_counted_in_the_caption(self):
        end = dt.datetime(2026, 8, 3, 12, 0)
        dense = server._dense_hours(self._hours({5: 10, 1: 4}, end), 6, end=end)
        out = "\n".join(server._chart_block(dense, server._hour_tick, "hour", "6 h"))
        self.assertIn("4 idle hour(s), shown blank", out)

    def test_duplicate_log_lines_for_one_hour_are_summed(self):
        # A restart flushes the partial hour it was in, then the next
        # process flushes the rest of that same hour when it rolls. Keying a
        # plain dict on the hour threw the first half away.
        end = dt.datetime(2026, 8, 3, 12, 0)
        hour = (end - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")
        rows = [dict(hour=hour, requests=6, hit=2, miss=4, day=1, night=5),
                dict(hour=hour, requests=4, hit=3, miss=1, day=0, night=4)]
        dense = server._dense_hours(rows, 2, end=end)
        self.assertEqual(dense[0]["requests"], 10)
        self.assertEqual(dense[0]["hit"], 5)

    def test_days_roll_up_out_of_the_hourly_log(self):
        # There is no daily log. The hourly file is never trimmed, so
        # grouping it by date is the entire implementation.
        rows = [dict(hour="2026-08-02T09:00", requests=4, hit=1, miss=3, day=4, night=0),
                dict(hour="2026-08-02T22:00", requests=6, hit=5, miss=1, day=0, night=6),
                dict(hour="2026-08-03T01:00", requests=2, hit=0, miss=2, day=0, night=2)]
        days = server._dense_days(rows, 3, end=dt.date(2026, 8, 3))
        self.assertEqual([e["date"] for e in days],
                         ["2026-08-01", "2026-08-02", "2026-08-03"])
        self.assertEqual([e["requests"] for e in days], [0, 10, 2])
        # `hours` is hours the log recorded, not hours that had traffic.
        self.assertEqual([e["hours"] for e in days], [0, 2, 1])
        self.assertEqual([e["recorded"] for e in days], [False, True, True])

    def test_long_windows_bucket_instead_of_overflowing_the_width(self):
        # 720 hours cannot be 720 columns. Buckets sum rather than average,
        # so the y-axis stays a real number you can check against the total.
        end = dt.datetime(2026, 8, 3, 12, 0)
        dense = server._dense_hours(self._hours({i: 1 for i in range(720)}, end),
                                    720, end=end)
        groups, per = server._chunks(dense, server.CHART_COLS)
        self.assertLessEqual(len(groups), server.CHART_COLS)
        self.assertEqual(sum(sum(e["requests"] for e in g) for g in groups), 720)
        self.assertGreater(per, 1)
        for line in server._chart_block(dense, server._hour_tick, "hour", "720 h",
                                        tick_every=server._hour_tick_every):
            self.assertLessEqual(len(line), 80)

    def test_sparkline_blanks_hours_with_no_ratio_to_take(self):
        # An hour with no requests has no hit rate. That is not 0%. Every row
        # keeps its full width so the percentage after it stays in column.
        self.assertEqual(server._spark_rows([None, None]), ["  ", "  "])
        rows = server._spark_rows([10.0, None, 90.0])
        for row in rows:
            self.assertEqual(row[1], " ")
            self.assertEqual(len(row), 3)
        for row in server._spark_rows([10.0, None, 90.0], width=2):
            self.assertEqual(len(row), 6)

    def test_sparkline_is_two_rows_tall(self):
        self.assertEqual(server.SPARK_ROWS, 2)
        self.assertEqual(len(server._spark_rows([50.0])), server.SPARK_ROWS)
        # A labelled pair is that many lines, label and number on the last.
        pair = server._spark_pair("hit%", [50.0, 90.0], 90.0, 1)
        self.assertEqual(len(pair), server.SPARK_ROWS)
        self.assertNotIn("hit%", pair[0])
        self.assertIn("hit%", pair[-1])
        self.assertTrue(pair[-1].endswith("90%"))

    def test_sparkline_is_scaled_to_100_percent_not_to_itself(self):
        # These are percentages, so height has to mean the value. Scaling to
        # the series' own range made a flat 88-91% hit rate look like a
        # mountain range and made two rows at different levels look alike.
        top, bottom = server._spark_rows([0.0, 100.0])
        self.assertEqual(bottom[1], "█")          # 100% fills both rows
        self.assertEqual(top[1], "█")
        self.assertEqual(top[0], " ")             # 0% reaches neither
        # 50% is exactly half height: full bottom row, empty top row.
        top, bottom = server._spark_rows([50.0])
        self.assertEqual(bottom, "█")
        self.assertEqual(top, " ")
        # Two low values stay low instead of being stretched to fill.
        top, bottom = server._spark_rows([10.0, 20.0])
        self.assertEqual(top, "  ")
        self.assertNotIn("█", bottom)
        # A real 0% is the shortest bar, still distinct from the blank None.
        self.assertEqual(server._spark_rows([0.0, None])[-1],
                         server._BLOCKS[1] + " ")

    def test_ratio_is_none_where_the_denominator_is_zero(self):
        groups = [[dict(requests=0, hit=0)], [dict(requests=4, hit=1)]]
        self.assertEqual(server._ratio(groups, "hit"), [None, 25.0])

    def test_hourly_table_marks_the_gap_instead_of_jumping_silently(self):
        # A silent jump between two rows reads as "no data"; a marker reads
        # as "quiet". Different claims.
        gap = server._idle_gap("2026-08-02T09:00", "2026-08-02T15:00")
        self.assertIn("5 hour(s) with no requests", gap)
        self.assertIsNone(server._idle_gap("2026-08-02T09:00", "2026-08-02T10:00"))
        # Duplicate lines for the same hour are not a gap.
        self.assertIsNone(server._idle_gap("2026-08-02T09:00", "2026-08-02T09:00"))

    def test_stats_page_carries_both_charts(self):
        text = server.stats_text()
        self.assertIn(f"LAST {server.CHART_HOURS} H", text)
        self.assertIn(f"LAST {server.CHART_DAYS} D", text)
        self.assertIn("/stats/daily", text)
        self.assertIn("/stats/hourly", text)

    def test_the_two_charts_sit_side_by_side_on_stats(self):
        text = server.stats_text()
        # Same line, hours left of days -- not stacked.
        title = next(l for l in text.splitlines() if "LAST 48 H" in l)
        self.assertIn("LAST 30 D", title)
        self.assertLess(title.index("LAST 48 H"), title.index("LAST 30 D"))
        # Both charts' sparklines land on the same two lines too.
        sparks = [l for l in text.splitlines() if l.lstrip().startswith("hit%")]
        self.assertEqual(len(sparks), 1)
        self.assertEqual(sparks[0].count("hit%"), 2)

    def test_side_by_side_puts_the_right_block_at_a_fixed_column(self):
        # Padded to the left block's widest line, so the right chart starts
        # in the same column on every row however the numbers come out.
        out = server._side_by_side(["a", "wide left line", "b"],
                                   ["one", "two", "three"])
        starts = {l.index(r) for l, r in zip(out, ("one", "two", "three"))}
        self.assertEqual(len(starts), 1)

    def test_side_by_side_pads_a_shorter_block(self):
        out = server._side_by_side(["a", "b", "c"], ["x"])
        self.assertEqual(len(out), 3)
        self.assertTrue(out[0].endswith("x"))

    def test_one_column_is_one_hour_and_one_day_on_stats(self):
        # No bucketing on /stats: the window is the column count.
        hourly = server._hourly_chart(cols=server.CHART_HOURS, legend=False)
        daily = server._daily_chart(cols=server.CHART_DAYS, width=1, legend=False)
        self.assertIn(f"per hour · last {server.CHART_HOURS} h".upper(), hourly[0])
        self.assertIn(f"per day · last {server.CHART_DAYS} d".upper(), daily[0])
        # Axis line is the gutter plus one character per hour / per day.
        axis = next(l for l in hourly if l.lstrip().startswith("0 ┼"))
        self.assertEqual(len(axis) - (server.CHART_PAD + 2), server.CHART_HOURS)
        axis = next(l for l in daily if l.lstrip().startswith("0 ┼"))
        self.assertEqual(len(axis) - (server.CHART_PAD + 2), server.CHART_DAYS)

    def test_daily_page_shows_every_day_including_the_empty_ones(self):
        text = server.stats_daily_text(days=5)
        self.assertIn("day (UTC)", text)
        today = dt.datetime.utcnow().date()
        for i in range(5):
            self.assertIn((today - dt.timedelta(days=i)).isoformat(), text)

    def test_daily_page_dashes_hit_rate_on_a_day_with_no_requests(self):
        # A day with no requests has no hit rate. Printing 0.0% claims every
        # request that day missed the cache, when there were none.
        rows = [dict(hour="2026-08-03T09:00", requests=4, hit=4, miss=0,
                     day=4, night=0)]
        entries = server._dense_days(rows, 2, end=dt.date(2026, 8, 3))
        blank, busy = entries
        self.assertEqual(blank["requests"], 0)
        self.assertEqual(busy["requests"], 4)
        # Rebuilt the way stats_daily_text formats it, so the assertion is
        # about the rule rather than about where the column happens to sit.
        self.assertEqual([("-" if not e["requests"]
                           else f"{100 * e['hit'] / e['requests']:.1f}%")
                          for e in entries], ["-", "100.0%"])

    def test_daily_page_with_an_empty_log_says_so(self):
        orig_log = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig_log)
        server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(), "empty.jsonl")
        orig = server._hour_stat.copy()
        self.addCleanup(lambda: (server._hour_stat.clear(),
                                 server._hour_stat.update(orig)))
        server._hour_stat.clear()
        self.assertIn("no data yet", server.stats_daily_text(days=3))


class WorldMap(unittest.TestCase):
    """The dotted map on /stats. The land mask is precomputed by
    build_worldmap.py from real country polygons; these check the projection,
    the heat ramp and the degradations."""

    def setUp(self):
        self._orig = server._geo_hits.copy()
        self.addCleanup(self._restore)
        server._geo_hits.clear()

    def _restore(self):
        server._geo_hits.clear()
        server._geo_hits.update(self._orig)

    def test_mask_matches_its_declared_size(self):
        rows, w, h, top, bot = server._load_worldmap()
        self.assertEqual(len(rows), h)
        self.assertEqual({len(r) for r in rows}, {w})
        self.assertGreater(top, bot)
        # Some land, and not all land.
        dots = sum(r.count("#") for r in rows)
        self.assertGreater(dots, 1000)
        self.assertLess(dots, w * h)

    def test_known_places_land_in_the_right_cell(self):
        _rows, w, h, top, bot = server._load_worldmap()
        zurich = server._map_cell(47.37, 8.55, w, h, top, bot)
        sydney = server._map_cell(-33.87, 151.21, w, h, top, bot)
        lima = server._map_cell(-12.05, -77.04, w, h, top, bot)
        # Sydney is south and east of Zurich; Lima is south and west.
        self.assertGreater(sydney[0], zurich[0])
        self.assertGreater(sydney[1], zurich[1])
        self.assertGreater(lima[0], zurich[0])
        self.assertLess(lima[1], zurich[1])
        # Greenwich sits on the horizontal midline of the grid.
        self.assertEqual(server._map_cell(0.0, 0.0, w, h, top, bot)[1], w // 2)

    def test_latitudes_outside_the_clipped_band_are_dropped(self):
        _rows, w, h, top, bot = server._load_worldmap()
        # The mask stops at 83N/56S. Antarctica has nowhere to go, and
        # silently clamping it to the bottom row would invent a location.
        self.assertIsNone(server._map_cell(-89.0, 0.0, w, h, top, bot))
        self.assertIsNone(server._map_cell(89.0, 0.0, w, h, top, bot))
        self.assertIsNotNone(server._map_cell(0.0, 0.0, w, h, top, bot))

    def test_coordinate_requests_bin_like_city_ones(self):
        # A request for "47.37,8.55" has no city name to key on, so the map
        # keys on the resolved position instead.
        _rows, w, h, top, bot = server._load_worldmap()
        server._geo_hits.update({"47,9": 5})
        heat = server._map_heat(w, h, top, bot)
        self.assertEqual(heat[server._map_cell(47.0, 9.0, w, h, top, bot)], 5)

    def test_malformed_geo_keys_are_skipped_not_fatal(self):
        _rows, w, h, top, bot = server._load_worldmap()
        server._geo_hits.update({"47,9": 3, "rubbish": 9, "": 1, "1,2,3": 4})
        heat = server._map_heat(w, h, top, bot)
        self.assertEqual(sum(heat.values()), 3)

    def test_traffic_over_water_still_gets_a_dot(self):
        # Reykjavik, Valletta and Honolulu all land on cells the mask calls
        # sea -- the polygons are simplified and an island can be smaller
        # than a two-degree cell. Skipping them made a third of real traffic
        # invisible, so a cell with requests is drawn whether or not the
        # mask agrees there is land under it.
        rows, w, h, top, bot = server._load_worldmap()
        land = {(r, c) for r, row in enumerate(rows)
                for c, ch in enumerate(row) if ch != " "}
        sea = next((r, c) for r in range(h) for c in range(w)
                   if (r, c) not in land)
        lat = top - (sea[0] + 0.5) * (top - bot) / h
        lon = -180 + (sea[1] + 0.5) * 360 / w
        server._geo_hits.update({f"{round(lat)},{round(lon)}": 9})
        server._heat_cache = (0.0, None, None)
        cell = server._map_cell(round(lat), round(lon), w, h, top, bot)
        line = server.api.strip_ansi(server._world_map()[cell[0]])
        self.assertEqual(line[cell[1]], server.MAP_DOT)
        self.assertIn(f'id="d{cell[0]}_{cell[1]}"', server._map_html())

    def test_empty_ocean_is_still_empty(self):
        # Only cells with traffic; the rest of the sea stays background.
        server._geo_hits.update({"47,9": 4})
        server._heat_cache = (0.0, None, None)
        plain = [server.api.strip_ansi(r) for r in server._world_map()]
        _rows, w, h, top, bot = server._load_worldmap()
        r, c = server._map_cell(0.0, -150.0, w, h, top, bot)   # mid-Pacific
        self.assertTrue(len(plain[r]) <= c or plain[r][c] == " ")

    def test_a_named_city_lands_on_the_map_like_a_coordinate(self):
        # Both go through r.place, so the map never sees the difference
        # between /Tokyo and /35.69,139.69.
        client = TestClient(server.app)
        with client:
            server._geo_hits.clear()
            client.get("/Tokyo", headers=TERMINAL)
            by_name = dict(server._geo_hits)
            server._geo_hits.clear()
            client.get("/35.69,139.69", headers=TERMINAL)
            by_coords = dict(server._geo_hits)
        self.assertTrue(by_name)
        self.assertEqual(set(by_name), set(by_coords))

    def test_the_ramp_spreads_even_when_one_cell_dominates(self):
        # A log scale collapses here: with a busiest of 300, cells on 5 and
        # on 1 both land on the palest step and the map is one red dot in a
        # field of white. Ranking uses the whole ramp whatever the spread.
        server._geo_hits.update({"47,9": 300, "36,140": 6, "52,0": 5,
                                 "41,-74": 4, "-12,-77": 3, "60,11": 3,
                                 "30,31": 2, "-34,151": 1})
        server._heat_cache = (0.0, None, None)
        _rows, w, h, top, bot = server._load_worldmap()
        shade, _heat = server._map_shader(w, h, top, bot)
        got = {}
        for key, n in server._geo_hits.items():
            lat, lon = (float(v) for v in key.split(","))
            got[n] = shade(*server._map_cell(lat, lon, w, h, top, bot))
        self.assertEqual(got[300], len(server.MAP_RAMP) - 1)   # busiest is red
        self.assertGreaterEqual(len(set(got.values())), 5)     # ramp is used
        # Monotonic: more requests never gets a cooler colour.
        ordered = [got[n] for n in sorted(got)]
        self.assertEqual(ordered, sorted(ordered))

    def test_equal_counts_get_equal_colours(self):
        # Ranking runs over distinct values, not over cells, so a tie cannot
        # straddle a colour boundary.
        server._geo_hits.update({"47,9": 50, "36,140": 7, "52,0": 7,
                                 "41,-74": 7, "-34,151": 1})
        server._heat_cache = (0.0, None, None)
        _rows, w, h, top, bot = server._load_worldmap()
        shade, _heat = server._map_shader(w, h, top, bot)
        tied = [shade(*server._map_cell(float(k.split(",")[0]),
                                        float(k.split(",")[1]), w, h, top, bot))
                for k in ("36,140", "52,0", "41,-74")]
        self.assertEqual(len(set(tied)), 1)

    def test_a_single_busy_cell_is_the_maximum(self):
        server._geo_hits.update({"47,9": 12})
        server._heat_cache = (0.0, None, None)
        _rows, w, h, top, bot = server._load_worldmap()
        shade, _heat = server._map_shader(w, h, top, bot)
        self.assertEqual(shade(*server._map_cell(47.0, 9.0, w, h, top, bot)),
                         len(server.MAP_RAMP) - 1)

    def test_busier_places_get_a_warmer_colour(self):
        server._geo_hits.update({"47,9": 5000, "-34,151": 5})
        text = "\n".join(server._world_map())
        codes = [int(m) for m in re.findall(r"\033\[38;5;(\d+)m", text)]
        self.assertIn(server.MAP_RAMP[0], codes)      # untouched land is white
        self.assertIn(server.MAP_RAMP[-1], codes)     # the busiest cell is red
        # Zurich outranks Sydney, so it must sit further along the ramp.
        _rows, w, h, top, bot = server._load_worldmap()
        heat = server._map_heat(w, h, top, bot)
        zh = heat[server._map_cell(47.0, 9.0, w, h, top, bot)]
        syd = heat[server._map_cell(-34.0, 151.0, w, h, top, bot)]
        self.assertGreater(zh, syd)

    def test_ocean_stays_blank(self):
        server._geo_hits.update({"47,9": 10})
        plain = [server.api.strip_ansi(r) for r in server._world_map()]
        # Mid-Pacific, far from any coast, on the row through the equator.
        _r, w, h, top, bot = server._load_worldmap()
        r, c = server._map_cell(0.0, -150.0, w, h, top, bot)
        line = plain[r]
        self.assertTrue(len(line) <= c or line[c] == " ")

    def test_map_reads_fine_with_the_colour_stripped(self):
        server._geo_hits.update({"47,9": 10})
        plain = server.api.strip_ansi("\n".join(server._world_map()))
        self.assertNotIn("\033", plain)
        self.assertIn(server.MAP_DOT, plain)

    def test_no_mask_file_means_no_map_rather_than_a_500(self):
        orig = server.WORLDMAP_FILE
        cached = server._worldmap
        self.addCleanup(setattr, server, "WORLDMAP_FILE", orig)
        self.addCleanup(setattr, server, "_worldmap", cached)
        server.WORLDMAP_FILE = os.path.join(tempfile.mkdtemp(), "nope.json")
        server._worldmap = None
        self.assertIsNone(server._load_worldmap())
        self.assertEqual(server._world_map(), [])
        self.assertEqual(server._map_block(), [])
        # And the page still renders.
        self.assertIn("skymap.sh:", server.stats_text())

    def test_geo_counter_survives_a_restart(self):
        orig = server.STATS_STATE_FILE
        self.addCleanup(setattr, server, "STATS_STATE_FILE", orig)
        server.STATS_STATE_FILE = os.path.join(tempfile.mkdtemp(), "state.json")
        server._geo_hits.update({"47,9": 7, "-34,151": 2})
        server._save_stats_state()
        server._geo_hits.clear()
        server._load_stats_state()
        self.assertEqual(server._geo_hits["47,9"], 7)
        self.assertEqual(server._geo_hits["-34,151"], 2)

    def test_the_map_is_on_the_stats_page(self):
        server._geo_hits.update({"47,9": 4})
        text = server.stats_text()
        self.assertIn("WHERE REQUESTS COME FROM", text)
        self.assertIn("distinct location(s)", text)


class LiveMap(unittest.TestCase):
    """/stats/live and the per-dot map the browser flashes. curl must not be
    affected by any of it."""

    @classmethod
    def setUpClass(cls):
        client_cm = TestClient(server.app)
        cls.client = client_cm.__enter__()
        cls.addClassCleanup(client_cm.__exit__, None, None, None)

    def setUp(self):
        self._hits = server._geo_hits.copy()
        self._recent = list(server._geo_recent)
        self.addCleanup(self._restore)
        server._geo_hits.clear()
        server._geo_recent.clear()
        server._heat_cache = (0.0, None, None)

    def _restore(self):
        server._geo_hits.clear()
        server._geo_hits.update(self._hits)
        server._geo_recent.clear()
        server._geo_recent.extend(self._recent)
        server._heat_cache = (0.0, None, None)

    def test_since_filters_out_what_the_caller_already_saw(self):
        now = time.time()
        server._geo_recent.extend([(now - 60, 47, 9), (now - 1, -34, 151)])
        server._geo_hits.update({"47,9": 5, "-34,151": 5})
        everything = server.stats_live_json(0.0)["flash"]
        self.assertEqual(len(everything), 2)
        recent = server.stats_live_json(now - 10)["flash"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(server.stats_live_json(now + 1)["flash"], [])

    def test_flash_carries_the_colour_the_dot_settles_to(self):
        # The bin key and the recent-buffer entry have to round identically.
        # A map column is ~2 degrees, so 47.37 and 47 can be different
        # columns, and then the flashed cell has no heat and settles white.
        now = time.time()
        server._geo_hits.update({"47,9": 500, "-34,151": 1})
        server._geo_recent.extend([(now, 47, 9), (now, -34, 151)])
        flash = {(r, c): i for r, c, i in server.stats_live_json(0.0)["flash"]}
        _rows, w, h, top, bot = server._load_worldmap()
        busy = server._map_cell(47.0, 9.0, w, h, top, bot)
        quiet = server._map_cell(-34.0, 151.0, w, h, top, bot)
        self.assertEqual(flash[busy], len(server.MAP_RAMP) - 1)
        self.assertGreater(flash[busy], flash[quiet])

    def test_the_poll_carries_the_two_lines_that_go_stale_fastest(self):
        # Finished strings, not numbers: the server owns the wording and the
        # arithmetic, and the page only swaps text.
        server._geo_hits.update({"47,9": 5, "-34,151": 2})
        server._places.update({"Zurich": 5, "Sydney": 2})
        server._heat_cache = (0.0, None, None)
        d = server.stats_live_json(0.0)
        self.assertEqual(d["head"], server._headline())
        self.assertIn("requests over", d["head"])
        self.assertIn("2 distinct location(s)", d["legend"])
        self.assertIn("busiest: Zurich (", d["legend"])
        # The raw numbers were here first and stay for anything scripting it.
        self.assertEqual(d["distinct"], 2)

    def test_the_page_ships_the_same_two_lines_the_poll_will_replace(self):
        # If the ids or the wording drift apart, the first poll silently
        # rewrites nothing and the numbers quietly stop moving.
        server._geo_hits.update({"47,9": 3})
        server._places.update({"Zurich": 3})
        server._heat_cache = (0.0, None, None)
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertIn('<span id="live-head">skymap.sh:', body)
        self.assertIn('<span id="live-legend">1 distinct location(s)', body)
        for el in ("live-head", "live-legend"):
            self.assertIn(f"retext('{el}'", body)
        # curl gets the lines themselves, no markers and no spans.
        text = self.client.get("/stats", headers=TERMINAL).text
        self.assertIn("skymap.sh:", text)
        self.assertIn("distinct location(s)", text)
        self.assertNotIn("live-head", text)

    def test_the_buffer_forgets_the_oldest(self):
        cap = server._geo_recent.maxlen
        for i in range(cap + 50):
            server._geo_recent.append((float(i), 47, 9))
        self.assertEqual(len(server._geo_recent), cap)
        self.assertEqual(server._geo_recent[0][0], 50.0)

    def test_positions_off_the_map_are_dropped_not_clamped(self):
        server._geo_recent.append((time.time(), -89, 0))   # Antarctica
        self.assertEqual(server.stats_live_json(0.0)["flash"], [])

    def test_junk_since_is_treated_as_from_the_beginning(self):
        server._geo_recent.append((time.time(), 47, 9))
        server._geo_hits.update({"47,9": 1})
        resp = self.client.get("/stats/live?since=abc")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["flash"]), 1)

    def test_route_counts_itself_and_is_not_cached(self):
        before = server._stat["page:stats.live"]
        resp = self.client.get("/stats/live")
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertEqual(server._stat["page:stats.live"], before + 1)

    def _throttle_after(self, n):
        """Drop the stats allowance to n for one test. setUpModule lifts it
        to a million so unrelated tests never trip it; these three are about
        the limit itself, so they need it back."""
        for name, value in (("STATS_RATE", n), ("STATS_BURST", n)):
            self.addCleanup(setattr, server, name, getattr(server, name))
            setattr(server, name, value)
        server._stats_buckets.clear()
        self.addCleanup(server._stats_buckets.clear)
        self.addCleanup(server._buckets.clear)

    def test_polling_draws_on_the_looser_stats_allowance(self):
        # An open tab polls 20 times a minute. Against the chart allowance of
        # 30 that would throttle the reader's actual sky requests, so the
        # stats family has its own, larger bucket.
        server._stats_buckets.clear()
        resp = self.client.get("/stats/live")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-ratelimit-limit"],
                         str(server.STATS_RATE))
        # The shipped defaults, not the ones setUpModule lifted.
        src = open(os.path.join(os.path.dirname(os.path.abspath(server.__file__)),
                                "server.py")).read()
        rate = int(re.search(r"^RATE = (\d+)", src, re.M).group(1))
        stats_rate = int(re.search(r"^STATS_RATE = (\d+)", src, re.M).group(1))
        self.assertGreater(stats_rate, rate)
        self.assertGreater(stats_rate, 20 * 2)   # room over a polling tab

    def test_hammering_stats_does_not_lock_you_out_of_the_charts(self):
        # Separate buckets, so abuse of one cannot deny the other.
        self._throttle_after(5)
        for _ in range(6):
            self.client.get("/stats/live")
        self.assertEqual(self.client.get("/stats/live").status_code, 429)
        self.assertEqual(self.client.get("/Zurich", headers=TERMINAL).status_code,
                         200)

    def test_the_stats_throttle_says_something_that_makes_sense(self):
        # THROTTLED is written for someone looping a chart -- on /stats it
        # would suggest watching a place they never asked for.
        self._throttle_after(5)
        for _ in range(6):
            self.client.get("/stats/live")
        resp = self.client.get("/stats/live")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("/stats", resp.text)
        self.assertNotIn("watch -n", resp.text)
        self.assertIn("retry-after", resp.headers)

    def test_browser_gets_addressable_dots_and_curl_does_not(self):
        server._geo_hits.update({"47,9": 3})
        server._heat_cache = (0.0, None, None)
        html_body = self.client.get("/stats", headers=BROWSER).text
        self.assertRegex(html_body, r'class="d h\d s\d" id="d\d+_\d+"')
        self.assertIn("/stats/live?since=", html_body)
        text = self.client.get("/stats", headers=TERMINAL).text
        self.assertNotIn("<i ", text)
        self.assertNotIn("stats/live", text)

    def test_colour_lives_in_classes_not_on_every_dot(self):
        # Seven colours, thousands of dots -- repeating the hex on each one
        # costs about 20 bytes a dot to say nothing new.
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertNotIn('style="color:#', server._map_html())
        for i in range(len(server.MAP_RAMP)):
            self.assertIn(f".h{i}{{color:", body)

    def test_a_busier_cell_gets_a_bigger_dot_as_well_as_a_warmer_one(self):
        # Size doubles up on colour: on a map this dense a warm dot is easy
        # to lose among its neighbours, a bigger one less so.
        body = self.client.get("/stats", headers=BROWSER).text
        for i, s in enumerate(server.MAP_SIZES):
            self.assertIn(f".s{i}{{--s:{s:g}}}", body)
        # Land nobody has asked from is nearly every dot on the map, and
        # swelling those would drown out the few that mean something.
        self.assertEqual(server.MAP_SIZES[0], 1.0)
        self.assertEqual(list(server.MAP_SIZES), sorted(server.MAP_SIZES))
        self.assertEqual(len(server.MAP_SIZES), len(server.MAP_RAMP))

    def test_a_dot_settles_back_to_the_size_its_total_deserves(self):
        # The flash used to leave an inline colour behind, which only worked
        # because size wasn't in play. Both now ride on the level classes,
        # so the settle has to put both back.
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertIn("e.className = 'd h' + l + ' s' + l;", body)
        self.assertNotIn("e.style.color", body)

    def test_dots_are_pinned_to_one_character_so_the_flash_cannot_shift_them(self):
        # The flash swaps in a wider glyph. Without a fixed advance width
        # that would shove the rest of the row sideways.
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertIn("width:1ch", body)
        self.assertIn("font-style:normal", body)   # <i> would italicise
        self.assertIn(server.MAP_FLASH_DOT, body)

    def test_polling_starts_after_the_dots_exist(self):
        # The script is injected into the drawer, which the parser reaches
        # before the <pre> holding the map. Starting immediately would find
        # no dots and never poll at all.
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertIn("DOMContentLoaded", body)
        # id="d\d+_\d+", not just 'id="d' -- the header's own #drawer-
        # trigger/#drawer-close also start with "d" and sit earlier still,
        # which isn't the same "before the map" this test actually cares
        # about.
        first_dot = re.search(r'id="d\d+_\d+"', body)
        self.assertIsNotNone(first_dot, "no map dot found in the response")
        self.assertLess(body.index("stats/live?since="), first_dot.start())

    def test_the_slot_marker_never_reaches_a_reader(self):
        for body in (self.client.get("/stats", headers=TERMINAL).text,
                     self.client.get("/stats", headers=BROWSER).text,
                     server.stats_text()):
            self.assertNotIn(server.MAP_SLOT, body)
            self.assertNotIn("\x00", body)

    def test_the_ramp_the_browser_gets_matches_the_server_palette(self):
        body = self.client.get("/stats", headers=BROWSER).text
        for n in server.MAP_RAMP:
            self.assertIn(server.api._xterm_hex(n), body)

    def test_heat_is_cached_but_not_forever(self):
        _rows, w, h, top, bot = server._load_worldmap()
        server._geo_hits.update({"47,9": 1})
        first, _t = server._cached_heat(w, h, top, bot)
        server._geo_hits.update({"47,9": 99})
        cached, _t = server._cached_heat(w, h, top, bot)
        self.assertEqual(cached, first)          # inside the TTL
        server._heat_cache = (time.time() - server.HEAT_TTL - 1,
                              *server._heat_cache[1:])
        fresh, _t = server._cached_heat(w, h, top, bot)
        self.assertNotEqual(fresh, first)        # expired, recomputed


class StatsDailyRoute(unittest.TestCase):
    """/stats/daily, the drill-down behind the 30-day chart on /stats."""

    @classmethod
    def setUpClass(cls):
        client_cm = TestClient(server.app)
        cls.client = client_cm.__enter__()
        cls.addClassCleanup(client_cm.__exit__, None, None, None)

    def test_plain_text_by_default(self):
        resp = self.client.get("/stats/daily", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers["content-type"])
        self.assertIn("daily stats", resp.text)

    def test_html_for_a_browser(self):
        resp = self.client.get("/stats/daily", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("skymap.sh: daily stats", resp.text)

    def test_json_view(self):
        resp = self.client.get("/stats/daily?format=json&days=4")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["days"]), 4)

    def test_days_is_clamped_and_survives_junk(self):
        self.assertEqual(len(self.client.get("/stats/daily?format=json&days=0")
                             .json()["days"]), 1)
        self.assertEqual(len(self.client.get("/stats/daily?format=json&days=abc")
                             .json()["days"]), server.CHART_DAYS)
        self.assertLessEqual(len(self.client.get("/stats/daily?format=json&days=99999")
                                 .json()["days"]), server.HOURLY_MAX_QUERY_DAYS)

    def test_the_route_counts_itself_on_stats(self):
        before = server._stat["page:stats.daily"]
        self.client.get("/stats/daily", headers=TERMINAL)
        self.assertEqual(server._stat["page:stats.daily"], before + 1)

    def test_not_cached_and_on_the_stats_allowance(self):
        server._stats_buckets.clear()
        resp = self.client.get("/stats/daily", headers=TERMINAL)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertEqual(resp.headers["x-ratelimit-limit"],
                         str(server.STATS_RATE))


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


class CacheKeyRespectsEveryRenderAffectingParam(unittest.TestCase):
    """_cache_key used to omit r.lines entirely -- a plain request and a
    ?nolines=1 request at the same place/time hashed to the identical key,
    so whichever hit the cache first silently answered both, and the 'l'
    shortcut appeared to do nothing. Regression coverage for that."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_nolines_actually_changes_the_rendered_chart(self):
        # A fixed, deterministic scene (astronomical positions don't depend
        # on "now") with a known-visible asterism -- Zurich at this exact
        # moment reliably shows the Big Dipper. Asserting on that label
        # directly, rather than just "the two responses differ", since a
        # trivial difference elsewhere (e.g. the "Share as a PNG" link,
        # which always carries nolines=1) would let a regression here pass
        # for the wrong reason.
        t = "2026-07-30T23:00"
        with_lines = self.client.get(f"/Zurich?t={t}", headers=TERMINAL).text
        without_lines = self.client.get(f"/Zurich?t={t}&nolines=1", headers=TERMINAL).text
        # Every character carries its own ANSI colour code, so the label
        # never appears as a contiguous substring in the raw response --
        # strip escapes first, same as server.py does for ?plain=1.
        self.assertIn("BIG DIPPER", server.api.strip_ansi(with_lines))
        self.assertNotIn("BIG DIPPER", server.api.strip_ansi(without_lines))

    def test_panel_actually_changes_the_rendered_layout(self):
        # Same bug, same fix, this time for r.panel: a plain request and a
        # ?panel=1 request at the same place/time/width used to hash to the
        # identical cache key, so whichever hit the cache first silently
        # answered both and the side panel appeared to do nothing.
        t = "2026-07-30T23:00"
        stacked = self.client.get(f"/Zurich?t={t}&w=150", headers=TERMINAL).text
        paneled = self.client.get(f"/Zurich?t={t}&w=150&panel=1", headers=TERMINAL).text
        # Both stack the inset for a terminal -- panel is a browser layout
        # instruction now, and a reader who cannot be handed positioned
        # boxes gets the pieces one after another either way. What must
        # still differ is the render itself, or one cache entry would answer
        # both: the paneled one carries the inset as its own block rather
        # than inside the chart, which moves where it lands in the text.
        self.assertNotEqual(stacked, paneled)
        for body in (stacked, paneled):
            self.assertNotIn("\x00", body)
            zenith_line = next(l for l in server.api.strip_ansi(body).split("\n")
                               if "zenith 70-90" in l)
            self.assertEqual(zenith_line.split("zenith 70-90")[0].strip(), "")


class KeyboardShortcuts(unittest.TestCase):
    """d/l read their target URLs, and z its landing URL for the arrow-key
    picker, from a small JS object (KBD) the server embeds per-page -- only
    the pages/states where a toggle actually means something should
    populate it, everything else gets {}."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_night_chart_page_offers_the_toggles(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn('"quadrant": "/Zurich?t=2026-07-30T23:00&quadrant"', resp.text)
        self.assertIn('"grid": "/Zurich?t=2026-07-30T23:00&quadrant"', resp.text)

    def test_day_view_offers_no_star_chart_toggles(self):
        # dso/quadrant don't apply to the Sun's-arc day view -- same gate
        # quadrant_btn's own disabled state already uses. Checking for the
        # JSON-key form (quote-colon-quote) specifically -- the bare word
        # "quadrant" also appears in the static hint text and JS comments on
        # every chart page regardless, which a plain substring check would
        # wrongly match.
        resp = self.client.get("/Zurich?t=2026-07-30T13:00", headers=BROWSER)
        self.assertNotIn('"quadrant": "', resp.text)
        self.assertNotIn('"grid": "', resp.text)

    def test_day_view_offers_the_golden_hour_toggle(self):
        # The mirror of the quadrant keys: golden hour is a daylight layer,
        # so 'g' is wired exactly where 'd' and 'z' are not.
        resp = self.client.get("/Zurich?t=2026-07-30T13:00", headers=BROWSER)
        self.assertIn('"golden": "/Zurich?t=2026-07-30T13:00&nogolden=1"', resp.text)

    def test_star_chart_offers_no_golden_toggle(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertNotIn('"golden": "', resp.text)

    def test_the_golden_toggle_turns_back_on_once_it_is_off(self):
        resp = self.client.get("/Zurich?t=2026-07-30T13:00&nogolden=1", headers=BROWSER)
        self.assertIn('"golden": "/Zurich?t=2026-07-30T13:00"', resp.text)

    def test_grid_toggle_stays_bare_even_when_already_zoomed_into_one_cell(self):
        # 'z' needs a "go to the bare grid" landing spot regardless of
        # whether the grid is currently off *or* already cropped to one
        # lettered cell -- api._quadrant_grid_url never carries the letter.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&quadrant=A", headers=BROWSER)
        self.assertIn('"grid": "/Zurich?t=2026-07-30T23:00&quadrant"', resp.text)

    def test_toggles_preserve_an_explicitly_picked_time(self):
        # The bug this guards against: dropping t= on a toggle click bounces
        # you back to "now", which can silently flip a picked nighttime view
        # to the daytime Sun's-arc view if it's actually daytime right now.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn('"quadrant": "/Zurich?t=2026-07-30T23:00&quadrant"', resp.text)

    def test_the_shortcut_hint_appears_on_a_chart_page(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('<p class="kbd-hint">', resp.text)

    def test_tab_reaches_the_one_search_bar_and_no_letter_duplicates_it(self):
        # Not in KBD (unconditional, same as the JS -- no server-side toggle
        # state involved), so check the hint text and the keydown handler
        # directly instead.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("<kbd>tab</kbd> search", resp.text)
        self.assertIn("e.key==='Tab'", resp.text)
        self.assertNotIn("<kbd>f</kbd> find", resp.text)
        # "f" meant "jump to the find field" and there is no find field any
        # more. It is not re-pointed at the search bar either: that would
        # spend a scarce single letter on a duplicate of tab.
        self.assertNotIn("e.key==='f'", resp.text)
        # "p" was dropped earlier for its own reason: a single letter that
        # jumps focus into a text field kills every shortcut pressed after it.
        self.assertNotIn("e.key==='p'", resp.text)
        self.assertNotIn("e.key==='/'", resp.text)

    def test_hint_and_js_bind_m_to_geolocation(self):
        # Same as p/f -- unconditional, no server-side toggle state, so
        # check the hint text and the keydown handler directly.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("<kbd>m</kbd> my location", resp.text)
        self.assertIn("e.key==='m'", resp.text)
        self.assertIn("navigator.geolocation", resp.text)
        self.assertIn("getCurrentPosition", resp.text)

    def test_m_shortcut_present_on_non_chart_pages_too(self):
        # Unlike d/l/z (which read from KBD, only populated on a chart
        # page), m has no server-side toggle state -- it's the same
        # unconditional JS on every page, same as p/f.
        for path in ("/catalog", "/legend", "/help"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn("e.key==='m'", resp.text, path)

    def test_d_binds_to_the_combined_quadrant_toggle_not_a_standalone_dso(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn("e.key==='d'&&KBD.quadrant", resp.text)
        self.assertNotIn("KBD.dso", resp.text)

    def test_z_and_arrow_keys_are_wired_and_q_is_gone(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn("e.key==='z'", resp.text)
        self.assertIn("ArrowLeft", resp.text)
        self.assertIn("ArrowRight", resp.text)
        self.assertIn("ArrowUp", resp.text)
        self.assertIn("ArrowDown", resp.text)
        self.assertNotIn("e.key==='q'", resp.text)
        self.assertNotIn("<kbd>q</kbd>", resp.text)

    def test_l_shortcut_is_gone(self):
        # Dropped -- no button/link ever exposed a lines toggle either, so
        # it was a keyboard-only feature nobody could discover. ?nolines=1
        # itself is untouched, still a real, working query param -- only
        # the dedicated keyboard binding and its now-unused URL-builder
        # (_nolines_toggle_url) are gone.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertNotIn("e.key==='l'", resp.text)
        self.assertNotIn("<kbd>l</kbd>", resp.text)
        self.assertNotIn('"nolines": "', resp.text)
        self.assertFalse(hasattr(server.api, "_nolines_toggle_url"))

    def test_other_pages_get_no_toggles_and_no_hint(self):
        # The .kbd-hint *style rule* is in every page's shared <style> block
        # regardless -- checking for the rendered <p class="kbd-hint"> tag
        # specifically is what actually distinguishes "hint shown" from not.
        for path in ("/catalog", "/legend", "/help", "/stats"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn("var KBD={};", resp.text, path)
            self.assertNotIn('<p class="kbd-hint">', resp.text, path)

    def test_help_documents_the_shortcuts(self):
        resp = self.client.get("/help", headers=TERMINAL)
        self.assertIn("KEYBOARD", resp.text)


class ControlsPanel(unittest.TestCase):
    """The explore form + toolbar are always visible on every page, chart
    included -- there used to be a '≡ controls' toggle that hid them behind
    a click on the chart view specifically; that's gone, so 'p'/'f' just
    focus the always-visible input directly, no open-the-panel-first step."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_chart_page_has_the_explore_form(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('id="explore"', resp.text)

    def test_no_toggle_button_or_hide_show_js_remain(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertNotIn('id="controls-toggle"', resp.text)
        self.assertNotIn('id="controls-panel"', resp.text)
        self.assertNotIn("openPanel", resp.text)
        self.assertNotIn("closePanel", resp.text)

    def test_other_pages_also_have_the_explore_form(self):
        for path in ("/catalog", "/legend", "/help", "/stats"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn('id="explore"', resp.text, path)
            self.assertNotIn('id="controls-toggle"', resp.text, path)


class HeaderIsAlwaysWide(unittest.TestCase):
    """The header (command bar + nav) sits outside .w/.w-wide entirely, so
    it never resizes between pages -- it used to be nested inside that div,
    which meant it stretched full-width on an auto-fit chart page (.w-wide)
    but was capped to 1200px on every other page (plain .w), visibly
    changing width/position depending on which page you were on."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_header_sits_before_the_width_wrapper_on_a_chart_page(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertLess(resp.text.index("<body>"), resp.text.index('class="header-row"'))
        self.assertLess(resp.text.index('class="header-row"'),
                        resp.text.index('class="w w-wide"'))

    def test_header_sits_before_the_width_wrapper_on_a_capped_page(self):
        resp = self.client.get("/catalog", headers=BROWSER)
        self.assertLess(resp.text.index("<body>"), resp.text.index('class="header-row"'))
        self.assertLess(resp.text.index('class="header-row"'), resp.text.index('class="w"'))


class ChartPreFontSizeScoping(unittest.TestCase):
    """#chart-pre is the same id every page's <pre> uses -- a bare
    #chart-pre{font-size:...} selector silently applies everywhere, not
    just the chart page it was meant for (bit the /stats live map once:
    a bigger font made its fixed-character-count ASCII grid wider in
    pixels, pushing it past the 1200px .w cap into a horizontal scroll
    that didn't exist before). .kbd-hint ~ #chart-pre is the actual
    "chart page only" scope, since SHORTCUTS_HINT (.kbd-hint) only
    renders there."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_rule_is_scoped_through_kbd_hint_not_bare_chart_pre(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn(".kbd-hint ~ #chart-pre{font-size:13px}", resp.text)
        self.assertNotIn(" #chart-pre{font-size:13px}", resp.text.replace(
            ".kbd-hint ~ #chart-pre{font-size:13px}", ""))

    def test_stats_page_has_no_kbd_hint_so_the_rule_does_not_apply(self):
        resp = self.client.get("/stats", headers=BROWSER)
        self.assertNotIn('class="kbd-hint"', resp.text)


RUNG_RE = re.compile(r'<pre class="chart-pre" data-cols="(\d+)"( data-panel="1")?>')
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s):
    """Character width of one rendered chart line, spans removed."""
    return TAG_RE.sub("", s)


def _rungs(text):
    """The (columns, panel) pairs a laddered page actually shipped."""
    return [(int(cols), bool(panel)) for cols, panel in RUNG_RE.findall(text)]


class WidthLadder(unittest.TestCase):
    """The plain horizon panorama ships every rung of api.CHART_LADDER in one
    response and lets a CSS container query pick one.

    This replaced an auto-fit script that measured the font with a hidden
    probe and then called location.replace() with a ?w= -- a second full page
    request per visit, which also meant _tally ran twice and every browser
    view was counted twice on /stats."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_plain_horizon_view_gets_the_wide_class_and_every_rung(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn('class="w w-wide"', resp.text)
        self.assertIn('<div id="chart-ladder">', resp.text)
        self.assertEqual(_rungs(resp.text),
                         [(cols, panel) for _min_ch, cols, panel in api.CHART_LADDER])

    def test_rungs_are_really_rendered_at_their_own_width(self):
        # The whole point: each rung is a distinct render, not the same
        # chart four times with a different data-cols attribute on it.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        bodies = re.findall(r'<pre class="chart-pre"[^>]*>(.*?)</pre>', resp.text, re.S)
        self.assertEqual(len(bodies), len(api.CHART_LADDER))
        widths = [max(len(strip_tags(b_line)) for b_line in body.split("\n"))
                  for body in bodies]
        # 60/60-with-panel/120/190 -- the panel rung is wider than the bare
        # 60 despite the same column count, and each step up is wider again.
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])
        self.assertLess(widths[2], widths[3])

    def test_no_duplicate_element_id_across_rungs(self):
        # An id has to be unique, which a repeated <pre id="chart-pre">
        # could not be -- that's why the rungs carry a class instead.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        body = resp.text.split("</head>", 1)[1]
        self.assertEqual(body.count('id="chart-pre"'), 0)

    def test_css_breakpoints_come_from_the_same_tuple_as_the_rungs(self):
        # The one way this can silently go wrong is CSS asking for a width
        # the server never rendered, so assert they share a source.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn("#chart-ladder{container-type:inline-size", resp.text)
        for i, (min_ch, _cols, _panel) in enumerate(api.CHART_LADDER):
            if min_ch is None:
                self.assertIn("#chart-ladder .chart-pre:nth-child(1){display:block}",
                              resp.text)
                continue
            self.assertIn(f"@container (min-width:{min_ch}ch)", resp.text)
            self.assertIn(f"#chart-ladder .chart-pre:nth-child({i + 1})"
                          "{display:block}", resp.text)

    def test_each_rung_fits_its_own_breakpoint(self):
        """A rung must be no wider than the container width that selects it.

        CHART_LADDER's breakpoints are measured widths, not arithmetic ones:
        the prose wraps at a fixed 76 characters with no panel (wider than a
        60-column chart), and the zenith inset adds 33ch rather than the
        43ch the reserving logic starts from. Deriving them instead of
        measuring made every rung switch ~10ch late. This renders each one
        and checks the real number, so changing the prose wrap or the inset
        fails here rather than quietly going back to charts that overflow
        the width that picked them.

        Checked over several places and dates, not one: a rung's width moves
        by a character or two with the sky being described, so a single
        sample hides off-by-ones (Zurich in August put the 60+panel rung at
        93ch; Tokyo in January renders the same rung 96ch wide).
        """
        for place, when in (("Zurich", "2026-07-30T23:00"),
                            ("Tokyo", "2026-01-15T20:00"),
                            ("Lima", "2026-11-03T04:00")):
            resp = self.client.get(f"/{place}?t={when}&night=1", headers=BROWSER)
            bodies = re.findall(r'<pre class="chart-pre"[^>]*>(.*?)</pre>',
                                resp.text, re.S)
            self.assertEqual(len(bodies), len(api.CHART_LADDER), place)
            for (min_ch, cols, panel), body in zip(api.CHART_LADDER, bodies):
                if min_ch is None:      # the default rung has no breakpoint
                    continue
                actual = max(len(strip_tags(line)) for line in body.split("\n"))
                self.assertLessEqual(
                    actual, min_ch,
                    f"{place} {when}: the {cols}-column rung (panel={panel}) "
                    f"renders {actual}ch wide but is selected at {min_ch}ch "
                    "-- it will overflow")

    def test_rung_breakpoints_and_widths_both_ascend(self):
        # A rung that is narrower than the one below it, or a breakpoint out
        # of order, would make the chart shrink as the window grows.
        breaks = [m for m, _c, _p in api.CHART_LADDER if m is not None]
        self.assertEqual(breaks, sorted(set(breaks)))
        used = [c + (33 if p else 0) for _m, c, p in api.CHART_LADDER]
        self.assertEqual(used, sorted(used))

    def test_every_rung_rule_has_the_same_specificity(self):
        # The bug this exists to prevent: :first-child is (1,2,0) and the
        # .chart-pre{display:none} inside an @container block is (1,1,0).
        # @container adds no specificity of its own, so the narrow rung won
        # at every width and the wider ones stacked underneath it -- three
        # charts on screen at 1400px, four at 2000px. Writing every rung
        # rule as :nth-child(k) makes them all (1,2,0), which leaves source
        # order to decide, which is the mechanism.
        css = api.chart_ladder_css()
        self.assertNotIn(":first-child", css)
        rung_rules = re.findall(r"#chart-ladder \.chart-pre(:[a-z-]+\([^)]*\))?"
                                r"\{display:(block|none)\}", css)
        self.assertTrue(rung_rules)
        for pseudo, _decl in rung_rules:
            self.assertTrue(pseudo and pseudo.startswith(":nth-child("),
                            f"display rule with no :nth-child() -- {pseudo!r} "
                            "is a different specificity to the others")

    def test_the_measure_and_reload_script_is_gone(self):
        # The regression this whole change exists to prevent coming back.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        for gone in ("applyFit", "computeFit", "location.replace", "var FIT_W"):
            self.assertNotIn(gone, resp.text, gone)

    def test_a_browser_object_page_is_tallied_once(self):
        # Was two: the page load, then the auto-fit reload going through
        # _tally a second time. One lookup, one count. The ladder renders
        # every width in one response now, so there is no second request.
        before = server._stat["requests"], server._hour_stat["object"]
        self.client.get("/Zurich/Venus?t=2026-07-30T23:00", headers=BROWSER)
        after = server._stat["requests"], server._hour_stat["object"]
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (1, 1))

    def test_animate_can_read_the_visible_rung_width(self):
        # The server no longer knows the width (CSS picked it), so the
        # stream URL is completed in the browser from data-cols -- without
        # it the frames arrive at DEFAULT_HORIZON_WIDTH and the chart
        # visibly shrinks the moment animate starts.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn("data-cols=", resp.text)
        self.assertIn("liveUrl+='&w='+cols", resp.text)

    def test_explicit_w_opts_out_of_the_ladder(self):
        # Someone who named a width means it, and it keeps shared ?w= links,
        # the CLI and the animate stream on the single-render path.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&w=150", headers=BROWSER)
        self.assertNotIn('<div id="chart-ladder">', resp.text)
        self.assertIn('<pre id="chart-pre" class="chart-pre">', resp.text)

    def test_facing_view_opts_out(self):
        # facing= has its own aspect-locked sizing formula -- the ladder
        # would fight it, see api.py's DEFAULT_HORIZON_WIDTH comment.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&facing=NW", headers=BROWSER)
        self.assertIn('class="w"', resp.text)
        self.assertNotIn('class="w w-wide"', resp.text)
        self.assertNotIn('<div id="chart-ladder">', resp.text)

    def test_disc_view_opts_out(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&view=disc", headers=BROWSER)
        self.assertNotIn('<div id="chart-ladder">', resp.text)

    def test_find_view_gets_the_ladder_too(self):
        # find used to crop to a narrow window (opted out, same as facing=)
        # -- it draws the full panorama now, same width as the ordinary
        # view, so the ladder applies exactly the same way.
        resp = self.client.get("/Zurich?find=Venus&t=2026-07-30T23:00", headers=BROWSER)
        self.assertIn('class="w w-wide"', resp.text)
        self.assertEqual(_rungs(resp.text),
                         [(cols, panel) for _min_ch, cols, panel in api.CHART_LADDER])

    def test_non_chart_pages_opt_out(self):
        # /stats is no longer in this list -- see the test below. Everything
        # here is prose, and prose keeps the 1200px measure.
        for path in ("/catalog", "/legend", "/help"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn('class="w"', resp.text, path)
            self.assertNotIn('class="w w-wide"', resp.text, path)
            self.assertNotIn('<div id="chart-ladder">', resp.text, path)
            # Still exactly one plain block, id and all -- skymapChartPre()
            # falls back to it with no ladder present.
            self.assertIn('<pre id="chart-pre" class="chart-pre">', resp.text, path)

    def test_stats_goes_wide_for_the_map_and_nothing_else_follows_it(self):
        # The world map is 216 columns and the default column is about 182,
        # so /stats had a scrollbar under the widest thing on the page. It
        # takes the same opt-out the chart page uses -- but per page, so the
        # prose pages above must not move with it.
        resp = self.client.get("/stats", headers=BROWSER)
        self.assertIn('class="w w-wide"', resp.text)
        # Wide layout only. The ladder re-renders the chart at several
        # widths, which is a chart-page trick with nothing to do with this.
        self.assertNotIn('<div id="chart-ladder">', resp.text)
        home = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertNotIn(" w-wide-stats", home.text)   # no second mechanism

    def test_the_map_still_fits_the_page_it_widened_for(self):
        # 216 columns of 11px monospace is ~1,426px, plus 32px of body
        # padding. Regenerating worldmap.json wider than this puts the
        # scrollbar straight back.
        _rows, w, _h, _top, _bot = server._load_worldmap()
        self.assertLessEqual(w, 216)

    def test_exactly_one_rung_is_visible_in_a_real_browser(self):
        """The only test here that resolves the cascade rather than reading
        the CSS as text.

        The string assertions above all passed against a version that put
        three charts on screen at 1400px and four at 2000px -- a specificity
        mistake no amount of substring matching can see. Skipped rather than
        failed where playwright/chromium isn't installed: it isn't in
        requirements.txt, and the rest of the suite must stay runnable with
        no browser at all."""
        playwright = pytest.importorskip("playwright.sync_api",
                                         reason="playwright not installed")
        import threading
        import uvicorn
        cfg = uvicorn.Config(server.app, host="127.0.0.1", port=8829,
                             log_level="error")
        srv = uvicorn.Server(cfg)
        threading.Thread(target=srv.run, daemon=True).start()
        self.addCleanup(setattr, srv, "should_exit", True)
        for _ in range(100):
            time.sleep(0.05)
            if srv.started:
                break
        else:
            self.skipTest("test server did not start")

        url = "http://127.0.0.1:8829/Zurich?t=2026-07-30T23:00"
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:                     # no browser binary
                self.skipTest(f"chromium unavailable: {exc}")
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                # A phone, a narrow window, and three desktop sizes either
                # side of the breakpoints.
                for viewport in (420, 800, 1100, 1400, 1700, 2000, 2600):
                    page.set_viewport_size({"width": viewport, "height": 900})
                    page.wait_for_timeout(120)
                    shown = page.eval_on_selector_all(
                        "#chart-ladder .chart-pre",
                        "els=>els.map((e,i)=>({i:i+1,cols:e.dataset.cols,"
                        "shown:getComputedStyle(e).display!=='none'}))"
                        ".filter(x=>x.shown)")
                    self.assertEqual(
                        len(shown), 1,
                        f"{viewport}px: {len(shown)} rungs visible "
                        f"({[s['cols'] for s in shown]}), expected exactly 1")
                # And the rung chosen has to grow with the window, never shrink.
                picked = []
                for viewport in (420, 1100, 1400, 2000, 2600):
                    page.set_viewport_size({"width": viewport, "height": 900})
                    page.wait_for_timeout(120)
                    picked.append(page.evaluate(
                        "()=>{const e=[...document.querySelectorAll("
                        "'#chart-ladder .chart-pre')].find("
                        "x=>getComputedStyle(x).display!=='none');"
                        "return e?[...e.parentNode.children].indexOf(e):-1;}"))
                self.assertEqual(picked, sorted(picked),
                                 f"rung index went backwards as the window "
                                 f"widened: {picked}")
            finally:
                browser.close()

    def test_the_inset_is_lifted_out_of_the_ladder_and_shipped_once(self):
        # It is the same 21-column drawing at every width, and it no longer
        # sits inside the text -- it floats over the chart, so it belongs to
        # the page rather than to any one rung.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertEqual(resp.text.count('id="chart-zenith"'), 1)
        self.assertNotIn("zenith 70-90", re.sub(
            r'<pre id="chart-zenith".*?</pre>', "", resp.text, flags=re.S))
        # every rung asks for the inset now; none of them pays width for it
        for _min_ch, cols, panel in api.CHART_LADDER:
            self.assertTrue(panel, cols)

    def test_the_prose_is_lifted_out_too_and_shipped_once(self):
        # A find view still has prose worth a block of its own; a plain
        # night chart no longer has any, since the top line took the lot.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&find=Vega",
                               headers=BROWSER)
        self.assertEqual(resp.text.count('id="chart-prose"'), 1)
        rungs = re.findall(r'<pre class="chart-pre"[^>]*>(.*?)</pre>',
                           resp.text, re.S)
        for body in rungs:
            self.assertNotIn("above the horizon in the", body)

    def test_the_daylight_view_leaves_no_fragments_or_markers(self):
        # Two bugs in one page. The prose is wrapped at 76 before the
        # summary lines are dropped, so removing them by their opening
        # words left the tail of a wrapped sentence behind -- a lone
        # "sets." under the chart. And split_chart_parts only looked for
        # the prose seam after finding a zenith seam, which the Sun's-path
        # view never has, so its marker reached the page as a tofu box.
        snap = {n: getattr(server, n).copy() for n in ("_places", "_geo_hits")}
        self.addCleanup(lambda: [(getattr(server, n).clear(),
                                  getattr(server, n).update(s))
                                 for n, s in snap.items()])
        for url in ("/Geneva?t=2026-08-19T14:00",
                    "/Reykjavik?t=2026-06-21T13:00"):
            resp = self.client.get(url, headers=BROWSER)
            text = server.api.strip_ansi(resp.text)
            self.assertNotIn("\x00", text, url)
            self.assertNotIn("sets.", text, url)      # the orphaned tail
            self.assertNotIn("Sunrise ", text, url)   # the sentence it came from
            # and the row that replaced them is there. "never fully dark" can
            # appear in it, which is why that phrase is not what is checked.
            self.assertRegex(text, r"☀ \d+°[NESW]+")

    def test_a_plain_night_chart_has_nothing_left_below_it(self):
        # Moon, planets, twilight and the star count all ride on the top
        # line now, so the chart runs to the shortcut bar.
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertNotIn('id="chart-prose"', resp.text)


class SidePanel(unittest.TestCase):
    """?panel=1 is parsed into Request.panel and never inferred -- only the
    browser's own auto-fit JS ever sets it (see AutoFitWidth above)."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_panel_param_is_tallied(self):
        self._orig_stat = server._stat.copy()
        server._stat.clear()
        self.addCleanup(lambda: (server._stat.clear(), server._stat.update(self._orig_stat)))
        self.client.get("/Zurich?t=2026-07-30T23:00&panel=1", headers=TERMINAL)
        resp = self.client.get("/stats?format=json", headers=TERMINAL)
        self.assertEqual(resp.json()["params"].get("panel"), 1)

    def test_panel_page_still_renders_successfully(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00&panel=1", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("zenith 70-90", resp.text)


class FollowLineOnlyOnCli(unittest.TestCase):
    """The "Follow @skymapsh..." line stays in curl/plain-text output
    (matches the CLI, which shares this same compose() text) but is
    stripped from the browser HTML page -- the header's social icons carry
    that invitation there instead."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_terminal_output_keeps_the_follow_line(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=TERMINAL)
        self.assertIn("Follow @skymapsh", server.api.strip_ansi(resp.text))

    def test_html_page_does_not_have_the_follow_line(self):
        resp = self.client.get("/Zurich?t=2026-07-30T23:00", headers=BROWSER)
        self.assertNotIn("Follow @skymapsh", resp.text)


class HeaderSocialIcons(unittest.TestCase):
    """GitHub/Reddit/Bluesky/X icon links sit inline in the header nav row,
    on every page -- replacing the old standalone "Created by ... see the
    repo" line that used to sit below the chart (chart-only, so catalog/
    legend/help/stats never had it; the icons fix that inconsistency for
    free)."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_chart_page_has_all_four_icons_and_not_the_old_footer_text(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('class="social-icons"', resp.text)
        self.assertIn("https://github.com/HabibiCodeCH/skymap-sh", resp.text)
        self.assertIn("https://www.reddit.com/r/skymap/", resp.text)
        self.assertIn("https://bsky.app/profile/skymap.sh", resp.text)
        self.assertIn("https://x.com/skymapsh", resp.text)
        self.assertNotIn("Created by", resp.text)

    def test_icons_appear_in_the_requested_order(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        text = resp.text
        positions = [text.index(url) for url in (
            "https://github.com/HabibiCodeCH/skymap-sh",
            "https://www.reddit.com/r/skymap/",
            "https://bsky.app/profile/skymap.sh",
            "https://x.com/skymapsh",
        )]
        self.assertEqual(positions, sorted(positions))

    def test_every_page_gets_the_icons(self):
        for path in ("/catalog", "/legend", "/help", "/stats"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn('class="social-icons"', resp.text, path)


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
        nav = resp.text[resp.text.index('class="t nav-row"'):]
        self.assertLess(nav.index('href="/"'), nav.index('href="/catalog"'))
        self.assertLess(nav.index('href="/catalog"'), nav.index('href="/demo"'))


class CompleteEndpoint(unittest.TestCase):
    """GET /complete backs the search bar's place suggestions -- cities.json
    (~3.9 MB) never ships to the browser, this is the server-side
    substitute."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_returns_ranked_json_matches(self):
        resp = self.client.get("/complete?q=new")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(rows[0]["name"], "New York")

    def test_rows_carry_the_size_band_the_dropdown_draws(self):
        rows = self.client.get("/complete?q=new").json()
        self.assertEqual(rows[0]["size"], 3)
        for row in rows:
            self.assertIn(row["size"], (1, 2, 3))

    def test_missing_q_is_not_an_error(self):
        resp = self.client.get("/complete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_response_is_aggressively_cached(self):
        resp = self.client.get("/complete?q=new")
        cc = resp.headers["cache-control"]
        self.assertIn("s-maxage=604800", cc)

    def test_exempt_from_the_per_ip_rate_limit(self):
        # A normal word can debounce past 30 keystrokes' worth of requests
        # on its own -- this endpoint must not throttle that.
        server._buckets.clear()
        for _ in range(50):
            resp = self.client.get("/complete?q=new")
            self.assertEqual(resp.status_code, 200)


class CompleteObjectsEndpoint(unittest.TestCase):
    """GET /complete/objects backs the find field's dropdown -- catalog
    data (stars/planets/deep-sky/constellations), not cities."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_returns_matches_with_glyph_and_colour(self):
        resp = self.client.get("/complete/objects?q=ven")
        self.assertEqual(resp.status_code, 200)
        objs = resp.json()
        self.assertTrue(any(o["name"] == "Venus" for o in objs))
        self.assertIn("glyph", objs[0])
        self.assertIn("color", objs[0])

    def test_missing_q_is_not_an_error(self):
        resp = self.client.get("/complete/objects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_response_is_cached_but_shorter_than_place_completion(self):
        # Shorter than /complete's week-long cache -- the Moon's glyph in
        # here reflects its real phase, so this can't be cached that long.
        resp = self.client.get("/complete/objects?q=ven")
        cc = resp.headers["cache-control"]
        self.assertIn("max-age=3600", cc)

    def test_exempt_from_the_per_ip_rate_limit(self):
        server._buckets.clear()
        for _ in range(50):
            resp = self.client.get("/complete/objects?q=ven")
            self.assertEqual(resp.status_code, 200)


class DrawerWiring(unittest.TestCase):
    """The drawer trigger + toggle/outside-click/Escape JS (SPEC-command-
    bar.md #9) is present on every page (see header_html/controls_html), so
    no page-specific gating -- only the element lookups are null-safe."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_js_class_added_for_progressive_enhancement(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("document.documentElement.classList.add('js');", resp.text)

    def test_js_class_script_runs_before_the_drawer_is_ever_painted(self):
        # Regression: this used to sit in the big script block down by
        # #chart-pre, after the drawer's own HTML. On a real full-page
        # navigation (e.g. clicking "show quadrants", a plain link) the
        # browser paints HTML as it parses it -- with the class-adding
        # script that late, the drawer's un-enhanced, full-width,
        # always-open state (full-width "go" button included) flashed on
        # screen for a frame before the class landed and CSS collapsed it
        # back into the narrow hidden panel. It has to run in <head>,
        # before the page body (and #drawer within it) exists to paint at all.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertLess(resp.text.index("classList.add('js')"), resp.text.index("<body>"))

    def test_trigger_toggles_the_drawer(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("drawer.classList.add('open');", resp.text)
        self.assertIn("window.skymapCloseDrawer", resp.text)

    def test_outside_click_closes_it_no_backdrop_needed(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("if(drawer.contains(e.target)||e.target===trigger)return;", resp.text)

    def test_escape_closes_the_drawer_before_blurring_a_focused_field(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        # Anchored on the drawer's own branch rather than "the first Escape
        # on the page". The search bar now has two Escape handlers of its
        # own and they come first in source order, which is correct: both
        # are gated on something being open (the suggestions, the help
        # panel), so they only act when there is something nearer to close.
        branches = resp.text.split("e.key==='Escape'")
        escape_branch = next(b for b in branches if "ae.blur()" in b)
        self.assertIn("window.skymapCloseDrawer()", escape_branch)
        self.assertLess(escape_branch.index("window.skymapCloseDrawer()"),
                        escape_branch.index("ae.blur()"))

    def test_present_on_non_chart_pages_too(self):
        for path in ("/catalog", "/legend", "/help", "/stats"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn('id="drawer-trigger"', resp.text, path)
            self.assertIn('id="drawer"', resp.text, path)

    def test_in_drawer_close_button_is_wired_to_the_same_close_function(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn(
            "closeBtn.addEventListener('click',window.skymapCloseDrawer);",
            resp.text)

    def test_reset_button_links_to_the_bare_root(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('href="/">↺ reset skymap</a>', resp.text)

    def test_gif_and_png_share_buttons_share_one_row(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        row_start = resp.text.index('<div class="share-row">')
        reset_start = resp.text.index("reset skymap")
        gif_pos = resp.text.index("Share as a GIF")
        png_pos = resp.text.index("Share as a PNG")
        self.assertTrue(row_start < gif_pos < png_pos < reset_start)

    def test_clicking_the_page_does_not_steal_focus_into_the_command_bar(self):
        # Removed deliberately. The keyboard shortcuts are ignored while a
        # text field has focus -- they have to be, or typing a place with a
        # space in it would pause the animation -- so refocusing #q after
        # every click left the shortcuts dead most of the time, and the way
        # to revive them was to click one of the few elements the rule
        # excepted. Tab and "p" still focus the bar on purpose.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertNotIn("document.addEventListener('click',function(e){",
                         resp.text)
        self.assertNotIn("q.focus();\n      q.select();", resp.text)

    def test_tab_still_focuses_the_command_bar_and_p_no_longer_does(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("if(e.key==='Tab'){", resp.text)
        self.assertIn("place.focus();place.select();", resp.text)
        self.assertNotIn("e.key==='p'", resp.text)

    def test_the_drawer_still_closes_on_an_outside_click(self):
        # A separate mousedown listener, not the removed click one -- the
        # drawer has no backdrop, so this is the only thing that closes it.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("document.addEventListener('mousedown',function(e){",
                      resp.text)
        self.assertIn("window.skymapCloseDrawer();", resp.text)


class CommandBarSubmitGoesToTheTypedPath(unittest.TestCase):
    """Enter goes to the path the bar is showing. It used to hand the text
    to the explore form to rebuild a URL from, which was fine while the bar
    held a bare place name -- once it holds "Tokyo/Venus", a rebuild that
    never saw the slash turns it back into /Venus."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_bar_submit_is_intercepted(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("bar.addEventListener('submit',function(e){", resp.text)
        self.assertIn("e.preventDefault();", resp.text)

    def test_a_highlighted_suggestion_wins_over_the_typed_text(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("if(active>=0&&matches[active]){", resp.text)
        self.assertIn("location.href=matches[active].href;", resp.text)

    def test_each_segment_is_encoded_separately_so_the_slash_survives(self):
        # encodeURIComponent on the whole string would turn the one
        # character doing the work into %2F.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("v.split('/').map(encodeURIComponent).join('/')", resp.text)
        self.assertNotIn("location.href='/'+encodeURIComponent(q.value);",
                         resp.text)

    def test_the_drawer_datetime_still_rides_along(self):
        # The explore form is no longer delegated to, so the one thing it
        # still contributed has to be picked up here instead.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("location.href=toPath(v)+(t?'?t='+encodeURIComponent(t):'');",
                      resp.text)

    def test_an_empty_bar_goes_home(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("if(!v){location.href='/';return;}", resp.text)


class ExploreFormEmptySubmitGoesHome(unittest.TestCase):
    """Clearing the command bar and pressing Enter (or "go" with find/date/
    time also empty) used to silently do nothing -- an early-return guard
    meant to catch an accidental blank submit, but there's no such thing as
    an empty case actually worth guarding: an empty place already means "/"
    (bare skymap.sh, located by IP) in the line right below it."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_no_early_return_guard_on_the_chart_page(self):
        # EXPLORE_DATETIME -- find lives in the header there, not this form.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertNotIn("if(!p&&!f&&!t)return false;", resp.text)

    def test_no_early_return_guard_on_a_non_chart_page(self):
        # EXPLORE -- has its own #find, same guard used to exist there too.
        resp = self.client.get("/catalog", headers=BROWSER)
        self.assertNotIn("if(!p&&!f&&!t)return false;", resp.text)

    def test_empty_p_falls_through_to_the_bare_home_navigation(self):
        # The form builds a PATH now rather than a ?find= query: every object
        # has its own page, so finding one navigates to it. With no place and
        # no find it still falls through to the bare home navigation.
        resp = self.client.get("/Zurich", headers=BROWSER)
        onsubmit = resp.text.split('onsubmit="', 1)[1].split('">', 1)[0]
        self.assertIn(":('/'+(p?encodeURIComponent(p):''))", onsubmit)

    def test_a_find_navigates_to_the_object_page(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        onsubmit = resp.text.split('onsubmit="', 1)[1].split('">', 1)[0]
        self.assertIn("encodeURIComponent(p)+'/'", onsubmit)
        self.assertNotIn("find=", onsubmit)


class CommandBarNoJsFallback(unittest.TestCase):
    """The command bar (header_html) is a real <form method="get"
    action="/">, so pressing Enter with no JS loaded still submits ?q=<value>
    to / -- root() bounces that on to the real place URL."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_q_redirects_to_the_place(self):
        resp = self.client.get("/?q=Geneva", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva")

    def test_other_query_params_are_preserved(self):
        resp = self.client.get("/?q=Geneva&t=2026-07-30T23:00",
                               headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva?t=2026-07-30T23:00")

    def test_blank_q_falls_through_to_the_normal_root_page(self):
        resp = self.client.get("/?q=", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)

    def test_no_q_at_all_is_unaffected(self):
        resp = self.client.get("/", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)


class CommandBarValue(unittest.TestCase):
    """header_html's value is whatever belongs after "skymap.sh/" -- the
    resolved place's display name on a chart page, the bare page name
    elsewhere (matching what the old static cta chip always showed)."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_chart_page_shows_the_place_name_and_a_trailing_slash(self):
        # The real display name is "Zürich" (with the umlaut), not the
        # ASCII "Zurich" typed in the URL. The slash is the invitation to
        # name an object; /Zürich/ and /Zürich are one page, so it costs
        # nothing when it is never used.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('value="Zürich/"', resp.text)

    def test_multi_word_place_shows_its_real_name_not_the_slug(self):
        resp = self.client.get("/New%20York", headers=BROWSER)
        self.assertIn('value="New York/"', resp.text)
        self.assertNotIn('value="NewYork"', resp.text)

    def test_catalog_page_shows_catalog(self):
        resp = self.client.get("/catalog", headers=BROWSER)
        self.assertIn('value="catalog"', resp.text)

    def test_help_page_shows_help(self):
        resp = self.client.get("/help", headers=BROWSER)
        self.assertIn('value="help"', resp.text)

    def test_p_shortcut_focuses_q_not_a_removed_place_field(self):
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("document.getElementById('q')", resp.text)
        self.assertNotIn("document.getElementById('place')", resp.text)

    def test_tab_also_jumps_to_the_command_bar(self):
        # Tab doubles as a global "jump into search" shortcut everywhere
        # except while already typing in a field -- see the guard just
        # above this branch (tag==='INPUT'||...) that #q's own keydown
        # handler (ghost-completion accept) relies on for the opposite case.
        resp = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn("e.key==='Tab'", resp.text)
        self.assertNotIn("e.key==='p'", resp.text)


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


class SphereGoldenIsAddressableAndCounted(unittest.TestCase):
    """Golden hour on the sphere is a client-side layer, so nothing reached
    the server when someone switched into it -- it shipped shareable by
    nobody and measurable by nobody, which are the same bug. ?golden=1 makes
    the mode a real address and a countable one."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        server._stat["sphere_golden"] = 0

    def test_the_parameter_is_counted(self):
        self.client.get("/Geneva/sphere?golden=1")
        self.client.get("/Geneva/sphere?golden=1")
        self.assertEqual(
            self.client.get("/stats/sphere?format=json").json()["sphere_golden"], 2)

    def test_a_plain_sphere_view_is_not_counted_as_golden(self):
        self.client.get("/Geneva/sphere")
        self.assertEqual(
            self.client.get("/stats/sphere?format=json").json()["sphere_golden"], 0)

    def test_the_stats_page_reports_it_against_total_sphere_views(self):
        self.client.get("/Geneva/sphere?golden=1")
        line = [l for l in self.client.get("/stats/sphere").text.split("\n")
                if "golden" in l]
        self.assertTrue(line)
        self.assertIn("of sphere views", line[0])

    def test_the_parameter_survives_the_coordinates_redirect(self):
        # /46.20,6.10/sphere bounces to /Geneva/sphere; a shared golden link
        # must not lose its mode on the way.
        resp = TestClient(server.app, follow_redirects=False).get(
            "/46.20,6.10/sphere?golden=1")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("golden=1", resp.headers["location"])

    def test_the_beacon_counts_a_switch_made_in_session(self):
        # The common case: land on the star sphere, tap `light`. replaceState
        # rewrites the address without a request, so this is the only thing
        # that can see it -- and it is most of the usage.
        server._stat["sphere_golden_on"] = 0
        self.client.get("/beacon/golden")
        self.assertEqual(
            self.client.get("/stats/sphere?format=json").json()["sphere_golden_on"], 1)

    def test_the_beacon_answers_post_because_sendBeacon_only_posts(self):
        # navigator.sendBeacon always POSTs. Declared GET-only this would
        # 405, and a fire-and-forget beacon would never tell anyone.
        for method in ("GET", "POST"):
            resp = self.client.request(method, "/beacon/golden")
            self.assertEqual(resp.status_code, 204, method)
            self.assertIn("no-store", resp.headers["cache-control"])

    def test_the_beacon_does_not_spend_the_visitors_rate_limit(self):
        # Flicking between the two modes fires this far more often than a
        # page view, and it must not eat the allowance meant for charts.
        self.assertIn("/beacon/golden", server.RATE_EXEMPT)

    def test_arrivals_and_switches_are_counted_separately(self):
        server._stat["sphere_golden"] = 0
        server._stat["sphere_golden_on"] = 0
        self.client.get("/Geneva/sphere?golden=1")   # arrived
        self.client.get("/beacon/golden")            # switched
        d = self.client.get("/stats/sphere?format=json").json()
        self.assertEqual((d["sphere_golden"], d["sphere_golden_on"]), (1, 1))
        text = self.client.get("/stats/sphere").text
        self.assertIn("arrived", text)
        self.assertIn("switched", text)

    def test_the_page_reads_the_parameter_and_the_toggle_writes_it(self):
        body = self.client.get("/Geneva/sphere").text
        self.assertIn("searchParams.get('golden')", body)
        self.assertIn("searchParams.set('golden', '1')", body)
        self.assertIn("replaceState", body)


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

    def test_red_mode_is_a_button_and_is_off_until_someone_presses_it(self):
        # Red mode exists because the page gets used outdoors after dark,
        # but it stays opt-in: it repaints the entire sky, and springing
        # that on anyone who happens to open the page at night would be a
        # far bigger surprise than the brightness it fixes.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn('<button id="night-toggle" class="toggle-btn"', resp.text)
        # class="toggle-btn on" would mean pre-enabled, the thing this
        # test exists to prevent.
        self.assertNotIn('id="night-toggle" class="toggle-btn on"', resp.text)
        self.assertIn("var nightOn = false;", resp.text)
        # The only thing allowed to turn it on at load is the visitor's own
        # remembered choice -- never sun_alt, never the clock.
        self.assertIn("localStorage.getItem('skymap.red') === '1'", resp.text)

    def test_red_mode_in_daylight_writes_names_in_black_not_red(self):
        # Red mode dulls the daytime sky dome but doesn't remove it, so the
        # background stays a broad red field. Red labels on it were
        # unreadable, and the glow behind them (there for contrast against
        # a black sky) smeared rather than helped. Anything painted
        # straight onto the sky stands down in daylight and hands over to
        # black and greys instead.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("body.night:not(.daytime) .sky-label span", resp.text)
        self.assertIn("body.night.daytime .sky-label span{color:#1c1c1c;text-shadow:none}",
                      resp.text)
        # Two body classes, so it wins over the plain body.daytime rules
        # without depending on where it sits in the stylesheet.
        for sel in ("body.night.daytime .con-label span",
                    "body.night.daytime .body-label span",
                    "body.night.daytime #find-reticle .tick"):
            self.assertIn(sel, resp.text)

    def test_red_mode_maps_from_true_colours_not_the_last_ones_drawn(self):
        # Toggling red on, off and on again must land back on the same
        # colours. Mapping from whatever is currently on the material
        # instead of from the remembered original compounds the filter on
        # every toggle, and the sky creeps darker each time.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("mat.userData.trueColor === undefined", resp.text)
        self.assertIn("geo.userData.trueColor = attr.array.slice()", resp.text)
        # The find marker's five-second fade to white is the one place that
        # used to set a colour behind paintScene's back.
        self.assertIn("setTrueColor(foundPoint.material, 0xffffff);", resp.text)

    def test_red_mode_skips_vertex_colour_materials(self):
        # Stars carry their colour per vertex and leave material.color at
        # white as a multiplier. Redifying that white as well multiplies
        # the filter in twice and the stars come out near black.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("if (mat && mat.color && !mat.vertexColors) {", resp.text)

    def test_red_mode_repaints_objects_that_arrive_after_the_toggle(self):
        # Deep sky objects, find markers and time-scrub reloads all land in
        # the scene long after red mode was switched on. Without this they
        # come in at full brightness against an otherwise red sky.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("if (scene.children.length !== _paintedChildren) paintScene();",
                      resp.text)

    def test_red_mode_recolours_the_scene_rather_than_filtering_the_canvas(self):
        # A CSS filter over the canvas is the one-line version of this and
        # costs a full-screen composite pass every frame on a phone. The
        # scene is recoloured once per toggle instead.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertNotIn("filter:hue-rotate", resp.text)
        self.assertNotIn("filter: hue-rotate", resp.text)
        self.assertNotIn("canvas{filter", resp.text)

    def test_sphere_page_holds_a_screen_wake_lock(self):
        # Held up at the sky outdoors, the phone auto-locking mid-session
        # is the worst thing it can do to this page.
        resp = self.client.get("/Zurich/sphere", headers=BROWSER)
        self.assertIn("navigator.wakeLock.request('screen')", resp.text)
        # A wake lock is dropped rather than paused whenever the page stops
        # being visible and is never restored on its own -- without the
        # re-request it survives exactly one interruption.
        self.assertIn("document.visibilityState === 'visible'", resp.text)

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

    # Whether a phone reaches the sphere depends on the User-Agent, and a
    # shared cache keyed on the URL alone does not know that. Cloudflare
    # caching one desktop page at `/` and handing it to every phone behind
    # it is the whole bug these three exist to prevent -- it looks
    # intermittent in the wild, because it depends on who arrived first.
    def test_a_browser_page_is_never_stored_by_a_shared_cache(self):
        for path in ("/", "/Tokyo"):
            cc = self.client.get(path, headers=BROWSER).headers["cache-control"]
            self.assertIn("private", cc, path)
            self.assertNotIn("s-maxage", cc, path)
            self.assertNotIn("public", cc, path)

    def test_the_redirect_itself_is_never_stored_either(self):
        # The same bug pointing the other way: a cached 302 would bounce
        # desktop visitors to the sphere.
        cc = self.client.get("/Tokyo", headers=MOBILE).headers["cache-control"]
        self.assertIn("no-store", cc)

    def test_terminal_and_json_keep_full_edge_caching(self):
        # The reason for not simply sending Vary: User-Agent. Curl and
        # ?format=json are the bulk of the traffic and are identical for
        # every visitor, so they stay shared-cacheable.
        for headers in (TERMINAL, {"user-agent": "curl/8.0", "accept": "*/*"}):
            cc = self.client.get("/Tokyo", headers=headers).headers["cache-control"]
            self.assertIn("s-maxage", cc)
            self.assertIn("public", cc)
        cc = self.client.get("/Tokyo?format=json", headers=TERMINAL).headers["cache-control"]
        self.assertIn("s-maxage", cc)

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


class HeadRequestsAreAnswered(unittest.TestCase):
    """HEAD asks for the headers a GET would return, without the body. It is
    what `curl -I` sends and what uptime monitors and link checkers use. All
    36 routes are declared with @app.get, which FastAPI takes literally, so
    every one of them used to answer 405 -- anything watching the site that
    way was reading a hard failure on every check."""

    def setUp(self):
        client_cm = TestClient(server.app, follow_redirects=False)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_every_kind_of_route_answers_head(self):
        for path in ("/", "/Geneva", "/healthz", "/robots.txt", "/stats",
                     "/legend", "/help", "/sitemap.xml", "/Geneva/sphere"):
            resp = self.client.request("HEAD", path, headers=TERMINAL)
            self.assertEqual(resp.status_code, 200, path)

    def test_head_reports_the_length_a_get_would_have_sent(self):
        # The body is still rendered, which is what makes Content-Length
        # honest; uvicorn drops it on the wire because it knows the request
        # was a HEAD.
        head = self.client.request("HEAD", "/Geneva", headers=TERMINAL)
        get = self.client.get("/Geneva", headers=TERMINAL)
        self.assertEqual(head.headers["content-length"],
                         get.headers["content-length"])

    def test_head_still_redirects_a_phone_to_the_sphere(self):
        resp = self.client.request("HEAD", "/", headers=MOBILE)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["location"].endswith("/sphere"))

    def test_head_keeps_the_cache_headers_a_get_would_get(self):
        head = self.client.request("HEAD", "/Geneva", headers=TERMINAL)
        get = self.client.get("/Geneva", headers=TERMINAL)
        self.assertEqual(head.headers["cache-control"], get.headers["cache-control"])

    def test_an_unsupported_method_is_still_rejected(self):
        # Only HEAD is folded onto GET; POST and friends must stay 405 so
        # this does not quietly turn into "any method works".
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            resp = self.client.request(method, "/Geneva", headers=TERMINAL)
            self.assertEqual(resp.status_code, 405, method)


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


class CoordinatesRedirectToNearbyCity(unittest.TestCase):
    """A browser landing on raw coordinates close to a well-known city (the
    'm' keyboard shortcut's real GPS fix, an old bookmarked link, typing
    lat,lon into the search box) gets bounced to that city's own name --
    curl/JSON keep the literal coordinates, since there's no URL bar to tidy
    up there and redirecting would silently break anyone scripting against
    an exact lat/lon."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        # _cache_key rounds to 0.1 deg on lat/lon alone, not on the place's
        # name -- by design, one Result entry serves both "Geneva" and
        # coordinates that round to the same cell. Perfectly fine at runtime
        # (same sky either way), but it means an earlier test's Geneva-by-
        # name request can otherwise leak into a later coordinates-by-number
        # one within this same class.
        server._cache.clear()

    def test_browser_is_redirected_to_the_city_name(self):
        resp = self.client.get("/46.20,6.15", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva")

    def test_redirect_is_not_cached_at_the_edge(self):
        # No Cache-Control here, like the old /healthz bug this codebase has
        # already hit once: Cloudflare applies its own default TTL to a
        # response with none, and a visitor who hit these exact coordinates
        # before this redirect existed keeps getting served that stale,
        # un-redirected response indefinitely.
        resp = self.client.get("/46.20,6.15", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_redirect_preserves_the_query_string(self):
        resp = self.client.get("/46.20,6.15?t=2026-07-30T23:00&panel=1",
                               headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"],
                         "/Geneva?t=2026-07-30T23:00&panel=1")

    def test_terminal_keeps_the_literal_coordinates(self):
        resp = self.client.get("/46.20,6.15", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Location", resp.headers)

    def test_json_keeps_the_literal_coordinates(self):
        # lookup_place snaps to 0.1 deg internally (its own cache-key
        # concern, unrelated to this redirect) -- 6.15 rounds to 6.20.
        resp = self.client.get("/46.20,6.15?format=json", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["place"], "46.20,6.20")

    def test_a_named_place_is_never_redirected(self):
        resp = self.client.get("/Geneva", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_coordinates_far_from_any_city_are_not_redirected(self):
        # Mid-Atlantic -- there's no city name to swap in for.
        resp = self.client.get("/30.0,-40.0", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_the_search_bar_shows_the_city_name_after_following_the_redirect(self):
        resp = self.client.get("/46.20,6.15", headers=BROWSER)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('value="Geneva/"', resp.text)


class BareDomainGeoRedirectsToNearbyCity(unittest.TestCase):
    """The explicit /lat,lon redirect above only ever fires when the URL
    path itself is coordinates -- landing on the bare domain builds a Place
    from the CDN's IP-geolocation headers instead (_geo(request) in
    server.py), a completely separate branch that never got the same
    city-name swap. A visitor opening skymap.sh from inside Geneva saw raw
    coordinates on first load and only got "Geneva" after clicking m or
    navigating somewhere else -- the exact bug this project's coordinate
    work was originally asked to fix, just left open on this one path."""

    GENEVA = {"cf-iplatitude": "46.20", "cf-iplongitude": "6.15"}
    MID_ATLANTIC = {"cf-iplatitude": "30.0", "cf-iplongitude": "-40.0"}

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        server._cache.clear()

    def test_root_with_cdn_geo_headers_redirects_to_the_city_name(self):
        resp = self.client.get("/", headers={**BROWSER, **self.GENEVA},
                               follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva")

    def test_root_redirect_is_not_cached_at_the_edge(self):
        # This one's even more load-bearing than the /lat,lon case: the
        # redirect is keyed off *this visitor's* IP, so caching it at all
        # would bounce every later visitor sharing that edge cache entry to
        # Geneva regardless of where they actually are.
        resp = self.client.get("/", headers={**BROWSER, **self.GENEVA},
                               follow_redirects=False)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_root_without_geo_headers_is_not_redirected(self):
        resp = self.client.get("/", headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_root_geo_headers_far_from_any_city_are_not_redirected(self):
        resp = self.client.get("/", headers={**BROWSER, **self.MID_ATLANTIC},
                               follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_terminal_mode_keeps_the_literal_coordinates(self):
        resp = self.client.get("/", headers={**TERMINAL, **self.GENEVA})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Location", resp.headers)


class OtherPlaceRoutesAlsoRedirectCoordinates(unittest.TestCase):
    """The coordinates-to-city bounce lived only in _respond (the main chart
    route) -- /events and /sphere resolve a place through the same
    _build/resolve_place path but never got the same treatment, so a browser
    on /46.20,6.15/events or /46.20,6.15/sphere still saw raw coordinates
    everywhere the main chart already said "Geneva". Extracted into
    _nearby_city_for_redirect precisely so a fourth route doesn't repeat
    this gap."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        server._cache.clear()

    def test_events_page_redirects_to_the_city_name(self):
        resp = self.client.get("/46.20,6.15/events", headers=BROWSER,
                               follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva/events")

    def test_events_redirect_is_not_cached_at_the_edge(self):
        resp = self.client.get("/46.20,6.15/events", headers=BROWSER,
                               follow_redirects=False)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_bare_events_with_cdn_geo_headers_redirects_to_the_city_name(self):
        resp = self.client.get(
            "/events", headers={**BROWSER, "cf-iplatitude": "46.20",
                                "cf-iplongitude": "6.15"},
            follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva/events")

    def test_events_terminal_mode_keeps_the_literal_coordinates(self):
        resp = self.client.get("/46.20,6.15/events", headers=TERMINAL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Location", resp.headers)

    def test_sphere_page_redirects_to_the_city_name(self):
        resp = self.client.get("/46.20,6.15/sphere", headers=BROWSER,
                               follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/Geneva/sphere")

    def test_sphere_redirect_is_not_cached_at_the_edge(self):
        resp = self.client.get("/46.20,6.15/sphere", headers=BROWSER,
                               follow_redirects=False)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_sphere_redirect_preserves_the_query_string(self):
        resp = self.client.get("/46.20,6.15/sphere?t=2026-07-30T23:00",
                               headers=BROWSER, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"],
                         "/Geneva/sphere?t=2026-07-30T23:00")


class SearchBarSubmitsAPath(unittest.TestCase):
    """The bar holds what follows skymap.sh/, slashes and all, so a plain
    form submit only has to put it back after the slash. This is the
    scriptless path; with JS the bar navigates to the same URL directly."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def _to(self, qs):
        return self.client.get(f"/?{qs}", follow_redirects=False,
                               headers=BROWSER).headers["location"]

    def test_two_segments_stay_two_segments(self):
        # quote() leaves "/" alone by default. Encoding it would make one
        # segment called "Tokyo/Venus", which is not a page.
        self.assertEqual(self._to("q=Tokyo/Venus"), "/Tokyo/Venus")

    def test_a_bare_object_is_still_a_bare_object(self):
        self.assertEqual(self._to("q=Venus"), "/Venus")

    def test_a_trailing_slash_survives(self):
        # What a chart page's bar holds before anything is typed after it.
        self.assertEqual(self._to("q=Tokyo/"), "/Tokyo/")

    def test_a_page_name_is_untouched(self):
        self.assertEqual(self._to("q=catalog"), "/catalog")

    def test_other_params_survive(self):
        self.assertIn("t=2026-07-30T23:00",
                      self._to("q=Tokyo/Venus&t=2026-07-30T23:00"))

    def test_there_is_no_second_mechanism_for_the_place(self):
        # from= existed briefly and is gone: the path carries the place, so
        # a parameter that also carried it could only ever disagree.
        self.assertEqual(self._to("q=Venus&from=Tokyo"), "/Venus?from=Tokyo")


class SearchBarPathsResolve(unittest.TestCase):
    """The URLs the bar builds are real pages, end to end."""

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_every_shape_the_bar_can_hold_is_a_page(self):
        for path in ("/Tokyo", "/Tokyo/", "/Tokyo/Venus", "/Venus",
                     "/catalog", "/Tokyo/events"):
            resp = self.client.get(path, headers=BROWSER)
            self.assertEqual(resp.status_code, 200, path)

    def test_the_bar_shows_the_path_of_the_page_it_is_on(self):
        for path, shown in (("/Tokyo", "Tokyo/"),
                            ("/Tokyo/Venus", "Tokyo/Venus"),
                            ("/Venus", "Venus"),
                            ("/catalog", "catalog")):
            resp = self.client.get(path, headers=BROWSER)
            self.assertIn(f'name="q" value="{shown}"', resp.text, path)


class StatsSurviveTheDeploy(unittest.TestCase):
    """The counters are persisted, so a rename in the code has to keep
    reading what the running server already wrote. Both files are
    gitignored, so a deploy never overwrites them -- which is exactly why
    the new code has to understand the old contents."""

    def test_a_pre_deploy_state_file_loads_whole(self):
        state = {
            "started": 1750000000,
            "stat": {"requests": 91234, "view:horizon": 60000,
                     "view:find": 12910},
            "places": {"Zurich": 5000}, "finds": {"Venus": 3240},
            "objects": {"Venus": 3100}, "sphere_places": {}, "events_places": {},
            "events_teased": {}, "referrers": {"bsky.app": 900},
            "geo": {"47,8": 5000},
        }
        d = tempfile.mkdtemp()
        orig = server.STATS_STATE_FILE
        self.addCleanup(setattr, server, "STATS_STATE_FILE", orig)
        server.STATS_STATE_FILE = os.path.join(d, "stats_state.json")
        with open(server.STATS_STATE_FILE, "w") as f:
            json.dump(state, f)
        server._load_stats_state()
        self.assertEqual(server._stat["requests"], 91234)
        self.assertEqual(dict(server._places), {"Zurich": 5000})
        self.assertEqual(dict(server._objects), {"Venus": 3100})
        # Frozen, but not thrown away: nothing writes to it now and nothing
        # shows it, and it still has to survive a save.
        self.assertEqual(dict(server._finds), {"Venus": 3240})
        server._save_stats_state()
        back = json.load(open(server.STATS_STATE_FILE))
        self.assertEqual(back["finds"], {"Venus": 3240})
        self.assertEqual(back["stat"]["view:find"], 12910)
        self.assertEqual(back["started"], 1750000000)

    def test_hourly_rows_written_before_the_rename_still_count(self):
        # The hourly log records object lookups under "object"; it used to
        # call the same number "find". _ZERO_FILL stamps a 0 onto any row
        # missing a key it knows about, so a fallback read at the chart was
        # dead code and the whole history flatlined -- the rename has to
        # happen as the rows are read.
        d = tempfile.mkdtemp()
        orig = server.HOURLY_LOG
        self.addCleanup(setattr, server, "HOURLY_LOG", orig)
        server.HOURLY_LOG = os.path.join(d, "stats_hourly.jsonl")
        now = dt.datetime.utcnow()
        rows = [{"hour": (now - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00"),
                 "requests": 100, "hit": 80, "miss": 20, "day": 40,
                 "night": 60, "find": 7 + h} for h in range(6, 0, -1)]
        rows.append({"hour": now.strftime("%Y-%m-%dT%H:00"), "requests": 100,
                     "hit": 80, "miss": 20, "day": 40, "night": 60,
                     "object": 5})
        with open(server.HOURLY_LOG, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        dense = server._dense_hours(server._read_hourly_history(days=1), 24)
        total = sum(e.get("object", 0) for e in dense)
        self.assertEqual(total, sum(7 + h for h in range(6, 0, -1)) + 5)

    def test_the_state_files_are_not_tracked_so_a_deploy_cannot_clobber_them(self):
        ignored = open(".gitignore").read()
        self.assertIn("stats_state.json", ignored)
        self.assertIn("stats_hourly.jsonl", ignored)


class UnfurlersGetTheHead(unittest.TestCase):
    """Every social card on the site looked missing from the outside while
    being correct in a browser.

    _wants() only reached its HTML branch when "text/html" was in the Accept
    header, and unfurlers send */*. So all of them fell through to the
    plain-text page, which has no <head> and therefore no card tags at all.
    The images were always fine and always reachable; nothing ever pointed a
    crawler at them.
    """

    BOTS = {
        "facebook": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "twitter": "Twitterbot/1.0",
        "linkedin": "LinkedInBot/1.0 (compatible; Mozilla/5.0)",
        "slack": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "discord": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
        "whatsapp": "WhatsApp/2.23.20.0",
        "telegram": "TelegramBot (like TwitterBot)",
        "bluesky": "Bluesky Cardyb/1.1",
        "google": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    }

    def setUp(self):
        client_cm = TestClient(server.app)
        self.client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)

    def test_every_unfurler_gets_the_card_tags(self):
        for name, ua in self.BOTS.items():
            r = self.client.get("/Venus", headers={"user-agent": ua,
                                                   "accept": "*/*"})
            self.assertIn('property="og:image"', r.text, name)
            self.assertIn('property="og:title"', r.text, name)
            self.assertIn('name="twitter:card"', r.text, name)

    def test_a_crawler_with_no_accept_header_at_all_still_gets_it(self):
        r = self.client.get("/Venus",
                            headers={"user-agent": self.BOTS["facebook"]})
        self.assertIn('property="og:image"', r.text)

    def test_it_applies_to_places_and_the_home_page_too(self):
        # This was never an object-page bug: the generic card was just as
        # invisible, on every page of the site.
        for path in ("/", "/Paris", "/catalog"):
            r = self.client.get(path, headers={"user-agent": self.BOTS["twitter"],
                                               "accept": "*/*"})
            self.assertIn('property="og:image"', r.text, path)

    def test_the_card_url_a_crawler_is_given_actually_serves_an_image(self):
        r = self.client.get("/Venus", headers={"user-agent": self.BOTS["slack"],
                                               "accept": "*/*"})
        url = re.search(r'property="og:image" content="[^"]*?(/[^"]+)"', r.text)
        self.assertTrue(url, "no og:image to follow")
        img = self.client.get(url.group(1))
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.headers["content-type"], "image/png")

    def test_a_terminal_still_gets_text(self):
        # The whole point of the site. A crawler is matched first, but curl
        # must not be caught by it.
        r = self.client.get("/Venus", headers={"user-agent": "curl/8.4.0"})
        self.assertNotIn("<html", r.text[:200])
        self.assertNotIn("property=", r.text)

    def test_crawlers_are_matched_before_the_terminal_list(self):
        # TERMINALS contains "fetch" and "http/", which are exactly the kind
        # of fragment a bot UA carries by accident. Order is what stops one
        # of those being served a plain-text page.
        r = self.client.get("/Venus",
                            headers={"user-agent": "SomeBot/1.0 fetch (+http://x)",
                                     "accept": "*/*"})
        self.assertNotIn("<html", r.text[:200])   # not a known crawler: text
        r = self.client.get("/Venus",
                            headers={"user-agent": "Twitterbot/1.0 fetch",
                                     "accept": "*/*"})
        self.assertIn('property="og:image"', r.text)   # known: html wins

    def test_an_explicit_format_still_wins(self):
        d = self.client.get("/Venus?format=json",
                            headers={"user-agent": self.BOTS["facebook"]}).json()
        self.assertEqual(d["object"], "Venus")


if __name__ == "__main__":
    unittest.main()
