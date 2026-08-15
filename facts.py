#!/usr/bin/env python3
"""
The things about an object that never change.

An object page computes where a thing is tonight and how bright it looks.
Neither of those tells you what it is. These do: how big, how far, how many
moons, who found it and when, what we sent to look at it.

Hand-written because there is nowhere permissive to take them from. The
catalogues this repo ships are positional -- RNGC gives coordinates, a type
and sometimes a magnitude; BSC5 gives spectra and parallaxes. Nothing in
either says Herschel found Uranus in 1781 or that Cassini arrived in 2004.
The databases that do carry that are variously CC BY-SA, non-commercial or
unpinned, and this repo bundles no copyleft data (see LICENSES.md).

Which is fine, because these are facts. Saturn's radius and the year Galileo
turned a telescope on Jupiter are measurements and dates, not anyone's
creative work -- the same footing as showers.json and the common-name table
in build_deepsky.py.

Field order within a type is the order they print. Anything absent is simply
not shown, so a partial entry is fine and better than a padded one.

Sources: values cross-checked against NASA planetary fact sheets
(nssdc.gsfc.nasa.gov, US government work, public domain) and the discovery
dates against the standard literature. Where a claim is genuinely disputed,
it is left out rather than stated.
"""
import json
import os

# JPL Horizons, fetched by build_planetinfo.py. Radius, mass, density,
# gravity, escape velocity, rotation, orbital period, axial tilt, albedo and
# temperature for the nine solar-system bodies -- measured values from the
# system sky.py already takes its planetary elements from, rather than
# numbers somebody typed carefully.
_PLANETINFO = None


def _planetinfo():
    global _PLANETINFO
    if _PLANETINFO is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "planetinfo.json")
        try:
            _PLANETINFO = json.load(open(path))
        except (OSError, ValueError):
            _PLANETINFO = {}
    return _PLANETINFO


def _fmt_day(hours):
    return f"{hours / 24:.1f} Earth days" if hours > 48 else \
        f"{int(hours)}h {int(round((hours % 1) * 60)):02d}m"


def _fmt_year(years):
    return f"{years * 365.25:.0f} Earth days" if years < 1 else \
        f"{years:.4g} Earth years"


def measured(name):
    """The JPL numbers for a solar-system body, as printable rows."""
    r = _planetinfo().get(name)
    if not r:
        return []
    out = []
    if "radius_km" in r:
        km = r["radius_km"]
        earths = km / 6371.0
        extra = (f", {earths:.0f} Earths across" if earths >= 2
                 else f", {earths:.2f} of Earth's" if abs(earths - 1) > 0.02 else "")
        out.append(("Radius", f"{km:,.0f} km{extra}"))
    if "mass_kg" in r:
        earths = r["mass_kg"] / 5.9722e24
        out.append(("Mass", f"{earths:,.0f} Earths" if earths >= 2
                    else f"{earths:.3f} of Earth's"))
    if "density" in r:
        out.append(("Density", f"{r['density']:.2f} g/cm3"))
    if "gravity" in r:
        out.append(("Surface gravity", f"{r['gravity']:.1f} m/s2, "
                    f"{r['gravity'] / 9.81:.2f}x Earth's"))
    if "escape_kms" in r:
        out.append(("Escape velocity", f"{r['escape_kms']:.1f} km/s"))
    if "rotation_hours" in r:
        out.append(("Day", _fmt_day(r["rotation_hours"])))
    if "orbit_years" in r:
        out.append(("Year", _fmt_year(r["orbit_years"])))
    if "obliquity_deg" in r:
        out.append(("Axial tilt", f"{r['obliquity_deg']:.1f} degrees"))
    if "albedo" in r:
        out.append(("Albedo", f"{r['albedo']:.2f}, reflects "
                    f"{r['albedo'] * 100:.0f}% of the light hitting it"))
    if "temp_k" in r:
        out.append(("Temperature", f"{r['temp_k']:.0f} K, "
                    f"{r['temp_k'] - 273.15:.0f} C"))
    return out


