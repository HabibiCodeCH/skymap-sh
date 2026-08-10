#!/usr/bin/env python3
"""Tests for the nearest-city timezone fallback in api.py.

Run:  python3 test_api.py
"""
import datetime as dt
import os
import json
import math
import re
import subprocess
import tempfile
import unittest
import api
import art
import objects
import sky


# Running the page's own script, rather than reading it and believing what
# it looks like. Several things the server does on the way out have to be
# done a second time in the browser -- a still chart is turned into HTML by
# Python and an animation frame by the page -- and the only way to know the
# two agree is to run the second one.
def _have_node():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _page_script():
    """The biggest inline script in PAGE, as the browser receives it. The
    template doubles its braces for .format(); the browser never sees that."""
    body = max(re.findall(r"<script[^>]*>(.*?)</script>", api.PAGE, re.S),
               key=len)
    return body.replace("{{", "{").replace("}}", "}")


def _grab_fn(src, name):
    """One named function out of the script, braces balanced."""
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"unbalanced: {name}")


def _run_page_js(names, entry, arg, setup=""):
    """Call `entry(arg)` in node with `names` lifted out of the page script.

    The argument goes through a file: it is a rendered chart frame, full of
    escape sequences and layout markers, and putting that on a command line
    or through a shell would prove nothing about what a browser does.

    `setup` is JavaScript run first, for the handful of functions that reach
    for the document -- a stub is enough, and it keeps the test about what
    the function computes rather than about a browser."""
    defs = "\n".join(_grab_fn(_page_script(), n) for n in names)
    with tempfile.TemporaryDirectory() as tmp:
        arg_path = os.path.join(tmp, "arg.txt")
        with open(arg_path, "w") as fh:
            fh.write(arg)
        run_path = os.path.join(tmp, "run.js")
        with open(run_path, "w") as fh:
            fh.write(f"{setup}\n{defs}\nconst fs=require('fs');\n"
                     f"process.stdout.write(String({entry}("
                     f"fs.readFileSync({json.dumps(arg_path)},'utf8'))));\n")
        got = subprocess.run(["node", run_path], capture_output=True, text=True)
        assert got.returncode == 0, got.stderr[:600]
        return got.stdout


def _drive_page_js(names, script):
    """Run `script` in node with `names` lifted out of the page script.

    For the behaviour that only shows up in a sequence -- pause, then three
    arrows, then the replies landing -- where checking the source proves
    nothing and only running it does."""
    defs = "\n".join(_grab_fn(_page_script(), n) for n in names)
    with tempfile.TemporaryDirectory() as tmp:
        run_path = os.path.join(tmp, "run.js")
        with open(run_path, "w") as fh:
            fh.write(defs + "\n" + script)
        got = subprocess.run(["node", run_path], capture_output=True, text=True)
        assert got.returncode == 0, got.stderr[:800]
        return got.stdout


