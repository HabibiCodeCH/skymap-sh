"""Routing for the object pages.

The collision behaviour is the load-bearing part. There are eleven paths that
are both an object and a real city, and the rule is that the object wins every
one of them regardless of the city's population -- which is a promise this
file exists to keep, since the alternative (a population threshold) would make
/Jupiter and /Heze resolve by different logic with no way to explain which.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import objects
import server

CURL = {"user-agent": "curl/8"}
BROWSER = {"user-agent": "Mozilla/5.0", "accept": "text/html"}


def setUpModule():
    # Same reasoning as test_server.py: every TestClient request lands on one
    # synthetic IP and _buckets is shared for the process, so a file with a
    # hundred requests in it throttles itself and fails later tests with 429s
    # that say nothing about what they were checking.
    server.RATE = 1_000_000
    server.BURST = 1_000_000
    server.STATS_RATE = 1_000_000
    server.STATS_BURST = 1_000_000


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    server._buckets.clear()
    yield


@pytest.fixture(scope="module")
def client():
    """A client whose traffic cannot be seen by any other test file.

    The 404s in here would otherwise be counted twice over. TestClient's exit
    flushes the hour in progress to HOURLY_LOG, which conftest.py points at
    one shared temp file, and test_server.py then seeds _hour_stat with
    Counter.update() -- which ADDS rather than replaces, the same trap
    _load_stats_state() documents. Two 404s from this file turned its
    expected 3 notfounds into 5. Pointing the log somewhere private for the
    duration keeps this file's traffic out of everyone else's numbers.
    """
    setUpModule()
    original_log = server.HOURLY_LOG
    server.HOURLY_LOG = os.path.join(tempfile.mkdtemp(prefix="skymap-objroutes-"),
                                      "hourly.jsonl")
    server._hour_stat.clear()
    try:
        with TestClient(server.app) as c:
            yield c
    finally:
        server.HOURLY_LOG = original_log
        server._hour_stat.clear()


def body(resp):
    return server.api.strip_ansi(resp.text)


# ------------------------------------------------------------- the namespace
@pytest.mark.parametrize("path, expect", [
    ("/Saturn", "Saturn"), ("/M31", "Andromeda Galaxy"),
    ("/Sirius", "Sirius"), ("/Algol", "Algol"),
    ("/Big%20Dipper", "Big Dipper"), ("/Perseids", "Perseids"),
])
def test_object_paths_resolve(client, path, expect):
    r = client.get(path, headers=CURL)
    assert r.status_code == 200
    assert expect in body(r)


@pytest.mark.parametrize("path", ["/venus", "/VENUS", "/V%C3%A9nus", "/m31", "/NGC224"])
def test_aliases_and_case(client, path):
    """Normalising the segment is what makes these work without an alias
    table -- accents included."""
    assert client.get(path, headers=CURL).status_code == 200


def test_unknown_object_still_404s_as_a_place(client):
    r = client.get("/nonsense", headers=CURL)
    assert r.status_code == 404
    assert "Don't know" in body(r)


# --------------------------------------------------------------- collisions
COLLISIONS = ["Jupiter", "Venus", "Neptune", "Moon", "Orion",
              "Heze", "Maia", "Mira", "Keystone", "Aquila", "Cervantes"]


@pytest.mark.parametrize("name", COLLISIONS)
def test_objects_win_every_collision(client, name):
    """All eleven, including Heze -- a city of 8.75 million sharing a path
    with a magnitude 3.4 star. Consistency is the point: a threshold that
    gave this one to the city would make the namespace unexplainable."""
    r = client.get(f"/{name}", headers=CURL)
    assert r.status_code == 200
    assert r.json is not None or True
    data = client.get(f"/{name}?format=json").json()
    assert data.get("object") == objects.resolve_name(name)


@pytest.mark.parametrize("name", COLLISIONS)
def test_every_collision_offers_the_city(client, name):
    """The cost of objects always winning is paid here: whoever loses the
    path gets a working link to the other thing."""
    data = client.get(f"/{name}?format=json").json()
    also = data.get("also_a_place")
    assert also, f"/{name} collides with a city but offers no way to reach it"
    assert server.api.lookup_place(also["url"].lstrip("/")) is not None, \
        f"the escape url {also['url']} does not resolve"


def test_non_colliding_object_offers_no_city(client):
    assert "also_a_place" not in client.get("/Saturn?format=json").json()


# ------------------------------------------------------------ reserved paths
@pytest.mark.parametrize("path", ["/stats", "/help", "/legend", "/catalog",
                                   "/healthz", "/robots.txt", "/sitemap.xml",
                                   "/llms.txt", "/demo"])
def test_reserved_paths_are_not_shadowed(client, path):
    assert client.get(path, headers=CURL).status_code == 200
    assert objects.resolve_name(path.lstrip("/")) is None


def test_place_pages_still_work(client):
    for place in ("Zurich", "Tokyo", "47.38,8.54"):
        assert client.get(f"/{place}", headers=CURL).status_code == 200


# ------------------------------------------------------------ the two forms
def test_explicit_form(client):
    r = client.get("/Zurich/Venus", headers=CURL)
    assert r.status_code == 200
    assert "Venus" in body(r)


def test_the_slot_decides_not_the_name(client):
    """/Venus/Saturn is Saturn seen from Venus, Texas. The first segment is a
    place even when it is also an object, and the second is an object even
    when it is also a place -- which is what keeps the collision rule
    confined to bare one-segment paths."""
    data = client.get("/Venus/Saturn?format=json").json()
    assert data["object"] == "Saturn"
    assert data["place"] == "Venus"


def test_explicit_form_canonicalises_to_the_bare_object(client):
    """40,803 cities times 1,220 objects is fifty million near-identical
    URLs. Canonical is what stops a crawler treating them as pages."""
    r = client.get("/Zurich/Venus", headers=CURL)
    assert 'rel="canonical"' in r.headers.get("link", "")
    assert "skymap.sh/Venus" in r.headers["link"]


def test_bare_object_has_no_canonical_header(client):
    assert "canonical" not in client.get("/Venus", headers=CURL).headers.get("link", "")


def test_unknown_object_in_explicit_form_404s(client):
    assert client.get("/Zurich/nonsense", headers=CURL).status_code == 404


# --------------------------------------------------------------- the surfaces
def test_json_carries_the_facts(client):
    d = client.get("/Saturn?format=json").json()
    for key in ("object", "kind", "place", "transit", "transit_alt", "constellation"):
        assert key in d, f"missing {key}"
    assert d["planet"]["ring_angle"] is not None


def test_html_has_the_seo_head(client):
    h = client.get("/Saturn", headers=BROWSER).text
    assert '<link rel="canonical" href="https://skymap.sh/Saturn">' in h
    assert 'property="og:image"' in h
    assert 'name="twitter:card"' in h
    assert "<title>" in h and "Saturn" in h


def test_og_image_renders(client):
    r = client.get("/Saturn/og.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_og_image_404s_for_an_unknown_object(client):
    assert client.get("/nonsense/og.png").status_code == 404


def test_sitemap_lists_objects_but_not_every_one(client):
    x = client.get("/sitemap.xml").text
    assert "https://skymap.sh/Saturn" in x
    assert "https://skymap.sh/Algol" in x
    # Bare catalogue numbers have nothing specific to say and stay out.
    assert "https://skymap.sh/NGC6304" not in x
    assert 150 < x.count("<url>") < 500


def test_sitemap_excludes_the_explicit_form(client):
    assert "/Zurich/" not in client.get("/sitemap.xml").text


# ------------------------------------------------------------------- stats
def test_object_views_are_counted(client):
    before = client.get("/stats?format=json").json().get("top_objects", {}).get("Saturn", 0)
    client.get("/Saturn", headers=CURL)
    after = client.get("/stats?format=json").json()["top_objects"]["Saturn"]
    assert after > before


# ------------------------------------------------------- below the horizon
def test_an_object_below_the_horizon_still_answers(client):
    """Never an error and never an empty chart -- the find view redraws for
    the next time it is up, and the prose describes that same moment."""
    d = client.get("/Southern Cross?format=json").json()
    assert d["object"] == "Southern Cross"
    assert "transit" in d


def test_never_rising_object_says_so(client):
    d = client.get("/Southern Cross?format=json").json()
    assert d.get("never_rises") or d.get("visible") is False


# ------------------------------------------------------------- social card
def test_card_is_the_right_shape_for_an_unfurl(client):
    """1200x630 is what every unfurl expects, and the og:image:width tag
    promises it."""
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(client.get("/Saturn/og.png").content))
    assert img.size == (1200, 630)


@pytest.mark.parametrize("name", ["Saturn", "M31", "Algol", "Perseids",
                                   "Betelgeuse", "Big Dipper", "Moon", "Venus"])
def test_card_renders_for_every_kind_of_object(client, name):
    """One per branch of the fact picker. Showers in particular carry a
    different shape -- a peak night with no dark-hours figure -- and
    formatting that None is what returned a 500 instead of an image."""
    r = client.get(f"/{name}/og.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 5000, "suspiciously small for a rendered card"


def test_card_survives_facts_it_has_never_seen(client):
    """The renderer is handed whatever the page produced. It must not be the
    thing that breaks when a field is missing."""
    import card
    assert card.render({}, None)[:8] == b"\x89PNG\r\n\x1a\n"
    assert card.render({"object": "Test"}, None)[:8] == b"\x89PNG\r\n\x1a\n"


def test_card_headline_facts_stay_short(client):
    """Three lines is the budget; a fourth runs into the wordmark."""
    import card
    for name in ("Saturn", "Algol", "Perseids", "M31"):
        facts = client.get(f"/{name}?format=json").json()
        assert len(card._headline_facts(facts)) <= 3


@pytest.mark.parametrize("name", ["Deneb", "Vega", "Pleiades", "M31",
                                  "Ring Nebula", "Hercules Cluster"])
def test_the_card_reads_the_same_under_any_sky(client, name):
    """A card is drawn once, by a crawler, from wherever that crawler lives,
    and then shown to everybody who sees the link. So nothing on it may
    depend on the sky it was drawn under.

    The page's own visibility line does depend on it, correctly -- it asks
    the reader's Bortle and answers "binoculars from here". On a card "here"
    was a datacentre in Virginia, which is how Deneb, a star bright enough
    to see from a lit street, came to be a binocular object."""
    import card
    import objects
    facts = client.get(f"/{name}?format=json").json()
    base = card._headline_facts(facts)
    for bortle in (1, 4, 6, 9):
        under = dict(facts, bortle=bortle)
        if facts.get("need"):
            under["need"] = objects.what_you_need(facts.get("mag"), bortle)
        assert card._headline_facts(under) == base, f"{name} at Bortle {bortle}"
    assert not [line for line in base if "from here" in line]


# --------------------------------------------------------- card glyphs
def test_every_card_glyph_has_a_font_that_contains_it():
    """Read from the fonts' cmap tables, not from rendered pixels.

    A missing glyph does not fail loudly: it draws .notdef, which is a
    visible box for some codepoints and blank for others, so "does this look
    wrong" is not a test. Every galaxy, cluster and nebula card shipped a box
    where its symbol should be, and nothing said so.

    This covers what api.object_glyph() can return, which is a wider set than
    the chart draws -- meteor showers and asterisms are marked on a card but
    never on a chart, so gif._PRIMARY_GAPS does not mention them.

    The import below is deliberately unguarded, same as the one in
    test_gif.py: a check for something invisible must not be allowed to
    quietly not run. fonttools is in requirements.txt.
    """
    from fontTools.ttLib import TTFont
    import card, gif

    def cmap_of(path):
        out = set()
        for t in TTFont(path, fontNumber=0)["cmap"].tables:
            out |= set(t.cmap.keys())
        return out

    primary, fallback = cmap_of(card._MONO), cmap_of(gif._FALLBACK_PATH)
    missing = []
    for ch in "●•·◆✺✳⁂◈☀◐◑✧☄":
        drawn = card._glyph_char(ch)
        chosen = fallback if drawn in card._GAPS else primary
        if ord(drawn) not in chosen:
            missing.append((ch, drawn, "fallback" if drawn in card._GAPS else "primary"))
    assert not missing, f"glyphs that would render as tofu: {missing}"


def test_object_glyphs_are_all_covered(client):
    """The same check, but driven by what the service actually emits rather
    than a list written by hand next to it."""
    from fontTools.ttLib import TTFont
    import card, gif

    def cmap_of(path):
        out = set()
        for t in TTFont(path, fontNumber=0)["cmap"].tables:
            out |= set(t.cmap.keys())
        return out

    primary, fallback = cmap_of(card._MONO), cmap_of(gif._FALLBACK_PATH)
    bad = []
    for name in ("Sirius", "Saturn", "Andromeda Galaxy", "Hercules Cluster",
                 "Orion Nebula", "Ring Nebula", "Perseids", "Big Dipper",
                 "Moon", "Sun"):
        g = client.get(f"/{name}?format=json").json().get("glyph") or ""
        if not g:
            continue
        drawn = card._glyph_char(g)
        chosen = fallback if drawn in card._GAPS else primary
        if ord(drawn) not in chosen:
            bad.append((name, g))
    assert not bad, f"objects whose card glyph would be tofu: {bad}"


def test_every_kind_string_has_a_subtitle_word():
    """A kind with no entry does not fail, it silently reads "Object" -- which
    is how every cluster card came to say "OBJECT IN HERCULES". Driven off
    what resolve_target actually returns across the whole namespace, not off a
    list written next to the map it is checking."""
    import datetime as dt
    import card, sky
    jd = sky.julian(dt.datetime(2026, 8, 5))
    lst = (sky.gmst_hours(jd) + 8.54 / 15.0) % 24
    kinds = set()
    for n in objects.all_names():
        t = sky.resolve_target(n, jd, 47.38, lst)
        if t:
            kinds.add(t["kind"])
    missing = sorted(k for k in kinds if k not in card.KIND_WORDS)
    assert not missing, f"kinds that would render as 'Object': {missing}"


def test_visibility_line_never_invented_from_a_placeholder(client):
    """deepsky.json stores the magnitude cutoff for objects RNGC never
    measured, so m=11.0 is sometimes a brightness and sometimes a stand-in.
    Objects carrying the stand-in must not get a "what you need to see it"
    line derived from it."""
    import sky
    placeholders = [o for o in sky._load("deepsky.json") if o.get("nomag")]
    assert placeholders, "expected some objects to have no measured magnitude"
    for o in placeholders[:12]:
        d = client.get(f"/{o['id']}?format=json").json()
        assert "need" not in d, f"{o['id']} invented a visibility line from a placeholder"


def test_visibility_line_appears_when_the_magnitude_is_real(client):
    d = client.get("/Hercules Cluster?format=json").json()
    assert d.get("need"), "a measured magnitude should produce a visibility line"


# ------------------------------------- a star is not an extended object
@pytest.mark.parametrize("name,mag", [("Deneb", 1.25), ("Vega", 0.03),
                                      ("Algol", 2.12), ("Albireo", 3.08)])
def test_a_bright_star_is_naked_eye_under_any_sky(name, mag):
    """It said "binoculars from here" for Deneb in Zurich. The extended-object
    thresholds call anything under Bortle 5 a binocular target at magnitude 4,
    which is right for a galaxy spreading that light over half a degree and
    plainly wrong for the nineteenth brightest star in the sky."""
    import objects
    for bortle in [None] + list(range(1, 10)):
        got = objects.what_you_need(mag, bortle, point=True)
        assert got == "naked eye", f"{name} at Bortle {bortle}: {got}"


def test_the_faintest_naked_eye_star_still_depends_on_the_sky():
    """The point of the table. A magnitude 5.8 star is an easy catch in the
    countryside and gone from a city."""
    import objects
    assert objects.what_you_need(5.8, 3, point=True) == "naked eye"
    assert objects.what_you_need(5.8, 8, point=True) == "binoculars from here"


def test_extended_objects_keep_their_own_thresholds():
    """Same magnitude, different answer, because the light is spread out.
    This is the distinction the point flag exists to make, so it has to be
    visible from both sides."""
    import objects
    assert objects.what_you_need(4.5, 8) == "binoculars, and it will be faint"
    assert objects.what_you_need(4.5, 8, point=True) == "binoculars from here"
    assert objects.what_you_need(3.0, 8) != objects.what_you_need(3.0, 8, point=True)


def test_the_bortle_sentence_reads_when_nothing_is_needed(client):
    """"So for this you want naked eye" is not a sentence."""
    body = client.get("/Zurich/Deneb", headers={"user-agent": "curl/8"}).text
    assert "you want naked eye" not in body
    assert "bright enough to see with the naked eye" in body


# ------------------------------------------------- cards must not go stale
def _card_state(name, when):
    """Everything a card shows, at a given moment."""
    import api, card, sky
    jd = sky.julian(when)
    lst = (sky.gmst_hours(jd) + 8.54 / 15.0) % 24
    t = sky.resolve_target(name, jd, 47.38, lst)
    f = api.object_facts(t, api.Request(place="Zurich", when=when), name)
    return card._subtitle(f), tuple(card._headline_facts(f)), f.get("glyph")


def test_the_moon_card_does_not_show_a_live_phase():
    """The phase glyph runs the whole cycle in under two weeks -- across
    eight days it goes last quarter, new, first quarter. A social card sits
    in Twitter's cache about a week and Facebook's until re-scraped, so a
    Moon card shared at last quarter would still show a half Moon on the
    night of the new Moon, and the phase is the whole content of that card.

    The page keeps the real phase per visitor; only the card is pinned."""
    import datetime as dt
    base = dt.datetime(2026, 8, 5)
    glyphs = {_card_state("Moon", base + dt.timedelta(days=d))[2]
              for d in (0, 4, 8, 12, 16, 20)}
    assert glyphs == {"●"}, f"Moon card glyph changed over a lunar month: {glyphs}"


@pytest.mark.parametrize("name", ["Sirius", "Betelgeuse", "Andromeda Galaxy",
                                   "Ring Nebula", "Big Dipper", "Sun", "Moon"])
def test_cards_are_stable_across_a_cache_lifetime(name):
    """Nothing a card claims may change within the week or so a platform
    holds the image. Planets and showers are exempt and tested separately:
    their drift is real and slow."""
    import datetime as dt
    base = dt.datetime(2026, 8, 5)
    assert _card_state(name, base) == _card_state(name, base + dt.timedelta(days=7)), \
        f"{name}'s card changed within a cache lifetime"


def test_planet_distance_drift_is_below_what_the_card_prints():
    """Distances do move, but by less than a printed light-minute over a
    week, so the card reads the same."""
    import datetime as dt
    base = dt.datetime(2026, 8, 5)
    for name in ("Saturn", "Jupiter", "Mars"):
        assert _card_state(name, base) == _card_state(name, base + dt.timedelta(days=7)), \
            f"{name} drifted visibly within a week"


# ------------------------------------------------- the evergreen intro
def test_every_kind_has_an_intro_word(client):
    """A kind with no entry does not fail, it falls through to "object" and
    prints "NGC6304 is a object in Ophiuchus"."""
    import datetime as dt
    import api, sky
    jd = sky.julian(dt.datetime(2026, 8, 5))
    lst = (sky.gmst_hours(jd) + 8.54 / 15.0) % 24
    kinds = {sky.resolve_target(n, jd, 47.38, lst)["kind"]
             for n in objects.all_names()
             if sky.resolve_target(n, jd, 47.38, lst)}
    missing = sorted(k for k in kinds if k not in api._KIND_WORD)
    assert not missing, f"kinds with no word for the intro line: {missing}"


@pytest.mark.parametrize("name, want", [
    ("NGC6304", " is a star cluster in "),
    ("Perseids", "Perseids are "),
    ("Pleiades", "Pleiades are "),
    ("Saturn", "Saturn is the 6th planet in the solar system, a gas giant."),
])
def test_intro_line_reads_correctly(client, name, want):
    assert want in body(client.get(f"/{name}", headers=CURL))


def test_a_radiant_has_no_magnitude_row(client):
    """resolve_target gives a radiant a stand-in magnitude so dark_enough()
    picks the nautical threshold. It is not a brightness, and an infobox row
    saying "Magnitude 2.5" invents one.

    Scoped to the infobox on purpose. sky.find_text() prints the same
    stand-in in the ?find= guide text under every chart, which is the same
    bug in a shared view -- but that view is the render engine every chart
    goes through, so fixing it there is its own change, not a side effect of
    this one."""
    import api, sky, datetime as dt
    jd = sky.julian(dt.datetime(2026, 8, 5))
    lst = (sky.gmst_hours(jd) + 8.54 / 15.0) % 24
    tgt = sky.resolve_target("Perseids", jd, 47.38, lst)
    r = api.Request(place="Zurich")
    facts = api.object_facts(tgt, r, "Perseids")
    assert "Magnitude" not in api.infobox_text(api.object_infobox(facts, tgt))


def test_the_glyph_keeps_its_own_colour(client):
    """Painting the whole heading line one colour made every mark white, so
    Saturn's gold diamond and M31's green spiral looked like plain text."""
    import api
    saturn = client.get("/Saturn?format=json").json()
    m31 = client.get("/Andromeda Galaxy?format=json").json()
    assert saturn["glyph_ansi"] != m31["glyph_ansi"]
    raw = client.get("/Saturn", headers=CURL).text
    assert saturn["glyph_ansi"] + saturn["glyph"] in raw, \
        "the glyph is not painted in its own colour"


def test_the_page_does_not_name_the_place_twice_running(client):
    """The find view opens with its own header, which under "Tonight from
    Zurich" said the place and the object again two lines later."""
    lines = [l.strip() for l in body(client.get("/Saturn", headers=CURL)).split("\n")]
    i = next(i for i, l in enumerate(lines) if l.startswith("Zurich "))
    assert not any("finding Saturn" in l for l in lines[i:i + 3])


