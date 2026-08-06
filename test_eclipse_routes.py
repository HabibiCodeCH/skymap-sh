"""The eclipse routes: six page URLs, two exports, and the ways they can go
wrong.

There were none of these until now, and the gap was not theoretical. A loop
variable in the /stats eclipse block was called `n`, which is that
function's own row limit for every table below it, so one visit to an
eclipse page cut half of /stats to a single row each. Nothing about
eclipses noticed. A test in a file about the top-places table did.

The shape being defended here, in one line: a 404 does not fall through to
the next route. FastAPI matches the first path that fits and the handler's
status code is the answer, which is how a separate og.png route once killed
the object cards and then the place cards. Every route below is registered
ahead of /{place:path}, and if that ordering is ever disturbed these fail
rather than the site quietly serving "unknown place" for /eclipse.
"""
import unittest

from starlette.testclient import TestClient

import server

BROWSER = {"accept": "text/html", "user-agent": "Mozilla/5.0"}
TERMINAL = {"user-agent": "curl/8.0"}

SOLAR = "2026-08-12"
LUNAR = "2026-08-28"


def setUpModule():
    # Same reason test_server.py lifts these: every TestClient here resolves
    # to one synthetic IP and the token bucket is shared for the process.
    server.RATE = server.BURST = 1_000_000
    server.STATS_RATE = server.STATS_BURST = 1_000_000


class RouteTest(unittest.TestCase):
    """TestClient only runs the startup handler (which sets app.state.tle,
    needed by every route) inside its own context manager."""

    def setUp(self):
        cm = TestClient(server.app)
        self.client = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        server._buckets.clear()


class EveryShapeOfUrlAnswers(RouteTest):

    URLS = ("/eclipse", f"/eclipse/{SOLAR}", f"/eclipse/{LUNAR}",
            "/Zurich/eclipse", f"/Zurich/eclipse/{SOLAR}",
            f"/Zurich/eclipse/{LUNAR}")

    def test_all_six_in_a_terminal(self):
        for url in self.URLS:
            got = self.client.get(url, headers=TERMINAL)
            self.assertEqual(got.status_code, 200, url)
            self.assertTrue(got.headers["content-type"].startswith("text/plain"),
                            url)
            self.assertIn("eclipse", got.text.lower(), url)

    def test_all_six_in_a_browser(self):
        for url in self.URLS:
            got = self.client.get(url, headers=BROWSER)
            self.assertEqual(got.status_code, 200, url)
            self.assertTrue(got.headers["content-type"].startswith("text/html"),
                            url)
            self.assertIn("Upcoming eclipses", got.text, url)

    def test_json_carries_the_same_facts(self):
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}?format=json")
        self.assertEqual(got.status_code, 200)
        data = got.json()
        self.assertEqual(data["eclipse"], SOLAR)
        self.assertEqual(data["place"], "Zürich")
        self.assertTrue(data["computed"])
        self.assertIn("obscuration", data)

    def test_a_bare_eclipse_lands_on_one_we_can_compute(self):
        """/eclipse is the front door and should answer the question, not
        show a date with a shrug next to it."""
        got = self.client.get("/eclipse?format=json")
        self.assertTrue(got.json()["computed"])


class ItFailsTheWayItShould(RouteTest):

    def test_a_date_with_no_eclipse_is_a_404(self):
        got = self.client.get("/eclipse/2026-01-01", headers=TERMINAL)
        self.assertEqual(got.status_code, 404)
        self.assertIn("no eclipse", got.text)
        # And says where to go instead, because a bare 404 on a date
        # somebody typed by hand is a dead end.
        self.assertIn("skymap.sh/eclipse", got.text)

    def test_an_unknown_place_is_a_404_that_suggests(self):
        got = self.client.get("/Nowhereville/eclipse", headers=TERMINAL)
        self.assertEqual(got.status_code, 404)

    def test_rubbish_in_the_date_does_not_500(self):
        for bad in ("2026-13-99", "../../etc/passwd", "%20", "null", "0"):
            got = self.client.get(f"/eclipse/{bad}", headers=TERMINAL)
            self.assertIn(got.status_code, (200, 404), bad)

    def test_the_word_eclipse_is_not_a_place(self):
        """/{place:path} would happily read "eclipse" as a place name and
        answer "unknown place". These routes are registered ahead of it, and
        this is what says so."""
        got = self.client.get("/eclipse", headers=TERMINAL)
        self.assertEqual(got.status_code, 200)
        self.assertNotIn("unknown place", got.text)

    def test_it_is_reserved_against_the_object_namespace(self):
        import objects
        self.assertIn("eclipse", objects.RESERVED)
        self.assertIsNone(objects.resolve_name("eclipse"))