# A page with an animate button and a chart that has picked a ladder rung.
# Enough for the stepping helpers, which read the moment, the step and the
# width off exactly those two elements.
_STEP_DOM = """
var _btn={attrs:{"data-live-url":"/Zurich?animate=24&t=2026-08-19T21:20&ui=1",
                 "data-step-min":"10"},
          getAttribute:function(k){return this.attrs[k];}};
var document={getElementById:function(id){
  return id==='animate-btn'?_btn:null;}};
var window={skymapChartPre:function(){
  return {getAttribute:function(k){return k==='data-cols'?'300':null;}};}};
"""


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
        # An afternoon moment: tonight's times only join the line once the
        # Sun is past its high point (see _head_day_blocks), and the
        # solstice noon this class uses elsewhere is before it.
        #
        # Given the room to say it. This is about the words the block uses,
        # not about whether the block is on the line -- and the line is
        # budgeted now (see DAY_HEAD_RANKS), so at the 110-column default
        # the darkness block is dropped before the first-stars one and the
        # sentence is legitimately absent. It used to survive there only
        # because the day line was trimmed against the chart's column count
        # while being set half again as wide, so every line overran its box.
        r = api.Request(place="London", when=dt.datetime(2026, 6, 21, 15, 0),
                        color=False, panel=True, width=140)
        text = api.compose(r).text
        self.assertIn("no full dark", text)
        self.assertNotIn("dark --", text)

    def test_the_blank_time_never_appears_at_any_width(self):
        """The half of the above that must hold whatever the budget does:
        the block is allowed to be trimmed away, and never allowed to render
        its missing time as "--"."""
        for w in (80, 110, 140, 200, 300):
            r = api.Request(place="London", when=dt.datetime(2026, 6, 21, 15, 0),
                            color=False, panel=True, width=w)
            self.assertNotIn("dark --", api.compose(r).text, w)

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
        """The tilde is what says "estimate" now. It used to be "est.", plus
        the nearest city in brackets -- sixteen characters of hedging and
        geography on the one line where every block is competing for room."""
        note = api.sky_note(-24.63, -70.40)
        self.assertRegex(note, r"^Bortle ~\d$")

    def test_the_note_does_not_name_a_town_on_this_line(self):
        """The reader's own place is already the first thing on the line.
        The prose under the chart still names the city when it is why the
        Milky Way is missing, which is where that answer belongs."""
        self.assertNotIn("Geneva", api.sky_note(46.20, 6.15))
        self.assertNotIn("(", api.sky_note(46.20, 6.15))

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
        # strip_ansi and not gif.ANSI: the page's copy carries the browser's
        # link markers too (the moment is clickable there, the PNG's is not),
        # and comparing the two means comparing what a reader sees. Stripping
        # colour alone left the href in the text as "#explore05 Aug 03:00".
        return " ".join(api.strip_ansi(text).split("\n")[n].split())

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
        # Gone midnight: the Bortle note waits for full dark, and 22:25 in
        # August is still astronomical twilight.
        r = api.Request(place="Geneva", when=dt.datetime(2026, 8, 6, 1, 0),
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




class TheModalFramesAreDrawnRound(unittest.TestCase):
    """A disc is drawn for a character cell art.CELL times as tall as it is
    wide. Get the line height wrong and every planet is an ellipse."""

    def _art_rows(self, block):
        """The drawing's own lines, out of the block's HTML."""
        pre = re.search(r"<pre[^>]*>(.*?)</pre>", block, re.S).group(1)
        return [l for l in re.sub(r"<[^>]+>", "", pre).split("\n") if l.strip()]

    def _rule(self, sel):
        m = re.search(re.escape(sel) + r"\{\{([^}]*)\}\}", api.PAGE)
        self.assertIsNotNone(m, sel)
        return m.group(1)

    def test_the_line_height_matches_the_cell_the_art_is_drawn_for(self):
        """0.6em per character across, art.CELL cells tall for one across, so
        1.2em down. It was 1.15, which measured 1.91:1 in Chromium against a
        target of 2.0 -- a 5% squash, invisible as a number and obvious on
        Saturn. One rule, on .mf-art: a quad cell is a frame like any other
        and takes the same drawing at the same shape."""
        # One rule for every drawing on the site, shared with the object
        # pages: .art-plate. The modal's own rule carries nothing but a size.
        self.assertIn("line-height:1.2em", self._rule(" .art-plate"))
        self.assertNotIn("line-height", self._rule(" .mf-art"))
        self.assertNotIn("line-height", self._rule(" .mf-cell .mf-art"))
        # And the object pages take it from the same place rather than
        # keeping a second copy that can drift.
        self.assertNotIn("line-height", api.OBJECT_CSS.split(".obj-art{")[1]
                         .split("}")[0])

    def test_the_type_is_sized_from_the_frame_and_not_from_a_number(self):
        """cqw, so one rule fits the big frame and a quad cell alike. The
        drawing's own column count goes on the element, because only there is
        it known -- and the second term caps the height, so a narrow drawing
        like Neptune grows to fill its box rather than past it."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 24, 23, 0),
                        width=300, panel=True)
        lines = art.planet_art("Neptune", illuminated=art.STYLE_ILLUMINATED,
                               **api._pole_kw("Neptune", r.when_utc))
        block = api._art_block(lines, "Neptune", "/x", cls="mf-art",
                               rows=api.MODAL_ART_ROWS)
        m = re.search(r"font-size:min\(([\d.]+)cqw,([\d.]+)cqw\)", block)
        self.assertIsNotNone(m, block[:200])
        wide, tall = float(m.group(1)), float(m.group(2))
        # Neptune is a bare disc on a 45-column canvas, so the blank margins
        # come off and width stops being what limits it.
        self.assertGreater(wide, tall)
        self.assertIn("container-type:inline-size", self._rule(" .mf-frame"))

    def test_the_blank_margins_come_off_evenly_or_not_at_all(self):
        """Trimmed by the smaller of the two margins, so a drawing that is
        not centred on its canvas keeps whatever offset it had. Take the
        blanks off each side independently and a disc slides sideways."""
        # 8 blank columns on the narrowest left margin, 4 on the right.
        canvas = ["          ####      ",
                  "        ########    ",
                  "          ####      "]
        rows = self._art_rows(api._art_block(canvas, "x", "", cls="mf-art",
                                             rows=3))
        self.assertEqual(len(rows), 3)
        # 4 came off each side -- the smaller margin -- not 8 and 4.
        self.assertEqual([len(l) - len(l.lstrip(" ")) for l in rows], [6, 4, 6])

    def test_a_drawing_that_fills_its_canvas_loses_nothing(self):
        """Saturn's rings run the full width, so there is no margin to take
        and the trim has to leave it exactly as it arrived."""
        canvas = ["==########==", "############", "==########=="]
        self.assertEqual(self._art_rows(
            api._art_block(canvas, "x", "", cls="mf-art", rows=3)), canvas)

    def test_the_caption_box_is_the_size_of_its_own_text(self):
        """.dt-cap reserves two lines, because the deck it was written for
        turned its caption over every seven seconds and a one-line slide
        beside a two-line one changed the box's height. These frames take
        their height from the grid, so the reservation bought nothing and
        left a line and a half of empty box under every caption -- the text
        was on the floor of its box and the box was not on the floor of the
        frame."""
        self.assertIn("min-height:0", self._rule(" .mf-frame .dt-cap"))
        # The base rule still reserves them -- this is an override, not a
        # deletion, so anything else that ever uses .dt-cap keeps what it had.
        self.assertIn("min-height:2.7em", api.PAGE)

    def test_nothing_is_padded_out_to_a_row_count(self):
        """The blank rows go inside the <pre>, and the <pre> is what gets
        centred -- so padding a 13-row drawing out to 14 sat it half a row
        high and ran its bottom row into the caption. The frames keep their
        matching height from the grid they are in, not from the row count."""
        self.assertEqual(api.MODAL_ART_ROWS, 0)
        canvas = ["", "  ####  ", "  ####  ", ""]
        rows = self._art_rows(api._art_block(canvas, "x", "", cls="mf-art",
                                             rows=api.MODAL_ART_ROWS))
        self.assertEqual(len(rows), 2)

    def test_the_height_cap_counts_the_rows_there_actually_are(self):
        """Two drawings of different depths both fill their frame, rather
        than a short one being held down to the space a tall one needs."""
        short = api._art_block(["  ####  ", "  ####  "], "x", "",
                               cls="mf-art", rows=0)
        tall = api._art_block(["  ####  "] * 8, "x", "", cls="mf-art", rows=0)
        get = lambda b: float(re.search(r"min\([\d.]+cqw,([\d.]+)cqw\)",
                                        b).group(1))
        self.assertGreater(get(short), get(tall))

    def test_the_drawing_is_centred_in_what_is_left(self):
        """Its own growing box, so the caption's margin-top:auto cannot take
        the slack and pin the picture to the ceiling."""
        # The centring is the shared frame's; .art-fill only adds the growing.
        frame = self._rule(" .art-frame")
        self.assertIn("align-items:center", frame)
        self.assertIn("justify-content:center", frame)
        self.assertIn("flex:1 1 auto", self._rule(" .art-fill"))
        # Never on the <pre> itself: ansi_to_html fills it with colour spans
        # and flex would make a row of every one of them.
        self.assertNotIn("flex", self._rule(" .art-plate"))
        # And never text-align, which centres each line by its own width.
        self.assertNotIn("text-align", self._rule(" .art-plate"))

    def test_the_caption_sits_on_the_floor_of_the_frame(self):
        """margin-top:auto puts it there, and .dt-art-box's own 12px bottom
        margin -- left over from the stack it used to live in -- lifted it
        back off. Measured 23px of gap where the frame's padding is 10."""
        rule = self._rule(" .mf-frame>.dt-art-box")
        self.assertIn("margin-bottom:0", rule)
        self.assertIn("margin-top:auto", self._rule(" .mf-frame .dt-cap"))


class TheZenithLabelsCanBeClicked(unittest.TestCase):
    """They were anchors already. The box they float in took the mouse."""

    def test_the_inset_lets_its_own_links_be_reached(self):
        """#chart-zenith is pointer-events:none on purpose -- it sits over the
        panorama's top rows and would swallow clicks meant for the labels
        under it -- but that applies to its children too, so the names in it
        were links no cursor could reach."""
        css = "".join(api.chart_ladder_css())
        self.assertIn("#chart-zenith a{pointer-events:auto}", css)
        self.assertIn("pointer-events:none", css)


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
        # And the peak still arrives with its rate on it. That is what the
        # span cannot carry -- a shower is running for five weeks and does
        # not have a rate for most of them -- so it is also how you tell
        # from the rendered line which of the two you are looking at.
        self.assertTrue(any("/hr" in api._event_line(e, r) for e in showers))



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

    def _day_line(self, hour):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, hour, 0),
                        width=300, panel=True)
        return api.strip_ansi(api._compose_day(r).text.split("\n")[1])

    def test_where_the_sun_is_now_leads_the_line(self):
        """Straight after the moment, morning and afternoon alike, and ahead
        of the day's own turning points. It used to sit in time order between
        sunrise and sunset, which moved it past the high point at lunchtime
        -- a block that moves is a block the eye has to find again, and this
        is the one block that also has to survive the crossing into night
        (see the night summary, which now carries it in the same place)."""
        for hour in (10, 17):
            got = self._day_line(hour)
            self.assertRegex(got, r"^\s*Z\u00fcrich \u00b7 \d\d \w\w\w \d\d:\d\d \u00b7 \u2600 ")

    def test_the_morning_has_lost_the_sunrise_and_kept_the_rest(self):
        """A block is on the line while what it names is still ahead. At
        10:00 the sunrise has happened and everything else has not."""
        got = self._day_line(10)
        self.assertNotIn("\u2191", got)
        self.assertRegex(got, r"\^\d\d:\d\d")
        self.assertRegex(got, r"\u2193\d\d:\d\d")
        self.assertIn("darkest ", got)

    def test_the_afternoon_drops_the_high_point_and_nothing_else(self):
        """One block changes at the high point, not the whole line."""
        got = self._day_line(17)
        self.assertNotIn("^", got)
        self.assertRegex(got, r"\u2193\d\d:\d\d [NESW]+")
        self.assertIn("stars ", got)
        self.assertIn("darkest ", got)

    def test_the_high_point_has_the_same_shape_as_the_arrows(self):
        """Mark, time, bearing -- the same three pieces as sunrise and
        sunset. It used to be "high 55 deg at 13:30", so the Sun's three
        moments read as two facts of one kind and one of another. The
        altitude it carried is still in the payload and still on the chart,
        which draws the arc it is the top of."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 10, 0),
                        width=300, panel=True)
        got = api.strip_ansi(api._compose_day(r).text.split("\n")[1])
        self.assertRegex(got, r"\^\d\d:\d\d [NESW]+")
        self.assertNotIn("high ", got)
        self.assertNotIn(" at ", got)

    def test_the_bearings_are_on_the_line(self):
        """The one fact here you cannot work out from the others. "Sunset
        20:30" says when; "20:30 WNW" says which window to stand at. Checked
        on the afternoon and the pre-dawn line, which is where each of the
        two arrows lives."""
        self.assertRegex(self._day_line(17), r"\u2193\d\d:\d\d [NESW]+")
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 5, 30),
                        width=300, panel=True)
        dawn = api.strip_ansi(api.compose(r).text)
        self.assertRegex(dawn, r"\u2191\d\d:\d\d [NESW]+")

    def test_a_degree_on_this_line_is_always_a_height(self):
        """One shape, one meaning, across both views. Every degree sign in
        the app is an altitude -- the Moon's, a planet's, a named star's, the
        Sun's own position -- and the rise/peak/set bearing was the single
        exception, a direction wearing the same look on the same line. A
        degree sign run straight into compass letters is the glued form that
        reads as a bearing, so it must not appear anywhere."""
        for hour in (5, 10, 17, 21):
            r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, hour, 0),
                            width=300, panel=True)
            got = api.strip_ansi(api.compose(r).text.split("\n")[1])
            self.assertNotRegex(got, r"\d\u00b0[NESW]", f"{hour}:00 -> {got}")
            for mark in ("\u2191", "\u2193", "^"):
                self.assertNotRegex(got, mark + r"\d\d:\d\d \d+\u00b0")

    def test_the_place_and_the_moment_arrive_as_their_own_span(self):
        """Which is the only way to bold part of a line that reaches the
        page as pre-rendered ANSI -- CSS needs an element to hold."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 7, 10, 0),
                        width=300, panel=True)
        raw = api._compose_day(r).text.split("\n")[1]
        head, _rungs = api.lift_chart_head([(220, True, api.ansi_to_html(raw))])
        self.assertIn('<span class="dh"><span style="color:', head)
        # Four, not two: the Sun's glyph is a colour run of its own inside
        # the second, which splits it (see paint_sun_glyph). The first span
        # is still where you are and when, which is the one CSS bolds.
        self.assertEqual(head.count("<span style="), 4)

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


