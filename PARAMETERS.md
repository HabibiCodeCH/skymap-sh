# Every parameter

Command line and URL forms are the same set. Every sample line below was
produced by actually running it.

Times in the examples use `2026-07-30T22:00` because Zurich is in daylight during
the day and you would get the Sun's arc instead of a star chart.

---

## Where

| you type | you get |
|---|---|
| `python3 cli.py` | `Zürich  47.38°N 8.54°E  …  horizon panorama` |
| `python3 cli.py Tokyo` | `Tokyo  35.69°N 139.69°E  …` |
| `python3 cli.py "San Francisco, US"` | `San Francisco  37.76°N 122.44°W  …` |
| `python3 cli.py "Paris, TX"` | `Paris  33.67°N 95.55°W  …` |
| `python3 cli.py "London, Canada"` | `London  42.98°N 81.25°W  …` |
| `python3 cli.py 47.38,8.54` | `47.40,8.50  47.40°N 8.50°E  …` |
| `python3 cli.py nyc` | `New York  40.69°N 73.92°W  …` |

40,803 cities in 155 countries. Bare names give the most populous match, so
`Paris` is France and `San Francisco` is California. After a comma you can put a
country code, a country name, a US state code, or a state name.

Aliases: `nyc  sf  la  hk  cdmx  sp  rio  blr  bombay  peking  saigon`

Coordinates snap to 0.1° (about 11 km). A name it doesn't know gives you a 404
and a list of near misses:

```
$ python3 cli.py atlanta
Atlanta, Georgia, United States   ← resolves fine

$ python3 cli.py wombat
Don't know 'wombat'.
Coordinates work too: 47.38,8.54
```

On the web the place is the path: `curl skymap.sh/Tokyo`, `curl 'skymap.sh/Paris, TX'`,
`curl skymap.sh/47.38,8.54`. With nothing at all, `curl skymap.sh` locates you by IP.

## When

| you type | you get |
|---|---|
| nothing | now, in the local clock of that place |
| `python3 cli.py Zurich 2026-07-30T22:00` | `…  30 Jul 2026 22:00  …` |
| URL: `?t=2026-07-30T22:00` | same |

Accepted range is ±2 years. Anything further away, or unparseable, falls back to
now. Times snap to a 5-minute grain. On the web page, a date/time picker sits
next to the place and find fields for this, no need to hand-type `?t=`.

## Which view

| you type | you get |
|---|---|
| nothing | `horizon panorama, 0-70° + zenith inset` |
| `--disc` / `?view=disc` | `looking up, north at top` |
| `--facing=NW` / `?facing=NW` | `facing NW, 140° wide, true shape` |
| `--facing=S --span=90` / `?facing=S&span=90` | `facing S, 90° wide, true shape` |
| `--night` / `?night=1` | forces the star chart in daylight |
| `--nolines` / `?nolines=1` | stars only, no asterism lines |

`facing` takes any of the 16 compass points (`N NNE NE ENE E …`) or a bearing in
degrees. `span` is clamped to 90–344°; below 90 the shapes would stretch, so it
says `(min)` in the header when it clamps.

## Deep sky

| you type | you get |
|---|---|
| `--dso` / `?dso=1` | galaxies, nebulae and clusters overlaid on the chart |
| nothing | stars and planets only (the default) |

739 objects from the Revised NGC (public domain, unlike most modern NGC/IC
compilations, see `LICENSES.md`), pre-filtered to magnitude 11: faint enough
to hold the entire Messier catalogue plus several hundred more, without the
deep tail of galaxies that need a telescope. NGC-only, so a few well-known
IC-numbered targets (the Heart, Soul, Pelican and Cocoon nebulae) aren't in
there. Four glyphs: `◍` galaxy, `⁂` open/globular cluster, `✳` nebula, `◈`
planetary nebula. About 30 of the well-known ones (Andromeda Galaxy, Orion
Nebula, Whirlpool Galaxy, the Double Cluster…) are labelled by name, the same
way stars and planets are. Only on the horizon and disc views: `--dso` has
no effect on `--find` or the daytime Sun's-path view, since there is nothing
to overlay there.

## Zoom into a quadrant

| you type | you get |
|---|---|
| `--quadrant=A` / `?quadrant=A` | crops the chart to that lettered cell |
| `--quadrant` / `?quadrant` (no letter) | the whole view, with cell letters marked on it |
| nothing | the whole view, no grid -- quadrants are opt-in |

`--quadrant` (with or without a letter) turns on the deep-sky layer
automatically too, as if `--dso` were also given -- one cell of the sky is a
small enough patch that stars alone often leave it looking near-empty, and
the whole point of zooming in is to reveal more.

