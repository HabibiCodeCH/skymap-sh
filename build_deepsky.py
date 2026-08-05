#!/usr/bin/env python3
"""
Build deepsky.json: galaxies, nebulae and star clusters, to go alongside
stars.json on the chart.

Source: the Revised NGC (Sulentic & Tifft 1973), an updated re-verification
of Dreyer's original New General Catalogue (1888), read through VizieR.
Deliberately NGC-only rather than OpenNGC (which also covers the IC
catalogue but is CC-BY-SA and would have put deepsky.json's licence at odds
with the rest of this repo; see LICENSES.md). That trade means a few
well-known IC-numbered targets (the Heart, Soul, Pelican and Cocoon nebulae
among them) aren't in here.

    curl -o vii1b.tsv 'https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VII/1B/catalog&-out.max=unlimited&-out=NGC,m_NGC,Type,_RAJ2000,_DEJ2000,Mag,Notes'
    python3 build_deepsky.py

Read through VizieR rather than from the raw catalogue file, for three
reasons. The raw path (cdsarc.cds.unistra.fr/ftp/VII/1B/catalog.dat) now
returns a bot-wall page instead of data, so the command that used to be
documented here no longer works. VizieR serves only the columns below --
identification, position, type, magnitude and cross-references -- and not
the catalogue's two prose description fields, so nothing here reproduces
anyone's writing. And it supplies coordinates already precessed to J2000,
which removed the single worst bug this file ever had.

That bug is worth recording. This script used to precess the catalogue's
B1975 positions to J2000 itself, with `yrs = -25.0` -- the wrong sign, since
B1975 to J2000 is twenty-five years forward, not back. It landed every
object near B1950 instead, roughly fifty years of precession out, and every
deep-sky object on every chart the site has ever drawn sat 24 to 39
arcminutes from where it belonged. About a Moon-width, consistently, for
739 objects. Taking J2000 straight from VizieR deletes the arithmetic and
the mistake together.

Kept types: galaxies, open/globular clusters, nebulae and cluster+nebula
pairs. Dropped: non-existent entries, unverified southern objects, and
anything without a recorded magnitude. Magnitude cutoff is 11.0 -- faint
enough to hold the entire Messier catalogue plus several hundred more NGC
objects, without the deep tail of galaxies that are invisible outside a
telescope.
"""
import json, re, sys

SRC, OUT = "vii1b.tsv", "deepsky.json"
MAG_LIMIT = 11.0

# RNGC type code -> our category glyph key (Note 1 in the ReadMe). A second
# digit means "in the LMC" (8) or "in the SMC" (9); the object's real type is
# always the first digit, so combination codes (e.g. "28") are handled by
# just reading that one.
CATEGORY = {"1": "clu", "2": "clu", "3": "neb", "4": "pln", "5": "gal", "6": "clu"}

# Traditional names are a published astronomical fact, not a creative work --
# same reasoning build_asterisms.py uses for "which stars form the Plough".
# Hand-picked, not exhaustive: the well-known handful, keyed on NGC number.
COMMON_NAMES = {
    224: "Andromeda Galaxy", 598: "Triangulum Galaxy", 1499: "California Nebula",
    1952: "Crab Nebula", 1976: "Orion Nebula", 2070: "Tarantula Nebula",
    2237: "Rosette Nebula", 2264: "Christmas Tree Cluster", 2392: "Eskimo Nebula",
    3242: "Ghost of Jupiter", 3372: "Carina Nebula", 4594: "Sombrero Galaxy",
    5139: "Omega Centauri", 5194: "Whirlpool Galaxy", 5457: "Pinwheel Galaxy",
    6205: "Hercules Cluster", 6514: "Trifid Nebula", 6523: "Lagoon Nebula",
    6543: "Cat's Eye Nebula", 6611: "Eagle Nebula", 6720: "Ring Nebula",
    6853: "Dumbbell Nebula", 6960: "Veil Nebula", 6992: "Veil Nebula",
    7000: "North America Nebula", 7009: "Saturn Nebula", 7293: "Helix Nebula",
    869: "Double Cluster", 884: "Double Cluster", 104: "47 Tucanae",
}

MESSIER_RE = re.compile(r"\bM0*([0-9]{1,3})\b")

# Messier numbers RNGC's cross-reference column simply does not record, keyed
# by NGC number. All three objects are in the catalogue and correctly placed;
# only the identification is missing, so without this /M77, /M78 and /M110
# have no page while their NGC numbers do.
#
# Hand-written for the same reason COMMON_NAMES is: which NGC object carries
# which Messier number is a published fact, not a judgement.
#
# M110 is the one that matters. It is M31's second companion, and the old
# reader gave it the name "M31" outright by reading its neighbour's number
# out of the prose -- so the fix that stopped that also has to supply the
# number it should have had.
MESSIER_EXTRA = {1068: 77, 2068: 78, 205: 110}

