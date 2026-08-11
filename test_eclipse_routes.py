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
import re
import unittest

from starlette.testclient import TestClient

import besselian
import eclipse_page
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

    def test_there_is_a_way_to_share_without_your_city_in_it(self):
        """Opening /eclipse/2026-08-12 bounces you to /Geneva/eclipse/... so
        the page can say Geneva rather than 46.20,6.10, and from then on the
        only URL you can copy has your location in it. Sharing that tells
        everyone who opens it what the eclipse does from Geneva, and the
        card that unfurls says Geneva too."""
        for url in (f"/eclipse/{SOLAR}", f"/Geneva/eclipse/{SOLAR}",
                    f"/Ibiza/eclipse/{LUNAR}"):
            got = self.client.get(url, headers=BROWSER)
            key = SOLAR if SOLAR in url else LUNAR
            box = got.text.split('id="ecl-share-box"')[1].split("</dialog>")[0]
            self.assertIn(f"https://skymap.sh/eclipse/{key}</code>", box, url)

    def test_the_place_link_is_offered_too_and_says_what_it_does(self):
        """Both are legitimate and they do opposite things. Picking one on
        the reader's behalf picks wrong for half of them."""
        got = self.client.get(f"/Ibiza/eclipse/{SOLAR}", headers=BROWSER)
        box = got.text.split('id="ecl-share-box"')[1].split("</dialog>")[0]
        self.assertIn(f"https://skymap.sh/eclipse/{SOLAR}</code>", box)
        self.assertIn(f"https://skymap.sh/Ibiza/eclipse/{SOLAR}</code>", box)
        self.assertIn("from where they are", box)
        self.assertIn("Everyone who opens it sees Ibiza", box)

    def test_both_links_are_offered_even_with_no_place_in_the_url(self):
        """Through a tunnel, or anywhere the CDN sends no coordinates, there
        is no bounce to a city URL -- and keying the second link off the
        route parameter meant the modal offered one link and no way to pin
        the place. Safe to name somebody here: this is behind a click, by a
        person. It is the meta tags and the card that must never report a
        crawler's location as the reader's, and they still do not."""
        got = self.client.get(f"/eclipse/{SOLAR}", headers=BROWSER)
        box = got.text.split('id="ecl-share-box"')[1].split("</dialog>")[0]
        self.assertEqual(box.count("<code"), 2)
        self.assertIn(f"https://skymap.sh/eclipse/{SOLAR}</code>", box)
        self.assertIn("Stays in", box)
        # ...while the tags above it still name nobody.
        desc = got.text.split('name="description" content="')[1].split('"')[0]
        self.assertIn("Greenland", desc)
        for city in ("Zurich", "Zürich", "Geneva"):
            self.assertNotIn(city, desc)

    def test_the_shared_link_is_the_canonical_one(self):
        """Not a second URL to keep in step with it: the link that follows
        the reader and the link worth indexing are the same link."""
        got = self.client.get(f"/Ibiza/eclipse/{SOLAR}", headers=BROWSER)
        box = got.text.split('id="ecl-share-box"')[1].split("</dialog>")[0]
        first = box.split("<code")[1].split(">")[1].split("<")[0]
        self.assertIn(f'<link rel="canonical" href="{first}">', got.text)

    def test_the_share_button_does_not_need_a_secure_context(self):
        """The regression this replaces: the script gated on
        navigator.clipboard before unhiding the button, and that API exists
        only in a secure context. Over plain http the early return fired and
        the button was never revealed, so skymap.sh/eclipse had no share
        control and https://skymap.sh/eclipse had one.

        http is not an edge case on this site. `curl skymap.sh` is the whole
        point of it and curl does not follow a redirect without -L, so http
        has to keep serving real pages and anything that quietly needs TLS
        breaks for half the traffic.

        Checked on the rendered script rather than the source, because it is
        the shipped gate that decides whether the button appears."""
        page = self.client.get(f"/Ibiza/eclipse/{SOLAR}", headers=BROWSER).text
        self.assertIn("if(!b||!d||!d.showModal)return;", page)
        self.assertNotIn("!navigator.clipboard||", page)
        # The button still ships hidden and is still revealed by script --
        # that part was never the bug.
        self.assertIn('id="ecl-share" hidden', page)
        self.assertIn("b.hidden=false;", page)

    def test_copy_falls_back_to_the_selection_without_a_clipboard(self):
        """The copy buttons are the only part that ever needed the API. Where
        it is missing they select the URL and ask the browser to copy its own
        selection, which is deprecated and works over http, which is the only
        place it is reached."""
        got = self.client.get(f"/Ibiza/eclipse/{SOLAR}", headers=BROWSER)
        self.assertIn("navigator.clipboard&&navigator.clipboard.writeText",
                      got.text)
        self.assertIn("document.execCommand('copy')", got.text)
        self.assertIn("r.selectNodeContents(t)", got.text)

    def test_a_crawler_following_it_gets_the_card_that_names_nobody(self):
        """Which is what makes the bare link the right one to share: the
        person who opens it is bounced to their own city, and the unfurler
        that fetches it is not bounced at all."""
        got = self.client.get(f"/eclipse/{SOLAR}",
                              headers={"user-agent": "Twitterbot/1.0",
                                       "accept": "*/*"})
        self.assertEqual(got.status_code, 200)
        self.assertIn(f'/eclipse/{SOLAR}/og.png"', got.text)
        # And the sentence beside it names nobody either. The image was
        # careful about this and the text was not, which is the worse half:
        # a wrong picture is a wrong picture, a wrong sentence reads as a
        # fact about the reader's own sky.
        desc = got.text.split('name="description" content="')[1].split('"')[0]
        for city in ("Zurich", "Zürich", "Geneva", "Ashburn"):
            self.assertNotIn(city, desc)
        self.assertIn("Greenland", desc)

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


