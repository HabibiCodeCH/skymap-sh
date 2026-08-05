"""Tests for objects.py and the four catalogue files behind it.

The constellation test is the load-bearing one: it checks our boundary lookup
against BSC5's own constellation assignment for every star that carries one,
which is 2,121 independent cases rather than a handful of hand-picked vectors.
"""
import datetime as dt
import json
import math

import pytest

import objects
import sky

ZURICH = (47.38, 8.54)
WHEN = dt.datetime(2026, 8, 5)


def _target(name, lat=ZURICH[0], lon=ZURICH[1], when=WHEN):
    jd = sky.julian(when)
    return sky.resolve_target(name, jd, lat, (sky.gmst_hours(jd) + lon / 15.0) % 24)


# ---------------------------------------------------------- constellations
def test_constellation_agrees_with_bsc5_for_every_star():
    """The whole catalogue, not a sample. BSC5 records which constellation
    each star belongs to; we derive it from the IAU boundaries. They should
    never disagree, and if they do the boundary scan or the precession is
    wrong."""
    stars = [s for s in sky._load("stars.json") if s.get("c")]
    assert len(stars) > 2000, "expected the bright-star catalogue to be loaded"
    bad = [(s.get("n") or s["hr"], s["c"], objects.constellation(s["ra"], s["de"]))
           for s in stars
           if (objects.constellation(s["ra"], s["de"]) or "").lower() != s["c"].lower()]
    assert not bad, f"{len(bad)} stars in the wrong constellation, e.g. {bad[:5]}"


@pytest.mark.parametrize("ra_h, dec, want", [
    (5.919, 7.407, "Ori"),      # Betelgeuse
    (6.752, -16.716, "CMa"),    # Sirius
    (18.615, 38.784, "Lyr"),    # Vega
    (2.530, 89.264, "UMi"),     # Polaris, hard case: precession near the pole
    (0.712, 41.269, "And"),     # M31
])
def test_constellation_known_objects(ra_h, dec, want):
    assert objects.constellation(ra_h, dec) == want


def test_constellation_covers_the_whole_sphere():
    """The boundaries tile the sky, so no position may come back None."""
    misses = [(ra, dec)
              for ra in [h * 0.5 for h in range(48)]
              for dec in range(-89, 90, 7)
              if objects.constellation(ra, dec) is None]
    assert not misses, f"{len(misses)} positions fell outside every boundary"


def test_boundary_table_order_is_preserved():
    """Roman's arrangement is scanned top down and the first match wins, so
    the file must stay in its original order. Sorting it would silently give
    wrong answers rather than fail, which is why this is a test."""
    rows = sky._load("constellations.json")
    assert len(rows) > 300
    decs = [r[2] for r in rows]
    assert decs != sorted(decs), "boundary file looks sorted; the lookup needs source order"
    assert decs[0] > decs[-1], "expected the table to run north to south"


# ------------------------------------------------------------- star extras
def test_starinfo_covers_the_chart():
    info = sky._load("starinfo.json")
    stars = sky._load("stars.json")
    assert len(info) > 2000
    # Every key must be a star we actually draw; a stray HR number means the
    # join in build_starinfo.py drifted.
    known = {str(s["hr"]) for s in stars}
    assert set(info) <= known


def test_every_starinfo_row_has_something_worth_having():
    for hr, rec in sky._load("starinfo.json").items():
        assert rec, f"HR {hr} has an empty record"
        assert set(rec) <= {"sp", "ly", "ly_err", "sep", "dmag", "var"}
        # Distance and its error travel together or not at all.
        assert ("ly" in rec) == ("ly_err" in rec)


@pytest.mark.parametrize("name, low, high", [
    ("Sirius", 8.0, 9.5),
    ("Vega", 24.0, 27.0),
    ("Arcturus", 34.0, 40.0),
    ("Aldebaran", 60.0, 70.0),
])
def test_known_star_distances(name, low, high):
    """Nearby stars have parallaxes good to a fraction of a percent, so these
    should land on the published values."""
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == name)
    got = objects.distance_ly(hr)
    assert got is not None, f"no distance for {name}"
    assert low <= got[0] <= high, f"{name}: {got[0]} ly outside {low}-{high}"
    assert got[1] == "good"


def test_distant_stars_are_flagged_as_uncertain():
    """Deneb's parallax carries a 56% error. The point of shipping the error
    is that the page can decline to state a figure, so this must not come
    back as 'good'."""
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == "Deneb")
    got = objects.distance_ly(hr)
    if got is not None:                       # absent is also an acceptable answer
        assert got[1] != "good"


