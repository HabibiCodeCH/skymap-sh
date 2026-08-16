#!/usr/bin/env python3
"""Replace whole BLURBS entries in blurbs.py, keeping the file's shape.

Reads NEW from a JSON file: {"Name": ["gloss", "paragraph"], ...}. Rewraps
each paragraph into implicitly concatenated string literals at the file's
own width, and never lets a [[link]] straddle a line break, which is the
thing that defeats every later search-and-replace over this file.
"""
import json, os, re, sys

# The repo from __file__, for the same reason audit_links.py does it.
PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blurbs.py")
WIDTH = 70          # inside the quotes, at 8 spaces of indent

TOKEN = re.compile(r"\[\[[^\]]+\]\]\S*|\S+")


def wrap(text, indent="        "):
    """One quoted string per line, breaking only between whole tokens and
    never inside a [[marker]]."""
    out, line = [], ""
    for tok in TOKEN.findall(text):
        if line and len(line) + 1 + len(tok) > WIDTH:
            out.append(line + " ")
            line = tok
        else:
            line = f"{line} {tok}" if line else tok
    if line:
        out.append(line)
    # Escaped, because the copy quotes things. Jupiter's paragraph already
    # carries \"Zeus pater\", and an unescaped one here would close the
    # string literal early and leave the file unparseable.
    return [f'{indent}"{l.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
            for l in out]


def main(json_path):
    new = json.load(open(json_path))
    lines = open(PATH).read().split("\n")
    starts = {}
    for i, l in enumerate(lines):
        m = re.match(r'    "(.+?)": \($', l)
        if m:
            starts[m.group(1)] = i
    order = sorted(starts.items(), key=lambda kv: kv[1])
    bounds = {}
    for j, (name, i) in enumerate(order):
        end = order[j + 1][1] if j + 1 < len(order) else len(lines)
        # back up over the blank line and any trailing comment block
        while end > i and not lines[end - 1].strip():
            end -= 1
        bounds[name] = (i, end)

    done, missing = [], []
    for name in sorted(new, key=lambda n: -bounds.get(n, (0, 0))[0]):
        if name not in bounds:
            missing.append(name)
            continue
        gloss, para = new[name]
        lo, hi = bounds[name]
        # The comma matters more than it looks. Without it the gloss and the
        # paragraph sit side by side inside one pair of brackets, Python
        # joins them into a single string, and BLURBS[name] stops being a
        # two-element tuple: unpacking it then yields the first two
        # characters of the gloss.
        gloss_lines = wrap(gloss)
        gloss_lines[-1] += ","
        block = [f'    "{name}": ('] + gloss_lines + wrap(para)
        block[-1] += "),"
        lines[lo:hi] = block
        done.append(name)

    open(PATH, "w").write("\n".join(lines))
    print(f"rewrote {len(done)}")
    if missing:
        print("NOT FOUND:", missing)


if __name__ == "__main__":
    main(sys.argv[1])
