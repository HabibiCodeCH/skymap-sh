"""Tests for events.py.

Where a published value exists it is asserted against, with a tolerance that
matches what sky.py's series can actually deliver: about an hour on a moon
phase, twenty minutes on an equinox. Tightening these past the ephemeris would
be testing the noise.
"""
import datetime as dt
import json

import pytest

import events
from events import from_julian, julian


# ---------------------------------------------------------------- time
@pytest.mark.parametrize("when", [
    dt.datetime(2000, 1, 1, 12, 0),
    dt.datetime(2026, 8, 12, 23, 0),
    dt.datetime(2026, 2, 28, 0, 0),
    dt.datetime(2028, 2, 29, 6, 30),      # leap day
    dt.datetime(2026, 12, 31, 23, 59, 59),
])
def test_julian_round_trip(when):
    assert abs((from_julian(julian(when)) - when).total_seconds()) < 1


def test_from_julian_rounding_rolls_the_date():
    """23:59:59.7 must become the next day, not hour 24."""
    jd = julian(dt.datetime(2026, 8, 12, 23, 59, 59)) + 0.7 / 86400
    assert from_julian(jd) == dt.datetime(2026, 8, 13, 0, 0, 0)


# ---------------------------------------------------------------- moon phases
def _find(evs, kind, name=None, on=None):
    for e in evs:
        if e["kind"] != kind:
            continue
        if name and e["name"] != name:
            continue
        if on and e["when_utc"].date() != on:
            continue
        return e
    return None


def test_moon_phases_against_published_times():
    """Published: New Moon 12 Aug 2026 17:37 UTC, Full Moon 28 Aug 2026 04:18 UTC."""
    evs = events.scan_global(dt.datetime(2026, 8, 1), 40)
    new = _find(evs, "moon_phase", "New Moon", dt.date(2026, 8, 12))
    full = _find(evs, "moon_phase", "Full Moon", dt.date(2026, 8, 28))
    assert new and full
    assert abs((new["when_utc"] - dt.datetime(2026, 8, 12, 17, 37)).total_seconds()) < 3600
    assert abs((full["when_utc"] - dt.datetime(2026, 8, 28, 4, 18)).total_seconds()) < 3600


def test_all_four_phases_appear_once_per_lunation():
    evs = events.scan_global(dt.datetime(2026, 1, 1), 29)
    got = [e["name"] for e in evs if e["kind"] == "moon_phase"]
    assert sorted(got) == sorted(set(got)), "a phase was found twice in one lunation"
    assert len(got) == 4


def test_phases_are_in_order_and_evenly_spaced():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 120)
           if e["kind"] == "moon_phase"]
    gaps = [(b["when_utc"] - a["when_utc"]).total_seconds() / 86400
            for a, b in zip(evs, evs[1:])]
    # A quarter of a synodic month is 7.38 days; the real spacing wobbles
    # either side of that because the Moon's orbit is eccentric.
    assert all(6.3 < g < 8.5 for g in gaps), gaps


def test_illumination_matches_the_phase():
    evs = events.scan_global(dt.datetime(2026, 1, 1), 40)
    assert _find(evs, "moon_phase", "New Moon")["illum"] <= 1
    assert _find(evs, "moon_phase", "Full Moon")["illum"] >= 99
    assert 48 <= _find(evs, "moon_phase", "First quarter Moon")["illum"] <= 52


# ---------------------------------------------------------------- seasons
def test_equinox_against_published_time():
    """Published: September equinox 2026 at 23 Sep 00:05 UTC."""
    evs = events.scan_global(dt.datetime(2026, 9, 1), 40)
    eq = _find(evs, "season", "September equinox")
    assert eq
    assert abs((eq["when_utc"] - dt.datetime(2026, 9, 23, 0, 5)).total_seconds()) < 1200


def test_four_seasons_in_a_year_in_order():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 366)
           if e["kind"] == "season"]
    assert [e["name"] for e in evs] == [
        "March equinox", "June solstice", "September equinox", "December solstice"]


def test_no_phantom_crossing_at_the_antipode():
    """The wrap guard in _crossings: a full year must give exactly four
    seasons, not eight. Without it every cycle produces a fake sign change
    halfway round."""
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 366)
           if e["kind"] == "season"]
    assert len(evs) == 4


