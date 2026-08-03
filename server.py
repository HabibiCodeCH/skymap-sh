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

import api, gif, sky, tle

app = FastAPI(title="skymap.sh", docs_url=None, redoc_url=None)

# Clients that want the terminal rendering even though they send Accept: */*
TERMINALS = ("curl", "wget", "httpie", "http/", "powershell", "libcurl", "lwp",
             "python-requests", "fetch")

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
# Separate from _places -- that one only counts the text/ASCII route (via
# _tally(), which sphere_page() never calls), so which cities people want
# to actually look around in would otherwise be invisible.
_sphere_places = Counter()
# Same reasoning as _sphere_places: /events and its two feeds never go through
# _tally(), so which cities people actually subscribe to would be invisible
# without their own tally. A subscription is a much stronger signal than a
# page view -- someone put it in their calendar.
_events_places = Counter()
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
                          sphere_places=dict(_sphere_places),
                          events_places=dict(_events_places),
                          events_teased=dict(_events_teased),
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
                         (_finds, "finds"), (_sphere_places, "sphere_places"),
                         (_events_places, "events_places"),
                         (_events_teased, "events_teased"),
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
    top_ref = _top_hour_referrers(hstat)
    if top_ref:
        row["top_referrers"] = top_ref
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
_BLOCKS = " ▁▂▃▄▅▆▇█"
_SPARK = "▁▂▃▄▅▆▇█"
_ZERO_FILL = ("requests", "hit", "miss", "day", "night")


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


def _ratio(groups, num, den="requests"):
    """Per-group percentage, or None where the group has no denominator --
    an hour with no requests has no hit rate, and that is not zero."""
    out = []
    for g in groups:
        bottom = sum(e[den] for e in g)
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
    share = 100 * sum(e["night"] for e in entries) / total if total else None
    # Same gutter as the chart rows above, so the series stack in one column
    # instead of each starting wherever its label ended.
    L += [""]
    L += _spark_pair("hit%", hit, now_hit, width)
    L += _spark_pair("night", night, share, width)
    L += [""]
    if legend:
        L.append(f"{gut}cache hit % (latest) and night share of the window")
    return L


def _side_by_side(left, right, gap=3):
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
    w = max((len(l) for l in left), default=0)
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
# White for land nobody has asked from, warming through yellow and orange to
# red at the busiest cell. xterm-256, the same palette sky.py's renderer uses,
# so api.ansi_to_html() converts it for the browser with no extra work.
MAP_RAMP = (231, 229, 227, 220, 214, 208, 196)
MAP_DOT = "·"
# Swapped in for the moment a dot flashes. A bullet is a bigger, rounder mark
# than a middle dot, which is the point -- at one character per cell a flash
# on a plain "·" is easy to miss. It only differs in the browser; the text
# map has no animation to swap anything for.
MAP_FLASH_DOT = "•"
_worldmap = None


def _load_worldmap():
    """(rows, width, height, lat_top, lat_bot), or None if the mask is
    missing. Missing is survivable -- the map is the one part of /stats that
    needs a generated file, and the page is more useful without it than
    500-ing over it."""
    global _worldmap
    if _worldmap is None:
        try:
            with open(WORLDMAP_FILE) as f:
                d = json.load(f)
            _worldmap = (d["rows"], d["width"], d["height"],
                         d["lat_top"], d["lat_bot"])
        except (OSError, json.JSONDecodeError, KeyError):
            _worldmap = ()
    return _worldmap or None


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


_heat_cache = (0.0, None, None)
HEAT_TTL = 2.0              # seconds


def _cached_heat(w, h, lat_top, lat_bot):
    """_map_heat walks every 1-degree bin and parses its key, which is a few
    milliseconds once _geo_hits is large. /stats/live is polled every few
    seconds per open tab, so without this every tab pays that separately.
    A couple of seconds stale is invisible on a map of running totals."""
    global _heat_cache
    at, heat, top = _heat_cache
    now = time.time()
    if heat is None or now - at > HEAT_TTL:
        heat = _map_heat(w, h, lat_top, lat_bot)
        top = max(heat.values()) if heat else 0
        _heat_cache = (now, heat, top)
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
    """The map with one addressable span per land dot.

    The text version emits one escape code per run of same-coloured dots,
    which is the right trade there. The browser needs the opposite: a dot
    cannot be flashed on its own unless it is its own element.

    Colour goes on a class rather than an inline style. There are only seven
    possible colours and thousands of dots, so repeating the hex on each one
    costs about 20 bytes a dot for nothing. The classes are defined once in
    stats_live_html() from the same MAP_RAMP."""
    loaded = _load_worldmap()
    if not loaded:
        return ""
    rows, w, h, lat_top, lat_bot = loaded
    shade, heat = _map_shader(w, h, lat_top, lat_bot)
    out = []
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == " " and (r, c) not in heat:
                out.append(" ")
                continue
            out.append(f'<i class="d h{shade(r, c)}" id="d{r}_{c}">'
                       f'{MAP_DOT}</i>')
        out.append("\n")
    return "".join(out).rstrip("\n")


