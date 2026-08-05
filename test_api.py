#!/usr/bin/env python3
"""Tests for the nearest-city timezone fallback in api.py.

Run:  python3 test_api.py
"""
import datetime as dt
import os
import json
import unittest
import api
import sky


class Aliases(unittest.TestCase):
    def test_airport_code_aliases_resolve(self):
        expected = {
            "cph": "Copenhagen", "bcn": "Barcelona", "ams": "Amsterdam",
            "cdg": "Paris", "lhr": "London", "fra": "Frankfurt",
            "muc": "Munich", "dxb": "Dubai", "sin": "Singapore",
            "ist": "Istanbul",
        }
        for code, city in expected.items():
            p = api.lookup_place(code)
            self.assertIsNotNone(p, f"'{code}' did not resolve at all")
            self.assertEqual(p.name, city, f"'{code}' resolved to {p.name!r}")


class NearestCity(unittest.TestCase):
    def test_finds_a_city_near_geneva(self):
        # 46.20, 6.10 is near the Geneva/Lausanne area.
        near = api._nearest_city(46.20, 6.10)
        self.assertIsNotNone(near)
        _lat, _lon, zone, _iso2, country, *_rest = near
        self.assertIn(country, ("Switzerland", "France"))
        self.assertTrue(zone)

    def test_prefers_the_recognisable_city_over_a_closer_suburb(self):
        # Vernier (a Geneva suburb, near the airport) can be a touch closer to
        # these exact coordinates than Geneva itself -- the fix must still
        # surface Geneva, since nobody looks up a chart and expects "Vernier".
        near = api._nearest_city(46.20, 6.10)
        self.assertEqual(near[7], "Geneva")

    def test_none_in_the_middle_of_the_ocean(self):
        # South Pacific, nowhere near land.
        near = api._nearest_city(-30.0, -140.0)
        self.assertIsNone(near)

    def test_memoised_result_is_consistent(self):
        first = api._nearest_city(46.20, 6.10)
        second = api._nearest_city(46.20, 6.10)
        self.assertEqual(first, second)

    def test_cache_does_not_leak_between_different_radii(self):
        # Regression: the memo cache used to key on (lat, lon) alone, so
        # whichever radii combination ran first for a cell silently answered
        # every later call for that same cell, radii ignored.
        lat, lon = 51.0, -60.0   # far enough from anything for a tight max
                                 # radius to plausibly miss while a wide one
                                 # (Canada's east coast) still hits.
        wide = api._nearest_city(lat, lon, prefer_radius_deg=0.5, max_radius_deg=5)
        tight = api._nearest_city(lat, lon, prefer_radius_deg=0.5, max_radius_deg=0.5)
        if wide is not None:
            self.assertIsNone(tight)


class ConfidentNearbyCity(unittest.TestCase):
    """_confident_nearby_city backs the browser-only redirect from raw
    coordinates to a city name (server.py's _respond) -- unlike
    _nearest_city's own up-to-~550 km fallback (a soft "near X" hint, never
    an identity claim), this only ever returns a city close enough (~55 km)
    that swapping the coordinates for its name is still an honest thing to
    show in the URL bar and search field."""

    def test_confident_when_squarely_in_a_city(self):
        self.assertEqual(api._confident_nearby_city(46.20, 6.15), "Geneva")

    def test_still_confident_a_little_off_centre(self):
        self.assertEqual(api._confident_nearby_city(46.25, 6.20), "Geneva")

    def test_none_far_from_any_city(self):
        # Mid-Atlantic -- _nearest_city's wider fallback might still name
        # something an ocean away; this must not.
        self.assertIsNone(api._confident_nearby_city(30.0, -40.0))

    def test_none_at_the_pole(self):
        self.assertIsNone(api._confident_nearby_city(90.0, 0.0))


class CoordinatesOnlyClaimACityTheyAreActuallyIn(unittest.TestCase):
    """The browser bounces raw coordinates to a nearby city's name, which
    replaces the coordinates in the URL and in everything computed from
    them. It used to claim any city within ~55 km, which made a spot 31 km
    up in the Jura render as Geneva -- a different valley, and a sky three
    and a half magnitudes darker. The reach now comes from the city's own
    population, because cities are not one size."""

    def test_a_dark_site_outside_town_is_not_that_town(self):
        self.assertIsNone(api._confident_nearby_city(46.42, 5.90))

    def test_and_its_sky_is_genuinely_different(self):
        # The reason this matters rather than being pedantry about names.
        jura = api.sky_brightness(46.42, 5.90)
        city = api.sky_brightness(46.20, 6.15)
        self.assertGreater(jura[0] - city[0], 3.0)
        self.assertGreater(api.milkyway_floor(46.42, 5.90), 0)
        self.assertEqual(api.milkyway_floor(46.20, 6.15), 0)

    def test_a_city_still_claims_its_own_centre_and_edges(self):
        self.assertEqual(api._confident_nearby_city(46.20, 6.15), "Geneva")
        self.assertEqual(api._confident_nearby_city(46.24, 6.09), "Geneva")

    def test_a_big_city_reaches_further_than_a_small_one(self):
        # 30 km from the middle of London is still London; 30 km from the
        # middle of Geneva is not Geneva. One rule, two answers, because the
        # radius comes from the population.
        self.assertEqual(api._confident_nearby_city(51.75, -0.35), "London")
        self.assertIsNone(api._confident_nearby_city(46.42, 5.90))

    def test_the_middle_of_an_ocean_claims_nothing(self):
        self.assertIsNone(api._confident_nearby_city(30.0, -40.0))
        self.assertIsNone(api._confident_nearby_city(90.0, 0.0))


class CompleteCities(unittest.TestCase):
    """complete_cities backs the command bar's ghost completion (GET
    /complete, SPEC-command-bar.md #4) -- narrower than suggest(): prefix
    only, bare display names, most populous first."""

    def test_ranks_by_population_not_alphabetically(self):
        # Newcastle < New York alphabetically, but New York is a much
        # bigger city -- the whole point of ranking by population.
        res = api.complete_cities("new")
        self.assertEqual(res[0], "New York")

    def test_case_insensitive(self):
        self.assertEqual(api.complete_cities("NEW")[0], "New York")

    def test_accent_folded(self):
        # "zur" has to reach "Zürich" despite the umlaut.
        self.assertIn("Zürich", api.complete_cities("zur"))

    def test_prefix_only_not_contains(self):
        # suggest()'s looser startswith-or-contains match is deliberately
        # not used here -- "ork" must not surface "New York".
        self.assertNotIn("New York", api.complete_cities("ork"))

    def test_returns_bare_names_not_disambiguated_labels(self):
        for name in api.complete_cities("gene"):
            self.assertNotIn(",", name)

    def test_capped_at_n(self):
        self.assertLessEqual(len(api.complete_cities("a", n=3)), 3)

    def test_no_duplicate_names(self):
        res = api.complete_cities("san")
        self.assertEqual(len(res), len(set(res)))

    def test_short_prefix_returns_nothing(self):
        self.assertEqual(api.complete_cities("n"), [])
        self.assertEqual(api.complete_cities(""), [])

    def test_unknown_prefix_returns_nothing(self):
        self.assertEqual(api.complete_cities("xyzzynonexistent"), [])

    def test_oversized_prefix_is_capped_not_scanned_in_full(self):
        # A pathologically long ?q= must not turn this into an unbounded
        # scan -- it's truncated to COMPLETE_PREFIX_CAP first.
        long_prefix = "new" + "x" * 100
        self.assertEqual(api.complete_cities(long_prefix), [])


class CitySizeBands(unittest.TestCase):
    """The dropdown draws a bigger dot for a bigger city, which needs a
    population band the endpoint can send. with_pop is opt-in so the plain
    string form (and everything that reads it) is unchanged."""

    def test_bands_are_the_ordinary_meanings_of_the_words(self):
        self.assertEqual(api.city_size(8_000_000), 3)   # major city
        self.assertEqual(api.city_size(1_000_000), 3)   # on the line
        self.assertEqual(api.city_size(250_000), 2)     # city
        self.assertEqual(api.city_size(100_000), 2)     # on the line
        self.assertEqual(api.city_size(4_000), 1)       # town
        self.assertEqual(api.city_size(0), 1)

    def test_default_shape_is_still_bare_strings(self):
        for row in api.complete_cities("lon"):
            self.assertIsInstance(row, str)

    def test_with_pop_adds_a_band_to_every_row(self):
        rows = api.complete_cities("lon", with_pop=True)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row["size"], (1, 2, 3))
            self.assertIsInstance(row["name"], str)

    def test_the_band_tracks_the_ranking_already_used(self):
        # Rows come back most populous first, so the bands can only ever
        # descend. A row banded higher than the one above it would mean the
        # size came from somewhere other than the sort key.
        bands = [r["size"] for r in api.complete_cities("lon", with_pop=True)]
        self.assertEqual(bands, sorted(bands, reverse=True))

    def test_london_is_a_major_city(self):
        rows = api.complete_cities("london", with_pop=True)
        self.assertEqual(rows[0]["name"], "London")
        self.assertEqual(rows[0]["size"], 3)


class CompleteObjects(unittest.TestCase):
    """complete_objects backs the find field's dropdown (GET
    /complete/objects) -- same _catalog_data() /catalog renders from, so a
    suggestion can't drift from what's actually findable."""

    def test_finds_a_planet(self):
        res = api.complete_objects("ven")
        self.assertTrue(any(o["name"] == "Venus" for o in res))

    def test_finds_a_named_star(self):
        res = api.complete_objects("veg")
        self.assertTrue(any(o["name"] == "Vega" for o in res))

    def test_matches_a_later_word_not_just_the_start(self):
        # "Big Dipper" should surface on "dip", not just "big".
        res = api.complete_objects("dip")
        self.assertTrue(any(o["name"] == "Big Dipper" for o in res))

    def test_case_insensitive(self):
        self.assertTrue(any(o["name"] == "Venus" for o in api.complete_objects("VEN")))

    def test_each_result_has_a_glyph_and_colour(self):
        for o in api.complete_objects("ven"):
            self.assertIn("glyph", o)
            self.assertTrue(o["color"].startswith("#"))

    def test_capped_at_n(self):
        self.assertLessEqual(len(api.complete_objects("a", n=3)), 3)

    def test_short_prefix_returns_nothing(self):
        self.assertEqual(api.complete_objects("v"), [])
        self.assertEqual(api.complete_objects(""), [])

    def test_unknown_prefix_returns_nothing(self):
        self.assertEqual(api.complete_objects("xyzzynonexistent"), [])

    def test_oversized_prefix_is_capped_not_scanned_in_full(self):
        long_prefix = "ven" + "x" * 100
        self.assertEqual(api.complete_objects(long_prefix), [])


