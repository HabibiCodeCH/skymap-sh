#!/usr/bin/env python3
"""
Build deepsky.json: galaxies, nebulae and star clusters, to go alongside
stars.json on the chart.

Source: the Revised NGC (Sulentic & Tifft 1973), an updated re-verification
of Dreyer's original New General Catalogue (1888), distributed by NASA's
Astronomical Data Center -- same "unrestricted, courtesy citation only"
provenance as stars.json's Yale BSC5, and deliberately NGC-only rather than
OpenNGC (which also covers the IC catalogue but is CC-BY-SA and would have
put deepsky.json's licence at odds with the rest of this repo; see
LICENSES.md). That trade means a few well-known IC-numbered targets (the
Heart, Soul, Pelican and Cocoon nebulae among them) aren't in here.

    curl -o rngc.dat https://cdsarc.cds.unistra.fr/ftp/VII/1B/catalog.dat
    python3 build_deepsky.py

Kept types: galaxies, open/globular clusters, nebulae and cluster+nebula
pairs. Dropped: non-existent entries, unverified southern objects, and
anything without a recorded magnitude. Magnitude cutoff is 11.0 -- faint
enough to hold the entire Messier catalogue plus several hundred more NGC
objects, without the deep tail of galaxies that are invisible outside a
telescope.
"""
import json, math, re, sys

SRC, OUT = "rngc.dat", "deepsky.json"
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


def field(line, a, b):
    """1-indexed inclusive byte range, matching the ReadMe's own numbering."""
    return line[a - 1:b].strip()


def precess_1975_to_j2000(ra_h, dec_d):
    """B1975 -> J2000, backward over -25 years. The precession rate only
    drifts per century, so evaluating it at J2000 instead of the exact 1975
    epoch is accurate to a small fraction of an arcsecond -- far below what
    this ASCII chart can even show. Same rate constants as sky.py's own
    precess(), just run in the other direction over a short span."""
    yrs = -25.0
    m = 3.07496 / 3600 * 15
    n_ra = 1.33621 / 3600 * 15
    n_dec = 20.0431 / 3600
    ra, dec = math.radians(ra_h * 15), math.radians(dec_d)
    dra = (m + n_ra * math.sin(ra) * math.tan(dec)) * yrs
    ddec = (n_dec * math.cos(ra)) * yrs
    return (ra_h + dra / 15) % 24, dec_d + ddec


def main():
    try:
        lines = open(SRC, encoding="latin-1").readlines()
    except FileNotFoundError:
        print(f"missing {SRC} -- see the fetch command in this file's docstring")
        return 1

    out = []
    for l in lines:
        if len(l) < 51:
            continue
        type_code = field(l, 8, 9)
        if not type_code or type_code in ("0", "7"):
            continue                       # unverified southern / non-existent
        cat = CATEGORY.get(type_code[0])
        if cat is None:
            continue
        # Diffuse nebulae (type 3) carry no magnitude in this catalog at all,
        # and most cluster+nebulosity (type 6) rows don't either -- there's
        # no stellar point-source brightness to give an extended nebula. Those
        # get included at the cutoff itself (sorted last among their peers)
        # rather than dropped outright, or ?dso=1 would show zero nebulae.
        mag_s = field(l, 48, 51)
        no_mag_ok = type_code[0] in ("3", "6")
        if not mag_s and not no_mag_ok:
            continue
        num_s, comp = field(l, 2, 5), field(l, 6, 6)
        try:
            num = int(num_s)
            rah, ram = int(field(l, 11, 12)), float(field(l, 14, 17))
            de_sign = -1 if field(l, 19, 19) == "-" else 1
            ded, dem = int(field(l, 20, 21)), int(field(l, 23, 24))
            mag = float(mag_s) if mag_s else MAG_LIMIT
        except ValueError:
            continue
        if mag > MAG_LIMIT:
            continue
        ra_h = rah + ram / 60
        de_d = de_sign * (ded + dem / 60)
        ra_j2000, de_j2000 = precess_1975_to_j2000(ra_h, de_d)

        notes = " ".join((field(l, 55, 94), field(l, 96, 151), field(l, 153, 192)))
        mm = MESSIER_RE.search(notes)
        common = COMMON_NAMES.get(num)
        if mm:
            name = f"M{int(mm.group(1))}"
        elif common:
            name = common
        else:
            name = f"NGC{num}{comp}"
        entry = dict(id=f"NGC{num}{comp}", ra=round(ra_j2000, 5),
                    de=round(de_j2000, 5), m=round(mag, 2), t=cat, n=name)
        if common:
            entry["cn"] = common
        out.append(entry)

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
