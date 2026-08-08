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
| `deepsky.json` | 749 galaxies, clusters, nebulae and planetary nebulae to mag 11 — RA, Dec, magnitude, type, Messier number where one exists | Revised NGC (Sulentic & Tifft, 1973), an ADC-distributed re-verification of Dreyer's 1888 NGC, **read through VizieR** rather than from the raw catalogue file. Object/Messier identification is a published fact; the small hand-authored common-name table in `build_deepsky.py` follows the same reasoning as `asterisms.json` | **Public domain**, same ADC "unrestricted, courtesy citation" provenance as BSC5. Deliberately NGC-only, not OpenNGC — OpenNGC is CC BY-SA 4.0 and also covers the IC catalogue, but bundling it would put this file's licence at odds with the rest of the repo. Coordinates come from VizieR already precessed to J2000, and only the identification, position, type, magnitude and cross-reference columns are read — **not** the catalogue's two prose description fields, so none of Dreyer's or the Palomar observers' writing is reproduced here. A handful of well-known IC-numbered targets (Heart, Soul, Pelican, Cocoon nebulae) aren't in here, and neither is M25, because this is NGC-only. The Pleiades are hand-added: they have no NGC number at all. |
| `build_deepsky.py` | Reads the Revised NGC through VizieR into `deepsky.json` | **Hand-written** here | Yours. |
| `showers.json` | 12 meteor showers — name, solar longitude of maximum, the solar longitudes the activity period runs between, radiant RA/Dec, ZHR | IAU Meteor Data Center shower numbering, values cross-checked against the IMO *Meteor Shower Calendar* Working List of Visual Meteor Showers (Table 5) | **Facts, not a work.** When the Perseids peak and where their radiant sits are measured quantities; no prose, formatting or selection from the IMO document is reproduced. The one-line notes are written here. Courtesy citation to the IMO is customary. |
| `eclipses.json` | 44 eclipses, 2026–2040 — date, time of greatest eclipse, type, the regions the track crosses, and coarse boxes around those regions | NASA/GSFC decade tables (`eclipse.gsfc.nasa.gov`, SEdecade + LEdecade), cross-checked against timeanddate.com | **Public domain.** Eclipse circumstances are US-government work. The boxes and the prose are written here. Deliberately a table rather than a computation: local circumstances need Besselian elements, and the boxes are regions rather than the track itself — see `NOTES.md`. |
| `besselian.json` | Polynomial Besselian elements for all 22 solar eclipses in `eclipses.json` — x, y, d, l1, l2, mu, tan f1/f2, ΔT | NASA/GSFC per-eclipse pages (`eclipse.gsfc.nasa.gov/SEsearch`), fetched and parsed by `build_besselian.py` | **Public domain**, same US-government-work provenance as `eclipses.json`. Measured quantities, no prose. These are what make local circumstances computable at all: they are not an ephemeris but the shadow cone's geometry pre-solved from VSOP87/ELP2000-82, so the Moon never enters our calculation. Validated against NASA's separately published path table — see `test_besselian.py`. |
| `lunar.json` | Published circumstances for all 22 lunar eclipses in `eclipses.json` — greatest eclipse, ΔT, saros, gamma, penumbral and umbral magnitude, the three phase durations, and the sublunar point | NASA/GSFC five-millennium canon (`eclipse.gsfc.nasa.gov/LEcat5`), fetched and parsed by `build_lunar.py` | **Public domain**, same provenance. Numbers from a table, no prose or selection reproduced. Every time and magnitude the lunar pages print is one of these rearranged; nothing is guessed from our own Moon, which is good to about 12 arcmin against a 40-arcmin umbra. |
| `eclipsemap.json` | Land masks for the region each solar eclipse crosses, 96 columns each | Same country polygons as `worldmap.json` (see above), sampled by `build_eclipsemap.py`; the window comes from our own track calculation | Same licence as the polygons. The shading over it is computed here from `besselian.json`, not traced from anyone's published map. |
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

## Added later: the Milky Way outline

| File | Contents | Origin | Licence |
|---|---|---|---|
| `milkyway.json` | Five nested brightness contours, baked to a 720x360 density grid | `mw.json` from d3-celestial (Olaf Frohn), itself derived from the Milky Way Outline Catalog (Jose R. Vieira) | **BSD-3-Clause** — permissive, commercial fine, attribution required. |

The source outline is not committed (`.gitignore`, same as `countries.geo.json`);
`build_milkyway.py` carries the curl line that fetches it and regenerates the
grid. The BSD notice requires the copyright line be reproduced, which is what
the attribution section below is for.

Deliberately not used: Mellinger's panorama is permission-required, and
Stellarium's sky textures are derived from it under negotiated terms rather
than inheriting the GPL, so neither is ours to ship.

## Added later: the object-page data

Four side files that say what an object *is*, for the object pages. Each is
keyed to a catalogue already shipped here and joined at read time. Nothing in
this section modifies `stars.json` or `deepsky.json` — those are what every
chart on the site draws from, and a side file cannot regress a chart.