class TheSunKeepsItsPlaceAfterItSets(unittest.TestCase):
    """The night line used to have no Sun in it at all, so at sunset every
    block was replaced at once -- one frame of an animation, at the moment
    somebody is most likely watching. It keeps its place down to the end of
    astronomical twilight, which is where "twilight" stops being said."""

    def _st(self, sun_alt, sun_az=290.0):
        return {"moon": {"alt": 11.0, "az": 67.0, "age": 7.4, "illum": 0.29},
                "sun": {"alt": sun_alt, "az": sun_az},
                "up": [], "visible": []}

    def _line(self, sun_alt):
        return api._sky_summary(self._st(sun_alt), 47.38, 200)

    def test_it_is_there_all_the_way_through_civil_twilight(self):
        for alt in (-0.5, -3.0, -5.9):
            self.assertIn("☀", self._line(alt), alt)

    def test_it_hands_over_where_the_page_says_stars(self):
        """CIVIL_ALT is the same threshold the day line calls "stars". Past
        it the Sun is no longer what somebody is watching, and the night
        line says everything worth saying."""
        self.assertNotIn("☀", self._line(api.CIVIL_ALT))
        self.assertNotIn("☀", self._line(-12.0))
        self.assertNotIn("☀", self._line(-30.0))

    def test_a_daylight_frame_carries_it_too(self):
        """This summary builds the header for animation frames, which run
        through the whole day. A frame at noon with no Sun on its line
        would be the same hole the night line used to have, at the other
        end. The day page composes its own line and never calls this."""
        self.assertIn("☀ 10° up", self._line(10.0))

    def test_it_leads_the_line(self):
        """Same place as on the day line: straight after the moment, ahead
        of the Moon. The whole point is that it does not move when the Sun
        crosses the horizon."""
        line = self._line(-3.0)
        self.assertLess(line.index("☀"), line.index("29%"))

    def test_the_depth_is_a_number_not_just_the_word_below(self):
        """It is what the reader is waiting on between sunset and full dark.
        The Moon says only "below the horizon" because its depth changes
        nothing. The sign is a word, not a minus: "-3° up" is a
        contradiction, and a minus is easy to lose in a line of numbers."""
        self.assertIn("☀ 3° down WNW", self._line(-3.0))
        self.assertNotIn("-3", self._line(-3.0))

    def test_a_sun_just_under_the_horizon_does_not_say_minus_zero(self):
        """Rounding happens before the sign is chosen, so -0.4 comes out as
        "0° up" rather than "-0° below"."""
        self.assertIn("☀ 0° up WNW", self._line(-0.4))

    def test_the_moon_still_outlives_it_on_the_narrowest_line(self):
        """Both are rank 0 and the Moon is what decides whether the rest of
        the night is worth going out for."""
        narrow = api._sky_summary(self._st(-3.0), 47.38, 20)
        self.assertIn("29%", narrow)
        self.assertNotIn("☀", narrow)


class TheLineCarriesOnlyWhatIsStillAhead(unittest.TestCase):
    """One or two blocks change at each boundary of the day, never the whole
    line. That is what lets an animation cross sunrise and sunset without
    the headline being swapped out from under the reader."""

    P = api.Place("T", 47.38, 8.54)
    OFF = 2.0
    EV = dict(sunrise=dt.datetime(2026, 8, 19, 4, 27),
              dawn_astro=dt.datetime(2026, 8, 19, 2, 27),
              transit=dt.datetime(2026, 8, 19, 11, 30),
              sunset=dt.datetime(2026, 8, 19, 18, 30),
              dusk_civil=dt.datetime(2026, 8, 19, 19, 3),
              dusk_astro=dt.datetime(2026, 8, 19, 20, 30),
              polar_day=False)

    def _at(self, hour, minute, sun_alt):
        return [t for _rank, t, _w in api._head_day_blocks(
            self.EV, self.P, self.OFF,
            dt.datetime(2026, 8, 19, hour, minute), sun_alt)]

    def _marks(self, hour, minute, sun_alt):
        """The blocks by their opening mark. The sunset carries a ☀ of its
        own (a bare down arrow beside a list of planets has no subject), so
        it is stripped here to leave the mark that says which moment."""
        return [t.lstrip("☀")[0] for t in self._at(hour, minute, sun_alt)]

    def test_the_deep_night_carries_none_of_it(self):
        """Before astronomical dawn the night line owns the line, the same
        way it does after civil dusk. A sunrise five hours off is not what
        somebody under a dark sky is reading for -- and the high point of a
        day that has not started is worse."""
        self.assertEqual(self._at(1, 0, -25.0), [])

    def test_from_astronomical_dawn_the_sunrise_appears(self):
        """The high point is still a fact about a day that has not
        started, so it waits."""
        got = self._at(3, 0, -10.0)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("↑"), got)

    def test_at_civil_dawn_the_whole_day_arrives_at_once(self):
        """The one boundary where more than two blocks move, and it is the
        right one: this is where the day starts being a day."""
        self.assertEqual(self._marks(4, 0, -3.0), ["↑", "^", "↓", "s", "d"])

    def test_after_sunrise_only_the_sunrise_goes(self):
        self.assertEqual(self._marks(8, 0, 20.0), ["^", "↓", "s", "d"])

    def test_after_the_high_point_the_sunset_and_tonight_arrive(self):
        got = self._at(14, 0, 30.0)
        self.assertEqual(self._marks(14, 0, 30.0)[0], "↓")
        self.assertTrue(any(t.startswith("stars ") for t in got), got)
        self.assertTrue(any(t.startswith("darkest ") for t in got), got)

    def test_after_sunset_the_sunset_goes_and_tonight_stays(self):
        """The one boundary the whole rework is for. Before it: Sun, Moon,
        planets, sunset, stars, darkest. After it the sunset drops and
        nothing else on the line moves."""
        got = self._at(18, 45, -3.0)
        self.assertNotIn("↓", "".join(got))
        self.assertTrue(any(t.startswith("stars ") for t in got), got)
        self.assertTrue(any(t.startswith("darkest ") for t in got), got)

    def test_past_civil_dusk_only_the_time_the_stars_arrive(self):
        """An hour and a half of nautical and astronomical twilight used to
        carry neither a time to wait for nor a count to read: "darkest" had
        dropped at civil dusk and the star count waits for full dark."""
        self.assertEqual(self._at(19, 30, -8.0), ["darkest 22:30"])

    def test_at_full_dark_even_that_goes(self):
        """The count takes over, which is the better answer once it is
        true."""
        self.assertEqual(self._at(23, 0, -25.0), [])

    def test_a_polar_day_says_so_instead_of_a_sunset(self):
        ev = dict(self.EV, polar_day=True, sunset=None, dusk_civil=None,
                  dusk_astro=None)
        got = [t for _r, t, _w in api._head_day_blocks(
            ev, self.P, self.OFF, dt.datetime(2026, 8, 19, 14, 0), 30.0)]
        self.assertEqual(got, ["the Sun does not set today"])

    def test_a_day_with_no_sunrise_at_all_prints_no_blank_times(self):
        """Polar night: every block is guarded on its own event, so nothing
        renders the "--" a missing time would give."""
        ev = dict(self.EV, sunrise=None, sunset=None, dusk_civil=None,
                  dusk_astro=None, polar_day=False)
        for hour, alt in ((10, -3.0), (14, -3.0), (2, -12.0)):
            got = api._head_day_blocks(ev, self.P, self.OFF,
                                       dt.datetime(2026, 8, 19, hour, 0), alt)
            self.assertNotIn("--", " ".join(t for _r, t, _w in got))


