#!/usr/bin/env python3
"""
Build constellations.json: which of the 88 constellations a position falls in.

Source: VI/42, "Identification of a Constellation From Position" (Roman 1987),
a rearrangement of the IAU boundaries Delporte drew in 1930 into a form you
can scan linearly. Distributed by the ADC with no copyright notice, same
"unrestricted" provenance as stars.json's BSC5 and deepsky.json's RNGC -- and
the boundaries themselves are the IAU's official delimitation, a published
fact rather than a creative work (see LICENSES.md).

    curl -o constbnd.tsv 'https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=VI/42/data&-out.max=unlimited&-out=RA_low,RA_up,DE_low,const'
    python3 build_constellations.py

Fetched through VizieR rather than the raw catalogue path the other build
scripts use: cdsarc.cds.unistra.fr now sits behind a bot wall that returns a
4 KB block page for every data file (the ReadMe files still come through).
The same wall breaks build_deepsky.py's documented curl line.

357 rows, so this is a small file. The output keeps Roman's own ordering,
which the lookup depends on: rows run from the north pole southwards, and the
FIRST row a position satisfies is its constellation. Sorting it any other way
silently breaks the algorithm.
"""
import json, sys

SRC, OUT = "constbnd.tsv", "constellations.json"


def main():
    try:
        lines = open(SRC, encoding="utf-8").readlines()
    except FileNotFoundError:
        print(f"missing {SRC} -- see the fetch command in this file's docstring")
        return 1

    out = []
    for l in lines:
        # VizieR TSV carries a comment block, then a header row, a units row
        # and a dashed rule before the data. Rows are only taken when all four
        # fields parse as the right shape, which drops all of that without
        # having to count how many preamble lines this particular export had.
        if l.startswith("#") or not l.strip():
            continue
        parts = l.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        try:
            ra_lo, ra_up, de_lo = (float(parts[i]) for i in range(3))
        except ValueError:
            continue
        con = parts[3].strip()
        # Three letters exactly -- the units row ("h h deg") and the dashed
        # rule both survive the float() check on some exports otherwise.
        if len(con) != 3 or not con.isalpha():
            continue
        out.append([round(ra_lo, 4), round(ra_up, 4), round(de_lo, 4), con])

    if len(out) < 300:
        print(f"only {len(out)} boundary rows parsed -- expected ~357, refusing to write")
        return 1

    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    names = {c[3] for c in out}
    print(f"{len(out)} boundary rows, {len(names)} constellations -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
