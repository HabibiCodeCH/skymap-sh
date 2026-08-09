#!/usr/bin/env python3
"""Tests for the nearest-city timezone fallback in api.py.

Run:  python3 test_api.py
"""
import datetime as dt
import os
import json
import re
import unittest
import api
import art
import objects
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

    def test_the_png_is_the_horizon_view_and_its_zenith(self):
        # The inset is part of the chart and every export carries it: the
        # cap of sky above the panorama is sky, and leaving it out gave the
        # shared picture less than the page it was shared from. What the
        # export still leaves out is everything that is not the drawing --
        # the prose, the footer, the share line.
        when = dt.datetime(2026, 7, 30, 22, 0)
        for find in ("M31", "Vega", "Jupiter"):
            art = api.compose_chart_only(api.Request(place="Zurich", when=when,
                                                     find=find, color=False))
            self.assertIn("zenith", art, find)
            self.assertNotIn("Share as a PNG", art, find)
        # and the plain export it is meant to match agrees
        plain = api.compose_chart_only(api.Request(place="Zurich", when=when,
                                                   color=False))
        self.assertIn("zenith", plain)
        # and so does the page both of them come from -- one flag, on
        # everywhere, so no view has its own idea of where the chart stops
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
    """find= wasn't the only one missing -- t= and nolines= also changed
    what /horizon.png actually rendered without ever reaching the "Share as
    a PNG" link either. Same bug, more instances of it. (view=disc was a
    third; the view itself is gone.)"""

    def test_explicit_time_travels_with_the_link(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 12, 18, 0))
        self.assertIn("t=2026-08-12T18:00", api._png_url(r))

    def test_default_now_does_not_freeze_the_link_to_a_timestamp(self):
        # No explicit ?t= means "whatever's current" -- the link must stay
        # bare so it keeps tracking the real time on every fetch, not get
        # pinned to the moment it happened to be generated.
        r = api.Request(place="Zurich")
        self.assertNotIn("t=", api._png_url(r))

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

    def test_an_ordinary_night_still_gets_a_darkest_time(self):
        """The word is "darkest" rather than "fully dark". The time is still
        astronomical dusk -- what changed is the claim made about it, since
        a city sky never gets fully dark whatever the Sun does, and
        "darkest" is true at both ends without needing to know the Bortle."""
        res = api.compose(api.Request(place="Geneva", when=self.ORDINARY, color=False))
        self.assertIsNotNone(res.data["dark_from"])
        self.assertFalse(res.data["never_fully_dark"])
        self.assertIn("darkest", res.data["prose"])

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

    def png_size(self, chart_only=False, **kw):
        """chart_only cuts the zenith inset off before measuring: it is a
        fixed 21x11 block riding under every export, so it does not scale
        with the width and only the panorama's own aspect is meaningful."""
        import io
        from PIL import Image
        import gif
        r = api.Request(place="-24.63,-70.40", when=self.WHEN, color=True, **kw)
        text = api.compose_chart_only(r)
        if chart_only:
            text = text.split("zenith ")[0]
        return Image.open(io.BytesIO(gif.frame_to_png(text))).size

    def test_the_export_is_wider_than_the_terminal_default(self):
        self.assertEqual(api.PNG_WIDTH, 140)
        self.assertGreater(api.PNG_WIDTH, api.DEFAULT_HORIZON_WIDTH)

    def test_the_terminal_default_is_untouched(self):
        r = api.Request(place="Geneva", when=self.WHEN)
        self.assertEqual(api._effective_width(r), api.DEFAULT_HORIZON_WIDTH)

    def test_height_follows_width_so_the_aspect_holds(self):
        # Widening without this gave a letterbox: 140 columns of chart in
        # the row count of a 110-column one.
        #
        # Measured on the panorama alone. The zenith inset is a fixed 21x11
        # block that rides under every export now, and a fixed block does
        # not scale with the width, so the whole image's ratio drifts by
        # design -- the thing this guards is the chart, which is the part
        # that letterboxed.
        #
        # delta is loose on purpose. The aspect can only ever be approximate:
        # the two-line header is the same height at every width, and the row
        # count is round(width / HORIZON_COLS_PER_ROW), so both a constant
        # and a rounding sit inside the ratio. What this guards is
        # letterboxing -- 140 columns in a 110-column row count, which is a
        # factor, not five percent.
        w1, h1 = self.png_size(chart_only=True)
        w2, h2 = self.png_size(width=200, chart_only=True)
        self.assertAlmostEqual(w1 / h1, w2 / h2, delta=0.15)

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
    object links to its own page, in the same tab.

    These used to link to /?find=<name>, which framed the object on a chart
    of the current sky. Every catalogue entry now has a page of its own, and
    a page is the better destination: it says what the object is as well as
    where it is tonight, it has a stable URL worth sharing, and it is what a
    search engine indexes."""

    def test_a_star_links_to_its_own_page(self):
        h = api.catalog_html()
        self.assertIn('href="/Sirius"', h)

    def test_nothing_in_the_catalog_opens_a_new_tab(self):
        """486 entries that each spawn a tab is a browser to tidy up. Back
        returns you to the catalog, which is what a list is for."""
        h = api.catalog_html()
        self.assertNotIn('target="_blank"', h)

    def test_moon_link_uses_the_plain_name_not_the_phase_annotated_display(self):
        # Displayed as "Moon (waning gibbous)" or similar, but only the bare
        # word resolves -- the phase text in parens would 404 if it leaked
        # into the href.
        import sky
        h = api.catalog_html()
        self.assertIn('href="/Moon"', h)
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
        # together: whatever the card links to has to be about this place.
        # It used to be a chart with the Sun crosshaired; the eclipse's own
        # page is the better answer to the same question, and it is where
        # this now goes.
        import events
        p = api.lookup_place(self.PLACE)
        r = api.Request(place=self.PLACE)
        evs = events.next_events(p.lat, p.lon, p.offset(r.when_utc), within_days=14,
                                 now_utc=dt.datetime(2026, 8, 3, 12, 0))
        ecl = next((e for e in evs if e["kind"] == "eclipse"), None)
        self.assertIsNotNone(ecl, "no eclipse in the window to check")
        url = api._event_url(ecl, r)
        self.assertTrue(url.startswith(f"/{r.place.slug}/"), url)
        self.assertIn("/eclipse/", url)


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


# Catalogue groups that are pages rather than objects: reached by typing
# the page name in the bar, not by completing an object name.
NOT_AN_OBJECT = {"eclipses"}


class EveryCatalogGroupIsSearchable(unittest.TestCase):
    """The search bar offered solar system, stars, deep sky and
    constellations, and silently skipped showers -- the one group that is
    only worth looking up in the few weeks around its peak. Every one of
    them already had a working page, so /Perseids resolved and nothing ever
    suggested it."""

    def test_showers_complete(self):
        for q, want in (("per", "Perseids"), ("gem", "Geminids"),
                        ("quad", "Quadrantids"), ("orio", "Orionids")):
            names = [o["name"] for o in api.complete_objects(q)]
            self.assertIn(want, names, q)

    def test_every_group_in_the_catalog_can_be_completed(self):
        """The guard that matters: a new group added to _catalog_data() but
        not to complete_objects() would be invisible in exactly the way
        showers were, and nothing else would fail."""
        d = api._catalog_data()
        probes = {
            "ours": "milky",
            "solar_system": "satu",
            "named_stars": "vega",
            "named_dso": "androm",
            "showers": "perse",
            "asterisms": "big",
        }
        # Eclipses are the one group that is not an object and is not
        # completed by name -- there is no name to type, only a date. The
        # bar reaches them as a page, the way /events and /catalog are
        # reached, and NOT_AN_OBJECT is where that is asserted. Listed here
        # so a group added later still has to be accounted for.
        self.assertEqual(set(probes) | NOT_AN_OBJECT, set(d),
                         "a catalog group has been added or renamed; give it "
                         "a probe here and a loop in complete_objects(), or "
                         "add it to NOT_AN_OBJECT and say how it is reached")
        for group, q in probes.items():
            self.assertTrue(api.complete_objects(q), f"{group} completes nothing")

    def test_the_groups_that_are_not_objects_are_reachable_anyway(self):
        """A catalogue row nothing can navigate to is a dead end. These are
        pages rather than objects, so the search bar has to offer them by
        page name instead."""
        import objects
        self.assertIn("eclipse", api.SEARCH_PAGES)
        self.assertIn("eclipse", objects.RESERVED)

    def test_a_shower_completion_resolves_to_a_real_page(self):
        import objects
        for o in api.complete_objects("per"):
            self.assertIsNotNone(objects.resolve_name(o.get("q") or o["name"]),
                                 o["name"])

    def test_the_shower_mark_is_the_one_the_chart_uses(self):
        got = {o["glyph"] for o in api.complete_objects("perse")}
        self.assertEqual(got, {api._SHOWER_GLYPH})


class OnePictureHeader(unittest.TestCase):
    """The still export and the animation frames are two renders on purpose
    -- an animation ramps the magnitude limit so stars fade in as the sky
    darkens -- but the line above the chart is one idea, and it has drifted
    twice. The Milky Way band was left off the still; the summary was left
    off the frames, so a shared GIF carried the old two-part CLI header
    while the page it came from carried the Moon, the planets, the twilight
    state and the Bortle estimate."""

    def _head(self, text):
        return api.strip_ansi(text).splitlines()[0].strip()

    def test_a_frame_carries_the_same_header_as_the_still(self):
        # At night, when both render the same panorama.
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 5, 22, 25),
                        width=140)
        self.assertEqual(self._head(api.compose_chart_only(r)),
                         self._head(api.compose_frame(r)[0]))

    def test_a_frame_header_is_the_summary_not_the_cli_two_parter(self):
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 5, 22, 25),
                        width=140)
        head = self._head(api.compose_frame(r)[0])
        self.assertIn("·", head)
        self.assertIn("Bortle", head)
        # The old form: place, then lat/lon, then a date, then a mode name.
        self.assertNotIn("46.20°N", head)
        self.assertNotIn("horizon panorama", head)

    def test_it_works_at_every_hour_including_when_a_body_is_not_drawn(self):
        # A frame only asks the renderer for the bodies it is drawing, so at
        # midday its stats carry no Moon and at night no Sun. The header
        # fills both from the ephemeris rather than trusting what was drawn,
        # which is what stopped this raising KeyError.
        for hour in range(0, 24, 3):
            r = api.Request(place="Geneva",
                            when=dt.datetime(2026, 8, 5, hour, 25), width=140)
            head = self._head(api.compose_frame(r)[0])
            self.assertTrue(head, hour)
            self.assertIn("Geneva", head, hour)

    def test_the_frame_stats_are_not_mutated(self):
        # compose_frame runs once per animation frame; the header must not
        # scribble on the render stats it was handed.
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 5, 12, 25),
                        width=140)
        art, st = api.render_linear(r.when_utc, r.place.lat, r.place.lon,
                                    color=False, width=140, height=24)
        before = {k: dict(v) if isinstance(v, dict) else v for k, v in st.items()}
        api._export_head(r, st, "")
        for k, v in before.items():
            if isinstance(v, dict):
                self.assertEqual(st[k], v, k)


class TheDayChartIsTheSameHeightAsTheNight(unittest.TestCase):
    """The Sun's arc was 72% of the star chart's height in a browser, to
    leave room for a panel of tonight beside it and a list of events under
    it. Both of those live in the modal now and the chart has the page to
    itself, so the reason is gone -- and a day chart drawn shorter than the
    night one is the two views disagreeing about their own axis, which is
    the thing this layout exists to stop."""

    NOON = dt.datetime(2026, 8, 7, 12, 0)

    def test_a_terminal_still_gets_the_full_height(self):
        r = api.Request(place="Zurich", when=self.NOON)
        self.assertEqual(api._day_height(r), api._horizon_height(r))

    def test_a_browser_gets_the_same_rows(self):
        r = api.Request(place="Zurich", when=self.NOON, width=300, panel=True)
        self.assertEqual(api._day_height(r), api._horizon_height(r))

    def test_the_short_chart_really_is_shorter(self):
        """Not just the number -- the drawing itself."""
        wide = api.Request(place="Zurich", when=self.NOON, width=300)
        panel = wide.sized(300, True)
        tall = api._compose_day(wide).text.count("\n")
        short = api._compose_day(panel).text.count("\n")
        self.assertLess(short, tall)

    def test_it_is_a_resolution_change_and_not_a_crop(self):
        """The same slice of sky, drawn with fewer rows. If this ever became
        a crop, the top of the arc would be the first thing to go -- so the
        Sun's greatest altitude is what proves it did not."""
        wide = api.Request(place="Zurich", when=self.NOON, width=300)
        panel = wide.sized(300, True)
        self.assertAlmostEqual(api._compose_day(wide).data["max_alt"],
                               api._compose_day(panel).data["max_alt"], places=6)

    def test_the_floor_holds_at_the_narrowest_rung(self):
        """The 80-column rung is 17 rows before the multiplier and 12 after
        the floor catches it. Fewer than that and 70 degrees of sky would be
        drawn on a handful of lines."""
        r = api.Request(place="Zurich", when=self.NOON,
                        width=api.CHART_LADDER[0][1], panel=True)
        self.assertGreaterEqual(api._day_height(r), 12)


