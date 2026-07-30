#!/usr/bin/env python3
"""
skymap.sh on the command line. Same composition layer the HTTP service uses, so
`python3 cli.py Zurich` and `curl skymap.sh/Zurich` cannot drift apart.

    python3 cli.py                          your sky now (defaults to Zurich)
    python3 cli.py Sydney
    python3 cli.py 47.38,8.54 2026-08-12T23:00
    python3 cli.py Zurich --facing=NNW --span=90
    python3 cli.py Zurich --find="Big Dipper"
    python3 cli.py Zurich --iss --json
"""
import sys, json, datetime as dt
import api, tle

def main(argv):
    if "--help" in argv or "-h" in argv:
        print(api.HELP); return 0
    flags = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else True)
             for a in argv if a.startswith("--")}
    pos = [a for a in argv if not a.startswith("--")]
    when = None
    if len(pos) > 1:
        try:
            when = dt.datetime.fromisoformat(pos[1])
        except ValueError:
            print(f"bad time '{pos[1]}' — use 2026-08-12T23:00"); return 2
    if pos and api.lookup_place(pos[0]) is None:
        print(f"Don't know '{pos[0]}'.")
        near = api.suggest(pos[0])
        if near:
            print("Did you mean:")
            for n in near:
                print(f"  {n}")
        print("Coordinates work too: 47.38,8.54")
        print('Add a country or state when a name repeats: "Paris, TX"')
        return 2
    r = api.Request(
        place=pos[0] if pos else "Zurich",
        when=when,
        view="disc" if flags.get("--disc") else "horizon",
        facing=flags.get("--facing") or None,
        span=float(flags["--span"]) if flags.get("--span") else None,
        find=flags.get("--find") or None,
        lines="--nolines" not in flags,
        night="--night" in flags,
        color="--plain" not in flags,
        tle=(tle.current() or f"{api.sky.BASE}/demo.tle") if "--iss" in flags else None,
    )
    res = api.compose(r)
    print(json.dumps(res.data, indent=2, default=str) if "--json" in flags else res.text)
    return 0 if res.status == 200 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