class EverySuggestionIsActuallyFindable(unittest.TestCase):
    """The find dropdown showed the Moon as "Moon (last quarter)" and then
    submitted that label as the search, which resolve_target could not parse
    -- so the one object whose label is not its name was the one object you
    could see in the list and not find."""

    LAT, LON = 46.20, 6.15

    def when(self):
        jd = sky.julian(dt.datetime(2026, 8, 4, 22, 0))
        return jd, (sky.gmst_hours(jd) + self.LON / 15.0) % 24

    def test_the_moon_suggestion_carries_a_searchable_name(self):
        moon = [o for o in api.complete_objects("moo") if "Moon" in o["name"]]
        self.assertTrue(moon)
        self.assertEqual(moon[0]["q"], "Moon")
        # The label still shows the phase -- that is why it exists.
        self.assertIn("(", moon[0]["name"])

    def test_every_suggestion_resolves_by_what_it_would_submit(self):
        jd, lst = self.when()
        for prefix in ("moo", "ven", "veg", "dip", "m31", "sun", "ori",
                       "and", "jup", "sat", "alt", "rig", "tea", "ple"):
            for o in api.complete_objects(prefix):
                q = o.get("q") or o["name"]
                self.assertIsNotNone(
                    sky.resolve_target(q, jd, self.LAT, lst),
                    f"{o['name']!r} suggests a query {q!r} that finds nothing")

    def test_the_label_already_shared_in_links_still_resolves(self):
        # The broken string is in browser history and in any URL anyone
        # copied while it was live, so it has to keep working.
        jd, lst = self.when()
        for s in ("Moon (last quarter)", "moon (waxing crescent)",
                  "Moon (full)", "  Moon (new)  "):
            t = sky.resolve_target(s, jd, self.LAT, lst)
            self.assertIsNotNone(t, s)
            self.assertEqual(t["name"], "Moon")

    def test_a_bracket_does_not_swallow_a_real_name(self):
        # Nothing findable has a bracket in its name, but a query that is
        # only a parenthetical must not silently become an empty search.
        jd, lst = self.when()
        self.assertIsNone(sky.resolve_target("(last quarter)", jd, self.LAT, lst))
        self.assertIsNone(sky.resolve_target("()", jd, self.LAT, lst))


class OneSearchBar(unittest.TestCase):
    """There is exactly one input. The separate find field is gone: it only
    ever existed on chart pages, so /events and /catalog had nowhere to type
    an object, and it split one question across two boxes."""

    def test_no_second_field_anywhere(self):
        for html_out in (api.header_html("Zurich/"),
                         api.header_html("Zurich/Venus"),
                         api.header_html("catalog")):
            self.assertNotIn('id="find"', html_out)
            self.assertNotIn('id="findbar"', html_out)
            self.assertEqual(html_out.count('name="q"'), 1)

    def test_the_bar_carries_its_dropdown_and_help_on_every_page(self):
        for value in ("Zurich", "catalog", "help", "stats"):
            html_out = api.header_html(value)
            self.assertIn('id="bar-dropdown"', html_out, value)
            self.assertIn('id="help-pill"', html_out, value)
            self.assertIn('id="search-help"', html_out, value)

    def test_copy_pill_is_gone(self):
        self.assertNotIn('id="copy"', api.header_html("Zurich"))


class SearchBarIsThePath(unittest.TestCase):
    """The bar shows exactly what follows skymap.sh/ and nothing else, so
    the command it displays is the command it runs. No side-channel saying
    which place is really meant."""

    def test_no_hidden_place_state(self):
        # An earlier version carried the place beside the query so the
        # server could recombine them, which let the bar read
        # "skymap.sh/venus" while the destination was /Tokyo/Venus.
        for value in ("Tokyo/", "Tokyo/Venus", "catalog"):
            html_out = api.header_html(value)
            self.assertNotIn("data-place", html_out)
            self.assertNotIn('name="from"', html_out)

    def test_the_value_is_rendered_verbatim(self):
        for value in ("Tokyo/", "Tokyo/Venus", "Venus", "catalog"):
            self.assertIn(f'name="q" value="{value}"', api.header_html(value))

    def test_the_value_is_escaped(self):
        html_out = api.header_html('"><script>')
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)


class SearchHelpPanel(unittest.TestCase):
    """The pill's panel, which is the only thing on the page that says the
    one bar takes all three kinds of thing."""

    def test_names_all_three_kinds(self):
        for word in ("Locations", "Objects", "Pages"):
            self.assertIn(f"<dt>{word}</dt>", api.SEARCH_HELP)

    def test_mentions_coordinates_and_links_the_catalog(self):
        self.assertIn("coordinates", api.SEARCH_HELP)
        self.assertIn('href="/catalog"', api.SEARCH_HELP)

    def test_lists_exactly_the_pages_the_dropdown_offers(self):
        # One tuple drives the panel's text and the dropdown's list (spliced
        # into PAGE as /*PAGES*/), so the advertised set cannot drift from
        # the offered one.
        for page in api.SEARCH_PAGES:
            self.assertIn(page, api.SEARCH_HELP)
        self.assertIn(json.dumps(list(api.SEARCH_PAGES)), api.PAGE)

    def test_stats_is_not_advertised_but_still_resolves(self):
        # Deliberately absent until the page is worth pointing at. Typing it
        # still works -- that is the ?q= redirect's job, not this list's.
        self.assertNotIn("stats", api.SEARCH_PAGES)


class ExploreVariants(unittest.TestCase):
    """EXPLORE (every page but the chart view) keeps its own #find input in
    the drawer; EXPLORE_DATETIME (the chart view) doesn't."""

    def test_explore_has_a_find_input(self):
        self.assertIn('id="find"', api.EXPLORE)

    def test_explore_datetime_has_no_find_input(self):
        self.assertNotIn('id="find"', api.EXPLORE_DATETIME)

    def test_explore_datetime_reads_the_missing_find_null_safely(self):
        # The chart page used to be guaranteed a #find in the header, so
        # this read it straight. Merging that field into the search bar took
        # the guarantee away, and an unguarded .value on a missing element
        # throws before location.href is reached -- "go" would have done
        # nothing at all on the one page type that has a chart.
        self.assertIn("var fEl=document.getElementById('find');",
                      api.EXPLORE_DATETIME)
        self.assertIn("var f=fEl?fEl.value.trim():'';", api.EXPLORE_DATETIME)
        self.assertNotIn("document.getElementById('find').value",
                         api.EXPLORE_DATETIME)

    def test_explore_datetime_still_has_date_time_and_go(self):
        self.assertIn('id="whenDate"', api.EXPLORE_DATETIME)
        self.assertIn('id="whenTime"', api.EXPLORE_DATETIME)
        self.assertIn('id="explore"', api.EXPLORE_DATETIME)


class ResolvePlaceFallback(unittest.TestCase):
    def test_bare_coordinates_keep_the_coordinates_as_name(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        self.assertEqual(p.name, "46.20,6.10")

    def test_bare_coordinates_get_a_real_timezone_not_longitude_over_15(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        # longitude/15 for 6.10 rounds to 0 -- the bug. A real zone must not.
        self.assertNotEqual(p.zone, None)
        self.assertNotEqual(round(p.lon / 15.0), self._true_offset(p))

    def test_bare_coordinates_carry_a_near_city_hint(self):
        p = api.resolve_place(None, fallback=(46.20, 6.10))
        self.assertIsNotNone(p.near)

    def test_unresolvable_coordinates_fall_back_to_longitude(self):
        p = api.resolve_place(None, fallback=(-30.0, -140.0))
        self.assertIsNone(p.zone)
        self.assertIsNone(p.near)

    @staticmethod
    def _true_offset(p):
        import datetime as dt
        return p.offset(dt.datetime(2026, 7, 30, 8, 32))


class DsoAndQuadrantRequests(unittest.TestCase):
    """?dso= and ?quadrant= are off/unset by default and only take effect on
    the night chart -- covers the Request plumbing added alongside them."""

    def _night_request(self, **kw):
        return api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0),
                           night=True, **kw)

    def test_defaults_are_off(self):
        r = api.Request(place="Zurich")
        self.assertFalse(r.dso)
        self.assertIsNone(r.quadrant)

    def test_quadrant_letter_is_upper_cased(self):
        r = api.Request(place="Zurich", quadrant="b")
        self.assertEqual(r.quadrant, "B")

    def test_bare_quadrant_implies_dso(self):
        r = api.Request(place="Zurich", quadrant="A")
        self.assertTrue(r.dso)

    def test_nodso_opts_out_of_the_quadrant_implied_dso(self):
        r = api.Request(place="Zurich", quadrant="A", nodso=True)
        self.assertFalse(r.dso)
        self.assertEqual(r.quadrant, "A")  # the grid itself is unaffected

    def test_nodso_has_no_effect_without_quadrant_or_dso(self):
        r = api.Request(place="Zurich", nodso=True)
        self.assertFalse(r.dso)

    def test_multi_char_garbage_is_dropped_before_it_can_reach_a_cache_key(self):
        # A single letter (or None) is the only shape ?quadrant= is allowed to
        # take by the time it reaches Request -- otherwise arbitrary garbage
        # values would each mint a fresh cache entry (server._cache_key keys
        # on r.quadrant), a free cache-busting surface.
        r = api.Request(place="Zurich", quadrant="ZZ")
        self.assertIsNone(r.quadrant)
        r = api.Request(place="Zurich", quadrant="7")
        self.assertIsNone(r.quadrant)

    def test_dso_flag_reaches_the_composed_output(self):
        r = self._night_request(dso=True)
        res = api.compose(r)
        self.assertTrue(res.data["dso"])
        self.assertIn("dso=1", res.text)

    def test_quadrant_reaches_the_composed_output(self):
        r = self._night_request(quadrant="A")
        res = api.compose(r)
        self.assertEqual(res.data["quadrant"]["applied"], "A")
        self.assertIn("quadrant A", res.text)

    def test_unknown_quadrant_is_reported_not_errored(self):
        # "Z" is a well-formed single letter, just not one the default grid
        # (A-F) generates -- this is the realistic typo case, distinct from
        # the malformed-input case covered above.
        r = self._night_request(quadrant="Z")
        res = api.compose(r)
        self.assertEqual(res.status, 200)
        self.assertEqual(res.data["quadrant"]["error"], "Z")
        self.assertIsNone(res.data["quadrant"]["applied"])

    def test_png_url_carries_both_params(self):
        r = self._night_request(dso=True, quadrant="C")
        url = api._png_url(r)
        self.assertIn("dso=1", url)
        self.assertIn("quadrant=C", url)


