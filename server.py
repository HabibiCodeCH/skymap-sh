#!/usr/bin/env python3
"""
skymap.sh — one URL, four consumers.

    curl skymap.sh/Zurich                    -> ANSI text
    curl -H 'Accept: text/plain' ...      -> text, no escape codes
    browser                               -> the same output in a page
    ?format=json                          -> the same facts, structured

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio, datetime as dt, html, json, os, re, secrets, time
from collections import OrderedDict
from fastapi import FastAPI, Request as Req
from fastapi.responses import (PlainTextResponse, HTMLResponse, JSONResponse,
                               StreamingResponse, FileResponse, Response)

import api, gif, sky, tle

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

# --- hourly history -----------------------------------------------------------
# _stat/_places/_finds above are the whole point of the "no IPs, no
# timestamps" design -- but they're purely in-memory, so a restart (deploy,
# crash, systemd bounce) silently zeroes them with no record anything
# happened. This appends one line per COMPLETED hour to a local file --
# still just tallies (requests/hits/misses/day/night), not raw events -- so
# a restart loses at most the current partial hour, not the whole history.
HOURLY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats_hourly.jsonl")
# Never trimmed -- one line per hour is tiny (a year is ~8,760 lines), so the
# file just keeps the whole history. This only caps how far back ?days= can
# ask the /stats/hourly view to look, not how much is actually kept on disk.
HOURLY_MAX_QUERY_DAYS = 3650
_hour_key = None
_hour_stat = Counter()


def _flush_hour(hour_key, hstat):
    if not hstat:
        return
    row = dict(hour=hour_key, requests=hstat["requests"], hit=hstat["hit"],
              miss=hstat["miss"], day=hstat["day"], night=hstat["night"])
    try:
        with open(HOURLY_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _roll_hour():
    global _hour_key, _hour_stat
    now_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
    if _hour_key is None:
        _hour_key = now_key
    elif now_key != _hour_key:
        _flush_hour(_hour_key, _hour_stat)
        _hour_key, _hour_stat = now_key, Counter()


def _read_hourly_history(days=7):
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    rows = []
    try:
        with open(HOURLY_LOG) as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if dt.datetime.fromisoformat(row["hour"]) >= cutoff:
                        rows.append(row)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except OSError:
        pass
    return rows


def _tally(r, daytime, hit, mode, status, data):
    _roll_hour()
    _stat["requests"] += 1
    _stat["hit" if hit else "miss"] += 1
    _stat["day" if daytime else "night"] += 1
    _stat[f"mode:{mode}"] += 1
    _hour_stat["requests"] += 1
    _hour_stat["hit" if hit else "miss"] += 1
    _hour_stat["day" if daytime else "night"] += 1
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


def stats_hourly_text(days=7):
    _roll_hour()
    rows = _read_hourly_history(days=days)
    if _hour_stat:
        rows = rows + [dict(hour=_hour_key, requests=_hour_stat["requests"],
                            hit=_hour_stat["hit"], miss=_hour_stat["miss"],
                            day=_hour_stat["day"], night=_hour_stat["night"])]
    if not rows:
        return "skymap.sh — hourly stats\n\nno data yet (first hour still in progress)\n"
    L = [f"skymap.sh — hourly stats, last {days}d ({len(rows)} hour(s) on record)", "",
        f"{'hour (UTC)':17} {'requests':>9} {'hit%':>6} {'day':>6} {'night':>6}"]
    for row in rows:
        req = row["requests"] or 1
        hitpct = 100 * row["hit"] / req
        current = "  (in progress)" if row["hour"] == _hour_key and row is rows[-1] else ""
        L.append(f"{row['hour']:17} {row['requests']:>9,} {hitpct:>5.1f}% "
                f"{row['day']:>6,} {row['night']:>6,}{current}")
    return "\n".join(L) + "\n"


def stats_hourly_json(days=7):
    _roll_hour()
    rows = _read_hourly_history(days=days)
    if _hour_stat:
        rows = rows + [dict(hour=_hour_key, requests=_hour_stat["requests"],
                            hit=_hour_stat["hit"], miss=_hour_stat["miss"],
                            day=_hour_stat["day"], night=_hour_stat["night"],
                            in_progress=True)]
    return dict(hours=rows)

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
    width = None
    if q.get("w"):
        try:
            width = float(q["w"])
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
        width=width,
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
         (r.find or "").lower(), bool(r.tle), r.night, r.width)
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


# --- animation ---------------------------------------------------------------
# Not cached, not bucketed like everything else -- each stream is generated
# live and holds a connection open for several seconds to under a minute,
# unlike every other request here which is instant. That's a real difference
# in shape, so it gets its own concurrency cap rather than reusing the
# per-request rate limiter, which only charges one token regardless of how
# long a request stays open.
ANIMATE_FRAME_DELAY = 0.15         # seconds per frame -- under local test now,
                                    # constant throughout, no slowdown anywhere
ANIMATE_STEP_MIN = 15              # simulated minutes per frame (4/hour)
ANIMATE_DUSK_LEAD_FRAMES = 5       # night sky starts showing this many frames
                                    # early at dusk -- good as-is, don't touch
ANIMATE_DAWN_LAG_FRAMES = 3        # stars last longer past dawn instead of
                                    # cutting off early -- the fade curve is
                                    # non-linear, so this is tuned by measured
                                    # effect (~4 frames later), not a literal
                                    # frame count; see compose_frame's
                                    # dawn_lag_minutes
ANIMATE_MAX_CONCURRENT = 8
_animate_active = 0
GIF_RENDER_WIDTH = api.DEFAULT_HORIZON_WIDTH   # same as the live default, so
                                    # the export stays this size regardless of
                                    # whatever ?w= the live terminal used --
                                    # height comes along for free, computed
                                    # the same way compose_frame always does

# Frozen per-run share links (see _animate's gif_id below): once a ?animate=
# stream finishes, its exact frames are rendered to a GIF and cached here
# under a short id, so "Share: <url>" at the end of a run is a permanent,
# pasteable link -- not a live/regenerating one. Plain files on local disk,
# swept for anything past GIF_TTL_DAYS whenever a new one is saved -- good
# enough at this volume, no separate cron/scheduler needed.
GIF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gif_cache")
GIF_TTL_DAYS = 7
os.makedirs(GIF_DIR, exist_ok=True)
_gif_bg_tasks = set()          # keeps background render tasks referenced so
                                # they aren't garbage-collected mid-render


def _sweep_gif_cache():
    cutoff = time.time() - GIF_TTL_DAYS * 86400
    for name in os.listdir(GIF_DIR):
        path = os.path.join(GIF_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _render_and_save_gif(gif_id, frames):
    _sweep_gif_cache()
    data = gif.frames_to_gif(frames, int(ANIMATE_FRAME_DELAY * 1000))
    with open(os.path.join(GIF_DIR, f"{gif_id}.gif"), "wb") as f:
        f.write(data)
    return data


async def _animate(base_r, hours, gif_id=None, base_url=None):
    global _animate_active
    steps = int(hours * 60 / ANIMATE_STEP_MIN)
    start = base_r.when_utc
    dusk_lead_minutes = ANIMATE_DUSK_LEAD_FRAMES * ANIMATE_STEP_MIN
    dawn_lag_minutes = ANIMATE_DAWN_LAG_FRAMES * ANIMATE_STEP_MIN
    gif_frames = []
    _animate_active += 1
    try:
        for i in range(steps):
            t = start + dt.timedelta(minutes=ANIMATE_STEP_MIN * i)
            frame_r = base_r.at(t)
            body, _sun_alt = api.compose_frame(frame_r,
                                               dusk_lead_minutes=dusk_lead_minutes,
                                               dawn_lag_minutes=dawn_lag_minutes)
            yield f"\033[2J\033[H{body}\n".encode()
            if gif_id:
                # Rendered separately, forced to GIF_RENDER_WIDTH regardless
                # of whatever ?w= the live terminal above is using -- same
                # place/time/frames either way, just a guaranteed consistent
                # export size for social sharing.
                gif_r = base_r.at(t)
                gif_r.width = GIF_RENDER_WIDTH
                gif_body, _ = api.compose_frame(gif_r,
                                                dusk_lead_minutes=dusk_lead_minutes,
                                                dawn_lag_minutes=dawn_lag_minutes)
                gif_frames.append(gif_body)
            await asyncio.sleep(ANIMATE_FRAME_DELAY)
        if gif_id and gif_frames:
            # Share link prints the instant the animation itself is done --
            # rendering the GIF (Pillow drawing every frame, then encoding)
            # takes real time, so it happens in a background thread after
            # the stream has already told you where to find it, instead of
            # making you sit through that render before seeing the URL.
            yield (f"\n{api.SUN_COL}Share as a GIF (link up for {GIF_TTL_DAYS} days): "
                  f"{base_url}/animate/{gif_id}.gif\033[0m\n").encode()
            task = asyncio.create_task(
                asyncio.to_thread(_render_and_save_gif, gif_id, gif_frames))
            _gif_bg_tasks.add(task)
            task.add_done_callback(_gif_bg_tasks.discard)
    finally:
        _animate_active -= 1


def _respond(request: Req, place: str | None):
    mode, colour = _wants(request)
    q = request.query_params
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
    if q.get("animate") is not None:
        if _animate_active >= ANIMATE_MAX_CONCURRENT:
            return PlainTextResponse(
                "Too many animations running right now -- try again shortly.\n",
                status_code=503, headers={"Cache-Control": "no-store"})
        try:
            hours = float(q.get("animate")) if q.get("animate") else 24.0
        except ValueError:
            hours = 24.0
        hours = max(1.0, min(24.0, hours))
        r = _build(request, place)
        # nogif=1: the "animate" button's live preview fetches this purely
        # to render frames client-side, and separately calls
        # /{place}/animate.gif for the actual shareable file -- rendering
        # and saving a second, unused GIF here would just be wasted work.
        if q.get("nogif"):
            gif_id = base_url = None
        else:
            gif_id = secrets.token_urlsafe(6)
            base_url = str(request.base_url).rstrip("/")
        return StreamingResponse(_animate(r, hours, gif_id=gif_id, base_url=base_url),
                                 media_type="text/plain",
                                 headers={"Cache-Control": "no-store"})
    r = _build(request, place)
    res, daytime, hit = _cached(r)
    _tally(r, daytime, hit, mode, res.status, res.data)
    edge = DAY_EDGE if daytime else NIGHT_EDGE
    headers = {"Cache-Control": f"public, max-age={edge // 4}, s-maxage={edge}, "
                                f"stale-while-revalidate=600",
               "X-Cache": "HIT" if hit else "MISS"}
    if mode == "json":
        return JSONResponse(res.data, status_code=res.status, headers=headers)
    # res.text may be a cached render from an earlier request -- {base_url}
    # is only ever a literal placeholder in it (see _compose_sky/_compose_day),
    # substituted with THIS request's own host every time, so a cached page
    # never leaks whatever host happened to generate it.
    base_url = str(request.base_url).rstrip("/")
    page_text = res.text.replace("{base_url}", base_url)
    if mode == "html":
        png_href = api._png_url(r).replace("{base_url}", "")  # relative is fine in a browser
        # r.place is always resolved by here (IP geolocation fills it in on
        # the bare root same as an explicit place does), so these depend on
        # r.place rather than the raw `place` URL segment, which is None on
        # the root even though there's a real location to animate/share.
        extra = f'<a href="{png_href}" target="_blank" rel="noopener">Share as a PNG</a>'
        animate_btn = (f'<button class="animate-btn" data-gif-url="{api._animate_gif_url(r)}" '
                      f'data-live-url="/{r.place.slug}?animate=24&amp;nogif=1" '
                      f'onclick="skymapAnimate(this)">▶ animate</button>')
        body = api.PAGE.format(title=f"skymap.sh — {r.place.name}",
                               path=f"/{r.place.slug}" if place else "",
                               explore=api.EXPLORE, animate_btn=animate_btn,
                               body=api.ansi_to_html(page_text), extra=extra)
        return HTMLResponse(body, status_code=res.status, headers=headers)
    text = page_text if colour else api.strip_ansi(page_text)
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
def help_(request: Req):
    mode, _colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh — usage", path="/help",
                               explore=api.EXPLORE, body=html.escape(api.HELP),
                               extra="", animate_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.HELP, headers=headers)


@app.get("/demo", response_class=HTMLResponse)
def demo():
    # Static, pre-rendered by build_sky_html.py -- already a complete page,
    # not run through api.PAGE, so just served as-is.
    with open(f"{api.sky.BASE}/sky_demo.html") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "public, max-age=3600"})


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


@app.get("/stats/hourly", response_class=PlainTextResponse)
def stats_hourly(request: Req):
    q = request.query_params
    try:
        days = max(1, min(HOURLY_MAX_QUERY_DAYS, int(q.get("days", 7))))
    except ValueError:
        days = 7
    if q.get("format") == "json":
        return JSONResponse(stats_hourly_json(days), headers={"Cache-Control": "no-store"})
    return PlainTextResponse(stats_hourly_text(days), headers={"Cache-Control": "no-store"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\n")


GIF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@app.get("/animate/{gif_id}.gif")
def animate_gif(gif_id: str):
    # Frozen per-run share link -- see _animate's gif_id. Filename comes
    # straight from the URL, so it's validated against the exact shape
    # secrets.token_urlsafe produces before touching the filesystem.
    if not GIF_ID_RE.match(gif_id):
        return PlainTextResponse("", status_code=404)
    path = os.path.join(GIF_DIR, f"{gif_id}.gif")
    if not os.path.isfile(path):
        return PlainTextResponse("Not found or expired.\n", status_code=404)
    return FileResponse(path, media_type="image/gif",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/{place}/horizon.png")
def horizon_png(request: Req, place: str):
    # Header + chart, no prose/footer/zenith inset, and no ?animate=
    # involved -- a single static image of whatever the regular page for
    # this place is showing right now (or at ?t=, if given).
    if api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    r = _build(request, place)
    art = api.compose_chart_only(r)
    data = gif.frame_to_png(art)
    edge = DAY_EDGE if not r.night and api.is_daytime(r) else NIGHT_EDGE
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": f"public, max-age={edge // 4}, s-maxage={edge}"})


@app.get("/{place}/animate.gif")
def animate_gif_inline(request: Req, place: str):
    # Synchronous (Starlette runs sync routes in a thread pool, so this
    # doesn't block the single worker's event loop) -- for the "animate"
    # button on the static page, which wants the finished GIF back in one
    # response rather than the CLI's live-streamed-then-rendered flow.
    # Still saved under a share id, same as the CLI path, so the page's JS
    # can point "Share as a GIF" at a permanent /animate/<id>.gif link.
    if api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    q = request.query_params
    # Same default as the CLI's bare ?animate= (24h) -- the GIF should
    # always match what was actually watched/requested, not quietly run a
    # shorter clip of its own. The button's live preview also runs 24h now,
    # and the ~6s render time comfortably finishes within that ~14.4s watch.
    try:
        hours = float(q.get("animate")) if q.get("animate") else 24.0
    except ValueError:
        hours = 24.0
    hours = max(1.0, min(24.0, hours))
    base_r = _build(request, place)
    steps = int(hours * 60 / ANIMATE_STEP_MIN)
    dusk_lead_minutes = ANIMATE_DUSK_LEAD_FRAMES * ANIMATE_STEP_MIN
    dawn_lag_minutes = ANIMATE_DAWN_LAG_FRAMES * ANIMATE_STEP_MIN
    frames = []
    for i in range(steps):
        t = base_r.when_utc + dt.timedelta(minutes=ANIMATE_STEP_MIN * i)
        gif_r = base_r.at(t)
        gif_r.width = GIF_RENDER_WIDTH
        body, _sun_alt = api.compose_frame(gif_r, dusk_lead_minutes=dusk_lead_minutes,
                                           dawn_lag_minutes=dawn_lag_minutes)
        frames.append(body)
    gif_id = secrets.token_urlsafe(6)
    data = _render_and_save_gif(gif_id, frames)
    return Response(data, media_type="image/gif",
                    headers={"Cache-Control": "no-store", "X-Gif-Id": gif_id,
                             "Access-Control-Expose-Headers": "X-Gif-Id"})


@app.get("/")
def root(request: Req):
    return _respond(request, None)


@app.get("/{place:path}")
def place(request: Req, place: str):
    if place.startswith(("favicon", ".well-known")):
        return PlainTextResponse("", status_code=404)
    return _respond(request, place)