# ---------------------------------------------------------------- conjunctions
def test_conjunction_separation_is_really_the_minimum():
    evs = [e for e in events.scan_global(dt.datetime(2026, 8, 1), 120)
           if e["kind"] == "conjunction"]
    assert evs, "no conjunctions found in four months, which cannot be right"
    for e in evs:
        jd = julian(e["when_utc"])
        here = events._separation(*e["bodies"], jd)
        # Nothing within half a day either side may be closer.
        for off in (-0.5, -0.2, 0.2, 0.5):
            assert events._separation(*e["bodies"], jd + off) >= here - 0.05


def test_conjunctions_respect_the_separation_limit():
    evs = [e for e in events.scan_global(dt.datetime(2026, 8, 1), 200)
           if e["kind"] == "conjunction"]
    for e in evs:
        limit = (events.CONJ_MAX_SEP_MOON if "Moon" in e["bodies"]
                 else events.CONJ_MAX_SEP)
        assert e["sep_deg"] <= limit


def test_daylight_conjunctions_are_dropped():
    """Both bodies must be far enough from the Sun to be seeable at all."""
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 365)
           if e["kind"] == "conjunction"]
    for e in evs:
        jd = julian(e["when_utc"])
        for b in e["bodies"]:
            assert abs(events._elongation(b, jd)) >= events.MIN_ELONGATION


# ---------------------------------------------------------------- elongations
def test_venus_greatest_elongation_is_a_turning_point():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 365)
           if e["kind"] == "elongation" and e["body"] == "Venus"]
    assert evs
    for e in evs:
        jd = julian(e["when_utc"])
        here = abs(events._elongation("Venus", jd))
        assert here > abs(events._elongation("Venus", jd - 5))
        assert here > abs(events._elongation("Venus", jd + 5))
        # Venus never gets further than about 47 degrees from the Sun.
        assert 40 < e["sep_deg"] < 48


def test_mercury_elongation_stays_under_29_degrees():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 365)
           if e["kind"] == "elongation" and e["body"] == "Mercury"]
    assert evs
    assert all(17 < e["sep_deg"] < 29 for e in evs), [e["sep_deg"] for e in evs]


# ---------------------------------------------------------------- oppositions
def test_opposition_puts_the_planet_opposite_the_sun():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 365)
           if e["kind"] == "opposition"]
    assert evs
    for e in evs:
        jd = julian(e["when_utc"])
        assert abs(abs(events._elongation(e["body"], jd)) - 180) < 0.5


# ---------------------------------------------------------------- showers
def test_perseid_peak_lands_in_mid_august():
    evs = events.scan_global(dt.datetime(2026, 7, 1), 90)
    p = _find(evs, "meteor_shower", "Perseids")
    assert p
    assert p["when_utc"].month == 8 and 11 <= p["when_utc"].day <= 14


def test_every_shower_fires_once_a_year():
    evs = [e for e in events.scan_global(dt.datetime(2026, 1, 1), 365)
           if e["kind"] == "meteor_shower"]
    names = [e["name"] for e in evs]
    table = [s["name"] for s in json.load(open(f"{events.BASE}/showers.json"))]
    assert sorted(names) == sorted(table)


@pytest.mark.parametrize("name,start,days,published", [
    ("Perseids",  dt.datetime(2026, 7, 1), 90, dt.datetime(2026, 8, 13, 3, 0)),
    ("Geminids",  dt.datetime(2026, 11, 1), 60, dt.datetime(2026, 12, 14, 14, 0)),
    ("Leonids",   dt.datetime(2026, 11, 1), 60, dt.datetime(2026, 11, 17, 23, 45)),
    ("Lyrids",    dt.datetime(2026, 4, 1), 40, dt.datetime(2026, 4, 22, 19, 40)),
    ("Draconids", dt.datetime(2026, 9, 20), 40, dt.datetime(2026, 10, 9, 1, 0)),
    ("Ursids",    dt.datetime(2026, 12, 1), 40, dt.datetime(2026, 12, 22, 22, 0)),
])
def test_shower_peak_times_match_the_imo_calendar(name, start, days, published):
    """Against the IMO 2026 Meteor Shower Calendar working list.

    The tolerance is 90 minutes, which is the guard that matters: the
    published solar longitudes are referenced to equinox J2000.0 while
    sky.py's sun() returns longitude of date. Ignoring the 0.36° between them
    put every peak nine to ten hours early -- the wrong night, not the wrong
    hour. Anything that reintroduces that blows straight through this.
    """
    e = _find(events.scan_global(start, days), "meteor_shower", name)
    assert e, f"{name} not found"
    off = abs((e["when_utc"] - published).total_seconds()) / 60
    assert off < 90, f"{name} off by {off:.0f} min ({e['when_utc']} vs {published})"