# Keyed on the canonical name objects.resolve_name() returns.
FACTS = {

    # ------------------------------------------------------- solar system
    "Sun": {
        "first_visit": "Pioneer 5, 1960",
        "missions": [("SOHO", "1996-"), ("Ulysses", "1990-2009"),
                     ("Parker Solar Probe", "2018-"),
                     ("Solar Orbiter", "2020-")],
    },
    "Moon": {
        "first_visit": "Luna 2, 1959",
        "first_photo": "the far side, Luna 3, 1959",
        "missions": [("Luna", "1959-1976"), ("Apollo", "1968-1972"),
                     ("Chang'e", "2007-"), ("Chandrayaan", "2008-")],
    },
    "Mercury": {
        "moons": "none",
        "discovered": "known since antiquity",
        "first_visit": "Mariner 10, 1974",
        "missions": [("Mariner 10", "1974-1975"),
                     ("MESSENGER", "2008-2015"),
                     ("BepiColombo", "2021-")],
    },
    "Venus": {
        "moons": "none",
        "discovered": "known since antiquity",
        "first_visit": "Mariner 2, 1962, the first flyby of any planet",
        "missions": [("Venera", "1961-1984"), ("Mariner", "1962-1974"),
                     ("Magellan", "1990-1994"),
                     ("Venus Express", "2006-2014"),
                     ("Akatsuki", "2015-2024")],
    },
    "Mars": {
        "moons": "2, Phobos and Deimos",
        "discovered": "known since antiquity",
        "first_visit": "Mariner 4, 1965",
        "missions": [("Viking", "1976-1982"), ("Pathfinder", "1997"),
                     ("Spirit", "2004-2010"), ("Opportunity", "2004-2018"),
                     ("Curiosity", "2012-"), ("InSight", "2018-2022"),
                     ("Perseverance", "2021-")],
    },
    "Jupiter": {
        "moons": "95 confirmed",
        "discovered": "known since antiquity; its moons by Galileo, 1610",
        "first_visit": "Pioneer 10, 1973",
        "missions": [("Pioneer 10 and 11", "1973-1974"),
                     ("Voyager 1 and 2", "1979"),
                     ("Galileo", "1995-2003"), ("Juno", "2016-"),
                     ("Europa Clipper", "arrives 2030")],
    },
    "Saturn": {
        "moons": "274 confirmed, more than every other planet together",
        "discovered": "known since antiquity; the rings by Huygens, 1655",
        "first_visit": "Pioneer 11, 1979",
        "missions": [("Pioneer 11", "1979"),
                     ("Voyager 1 and 2", "1980-1981"),
                     ("Cassini-Huygens", "2004-2017")],
    },
    "Uranus": {
        "moons": "28",
        "discovered": "1781, William Herschel, the first planet ever found",
        "first_visit": "Voyager 2, 1986, and nothing since",
        "missions": [("Voyager 2", "1986")],
    },
    "Neptune": {
        "moons": "16",
        "discovered": "1846, Le Verrier and Galle, predicted before it was seen",
        "first_visit": "Voyager 2, 1989, and nothing since",
        "missions": [("Voyager 2", "1989")],
    },

    # ------------------------------------------------------------ deep sky
    "Andromeda Galaxy": {
        "distance_fixed": "2.5 million light years",
        "stars_in": "about a trillion",
        "discovered": "964, Al-Sufi, who called it a little cloud",
        "first_photo": "1888, Isaac Roberts",
    },
    "Orion Nebula": {
        "distance_fixed": "1,344 light years",
        "age": "under a million years, and still forming stars",
        "discovered": "1610, Nicolas-Claude Fabri de Peiresc",
        "first_photo": "1880, Henry Draper, the first photograph of any nebula",
    },
    "Hercules Cluster": {
        "distance_fixed": "22,200 light years",
        "stars_in": "several hundred thousand",
        "age": "11.6 billion years",
        "discovered": "1714, Edmond Halley",
    },
    "Pleiades": {
        "distance_fixed": "444 light years",
        "stars_in": "about 1,000, of which 6 or 7 are naked-eye",
        "age": "100 million years",
        "discovered": "known since antiquity, and named in the Iliad",
    },
    "Whirlpool Galaxy": {
        "distance_fixed": "31 million light years",
        "discovered": "1773, Charles Messier",
        "first_drawn": "1845, Lord Rosse, the first spiral anyone recorded",
        "first_photo": "1889, Isaac Roberts, which showed the spiral was real",
    },
    "Ring Nebula": {
        "distance_fixed": "2,570 light years",
        "age": "roughly 7,000 years since the star shed it",
        "discovered": "1779, Antoine Darquier de Pellepoix",
    },
    "Dumbbell Nebula": {
        "distance_fixed": "1,360 light years",
        "discovered": "1764, Charles Messier, the first planetary nebula found",
    },
    "Lagoon Nebula": {
        "distance_fixed": "4,100 light years",
        "discovered": "1654, Giovanni Battista Hodierna",
    },
    "Sombrero Galaxy": {
        "distance_fixed": "31 million light years",
        "stars_in": "about 2,000 globular clusters orbit it",
        "discovered": "1781, Pierre Mechain",
    },
    "Crab Nebula": {
        "distance_fixed": "6,500 light years",
        "age": "the star exploded in 1054 and was seen in daylight",
        "discovered": "1731, John Bevis",
    },
    "Triangulum Galaxy": {
        "distance_fixed": "2.7 million light years",
        "discovered": "1654, Giovanni Battista Hodierna",
    },
    "Double Cluster": {
        "distance_fixed": "7,500 light years",
        "age": "12.8 million years, young for a cluster",
        "discovered": "recorded by Hipparchus around 130 BC",
    },

    # -------------------------------------------------------------- stars
    "Sirius": {
        "distance_fixed": "8.6 light years, the fifth nearest star system",
        "radius": "1.7 times the Sun",
        "discovered": "its white dwarf companion by Alvan Graham Clark, 1862",
    },
    "Betelgeuse": {
        "radius": "about 700 times the Sun, past the orbit of Mars",
        "first_photo": "1995, Hubble, the first star other than the Sun "
                       "resolved as a disc",
    },
    "Rigel": {
        "distance_fixed": "about 860 light years",
        "radius": "79 times the Sun",
    },
    "Vega": {
        "distance_fixed": "25 light years",
        "radius": "2.4 times the Sun, and visibly flattened by its spin",
        "first_photo": "1850, Harvard, the first star ever photographed",
    },
    "Polaris": {
        "distance_fixed": "about 430 light years",
        "radius": "46 times the Sun",
    },
    "Arcturus": {
        "distance_fixed": "37 light years",
        "radius": "25 times the Sun",
    },
    "Antares": {
        "radius": "about 700 times the Sun",
    },
    "Aldebaran": {
        "distance_fixed": "65 light years",
        "radius": "44 times the Sun",
    },
    "Algol": {
        "distance_fixed": "90 light years",
        "discovered": "its variability explained by John Goodricke, 1783",
    },
    "Capella": {
        "distance_fixed": "43 light years",
        "discovered": "resolved as a double by William Campbell, 1899",
    },
    "Deneb": {
        "radius": "about 200 times the Sun",
    },

    # ----------------------------------------------------- meteor showers
    "Perseids": {
        "parent": "comet Swift-Tuttle, which returns every 133 years",
        "discovered": "linked to the comet by Giovanni Schiaparelli, 1866",
    },
    "Geminids": {
        "parent": "3200 Phaethon, an asteroid rather than a comet",
        "discovered": "first recorded 1862",
    },
    "Quadrantids": {
        "parent": "2003 EH1, probably a dead comet",
        "discovered": "first recorded 1825",
    },
    "Lyrids": {
        "parent": "comet Thatcher, which returns every 415 years",
        "discovered": "recorded in China in 687 BC, the oldest known shower",
    },
}