class TheMapFitsItsColumn(RouteTest):
    """It is a fixed number of characters wide -- 96 for a solar eclipse's
    region, 128 for a lunar one's whole world -- so the font size has to come
    off the column, not off a constant. The first attempt divided by a
    parenthesised product inside calc(), which is where calc() support
    actually stops: the whole declaration was thrown away and the map went
    back to 11px and a sideways scrollbar with half the track off the edge."""

    def test_the_markup_carries_a_scale_the_stylesheet_can_use(self):
        for url, cols in ((f"/Zurich/eclipse/{SOLAR}", 96),
                          (f"/Zurich/eclipse/{LUNAR}", 128)):
            got = self.client.get(url, headers=BROWSER)
            pre = got.text.split('class="ecl-map"')[1][:60]
            self.assertIn("--colf:", pre, url)
            colf = float(pre.split("--colf:")[1].split('"')[0])
            self.assertAlmostEqual(colf, 1.0 / (cols * 0.66), places=4)

    def test_the_map_never_offers_to_scroll(self):
        """A <pre> here picks up overflow-x:auto from three separate rules,
        and a box a hair narrower than its contents then grows a scrollbar
        under a map that looks perfectly complete. There is nothing to
        scroll -- the map is sized to fit -- so it takes its own content's
        width and does not offer."""
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)
        rule = got.text.split(".obj-live pre.ecl-map{")[1].split("}")[0]
        self.assertIn("overflow:visible", rule)
        self.assertIn("width:max-content", rule)

    def test_the_rule_outweighs_the_one_it_has_to_beat(self):
        """The div the map sits in sets overflow-x:auto on every <pre> in it,
        as ".obj-live pre" -- a class and an element, (0,1,1). A bare
        ".ecl-map" is (0,1,0) and loses, so turning that overflow off from
        here was discarded before it ever reached the browser. Five attempts
        at the font size went past this without touching it."""
        import re
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)

        def weight(sel):
            return (sel.count("."), len(re.findall(r"(?:^|\s)(?!\.)[a-z]+", sel)))

        loser = weight(".obj-live pre")
        winner = weight(".obj-live pre.ecl-map")
        self.assertGreater(winner, loser)
        self.assertIn(".obj-live pre.ecl-map{", got.text)

    def test_the_column_is_the_container_and_there_is_only_one_box(self):
        """A container query cannot measure the element it sizes, so one
        ancestor has to volunteer. It used to be a wrapper div that did
        nothing else, which meant reasoning about two widths where there is
        only one that matters: the column the map has to fit inside."""
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)
        self.assertIn(".obj-live{container-type:inline-size}", got.text)
        self.assertNotIn("ecl-mapwrap", got.text)

    def test_the_map_fits_at_every_size_the_clamp_allows(self):
        """The arithmetic the stylesheet does, done here. A glyph is at most
        0.602em wide in any of the fonts offered, and the estimate is 0.66,
        so there is real room rather than a pixel or two -- sized to exactly
        the column, the box grew a scrollbar under a map that looked
        perfectly complete."""
        for cols in (96, 128):
            colf = 1.0 / (cols * 0.66)
            for column_px in (430, 600, 740, 760, 1000):
                size = min(12.0, max(5.5, column_px * colf))
                width = cols * size * 0.602
                self.assertLess(width, column_px, f"{cols} cols in {column_px}px")