The horizon view is split into a fixed 4x3 grid (`A B C D`, `E F G H`,
`I J K L`), always 12 cells, whatever the current span. The letters are
computed fresh from `facing`/`span` every time, not stored anywhere, so
`?quadrant=A` means the same patch of sky on every request as long as the rest
of the URL matches. There's no persistent session: to zoom in, rerun the same
command with `--quadrant=` (or `?quadrant=`) added; a crop doesn't draw its own
sub-grid, so there's no further zoom past one cell. An unrecognised letter is
reported and ignored, falling back to the full view. Horizon view only: `disc`
and `--find` ignore it.

While the Sun is up you get `the Sun's path today` whatever else you asked for:
its arc, with rise, transit and set, and the marker on where it is right now.
`facing`, `span` and `view` are ignored during daylight and it says so, because
the Sun's path is a whole-sky view. `--night` / `?night=1` forces the star chart
anyway.

## Find one thing

| you type | you get |
|---|---|
| `--find=Venus` | `finding Venus, 60° window`, crosshair on it, directions in fists |
| `--find=Mars` | `Not visible right now …  Next chance: 03:50` and the chart for then |
| `--find=Mercury` | `Mercury is not visible from Zürich` and why: 19° from the Sun |
| `--find="Big Dipper"` | `finding Big Dipper, 60° window` |
| `--find=Vega` | any of 327 named stars |
| `--find=Moon` | Sun and Moon too |
| `--find=M31` | `finding Andromeda Galaxy, 60° window`, same as any of 739 deep-sky objects |
| `--find=wombat` | `Don't know 'wombat'.` and what it does accept |

Accepts: 7 planets, Sun, Moon, 327 named stars, 28 asterisms, 739 deep-sky
objects (by Messier number, NGC id, or one of 28 common names: Andromeda
Galaxy, Ring Nebula, Double Cluster and the like). `?span=` widens the window
here too.

## What's coming up

| you type | you get |
|---|---|
| `--events` / `/{place}/events` | the next 90 days, in local time |
| `--next` / `?next=1` | one bare line, or nothing |
| `--days=20` / `?days=20` | a different window; clamped to 7–365 |
| `/{place}/events.ics` | an iCalendar feed to subscribe to |
| `/{place}/events.rss` | the same as RSS |
| `--events --json` / `?format=json` | structured, under `upcoming` |

Meteor showers, eclipses, oppositions, greatest elongations, close approaches,
moon phases, equinoxes and solstices. Everything except showers and eclipses is
computed from the same ephemeris the charts use; those two come from
`showers.json` and `eclipses.json`.

```
$ python3 cli.py Zurich 2026-08-11T23:00 --events --days=20

  Zürich  47.38°N 8.54°E  ·  next 20 days  ·  local time

  Wed 12 Aug  ◉ Partial solar eclipse here       8° WNW
              total only along a narrow track through the Arctic, Greenland,
              Iceland and northern Spain; a partial eclipse either side of
              it, which is what you get
  Wed 12 Aug  ○ New Moon
  Thu 13 Aug  ☄ Perseids peak                    66° NE, best 22:10-04:50, up to 100/hr
              the Moon is down, nothing washing it out
  Fri 14 Aug  ✦ Venus at greatest elongation east 11° WSW, 45.5° from the Sun
              highest in the evening sky after sunset
  Sun 16 Aug  ● Moon and Venus 1.9° apart        10° WSW
  Thu 20 Aug  ◑ First quarter Moon
  Fri 28 Aug  ● Full Moon
  Fri 28 Aug  ◐ Partial lunar eclipse            5° WSW
              visible from the Americas, Europe and Africa
```

Whether you can actually see a thing is worked out for your latitude, so the
list is not the same everywhere. Events that happen but aren't visible from
where you asked are listed at the bottom with the reason, rather than dropped:

```
$ python3 cli.py Sydney 2026-08-11T23:00 --events --days=10

  Happening, but not from here:
  Tue 11 Aug  Moon and Mercury 2.0° apart: never above the horizon in a dark
              enough sky that night
  Thu 13 Aug  Total solar eclipse: the Sun is below the horizon here, it's
              night
  Thu 13 Aug  Perseids peak: never above the horizon in a dark enough sky
              that night
```

A solar eclipse never tells one place it will see totality. Totality is a band
a hundred-odd km wide, and nothing computable here separates a 90% partial from
being on the centre line — the difference is about 0.07° of Sun-Moon separation
and this ephemeris carries four times that. So `eclipses.json` records the
regions NASA lists for each track: outside them you get "Partial solar eclipse
here", inside them "Total solar eclipse: track nearby" and a pointer to a
detailed map. Zürich reads partial, Reykjavík reads track nearby.