class SideBySideHelper(unittest.TestCase):
    """_side_by_side zips two text blocks into one, left padded to its own
    widest *visible* line -- the underlying tool the ?panel=1 side-panel
    layout is built on."""

    def test_pads_left_to_its_widest_visible_line(self):
        out = api._side_by_side(["ab", "abcde"], ["X", "Y"], gap=1)
        self.assertEqual(out[0], "ab    X")
        self.assertEqual(out[1], "abcde Y")

    def test_row_with_no_right_content_has_no_trailing_padding(self):
        out = api._side_by_side(["a", "b", "c"], ["X"], gap=2)
        self.assertEqual(out[1], "b")
        self.assertEqual(out[2], "c")

    def test_measures_by_visible_width_not_raw_ansi_length(self):
        # One visible character, but a much longer raw string once the
        # colour codes are in it -- padding on raw length would misalign
        # the right column.
        colored = "\033[38;5;255mA\033[0m"
        out = api._side_by_side([colored, "BB"], ["", "R"], gap=1)
        self.assertEqual(out[0], colored)
        self.assertEqual(out[1], "BB R")


class ZenithInsetOrientation(unittest.TestCase):
    """The panorama centres its sweep on south up north and on north down
    south, because that is where the ecliptic rides high. The inset stayed
    north-up everywhere, so south of the equator the strip and the disc put
    the same sky on opposite sides."""

    def _inset(self, place):
        r = api.Request(place=place, when=dt.datetime(2026, 8, 4, 22, 0),
                        panel=True, night=True, color=False)
        _chart, zenith, _prose = api.split_chart_parts(api.compose(r).text)
        return [l for l in zenith.split("\n") if l.strip()]

    def _cardinal_positions(self, lines):
        # Only inside the disc itself: a star name sits three spaces past
        # its right edge and can hold any letter. Within the disc the
        # cardinals are the only alphabetic characters there are.
        pos = {}
        for row, line in enumerate(lines):
            for col, ch in enumerate(line[:21]):
                if ch in "NESW":
                    pos.setdefault(ch, (row, col))
        return pos

    def test_north_up_and_east_left_in_the_northern_hemisphere(self):
        pos = self._cardinal_positions(self._inset("Zurich"))
        self.assertLess(pos["N"][0], pos["S"][0])      # north above south
        self.assertLess(pos["E"][1], pos["W"][1])      # east left of west

    def test_turned_half_a_circle_in_the_southern_hemisphere(self):
        pos = self._cardinal_positions(self._inset("Wellington"))
        self.assertLess(pos["S"][0], pos["N"][0])      # south above north
        self.assertLess(pos["W"][1], pos["E"][1])      # west left of east

    def test_it_is_a_rotation_and_not_a_mirror(self):
        # A mirror would put south at the top while leaving east on the
        # left, which reads fine and is wrong -- it swaps the two directions
        # a reader turns to.
        north = self._cardinal_positions(self._inset("Zurich"))
        south = self._cardinal_positions(self._inset("Wellington"))
        for a, b in (("N", "S"), ("E", "W")):
            self.assertEqual(north[a], south[b], f"{a}/{b} are not opposite")


class SidePanelLayout(unittest.TestCase):
    """?panel=1 (Request.panel) moves the zenith inset beside the horizon
    chart; prose text still renders in its own full-width block below,
    same as the non-panel layout -- only the inset rides beside the chart,
    since it's the one piece narrow enough to fit without squeezing prose
    into a cramped column. Only ever set by the browser's auto-fit JS, so a
    plain Request (CLI included) defaults to False and renders exactly as
    it always has (see test_server.py's CLI-parity check for the
    byte-identical guarantee at the HTTP layer)."""

    def _request(self, **kw):
        return api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0), **kw)

    def test_default_is_off(self):
        r = api.Request(place="Zurich")
        self.assertFalse(r.panel)

    def test_panel_marks_the_three_pieces_for_the_browser_to_place(self):
        # panel used to mean "put the inset beside the chart", which cost the
        # chart the inset's width at every size. It now means "hand the
        # pieces over separately": the browser floats the inset over the
        # chart's corner, so the panorama keeps the whole width.
        text = api.compose(self._request(panel=True)).text
        chart, zenith, prose = api.split_chart_parts(text)
        self.assertIn("zenith 70-90", zenith)
        self.assertNotIn("zenith 70-90", chart)
        self.assertIn("Share as a PNG", prose)
        self.assertNotIn("Share as a PNG", chart)

    def test_the_chart_is_no_narrower_for_having_an_inset(self):
        # The point of the whole arrangement.
        paneled, _z, _p = api.split_chart_parts(
            api.compose(self._request(panel=True)).text)
        stacked = api.strip_ansi(api.compose(self._request(panel=False)).text)
        chart_line = lambda t: max(len(l) for l in api.strip_ansi(t).split("\n"))
        self.assertGreaterEqual(chart_line(paneled), chart_line(stacked) - 2)

    def test_a_reader_never_sees_the_seams(self):
        text = api.compose(self._request(panel=True)).text
        self.assertNotIn("\x00", api.strip_slots(text))
        # and stripping leaves the pieces in the order they were composed
        plain = api.strip_ansi(api.strip_slots(text))
        self.assertLess(plain.index("zenith 70-90"), plain.index("Share as a PNG"))

    def test_without_panel_the_zenith_label_is_alone_on_its_line(self):
        text = api.strip_ansi(api.compose(self._request(panel=False)).text)
        zenith_line = next(l for l in text.split("\n") if "zenith 70-90" in l)
        before = zenith_line.split("zenith 70-90")[0]
        self.assertEqual(before.strip(), "")

    def test_facing_view_has_no_zenith_inset_but_panel_still_works(self):
        # facing= never draws a zenith inset (its own aspect-locked window
        # already replaces it) -- panel=True must degrade gracefully, not
        # crash looking for something that was never there.
        res = api.compose(self._request(panel=True, facing="NW"))
        self.assertNotIn("zenith", api.strip_ansi(res.text))

    def test_panel_prose_renders_full_width_below_the_chart_not_beside_it(self):
        text = api.strip_ansi(api.compose(self._request(panel=True)).text)
        share_line = next(l for l in text.split("\n") if "Share as a PNG" in l)
        before = share_line.split("Share as a PNG")[0]
        self.assertEqual(before.strip(), "")

    def test_panel_prose_wraps_wider_than_the_non_panel_default(self):
        # Full-width now that it's below the chart rather than squeezed
        # beside the zenith inset -- should wrap at the chart's own width,
        # not the old fixed 76-column default.
        r_panel = self._request(panel=True)
        r_stacked = self._request(panel=False)
        prose_panel = api.compose(r_panel).data["prose"]
        prose_stacked = api.compose(r_stacked).data["prose"]
        self.assertGreater(api._effective_width(r_panel), 76)
        self.assertLessEqual(
            max(len(l) for l in prose_panel.split("\n")),
            api._effective_width(r_panel),
        )
        self.assertTrue(prose_stacked)  # sanity: default path still renders

    def test_the_browser_find_view_is_one_line_above_and_one_below(self):
        # The four guide sentences became a single row, and the fist
        # instruction went with them: "a closed fist at arm's length is
        # about 10°" is worth reading once, and it was printed on every
        # find chart forever.
        r = api.Request(place="Zurich", find="Venus",
                        when=dt.datetime(2026, 7, 30, 21, 10), panel=True)
        chart, _zen, prose = api.split_chart_parts(api.compose(r).text)
        self.assertNotIn("closed fist", prose)
        # The footer ("Follow @skymapsh") rides in this block too and is
        # stripped for the browser by strip_duplicate_ui_lines, so what
        # matters here is that the guide itself is a single row.
        body = [l for l in api.strip_ansi(prose).split("\n")
                if l.strip() and "@skymapsh" not in l]
        self.assertEqual(len(body), 1, body)
        self.assertIn("Venus · ", body[0])
        head = [l for l in api.strip_ansi(chart).split("\n") if l.strip()][0]
        self.assertIn("finding Venus", head)
        self.assertNotIn("full panorama", head)

    def test_every_shortened_reason_still_exists_in_sky(self):
        # The short forms are keyed on visibility()'s exact sentences. If one
        # is reworded there, the lookup misses and the long version quietly
        # comes back to a line with no room for it.
        src = open(os.path.join(os.path.dirname(os.path.abspath(api.__file__)),
                                "sky.py")).read()
        for long_form in api.SHORT_WHY:
            self.assertIn(long_form, src, long_form)

    def test_the_cli_find_view_keeps_its_sentences(self):
        # Same request without panel: the terminal reads prose, and its
        # layout is a separate review.
        r = api.Request(place="Zurich", find="Venus",
                        when=dt.datetime(2026, 7, 30, 21, 10))
        text = api.strip_ansi(api.compose(r).text)
        # Wrapped at 76 for a terminal, so the sentence spans two lines --
        # assert the halves rather than the whole.
        self.assertIn("Face WSW and look about one fist up", text)
        self.assertIn("closed fist at arm's length is about", text)
        self.assertIn("Magnitude -4.2.", text)


class StripFooterLine(unittest.TestCase):
    """strip_footer_line removes _footer's "Follow @skymapsh..." line from
    an already-composed render -- used only by server.py's HTML branch, so
    curl/CLI output (which never calls it) keeps the invitation inline."""

    def test_removes_the_footer_line_and_collapses_the_blank_gap(self):
        # Exact marker text, including _footer's leading two-space indent --
        # api.strip_footer_line matches on the plain (uncoloured) form. The
        # blank line *before* the footer survives (it was there anyway);
        # only the footer line and the blank *after* it are removed.
        text = "\n".join(["header", "", "  Follow @skymapsh for skymap.sh updates", ""])
        self.assertEqual(api.strip_footer_line(text), "header\n")

    def test_matches_after_the_prose_indent_has_been_stripped(self):
        # The object page takes the chart's two-space margin off its prose
        # (strip_prose_indent) before this runs, so matching the marker with
        # its indent attached silently missed and the footer came back at
        # the foot of every object page.
        text = "\n".join(["header", "", "Follow @skymapsh for skymap.sh updates", ""])
        self.assertEqual(api.strip_footer_line(text), "header\n")

    def test_the_two_run_in_either_order(self):
        raw = "\n".join(["  A sentence.", "",
                         "  Follow @skymapsh for skymap.sh updates", ""])
        first = api.strip_prose_indent(api.strip_footer_line(raw))
        second = api.strip_footer_line(api.strip_prose_indent(raw))
        self.assertEqual(first, second)
        self.assertNotIn("Follow", first)

    def test_leaves_everything_else_untouched(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0))
        original = api.compose(r).text.split("\n")
        stripped = api.strip_footer_line(api.compose(r).text).split("\n")
        self.assertNotIn("Follow", api.strip_ansi(stripped[-1]))
        # _footer is always the second-to-last element (compose() appends
        # ["", _footer(...), ""]) -- stripping it and the trailing blank
        # after it should leave everything before, including the blank
        # line that was *before* it, untouched.
        self.assertEqual(stripped, original[:-2])


