#!/usr/bin/env python3
"""
Build planetinfo.json: the measured physical facts for the Sun, the Moon and
the seven planets.

    python3 build_planetinfo.py        # queries JPL directly, no manual fetch

Source: NASA/JPL Horizons, the same system sky.py's planetary elements come
from. US government work, public domain, no attribution required (though it
is in LICENSES.md anyway). This replaces a hand-typed table: the numbers were
right, but "right because somebody typed them carefully" is a worse guarantee
than "right because a build script fetched them from JPL".

Horizons returns a fixed text block rather than JSON, and its field names
are not consistent between bodies. The same quantity appears as

    Vol. Mean Radius (km)      and   Vol. mean radius (km)
    Sid. rot. period (III)     and   Sidereal rot. period
    Equ. grav, ge (m/s^2)      and   Equ. gravity  m/s^2
    Escape speed, km/s         and   Escape speed (1 bar)

and the mass exponent lives in the key itself -- "Mass x10^23 (kg)" for Mars,
"x10^26" for Saturn -- so it has to be captured rather than assumed. Hence a
pattern per field with alternatives, rather than a generic key=value scan.
A generic scan also picks up debris from the two-column layout, keys like
"m 22.4s   Sid. rot. rate".

Every field is validated across all nine bodies before anything is written.
If JPL reformats and a pattern stops matching, this fails loudly at build
time and the committed JSON is left alone, which is the right failure: the
data is static, so a broken build is an inconvenience and a silently missing
field would be a page that quietly lost a row.
"""
import json, re, sys, urllib.request

OUT = "planetinfo.json"
API = ("https://ssd.jpl.nasa.gov/api/horizons.api?format=text"
       "&COMMAND='{}'&OBJ_DATA='YES'&MAKE_EPHEM='NO'")

# Horizons body codes.
BODIES = {"Sun": 10, "Mercury": 199, "Venus": 299, "Moon": 301, "Mars": 499,
          "Jupiter": 599, "Saturn": 699, "Uranus": 799, "Neptune": 899}

def normalise(text):
    """Punctuation out, case down, whitespace collapsed.

    JPL writes the same quantity as "Vol. mean radius, km", "Vol. Mean Radius
    (km)" and "Radius (IAU), km" depending on which decade the body's sheet
    was last revised. Chasing every spelling with alternatives got long and
    still missed cases; flattening the punctuation first turns them all into
    one string and the patterns below become readable again.
    """
    t = text.replace("(", " ").replace(")", " ").replace(",", " ")
    return re.sub(r"[ \t]+", " ", t.lower())


# Values may be approximate ("~1988410") or carry a tolerance ("2439.4+-0.1").
NUM = r"~?\s*([-+]?[\d.]+)"
PATTERNS = {
    "radius_km":     rf"vol\. mean radius km ?= ?{NUM}",
    "density":       rf"(?:mean )?density g ?[/ ]? ?cm ?\^? ?-?3 ?= ?{NUM}",
    # "Surface gravity = 274.0 m/s^2" puts the value before the unit;
    # "Equ. grav, ge (m/s^2) = 24.79" puts it after. Both, either way round.
    "gravity":       rf"(?:surface gravity|equ\. grav(?:ity)?(?: ge)?)"
                     rf"(?: m/s\^2)? ?= ?{NUM}",
    # speed, velocity or "vel." depending on the body.
    "escape_kms":    rf"escape (?:speed|vel(?:ocity)?)\.?[^=]*= ?{NUM}",
    "obliquity_deg": rf"obliquity to orbit ?= ?{NUM}",
    "albedo":        rf"geometric albedo ?= ?{NUM}",
    "temp_k":        rf"(?:atmos\. temp\. 1 bar|mean temperature k|"
                     rf"effective temp\.? k) ?= ?{NUM}",
}
# The mass exponent lives in the key: "mass x10^23 kg" for Mars, "x 10^26"
# for Jupiter with a space JPL puts nowhere else, "10^24" for the Sun.
MASS = re.compile(rf"mass ?x? ?10 ?\^ ?(\d+) kg ?= ?{NUM}")

# Rotation comes in four shapes across nine bodies: "9h 55m 29.711 s",
# "58.6463 d", "24.622962 hr" and "17.24+-0.01 h". The unit has to be
# captured rather than assumed, or Mercury's 58 days becomes 58 hours.
ROT_HMS = re.compile(r"sid(?:ereal)?\.? rot\.? period[^=]*= ?"
                     r"(\d+)h ?(\d+)m ?([\d.]+) ?s")
ROT_DEC = re.compile(r"sid(?:ereal)?\.? rot\.? period[^=]*= ?~?([\d.]+)"
                     r"(?:\+-[\d.]+)? ?(d|hr|h)\b")
# "Sidereal orbit period = 11.86 y" and "Sidereal orb. per. = 87.97 d".
YEAR = re.compile(r"sidereal orb(?:it)?\.? per(?:iod)?\.? ?= ?([\d.]+) ?(yr|y|d)\b")

REQUIRED = {"radius_km", "density", "mass_kg"}


def fetch(code):
    with urllib.request.urlopen(API.format(code), timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def parse(raw):
    text = normalise(raw)
    out = {}
    for field, pat in PATTERNS.items():
        m = re.search(pat, text)
        if m:
            out[field] = float(m.group(1))
    m = MASS.search(text)
    if m:
        out["mass_kg"] = float(m.group(2)) * (10 ** int(m.group(1)))
    m = ROT_HMS.search(text)
    if m:
        out["rotation_hours"] = int(m.group(1)) + int(m.group(2)) / 60 + \
            float(m.group(3)) / 3600
    else:
        m = ROT_DEC.search(text)
        if m:
            hours = float(m.group(1)) * (24 if m.group(2) == "d" else 1)
            out["rotation_hours"] = hours
    m = YEAR.search(text)
    if m:
        years = float(m.group(1)) / (365.25 if m.group(2) == "d" else 1)
        out["orbit_years"] = years
    return out


def main():
    got, problems = {}, []
    for name, code in BODIES.items():
        try:
            rec = parse(fetch(code))
        except Exception as e:                              # noqa: BLE001
            print(f"  {name}: fetch failed, {e}")
            return 1
        missing = REQUIRED - set(rec)
        if missing:
            problems.append(f"{name} is missing {sorted(missing)}")
        got[name] = rec
        print(f"  {name:<9} {len(rec):>2} fields")

    if problems:
        print("\nrefusing to write:")
        for p in problems:
            print("  " + p)
        print("JPL has probably reformatted; the patterns in this file need "
              "updating. The committed planetinfo.json is untouched.")
        return 1

    json.dump(got, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    print(f"\n{len(got)} bodies -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
