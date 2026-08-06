"""The eclipse solver, checked against NASA's own published predictions.

This is the rare case where real ground truth exists: NASA/GSFC publishes,
for every eclipse, both the Besselian elements and the resulting path, and
the path is not something we can derive circularly from the elements without
implementing the whole calculation correctly. So these compare our answer to
theirs at 15 points along the track and at the point of greatest eclipse.

The fixture is coordinates and durations transcribed from
eclipse.gsfc.nasa.gov/SEpath/SEpath2001/SE2026Aug12Tpath.html -- measured
quantities from US government work, no prose, the same provenance as
eclipses.json.

Why this matters more than usual: an eclipse page states times to the minute
and coverage to the percent, and a reader has no way to sanity-check either.
A wrong number here is invisible until someone stands outside at the time we
printed and the Sun is still whole.
"""
import math
import unittest

import besselian

KEY = "2026-08-12"

# UT of the central-line point, its latitude and longitude, the path width in
# km, and the duration of totality on the central line in seconds.
NASA_PATH = [
    ("17:02",   82.2750,   112.4867,  273,  105.8),
    ("17:08",   87.8233,    33.0000,  275,  117.7),
    ("17:14",   83.9317,   -21.1867,  276,  124.9),
    ("17:20",   79.7733,   -26.9817,  278,  130.0),
    ("17:26",   76.0183,   -27.9283,  280,  133.7),
    ("17:32",   72.5567,   -27.6033,  283,  136.2),
    ("17:38",   69.2983,   -26.7600,  288,  137.7),
    ("17:44",   66.1850,   -25.6300,  292,  138.2),
    ("17:50",   63.1717,   -24.2867,  298,  137.9),
    ("17:56",   60.2217,   -22.7367,  304,  136.6),
    ("18:02",   57.2967,   -20.9467,  309,  134.5),
    ("18:08",   54.3617,   -18.8467,  315,  131.3),
    ("18:14",   51.3600,   -16.3033,  319,  127.0),
    ("18:20",   48.2117,   -13.0483,  319,  121.2),
    ("18:26",   44.7133,    -8.3983,  311,  113.0),
]

# NASA's "Circumstances at Greatest Eclipse" block for this eclipse.
GREATEST = dict(ut="17:45:51", lat=65.2, lon=-25.2, sun_alt=25.8,
                path_width=293.9, duration=138.0, magnitude=1.0386)

_KM_PER_DEG = 111.195


def _ut_hours(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) + int(m) / 60.0


class TheCentralLineMatchesNASA(unittest.TestCase):
    """Every point NASA puts on the central line has to come out total here,
    for as long as NASA says. Fifteen independent checks of the same maths."""

    def test_every_central_line_point_is_total(self):
        for ut, lat, lon, _w, _d in NASA_PATH:
            c = besselian.local(KEY, lat, lon)
            self.assertEqual(c["kind"], "total", f"{ut} {lat},{lon}")

    def test_duration_on_the_central_line(self):
        """Within two seconds of NASA, on durations around 130 s."""
        for ut, lat, lon, _w, nasa in NASA_PATH:
            ours = besselian.duration_seconds(besselian.local(KEY, lat, lon))
            self.assertIsNotNone(ours, ut)
            self.assertLess(abs(ours - nasa), 2.0,
                            f"{ut}: ours {ours:.1f}s vs NASA {nasa:.1f}s")

    def test_maximum_happens_when_nasa_says(self):
        """The tabulated time is when the axis passes that point, so our
        computed maximum has to land on it. Ten seconds of slack because the
        table's coordinates are given to a tenth of an arcminute and the
        first rows sit near the pole, where that is a long way."""
        for ut, lat, lon, _w, _d in NASA_PATH:
            c = besselian.local(KEY, lat, lon)
            self.assertLess(abs(c["maximum"] - _ut_hours(ut)) * 3600, 10.0, ut)

    def test_obscuration_is_total_where_the_eclipse_is(self):
        # Caught a real bug: the Sun's and Moon's radii in the fundamental
        # plane were the wrong way round, which reported a total eclipse as
        # 93% covered. Everything else still looked right.
        for ut, lat, lon, _w, _d in NASA_PATH:
            c = besselian.local(KEY, lat, lon)
            self.assertAlmostEqual(c["obscuration"], 1.0, places=6, msg=ut)


