#!/usr/bin/env python3
"""Replace the one-line glosses in blurbs.py, and nothing else.

    python3 set_glosses.py new-glosses.json      # {"Name": "the gloss", ...}

Deliberately narrower than rewrite_blurbs.py, which replaces whole entries
and would take the section comments between them with it. This walks each
entry from its opening line to the first line ending in `",` -- the gloss
is the only string group that ends that way, since every paragraph line
ends in a bare quote and the last one ends in `"),`.
"""
import io, json, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, "blurbs.py")
WIDTH = 70


def wrap(text, indent="        "):
    out, line = [], ""
    for tok in text.split():
        if line and len(line) + 1 + len(tok) > WIDTH:
            out.append(line + " ")
            line = tok
        else:
            line = f"{line} {tok}" if line else tok
    if line:
        out.append(line)
    esc = [l.replace("\\", "\\\\").replace('"', '\\"') for l in out]
    lines = [f'{indent}"{l}"' for l in esc]
    lines[-1] += ","          # the comma that keeps the tuple a 2-tuple
    return lines


def main(json_path):
    new = json.load(io.open(json_path, encoding="utf-8"))
    lines = io.open(PATH, encoding="utf-8").read().split("\n")
    done, missing = [], []
    for name, gloss in new.items():
        for bad in ("--", "—", "–"):
            if bad in gloss:
                sys.exit(f"refused: {name} gloss contains {bad!r}")
        start = next((i for i, l in enumerate(lines)
                      if l == f'    "{name}": ('), None)
        if start is None:
            missing.append(name)
            continue
        end = start + 1
        while not lines[end].rstrip().endswith('",'):
            end += 1
        lines[start + 1:end + 1] = wrap(gloss)
        done.append(name)
    io.open(PATH, "w", encoding="utf-8").write("\n".join(lines))
    print(f"set {len(done)}")
    if missing:
        print("NOT FOUND:", missing)


if __name__ == "__main__":
    main(sys.argv[1])