class TheTonightPanel(unittest.TestCase):
    """What goes beside the shrunk arc. Reads the day view's own JSON payload
    rather than recomputing anything, so a number can only be wrong here by
    being wrong at ?format=json too."""

    def _req(self, place, when):
        return api.Request(place=place, when=when, width=300, panel=True)

    def _data(self, place, when):
        return api._compose_day(self._req(place, when)).data

    def _panel(self, place, when):
        r = self._req(place, when)
        return api.day_tonight_html(r, api._compose_day(r).data)

    def test_it_carries_only_what_the_summary_line_does_not(self):
        """The line above it already gives the place, the clock, sunrise,
        sunset, first stars, full dark and which planets are up. Repeating
        those five facts eighteen inches lower was half the reason the page
        did not fit on a screen."""
        html = self._panel("Zurich", dt.datetime(2026, 8, 7, 12, 0))
        self.assertIn("moon", html)
        for gone in ("first stars", "fully dark", "sun highest"):
            self.assertNotIn(gone, html, gone)

    def test_the_times_match_the_payload(self):
        when = dt.datetime(2026, 8, 7, 12, 0)
        data, html = self._data("Zurich", when), self._panel("Zurich", when)
        # The Moon is what is left in the grid.
        self.assertIn(data["moon"]["phase"], html)
        # The button still points at first stars, which is the moment there
        # is something on the chart rather than the moment the light goes.
        self.assertIn(data["first_stars"][:16], html)

    def test_every_drawing_is_its_own_way_into_the_night(self):
        """There is no general "show me tonight's sky" button any more. Each
        slide links to the thing it is a picture of, at the moment that thing
        is worth looking at, which is four more useful links than one vague
        one."""
        when = dt.datetime(2026, 8, 7, 12, 0)
        html = self._panel("Zurich", when)
        self.assertNotIn("dt-cta", html)
        self.assertIn('class="dt-art-box" href="/Zurich/', html)

    def test_a_night_that_never_darkens_is_said_on_the_line_above(self):
        """Reykjavik in June has no astronomical dusk at all. That fact did
        not disappear with the row -- the summary line carries it, which is
        exactly why the row was redundant."""
        when = dt.datetime(2026, 6, 21, 12, 0)
        r = self._req("Reykjavik", when)
        res = api._compose_day(r)
        self.assertTrue(res.data["never_fully_dark"])
        self.assertNotIn("never tonight", self._panel("Reykjavik", when))
        self.assertIn("never fully dark", api.strip_ansi(res.text))

    def test_polar_day_drops_the_countdown_rather_than_faking_one(self):
        """No sunset means no first stars, so there is nothing to link to and
        no time to print. The panel keeps what it does know."""
        when = dt.datetime(2026, 6, 21, 12, 0)
        data = self._data("Longyearbyen", when)
        html = self._panel("Longyearbyen", when)
        self.assertIsNone(data["first_stars"])
        self.assertNotIn("first stars", html)
        self.assertNotIn("dt-cta", html)
        # The box is still there, still says what the Moon is doing, and
        # simply has no button to offer.
        self.assertIn('id="day-tonight"', html)
        self.assertIn("moon", html)

    def test_a_night_view_gets_no_panel_at_all(self):
        """The guard that lets the caller stay one line."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 23, 0),
                        width=300, panel=True)
        self.assertEqual(api.day_tonight_html(r, api.compose(r).data), "")

    def test_a_payload_with_nothing_in_it_still_renders(self):
        """Every row is optional now. The box is the drawing and the button;
        the grid is whatever is left worth saying."""
        r = self._req("Zurich", dt.datetime(2026, 8, 7, 12, 0))
        html = api.day_tonight_html(r, dict(view="day", visible_tonight=[],
                                            moon={}, events={}))
        self.assertIn('id="day-tonight"', html)

    def test_the_links_use_the_places_own_slug(self):
        """"New York" is two words and its slug is one. The panel takes the
        slug off the request rather than being handed one, which is what
        stops these links and the rest of the page disagreeing about the URL
        for the place they are both describing."""
        r = self._req("New York", dt.datetime(2026, 8, 7, 12, 0))
        html = api.day_tonight_html(r, api._compose_day(r).data)
        self.assertEqual(r.place.slug, "NewYork")
        self.assertIn(f'href="/{r.place.slug}/', html)


class TheNextUpList(unittest.TestCase):
    """Five rows under the arc, from the same _events_for/_event_date/
    _event_url that /{place}/events uses -- so the short list and the long
    one cannot disagree about a date or a destination."""

    def _r(self, place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0)):
        return api.Request(place=place, when=when, width=300, panel=True)

    def test_it_stops_at_five_dated_rows(self):
        """The cap is on the dated rows. Anything running tonight sits above
        them in its own group and outside the count -- a shower is not a date
        and giving it one of the five put "on tonight" in front of "on the
        12th" and pushed the Perseids' own peak off the page."""
        # class="nu-row and not class="nu-row": a row on a night carrying
        # more than one event is class="nu-row nu-super".
        html = api.day_next_up_html(self._r())
        dated = html.count('class="nu-row') - html.count('class="nu-row nu-now')
        self.assertEqual(dated, api.DAY_NEXT_UP_ROWS)

    def test_the_on_now_group_sits_above_the_dated_rows(self):
        html = api.day_next_up_html(self._r())
        self.assertIn('class="nu-row nu-now', html)
        self.assertIn("on now", html)
        # Above, so it reads as a group rather than as a row whose date
        # failed to render.
        self.assertLess(html.index('nu-now'), html.index('nu-when">Wed'))

    def test_the_rows_are_the_ones_the_events_page_would_show(self):
        r = self._r()
        html = api.day_next_up_html(r)
        want = api._events_for(r, days=api.EVENTS_WINDOW_DAYS,
                               visible_only=True)[:api.DAY_NEXT_UP_ROWS]
        for e in want:
            self.assertIn(api.html.escape(e["headline"]), html)
            self.assertIn(api.html.escape(api._event_url(e, r)), html)

    def test_the_dates_are_the_evening_you_go_outside(self):
        """_event_date, not the peak instant -- the 2026 Perseid maximum is
        13 Aug 02:10 UT and belongs on the 12th, which is what every almanac
        and this site's own event list say."""
        r = self._r()
        for e in api._events_for(r, days=api.EVENTS_WINDOW_DAYS,
                                 visible_only=True)[:api.DAY_NEXT_UP_ROWS]:
            self.assertIn(f"{api._event_date(e):%a %d %b}", api.day_next_up_html(r))

    def test_it_only_lists_what_you_could_actually_go_and_see(self):
        """The long list has room to say "happening, but not from here" and
        why; five rows do not, and a row you cannot act on is worse than one
        fewer row.

        Matched on the url rather than the headline, because headlines repeat:
        "Moon and Mercury 2.0° apart" is a reachable event in August and an
        unreachable one in October, so a headline test would pass or fail on
        which month it happened to run in."""
        r = self._r()
        html = api.day_next_up_html(r)
        blocked = [e for e in api._events_for(r, days=api.EVENTS_WINDOW_DAYS,
                                              visible_only=False)
                   if e["visible"] is False]
        self.assertTrue(blocked, "nothing unreachable in the window -- "
                                 "this test would pass on an empty page")
        for e in blocked:
            self.assertNotIn(api.html.escape(api._event_url(e, r)), html)

    def test_it_offers_the_full_list(self):
        self.assertIn('href="/Zurich/events"', api.day_next_up_html(self._r()))

    def test_nothing_coming_up_renders_nothing(self):
        self.assertEqual(api.day_next_up_html(self._r(), n=0), "")


