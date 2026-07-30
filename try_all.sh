#!/usr/bin/env bash
# Every parameter, one command each. Pauses between so you can look.
# Run all:        ./try_all.sh
# No pausing:     ./try_all.sh -q
# One section:    ./try_all.sh places | views | find | output | edges
cd "$(dirname "$0")"
N=2026-07-30T22:00
Q=0; [ "$1" = "-q" ] && { Q=1; shift; }
SECT=${1:-all}
run() { printf '\n\033[1;36m$ %s\033[0m\n' "$*"; "$@"; [ $Q -eq 0 ] && read -rp $'\n-- enter --' _; }

if [ "$SECT" = all ] || [ "$SECT" = places ]; then
run python3 cli.py
run python3 cli.py Zurich "$N"
run python3 cli.py Tokyo "$N"
run python3 cli.py Sydney 2026-07-30T21:00
run python3 cli.py Nairobi 2026-07-30T21:00
run python3 cli.py "San Francisco, US" "$N"
run python3 cli.py "Paris, TX" "$N"
run python3 cli.py "Paris, FR" "$N"
run python3 cli.py "London, Canada" "$N"
run python3 cli.py "Springfield, IL" "$N"
run python3 cli.py nyc "$N"
run python3 cli.py bombay "$N"
run python3 cli.py 47.38,8.54 "$N"
run python3 cli.py -33.87,151.21 2026-07-30T21:00
run python3 cli.py 0,0 "$N"
fi

if [ "$SECT" = all ] || [ "$SECT" = views ]; then
run python3 cli.py Zurich "$N" --disc
run python3 cli.py Zurich "$N" --facing=N
run python3 cli.py Zurich "$N" --facing=NNW --span=90
run python3 cli.py Zurich "$N" --facing=S --span=180
run python3 cli.py Zurich "$N" --facing=270 --span=120
run python3 cli.py Zurich "$N" --facing=E --span=30
run python3 cli.py Zurich "$N" --nolines
run python3 cli.py Tokyo 2026-07-30T12:00
run python3 cli.py Tokyo 2026-07-30T12:00 --night
fi

if [ "$SECT" = all ] || [ "$SECT" = find ]; then
run python3 cli.py Zurich "$N" --find=Venus
run python3 cli.py Zurich "$N" --find=Mars
run python3 cli.py Zurich "$N" --find=Jupiter
run python3 cli.py Zurich "$N" --find=Saturn
run python3 cli.py Zurich "$N" --find=Mercury
run python3 cli.py Zurich "$N" --find=Moon
run python3 cli.py Zurich "$N" --find=Vega
run python3 cli.py Zurich "$N" --find=Polaris
run python3 cli.py Zurich "$N" "--find=Big Dipper"
run python3 cli.py Zurich "$N" "--find=Summer Triangle"
run python3 cli.py Sydney 2026-07-30T21:00 "--find=Southern Cross"
run python3 cli.py Zurich 2026-12-21T22:00 --find=Orion
run python3 cli.py Zurich "$N" --find=Venus --span=120
fi

if [ "$SECT" = all ] || [ "$SECT" = output ]; then
run python3 cli.py Zurich "$N" --plain
run python3 cli.py Zurich "$N" --json
run python3 cli.py Zurich "$N" --find=Venus --json
run python3 cli.py Zurich "$N" --iss
run python3 cli.py --help
fi

if [ "$SECT" = all ] || [ "$SECT" = edges ]; then
run python3 cli.py Reykjavik 2026-06-21T23:00
run python3 cli.py Reykjavik 2026-12-21T13:00
run python3 cli.py "Tromso, NO" 2026-12-21T12:00
run python3 cli.py 89,0 "$N"
run python3 cli.py Zurich 2026-08-12T23:00
run python3 cli.py Atlantis
run python3 cli.py Zurich "$N" --find=wombat
run python3 cli.py Zurich notadate
run python3 cli.py Zurich 2400-01-01T00:00
fi
