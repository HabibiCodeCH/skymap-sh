# skymap.sh

The sky above you, as text: CLI, web, Bluesky bot, and now mobile too.

```
curl skymap.sh                      located by IP
curl skymap.sh/Zurich               any of 40,803 cities
curl 'skymap.sh/San Francisco, US'  country code, country, or US state
curl skymap.sh/47.38,8.54           any coordinates
curl 'skymap.sh/Zurich?find=Venus'  crosshair one object, told in fists
curl 'skymap.sh/Zurich?format=json' the same facts, structured
curl 'skymap.sh/Zurich?animate'     24h sky, streamed live, frame by frame
```

Stars to magnitude 4–5, asterisms people actually recognise, planets, the Moon
with its phase, and the next visible ISS pass. No API key, no signup, no data
files to download.

`?dso=1` overlays 739 galaxies, nebulae and clusters (Revised NGC, public
domain). `?quadrant=A` crops the chart to one lettered cell instead of the
whole sky, letters are marked on the chart to pick from.

On a phone, an additive 3D sky sphere is one tap away: look around by
moving the phone, at `/{place}/sphere`. On the handful of nights a year a
meteor shower is running, it marks the radiant so you can physically turn and
face it.

`/{place}/events` is what's coming up over that place in the next 90 days:
meteor showers with the radiant's altitude and whether the Moon is in the way,
eclipses, oppositions, close approaches, phases and equinoxes. Subscribe with
`/events.ics` (calendar) or `/events.rss` (reader), or put the one-line form in
your shell:

```sh
sky() { curl -s "skymap.sh/${SKYMAP_PLACE:-Zurich}/events?next=1"; }
```

When something is close, one line about it also appears under the chart itself.

## Run it

```
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python tle.py                 # fetch the ISS element set
venv/bin/uvicorn server:app --port 8000
```

Command line, same engine:

```
python3 cli.py Sydney --facing=S --span=90
python3 cli.py Zurich --find="Big Dipper"
python3 cli.py Zurich 2026-08-12T23:00 --json    # marks a real ISS pass automatically
```

## Layout

| file | what it is |
|---|---|
| `sky.py` | the engine: ephemerides, projections, renderers |
| `api.py` | request → assembled text + structured data. One implementation for CLI and HTTP |
| `server.py` | FastAPI: content negotiation, geo fallback, rate limit |
| `gif.py` | renders ANSI frames to the shareable GIF/PNG (Pillow + bundled JetBrains Mono) |
| `cli.py` | terminal entry point |
| `tle.py` | fetches and validates the ISS element set; run from cron |
| `build_asterisms.py` | regenerates `asterisms.json` from Bayer designations |
| `stars.json` | Yale BSC5, 2,887 stars to mag 5.5 |
| `asterisms.json` | 28 hand-authored shapes |
| `deepsky.json` | 739 galaxies/nebulae/clusters to mag 11, from the Revised NGC (public domain) |
| `build_deepsky.py` | regenerates the above from the Revised NGC catalogue (build time only) |
| `cities.json` | 40,803 cities with timezone, country, state, population |
| `build_cities.py` | regenerates the above (needs `tzfpy`, build time only) |
| `events.py` | what's coming up: phases, seasons, oppositions, elongations, conjunctions, computed from the same ephemeris |
| `showers.json` | 12 meteor showers, keyed by solar longitude so peaks land right in any year |
| `eclipses.json` | 10 eclipses 2026-2028; a table, not a computation (see `NOTES.md`) |

`PARAMETERS.md` lists every option with real sample output.

`NOTES.md` records why things are the way they are. `LICENSES.md` records where
the data came from: everything shipped is public domain or written here.

## One URL, four consumers

Negotiated on `User-Agent` and `Accept`:

| client | gets |
|---|---|
| `curl`, `wget`, httpie | ANSI colour |
| `Accept: text/plain` | text, no escape codes |
| a browser | the same output in a page |
| `?format=json` | structured data |

## Animate, then share it

`?animate` streams the next 24h of sky, one frame every 15 simulated
minutes, live in the terminal: stars and planets fade in and out with real
twilight, no hard cut at sunset. When the stream finishes it prints a
shareable GIF link, already rendered and cached:

```
curl 'skymap.sh/Tokyo?animate'
...
Want a shareable GIF of this? Run:
  curl 'skymap.sh/Tokyo/animate.gif?t=2026-08-12T18:00'
```

Every place also has a static PNG of its current chart at `/<place>/horizon.png`,
and the web page (a browser visiting `skymap.sh/<place>`) has an "animate"
button that plays the same live sequence in the page before its own GIF
link appears next to it.

## Deploying

`Caddyfile`, `sky.service` and `sky.cron` are a working origin: Caddy terminates
TLS and proxies to uvicorn under systemd, cron refreshes the TLE every six hours.
Put Cloudflare in front: it absorbs a launch burst and supplies the
`CF-IPLatitude` / `CF-IPLongitude` headers that make a bare `curl skymap.sh` know
where you are.

Responses carry `s-maxage` matching the render bucket (300 s at night, 900 s by
day). Get that header right and almost nothing reaches origin.

### Load

A cold render is ~12 ms; a cache hit is a dict lookup at ~2 ms end-to-end, or
about 440 req/s single-threaded. Requests are bucketed in time (5 minutes at
night, 15 by day), so 30 clients asking within a bucket produce one render and
29 hits, measured 98.8% hit rate under a repeat load. Origin sees 12 renders
per city per hour at night, 4 by day.

While the Sun is up there is no star chart worth drawing, so the default view
becomes the Sun's arc across today with rise, transit and set marked. It is a
cheaper render and a longer bucket. `?night=1` overrides.

Per-IP token bucket in `server.py`: 30 requests/minute sustained, burst 45.
Someone running `watch -n 1 curl skymap.sh` is 86,400 requests a day; they get a
429 that explains the sky is recomputed every five minutes and suggests
`watch -n 300`. The buckets (and the `/stats` counters) are per process, and
Caddy's proxy has enough source-IP stickiness that different visitors can land
on different workers and see different, non-overlapping numbers, so
`sky.service` runs a single worker rather than multiplying either one.

Cache-key surfaces are bounded in code so a client cannot generate misses for
free: `?t=` snaps to a 5-minute grain and clamps to ±2 years, coordinates snap to
0.1° (~11 km) at parse time, and the 40-day `find` scan is memoised (68 ms cold,
0.08 ms warm). See `DEPLOY.md` for the edge rules that finish the job, including
the Cloudflare cache-key rule that stops unknown query parameters busting the
CDN.

## Credits

Star positions from the Yale Bright Star Catalogue (Hoffleit & Warren 1991).
Planetary positions from JPL approximate elements; Sun and Moon from Meeus.
Satellite elements from CelesTrak.
