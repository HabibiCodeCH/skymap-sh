#!/usr/bin/env python3
"""
Build cities.json, with the timezone resolved here so the service needs no extra
dependency at runtime.

Source: condwanaland/worldcities — a mirror of the SimpleMaps World Cities basic
database (CC BY 4.0). 41,000 cities with population, ISO country code and
admin area, which is what lets "San Francisco" mean the one in California
rather than the village in Costa Rica.

Timezones from tzfpy (point-in-polygon against the IANA zones). Build-time only:

    pip install tzfpy
    python3 build_cities.py

Output, keyed on the normalised name so each name is stored once and the most
populous city answering to it comes first:

  { "paris": [[48.857, 2.352, "Europe/Paris", "fr", "France", "Ile-de-France",
               11020000, "Paris"], ...] }
"""
import csv, json, re, sys, unicodedata
from collections import defaultdict

SRC, OUT = "wc.csv", "cities.json"
MIN_POP = 1000          # below this nobody is asking, and it halves the file


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    try:
        from tzfpy import get_tz
    except ImportError:
        print("pip install tzfpy"); return 1

    index = defaultdict(list)
    kept = skipped = nozone = 0

    for row in csv.DictReader(open(SRC, encoding="utf-8")):
        try:
            lat, lon = float(row["lat"]), float(row["lng"])
        except (ValueError, KeyError):
            skipped += 1; continue
        try:
            pop = int(float(row["population"] or 0))
        except ValueError:
            pop = 0
        # keep anything flagged as a capital even if it is small
        if pop < MIN_POP and not row.get("capital"):
            skipped += 1; continue
        zone = get_tz(lon, lat)
        if not zone:
            nozone += 1; continue
        entry = [round(lat, 4), round(lon, 4), zone, (row["iso2"] or "").lower(),
                 row["country"], row.get("admin_name") or "", pop,
                 row["city"] or row["city_ascii"]]
        for key in {norm(row["city_ascii"]), norm(row["city"])}:
            if key:
                index[key].append(entry)
        kept += 1

    for k in index:                      # biggest first
        index[k].sort(key=lambda e: -e[6])

    json.dump(index, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)

    dupes = sum(1 for v in index.values() if len(v) > 1)
    print(f"{kept} cities kept, {skipped} below pop {MIN_POP}, {nozone} without a zone")
    print(f"{len(index)} distinct names, {dupes} of them shared")
    for name in ("paris", "london", "sanfrancisco", "springfield", "santiago",
                 "zurich", "newyork"):
        v = index.get(name, [])
        print(f"  {name:13} " + " | ".join(f"{e[7]}, {e[4]} ({e[6]:,})" for e in v[:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