class TheEventTailIsWrittenOnce(unittest.TestCase):
    """Both lists render "where to look and when". Sharing _event_tail is
    what stops them ending up disagreeing about whether a shower says its
    rate or a conjunction says its altitude."""

    def test_the_long_list_still_reads_the_same(self):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0))
        for e in api._events_for(r, days=api.EVENTS_WINDOW_DAYS, visible_only=True):
            line = api._event_line(e, r)
            for piece in api._event_tail(e):
                self.assertIn(piece, line)

    def test_a_shower_says_its_rate_in_both(self):
        """The peak, specifically. A shower merely running carries no rate at
        all -- see events.active_showers -- so picking the first shower in
        the list would now pick one with nothing to assert about."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0))
        evs = api._events_for(r, days=api.EVENTS_WINDOW_DAYS, visible_only=True)
        shower = next(e for e in evs
                      if e["kind"] == "meteor_shower" and e.get("at_peak"))
        self.assertTrue(any("/hr" in p for p in api._event_tail(shower)))
        self.assertIn("/hr", api._event_line(shower, r))

    def test_a_shower_merely_running_quotes_no_rate(self):
        """The other half. zhr is the maximum under a perfect sky, and a
        night three weeks off peak is not that night.

        Through _running_now, not _events_for: a span is dated now and is
        kept out of the chronological list for that reason."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0))
        running = api._running_now(r)
        self.assertTrue(running, "the Perseids are running on 7 August")
        for e in running:
            self.assertFalse(e.get("at_peak"))
            self.assertNotIn("/hr", api._event_line(e, r))

    def test_the_chronological_list_keeps_the_peak_and_only_the_peak(self):
        """The regression this separation exists to prevent: a span dated now
        sorted ahead of everything, took a row off the five-row cap and
        pushed the Perseids' own peak off the page."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0))
        evs = api._events_for(r, days=api.EVENTS_WINDOW_DAYS, visible_only=True)
        showers = [e for e in evs if e["kind"] == "meteor_shower"]
        self.assertTrue(showers)
        for e in showers:
            self.assertTrue(e.get("at_peak"), e["headline"])
        self.assertIn("/hr", api.day_next_up_html(
            api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0),
                        width=300, panel=True)))


class TheDayLayout(unittest.TestCase):
    """Head above, arc and panel side by side, the list beneath. Every piece
    is optional and degrades by disappearing."""

    def test_every_piece_present(self):
        out = api.day_layout("HEAD", "CHART", "PANEL", "LIST")
        self.assertIn('id="day-split"', out)
        for want in ("HEAD", "CHART", "PANEL", "LIST"):
            self.assertIn(want, out)
        self.assertTrue(out.startswith("HEAD"))

    def test_the_list_sits_under_the_chart_and_not_under_the_grid(self):
        """The panel beside the arc is taller than the arc, so a list below
        the whole grid started below the fold with a hand's width of black
        above it. In the left column it fills exactly that gap."""
        out = api.day_layout("", "CHART", "PANEL", "LIST")
        main = out.split('id="day-main"')[1].split('PANEL')[0]
        self.assertIn("CHART", main)
        self.assertIn("LIST", main)

    def test_the_title_says_what_the_box_is(self):
        out = api.day_layout("", "CHART", "PANEL", "")
        self.assertIn("the sky above you now", out)

    def test_no_panel_leaves_the_chart_full_width(self):
        out = api.day_layout("", "CHART", "", "LIST")
        self.assertNotIn('id="day-split"', out)
        self.assertEqual(out, "CHARTLIST")

    def test_nothing_but_the_chart_returns_it_untouched(self):
        self.assertEqual(api.day_layout("", "CHART", "", ""), "CHART")

    def test_the_chart_column_can_shrink(self):
        """#chart-ladder is a container-type:inline-size query container, so
        it measures its parent. min-width:0 on the column is what lets that
        parent be narrower than the widest rung inside it -- without it the
        grid track refuses to go below min-content and the panel is pushed
        off the right edge."""
        # PAGE is a format template, so every CSS brace in it is doubled.
        css = api.PAGE
        self.assertIn("#day-chart,#night-chart{{min-width:0;background:#04060a}}", css)
        self.assertIn("minmax(0,1fr) 300px", css)

    def test_the_panel_column_is_wide_enough_for_the_drawing(self):
        """45 characters (art.COLS) at 10px in a 0.6em monospace is 270px,
        and the box adds 12px of padding either side. At 280px the last two
        columns of every planet were clipped off."""
        self.assertGreaterEqual(300 - 24, art.COLS * 10 * 0.6)


class TheSummaryLineGetsItsOwnBox(unittest.TestCase):
    """It was the chart's first line, sized as prose inside a <pre> of
    drawing. Out here it is a sentence in a box, and it gets the full width
    of the page rather than whatever the picture left it."""

    def _rungs(self):
        return [(80, True, "\n  HEAD-80\n\n 70° chart eighty\n"),
                (120, True, "\n  HEAD-120 longer\n\n 70° chart one twenty\n")]

    def test_the_line_leaves_the_chart(self):
        head, rungs = api.lift_chart_head(self._rungs())
        self.assertIn("HEAD-80", head)
        self.assertIn("HEAD-120 longer", head)
        for _cols, _panel, body in rungs:
            self.assertNotIn("HEAD-", body)
            self.assertIn("70°", body)

    def test_one_line_per_rung_because_the_line_is_not_one_line(self):
        """The summary drops pieces to fit the width it is given, so there
        are as many versions of it as there are rungs, and the box picks its
        own the same way the chart picks its own."""
        head, _rungs = api.lift_chart_head(self._rungs())
        self.assertEqual(head.count('<span class="dh">'), 2)

    def test_the_blank_line_under_it_goes_too(self):
        """It was the gap between the sentence and the drawing. The drawing
        now starts the box, so the gap would be a hole at the top of it."""
        _head, rungs = api.lift_chart_head(self._rungs())
        self.assertTrue(rungs[0][2].startswith(" 70°"))

    def test_the_line_reads_in_the_order_the_day_happens(self):
        """Sun up, where it is now, how high it gets, Sun down, stars, dark.
        Grouped by kind instead -- times together, angles together -- it read
        as a table that had lost its headings. The current position moves
        with the clock: in front of the high point in the morning and behind
        it in the afternoon."""
        def line(hour):
            r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, hour, 0),
                            width=300, panel=True)
            return api.strip_ansi(api._compose_day(r).text.split("\n")[1])
        for hour, order in ((10, ["\u2191", "\u2600", "high", "\u2193",
                                  "stars", "darkest"]),
                            (17, ["\u2191", "high", "\u2600", "\u2193",
                                  "stars", "darkest"])):
            got = line(hour)
            at = [got.index(w) for w in order]
            self.assertEqual(at, sorted(at), f"{hour}:00 -> {got}")

    def test_the_bearings_are_on_the_line(self):
        """The one fact here you cannot work out from the others. "Sunrise
        06:11" says when to set an alarm; "06:11 64 deg ENE" says which
        window to stand at."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 10, 0),
                        width=300, panel=True)
        got = api.strip_ansi(api._compose_day(r).text.split("\n")[1])
        self.assertRegex(got, r"\u2191\d\d:\d\d \d+\u00b0[NESW]+")
        self.assertRegex(got, r"\u2193\d\d:\d\d \d+\u00b0[NESW]+")

    def test_the_place_and_the_moment_arrive_as_their_own_span(self):
        """Which is the only way to bold part of a line that reaches the
        page as pre-rendered ANSI -- CSS needs an element to hold."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 10, 0),
                        width=300, panel=True)
        raw = api._compose_day(r).text.split("\n")[1]
        head, _rungs = api.lift_chart_head([(220, True, api.ansi_to_html(raw))])
        self.assertIn('<span class="dh"><span style="color:', head)
        self.assertEqual(head.count("<span style="), 2)

    def test_the_two_space_indent_comes_off(self):
        """Every prose line in the composed text carries it. In a box of its
        own it is a margin made of characters, which cannot line up with a
        title set in a different size -- so it comes off here and goes back
        as padding in CSS."""
        head, _rungs = api.lift_chart_head(
            [(80, True, '\n  <span style="color:#eeeeee">  Zurich · 07 Aug</span>\n\nchart')])
        self.assertIn('<span style="color:#eeeeee">Zurich', head)

    def test_a_rung_with_nothing_in_it_is_left_alone(self):
        head, rungs = api.lift_chart_head([(80, True, "\n\n")])
        self.assertEqual(head, "")
        self.assertEqual(rungs, [(80, True, "\n\n")])

    def test_both_ladders_come_off_one_table(self):
        """Generated from CHART_LADDER by the same function, so the box and
        the chart under it cannot drift apart -- they measure different
        widths, which is the point, but off the same table."""
        joined = api.chart_ladder_css()
        self.assertIn("#day-head-ladder .dh:nth-child", joined)
        for min_ch, _cols, _panel in api.CHART_LADDER:
            if min_ch is None:
                continue
            self.assertIn(f"@container (min-width:{min_ch}ch)", joined)

    def test_the_chart_ladders_breakpoints_are_written_unscaled(self):
        """It is pinned at CHART_FONT_PX, so its own scale factor is 1 and
        the thresholds come out as the integers CHART_LADDER holds -- not
        "107.0ch", which is the same width and a gratuitous diff."""
        joined = "".join(api._ladder_rules("#chart-ladder", ".chart-pre",
                                           api.CHART_FONT_PX))
        self.assertNotIn(".0ch", joined)
        for min_ch, _cols, _panel in api.CHART_LADDER:
            if min_ch is not None:
                self.assertIn(f"(min-width:{min_ch}ch)", joined)

    def test_a_larger_ladder_asks_for_fewer_of_its_own_characters(self):
        """The bug this exists to catch: a ch resolves against the query
        container's own font, so the same 1222px box is 203ch to the 10px
        chart and 123ch to the 16.5px summary line. Handed the chart's raw
        thresholds the line cleared one of six and sat on rung 2 of 12 at
        every window size, planets and star count included in the markup and
        shown at none of them."""
        joined = "".join(api._ladder_rules("#day-head-ladder", ".dh",
                                           api.DAY_HEAD_PX))
        scale = api.CHART_FONT_PX / api.DAY_HEAD_PX
        self.assertLess(scale, 1)
        for min_ch, _cols, _panel in api.CHART_LADDER:
            if min_ch is None:
                continue
            at = round(min_ch * scale, 1)
            at = int(at) if at == int(at) else at
            self.assertIn(f"(min-width:{at}ch)", joined)
            # And emphatically not the chart's own number, which is the
            # whole of the defect.
            self.assertNotIn(f"(min-width:{min_ch}ch)", joined)

    def test_the_widest_rung_is_reachable_in_a_real_box(self):
        """A 4K display is about 380 of the summary's characters wide. If the
        top rung needed more than that it could never appear on any screen,
        which is what the unscaled thresholds asked for (227 of them at
        16.5px is a 3750px box for the chart column alone)."""
        joined = "".join(api._ladder_rules("#day-head-ladder", ".dh",
                                           api.DAY_HEAD_PX))
        asked = [float(s.split("ch)")[0])
                 for s in joined.split("(min-width:")[1:]]
        self.assertLess(max(asked), 380)

    def test_the_stage_never_asks_the_ladder_for_an_intrinsic_width(self):
        """#chart-ladder is container-type:inline-size, which *contains* the
        inline axis -- it contributes nothing to a parent asking for
        max-content or fit-content, which resolve to 0 rather than to the
        chart's width.

        This has now collapsed the chart twice: once through fit-on, which
        stranded the zenith inset off the left edge, and once through
        anim-wide, where theatre mode on the day page grew a box 614px tall
        and 0px wide around a 1281px chart. Both times the markup was correct
        and only the layout was gone, which is why it reads as unreproducible
        from the server. No rule that reaches #chart-stage may ask for a
        shrink-to-fit width while the ladder is inside it."""
        joined = api.chart_ladder_css()
        for rule in joined:
            if "#chart-stage" not in rule:
                continue
            for shrink in ("max-content", "min-content", "fit-content"):
                self.assertNotIn(shrink, rule, rule)

    def test_the_ladder_is_still_a_query_container(self):
        """The premise of the test above -- if this stops being true the
        containment rule no longer applies and that test proves nothing."""
        joined = "".join(api.chart_ladder_css())
        self.assertIn("#chart-ladder{container-type:inline-size", joined)

    def test_the_summary_box_stays_up_through_an_animation(self):
        """It used to fold away, because the frame brings a header of its
        own and the box beside it was frozen at the moment the page was
        built. But the headline is where and when you are, and an animation
        is exactly when "when" is changing: taking it off screen at that
        moment removes the one line the movement is about."""
        css = "".join(api.chart_ladder_css())
        self.assertNotIn("#day-head{max-height:0", css)
        self.assertNotIn("html.anim-on #day-head", css)

    def test_the_page_reserves_room_for_the_fixed_shortcut_bar(self):
        """.kbd-hint is position:fixed, so it is out of the flow and nothing
        under it reserves room on its own. The page hands that room back as
        body padding, and it has to be the bar plus the page's one gap --
        a flat 40 left 7px, half what every other pair of boxes gets."""
        self.assertIn(f"padding:24px 16px {api.KBD_BAR_H + api.BOX_GAP}px",
                      api.PAGE)
        # And no leftover format field: PAGE is .format()ed per request, so
        # an unsubstituted {BOTTOM_PAD} would raise KeyError on every page.
        self.assertNotIn("{BOTTOM_PAD}", api.PAGE)

    def test_the_chart_keeps_the_frame_every_other_box_has(self):
        """It was borderless for a while, to buy back the 47px of chrome on
        a page whose rows are chosen from its width with no idea how tall
        the window is. The frame is worth more than the pixels: it is the
        one box on the page now, and an unframed one read as a drawing that
        had escaped the layout."""
        self.assertNotIn("#night-chart{{border:0", api.PAGE)
        # The title still goes: the headline above already says where and
        # when, and "the sky above you now" over it said it twice.
        self.assertIn("#night-chart>.box-head{{display:none}}", api.PAGE)

    def test_the_chart_box_is_framed_like_every_other(self):
        """No override of its own any more, so it cannot drift from the rest
        of the page: it takes .day-box's border and padding like the headline
        above it, and the two line up because they are the same rule."""
        box = re.search(r"\.day-box\{\{background:#0d1117;"
                        r"border:(\d+)px solid[^}]*?padding:(\d+)px", api.PAGE,
                        re.S)
        self.assertIsNotNone(box)
        self.assertIn("day-box", api.chart_page("", "", ""))

    def test_the_day_chart_keeps_its_box(self):
        """One card among several beside the tonight panel; a borderless one
        would be the odd box out."""
        self.assertNotIn("#day-chart{{border:0", api.PAGE)
        self.assertNotIn("#day-chart>.box-head{{display:none}}", api.PAGE)

    def test_the_box_measures_itself_at_reading_size(self):
        """A ch resolves against the query container's own font, so the size
        has to be pinned on the container itself -- inheritance would leave
        it measuring in whatever the generic pre{} rule last said."""
        joined = api.chart_ladder_css()
        self.assertIn(f"#day-head-ladder{{container-type:inline-size;"
                      f"font-size:{api.DAY_HEAD_PX}px}}", joined)


class TheSummaryLineDropsBlocksWorstFirst(unittest.TestCase):
    """It is one line at every width, so something has to go as the box gets
    narrower. Which thing goes is the decision under test."""

    def _st(self):
        star = {"m": 1.2, "n": "Vega"}
        return {"moon": {"alt": 11.0, "az": 67.0, "age": 7.4, "illum": 0.29},
                "sun": {"alt": -19.0},
                "up": [{"name": "Saturn", "mag": 0.8, "alt": 29.0, "az": 112.0},
                       {"name": "Uranus", "mag": 5.7, "alt": 10.0, "az": 67.0}],
                "visible": [(star, 60.0, 300.0)] * 223}

    def _at(self, width):
        return api._sky_summary(self._st(), 47.38, width,
                                note="Bortle 8 est. (Zürich)")

    def _narrowest_holding(self, text):
        """The tightest width at which `text` is still on the line."""
        return min(w for w in range(20, 220) if text in self._at(w))

    def test_everything_is_there_when_there_is_room(self):
        full = self._at(200)
        for block in ("29%", "Saturn", "full dark", "Bortle 8", "223 stars"):
            self.assertIn(block, full)

    def test_the_star_count_outlives_the_bortle_note(self):
        """Swapped deliberately. The count is how much is up right now and it
        runs from two to four hundred over an evening; the note is the same
        sentence every night from the same place."""
        self.assertLess(self._narrowest_holding("223 stars"),
                        self._narrowest_holding("Bortle 8"))

    def test_the_planets_outlive_both(self):
        self.assertLess(self._narrowest_holding("Saturn"),
                        self._narrowest_holding("223 stars"))

    def test_the_moon_survives_every_trim(self):
        """It decides how much of the rest is worth looking for."""
        self.assertIn("29%", self._at(20))

    def test_the_named_stars_go_before_anything_else(self):
        """Longest block on the line, and the only one whose contents are
        already labelled on the chart a few rows down."""
        st = self._st()
        wide = api._sky_summary(st, 47.38, 400, n_stars=3, note="Bortle 8")
        self.assertIn("Vega", wide)
        # Tight enough to lose one block: it is that one.
        tight = api._sky_summary(st, 47.38, len(wide) - 4, n_stars=3,
                                 note="Bortle 8")
        self.assertNotIn("Vega", tight)
        self.assertIn("223 stars", tight)


class TheHeaderNamesOnlyWhatTheChartCannotSay(unittest.TestCase):
    """"horizon panorama, 0-70°" described the default view, and the default
    is already labelled by the drawing: the axis runs 0-70 down the left edge
    and the inset is captioned in its corner. Worst of all when something
    joined it -- zooming into one twelfth of the sky read "horizon panorama,
    0-70°, quadrant K", a panorama being the one thing that view is not."""

    def _head(self, **kw):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 8, 2, 0),
                        width=220, **kw)
        # First non-blank: the render opens with a blank line.
        return next(l for l in api.strip_ansi(api.compose(r).text).splitlines()
                    if l.strip())

    def test_the_plain_view_says_nothing_about_being_a_panorama(self):
        self.assertNotIn("horizon panorama", self._head())
        self.assertNotIn("0-70", self._head())

    def test_a_quadrant_crop_names_only_the_quadrant(self):
        head = self._head(quadrant="K")
        self.assertIn("quadrant K", head)
        self.assertNotIn("panorama", head)

    def test_a_facing_window_keeps_its_description(self):
        """Which way it points and how wide it is cannot be read off the
        drawing, so that one stays."""
        head = self._head(facing="N", span=90)
        self.assertIn("facing N", head)
        self.assertIn("true shape", head)
        self.assertNotIn("panorama", head)

    def test_the_export_and_the_animation_dropped_it_too(self):
        """Both built their own copy of this line, so both had to be changed:
        a PNG someone shares and a frame mid-animation are views like any
        other. Checked on the rendered text rather than the source, which
        would only be matching the comment that explains the change."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 8, 2, 0),
                        width=220)
        self.assertNotIn("horizon panorama",
                         api.strip_ansi(api.compose_chart_only(r)))
        body, _sun_alt = api.compose_frame(r)
        self.assertNotIn("horizon panorama", api.strip_ansi(body))


class TheTonightPanelIsAboutTonight(unittest.TestCase):
    """It is headed TONIGHT, so everything in it has to be tonight. It used
    to draw from the next fortnight, which put "Perseids peak, Wed 12 Aug"
    in front of a reader on the 8th -- and put it there twice, because the
    upcoming-events list under the arc was already carrying that row."""

    def _slides(self, when):
        r = api.Request(place="Zurich", when=when, width=220, panel=True)
        return r, api.day_panel_slides(r, api.compose(r).data)

    def test_an_event_days_away_is_not_in_it(self):
        """8 Aug 2026: the Perseids peak on the 12th and Venus reaches
        greatest elongation on the 14th. Neither is tonight.

        The Perseids themselves are, though -- they run from 17 July to 24
        August -- so what must not appear is the *peak*, dated four nights
        out, not the shower."""
        _r, slides = self._slides(dt.datetime(2026, 8, 8, 14, 0))
        caps = " ".join(c for _l, c, _u in slides)
        self.assertNotIn("Perseids peak", caps)
        self.assertNotIn("12 Aug", caps)
        self.assertNotIn("greatest elongation", caps)

    def test_a_shower_running_tonight_is_in_it(self):
        """The other half of the rule above, and the reason it changed."""
        _r, slides = self._slides(dt.datetime(2026, 8, 8, 14, 0))
        caps = " ".join(c for _l, c, _u in slides)
        self.assertIn("Perseids ongoing", caps)

    def test_tonights_event_is_in_it(self):
        """The same shower, viewed on the night it actually peaks."""
        _r, slides = self._slides(dt.datetime(2026, 8, 12, 14, 0))
        self.assertIn("Perseids", " ".join(c for _l, c, _u in slides))

    def test_the_small_hours_belong_to_the_evening_before(self):
        """A conjunction at 02:11 on the 12th is something you go outside for
        on the evening of the 11th, and it is filed under that night."""
        _r, slides = self._slides(dt.datetime(2026, 8, 11, 14, 0))
        self.assertIn("Mercury", " ".join(c for _l, c, _u in slides))

    def test_a_quiet_night_still_has_something_to_draw(self):
        """It falls through to the planets that are up and then to the
        brightest star, so the box never comes out empty."""
        for when in (dt.datetime(2026, 8, 8, 14, 0),
                     dt.datetime(2026, 8, 20, 14, 0),
                     dt.datetime(2026, 9, 15, 14, 0)):
            _r, slides = self._slides(when)
            self.assertTrue(slides, when)
            for lines, _c, _u in slides:
                self.assertTrue(lines)

    def test_every_slide_is_tonight(self):
        """The property, over a run of dates rather than the handful picked
        above.

        Tonight's evening or the morning after it, because those are one
        night: a caption reads "Wed 12 Aug" for a conjunction at 02:11 that
        a reader goes out for on the evening of the 11th. Anything two days
        out is the bug this is here to catch."""
        for day in range(1, 29):
            when = dt.datetime(2026, 8, day, 14, 0)
            r, slides = self._slides(when)
            night = api._night_of(r.when_local)
            ok = {f"{night:%a %d %b}",
                  f"{night + dt.timedelta(days=1):%a %d %b}"}
            for _lines, cap, _u in slides:
                if " · " not in cap or cap.endswith("up tonight"):
                    continue
                self.assertTrue(any(d in cap for d in ok), (day, cap, ok))


class TheEclipseCountdownBox(unittest.TestCase):
    """A solar eclipse is the one thing on this list that happens in
    daylight, so it is the one thing a reader of a daylight page could walk
    outside and watch. It gets the top of the panel for the week before."""

    def _box(self, place, when):
        return api.day_eclipse_html(api.Request(place=place, when=when,
                                                width=300, panel=True))

    def test_it_appears_in_the_week_before(self):
        """12 Aug 2026 is total across Spain and deeply partial from Zurich."""
        html = self._box("Zurich", dt.datetime(2026, 8, 7, 12, 0))
        self.assertIn('id="day-eclipse"', html)
        self.assertIn("in 5 days", html)
        self.assertIn("/Zurich/eclipse/2026-08-12", html)

    def test_the_title_counts_down(self):
        for day, want in ((5, "in 7 days"), (11, "tomorrow"), (12, "today")):
            html = self._box("Zurich", dt.datetime(2026, 8, day, 12, 0))
            self.assertIn(want, html, f"12 Aug seen from {day} Aug")

    def test_the_clock_is_the_local_maximum_and_not_a_shifted_global_one(self):
        """An event's when_local is the *global* greatest-eclipse instant
        shifted by the timezone offset -- a local-looking rendering of
        somebody else's moment. For Zurich on 12 Aug 2026 it reads 19:47
        against a real local maximum of 20:17. Half an hour, on the one kind
        of event where half an hour decides whether you see it."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 12, 0),
                        width=300, panel=True)
        want = api.eclipse_page.facts(api.eclipse_page.by_key("2026-08-12"),
                                      r.place, r.when_utc)["maximum"]
        self.assertIn(f"at {want}", api.day_eclipse_html(r))
        # And it is the same clock the eclipse's own page prints, which is
        # the point: two pages about one moment cannot disagree about when.
        self.assertEqual(want, "20:17")

    def test_a_lunar_eclipse_gets_the_box_too(self):
        """Solar alone put this on screen about twice a year. With lunar in
        it, the box turns up often enough to be a thing readers look for."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 21, 12, 0),
                        width=300, panel=True)
        html = api.day_eclipse_html(r)
        self.assertIn('id="day-eclipse"', html)
        self.assertIn("28 Aug", html)
        # Drawn as the Moon in the shadow, not as a bitten Sun.
        self.assertIn('class="dt-art"', html)

    def test_it_is_absent_the_rest_of_the_year(self):
        """Eight days out is one day too far. If this box were always there
        it would be furniture, and furniture stops being read."""
        self.assertEqual(self._box("Zurich", dt.datetime(2026, 8, 4, 12, 0)), "")
        self.assertEqual(self._box("Zurich", dt.datetime(2026, 3, 1, 12, 0)), "")

    def test_the_disc_is_drawn_for_here_and_not_in_general(self):
        """The whole content of a partial eclipse is how much of the Sun
        this place loses, so the drawing is the local one."""
        html = self._box("Zurich", dt.datetime(2026, 8, 10, 12, 0))
        self.assertIn('class="dt-art"', html)

    def test_a_place_the_shadow_misses_gets_no_box(self):
        """Sydney sees nothing of the 12 Aug 2026 eclipse. Counting down to
        an eclipse that never rises there would be a straight lie."""
        self.assertEqual(self._box("Sydney", dt.datetime(2026, 8, 10, 12, 0)), "")


class TheTonightPanelDraws(unittest.TestCase):
    """A drawing above the numbers: the best thing coming, then a planet
    that will be up, then the brightest star that will be. Each step down is
    a step further from "worth setting an alarm for", and the last one always
    has an answer."""

    def _req(self, place, when):
        return api.Request(place=place, when=when, width=300, panel=True)

    def test_the_event_it_picks_is_the_one_the_site_ranks_first(self):
        """Through ev_mod.next_events, the same ranking the coming-up strip
        uses, so the picture and the strip above it cannot point at
        different things.

        Viewed on the 12th, the night the shower peaks. It used to be viewed
        on the 7th and still expected the Perseids, because the panel drew
        from the next fortnight -- which is the thing that put an event five
        days out under a heading reading TONIGHT."""
        r = self._req("Zurich", dt.datetime(2026, 8, 12, 12, 0))
        picture = api.day_panel_art(r, api._compose_day(r).data)
        self.assertIsNotNone(picture)
        _lines, caption, url = picture
        self.assertIn("Perseids", caption)
        self.assertIn("/Zurich/Perseids", url)

    def test_the_same_shower_five_days_out_is_not_drawn_as_a_peak(self):
        """The other half of the rule above, and the reason it changed.

        The Perseids are running on 7 August, so the deck may well draw them
        -- as running. What it must not do is offer the peak, which is five
        nights away and belongs to the list under the arc."""
        r = self._req("Zurich", dt.datetime(2026, 8, 7, 12, 0))
        picture = api.day_panel_art(r, api._compose_day(r).data)
        self.assertIsNotNone(picture)          # never empty
        _lines, caption, _url = picture
        self.assertNotIn("peak", caption)
        self.assertNotIn("12 Aug", caption)

    def test_a_quiet_fortnight_falls_through_to_a_planet(self):
        r = self._req("Zurich", dt.datetime(2026, 3, 1, 12, 0))
        data = api._compose_day(r).data
        picture = api.day_panel_art(r, data)
        self.assertIsNotNone(picture)
        _lines, caption, _url = picture
        if data["visible_tonight"]:
            self.assertIn("up tonight", caption)

    def test_the_last_resort_finds_a_star_and_it_is_the_right_one(self):
        """Tested directly because no real page reaches it: something is
        always coming up or a planet is always out. It is the branch that
        guarantees the panel is never empty, so it is worth knowing it works
        rather than assuming."""
        for place, when, want in (("Zurich", dt.datetime(2026, 1, 15, 22, 0), "Sirius"),
                                  ("Sydney", dt.datetime(2026, 6, 15, 20, 0), "Canopus")):
            r = self._req(place, when)
            star = api._brightest_star_tonight(r, when)
            self.assertIsNotNone(star, place)
            self.assertEqual(star["n"], want)
            sp = objects.star_info(star["hr"]).get("sp")
            self.assertTrue(art.star_art_for(sp), f"{want} draws nothing")

    def test_a_place_with_no_night_draws_nothing_rather_than_pretending(self):
        """Reykjavik in midsummer has no first stars at all. There is no
        tonight to illustrate, and a picture there would be decoration."""
        r = self._req("Reykjavik", dt.datetime(2026, 6, 21, 12, 0))
        data = api._compose_day(r).data
        self.assertIsNone(data["first_stars"])
        self.assertIsNone(api.day_panel_art(r, data))

    def test_a_new_moon_draws_nothing_and_the_next_thing_gets_the_slot(self):
        """Drawn honestly a new Moon is a black disc: correct, and useless in
        a panel whose job is to give somebody a reason to go outside."""
        self.assertEqual(api._moon_art_for(0.0, False), [])
        self.assertTrue(api._moon_art_for(0.55, True))

    def test_the_countdown_words(self):
        self.assertEqual(api._countdown(0), "today")
        self.assertEqual(api._countdown(1), "tomorrow")
        self.assertEqual(api._countdown(6), "in 6 days")

    def test_days_are_counted_by_date_and_not_by_hours(self):
        """An eclipse at 09:00 tomorrow is tomorrow's eclipse even though it
        is fifteen hours away. Counting elapsed hours would call it today at
        six this evening and send somebody out on the wrong morning."""
        now = dt.datetime(2026, 8, 7, 18, 0)
        self.assertEqual(api._days_until(dt.datetime(2026, 8, 8, 9, 0), now), 1)
        self.assertEqual(api._days_until(dt.datetime(2026, 8, 7, 23, 30), now), 0)

    def test_the_drawing_is_centred_in_a_box_of_fixed_height(self):
        """Blank rows come off and then go back on evenly. Trimming is what
        stops five dead rows between a picture and its caption; padding is
        what stops the box changing height from one town to the next, which
        it did -- the same eclipse is 12 rows from Zurich and 15 from
        Madrid, because the disc is drawn where the Sun is."""
        block = api._art_block(["", "  ", " x ", "", "  "], "cap", "/somewhere")
        drawn = block.split('aria-hidden="true">')[1].split("</pre>")[0]
        self.assertEqual(len(drawn.split("\n")), api.DAY_ART_ROWS)
        self.assertEqual(drawn.strip(), "x")
        # Centred, not hanging from the top.
        rows = drawn.split("\n")
        above = next(i for i, l in enumerate(rows) if l.strip())
        self.assertEqual(above, len(rows) - 1 - above)

    def test_every_drawing_the_panel_can_show_fits_that_box(self):
        """9 rows for a bright star, 15 for a shower, 17 for a planet. The
        box is the tallest of them, so nothing is ever cropped."""
        import eclipse as eclipse_map
        drawings = [art.planet_art("Saturn", illuminated=0.76),
                    art.planet_art("Moon", illuminated=1.0),
                    art.shower_art("Perseids"),
                    art.star_art_for("A1Vm"),
                    eclipse_map.disc_art("2026-08-12", 47.38, 8.54),
                    eclipse_map.disc_art("2026-08-12", 40.42, -3.70)]
        for lines in drawings:
            block = api._art_block(lines, "cap", "")
            drawn = block.split('aria-hidden="true">')[1].split("</pre>")[0]
            self.assertEqual(len(drawn.split("\n")), api.DAY_ART_ROWS)

    def test_the_caption_is_escaped(self):
        block = api._art_block(["x"], "<script>", "/a&b")
        self.assertNotIn("<script>", block)
        self.assertIn("&amp;b", block)

    def test_no_url_leaves_it_unlinked_rather_than_linked_to_nothing(self):
        block = api._art_block(["x"], "cap", "")
        self.assertNotIn("<a ", block)
        self.assertIn("dt-art-box", block)