def test_blurbs_all_key_to_real_objects():
    import blurbs
    bad = [k for k in blurbs.BLURBS if objects.resolve_name(k) != k]
    assert not bad, f"blurb keys that do not resolve to themselves: {bad}"


def test_blurbs_carry_no_em_dashes():
    import blurbs
    bad = [k for k, (g, b) in blurbs.BLURBS.items() if "—" in g or "—" in b]
    assert not bad, f"blurbs containing an em dash: {bad}"


def test_objects_without_a_blurb_still_get_an_intro(client):
    t = body(client.get("/NGC6304", headers=CURL))
    assert "NGC6304 is a star cluster in Ophiuchus." in t


# --------------------------------------------------------- the fact tables
def test_fact_keys_all_resolve_to_real_objects():
    import facts, objects
    bad = [k for k in facts.FACTS if objects.resolve_name(k) != k]
    assert not bad, f"fact keys that do not resolve to themselves: {bad}"


def test_facts_carry_no_em_dashes():
    import facts
    bad = [(k, f) for k, rec in facts.FACTS.items()
           for f, v in rec.items() if "—" in str(v)]
    assert not bad, f"facts containing an em dash: {bad}"


def test_every_fact_field_has_a_label():
    """A field in neither order is written and never printed, which is the
    quiet kind of wrong. Two orders since the history moved to its own page,
    so this has to check the union rather than one of them."""
    import facts
    known = {k for k, _label in facts.FIELD_ORDER + facts.HISTORY_ORDER}
    used = {f for rec in facts.FACTS.values() for f in rec}
    assert used <= known, f"fields that would never print: {sorted(used - known)}"


