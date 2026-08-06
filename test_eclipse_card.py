"""The social card for an eclipse page.

The card is the whole page for most of the people who ever meet it: a link
in a group chat, seen once, at about 350 pixels wide. So what these check is
that it says something true and specific at that size, and that the one
thing a card must never do -- report a crawler's location as the reader's --
cannot happen.
"""
import unittest

from starlette.testclient import TestClient

import server

SOLAR = "2026-08-12"
LUNAR = "2026-08-28"

BROWSER = {"accept": "text/html", "user-agent": "Mozilla/5.0"}


def setUpModule():
    # Same reason test_server.py lifts these: every TestClient here resolves
    # to one synthetic IP and the token bucket is shared for the process.
    server.RATE = server.BURST = 1_000_000


class CardTest(unittest.TestCase):
    """TestClient only runs the startup handler (which sets app.state.tle,
    needed by every route) inside its own context manager."""

    def setUp(self):
        cm = TestClient(server.app)
        self.client = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        server._buckets.clear()


class EveryPageThatAdvertisesACardHasOne(CardTest):
    """The tags shipped before the routes did, so every eclipse page spent a
    day pointing at a 404. That is worse than having no card: the platform
    caches the failure."""

    def test_the_tag_and_the_route_agree(self):
        for url in (f"/eclipse/{SOLAR}", f"/Ibiza/eclipse/{SOLAR}",
                    f"/eclipse/{LUNAR}", f"/Zurich/eclipse/{LUNAR}"):
            page = self.client.get(url, headers=BROWSER)
            self.assertEqual(page.status_code, 200, url)
            tag = page.text.split('og:image" content="')[1].split('"')[0]
            got = self.client.get(tag.replace("http://testserver", ""))
            self.assertEqual(got.status_code, 200, tag)
            self.assertEqual(got.headers["content-type"], "image/png")

    def test_a_place_page_advertises_that_places_card(self):
        page = self.client.get(f"/Ibiza/eclipse/{SOLAR}",
                          headers=BROWSER)
        self.assertIn(f"/Ibiza/eclipse/{SOLAR}/og.png", page.text)

    def test_a_bare_page_advertises_the_bare_card(self):
        page = self.client.get(f"/eclipse/{SOLAR}", headers=BROWSER)
        self.assertIn(f"/eclipse/{SOLAR}/og.png", page.text)
        self.assertNotIn(f"/eclipse/{SOLAR}/og.png", page.text.split(
            f"/eclipse/{SOLAR}/og.png", 1)[0])


class TheCardSaysSomethingTrue(CardTest):

    def _lines(self, key, place=None):
        r = server.api.Request(place=place) if place else None
        return server.api.compose_eclipse_card(r, key, place)

    def test_a_named_place_gets_its_own_answer(self):
        kicker, head, _detail, _rows = self._lines(SOLAR, "Ibiza")
        self.assertIn("IBIZA", (kicker + head).upper())
        self.assertIn("totality", head)

    def test_nobody_is_named_when_nobody_asked(self):
        """The one rule a card cannot break. It is fetched once by a crawler
        in a datacentre and then shown to everyone, so a place on a bare
        card is a machine's location presented as the reader's."""
        kicker, head, detail, _rows = self._lines(SOLAR)
        blob = " ".join((kicker, head, detail))
        for city in ("Ashburn", "Ibiza", "Zurich", "Zürich", "Virginia"):
            self.assertNotIn(city, blob)
        self.assertIn("2026", blob)
        self.assertIn("Greenland", blob)

    def test_a_place_that_sees_nothing_says_so(self):
        _kicker, head, _detail, rows = self._lines(SOLAR, "Tokyo")
        self.assertIn("not visible", head)
        # And falls back to the map, because there is no disc to draw.
        self.assertTrue(rows, "nothing at all to look at")

    def test_a_lunar_card_leads_with_the_moon(self):
        _kicker, head, _detail, rows = self._lines(LUNAR, "Zurich")
        self.assertIn("Moon", head)
        self.assertEqual(len(rows), server.api.eclipse_map.ART_ROWS)


class TheStatsTableSurvivesAnEclipse(CardTest):
    """A loop variable in the eclipse block was called n, which is also this
    function's row limit for every table below it. One visit to an eclipse
    page cut "top places" from fifty rows to one. Nothing about eclipses
    caught it; a test about the places table did, in a file that knows
    nothing about them. This is that test, kept here as well, next to the
    thing that broke it."""

    def test_a_visit_to_an_eclipse_page_does_not_shrink_the_tables(self):
        self.client.get(f"/eclipse/{SOLAR}", headers=BROWSER)
        server._places.clear()
        self.addCleanup(server._places.clear)
        for i in range(60):
            server._places[f"City{i}"] = 60 - i
        text = self.client.get("/stats", headers={"user-agent": "curl/8.0"}).text
        shown = text[text.find("top places"):]
        self.assertIn("City49", shown)


class TheCardIsAnImage(CardTest):

    def test_it_is_the_size_every_platform_expects(self):
        import io
        from PIL import Image
        got = self.client.get(f"/Ibiza/eclipse/{SOLAR}/og.png")
        img = Image.open(io.BytesIO(got.content))
        self.assertEqual(img.size, (1200, 630))

    def test_the_tags_promise_that_size(self):
        page = self.client.get(f"/eclipse/{SOLAR}", headers=BROWSER)
        self.assertIn('og:image:width" content="1200"', page.text)
        self.assertIn('og:image:height" content="630"', page.text)

    def test_an_eclipse_that_does_not_exist_has_no_card(self):
        self.assertEqual(self.client.get("/eclipse/2026-01-01/og.png").status_code, 404)
        self.assertEqual(
            self.client.get(f"/Nowhereville/eclipse/{SOLAR}/og.png").status_code, 404)

    def test_the_card_is_counted_separately(self):
        before = server._stat["og_eclipse"]
        self.client.get(f"/eclipse/{SOLAR}/og.png")
        self.assertEqual(server._stat["og_eclipse"], before + 1)


if __name__ == "__main__":
    unittest.main()