class AnAnimationDrivesTheHeadlineRatherThanDrawingItsOwn(unittest.TestCase):
    """The headline used to sit frozen at the moment the page loaded while
    the chart ran through a whole night under it, and the frame drew a
    second header of its own inside the drawing -- two headers on one page
    disagreeing about the time. The frame hands its header over now, and the
    box shows that instead."""

    def _frame(self, hour, minute=0, **kw):
        r = api.Request(place="Zurich",
                        when=dt.datetime(2026, 8, 19, hour, minute),
                        width=200, **kw)
        return api.compose_frame(r)[0]

    def test_a_browser_frame_hands_its_header_over(self):
        head, sep, chart = self._frame(20, panel=True).partition(api.HEAD_SLOT)
        self.assertTrue(sep, "no seam in a panel frame")
        self.assertIn("Zürich", api.strip_ansi(head))
        # And the chart starts straight away: the two rows the header used
        # to cost are what made a frame taller than the still it replaced.
        self.assertTrue(api.strip_ansi(chart).lstrip("\n").startswith(" 70°"),
                        api.strip_ansi(chart)[:40])

    def test_a_terminal_frame_still_draws_it(self):
        """curl and the GIF have nowhere else to put it."""
        body = self._frame(20, panel=False)
        self.assertNotIn(api.HEAD_SLOT, body)
        lines = api.strip_ansi(body).splitlines()
        self.assertIn("Zürich", lines[0])
        self.assertEqual(lines[1].strip(), "")

    def test_the_seam_does_not_collide_with_another(self):
        """Every slot is three control bytes and they are told apart by the
        middle one. Two sharing a value would split each other's text."""
        slots = [api.ZENITH_SLOT, api.PROSE_SLOT, api.OBJECT_SLOT,
                 api.OBJPROSE_SLOT, api.OBJWHAT_SLOT, api.HEAD_SLOT]
        self.assertEqual(len(set(slots)), len(slots))

    def test_a_reader_handed_the_raw_text_gets_the_header_back(self):
        """strip_slots is what a terminal asking for ?panel=1 gets: the
        seams are places for a browser to break the text apart, and anyone
        else should just read down the page."""
        got = api.strip_slots(self._frame(20, panel=True))
        self.assertNotIn(api.HEAD_SLOT, got)
        lines = api.strip_ansi(got).splitlines()
        self.assertIn("Zürich", lines[0])
        self.assertEqual(lines[1].strip(), "")

    def test_the_handed_over_line_is_trimmed_to_the_box(self):
        """Untrimmed it overran the headline box on any window narrower than
        the widest rung, which is most of them. A picture still gets the
        whole line -- it has no box and no rung."""
        narrow = self._frame(20, panel=True).partition(api.HEAD_SLOT)[0]
        picture = self._frame(20, panel=False).splitlines()[0]
        self.assertLess(len(api.strip_ansi(narrow)),
                        len(api.strip_ansi(picture)))

    def test_the_moment_moves_with_the_frames(self):
        """The whole point. It used to read the page's own moment while the
        chart ran through the night."""
        seen = [api.strip_ansi(self._frame(h, panel=True)
                               .partition(api.HEAD_SLOT)[0])
                for h in (19, 21, 23)]
        self.assertIn("19 Aug 19:00", seen[0])
        self.assertIn("19 Aug 21:00", seen[1])
        self.assertIn("19 Aug 23:00", seen[2])

    def test_the_blocks_change_as_the_sun_crosses(self):
        """Sunset on the line before, gone after; the Sun itself on both
        sides of the horizon and off it by full dark."""
        before = api.strip_ansi(self._frame(20, panel=True)
                                .partition(api.HEAD_SLOT)[0])
        after = api.strip_ansi(self._frame(21, panel=True)
                               .partition(api.HEAD_SLOT)[0])
        night = api.strip_ansi(self._frame(23, panel=True)
                               .partition(api.HEAD_SLOT)[0])
        self.assertIn("↓20:30", before)
        self.assertNotIn("↓20:30", after)
        self.assertIn("☀", before)
        self.assertNotIn("☀", night)


class OneDaysSunEventsAreWalkedOnce(unittest.TestCase):
    """sun_events steps through the day in ten-minute jumps -- 145 solar
    positions -- and the answer is the same for every moment in that day
    from that place. An animation asked for it ninety-six times over one
    day and one place."""

    def setUp(self):
        api._SUN_EVENTS_MEMO.clear()

    def test_the_same_day_and_place_is_computed_once(self):
        day0 = dt.datetime(2026, 8, 19, 0, 0)
        a = api.sun_events_cached(day0, 47.38, 8.54)
        b = api.sun_events_cached(day0, 47.38, 8.54)
        self.assertIs(a, b)
        self.assertEqual(len(api._SUN_EVENTS_MEMO), 1)

    def test_it_still_answers_a_different_day_or_place(self):
        day0 = dt.datetime(2026, 8, 19, 0, 0)
        here = api.sun_events_cached(day0, 47.38, 8.54)
        there = api.sun_events_cached(day0, 69.65, 18.96)
        tomorrow = api.sun_events_cached(day0 + dt.timedelta(days=1), 47.38, 8.54)
        self.assertNotEqual(here["sunrise"], there["sunrise"])
        self.assertNotEqual(here["sunrise"], tomorrow["sunrise"])

    def test_it_matches_the_function_it_stands_in_for(self):
        day0 = dt.datetime(2026, 8, 19, 0, 0)
        self.assertEqual(api.sun_events_cached(day0, 47.38, 8.54),
                         sky.sun_events(day0, 47.38, 8.54))

    def test_it_cannot_grow_without_bound(self):
        """A miss costs a millisecond, so the whole thing is dropped rather
        than aged -- all a cache this shape needs."""
        for i in range(api._SUN_EVENTS_MAX + 2):
            api.sun_events_cached(dt.datetime(2026, 1, 1) + dt.timedelta(days=i),
                                  47.38, 8.54)
        self.assertLessEqual(len(api._SUN_EVENTS_MEMO), api._SUN_EVENTS_MAX)


class TheAnimatedHeadlineIsSwappedLikeTheStillOne(unittest.TestCase):
    """A frame's line reaches the browser as ANSI and becomes HTML there, so
    the two swaps the server makes on the still line -- the pin and the
    dimmed directions -- have to be made again in the page script. These
    check the page carries what that script needs."""

    def _page(self, place):
        r = api.Request(place=place, when=dt.datetime(2026, 8, 19, 21, 0),
                        width=200, panel=True)
        rungs = [(200, True, api.ansi_to_html(api._compose_sky(r).text))]
        return api.lift_chart_head(rungs, r.place.near)[0]

    def test_the_hint_is_handed_to_the_script(self):
        """Handed over rather than parsed out of the line: finding where a
        place name ends by looking at the text would be a guess."""
        got = self._page("46.90,7.10")
        self.assertIn('data-near="', got)
        self.assertIn("Lausanne", got)

    def test_a_named_place_hands_over_nothing(self):
        self.assertNotIn("data-near", self._page("Zurich"))

    def test_the_attribute_is_escaped(self):
        """It goes straight into an attribute and again into a title and an
        aria-label on the other side."""
        got, _ = api.lift_chart_head(
            [(80, True, '<span style="color:#eeeeee">  Zurich · 07 Aug</span>'
                        '\n\nchart')], 'Ex"ample & Co')
        self.assertIn('data-near="Ex&quot;ample &amp; Co"', got)