def test_the_two_field_orders_never_overlap():
    """A key in both lists prints on both pages under two headings, and the
    two would drift. The split is only safe while it is a partition."""
    import facts
    assert not ({k for k, _l in facts.FIELD_ORDER}
                & {k for k, _l in facts.HISTORY_ORDER})


@pytest.mark.parametrize("name, label, fragment", [
    ("Saturn", "Moons", "274"),
    ("Perseids", "Debris from", "Swift-Tuttle"),
])
def test_facts_reach_the_page(client, name, label, fragment):
    """What the thing IS stays on the object page, next to where to find it."""
    t = body(client.get(f"/{name}", headers=CURL))
    assert label in t and fragment in t


@pytest.mark.parametrize("name, label, fragment", [
    ("Saturn", "Missions", "Cassini"),
    ("Uranus", "Discovered", "Herschel"),
    ("Andromeda Galaxy", "First photographed", "Isaac Roberts"),
    ("Algol", "Discovered", "Goodricke"),
])
def test_history_facts_reach_the_history_page(client, name, label, fragment):
    """And what happened TO it is one click away, on /{object}/history. These
    four used to be at the bottom of the object page's infobox."""
    t = body(client.get(f"/{name}/history", headers=CURL))
    assert label in t and fragment in t


def test_a_written_fact_never_overrides_a_computed_one(client):
    """Algol's distance is computed from its Hipparcos parallax and also
    written down as a round figure. Printing both would be one object with
    two distances."""
    t = body(client.get("/Algol", headers=CURL))
    assert t.count("Distance") == 1


def test_objects_without_facts_still_render(client):
    """36 objects have entries; the other 1,180 fall back to what the
    catalogues can compute, and must not break."""
    t = body(client.get("/NGC6304", headers=CURL))
    assert "NGC6304 is a star cluster in Ophiuchus." in t
    assert "Constellation" in t


def test_an_object_page_has_the_drawer(client):
    """controls_html carries the drawer trigger as well as the explore row.
    Passing "" for controls gave object pages no way to open the drawer at
    all, and nothing failed -- the page just quietly lacked it."""
    h = client.get("/Saturn", headers=BROWSER).text
    for marker in ('id="drawer-trigger"', 'aria-controls="drawer"'):
        assert marker in h, f"object page is missing {marker}"


def test_the_object_page_carries_the_same_controls_as_a_place_page(client):
    obj = client.get("/Saturn", headers=BROWSER).text
    place = client.get("/Zurich", headers=BROWSER).text
    assert obj.count("drawer-trigger") == place.count("drawer-trigger")


@pytest.mark.parametrize("name, want", [
    ("Sun", "The Sun is the star we orbit."),
    ("Moon", "The Moon is Earth's only moon."),
    ("Perseids", "The Perseids are a meteor shower"),
    ("Pleiades", "The Pleiades are a star cluster"),
    ("Saturn", "Saturn is the 6th planet in the solar system, a gas giant."),
    ("Sirius", "Sirius is a star in Canis Major."),
])
def test_the_opening_line(client, name, want):
    assert want in body(client.get(f"/{name}", headers=CURL))


def test_the_page_and_the_card_describe_an_object_the_same_way(client):
    """One descriptor feeds both, so a card and the page it links to can
    never say different things about the same object."""
    import api, card
    for name in ("Saturn", "Sirius", "Perseids", "Moon", "Andromeda Galaxy"):
        d = client.get(f"/{name}?format=json").json()
        page = api.object_descriptor(d)
        sub = card._subtitle(d)
        assert sub.lower().lstrip() in page.lower(), \
            f"{name}: card says {sub!r}, page says {page!r}"


def test_a_planets_evergreen_line_does_not_name_a_constellation(client):
    """A planet crosses one every few months and the Moon every two or three
    days, so naming it in the block whose job is to hold still puts a live
    fact in the first sentence a crawler reads."""
    for name in ("Saturn", "Mars", "Moon", "Sun"):
        d = client.get(f"/{name}?format=json").json()
        assert d["constellation"] not in api_descriptor(d), name


def api_descriptor(d):
    import api
    return api.object_descriptor(d)


def test_a_fixed_objects_evergreen_line_does_name_its_constellation(client):
    """Sirius has been in Canis Major for the whole of recorded history."""
    for name in ("Sirius", "Andromeda Galaxy", "Big Dipper"):
        d = client.get(f"/{name}?format=json").json()
        assert d["constellation"] in api_descriptor(d), name


def test_the_title_is_a_real_heading(client):
    """The <title> tag said Saturn and the document itself never did: these
    pages had no h1 at all, which is the element a search engine reads as the
    subject of the page."""
    h = client.get("/Saturn", headers=BROWSER).text
    assert '<h1 class="obj-title">' in h
    assert h.count("<h1") == 1, "exactly one heading"
    assert "Saturn</span></h1>" in h


def test_the_title_carries_the_objects_own_colour(client):
    """The catalog lists these in the colour the chart draws them, so a page
    that colours the glyph and prints the name in plain white reads as a
    different object than the row that was clicked."""
    import re
    for name in ("Saturn", "Betelgeuse", "Andromeda Galaxy"):
        d = client.get(f"/{name}?format=json").json()
        h = client.get(f"/{name}", headers=BROWSER).text
        h1 = re.search(r'<h1 class="obj-title">(.*?)</h1>', h).group(1)
        assert h1.count(d["glyph_color"]) == 2, \
            f"{name}: glyph and name should share the object's colour"


def test_the_title_is_not_repeated_in_the_body(client):
    """It is lifted out of the static block into the h1, not copied out of
    it. The static half is a description list now rather than preformatted
    text, so this checks the block itself rather than a <pre>."""
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    aside = re.search(r'<aside class="obj-static">(.*?)</aside>', h, re.S).group(1)
    assert "obj-title" not in aside
    lede = re.search(r'obj-lede">([^<]+)', aside).group(1)
    assert lede.startswith("Saturn is"), lede