class StripDuplicateUiLines(unittest.TestCase):
    """strip_duplicate_ui_lines removes prose that now duplicates real UI
    (the coming-up card, the drawer's PNG button) -- used only by server.py's
    HTML branch, so curl/JSON/PNG output keeps every line."""

    WHEN = dt.datetime(2026, 8, 11, 23, 0)   # two nights before the Perseid peak

    def _req(self, **kw):
        kw.setdefault("when", self.WHEN)
        return api.Request(place="Zurich", color=False, **kw)

    def test_removes_coming_up_even_when_it_wrapped_to_two_lines(self):
        r = self._req()
        res = api.compose(r)
        self.assertIn("Coming up:", res.text)   # sanity: the teaser is there
        stripped = api.strip_duplicate_ui_lines(res.text, r, res, "http://x")
        self.assertNotIn("Coming up:", stripped)
        self.assertNotIn("Perseids", stripped)

    def test_removes_the_png_share_line_with_base_url_substituted(self):
        r = self._req()
        res = api.compose(r)
        page_text = res.text.replace("{base_url}", "http://x")
        stripped = api.strip_duplicate_ui_lines(page_text, r, res, "http://x")
        self.assertNotIn("Share as a PNG", stripped)

    def test_wrong_base_url_fails_to_match_and_leaves_the_line(self):
        # Guards the bug this function had while being built: _png_url(r)
        # on its own still has the bare {base_url} placeholder, which
        # would never match an already-substituted line -- the base_url
        # passed in here MUST be the same one already baked into text.
        r = self._req()
        res = api.compose(r)
        page_text = res.text.replace("{base_url}", "http://real-host")
        stripped = api.strip_duplicate_ui_lines(page_text, r, res, "http://wrong-host")
        self.assertIn("Share as a PNG", stripped)

    def test_removes_see_tonight_on_the_daytime_view_only(self):
        r = self._req(when=dt.datetime(2026, 8, 11, 13, 0))
        res = api.compose(r)
        self.assertIn("See tonight's chart now", res.text)
        stripped = api.strip_duplicate_ui_lines(res.text, r, res, "http://x")
        self.assertNotIn("See tonight's chart now", stripped)

    def test_quiet_night_has_nothing_to_strip_for_coming_up_but_still_strips_png(self):
        # No event due -- res.data["coming_up"] is None, so that half is a
        # no-op -- but every view still has its own PNG share line, which
        # should still come out regardless of whether there's an event.
        r = self._req(when=dt.datetime(2026, 6, 1, 23, 0))
        res = api.compose(r)
        self.assertNotIn("Coming up:", res.text)
        page_text = res.text.replace("{base_url}", "http://x")
        stripped = api.strip_duplicate_ui_lines(page_text, r, res, "http://x")
        self.assertNotIn("Share as a PNG", stripped)

    def test_no_op_on_find_view_which_has_neither_line(self):
        r = self._req(find="Venus")
        res = api.compose(r)
        page_text = res.text.replace("{base_url}", "http://x")
        stripped = api.strip_duplicate_ui_lines(page_text, r, res, "http://x")
        self.assertEqual(stripped, page_text)


class KeyboardShortcutToggleUrls(unittest.TestCase):
    """The d/l/q keyboard shortcuts and the quadrant button all navigate to
    one of these -- each should flip exactly the one thing it's for and
    leave the rest of the current view (facing/span/w/t) alone. In
    particular: an explicitly-picked time must survive the toggle, or you'd
    land back on "now" -- e.g. toggling from a deliberately-picked nighttime
    moment could bounce you to the daytime Sun's-arc view if "now" happens
    to be daytime when you click."""

    # A concrete, explicit moment (not "now") -- exercises exactly the
    # t=-carries-over behaviour above, on every toggle in this class.
    WHEN = dt.datetime(2026, 7, 30, 22, 0)
    T = "t=2026-07-30T22:00"

    def _request(self, **kw):
        # Actually nighttime at Zurich, but no ?night=1 override -- so the
        # toggle URLs under test come out clean (no incidental night=1)
        # unless a test explicitly asks for the override too.
        return api.Request(place="Zurich", when=self.WHEN, **kw)

    def test_quadrant_toggle_turns_it_on(self):
        r = self._request()
        self.assertEqual(api._quadrant_toggle_url(r), f"/Zurich?{self.T}&quadrant")

    def test_quadrant_toggle_turns_it_off_and_drops_the_dso_it_implied(self):
        r = self._request(quadrant="A")
        self.assertEqual(api._quadrant_toggle_url(r), f"/Zurich?{self.T}")

    def test_quadrant_toggle_preserves_facing_span_and_width(self):
        r = self._request(facing="NW", span=90, width=100)
        url = api._quadrant_toggle_url(r)
        self.assertIn("facing=NW", url)
        self.assertIn("span=90", url)
        self.assertIn("w=100", url)
        self.assertIn("quadrant", url)

    def test_quadrant_toggle_preserves_an_explicitly_picked_time(self):
        # The regression this whole class exists to catch: dropping t= would
        # silently bounce a nighttime view back to "now", which could be
        # daytime -- see the class docstring.
        r = self._request()
        self.assertIn(self.T, api._quadrant_toggle_url(r))

    def test_quadrant_toggle_preserves_panel(self):
        # Regression: dropping panel= here silently moved the zenith inset
        # from beside the chart to below it the moment the 'd' shortcut
        # fired on an auto-fit-widened page.
        r = self._request(width=170, panel=True)
        self.assertIn("panel=1", api._quadrant_toggle_url(r))

    def test_grid_url_preserves_panel(self):
        r = self._request(width=170, panel=True)
        self.assertIn("panel=1", api._quadrant_grid_url(r))

    def test_dso_toggle_preserves_panel(self):
        r = self._request(width=170, panel=True)
        self.assertIn("panel=1", api._dso_toggle_url(r))

    def test_grid_url_lands_on_the_bare_grid_from_off(self):
        r = self._request()
        self.assertEqual(api._quadrant_grid_url(r), f"/Zurich?{self.T}&quadrant")

    def test_grid_url_drops_the_letter_when_already_zoomed_into_one_cell(self):
        # Unlike _quadrant_toggle_url (which would turn everything off from
        # here), _quadrant_grid_url always lands on the bare lettered grid --
        # the 'z' shortcut's job is to get you back to a pickable state, not
        # to toggle anything off.
        r = self._request(quadrant="A")
        self.assertEqual(api._quadrant_grid_url(r), f"/Zurich?{self.T}&quadrant")

    def test_grid_url_is_idempotent_from_the_bare_grid_itself(self):
        r = self._request(quadrant="")
        self.assertEqual(api._quadrant_grid_url(r), f"/Zurich?{self.T}&quadrant")

    def test_dso_toggle_turns_it_on(self):
        r = self._request()
        self.assertEqual(api._dso_toggle_url(r), f"/Zurich?{self.T}&dso=1")

    def test_dso_toggle_turns_it_off(self):
        r = self._request(dso=True)
        self.assertEqual(api._dso_toggle_url(r), f"/Zurich?{self.T}")

    def test_dso_toggle_stays_independent_of_an_active_quadrant_grid(self):
        # Quadrant force-implies dso -- turning it off here has to write an
        # explicit ?nodso=1 override, or the implied-True default would win
        # and the toggle would silently no-op.
        r = self._request(quadrant="A")
        self.assertTrue(r.dso)
        self.assertEqual(api._dso_toggle_url(r), f"/Zurich?{self.T}&quadrant&nodso=1")

    def test_dso_toggle_drops_the_nodso_override_to_turn_back_on(self):
        r = self._request(quadrant="A", nodso=True)
        self.assertFalse(r.dso)
        self.assertEqual(api._dso_toggle_url(r), f"/Zurich?{self.T}&quadrant")

    def test_dso_toggle_preserves_an_explicitly_picked_time(self):
        r = self._request()
        self.assertIn(self.T, api._dso_toggle_url(r))

    def test_quadrant_toggle_never_writes_nodso(self):
        # Toggling the grid itself always resets to the normal implied-dso
        # default -- only the 'd' shortcut opts out of it.
        r = self._request()
        self.assertNotIn("nodso", api._quadrant_toggle_url(r))

class ControlsPanel(unittest.TestCase):
    """controls_html renders the explore form + toolbar directly, no panel
    wrapper and no toggle -- always visible on every page, chart included."""

    def test_controls_has_no_panel_wrapper_or_toggle(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "EXTRA_MARKER")
        self.assertNotIn("controls-panel", html)
        self.assertNotIn("controls-toggle", html)
        self.assertIn("EXPLORE_MARKER", html)
        self.assertIn("ANIMATE_MARKER", html)
        self.assertIn("QUADRANT_MARKER", html)
        self.assertIn("EXTRA_MARKER", html)

    def test_examples_comes_after_every_button_in_dom_order(self):
        # class="tries" is forced onto its own full-width line via CSS
        # (flex-basis:100%), which only puts it *below* the buttons if it's
        # last in DOM order -- earlier would push the buttons down instead.
        # DRAWER_LINKS_HTML (catalog/demo/legend) also carries class="tries"
        # and sits at the very top, so this looks for "Examples:" -- the
        # text unique to the Examples section -- not the bare class.
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "EXTRA_MARKER")
        tries_pos = html.index("Examples:")
        self.assertGreater(tries_pos, html.index("ANIMATE_MARKER"))
        self.assertGreater(tries_pos, html.index("QUADRANT_MARKER"))
        self.assertGreater(tries_pos, html.index("EXTRA_MARKER"))

    def test_header_has_no_toggle(self):
        html = api.header_html("Zurich")
        self.assertIn('class="t nav-row"', html)
        self.assertNotIn("controls-toggle", html)


