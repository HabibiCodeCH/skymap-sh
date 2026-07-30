#!/usr/bin/env python3
"""
skymap.sh — one URL, four consumers.

    curl skymap.sh/Zurich                    -> ANSI text
    curl -H 'Accept: text/plain' ...      -> text, no escape codes
    browser                               -> the same output in a page
    ?format=json                          -> the same facts, structured

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import datetime as dt, json, os, time
from collections import OrderedDict
from fastapi import FastAPI, Request as Req
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse

import api, sky, tle

app = FastAPI(title="skymap.sh", docs_url=None, redoc_url=None)

# Clients that want the terminal rendering even though they send Accept: */*
TERMINALS = ("curl", "wget", "httpie", "http/", "powershell", "libcurl", "lwp",
             "python-requests", "fetch")
# --- response cache ----------------------------------------------------------
# Rendering is 5.5 ms; serving a cached render is a dict lookup. Requests are
# bucketed in time, so 30 people (or one loop) asking within the same bucket all
# get the first render. Night moves fast enough to want a minute; by day the
# only thing changing is the Sun marker, quantised to 10 minutes, so a daytime
# answer stays true for a quarter of an hour.
# Bucket sizes are set by what a cell is worth, not by taste. The sky turns
# 0.25 deg/min and one column is ~3.1 deg wide, so a 5-minute bucket is 1.25 deg
# — visually identical. By day the only moving thing is the Sun marker, and the
# day view is coarser, so 15 minutes is the same argument. Edge TTL equals the
# bucket, so nothing is ever served staler than one bucket.
NIGHT_BUCKET = 300          # seconds
DAY_BUCKET = 900            # seconds
NIGHT_TTL, DAY_TTL = 420, 1200        # origin holds a little past the bucket
NIGHT_EDGE, DAY_EDGE = 300, 900
CACHE_MAX = 3000
_cache = OrderedDict()      # key -> (expires_at, Result)
_hits = _misses = 0

# --- usage counters ----------------------------------------------------------
# What people ask for, not who asked. No IPs, no user agents, no timestamps per
# request — just tallies, so there is nothing here worth leaking and nothing to
# put in a privacy policy.
#
# Origin only sees cache misses, which is a small and unrepresentative slice of
# real traffic. Cloudflare's analytics is the honest number for volume; this is
# for the product question: which places, which objects, which views.
from collections import Counter
STARTED = time.time()
_stat = Counter()
_places = Counter()
_finds = Counter()
_TOP_KEEP = 2000            # trim the long tail so the tables cannot grow forever


def _tally(r, daytime, hit, mode, status, data):
    _stat["requests"] += 1
    _stat["hit" if hit else "miss"] += 1
    _stat["day" if daytime else "night"] += 1
    _stat[f"mode:{mode}"] += 1
    if status != 200:
        _stat[f"status:{status}"] += 1
    _stat["view:find" if r.find else
          f"view:{'facing' if r.facing else r.view}"] += 1
    # ISS is shown to everyone now, so this counts something more useful than
    # "asked for it": how often a visitor's chart actually included a real pass.
    if data.get("iss_pass"):
        _stat["iss"] += 1
    _places[r.place.name] += 1
    if r.find:
        _finds[r.find.strip().title()[:40]] += 1
    if len(_places) > _TOP_KEEP:
        for k, _v in _places.most_common()[_TOP_KEEP:]:
            del _places[k]
    if len(_finds) > _TOP_KEEP:
        for k, _v in _finds.most_common()[_TOP_KEEP:]:
            del _finds[k]


def stats_text(n=15):
    up = time.time() - STARTED
    req = _stat["requests"] or 1
    L = [f"skymap.sh — {req:,} requests over {up/3600:.1f} h "
         f"({req/max(up,1)*60:.1f}/min)", ""]
    L.append(f"cache      {_stat['hit']:,} hit / {_stat['miss']:,} miss "
             f"({100*_stat['hit']/req:.1f}% hit)")
    L.append(f"sky        {_stat['night']:,} night / {_stat['day']:,} day")
    L.append("")
    L.append("views")
    for k in sorted(k for k in _stat if k.startswith("view:")):
        L.append(f"  {k[5:]:12} {_stat[k]:>8,}")
    if _stat["iss"]:
        L.append(f"  {'iss':12} {_stat['iss']:>8,}")
    L.append("")
    L.append("output")
    for k in sorted(k for k in _stat if k.startswith("mode:")):
        L.append(f"  {k[5:]:12} {_stat[k]:>8,}")
    errs = sorted(k for k in _stat if k.startswith("status:"))
    if errs:
        L.append("")
        L.append("non-200")
        for k in errs:
            L.append(f"  {k[7:]:12} {_stat[k]:>8,}")
    L.append("")
    L.append(f"top places ({len(_places):,} distinct)")
    for name, c in _places.most_common(n):
        L.append(f"  {name[:28]:28} {c:>8,}")
    if _finds:
        L.append("")
        L.append(f"top finds ({len(_finds):,} distinct)")
        for name, c in _finds.most_common(n):
            L.append(f"  {name[:28]:28} {c:>8,}")
    return "\n".join(L) + "\n"


def stats_json(n=50):
    return dict(
        uptime_s=round(time.time() - STARTED),
        requests=_stat["requests"], cache_hit=_stat["hit"], cache_miss=_stat["miss"],
        night=_stat["night"], day=_stat["day"], iss=_stat["iss"],
        views={k[5:]: v for k, v in _stat.items() if k.startswith("view:")},
        modes={k[5:]: v for k, v in _stat.items() if k.startswith("mode:")},
        errors={k[7:]: v for k, v in _stat.items() if k.startswith("status:")},
        places_distinct=len(_places), finds_distinct=len(_finds),
        top_places=dict(_places.most_common(n)),
        top_finds=dict(_finds.most_common(n)),
    )

# --- per-IP rate limit -------------------------------------------------------
# The sky does not change in a second, but `watch -n 1 curl skymap.sh` does not know
# that: one such client is 86,400 requests a day. A token bucket costs a dict
# entry and stops it becoming someone else's bill.
#
# NOTE: this is per process. With N gunicorn workers the effective ceiling is
# N x RATE, so divide, or move the buckets to Redis if you run more than one box.
RATE = 30                   # sustained requests per minute per IP
BURST = 45                  # allowed spike before shaping kicks in
MAX_IPS = 20000             # bounded so the table cannot grow without limit
_buckets = OrderedDict()    # ip -> [tokens, last_seen]


def client_ip(request: Req):
    h = request.headers
    for k in ("cf-connecting-ip", "x-real-ip"):
        if h.get(k):
            return h[k]
    if h.get("x-forwarded-for"):
        return h["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else "?"


def take_token(ip, now=None):
    """True if allowed. Returns (ok, retry_after_seconds)."""
    now = now or time.monotonic()
    tokens, last = _buckets.pop(ip, (BURST, now))
    tokens = min(BURST, tokens + (now - last) * RATE / 60.0)
    ok = tokens >= 1.0
    if ok:
        tokens -= 1.0
    _buckets[ip] = (tokens, now)
    if len(_buckets) > MAX_IPS:
        _buckets.popitem(last=False)          # evict least recently seen
    return ok, 0 if ok else max(1, int((1.0 - tokens) * 60 / RATE))


THROTTLED = """\
  Slow down a moment.

  You are asking faster than {rate} requests a minute, which is faster than the
  sky changes — positions here are recomputed every 5 minutes, so a tighter loop
  returns you the same picture and costs us both.

  If you want it live on screen:   watch -n 300 curl -s skymap.sh/{place}

  Try again in {retry}s.
