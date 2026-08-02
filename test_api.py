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