class OnlyThePausedFrameGetsItsLabelsAsLinks(unittest.TestCase):
    """The still chart has had them all along. A running animation replaces
    the whole chart several times a second, and an anchor in a frame nobody
    can click is markup for its own sake -- 144 frames of it. So the page
    asks for them one frame at a time, on the frame it has stopped on."""

    def _frame(self, **kw):
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 19, 23, 0),
                        width=200, panel=True, **kw)
        return api.compose_frame(r)[0]

    def test_a_plain_frame_carries_none(self):
        self.assertNotIn("<a ", api.ansi_to_html(self._frame()))

    def test_asking_for_them_gets_them(self):
        html = api.ansi_to_html(self._frame(links=True))
        self.assertIn("<a ", html)
        self.assertIn("/Zurich/", html)

    def test_they_carry_the_frames_own_moment(self):
        """A label opens the sky it was drawn in, which for a frame is the
        frame's moment and not the page's."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 19, 20, 0),
                        width=200, panel=True, links=True)
        later = r.at(r.when_utc + dt.timedelta(hours=3))
        html = api.ansi_to_html(api.compose_frame(later)[0])
        self.assertIn("t=2026-08-19T23:00", html)
        self.assertNotIn("t=2026-08-19T20:00", html)

    def test_a_cheap_copy_of_a_request_keeps_the_flag(self):
        """Request.at is what an animation builds every frame from, and it
        copies field by field -- a flag left out there is a flag that only
        works on the first frame."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 19, 23, 0),
                        panel=True, links=True)
        self.assertTrue(r.at(r.when_utc + dt.timedelta(minutes=10)).links)

    def test_a_terminal_frame_never_gets_them(self):
        """The markers would print as control characters, and a terminal
        cannot click a star."""
        r = api.Request(place="Zurich", when=dt.datetime(2026, 8, 19, 23, 0),
                        width=200, panel=False, links=True)
        self.assertNotIn("<a ", api.ansi_to_html(api.compose_frame(r)[0]))

    def test_a_refetched_frame_asks_at_the_width_on_screen(self):
        """The width is not in data-live-url. CSS picks the ladder rung, the
        script reads it off the element and appends it to its own copy of
        the URL -- so anything that goes back to the attribute asks for the
        default width and gets a chart two thirds the size of the one it is
        replacing. Measured: 221 columns against 358.

        Both refetches have to read the resolved URL. This checks the page
        script itself, because the mistake is invisible in any output the
        server can be asked for."""
        src = _page_script()
        self.assertIn("url:liveUrl", src)
        for fn in ("skymapAnimDeepSky", "skymapAnimLinks"):
            body = _grab_fn(src, fn)
            self.assertIn("A.url", body, fn)
            self.assertNotIn("data-live-url", body, fn)

    def test_every_way_of_showing_a_frame_goes_through_one_painter(self):
        """The reason two of these shipped broken. Each new way of putting a
        frame on screen was written by copying the last one, so each started
        identical and then quietly grew a difference nobody saw until it was
        used. One painter means a path cannot be missing a piece."""
        src = _page_script()
        for fn in ("skymapAnimShow", "skymapScrubTo"):
            body = _grab_fn(src, fn)
            self.assertIn("skymapPaintFrame(", body, fn)
            self.assertNotIn("innerHTML=", body, fn)

    def test_everything_that_comes_to_rest_asks_for_links(self):
        """Pausing did, stepping did not, so stepping showed plain labels on
        every frame but the one somebody happened to pause on."""
        src = _page_script()
        for fn in ("skymapAnimPlay", "skymapStepFrame"):
            self.assertIn("skymapSettle(", _grab_fn(src, fn), fn)

    @unittest.skipUnless(_have_node(), "node not available")
    def test_three_quick_steps_still_end_on_a_linked_frame(self):
        """The reported case: animate, pause, three arrows. The first press
        starts a request, the next two are turned away by the busy flag, and
        the first reply is answering a frame nobody is looking at any more.
        Only running the sequence shows it."""
        got = _drive_page_js(
            ["skymapSettle", "skymapAnimShow", "skymapAnimStep",
             "skymapAnimLinks", "skymapStepFrame", "skymapScrubTo"],
            """
var ASKED=[],PENDING=[];
var document={documentElement:{classList:{add:function(){},remove:function(){}}},
              getElementById:function(){return null;}};
var window={skymapChartPre:function(){return {innerHTML:''};}};
function skymapAnimCook(){return {head:'',body:'',zen:''};}
function skymapAnimZoom(){}
function skymapAnimSyncPng(){}
function skymapPaintFrame(){}
function skymapAnimFrameTime(i){return '2026-08-19T2'+i+':00';}
function skymapFetchFrame(url){
  ASKED.push(Number(/t=2026-08-19T2(\\d)/.exec(url)[1]));
  return new Promise(function(res){PENDING.push(function(){res('FRAME');});});
}
window.skymapAnim={frames:['a','b','c','d','e','f'],cooked:{},at:0,
  playing:false,linked:{},dsoOn:{},loadingLinks:false,
  url:'/Zurich?animate=24&t=2026-08-19T20:00&ui=1&w=300',
  live:null,zen:null,pre:{innerHTML:''},
  btn:{textContent:'',getAttribute:function(){return null;}}};
window.skymapScrub={off:0,busy:false,base:null};
skymapSettle();
skymapStepFrame(1);skymapStepFrame(1);skymapStepFrame(1);
(async function(){
  for(var i=0;i<8&&PENDING.length;i++){PENDING.shift()();
    await new Promise(function(r){setImmediate(r);});}
  process.stdout.write(JSON.stringify(
    {at:window.skymapAnim.at,asked:ASKED}));
})();
""")
        got = json.loads(got)
        self.assertEqual(got["at"], 3)
        self.assertIn(3, got["asked"],
                      f"the frame on screen never asked for links: {got}")

    @unittest.skipUnless(_have_node(), "node not available")
    def test_the_browsers_own_converter_makes_them_anchors(self):
        """The one that matters, and the one whose absence shipped a broken
        feature: a still chart is turned into HTML by Python and a frame by
        the page's own script, so anything the Python side does on the way
        out has to be done there too. Without it the markers arrived as
        literal text and a paused frame printed its own hrefs across the
        sky. Checked by running the page's real ansiToHtml over a real
        frame rather than by reading it."""
        frame = self._frame(links=True).partition(api.HEAD_SLOT)[2]
        got = _run_page_js(["escapeHtml", "xtermHex", "anchorMarkers",
                            "ansiToHtml"], "ansiToHtml", frame)
        self.assertIn('<a class="sky-link" href="/Zurich/', got)
        for marker in (sky.LINK_START, sky.LINK_SEP, sky.LINK_END):
            self.assertNotIn(marker, got)
        self.assertNotIn("&#x1", got)      # nor escaped into an entity


class TheArrowsStepBeforeAnythingIsPlaying(unittest.TestCase):
    """They used to do nothing until somebody had pressed space, which made
    the one obvious way to look at another moment invisible. And even then a
    stream only runs forward from the page's own moment, so the left arrow
    had nothing behind it at any point."""

    def test_the_handler_is_not_behind_the_animation_guard(self):
        """The transport block only binds while there are frames, so the
        arrow fallback has to sit after it -- inside, it would never run on
        arrival, which is the whole case this is for."""
        src = _page_script()
        guard = src.index("window.skymapAnim&&window.skymapAnim.frames.length")
        calls = [m.start() for m in re.finditer(r"skymapStepFrame\(", src)]
        self.assertTrue([c for c in calls if c > guard],
                        "no arrow handler after the animation guard")

    def test_stepping_prefers_the_buffer_and_falls_back_to_a_request(self):
        """Inside a running stream the frames ahead are already in memory;
        only the past, and the state before one has been started, has to be
        asked for."""
        body = _grab_fn(_page_script(), "skymapStepFrame")
        self.assertIn("A.at+d>=0", body)
        self.assertIn("skymapAnimStep(d)", body)
        self.assertIn("skymapScrubTo", body)

    @unittest.skipUnless(_have_node(), "node not available")
    def test_a_step_back_asks_for_an_earlier_moment(self):
        """The whole point of the change, and the half a stream cannot do."""
        got = _run_page_js(["skymapFrameTime"], "skymapFrameTime",
                           "-1", setup=_STEP_DOM)
        self.assertEqual(got.strip(), "2026-08-19T21:10")
        got = _run_page_js(["skymapFrameTime"], "skymapFrameTime",
                           "3", setup=_STEP_DOM)
        self.assertEqual(got.strip(), "2026-08-19T21:50")

    @unittest.skipUnless(_have_node(), "node not available")
    def test_a_stepped_frame_is_asked_for_at_the_width_on_screen(self):
        """Same trap the refetches fell into: the width is not in
        data-live-url, it is on whichever ladder rung CSS picked."""
        js = ("function go(off){return skymapFrameUrl("
              "skymapFrameTime(Number(off)),'&links=1');}")
        got = _run_page_js(["skymapFrameTime", "skymapFrameUrl"], "go", "-3",
                           setup=_STEP_DOM + js)
        self.assertIn("w=300", got)
        self.assertIn("animate=1", got)
        self.assertIn("links=1", got)
        self.assertIn("t=2026-08-19T20%3A50", got)


class TheDarkAnswersWaitUntilItIsDark(unittest.TestCase):
    """The Bortle estimate and the star count are both answers about a fully
    dark sky. Printed through twilight they are a description of two hours
    from now and a number in freefall -- 114 stars at astronomical dawn, 40
    twenty minutes later -- on the line that has least room to spare."""

    def _line(self, sun_alt):
        star = {"m": 1.2, "n": "Vega"}
        st = {"moon": {"alt": 11.0, "az": 67.0, "age": 7.4, "illum": 0.29},
              "sun": {"alt": sun_alt, "az": 290.0}, "up": [],
              "visible": [(star, 60.0, 300.0)] * 223}
        return api._sky_summary(st, 47.38, 300, note="Bortle ~8")

    def test_both_are_there_at_full_dark(self):
        for block in ("Bortle ~8", "223 stars"):
            self.assertIn(block, self._line(-20.0))

    def test_neither_survives_any_twilight(self):
        for alt in (-17.9, -12.0, -8.0, -3.0):
            got = self._line(alt)
            self.assertNotIn("Bortle", got, alt)
            self.assertNotIn("stars", got, alt)

    def test_the_moon_being_down_is_one_word(self):
        """"below the horizon" spent seventeen characters on the one block
        with nothing to report, and "down" pairs with the "up SSW" the rest
        of the line uses."""
        st = {"moon": {"alt": -20.0, "az": 67.0, "age": 7.4, "illum": 0.48},
              "sun": {"alt": -20.0, "az": 290.0}, "up": [], "visible": []}
        got = api._sky_summary(st, 47.38, 300)
        self.assertIn("48% down", got)
        self.assertNotIn("below the horizon", got)