def phone_block(markup, needle):
    """The phone rules for `needle`, out of the page's stylesheet.

    The page carries more than one 700px block -- the header has its own --
    so this picks the one that mentions the thing being asked about rather
    than the last one written."""
    for block in markup.split("@media (max-width:700px){")[1:]:
        body = block.split("\n}")[0]
        if needle in body:
            return body
    raise AssertionError(f"no phone block mentions {needle}")


class ThePhoneReadsTheTimesInOneBlock(RouteTest):
    """Five labelled numbers at desktop spacing wrap into a ragged block two
    or three lines deep on a phone, and they are the answer the page exists
    to give."""

    def test_the_place_takes_its_own_line_and_the_times_close_up(self):
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)
        rule = phone_block(got.text, ".ecl-times")
        self.assertIn(".ecl-where{flex:0 0 100%", rule)
        self.assertIn(".ecl-times div{min-width:0}", rule)

    def test_the_numbers_stay_a_row(self):
        """The element carries .obj-live-head and .ecl-head as well, and the
        rule that unstacks the header sets display on those two. A one-class
        rule here loses to it, and the row becomes five blocks -- one number
        per line, the opposite of the point."""
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)
        rule = phone_block(got.text, ".ecl-times")
        self.assertIn(".obj-live-head.ecl-times{display:flex", rule)
        self.assertNotIn(".ecl-head{min-height:0;display:block}", rule)

    def test_the_reserved_height_goes_when_there_is_nothing_to_align(self):
        """It exists to keep the two drawings level side by side. Stacked,
        it is a hole above the times."""
        got = self.client.get(f"/Zurich/eclipse/{SOLAR}", headers=BROWSER)
        rule = phone_block(got.text, ".ecl-sec")
        self.assertIn("min-height:0", rule)
        # ...and it is still there for the side-by-side case.
        self.assertIn("min-height:3.3rem", got.text)


class TheWayIn(RouteTest):
    """A page nothing links to is a page nobody finds."""

    def test_the_search_bar_offers_it(self):
        got = self.client.get("/Zurich", headers=BROWSER)
        self.assertIn('"eclipse"', got.text)

    def test_the_catalogue_says_how_far_the_table_goes(self):
        """Six dates say nothing about whether this is a handful or a decade
        of them, and the answer is the reason to come back."""
        import eclipse_page
        span = eclipse_page.table_span()
        self.assertIn("eclipses tracked", span)
        for headers in (TERMINAL, BROWSER):
            got = self.client.get("/catalog", headers=headers)
            self.assertIn(span, got.text)

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


