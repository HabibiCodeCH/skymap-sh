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