class TheAfternoonCarriesTheLightItself(unittest.TestCase):
    """golden, blue and the shadow note used to exist only inside the day
    chart's own header, where an animation dropped them and a narrow browser
    never saw them. Two of the three have a home on the line now."""

    def _bands(self):
        return dict(golden_am=dict(start=dt.datetime(2026, 8, 19, 4, 7),
                                   end=dt.datetime(2026, 8, 19, 5, 9)),
                    golden_pm=dict(start=dt.datetime(2026, 8, 19, 17, 48),
                                   end=dt.datetime(2026, 8, 19, 18, 50)))

    def test_it_names_the_next_window_not_both(self):
        """The morning one is over by the time anybody reads an afternoon
        line, and the block answers "when should I be outside", which has
        one answer."""
        self.assertEqual(
            api._golden_block(self._bands(), 2.0, dt.datetime(2026, 8, 19, 14, 0)),
            "golden 19:48")

    def test_standing_in_one_it_says_when_it_ends(self):
        self.assertEqual(
            api._golden_block(self._bands(), 2.0, dt.datetime(2026, 8, 19, 18, 0)),
            "golden \u2192 20:50")

    def test_after_the_last_one_it_says_nothing(self):
        self.assertEqual(
            api._golden_block(self._bands(), 2.0, dt.datetime(2026, 8, 19, 19, 0)),
            "")

    def test_the_shadow_says_how_long_and_which_way(self):
        """Which way is the Sun's bearing turned around: the shadow falls
        away from the light."""
        self.assertEqual(api._shadow_block(45.0, 180.0), "shadows 1.0x N")

    def test_a_shadow_at_the_horizon_is_capped_rather_than_absurd(self):
        """cot(h) is 57x half a degree up, where the slope of the ground you
        are standing on matters more than the arithmetic."""
        self.assertIn(f">{api.SHADOW_CAP:.0f}x", api._shadow_block(0.5, 270.0))

    def test_neither_outlives_the_sun(self):
        self.assertEqual(api._shadow_block(-1.0, 270.0), "")


class TheSunGlyphIsColouredByWhereTheSunIs(unittest.TestCase):
    """Red-orange-yellow above the horizon, the blue hour under it, grey by
    the time it is about to leave the line."""

    def test_it_shares_the_charts_own_ramp_while_the_sun_is_up(self):
        """Two ramps that drifted apart would put a yellow glyph over a red
        marker."""
        for alt in (60.0, 20.0, 2.0):
            self.assertEqual(api._sun_head_color(alt), api._sun_color(alt))

    def test_it_turns_blue_the_moment_the_sun_is_down(self):
        self.assertEqual(api._sun_head_color(-0.5), api._SUN_DOWN_GRADIENT[0])

    def test_it_is_grey_by_the_point_it_leaves_the_line(self):
        """The ramp is spent over exactly the stretch the glyph is on
        screen for, so it arrives at grey as the block goes rather than
        two thirds of the way through a gradient nobody sees the end of."""
        self.assertEqual(api._sun_head_color(api.CIVIL_ALT),
                         api._SUN_DOWN_GRADIENT[-1])

    def test_painting_hands_the_line_back_its_own_colour(self):
        """A reset here would strip the rest of the line to the terminal's
        default, which is the whole line after the first block."""
        painted = api.paint_sun_glyph(f"{sky.C.LABEL}☀ 55°SSW",
                                      55.0, sky.C.LABEL, True)
        self.assertIn(api._sun_head_color(55.0) + "☀" + sky.C.LABEL,
                      painted)
        self.assertNotIn("☀" + sky.C.OFF, painted)

    def test_a_terminal_without_colour_gets_the_line_untouched(self):
        plain = "☀ 55°SSW"
        self.assertEqual(api.paint_sun_glyph(plain, 55.0, sky.C.LABEL, False),
                         plain)

    def test_only_the_position_block_is_coloured(self):
        """The sunset block carries the same glyph as a label. Colouring it
        by the current altitude would say something untrue about a time
        hours away -- and if the position block is absent, as it is through
        the night, nothing on the line should be coloured at all."""
        line = "☀ 3° down WNW · ☀↓20:30 WNW"
        got = api.paint_sun_glyph(line, -3.0, sky.C.LABEL, True)
        self.assertEqual(got.count(api._sun_head_color(-3.0)), 1)
        self.assertIn("· ☀↓20:30", got)
        night = api.paint_sun_glyph("◑ 48% down · ☀↓20:30 WNW", -20.0,
                                    sky.C.LABEL, True)
        self.assertEqual(night, "◑ 48% down · ☀↓20:30 WNW")


class TheDirectionsAreSetSmallerThanTheirFacts(unittest.TestCase):
    """The fact you act on is the time or the height; the direction is the
    detail that says which window to stand at."""

    def test_the_three_moments_of_the_sun_get_it(self):
        got = api.dim_directions("↑06:27 ENE · ↓20:30 WNW · ^13:30 S")
        self.assertEqual(got.count('<span class="dir">'), 3)
        self.assertIn('↑06:27 <span class="dir">ENE</span>', got)
        self.assertIn('^13:30 <span class="dir">S</span>', got)

    def test_every_height_on_either_line_gets_it_too(self):
        """The Sun's own position, the Moon's, a planet's -- day line and
        night line alike. The tail is "up SSW" or "down WNW"; the number
        stays at reading size because it is the fact."""
        got = api.dim_directions("☀ 55° up SSW · ◑ 47% 15° up SSW "
                                 "· Venus 12° up WSW")
        self.assertEqual(got.count('<span class="dir">'), 3)
        self.assertIn('55° <span class="dir">up SSW</span>', got)
        self.assertIn('12° <span class="dir">up WSW</span>', got)

    def test_a_sun_under_the_horizon_gets_it(self):
        got = api.dim_directions("☀ 3° down WNW")
        self.assertIn('3° <span class="dir">down WNW</span>', got)

    def test_the_glyph_labelling_the_sunset_is_dimmed_but_not_the_other_one(self):
        """A down arrow beside a list of planets is a mark with no subject,
        so the sunset block names its own. The block that says where the Sun
        is now keeps its full size and its own colour -- it is the fact, not
        a label on one."""
        got = api.dim_directions("☀ 3° down WNW · ☀↓20:30 WNW")
        self.assertIn('<span class="dir">☀</span>↓20:30', got)
        self.assertTrue(got.startswith("☀ 3°"), got)

    def test_the_moon_being_down_is_left_alone(self):
        """"below the horizon" is the whole fact and has no direction in it.
        It is also the block that survives every trim, so it is the last
        thing that should be set smaller than its neighbours."""
        line = "◑ 48% below the horizon"
        self.assertEqual(api.dim_directions(line), line)

    def test_an_empty_line_is_handed_straight_back(self):
        self.assertEqual(api.dim_directions(""), "")


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


class DayHeadlineFitsItsBoxTest(unittest.TestCase):
    """The day headline is set at DAY_HEAD_PX in its own box while the chart
    below it is drawn at CHART_FONT_PX, so a character up there is 1.65 of a
    column down here. It was trimmed against the column count, which handed
    it 65% more line than the box holds, and it wrapped onto a second row at
    every window narrower than about 1500px -- pushing the chart down, on a
    page whose whole layout is the chart sized to the window.

    The night composer scales for this and always did. This is the day one.
    """

    WHEN = dt.datetime(2026, 8, 10, 11, 1)      # daylight: the day composer

    def _head(self, width, place="Marseille"):
        r = api.Request(place=place, when=self.WHEN, color=False, panel=True,
                        width=width)
        text = api.strip_ansi(api.compose(r).text)
        return next((l for l in text.split("\n") if l.strip()), "").strip()

    def _room(self, width):
        return int(width * api.CHART_FONT_PX / api.DAY_HEAD_PX)

    def test_every_rung_of_the_ladder_fits_its_own_budget(self):
        """Every width the browser can actually pick, not a sample: the
        ladder ships one rung per CHART_LADDER entry and CSS chooses by
        container width, so a single rung over budget is a real window that
        wraps."""
        for _min_ch, cols, _panel in api.CHART_LADDER:
            head = self._head(cols)
            self.assertLessEqual(len(head), self._room(cols),
                                 f"{cols} cols: {head!r}")

    def test_the_budget_is_the_scaled_one_not_the_column_count(self):
        """The bug in one assertion. At 160 columns the old budget allowed
        160 characters and the box holds 96."""
        cols = 160
        self.assertLess(self._room(cols), cols)
        self.assertLessEqual(len(self._head(cols)), self._room(cols))

    def test_it_gives_up_blocks_in_the_agreed_order(self):
        """Widening the window adds blocks back in the reverse of the drop
        order, so this reads the ranking off the rendered line rather than
        off the table it comes from."""
        seen = []
        for _min_ch, cols, _panel in api.CHART_LADDER:
            for block in [b.strip() for b in self._head(cols).split(" · ")][2:]:
                kind = block.split()[0]
                if kind not in seen:
                    seen.append(kind)
        self.assertEqual(seen[0][0], "\N{BLACK SUN WITH RAYS}")
        for a, b in (("stars", "darkest"), ("darkest", "^13:40"),
                     ("^13:40", "golden"), ("golden", "shadows")):
            self.assertLess(seen.index(a), seen.index(b),
                            f"{a} should outlive {b}: {seen}")

    def test_no_two_day_blocks_share_a_rank(self):
        """A tie is decided by which block happens to be appended first,
        which is the trim picking on list position rather than on a decision
        anybody wrote down. Sunrise and sunset are the one shared number:
        they are never both on the line."""
        ranks = [v for k, v in api.DAY_HEAD_RANKS.items() if k != "set"]
        self.assertEqual(len(ranks), len(set(ranks)), api.DAY_HEAD_RANKS)
        self.assertEqual(api.DAY_HEAD_RANKS["rise"], api.DAY_HEAD_RANKS["set"])
        self.assertEqual(api.DAY_HEAD_RANKS["sun"], 0)

    def test_the_night_line_keeps_the_ranks_it_was_tuned_with(self):
        """_head_day_blocks serves both lines and the two rank these blocks
        differently on purpose -- by night the Moon never goes at all. The
        default is the night's, so adding the day table changed nothing
        there."""
        self.assertEqual(api.NIGHT_HEAD_RANKS["moon"], 0)
        self.assertNotEqual(api.DAY_HEAD_RANKS["moon"],
                            api.NIGHT_HEAD_RANKS["moon"])
        r = api.Request(place="Marseille", when=dt.datetime(2026, 8, 10, 2, 0),
                        color=False, panel=True, width=200)
        p = r.place
        ev = api.sun_events_cached(api._day0(r), p.lat, p.lon)
        off = p.offset(r.when_utc)
        default = api._head_day_blocks(ev, p, off, r.when_utc, -20.0)
        asked = api._head_day_blocks(ev, p, off, r.when_utc, -20.0,
                                     ranks=api.NIGHT_HEAD_RANKS)
        self.assertEqual(default, asked)

    def test_the_static_headline_clips_rather_than_wrapping(self):
        """Last line of defence, and the reason a future miscalculation is a
        missing tail rather than a shoved page. #day-head-live has always
        done this; the ladder's own rungs did not."""
        self.assertIn("#day-head .dh{white-space:pre;overflow:hidden",
                      api.PAGE.replace("{{", "{").replace("}}", "}"))