def test_shower_peaks_drift_with_solar_longitude_not_the_calendar():
    """Storing solar longitude is the whole point: the same shower must come
    back at nearly, but not exactly, the same date in a later year."""
    a = _find(events.scan_global(dt.datetime(2026, 7, 1), 90), "meteor_shower", "Perseids")
    b = _find(events.scan_global(dt.datetime(2029, 7, 1), 90), "meteor_shower", "Perseids")
    delta_hours = abs((b["when_utc"].replace(year=2026) - a["when_utc"]).total_seconds()) / 3600
    assert delta_hours < 36


# ---------------------------------------------------------------- localisation
ZURICH = (47.38, 8.54, 2)
SYDNEY = (-33.87, 151.21, 10)
TROMSO = (69.65, 18.96, 2)
NAIROBI = (-1.29, 36.82, 3)


def test_perseid_radiant_is_high_from_zurich():
    evs = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=30)
    p = _find(evs, "meteor_shower", "Perseids")
    assert p["visible"] is True
    assert p["alt"] > 50                     # dec +58 from lat +47
    assert p["compass"] in ("N", "NNE", "NE", "ENE")


def test_perseid_radiant_never_rises_from_sydney():
    """Radiant at dec +58 from latitude -34: it is below the horizon always,
    and saying so is more use than silently dropping the event."""
    evs = events.upcoming(*SYDNEY, now_utc=dt.datetime(2026, 8, 1), days=30)
    p = _find(evs, "meteor_shower", "Perseids")
    assert p["visible"] is False
    assert "horizon" in p["reason"]


def test_no_astronomical_darkness_in_a_northern_august():
    """Tromsø in August: the Sun never gets more than about 5° below the
    horizon, so there is no shower to watch whatever the radiant does."""
    evs = events.upcoming(*TROMSO, now_utc=dt.datetime(2026, 8, 1), days=30)
    p = _find(evs, "meteor_shower", "Perseids")
    assert p["visible"] is False


def test_geminids_work_from_both_hemispheres():
    """Dec +33 is high from Zürich and low but real from Sydney."""
    z = _find(events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 12, 1), days=30),
              "meteor_shower", "Geminids")
    s = _find(events.upcoming(*SYDNEY, now_utc=dt.datetime(2026, 12, 1), days=30),
              "meteor_shower", "Geminids")
    assert z["visible"] is True and s["visible"] is True
    assert z["alt"] > s["alt"]


def test_bright_twilight_objects_are_not_marked_invisible():
    """Venus at greatest elongation east is the evening star at its best. A
    blanket "sun below -12" rule called this invisible from Zürich, which is
    the bug dark_enough() exists to prevent."""
    evs = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=30)
    v = [e for e in evs if e["kind"] == "elongation" and e["body"] == "Venus"]
    assert v and v[0]["visible"] is True


def test_window_is_one_contiguous_night():
    """An 18-hour scan either side spans two evenings; the window must be the
    run containing the best moment, not the outer bounds of both."""
    evs = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=30)
    for e in evs:
        w = e.get("window_local")
        if not w:
            continue
        assert w[0] != w[1], f"{e['name']} produced a zero-width window"


def test_local_time_uses_the_offset():
    z = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=10)[0]
    assert (z["when_local"] - z["when_utc"]).total_seconds() == 2 * 3600