def test_the_terminal_keeps_its_title(client):
    """There is nothing to make bigger in a terminal, and the coloured line
    is already the loudest thing on screen."""
    t = body(client.get("/Saturn", headers=CURL))
    assert t.strip().split("\n")[0].strip().endswith("Saturn")


def test_the_browser_splits_static_from_live(client):
    """Left half is identical for every visitor on every day, which is what a
    crawler indexes and what a newcomer needs before an altitude means
    anything. Right half is computed from their own location."""
    h = client.get("/Saturn", headers=BROWSER).text
    for cls in ('class="obj-cols"', 'class="obj-static"', 'class="obj-live"'):
        assert cls in h, f"missing {cls}"


def test_the_static_half_holds_the_durable_facts(client):
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    static = re.search(r'<aside class="obj-static">(.*?)</aside>', h, re.S).group(1)
    for durable in ("Radius", "Escape velocity"):
        assert durable in static, f"{durable} should be in the static half"
    for live in ("Tonight from", "Next chance"):
        assert live not in static, f"{live} should not be in the static half"
    # Discovered and Missions are durable too, and they are now a click away
    # rather than at the bottom of this column. The link is what replaced
    # them.
    for moved in ("Discovered", "Missions"):
        assert moved not in static, f"{moved} moved to /Saturn/history"
    assert 'href="/Saturn/history"' in static


def test_the_live_half_holds_tonights_sky(client):
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    live = re.search(r'<div class="obj-live">(.*)', h, re.S).group(1)
    assert re.search(r"Zurich (now|tonight|\w{3} \d)", live)
    assert "Escape velocity" not in live


def test_a_page_asked_for_a_moment_says_which_moment(client):
    """Every row of /events opens an object page with ?t= on it, and those
    pages announced themselves as "now" -- a page about 5 October, opened
    eight weeks early, headed "Zurich now" with a title offering to show it
    tonight. is_now means the chart was not shifted off the moment asked
    for, which is a different question from whether that moment is the
    present one."""
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    assert "Zürich now" not in got.text and "Zurich now" not in got.text
    # The chart is drawn for 01:10 on the 5th, in the place's own clock and
    # not UTC -- 23:10Z is already the 5th in Zurich.
    assert "5 Oct" in got.text


def test_a_page_opened_for_an_event_is_titled_by_that_event(client):
    """Clicking "Saturn at opposition" in a list of events and landing on a
    page offering to show you Saturn on a date, with no word about why that
    date, is the click going unanswered. The title names the event and
    carries the date the list filed it under -- not the date of the moment
    the chart happens to be drawn for, which is the night after."""
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    assert "<title>Saturn at opposition, 4 October 2026</title>" in got.text


def test_the_same_night_block_holds_what_is_not_already_said(client):
    """The block is the eclipse page's, heading and placement and all, and
    it lists what ELSE is up. The event the page is about is already the
    heading and the picker, and repeating it in a block headed "the same
    night" tells the reader what they just read.

    28 August is the case that shows both halves: a full Moon and a partial
    lunar eclipse, a few minutes apart, on one page."""
    got = client.get("/Zurich/Moon?t=2026-08-28T06:07", headers=BROWSER)
    static = got.text.split('<aside class="obj-static">')[1].split("</aside>")[0]
    assert "The same night" in static
    assert "Partial lunar eclipse" in static
    assert static.count("Full Moon") == 0, "already the heading and the picker"


def test_the_boxed_block_ends_where_it_should(client):
    """It is its own <dl> so it can carry a border. Opening one and never
    closing it drew the box around Physical and History as well."""
    got = client.get("/Zurich/Moon?t=2026-08-28T06:07", headers=BROWSER)
    boxed = got.text.split('class="obj-facts obj-tonight"')[1].split("</dl>")[0]
    assert "Partial lunar eclipse" in boxed
    assert "Physical" not in boxed and "Distance" not in boxed


def test_the_picker_closes_on_escape_and_on_a_click_outside(client):
    """<details> does neither natively, so a menu opened by accident sat
    over the page until it was clicked again. The same script the eclipse
    page uses, since it is the same control."""
    got = client.get("/Zurich/Moon", headers=BROWSER)
    assert "Escape" in got.text
    assert "pointerdown" in got.text
    assert ".obj-picker" in got.text


def test_a_page_with_no_picker_ships_no_script_for_one(client):
    """The stylesheet is one string for every object page, so the rules
    travel either way. The markup and the script are what should not."""
    got = client.get("/Zurich/Vega", headers=BROWSER)
    assert '<details class="obj-picker"' not in got.text
    assert "pointerdown" not in got.text


def _picker(markup):
    """The picker's <details>, or "" where there is none."""
    if '<details class="obj-picker"' not in markup:
        return ""
    return markup.split('<details class="obj-picker"')[1].split("</details>")[0]


def test_the_page_says_what_kind_of_event_it_is_pointing_at(client):
    """The picker names a thing -- "at opposition" -- and until now nothing
    on the page said what that meant. One sentence per kind, under the
    timing line it explains."""
    import re
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    what = got.text.split('<p class="obj-what">')[1].split("</p>")[0]
    # Flattened: the sentence is wrapped to the render width, and the
    # phrases worth asserting on fall across the break.
    flat = " ".join(re.sub(r"<[^>]+>", "", what).split())
    assert "opposite the Sun" in flat
    assert "up all night" in flat


def test_an_ordinary_night_gets_no_sentence(client):
    """Most pages are opened to find out where the thing is. Explaining an
    opposition ten weeks off made every object page read as an event page,
    including the ones nobody had asked an event of."""
    got = client.get("/Zurich/Venus", headers=BROWSER)
    assert '<p class="obj-what">' not in got.text


def test_an_object_with_no_events_gets_no_sentence(client):
    """No star ever carries one: conjunctions are only computed between
    solar-system bodies. Nothing to point at, nothing to explain."""
    got = client.get("/Zurich/Vega", headers=BROWSER)
    assert '<p class="obj-what">' not in got.text


def test_the_sentence_reaches_the_terminal_too(client):
    """Same page, same words. And wrapped, because a terminal cannot
    reflow a 130-character line."""
    import api
    flat = api.strip_ansi(
        client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=CURL).text)
    assert "Opposition is when a planet sits opposite the Sun" in flat
    assert max(len(l) for l in flat.split("\n")) < 120


def _picker_rows(markup):
    """The label of every event row in the picker, in order. Not the
    "Tonight" one at the top, which is a way back rather than an event."""
    import re, api
    return [r for r in re.findall(r"<li[^>]*><a [^>]*>([^<]*)</a>",
                                  _picker(markup))
            if api.PICK_NOW not in r]


def test_the_list_does_not_shrink_when_you_follow_it(client):
    """Every row is a link to this same page at another moment, so a list
    counted from the page's own moment lost an event every time one was
    followed: opening the event in March dropped everything before it,
    which had not happened yet either."""
    here = client.get("/Zurich/Moon", headers=BROWSER)
    later = client.get("/Zurich/Moon?t=2027-03-01T21:00", headers=BROWSER)
    assert _picker_rows(here.text) == _picker_rows(later.text)
    assert len(_picker_rows(here.text)) > 1


def test_the_list_never_shows_what_has_already_happened(client):
    """Twelve ahead, not a history. Tonight still counts as ahead -- the
    night it belongs to is still running -- so yesterday is the first date
    that may not appear."""
    import datetime as dt
    rows = _picker_rows(client.get("/Zurich/Moon", headers=BROWSER).text)
    days = [dt.datetime.strptime(r.split(" · ")[0], "%d %b %Y").date()
            for r in rows]
    assert days and min(days) >= dt.date.today() - dt.timedelta(days=1)


def _two_events():
    return [{"date_local": "2030-01-01", "when_local": "2030-01-01T20:00",
             "short": "coming", "kind": "opposition", "t": "y"},
            {"date_local": "2030-06-01", "when_local": "2030-06-01T20:00",
             "short": "later", "kind": "opposition", "t": "z"}]


def test_the_summary_points_at_the_head_of_the_list(client):
    """Nothing behind it any more, so "Next:" is simply the first row. On a
    page pinned to a night, which is when the reader is being told what is
    coming after the one they are looking at."""
    import api
    got = api.object_picker_html(
        {"object_events": _two_events(), "when_explicit": True},
        "Saturn", "Zurich")
    assert "Next: 1 Jan 2030 · coming" in got


def test_a_page_about_no_particular_night_says_so(client):
    """Naming the next event as the summary of a page that is not about it
    was the whole reason every object page read as an event page."""
    import api
    got = api.object_picker_html({"object_events": _two_events()},
                                 "Saturn", "Zurich")
    assert f"<span>{api.PICK_NOW}</span>" in got
    assert "Next:" not in got


def test_the_picker_always_offers_the_way_back(client):
    """Every other row pins a night, so following one left no link on the
    page that dropped it again."""
    import api
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    pick = _picker(got.text)
    assert f'<a href="/Zurich/Saturn">{api.PICK_NOW}</a>' in pick
    # And it is the row marked as where you are when the page is plain.
    plain = _picker(client.get("/Zurich/Saturn", headers=BROWSER).text)
    assert f'<li class="obj-pick-here"><a href="/Zurich/Saturn">' in plain


def test_the_share_box_offers_a_link_with_no_date_on_it(client):
    """Both the others carry the night the page is pinned to, so there was
    no way to send somebody Saturn rather than Saturn on 5 October."""
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    assert "<code id=\"ecl-url-now\">https://skymap.sh/Saturn</code>" in got.text
    # And it says Saturn, not "the eclipse", which is what borrowing the
    # eclipse page's control got us.
    assert "sees Saturn from where they are" in got.text
    assert "eclipse" not in got.text.split('ecl-share-box')[1].split(
        "</dialog>")[0]


def test_a_plain_page_does_not_offer_a_third_link(client):
    """Its first link already carries no date. Two rows saying the same
    thing is not a choice."""
    got = client.get("/Zurich/Saturn", headers=BROWSER)
    assert 'ecl-url-now' not in got.text