class CommandBar(unittest.TestCase):
    """header_html renders the "$ curl skymap.sh/<value>" command bar --
    everything up to and including the "/" is fixed decorative text, #q is
    the one real, editable input. Replaces both the old static cta chip and
    EXPLORE's separate #place field (SPEC-command-bar.md)."""

    def test_value_prefills_the_input(self):
        html = api.header_html("Geneva")
        self.assertIn('id="q"', html)
        self.assertIn('value="Geneva"', html)

    def test_value_is_html_escaped(self):
        html = api.header_html('<script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_default_value_is_empty(self):
        html = api.header_html()
        self.assertIn('value=""', html)

    def test_fixed_prefix_reads_as_a_curl_command(self):
        html = api.header_html("Geneva")
        self.assertIn('<span class="curlword">curl </span>skymap.sh/', html)

    def test_form_has_a_real_action_for_the_no_js_fallback(self):
        html = api.header_html("Geneva")
        self.assertIn('<form class="cmdbar" id="bar" method="get" action="/">', html)

    def test_decorative_chrome_is_aria_hidden(self):
        html = api.header_html("Geneva")
        self.assertIn('<span class="prompt" aria-hidden="true">', html)
        self.assertIn('<span class="fixed" aria-hidden="true">', html)
        self.assertIn('<span class="cursor" id="cur" aria-hidden="true">', html)

    def test_the_input_itself_has_a_real_label(self):
        # The screen-reader experience should be one labelled text input --
        # everything else in the bar is aria-hidden (see above). The label
        # names all three kinds now that the separate find field is gone;
        # "City, or lat,lon" described half of what the box accepts.
        html = api.header_html("Geneva")
        self.assertIn('aria-label="A place, an object, or a page"', html)

    def test_the_input_announces_its_dropdown(self):
        html = api.header_html("Geneva")
        self.assertIn('role="combobox"', html)
        self.assertIn('aria-controls="bar-dropdown"', html)

    def test_ios_autocorrect_and_autocapitalize_are_off(self):
        # Mandatory per the spec -- iOS otherwise rewrites a meaningful
        # fraction of real city names.
        html = api.header_html("Geneva")
        self.assertIn('autocapitalize="off"', html)
        self.assertIn('autocorrect="off"', html)

    def test_no_leftover_place_input_anywhere(self):
        html = api.header_html("Geneva") + api.EXPLORE
        self.assertNotIn('id="place"', html)

    def test_drawer_trigger_sits_after_the_social_icons(self):
        html = api.header_html("Geneva")
        self.assertGreater(html.index('id="drawer-trigger"'), html.index("social-icons"))

    def test_drawer_trigger_starts_closed(self):
        html = api.header_html("Geneva")
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-controls="drawer"', html)


class Drawer(unittest.TestCase):
    """controls_html renders the drawer (SPEC-command-bar.md #9, adapted:
    right-side slide-in, no backdrop) -- find/date/time/go, the toolbar,
    and Examples, grouped into block-stacked sections. No-JS fallback is
    load-bearing (see the function's own docstring): the server-rendered
    HTML carries no hidden/inline-style state of its own, so every control
    stays reachable without PAGE's script ever running."""

    def test_wraps_content_in_the_drawer_container(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        self.assertIn('<div id="drawer">', html)
        self.assertIn("EXPLORE_MARKER", html)
        self.assertIn("ANIMATE_MARKER", html)
        self.assertIn("QUADRANT_MARKER", html)
        self.assertIn("SPHERE_MARKER", html)
        self.assertIn("EXTRA_MARKER", html)

    def test_grouped_into_four_block_sections(self):
        # links (catalog/demo/legend), explore, actions, examples.
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        self.assertEqual(html.count('class="drawer-section"'), 4)

    def test_links_section_is_first(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        links_pos = html.index('href="/catalog"')
        self.assertLess(links_pos, html.index("EXPLORE_MARKER"))

    def test_examples_is_the_last_section(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        tries_pos = html.index("Examples:")
        self.assertGreater(tries_pos, html.index("ANIMATE_MARKER"))
        self.assertGreater(tries_pos, html.index("EXTRA_MARKER"))

    def test_no_hidden_state_baked_into_the_server_render(self):
        # The whole no-JS fallback depends on this -- if the server ever
        # rendered #drawer pre-hidden (an inline style, a "closed" class),
        # everything inside it would be unreachable without JS.
        html = api.controls_html("EXPLORE_MARKER")
        self.assertNotIn("hidden", html)
        self.assertNotIn("style=", html)

    def test_sphere_btn_comes_before_extra_in_the_actions_section(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        self.assertLess(html.index("SPHERE_MARKER"), html.index("EXTRA_MARKER"))

    def test_close_button_is_the_first_thing_in_the_drawer(self):
        html = api.controls_html("EXPLORE_MARKER")
        self.assertLess(html.index('id="drawer-close"'), html.index("EXPLORE_MARKER"))

    def test_reset_link_present_even_with_no_chart_specific_buttons(self):
        # "start over" has to work from /catalog, /help etc too, where
        # animate_btn/quadrant_btn/sphere_btn/extra are all "".
        html = api.controls_html("EXPLORE_MARKER")
        self.assertIn('<a class="animate-btn" href="/">↺ reset skymap</a>', html)

    def test_reset_link_comes_after_the_page_specific_actions(self):
        html = api.controls_html("EXPLORE_MARKER", "ANIMATE_MARKER",
                                  "QUADRANT_MARKER", "SPHERE_MARKER", "EXTRA_MARKER")
        self.assertGreater(html.index("reset skymap"), html.index("EXTRA_MARKER"))


class FindOnThePngExport(unittest.TestCase):
    """?find= used to be silently dropped by the PNG export: _png_url()
    never put it in the link, and compose_chart_only() never looked at
    r.find even when it was there -- so "Share as a PNG" on a find page
    quietly handed back the plain full-sweep chart instead of the crosshair
    the page itself was showing."""

    def test_png_url_carries_find_url_encoded(self):
        r = api.Request(place="Zurich", find="Andromeda Galaxy")
        url = api._png_url(r)
        self.assertIn("find=Andromeda%20Galaxy", url)

    def test_png_url_omits_find_when_not_asked_for(self):
        r = api.Request(place="Zurich")
        self.assertNotIn("find=", api._png_url(r))

    def test_chart_only_draws_the_same_target_the_page_does(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0), find="M31")
        page = api.compose(r)
        png_art = api.compose_chart_only(r)
        self.assertIn("ANDROMEDA GALAXY", page.text.upper())
        self.assertIn("ANDROMEDA GALAXY", png_art.upper())

    def test_the_png_is_the_horizon_view_and_nothing_under_it(self):
        # Every other branch of compose_chart_only passes inset=False; this
        # one relied on render_linear's default, which is on. A shared find
        # PNG came out with a zenith inset stacked under the horizon that no
        # other PNG has.
        when = dt.datetime(2026, 7, 30, 22, 0)
        for find in ("M31", "Vega", "Jupiter"):
            art = api.compose_chart_only(api.Request(place="Zurich", when=when,
                                                     find=find, color=False))
            self.assertNotIn("zenith", art, find)
        # and the plain export it is meant to match still has none either
        plain = api.compose_chart_only(api.Request(place="Zurich", when=when,
                                                   color=False))
        self.assertNotIn("zenith", plain)
        # while the page both of them come from keeps its inset
        page = api.compose(api.Request(place="Zurich", when=when, find="M31",
                                       color=False))
        self.assertIn("zenith", page.text)

    def test_chart_only_falls_back_to_the_plain_chart_for_an_unknown_target(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 22, 0), find="Not A Real Thing")
        # Should not raise, and should still produce a real chart rather
        # than nothing -- an unresolvable ?find= degrades gracefully.
        art = api.compose_chart_only(r)
        self.assertTrue(art)


class PngUrlCarriesEveryRenderingParameter(unittest.TestCase):
    """find= wasn't the only one missing -- t=, view=disc and nolines= all
    changed what /horizon.png actually rendered without ever reaching the
    "Share as a PNG" link either. Same bug, three more instances of it."""

    def test_explicit_time_travels_with_the_link(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 12, 18, 0))
        self.assertIn("t=2026-08-12T18:00", api._png_url(r))

    def test_default_now_does_not_freeze_the_link_to_a_timestamp(self):
        # No explicit ?t= means "whatever's current" -- the link must stay
        # bare so it keeps tracking the real time on every fetch, not get
        # pinned to the moment it happened to be generated.
        r = api.Request(place="Zurich")
        self.assertNotIn("t=", api._png_url(r))

    def test_disc_view_travels_with_the_link(self):
        r = api.Request(place="Zurich", view="disc")
        self.assertIn("view=disc", api._png_url(r))

    def test_nolines_travels_with_the_link(self):
        r = api.Request(place="Zurich", lines=False)
        self.assertIn("nolines=1", api._png_url(r))

    def test_default_view_and_lines_add_nothing_to_the_link(self):
        r = api.Request(place="Zurich")
        url = api._png_url(r)
        self.assertNotIn("view=", url)
        self.assertNotIn("nolines", url)


class NightOverrideDuringDaylight(unittest.TestCase):
    """?night=1 forces the star chart even while the Sun is up. The Moon
    used to be silently dropped from render_linear's bodies set whenever it
    wasn't bright enough to matter -- fine for what gets drawn, but
    sky_read() reads moon["alt"] unconditionally, so this crashed with a
    KeyError every time someone used --night in broad daylight."""

    def test_does_not_crash_and_reports_moon_altitude(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 13, 0), night=True)
        res = api.compose(r)
        self.assertEqual(res.status, 200)
        self.assertIn("alt", res.data["moon"])

    def test_chart_only_path_does_not_crash_either(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 7, 30, 13, 0), night=True)
        api.compose_chart_only(r)   # raises on failure; nothing to assert


class FullDarkMeansAstronomicalDark(unittest.TestCase):
    """"Fully dark" is astronomical dusk, the Sun at -18 deg, and nothing
    else. The day view used to fall back to nautical dusk when astronomical
    never happened, which printed a real-looking time for a darkness that
    never arrives -- London on the solstice claimed "fully dark 23:23" on a
    night that never gets there. Everywhere between ~48.5 deg and the Arctic
    circle has months of those nights, so this was wrong for a good part of
    Europe and Canada for a good part of the year."""

    # 21 June at 51.5N: the Sun bottoms out around -15 deg, so there is a
    # nautical dusk but no astronomical one.
    SOLSTICE = dt.datetime(2026, 6, 21, 12, 0)
    # Geneva in August still gets a real astronomical dusk, which is what
    # keeps these tests honest -- they would also pass if the feature simply
    # never reported full darkness anywhere.
    ORDINARY = dt.datetime(2026, 8, 4, 12, 0)

    def test_solstice_night_does_not_claim_a_full_dark_time(self):
        res = api.compose(api.Request(place="London", when=self.SOLSTICE, color=False))
        self.assertIn("never gets fully dark", res.data["prose"])
        self.assertNotIn("fully dark 2", res.data["prose"])

    def test_solstice_night_still_reports_first_stars(self):
        # The sky does get dark enough for the brightest things, and that
        # time is genuinely useful -- suppressing the whole line would trade
        # one wrong answer for no answer.
        res = api.compose(api.Request(place="London", when=self.SOLSTICE, color=False))
        self.assertIsNotNone(res.data["first_stars"])
        self.assertIn("first stars about", res.data["prose"])

    def test_solstice_night_reports_no_dark_from_and_says_why(self):
        res = api.compose(api.Request(place="London", when=self.SOLSTICE, color=False))
        self.assertIsNone(res.data["dark_from"])
        self.assertTrue(res.data["never_fully_dark"])
        # Not polar day: the Sun does still set, it just never gets far down.
        self.assertFalse(res.data["polar_day"])

    def test_an_ordinary_night_still_gets_a_full_dark_time(self):
        res = api.compose(api.Request(place="Geneva", when=self.ORDINARY, color=False))
        self.assertIsNotNone(res.data["dark_from"])
        self.assertFalse(res.data["never_fully_dark"])
        self.assertIn("fully dark", res.data["prose"])

    def test_dark_from_matches_astronomical_and_not_nautical_dusk(self):
        r = api.Request(place="Geneva", when=self.ORDINARY, color=False)
        res = api.compose(r)
        off = r.place.offset(r.when_utc)
        day0 = r.when_local.replace(hour=0, minute=0, second=0, microsecond=0) \
            - dt.timedelta(hours=off)
        ev = sky.sun_events(day0, r.place.lat, r.place.lon)
        want = (ev["dusk_astro"] + dt.timedelta(hours=off)).isoformat()
        self.assertEqual(res.data["dark_from"], want)
        self.assertNotEqual(ev["dusk_astro"], ev["dusk_nautical"])

    def test_panel_head_says_no_full_dark_rather_than_a_blank_time(self):
        # The compact one-row head has its own copy of this sentence, and a
        # missing time renders there as "--", which reads as a bug.
        r = api.Request(place="London", when=self.SOLSTICE, color=False, panel=True)
        text = api.compose(r).text
        self.assertIn("no full dark", text)
        self.assertNotIn("dark --", text)

    def test_sphere_countdown_is_null_when_full_dark_never_comes(self):
        # The 3D page already had the right words for null; it just never
        # reached them, because the countdown fell back to nautical too.
        d = api._compose_sphere(api.Request(place="London", when=self.SOLSTICE))
        self.assertIsNone(d["hours_to_dark"])

    def test_sphere_countdown_still_counts_down_on_an_ordinary_day(self):
        d = api._compose_sphere(api.Request(place="Geneva", when=self.ORDINARY))
        self.assertIsNotNone(d["hours_to_dark"])
        self.assertGreater(d["hours_to_dark"], 0)


