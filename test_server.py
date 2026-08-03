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
    # The /stats family draws on its own bucket, so it needs lifting too --
    # otherwise the stats tests throttle each other instead.
    server.RATE = 1_000_000
    server.BURST = 1_000_000
    server.STATS_RATE = 1_000_000
    server.STATS_BURST = 1_000_000


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
        # The script is injected into the toolbar, which the parser reaches
        # before the <pre> holding the map. Starting immediately would find
        # no dots and never poll at all.
        body = self.client.get("/stats", headers=BROWSER).text
        self.assertIn("DOMContentLoaded", body)
        self.assertLess(body.index("stats/live?since="), body.index('id="d'))

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
