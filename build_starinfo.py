#!/usr/bin/env python3
"""
Build starinfo.json: what a star IS, for the stars already on the chart.

stars.json says where a star is and how bright. This says what kind of star
it is, how far away, and whether it is double or variable -- the facts an
object page needs and a chart does not.

Deliberately a SEPARATE file rather than extra fields on stars.json. There is
no build script for stars.json in this repo, so regenerating it would mean
reconstructing how it was made and risking a silent change to every chart on
the site. This file is keyed by HR number and joined at read time; stars.json
is never touched.

    curl -o bsc5.dat.gz http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz
    gunzip bsc5.dat.gz
    curl -o hip.tsv 'https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=I/239/hip_main&-out.max=unlimited&-out=HIP,HD,Plx,e_Plx&Plx=>0'
    python3 build_starinfo.py

Two sources:

  BSC5 (Yale Bright Star Catalogue, 5th ed.) -- the same public-domain
  catalogue stars.json itself came from. Gives spectral type (9,096 of 9,110
  rows have one) and double-star separations. Fetched from Harvard rather
  than CDS: cdsarc.cds.unistra.fr now returns a bot-wall page for every data
  file. Harvard serves it over http only; their TLS certificate does not
  match the hostname.

  Hipparcos (ESA 1997) -- for distance, joined on HD number. BSC5 carries its
  own parallax column and it is NOT used: it is pre-Hipparcos ground-based
  measurement and it fails worst on exactly the famous stars an object page
  gets visited for. Measured against modern values it puts Antares at 136 ly
  instead of 550, Spica at 142 instead of 250, and gives Deneb a negative
  parallax. Hipparcos gets those right and, more importantly, ships a
  standard error with every one, so the page can hedge or stay silent
  instead of stating a wrong number confidently.
"""
import json, sys

BSC, HIP, STARS, OUT = "bsc5.dat", "hip.tsv", "stars.json", "starinfo.json"

# Parallax below this is noise dressed as a measurement -- 0.5 mas is 6,500
# light years, well past anything the naked eye resolves as a single star,
# and the error bar there is routinely larger than the value.
MIN_PLX_MAS = 0.5


def f(line, a, b):
    """1-indexed inclusive byte range, matching the ReadMe's own numbering."""
    return line[a - 1:b].strip()


def load_hipparcos():
    """HD number -> (parallax mas, standard error mas)."""
    out = {}
    for l in open(HIP, encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        p = l.rstrip("\n").split("\t")
        if len(p) != 4 or not p[1].strip().isdigit():
            continue
        try:
            plx, err = float(p[2]), float(p[3])
        except ValueError:
            continue
        hd = int(p[1])
        # A handful of HD numbers appear twice (resolved components of the
        # same system). Keep the better-measured one rather than whichever
        # happened to be last.
        if hd not in out or err < out[hd][1]:
            out[hd] = (plx, err)
    return out


def main():
    try:
        bsc = open(BSC, encoding="latin-1").readlines()
        hip = load_hipparcos()
        want = {s["hr"] for s in json.load(open(STARS))}
    except FileNotFoundError as e:
        print(f"missing {e.filename} -- see the fetch commands in this file's docstring")
        return 1

    out, n_dist, n_sp = {}, 0, 0
    for l in bsc:
        try:
            hr = int(f(l, 1, 4))
        except ValueError:
            continue
        if hr not in want:                  # only what the chart already ships
            continue
        rec = {}
        sp = f(l, 128, 147)
        if sp:
            rec["sp"] = sp
            n_sp += 1
        hd = f(l, 26, 31)
        got = hip.get(int(hd)) if hd.isdigit() else None
        if got and got[0] >= MIN_PLX_MAS:
            plx, err = got
            rec["ly"] = round(3261.6 / plx, 1)
            # Kept as a percentage because that is what the prose needs to
            # decide between "25 light years", "about 600 light years" and
            # saying nothing at all.
            rec["ly_err"] = round(100 * err / plx, 1)
            n_dist += 1
        # Separation of the components, arcseconds, and their magnitude
        # difference -- both only meaningful together, so both or neither.
        sep, dmag = f(l, 185, 190), f(l, 181, 184)
        if sep and dmag:
            try:
                rec["sep"] = float(sep)
                rec["dmag"] = float(dmag)
            except ValueError:
                pass
        var = f(l, 52, 60)
        if var:
            rec["var"] = var
        if rec:
            out[str(hr)] = rec

    if len(out) < 1000:
        print(f"only {len(out)} stars matched -- expected ~2,800, refusing to write")
        return 1

    json.dump(out, open(OUT, "w"), separators=(",", ":"), sort_keys=True)
    print(f"{len(out)} stars -> {OUT}  ({n_sp} spectral, {n_dist} with distance)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