| File | Contents | Origin | Licence |
|---|---|---|---|
| `starinfo.json` | 2,887 stars — spectral type, distance in light years with its error, double-star separation, variable-star designation | Spectral type and duplicity from the **Yale BSC5** already used for `stars.json`; distance from the **Hipparcos Catalogue** (ESA 1997, I/239), joined on HD number | **Public domain.** BSC5 as above. Hipparcos is ESA, distributed through the ADC/CDS with no copyright notice or usage restriction, same provenance as BSC5 and the RNGC. |
| `constellations.json` | 357 boundary rows covering all 88 constellations | **VI/42**, "Identification of a Constellation From Position" (Roman 1987), a rearrangement of the IAU boundaries Delporte drew in 1930 | **Public domain.** NASA/ADC, authored by Nancy Grace Roman, no copyright notice. The boundaries themselves are the IAU's official delimitation — a published fact, same reasoning as `showers.json`. |
| `variables.json` | 569 variable stars — type, period, epoch, brightness range or amplitude | **General Catalogue of Variable Stars** (Samus+), B/gcvs | **Public domain**, no copyright notice, same ADC/CDS provenance. |
| `dsoinfo.json` | Angular sizes for 51 Messier objects | **Hand-authored** in `build_dsoinfo.py` from published visual dimensions | Yours. How big M31 looks is a measured quantity, not a creative work — the same reasoning `showers.json` and the common-name table in `build_deepsky.py` already rest on. |
| `stars_motion.json` | 130 stars — annual proper motion, radial velocity, distance. Only the stars `asterisms.json` draws with, since a shape is the only thing that can deform | Proper motion and radial velocity from the **Yale BSC5** already shipped as `bsc5.dat`; distance from the **Hipparcos** figures already in `starinfo.json`. Built by `build_starmotion.py` | **Public domain**, both, and both already in this repo — this file introduces no new source. BSC5's own parallax column is ignored here for the reason given below: it puts Alioth at 111 parsecs where Hipparcos puts it at 24.8. |

`stars.json` gains nothing and loses nothing: there is no build script for it in
this repo, so regenerating it would mean reconstructing how it was originally
made and risking a silent change to every chart. `starinfo.json` is a separate
file for exactly that reason.

### Two sources deliberately not used

**NGC 2000.0 (VII/118)** has angular size and constellation for every NGC and
IC object in one file, which is precisely what `dsoinfo.json` wants. Its ReadMe
carries an explicit restriction:

> This catalog is copyrighted by Sky Publishing Corporation … for scientific
> research purposes only. The data should not be used for commercial purposes
> without the explicit permission of Sky Publishing Corporation.

That contradicts the promise at the top of this file, so it is out for the same
reason OpenNGC is.

**SIMBAD** also has the sizes, and covers 584 of the 739 objects in
`deepsky.json` rather than 51. CDS's own terms state their datasets carry
"Open Licence or ODbL or CC-BY" without saying which applies to which dataset.
**ODbL is share-alike**, so that is an unpinned licence with a copyleft option
on it, and this repo promises to bundle no copyleft data. There is also a
difference in kind between quoting individual measured facts and extracting
several hundred rows from a database, which is what database rights cover.
Hand-authoring the well-known sizes avoids both questions. If CDS ever pins
SIMBAD to plain CC BY in writing, this decision is worth revisiting — the
coverage is much better.

### BSC5 parallax is present and unused

BSC5 carries its own parallax column. `build_starinfo.py` ignores it and uses
Hipparcos instead, deliberately. BSC5's parallaxes are pre-Hipparcos
ground-based measurements that fail worst on exactly the bright, distant stars
an object page gets visited for: measured against modern values they put
Antares at 136 light years instead of 550, Spica at 142 instead of 250, and
give Deneb a negative parallax. Only 36% of rows have one at all. Hipparcos
gets those right and ships a standard error with each, so the page can hedge
or stay silent instead of stating a wrong number confidently.

### A note on fetching

`cdsarc.cds.unistra.fr` now sits behind a bot wall that returns a ~4 KB block
page for every data file; the ReadMe files still come through. This breaks the
`curl` line documented in `build_deepsky.py`. The build scripts added here
fetch through VizieR's `asu-tsv` endpoint instead, and BSC5 comes from
Harvard's mirror (`tdc-www.harvard.edu`, http only — their TLS certificate does
not match the hostname).

## Runtime dependency you still need to add

`demo.tle` is synthetic. For real ISS passes, fetch on a daily cron:

    https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE

CelesTrak's data derives from US Space Force public tracking data (public
domain). CelesTrak asks that you cache rather than poll per request — one fetch
a day is both correct and polite, since TLEs are only issued a few times daily.

## Attribution to include anyway

Not legally required, but it costs a footer line and it is the right thing:

> Star positions and spectral types from the Yale Bright Star Catalogue
> (Hoffleit & Warren 1991). Stellar distances from the Hipparcos Catalogue
> (ESA 1997). Constellation boundaries after Delporte (1930), via Roman
> (1987). Variable-star data from the General Catalogue of Variable Stars
> (Samus et al.). Deep-sky objects from the Revised NGC (Sulentic & Tifft,
> 1973), after Dreyer's New General Catalogue (1888). Planetary positions
> from JPL approximate elements; Sun and Moon from Meeus. Satellite elements
> from CelesTrak. City data from SimpleMaps World Cities (CC BY 4.0). Milky
> Way outline from d3-celestial (Olaf Frohn, BSD-3-Clause), after the Milky
> Way Outline Catalog (Jose R. Vieira).

The city data and the Milky Way outline are the two items that legally require
the credit rather than merely deserving it -- CC BY on one, the BSD notice on
the other.