"""


@app.on_event("startup")
def _warm():
    """Parse the catalogues once, and check the element set we shipped with."""
    sky._load("stars.json"); sky._load("asterisms.json")
    p = tle.current()
    app.state.tle = p
    if p:
        try:
            tle.validate(open(p).read())
            print(f"[startup] TLE ok, {tle.age(p)/3600:.1f}h old")
        except Exception as e:
            print(f"[startup] TLE unusable ({e}); ISS disabled")
            app.state.tle = None
    else:
        print("[startup] no TLE on disk; run tle.py — ISS disabled")


def _wants(request: Req):
    """(mode, colour). mode is 'json' | 'html' | 'text'."""
    q = request.query_params
    ua = (request.headers.get("user-agent") or "").lower()
    accept = (request.headers.get("accept") or "").lower()
    terminal = any(t in ua for t in TERMINALS)

    if q.get("format") == "json":
        return "json", False
    if not terminal and "text/html" in accept:
        return "html", True
    if q.get("plain") or (not terminal and "text/plain" in accept):
        return "text", False
    return "text", "plain" not in q


def _geo(request: Req):
    """Coordinates from the CDN, so a bare `curl skymap.sh` knows where you are.
    Cloudflare sets these; other CDNs use different names."""
    h = request.headers
    for la, lo in (("cf-iplatitude", "cf-iplongitude"),
                   ("x-vercel-ip-latitude", "x-vercel-ip-longitude"),
                   ("fly-client-latitude", "fly-client-longitude")):
        if h.get(la) and h.get(lo):
            try:
                # 0.1 deg is about 11 km — the same sky, and it collapses a
                # whole city onto one cache entry.
                return round(float(h[la]), 1), round(float(h[lo]), 1)
            except ValueError:
                pass
    return None


def _build(request: Req, place: str | None):
    q = request.query_params
    when = None
    if q.get("t"):
        try:
            when = dt.datetime.fromisoformat(q["t"].replace("Z", ""))
        except ValueError:
            pass
    span = None
    if q.get("span"):
        try:
            span = float(q["span"])
        except ValueError:
            pass
    return api.Request(
        place=place,
        when=when,
        view="disc" if q.get("view") == "disc" else "horizon",
        facing=q.get("facing") or None,
        span=span,
        find=q.get("find") or None,
        lines=not q.get("nolines"),
        color=True,
        fallback=_geo(request),
        tle=app.state.tle,   # shown automatically whenever a real pass is up;
                             # ?iss= is no longer required, kept as a no-op
        night=bool(q.get("night")),
    )


UNKNOWN = """\
  Don't know '{q}'.
{did}
  Coordinates work too:  curl skymap.sh/47.38,8.54
  Or just:               curl skymap.sh          (located by your IP)
  Add a country or state when a name repeats:
                         curl 'skymap.sh/San Francisco, US'
                         curl 'skymap.sh/Paris, TX'