class LightPollutionDecidesTheMilkyWay(unittest.TestCase):
    """Walker's Law over cities.json, which the spec chose because it needs
    no new data, no licence and no runtime dependency. The estimate is crude
    and labelled as such; what it has to get right is the decision it drives
    -- whether to draw a band someone could not actually see."""

    def test_cities_are_bright_and_remote_places_are_dark(self):
        for name, lat, lon, worst, best in (
                ("central London", 51.507, -0.128, 8, 9),
                ("Geneva", 46.20, 6.15, 8, 9),
                ("Tokyo", 35.69, 139.69, 8, 9),
                ("Atacama", -24.63, -70.40, 1, 2),
                ("Mauna Kea", 19.82, -155.47, 1, 2)):
            b = api.sky_brightness(lat, lon)[1]
            self.assertTrue(worst <= b <= best, f"{name} came out Bortle {b}")

    def test_a_city_centre_does_not_return_a_runaway_number(self):
        # Walker's Law is r^-2.5 and diverges as you approach a city. Without
        # the population-radius floor, central Geneva came out at 14.1
        # mag/arcsec2 against a real 17.5-18 -- and standing in a city is the
        # commonest request there is.
        for lat, lon in ((51.507, -0.128), (46.20, 6.15), (35.69, 139.69)):
            mag = api.sky_brightness(lat, lon)[0]
            self.assertGreater(mag, 15.5)

    def test_driving_out_of_town_darkens_the_sky(self):
        city = api.sky_brightness(46.20, 6.15)[0]
        jura = api.sky_brightness(46.42, 5.90)[0]
        self.assertGreater(jura, city + 2.0)

    def test_no_milky_way_from_a_city_and_all_of_it_from_a_dark_site(self):
        self.assertEqual(api.milkyway_floor(46.20, 6.15), 0)     # Geneva
        self.assertEqual(api.milkyway_floor(-24.63, -70.40), 1)  # Atacama

    def test_twilight_suppresses_it_even_at_a_dark_site(self):
        dark = (-24.63, -70.40)
        self.assertEqual(api._milkyway_floor_now(*dark, sun_alt=-5), 0)
        self.assertEqual(api._milkyway_floor_now(*dark, sun_alt=-10), 0)
        self.assertGreater(api._milkyway_floor_now(*dark, sun_alt=-14), 1)
        self.assertEqual(api._milkyway_floor_now(*dark, sun_alt=-30), 1)

    def test_a_city_stays_dark_at_every_sun_altitude(self):
        for alt in (-5, -14, -20, -40):
            self.assertEqual(api._milkyway_floor_now(46.20, 6.15, alt), 0)

    def test_the_note_is_short_and_says_it_is_an_estimate(self):
        note = api.sky_note(-24.63, -70.40)
        self.assertIn("Bortle", note)
        self.assertIn("est.", note)
        self.assertLess(len(note), 30)

    def test_the_note_names_the_town_when_that_is_why_there_is_no_band(self):
        self.assertIn("Geneva", api.sky_note(46.20, 6.15))
        self.assertNotIn("(", api.sky_note(-24.63, -70.40))

    def test_the_estimate_is_memoised(self):
        import time
        api.sky_brightness(48.85, 2.35)
        t = time.time()
        api.sky_brightness(48.85, 2.35)
        self.assertLess(time.time() - t, 0.002)


class GoldenHourOnTheDayView(unittest.TestCase):
    """The day view's golden-hour line and its JSON. Times are the cheap
    half: every sunrise calculator has them. The bearings and the shadow are
    what this is for, so most of these are about those."""

    NOON = dt.datetime(2026, 8, 4, 12, 0)

    def data(self, place="Geneva", when=None):
        return api.compose(api.Request(place=place, when=when or self.NOON,
                                       color=False)).data

    def chart(self, place="Geneva", when=None, width=120):
        """The rendered chart. The golden-hour facts live on it rather than
        in a paragraph underneath, since a daylight chart is mostly empty
        sky and the numbers read better beside the band they describe."""
        return api.compose(api.Request(place=place, when=when or self.NOON,
                                       color=False, width=width)).text

    def layer(self, place="Geneva", when=None, width=120):
        """(alt_bands, notes) for one chart -- what the golden layer actually
        asked the renderer to draw, for assertions that would otherwise be
        confounded by the prose printed underneath it."""
        r = api.Request(place=place, when=when or self.NOON, color=False,
                        width=width)
        p, off = r.place, r.place.offset(r.when_utc)
        day0 = r.when_local.replace(hour=0, minute=0, second=0,
                                    microsecond=0) - dt.timedelta(hours=off)
        ev = sky.sun_events(day0, p.lat, p.lon)
        bands = sky.sun_bands(day0, p.lat, p.lon, ev)
        sa, sz = sky.sun_altaz(r.when_utc, p.lat, p.lon)
        return api._golden_layer(r, bands, ev, off, sa, sz, 70.0, width)

    def test_the_chart_names_both_windows(self):
        self.assertIn("golden 05:59-07:03 · 20:18-21:22", self.chart())

    def test_the_line_is_marked_while_the_golden_hour_is_actually_running(self):
        # 20:30 puts the Sun at 4 degrees, inside the band. The line stops
        # being a schedule and becomes an instruction, so it gets arrows.
        chart = self.chart(when=dt.datetime(2026, 8, 4, 20, 30))
        self.assertIn(">> golden 05:59-07:03 · 20:18-21:22 <<", chart)

    def test_the_line_is_unmarked_when_the_golden_hour_is_hours_away(self):
        self.assertNotIn(">>", self.chart(when=dt.datetime(2026, 8, 4, 12, 0)))

    def test_the_marked_line_still_fits_the_narrowest_rung(self):
        # Four characters wider than the plain form, on the chart that has
        # the least room for them.
        chart = self.chart(when=dt.datetime(2026, 8, 4, 20, 30), width=80)
        self.assertIn(">> golden", chart)
        self.assertIn("<<", chart)

    def test_the_blue_hour_line_never_gets_arrows(self):
        # Blue hour is below the horizon, so the day view is never on screen
        # during it -- arrows there would be a promise the chart cannot keep.
        chart = self.chart(when=dt.datetime(2026, 8, 4, 20, 30))
        self.assertIn(" blue 05:46-05:59 · 21:22-21:35 ", chart)

    def test_the_chart_names_the_blue_hour_windows(self):
        # Blue hour runs from -6 to -4, entirely below the horizon, so it
        # never gets a band -- it has to appear as text or not at all.
        self.assertIn("blue 05:46-05:59 · 21:22-21:35", self.chart())

    def test_the_chart_gives_rise_and_set_bearings(self):
        chart = self.chart()
        self.assertIn("sunrise 06:20  64° ENE", chart)
        self.assertIn("sunset 21:01  296° WNW", chart)

    def test_the_chart_gives_shadow_length_and_direction(self):
        self.assertIn("shadows 0.7x toward", self.chart())

    def test_the_band_is_drawn_as_a_stripe(self):
        # A run of colons long enough that it cannot be anything else.
        self.assertIn(":" * 40, self.chart())

    def test_the_narrowest_rung_keeps_the_bearings_and_drops_the_shadow(self):
        # The full line is two columns too wide for an 80-column chart. The
        # bearings are the point, so the shadow is what gives way.
        chart = self.chart(width=80)
        self.assertIn("sunrise 06:20", chart)
        self.assertNotIn("shadows", chart)

    def test_the_json_still_carries_the_convention(self):
        # It is no longer spelled out on the chart -- anyone reading a band
        # of colons knows what golden hour is -- but a client comparing this
        # against another tool still needs to know which convention it is.
        conv = self.data()["golden"]["convention"]
        self.assertEqual((conv["lo_alt"], conv["hi_alt"]), (-4.0, 6.0))

    def test_the_toggle_removes_the_band_the_text_and_the_json(self):
        r = api.Request(place="Geneva", when=self.NOON, color=False,
                        width=120, nogolden=True)
        res = api.compose(r)
        self.assertNotIn(":" * 40, res.text)
        self.assertNotIn("golden 05:59", res.text)
        self.assertNotIn("blue 05:46", res.text)
        self.assertIsNone(res.data["golden"])

    def test_shadow_points_directly_away_from_the_sun(self):
        d = self.data()
        opposed = (d["golden"]["shadow"]["az"] - d["sun"]["az"]) % 360
        self.assertAlmostEqual(opposed, 180, delta=1)

    def test_shadow_is_capped_rather_than_quoted_near_the_horizon(self):
        # cot(h) runs away as the Sun drops; a bare "32.3x" reads as
        # precision that the ground's own slope has already destroyed.
        when = dt.datetime(2026, 8, 4, 20, 45)
        self.assertTrue(self.data(when=when)["golden"]["shadow"]["capped"])
        self.assertIn("shadows >20x", self.chart(when=when))

    def test_json_carries_all_four_bands_with_bearings(self):
        g = self.data()["golden"]
        for k in ("golden_am", "golden_pm", "blue_am", "blue_pm"):
            self.assertIsNotNone(g[k], k)
            self.assertIsInstance(g[k]["az_start"], int, k)
            self.assertIsInstance(g[k]["compass_end"], str, k)

    def test_json_states_the_convention_too(self):
        conv = self.data()["golden"]["convention"]
        self.assertEqual(conv["lo_alt"], -4.0)
        self.assertEqual(conv["hi_alt"], 6.0)

    def test_json_times_are_whole_seconds(self):
        # They come out of a bisection carrying a microsecond tail that reads
        # as precision the Sun's position does not have.
        start = self.data()["golden"]["golden_pm"]["start"]
        self.assertNotIn(".", start)

    def test_arctic_summer_says_golden_light_all_night(self):
        when = dt.datetime(2026, 6, 21, 12, 0)
        d = self.data(place="Tromso", when=when)
        self.assertEqual(d["golden"]["note"], "all_night")
        self.assertTrue(d["golden"]["golden_pm"]["open_end"])
        # One window that never closes, not two that pretend to.
        self.assertIn("golden from 22:35 all night",
                      self.chart(place="Tromso", when=when))

    def test_arctic_summer_reports_no_rise_or_set_bearing(self):
        # The Sun does not set, so there is no set bearing to give. The
        # golden layer drops that clause rather than printing a placeholder.
        # Asserted against the layer's own notes, not the whole chart: the
        # prose underneath has said "sunset --" on a polar day since long
        # before this feature, and that is a separate line.
        when = dt.datetime(2026, 6, 21, 12, 0)
        d = self.data(place="Tromso", when=when)
        self.assertIsNone(d["golden"]["sunset_az"])
        self.assertIsNone(d["golden"]["sunrise_az"])
        _bands, notes = self.layer(place="Tromso", when=when)
        self.assertFalse(any("sunset" in n["text"] for n in notes))
        self.assertTrue(any("shadows" in n["text"] for n in notes))

    def test_the_arc_marks_the_golden_stretch_differently(self):
        # The band is a range of Sun altitudes, so the arc colours itself
        # where it crosses them. Only the part above the horizon can show.
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 4, 19, 30),
                        color=True, width=100)
        self.assertIn("•", api.compose(r).text)

    def test_a_colourless_render_still_works(self):
        # The golden glyph carries an ANSI colour; --no-color must not leak
        # an escape sequence into the text.
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 4, 19, 30),
                        color=False, width=100)
        self.assertNotIn("\033", api.compose(r).text)


