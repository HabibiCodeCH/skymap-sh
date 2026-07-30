# Data provenance and licensing

This file covers the *data* — see `LICENSE` in the repo root for the code
itself (MIT).

Everything shipped in this repo is either public domain, hand-authored here, or
US-government work. **No copyleft data is bundled.** You can release this under
any licence you like, including a closed commercial service.

## What is in the repo

| File | Contents | Origin | Licence |
|---|---|---|---|
| `stars.json` | 2,887 stars to mag 5.5 — RA, Dec, V mag, B−V, Bayer letter, constellation, proper name | Yale Bright Star Catalogue, 5th ed. (BSC5), Hoffleit & Warren 1991 | **Public domain.** Distributed by the Astronomical Data Center (NASA/GSFC) and Harvard CfA as an unrestricted catalogue. Courtesy citation is customary, not required. |
| `asterisms.json` | 28 asterism line lists | **Hand-authored** in `build_asterisms.py` as ordered Bayer designations ("eta UMa", "zeta UMa", …), resolved against BSC5 | Yours. Which stars form the Plough is a published astronomical fact, not a creative work, and no third-party line file was consulted. |
| `demo.tle` | Synthetic ISS-like orbit | Generated here | Yours. Replace with CelesTrak at runtime. |
| `sky.py` | All code, including the Meeus solar/lunar series and JPL's approximate planetary elements | Written here; the algorithms are published formulae | Yours. Formulae are not copyrightable; the specific expression here is original. |

## What was removed, and why

Two dependencies in the earlier prototype would have blocked a closed release:

**HYG Database v4.1 — CC BY-SA 4.0.** Share-alike attaches to the database, so
publishing a service built on it would oblige you to release the derived star
file under the same terms. Replaced by BSC5, which is unrestricted. BSC5 goes
to mag ~6.5 across 9,096 stars — several times what a naked-eye chart needs.

**Stellarium `skycultures/modern/index.json` — GPL.** This was the real blocker:
the constellation and asterism line data was being shipped essentially verbatim.
Replaced by `build_asterisms.py`, which encodes each shape as a list of Bayer
designations written from published star charts and resolves them against BSC5
at build time. Roughly 60 lines of data. The GPL dependency is gone entirely.

## Added later: the city list

| File | Contents | Origin | Licence |
|---|---|---|---|
| `cities.json` | 40,803 cities — name, lat/lon, IANA timezone, country, state, population | SimpleMaps World Cities basic database, via the condwanaland/worldcities mirror | **CC BY 4.0** — attribution only, no share-alike. Credit it and you are done. |

Timezones were resolved at build time with `tzfpy`, so the service needs no
timezone library at runtime. `build_cities.py` regenerates the file; that is the
only place tzfpy is used, and it is not in `requirements.txt` for that reason.

## Runtime dependency you still need to add

`demo.tle` is synthetic. For real ISS passes, fetch on a daily cron:

    https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE

CelesTrak's data derives from US Space Force public tracking data (public
domain). CelesTrak asks that you cache rather than poll per request — one fetch
a day is both correct and polite, since TLEs are only issued a few times daily.

## Attribution to include anyway

Not legally required, but it costs a footer line and it is the right thing:

> Star positions from the Yale Bright Star Catalogue (Hoffleit & Warren 1991).
> Planetary positions from JPL approximate elements; Sun and Moon from Meeus.
> Satellite elements from CelesTrak. City data from SimpleMaps World Cities
> (CC BY 4.0).

The city data is the one item that legally requires the credit rather than
merely deserving it.