# ---------------------------------------------------------------- eclipses
def test_lunar_eclipse_visible_where_the_moon_is_up():
    evs = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=40)
    ec = [e for e in evs if e["kind"] == "eclipse" and "lunar" in e["eclipse_type"]]
    assert ec
    for e in ec:
        assert e["visible"] == (e["alt"] > 0)


def test_solar_eclipse_excluded_where_the_sun_is_down():
    """12 Aug 2026, 17:46 UTC is the small hours in Sydney."""
    evs = events.upcoming(*SYDNEY, now_utc=dt.datetime(2026, 8, 1), days=30)
    ec = _find(evs, "eclipse")
    assert ec["visible"] is False
    assert "below the horizon" in ec["reason"]


MADRID = (40.42, -3.70, 2)
BURGOS = (42.34, -3.70, 2)          # northern Spain, inside the 2026 track
REYKJAVIK = (64.15, -21.94, 0)      # western Iceland, inside it too


def test_solar_eclipse_says_partial_where_it_is_partial():
    """Zürich gets a deep partial on 12 Aug 2026. The headline said "Total
    solar eclipse", which is the eclipse's global type and a promise Zürich
    cannot keep."""
    ec = _find(events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=30),
               "eclipse")
    assert ec["visible"] is True and ec["in_range"] is True
    assert ec["headline"] == "Partial solar eclipse here"
    assert ec["local_type"] == "partial"
    assert "narrow track" in ec["note"]


@pytest.mark.parametrize("place", [REYKJAVIK, BURGOS])
def test_solar_eclipse_says_track_nearby_in_the_region(place):
    """Not "total solar eclipse": a box is a region, not the track. NASA names
    whole countries, so the same wording has to be honest for someone in Perth
    when the 2028 bracket says only "[Total: Australia]"."""
    ec = _find(events.upcoming(*place, now_utc=dt.datetime(2026, 8, 1), days=30),
               "eclipse")
    assert ec["headline"] == "Total solar eclipse: track nearby"
    assert ec["local_type"] == "near-track"
    assert "detailed map" in ec["note"]


def test_no_solar_eclipse_ever_headlines_plain_totality():
    """The whole point: no place is told it will see totality."""
    for place in (ZURICH, SYDNEY, MADRID, BURGOS, REYKJAVIK, TROMSO, NAIROBI):
        for e in events.upcoming(*place, now_utc=dt.datetime(2026, 1, 1), days=365 * 14):
            if e["kind"] == "eclipse" and e.get("in_range"):
                assert e["headline"] in ("Partial solar eclipse here",
                                         "Total solar eclipse: track nearby",
                                         "Annular solar eclipse: track nearby",
                                         "Hybrid solar eclipse: track nearby"), e["headline"]


def test_eclipse_table_covers_2026_to_2040():
    ecs = events._eclipses()
    years = {int(e["when_utc"][:4]) for e in ecs}
    assert min(years) == 2026 and max(years) == 2040
    solar = [e for e in ecs if "solar" in e["type"]]
    assert len(solar) >= 20
    # Every solar entry needs boxes, or it can never say anything but partial.
    assert all(e.get("total_boxes") for e in solar)
    # 2029 has no total or annular solar eclipse at all, only partials.
    assert not [e for e in solar if e["when_utc"].startswith("2029")]


def test_no_penumbral_lunar_eclipses_in_the_table():
    """Nobody can tell one from an ordinary full Moon, so listing them is
    noise. Two 2027 entries were also wrongly typed as total at one point."""
    assert not [e for e in events._eclipses() if "penumbral" in e["type"]]


def test_central_spain_is_outside_the_2026_track():
    """Madrid sees a very deep partial and no totality. The northern-Spain box
    must not swallow the whole country."""
    ec = _find(events.upcoming(*MADRID, now_utc=dt.datetime(2026, 8, 1), days=30),
               "eclipse")
    assert ec["local_type"] == "partial"


def test_totality_boxes_are_well_formed():
    for ec in events._eclipses():
        for box in ec.get("total_boxes") or []:
            lo_lat, hi_lat, lo_lon, hi_lon = box
            assert -90 <= lo_lat < hi_lat <= 90, box
            assert -180 <= lo_lon < hi_lon <= 180, box