def test_spectral_types_look_like_spectral_types():
    info = sky._load("starinfo.json")
    sp = [r["sp"] for r in info.values() if "sp" in r]
    assert len(sp) > 2000
    # Harvard classes, plus the older Yerkes luminosity prefixes BSC5 still
    # carries for 37 stars -- "gK4" is a K4 giant, "sgG9" a G9 subgiant,
    # "dF5" a dwarf, "cK2" a supergiant. Anything rendering the spectral type
    # has to strip those before reading the class off the front.
    lead = "OBAFGKMSCRNWD+pe" + "gsdc"
    odd = [s for s in sp if s[0] not in lead]
    assert not odd, f"unexpected leading character: {odd[:5]}"


def test_star_info_is_empty_not_an_error_for_unknown_hr():
    assert objects.star_info(999999) == {}
    assert objects.variable_info(999999) == {}
    assert objects.distance_ly(999999) is None


# --------------------------------------------------------------- variables
def test_algol_period():
    """Algol is the reason this file exists: a 2.867-day eclipsing binary
    whose next minimum is fully predictable."""
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == "Algol")
    rec = objects.variable_info(hr)
    assert rec.get("period") == pytest.approx(2.8673, abs=1e-3)
    assert rec.get("max") == pytest.approx(2.12, abs=0.05)
    assert rec.get("min") == pytest.approx(3.39, abs=0.05)


def test_variables_are_all_stars_we_draw():
    known = {str(s["hr"]) for s in sky._load("stars.json")}
    assert set(sky._load("variables.json")) <= known


def test_variable_ranges_are_the_right_way_round():
    """max is the brightest magnitude, min the faintest, so numerically
    max < min. Getting these backwards would invert every range on the site."""
    for hr, rec in sky._load("variables.json").items():
        if "max" in rec and "min" in rec:
            assert rec["max"] <= rec["min"], f"HR {hr} range inverted"


def test_amplitudes_are_not_stored_as_minima():
    """GCVS puts the amplitude of the variation in the same column as the
    magnitude at minimum, distinguished only by a flag. Misreading one as the
    other made Epsilon Eridani vary between magnitude 3.73 and 0.05, which
    would be the brightest object in the night sky."""
    v = sky._load("variables.json")
    assert any("amp" in r for r in v.values()), "no amplitudes recorded at all"
    for hr, rec in v.items():
        # An amplitude is a difference, so it is small; a minimum magnitude
        # for anything in this catalogue is not.
        if "amp" in rec:
            assert rec["amp"] < 12, f"HR {hr} amplitude {rec['amp']} looks like a magnitude"
        assert not ("amp" in rec and "min" in rec), f"HR {hr} has both"


def test_epsilon_eridani_amplitude_specifically():
    """The star that exposed the bug."""
    hr = next((s["hr"] for s in sky._load("stars.json")
               if s.get("n") == "Epsilon Eridani"), None)
    if hr is None:
        pytest.skip("Epsilon Eridani not in stars.json under that name")
    rec = objects.variable_info(hr)
    assert "min" not in rec, "0.05 must not be recorded as a minimum magnitude"


# -------------------------------------------------------------- deep sky
def test_dso_sizes_land_on_the_right_objects():
    """deepsky.json's name field is not unique -- NGC205 is labelled M31 and
    NGC595 is labelled M33 -- so a size joined by name alone lands on the
    wrong object. M31 must be the big one."""
    assert objects.dso_size("NGC224").get("maj") == pytest.approx(178.0)
    assert objects.dso_size("NGC205").get("maj") == pytest.approx(17.0)
    assert objects.dso_size("NGC598").get("maj") == pytest.approx(73.0)


def test_dso_sizes_reference_real_objects():
    known = {o["id"] for o in sky._load("deepsky.json")}
    assert set(sky._load("dsoinfo.json")) <= known


def test_dso_minor_axis_never_exceeds_major():
    for oid, rec in sky._load("dsoinfo.json").items():
        if "min" in rec:
            assert rec["min"] <= rec["maj"], f"{oid} minor axis larger than major"


def test_dso_size_is_empty_not_an_error_for_unknown_id():
    assert objects.dso_size("NGC999999") == {}


