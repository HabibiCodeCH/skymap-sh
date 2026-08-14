#!/usr/bin/env python3
"""
skymap.sh: one URL, four consumers.

    curl skymap.sh/Zurich                    -> ANSI text
    curl -H 'Accept: text/plain' ...      -> text, no escape codes
    browser                               -> the same output in a page
    ?format=json                          -> the same facts, structured

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio, datetime as dt, html, json, math, os, re, secrets, threading, time
from collections import OrderedDict, deque
from urllib.parse import quote, urlparse
from fastapi import FastAPI, Request as Req
from fastapi.responses import (PlainTextResponse, HTMLResponse, JSONResponse,
                               StreamingResponse, FileResponse, Response,
                               RedirectResponse)

import api, art, besselian, card, gif, lunar, objects, planes, sky, tle

app = FastAPI(title="skymap.sh", docs_url=None, redoc_url=None)

# Clients that want the terminal rendering even though they send Accept: */*
TERMINALS = ("curl", "wget", "httpie", "http/", "powershell", "libcurl", "lwp",
             "python-requests", "fetch")

# Link unfurlers and search crawlers.
#
# These ask for */* rather than text/html, and _wants() only reached its HTML
# branch when text/html was in the Accept header -- so every one of them fell
# through to the plain-text page, which has no <head> and therefore no card
# tags at all. Every social card on the site looked broken from the outside
# while being perfectly correct in a browser, which is why a card debugger
# reported them missing rather than wrong.
#
# Matched ahead of TERMINALS, not after: a crawler is definitively not a
# terminal, and that list contains "fetch" and "http/", which are exactly the
# kind of fragments a bot's UA string can carry by accident.
CRAWLERS = ("facebookexternalhit", "facebookcatalog", "twitterbot",
            "linkedinbot", "slackbot", "discordbot", "whatsapp",
            "telegrambot", "cardyb", "mastodon", "pinterest", "redditbot",
            "embedly", "iframely", "quora link preview", "skypeuripreview",
            "vkshare", "tumblr", "flipboard", "opengraph", "snapchat",
            "googlebot", "bingbot", "applebot", "duckduckbot", "yandexbot",
            "baiduspider", "petalbot", "ia_archiver")


def _is_crawler(ua):
    return any(b in ua for b in CRAWLERS)


def _crawler_req(request):
    return _is_crawler((request.headers.get("user-agent") or "").lower())

# Phone browsers only -- iPadOS Safari's UA is indistinguishable from desktop
# Safari by design, so it isn't and can't be matched here; it lands on the
# text page like a laptop would. The plain-text/ASCII view has no real value
# on a phone screen the way the 3D sphere does, so a real phone gets sent
# straight there instead of the text page it can't do much with.
MOBILE_UA = ("iphone", "ipod", "android", "windows phone", "blackberry")

# Crawlers self-identify in their UA (a matter of etiquette, not enforcement),
# and Googlebot's and Bingbot's mobile crawlers both send an Android/iPhone-
# looking UA -- without this, they'd get redirected to the sphere page same
# as a real phone, meaning Google's mobile index (the primary one today)
# would see a thin, JS-only page instead of the real text content this site
# is actually about.
CRAWLER_UA = ("bot", "spider", "crawler", "slurp", "facebookexternalhit")

def _is_mobile(request):
    ua = (request.headers.get("user-agent") or "").lower()
    if any(t in ua for t in TERMINALS) or any(t in ua for t in CRAWLER_UA):
        return False
    return any(t in ua for t in MOBILE_UA)

def _sphere_os(request):
    """Coarse OS bucket for the sphere-views-by-OS stats block. "ipad" is
    checked even though iPadOS Safari's real UA doesn't contain it (spoofed
    as desktop Safari by design, same limitation as _is_mobile) -- harmless
    to check, and catches the rare browser/webview that does send it."""
    ua = (request.headers.get("user-agent") or "").lower()
    if "iphone" in ua or "ipod" in ua or "ipad" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    return "other"
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
# A chart with aircraft on it cannot outlive the aircraft. The rest of this
# page is a prediction and holds for twenty minutes quite happily -- the Sun
# does nothing surprising in that time -- but a plane at 900 km/h crosses
# four degrees of sky in fifteen seconds, and a cached chart served nineteen
# minutes later shows it somewhere it has long since left.
#
# Matched to planes.POS_TTL, so the page and the position behind it go stale
# together. The upstream cost does not move: planes.py caches by tile, so a
# hundred readers in one city still make one call every fifteen seconds
# however often their pages re-render.
PLANES_BUCKET = 15
PLANES_TTL = 20
NIGHT_EDGE, DAY_EDGE = 300, 900
CACHE_MAX = 3000
# The social card is a 1200x630 raster, not a terminal view, so it gets its
# own width rather than the chart default.
OG_WIDTH = 140
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
# Views that existed once and no longer do. Their totals stay in _stat and on
# disk -- deleting them would quietly rewrite the record of what the site used
# to be -- but they are left out of everything that reads like a live counter.
# view:disc was the whole sky drawn as a circle; two people ever opened it.
RETIRED_VIEWS = ("view:find", "view:disc")
_stat = Counter()
_places = Counter()
# Frozen. This was the "which object" leaderboard back when finding one meant
# a crosshair on your own chart; objects have their own pages now and _objects
# below counts them. Nothing increments this any more, but it is still loaded
# and saved so the historical numbers stay on disk instead of being wiped by
# the first save after the change. Not shown anywhere.
_finds = Counter()
# Which objects get looked up, same shape as _places.
_objects = Counter()
# Separate from _places -- that one only counts the text/ASCII route (via
# _tally(), which sphere_page() never calls), so which cities people want
# to actually look around in would otherwise be invisible.
_sphere_places = Counter()
# Same reasoning as _sphere_places: /events and its two feeds never go through
# _tally(), so which cities people actually subscribe to would be invisible
# without their own tally. A subscription is a much stronger signal than a
# page view -- someone put it in their calendar.
_events_places = Counter()
# Which eclipses people look at. Keyed by date rather than name, because
# "Total solar eclipse" happens twenty-odd times in the table and the
# interesting question is which one they came for.
_eclipse_keys = Counter()
# What the "Coming up" line actually promoted, and how often it was absent.
# Page views tell you people opened the list; this tells you whether the
# feature does anything on the pages nobody opened it from -- which is most
# of them, since the teaser is meant to be missing on a quiet night.
_events_teased = Counter()
_referrers = Counter()
# Where requests come from, binned to whole degrees, for the dotted world map
# on /stats. Keyed on coordinates rather than place name because plenty of
# requests are raw lat/lon rather than a city -- those have no name to key on,
# and a name would need resolving back to a position anyway. Whole degrees is
# already finer than the map can draw.
_geo_hits = Counter()
# The last few hundred requests with a timestamp, for the live map. _geo_hits
# is a running total with no time axis, so nothing in it can say which
# requests are new -- the same gap the counters had before the charts landed.
# Deliberately not persisted: "what arrived in the last few seconds" means
# nothing after a restart.
_geo_recent = deque(maxlen=400)
_TOP_KEEP = 2000            # trim the long tail so the tables cannot grow forever
_GEO_KEEP = 5000            # same idea for the map: distinct 1-degree cells

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
                          places=dict(_places), finds=dict(_finds),
                          objects=dict(_objects),
                          sphere_places=dict(_sphere_places),
                          events_places=dict(_events_places),
                          events_teased=dict(_events_teased),
                          eclipse_keys=dict(_eclipse_keys),
                          referrers=dict(_referrers), geo=dict(_geo_hits)), f)
        os.replace(tmp, STATS_STATE_FILE)   # atomic -- a crash mid-write
    except OSError:                          # can't leave a corrupt file
        pass


def _load_stats_state():
    """Restore the counters from disk, replacing whatever is in memory.

    Replacing, not adding. Counter.update() adds, so loading twice doubled
    every number and then persisted the doubled value on the way out. In
    production there is one startup per process, so it never showed; under
    pytest two TestClient context managers are two startups, and the doubling
    compounded across runs until stats_state.json held 366-digit integers and
    /stats died with OverflowError trying to format them.

    "Restore from disk" replacing memory is also just the right meaning, and
    it makes the function safe to call more than once.
    """
    global STARTED
    try:
        with open(STATS_STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return
    STARTED = data.get("started", STARTED)
    for counter, key in ((_stat, "stat"), (_places, "places"),
                         (_finds, "finds"), (_objects, "objects"),
                         (_sphere_places, "sphere_places"),
                         (_events_places, "events_places"),
                         (_events_teased, "events_teased"),
                         (_eclipse_keys, "eclipse_keys"),
                         (_referrers, "referrers"), (_geo_hits, "geo")):
        counter.clear()
        counter.update(data.get(key, {}))


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
# Held only while the hour is being closed. See _roll_hour for why the
# unlocked version lost requests out of the charts but not out of the
# headline.
_hour_lock = threading.Lock()

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


HOURLY_TOP_REFERRERS = 5    # per-hour breakdown, not the all-time list -- kept
                            # small so a forever-growing log stays cheap to read


def _top_hour_referrers(hstat, n=HOURLY_TOP_REFERRERS):
    refs = {k[4:]: v for k, v in hstat.items() if k.startswith("ref:")}
    return dict(sorted(refs.items(), key=lambda kv: -kv[1])[:n])


def _flush_hour(hour_key, hstat):
    # Cumulative snapshot goes out regardless of whether this particular
    # hour had any traffic -- the totals it's saving span the process's
    # whole history, not just the hour that just ended.
    _save_stats_state()
    if not hstat:
        return
    row = dict(hour=hour_key, requests=hstat["requests"], hit=hstat["hit"],
              miss=hstat["miss"], day=hstat["day"], night=hstat["night"])
    # Only when there were any, the same way top_referrers is written. Most
    # hours have none, and a key repeated on every line of a file that is
    # never trimmed is a cost with no reader.
    if hstat["notfound"]:
        row["notfound"] = hstat["notfound"]
    # Same rule for the client mix and the object-lookup count: written only
    # when there is something to say, so a quiet hour stays one short line in
    # a file that is never trimmed.
    for k in CLIENTS + ("object",):
        if hstat[k]:
            row[k] = hstat[k]
    top_ref = _top_hour_referrers(hstat)
    if top_ref:
        row["top_referrers"] = top_ref
    try:
        with open(HOURLY_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _roll_hour():
    """Close the hour that just ended, if one did.

    Locked, and the counter is swapped *before* the flush rather than after.
    Route handlers run in a threadpool, so several requests can be inside
    this at once. Unlocked, and with _hour_key only updated after the write,
    a second thread arriving during the flush also saw a boundary, also
    flushed, and then rebound _hour_stat a second time -- throwing away
    everything the first thread's fresh Counter had collected in between.
    _stat is never rebound, so it kept those requests and the log did not:
    the headline on /stats and the bars underneath it drifted apart by
    roughly one request per hour boundary, and the same hour turned up in
    the log twice.

    The fast path stays lock-free. An hour is 3,600 seconds long and this
    runs on every request, so the overwhelmingly common answer is "no, the
    hour has not changed", and that answer needs no lock to be right."""
    global _hour_key, _hour_stat
    now_key = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:00")
    if now_key == _hour_key:
        return
    pending = None
    with _hour_lock:
        # Re-read under the lock. A thread that queued behind the one that
        # did the roll would otherwise close the same hour all over again.
        if _hour_key is None:
            _hour_key = now_key
        elif now_key != _hour_key:
            pending = (_hour_key, _hour_stat)
            # From here on requests land in the new hour's counter, and the
            # one handed to _flush_hour below is nobody's but ours.
            _hour_key, _hour_stat = now_key, Counter()
    # Outside the lock. The swap above is a pointer move; the flush is a
    # 26 KB JSON write and a file append, and no other request needs to wait
    # behind that to be counted correctly.
    if pending:
        _flush_hour(*pending)


def _read_hourly_history(days=7):
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    rows = []
    try:
        with open(HOURLY_LOG) as f:
            for line in f:
                try:
                    row = json.loads(line)
                    # Rows written before object pages replaced "find" carry
                    # the same quantity under the old name. Renamed here, on
                    # the way in, so nothing downstream has to know there
                    # were ever two names for it.
                    #
                    # It has to happen here and not at the chart: _ZERO_FILL
                    # stamps a 0 onto every row missing a key it knows
                    # about, so by the time the chart saw an old row it
                    # already had object=0 and any fallback to "find" was
                    # dead code. That silently flatlined the whole history.
                    if "object" not in row and "find" in row:
                        row["object"] = row["find"]
                    if dt.datetime.fromisoformat(row["hour"]) >= cutoff:
                        rows.append(row)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except OSError:
        pass
    return rows


def _hourly_rows(days):
    """Log rows for the window, plus the hour currently in progress -- that
    one is still only in memory, so reading the file alone always leaves the
    chart and the table an hour short of now."""
    _roll_hour()
    rows = _read_hourly_history(days=days)
    if _hour_stat:
        rows = rows + [dict(hour=_hour_key, requests=_hour_stat["requests"],
                            hit=_hour_stat["hit"], miss=_hour_stat["miss"],
                            day=_hour_stat["day"], night=_hour_stat["night"],
                            notfound=_hour_stat["notfound"],
                            object=_hour_stat["object"],
                            **{k: _hour_stat[k] for k in CLIENTS},
                            top_referrers=_top_hour_referrers(_hour_stat))]
    return rows


# --- plaintext charts ---------------------------------------------------------
# Eight rows of eighth-blocks give 64 steps of vertical resolution, which is
# enough to tell a busy hour from a quiet one without the chart eating half
# the page. 60 columns keeps the widest chart inside an 80-column terminal,
# which matters because `curl skymap.sh/stats` is a real way people read this.
CHART_ROWS = 12
SPARK_ROWS = 2              # two rows is 16 steps instead of 8, enough to see
                            # a hit rate move rather than guess at it
CHART_COLS = 60
CHART_HOURS = 48            # two full diurnal cycles, so the daily rhythm shows
CHART_DAYS = 30
CHART_PAD = 7               # width of the y-axis label gutter
FINDS_ROWS = 5              # the finds chart sits under two full-height ones
                            # already -- tall enough to read a shape, short
                            # enough not to push the map off the first screen
_BLOCKS = " ▁▂▃▄▅▆▇█"
_SPARK = "▁▂▃▄▅▆▇█"
# _wants' three modes as the names the page shows. text is curl and the CLI,
# html is a browser, json is a script -- and a phone is html, so it is split
# back out in _tally rather than being a mode of its own.
CLIENT_OF = {"text": "cli", "html": "web", "json": "json"}
# "bot" is its own client, not a flavour of web. An unfurler fetches a page
# once per share and never reads it, so counting it beside real visitors
# inflated exactly the numbers anyone would look at /stats to learn: how
# many people came, from where, and which objects they wanted.
CLIENTS = ("cli", "web", "mobile", "json", "bot")


def _client_of(mode, mobile, crawler):
    """Which of CLIENTS a request belongs to.

    Its own function because two paths have to agree on the answer: the
    normal one through _tally, and the unknown-place 404, which never
    reaches _tally but is still a request and still came from somebody. When
    the 404 was counted without a client the four buckets stopped adding up
    to the hour's requests, which is the one thing /stats promises about
    them in writing."""
    if crawler:
        return "bot"
    return "mobile" if mobile and mode == "html" else CLIENT_OF[mode]

# notfound rides alongside requests rather than inside it. A request for a
# place that doesn't exist isn't a cache hit or a miss and has no day or
# night, so folding it into `requests` would leave every ratio taken against
# it slightly wrong. Kept separate, the header's running total reconciles
# exactly: its request count is the log's requests plus its notfounds.
_ZERO_FILL = ("requests", "hit", "miss", "day", "night", "notfound",
              "cli", "web", "mobile", "json", "bot", "object")


def _merge_hour_rows(rows):
    """One entry per hour, summed, oldest first.

    The charts have always summed same-hour rows; the table underneath them
    listed the log line by line, which was fine while an hour could only
    produce one. Now that a restart flushes the hour it was in, a deploy
    leaves two lines for that hour -- the part before it and the part after
    -- and the table would show the hour twice, each time with a slice of
    its traffic and a hit% taken against that slice."""
    merged = {}
    for r in rows:
        m = merged.setdefault(r["hour"], dict(hour=r["hour"]))
        for k in _ZERO_FILL:
            m[k] = m.get(k, 0) + r.get(k, 0)
        refs = r.get("top_referrers")
        if refs:
            acc = m.setdefault("top_referrers", {})
            for dom, n in refs.items():
                acc[dom] = acc.get(dom, 0) + n
    out = []
    for key in sorted(merged):
        m = merged[key]
        if m.get("top_referrers"):
            # Two halves of an hour bring up to five domains each; the cap is
            # what the rest of the code expects a row to carry.
            m["top_referrers"] = dict(sorted(m["top_referrers"].items(),
                                             key=lambda kv: -kv[1])[:HOURLY_TOP_REFERRERS])
        out.append(m)
    return out