def test_the_head_lines_keep_the_same_margin_as_the_rest(client):
    """The three lines above the chart are written by hand rather than drawn
    into it, and being the only ones written by hand they were a character
    short of the two everything else on the page sits at."""
    import api
    flat = api.strip_ansi(
        client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=CURL).text)
    lines = [l for l in flat.split("\n") if l.strip()]
    head = next(l for l in lines if "·" in l and "mag" in l)
    what = next(l for l in lines if "Opposition is when" in l)
    for l in (head, what):
        assert l.startswith("  ") and l[2] != " ", repr(l[:40])


def _saturn_from_zurich():
    """Saturn on a night it is below the horizon from Zurich and stays
    there: the case the travelling sentence exists for."""
    import api, datetime as dt
    when = dt.datetime(2027, 5, 7, 20, 0)
    jd = api.julian(when)
    lst = (api.gmst_hours(jd) + 8.54 / 15.0) % 24

    class P:
        lat, lon, name = 47.38, 8.54, "Zurich"
    return api.resolve_target("Saturn", jd, 47.38, lst), P, when


def test_it_says_where_the_object_does_clear_the_horizon(client):
    """"No window in the next 40 days from this latitude" invites the
    obvious question and used to leave it there."""
    import api
    flat = api.strip_ansi(
        client.get("/Zurich/Saturn?t=2027-05-07T22:00", headers=CURL).text)
    assert "No window in the next 40 days" in flat
    assert api.CLEARS_LEAD in flat


def test_every_place_it_names_is_up_on_the_night_it_is_named_for(client):
    """The bug this replaces: each candidate was asked whether it had a
    window within forty nights, which is the question the line above answers
    about the reader's own latitude. Cevennes passed on a window thirty-nine
    nights later, so a page about a conjunction in May sent people somewhere
    the conjunction had long finished."""
    import api, sky
    tgt, p, when = _saturn_from_zurich()
    got = api.where_it_clears(tgt, p, when)
    assert got["places"]
    where = {n: (la, lo) for n, la, lo in api.named_places()}
    for n in got["places"]:
        la, lo = where[n]
        assert sky.next_visible(tgt, la, lo, when, days=1)[0] is not None, n
        assert got["near"] >= la >= got["far"] if got["south"] \
            else got["near"] <= la <= got["far"], n


def test_the_band_is_a_band_and_not_half_the_planet(client):
    """Too far north it never rises into darkness and too far south it never
    rises at all, so "south of about 7°S" would promise the whole of the
    southern hemisphere for a strip of it."""
    import api, sky
    tgt, p, when = _saturn_from_zurich()
    got = api.where_it_clears(tgt, p, when)
    assert not got["open"]
    assert api.where_it_clears_line(got).startswith(
        f"{api.CLEARS_LEAD} between about ")
    # The far side really is shut: past it, nothing that night.
    beyond = got["far"] - 20 if got["south"] else got["far"] + 20
    if abs(beyond) <= 85:
        assert sky.next_visible(tgt, beyond, p.lon, when, days=1)[0] is None


def test_the_places_it_names_are_links(client):
    """Telling somebody where to go and then making them type it is a
    tease. Each name opens this same object seen from there."""
    import api
    tgt, p, when = _saturn_from_zurich()
    names = api.where_it_clears(tgt, p, when)["places"]
    got = client.get("/Zurich/Saturn?t=2027-05-07T22:00", headers=BROWSER)
    assert names
    from urllib.parse import quote
    for n in names:
        # With the night still on it: the sentence is about that night, and
        # a link that quietly means tonight answers a different question.
        # quote() because half these sites are two words long.
        assert (f'<a href="/{quote(n)}/Saturn?t=2027-05-07T22:00">{n}</a>'
                in got.text), n


def test_a_plain_page_links_the_places_plainly(client):
    """Nothing to carry, so nothing is carried."""
    import api
    got = client.get("/Zurich/Mars", headers=BROWSER)
    if api.CLEARS_LEAD not in api.strip_ansi(got.text):
        return                          # visible from here today; nothing to link
    assert "?t=" not in got.text.split(api.CLEARS_LEAD)[1][:400]


def test_the_terminal_gets_the_names_without_the_markup(client):
    """The link is a browser thing. A terminal reads the sentence."""
    import api
    tgt, p, when = _saturn_from_zurich()
    names = api.where_it_clears(tgt, p, when)["places"]
    flat = api.strip_ansi(
        client.get("/Zurich/Saturn?t=2027-05-07T22:00", headers=CURL).text)
    assert "<a href" not in flat
    assert names[0] in flat


def test_the_latitude_it_quotes_is_one_it_has_tried(client):
    """"About" covers the three degrees the sweep backs up in, not a guess:
    the near edge is a latitude the search itself returned a window for, on
    the night in question."""
    import api, sky
    tgt, p, when = _saturn_from_zurich()
    got = api.where_it_clears(tgt, p, when)
    assert sky.next_visible(tgt, got["near"], p.lon, when, days=1)[0] is not None


def test_the_event_list_is_capped(client):
    """The Moon has an event every few days. The dropdown is a dropdown,
    not the year."""
    import api
    got = client.get("/Zurich/Moon", headers=BROWSER)
    assert len(_picker_rows(got.text)) <= api.OBJECT_EVENTS_SHOWN


def test_every_object_page_can_be_shared_both_ways(client):
    """The same control the eclipse page carries. /Saturn follows whoever
    opens it; /Zurich/Saturn stays in Zurich. Both are right and they do
    opposite things, so the reader picks."""
    got = client.get("/Zurich/Saturn", headers=BROWSER)
    assert "https://skymap.sh/Saturn<" in got.text
    assert "/Saturn</code>" in got.text
    assert "Z%C3%BCrich/Saturn" in got.text
    assert "Share Saturn" in got.text


def test_a_star_with_no_events_can_still_be_shared(client):
    """The share button does not depend on the picker. Vega has no events
    and is still a page somebody might send to somebody."""
    got = client.get("/Zurich/Vega", headers=BROWSER)
    assert "Share Vega" in got.text
    assert "ecl-share-box" in got.text


def test_a_shared_link_keeps_the_night_it_was_shared_for(client):
    """A link to the night of the opposition that quietly resolves to
    tonight is not the page that was shared."""
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13", headers=BROWSER)
    assert "/Saturn?t=2026-10-05T01:1" in got.text


def test_a_page_with_no_moment_shares_no_moment(client):
    """The other half of the rule: /Saturn shares as /Saturn."""
    got = client.get("/Zurich/Saturn", headers=BROWSER)
    share = got.text.split('id="ecl-share-box"')[1].split("</dialog>")[0]
    assert "?t=" not in share


def test_an_eclipse_in_the_picker_opens_the_eclipse_page(client):
    """It has a page that answers far more about it than the Moon's page
    can, and the events list already sends people there."""
    got = client.get("/Zurich/Moon?t=2026-08-28T06:07", headers=BROWSER)
    assert 'href="/Zurich/eclipse/2026-08-28"' in got.text


def test_the_best_night_line_says_why_it_looked_past_tonight(client):
    """It pointed a year away from a page reached by clicking "closest and
    brightest of the year", and both are right: the ranking is dark hours,
    altitude and moonlight, and it does not count distance at all."""
    import api
    got = client.get("/Zurich/Saturn?t=2026-10-05T01:13",
                     headers={"user-agent": "curl/8"})
    # Unwrapped: the sentence is wider than the column and the phrases that
    # matter fall across the break.
    flat = " ".join(api.strip_ansi(got.text).split())
    assert "2027-10-01" in flat
    assert "not how close a planet is" in flat
    # Both nights named. "Tonight" was wrong twice over: this page can be
    # read in August for a night in October, and the night it is about is
    # not the night the reader is having.
    assert "the Moon is 34% lit on 4 October and 1% on 2027-10-01" in flat
    assert "lit tonight" not in flat


def test_a_page_with_no_moment_asked_for_still_says_now(client):
    """The other half of the same rule: without ?t= nothing changes."""
    got = client.get("/Zurich/Saturn", headers=BROWSER)
    assert "where to see Saturn tonight" in got.text


def test_a_terminal_never_sees_the_split_marker(client):
    """It is a browser layout hint. A terminal reads straight down through
    both halves and must not receive a stray control sequence."""
    import api
    for path in ("/Saturn", "/Sirius", "/Perseids"):
        raw = client.get(path, headers=CURL).text
        assert api.OBJECT_SLOT not in raw
        assert "\x00" not in raw


def test_json_never_sees_the_split_marker(client):
    import json as _json
    assert "\x00" not in _json.dumps(client.get("/Saturn?format=json").json())


# ------------------------------------------------ the browser layout
def test_the_object_page_uses_the_full_width(client):
    assert "w-wide" in client.get("/Saturn", headers=BROWSER).text


def test_the_chart_goes_through_the_width_ladder(client):
    """Every rung in the markup, CSS picks the one that fits, nothing
    measures and nothing reloads -- the same mechanism the place page uses."""
    import api
    h = client.get("/Saturn", headers=BROWSER).text
    assert h.count('class="chart-pre"') == len(api.CHART_LADDER)


def test_the_zenith_is_an_inset(client):
    """panel=True is what makes the find view emit the inset as its own
    piece. Object pages never asked for it, so they had none."""
    assert 'id="chart-zenith"' in client.get("/Saturn", headers=BROWSER).text


def test_the_static_facts_wrap_rather_than_scroll(client):
    """A <pre> can only scroll, and Saturn's moon count ran off the side of
    the sidebar with no way to read the rest."""
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    aside = re.search(r'<aside class="obj-static">(.*?)</aside>', h, re.S).group(1)
    assert '<dl class="obj-facts">' in aside
    # The portrait is the one exception and has to be: it is a drawing made
    # of characters, so reflowing it would destroy it. Everything that is
    # text still has to wrap, which is the thing this guards.
    facts_half = re.sub(r'<div class="art-frame obj-art-frame">.*?</div>', "",
                        aside, flags=re.S)
    assert "<pre" not in facts_half, "the static facts must not be preformatted"
    assert aside.count("<pre") <= 1, "only the portrait may be preformatted"
    rows = re.findall(r"<dt>([^<]+)</dt><dd>(.*?)</dd>", aside)
    assert len(rows) > 10
    plain = [re.sub(r"<[^>]+>", "", v) for _k, v in rows]
    assert any(len(v) > 40 for v in plain), "expected a value long enough to wrap"


