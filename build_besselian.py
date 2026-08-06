#!/usr/bin/env python3
"""Builds besselian.json: NASA's Besselian elements for the solar eclipses
we have a page for.

    python3 build_besselian.py

The first version of this table was two dozen numbers typed in by hand, with
a comment saying more would be added "when there is a reason to trust each
one". That reasoning was backwards. Hand-transcription is exactly the step
that goes wrong silently -- a digit dropped from x2 shifts the track by
kilometres and nothing raises -- and doing it eight more times would have
made the risk eight times worse, not the confidence eight times higher.

So: fetched and parsed. The transcription is now a program that either
works for every eclipse or fails loudly on one, and test_besselian.py still
checks the result against NASA's independently published path.

Source: eclipse.gsfc.nasa.gov, US government work and public domain, the
same provenance as the decade tables eclipses.json already draws on.
"""
import json
import re
import sys
import urllib.request

SRC = "https://eclipse.gsfc.nasa.gov/SEsearch/SEdata.php?Ecl=+{d}"
OUT = "besselian.json"
MONTHS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def _clean(raw):
    t = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ")
    # The page emits PHP warnings for the cubic terms some eclipses lack.
    t = re.sub(r"Warning\s*:.*?on line \d+", " ", t, flags=re.S)
    return re.sub(r"[ \t]+", " ", t)


def parse(raw, key):
    t = _clean(raw)

    m = re.search(r"Polynomial Besselian Elements for: "
                  r"(\d{4}) (\w{3}) (\d+) ([\d.]+) TDT", t)
    if not m:
        raise ValueError(f"{key}: no polynomial header")
    year, mon, day, t0 = m.group(1), m.group(2), m.group(3), float(m.group(4))
    got = f"{year}-{MONTHS[mon]:02d}-{int(day):02d}"
    if got != key:
        raise ValueError(f"{key}: page is for {got}")

    # Rows "n v v v v v v", n ascending from 0. The last row carries only x
    # and y for most eclipses, which is why the columns are read per row
    # rather than as a fixed block.
    body = t[m.end():t.index("tan f1")]
    coeffs = {k: [] for k in ("x", "y", "d", "l1", "l2", "mu")}
    for n in range(4):
        row = re.search(rf"(?:^| ){n} ((?:-?[\d.]+ ?){{2,6}})", body)
        if not row:
            break
        vals = [float(v) for v in row.group(1).split()]
        for name, v in zip(("x", "y", "d", "l1", "l2", "mu"), vals):
            coeffs[name].append(v)
    if len(coeffs["x"]) < 3:
        raise ValueError(f"{key}: only {len(coeffs['x'])} x coefficients")

    tf = re.search(r"tan f1 = ([-\d.]+) tan f2 = ([-\d.]+)", t)
    dt_ = re.search(r"T = ([\d.]+) s", t)
    if not tf or not dt_:
        raise ValueError(f"{key}: missing tan f or delta T")

    kind = re.search(r"(Total|Annular|Hybrid|Partial) Solar Eclipse", t)
    return dict(name=f"{kind.group(1)} solar eclipse" if kind else "Solar eclipse",
                t0=t0, tanf1=float(tf.group(1)), tanf2=float(tf.group(2)),
                dT=float(dt_.group(1)), **coeffs)


def main():
    rows = [e for e in json.load(open("eclipses.json")) if "when_utc" in e]
    keys = [e["when_utc"][:10] for e in rows if "solar" in e["type"]]
    out, bad = {}, []
    for key in keys:
        url = SRC.format(d=key.replace("-", ""))
        try:
            raw = urllib.request.urlopen(url, timeout=30).read().decode(
                "utf-8", "replace")
            out[key] = parse(raw, key)
            print(f"  {key}  {out[key]['name']}")
        except Exception as ex:                       # noqa: BLE001
            bad.append(f"{key}: {ex}")
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"\n{OUT}: {len(out)} eclipses")
    for b in bad:
        print(f"  SKIPPED {b}")
    return 1 if not out else 0


if __name__ == "__main__":
    sys.exit(main())