class TheCrossingMarker(unittest.TestCase):
    """The few bytes that arm the sunset takeover.

    Not the drawing -- that is art.py's and it is fetched separately. This
    is only "is there a crossing near enough to be worth waiting for, and
    when exactly".
    """
    # 2026-08-10, Zurich: the Sun's limb touches the horizon at 20:42:43
    # local and the last of it goes at 20:46:08.
    SUNSET_LOCAL = dt.datetime(2026, 8, 10, 20, 42, 43)

    def setUp(self):
        self.place = api.lookup_place("Zurich")

    def at(self, local, **kw):
        """The marker as it would be at a local wall-clock moment."""
        return api.crossing_arm_html(
            self.place, local - dt.timedelta(hours=2), **kw)

    def field(self, markup, name):
        return re.search(rf'data-{name}="([^"]*)"', markup).group(1)

    def test_it_arms_inside_the_window(self):
        self.assertTrue(self.at(dt.datetime(2026, 8, 10, 19, 30)))
        self.assertTrue(self.at(dt.datetime(2026, 8, 10, 20, 41)))

    def test_it_stays_quiet_outside_it(self):
        # Six hours out, and a full-screen takeover on a page somebody
        # opened at lunchtime and forgot is an ambush, not a moment.
        self.assertEqual(self.at(dt.datetime(2026, 8, 10, 14, 0)), "")
        # And half past nine at night: tomorrow's sunrise is nine hours off.
        self.assertEqual(self.at(dt.datetime(2026, 8, 10, 21, 30)), "")

    def test_a_crossing_already_running_still_arms(self):
        # Landing mid-sunset should show you the sunset happening outside.
        self.assertTrue(self.at(dt.datetime(2026, 8, 10, 20, 44)))

    def test_a_pinned_page_never_arms(self):
        # ?t= is not that minute and never becomes it.
        self.assertEqual(self.at(dt.datetime(2026, 8, 10, 19, 30),
                                 pinned=True), "")

    def test_no_place_arms_nothing(self):
        self.assertEqual(api.crossing_arm_html(None), "")

    def test_the_midnight_sun_arms_nothing(self):
        far_north = api.lookup_place("Longyearbyen")
        self.assertEqual(
            api.crossing_arm_html(far_north, dt.datetime(2026, 6, 21, 10, 0)),
            "")

    def test_the_instants_are_absolute(self):
        # Not "in N seconds". A page can be served from cache minutes after
        # it was built, and a countdown baked into it would be that stale;
        # an epoch instant stays true however long it sat.
        m = self.at(dt.datetime(2026, 8, 10, 19, 30))
        at = dt.datetime.utcfromtimestamp(int(self.field(m, "at")))
        end = dt.datetime.utcfromtimestamp(int(self.field(m, "end")))
        self.assertEqual(at, self.SUNSET_LOCAL - dt.timedelta(hours=2))
        self.assertLess(at, end)
        self.assertLess((end - at).total_seconds(), 600)

    def test_the_same_crossing_gets_the_same_key_from_any_moment(self):
        # The key is what makes "once per crossing" mean the crossing and
        # not the page load, so two pages opened minutes apart have to agree.
        a = self.field(self.at(dt.datetime(2026, 8, 10, 19, 30)), "key")
        b = self.field(self.at(dt.datetime(2026, 8, 10, 20, 30)), "key")
        self.assertEqual(a, b)
        self.assertIn("Zurich", a)

    def test_tomorrows_sunrise_is_a_different_crossing(self):
        # Seeing tonight's sunset must not use up tomorrow morning.
        tonight = self.field(self.at(dt.datetime(2026, 8, 10, 19, 30)), "key")
        morning = self.field(
            self.at(dt.datetime(2026, 8, 11, 5, 30)), "key")
        self.assertNotEqual(tonight, morning)

    def test_it_points_at_the_place_it_is_about(self):
        m = self.at(dt.datetime(2026, 8, 10, 19, 30))
        self.assertEqual(self.field(m, "url"), "/Zurich/crossing.json")

    def test_the_page_counts_in_the_same_window_the_server_arms_in(self):
        # Two copies of one number, in two languages. A page that armed on a
        # wider window than the server does would fire off a remembered
        # crossing the server had already decided was too far away.
        wanted = int(api.CROSSING_ARM_H * 3600_000)
        self.assertIn(f"ahead>{wanted}", api.PAGE)
        self.assertNotIn("{CROSSING_ARM_H_MS}", api.PAGE)

    def test_it_is_invisible_and_not_a_control(self):
        m = self.at(dt.datetime(2026, 8, 10, 19, 30))
        self.assertIn("hidden", m)
        self.assertNotIn("<button", m)
        self.assertNotIn("href", m)


