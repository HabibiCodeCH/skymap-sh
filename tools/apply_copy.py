#!/usr/bin/env python3
"""Apply an approved blurb, in one step, the way every approved one has gone in.

    python3 apply_copy.py "Arcturus" < the-new-paragraph.txt

Three things happen together, because doing any one without the others is
what left the earlier entries inconsistent:

  1. blurbs.BLURBS keeps its glyph and takes the new paragraph.
  2. the etymology "story" is deleted. The approved shape is one merged
     paragraph in the blurb plus from/reading/literal as rows, so a story
     left behind prints the same words twice on the page.
  3. the name is added to DONE in build_review.py.

Refuses copy containing an em dash or a double hyphen.
"""
import sys, os, re, io

S = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def apply(name, text):
    text = " ".join(text.split())
    # Straight quotes only. A curly quote pasted in from a document reads
    # identically to the eye and differently to every grep, and normalising
    # it here is the only place it can be done once for all of them.
    for a, b in (("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'")):
        text = text.replace(a, b)
    for bad in ("--", "\u2014", "\u2013"):
        if bad in text:
            sys.exit(f"refused: copy contains {bad!r}")

    p = f"{REPO}/blurbs.py"
    src = io.open(p, encoding="utf-8").read()
    # Anchored on the closing quote-paren-comma that ends an entry, not on
    # the first ")" with a comma after it. Betelgeuse's paragraph contains
    # "(the two letters look alike), giving", which the looser pattern
    # matched as the end of the entry and duplicated everything after it.
    m = re.search(r'(%s: \()(.*?"\),\n)' % re.escape(f'"{name}"'), src, re.S)
    if not m:
        sys.exit(f"no blurb entry for {name!r}")
    # One or more string literals, because a long gloss is wrapped across
    # lines and Python joins them. Hydrus and Ophiuchus are both written
    # that way, and matching a single literal threw on both.
    run = re.match(r'\s*((?:"(?:[^"\\]|\\.)*"\s*)+),', m.group(2))
    if not run:
        sys.exit(f"cannot read the gloss for {name!r}")
    glyph = "\n".join(f'        {s}'
                      for s in re.findall(r'"(?:[^"\\]|\\.)*"', run.group(1)))
    body = text.replace("\\", "\\\\").replace('"', '\\"')
    io.open(p, "w", encoding="utf-8").write(
        src[:m.start()] + f'{m.group(1)}\n{glyph},\n        "{body}"),\n'
        + src[m.end():])

    p = f"{REPO}/etymology.py"
    src = io.open(p, encoding="utf-8").read()
    m = re.search(r'(%s:\s*\{)(.*?)(\n\s*\},)' % re.escape(f'"{name}"'), src, re.S)
    dropped = False
    if m:
        cut = re.sub(r'\n\s*"story":\s*(?:"(?:[^"\\]|\\.)*"\s*)+,', '', m.group(2))
        dropped = cut != m.group(2)
        if dropped:
            io.open(p, "w", encoding="utf-8").write(
                src[:m.start()] + m.group(1) + cut + m.group(3) + src[m.end():])

    p = f"{S}/build_review.py"
    src = io.open(p, encoding="utf-8").read()
    if f'"{name}",' not in src.split("DONE = {")[1].split("}")[0]:
        src = src.replace("\n}\n\nPORT", f'\n    "{name}",{" " * max(1, 21 - len(name))}'
                          f"# blurb + etymology combined 14 Aug\n}}\n\nPORT", 1)
        io.open(p, "w", encoding="utf-8").write(src)
    return dropped


if __name__ == "__main__":
    name = sys.argv[1]
    text = sys.stdin.read()
    dropped = apply(name, text)
    sys.path.insert(0, REPO)
    import blurbs, etymology
    print(f"{name}: blurb set ({len(blurbs.BLURBS[name][1])} chars), "
          f"story {'dropped' if dropped else 'none to drop'}, marked done")