# Objects the NGC simply does not contain, added by hand.
#
# The Pleiades have no NGC number: Dreyer catalogued nebulae and clusters
# that needed a telescope, and a naked-eye group six Moon-widths across that
# every culture on Earth already had a name for was not on that list. So no
# amount of parsing recovers it, and leaving it out means the single most
# looked-at cluster in the sky is missing from a service about looking at
# the sky. Position and magnitude are published facts, same footing as
# COMMON_NAMES above and showers.json -- see LICENSES.md.
#
# The id is "M45" rather than an NGC number because there is no NGC number
# to give; nothing downstream requires the id to start with NGC, it only
# has to be unique and stable.
EXTRA = [
    dict(id="M45", ra=3.79, de=24.117, m=1.6, t="clu", n="M45", cn="Pleiades"),
]


def main():
    try:
        rows = [l.rstrip("\n").split("\t")
                for l in open(SRC, encoding="utf-8")
                if not l.startswith("#") and l.strip()]
    except FileNotFoundError:
        print(f"missing {SRC} -- see the fetch command in this file's docstring")
        return 1

    out = []
    for r in rows:
        if len(r) < 7:
            continue
        num_s, comp, type_code = r[0].strip(), r[1].strip(), r[2].strip()
        # VizieR prefaces the data with a header row, a units row and a rule.
        # Requiring the identification to be a number drops all three without
        # counting how many preamble lines this particular export had.
        if not num_s.isdigit():
            continue
        if not type_code or type_code in ("0", "7"):
            continue                       # unverified southern / non-existent
        cat = CATEGORY.get(type_code[0])
        if cat is None:
            continue

        # Which Messier object this is, from the cross-reference field ONLY.
        #
        # The old fixed-width reader searched this together with the
        # catalogue's two prose fields -- Dreyer's visual notes and the
        # Palomar description -- and both mention neighbours. "Companion to
        # M 31" in NGC205's description made NGC205 an object called M31.
        # Seven Messier numbers ended up claimed by more than one row, the
        # Beehive by five of them (NGC2624, 2625, 2632, 2637 and 2643).
        #
        # The cross-reference column is where RNGC records what an object
        # actually is. Reading only it still finds all 104 Messier numbers in
        # the catalogue and leaves exactly one shared between two rows -- M76,
        # genuinely a two-component object, the same situation the Double
        # Cluster and the Veil are in above.
        mm = MESSIER_RE.search(r[6])
        messier = int(mm.group(1)) if mm else MESSIER_EXTRA.get(int(num_s))

        mag_s = r[5].strip()
        # Diffuse nebulae (type 3) carry no magnitude in this catalog at all,
        # and most cluster+nebulosity (type 6) rows don't either -- there's
        # no stellar point-source brightness to give an extended nebula. Those
        # get included at the cutoff itself (sorted last among their peers)
        # rather than dropped outright, or ?dso=1 would show zero nebulae.
        no_mag_ok = type_code[0] in ("3", "6")
        # A Messier number always qualifies, whatever the magnitude column
        # says or fails to say. Messier catalogued things bright enough to be
        # mistaken for a comet through an 18th-century refractor, so every one
        # of them belongs on a chart like this by definition -- and RNGC's
        # 1973 photographic magnitudes run systematically faint for planetary
        # nebulae, which is why the Owl Nebula (modern mag ~9.9) is recorded
        # here at 12.0 and was being dropped. The Crab was dropped for a
        # different reason: no magnitude at all, and type 4 is not one of the
        # no-magnitude exemptions above.
        if not mag_s and not no_mag_ok and messier is None:
            continue
        try:
            num = int(num_s)
            ra_j2000 = float(r[3]) / 15.0        # VizieR gives degrees
            de_j2000 = float(r[4])
            mag = float(mag_s) if mag_s else MAG_LIMIT
        except ValueError:
            continue
        if mag > MAG_LIMIT and messier is None:
            continue

        common = COMMON_NAMES.get(num)
        if messier is not None:
            name = f"M{messier}"
        elif common:
            name = common
        else:
            name = f"NGC{num}{comp}"
        entry = dict(id=f"NGC{num}{comp}", ra=round(ra_j2000, 5),
                    de=round(de_j2000, 5), m=round(mag, 2), t=cat, n=name)
        if common:
            entry["cn"] = common
        out.append(entry)

    out.extend(EXTRA)
    out.sort(key=lambda e: e["m"])
    json.dump(out, open(OUT, "w"), separators=(",", ":"))

    by_cat = {}
    for e in out:
        by_cat[e["t"]] = by_cat.get(e["t"], 0) + 1
    print(f"{len(out)} deep-sky objects to mag {MAG_LIMIT}")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:4} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