# -------------------------------------------------- rise, transit and set
def test_sun_rise_and_set_agree_with_sky_py():
    """sky.py samples the Sun's arc at ten-minute steps and interpolates;
    this is closed form. They should land within a couple of minutes, and a
    larger gap means one of them is wrong."""
    mine = objects.rise_transit_set(_target("Sun"), *ZURICH, WHEN)
    theirs = sky.sun_events(WHEN, *ZURICH)
    for ours, name in ((mine["rise"], "sunrise"), (mine["set"], "sunset")):
        gap = abs((ours - theirs[name]).total_seconds()) / 60
        assert gap < 5, f"{name} differs by {gap:.1f} minutes"


def test_transit_altitude_is_the_geometric_one():
    """An object's greatest altitude is 90 - |latitude - declination|,
    exactly. Anything else means the transit search drifted."""
    for name in ("Sirius", "Vega", "M31"):
        t = _target(name)
        got = objects.rise_transit_set(t, *ZURICH, WHEN)
        want = 90.0 - abs(ZURICH[0] - t["dec"])
        assert got["transit_alt"] == pytest.approx(want, abs=0.6)


def test_rise_and_set_straddle_transit():
    got = objects.rise_transit_set(_target("Sirius"), *ZURICH, WHEN)
    assert got["rise"] < got["transit"] < got["set"]
    assert got["up_hours"] == pytest.approx(
        (got["set"] - got["rise"]).total_seconds() / 3600, abs=0.05)


@pytest.mark.parametrize("name, lat, expect", [
    ("Polaris", 70, "circumpolar"),
    ("Polaris", -33, "never_rises"),
    ("Southern Cross", 47.38, "never_rises"),
    ("Southern Cross", -33, "circumpolar"),
])
def test_circumpolar_and_never_rising(name, lat, expect):
    """At extreme latitudes half the catalogue is one or the other, and these
    are answers rather than errors."""
    got = objects.rise_transit_set(_target(name, lat=lat), lat, 8.54, WHEN)
    assert got.get(expect) is True
    assert "transit" in got, "a transit time is still meaningful either way"


@pytest.mark.parametrize("date, expect", [
    (dt.datetime(2026, 6, 21), "circumpolar"),      # midnight sun
    (dt.datetime(2026, 12, 21), "never_rises"),     # polar night
])
def test_arctic_sun(date, expect):
    lat, lon = 69.6, 18.96                           # Tromso
    got = objects.rise_transit_set(_target("Sun", lat=lat, lon=lon, when=date),
                                    lat, lon, date)
    assert got.get(expect) is True


# ------------------------------------------------------ best night of year
def test_best_night_lands_in_the_right_season():
    """Andromeda is an autumn object from the northern hemisphere and Orion a
    winter one. If these drift into the wrong half of the year the scan is
    weighting something incorrectly."""
    m31 = objects.best_this_year(_target("M31"), *ZURICH, WHEN)
    assert m31["when_utc"].month in (9, 10, 11, 12)
    orion = objects.best_this_year(_target("Orion Nebula"), *ZURICH, WHEN)
    assert orion["when_utc"].month in (11, 12, 1, 2)


def test_best_night_prefers_a_dark_moon():
    """Moonlight is the discount in the score, so the winner should never be
    a night with a bright Moon when a darker one was available."""
    for name in ("M31", "M13", "Orion Nebula"):
        got = objects.best_this_year(_target(name), *ZURICH, WHEN)
        assert got["moon_illum"] < 0.35, f"{name} chose a moonlit night"


def test_best_night_is_none_when_never_visible():
    assert objects.best_this_year(_target("Southern Cross"), *ZURICH, WHEN) is None


def test_best_night_skipped_for_sun_and_moon():
    for name in ("Sun", "Moon"):
        assert objects.best_this_year(_target(name), *ZURICH, WHEN) is None


def test_best_night_is_cheap():
    """Closed form per night, not a sampled sky. The naive version costs
    about 200 ms, seven times the most expensive thing the service does."""
    import time
    t = _target("M31")
    start = time.perf_counter()
    objects.best_this_year(t, *ZURICH, WHEN)
    assert (time.perf_counter() - start) < 0.05


# ----------------------------------------------------------- planet facts
def test_planet_apparent_sizes_are_plausible():
    """Ranges a planet's disc actually spans, seen from Earth."""
    jd = sky.julian(WHEN)
    lst = (sky.gmst_hours(jd) + ZURICH[1] / 15.0) % 24
    bounds = {"Mercury": (4, 14), "Venus": (9, 67), "Mars": (3, 26),
              "Jupiter": (29, 51), "Saturn": (14, 21),
              "Uranus": (3, 4.2), "Neptune": (2, 2.5)}
    for name, (lo, hi) in bounds.items():
        got = objects.planet_facts(name, jd, ZURICH[0], lst)["apparent_arcsec"]
        assert lo <= got <= hi, f"{name} {got} arcsec outside {lo}-{hi}"