# The order fields print in, and what each is called on the page. Anything a
# type does not carry is skipped, so one order serves every type.
#
# A value is normally a string. "missions" is a list of (name, when) pairs
# instead, because a run-on line of seven programme names says which ones
# went there and nothing about when, and when is most of what makes the list
# worth reading: Uranus has had one visitor, in 1986, and the shape of the
# row should say so before the words do.
#
# Dates are the years the spacecraft was AT this object, not its launch.
# On a page about Saturn, Cassini's 1997 launch is trivia and its 2004-2017
# tour is the fact. Anything that has not arrived says so.
#
# Split in two, and the split is the whole point of /{object}/about. What a
# thing IS stays on the object page next to where it is tonight; what
# happened TO it -- who found it, who photographed it first, what we have
# sent to look at it -- is a different question asked by a different reader,
# and it now has its own page. Neither list may contain a key from the other:
# a fact printed twice under two headings is the bug this ordering prevents.
FIELD_ORDER = [
    ("radius", "Radius"),
    ("mass", "Mass"),
    ("distance_fixed", "Distance"),
    ("moons", "Moons"),
    ("stars_in", "Stars"),
    ("day", "Day"),
    ("rotation", "Rotation"),
    ("year", "Year"),
    ("age", "Age"),
    ("parent", "Debris from"),
]

# The history half. These four used to sit at the bottom of the object
# page's infobox under a "History" heading, in a box already carrying twenty
# rows, and they are the ones least to do with finding the thing tonight.
HISTORY_ORDER = [
    ("discovered", "Discovered"),
    # Between finding it and photographing it there is a third act, and for
    # the deep sky it is the one that mattered: somebody at an eyepiece
    # drawing what they saw. Rosse's 1845 sketch of the Whirlpool is the
    # first spiral anyone recorded and it sat 44 years ahead of the plate
    # that confirmed it, with nothing on the page between the two dates.
    ("first_drawn", "First drawn"),
    ("first_photo", "First photographed"),
    ("first_visit", "First visited"),
    ("missions", "Missions"),
]


def _rows(name, order):
    rec = FACTS.get(name)
    if not rec:
        return []
    return [(label, rec[key]) for key, label in order if rec.get(key)]


def for_object(name):
    """The hand-written physical facts, in print order. Empty when we have
    nothing, which is the common case: 40-odd objects have entries and the
    other 1,180 fall back to what the catalogues can compute."""
    return _rows(name, FIELD_ORDER)


def history_for(name):
    """The hand-written history, in print order, for /{object}/about.

    Same shape and the same emptiness rule as for_object(). This is what
    gives the history page something to say on day one, before a word of
    etymology is written: the 36 objects in FACTS already carry it."""
    return _rows(name, HISTORY_ORDER)
