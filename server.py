#!/usr/bin/env python3
"""
skymap.sh — one URL, four consumers.

    curl skymap.sh/Zurich                    -> ANSI text
    curl -H 'Accept: text/plain' ...      -> text, no escape codes
    browser                               -> the same output in a page
    ?format=json                          -> the same facts, structured

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio, datetime as dt, html, json, os, re, secrets, threading, time
from collections import OrderedDict
from urllib.parse import quote
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

# --- persisting the live counters ----------------------------------------------
# _stat/_places/_finds are otherwise purely in-memory, so a restart (deploy,
# crash, systemd bounce) would silently zero them. Snapshotted to disk on
# every hour boundary (piggybacking _flush_hour's existing cadence, not a
# separate timer) and on a graceful shutdown, then restored once at startup
# -- STARTED comes back too, so "X requests over Y h" keeps counting from
# the real first-ever start rather than resetting every deploy.
STATS_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats_state.json")


def _save_stats_state():
    try:
        tmp = f"{STATS_STATE_FILE}.tmp"
        with open(tmp, "w") as f:
            json.dump(dict(started=STARTED, stat=dict(_stat),
                          places=dict(_places), finds=dict(_finds)), f)
        os.replace(tmp, STATS_STATE_FILE)   # atomic -- a crash mid-write
    except OSError:                          # can't leave a corrupt file
        pass


def _load_stats_state():
    global STARTED
    try:
        with open(STATS_STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return
    STARTED = data.get("started", STARTED)
    _stat.update(data.get("stat", {}))
    _places.update(data.get("places", {}))
    _finds.update(data.get("finds", {}))


# --- hourly history -----------------------------------------------------------
# A second, complementary view of the same underlying data: one line per
# COMPLETED hour, so /stats/hourly can chart a trend even though the live
# counters above are just a running total with no time axis of their own.
HOURLY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats_hourly.jsonl")
# Never trimmed -- one line per hour is tiny (a year is ~8,760 lines), so the
# file just keeps the whole history. This only caps how far back ?days= can
# ask the /stats/hourly view to look, not how much is actually kept on disk.
HOURLY_MAX_QUERY_DAYS = 3650
_hour_key = None
_hour_stat = Counter()

# bsky_bot.py runs as its own process (a systemd unit, not a uvicorn worker),
# so it can't share _stat directly -- it persists its own tallies to this file
# on every poll, and /stats just reads it. Missing/malformed is normal (the
# bot may not be deployed, or hasn't written yet) and shows nothing, not an
# error.
BSKY_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bsky_bot_state.json")


def _read_bsky_stats():
    try:
        with open(BSKY_STATE_FILE) as f:
            return json.load(f).get("stats") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _flush_hour(hour_key, hstat):
    # Cumulative snapshot goes out regardless of whether this particular
    # hour had any traffic -- the totals it's saving span the process's
    # whole history, not just the hour that just ended.
    _save_stats_state()
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


def _tally(r, daytime, hit, mode, status, data, colour=True):
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
    # Every remaining request-shaping parameter, so /stats reflects the full
    # surface rather than just the ones that happened to get counters as they
    # shipped -- dso/quadrant landed with none at all until this pass.
    if r.dso:
        _stat["param:dso"] += 1
    if r.quadrant_requested:
        _stat["param:quadrant"] += 1
    if r.night:
        _stat["param:night"] += 1
    if not r.lines:
        _stat["param:nolines"] += 1
    if r.width:
        _stat["param:w"] += 1
    if not colour:
        _stat["param:plain"] += 1
    _places[r.place.name] += 1
    if r.find:
        _finds[r.find.strip().title()[:40]] += 1
    if len(_places) > _TOP_KEEP:
        for k, _v in _places.most_common()[_TOP_KEEP:]:
            del _places[k]
    if len(_finds) > _TOP_KEEP:
        for k, _v in _finds.most_common()[_TOP_KEEP:]:
            del _finds[k]


def stats_text(n=50):
    up = time.time() - STARTED
    req = _stat["requests"] or 1
    L = [f"skymap.sh — {req:,} requests over {up/3600:.1f} h "
         f"({req/max(up,1)*60:.1f}/min)", ""]
    L.append(f"cache      {_stat['hit']:,} hit / {_stat['miss']:,} miss "
             f"({100*_stat['hit']/req:.1f}% hit)")
    L.append(f"sky        {_stat['night']:,} night / {_stat['day']:,} day")
    L.append("")
    if _stat["animate"] or _stat["gif"] or _stat["png"]:
        L.append("sharing")
        rej = f"  ({_stat['animate_rejected']:,} rejected)" if _stat["animate_rejected"] else ""
        L.append(f"  {'animate':12} {_stat['animate']:>8,}{rej}")
        rej = f"  ({_stat['gif_rejected']:,} rejected)" if _stat["gif_rejected"] else ""
        L.append(f"  {'gif':12} {_stat['gif']:>8,}{rej}")
        L.append(f"  {'png':12} {_stat['png']:>8,}")
        L.append("")
    L.append("views")
    for k in sorted(k for k in _stat if k.startswith("view:")):
        L.append(f"  {k[5:]:12} {_stat[k]:>8,}")
    if _stat["iss"]:
        L.append(f"  {'iss':12} {_stat['iss']:>8,}")
    L.append("")
    params = sorted(k for k in _stat if k.startswith("param:"))
    if params:
        L.append("parameters")
        for k in params:
            L.append(f"  {k[6:]:12} {_stat[k]:>8,}")
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
    bsky = _read_bsky_stats()
    if bsky:
        L.append("bluesky bot")
        L.append(f"  {'mentions':12} {bsky.get('mentions', 0):>8,}")
        L.append(f"  {'replies':12} {bsky.get('replies', 0):>8,}")
        if bsky.get("unknown_place"):
            L.append(f"  {'unknown':12} {bsky['unknown_place']:>8,}")
        if bsky.get("usage_hint"):
            L.append(f"  {'usage hint':12} {bsky['usage_hint']:>8,}")
        if bsky.get("errors"):
            L.append(f"  {'errors':12} {bsky['errors']:>8,}")
    # Unconditional -- was only appended inside `if bsky:` above, so the
    # blank line before "top places" silently vanished whenever there was
    # no bluesky data yet, unlike every other section here.
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
        animate=_stat["animate"], animate_rejected=_stat["animate_rejected"],
        gif=_stat["gif"], gif_rejected=_stat["gif_rejected"], png=_stat["png"],
        views={k[5:]: v for k, v in _stat.items() if k.startswith("view:")},
        modes={k[5:]: v for k, v in _stat.items() if k.startswith("mode:")},
        errors={k[7:]: v for k, v in _stat.items() if k.startswith("status:")},
        params={k[6:]: v for k, v in _stat.items() if k.startswith("param:")},
        places_distinct=len(_places), finds_distinct=len(_finds),
        top_places=dict(_places.most_common(n)),
        top_finds=dict(_finds.most_common(n)),
        bsky=_read_bsky_stats(),
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
    _load_stats_state()
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


@app.on_event("shutdown")
def _save_on_exit():
    # `systemctl restart` (a normal deploy) sends SIGTERM first, so this is
    # the common case that actually matters -- the hourly-boundary save
    # covers crashes/kills that skip shutdown handling entirely.
    _save_stats_state()


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
        dso=bool(q.get("dso")),
        # "quadrant" in q (not q.get(...) or None) so a bare ?quadrant with no
        # letter yet -- just asking to see the grid -- is still distinguished
        # from the param being absent entirely; api.Request uses that
        # difference to decide whether to switch dso on.
        quadrant=(q["quadrant"] if "quadrant" in q else None),
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
         (r.find or "").lower(), bool(r.tle), r.night, r.width, r.dso, r.quadrant)
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
ANIMATE_MAX_CONCURRENT = 250       # the text stream costs ~1.4ms of CPU and
                                    # no image buffers per frame (measured),
                                    # so this is cheap -- unlike the GIF
                                    # render below, which is the actual
                                    # expensive path and gets its own,
                                    # much tighter cap
_animate_active = 0
GIF_RENDER_MAX_CONCURRENT = 7       # each render now peaks ~118MB (measured,
                                    # down from ~180MB after gif.py's
                                    # glyph-cache and streaming-encode fixes)
                                    # -- 7 * 118 + ~110 baseline is ~936MB,
                                    # against sky.service's MemoryMax=1024M.
                                    # 8 would be ~1054MB, over the ceiling --
                                    # not a number to raise without also
                                    # raising MemoryMax
_gif_render_active = 0
_gif_render_lock = threading.Lock()    # animate_gif_inline runs in
                                        # Starlette's threadpool, not the
                                        # asyncio event loop -- a plain int
                                        # counter isn't safe against real
                                        # concurrent threads without this
GIF_RENDER_WIDTH = api.DEFAULT_HORIZON_WIDTH   # same as the live default, so
                                    # the export stays this size regardless of
                                    # whatever ?w= the live terminal used --
                                    # height comes along for free, computed
                                    # the same way compose_frame always does

# Frozen share links: whoever actually renders a GIF (see animate_gif_inline)
# gets a permanent, pasteable /animate/<id>.gif URL, not a live/regenerating
# one. Plain files on local disk, swept for anything past GIF_TTL_DAYS
# whenever a new one is saved -- good enough at this volume, no separate
# cron/scheduler needed.
GIF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gif_cache")
GIF_TTL_DAYS = 7
os.makedirs(GIF_DIR, exist_ok=True)


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


async def _animate(base_r, hours, base_url, is_ui=False):
    """Live text preview only -- never renders a GIF. Every ?animate view
    used to also silently render and save a GIF in the background, which
    meant the expensive Pillow work happened on every view whether or not
    anyone wanted to share it. Now it only happens for whoever actually
    asks, via /{place}/animate.gif -- see animate_gif_inline.

    is_ui=True means this is the page's own JS fetch (marked with ?ui=1),
    not a real terminal -- it already has a "Share as a GIF" button, so it
    skips the trailing curl-command hint meant for actual curl/CLI users."""
    global _animate_active
    steps = int(hours * 60 / ANIMATE_STEP_MIN)
    start = base_r.when_utc
    dusk_lead_minutes = ANIMATE_DUSK_LEAD_FRAMES * ANIMATE_STEP_MIN
    dawn_lag_minutes = ANIMATE_DAWN_LAG_FRAMES * ANIMATE_STEP_MIN
    _animate_active += 1
    try:
        for i in range(steps):
            t = start + dt.timedelta(minutes=ANIMATE_STEP_MIN * i)
            frame_r = base_r.at(t)
            body, _sun_alt = api.compose_frame(frame_r,
                                               dusk_lead_minutes=dusk_lead_minutes,
                                               dawn_lag_minutes=dawn_lag_minutes)
            yield f"\033[2J\033[H{body}\n".encode()
            await asyncio.sleep(ANIMATE_FRAME_DELAY)
        if not is_ui:
            # Same t= carry-over as the web button's data-live-url -- without
            # it, copy-pasting this exact command renders from the real
            # current moment instead of whatever the preview just played
            # from, silently (no error, just the wrong GIF).
            # Quoted: zsh (the default shell on macOS) treats a bare ? as a
            # glob character and errors with "no matches found" on an
            # unquoted URL like this one.
            live_t = base_r.when_local.strftime("%Y-%m-%dT%H:%M")
            yield (f"\n{api.SUN_COL}Want a shareable GIF of this? Run:\n"
                  f"  curl '{base_url}/{base_r.place.slug}/animate.gif?t={live_t}'"
                  f"\033[0m\n").encode()
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
    if q.get("animate") is not None and mode != "html":
        # A browser tab, on the other hand, falls through to the normal page
        # render below -- ?animate= there is handled by the "autoplay" bit
        # in the animate_btn markup, which starts the same live-preview JS
        # fetch the button itself uses. Serving this raw text/plain ANSI
        # stream straight into a browser used to print literal escape codes
        # onto the page instead of an animation.
        if _animate_active >= ANIMATE_MAX_CONCURRENT:
            _stat["animate_rejected"] += 1
            return PlainTextResponse(
                "Too many animations running right now -- try again shortly.\n",
                status_code=503, headers={"Cache-Control": "no-store"})
        try:
            hours = float(q.get("animate")) if q.get("animate") else 24.0
        except ValueError:
            hours = 24.0
        hours = max(1.0, min(24.0, hours))
        r = _build(request, place)
        base_url = str(request.base_url).rstrip("/")
        _stat["animate"] += 1
        return StreamingResponse(_animate(r, hours, base_url, is_ui=bool(q.get("ui"))),
                                 media_type="text/plain",
                                 headers={"Cache-Control": "no-store"})
    r = _build(request, place)
    res, daytime, hit = _cached(r)
    _tally(r, daytime, hit, mode, res.status, res.data, colour)
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
        # Share as a GIF (hidden until animate starts, see skymapAnimate) +
        # Share as a PNG (always there), right-aligned in the toolbar above
        # the chart, not down beside it -- gif-btn/gif-status are found by
        # id from the JS now rather than by parentElement.querySelector, so
        # they can live in a different part of the page than animate-btn.
        # gif-status sits in its own column under the button (.gif-group),
        # so the "View GIF" link that appears there once rendering finishes
        # reads as belonging to that button, not floating next to Share as a PNG.
        extra = ('<div class="gif-group">'
                f'<button id="gif-btn" class="animate-btn gif-btn" '
                f'data-gif-url="{api._animate_gif_url(r)}" '
                'onclick="skymapRenderGif(this)" hidden>Share as a GIF</button>'
                '<span id="gif-status" class="gif-status"></span>'
                '</div>'
                f'<a class="animate-btn" href="{png_href}" target="_blank" '
                'rel="noopener">Share as a PNG</a>')
        # Carries the exact moment on screen (r.when_local, whether that
        # came from ?t= or just defaulted to now) into the live-preview
        # fetch -- otherwise the animation would start from real "now"
        # while the static frame above it shows whatever time was asked
        # for, which is confusing on any ?t= link and outright broken on a
        # future one.
        live_t = r.when_local.strftime("%Y-%m-%dT%H:%M")
        # ui=1 marks this as the page's own JS fetch, not a real curl/terminal
        # session -- fetch() doesn't send Accept: text/html by default, so
        # _wants() can't tell the two apart on headers alone, and the
        # browser already has a real "Share as a GIF" button, so it doesn't
        # need the curl-command hint _animate() appends for actual terminals.
        animate_btn = (
            '<div class="animate-controls">'
            f'<button id="animate-btn" class="animate-btn" '
            f'data-live-url="/{r.place.slug}?animate=24&t={live_t}&ui=1" '
            'onclick="skymapAnimate(this)">▶ animate</button>'
            '</div>')
        if q.get("animate") is not None:
            # A shared .../?t=...&animate=24 link opened as a page (rather
            # than fetched by the button's own JS) lands here -- start the
            # same live preview automatically instead of leaving the user
            # looking at a static frame with an unclicked button.
            animate_btn += (
                '<script>document.addEventListener("DOMContentLoaded",'
                'function(){var b=document.getElementById("animate-btn");'
                'if(b)skymapAnimate(b);});</script>')
        # Quadrants only affect the night chart (_compose_sky) -- during the
        # Sun's-arc day view there's no facing/span window to crop, so the
        # button would do nothing. Same day/night gate _compose_sky itself
        # uses, not just `daytime` alone, since --night/?night=1 overrides it.
        if not r.night and daytime:
            quadrant_btn = ('<button class="animate-btn" disabled '
                            'title="Only available on the night chart">⊞ show quadrants</button>')
        else:
            label = "hide quadrants" if r.quadrant_requested else "show quadrants"
            quadrant_btn = (f'<a class="animate-btn" href="{api._quadrant_toggle_url(r)}">'
                           f'⊞ {label}</a>')
        # Pre-filled with the place actually being viewed -- otherwise
        # picking a date/time without retyping the city loses it: the JS
        # reads an empty #place and falls back to the home/IP-located page.
        explore = api.EXPLORE.format(place=html.escape(r.place.name))
        body = api.PAGE.format(title=f"skymap.sh — {r.place.name}",
                               path=f"/{r.place.slug}" if place else "",
                               explore=explore, animate_btn=animate_btn,
                               quadrant_btn=quadrant_btn,
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
                               explore=api.EXPLORE.format(place=""), body=html.escape(api.HELP),
                               extra="", animate_btn="", quadrant_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.HELP, headers=headers)


@app.get("/favicon.ico")
def favicon_ico():
    path = f"{api.sky.BASE}/favicon.ico"
    if not os.path.isfile(path):
        return PlainTextResponse("", status_code=404)
    return FileResponse(path, media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    path = f"{api.sky.BASE}/apple-touch-icon.png"
    if not os.path.isfile(path):
        return PlainTextResponse("", status_code=404)
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/demo", response_class=HTMLResponse)
def demo():
    # Static, pre-rendered by build_sky_html.py -- already a complete page,
    # not run through api.PAGE, so just served as-is.
    with open(f"{api.sky.BASE}/sky_demo.html") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "public, max-age=3600"})


@app.get("/demo_animate.gif")
def demo_animate_gif():
    # /demo has no trailing slash, so the demo page's own <img src="demo_
    # animate.gif"> (a relative path) resolves against the browser's URL bar
    # to /demo_animate.gif, not /demo/demo_animate.gif -- this is that route.
    # Same static, pre-rendered file build_sky_html.py already produced.
    path = f"{api.sky.BASE}/demo_animate.gif"
    if not os.path.isfile(path):
        return PlainTextResponse("", status_code=404)
    return FileResponse(path, media_type="image/gif",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/gif-capacity")
def gif_capacity():
    # Polled by the "Share as a GIF" button so it can grey itself out before
    # a click would just 503 -- a stale read here is harmless (the render
    # endpoint still enforces the real cap itself), this is a UX hint, not
    # the source of truth.
    return JSONResponse(
        {"available": _gif_render_active < GIF_RENDER_MAX_CONCURRENT},
        headers={"Cache-Control": "no-store"})


@app.get("/legend", response_class=PlainTextResponse)
def legend(request: Req):
    mode, colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh — legend", path="/legend",
                               explore=api.EXPLORE.format(place=""),
                               body=api.ansi_to_html(api.legend_text(True)),
                               extra="", animate_btn="", quadrant_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.legend_text(colour), headers=headers)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    p = app.state.tle
    total = _hits + _misses
    return PlainTextResponse(
        f"ok stars={len(sky._load('stars.json'))} "
        f"asterisms={len(sky._load('asterisms.json'))} "
        f"deepsky={len(sky._load('deepsky.json'))} "
        f"tle={'%.1fh' % (tle.age(p)/3600) if p else 'none'} "
        f"cache={len(_cache)}/{CACHE_MAX} "
        f"hitrate={100*_hits/total:.1f}% ({_hits}/{total}) "
        f"nv={api.nv_stats()}\n" if total else
        f"ok cache empty\n")


@app.get("/stats", response_class=PlainTextResponse)
def stats(request: Req):
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_json(), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh — stats", path="/stats",
                               explore=api.EXPLORE, body=html.escape(stats_text()),
                               extra="", animate_btn="", quadrant_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_text(), headers=headers)


@app.get("/stats/hourly", response_class=PlainTextResponse)
def stats_hourly(request: Req):
    q = request.query_params
    try:
        days = max(1, min(HOURLY_MAX_QUERY_DAYS, int(q.get("days", 7))))
    except ValueError:
        days = 7
    if q.get("format") == "json":
        return JSONResponse(stats_hourly_json(days), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh — stats", path="/stats/hourly",
                               explore=api.EXPLORE, body=html.escape(stats_hourly_text(days)),
                               extra="", animate_btn="", quadrant_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_hourly_text(days), headers=headers)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    # /animate and /stats aren't content -- each is either a one-shot,
    # ID-scoped render or a live counter, so indexing them just burns crawl
    # budget a search engine would rather spend on real pages.
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /animate/\n"
        "Disallow: /stats\n"
        "Sitemap: https://skymap.sh/sitemap.xml\n"
    )


# A handful of stable pages plus the same example cities already linked from
# the home page's own "Examples:" row (api.EXPLORE) -- not the 40,803-city
# catalogue, which would be noise no crawler should spend budget on and
# would go stale immediately anyway (every page is a live render).
SITEMAP_PLACES = ("Nairobi", "Tokyo", "London", "New York", "Buenos Aires", "Sydney")
SITEMAP_STATIC = ("/", "/demo", "/help", "/legend")


@app.get("/sitemap.xml", response_class=Response)
def sitemap():
    urls = [f"https://skymap.sh{p}" for p in SITEMAP_STATIC]
    urls += [f"https://skymap.sh/{quote(p)}" for p in SITEMAP_PLACES]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
            "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) +
            "</urlset>\n")
    return Response(body, media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    return PlainTextResponse(
        "# skymap.sh\n\n"
        "> The night sky above any place on Earth, as plain text. No signup, "
        "no API key, no JavaScript required to read it.\n\n"
        "## Usage\n\n"
        "- `curl skymap.sh` -- the visitor's own sky, located by IP\n"
        "- `curl skymap.sh/Zurich` -- any of 40,803 cities, or `lat,lon` coordinates\n"
        "- `curl 'skymap.sh/Zurich?find=Venus'` -- locate one object, direction "
        "and altitude given in fists held at arm's length\n"
        "- `curl 'skymap.sh/Zurich?format=json'` -- the same facts as structured data\n"
        "- `curl 'skymap.sh/Zurich?animate'` -- the next 24h streamed live, one "
        "frame every 15 simulated minutes\n\n"
        "## Reference\n\n"
        "- /help -- every parameter, with real sample output\n"
        "- /legend -- every character and colour used on the chart\n"
        "- /demo -- a worked example with commentary\n\n"
        "## Data\n\n"
        "Stars to magnitude 4-5 (Yale Bright Star Catalogue), 28 hand-authored "
        "asterisms, the 7 planets, Sun and Moon with phase, the next visible ISS "
        "pass, and (behind ?dso=1) 739 galaxies, nebulae and clusters from the "
        "Revised NGC. Everything shipped is public domain.\n"
    )


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
    _stat["png"] += 1
    edge = DAY_EDGE if not r.night and api.is_daytime(r) else NIGHT_EDGE
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": f"public, max-age={edge // 4}, s-maxage={edge}"})


@app.get("/{place}/animate.gif")
def animate_gif_inline(request: Req, place: str):
    # Synchronous (Starlette runs sync routes in a thread pool, so this
    # doesn't block the single worker's event loop). The only place a GIF
    # actually gets rendered -- neither the CLI's ?animate stream nor the
    # web button's live preview does this automatically any more, only on
    # request, since it's real Pillow work (draw + quantise + encode 96
    # frames, ~180MB peak, ~6s) rather than the cheap text stream.
    global _gif_render_active
    if api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    ua = (request.headers.get("user-agent") or "").lower()
    terminal = any(t in ua for t in TERMINALS)
    with _gif_render_lock:
        if _gif_render_active >= GIF_RENDER_MAX_CONCURRENT:
            _stat["gif_rejected"] += 1
            msg = "Too many GIFs rendering right now -- try again in a few seconds.\n"
            return PlainTextResponse(msg, status_code=503,
                                     headers={"Cache-Control": "no-store"})
        _gif_render_active += 1
    try:
        q = request.query_params
        # Same default as the CLI's bare ?animate= (24h) -- the GIF should
        # always match what was actually watched/requested, not quietly run
        # a shorter clip of its own.
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
        _stat["gif"] += 1
    finally:
        with _gif_render_lock:
            _gif_render_active -= 1
    if terminal:
        base_url = str(request.base_url).rstrip("/")
        return PlainTextResponse(
            f"Share as a GIF (link up for {GIF_TTL_DAYS} days): "
            f"{base_url}/animate/{gif_id}.gif\n",
            headers={"Cache-Control": "no-store"})
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