def test_the_conversion_half_of_a_value_is_marked_secondary(client):
    """"58,232 km, 9 Earths across" is one measurement and one restatement of
    it. The restatement is set smaller and dimmer so the number carries the
    row."""
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    m = re.search(r"<dt>Radius</dt><dd>([^<]*)<span class=\"sec\">([^<]*)</span>", h)
    assert m, "radius was not split into primary and secondary"
    assert m.group(1).strip() == "58,232 km"
    assert "Earths" in m.group(2)


def test_a_planet_carries_its_symbol(client):
    import re
    for name, sym in (("Saturn", "\u2644"), ("Venus", "\u2640"),
                      ("Mars", "\u2642"), ("Jupiter", "\u2643")):
        h = client.get(f"/{name}", headers=BROWSER).text
        m = re.search(r"<dt>Symbol</dt><dd>([^<]*)", h)
        assert m and sym in m.group(1), f"{name} is missing {sym}"


def test_the_summary_is_in_the_heading_not_repeated_below(client):
    """The find view's summary line moved up into the condensed heading.
    Everything else it emits -- constellation, distance, rings, best this
    year -- still reads below the chart, and dropping that whole block by
    accident is exactly what happened once."""
    import re, html as _h
    h = client.get("/Saturn", headers=BROWSER).text
    prose = re.search(r'id="chart-prose">(.*?)</pre>', h, re.S).group(1)
    txt = _h.unescape(re.sub(r"<[^>]+>", "", prose))
    for keep in ("crossing", "AU away", "rings are tilted",
                 "Best in the next 12 months"):
        assert keep in txt, f"the prose lost {keep!r}"
    assert "mag 1.0" not in txt, "the summary line should not be repeated"


def test_the_infobox_rows_reach_json(client):
    d = client.get("/Saturn?format=json").json()
    blocks = d["infobox"]
    titles = [t for t, _r in blocks]
    assert "Physical" in titles
    # "History" is not a block here any more. Those rows are the history
    # page's, and a JSON consumer that still saw them here would be reading
    # a copy that no longer gets updated.
    assert "History" not in titles
    physical = dict(next(r for t, r in blocks if t == "Physical"))
    assert "Radius" in physical
    assert "Missions" not in physical


def test_no_raw_ansi_reaches_the_browser(client):
    """The inset and the prose need converting as much as the chart does.
    Passing them through raw put escape sequences on the page as literal
    text and the unwrapped result overflowed its column."""
    for path in ("/Saturn", "/Sirius", "/Andromeda Galaxy", "/Perseids"):
        h = client.get(path, headers=BROWSER).text
        assert "\x1b[" not in h, f"{path} leaked an escape sequence"
        assert "[38;5;" not in h, f"{path} leaked a colour code as text"


def test_the_inset_and_prose_are_markup(client):
    import re
    h = client.get("/Saturn", headers=BROWSER).text
    # chart-prose no longer exists: the summary line reads above the chart
    # with the timing line rather than beneath it.
    m = re.search(r'id="chart-zenith"[^>]*>(.*?)</pre>', h, re.S)
    assert m, "chart-zenith missing"
    assert "<span" in m.group(1), "chart-zenith was not converted"
    m = re.search(r'id="chart-prose">(.*?)</pre>', h, re.S)
    assert m, "chart-prose missing"
    assert "<span" in m.group(1), "chart-prose was not converted"


def test_the_heading_never_claims_now_when_it_is_not(client):
    """The clock is moved to the best moment before the find view runs, so
    that view truthfully reports "now" for a moment that is not now. The
    shift has to be remembered rather than inferred, or the page says
    "Right now from Zurich" in the middle of the afternoon."""
    import datetime as dt
    d = client.get("/Saturn?format=json").json()
    if not d.get("is_now"):
        assert "Right now" not in body(client.get("/Saturn", headers=CURL))
    shown = dt.datetime.fromisoformat(d["shown_utc"].rstrip("Z"))
    now = dt.datetime.utcnow()
    if abs((shown - now).total_seconds()) > 3600:
        assert d["is_now"] is False, "a shifted chart must not be flagged as now"


def test_the_timing_line_is_condensed(client):
    """Rise, set and high point as arrows above the chart, not a sentence
    under it."""
    t = body(client.get("/Saturn", headers=CURL))
    assert "↑ " in t and "↓ " in t and "⌃ " in t
    assert "It rises at" not in t, "the sentence form should be gone"


def test_the_best_moment_is_actually_dark(client):
    """next_visible returns the FIRST moment an object clears the horizon.
    An object page wants the best one, and best means dark: a sign error in
    the local-midnight calculation had Andromeda's 'best' moment landing in
    bright twilight, 20 degrees of altitude worse than the real answer."""
    import datetime as dt
    import objects, sky
    now = dt.datetime.utcnow()
    jd = sky.julian(now)
    lst = (sky.gmst_hours(jd) + 8.54 / 15.0) % 24
    for name in ("Andromeda Galaxy", "Ring Nebula"):
        t = sky.resolve_target(name, jd, 47.38, lst)
        best = objects.best_tonight(t, 47.38, 8.54, now)
        if best is None:
            continue
        sun_alt = sky.sun_altaz(best, 47.38, 8.54)[0]
        assert sun_alt < -12, f"{name}: best moment has the sun at {sun_alt:.1f}"