"""


def _cache_key(r, daytime):
    q = (round(r.place.lat, 1), round(r.place.lon, 1), r.view, r.facing, r.span,
         (r.find or "").lower(), bool(r.tle), r.night)
    bucket = DAY_BUCKET if daytime else NIGHT_BUCKET
    stamp = int(r.when_utc.timestamp() // bucket)
    return (q, stamp)


def _cached(r):
    """(Result, daytime, from_cache). One entry serves all four output modes."""
    global _hits, _misses
    daytime = api.is_daytime(r)
    key = _cache_key(r, daytime)
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        _cache.move_to_end(key)
        _hits += 1
        return hit[1], daytime, True
    _misses += 1
    r.color = True                      # cache the coloured render; strip on the way out
    res = api.compose(r)
    _cache[key] = (now + (DAY_TTL if daytime else NIGHT_TTL), res)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return res, daytime, False


def _respond(request: Req, place: str | None):
    mode, colour = _wants(request)
    if place and api.lookup_place(place) is None:
        near = api.suggest(place)
        did = ("\n  Did you mean:\n" + "".join(f"    {n}\n" for n in near)
               if near else "")
        _stat["requests"] += 1; _stat["status:404"] += 1; _stat[f"mode:{mode}"] += 1
        msg = UNKNOWN.format(q=place[:60], did=did)
        if mode == "json":
            return JSONResponse({"error": "unknown_place", "query": place,
                                 "suggestions": near}, status_code=404)
        return PlainTextResponse(msg, status_code=404)
    r = _build(request, place)
    res, daytime, hit = _cached(r)
    _tally(r, daytime, hit, mode, res.status, res.data)
    edge = DAY_EDGE if daytime else NIGHT_EDGE
    headers = {"Cache-Control": f"public, max-age={edge // 4}, s-maxage={edge}, "
                                f"stale-while-revalidate=600",
               "X-Cache": "HIT" if hit else "MISS"}
    if mode == "json":
        return JSONResponse(res.data, status_code=res.status, headers=headers)
    if mode == "html":
        body = api.PAGE.format(title=f"skymap.sh — {r.place.name}",
                               path=f"/{r.place.slug}" if place else "",
                               body=api.ansi_to_html(res.text))
        return HTMLResponse(body, status_code=res.status, headers=headers)
    text = res.text if colour else api.strip_ansi(res.text)
    return PlainTextResponse(text, status_code=res.status, headers=headers)


@app.middleware("http")
async def ratelimit(request: Req, call_next):
    if request.url.path in ("/healthz", "/robots.txt", "/stats"):
        return await call_next(request)
    ok, retry = take_token(client_ip(request))
    if not ok:
        place = (request.url.path.strip("/") or "Zurich").split("?")[0]
        return PlainTextResponse(
            THROTTLED.format(rate=RATE, retry=retry, place=place),
            status_code=429,
            headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
    resp = await call_next(request)
    resp.headers["X-RateLimit-Limit"] = str(RATE)
    return resp


@app.get("/help", response_class=PlainTextResponse)
@app.get("/usage", response_class=PlainTextResponse)
def help_():
    return PlainTextResponse(api.HELP, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    p = app.state.tle
    total = _hits + _misses
    return PlainTextResponse(
        f"ok stars={len(sky._load('stars.json'))} "
        f"asterisms={len(sky._load('asterisms.json'))} "
        f"tle={'%.1fh' % (tle.age(p)/3600) if p else 'none'} "
        f"cache={len(_cache)}/{CACHE_MAX} "
        f"hitrate={100*_hits/total:.1f}% ({_hits}/{total}) "
        f"nv={api.nv_stats()}\n" if total else
        f"ok cache empty\n")


@app.get("/stats", response_class=PlainTextResponse)
def stats(request: Req):
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_json(), headers={"Cache-Control": "no-store"})
    return PlainTextResponse(stats_text(), headers={"Cache-Control": "no-store"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\n")


@app.get("/")
def root(request: Req):
    return _respond(request, None)


@app.get("/{place:path}")
def place(request: Req, place: str):
    if place.startswith(("favicon", ".well-known")):
        return PlainTextResponse("", status_code=404)
    return _respond(request, place)