# Stands in for the map while stats_text() builds the page, so the HTML route
# can splice its own per-dot version in. A control character because it must
# never collide with real content, and curl never sees it -- the text path
# renders the real map straight in.
MAP_SLOT = "\x00worldmap\x00"


def _map_block(body=None):
    """Title, map, and a legend naming the busiest place, or nothing at all
    when there is no map file and no traffic to draw on it."""
    if not _load_worldmap():
        return []
    body = _world_map() if body is None else body
    if not body:
        return []
    L = ["WHERE REQUESTS COME FROM", ""] + body + [""]
    ramp = "".join(f"\033[38;5;{n}m{MAP_DOT}\033[0m" for n in MAP_RAMP)
    busiest = ""
    if _places:
        name, c = _places.most_common(1)[0]
        busiest = f"   busiest: {name} ({c:,})"
    L.append(f"quiet {ramp} busy   {len(_geo_hits):,} distinct location(s){busiest}")
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


def _tally(r, daytime, hit, mode, status, data, colour=True, referrer=None):
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
    if r.find:
        _finds[r.find.strip().title()[:40]] += 1
    if referrer:
        _referrers[referrer] += 1
        _hour_stat[f"ref:{referrer}"] += 1
    if len(_places) > _TOP_KEEP:
        for k, _v in _places.most_common()[_TOP_KEEP:]:
            del _places[k]
    if len(_finds) > _TOP_KEEP:
        for k, _v in _finds.most_common()[_TOP_KEEP:]:
            del _finds[k]
    if len(_referrers) > _TOP_KEEP:
        for k, _v in _referrers.most_common()[_TOP_KEEP:]:
            del _referrers[k]
    if len(_geo_hits) > _GEO_KEEP:
        for k, _v in _geo_hits.most_common()[_GEO_KEEP:]:
            del _geo_hits[k]


