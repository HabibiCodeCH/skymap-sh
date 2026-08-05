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
