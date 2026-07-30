#!/usr/bin/env python3
"""
Keep a fresh ISS element set on disk.

CelesTrak asks that you cache rather than poll per request — element sets are
only issued a few times a day, so one fetch every few hours is both correct and
polite. Run this from cron; the service only ever reads the file.

    */6 * * * * cd /srv/sky && python3 tle.py >> tle.log 2>&1
"""
import os, sys, time, urllib.request, urllib.error

CATNR = 25544                                   # ISS (ZARYA)
URL = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={CATNR}&FORMAT=TLE"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iss.tle")
UA = "skymap.sh/1.0 (+https://skymap.sh; contact: enquiries@habibicode.org)"
MAX_AGE = 6 * 3600                              # refetch after this
STALE_AFTER = 7 * 24 * 3600                     # refuse to use beyond this


def _checksum_ok(line):
    s = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
    return len(line) >= 69 and line[68].isdigit() and s % 10 == int(line[68])


def validate(text):
    """A TLE we would actually trust: two lines, right numbers, checksums pass,
    and SGP4 can propagate it. Returns the cleaned text or raises."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    l1 = next((l for l in lines if l.startswith("1 ")), None)
    l2 = next((l for l in lines if l.startswith("2 ")), None)
    if not l1 or not l2:
        raise ValueError("no TLE lines found")
    if int(l1[2:7]) != CATNR or int(l2[2:7]) != CATNR:
        raise ValueError(f"wrong catalogue number: {l1[2:7]}")
    for l in (l1, l2):
        if not _checksum_ok(l):
            raise ValueError(f"checksum failed: {l[:20]}...")
    from sgp4.api import Satrec, jday                       # propagates?
    sat = Satrec.twoline2rv(l1, l2)
    e, r, _v = sat.sgp4(*jday(*time.gmtime()[:6]))
    if e != 0:
        raise ValueError(f"sgp4 error {e}")
    alt = (sum(x * x for x in r) ** 0.5) - 6378.137
    if not 300 < alt < 500:                                 # ISS lives ~400 km
        raise ValueError(f"implausible altitude {alt:.0f} km")
    name = lines[0] if not lines[0].startswith(("1 ", "2 ")) else "ISS (ZARYA)"
    return f"{name}\n{l1}\n{l2}\n"


def age(path=CACHE):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return float("inf")


def refresh(path=CACHE, force=False):
    """Fetch if stale. Never replaces a good cache with a bad download."""
    if not force and age(path) < MAX_AGE:
        return path, "fresh"
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("ascii", "replace")
        clean = validate(text)
    except (urllib.error.URLError, OSError, ValueError, ImportError) as e:
        if os.path.exists(path):
            return path, f"fetch failed ({e}); keeping cache {age(path)/3600:.1f}h old"
        return None, f"fetch failed ({e}) and no cache"
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(clean)
    os.replace(tmp, path)                       # atomic; readers never see half a file
    return path, "updated"


def current(path=CACHE):
    """Path to a usable element set, or None. Does not fetch — cron does that."""
    if os.path.exists(path) and age(path) < STALE_AFTER:
        return path
    return None


if __name__ == "__main__":
    p, status = refresh(force="--force" in sys.argv)
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {status}"
          + (f"  age {age(p)/3600:.1f}h" if p else ""))
    sys.exit(0 if p else 1)
