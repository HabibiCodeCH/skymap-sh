#!/usr/bin/env python3
"""
Build dsoinfo.json: how big a Messier object actually looks.

"M31 is about 178 arcminutes across, six Moon-widths" is what turns a
catalogue row into something someone can picture, and it is the one number
deepsky.json does not carry.

    python3 build_dsoinfo.py        # no fetch, the table is below

Hand-authored, for the same reason showers.json and build_deepsky.py's
COMMON_NAMES table are hand-authored: an object's angular size is a measured
fact, not a creative work, and typing the well-known ones costs nothing and
carries no licensing question. See LICENSES.md.

Deliberately NOT taken from a catalogue:

  The Revised NGC, which deepsky.json is built from, has no size field. Bytes
  40-46 look like one and are not -- they are Xpos/Ypos, the object's
  position in millimetres on a POSS photographic print.

  NGC 2000.0 (VII/118) has the right data for every NGC and IC object and is
  copyrighted by Sky Publishing Corporation for "scientific research purposes
  only", explicitly not commercial. Out, same as OpenNGC.

  SIMBAD has it too, and CDS's own terms say their datasets carry "Open
  Licence or ODbL or CC-BY" without saying which applies where. ODbL is
  share-alike, so that is an unpinned licence on a repo that promises to
  bundle no copyleft data. Bulk extraction from a database is also a
  different act from quoting individual facts, which is what this table does.

Dimensions are the major axis in arcminutes, with the minor axis where the
object is visibly elongated. These are the conventional visual extents -- the
figures quoted in observing guides, which run smaller than the isophotal
extents research catalogues give, because they describe what an eyepiece
shows rather than where the light formally ends. That is the right convention
for a service that tells people where to look.

Only the well-known objects are here. An object with no entry simply prints
no size, which is better than padding the table with numbers nobody checked.
"""
import json, sys

OUT, DEEPSKY = "dsoinfo.json", "deepsky.json"

# Messier number -> (major arcmin, minor arcmin or None if roughly round).
SIZES = {
    2:  (16.0, None),
    3:  (18.0, None),
    4:  (26.0, None),
    5:  (23.0, None),
    6:  (25.0, None),    # Butterfly Cluster
    7:  (80.0, None),    # Ptolemy Cluster
    8:  (90.0, 40.0),    # Lagoon Nebula
    10: (20.0, None),
    11: (14.0, None),    # Wild Duck Cluster
    13: (20.0, None),    # Hercules Cluster
    15: (18.0, None),
    16: (35.0, 28.0),    # Eagle Nebula
    17: (11.0, None),    # Omega / Swan Nebula
    20: (28.0, None),    # Trifid Nebula
    22: (32.0, None),
    27: (8.0, 5.7),      # Dumbbell Nebula
    31: (178.0, 63.0),   # Andromeda Galaxy
    32: (8.0, 6.0),
    33: (73.0, 45.0),    # Triangulum Galaxy
    35: (28.0, None),
    36: (12.0, None),
    37: (24.0, None),
    38: (21.0, None),
    39: (32.0, None),
    41: (38.0, None),
    42: (85.0, 60.0),    # Orion Nebula
    43: (20.0, 15.0),
    44: (95.0, None),    # Beehive Cluster
    46: (27.0, None),
    47: (30.0, None),
    51: (11.0, 7.0),     # Whirlpool Galaxy
    52: (13.0, None),
    53: (13.0, None),
    57: (1.4, 1.0),      # Ring Nebula
    63: (12.6, 7.2),     # Sunflower Galaxy
    64: (9.3, 5.4),      # Black Eye Galaxy
    65: (8.0, 1.5),
    66: (9.0, 4.0),
    67: (30.0, None),
    74: (10.0, 9.5),
    77: (7.0, 6.0),
    78: (8.0, 6.0),
    80: (10.0, None),
    81: (27.0, 14.0),    # Bode's Galaxy
    82: (11.0, 4.0),     # Cigar Galaxy
    83: (13.0, 11.0),
    87: (8.0, 7.0),
    92: (14.0, None),
    97: (3.4, None),     # Owl Nebula
    101: (29.0, None),   # Pinwheel Galaxy
    104: (9.0, 4.0),     # Sombrero Galaxy
    110: (17.0, 10.0),
}

# Messier numbers deepsky.json does not label "M##" in its n field, so the
# join below cannot find them by name. Two causes, both in build_deepsky.py's
# Messier regex: it found no designation in the notes (M77, M78, which are
# stored under their bare NGC numbers), or it found the wrong one (NGC205 is
# M110, but its notes mention its neighbour M31 and it is labelled that).
NGC_FOR = {77: "NGC1068", 78: "NGC2068", 110: "NGC205"}

# A number listed above that is absent from deepsky.json is skipped, and the
# build says which. M1, M45, M76 and M97 are all in that position: the
# Revised NGC's magnitude cutoff and type filtering drop them upstream in
# build_deepsky.py, and this file cannot size what the chart does not carry.
# Their sizes stay in the table regardless, so they start working the day
# the catalogue does.


def main():
    try:
        deepsky = json.load(open(DEEPSKY))
    except FileNotFoundError:
        print(f"missing {DEEPSKY} -- run build_deepsky.py first")
        return 1

    # deepsky.json labels an object "M31" in its n field, but that field is
    # not unique: NGC205 also carries "M31" and NGC595 also carries "M33",
    # because build_deepsky.py's Messier regex reads cross-reference mentions
    # in the notes ("companion to M 31") as the object's own designation.
    # Taking the brightest match is what makes this table land on the real
    # M31 and M33 rather than on their neighbours.
    by_messier = {}
    for o in deepsky:
        n = o.get("n", "")
        if not (n.startswith("M") and n[1:].isdigit()):
            continue
        num = int(n[1:])
        if num not in by_messier or o["m"] < by_messier[num]["m"]:
            by_messier[num] = o

    by_id = {o["id"]: o for o in deepsky}
    out, missing = {}, []
    for num, (maj, minor) in SIZES.items():
        o = by_messier.get(num) or by_id.get(NGC_FOR.get(num, ""))
        if o is None:
            missing.append(num)
            continue
        rec = {"maj": maj}
        if minor:
            rec["min"] = minor
        out[o["id"]] = rec

    json.dump(out, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    note = f", {len(missing)} not in deepsky.json ({missing})" if missing else ""
    print(f"{len(out)} Messier objects sized -> {OUT}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