class TheSunCanSetEclipsed(unittest.TestCase):
    """On 12 August 2026 the Sun goes down over central Europe with a bite
    out of it, and the drawing has to show that.

    A plain round Sun setting that evening would be wrong at the exact
    moment more people are looking at the sky than any other this year --
    64% wrong over Milan.
    """
    NOON = dt.datetime(2026, 8, 12, 12, 0)

    def lit(self, frame_html):
        return sum(l.count("#") + l.count("+")
                   for l in re.sub(r"<[^>]*>", "", frame_html).splitlines())

    def crossing(self, place):
        return api.crossing_frames(api.Request(place=place, when=self.NOON))

    def test_it_knows_which_places_set_eclipsed(self):
        for name in ("Zurich", "Milan", "Munich", "Berlin", "Madrid"):
            self.assertTrue(self.crossing(name)["eclipsed"], name)
        # The eclipse is over before the Sun sets in these.
        for name in ("London", "Oslo", "Reykjavik"):
            self.assertFalse(self.crossing(name)["eclipsed"], name)

    def test_the_bite_is_as_deep_as_the_eclipse_really_is(self):
        # Ordered by how much of the Sun is covered at that place's sunset:
        # Milan 64%, Munich 58%, Zurich 41%, Berlin 30%, Madrid 7%. The
        # drawing has to agree, or the geometry is decorative.
        lit = {n: self.lit(self.crossing(n)["frames"][0])
               for n in ("Milan", "Munich", "Zurich", "Berlin", "Madrid",
                         "London")}
        self.assertLess(lit["Milan"], lit["Munich"])
        self.assertLess(lit["Munich"], lit["Zurich"])
        self.assertLess(lit["Zurich"], lit["Berlin"])
        self.assertLess(lit["Berlin"], lit["Madrid"])
        self.assertLess(lit["Madrid"], lit["London"])

    def test_the_moon_keeps_moving_while_the_sun_goes_down(self):
        # Not one bite held for the whole run: Zurich's Sun sets 41% covered
        # and still uncovering, so the crescent has to open as it drops.
        p = api.lookup_place("Zurich")
        r = api.Request(place="Zurich", when=self.NOON)
        first, last, _rising = api.next_crossing(p, r.when_utc)
        span = (last - first).total_seconds()
        inst = [first + dt.timedelta(seconds=span * i / 43) for i in range(44)]
        bites = api.crossing_bites(p, inst, dt.date(2026, 8, 12))
        seps = [math.hypot(b[0], b[1]) for b in bites if b]
        self.assertEqual(len(seps), 44)
        self.assertEqual(seps, sorted(seps), "the Moon stopped, or went back")
        self.assertGreater(seps[-1] - seps[0], 0.01, "the bite never moved")

    def test_the_geometric_horizon_does_not_veto_a_setting_sun(self):
        # The trap this walked into once, and the one most likely to be
        # walked into again. eclipse.disc_art refuses zeta <= 0 -- the far
        # side of the Earth -- but zeta is measured against the *geometric*
        # horizon and sunset is defined 0.833 degrees below it. So zeta is
        # negative at every instant this is ever asked about, and copying
        # that test silently threw away every bite of every crossing.
        p = api.lookup_place("Zurich")
        r = api.Request(place="Zurich", when=self.NOON)
        first, last, _rising = api.next_crossing(p, r.when_utc)
        bites = api.crossing_bites(p, [first, last], dt.date(2026, 8, 12))
        self.assertTrue(all(bites), "a setting Sun was refused its eclipse")

    def test_an_ordinary_evening_has_no_bite(self):
        plain = api.crossing_frames(
            api.Request(place="Zurich", when=dt.datetime(2026, 8, 10, 12, 0)))
        self.assertFalse(plain["eclipsed"])
        self.assertGreater(self.lit(plain["frames"][0]),
                           self.lit(self.crossing("Zurich")["frames"][0]))

    def test_it_is_not_wired_to_this_one_eclipse(self):
        # The next eclipse in the table has to work with nothing told to it.
        p = api.lookup_place("Madrid")
        import besselian
        c = besselian.local("2027-08-02", p.lat, p.lon)
        day0 = dt.datetime(2027, 8, 2)
        inst = [day0 + dt.timedelta(hours=c["first"]
                                    + (c["last"] - c["first"]) * i / 43)
                for i in range(44)]
        bites = api.crossing_bites(p, inst, dt.date(2027, 8, 2))
        self.assertTrue(all(bites), "the 2027 eclipse was not found")

    def test_a_day_with_no_eclipse_finds_none(self):
        self.assertEqual(api._eclipse_keys_near(dt.date(2026, 5, 5)), [])
        self.assertIn("2026-08-12", api._eclipse_keys_near(dt.date(2026, 8, 12)))
        # The day either side too: the key is a UT date and a place far
        # enough east or west keeps a different one.
        self.assertIn("2026-08-12", api._eclipse_keys_near(dt.date(2026, 8, 13)))

    def test_the_basis_is_measured_not_assumed(self):
        # East and north, as they lie in the observer's sky. Two checks that
        # do not depend on any sign convention: the pair is close to
        # orthogonal, and north has to tilt away from straight up for an
        # object that is not on the meridian.
        (ex, ey), (nx, ny) = api._sky_basis(12.0, 20.0, 47.4, 18.0)
        self.assertLess(abs(ex * nx + ey * ny), 0.02, "not orthogonal")
        self.assertAlmostEqual(math.hypot(ex, ey), 1.0, places=2)
        self.assertAlmostEqual(math.hypot(nx, ny), 1.0, places=2)
        # On the meridian, north is straight up and east is straight across.
        (mex, mey), (mnx, mny) = api._sky_basis(18.0, 20.0, 47.4, 18.0)
        self.assertAlmostEqual(abs(mny), 1.0, places=2)
        self.assertLess(abs(mnx), 0.02)


class TheEclipseWelcome(unittest.TestCase):
    """On the day an eclipse crosses a place, the site opens with it drawn.

    Nothing new is drawn -- eclipse.disc_frames has made these since the
    eclipse pages were built. What is tested here is the judgement around
    them: who gets greeted, who is left alone, and what the line under the
    picture says.
    """
    DAY = dt.datetime(2026, 8, 12, 9, 0)      # Wednesday morning, UT

    def place(self, name):
        p = api.lookup_place(name)
        self.assertIsNotNone(p, name)
        return p

    def test_it_greets_the_places_that_see_one(self):
        for name in ("Zurich", "Madrid", "London", "Reykjavik", "Lisbon"):
            self.assertIsNotNone(api.welcome_eclipse(self.place(name),
                                                     self.DAY), name)

    def test_it_leaves_everyone_else_alone(self):
        # Nothing at all east of Berlin on this one, and the feature has to
        # be silent there rather than apologetic.
        for name in ("Vienna", "Rome", "Athens", "Istanbul"):
            self.assertIsNone(api.welcome_eclipse(self.place(name), self.DAY),
                              name)

    def test_a_sliver_is_not_worth_a_takeover(self):
        # New York sees 10% of the Sun covered, which is not visible to the
        # naked eye. Taking over somebody's screen for it oversells it.
        ny = self.place("New York")
        self.assertIsNone(api.welcome_eclipse(ny, self.DAY))
        self.assertGreater(api.WELCOME_FLOOR, 0.10)

    def test_only_on_the_day(self):
        z = self.place("Zurich")
        self.assertIsNotNone(api.welcome_eclipse(z, self.DAY))
        for when in (dt.datetime(2026, 8, 10, 9, 0),
                     dt.datetime(2026, 8, 14, 9, 0),
                     dt.datetime(2026, 3, 1, 9, 0)):
            self.assertIsNone(api.welcome_eclipse(z, when), when)

    def test_the_caption_says_when_and_which_way(self):
        # The two things the picture cannot say. Maximum, not first contact:
        # it is the moment worth being outside for.
        self.assertEqual(api.welcome_caption(self.place("Zurich"),
                                             "2026-08-12", "partial"),
                         "Enjoy the eclipse today, 20:17 WNW")
        self.assertEqual(api.welcome_caption(self.place("Madrid"),
                                             "2026-08-12", "total"),
                         "Enjoy totality today, 20:32 WNW")

    def test_the_caption_carries_no_degree_sign(self):
        # Every degree in this app is a height, so a bearing never has one.
        for name in ("Zurich", "Madrid", "Reykjavik", "London"):
            cap = api.welcome_caption(self.place(name), "2026-08-12", "total")
            self.assertNotIn("\N{DEGREE SIGN}", cap, name)

    def test_the_caption_sits_under_the_drawing(self):
        frames, _labels = api.welcome_frames(self.place("Zurich"),
                                             "2026-08-12", "partial")
        rows = re.sub(r"<[^>]*>", "", frames[0]).splitlines()
        self.assertIn("Enjoy the eclipse today", rows[-1])
        # A blank row between, so it reads as a caption under a picture
        # rather than as another row of the picture.
        self.assertEqual(rows[-2].strip(), "")

    def test_every_frame_carries_it(self):
        frames, _l = api.welcome_frames(self.place("Madrid"), "2026-08-12",
                                        "total")
        for i, f in enumerate(frames):
            self.assertIn("Enjoy totality today", f, i)

    def test_nothing_to_draw_is_not_a_crash(self):
        self.assertIsNone(api.welcome_frames(self.place("Vienna"),
                                             "2026-08-12", "partial"))

    def test_the_eclipse_pages_did_not_get_the_caption(self):
        # welcome_frames adds it, disc_frames does not -- the eclipse page
        # already carries the times in a row of its own, and a second copy
        # inside the drawing would be the same fact twice.
        import eclipse
        p = self.place("Zurich")
        frames, _l = eclipse.disc_frames("2026-08-12", p.lat, p.lon, tz=2)
        self.assertTrue(frames)
        self.assertNotIn("Enjoy", "".join("".join(f) for f in frames))

    def test_the_marker_arms_only_where_it_should(self):
        z = self.place("Zurich")
        self.assertIn('id="welcome-arm"', api.welcome_arm_html(z, self.DAY))
        self.assertEqual(api.welcome_arm_html(z, self.DAY, pinned=True), "")
        self.assertEqual(api.welcome_arm_html(None), "")
        self.assertEqual(
            api.welcome_arm_html(self.place("Vienna"), self.DAY), "")

    def test_both_takeovers_are_armed_together(self):
        # One call, so a page cannot end up arming one and not the other.
        armed = api._arms(self.place("Zurich"), self.DAY)
        self.assertIn('id="welcome-arm"', armed)

    def test_there_is_one_stage_and_two_callers(self):
        # The extraction is the point: two copies of a play loop is the
        # shape that put anchors across the sky and left the eclipse
        # drawings uncentred.
        self.assertEqual(api.PAGE.count("function skymapTakeover"), 1)
        self.assertEqual(api.PAGE.count("skymapTakeover("), 3)  # def + 2 uses
        # And a guard so the two cannot stack on the same evening.
        self.assertIn("SKYMAP_STAGE", api.PAGE)
