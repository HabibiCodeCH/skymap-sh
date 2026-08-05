#!/usr/bin/env python3
"""
Build variables.json: period, epoch and brightness range for the variable
stars we already draw.

This is what makes "Algol's next minimum is at 23:14 tonight" possible --
a fully deterministic prediction from a period and an epoch, which is one of
the nicer things an object page can tell someone.

Source: the General Catalogue of Variable Stars (Samus+), B/gcvs at CDS.
No copyright notice, same unrestricted provenance as the other catalogues
here (see LICENSES.md).

    curl -o gcvs.tsv 'https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=B/gcvs/gcvs_cat&-out.max=unlimited&-out=_RAJ2000,_DEJ2000,GCVS,VarType,magMax,l_Min1,Min1,Period,Epoch'
    python3 build_variables.py

l_Min1 is not optional. For roughly one star in six the Min1 column holds the
AMPLITUDE of the variation rather than the magnitude at minimum, flagged by a
"(" in l_Min1. Read as a magnitude it is nonsense in the worst way: Epsilon
Eridani's 0.05 would become a minimum brightness of 0.05, making a fourth-
magnitude star the brightest thing in the sky. Amplitudes are stored under
their own key so the prose can say "varies by 0.05 magnitudes" instead.

Joined on POSITION, not on name. GCVS designations ("bet Per", "Alp Ori")
and BSC5's own VarID column agree often enough to be tempting and not often
enough to be safe -- BSC5 records some variables as the bare string "Var",
and the two catalogues disambiguate components of multiple systems
differently. A 30-arcsecond positional match has neither problem.

GCVS is ~60,000 stars against the 2,887 on our chart, so the output is small.
"""
import json, math, sys

GCVS, STARS, OUT = "gcvs.tsv", "stars.json", "variables.json"

# Naked-eye variables are what this is for, and 30" is far tighter than the
# separation of any two stars we draw while still absorbing the epoch and
# proper-motion differences between the two catalogues.
MATCH_ARCSEC = 30.0
D = math.pi / 180


def sep_arcsec(ra1_h, de1, ra2_h, de2):
    """Angular separation, small-angle -- only ever called on near-coincident
    pairs, where the flat approximation is exact to well under an arcsecond."""
    dde = de1 - de2
    dra = (ra1_h - ra2_h) * 15 * math.cos((de1 + de2) / 2 * D)
    return math.hypot(dra, dde) * 3600


def main():
    try:
        stars = json.load(open(STARS))
        rows = [l for l in open(GCVS, encoding="utf-8")
                if not l.startswith("#") and l.strip()]
    except FileNotFoundError as e:
        print(f"missing {e.filename} -- see the fetch command in this file's docstring")
        return 1

    # Bin our own stars by whole degree of declination so each GCVS row is
    # compared against a handful of candidates rather than all 2,887.
    bins = {}
    for s in stars:
        bins.setdefault(int(math.floor(s["de"])), []).append(s)

    out, seen = {}, {}
    for l in rows:
        p = l.rstrip("\n").split("\t")
        if len(p) != 9:
            continue
        try:
            ra = float(p[0]) / 15.0                  # VizieR gives degrees
            de = float(p[1])
        except ValueError:
            continue                                  # header, units, rule
        cands = []
        for b in (int(math.floor(de)) - 1, int(math.floor(de)), int(math.floor(de)) + 1):
            cands.extend(bins.get(b, ()))
        best, best_d = None, MATCH_ARCSEC
        for s in cands:
            d = sep_arcsec(ra, de, s["ra"], s["de"])
            if d < best_d:
                best, best_d = s, d
        if best is None:
            continue
        rec = {}
        # "(" in l_Min1 means the Min1 column is the amplitude of the
        # variation, not the magnitude at minimum. Two different quantities
        # in one column, and only this flag tells them apart.
        min_key = "amp" if "(" in p[5] else "min"
        for key, idx in (("type", 3), ("max", 4), (min_key, 6),
                         ("period", 7), ("epoch", 8)):
            v = p[idx].strip()
            if not v:
                continue
            if key == "type":
                rec[key] = v
                continue
            try:
                rec[key] = float(v)
            except ValueError:
                pass
        # A minimum fainter than the maximum is the same confusion arriving
        # unflagged. Physically impossible, so it is an amplitude too.
        if "min" in rec and "max" in rec and rec["min"] < rec["max"]:
            rec["amp"] = rec.pop("min")
        if not rec:
            continue
        rec["gcvs"] = p[2].strip()
        hr = str(best["hr"])
        # Two GCVS rows can fall inside 30" of the same star (components of a
        # close pair). Keep the nearer one so the brighter, better-known
        # variable wins rather than whichever came later in the file.
        if hr not in out or best_d < seen[hr]:
            out[hr], seen[hr] = rec, best_d

    if not out:
        print("no variables matched -- refusing to write")
        return 1

    json.dump(out, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    usable = sum(1 for r in out.values() if r.get("period") and r.get("epoch"))
    print(f"{len(out)} variables -> {OUT}  ({usable} with both period and epoch)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