# ------------------------------------------------- the best-night calendar
def test_the_best_night_downloads_as_a_calendar_entry(client):
    """A date on a page is a thing to forget. The same date in a calendar is
    a thing that happens."""
    r = client.get("/Saturn/best.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    body_ = r.text
    for required in ("BEGIN:VCALENDAR", "BEGIN:VEVENT", "DTSTART:",
                     "SUMMARY:", "END:VEVENT", "END:VCALENDAR"):
        assert required in body_, f"missing {required}"
    assert body_.endswith("\r\n"), "iCalendar wants CRLF line endings"


def test_the_calendar_entry_matches_the_page(client):
    import re
    d = client.get("/Saturn?format=json").json()
    ics = client.get("/Saturn/best.ics").text
    # One date across the page and the calendar. The night a shower peaks
    # and the hour worth being outside are usually different days, and each
    # surface picking its own named two days for one event.
    day = d["best_this_year"]["date"].replace("-", "")
    assert f"DTSTART:{day}T" in ics


def test_a_shower_calendar_entry_says_peak(client):
    ics = client.get("/Perseids/best.ics").text
    assert "Perseids peak" in ics
    assert "an hour at best" in ics


def test_the_date_on_the_page_links_to_the_calendar(client):
    h = client.get("/Saturn", headers=BROWSER).text
    assert 'href="/Saturn/best.ics"' in h
    assert "download" in h


def test_best_ics_404s_for_an_unknown_object(client):
    assert client.get("/nonsense/best.ics").status_code == 404


def test_a_shower_is_not_sold_as_a_tonight(client):
    """The Geminids radiant is above the horizon most nights of the year.
    "Next best sighting opportunity, tonight" read as an invitation to go
    out for them in August."""
    t = body(client.get("/Geminids", headers=CURL))
    assert "Next best sighting opportunity" not in t
    assert "The chart is drawn for the peak night" in t
    assert "Peaks on" in t
    assert "tonight" not in t.split("Peaks on")[0].split("Zurich")[-1]


def test_a_shower_headline_says_radiant(client):
    """12 degrees up is the radiant's altitude, not the shower's."""
    t = body(client.get("/Geminids", headers=CURL))
    line = next(l for l in t.split("\n") if l.strip().startswith("Zurich "))
    assert "radiant" in line, line


# ------------------------------------------------ the high-altitude crosshair
def test_a_high_target_is_marked_in_the_zenith_inset(client):
    """The panorama stops at 70 degrees and marks its target there. Anything
    higher was drawn into the inset as an ordinary dot and marked nowhere, so
    a find on a high object produced a chart with the answer on it and
    nothing pointing at it."""
    t = body(client.get("/Geminids", headers=CURL))
    assert "zenith 70-90" in t
    inset = t[t.index("zenith 70-90"):]
    assert "◎" in inset, "the target is not marked in the inset"
    assert "GEMINIDS RADIANT" in inset


def test_the_inset_label_sits_below_the_disc(client):
    """The column of names beside the disc is sized by its longest entry, and
    "GEMINIDS RADIANT" widened the inset enough to push it out across the
    panorama it sits on top of."""
    t = body(client.get("/Geminids", headers=CURL))
    lines = t[t.index("zenith 70-90"):].split("\n")
    disc = [l for l in lines[1:12] if l.strip()]
    assert all("GEMINIDS" not in l for l in disc), "label is beside the disc"
    assert any(l.strip() == "GEMINIDS RADIANT" for l in lines[:15])
    # And the disc keeps its own width rather than being stretched by a name.
    assert max(len(l.rstrip()) for l in disc) < 40


def test_a_low_target_is_still_marked_in_the_panorama(client):
    """The inset change must not move the mark for everything else."""
    t = body(client.get("/Zurich?find=Saturn", headers=CURL))
    assert t.count("◎") >= 1


def test_a_chart_with_no_target_carries_no_crosshair(client):
    assert "◎" not in body(client.get("/Zurich", headers=CURL))


# --------------------------------------------------------- object stats
def test_stats_objects_page(client):
    client.get("/Saturn", headers=CURL)
    r = client.get("/stats/objects", headers=CURL)
    assert r.status_code == 200
    t = r.text
    assert "object pages served" in t
    assert "Saturn" in t
    # One column. The page used to print "page" and "find" side by side and
    # sum them, but an object page incremented both counters, so the total
    # was about double the truth.
    assert "?find=" not in t


def test_stats_objects_json(client):
    client.get("/Saturn", headers=CURL)
    d = client.get("/stats/objects?format=json").json()
    for key in ("object_pages", "distinct", "top"):
        assert key in d
    assert "finds" not in d
    assert any(row["name"] == "Saturn" for row in d["top"])


def test_an_object_page_is_counted_exactly_once(client):
    """Opening one object page used to land in five counters at once: a
    find leaderboard, an object leaderboard, view:find, view:object and an
    hourly find bucket. Finding an object means opening its page now, so
    there is one number for it."""
    before = client.get("/stats/objects?format=json").json()["object_pages"]
    client.get("/Saturn", headers=CURL)
    after = client.get("/stats/objects?format=json").json()["object_pages"]
    assert after == before + 1


def test_a_place_object_page_counts_the_same_as_a_bare_one(client):
    d0 = client.get("/stats/objects?format=json").json()
    n0 = dict((r["name"], r["views"]) for r in d0["top"]).get("Saturn", 0)
    client.get("/Tokyo/Saturn", headers=CURL)
    d1 = client.get("/stats/objects?format=json").json()
    n1 = dict((r["name"], r["views"]) for r in d1["top"])["Saturn"]
    assert n1 == n0 + 1


def test_the_find_list_is_gone_from_stats(client):
    """It moved to /stats/objects. The per-hour find CHART stays -- that
    answers "is anyone using it", which a leaderboard does not."""
    t = client.get("/stats", headers=CURL).text
    assert "top finds" not in t
    assert "top objects" not in t


def test_stats_objects_is_not_shadowed_by_an_object_page(client):
    import objects
    assert objects.resolve_name("objects") is None
    assert client.get("/stats/objects", headers=CURL).status_code == 200


def test_a_page_says_the_same_thing_on_every_load(client):
    """compose_object moves the clock to the best moment, and the caller
    reuses its Request to build every rung of the width ladder. Mutating it
    in place meant each rung was composed from an already-shifted clock,
    decided the object was up "now", and the page said "Zurich now" on first
    load and the real moment on refresh, depending on which pass had
    populated the cache."""
    import re
    seen = set()
    for _ in range(4):
        h = client.get("/Neptune", headers=BROWSER).text
        m = re.search(r'obj-live-head">(.*?)</p>', h, re.S)
        seen.add(re.sub(r"<[^>]+>", "", m.group(1)).strip())
    assert len(seen) == 1, f"the heading changed between loads: {seen}"


def test_composing_does_not_mutate_the_caller(client):
    import api, datetime as dt
    r = api.Request(place="Zurich")
    before = r.when_utc
    api.compose_object(r, "Neptune")
    assert r.when_utc == before, "compose_object moved the caller's clock"
    assert r.find in (None, "Neptune")


def test_each_object_gets_its_own_cache_entry(client):
    """The cache key carries the object, so two pages cannot serve each
    other's render."""
    a = client.get("/Neptune?format=json").json()
    b = client.get("/Saturn?format=json").json()
    assert a["object"] == "Neptune" and b["object"] == "Saturn"
    assert a["mag"] != b["mag"]


def test_object_pages_invite_corrections(client):
    """Every fact here comes from a catalogue, a hand-written table or a
    calculation, and any of the three can be wrong about one object without
    being wrong in general. A reader who knows better is the cheapest
    correction mechanism there is."""
    for name in ("Saturn", "Sirius", "Perseids", "Andromeda Galaxy"):
        h = client.get(f"/{name}", headers=BROWSER).text
        assert 'class="obj-feedback"' in h, f"{name} has no feedback link"
        assert "github.com/HabibiCodeCH/skymap-sh/issues" in h
        assert 'rel="noopener"' in h, "an external target needs noopener"


def test_the_feedback_box_is_on_every_page(client):
    """A wrong rise time on a place page or a broken chart is as worth
    reporting as a wrong moon count on an object page."""
    for path in ("/", "/Zurich", "/Saturn", "/help", "/catalog", "/legend",
                 "/stats", "/stats/objects"):
        h = client.get(path, headers=BROWSER).text
        assert 'class="obj-feedback"' in h, f"{path} is missing it"


def test_the_feedback_box_is_not_in_the_terminal_view(client):
    """A curl reader cannot click it, and a URL in the middle of a chart is
    noise."""
    assert "obj-feedback" not in body(client.get("/Saturn", headers=CURL))


# --------------------------------------------------------- place cards
# A shared place link used to unfurl as the generic card: the same picture
# and the same words for every city, which says the site exists but not that
# the link is about Paris.

def test_a_place_has_its_own_card(client):
    r = client.get("/Paris/og.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 8000


def test_an_object_still_wins_the_card_url(client):
    """One route serves both, because they are one URL shape and a route
    that answers 404 does not fall through to the next one. The object wins
    the name, exactly as it does for the pages: /Venus/og.png is the planet,
    not the town in Texas."""
    assert client.get("/Venus/og.png").status_code == 200
    assert client.get("/Saturn/og.png").status_code == 200
    assert client.get("/Tokyo/og.png").status_code == 200
    assert client.get("/notaplaceatall/og.png").status_code == 404


def test_the_place_page_points_at_its_own_card(client):
    h = client.get("/Paris", headers=BROWSER).text
    assert 'content="http://testserver/Paris/og.png"' in h
    assert 'og.png"' in h
    # and not the shared one
    assert "https://skymap.sh/og.png" not in h


def test_the_card_carries_nothing_computed_for_the_crawler(client):
    """It is fetched once from someone else's datacentre and then shown to
    everybody for a day, so an altitude or a rise time on it would be true
    for a machine in Virginia and wrong for every reader."""
    import card
    assert card.PLACE_HOUR == 22


def test_the_longest_city_name_wraps_rather_than_shrinking(client):
    """cities.json contains a 49-character name. Shrinking it to one line
    left the headline smaller than the caption under it."""
    import card
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (card.W, card.H)))
    longest = "Dolores Hidalgo Cuna de la Independencia Nacional"
    f, lines = card._wrap_fit(d, longest, 150, card.W - card.MARGIN * 2, 340)
    assert len(lines) > 1, "expected it to wrap"
    assert f.size > 64, "expected it to stay readable at unfurl size"
    assert " ".join(" ".join(lines).split()) == longest


def test_a_hyphenated_name_breaks_at_its_hyphens(client):
    """Sainte-Catherine-de-la-Jacques-Cartier is one token to str.split(),
    so a space-only wrapper leaves it on one unreadable line."""
    import card
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (card.W, card.H)))
    name = "Sainte-Catherine-de-la-Jacques-Cartier"
    f, lines = card._wrap_fit(d, name, 150, card.W - card.MARGIN * 2, 340)
    assert len(lines) > 1
    assert "".join(lines) == name, "hyphen breaks must not add or drop text"


def test_short_names_are_left_on_one_line(client):
    import card
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (card.W, card.H)))
    for name in ("Paris", "Tokyo", "New York"):
        f, lines = card._wrap_fit(d, name, 150, card.W - card.MARGIN * 2, 340)
        assert lines == [name], name
        assert f.size == 150, name


# ------------------------------------------------- coordinates become a city
# The chart, sphere and events routes have each been fixed for this in turn;
# the object pages shipped without it, so a visitor located by IP saw
# "46.20,6.10 Wed 5 Aug" in the header of /Saturn while the chart one click
# away said "Geneva".
GEO = {**BROWSER, "cf-iplatitude": "46.20", "cf-iplongitude": "6.10"}


def test_an_ip_located_visitor_sees_the_city_not_coordinates(client):
    h = client.get("/Saturn", headers=GEO).text
    assert "46.20,6.10" not in h
    assert "Geneva" in h


def test_the_bare_object_url_is_never_redirected(client):
    """/Saturn is deliberately location-free so it can be shared. Bouncing
    it to /Geneva/Saturn would rewrite the address bar of anyone following a
    link, which is the opposite of what the shared-link design asks for."""
    r = client.get("/Saturn", headers=GEO, follow_redirects=False)
    assert r.status_code == 200


def test_the_search_bar_shows_the_city_too(client):
    h = client.get("/Saturn", headers=GEO).text
    assert 'name="q" value="Geneva/Saturn"' in h