def test_missing_box_data_defaults_to_partial_not_total():
    """Under-claiming is the safe direction: the track is a sliver, so
    "partial" is right for almost everywhere that sees the eclipse."""
    assert events._in_totality_region({"regions": "x"}, 47.0, 8.0) is None


# ---------------------------------------------------------------- ids
def test_event_id_is_stable_across_scans():
    a = events.scan_global(dt.datetime(2026, 8, 1), 60)
    b = events.scan_global(dt.datetime(2026, 8, 1), 60)
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_event_ids_are_unique_in_a_window():
    evs = events.scan_global(dt.datetime(2026, 1, 1), 365)
    ids = [e["id"] for e in evs]
    assert len(ids) == len(set(ids)), "duplicate id would collide as an ICS UID"


def test_event_id_survives_a_shifted_start_date():
    """The bot and a calendar client must not see a new id just because the
    scan began on a different day."""
    a = {e["id"] for e in events.scan_global(dt.datetime(2026, 8, 1), 60)}
    b = {e["id"] for e in events.scan_global(dt.datetime(2026, 8, 5), 50)}
    assert b <= a


def test_event_id_shape():
    assert events.event_id("shower", "Southern Delta Aquariids",
                           dt.datetime(2026, 7, 30, 4, 0)) == \
        "shower-southern-delta-aquariids-20260730"


# ---------------------------------------------------------------- entry points
def test_upcoming_never_returns_past_events():
    now = dt.datetime(2026, 8, 15, 12, 0)
    for e in events.upcoming(*ZURICH, now_utc=now, days=60):
        assert e["when_utc"] >= now


def test_upcoming_is_sorted():
    evs = events.upcoming(*ZURICH, now_utc=dt.datetime(2026, 8, 1), days=90)
    assert evs == sorted(evs, key=lambda e: e["when_utc"])


def test_visible_only_drops_the_impossible():
    now = dt.datetime(2026, 8, 1)
    all_ = events.upcoming(*SYDNEY, now_utc=now, days=30)
    some = events.upcoming(*SYDNEY, now_utc=now, days=30, visible_only=True)
    assert len(some) < len(all_)
    assert all(e["visible"] is not False for e in some)


def test_next_event_prefers_a_shower_over_a_quarter_moon():
    n = events.next_event(*ZURICH, now_utc=dt.datetime(2026, 8, 10), within_days=14)
    assert n["name"] == "Perseids"


def test_next_event_skips_an_eclipse_nobody_here_can_see():
    """Sydney must not be told about the 12 Aug 2026 eclipse at all."""
    n = events.next_event(*SYDNEY, now_utc=dt.datetime(2026, 8, 10), within_days=14)
    assert n is None or n["kind"] != "eclipse"


def test_next_event_returns_none_when_nothing_is_close():
    n = events.next_event(*ZURICH, now_utc=dt.datetime(2026, 8, 1), within_days=1)
    assert n is None or n["when_utc"] <= dt.datetime(2026, 8, 2)


def test_equator_sees_both_northern_and_southern_radiants():
    evs = events.upcoming(*NAIROBI, now_utc=dt.datetime(2026, 1, 1), days=365,
                          visible_only=True)
    showers = {e["name"] for e in evs if e["kind"] == "meteor_shower"}
    assert "Perseids" in showers and "Eta Aquariids" in showers


# ---------------------------------------------------------------- caching
def test_scan_is_memoised_per_utc_day():
    events._scan_cached.cache_clear()
    events.scan_cached(dt.datetime(2026, 8, 3, 1, 0), 90)
    events.scan_cached(dt.datetime(2026, 8, 3, 23, 0), 90)
    assert events._scan_cached.cache_info().hits == 1


def test_localise_does_not_mutate_the_cached_scan():
    """The global scan is shared by every request; localising for Zürich must
    not leave Zürich's altitudes on it for the next caller."""
    evs = events.scan_cached(dt.datetime(2026, 8, 3), 60)
    before = json.dumps([sorted(e.keys()) for e in evs])
    for e in evs:
        events.localise(e, *ZURICH)
    assert json.dumps([sorted(e.keys()) for e in evs]) == before