class TheDrawingsSitOnTheSharedPlate(RouteTest):
    """Every picture made of characters uses one component: .art-frame does
    the centring, .art-plate pins the cell ratio the drawing was built for.

    This exists because the eclipse pages were left behind once already.
    3e6b198 moved the centring out of .obj-art-frame and into .art-frame,
    updated api.py, and did not touch eclipse_page.py -- so both eclipse
    drawings went on carrying a class that no longer centred anything and
    sat jammed against the left edge of their frames, on prod, until
    somebody looked. A grep is enough to catch that, and nothing else was.
    """

    def frames(self, html):
        """(wrapper class list, pre class list) for every drawing found."""
        pairs = re.findall(
            r'<div class="([^"]*art-frame[^"]*|[^"]*obj-art-frame[^"]*)">'
            r'\s*<pre class="([^"]*)"', html)
        return pairs

    def test_the_solar_page_centres_both_its_drawings(self):
        r = self.client.get("/Zurich/eclipse/2026-08-12", headers=BROWSER)
        self.assertEqual(r.status_code, 200)
        found = self.frames(r.text)
        self.assertTrue(found, "no drawing found on the eclipse page")
        for frame_cls, plate_cls in found:
            self.assertIn("art-frame", frame_cls.split(),
                          f"wrapper does not centre: {frame_cls}")
            self.assertIn("art-plate", plate_cls.split(),
                          f"plate has no cell ratio: {plate_cls}")

    def test_the_animation_frame_is_one_of_them(self):
        r = self.client.get("/Zurich/eclipse/2026-08-12", headers=BROWSER)
        self.assertIn('class="art-frame obj-art-frame ecl-anim"', r.text)
        self.assertIn('class="art-plate obj-art" id="ecl-play"', r.text)

    def test_a_lunar_page_too(self):
        r = self.client.get("/eclipse", headers=BROWSER)
        self.assertEqual(r.status_code, 200)
        for frame_cls, plate_cls in self.frames(r.text):
            self.assertIn("art-frame", frame_cls.split())
            self.assertIn("art-plate", plate_cls.split())

    def test_the_border_did_not_go_with_the_centring(self):
        # Both classes, not one instead of the other: .obj-art-frame is still
        # what gives the drawing its border and its floor height.
        r = self.client.get("/Zurich/eclipse/2026-08-12", headers=BROWSER)
        self.assertIn("obj-art-frame", r.text)


class TotalityIsNeverClaimedShortOfIt(unittest.TestCase):
    """Bilbao on 12 August 2026 is 99.979% covered and outside the path.
    Rounded for display that read "100% covered", one line above the
    paragraph saying this page will not tell you whether the Sun is fully
    covered there. 100% is the number somebody takes their filter off for.
    """

    BILBAO = (43.257, -2.924)
    IBIZA = (38.91, 1.43)

    def local(self, lat, lon):
        return besselian.local("2026-08-12", lat, lon)

    def test_a_hair_short_of_total_never_prints_a_hundred(self):
        f = self.local(*self.BILBAO)
        self.assertNotEqual(f["kind"], "total")
        self.assertGreater(f["obscuration"], 0.995)
        self.assertEqual(eclipse_page.covered_pct(f), ">99%")
        self.assertEqual(eclipse_page.covered_pct(f, 1), ">99.9%")

    def test_real_totality_still_prints_a_hundred(self):
        f = self.local(*self.IBIZA)
        self.assertEqual(f["kind"], "total")
        self.assertEqual(eclipse_page.covered_pct(f), "100%")

    def test_ordinary_values_are_left_alone(self):
        for pct, want in ((0.904612, "90%"), (0.946496, "95%"), (0.5, "50%")):
            f = {"obscuration": pct, "kind": "partial"}
            self.assertEqual(eclipse_page.covered_pct(f), want)

    def test_the_page_itself_does_not_say_a_hundred_at_bilbao(self):
        client_cm = TestClient(server.app)
        client = client_cm.__enter__()
        self.addCleanup(client_cm.__exit__, None, None, None)
        body = client.get("/Bilbao/eclipse/2026-08-12", headers=TERMINAL).text
        self.assertIn("covered", body)
        self.assertNotIn("100% covered", body)
        self.assertNotIn("100.0% of the Sun", body)