class ThePathIsTheRightWidth(unittest.TestCase):
    """Durations alone could in principle be matched by an umbra of the wrong
    size in the wrong place. The width is the independent check on that, and
    it is measured the way a person would: walk across the track until
    totality stops."""

    def _width_km(self, i):
        _ut, lat, lon, nasa_w, _d = NASA_PATH[i]
        (_, la0, lo0, _, _), (_, la1, lo1, _, _) = NASA_PATH[i - 1], NASA_PATH[i + 1]
        dx = (lo1 - lo0) * math.cos(math.radians(lat))
        dy = la1 - la0
        n = math.hypot(dx, dy)
        px, py = -dy / n, dx / n                       # across the track
        hits = []
        for step in range(-800, 801):
            s = step * 0.25                            # 250 m
            dlat = py * s / _KM_PER_DEG
            dlon = px * s / (_KM_PER_DEG * math.cos(math.radians(lat)))
            if besselian.duration_seconds(
                    besselian.local(KEY, lat + dlat, lon + dlon)):
                hits.append(s)
        return (max(hits) - min(hits)) if hits else 0.0, nasa_w

    def test_width_agrees_with_nasa(self):
        # Mid-path only. The first rows are within a few degrees of the pole,
        # where "perpendicular to the track" stops being a useful idea and
        # this measurement, not the solver, is what breaks down.
        for i in (5, 8, 11, 13):
            ours, nasa = self._width_km(i)
            self.assertLess(abs(ours - nasa), 6.0,
                            f"row {i}: ours {ours:.1f} km vs NASA {nasa} km")


class GreatestEclipseMatchesNASA(unittest.TestCase):

    def test_it_is_total_there(self):
        c = besselian.local(KEY, GREATEST["lat"], GREATEST["lon"])
        self.assertEqual(c["kind"], "total")

    def test_duration_and_time(self):
        c = besselian.local(KEY, GREATEST["lat"], GREATEST["lon"])
        d = besselian.duration_seconds(c)
        self.assertLess(abs(d - GREATEST["duration"]), 2.0)
        want = _ut_hours(GREATEST["ut"]) + int(GREATEST["ut"][6:]) / 3600.0
        self.assertLess(abs(c["maximum"] - want) * 3600, 15.0)

    def test_the_diameter_ratio_is_nasas_eclipse_magnitude(self):
        """The check that proved the geometry rather than merely the timing.

        NASA's headline "Eclipse Magnitude = 1.0386" for a central eclipse is
        the ratio of the two apparent diameters, which is a different
        quantity from the magnitude in local circumstances (1.0174 here).
        Reproducing it to four figures means L1, L2 and the projection of
        the observer onto the fundamental plane are all right, none of which
        the duration alone would prove."""
        r = besselian.diameter_ratio(KEY, GREATEST["lat"], GREATEST["lon"])
        self.assertAlmostEqual(r, GREATEST["magnitude"], places=4)