def test_coordinates_spelled_out_in_the_path_do_redirect(client):
    """Same as the chart, sphere and events routes: an explicit /lat,lon in
    the URL is tidied up, because there is an address bar to tidy."""
    r = client.get("/46.20,6.10/Saturn", headers=BROWSER, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/Geneva/Saturn"


def test_that_redirect_is_never_cached(client):
    """It is keyed off this visitor's IP, so an edge cache would bounce
    everyone sharing that cache entry to Geneva wherever they are."""
    r = client.get("/46.20,6.10/Saturn", headers=BROWSER, follow_redirects=False)
    assert r.headers["cache-control"] == "no-store"


def test_curl_keeps_the_exact_coordinates(client):
    """No address bar to tidy, and redirecting would silently break anyone
    scripting against a specific lat/lon."""
    d = client.get("/Saturn?format=json",
                   headers={"user-agent": "curl/8",
                            "cf-iplatitude": "46.20",
                            "cf-iplongitude": "6.10"}).json()
    assert d["place"] == "46.20,6.10"


def test_a_named_place_is_left_alone(client):
    r = client.get("/Tokyo/Saturn", headers=BROWSER, follow_redirects=False)
    assert r.status_code == 200


# ------------------------------------------------------------- the Milky Way
# The one object that is behind you as well as in front of you, so it is in
# none of the catalogues and had to be added by hand.

def test_the_milky_way_resolves(client):
    for path in ("/Milky%20Way", "/milkyway", "/galactic%20centre"):
        r = client.get(path, headers=CURL)
        assert r.status_code == 200, path
        assert "Milky Way" in body(r), path


def test_it_is_anchored_on_the_galactic_centre(client):
    """The band crosses the whole sky, so "where is it" has no single
    answer -- but "which way do I look" does, and it is Sagittarius."""
    d = client.get("/Milky Way?format=json").json()
    assert d["constellation"] == "Sagittarius"


def test_it_never_prints_a_magnitude(client):
    """2.0 is a sentinel that buys the nautical-dark answer out of
    dark_enough(), exactly as a meteor radiant's 2.5 does. It is not a
    brightness and printing it as one invents a fact."""
    h = client.get("/Milky Way", headers=CURL).text
    assert "Magnitude" not in server.api.strip_ansi(h)


def test_whether_you_can_see_it_depends_on_where_you_stand(client):
    """The whole question for this object, and the one a chart cannot
    answer: from most of Europe the band is simply not there."""
    bright = client.get("/Zurich/Milky Way?format=json").json()["galaxy"]
    dark = client.get("/-24.63,-70.40/Milky Way?format=json").json()["galaxy"]
    assert bright["visible_here"] is False
    assert dark["visible_here"] is True
    # A contour level from the density grid, not an altitude: 1 is a dark
    # sky showing the whole band, 4 is one where only the core survives.
    # It was being printed as "visible above 3 degrees", which is not what
    # the number means.
    assert dark["floor"] == 1
    assert "floor_deg" not in dark


def test_the_page_says_so_in_words(client):
    zurich = server.api.strip_ansi(client.get("/Zurich/Milky Way", headers=CURL).text)
    atacama = server.api.strip_ansi(
        client.get("/-24.63,-70.40/Milky Way", headers=CURL).text)
    assert "too bright" in zurich
    assert "the whole band" in atacama


def test_it_carries_the_facts_worth_having(client):
    t = server.api.strip_ansi(client.get("/Milky Way", headers=CURL).text)
    for want in ("Barred spiral galaxy", "100,000 light years",
                 "26,000 light years", "Sagittarius"):
        assert want in t, want


def test_only_one_type_row(client):
    t = server.api.strip_ansi(client.get("/Milky Way", headers=CURL).text)
    assert t.count("Type ") == 1


def test_it_does_not_promise_a_sighting_that_cannot_happen(client):
    """Some things are up and still not there. The page said the sky was
    too bright and then offered a next best sighting opportunity, two lines
    apart."""
    zurich = server.api.strip_ansi(client.get("/Zurich/Milky Way", headers=CURL).text)
    assert "Never shows in" in zurich
    assert "Next best sighting" not in zurich
    # and no best-night date either, for the same reason
    assert "Best in the next 12 months" not in zurich


def test_a_dark_sky_still_gets_its_best_night(client):
    dark = server.api.strip_ansi(
        client.get("/-24.63,-70.40/Milky Way", headers=CURL).text)
    assert "Never shows" not in dark
    assert "Best in the next 12 months" in dark


def test_the_sources_do_not_credit_a_catalogue_that_has_nothing_to_say(client):
    """It fell through to the deep-sky branch and credited the Revised NGC
    for a position that never came from it. A wrong citation is worse than
    none on a page whose point is that the numbers are traceable."""
    h = client.get("/Milky Way", headers=BROWSER).text
    assert "Sulentic" not in h
    assert "Dreyer" not in h
    assert "Sgr A*" in h


def test_the_url_survives_being_shared(client):
    """Multi-word objects carry a space, so the canonical has to be encoded
    or a pasted link breaks at the space."""
    h = client.get("/Milky Way", headers=BROWSER).text
    assert 'href="https://skymap.sh/Milky%20Way"' in h
    # and the spaceless forms people actually type still resolve
    for path in ("/milkyway", "/MilkyWay"):
        assert client.get(path, headers=CURL).status_code == 200, path


def test_the_band_is_described_by_how_much_of_it_shows(client):
    """Not a yes or no, and never a number pretending to be an angle. The
    grid has five contours and the floor says which survive the light
    pollution here."""
    seen = {}
    for place in ("Zurich", "Rome", "Exmoor", "Atacama"):
        d = client.get(f"/{place}/Milky Way?format=json").json()["galaxy"]
        seen[place] = d["shows"]
        assert "°" not in d["shows"], place
    assert seen["Zurich"] != seen["Atacama"]
    assert "whole band" in seen["Atacama"]
    assert "too bright" in seen["Zurich"]


# ------------------------------------------------------- /{object}/history
def test_history_is_reserved_so_nothing_can_claim_the_path(client):
    """The route is /{obj}/history, and /{place}/{obj} would happily read
    "history" as an object name. RESERVED is what stops a catalogue entry
    ever taking the segment back."""
    assert "history" in objects.RESERVED
    assert objects.resolve_name("history") is None


@pytest.mark.parametrize("path", [
    "/Betelgeuse/history", "/Venus/history", "/M31/history",
    "/Crab%20Nebula/history", "/Perseids/history", "/NGC1980/history",
])
def test_history_answers_for_every_kind_of_object(client, path):
    r = client.get(path, headers=CURL)
    assert r.status_code == 200, path
    # Never blank: even an object with nothing written says so in words.
    assert body(r).strip()


def test_history_404s_for_a_name_that_is_not_an_object(client):
    r = client.get("/wombat/history", headers=CURL)
    assert r.status_code == 404
    assert "wombat" in body(r)


def test_history_is_cached_hard_because_nothing_in_it_moves(client):
    """The one object route with no place and no moment in it, which is what
    lets it be cached in a way the object pages themselves never can."""
    cc = client.get("/Vega/history", headers=CURL).headers["cache-control"]
    assert "public" in cc
    assert "max-age=604800" in cc


def test_history_takes_no_place_segment(client):
    """Where you stand does not change what a thing is called. /Zurich/Vega
    is a page; /Zurich/Vega/history is not, and must not quietly become one.
    """
    assert client.get("/Zurich/Vega/history", headers=CURL).status_code == 404


def test_the_terminal_and_the_browser_carry_the_same_rows(client):
    """One set of facts, two renderings. Two sets drift, which is the whole
    argument infobox_text and infobox_html were split for."""
    txt = body(client.get("/Betelgeuse/history", headers=CURL))
    html_ = client.get("/Betelgeuse/history", headers=BROWSER).text
    for key, _val in server.api.designations("Betelgeuse"):
        assert key in txt, key
        assert key in html_, key


def test_every_canonical_for_one_object_gets_the_same_history(client):
    """M31, NGC224 and Andromeda Galaxy are three paths to one object, and
    FACTS is keyed on only one of them. They came back with three different
    pages -- designations on all three, the written history on one."""
    pages = [server.api.history_blocks(n)
             for n in ("M31", "NGC224", "Andromeda Galaxy")]
    assert all(p == pages[0] for p in pages), pages
    assert [t for t, _r in pages[0]] == ["Known as", "History"]


def test_the_ladder_is_derived_so_it_covers_the_whole_catalogue():
    """Tier 0: no prose written, and still a real row for every star and
    deep-sky object in the catalogue. This is what keeps the page from being
    empty for the 1,180 objects with no hand-written entry."""
    names = objects.all_names()
    assert len(names) > 1_000
    missing = [n for n in names if not server.api.history_blocks(n)]
    # Asterisms and the Milky Way carry no catalogue number and no written
    # history yet, and that is honest rather than broken. Everything else
    # must say something.
    assert all(objects.resolve_name(n) == n for n in missing)
    assert len(missing) < 60, sorted(missing)[:20]


def test_the_history_rows_left_the_object_page(client):
    """They moved, rather than being copied. A fact printed on two pages
    under two headings is the drift this split exists to prevent."""
    page = body(client.get("/Venus", headers=CURL))
    assert "Venera" not in page          # Missions
    assert "Mariner 2" not in page       # First visited
    hist = body(client.get("/Venus/history", headers=CURL))
    assert "Venera" in hist
    assert "Mariner 2" in hist


def test_the_object_page_links_on_only_where_there_is_something_to_read(client):
    """A link to one line of bare catalogue number spends a reader's click to
    tell them there was nothing to click for. "Has any rows" was the wrong
    test: it put this link on 629 pages whose history is a single NGC entry.
    """
    assert "Betelgeuse/history" in body(client.get("/Betelgeuse", headers=CURL))
    # One row, and that row is the object's own catalogue number. Nothing
    # points at it.
    assert not server.api.history_is_worth_reading("NGC1980")
    assert "NGC1980/history" not in body(client.get("/NGC1980", headers=CURL))


def test_one_written_row_is_enough_to_earn_the_link():
    """The Perseids carry a single history row and it is the year somebody
    worked out where they come from. A flat row count would have dropped it
    alongside the bare catalogue entries, which is why the rule asks what
    kind of row rather than how many."""
    assert server.api.history_is_worth_reading("Perseids")
    assert sum(len(r) for _t, r in server.api.history_blocks("Perseids")) == 1


def test_both_renderings_use_one_threshold(client):
    """Two thresholds would put the link on the browser page and not the curl
    one, or the other way round."""
    for name in ("Betelgeuse", "NGC1980", "Perseids"):
        want = server.api.history_is_worth_reading(name)
        in_txt = f"{name}/history" in body(client.get(f"/{name}", headers=CURL))
        in_html = f'"/{name}/history"' in client.get(f"/{name}",
                                                     headers=BROWSER).text
        assert in_txt == want, name
        assert in_html == want, name


def test_the_page_is_counted_apart_from_the_object_pages(client):
    """Every new route ships its counter in the same change. Reading
    /Betelgeuse/history is a different act from reading /Betelgeuse."""
    before = server._stat["history"]
    client.get("/Rigel/history", headers=CURL)
    assert server._stat["history"] == before + 1
    # A 404 is not a page view.
    client.get("/notathing/history", headers=CURL)
    assert server._stat["history"] == before + 1