def stats_text(n=50, map_slot=False):
    """map_slot leaves MAP_SLOT where the map goes instead of drawing it, so
    the HTML route can splice in its per-dot version. The text path never
    passes it and never sees the marker."""
    up = time.time() - STARTED
    req = _stat["requests"] or 1
    L = [f"skymap.sh: {req:,} requests over {up/3600:.1f} h "
         f"({req/max(up,1)*60:.1f}/min)", ""]
    # Charts first. The counters below are a running total with no time axis
    # of their own, so they can't answer "is it growing" -- which is usually
    # the first thing anyone opening this page wants to know.
    # Side by side, hours against days. One column is one hour on the left
    # and one day on the right -- no bucketing, so `cols` is just the window.
    gut = f"{'':{CHART_PAD + 2}}"
    hourly = _hourly_chart(cols=CHART_HOURS, legend=False)
    hourly.append(f"{gut}(hour by hour: /stats/hourly)")
    daily = _daily_chart(cols=CHART_DAYS, width=1, legend=False)
    daily.append(f"{gut}(day by day: /stats/daily)")
    L += _side_by_side(hourly, daily)
    L += ["", f"{gut}sparklines: cache hit % (latest) and night share of "
              f"the window", ""]
    mapped = _map_block([MAP_SLOT] if map_slot else None)
    if mapped:
        L += mapped + ["", ""]
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
    if _stat["sphere"]:
        L.append(f"  {'sphere':12} {_stat['sphere']:>8,}  (see /stats/sphere)")
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
    if _finds:
        L.append("")
        L.append(f"top finds ({len(_finds):,} distinct)")
        for name, c in _finds.most_common(n):
            L.append(f"  {name[:28]:28} {c:>8,}")
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
        sphere=_stat["sphere"],
        events=dict(page=_stat["events"], ics=_stat["events.ics"],
                    rss=_stat["events.rss"], via_nav=_stat["events_ip"],
                    places_distinct=len(_events_places),
                    top_places=dict(_events_places.most_common(n)),
                    teaser_shown=_stat["teaser:shown"],
                    teaser_absent=_stat["teaser:absent"],
                    top_teased=dict(_events_teased.most_common(n))),
        views={k[5:]: v for k, v in _stat.items() if k.startswith("view:")},
        pages={k[5:]: v for k, v in _stat.items() if k.startswith("page:")},
        modes={k[5:]: v for k, v in _stat.items() if k.startswith("mode:")},
        errors={k[7:]: v for k, v in _stat.items() if k.startswith("status:")},
        params={k[6:]: v for k, v in _stat.items() if k.startswith("param:")},
        places_distinct=len(_places), finds_distinct=len(_finds),
        top_places=dict(_places.most_common(n)),
        top_finds=dict(_finds.most_common(n)),
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
        mobile_redirect=_stat["mobile_redirect"],
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
    rows = _hourly_rows(days)
    if not rows:
        return "skymap.sh: hourly stats\n\nno data yet (first hour still in progress)\n"
    # The chart spans the window the caller asked for, zero-filled, so it
    # covers idle hours the table below can only mark as gaps.
    hours = hours or min(days * 24, HOURLY_MAX_QUERY_DAYS * 24)
    L = [f"skymap.sh: hourly stats, last {days}d ({len(rows)} hour(s) on record)", ""]
    L += _chart_block(_dense_hours(rows, hours), _hour_tick, "hour", f"{hours} h",
                      tick_every=_hour_tick_every)
    L += ["",
        f"{'hour (UTC)':17} {'requests':>9} {'hit%':>6} {'day':>6} {'night':>6}  "
        f"{'top referrer':24}"]
    prev = None
    for row in rows:
        if prev:
            gap = _idle_gap(prev, row["hour"])
            if gap:
                L.append(gap)
        prev = row["hour"]
        req = row["requests"] or 1
        hitpct = 100 * row["hit"] / req
        current = "  (in progress)" if row["hour"] == _hour_key and row is rows[-1] else ""
        L.append(f"{row['hour']:17} {row['requests']:>9,} {hitpct:>5.1f}% "
                f"{row['day']:>6,} {row['night']:>6,}  "
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
        f"{'hours':>6}"]
    for e in entries:
        # Every day in the window gets a row, including the empty ones. A
        # daily table is 30 lines at most, so unlike the hourly one there is
        # room to just show the zeroes rather than collapse them. A day with
        # no requests gets `-` for hit%, not 0.0% -- there is no ratio to
        # take, same rule the sparklines use.
        hit = (f"{100 * e['hit'] / e['requests']:.1f}%" if e["requests"] else "-")
        L.append(f"{e['date']:12} {e['requests']:>9,} "
                 f"{hit:>6} {e['day']:>7,} {e['night']:>7,} "
                 f"{e['hours']:>6,}")
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
    after its flash, so the resting colour keeps up as totals grow."""
    now = time.time()
    loaded = _load_worldmap()
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
    return dict(now=now, flash=flash, requests=_stat["requests"],
                distinct=len(_geo_hits))


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
    _tally(r, daytime, hit, mode, res.status, res.data, colour,
           referrer=_referrer_domain(request))
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
        # Shown for everyone -- CSS (.mobile-only, a pointer:coarse media
        # query) decides who actually sees it, since there's no reliable
        # server-side "does this phone have a gyroscope" signal the way
        # TERMINALS lets curl/wget be told apart from a browser.
        sphere_btn = f'<a class="animate-btn mobile-only" href="/{r.place.slug}/sphere">◎ View in 3D</a>'
        body = api.PAGE.format(title=f"skymap.sh: {r.place.name}",
                               header=api.header_html(f"/{r.place.slug}" if place else ""),
                               explore=explore, animate_btn=animate_btn,
                               quadrant_btn=quadrant_btn, sphere_btn=sphere_btn,
                               body=api.ansi_to_html(page_text), extra=extra)
        return HTMLResponse(body, status_code=res.status, headers=headers)
    text = page_text if colour else api.strip_ansi(page_text)
    return PlainTextResponse(text, status_code=res.status, headers=headers)


@app.middleware("http")
async def ratelimit(request: Req, call_next):
    path = request.url.path
    if path in ("/healthz", "/robots.txt"):
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
        body = api.PAGE.format(title="skymap.sh: usage", header=api.header_html("/help"),
                               explore=api.EXPLORE.format(place=""), body=html.escape(api.HELP),
                               extra="", animate_btn="", quadrant_btn="", sphere_btn="")
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
    _stat["page:legend"] += 1
    mode, colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh: legend", header=api.header_html("/legend"),
                               explore=api.EXPLORE.format(place=""),
                               body=api.ansi_to_html(api.legend_text(True)),
                               extra="", animate_btn="", quadrant_btn="", sphere_btn="")
        return HTMLResponse(body, headers=headers)
    return PlainTextResponse(api.legend_text(colour), headers=headers)


@app.get("/catalog", response_class=PlainTextResponse)
def catalog(request: Req):
    _stat["page:catalog"] += 1
    mode, colour = _wants(request)
    headers = {"Cache-Control": "public, max-age=3600"}
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh: catalog", header=api.header_html("/catalog"),
                               explore=api.EXPLORE.format(place=""),
                               body=api.catalog_html(),
                               extra="", animate_btn="", quadrant_btn="",
                               sphere_btn="")
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
        page = api.PAGE.format(title="skymap.sh: stats", header=api.header_html("/stats"),
                               explore=api.EXPLORE, body=body,
                               extra=api.stats_live_html(
                                   [api._xterm_hex(n) for n in MAP_RAMP],
                                   MAP_DOT, MAP_FLASH_DOT),
                               animate_btn="",
                               quadrant_btn="", sphere_btn="")
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


@app.get("/stats/sphere", response_class=PlainTextResponse)
def stats_sphere(request: Req):
    if request.query_params.get("format") == "json":
        return JSONResponse(stats_sphere_json(), headers={"Cache-Control": "no-store"})
    headers = {"Cache-Control": "no-store"}
    mode, _colour = _wants(request)
    if mode == "html":
        body = api.PAGE.format(title="skymap.sh: sphere stats",
                               header=api.header_html("/stats/sphere"),
                               explore=api.EXPLORE, body=html.escape(stats_sphere_text()),
                               extra="", animate_btn="", quadrant_btn="", sphere_btn="")
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
        body = api.PAGE.format(title="skymap.sh: daily stats",
                               header=api.header_html("/stats/daily"),
                               explore=api.EXPLORE, body=html.escape(stats_daily_text(days)),
                               extra="", animate_btn="", quadrant_btn="", sphere_btn="")
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
        body = api.PAGE.format(title="skymap.sh: stats", header=api.header_html("/stats/hourly"),
                               explore=api.EXPLORE, body=html.escape(stats_hourly_text(days)),
                               extra="", animate_btn="", quadrant_btn="", sphere_btn="")
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
    p = api.lookup_place(place)
    if p is None:
        return PlainTextResponse("Not found.\n", status_code=404)
    _stat["sphere"] += 1
    _stat[f"sphere_os:{_sphere_os(request)}"] += 1
    _sphere_places[p.name] += 1
    if len(_sphere_places) > _TOP_KEEP:
        for k, _v in _sphere_places.most_common()[_TOP_KEEP:]:
            del _sphere_places[k]
    # Same resolution the mobile home-redirect itself uses (IP geo fallback,
    # no explicit place) -- if it lands on this same place, this genuinely
    # is the visitor's own sky, not somewhere they navigated to.
    home = _build(request, None).place.slug == p.slug
    body = api.SPHERE_PAGE.format(title=f"skymap.sh: {p.name} in 3D",
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
    kind, colour = _wants(request)
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
        body = api.PAGE.format(
            title=f"skymap.sh: what's coming up over {r.place.name}",
            header=api.header_html(f"/{r.place.slug}/events"),
            explore=api.EXPLORE,
            body=api.events_html(r, days=_events_window(request)),
            extra="", animate_btn="", quadrant_btn="", sphere_btn="")
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
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{r.place.slug}/sphere{qs}", status_code=302)


@app.get("/")
def root(request: Req):
    redirect = _mobile_sphere_redirect(request, None)
    if redirect:
        return redirect
    return _respond(request, None)


@app.get("/{place:path}")
def place(request: Req, place: str):
    if place.startswith(("favicon", ".well-known")):
        return PlainTextResponse("", status_code=404)
    redirect = _mobile_sphere_redirect(request, place)
    if redirect:
        return redirect
    return _respond(request, place)