def test_outer_planets_are_always_nearly_full():
    jd = sky.julian(WHEN)
    lst = (sky.gmst_hours(jd) + ZURICH[1] / 15.0) % 24
    for name in ("Jupiter", "Saturn", "Uranus", "Neptune"):
        assert objects.planet_facts(name, jd, ZURICH[0], lst)["illuminated"] > 0.95


def test_inner_planets_stay_near_the_sun():
    """Mercury never gets more than about 28 degrees from the Sun and Venus
    never more than about 47. A larger elongation means the angle is being
    computed in the wrong frame -- which is exactly what using sky.planet()'s
    'elon' field (heliocentric longitude) instead would produce."""
    for name, limit in (("Mercury", 30), ("Venus", 48)):
        worst = max(
            objects.planet_facts(name, sky.julian(WHEN + dt.timedelta(days=d)),
                                  ZURICH[0], 0.0)["elongation"]
            for d in range(0, 400, 5))
        assert worst <= limit, f"{name} reached {worst} degrees from the Sun"


def test_saturn_rings_open_after_the_2025_crossing():
    """2025 was a ring-plane crossing, so the rings were edge-on and all but
    invisible. They widen from there towards a maximum near 27 degrees."""
    angles = [objects.planet_facts("Saturn", sky.julian(dt.datetime(y, 8, 5)),
                                    ZURICH[0], 0.0)["ring_angle"]
              for y in (2025, 2026, 2027, 2029, 2032)]
    assert angles[0] < 6, "should be nearly edge-on just after the crossing"
    assert angles == sorted(angles), "should open steadily over these years"
    assert max(angles) < 28, "cannot open wider than the tilt allows"


def test_light_minutes_match_the_distance():
    jd = sky.julian(WHEN)
    f = objects.planet_facts("Saturn", jd, ZURICH[0], 0.0)
    assert f["light_minutes"] == pytest.approx(f["distance_au"] * 8.3167, rel=0.01)


# ------------------------------------------------------- spectra and variables
@pytest.mark.parametrize("name, want", [
    ("Betelgeuse", "red supergiant"),
    ("Vega", "white main-sequence star"),
    ("Arcturus", "orange giant"),
    ("Rigel", "blue-white supergiant"),
    ("Aldebaran", "orange giant"),
])
def test_spectral_descriptions(name, want):
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == name)
    assert objects.describe_spectrum(objects.star_info(hr).get("sp")) == want


@pytest.mark.parametrize("sp", ["", None, "?", "Xq"])
def test_unreadable_spectra_say_nothing(sp):
    """A wrong description of a star is worse than no description."""
    assert objects.describe_spectrum(sp) is None


def test_yerkes_prefix_notation():
    """BSC5 still uses the old prefixes for a few dozen stars: gK4 is a K4
    giant, not a star of class 'g'."""
    assert objects.describe_spectrum("gK4") == "orange giant"
    assert objects.describe_spectrum("sgG9") == "yellow subgiant"
    assert objects.describe_spectrum("dF5") == "yellow-white main-sequence star"


def test_algol_minima_are_one_period_apart():
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == "Algol")
    period = objects.variable_info(hr)["period"]
    first = objects.next_minimum(hr, WHEN)
    assert first is not None and first > WHEN
    second = objects.next_minimum(hr, first + dt.timedelta(minutes=1))
    gap = (second - first).total_seconds() / 86400
    assert gap == pytest.approx(period, abs=1e-3)


def test_pulsating_variables_get_no_minimum():
    """The GCVS epoch marks maximum light for pulsating stars, so reporting
    it as a minimum would be wrong in a way nobody would notice."""
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == "Betelgeuse")
    assert objects.next_minimum(hr, WHEN) is None


def test_next_minimum_is_none_for_ordinary_stars():
    hr = next(s["hr"] for s in sky._load("stars.json") if s.get("n") == "Vega")
    assert objects.next_minimum(hr, WHEN) is None


# ------------------------------------------------------------ file hygiene
@pytest.mark.parametrize("name", ["constellations.json", "starinfo.json",
                                   "variables.json", "dsoinfo.json"])
def test_catalogue_files_are_compact(name):
    """These ship in the repo and are read on every cold start; a
    pretty-printed rewrite would bloat them for no gain."""
    raw = open(f"{sky.BASE}/{name}").read()
    assert ", " not in raw[:2000], f"{name} looks pretty-printed"
    json.loads(raw)