def _dense_hours(rows, hours, end=None):
    """One entry per hour in the window, oldest first, with hours the log
    never recorded filled in as zeros.

    _flush_hour returns early on an hour with no traffic, and _roll_hour only
    fires when a request arrives, so an idle stretch leaves no line at all.
    Charted straight off the log the x-axis would be "rows in the file"
    rather than time: two neighbouring columns could be a whole night apart
    with nothing on screen saying so. Zero-filling makes the axis mean
    elapsed time again, and a quiet hour reads as the blank column it is.
    """
    end = (end or dt.datetime.utcnow()).replace(minute=0, second=0, microsecond=0)
    # Summed, not last-one-wins. The log can hold more than one line for the
    # same hour: a restart flushes the partial hour it was in, and the next
    # process flushes the rest of that same hour when it rolls. Keying a
    # plain dict on the hour silently threw the first half away.
    by_hour = {}
    for r in rows:
        acc = by_hour.setdefault(r["hour"], Counter())
        for k in _ZERO_FILL:
            acc[k] += r.get(k, 0)
    out = []
    for i in range(hours - 1, -1, -1):
        key = (end - dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
        row = by_hour.get(key) or {}
        entry = dict(hour=key, recorded=key in by_hour)
        entry.update({k: row.get(k, 0) for k in _ZERO_FILL})
        out.append(entry)
    return out


def _dense_days(rows, days, end=None):
    """The same idea one level up: one entry per UTC calendar day, summed out
    of the hourly log.

    There is no daily log and there doesn't need to be -- the hourly file is
    never trimmed, so grouping it by date is the entire implementation, and
    the history reaches back as far as the server has ever run. A day with no
    traffic is zero-filled here for the same reason an hour is."""
    end = end or dt.datetime.utcnow().date()
    acc = {}
    for row in rows:
        day = acc.setdefault(row["hour"][:10], Counter())
        for k in _ZERO_FILL:
            day[k] += row.get(k, 0)
        day["hours"] += 1
    out = []
    for i in range(days - 1, -1, -1):
        key = (end - dt.timedelta(days=i)).isoformat()
        day = acc.get(key) or Counter()
        entry = dict(date=key, hours=day["hours"], recorded=key in acc)
        entry.update({k: day[k] for k in _ZERO_FILL})
        out.append(entry)
    return out


def _chunks(entries, max_cols=CHART_COLS):
    """Squeeze a long series into the chart width by grouping adjacent
    entries. Returns (list of groups, entries per group).

    Whatever is drawn from a group is summed, not averaged: the y-axis then
    reads as "requests per group", a real number you can check against the
    totals printed below the chart. An average over a group that is partly
    zero-filled reads as neither the busy hours nor the quiet ones."""
    n = len(entries)
    if not n:
        return [], 1
    per = max(1, -(-n // max_cols))
    return [entries[i:i + per] for i in range(0, n, per)], per


def _bar_chart(values, tick_label, rows=CHART_ROWS, width=1, tick=6,
               pad=CHART_PAD):
    """A column chart in text, drawn top row down.

    A zero is always blank, never a stub. An hour with no requests and an
    hour with one request must not look the same, which is exactly what a
    minimum-one-pixel bar would do to them.

    Always exactly `rows` rows plus an axis, even for a window with no
    traffic at all. An empty chart that collapsed to a one-line apology made
    the page jump by eight lines depending on the data, and put the two
    charts on /stats at different heights."""
    top = max(values) if values else 0
    L = []
    for i in range(rows):
        r = rows - i                       # 1 = bottom row
        line = ""
        for v in values:
            level = v / top * rows - (r - 1) if top else 0
            if v <= 0 or level <= 0:
                line += " " * width
            elif level >= 1:
                line += "█" * width
            else:
                line += _BLOCKS[max(1, round(level * 8))] * width
        # Roughly four numbers up the side however tall the chart is -- one
        # per row is noise, and the top and zero lines are the two that
        # actually get read.
        every = max(2, rows // 4)
        lab = f"{round(top * (rows - i) / rows):,}" if i % every == 0 else ""
        L.append(f"{lab:>{pad}} ┤{line}")
    axis = "".join(("┬" if i % tick == 0 else "─") + "─" * (width - 1)
                   for i in range(len(values)))
    L.append(f"{0:>{pad},} ┼{axis}")
    marks = " " * (pad + 2)
    for i in range(0, len(values), tick):
        marks += tick_label(i).ljust(tick * width)
    L.append(marks.rstrip())
    L.append("")
    return L


def _spark_rows(values, rows=SPARK_ROWS, width=1, full=100.0):
    """A percentage series as a short bar chart, `rows` tall, no axis.
    `width` matches the chart above so a sparkline column sits under the bar
    it belongs to.

    Scaled against `full`, not against the series' own min and max. These are
    percentages, so a bar's height should mean the value: 50%% is half-height
    every time, and the hit%% row can be compared against the night row
    directly. Self-scaling made a flat 88-91%% hit rate look like a mountain
    range, and made two rows at completely different levels look alike.

    None means "no ratio to take" -- an hour with no requests has no hit rate,
    which is not the same as a hit rate of zero. Those render blank, the same
    rule the charts use, while a real 0%% still gets the shortest visible bar
    on the bottom row.

    Always the full width, blanks included, so whatever is printed after it
    lands in the same column whether or not there is data."""
    out = []
    for i in range(rows):
        r = rows - i                       # 1 = bottom row
        line = ""
        for v in values:
            if v is None:
                line += " " * width
                continue
            level = v / full * rows - (r - 1)
            if level >= 1:
                line += "█" * width
            elif level > 0:
                line += _BLOCKS[max(1, round(level * 8))] * width
            elif r == 1:
                line += _BLOCKS[1] * width      # a real 0%, not a blank
            else:
                line += " " * width
        out.append(line)
    return out


def _spark_pair(label, values, value, width):
    """One labelled sparkline: `rows` lines, with the label and the current
    number on the bottom one so they sit level with the axis of the bars."""
    rows = _spark_rows(values, width=width)
    out = []
    for i, row in enumerate(rows):
        last = i == len(rows) - 1
        tail = ("  " + (f"{value:.0f}%" if value is not None else "-")
                if last else "")
        out.append(f"{label if last else '':>{CHART_PAD}} ┤{row}{tail}")
    return out


def _hour_tick(per):
    """Clock time while each column is one hour. Once a column is several
    hours wide the ticks land a day or more apart, and the clock time alone
    stops saying which day you're looking at -- so the label becomes a date."""
    if per > 1:
        return lambda e: e["hour"][5:10]
    return lambda e: e["hour"][11:16]


def _day_tick(_per):
    return lambda e: e["date"][5:]


def _hour_tick_every(per):
    """Space the hour ticks a whole number of days apart, so every label is
    the same time of day. At 6 columns minimum they also stay far enough
    apart not to collide."""
    return max(6, round(24 / per)) if per > 1 else 6


def _answered(e):
    """Requests that actually produced a chart, so the only ones a hit rate
    or a day/night split can be taken over.

    An unknown place is a request -- it is counted as one, and it draws a
    bar like any other -- but it is neither a cache hit nor a miss, and it
    happens neither by day nor by night, because there is no place to say
    when it is there. Left in the denominator it drags both ratios down by
    the share of traffic asking for somewhere that doesn't exist.

    .get because notfound is written to the log only in hours that had one
    (see _flush_hour), so a row read straight off disk may not carry the
    key at all. _dense_hours zero-fills it, but not every caller goes
    through there."""
    return e["requests"] - e.get("notfound", 0)


def _all_requests(e):
    return e["requests"]


def _ratio(groups, num, den=_answered):
    """Per-group percentage, or None where the group has no denominator --
    an hour with no requests has no hit rate, and that is not zero.

    `den` is a function of an entry rather than a field name because the
    right denominator is not always a field: the two ratio lines want the
    requests that could have had an answer, and the client mix wants every
    request, 404s included, or its four shares stop adding up to the whole."""
    out = []
    for g in groups:
        bottom = sum(den(e) for e in g)
        out.append(100 * sum(e[num] for e in g) / bottom if bottom else None)
    return out


def _chart_block(entries, tick_for, unit, span, width=1, tick_every=None,
                 cols=CHART_COLS, legend=True):
    """Title, chart, and the two ratio sparklines under it. Shared because
    /stats and the drill-down pages draw the same thing over different
    windows, just at different bucket sizes.

    `cols` is the data-column budget. The drill-down pages give a chart the
    full width; /stats sits two of them side by side and halves it. `legend`
    is off for those, since one line under the pair says it for both."""
    groups, per = _chunks(entries, cols // width)
    # Tick labels are 5-6 characters, so they need at least that many columns
    # between them or they run together.
    tick = tick_every(per) if tick_every else max(5, -(-6 // width))
    tick_of = tick_for(per)
    vals = [sum(e["requests"] for e in g) for g in groups]
    total = sum(vals)
    idle = sum(1 for e in entries if not e["requests"])
    bucket = f"{per} {unit}s" if per > 1 else unit
    # Title, then the numbers as a caption under the chart. All on one line
    # it ran past 80 columns on a long window with big counts, which wraps in
    # exactly the terminal the whole page is shaped for.
    # Every branch below appends unconditionally. The block is the same
    # number of lines whatever the data says, so the page doesn't jump by
    # eight lines when a window happens to be quiet, and the two charts on
    # /stats always sit at the same height as each other.
    L = [f"requests per {bucket} · last {span}".upper(), ""]
    L += _bar_chart(vals, lambda i: tick_of(groups[i][0]), width=width, tick=tick)
    gut = " " * (CHART_PAD + 2)
    if total:
        peak = max(entries, key=lambda e: e["requests"])
        when = (peak["hour"][5:13] if "hour" in peak else peak["date"][5:])
        L.append(f"{gut}{total:,} req · peak {peak['requests']:,} at {when}")
    else:
        L.append(f"{gut}no requests recorded in this window")
    L.append(f"{gut}{idle:,} idle {unit}(s), shown blank")
    hit = _ratio(groups, "hit")
    night = _ratio(groups, "night")
    now_hit = next((v for v in reversed(hit) if v is not None), None)
    # Over the same denominator as the bars above it, not over `total`.
    # `total` counts every request in the window including the ones for
    # places that don't exist, which have no sky and so belong to neither
    # half of the split.
    answered = sum(_answered(e) for e in entries)
    share = (100 * sum(e["night"] for e in entries) / answered
             if answered else None)
    # Same gutter as the chart rows above, so the series stack in one column
    # instead of each starting wherever its label ended.
    L += [""]
    L += _spark_pair("hit%", hit, now_hit, width)
    L += _spark_pair("night", night, share, width)
    L += [""]
    if legend:
        L.append(f"{gut}cache hit % (latest) and night share of the window")
    return L


def _client_mix_block(entries, cols=CHART_COLS, width=1, legend=True):
    """Who asked, as four sparklines that add up to the window.

    Percentages of the same bucket, so the four bars at any column stack to
    100% -- which is the point of splitting mobile back out of web rather
    than counting a phone as both. An hour with no requests has no mix and
    draws blank, the same rule the hit% line already follows.

    Fixed height whatever the data says, like _chart_block, so /stats'
    two columns stay level with each other."""
    groups, _per = _chunks(entries, cols // width)
    # Against what was actually recorded, not against every request in the
    # window. The four fields only started being logged when they shipped,
    # so an hour from before that has requests and a mix of nothing -- left
    # in the denominator it drags all four tails towards zero and they stop
    # adding up to the whole, which is the one thing this block promises.
    recorded = sum(e[c] for e in entries for c in CLIENTS)
    L = [""]
    for name in CLIENTS:
        share = 100 * sum(e[name] for e in entries) / recorded if recorded else None
        L += _spark_pair(name, _ratio(groups, name, den=_all_requests),
                         share, width)
    L += [""]
    if legend:
        L.append(f"{' ' * (CHART_PAD + 2)}share of requests by client")
    return L


def _finds_block(entries, unit, cols=CHART_COLS, width=1, tick_every=None,
                 tick_for=None, rows=FINDS_ROWS):
    """How many objects were looked up, over the window.

    Counts, not a percentage, so this is a small bar chart rather than a
    sparkline -- "six lookups this hour" is the number worth reading, and a
    share of requests would just track traffic. Short on purpose: it sits
    under two full-height charts already."""
    groups, per = _chunks(entries, cols // width)
    vals = [sum(e.get("object", 0) for e in g) for g in groups]
    total = sum(vals)
    bucket = f"{per} {unit}s" if per > 1 else unit
    tick = tick_every(per) if tick_every else max(5, -(-6 // width))
    tick_of = tick_for(per)
    L = [f"object lookups per {bucket}".upper(), ""]
    L += _bar_chart(vals, lambda i: tick_of(groups[i][0]), rows=rows,
                    width=width, tick=tick)
    gut = " " * (CHART_PAD + 2)
    L.append(f"{gut}{total:,} lookup(s) in this window" if total
             else f"{gut}no lookups in this window")
    return L


def _side_by_side(left, right, gap=3, left_width=None):
    """Two chart blocks rendered on the same lines, hours on the left and
    days on the right, sparklines included.

    _chart_block emits the same number of lines whatever the data says, so
    this is a straight zip -- it pads anyway rather than depend on that
    holding forever. The left column is padded to its own widest line, so
    the right chart starts at a fixed column and the two stay aligned
    however the numbers come out."""
    n = max(len(left), len(right))
    left = left + [""] * (n - len(left))
    right = right + [""] * (n - len(right))
    # left_width lets a page that stacks several of these pass one width for
    # all of them. Without it each block pads to its own widest line, so the
    # right-hand column starts a few characters further left under a short
    # block than under a tall one -- which reads as the charts being out of
    # alignment with each other, because they are.
    w = left_width if left_width is not None else max((len(l) for l in left),
                                                      default=0)
    return [f"{l:<{w}}{' ' * gap}{r}".rstrip() for l, r in zip(left, right)]


def _hourly_chart(hours=CHART_HOURS, cols=CHART_COLS, legend=True):
    # +1 day of slack: a 48 h window that starts mid-day still needs the
    # calendar day before the one _read_hourly_history's cutoff lands in.
    rows = _hourly_rows(days=max(2, -(-hours // 24) + 1))
    return _chart_block(_dense_hours(rows, hours), _hour_tick,
                        "hour", f"{hours} h", tick_every=_hour_tick_every,
                        cols=cols, legend=legend)


def _daily_chart(days=CHART_DAYS, cols=CHART_COLS, width=2, legend=True):
    rows = _hourly_rows(days=days + 1)
    # Two columns per day on its own page, where there is room to spare. One
    # column per day beside the hourly chart on /stats, where there isn't.
    return _chart_block(_dense_days(rows, days), _day_tick,
                        "day", f"{days} d", width=width, cols=cols,
                        legend=legend)


# --- dotted world map ---------------------------------------------------------
# Land mask precomputed by build_worldmap.py from real country polygons. See
# that file for why it isn't derived from cities.json.
WORLDMAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "worldmap.json")
# Grey for land nobody has asked from, warming through yellow and orange to
# red at the busiest cell. xterm-256, the same palette sky.py's renderer uses,
# so api.ansi_to_html() converts it for the browser with no extra work.
# The first step is grey rather than white because it is not really a step:
# it is ten thousand dots, the whole shape of the continents, and the six
# colours that mean something have to read against it. At white they didn't
# -- the map was a bright coastline with a few brighter specks on it. Dimmed,
# the land recedes to the background it always was and the traffic sits on
# top of it. The other six are untouched; only the floor moved.
MAP_RAMP = (248, 229, 227, 220, 214, 208, 196)
MAP_DOT = "·"
# Swapped in for the moment a dot flashes. A bullet is a bigger, rounder mark
# than a middle dot, which is the point -- at one character per cell a flash
# on a plain "·" is easy to miss. It only differs in the browser; the text
# map has no animation to swap anything for.
MAP_FLASH_DOT = "•"
# How big each ramp step's dot is drawn in the browser, as a multiplier on the
# glyph. Size says the same thing colour does, which is the point: on a map
# this dense, a warm dot two shades along is easy to lose against its
# neighbours, and a bigger one isn't. Level 0 is land nobody has asked from
# and stays at 1 -- that's nearly every dot on the map, and swelling those
# would drown out the handful that mean something.
# Browser only. A terminal can't scale a character, and the wider glyphs that
# could stand in for size (●, ◉) are double-width in enough terminals to
# break the map's alignment where it matters most.
MAP_SIZES = (1.0, 1.15, 1.35, 1.55, 1.75, 1.95, 2.2)
# The browser draws the map at its own size rather than the page's 11px, which
# is what pays for the finer grid: 340 columns at 7px is the same 1,426 pixels
# 216 columns at 11px was, and 100 rows at 1.05 is the same height 55 rows at
# 1.22 was. Same box on the page, nearly three times the columns in it.
# These two numbers and build_worldmap.py's FINE_WIDTH/FINE_HEIGHT are one
# decision in two places: change one and the map changes shape or starts
# pulling a scrollbar.
MAP_FONT_PX = 7
MAP_LINE_HEIGHT = 1.05
_worldmap = None


def _load_worldmap(fine=False):
    """(rows, width, height, lat_top, lat_bot), or None if the mask is
    missing. Missing is survivable -- the map is the one part of /stats that
    needs a generated file, and the page is more useful without it than
    500-ing over it.

    fine picks the browser's denser grid. A terminal is stuck with whatever
    font the shell is set to, so the coarse grid is as sharp as curl can get;
    the page can shrink its own text and take the finer one."""
    global _worldmap
    if _worldmap is None:
        try:
            with open(WORLDMAP_FILE) as f:
                d = json.load(f)
            coarse = (d["rows"], d["width"], d["height"],
                      d["lat_top"], d["lat_bot"])
            # A mask built before the fine grid existed still draws a map --
            # both readers just get the coarse one. Worth the two lines: the
            # JSON is generated, and a deploy that ships the code ahead of it
            # would otherwise lose the map entirely rather than sharpen it.
            _worldmap = {False: coarse, True: coarse}
            if "fine_rows" in d:
                _worldmap[True] = (d["fine_rows"], d["fine_width"],
                                   d["fine_height"], d["lat_top"], d["lat_bot"])
        except (OSError, json.JSONDecodeError, KeyError):
            _worldmap = ()
    return _worldmap[bool(fine)] if _worldmap else None


def _map_cell(lat, lon, w, h, lat_top, lat_bot):
    """Grid cell for a position, or None if it falls outside the clipped
    latitude band -- the mask stops at 83N/56S, and a request from further
    south than that has nowhere on the map to go."""
    if not lat_bot <= lat <= lat_top:
        return None
    r = int((lat_top - lat) / (lat_top - lat_bot) * h)
    c = int((lon + 180) / 360 * w)
    return (min(h - 1, max(0, r)), min(w - 1, max(0, c)))


def _map_heat(w, h, lat_top, lat_bot):
    """{cell: requests}, the 1-degree bins collapsed onto the map grid."""
    heat = Counter()
    for key, n in _geo_hits.items():
        try:
            lat, lon = (float(v) for v in key.split(","))
        except ValueError:
            continue
        cell = _map_cell(lat, lon, w, h, lat_top, lat_bot)
        if cell:
            heat[cell] += n
    return heat


def _world_map():
    """The land mask with request cells warmed up, as ANSI-coloured rows.

    Colour is on a log scale. Traffic is dominated by wherever the author
    lives, and on a linear scale that one cell is red and every other cell on
    Earth is white -- which is true but says nothing."""
    loaded = _load_worldmap()
    if not loaded:
        return []
    rows, w, h, lat_top, lat_bot = loaded
    shade, heat = _map_shader(w, h, lat_top, lat_bot)
    out = []
    for r, row in enumerate(rows):
        line, pen = [], None
        for c, ch in enumerate(row):
            if ch == " " and (r, c) not in heat:
                # Close the colour before a run of ocean so the escape codes
                # don't outnumber the dots.
                if pen is not None:
                    line.append("\033[0m")
                    pen = None
                line.append(" ")
                continue
            i = shade(r, c)
            if i != pen:
                line.append(f"\033[38;5;{MAP_RAMP[i]}m")
                pen = i
            line.append(MAP_DOT)
        if pen is not None:
            line.append("\033[0m")
        out.append("".join(line).rstrip())
    return out


_heat_cache = {}            # (width, height) -> (at, heat, busiest)
HEAT_TTL = 2.0              # seconds


def _cached_heat(w, h, lat_top, lat_bot):
    """_map_heat walks every 1-degree bin and parses its key, which is a few
    milliseconds once _geo_hits is large. /stats/live is polled every few
    seconds per open tab, so without this every tab pays that separately.
    A couple of seconds stale is invisible on a map of running totals.

    Keyed by grid size, because there are two: the same request lands in a
    different cell on the terminal's map than on the browser's, and one
    shared entry would hand whichever asked second the other's coordinates."""
    at, heat, top = _heat_cache.get((w, h), (0.0, None, None))
    now = time.time()
    if heat is None or now - at > HEAT_TTL:
        heat = _map_heat(w, h, lat_top, lat_bot)
        top = max(heat.values()) if heat else 0
        _heat_cache[(w, h)] = (now, heat, top)
    return heat, top


def _map_shader(w, h, lat_top, lat_bot):
    """((row, col) -> index into MAP_RAMP, the heat itself). Shared so the
    text map and the browser's map cannot drift apart on what colour a cell
    should be.

    Colour goes by rank, not by value. A log scale still collapses when one
    cell dwarfs the rest: with a busiest of 300, a cell on 5 and a cell on 1
    both land on the palest step, and the map reads as one red dot in a sea
    of white. Ranking spreads whatever spread exists, so the ramp is always
    fully used and neighbouring cells stay distinguishable.

    The trade is that a colour no longer means an absolute number -- 5 and 6
    requests can be different colours on a quiet map. That is the right way
    round for a map whose job is "where is the traffic", and the actual
    counts are in the table below it. Equal counts always get equal colours,
    which is why the ranking runs over distinct values rather than cells."""
    heat, _top = _cached_heat(w, h, lat_top, lat_bot)
    counts = sorted({n for n in heat.values() if n})
    if not counts:
        rank = {}
    elif len(counts) == 1:
        # One busy cell and nothing else. It is the maximum, so it is red.
        rank = {counts[0]: len(MAP_RAMP) - 1}
    else:
        span = len(counts) - 1
        rank = {n: 1 + round(i / span * (len(MAP_RAMP) - 2))
                for i, n in enumerate(counts)}

    def shade(r, c):
        return rank.get(heat.get((r, c), 0), 0)
    return shade, heat


def _map_html():
    """The map with one addressable element per land dot, on the fine grid.

    The text version emits one escape code per run of same-coloured dots,
    which is the right trade there. The browser needs the opposite: a dot
    cannot be flashed on its own unless it is its own element.

    Which means the markup is ten thousand copies of the same tag, so what
    each copy costs is the whole budget. Colour and size ride on one class,
    defined once in stats_live_html() from the same MAP_RAMP -- and the class
    is left off entirely for the resting level, which is nearly every dot on
    the map. What is left is an id, because a dot has to be findable, and the
    tag itself, because a dot has to be an element. At that point the fine
    grid costs less markup than the coarse one did before the diet.

    The wrapper is what makes the fine grid fit: it carries the map's own
    font size and line height (see MAP_FONT_PX), so the 340 columns land in
    the same box the 216 did. inline-block rather than block -- the map sits
    inside a <pre>, and a block would turn the newlines on either side of it
    into an extra blank line each."""
    loaded = _load_worldmap(fine=True)
    if not loaded:
        return ""
    rows, w, h, lat_top, lat_bot = loaded
    shade, heat = _map_shader(w, h, lat_top, lat_bot)
    out = ['<span class=wmap>']
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == " " and (r, c) not in heat:
                out.append(" ")
                continue
            i = shade(r, c)
            cls = f'class=h{i} ' if i else ""
            out.append(f'<i {cls}id=d{r}_{c}>{MAP_DOT}</i>')
        out.append("\n")
    return "".join(out).rstrip("\n") + "</span>"


# Stands in for the map while stats_text() builds the page, so the HTML route
# can splice its own per-dot version in. A control character because it must
# never collide with real content, and curl never sees it -- the text path
# renders the real map straight in.
MAP_SLOT = "\x00worldmap\x00"
# The same trick for the two lines /stats/live can keep current: the top line
# and the tail of the map's legend. Unlike MAP_SLOT these go through
# ansi_to_html on the way -- a NUL survives escaping untouched -- and the
# route swaps in a span the poll can address afterwards.
HEAD_SLOT = "\x00headline\x00"
LEGEND_SLOT = "\x00maplegend\x00"


def _map_legend():
    """The tail of the map's legend line: how many distinct places have asked
    and which one asks most. Its own function because /stats/live sends the
    finished string rather than the numbers -- both move as requests land,
    and rebuilding the sentence in JS is a second copy of the wording to keep
    in sync for nothing."""
    busiest = ""
    if _places:
        name, c = _places.most_common(1)[0]
        busiest = f"   busiest: {name} ({c:,})"
    return f"{len(_geo_hits):,} distinct location(s){busiest}"


def _map_block(body=None, slots=False):
    """Title, map, and a legend naming the busiest place, or nothing at all
    when there is no map file and no traffic to draw on it."""
    if not _load_worldmap():
        return []
    body = _world_map() if body is None else body
    if not body:
        return []
    L = ["WHERE REQUESTS COME FROM", ""] + body + [""]
    ramp = "".join(f"\033[38;5;{n}m{MAP_DOT}\033[0m" for n in MAP_RAMP)
    tail = LEGEND_SLOT if slots else _map_legend()
    L.append(f"quiet {ramp} busy   {tail}")
    return L


def _referrer_domain(request: Req):
    """Bare domain from the Referer header, or None for direct/CLI traffic.
    Self-referrals (a link from skymap.sh back to skymap.sh) aren't an
    origin worth counting, so those are dropped too."""
    ref = request.headers.get("referer")
    if not ref:
        return None
    try:
        host = urlparse(ref).netloc.lower()
    except ValueError:
        return None
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host or host == (request.headers.get("host") or "").split(":")[0].lower():
        return None
    return host


def _tally(r, daytime, hit, mode, status, data, colour=True, referrer=None,
           mobile=False, obj=None, crawler=False):
    _roll_hour()
    _stat["requests"] += 1
    _stat["hit" if hit else "miss"] += 1
    _stat["day" if daytime else "night"] += 1
    _stat[f"mode:{mode}"] += 1
    _hour_stat["requests"] += 1
    _hour_stat["hit" if hit else "miss"] += 1
    _hour_stat["day" if daytime else "night"] += 1
    # Who asked, per hour, as four buckets that add up to the hour's requests.
    # mode is already a three-way split of every request (json/html/text);
    # mobile is not a fourth mode but a subset of html, so a phone has to be
    # taken *out* of web rather than counted twice. Recorded per hour rather
    # than only all-time so /stats can chart the mix over the window -- the
    # all-time mode: counters can't say whether the CLI share is growing.
    _hour_stat[_client_of(mode, mobile, crawler)] += 1
    if crawler:
        # Everything below this point answers a question about readers --
        # which places, which objects, where in the world, which referrer.
        # A crawler is none of those, and one share of a link produces a
        # fetch from every platform it lands on. Load is still counted
        # above; the leaderboards are not.
        _stat["ua:crawler"] += 1
        return
    if mobile:
        _stat["ua:mobile"] += 1
    # Object lookups per hour: the leaderboard says which object, never
    # whether anyone is still using it over time.
    #
    # Keyed on obj, not on r.find. Object pages set r.find to draw their
    # crosshair, so "has a find" stopped meaning "is a find" the moment
    # objects got pages of their own -- one lookup was landing in a find
    # counter, an object counter and two view counters at once.
    if obj:
        _hour_stat["object"] += 1
    if status != 200:
        _stat[f"status:{status}"] += 1
    _stat["view:object" if obj else
          f"view:{'facing' if r.facing else r.view}"] += 1
    # ISS is shown to everyone now, so this counts something more useful than
    # "asked for it": how often a visitor's chart actually included a real pass.
    if data.get("iss_pass"):
        _stat["iss"] += 1
    # Only charts carry coming_up at all, so this counts the pages the teaser
    # was actually eligible to appear on -- the denominator that makes the
    # "shown" number mean anything.
    if "coming_up" in data:
        if data["coming_up"]:
            _stat["teaser:shown"] += 1
            card = data.get("coming_up_card") or {}
            if card.get("headline"):
                _events_teased[card["headline"][:34]] += 1
        else:
            _stat["teaser:absent"] += 1
    # Every remaining request-shaping parameter, so /stats reflects the full
    # surface rather than just the ones that happened to get counters as they
    # shipped -- dso/quadrant landed with none at all until this pass.
    if r.dso:
        _stat["param:dso"] += 1
    if r.nodso:
        _stat["param:nodso"] += 1
    if r.quadrant_requested:
        _stat["param:quadrant"] += 1
    if r.night:
        _stat["param:night"] += 1
    # Golden hour is on by default, so counting the parameter would only ever
    # count people switching it off. Both halves are worth knowing: "shown"
    # is the denominator that says how often the layer was even eligible,
    # which is the only thing that makes the opt-out rate mean anything.
    if daytime:
        _stat["golden:off" if not r.golden else "golden:shown"] += 1
    if not r.lines:
        _stat["param:nolines"] += 1
    if r.width:
        _stat["param:w"] += 1
    if r.panel:
        _stat["param:panel"] += 1
    # One per paused animation frame whose labels were asked for as links,
    # which is also a count of how often anybody stops an animation to look
    # something up -- the reason the parameter exists.
    if r.links:
        _stat["param:links"] += 1
    if not colour:
        _stat["param:plain"] += 1
    _places[r.place.name] += 1
    # Straight off the resolved position, so a request for "47.37,8.55" lands
    # in the same bin as one for "Zurich". A string key because this is
    # persisted as JSON, and JSON object keys are strings.
    lat, lon = round(r.place.lat), round(r.place.lon)
    _geo_hits[f"{lat},{lon}"] += 1
    # Rounded the same way as the key above, not raw. A map column is about
    # two degrees wide, so 47.37 and 47 can land in different columns -- and
    # then a flashed dot settles to white because the cell the heat is
    # counted against isn't the cell that flashed.
    _geo_recent.append((time.time(), lat, lon))
    # _finds is no longer written to. It was the "which object" leaderboard
    # from when finding one meant a crosshair on your own chart; an object
    # is its own page now, _objects counts it, and every object page was
    # landing in both. The counter is still loaded and saved so the
    # historical numbers survive on disk rather than being erased by the
    # first save after this change.
    if referrer:
        _referrers[referrer] += 1
        _hour_stat[f"ref:{referrer}"] += 1
    if len(_places) > _TOP_KEEP:
        for k, _v in _places.most_common()[_TOP_KEEP:]:
            del _places[k]
    if len(_objects) > _TOP_KEEP:
        for k, _v in _objects.most_common()[_TOP_KEEP:]:
            del _objects[k]
    if len(_referrers) > _TOP_KEEP:
        for k, _v in _referrers.most_common()[_TOP_KEEP:]:
            del _referrers[k]
    if len(_geo_hits) > _GEO_KEEP:
        for k, _v in _geo_hits.most_common()[_GEO_KEEP:]:
            del _geo_hits[k]


def _headline():
    """The top line of /stats. Its own function for the same reason
    _map_legend is: /stats/live sends the whole line back on every poll. The
    count moves, and so do the two figures derived from it -- updating only
    the count in place would leave a page claiming 4,000 requests at a rate
    that was true a hundred requests ago."""
    up = time.time() - STARTED
    req = _stat["requests"] or 1
    return (f"skymap.sh: {req:,} requests over {up/3600:.1f} h "
            f"({req/max(up,1)*60:.1f}/min)")


def stats_text(n=50, map_slot=False):
    """map_slot leaves MAP_SLOT where the map goes instead of drawing it, so
    the HTML route can splice in its per-dot version -- and leaves HEAD_SLOT
    and LEGEND_SLOT for the two lines the browser keeps current. The text
    path never passes it and never sees the markers."""
    req = _stat["requests"] or 1
    L = [HEAD_SLOT if map_slot else _headline(), ""]
    # Charts first. The counters below are a running total with no time axis
    # of their own, so they can't answer "is it growing" -- which is usually
    # the first thing anyone opening this page wants to know.
    # Side by side, hours against days. One column is one hour on the left
    # and one day on the right -- no bucketing, so `cols` is just the window.
    gut = f"{'':{CHART_PAD + 2}}"
    # The same two windows the charts use, kept here rather than rebuilt per
    # block: the client mix and the finds chart below have to bucket
    # identically to the bars above them or the columns stop lining up.
    h_entries = _dense_hours(_hourly_rows(days=max(2, -(-CHART_HOURS // 24) + 1)),
                             CHART_HOURS)
    d_entries = _dense_days(_hourly_rows(days=CHART_DAYS + 1), CHART_DAYS)
    hourly = _chart_block(h_entries, _hour_tick, "hour", f"{CHART_HOURS} h",
                          tick_every=_hour_tick_every, cols=CHART_HOURS,
                          legend=False)
    hourly.append(f"{gut}(hour by hour: /stats/hourly)")
    daily = _chart_block(d_entries, _day_tick, "day", f"{CHART_DAYS} d",
                         width=1, cols=CHART_DAYS, legend=False)
    daily.append(f"{gut}(day by day: /stats/daily)")
    # Who asked, then how many of them were looking for something. Only on
    # /stats: the drill-down pages answer one question each and get the
    # chart they are named after, nothing stacked underneath it.
    mix_h = _client_mix_block(h_entries, cols=CHART_HOURS, legend=False)
    mix_d = _client_mix_block(d_entries, cols=CHART_DAYS, legend=False)
    finds_h = _finds_block(h_entries, "hour", cols=CHART_HOURS,
                           tick_every=_hour_tick_every, tick_for=_hour_tick)
    finds_d = _finds_block(d_entries, "day", cols=CHART_DAYS,
                           tick_for=_day_tick)
    # One left-column width for all three pairs, so the day charts line up
    # with each other down the page instead of each starting wherever its
    # own hour block happened to end.
    left_w = max(len(l) for blk in (hourly, mix_h, finds_h) for l in blk)
    L += _side_by_side(hourly, daily, left_width=left_w)
    L += ["", f"{gut}sparklines: cache hit % (latest) and night share of "
              f"the window", ""]
    L += _side_by_side(mix_h, mix_d, left_width=left_w)
    # Says which period each half is about. The bars are per column and the
    # figure is the whole window, the same split the night line above uses --
    # but unlabelled it reads as a contradiction whenever the latest column
    # disagrees with the window, which on a quiet hour it easily does.
    L += [f"{gut}share of requests by client · the four add up to the whole",
          f"{gut}bars are per column; the figure on the right is the window",
          ""]
    L += _side_by_side(finds_h, finds_d, left_width=left_w)
    L += [""]
    mapped = _map_block([MAP_SLOT] if map_slot else None, slots=map_slot)
    if mapped:
        L += mapped + ["", ""]
    # Over hit + miss, not over `req`. Plenty of things counted as requests
    # never consult the cache at all -- an unknown place, a phone being sent
    # to the sphere -- and dividing by all of them reported a hit rate lower
    # than the one the cache actually achieved. The two numbers printed
    # beside it are the whole denominator, which is the other reason: a
    # percentage nobody can reproduce from the figures next to it reads as
    # a typo.
    looked_up = _stat["hit"] + _stat["miss"] or 1
    L.append(f"cache      {_stat['hit']:,} hit / {_stat['miss']:,} miss "
             f"({100*_stat['hit']/looked_up:.1f}% hit)")
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
    if _stat["welcome"] or _stat["welcome_none"]:
        L.append("welcome")
        L.append(f"  {'shown':12} {_stat['welcome']:>8,}")
        for kind in ("total", "annular", "partial"):
            if _stat[f"welcome:{kind}"]:
                L.append(f"  {kind:12} {_stat[f'welcome:{kind}']:>8,}")
        # Most of the map sees no eclipse most days. Counted so that
        # "nothing to greet anyone with" cannot read as "it is broken".
        L.append(f"  {'none to show':12} {_stat['welcome_none']:>8,}")
        L.append("")
    if _stat["crossing"] or _stat["crossing_none"]:
        # Split by direction, because they are two different questions. A
        # sunset is watched by somebody who had the page open anyway; a
        # sunrise means somebody was up, or left it open all night.
        L.append("crossing")
        L.append(f"  {'sunset':12} {_stat['crossing_set']:>8,}")
        L.append(f"  {'sunrise':12} {_stat['crossing_rise']:>8,}")
        # Not a failure -- there is no crossing to draw inside the Arctic
        # circle in summer. Counted so that "nobody sees this" and "it is
        # broken" cannot look the same from here.
        L.append(f"  {'none to draw':12} {_stat['crossing_none']:>8,}")
        L.append("")
    L.append("views")
    # view:find and view:disc keep their historical totals in _stat (and on
    # disk) but neither is written to any more, so both are skipped here: a
    # line that can only ever show the same number again reads as a stuck
    # counter, not as history.
    for k in sorted(k for k in _stat if k.startswith("view:")
                    and k not in RETIRED_VIEWS):
        L.append(f"  {k[5:]:12} {_stat[k]:>8,}")
    if _stat["iss"]:
        L.append(f"  {'iss':12} {_stat['iss']:>8,}")
    if _stat["sphere"]:
        L.append(f"  {'sphere':12} {_stat['sphere']:>8,}  (see /stats/sphere)")
    if _stat["geo_redirect"]:
        L.append(f"  {'geo_redirect':12} {_stat['geo_redirect']:>8,}")
    L.append("")
    if _stat["eclipse"]:
        L.append("eclipses")
        L.append(f"  {'page':12} {_stat['eclipse']:>8,}")
        if _stat["eclipse_gif"]:
            L.append(f"  {'gif':12} {_stat['eclipse_gif']:>8,}")
        # Kept apart from the site-wide og count, the same way the event
        # cards are: a card fetch is a link somebody shared, not a page
        # somebody read, and the two answer different questions.
        if _stat["og_eclipse"]:
            L.append(f"  {'card':12} {_stat['og_eclipse']:>8,}")
        # NOT `n`. This function's own parameter is n=50, the row limit for
        # every table below here, and a loop variable called n left it set
        # to whatever the last eclipse's hit count happened to be: one visit
        # to an eclipse page cut "top places" from fifty rows to one, and
        # the same for referrers, objects and the rest. Caught by a test
        # about the places table, in a file that knows nothing about
        # eclipses.
        for key, hits in _eclipse_keys.most_common(5):
            L.append(f"  {key:12} {hits:>8,}")
        L.append("")
    if _stat["evolution_gif"]:
        # Its own line rather than lumped in with the sky animations. This
        # one is a constellation over 100,000 years, which is a different
        # thing being asked for than tonight sped up.
        L.append("constellation evolution")
        L.append(f"  {'gif':12} {_stat['evolution_gif']:>8,}")
        L.append("")
    if _stat["about"]:
        # Counted apart from the object pages it hangs off. Somebody reading
        # /Betelgeuse/about came for what it is called, not for where to
        # point, and folding the two together would hide which of the two
        # this site is actually being used for.
        L.append("object history")
        L.append(f"  {'page':12} {_stat['about']:>8,}")
        L.append("")
    if _stat["events"] or _stat["events.ics"] or _stat["events.rss"]:
        L.append("what's coming up")
        L.append(f"  {'page':12} {_stat['events']:>8,}")
        # Feed pulls are the number worth watching: a page view is a glance,
        # a subscription keeps costing a request an hour until it's cancelled.
        L.append(f"  {'ics':12} {_stat['events.ics']:>8,}")
        L.append(f"  {'rss':12} {_stat['events.rss']:>8,}")
        if _stat["events_ip"]:
            L.append(f"  {'via nav':12} {_stat['events_ip']:>8,}  "
                     f"(bare /events, located by IP)")
        if _events_places:
            # Not "top places": test_server.py keys on that exact string to
            # find the main table, and a second occurrence here shadowed it.
            L.append(f"  by place ({len(_events_places):,} distinct)")
            for name, c in _events_places.most_common(10):
                L.append(f"    {name[:26]:26} {c:>8,}")
        shown, absent = _stat["teaser:shown"], _stat["teaser:absent"]
        if shown or absent:
            L.append(f"  teaser       {shown:,} shown / {absent:,} quiet "
                     f"({100*shown/(shown+absent):.0f}% of charts)")
            for name, c in _events_teased.most_common(8):
                L.append(f"    {name[:26]:26} {c:>8,}")
        L.append("")
    # Golden hour: how many daylight charts could have carried the layer, and
    # how many visitors turned it off with g. An opt-out rate is the only
    # honest read on a default-on feature -- a raw parameter count would just
    # be the people who disliked it.
    g_shown, g_off = _stat["golden:shown"], _stat["golden:off"]
    if g_shown or g_off:
        total = g_shown + g_off
        L.append("golden hour")
        L.append(f"  {'shown':12} {g_shown:>8,}  ({100*g_shown/total:.0f}% of "
                 f"{total:,} daylight charts)")
        L.append(f"  {'switched off':12} {g_off:>8,}")
        L.append("")
    # The day page's tonight panel and next-up list, counted against the
    # daylight charts that could have carried them. Not the same denominator
    # as golden:shown -- that one counts every daylight chart including curl's,
    # and this is browser-only -- so it is printed as its own share rather
    # than folded into the block above and read as a percentage of the wrong
    # total.
    d_panel = _stat["day:panel"]
    if d_panel:
        L.append("day page")
        L.append(f"  {'panel':12} {d_panel:>8,}  (browser daylight charts)")
        L.append("")
    # The aircraft layer on the chart. Three counters, not one, because the
    # question is not "how many saw it" -- it is on by default in daylight,
    # so almost every day chart did. What is worth knowing is whether anyone
    # turns it off, and whether anyone at night goes looking for it.
    ch_on, ch_off, ch_night = (_stat["chart_planes"], _stat["chart_noplanes"],
                               _stat["chart_planes_night"])
    if ch_on or ch_off or ch_night:
        L.append("planes on the chart")
        L.append(f"  {'drawn':12} {ch_on:>8,}  (day charts, the default)")
        L.append(f"  {'turned off':12} {ch_off:>8,}  "
                 f"({100 * ch_off / max(ch_on + ch_off, 1):.0f}% of daylight)")
        L.append(f"  {'asked at night':12} {ch_night:>8,}  (?planes=1 after dark)")
        L.append("")
    pages = sorted(k for k in _stat if k.startswith("page:"))
    if pages:
        L.append("pages")
        for k in pages:
            L.append(f"  {k[5:]:12} {_stat[k]:>8,}")
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
    # The "which object" leaderboard lives on /stats/objects. The per-hour
    # chart stays here -- that answers "is anyone still using it", which no
    # leaderboard does.
    if _referrers:
        L.append("")
        L.append(f"top referrers ({len(_referrers):,} distinct)")
        for name, c in _referrers.most_common(n):
            L.append(f"  {name[:28]:28} {c:>8,}")
    return "\n".join(L) + "\n"


def stats_json(n=50):
    return dict(
        uptime_s=round(time.time() - STARTED),
        requests=_stat["requests"], cache_hit=_stat["hit"], cache_miss=_stat["miss"],
        night=_stat["night"], day=_stat["day"], iss=_stat["iss"],
        animate=_stat["animate"], animate_rejected=_stat["animate_rejected"],
        gif=_stat["gif"], gif_rejected=_stat["gif_rejected"], png=_stat["png"],
        welcome=_stat["welcome"], welcome_none=_stat["welcome_none"],
        crossing=_stat["crossing"], crossing_set=_stat["crossing_set"],
        crossing_rise=_stat["crossing_rise"],
        crossing_none=_stat["crossing_none"],
        sphere=_stat["sphere"], geo_redirect=_stat["geo_redirect"],
        eclipse=dict(page=_stat["eclipse"], gif=_stat["eclipse_gif"],
                     card=_stat["og_eclipse"],
                     distinct=len(_eclipse_keys),
                     top=dict(_eclipse_keys.most_common(n))),
        evolution=dict(gif=_stat["evolution_gif"]),
        about=dict(page=_stat["about"]),
        events=dict(page=_stat["events"], ics=_stat["events.ics"],
                    rss=_stat["events.rss"], via_nav=_stat["events_ip"],
                    places_distinct=len(_events_places),
                    top_places=dict(_events_places.most_common(n)),
                    teaser_shown=_stat["teaser:shown"],
                    teaser_absent=_stat["teaser:absent"],
                    golden_shown=_stat["golden:shown"],
                    golden_off=_stat["golden:off"],
                    top_teased=dict(_events_teased.most_common(n))),
        # day_page, not day: `day` above is already the daylight/night request
        # split, and that one is the older, more-read number of the two.
        day_page=dict(panel=_stat["day:panel"]),
        chart_planes=dict(drawn=_stat["chart_planes"],
                          turned_off=_stat["chart_noplanes"],
                          asked_at_night=_stat["chart_planes_night"]),
        views={k[5:]: v for k, v in _stat.items()
               if k.startswith("view:") and k not in RETIRED_VIEWS},
        pages={k[5:]: v for k, v in _stat.items() if k.startswith("page:")},
        modes={k[5:]: v for k, v in _stat.items() if k.startswith("mode:")},
        errors={k[7:]: v for k, v in _stat.items() if k.startswith("status:")},
        params={k[6:]: v for k, v in _stat.items() if k.startswith("param:")},
        places_distinct=len(_places),
        top_places=dict(_places.most_common(n)),
        # No top_finds: it was the same leaderboard as top_objects, fed by
        # the same requests, and is frozen now.
        objects_distinct=len(_objects),
        top_objects=dict(_objects.most_common(n)),
        referrers_distinct=len(_referrers),
        top_referrers=dict(_referrers.most_common(n)),
        bsky=_read_bsky_stats(),
    )


def stats_sphere_text(n=50):
    L = [f"skymap.sh: sphere stats ({_stat['sphere']:,} views, "
        f"{_stat['sphere_json']:,} data fetches, {_stat['mobile_redirect']:,} "
        f"mobile auto-redirects)", ""]
    if _stat["sphere_radiant"]:
        L.append(f"  {'radiant':12} {_stat['sphere_radiant']:>8,}  "
                 f"(views on a night with a shower running)")
    used = _stat["sphere_golden"] + _stat["sphere_golden_on"]
    if used:
        share = 100 * used / max(_stat["sphere"], 1)
        L.append(f"  {'golden':12} {used:>8,}  "
                 f"({share:.0f}% of sphere views reached golden hour)")
        L.append(f"    {'arrived':10} {_stat['sphere_golden']:>8,}  "
                 f"(opened on a ?golden=1 link)")
        L.append(f"    {'switched':10} {_stat['sphere_golden_on']:>8,}  "
                 f"(tapped into it from the star view)")
    if _stat["planes"]:
        L.append("")
        L.append(f"planes ({_stat['planes']:,} fetches, floor "
                 f"{planes.FLOOR_DEG:.0f}°)")
        # Aircraft per fetch is the number that says whether the floor is
        # right. Below about one, the toggle mostly shows an empty sky and
        # the floor is too high for wherever people actually are -- which is
        # not a thing that can be judged from Geneva alone.
        shown = _stat["planes_shown"]
        served = max(_stat["planes"] - _stat["planes_error"], 1)
        L.append(f"  {'shown':12} {shown:>8,}  "
                 f"({shown / served:.1f} per fetch)")
        # The welcome screen counts aircraft before anyone presses anything.
        # Everything left over is somebody who turned the toggle on, so this
        # pair is what says whether the count on the door is worth its call.
        welcome = _stat["planes_welcome"]
        L.append(f"  {'from welcome':12} {welcome:>8,}  "
                 f"({_stat['planes'] - welcome:,} from the toggle)")
        # Route coverage decides whether the feature reads as "a plane" or as
        # "BA530 to Split". Below about half, the inference framing is
        # carrying more weight than it can.
        if shown:
            L.append(f"  {'routed':12} {_stat['planes_routed']:>8,}  "
                     f"({100 * _stat['planes_routed'] / shown:.0f}% had a "
                     f"route)")
        # Empty and broken are different answers and are counted apart: a
        # quiet sky over a covered city, against a city no volunteer feeds.
        L.append(f"  {'empty':12} {_stat['planes_empty']:>8,}  "
                 f"(nothing above the floor)")
        L.append(f"  {'upstream err':12} {_stat['planes_error']:>8,}")
        # Kept out of the site-wide hit rate on purpose, and split in two
        # here for the same reason. A 15-second position entry is meant to
        # miss and a 6-hour route entry is meant to hit; one blended number
        # would describe neither of them.
        for label, hit, miss in (("pos cache", planes.stats["pos_hit"],
                                  planes.stats["pos_miss"]),
                                 ("route cache", planes.stats["route_hit"],
                                  planes.stats["route_miss"])):
            total = hit + miss
            if total:
                L.append(f"  {label:12} {hit:>8,}  "
                         f"({100 * hit / total:.0f}% of {total:,} hit)")
    sphere_os = sorted(k for k in _stat if k.startswith("sphere_os:"))
    if sphere_os:
        L.append("views by OS")
        for k in sphere_os:
            L.append(f"  {k[10:]:12} {_stat[k]:>8,}")
        L.append("")
    L.append(f"top sphere places ({len(_sphere_places):,} distinct)")
    for name, c in _sphere_places.most_common(n):
        L.append(f"  {name[:28]:28} {c:>8,}")
    return "\n".join(L) + "\n"


def stats_sphere_json(n=50):
    return dict(
        sphere=_stat["sphere"], sphere_json=_stat["sphere_json"],
        sphere_radiant=_stat["sphere_radiant"],
        sphere_golden=_stat["sphere_golden"],
        sphere_golden_on=_stat["sphere_golden_on"],
        mobile_redirect=_stat["mobile_redirect"],
        planes=dict(fetches=_stat["planes"], shown=_stat["planes_shown"],
                    from_welcome=_stat["planes_welcome"],
                    routed=_stat["planes_routed"],
                    empty=_stat["planes_empty"], errors=_stat["planes_error"],
                    floor=planes.FLOOR_DEG,
                    # Never folded into the site-wide hit rate, and never
                    # folded into each other. See stats_sphere_text.
                    cache=dict(planes.stats)),
        by_os={k[10:]: v for k, v in _stat.items() if k.startswith("sphere_os:")},
        places_distinct=len(_sphere_places),
        top_places=dict(_sphere_places.most_common(n)),
    )


def _hour_top_referrer_str(row):
    """The single busiest domain that hour, e.g. 'twitter.com (42)' -- the
    full per-hour breakdown (up to HOURLY_TOP_REFERRERS domains) is only
    in the JSON view; the text table has room for one column, not a list."""
    top_ref = row.get("top_referrers") or {}
    if not top_ref:
        return ""
    name, c = next(iter(top_ref.items()))
    return f"{name[:18]} ({c})"


def _referrer_grid(rows):
    """Hours down the side, domains across the top, so one domain's traffic
    reads as a column over time -- the "top referrer" column in the table
    above only ever names each hour's winner, which hides everything else
    and can't show a trend.

    Only as complete as the log: _flush_hour stores each hour's top
    HOURLY_TOP_REFERRERS domains and drops the rest, so an hour where a
    domain placed below that cutoff genuinely has no number to show. Those
    read as `-` rather than 0, since "not recorded" and "no visits" aren't
    the same claim."""
    totals = Counter()
    for row in rows:
        for name, c in (row.get("top_referrers") or {}).items():
            totals[name] += c
    if not totals:
        return []
    cols = [name for name, _c in totals.most_common(HOURLY_TOP_REFERRERS)]
    widths = [max(len(name[:16]), 6) for name in cols]
    L = ["", f"visits per referrer per hour "
             f"({len(totals):,} domain(s) seen, {len(cols)} shown)", ""]
    head = f"{'hour (UTC)':17}"
    for name, w in zip(cols, widths):
        head += f" {name[:16]:>{w}}"
    L.append(head)
    # Only hours that actually recorded a referrer. Referrer tracking is
    # newer than the hourly log, and most traffic is direct or CLI anyway,
    # so printing every hour buries the handful that carry data under a
    # wall of dashes.
    shown = [r for r in rows if r.get("top_referrers")]
    for row in shown:
        ref = row["top_referrers"]
        line = f"{row['hour']:17}"
        for name, w in zip(cols, widths):
            v = ref.get(name)
            line += f" {(format(v, ',') if v else '-'):>{w}}"
        L.append(line)
    skipped = len(rows) - len(shown)
    if skipped:
        L.append(f"({skipped:,} hour(s) with no referred visits not shown)")
    L += ["", f"totals over the window:"]
    for name, c in totals.most_common(HOURLY_TOP_REFERRERS):
        L.append(f"  {name[:28]:28} {c:>8,}")
    L.append("")
    L.append(f"`-` means that domain wasn't in that hour's top "
             f"{HOURLY_TOP_REFERRERS}, which is all the log keeps.")
    return L


def _idle_gap(prev_hour, hour):
    """The table lists only hours the log actually recorded, so two adjacent
    rows can be a whole night apart. One line naming the hole says "quiet";
    a silent jump says "no data", and those are different claims.

    Collapsed to a marker rather than one zero row per hour: a week-long
    window on a quiet site would otherwise be 168 rows, most of them empty."""
    missing = round((dt.datetime.fromisoformat(hour)
                     - dt.datetime.fromisoformat(prev_hour)).total_seconds() / 3600) - 1
    if missing < 1:
        return None
    return f"{'· · ·':>17}   {missing:,} hour(s) with no requests"


def stats_hourly_text(days=7, hours=None):
    rows = _merge_hour_rows(_hourly_rows(days))
    if not rows:
        return "skymap.sh: hourly stats\n\nno data yet (first hour still in progress)\n"
    # The chart spans the window the caller asked for, zero-filled, so it
    # covers idle hours the table below can only mark as gaps.
    hours = hours or min(days * 24, HOURLY_MAX_QUERY_DAYS * 24)
    L = [f"skymap.sh: hourly stats, last {days}d ({len(rows)} hour(s) on record)", ""]
    L += _chart_block(_dense_hours(rows, hours), _hour_tick, "hour", f"{hours} h",
                      tick_every=_hour_tick_every)
    L += ["",
        f"{'hour (UTC)':17} {'requests':>9} {'hit%':>6} {'day':>6} {'night':>6} "
        f"{'404':>5}  {'top referrer':24}"]
    prev = None
    for row in rows:
        if prev:
            gap = _idle_gap(prev, row["hour"])
            if gap:
                L.append(gap)
        prev = row["hour"]
        # hit% over the requests that could have hit the cache, not over
        # every request in the row: the 404 column beside it is exactly the
        # difference, and those never went near the cache.
        req = (row["requests"] - row.get("notfound", 0)) or 1
        hitpct = 100 * row["hit"] / req
        current = "  (in progress)" if row["hour"] == _hour_key and row is rows[-1] else ""
        # Blank rather than 0: most hours have none, and a column of zeroes
        # is harder to scan past than an empty one.
        nf = f"{row['notfound']:,}" if row.get("notfound") else ""
        L.append(f"{row['hour']:17} {row['requests']:>9,} {hitpct:>5.1f}% "
                f"{row['day']:>6,} {row['night']:>6,} {nf:>5}  "
                f"{_hour_top_referrer_str(row):24}{current}")
    L += _referrer_grid(rows)
    return "\n".join(L) + "\n"


def stats_daily_text(days=CHART_DAYS):
    rows = _hourly_rows(days + 1)
    if not rows:
        return "skymap.sh: daily stats\n\nno data yet (first hour still in progress)\n"
    entries = _dense_days(rows, days)
    L = [f"skymap.sh: daily stats, last {days}d", ""]
    L += _chart_block(entries, _day_tick, "day", f"{days} d", width=2)
    L += ["",
        f"{'day (UTC)':12} {'requests':>9} {'hit%':>6} {'day':>7} {'night':>7} "
        f"{'404':>5} {'hours':>6}"]
    for e in entries:
        # Every day in the window gets a row, including the empty ones. A
        # daily table is 30 lines at most, so unlike the hourly one there is
        # room to just show the zeroes rather than collapse them. A day with
        # no requests gets `-` for hit%, not 0.0% -- there is no ratio to
        # take, same rule the sparklines use.
        # Same denominator as the hourly table: a day whose only traffic was
        # requests for places that don't exist has no hit rate to report,
        # and gets `-` rather than a 0.0% it never earned.
        served = _answered(e)
        hit = f"{100 * e['hit'] / served:.1f}%" if served else "-"
        nf = f"{e['notfound']:,}" if e["notfound"] else ""
        L.append(f"{e['date']:12} {e['requests']:>9,} "
                 f"{hit:>6} {e['day']:>7,} {e['night']:>7,} "
                 f"{nf:>5} {e['hours']:>6,}")
    L.append("")
    L.append("`hours` is how many hours of that day the log recorded at all -- "
             "fewer than 24")
    L.append("means the server was idle or down for the rest, not that traffic "
             "was zero.")
    return "\n".join(L) + "\n"


def stats_live_json(since=0.0):
    """What has arrived since the caller last asked.

    Returns map cells rather than coordinates: the browser has no projection
    and shouldn't need one, and a cell is what it has to address anyway. Each
    entry is [row, col, ramp index] -- the index is where the dot settles
    after its flash, so the resting colour keeps up as totals grow.

    The fine grid, because the only caller is the page that drew it."""
    now = time.time()
    loaded = _load_worldmap(fine=True)
    flash = []
    if loaded:
        _rows, w, h, lat_top, lat_bot = loaded
        shade, _heat = _map_shader(w, h, lat_top, lat_bot)
        cells = set()
        for at, lat, lon in _geo_recent:
            if at <= since:
                continue
            cell = _map_cell(lat, lon, w, h, lat_top, lat_bot)
            if cell:
                cells.add(cell)
        flash = [[r, c, shade(r, c)] for r, c in sorted(cells)]
    # head and legend are the two lines the page can keep current without
    # redrawing anything: finished strings, because the server is the one
    # that owns their wording and their arithmetic. The raw numbers stay
    # alongside them -- they were here first and anything scripting this
    # endpoint wants those, not a sentence.
    return dict(now=now, flash=flash, requests=_stat["requests"],
                distinct=len(_geo_hits), head=_headline(),
                legend=_map_legend())


def stats_daily_json(days=CHART_DAYS):
    return dict(days=_dense_days(_hourly_rows(days + 1), days))


def stats_hourly_json(days=7):
    rows = _hourly_rows(days)
    if rows and rows[-1]["hour"] == _hour_key:
        rows[-1] = dict(rows[-1], in_progress=True)
    return dict(hours=rows)

# --- per-IP rate limit -------------------------------------------------------
# The sky does not change in a second, but `watch -n 1 curl skymap.sh` does not know
# that: one such client is 86,400 requests a day. A token bucket costs a dict
# entry and stops it becoming someone else's bill.
#
# NOTE: this is per process. With N gunicorn workers the effective ceiling is
# N x RATE, so divide, or move the buckets to Redis if you run more than one box.
# Paths that never spend a visitor's allowance. All of them are cheap,
# cached or length-capped, and all of them fire more often than a page view
# does: /complete on every pause in typing, /beacon/golden on every flick
# between the two sphere modes. Throttling those would eat the allowance
# meant for actual charts.
RATE_EXEMPT = ("/healthz", "/robots.txt", "/complete", "/complete/objects",
               "/beacon/golden")

RATE = 30                   # sustained requests per minute per IP
BURST = 45                  # allowed spike before shaping kicks in
MAX_IPS = 20000             # bounded so the table cannot grow without limit
_buckets = OrderedDict()    # ip -> [tokens, last_seen]

# The /stats family gets its own, looser bucket rather than sharing the one
# above. An open /stats tab polls /stats/live every 3 s -- 20 requests a
# minute -- which would eat two thirds of the chart allowance and start
# throttling the reader's actual sky requests. A separate bucket also means
# hammering /stats cannot lock someone out of the charts, or the reverse.
#
# These are deliberately generous: the whole family is no-store and cheap
# (0.3 ms for /stats/live, 2 ms for /stats itself), so the cap exists to stop
# abuse, not to shape normal use. A polling tab uses a fifth of it.
STATS_RATE = 100            # sustained requests per minute per IP
STATS_BURST = 140
_stats_buckets = OrderedDict()
STATS_PATHS = ("/stats", "/stats/sphere", "/stats/hourly", "/stats/daily",
               "/stats/live")


def client_ip(request: Req):
    h = request.headers
    for k in ("cf-connecting-ip", "x-real-ip"):
        if h.get(k):
            return h[k]
    if h.get("x-forwarded-for"):
        return h["x-forwarded-for"].split(",")[0].strip()
    return request.client.host if request.client else "?"


def take_token(ip, now=None, buckets=None, rate=RATE, burst=BURST):
    """True if allowed. Returns (ok, retry_after_seconds).

    `buckets` picks which table to draw from, so the /stats family can have
    its own allowance without its polling counting against the charts."""
    now = now or time.monotonic()
    buckets = _buckets if buckets is None else buckets
    tokens, last = buckets.pop(ip, (burst, now))
    tokens = min(burst, tokens + (now - last) * rate / 60.0)
    ok = tokens >= 1.0
    if ok:
        tokens -= 1.0
    buckets[ip] = (tokens, now)
    if len(buckets) > MAX_IPS:
        buckets.popitem(last=False)           # evict least recently seen
    return ok, 0 if ok else max(1, int((1.0 - tokens) * 60 / rate))


THROTTLED = """\
  Slow down a moment.

  You are asking faster than {rate} requests a minute, which is faster than the
  sky changes: positions here are recomputed every 5 minutes, so a tighter loop
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
        print("[startup] no TLE on disk; run tle.py, ISS disabled")


@app.on_event("shutdown")
def _save_on_exit():
    # `systemctl restart` (a normal deploy) sends SIGTERM first, so this is
    # the common case that actually matters -- the hourly-boundary save
    # covers crashes/kills that skip shutdown handling entirely.
    #
    # The hour in progress goes out with it. Only _roll_hour used to write
    # to the log, so everything tallied since the last o'clock died with the
    # process: the cumulative counters survived in the state file and the
    # charts quietly lost that stretch, which on a day of several deploys
    # added up to hours of missing traffic. _dense_hours has always summed
    # duplicate rows for the same hour precisely so this could happen -- the
    # next process flushes the rest of that hour when it rolls.
    global _hour_stat
    # Same order as _roll_hour, and under the same lock: take the hour away
    # first, then write it. A request still in flight while this runs then
    # lands in the replacement counter rather than in the one being flushed,
    # instead of being counted into a Counter that is about to be dropped.
    with _hour_lock:
        # Cleared so a second shutdown can't write the same hour twice. One
        # process only shuts down once; two TestClient context managers in
        # one pytest run are two startups and two shutdowns.
        ending, ended = _hour_key, _hour_stat
        _hour_stat = Counter()
    _flush_hour(ending, ended)   # saves the cumulative state too


def _wants(request: Req):
    """(mode, colour). mode is 'json' | 'html' | 'text'."""
    q = request.query_params
    ua = (request.headers.get("user-agent") or "").lower()
    accept = (request.headers.get("accept") or "").lower()
    terminal = any(t in ua for t in TERMINALS)

    if q.get("format") == "json":
        return "json", False
    # An unfurler asks for */* and needs the <head>. Ahead of the terminal
    # test on purpose: see CRAWLERS.
    if _is_crawler(ua):
        return "html", True
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
        view="horizon",
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
        nodso=bool(q.get("nodso")),
        panel=bool(q.get("panel")),
        # Whether the answer is going to be markup. ?panel= alone was the
        # gate on the chart's link markers, and anyone can send it -- so a
        # terminal asking for ?panel=1 got raw \x11/\x12/\x13 and the href
        # between them printed into the chart. panel still means what it
        # always did (the inset beside the chart, a documented CLI option);
        # this is the separate question _chart_link actually needed to ask.
        browser=_wants(request)[0] == "html",
        planes=bool(q.get("planes")),
        noplanes=bool(q.get("noplanes")),
        # The opt-out, not the opt-in: golden hour is on by default, so the
        # plain URL stays clean and only someone who turned it off carries a
        # parameter for it.
        nogolden=bool(q.get("nogolden")),
        # Anchors on an animation frame's labels. The page asks for it one
        # frame at a time, on the frame it has paused on. See api.Request.
        links=bool(q.get("links")),
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


api._plane_counter = lambda key: _stat.__setitem__(key, _stat[key] + 1)


def _cache_ttl(r, daytime):
    """How long this render may be held. See PLANES_BUCKET."""
    if api.planes_on(r):
        return PLANES_TTL
    return DAY_TTL if daytime else NIGHT_TTL


def _cache_key(r, daytime):
    # quadrant_requested as well as quadrant, and they are not the same
    # question. A bare ?quadrant -- show me the grid, I have not picked a
    # letter yet -- leaves r.quadrant None and only turns dso on, so its key
    # was identical to plain ?dso=1's. Whichever of the two was asked for
    # first won the entry and the other was served its answer: ?quadrant came
    # back with no grid, or ?dso=1 came back wearing one. ?quadrant&nodso=1
    # collided with the plain view the same way.
    #
    # The name is in here for the same reason, found the hard way a second
    # time. Without it the key was the rounded cell alone, so every request
    # landing within about 11 km shared one cached page -- and the page
    # carries the whole Place inside it, name, exact coordinates and the
    # "near X" hint. Whichever request arrived first decided who everyone
    # else was told they were:
    #
    #   ask /47.38,8.54 first, then /Zurich  -> both say "47.40,8.50"
    #   ask /Zurich first, then /47.38,8.54  -> both say "Zürich"
    #
    # and it is not only coordinates against a name. 754 pairs of distinct
    # towns over 40,000 people share a cell -- New York with Brooklyn, Manila
    # with Quezon City, Kinshasa with Brazzaville, which is two countries.
    #
    # The sky was never wrong: both round to the same cell, and 11 km is well
    # inside what a text chart resolves, which is what the rounding is for.
    # Only the identity was, which is why nobody reported it.
    #
    # This costs nothing in cardinality. Coordinates reach here already
    # snapped to 0.1 on every path -- lookup_place snaps typed ones, _geo
    # snaps the CDN's -- so a coordinate name is one of the same 6.5 million,
    # and named cities add the 41,000 in the catalogue.
    # planes_on and not the raw flags: two URLs that resolve to the same
    # answer are the same page, and a day chart with ?planes=1 renders
    # exactly what the bare URL does.
    q = (r.place.name, round(r.place.lat, 1), round(r.place.lon, 1),
         api.planes_on(r),
         r.view, r.facing, r.span,
         (r.find or "").lower(), bool(r.tle), r.night, r.width, r.dso, r.quadrant,
         r.quadrant_requested, r.lines, r.panel, r.golden, r.links)
    bucket = PLANES_BUCKET if api.planes_on(r) else (
        DAY_BUCKET if daytime else NIGHT_BUCKET)
    stamp = int(r.when_utc.timestamp() // bucket)
    return (q, stamp)


def _cached(r):
    """(Result, daytime, from_cache). One entry serves all four output modes."""
    global _hits, _misses
    daytime = api.is_daytime(r)
    # Counted here and not in the composer: the composer sits behind this
    # cache, so with a fifteen-second entry three readers in one bucket
    # showed up as one. This runs per request, which is the question being
    # asked -- how many people were shown aircraft, not how many times the
    # chart was drawn.
    api._count_planes(r, daytime)
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
    _cache[key] = (now + _cache_ttl(r, daytime), res)
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
# Three numbers decide what an animation looks like, and they are separate
# on purpose -- they used to be one, and that made every question about it
# the same question.
#
#   ANIMATE_STEP_MIN   how much sky passes between frames
#   ANIMATE_PLAY_MS    how long each frame is on screen
#   ANIMATE_FRAME_DELAY  how fast the server hands them over
#
# Ten minutes is where the step stops paying, and it is worth writing down
# why rather than leaving it as taste.
#
# The chart is a character grid, so every position snaps to a cell. A column
# is about 3.1 degrees wide at the usual width and the sky turns 0.25
# degrees a minute, so ten minutes moves a star most of a column and five
# moves it less than half of one -- at a five-minute step two frames in
# three put it back in the cell it was already in. The jumps that read as
# jerky are the grid's, and no frame rate touches them.
#
# What a finer step does refine is everything not on the grid: the twilight
# fade, the Sun glyph's colour, and the headline's own numbers. That is real,
# and it is why this is ten and not fifteen. It stops at ten because the day
# chart's Sun arc is bucketed at DAY_BUCKET, ten minutes, so below that the
# daytime trail cannot differ at all.
#
# Duration is the other half. A 24-hour run is 144 frames at 130ms, about 19
# seconds -- the same length as the old 96 frames at 200ms, for half again
# the bytes. Five minutes at 150ms was the alternative: 288 frames, 6MB, and
# 43 seconds of watching, which is the part anybody would actually feel.
#
# The wire delay has to stay under the play rate or the buffer drains and
# playback stalls waiting on the network. A frame costs about 12ms to build,
# so 90ms of sleep hands one over every ~102ms against 130ms of playback --
# ahead, with room for a slow frame. There is a test on that inequality.
# The welcome plays a touch slower than the crossing. It has 17-25 frames
# against 44 and covers two hours rather than three minutes, so the same
# 170ms would be over before it registered.
WELCOME_FRAME_MS = 260
ANIMATE_STEP_MIN = 10              # simulated minutes per frame (6/hour)
ANIMATE_PLAY_MS = 130              # how long the page holds each frame
ANIMATE_FRAME_DELAY = 0.09         # seconds between frames on the wire
# The GIF follows the stream rather than keeping a pace of its own. A shared
# clip is "here is what I just watched", so it should be what was watched:
# the same step and the same speed, or the thing somebody sends on is a
# different animation from the one they saw.
#
# It is not free. Every frame is a rendered image rather than a line of
# text, so the step decides Pillow work and file size instead of bandwidth
# -- a six-hour clip goes from 24 frames to 36, and 117KB to about 175KB.
# Worth it for the two not disagreeing.
GIF_STEP_MIN = ANIMATE_STEP_MIN
GIF_FRAME_MS = ANIMATE_PLAY_MS
# In minutes, not frames. These are tuned by eye against the sky rather than
# against the frame rate -- how early the night field starts showing, how
# long the stars last past dawn -- so they have to hold their value when the
# step changes. As frame counts (5 and 3, times a 15-minute step) they came
# to 75 and 45 minutes, and moving the step to ten would silently have made
# them 50 and 30. Same numbers, said in the units that mean something.
ANIMATE_DUSK_LEAD_MIN = 75         # night sky starts showing this early at
                                    # dusk -- good as-is, don't touch
ANIMATE_DAWN_LAG_MIN = 45          # stars last longer past dawn instead of
                                    # cutting off early -- the fade curve is
                                    # non-linear, so this is tuned by measured
                                    # effect, not by arithmetic; see
                                    # compose_frame's dawn_lag_minutes
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
    data = gif.frames_to_gif(frames, GIF_FRAME_MS)
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
    dusk_lead_minutes = ANIMATE_DUSK_LEAD_MIN
    dawn_lag_minutes = ANIMATE_DAWN_LAG_MIN
    _animate_active += 1
    try:
        for i in range(steps):
            t = start + dt.timedelta(minutes=ANIMATE_STEP_MIN * i)
            frame_r = base_r.at(t)
            # is_ui is already "this stream is the browser's live preview",
            # and panel is what tells api to lay a frame out the way the page
            # around it is laid out -- the zenith inset handed back as its own
            # piece rather than stacked underneath as a dozen more rows. The
            # live URL never carried it, so every browser frame was built in
            # terminal shape and #chart-zenith sat frozen at the moment the
            # page was loaded while the chart ran through the night.
            frame_r.panel = bool(is_ui)
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


def _nearby_city_for_redirect(request: Req, place: str | None, mode: str):
    """The city name a browser landing on raw coordinates should be bounced
    to instead, or None if there's nothing to redirect. Coordinates can come
    from the URL path itself (an explicit /lat,lon, the 'm' keyboard
    shortcut's real GPS fix, a bookmarked link, someone pasting lat,lon into
    the search box) or, when place is None, the CDN's own IP geolocation on
    a bare landing (_geo, the same fallback api.Request uses to render).

    curl/JSON/ICS/RSS callers keep the exact coordinates verbatim --
    redirecting those would silently break anyone scripting or subscribing
    against a specific lat/lon, and there's no URL bar to tidy up there, so
    every caller of this must gate on mode == "html" itself before using it.
    """
    if mode != "html":
        return None
    # An unfurler's IP is a datacentre, not a reader. Bluesky's fetcher sits
    # in Columbus, so IP-geolocating it bounced skymap.sh to /Columbus and
    # every card shared on Bluesky said "the night sky above Columbus" --
    # someone else's city, pinned to the link for everyone who saw it.
    #
    # Only the IP branch is refused. Coordinates spelled out in the path are
    # a real request for that place and still tidy up, for a crawler as much
    # as for anyone.
    if not place and _is_crawler((request.headers.get("user-agent") or "").lower()):
        return None
    if place:
        m = api.LATLON.match(place)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
    else:
        latlon = _geo(request)
        if not latlon:
            return None
        lat, lon = latlon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return api._confident_nearby_city(lat, lon)


def _respond(request: Req, place: str | None):
    mode, colour = _wants(request)
    q = request.query_params
    # A browser landing on raw coordinates gets bounced to the nearby city's
    # own name instead -- both the URL bar and the search field then read
    # "Geneva", not "46.20,6.20".
    city = _nearby_city_for_redirect(request, place, mode)
    if city:
        _stat["geo_redirect"] += 1
        qs = f"?{request.url.query}" if request.url.query else ""
        # no-store, like /healthz -- without an explicit Cache-Control,
        # Cloudflare applies its own default TTL to this at the edge, and a
        # visitor who hit these exact coordinates before this redirect
        # existed (or before today's deploy) keeps getting served that
        # stale, un-redirected response indefinitely. Even more load-bearing
        # when place is None (the bare-domain, IP-geolocation case): this
        # redirect is keyed off *this visitor's* IP, so caching it at all
        # would bounce every later visitor sharing that edge cache entry to
        # Geneva regardless of where they actually are.
        # #ip when the server chose this place, nothing when the reader did.
        # The whole "looks like you're not in Zurich" notice hangs off this
        # one bit: a place somebody typed, clicked or bookmarked is their
        # decision and must never be second-guessed, and only the bare-domain
        # landing (place is None) is the site guessing from an IP.
        #
        # A fragment rather than a query parameter, for three reasons: it
        # never reaches the server, so it cannot split a cache entry; it is
        # not part of what a shared link means; and the page strips it from
        # the address bar as soon as it has read it, so a reload does not
        # bring the notice back.
        mark = "#ip" if not place else ""
        return RedirectResponse(f"/{quote(city)}{qs}{mark}", status_code=302,
                               headers={"Cache-Control": "no-store"})
    if place and api.lookup_place(place) is None:
        near = api.suggest(place)
        did = ("\n  Did you mean:\n" + "".join(f"    {n}\n" for n in near)
               if near else "")
        # _roll_hour first: this path never goes through _tally, so nothing
        # else here advances the hour, and without it a 404 arriving in a
        # quiet stretch lands in whatever hour the last real request was in.
        _roll_hour()
        _stat["requests"] += 1; _stat["status:404"] += 1; _stat[f"mode:{mode}"] += 1
        # requests as well as notfound. A 404 is a request, and counting it
        # in one book and not the other is what made the headline total on
        # /stats disagree with the charts underneath it: every unknown place
        # landed in _stat and in none of the bars, so the two numbers drifted
        # apart by exactly the 404 count. notfound stays alongside it -- the
        # hourly table has its own column for these, so they are still
        # separable, they are just no longer missing from the total.
        _hour_stat["requests"] += 1
        _hour_stat[_client_of(mode, _is_mobile(request),
                              _is_crawler((request.headers.get("user-agent")
                                           or "").lower()))] += 1
        _hour_stat["notfound"] += 1
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
    _tally(r, daytime, hit, mode, res.status, res.data, colour,
           crawler=_crawler_req(request),
           referrer=_referrer_domain(request), mobile=_is_mobile(request))
    edge = DAY_EDGE if daytime else NIGHT_EDGE
    # A browser page is private; a terminal or JSON response is not.
    #
    # These routes decide what to serve from the User-Agent: a phone gets a
    # 302 to the sphere (_mobile_sphere_redirect) and everyone else gets the
    # page. A shared cache with no Vary keyed only on the URL, which is what
    # Cloudflare does by default, therefore serves whichever it saw first to
    # everyone for the length of s-maxage -- one desktop visitor warms `/`
    # with the text page and every phone behind it lands there instead of on
    # the sphere. It looks intermittent because it depends on who arrived
    # first inside each window.
    #
    # The width ladder made this constant rather than occasional: browsers
    # used to bounce themselves to `/?w=NNN` (a different cache key) and now
    # they stay on the bare URL, which is exactly the entry a phone needs.
    #
    # Only ?format=json keeps edge caching, because only it has a URL of its
    # own. Text and HTML are two representations of ONE url chosen by the
    # user agent, and a shared cache stores one object per url: Cloudflare
    # honours Vary for Accept-Encoding and nothing else, so no header we can
    # send makes it keep both. It stored the curl render of /Venus and then
    # served that text/plain to Twitterbot, which reported the card missing
    # -- correctly, since it was looking at a terminal chart.
    #
    # So the negotiated page is private and the CDN keeps out of it. The
    # process-local render cache (X-Cache below) is untouched and does the
    # real work anyway; what is lost is one edge hop for curl.
    if mode == "json":
        cache = (f"public, max-age={edge // 4}, s-maxage={edge}, "
                 f"stale-while-revalidate=600")
    else:
        cache = f"private, max-age={edge // 4}"
    headers = {"Cache-Control": cache,
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
        # Share as a GIF + Share as a PNG side by side (.share-row) in the
        # drawer's actions section -- gif-btn/gif-status are found by id
        # from the JS rather than by parentElement.querySelector, so they
        # can live in a different part of the page than animate-btn.
        # gif-status sits in its own column under the button (.gif-group),
        # so the "View GIF" link that appears there once rendering finishes
        # reads as belonging to that button, not floating next to Share as a PNG.
        # Always visible (rendering doesn't actually depend on animate having
        # played -- data-gif-url is a real, independent server route) --
        # skymapPollGifCapacity greys it out on page load whenever the
        # server's at its concurrent-render cap, same as it always has, just
        # no longer gated behind clicking animate first.
        extra = ('<div class="share-row">'
                '<div class="gif-group">'
                f'<button id="gif-btn" class="animate-btn gif-btn" '
                f'data-gif-url="{api._animate_gif_url(r)}" '
                'onclick="skymapRenderGif(this)">Share as a GIF</button>'
                '<span id="gif-status" class="gif-status"></span>'
                '</div>'
                f'<a class="animate-btn" href="{png_href}" target="_blank" '
                'rel="noopener">Share as a PNG</a>'
                '</div>')
        # Carries the exact moment on screen (r.when_local, whether that
        # came from ?t= or just defaulted to now) into the live-preview
        # fetch -- otherwise the animation would start from real "now"
        # while the static frame above it shows whatever time was asked
        # for, which is confusing on any ?t= link and outright broken on a
        # future one.
        live_t = r.when_local.strftime("%Y-%m-%dT%H:%M")
        # Carries the static chart's own width through too -- compose_frame
        # (unlike the GIF export) renders at whatever width it's given, and
        # without this the preview replaces #chart-pre with frames rendered
        # at the DEFAULT_HORIZON_WIDTH fallback, visibly *shrinking* the
        # chart the moment animate starts on any auto-fit-widened page.
        live_w = f"&w={r.width}" if r.width else ""
        # ui=1 marks this as the page's own JS fetch, not a real curl/terminal
        # session -- fetch() doesn't send Accept: text/html by default, so
        # _wants() can't tell the two apart on headers alone, and the
        # browser already has a real "Share as a GIF" button, so it doesn't
        # need the curl-command hint _animate() appends for actual terminals.
        animate_btn = (
            '<div class="animate-controls">'
            f'<button id="animate-btn" class="animate-btn" '
            f'data-live-url="/{r.place.slug}?animate=24&t={live_t}{live_w}&ui=1" '
            # The page's playback tick reads this rather than hardcoding a
            # number, so retuning the pace here cannot leave the browser
            # playing at a speed nobody chose. It is ANIMATE_PLAY_MS and not
            # the wire delay: playing a little slower than the frames arrive
            # is what keeps the buffer ahead, so the tick never waits on the
            # network. See the constant for the rest of the reasoning.
            f'data-frame-ms="{ANIMATE_PLAY_MS}" '
            # Simulated minutes per frame, so the page can work out which
            # moment the paused frame is showing and ask for that one again
            # with deep sky on.
            f'data-step-min="{ANIMATE_STEP_MIN}" '
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
        # No place or find field of its own any more -- the command bar's
        # #q is already pre-filled with the place actually being viewed,
        # and find is promoted onto the header too (header_html's
        # find_value below), right next to it. This form's own onsubmit
        # still reads both by id regardless of where they live in the DOM.
        # Armed once for the page, used by whichever header branch runs. A
        # pinned ?t= page arms nothing: it is not that minute and never
        # becomes it.
        pinned = q.get("t") is not None
        own = _geo(request)          # private route, so this may go in
        crossing = (api.welcome_arm_html(r.place, r.when_utc, pinned=pinned,
                                         own=own)
                    + api.crossing_arm_html(r.place, pinned=pinned, own=own))
        # No date/time form in the drawer any more: the moment on the
        # headline is clickable and opens a picker where the question is
        # asked. Two ways to set the same thing, one of them three clicks
        # deep in a drawer, was one too many.
        #
        # The command bar's own submit already reads #whenDate/#whenTime
        # null-safely, so typing a place still works -- it just no longer
        # carries a date across with it, which nothing on this page can now
        # set anyway.
        explore = ""
        # Shown for everyone -- CSS (.mobile-only, a pointer:coarse media
        # query) decides who actually sees it, since there's no reliable
        # server-side "does this phone have a gyroscope" signal the way
        # TERMINALS lets curl/wget be told apart from a browser.
        sphere_btn = f'<a class="animate-btn mobile-only" href="/{r.place.slug}/sphere">◎ View in 3D</a>'
        # Same day/night gate quadrant_btn's disabled state uses -- dso and
        # quadrant only mean anything on the star chart, not the Sun's-arc
        # day view. "quadrant" (the 'd' key) moves dso and the grid
        # together; "grid" (the 'z' key) always lands on the bare lettered
        # grid so the arrow-key/enter picker has something to land on.
        star_chart = r.night or not daytime
        kbd = {}
        if star_chart:
            kbd["quadrant"] = api._quadrant_toggle_url(r)
            kbd["grid"] = api._quadrant_grid_url(r)
        else:
            # The mirror of the above: golden hour is a daylight layer, so
            # the g key exists exactly where the quadrant keys do not.
            kbd["golden"] = api._golden_toggle_url(r)
        # No p on a pinned chart: there is nothing to toggle, and a key that
        # navigates somewhere for no visible reason is worse than an inert one.
        if not r.when_explicit:
            kbd["planes"] = api._planes_toggle_url(r)
        controls = api.controls_html(explore, animate_btn, quadrant_btn, sphere_btn, extra)
        # Trailing slash: the bar is a path, and on a chart the next segment
        # is the invitation. Typing after it searches objects, so "Tokyo/"
        # then "ven" reads as the URL it will go to. /Tokyo/ and /Tokyo are
        # the same page, so the slash costs nothing if it is never used.
        header = api.header_html(f"{r.place.name}/", crossing=crossing)
        # The width ladder applies to any plain horizon panorama, find=
        # included -- find draws the full panorama now, not a crop, so it
        # goes through the same _effective_width(r) as the ordinary view
        # (see _compose_sky's width= line). facing= is still excluded: it
        # has its own aspect-locked "true shape" formula _effective_width
        # doesn't govern. disc is a fixed circle, excluded for the same
        # reason.
        #
        # An explicit ?w= opts out too: someone who named a width means it,
        # and the ladder would quietly override them. That's also what keeps
        # a shared ...?w=170 link, the CLI, and the animate stream on the
        # single-render path they have always been on.
        fits_width = not r.facing
        laddered = fits_width and not r.width
        # Called fresh here rather than read off res.data -- _compose_find
        # doesn't set coming_up_card (find already answers "what's worth
        # looking at"), but the card is a homepage highlight, not tied to
        # whichever view composed this particular render. scan_global() is
        # memoised per UTC day, so a second call here is cheap. Plural
        # (events_cards, not events_card): the odd night two things are
        # both genuinely close -- an eclipse and a shower peak a day apart,
        # say -- gets both, cycled, not just whichever ranks higher.
        # Gone from the chart pages entirely. By day it said the same thing
        # the "next up" box says, one line at a time and with a dismiss
        # button, where the box says five rows at once and needs no
        # dismissing. By night the chart is the whole page and the strip was
        # the one thing standing between it and the top of the window.
        #
        # events_cards() is still called nowhere else on this path, so this
        # is a line of work saved as well as a strip of the fold.
        coming_up_card = ""
        # strip_duplicate_ui_lines: the prose repeats itself once real UI
        # exists for the same thing -- Coming up (the card above), Share
        # as a PNG (the drawer button), See tonight's chart now (a curl
        # command, odd to hand a browser reader who can just click). CLI/
        # JSON/PNG output is untouched -- both strips only run on the copy
        # of page_text that becomes this HTML response.
        html_text = api.strip_duplicate_ui_lines(page_text, r, res, base_url)

        def _rendered(text):
            return api.ansi_to_html(api.strip_footer_line(text))

        if laddered:
            # One render per rung, each through the same _cached() as any
            # other request -- so a rung a visitor has already been served
            # (at this place, in this time bucket) is a cache hit, not
            # repeated work. Costs ~4 ms per rung on a cold miss, against
            # the up-to-34 separate cache entries ?w= and ?panel= used to
            # split this page into once the auto-fit reload had picked a
            # width per visitor.
            rungs, zenith, prose = [], "", ""
            for _min_ch, cols, panel in api.CHART_LADDER:
                rr = r.sized(cols, panel)
                rung_res, _daytime, _hit = _cached(rr)
                rung_text = rung_res.text.replace("{base_url}", base_url)
                rung_text = api.strip_duplicate_ui_lines(rung_text, rr, rung_res,
                                                         base_url)
                # The inset and the prose come out of the rung rather than
                # staying in it, so the panorama gets the full width at every
                # step of the ladder. Both are identical across rungs, so the
                # last one to set them wins and it makes no difference which:
                # taken from whichever rungs actually carry the markers, since
                # the narrowest has no panel and therefore no inset.
                chart, rung_zenith, rung_prose = api.split_chart_parts(rung_text)
                if rung_zenith:
                    zenith = _rendered(rung_zenith)
                if rung_prose:
                    prose = _rendered(rung_prose)
                rungs.append((cols, panel, _rendered(chart)))
            # Same day/night gate the quadrant and golden-hour controls above
            # use. The Sun's arc renders at 70% height in a browser
            # (api._day_height), and this is what fills the room: where and
            # when you are in a box of its own, the night it is counting down
            # to beside the arc, and the next few events under both.
            #
            # res.data, not a recomputation -- that is the day view's own JSON
            # payload, already built by _compose_day for ?format=json.
            # One layout, day and night. The day page used to be a different
            # shape -- the Sun's arc in a narrow column with a panel of
            # tonight beside it and a list of events beneath -- and the chart
            # paid for all of it in width and in rows. Both views share one
            # axis and one set of pieces now, so there is nothing left for
            # two layouts to express.
            #
            # Both take the summary line out of the drawing and into a box of
            # its own, so head=False either way. The object pages lift theirs
            # into the lede instead and never ask for it.
            head_html, rungs = api.lift_chart_head(rungs, r.place.near,
                                                   r.when_local)
            head_html = api.pin_near(head_html, r.place.near)
            head_html = api.dim_directions(head_html)
            chart_html = api.chart_layout(rungs, zenith, prose, head=False)
            on_pill, on_modal = api.sky_pill_html(r, res.data)
            header = api.header_html(f"{r.place.name}/", pill=on_pill,
                                     crossing=crossing)
            chart_html = api.chart_page(head_html, chart_html, on_modal)
            if not r.night and daytime:
                _stat["day:panel"] += 1
        else:
            chart_html = api.chart_pre(_rendered(html_text))
        # A place named in the URL gets its own card; the bare domain keeps
        # the generic one.
        #
        # place is the path segment, so it is None exactly when the location
        # was guessed from the caller's IP -- and for an unfurler that IP is
        # a datacentre. Handing that page a place card meant a link to
        # skymap.sh unfurled as whichever city the crawler happened to sit
        # in, and stayed that way for everyone who saw the post.
        if place:
            body = api._object_page_template().format(
                               title=f"skymap.sh: {r.place.name}",
                               head_extra=api.place_head(r.place, base_url),
                               header=header, controls=controls,
                               wide_class=" w-wide" if fits_width else "",
                               coming_up_card=coming_up_card,
                               kbd_urls=json.dumps(kbd), shortcuts_hint=api.shortcuts_hint(r),
                               body=chart_html)
        else:
            # Plain "skymap.sh", not the guessed location: this branch is
            # reached by unfurlers, and titling the card with the city their
            # datacentre sits in leaks it into every post the link appears
            # in -- as coordinates, at that, since a bare IP fallback keeps
            # them as its display name.
            body = api._object_page_template().format(
                               title="skymap.sh",
                               head_extra=api.home_head(),
                               header=header, controls=controls,
                               wide_class=" w-wide" if fits_width else "",
                               coming_up_card=coming_up_card,
                               kbd_urls=json.dumps(kbd), shortcuts_hint=api.shortcuts_hint(r),
                               body=chart_html)
        return HTMLResponse(body, status_code=res.status, headers=headers)
    # The layout seams are for a browser to break the text apart at; a
    # terminal asking for ?panel=1 gets the pieces stacked, not the markers.
    text = api.strip_slots(page_text)
    text = text if colour else api.strip_ansi(text)
    return PlainTextResponse(text, status_code=res.status, headers=headers)


@app.middleware("http")
async def head_as_get(request: Req, call_next):
    """Answer HEAD the way GET would.

    HEAD asks for the headers a GET would return, without the body -- it is
    what `curl -I` sends, and what uptime monitors and link checkers use
    because it costs nothing. Every route here is declared with @app.get,
    and FastAPI takes that literally, so all 36 of them answered 405 Method
    Not Allowed. Anything watching skymap.sh that way had been reading a
    hard failure on every check.

    Rewriting the method in the scope rather than adding HEAD to 36
    decorators keeps it in one place and covers routes added later. The body
    still gets rendered, which is what makes Content-Length honest, and
    uvicorn's HTTP layer drops it on the wire because it knows the request
    was a HEAD. Nothing downstream branches on the method.

    The rate limiter is the outer of the two (@app.middleware registers
    inward-out, so the one written later wraps the one written first), which
    is the way round we want: a HEAD is throttled on the same bucket as the
    GET it stands in for rather than slipping past on a technicality."""
    if request.method == "HEAD":
        request.scope["method"] = "GET"
    return await call_next(request)


@app.middleware("http")
async def ratelimit(request: Req, call_next):
    path = request.url.path
    if path in RATE_EXEMPT:
        # /complete and /complete/objects are exempt too -- both fire one
        # debounced request per pause in typing, which a normal word can
        # easily reach on its own; both are cheap, cached, and length-
        # capped, so there's nothing here worth throttling per visitor.
        return await call_next(request)
    # The /stats family draws on its own bucket. An open /stats tab polls
    # /stats/live 20 times a minute, and against the chart allowance of 30
    # that would throttle the reader's actual sky requests within seconds.
    stats = path in STATS_PATHS
    rate = STATS_RATE if stats else RATE
    ok, retry = take_token(
        client_ip(request),
        buckets=_stats_buckets if stats else _buckets,
        rate=rate, burst=STATS_BURST if stats else BURST)
    if not ok:
        # THROTTLED is written for someone looping a chart; on a stats page
        # it would suggest watching a place they never asked for.
        if stats:
            return PlainTextResponse(
                f"  Slow down a moment -- {rate} requests a minute for "
                f"/stats.\n  Retry in {retry}s.\n",
                status_code=429,
                headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
        place = (path.strip("/") or "Zurich").split("?")[0]
        return PlainTextResponse(
            THROTTLED.format(rate=rate, retry=retry, place=place),
            status_code=429,
            headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
    resp = await call_next(request)
    resp.headers["X-RateLimit-Limit"] = str(rate)
    return resp


@app.get("/help", response_class=PlainTextResponse)
@app.get("/usage", response_class=PlainTextResponse)
def help_(request: Req):
    _stat["page:help"] += 1
    mode, _colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        controls = api.controls_html(api.EXPLORE)
        # /help, even when reached at /usage: the two are one page under two
        # names, and without this a crawler indexes both and splits the page
        # against itself.
        body = api.PAGE.format(title="skymap.sh: usage", header=api.header_html("help"),
                               canonical=api.canonical_url("/help"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(html.escape(api.HELP)),
                               kbd_urls="{}", shortcuts_hint="")
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


@app.get("/vendor/three/three.module.js")
def three_module_js():
    # Self-hosted instead of pulled from unpkg.com at request time -- one
    # less third party in the request path of every /sphere page load.
    # Pinned to the exact version vendored in, so this never needs to
    # change until a deliberate upgrade replaces the file on disk.
    path = f"{api.sky.BASE}/vendor/three/three.module.js"
    return FileResponse(path, media_type="text/javascript",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/vendor/three/CSS2DRenderer.js")
def css2drenderer_js():
    path = f"{api.sky.BASE}/vendor/three/CSS2DRenderer.js"
    return FileResponse(path, media_type="text/javascript",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/demo", response_class=HTMLResponse)
def demo():
    _stat["page:demo"] += 1
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


@app.get("/complete")
def complete(request: Req):
    """The search bar's place suggestions -- up to 8 canonical city names
    starting with ?q=, most populous first, each with a 1/2/3 size band so
    the dropdown can show a bigger dot for a bigger city. cities.json is
    ~3.9 MB and never goes to the browser; this is the server-side
    substitute. Aggressively cached (completions are static data and should
    never reach origin twice for the same prefix) and prefix-capped, so a
    pathological ?q= can't turn this into a scanning oracle.

    The rows used to be bare strings. The cache here runs a week deep, so
    for a week after a deploy some browsers still get the old shape; the
    dropdown script reads either, and an old row simply gets no dot."""
    q = request.query_params.get("q", "")[:api.COMPLETE_PREFIX_CAP]
    return JSONResponse(api.complete_cities(q, with_pop=True),
                        headers={"Cache-Control": "public, max-age=86400, "
                                                  "s-maxage=604800, immutable"})


@app.get("/complete/objects")
def complete_objects(request: Req):
    """The find field's dropdown data source -- up to 8 catalog objects
    (solar system, named stars, deep sky, constellations) matching ?q=, each
    with the same glyph/colour /catalog shows. Much shorter cache than
    /complete: the Moon's glyph reflects its real phase (see
    _catalog_data()), and a week-long cache would show a stale one -- an
    hour is short enough that nobody notices, long enough this still isn't
    hit on every keystroke across visitors."""
    q = request.query_params.get("q", "")[:api.COMPLETE_OBJECT_CAP]
    return JSONResponse(api.complete_objects(q),
                        headers={"Cache-Control": "public, max-age=3600, s-maxage=3600"})


@app.get("/gif-capacity")
def gif_capacity():
    # Polled by the "Share as a GIF" button so it can grey itself out before
    # a click would just 503 -- a stale read here is harmless (the render
    # endpoint still enforces the real cap itself), this is a UX hint, not
    # the source of truth.
    return JSONResponse(
        {"available": _gif_render_active < GIF_RENDER_MAX_CONCURRENT},
        headers={"Cache-Control": "no-store"})


@app.get("/milkyway.json")
def milkyway_json():
    """The Milky Way density grid, for the 3D view to draw from.

    A static asset rather than part of each place's sphere.json: the sky's
    own structure does not depend on where you are standing, so sending it
    per place would be the same 6 KB again for every visitor and every
    location. Cached hard -- it only changes when build_milkyway.py runs,
    which is never at runtime."""
    return FileResponse(os.path.join(sky.BASE, "milkyway.json"),
                        media_type="application/json",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.api_route("/beacon/golden", methods=["GET", "POST"])
def beacon_golden():
    """Someone switched into golden hour without loading a new page.

    ?golden=1 already counts arrivals -- a shared link, a bookmark, a reload
    -- but the common case is landing on the star sphere and tapping
    `light`, and replaceState deliberately rewrites the address without
    making a request. That toggle was the one thing the counter could not
    see, and it is most of the usage.

    GET and POST both, because navigator.sendBeacon always POSTs and the
    fetch fallback does not -- declared GET-only this would have 405'd, which
    a fire-and-forget beacon is precisely the wrong thing to discover late.

    Deliberately tiny: 204, no body, no cache, and exempt from the rate
    limiter below, since a visitor flicking between the two modes should not
    spend their chart allowance on it."""
    _stat["sphere_golden_on"] += 1
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@app.get("/legend", response_class=PlainTextResponse)
def legend(request: Req):
    _stat["page:legend"] += 1
    mode, colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        controls = api.controls_html(api.EXPLORE)
        body = api.PAGE.format(title="skymap.sh: legend", header=api.header_html("legend"),
                               canonical=api.canonical_url("/legend"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(api.ansi_to_html(api.legend_text(True))),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.legend_text(colour), headers=headers)


@app.get("/catalog", response_class=PlainTextResponse)
def catalog(request: Req):
    _stat["page:catalog"] += 1
    mode, colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        controls = api.controls_html(api.EXPLORE)
        body = api.PAGE.format(title="skymap.sh: catalog", header=api.header_html("catalog"),
                               canonical=api.canonical_url("/catalog"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(api.catalog_html()),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.catalog_text(colour), headers=headers)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    # no-store, like /stats. Without a Cache-Control header Cloudflare applies
    # its own default TTL and cached this: a post-deploy check came back
    # cf-cache-status HIT reporting a TLE age four days out of date while
    # origin was serving 0.0h. A health endpoint that can lie about whether
    # the deploy landed is worse than no health endpoint.
    p = app.state.tle
    total = _hits + _misses
    body = (f"ok stars={len(sky._load('stars.json'))} "
            f"asterisms={len(sky._load('asterisms.json'))} "
            f"deepsky={len(sky._load('deepsky.json'))} "
            f"tle={'%.1fh' % (tle.age(p)/3600) if p else 'none'} "
            f"cache={len(_cache)}/{CACHE_MAX} "
            f"hitrate={100*_hits/total:.1f}% ({_hits}/{total}) "
            f"nv={api.nv_stats()}\n") if total else "ok cache empty\n"
    return PlainTextResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/stats", response_class=PlainTextResponse)
def stats(request: Req):
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_json(), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, colour = _wants(request)
    if mode == "html":
        # ansi_to_html, not html.escape: the world map is the one coloured
        # thing on this page, and escaping would print its escape codes.
        # ansi_to_html escapes everything else on the way through -- which is
        # also why the per-dot map is spliced in after the conversion rather
        # than before it, or its own markup would be escaped too.
        before, _slot, after = stats_text(map_slot=True).partition(MAP_SLOT)
        body = (api.ansi_to_html(before) + _map_html()
                + api.ansi_to_html(after))
        # The two lines /stats/live keeps current. They ride through the
        # escaping as markers and come out as spans the poll can find, so
        # the numbers at the top of the page and under the map stop being a
        # snapshot of whenever the tab was opened.
        body = body.replace(
            HEAD_SLOT, f'<span id="live-head">{html.escape(_headline())}</span>')
        body = body.replace(
            LEGEND_SLOT,
            f'<span id="live-legend">{html.escape(_map_legend())}</span>')
        controls = api.controls_html(api.EXPLORE, extra=api.stats_live_html(
            [api._xterm_hex(n) for n in MAP_RAMP], MAP_SIZES, MAP_DOT,
            MAP_FLASH_DOT, MAP_FONT_PX, MAP_LINE_HEIGHT))
        # w-wide, the same opt-out the chart page uses: the map is about
        # 1,426 pixels across (340 columns at 7px, see MAP_FONT_PX) and the
        # default 1200px column can't hold it, so /stats spent its whole life
        # with a scrollbar under the widest thing on it. Per page, so nothing
        # else moves -- prose pages keep the 1200px measure that makes them
        # readable.
        page = api.PAGE.format(title="skymap.sh: stats", header=api.header_html("stats"),
                               canonical=api.canonical_url("/stats"),
                               controls=controls, wide_class=" w-wide",
                               coming_up_card="",
                               body=api.chart_pre(body), kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(page, headers=headers)
    text = stats_text()
    return PlainTextResponse(text if colour else api.strip_ansi(text),
                             headers=headers)


@app.get("/stats/live", response_class=JSONResponse)
def stats_live(request: Req):
    _stat["page:stats.live"] += 1
    try:
        since = float(request.query_params.get("since", 0))
    except ValueError:
        since = 0.0
    return JSONResponse(stats_live_json(since),
                        headers={"Cache-Control": "no-store"})


def stats_objects_text(n=60):
    """Which objects people actually look up.

    One column, one number. This used to print page and find side by side
    and sum them into a "total" -- but an object page incremented both, so
    the total was roughly double the truth and the two columns were the
    same measurement printed twice. Finding an object means opening its
    page now; there is no second route left to keep a second column for.
    """
    total_obj = sum(_objects.values())
    L = [f"skymap.sh -- objects",
         "",
         f"object pages served   {total_obj:>10,}   {len(_objects):,} distinct",
         ""]
    if not _objects:
        L.append("nothing looked up yet")
        return "\n".join(L) + "\n"
    L.append(f"{'object':<34}{'views':>9}")
    L.append("-" * 43)
    for name, c in _objects.most_common(n):
        L.append(f"{name[:34]:<34}{c:>9,}")
    return "\n".join(L) + "\n"


def stats_objects_json(n=200):
    return dict(
        object_pages=sum(_objects.values()),
        distinct=len(_objects),
        top=[dict(name=nm, views=c) for nm, c in _objects.most_common(n)])


@app.get("/stats/objects", response_class=PlainTextResponse)
def stats_objects(request: Req):
    """Which objects get looked up, by page and by find."""
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_objects_json(), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh: object stats",
                               header=api.header_html("stats/objects"),
                               canonical=api.canonical_url("/stats/objects"),
                               controls=api.controls_html(api.EXPLORE),
                               wide_class="", coming_up_card="",
                               body=api.chart_pre(html.escape(stats_objects_text())),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_objects_text(), headers=headers)


@app.get("/stats/sphere", response_class=PlainTextResponse)
def stats_sphere(request: Req):
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_sphere_json(), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        controls = api.controls_html(api.EXPLORE)
        body = api.PAGE.format(title="skymap.sh: sphere stats",
                               header=api.header_html("stats/sphere"),
                               canonical=api.canonical_url("/stats/sphere"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(html.escape(stats_sphere_text())),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_sphere_text(), headers=headers)


@app.get("/stats/daily", response_class=PlainTextResponse)
def stats_daily(request: Req):
    _stat["page:stats.daily"] += 1
    q = request.query_params
    try:
        days = max(1, min(HOURLY_MAX_QUERY_DAYS, int(q.get("days", CHART_DAYS))))
    except ValueError:
        days = CHART_DAYS
    if q.get("format") == "json":
        return JSONResponse(stats_daily_json(days), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        controls = api.controls_html(api.EXPLORE)
        # No ?days=: every window is the same page over a different span,
        # and each one indexed separately would be the same numbers N times.
        body = api.PAGE.format(title="skymap.sh: daily stats",
                               header=api.header_html("stats/daily"),
                               canonical=api.canonical_url("/stats/daily"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(html.escape(stats_daily_text(days))),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_daily_text(days), headers=headers)


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
        controls = api.controls_html(api.EXPLORE)
        body = api.PAGE.format(title="skymap.sh: stats", header=api.header_html("stats/hourly"),
                               canonical=api.canonical_url("/stats/hourly"),
                               controls=controls, wide_class="",
                               coming_up_card="",
                               body=api.chart_pre(html.escape(stats_hourly_text(days))),
                               kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(stats_hourly_text(days), headers=headers)


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    # /animate and /stats aren't content -- each is either a one-shot,
    # ID-scoped render or a live counter, so indexing them just burns crawl
    # budget a search engine would rather spend on real pages. /sphere is a
    # mobile-only, JS-dependent re-skin of the same place page, one per
    # place -- thin/duplicate content not worth a separate index entry
    # (crawlers are also exempted from ever being redirected there, see
    # CRAWLER_UA, but this is a second line of defence for the URL itself).
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /animate/\n"
        "Disallow: /stats\n"
        "Disallow: /*/sphere\n"
        "Disallow: /*/sphere.json\n"
        # Live aircraft, valid for about fifteen seconds and fetched only by
        # the sphere's own toggle. A crawler indexing it would be indexing a
        # moment, and every fetch is an upstream call against somebody else's
        # free service on behalf of a reader who does not exist.
        "Disallow: /*/planes.json\n"
        # The events *page* is real content and stays indexable; the two
        # feeds are the same facts in machine formats, so crawling them is
        # duplicate content on a budget better spent elsewhere. Readers
        # subscribing on a person's behalf ignore robots.txt anyway.
        "Disallow: /*/events.ics\n"
        "Disallow: /*/events.rss\n"
        "Sitemap: https://skymap.sh/sitemap.xml\n"
    )


# A handful of stable pages plus the same example cities already linked from
# the home page's own "Examples:" row (api.EXPLORE) -- not the 40,803-city
# catalogue, which would be noise no crawler should spend budget on and
# would go stale immediately anyway (every page is a live render).
SITEMAP_PLACES = ("Nairobi", "Tokyo", "London", "New York", "Buenos Aires", "Sydney")
# /eclipse is here and /catalog is not, which is a decision rather than an
# oversight: /eclipse is text about a specific event on a specific date, and
# /catalog is an index of pages that are each in this sitemap already.
SITEMAP_STATIC = ("/", "/demo", "/help", "/legend", "/eclipse")


@app.get("/sitemap.xml", response_class=Response)
def sitemap():
    urls = [f"https://skymap.sh{p}" for p in SITEMAP_STATIC]
    urls += [f"https://skymap.sh/{quote(p)}" for p in SITEMAP_PLACES]
    # The object pages, which are the one part of this service with a stable
    # URL per thing rather than a live render per place. Only the ones worth
    # indexing -- see objects.sitemap_names(), which leaves out the bare
    # catalogue numbers whose pages have nothing specific to say.
    #
    # /{place}/{object} is deliberately absent and deliberately NOT
    # disallowed in robots.txt: it carries rel="canonical" back to the bare
    # object path, and a crawler has to be allowed to fetch a page in order
    # to read that tag. Blocking it would leave the duplicates indexable by
    # URL alone with no canonical ever seen.
    urls += [f"https://skymap.sh/{quote(n)}" for n in objects.sitemap_names()]
    # One page per eclipse still to come. These are the closest thing here to
    # an ordinary web page -- a fixed date, a fixed track across the Earth,
    # text that will read the same next year as it does today -- so they are
    # worth a crawler's time in a way a live sky render is not.
    #
    # Only the ones ahead. Every eclipse back to 2001 is in the table and
    # resolves, but a sitemap is a list of what is worth indexing now, and
    # nobody is searching for the path of the 2006 totality.
    #
    # Through api, which is how the /eclipse route below reaches it too --
    # server.py has never imported eclipse_page directly and this is not the
    # place to start.
    urls += [f"https://skymap.sh/eclipse/{api.eclipse_page.key_of(e)}"
             for e in api.eclipse_page.upcoming(dt.datetime.utcnow(), count=None)]
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


@app.get("/{place}/crossing.json")
def crossing_json(request: Req, place: str):
    """The next sunset or sunrise, drawn, for the page to play at the minute
    it happens.

    Its own route rather than markup inlined into every chart page, because
    the frames are 60-odd KB that almost nobody will see: a page is only
    open across a crossing occasionally, and paying for the drawing on every
    load to cover that would be the whole of the page-weight budget spent on
    a few seconds a day. The page fetches this when the moment is close.

    Always JSON whatever the UA, like sphere.json above and for the same
    reason -- nothing but the page's own script ever asks for it. A terminal
    wanting an animation already has ?animate.
    """
    if api.lookup_place(place) is None:
        return JSONResponse({"error": "unknown_place"}, status_code=404)
    r = _build(request, place)
    data = api.crossing_frames(r)
    if data is None:
        # Not an error. Inside the Arctic circle in June there is no sunset
        # to draw, and a page there should quietly not have this rather than
        # see a failure it cannot do anything about.
        _stat["crossing_none"] += 1
        return JSONResponse({"crossing": None},
                            headers={"Cache-Control": "public, max-age=3600"})
    _stat["crossing"] += 1
    _stat["crossing_rise" if data["rising"] else "crossing_set"] += 1
    # Good until the crossing itself: the drawing is the same for everyone at
    # this place all day, and stale after it happens because the next answer
    # is a different crossing.
    left = (dt.datetime.fromisoformat(data["ends_local"])
            - r.when_local).total_seconds()
    age = max(60, min(6 * 3600, int(left)))
    return JSONResponse(data, headers={
        "Cache-Control": f"public, max-age={age // 4}, s-maxage={age}"})


WELCOME_MAX_AGE = 1800
WELCOME_NONE_MAX_AGE = 3600


def _welcome_ttl(r, cap, until_local=None):
    """Seconds this answer may be cached for, never past the moment it stops
    being true: last contact where there is a greeting, local midnight
    otherwise.

    The answer to "is there an eclipse today" stops being true at midnight,
    so an entry that outlives the day is served as fact after it has become
    false. It goes wrong in both directions and the quiet one is worse:

      - a greeting cached at 23:50 keeps greeting until 00:20, so the day
        after the eclipse opens with yesterday's,
      - a "no eclipse" cached at 23:50 on the eve keeps refusing until
        00:50, so the first fifty minutes of eclipse day are silent -- and
        nobody reports a greeting that did not arrive.

    Same shape as the bug this route just had, half an hour wide instead of
    a day. Clamped here rather than by shortening the cache for everyone,
    because the entry is perfectly good right up to the boundary.
    """
    off = r.place.offset(r.when_utc) if r.place else 0
    local = r.when_utc + dt.timedelta(hours=off)
    midnight = dt.datetime.combine(local.date() + dt.timedelta(days=1),
                                   dt.time.min)
    # A greeting expires at last contact, which on eclipse evening is hours
    # before midnight -- cached to midnight it would outlive the eclipse and
    # be handed out afterwards, which is the thing the greeting must never do.
    edge = min(midnight, until_local) if until_local else midnight
    left = int((edge - local).total_seconds())
    # Never zero: a max-age of 0 on a page every visitor fetches would turn
    # the last second of the day into an origin stampede.
    return max(60, min(cap, left))


@app.get("/{place}/welcome.json")
def welcome_json(request: Req, place: str):
    """The eclipse to greet somebody with today, drawn.

    Separate from the eclipse page's own frames, which are inlined there
    because that page is entirely about the eclipse. This is for every other
    page, where it is a greeting rather than the subject, and it is fetched
    only on the day and only when there is enough eclipse to be worth it.
    """
    if api.lookup_place(place) is None:
        return JSONResponse({"error": "unknown_place"}, status_code=404)
    r = _build(request, place)
    got = api.welcome_eclipse(r.place, r.when_utc)
    if got is None:
        # Not an error: most of the map sees no eclipse most days, and half
        # of Europe sees none of this one.
        _stat["welcome_none"] += 1
        return JSONResponse(
            {"welcome": None},
            headers={"Cache-Control": "public, max-age="
                     f"{_welcome_ttl(r, WELCOME_NONE_MAX_AGE)}"})
    made = api.welcome_frames(r.place, got["key"], got["kind"])
    if made is None:
        _stat["welcome_none"] += 1
        return JSONResponse(
            {"welcome": None},
            headers={"Cache-Control": "public, max-age="
                     f"{_welcome_ttl(r, WELCOME_NONE_MAX_AGE)}"})
    frames, labels = made
    _stat["welcome"] += 1
    _stat[f"welcome:{got['kind']}"] += 1
    return JSONResponse(dict(
        key=got["key"], frames=frames, labels=labels,
        kind=got["kind"], obscuration=round(got["obscuration"], 4),
        starts_local=got["starts"].strftime("%Y-%m-%dT%H:%M:%S"),
        ends_local=got["ends"].strftime("%Y-%m-%dT%H:%M:%S"),
        frame_ms=WELCOME_FRAME_MS, hold_ms=api.CROSSING_HOLD_MS,
    ), headers={"Cache-Control": "public, max-age="
                f"{_welcome_ttl(r, WELCOME_MAX_AGE, got['ends'])}"})


@app.get("/{place}/planes.json")
def planes_json(request: Req, place: str):
    """Aircraft overhead right now, for the sphere's Planes toggle.

    Deliberately outside _cached(). Everything else on this site is a
    prediction and caches for minutes to hours -- the day view holds for
    twenty (DAY_TTL) because the Sun does not do anything surprising in that
    time. Planes do. Their own micro-cache lives in planes.py, keyed on the
    tile rather than on the request, so the sharing that matters (two people
    in the same city, one upstream call) still happens without this response
    ever being served stale.

    A plain def, not async: the upstream fetch and the route lookups block,
    and Starlette runs a sync route in its threadpool, so the event loop --
    and every open ?animate stream on it -- is untouched. An async def here
    would stall all of them for the duration of somebody else's network call.

    Always JSON whatever the UA, like sphere.json and crossing.json above.
    """
    if api.lookup_place(place) is None:
        return JSONResponse({"error": "unknown_place"}, status_code=404)
    r = _build(request, place)
    _stat["planes"] += 1
    # The welcome screen asks for a count before anyone has pressed anything,
    # so without this every landing would look like somebody using the
    # feature. Split, "planes" stays the total and the difference between the
    # two is the only number that answers "did the count make them tap it".
    if request.query_params.get("welcome"):
        _stat["planes_welcome"] += 1
    found, err = planes.overhead(r.place.lat, r.place.lon)
    if err:
        _stat["planes_error"] += 1
    elif not found:
        # Counted apart from an error on purpose. An empty sky over Geneva
        # means a quiet ten minutes; an empty sky over the mid-Atlantic means
        # nobody is feeding the aggregator there, and only the ratio of these
        # two counters over time can tell which places are which.
        _stat["planes_empty"] += 1
    else:
        _stat["planes_shown"] += len(found)
        _stat["planes_routed"] += sum(1 for p in found if p["route"])
    return JSONResponse(
        {"planes": found, "error": err,
         "floor": planes.FLOOR_DEG, "radius_nm": planes.RADIUS_NM,
         # ODbL 1.0 requires attribution wherever the data is shown, so it
         # travels with the data rather than being left to each caller to
         # remember. The page prints it; anything else reading this endpoint
         # is handed the obligation along with the aircraft.
         "attribution": planes.ATTRIBUTION},
        headers={"Cache-Control": "no-store"})


@app.get("/{place}/sphere.json")
def sphere_json(request: Req, place: str):
    # Data for the mobile 3D view -- always JSON regardless of UA, unlike
    # the main route's ?format=json, since this is only ever fetched by
    # SPHERE_PAGE's own script, never something a curl/terminal user asks for.
    if api.lookup_place(place) is None:
        return JSONResponse({"error": "unknown_place"}, status_code=404)
    r = _build(request, place)
    data = api._compose_sphere(r)
    _stat["sphere_json"] += 1
    # How often anyone actually opens the 3D view on a night with a shower
    # running -- the whole reason the radiant marker exists, and the only way
    # to tell whether it's ever seen.
    if data.get("markers"):
        _stat["sphere_radiant"] += 1
    edge = DAY_EDGE if not r.night and api.is_daytime(r) else NIGHT_EDGE
    return JSONResponse(data, headers={
        "Cache-Control": f"public, max-age={edge // 4}, s-maxage={edge}"})


@app.get("/{place}/sphere", response_class=HTMLResponse)
def sphere_page(request: Req, place: str):
    # This route is always HTML (response_class=HTMLResponse), so the same
    # coordinates-to-city bounce the main chart route does always applies
    # here too -- /46.20,6.10/sphere used to show the raw coordinates in the
    # title and the 3D view's own header, where /Geneva/sphere already said
    # "Geneva".
    city = _nearby_city_for_redirect(request, place, "html")
    if city:
        _stat["geo_redirect"] += 1
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/{quote(city)}/sphere{qs}", status_code=302,
                               headers={"Cache-Control": "no-store"})
    p = api.lookup_place(place)
    if p is None:
        return PlainTextResponse("Not found.\n", status_code=404)
    _stat["sphere"] += 1
    _stat[f"sphere_os:{_sphere_os(request)}"] += 1
    # Golden hour on the sphere is a client-side layer, so nothing would
    # otherwise reach the server when someone switches into it -- it shipped
    # measurable only by the fact that nobody could tell. ?golden=1 makes the
    # mode a real address: shareable, bookmarkable, survives a reload, and
    # countable here for free.
    if request.query_params.get("golden"):
        _stat["sphere_golden"] += 1
    _sphere_places[p.name] += 1
    if len(_sphere_places) > _TOP_KEEP:
        for k, _v in _sphere_places.most_common()[_TOP_KEEP:]:
            del _sphere_places[k]
    # Same resolution the mobile home-redirect itself uses (IP geo fallback,
    # no explicit place) -- if it lands on this same place, this genuinely
    # is the visitor's own sky, not somewhere they navigated to.
    home = _build(request, None).place.slug == p.slug
    # robots.txt disallows this path, so nothing should ever read the
    # canonical -- it is here because a page that names itself costs one
    # line, and the disallow is a policy that could be revisited while this
    # would be quietly forgotten.
    body = api.SPHERE_PAGE.format(title=f"skymap.sh: {p.name} in 3D",
                                  canonical=api.canonical_url(f"/{quote(p.name)}/sphere"),
                                  place_slug=p.slug, place_name=html.escape(p.name),
                                  home_suffix=" (my sky)" if home else "")
    return HTMLResponse(body, headers={"Cache-Control": "public, max-age=300"})


# What's coming up changes on the scale of days, not the five minutes a star
# chart does, so these get their own bucket. A day at the edge means a reader
# polling hourly costs one origin render per city per day.
EVENTS_EDGE = 86400


def _events_headers():
    return {"Cache-Control": f"public, max-age={EVENTS_EDGE // 4}, "
                             f"s-maxage={EVENTS_EDGE}"}


# Snapped to a ladder, not merely clamped. Clamping to 7-365 still leaves 359
# distinct values, and the global scan is memoised on (date, days) -- so a
# client walking ?days=30,31,32... got zero cache hits and 75 ms of origin
# work every time, while minting a fresh CDN key on each request too. Seven
# rungs is every window anyone actually wants and bounds both surfaces at
# once, the same bargain ?t= (5-minute grain) and coordinates (0.1°) already
# make. See "Bounding the cache-key surface" in DEPLOY.md.
EVENTS_WINDOWS = (7, 14, 30, 60, 90, 180, 365)


def _events_window(request: Req):
    """?days=, snapped up to the next rung of EVENTS_WINDOWS."""
    raw = request.query_params.get("days")
    if not raw:
        return api.EVENTS_WINDOW_DAYS
    try:
        want = max(7, min(365, int(raw)))
    except ValueError:
        return api.EVENTS_WINDOW_DAYS
    return next(w for w in EVENTS_WINDOWS if w >= want)


@app.get("/events.ics")
def events_ics_here(request: Req):
    """The nav points at /events, so /events.ics is the next thing anyone
    tries -- and it 404'd, which a calendar app reports as a flat "the URL
    is not valid". Same IP fallback as the page.

    A subscription pinned to a place is the better thing to hand out, since
    this one follows whatever IP the calendar app fetches from, but it has
    to work rather than fail."""
    _stat["events_ip"] += 1
    return events_ics(request, None)


@app.get("/events.rss")
def events_rss_here(request: Req):
    _stat["events_ip"] += 1
    return events_rss(request, None)


@app.get("/events", response_class=PlainTextResponse)
def events_here(request: Req):
    """What's coming up over wherever the visitor is.

    The nav is identical on every page so it cannot carry a place, and this
    is how the rest of the site already answers that: a bare `curl skymap.sh`
    locates by IP, so a bare /events does too. Falls back to _build's usual
    default when the CDN sends no coordinates.
    """
    _stat["events_ip"] += 1
    return events_page(request, None)


def _respond_eclipse(request: Req, place: str | None, key: str | None):
    """The eclipse page, for any of the three paths that reach it.

    Registered ahead of /{place:path} on purpose. A 404 here does NOT fall
    through to the next route -- FastAPI matches the first path that fits
    and the handler's status code is the answer -- which is how a separate
    og.png route once killed the object cards and then the place cards.
    """
    kind, colour = _wants(request)
    # The same bounce every other place-aware route does, so an eclipse page
    # reached by IP says "Geneva" rather than "46.20,6.10".
    city = _nearby_city_for_redirect(request, place, kind)
    if city:
        _stat["geo_redirect"] += 1
        tail = f"/eclipse/{key}" if key else "/eclipse"
        return RedirectResponse(f"/{quote(city)}{tail}", status_code=302,
                                headers={"Cache-Control": "no-store"})
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse(UNKNOWN.format(q=place, did=api.suggest(place)),
                                 status_code=404)
    r = _build(request, place)
    if key is None:
        key = api.eclipse_page.key_of(api.eclipse_page.next_computable(r.when_utc))
    composed = api.compose_eclipse(r, key)
    if composed is None:
        return PlainTextResponse(f"no eclipse on {key}\n\n"
                                 f"try skymap.sh/eclipse for the next one\n",
                                 status_code=404)
    res, entry, rows, legend, disc, frames, labels = composed
    _stat["eclipse"] += 1
    _eclipse_keys[key] += 1

    # A day either side of the event the page changes meaning, and the rest
    # of the time it is the same for hours. Short enough to follow the
    # eclipse, long enough that a spike does not reach the origin.
    headers = {"Cache-Control": "public, max-age=600"}
    if kind == "json":
        return JSONResponse(res.data, headers=headers)
    if kind == "html":
        base_url = str(request.base_url).rstrip("/")
        return HTMLResponse(
            api.eclipse_html(r, res.data, key, entry, rows, legend, disc,
                             frames, labels, place=place, base_url=base_url),
            headers=headers)
    return PlainTextResponse(res.text if colour else api.strip_ansi(res.text),
                             headers=headers)


# Rendered through the same pipeline the sky animations use: gif.py takes
# ANSI frame text and hands back bytes, and these frames are already ANSI.
# Registered before the page routes below only for tidiness -- the paths
# differ by a segment, so ordering is not load-bearing here the way it is
# against /{place:path}.
ECLIPSE_GIF_MS = 160


def _respond_eclipse_og(request: Req, place: str | None, key: str):
    """The social card. Registered ahead of the page routes for the same
    reason every other og.png route is: a 404 here does not fall through."""
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    r = _build(request, place) if place is not None else None
    composed = api.compose_eclipse_card(r, key, place)
    if composed is None:
        return PlainTextResponse("", status_code=404)
    kicker, headline, detail, rows = composed
    _stat["og"] += 1
    _stat["og_eclipse"] += 1
    return Response(card.render_eclipse(kicker, headline, detail, rows),
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400, "
                                              "s-maxage=604800"})


@app.get("/eclipse/{key}/og.png")
def eclipse_og(request: Req, key: str):
    return _respond_eclipse_og(request, None, key)


@app.get("/{place}/eclipse/{key}/og.png")
def eclipse_og_at_place(request: Req, place: str, key: str):
    return _respond_eclipse_og(request, place, key)


def _respond_eclipse_gif(request: Req, place: str | None, key: str):
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse("unknown place\n", status_code=404)
    if key not in besselian.ELEMENTS and not lunar.has(key):
        return PlainTextResponse("no elements for that eclipse\n",
                                 status_code=404)
    r = _build(request, place)
    # The same two pictures the page draws: a disc being covered for a solar
    # eclipse, the Moon's whole night for a lunar one.
    if key in besselian.ELEMENTS:
        frames, _labels = api.eclipse_map.disc_frames(key, r.place.lat,
                                                      r.place.lon)
    else:
        frames, _labels = api.eclipse_map.arc_frames(key, r.place.lat,
                                                     r.place.lon)
    if not frames:
        # Nothing to animate where the Sun is down for the whole event.
        return PlainTextResponse("this eclipse is not visible from there\n",
                                 status_code=404)
    _stat["eclipse_gif"] += 1
    # On the drawing's own grid, not the chart's. art.py builds these discs
    # for a cell exactly twice as tall as it is wide; the GIF renderer's
    # default cell is 2.3, which came out as a Sun 15% taller than the one on
    # the page it was exported from.
    data = gif.frames_to_gif(["\n".join(f) for f in frames], ECLIPSE_GIF_MS,
                             gif.cell_h_for(art.CELL))
    return Response(data, media_type="image/gif", headers={
        "Cache-Control": "public, max-age=86400",
        "Content-Disposition":
            f'inline; filename="eclipse-{key}-{quote(r.place.slug)}.gif"'})


@app.get("/eclipse/{key}/animate.gif")
def eclipse_gif(request: Req, key: str):
    return _respond_eclipse_gif(request, None, key)


@app.get("/{place}/eclipse/{key}/animate.gif")
def eclipse_gif_at_place(request: Req, place: str, key: str):
    return _respond_eclipse_gif(request, place, key)


@app.get("/eclipse", response_class=PlainTextResponse)
def eclipse_next(request: Req):
    """The next eclipse this can actually compute, from wherever you are."""
    return _respond_eclipse(request, None, None)


@app.get("/eclipse/{key}", response_class=PlainTextResponse)
def eclipse_dated(request: Req, key: str):
    return _respond_eclipse(request, None, key)


@app.get("/{place}/eclipse", response_class=PlainTextResponse)
def eclipse_at_place(request: Req, place: str):
    return _respond_eclipse(request, place, None)


@app.get("/{place}/eclipse/{key}", response_class=PlainTextResponse)
def eclipse_at_place_dated(request: Req, place: str, key: str):
    return _respond_eclipse(request, place, key)


@app.get("/{place}/events.ics")
def events_ics(request: Req, place: str | None):
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    r = _build(request, place)
    _stat["events.ics"] += 1
    _events_places[r.place.slug] += 1
    body = api.events_ics(r, base_url=str(request.base_url).rstrip("/"),
                          days=_events_window(request))
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers=_events_headers() | {
                        "Content-Disposition":
                            f'inline; filename="skymap-{r.place.slug}.ics"'})


@app.get("/{place}/events.rss")
def events_rss(request: Req, place: str | None):
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse("", status_code=404)
    r = _build(request, place)
    _stat["events.rss"] += 1
    _events_places[r.place.slug] += 1
    body = api.events_rss(r, base_url=str(request.base_url).rstrip("/"),
                          days=_events_window(request))
    return Response(body, media_type="application/rss+xml; charset=utf-8",
                    headers=_events_headers())


@app.get("/{place}/events", response_class=PlainTextResponse)
def events_page(request: Req, place: str | None):
    kind, colour = _wants(request)
    # Same bounce-to-city-name the main chart route does -- this route
    # resolves coordinates through the same _build/resolve_place path, which
    # keeps coordinates as the display name by design, so without this an
    # /events page reached via raw coordinates (or a bare /events landing by
    # IP) showed "46.20,6.10" everywhere the main chart already says
    # "Geneva".
    city = _nearby_city_for_redirect(request, place, kind)
    if city:
        _stat["geo_redirect"] += 1
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/{quote(city)}/events{qs}", status_code=302,
                               headers={"Cache-Control": "no-store"})
    if place is not None and api.lookup_place(place) is None:
        return PlainTextResponse(UNKNOWN.format(q=place, did=api.suggest(place)),
                                 status_code=404)
    r = _build(request, place)
    next_only = bool(request.query_params.get("next"))
    _stat["events"] += 1
    if next_only:
        _stat["param:next"] += 1
    # slug, not name: the no-place fallback is "Zurich" where a real lookup
    # gives "Zürich", which split one city across two rows.
    _events_places[r.place.slug] += 1
    res = api._compose_events(r, next_only=next_only,
                              days=_events_window(request))
    if kind == "json":
        return JSONResponse(res.data, headers=_events_headers())
    if next_only:
        # Deliberately bare: this goes in a shell prompt or a MOTD, so no
        # header, no nav, no footer. Empty body when nothing is coming, so
        # `sky()` in a profile prints nothing rather than a blank box.
        return PlainTextResponse(res.text, headers=_events_headers())
    if kind == "html":
        # events_html(), not ansi_to_html(res.text): the browser version wraps
        # each event row in a link to the chart for that moment, which the
        # ANSI text has no way to carry.
        controls = api.controls_html(api.EXPLORE)
        body = api.PAGE.format(
            # place_words, not place.name: a browser that could not be
            # redirected to a city name still has coordinates here, and
            # "over 46.00,8.90" is not a sentence.
            title=f"skymap.sh: what's coming up over {api.place_words(r.place)}",
            header=api.header_html(f"{r.place.slug}/events"),
            # The place's own name, not whatever was typed to get here, and
            # without ?days= or ?next.
            canonical=api.canonical_url(f"/{quote(r.place.name)}/events"),
            controls=controls, wide_class="",
            coming_up_card="",
            body=api.chart_pre(api.events_html(r, days=_events_window(request))),
            kbd_urls="{}", shortcuts_hint="")
        return HTMLResponse(body, headers=_events_headers())
    return PlainTextResponse(api.strip_ansi(res.text) if not colour else res.text,
                             headers=_events_headers())


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
        # GIF_STEP_MIN, not the stream's: a shared file wants fewer, larger
        # steps. See the constant.
        steps = int(hours * 60 / GIF_STEP_MIN)
        dusk_lead_minutes = ANIMATE_DUSK_LEAD_MIN
        dawn_lag_minutes = ANIMATE_DAWN_LAG_MIN
        frames = []
        for i in range(steps):
            t = base_r.when_utc + dt.timedelta(minutes=GIF_STEP_MIN * i)
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


def _mobile_sphere_redirect(request, place):
    """A phone landing on skymap.sh -- root or any named place -- goes
    straight to that place's 3D sphere instead of the text view, which has
    no real value on a phone screen. Query string carries over (?t=, mainly,
    which the sphere page's own JS already forwards to its data fetch)."""
    if not _is_mobile(request):
        return None
    if place and api.lookup_place(place) is None:
        return None   # let the normal 404 flow handle an unknown place
    r = _build(request, place)
    _stat["mobile_redirect"] += 1
    # Counted as a request from a phone, because that is what it is. This
    # path returns before _tally ever runs, so without it the client mix on
    # /stats would report next to no mobile traffic while phones are plainly
    # arriving -- they just get sent to the sphere before the chart code
    # sees them. The sphere view that follows is a different surface and
    # stays in /stats/sphere; counting it here as well would be the same
    # visitor twice.
    _roll_hour()
    _stat["requests"] += 1
    _hour_stat["requests"] += 1
    _hour_stat["mobile"] += 1
    _stat["ua:mobile"] += 1
    qs = f"?{request.url.query}" if request.url.query else ""
    # The other half of keeping this decision out of a shared cache. The page
    # response is marked private above; without the same treatment here a
    # cached 302 would bounce desktop visitors to the sphere, which is the
    # identical bug pointing the other way.
    # Same #ip mark as the chart redirect above, and the same rule: only the
    # bare-domain landing is the site guessing. A phone that tapped a link to
    # /Tokyo/sphere is being shown Tokyo because somebody asked for Tokyo.
    #
    # This mark usually has one more hop to survive. A phone on the bare
    # domain lands here with coordinates, so the chain is / ->
    # /38.90,1.40/sphere#ip -> /Ibiza/sphere, and the second hop is issued by
    # sphere_page, which cannot see the fragment: fragments are never sent to
    # a server. What carries it across is the user agent -- RFC 7231 7.1.2
    # says a redirect whose Location has no fragment of its own MUST inherit
    # the one from the URL it came from. So the rule for anything adding a
    # redirect on this path is: do not put a fragment on it, and #ip arrives
    # intact. Put one on, and the mark is silently dropped and the welcome
    # screen goes quiet on exactly the visitors it is for.
    mark = "#ip" if not place else ""
    return RedirectResponse(f"/{r.place.slug}/sphere{qs}{mark}", status_code=302,
                            headers={"Cache-Control": "private, no-store"})


@app.get("/")
def root(request: Req):
    q = request.query_params.get("q", "").strip()
    if q:
        # The search bar (header_html/PAGE's script) is a real <form
        # method="get" action="/">, so pressing Enter works with no JS at
        # all -- it just lands here first and gets bounced on to the real
        # URL, one redirect heavier than the scripted version but
        # functionally identical.
        #
        # quote() leaves "/" alone by default, which is the whole point: the
        # bar holds a path, so "Tokyo/Venus" arrives here as one string and
        # has to stay two segments. There is no separate "which place was I
        # on" parameter to recombine -- an earlier version had one, and it
        # let the bar read skymap.sh/venus while the destination was
        # /Tokyo/Venus.
        rest = [f"{k}={v}" for k, v in request.query_params.items() if k != "q"]
        qs = f"?{'&'.join(rest)}" if rest else ""
        return RedirectResponse(f"/{quote(q)}{qs}", status_code=302)
    redirect = _mobile_sphere_redirect(request, None)
    if redirect:
        return redirect
    return _respond(request, None)


def _rendered_obj(text):
    """ANSI to markup, footer dropped -- the same treatment the place page
    gives every piece of its ladder."""
    return api.ansi_to_html(api.strip_footer_line(text))


def _respond_object(request: Req, place: str | None, canonical: str):
    """An object page. Same content negotiation, caching and stats as every
    other view -- the only thing that differs is what gets composed."""
    mode, colour = _wants(request)
    # Coordinates get the nearby city's name, the same as every other view.
    #
    # The chart, sphere and events routes all bounce raw coordinates to the
    # city, and the object pages were added later without it -- so a visitor
    # located by IP saw "46.20,6.10 Wed 5 Aug" in the header of /Saturn while
    # the chart one click away said "Geneva".
    #
    # Two forms, two different answers. Coordinates spelled out in the path
    # redirect, exactly like the siblings do. The bare /Saturn must NOT:
    # that URL is deliberately location-free so it can be shared, and
    # bouncing it to /Geneva/Saturn would rewrite the address bar of anyone
    # who followed a link. It gets the city's own Place instead -- the same
    # end state the redirect reaches, without touching the URL. Swapping the
    # whole Place rather than just relabelling it keeps the coordinates, the
    # timezone and the cache key agreeing with the name; renaming alone
    # would file one cache entry under "Geneva" for every visitor within
    # 55 km of it and serve them each other's sky.
    if mode == "html":
        city = _nearby_city_for_redirect(request, place, mode)
        if city:
            if place:  # explicit coordinates in the path
                _stat["geo_redirect"] += 1
                qs = f"?{request.url.query}" if request.url.query else ""
                return RedirectResponse(
                    f"/{quote(city)}/{quote(canonical)}{qs}", status_code=302,
                    headers={"Cache-Control": "no-store"})
            place = city
    r = _build(request, place)
    r.find = canonical
    res, daytime, hit = _cached_object(r, canonical)
    _tally(r, daytime, hit, mode, res.status, res.data, colour,
           crawler=_crawler_req(request),
           referrer=_referrer_domain(request), mobile=_is_mobile(request),
           obj=canonical)
    # Outside _tally, so it needs the same guard: which objects people look
    # up is a question about readers, and a crawler fetching a card for a
    # shared link is not one.
    if not _crawler_req(request):
        _objects[canonical] += 1
    edge = DAY_EDGE if daytime else NIGHT_EDGE
    headers = {"X-Cache": "HIT" if hit else "MISS"}
    # /{place}/{object} is the same page as /{object} with the location
    # spelled out, and there are 40,803 cities times 1,220 objects of them.
    # Canonical points every one at the bare object path so that a crawler
    # indexes ~1,200 URLs rather than fifty million near-identical ones.
    if place:
        headers["Link"] = f'<https://skymap.sh/{quote(canonical)}>; rel="canonical"'
    # Same rule as the chart route, for the same reason: text and HTML share
    # one url, a shared cache keeps one of them, and the one it kept was the
    # terminal render.
    if mode == "json":
        headers["Cache-Control"] = (f"public, max-age={edge // 4}, "
                                    f"s-maxage={edge}, stale-while-revalidate=600")
    else:
        headers["Cache-Control"] = f"private, max-age={edge // 4}"
    if mode == "json":
        return JSONResponse(res.data, status_code=res.status, headers=headers)
    base_url = str(request.base_url).rstrip("/")
    text = res.text.replace("{base_url}", base_url)
    if mode != "html":
        # The split marker is only meaningful to the browser layout; a
        # terminal reads straight down through both halves.
        text = (text.replace(api.OBJECT_SLOT, "")
                    .replace(api.OBJPROSE_SLOT, "")
                    # Marker and its newline both, so the sentence sits
                    # directly under the timing line it explains rather than
                    # a blank line below it.
                    .replace(api.OBJWHAT_SLOT + "\n", ""))
    if mode == "html":
        # One render per rung of the width ladder, exactly as the place page
        # does it: the browser is handed every width at once and CSS picks
        # the one that fits, so nothing measures anything and nothing
        # reloads. Each rung goes through the same _cached_object(), so a
        # width somebody has already been served at this place in this time
        # bucket is a cache hit rather than repeated work.
        #
        # panel=True is what makes the find view emit the zenith inset and
        # the prose as separate pieces (ZENITH_SLOT / PROSE_SLOT). Object
        # pages never asked for it before, which is why they had no inset --
        # the support was already there.
        rungs, zenith, prose, static = [], "", "", ""
        live_head, live_sub, live_what = "", "", ""
        for _min_ch, cols, panel in api.CHART_LADDER:
            rr = r.sized(cols, panel)
            rr.find = canonical
            rung_res, _daytime, _hit = _cached_object(rr, canonical)
            rung_text = rung_res.text.replace("{base_url}", base_url)
            rung_static, _sep, rung_live = rung_text.partition(api.OBJECT_SLOT)
            # The static half is the same at every width, so it is taken once
            # and the ladder carries only the chart, which is the one thing
            # that genuinely differs between rungs.
            static = static or rung_static
            chart, rung_zenith, rung_prose = api.split_chart_parts(rung_live)
            # "Tonight from Zurich" is a sentence, not part of the drawing.
            # Lifted out of the <pre> so it can be set in the same face and
            # size as the lede opposite it, and so the two columns start on
            # the same line.
            chart_lines = chart.split("\n")
            for _i, _l in enumerate(chart_lines):
                if _l.strip():
                    live_head = live_head or _rendered_obj(_l).strip()
                    chart = "\n".join(chart_lines[_i + 1:]).lstrip("\n")
                    break
            # The object's own prose reads above the chart rather than under
            # it: whether it is worth going outside is the sentence you want
            # before the picture, not after.
            obj_prose_txt, _sep2, chart = chart.partition(api.OBJPROSE_SLOT)
            # And out of that, the one sentence saying what kind of event the
            # picker beside the heading names. Absent on every page with no
            # event, which partition reports as an empty tail.
            obj_prose_txt, _sep3, what_txt = obj_prose_txt.partition(
                api.OBJWHAT_SLOT)
            if obj_prose_txt.strip() and not live_sub:
                live_sub = _rendered_obj(obj_prose_txt).strip()
            if what_txt.strip() and not live_what:
                live_what = _rendered_obj(what_txt).strip()
            chart = chart.lstrip("\n")
            # All three pieces need converting, not just the chart. Passing
            # the inset and the prose through raw put their escape sequences
            # on the page as literal text -- "[38;5;242mzenith 70-90 deg[0m"
            # -- and the unwrapped result overflowed its column.
            if rung_zenith:
                zenith = _rendered_obj(rung_zenith)
            if rung_prose:
                # The find view's summary line ("Saturn . 42 deg up . SSE .
                # mag 1.0") is now said by the heading above the chart, so
                # only that first line is dropped here. Everything after it
                # is the object's own prose and stays.
                _pl = [l for l in rung_prose.split("\n")]
                for _j, _l in enumerate(_pl):
                    if _l.strip():
                        _pl = _pl[_j + 1:]
                        break
                # The margin comes off the text and goes on the box, so a
                # wrapped line starts where the line above it did.
                prose = _rendered_obj(
                    api.strip_prose_indent("\n".join(_pl).strip("\n")))
            # The places the chart offers to travel to become links to this
            # same object seen from there, which is the page anybody reading
            # that sentence wants next.
            rungs.append((cols, panel,
                          api.link_clears_places(
                              _rendered_obj(chart), canonical, rung_res.data,
                              q=(f"?t={r.when_local:%Y-%m-%dT%H:%M}"
                                 if r.when_explicit else ""))))
        return HTMLResponse(api.object_html(r, canonical, text, res.data,
                                            place=place, base_url=base_url,
                                            rungs=rungs, zenith=zenith,
                                            prose=prose, static=static,
                                            live_head=live_head,
                                            live_sub=live_sub,
                                            live_what=live_what,
                                            # private route, so the reader's
                                            # own position may go in here
                                            own=_geo(request)),
                            status_code=res.status, headers=headers)
    return PlainTextResponse(api.strip_ansi(text) if not colour else text,
                             status_code=res.status, headers=headers)


def _cached_object(r, canonical):
    """Same cache and the same buckets as the sky views, with the object
    page marked as its own kind of entry -- r.find is already set to the
    object, so without the marker an object page and a ?find= chart for the
    same target would serve each other's render.

    The object namespace is closed and validated before this is reached, so
    unlike a place name it cannot be used to mint unbounded cache misses."""
    global _hits, _misses
    daytime = api.is_daytime(r)
    q, stamp = _cache_key(r, daytime)
    key = (("object",) + q, stamp)
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        _cache.move_to_end(key)
        _hits += 1
        return hit[1], daytime, True
    _misses += 1
    r.color = True                      # cache the coloured render; strip on the way out
    res = api.compose_object(r, canonical)
    _cache[key] = (now + _cache_ttl(r, daytime), res)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return res, daytime, False


@app.get("/og.png")
def generic_og():
    """The card for everything that is not one object -- the home page and
    every place page. One fixed image: it is the same for all of them, and
    the sky behind it is pinned rather than live (see card.py) because a
    crawler fetching this at noon would otherwise get an empty daylight
    chart as the first thing anyone sees of the site."""
    _stat["og"] += 1
    return Response(card.render_generic(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400, s-maxage=604800"})


@app.get("/{obj}/best.ics")
def object_best_ics(request: Req, obj: str):
    """The object's best night of the year, as one calendar entry.

    Registered ahead of /{place}/{obj}, which would otherwise read
    "best.ics" as an object name."""
    canonical = objects.resolve_name(obj)
    if canonical is None:
        return PlainTextResponse("", status_code=404)
    r = _build(request, None)
    r.find = canonical
    res, _daytime, _hit = _cached_object(r, canonical)
    base_url = str(request.base_url).rstrip("/")
    ics = api.object_best_ics(r, canonical, res.data, base_url=base_url)
    if not ics:
        return PlainTextResponse("", status_code=404)
    _stat["ics"] += 1
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=86400",
                             "Content-Disposition":
                                 f'attachment; filename="{quote(canonical)}.ics"'})


# Fifty thousand years each way, in 41 frames. The pace, and the pauses on
# the two ends, live in motion.py with the drawing they belong to.


@app.get("/{obj}/evolution.gif")
def object_evolution_gif(request: Req, obj: str):
    """An asterism's shape over 100,000 years.

    Registered ahead of /{place}/{obj} for the same reason /{obj}/og.png is:
    otherwise "Big Dipper" is read as a place and "evolution.gif" as an
    object. A 404 here does not fall through to the next route either -- the
    handler's status code is the answer -- which is why this must only ever
    404 for something that genuinely has no shape to show.

    No place in the path, deliberately. Where you stand changes nothing
    about how a constellation deforms, so this is one image for everyone and
    it can be cached hard.
    """
    canonical = objects.resolve_name(obj)
    if canonical is None or not api.motion.asterism(canonical):
        return PlainTextResponse(
            "no shape to show here\n\n"
            "constellation evolution is drawn for asterisms:\n"
            "  curl 'skymap.sh/Big Dipper/evolution.gif'\n", status_code=404)
    frames = api.motion.frames(canonical)
    if not frames:
        return PlainTextResponse("", status_code=404)
    _stat["evolution_gif"] += 1
    # Drawn at twice the size it is shown at. This one sits inline next to
    # the page's own text, which the browser renders at device resolution --
    # a 1x bitmap beside it is stretched by the display and only the picture
    # looks soft. The sky animations are shown on their own and keep 1x.
    data = gif.frames_to_gif(["\n".join(f) for f in frames],
                             api.motion.frame_durations(len(frames)),
                             gif.cell_h_for(art.CELL),
                             scale=api.motion.GIF_SCALE)
    return Response(data, media_type="image/gif",
                    headers={"Cache-Control": "public, max-age=604800, "
                                              "s-maxage=2592000",
                             "Content-Disposition":
                                 f'inline; filename="{quote(canonical)}'
                                 f'-evolution.gif"'})


@app.get("/{obj}/about", response_class=PlainTextResponse)
def object_about(request: Req, obj: str):
    """What an object has been called, and what is known about it.

    Registered ahead of /{place}/{obj} for the same reason /{obj}/og.png and
    /{obj}/evolution.gif are: otherwise "Venus" is read as a place and
    "about" as an object. `about` is in objects.RESERVED so nothing in
    any catalogue can ever claim the second segment back.

    No place in the path and no moment, deliberately. Where you stand does
    not change who found a thing or what it has been called, so this is one
    page for everybody and the only object route that can be cached hard --
    every other one is redrawn as the sky moves.
    """
    canonical = objects.resolve_name(obj)
    if canonical is None:
        return PlainTextResponse(
            f"Don't know '{obj}'.\n\n"
            "about is written for anything with a page:\n"
            "  curl 'skymap.sh/Betelgeuse/about'\n", status_code=404)
    _stat["about"] += 1
    mode, _colour = _wants(request)
    # A week, and a month at the edge. Nothing on this page depends on the
    # reader or the hour, which is what earns a cache time the object pages
    # themselves could never take.
    headers = {"Cache-Control": "public, max-age=604800, s-maxage=2592000"}
    if mode == "html":
        base_url = str(request.base_url).rstrip("/")
        return HTMLResponse(api.about_page(canonical, base_url),
                            headers=headers)
    return PlainTextResponse(api.about_text(canonical), headers=headers)


@app.get("/{obj}/og.png")
def object_og(request: Req, obj: str):
    """The social card for /{obj} or /{place} -- one route, because they are
    one URL shape and a route that answers 404 does not fall through to the
    next one. Two handlers for this meant whichever was registered second
    never ran, so either every object card or every place card was dead.

    An object wins the name, exactly as it does for the pages themselves:
    /Venus/og.png is the planet, not the town in Texas.

    Registered ahead of /{place}/{obj}, which would otherwise read "og.png"
    as an object name.
    """
    canonical = objects.resolve_name(obj)
    if canonical is None:
        # Not an object, so try it as a place. Its card is that place's own
        # sky at ten at night rather than at the moment a crawler asked,
        # which is daylight about half the time.
        if api.lookup_place(obj) is None:
            return PlainTextResponse("", status_code=404)
        p = api.resolve_place(obj)
        _stat["og"] += 1
        return Response(card.render_place(p.name), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400, "
                                                  "s-maxage=86400"})
    r = _build(request, None)
    r.find = canonical
    r.width = OG_WIDTH
    res, _daytime, _hit = _cached_object(r, canonical)
    art = api.compose_chart_only(r)
    facts = dict(res.data)
    _stat["og"] += 1
    edge = DAY_EDGE if api.is_daytime(r) else NIGHT_EDGE
    return Response(card.render(facts, art), media_type="image/png",
                    headers={"Cache-Control": f"public, max-age={edge}, s-maxage={edge}"})


@app.get("/{place}/{obj}")
def place_object(request: Req, place: str, obj: str):
    """`/Zurich/Venus` -- the explicit form, where the location is spelled
    out instead of guessed from the request's IP.

    The slot decides what a segment means, not the name in it. The first
    segment is a place even when it is also an object (`/Venus/Saturn` is
    Saturn seen from Venus, Texas) and the second is an object even when it
    is also a place. That keeps the two forms readable and is why the
    collision rule only ever has to apply to a bare one-segment path.
    """
    canonical = objects.resolve_name(obj)
    if canonical is None or api.lookup_place(place) is None:
        return _respond(request, f"{place}/{obj}")     # falls through to the 404
    return _respond_object(request, place, canonical)


@app.get("/{place:path}")
def place(request: Req, place: str):
    if place.startswith(("favicon", ".well-known")):
        return PlainTextResponse("", status_code=404)
    # Objects win a bare path, every time, whatever the city's population.
    # /Jupiter is the planet, /Heze is a star, and both pages carry a line
    # pointing at the town. See api.object_collision() for why a threshold
    # would be worse than a rule.
    if "/" not in place:
        canonical = objects.resolve_name(place)
        if canonical is not None:
            return _respond_object(request, None, canonical)
    redirect = _mobile_sphere_redirect(request, place)
    if redirect:
        return redirect
    return _respond(request, place)