The table covers every total, annular and hybrid solar eclipse and every total
and partial lunar eclipse from 2026 to 2040, from NASA's decade tables.
Penumbral lunar eclipses are left out because nobody can tell one from an
ordinary full Moon.

`--next` is one line and nothing else, for a shell prompt or a MOTD. It prints
nothing at all when there's nothing close, so it composes into scripts:

```
$ python3 cli.py Zurich 2026-08-11T23:00 --next
Perseids peak tomorrow night, up to 100 an hour, radiant 66° NE, the Moon is down, nothing washing it out.

$ sky() { curl -s "skymap.sh/${SKYMAP_PLACE:-Zurich}/events?next=1"; }
```

The same line appears under the chart itself when something is close, so a
plain `curl skymap.sh/Zurich` mentions the Perseids without being asked. It is
absent most nights on purpose: a shower is worth flagging a fortnight out, the
Moon passing Jupiter only the night before, and moon phases never, since there
is one every 7.4 days and a line that is always there stops being read.

On a shower night the sphere marks the radiant: a ring around empty sky (a
radiant is a direction, not an object, so there is nothing there to draw) with
four ticks pointing the way meteors streak, the shower's name, and a line
across the bottom with the window, the rate and what the Moon is doing. It sits
at the radiant's altitude at the *best* moment that night rather than at the
moment you loaded the page, because the radiant climbs through the night and
where to look when you actually go out is the useful answer. Absent on all but
a handful of nights a year, and absent anywhere the radiant never rises.

JSON keys, events view: `place lat lon tz_offset when_utc window_days upcoming`,
where each entry in `upcoming` has `kind name headline id when_utc when_local
visible` plus whatever that kind carries — `alt compass window_local zhr
moon_illum moon_up moon_verdict sep_deg bodies mag regions reason`.

`id` is stable and day-grained (`shower-perseids-20260813`). It is the ICS UID
and the RSS GUID, so a reader never re-flags an item it has already shown.

## Output format

| you type | you get |
|---|---|
| nothing (terminal) | colour |
| `--plain` / `?plain=1` | no colour codes |
| `--json` / `?format=json` | structured data, same facts |
| browser | the same text in a page |
| `-H 'Accept: text/plain'` | plain text |

The ISS is marked automatically whenever a real pass is up, no flag needed.
That needs `python3 tle.py` to have run first, to fetch the current orbit from
CelesTrak. Without a fetched element set the ISS is quietly left off.

`?w=100` renders at that many columns instead of the default, scaling both
dimensions together so the aspect ratio stays honest. Clamped to 60–220. Fit
any terminal automatically by adding this to your shell profile:

    skymap() { curl "skymap.sh/${1:-}?w=$(tput cols)"; }

JSON keys, night view: `place lat lon tz_offset when_utc when_local view facing
span sun_alt moon bodies brightest asterisms stars_up iss_pass prose`

JSON keys, day view: `view daytime sun events max_alt polar_day polar_night
first_stars dark_from visible_tonight moon prose`

JSON keys, find view: `target kind visible reason alt az compass mag
next_visible shown_utc guide`, plus `solar_elongation` when there is no window
at all.

## Web only

| URL | you get |
|---|---|
| `/help` (or `/usage`) | this list, short form |
| `/legend` | every character and colour a chart can draw, explained |
| `/demo` | six-plus real renders, side by side |
| `/healthz` | `ok stars=2887 asterisms=28 deepsky=739 tle=… cache=… hitrate=…` |
| `/stats` | what people ask for: top cities, top finds, top referrers, views, cache hit rate |
| `/stats?format=json` | the same, structured |
| `/{place}/sphere` | mobile-only 3D sky sphere, look around by tilting the phone |
| `/{place}/events` | what's coming up over that place, next 90 days |
| `/{place}/events.ics` | iCalendar feed of the same |
| `/{place}/events.rss` | RSS feed of the same |
| `/{place}/sphere.json` | the same sky as stars/asterisms/deep-sky/bodies with resolved alt/az, for the 3D view |
| `/robots.txt` | allow all |
| unknown place | 404 with near misses |
| more than 30 requests a minute | 429 explaining the sky updates every 5 minutes |

## Combinations worth trying

```
python3 cli.py Zurich 2026-07-30T22:00 --facing=NNW --span=90
python3 cli.py Sydney 2026-07-30T21:00
python3 cli.py Reykjavik 2026-06-21T23:00          never gets dark
python3 cli.py "Tromso, NO" 2026-12-21T12:00       polar night
python3 cli.py Nairobi 2026-07-30T21:00 --disc     equatorial sky
python3 cli.py Zurich 2026-08-12T23:00             Perseid peak, no Moon
python3 cli.py Zurich --find=Saturn
python3 cli.py Singapore --json
```
