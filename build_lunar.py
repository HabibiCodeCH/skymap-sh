#!/usr/bin/env python3
"""Builds lunar.json: NASA's published circumstances for the lunar eclipses
we have a page for.

    python3 build_lunar.py

The same argument as build_besselian.py, for the same reason. sky.moon() is
a seven-term geocentric series good to about 12 arcmin, and the Earth's
umbra is 40 arcmin across at the Moon's distance: an error a third of the
shadow's radius cannot say when the Moon enters it, or how deep it goes, or
whether an eclipse is total at all. So the numbers come from somebody who
did the work properly.

What the catalogue gives, per eclipse:

    gamma          how close the Moon's centre passes the shadow axis
    umbral mag     how much of the Moon's diameter is inside the umbra at
                   greatest eclipse -- over 1.0 means totality
    durations      penumbral, partial and total, in minutes, centred on
                   greatest eclipse, so every contact time follows exactly
    zenith         where the Moon is overhead at greatest eclipse, which is
                   what decides who can see it at all

That last one is why a lunar page needs no ephemeris of ours anywhere: the
Moon is up wherever you are less than 90 degrees from the sublunar point,
and the sublunar point is published.

Source: eclipse.gsfc.nasa.gov, US government work and public domain, the
same provenance as besselian.json and the decade tables in eclipses.json.
"""
import json
import re
import sys
import urllib.request

SRC = "https://eclipse.gsfc.nasa.gov/LEcat5/LE2001-2100.html"
OUT = "lunar.json"
MONTHS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}

# One catalogue row. Everything is positional and single-spaced once the
# markup is gone, so this is a transcription of the column layout:
#
#   09709 2026 Aug 28 04:14:04 75 329 138 P t- 0.4964 1.9645 0.9299
#         337.8 198.1 - 9S 63W
#
#   num  year mon day  TD of greatest  dT  lunation  saros  type  QSE
#   gamma  penumbral-mag  umbral-mag  pen-min  partial-min  total-min
#   zenith-lat zenith-lon
#
# The type is \S+ rather than \w+: a total eclipse is written "T+" or "T-"
# depending on which node it happens at, and matching only word characters
# silently dropped four of our twenty-two.
ROW = re.compile(
    r"(\d{5}) (\d{4}) (\w{3}) (\d\d) (\d\d):(\d\d):(\d\d) (\d+) (\d+) (\d+) "
    r"(\S+) (\S+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) ([\d.]+|-) ([\d.]+|-) "
    r"([\d.]+|-) (\d+[NS]) (\d+[EW])")

KIND = {"T": "total", "P": "partial", "N": "penumbral"}


def _signed(text):
    """"9S" -> -9.0, "63W" -> -63.0. North and east positive, like
    everything else in this repo."""
    value = float(text[:-1])
    return -value if text[-1] in "SW" else value


def _minutes(text):
    return None if text == "-" else float(text)


def parse(raw):
    """Every lunar eclipse in the catalogue, keyed by date."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    out = {}
    for m in ROW.finditer(text):
        g = m.groups()
        key = f"{g[1]}-{MONTHS[g[2]]:02d}-{int(g[3]):02d}"
        out[key] = dict(
            # TD, not UT. The page converts with dT, the same way
            # besselian.py does, rather than storing a number that looks
            # like a clock time and is not one.
            td=int(g[4]) + int(g[5]) / 60.0 + int(g[6]) / 3600.0,
            dT=int(g[7]),
            saros=int(g[9]),
            kind=KIND.get(g[10][0], "penumbral"),
            gamma=float(g[12]),
            pen_mag=float(g[13]),
            um_mag=float(g[14]),
            pen_min=_minutes(g[15]),
            par_min=_minutes(g[16]),
            tot_min=_minutes(g[17]),
            zen_lat=_signed(g[18]),
            zen_lon=_signed(g[19]),
        )
    return out


def main():
    try:
        raw = urllib.request.urlopen(SRC, timeout=30).read().decode(
            "utf-8", "replace")
    except OSError as ex:                              # noqa: BLE001
        print(f"could not fetch {SRC}: {ex}")
        return 1
    catalogue = parse(raw)
    print(f"{len(catalogue)} lunar eclipses in the catalogue")

    rows = [e for e in json.load(open("eclipses.json")) if "when_utc" in e]
    keys = [e["when_utc"][:10] for e in rows if "lunar" in e["type"]]
    out, missing = {}, []
    for key in keys:
        if key not in catalogue:
            missing.append(key)
            continue
        out[key] = catalogue[key]
        d = out[key]
        print(f"  {key}  {d['kind']:10s} umbral mag {d['um_mag']:+.4f}  "
              f"gamma {d['gamma']:+.4f}")
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(f"\n{OUT}: {len(out)} of {len(keys)} eclipses")
    for key in missing:
        print(f"  MISSING {key}: not in the catalogue")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