class ImageExportsAreWiderThanATerminal(unittest.TestCase):
    """A PNG is a raster, not somebody's window: nothing has to fit, and the
    extra columns are what make it legible at a glance rather than a thin
    strip. The terminal default stays where it is."""

    WHEN = dt.datetime(2026, 8, 5, 3, 0)

    def png_size(self, **kw):
        import io
        from PIL import Image
        import gif
        r = api.Request(place="-24.63,-70.40", when=self.WHEN, color=True, **kw)
        return Image.open(io.BytesIO(gif.frame_to_png(api.compose_chart_only(r)))).size

    def test_the_export_is_wider_than_the_terminal_default(self):
        self.assertEqual(api.PNG_WIDTH, 140)
        self.assertGreater(api.PNG_WIDTH, api.DEFAULT_HORIZON_WIDTH)

    def test_the_terminal_default_is_untouched(self):
        r = api.Request(place="Geneva", when=self.WHEN)
        self.assertEqual(api._effective_width(r), api.DEFAULT_HORIZON_WIDTH)

    def test_height_follows_width_so_the_aspect_holds(self):
        # Widening without this gave a letterbox: 140 columns of chart in
        # the row count of a 110-column one.
        w1, h1 = self.png_size()
        w2, h2 = self.png_size(width=200)
        self.assertAlmostEqual(w1 / h1, w2 / h2, delta=0.08)

    def test_an_explicit_width_still_wins(self):
        self.assertGreater(self.png_size(width=200)[0], self.png_size()[0])


class TheExportMatchesWhatIsOnScreen(unittest.TestCase):
    """A shared PNG should be the picture someone was looking at. Two ways
    it was not: the header said something different from the page's, and a
    paused animation frame exported the moment the run started from."""

    WHEN = dt.datetime(2026, 8, 5, 3, 2)
    PLACE = "-23.90,-69.10"

    def line(self, text, n):
        import gif
        return " ".join(gif.ANSI.sub("", text).split("\n")[n].split())

    def top_line(self, text):
        return self.line(text, 0)

    def test_the_png_header_matches_the_widest_rung_exactly(self):
        # The browser ships nine rungs and each trims the top line to its
        # own width, so a narrow one says less than a wide one. An export
        # has no rung and must carry what the widest view carries -- an
        # earlier version matched a narrow rung and silently dropped the
        # planets, the darkness and the star count.
        png = self.top_line(api.compose_chart_only(
            api.Request(place=self.PLACE, when=self.WHEN, color=False)))
        widest = max(api.CHART_LADDER, key=lambda rung: rung[1])
        page = api.compose(api.Request(place=self.PLACE, when=self.WHEN,
                                       color=False, panel=True,
                                       width=widest[1])).text
        self.assertEqual(png, self.line(page, 1))

    def test_nothing_is_trimmed_off_the_export_header(self):
        # A place with a lot to say: several planets and a star count.
        png = self.top_line(api.compose_chart_only(
            api.Request(place="-14.50,17.50", color=False,
                        when=dt.datetime(2026, 8, 5, 22, 40))))
        self.assertIn("stars", png)
        self.assertIn("Bortle", png)

    def test_the_png_header_carries_the_facts_the_page_shows(self):
        png = self.top_line(api.compose_chart_only(
            api.Request(place=self.PLACE, when=self.WHEN, color=False)))
        for fact in ("Bortle", "full dark", "stars"):
            self.assertIn(fact, png)

    def test_the_redundant_mode_label_is_dropped_like_the_page_does(self):
        # The axis is labelled 0-70 down the left edge; saying "horizon
        # panorama" as well costs the width the summary needs.
        plain = self.top_line(api.compose_chart_only(
            api.Request(place=self.PLACE, when=self.WHEN, color=False)))
        self.assertNotIn("horizon panorama", plain)

    def test_a_facing_window_keeps_its_label(self):
        # That one is not obvious from looking, so it stays.
        facing = self.top_line(api.compose_chart_only(
            api.Request(place=self.PLACE, when=self.WHEN, color=False,
                        facing="SW")))
        self.assertIn("facing SW", facing)

    def test_the_page_wires_the_png_link_to_the_paused_frame(self):
        # The anchor is written once at render time, so without this a
        # frame eleven hours into a run exported the starting moment.
        self.assertIn("skymapAnimSyncPng", api.PAGE)
        self.assertIn("skymapAnimFrameTime(A.at)", api.PAGE)
        self.assertIn("horizon.png", api.PAGE)


class HelpTextIsCurrent(unittest.TestCase):
    """HELP is free text, easy for the UI to drift out from under -- a
    handful of content checks so a future feature/shortcut change is more
    likely to also update the doc, not just leave it stale."""

    def test_mentions_every_wired_up_keyboard_shortcut(self):
        for key in ("tab  ", "f ", "m ", "esc", "a ", "g ", "d ", "z "):
            self.assertIn(key, api.HELP)

    def test_find_mentions_deep_sky_and_radiants(self):
        # resolve_target() accepts both (sky.py) -- the doc used to only
        # list planets/Sun/Moon/stars/asterisms.
        self.assertIn("deep-sky", api.HELP)
        self.assertIn("radiant", api.HELP)

    def test_mentions_events(self):
        self.assertIn("EVENTS", api.HELP)
        self.assertIn("/events", api.HELP)
        self.assertIn(".ics", api.HELP)
        self.assertIn(".rss", api.HELP)

    def test_documented_events_window_matches_the_real_default(self):
        self.assertIn(f"next {api.EVENTS_WINDOW_DAYS} days", api.HELP)


class CatalogText(unittest.TestCase):
    """catalog_text() lists every object findable by name via ?find= -- it
    must actually match what resolve_target() accepts, or the page would
    promise names that fail to find."""

    def setUp(self):
        self.jd = api.julian(dt.datetime(2026, 7, 30, 23, 0))

    def test_section_counts_match_the_underlying_catalogues(self):
        text = api.catalog_text(color=False)
        stars = api.sky._load("stars.json")
        asterisms = api.sky._load("asterisms.json")
        dso = api.sky._load("deepsky.json")
        n_stars = sum(1 for s in stars if s.get("n"))
        n_dso = sum(1 for o in dso if o["n"] != o["id"])
        self.assertIn(f"NAMED STARS ({n_stars})", text)
        self.assertIn(f"CONSTELLATIONS ({len(asterisms)})", text)
        self.assertIn(f"DEEP SKY ({n_dso})", text)

    def test_a_named_star_is_actually_findable(self):
        text = api.catalog_text(color=False)
        self.assertIn("Sirius", text)
        self.assertIsNotNone(api.resolve_target("Sirius", self.jd, 47.4, 0.0))

    def test_an_asterism_is_actually_findable(self):
        text = api.catalog_text(color=False)
        self.assertIn("Big Dipper", text)
        self.assertIsNotNone(api.resolve_target("Big Dipper", self.jd, 47.4, 0.0))

    def test_a_common_named_dso_shows_its_messier_and_common_name(self):
        text = api.catalog_text(color=False)
        self.assertIn("M31 (Andromeda Galaxy)", text)
        self.assertIsNotNone(api.resolve_target("M31", self.jd, 47.4, 0.0))
        self.assertIsNotNone(api.resolve_target("Andromeda Galaxy", self.jd, 47.4, 0.0))

    def test_bare_ngc_numbered_objects_are_excluded(self):
        # Those have no traditional name -- just a catalogue number -- so
        # they don't belong on a page of *named* objects.
        text = api.catalog_text(color=False)
        dso_section = text[text.index("DEEP SKY"):]
        self.assertNotIn("NGC", dso_section)

    def test_solar_system_bodies_are_listed(self):
        text = api.catalog_text(color=False)
        for body in ("Sun", "Moon", "Venus", "Jupiter"):
            self.assertIn(body, text)

    def test_solar_system_bodies_use_the_same_glyphs_as_the_chart(self):
        # Same glyphs sky.py's render()/render_linear() actually draw on the
        # chart -- so this list can't drift into showing symbols nothing on
        # screen matches. Moon's glyph is the real current phase, not a
        # fixed circle, so it's checked separately below.
        text = api.catalog_text(color=False)
        i = text.index("SOLAR SYSTEM")
        section = text[i:text.index("CONSTELLATIONS")]
        self.assertIn("☀ Sun", section)
        self.assertIn("◆ Mercury", section)

    def test_moon_shows_its_real_current_phase(self):
        import sky
        text = api.catalog_text(color=False)
        age = sky.moon(sky.julian(dt.datetime.utcnow()))["age"]
        self.assertIn(f"Moon ({sky.phase_name(age)})", text)
        self.assertIn(sky.moon_glyph(age), text[text.index("SOLAR SYSTEM"):text.index("Moon")])

    def test_named_stars_show_a_brightness_glyph_and_full_constellation_name(self):
        text = api.catalog_text(color=False)
        # Sirius is mag -1.46, well under sky.glyph_for's 0.8 cutoff for the
        # brightest dot -- and CMa's full name should show, not the abbreviation.
        self.assertIn("● Sirius", text)
        self.assertIn("Canis Major", text)
        self.assertNotIn(" CMa\n", text)


