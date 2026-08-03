#!/usr/bin/env python3
"""Tests for the nearest-city timezone fallback in api.py.

Run:  python3 test_api.py
"""
import datetime as dt
import unittest
import api


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


class HeaderFindField(unittest.TestCase):
    """header_html's find_value param -- None (every page but the chart
    view) omits the find field entirely; a string (possibly empty, the
    chart view) renders it pre-filled."""

    def test_find_value_none_omits_the_field(self):
        self.assertNotIn('id="find"', api.header_html("Zurich"))
        self.assertNotIn('id="findbar"', api.header_html("Zurich"))

    def test_find_value_present_renders_the_field(self):
        html_out = api.header_html("Zurich", find_value="")
        self.assertIn('id="find"', html_out)
        self.assertIn('id="find-dropdown"', html_out)

    def test_find_value_is_prefilled_and_escaped(self):
        html_out = api.header_html("Zurich", find_value='<script>Venus')
        self.assertIn('value="&lt;script&gt;Venus"', html_out)


class ExploreVariants(unittest.TestCase):
    """EXPLORE (every page but the chart view) keeps its own #find input in
    the drawer; EXPLORE_DATETIME (the chart view) doesn't, since that page
    gets a promoted #find in the header instead."""

    def test_explore_has_a_find_input(self):
        self.assertIn('id="find"', api.EXPLORE)

    def test_explore_datetime_has_no_find_input(self):
        self.assertNotIn('id="find"', api.EXPLORE_DATETIME)

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

    def test_panel_produces_fewer_total_lines_than_stacked(self):
        stacked = api.compose(self._request(panel=False)).text.split("\n")
        paneled = api.compose(self._request(panel=True)).text.split("\n")
        self.assertLess(len(paneled), len(stacked))

    def test_panel_places_the_zenith_label_beside_chart_content(self):
        text = api.strip_ansi(api.compose(self._request(panel=True)).text)
        zenith_line = next(l for l in text.split("\n") if "zenith 70-90" in l)
        before = zenith_line.split("zenith 70-90")[0]
        self.assertTrue(before.strip(), "expected chart content before the zenith label")

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

    def test_find_guide_also_wraps_to_the_panel_width_not_a_fixed_76(self):
        # find_text() used to ignore panel entirely, wrapping its guide
        # sentences at a fixed 76 columns even once the chart itself (see
        # _compose_find's side_panel=r.panel) had the full effective width.
        r = api.Request(place="Zurich", find="Venus",
                        when=dt.datetime(2026, 7, 30, 21, 10), panel=True)
        text = api.strip_ansi(api.compose(r).text)
        self.assertIn(
            "Face WSW and look about one fist up — a closed fist at "
            "arm's length is about 10°.",
            text,
        )


class StripFooterLine(unittest.TestCase):
    """strip_footer_line removes _footer's "Follow @habibicode..." line from
    an already-composed render -- used only by server.py's HTML branch, so
    curl/CLI output (which never calls it) keeps the invitation inline."""

    def test_removes_the_footer_line_and_collapses_the_blank_gap(self):
        # Exact marker text, including _footer's leading two-space indent --
        # api.strip_footer_line matches on the plain (uncoloured) form. The
        # blank line *before* the footer survives (it was there anyway);
        # only the footer line and the blank *after* it are removed.
        text = "\n".join(["header", "", "  Follow @habibicode for skymap.sh updates", ""])
        self.assertEqual(api.strip_footer_line(text), "header\n")

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
        # everything else in the bar is aria-hidden (see above).
        html = api.header_html("Geneva")
        self.assertIn('aria-label="City, or lat,lon"', html)

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


class HelpTextIsCurrent(unittest.TestCase):
    """HELP is free text, easy for the UI to drift out from under -- a
    handful of content checks so a future feature/shortcut change is more
    likely to also update the doc, not just leave it stale."""

    def test_mentions_every_wired_up_keyboard_shortcut(self):
        for key in ("p/tab", "f ", "m ", "esc", "a ", "g ", "d ", "z "):
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
    object is a link to /?find=<name> opened in a new tab, so browsing the
    catalog never navigates away from the chart on screen. A bare place
    (no city in the path) resolves through the visitor's own geo-IP fallback
    in the new tab, same as curl skymap.sh with no place given."""

    def test_a_star_links_to_a_bare_find_in_a_new_tab(self):
        h = api.catalog_html()
        self.assertIn('href="/?find=Sirius" target="_blank" rel="noopener"', h)

    def test_moon_link_uses_the_plain_name_not_the_phase_annotated_display(self):
        # Displayed as "Moon (waning gibbous)" or similar, but resolve_target
        # only matches the bare word "moon" -- the phase text in parens
        # would never resolve if it leaked into the href.
        import sky
        h = api.catalog_html()
        self.assertIn('href="/?find=Moon" target="_blank" rel="noopener"', h)
        age = sky.moon(sky.julian(dt.datetime.utcnow()))["age"]
        self.assertIn(f"Moon ({sky.phase_name(age)})", h)

    def test_a_multi_word_name_is_url_encoded(self):
        h = api.catalog_html()
        self.assertIn("find=Big%20Dipper", h)

    def test_a_dso_links_with_dso_and_quadrant_turned_on(self):
        h = api.catalog_html()
        # Displayed as "M31 (Andromeda Galaxy)" but the href must use the
        # canonical short id, not the whole parenthesised label.
        self.assertIn("href=\"/?find=M31&amp;dso=1&amp;quadrant\"", h)
        self.assertIn(">M31 (Andromeda Galaxy)<", h)

    def test_a_non_dso_link_does_not_carry_dso_or_quadrant(self):
        h = api.catalog_html()
        sirius_link = h[h.index('href="/?find=Sirius"'):][:120]
        self.assertNotIn("dso=1", sirius_link)
        self.assertNotIn("quadrant", sirius_link)

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
        self.assertIn("DEEP SKY (112)", text)
        self.assertIn("DEEP SKY (112)", h)


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
