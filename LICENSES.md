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
| `deepsky.json` | 739 galaxies, clusters, nebulae and planetary nebulae to mag 11 — RA, Dec, magnitude, type, Messier number where one exists | Revised NGC (Sulentic & Tifft, 1973), an ADC-distributed re-verification of Dreyer's 1888 NGC. Object/Messier identification is a published fact; the small hand-authored common-name table in `build_deepsky.py` follows the same reasoning as `asterisms.json` | **Public domain**, same ADC "unrestricted, courtesy citation" provenance as BSC5. Deliberately NGC-only, not OpenNGC — OpenNGC is CC BY-SA 4.0 and also covers the IC catalogue, but bundling it would put this file's licence at odds with the rest of the repo. Coordinates precessed here from B1975 to J2000; a handful of well-known IC-numbered targets (Heart, Soul, Pelican, Cocoon nebulae) aren't in here as a result. |
| `build_deepsky.py` | Parses the Revised NGC fixed-width catalogue into `deepsky.json` | **Hand-written** here | Yours. |
| `showers.json` | 12 meteor showers — name, solar longitude of maximum, radiant RA/Dec, ZHR | IAU Meteor Data Center shower numbering, values cross-checked against the IMO *Meteor Shower Calendar* Working List of Visual Meteor Showers (Table 5) | **Facts, not a work.** When the Perseids peak and where their radiant sits are measured quantities; no prose, formatting or selection from the IMO document is reproduced. The one-line notes are written here. Courtesy citation to the IMO is customary. |
| `eclipses.json` | 10 eclipses, 2026–2028 — date, type, and the region totality/annularity crosses | Dates and types are the published circumstances (NASA/GSFC eclipse canon, cross-checked against timeanddate.com) | **Public domain.** Eclipse circumstances are US-government work. The region strings are written here. Deliberately a table rather than a computation: local circumstances need Besselian elements, see `NOTES.md`. |
| `events.py` | Moon phases, equinoxes/solstices, oppositions, elongations, conjunctions | Computed from `sky.py`'s own ephemeris | Yours. |

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
> Deep-sky objects from the Revised NGC (Sulentic & Tifft, 1973), after
> Dreyer's New General Catalogue (1888). Planetary positions from JPL
> approximate elements; Sun and Moon from Meeus. Satellite elements from
> CelesTrak. City data from SimpleMaps World Cities (CC BY 4.0).

The city data is the one item that legally requires the credit rather than
merely deserving it.