class CatalogHtml(unittest.TestCase):
    """catalog_html() is the browser-only twin of catalog_text() -- every
    object links to its own page, opened in a new tab so browsing the catalog
    never navigates away from the chart on screen.

    These used to link to /?find=<name>, which framed the object on a chart
    of the current sky. Every catalogue entry now has a page of its own, and
    a page is the better destination: it says what the object is as well as
    where it is tonight, it has a stable URL worth sharing, and it is what a
    search engine indexes."""

    def test_a_star_links_to_its_own_page_in_a_new_tab(self):
        h = api.catalog_html()
        self.assertIn('href="/Sirius" target="_blank" rel="noopener"', h)

    def test_moon_link_uses_the_plain_name_not_the_phase_annotated_display(self):
        # Displayed as "Moon (waning gibbous)" or similar, but only the bare
        # word resolves -- the phase text in parens would 404 if it leaked
        # into the href.
        import sky
        h = api.catalog_html()
        self.assertIn('href="/Moon" target="_blank" rel="noopener"', h)
        age = sky.moon(sky.julian(dt.datetime.utcnow()))["age"]
        self.assertIn(f"Moon ({sky.phase_name(age)})", h)

    def test_a_multi_word_name_is_url_encoded(self):
        h = api.catalog_html()
        self.assertIn('href="/Big%20Dipper"', h)

    def test_a_dso_links_by_designation_not_by_its_whole_label(self):
        h = api.catalog_html()
        # Displayed as "M31 (Andromeda Galaxy)" but the href must use the
        # canonical short id, not the whole parenthesised label, which does
        # not resolve to anything.
        self.assertIn('href="/M31"', h)
        self.assertIn(">M31 (Andromeda Galaxy)<", h)

    def test_no_link_still_points_at_the_old_find_view(self):
        h = api.catalog_html()
        self.assertNotIn("/?find=", h)

    def test_every_catalog_link_resolves_to_a_real_object(self):
        """486 entries, and a catalogue that links into a 404 is worse than
        one that does not link at all."""
        import objects
        d = api._catalog_data()
        targets = ([nm for nm, _d, _g, _c in d["solar_system"]]
                   + list(d["asterisms"])
                   + [s["n"] for s in d["named_stars"]]
                   + [o["n"] for o in d["named_dso"]])
        broken = [t for t in targets if objects.resolve_name(t) is None]
        self.assertEqual(broken, [], f"catalog links with no page: {broken}")

    def test_planets_get_distinct_colours_not_one_shared_colour(self):
        h = api.catalog_html()
        mercury = h[h.index("Mercury") - 60:h.index("Mercury")]
        venus = h[h.index("Venus") - 60:h.index("Venus")]
        self.assertNotEqual(
            mercury[mercury.index("color:"):mercury.index("color:") + 20],
            venus[venus.index("color:"):venus.index("color:") + 20])

    def test_lists_the_same_objects_as_the_terminal_version(self):
        # Both are built from _catalog_data() -- this pins that they can't
        # drift into showing different objects for the two audiences.
        text = api.catalog_text(color=False)
        h = api.catalog_html()
        self.assertIn("NAMED STARS (327)", text)
        self.assertIn("NAMED STARS (327)", h)
        self.assertIn("DEEP SKY (122)", text)
        self.assertIn("DEEP SKY (122)", h)


class TwilightFade(unittest.TestCase):
    """How fast stars arrive as the Sun goes down. The curve used to hold
    them back until well past nautical twilight: at 11 degrees down it
    allowed magnitude -0.91, one star in the whole catalogue, so a chart an
    hour after dusk showed a planet and nothing else."""

    def limit(self, alt):
        return api._fade_mag_limit(alt)

    def test_nothing_while_the_sun_is_up_and_the_full_catalogue_at_full_dark(self):
        # The endpoints are the part that must not move.
        self.assertEqual(self.limit(10), -5.0)
        self.assertEqual(self.limit(0), -5.0)
        self.assertEqual(self.limit(-18), 4.0)
        self.assertEqual(self.limit(-30), 4.0)

    def test_the_first_evening_stars_arrive_when_they_really_do(self):
        # Vega 0.03, Arcturus -0.05: naked-eye well before astronomical
        # twilight. Anything later than about 9 degrees is the old bug.
        self.assertGreaterEqual(self.limit(-9), 0.05)
        # Deneb (1.25) and the rest of first magnitude by nautical twilight.
        self.assertGreaterEqual(self.limit(-12), 1.25)
        # But not a sky full of stars while it is still properly bright.
        self.assertLess(self.limit(-4), 0.0)

    def test_it_only_ever_brightens_as_the_sun_sets(self):
        prev = None
        for tenths in range(0, -181, -1):
            cur = self.limit(tenths / 10)
            if prev is not None:
                self.assertGreaterEqual(cur, prev, f"at {tenths/10}")
            prev = cur

    def test_a_real_chart_after_dusk_has_stars_in_it(self):
        # The end of the whole point: a Geneva chart at nautical twilight
        # showing Venus alone was what started this.
        # Request takes local wall clock at the place -- handing it UTC
        # renders two hours earlier, which in August is still daylight and
        # gets the Sun's-path view instead of a star chart.
        text = api.compose(api.Request(place="Geneva",
                                       when=dt.datetime(2026, 8, 3, 22, 13),
                                       color=False)).text
        self.assertIn("Vega", text)
        self.assertIn("Arcturus", text)


class FindingTheSun(unittest.TestCase):
    """?find=Sun answered "not visible: the sky is still too bright", then
    "0° from the Sun: too deep in the glare", and drew nothing. Both rules
    are about picking a faint thing out of a bright sky, which is not a
    question about the Sun. It matters beyond curiosity: the "show me that
    sky" button on a solar eclipse goes straight here, and a solar eclipse
    is by definition something you look at in daylight."""

    # 12 Aug 2026, the total solar eclipse. Partial from Geneva, with the
    # Sun about 10° up an hour before it sets -- the awkward case, low and
    # in daylight.
    PLACE = "Geneva"
    ECLIPSE_LOCAL = dt.datetime(2026, 8, 12, 19, 47)

    def _at(self, local, **kw):
        # Straight through: Request's when= is local wall clock at the place
        # (it subtracts the offset itself). Converting first landed these
        # two hours early -- still daylight, so the assertions held, but not
        # on the moment they name.
        return api.compose(api.Request(place=self.PLACE, when=local, color=False,
                                       find="Sun", **kw))

    def test_the_sun_is_visible_when_it_is_up(self):
        res = self._at(self.ECLIPSE_LOCAL)
        self.assertTrue(res.data["visible"], res.text[:200])
        self.assertNotIn("too deep in the glare", res.text)
        self.assertNotIn("too bright", res.text)

    def test_the_chart_is_actually_drawn_and_points_at_the_sun(self):
        res = self._at(self.ECLIPSE_LOCAL)
        self.assertIn("finding Sun", res.text)
        self.assertIn("SUN", res.text)          # the marker, not just prose
        self.assertIn("Moon", res.text)          # its eclipse mate, on top of it
        self.assertIn("above the horizon in the", res.text)   # where to look
        self.assertGreater(res.text.count("\n"), 30)          # a chart, not a note

    def test_daylight_does_not_get_a_night_sky_drawn_over_it(self):
        # mag_limit alone fades the star field but not the lines through it
        # or the planets, and nothing noticed while find in daylight never
        # reached a chart at all.
        res = self._at(self.ECLIPSE_LOCAL)
        for label in ("LYRA", "NORTHERN CROSS", "SPRING TRIANGLE", "SICKLE"):
            self.assertNotIn(label, res.text)
        for body in ("Venus", "Jupiter", "Mercury", "Saturn"):
            self.assertNotIn(body, res.text)

    def test_a_chart_for_a_picked_moment_does_not_claim_it_is_visible_now(self):
        # The header says 12 Aug 2026 19:45 and the notice under it said
        # "Visible now." -- read together that is a chart claiming the
        # present tense for a Wednesday next week.
        res = self._at(self.ECLIPSE_LOCAL)
        self.assertIn("Visible then.", res.text)
        self.assertNotIn("Visible now.", res.text)

    def test_a_chart_for_the_present_still_says_now(self):
        # now= rather than when=, so the request carries no ?t= and the
        # chart really is about the moment someone is reading it.
        p = api.lookup_place(self.PLACE)
        now = self.ECLIPSE_LOCAL - dt.timedelta(hours=p.offset(dt.datetime(2026, 8, 12)))
        res = api.compose(api.Request(place=self.PLACE, now=now, find="Sun",
                                      color=False))
        self.assertIn("Visible now.", res.text)
        self.assertNotIn("Visible then.", res.text)

    def test_not_visible_at_a_picked_moment_drops_the_present_tense_too(self):
        res = self._at(dt.datetime(2026, 8, 13, 1, 0))
        self.assertIn("Not visible then,", res.text)
        self.assertNotIn("right now", res.text)

    def test_after_dark_the_answer_is_the_next_sunrise(self):
        # Not "no window in the next 40 days", which is what searching for a
        # dark sky with the Sun up gets you.
        res = self._at(dt.datetime(2026, 8, 13, 1, 0))
        self.assertFalse(res.data["visible"])
        self.assertEqual(res.data["reason"], "below the horizon")
        self.assertIsNotNone(res.data["next_visible"])
        self.assertNotIn("too deep in the glare", res.text)
        self.assertIn("Next chance", res.text)

    def test_the_eclipse_card_still_points_here(self):
        # The bug arrived through the card's CTA, so this pins the two ends
        # together: whatever the card links to has to be a chart.
        import events
        p = api.lookup_place(self.PLACE)
        r = api.Request(place=self.PLACE)
        evs = events.next_events(p.lat, p.lon, p.offset(r.when_utc), within_days=14,
                                 now_utc=dt.datetime(2026, 8, 3, 12, 0))
        ecl = next((e for e in evs if e["kind"] == "eclipse"), None)
        self.assertIsNotNone(ecl, "no eclipse in the window to check")
        self.assertIn("find=Sun", api._event_url(ecl, r))


class LegendMatchesTheRealGlyphs(unittest.TestCase):
    def test_moon_phase_row_is_generated_not_hand_typed(self):
        # Regression test: this line used to be a separately hand-typed
        # literal string that could (and did) drift out of sync once
        # moon_glyph()'s own output changed.
        import sky
        text = api.legend_text(color=False)
        expected = " ".join(sky.moon_glyph(a) for a in range(0, 360, 45))
        self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