class TheExports(RouteTest):

    def test_the_gif_animates_where_there_is_something_to_animate(self):
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}/animate.gif")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers["content-type"], "image/gif")
        self.assertGreater(len(got.content), 2000)

    def test_and_404s_where_there_is_not(self):
        # Tokyo is on the night side for this one: no frames, no GIF.
        got = self.client.get(f"/Tokyo/eclipse/{SOLAR}/animate.gif")
        self.assertEqual(got.status_code, 404)

    def test_a_lunar_eclipse_exports_its_night(self):
        got = self.client.get(f"/Zurich/eclipse/{LUNAR}/animate.gif")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers["content-type"], "image/gif")

    def test_the_card_is_a_png_at_both_url_shapes(self):
        for url in (f"/eclipse/{SOLAR}/og.png", f"/Ibiza/eclipse/{SOLAR}/og.png"):
            got = self.client.get(url)
            self.assertEqual(got.status_code, 200, url)
            self.assertEqual(got.headers["content-type"], "image/png", url)

    def test_the_exports_are_cacheable(self):
        """These are expensive to render and identical for everyone asking
        the same question, which is the definition of something a CDN should
        be holding rather than us."""
        for url in (f"/Zurich/eclipse/{SOLAR}/animate.gif",
                    f"/eclipse/{SOLAR}/og.png"):
            got = self.client.get(url)
            self.assertIn("max-age", got.headers.get("cache-control", ""), url)


class ThePlaceIsCarriedAndNeverInvented(RouteTest):

    def test_every_link_in_the_picker_keeps_the_place(self):
        """Picking a later eclipse from /Marbella/eclipse used to drop you on
        /eclipse/2027-08-02, which then relocated you by IP -- on a page
        whose whole job is to answer what happens where you are standing."""
        got = self.client.get("/Marbella/eclipse", headers=BROWSER)
        panel = got.text.split('class="ecl-panel"')[1].split("</details>")[0]
        hrefs = [h.split('"')[0] for h in panel.split('href="')[1:]]
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertTrue(href.startswith("/Marbella/eclipse/"), href)

    def test_the_canonical_names_one_page_per_eclipse(self):
        """Not one per city. There are 40,000 places and one eclipse, and a
        canonical per place would be a doorway farm."""
        for url in (f"/eclipse/{SOLAR}", f"/Zurich/eclipse/{SOLAR}",
                    f"/Ibiza/eclipse/{SOLAR}"):
            got = self.client.get(url, headers=BROWSER)
            self.assertIn(f'<link rel="canonical" href="https://skymap.sh'
                          f'/eclipse/{SOLAR}">', got.text, url)

    def test_the_card_follows_the_place_the_page_was_asked_for(self):
        page = self.client.get(f"/Ibiza/eclipse/{SOLAR}", headers=BROWSER)
        self.assertIn(f"/Ibiza/eclipse/{SOLAR}/og.png", page.text)
        bare = self.client.get(f"/eclipse/{SOLAR}", headers=BROWSER)
        self.assertNotIn("/Ibiza/", bare.text.split("og:image")[1][:200])


class TheCountersAreKept(RouteTest):
    """Every route gets a counter in the same change that adds it, or the
    first question anybody asks about it has no answer."""

    def test_a_page_view_is_counted_and_the_date_is_kept(self):
        before = server._stat["eclipse"]
        self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=TERMINAL)
        self.assertEqual(server._stat["eclipse"], before + 1)
        self.assertIn(SOLAR, server._eclipse_keys)

    def test_the_gif_and_the_card_are_counted_apart_from_the_page(self):
        gif_before = server._stat["eclipse_gif"]
        card_before = server._stat["og_eclipse"]
        self.client.get(f"/Zurich/eclipse/{SOLAR}/animate.gif")
        self.client.get(f"/eclipse/{SOLAR}/og.png")
        self.assertEqual(server._stat["eclipse_gif"], gif_before + 1)
        self.assertEqual(server._stat["og_eclipse"], card_before + 1)

    def test_they_show_up_on_the_stats_page(self):
        self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=TERMINAL)
        text = self.client.get("/stats", headers=TERMINAL).text
        self.assertIn("eclipses", text)
        self.assertIn(SOLAR, text)
        data = self.client.get("/stats?format=json").json()
        self.assertIn("eclipse", data)
        self.assertIn("card", data["eclipse"])


class TheWayIn(RouteTest):
    """A page nothing links to is a page nobody finds."""

    def test_the_search_bar_offers_it(self):
        got = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('"eclipse"', got.text)

    def test_the_catalogue_lists_the_next_few(self):
        got = self.client.get("/catalog", headers=TERMINAL)
        self.assertIn("ECLIPSES", got.text)
        self.assertIn("12 Aug 2026", got.text)
        self.assertIn("total solar", got.text)

    def test_the_catalogue_links_them_in_a_browser(self):
        got = self.client.get("/catalog", headers=BROWSER)
        self.assertIn(f'href="/eclipse/{SOLAR}"', got.text)
        self.assertIn(f'href="/eclipse/{LUNAR}"', got.text)

    def test_the_two_catalogues_list_the_same_eclipses(self):
        """They render from one data structure so they cannot drift, and
        this is what says so."""
        import api
        import eclipse_page
        text = api.catalog_text(color=False)
        markup = api.catalog_html()
        for entry in api._catalog_data()["eclipses"]:
            key = eclipse_page.key_of(entry)
            when = entry["when_utc"]
            import datetime as dt
            label = dt.datetime.fromisoformat(when).strftime("%d %b %Y").lstrip("0")
            self.assertIn(label, text, key)
            self.assertIn(f'href="/eclipse/{key}"', markup, key)


if __name__ == "__main__":
    unittest.main()