class ItRefusesToGuess(unittest.TestCase):

    def test_an_eclipse_with_no_elements_raises(self):
        # The entire reason for this file is to stop producing confident
        # numbers from an ephemeris that cannot support them. Silently
        # falling back to anything would undo that.
        #
        # A lunar date, deliberately: these elements are a solar
        # construction and no lunar eclipse will ever be in this table.
        # The date this used to name, 2027-08-02, has elements now.
        with self.assertRaises(KeyError):
            besselian.local("2026-08-28", 47.0, 8.0)

    def test_every_solar_eclipse_in_the_table_has_elements(self):
        """The page 500ed for every eclipse but one, because the table had
        a single hand-typed entry. Fetching them is build_besselian.py's
        job; this is what notices when it has not been re-run."""
        import json
        rows = [e for e in json.load(open("eclipses.json")) if "when_utc" in e]
        for e in rows:
            if "solar" in e["type"]:
                self.assertIn(e["when_utc"][:10], besselian.ELEMENTS, e["name"])

    def test_a_place_nowhere_near_it_sees_nothing(self):
        # Mid-Pacific, the far side of the planet from the shadow.
        c = besselian.local(KEY, -30.0, -150.0)
        self.assertEqual(c["kind"], "none")
        self.assertEqual(c["obscuration"], 0.0)
        self.assertIsNone(c["maximum"])


class TheEdgeIsNotPromised(unittest.TestCase):
    """Places within a few km of the limit are inside the uncertainty of the
    prediction itself, and the page must not claim them either way."""

    def test_madrid_is_reported_as_too_close_to_call(self):
        # Computes as total by ~15 s; most published maps put it just
        # outside. Both are inside the lunar-limb uncertainty.
        c = besselian.local(KEY, 40.4168, -3.7038)
        self.assertTrue(besselian.on_the_edge(c))

    def test_a_place_well_inside_is_not_flagged(self):
        c = besselian.local(KEY, 43.3619, -5.8494)      # Oviedo, ~106 s
        self.assertEqual(c["kind"], "total")
        self.assertFalse(besselian.on_the_edge(c))

    def test_a_place_well_outside_is_not_flagged(self):
        c = besselian.local(KEY, 47.3769, 8.5417)       # Zurich, ~90%
        self.assertEqual(c["kind"], "partial")
        self.assertFalse(besselian.on_the_edge(c))


class TheFarSideOfTheEarthSeesNothing(unittest.TestCase):
    """The shadow axis passes through the Earth and comes out the other
    side, where (u, v) goes small again and the projection will cheerfully
    report totality. Only the sign of zeta distinguishes the two.

    This shipped broken and every point test in this file passed. It
    surfaced when the whole grid was drawn for the map and a second red
    streak appeared across the Mediterranean, which is the argument for
    computing the map from the same numbers rather than tracing it."""

    def test_places_where_the_sun_is_down_see_no_eclipse(self):
        for name, lat, lon in (("Greece", 36.80, 22.45),
                               ("Tunisia", 36.80, 10.05),
                               ("Tokyo", 35.6762, 139.6503),
                               ("Sydney", -33.87, 151.21)):
            c = besselian.local(KEY, lat, lon)
            self.assertEqual(c["kind"], "none", name)
            self.assertEqual(c["obscuration"], 0.0, name)
            self.assertIsNone(c["maximum"], name)

    def test_the_mediterranean_carries_no_second_track(self):
        # The shape of the bug, asserted directly: nowhere south of the
        # Pyrenees and east of Italy is in this eclipse at all.
        for lat in (34.0, 36.0, 38.0):
            for lon in range(8, 30, 2):
                c = besselian.local(KEY, lat, float(lon))
                self.assertNotEqual(c["kind"], "total", (lat, lon))


class SunsetDuringTheEclipse(unittest.TestCase):
    """Most of the audience for this one watches it low in the west, and
    some of them lose the Sun before it ends."""

    def test_zurich_loses_the_sun_partway_through(self):
        c = besselian.local(KEY, 47.3769, 8.5417)
        self.assertEqual(c["kind"], "partial")
        self.assertTrue(c["sun_up_at_first"])
        self.assertFalse(c["sun_up_at_last"])
        self.assertTrue(c["sun_set_during"])

    def test_iceland_keeps_it_throughout(self):
        c = besselian.local(KEY, 64.15, -21.94)
        self.assertTrue(c["sun_up_at_first"])
        self.assertTrue(c["sun_up_at_last"])
        self.assertFalse(c["sun_set_during"])


if __name__ == "__main__":
    unittest.main()
