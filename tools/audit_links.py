#!/usr/bin/env python3
"""Every name in the copy that has a page and is not linked to it.

Two kinds. A direct hit is a name the site resolves as written. An alias is
a word readers use for something filed under a different name, which is what
the [[Page|words]] form exists for. Self-links are skipped: the Big Dipper
page saying "part of Ursa Major" must not link to itself.
"""
import os, re, sys
# The repo from __file__, never an absolute path: these scripts were rescued
# from a temp directory once already and hardcoding where they live is what
# made that painful.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blurbs, objects, sky

ALIAS = {
    "Alpha Centauri": "Rigil Kentaurus", "Beta Centauri": "Hadar",
    "Bootes": "Kite", "Leo": "Sickle", "Hercules": "Keystone",
    "Sagittarius": "Teapot", "Cassiopeia": "Cassiopeia's W",
    "Cygnus": "Northern Cross", "Ursa Major": "Big Dipper",
    "Ursa Minor": "Little Dipper", "Pegasus": "Great Square",
    "Crux": "Southern Cross", "Delphinus": "Job's Coffin",
}

names = {s["n"] for s in sky._load("stars.json") if s.get("n")}
names |= {o["cn"] for o in sky._load("deepsky.json") if o.get("cn")}
names |= {a["name"] for a in sky._load("asterisms.json")}
names |= {s["name"] for s in sky._load("showers.json")}
names |= set(blurbs.BLURBS)
names = {n for n in names if objects.resolve_name(n)}

# Generic words that are references to the sky rather than to a page.
SKIP = {"Sun", "Moon", "Earth"}

hits = []
for entry, (gloss, para) in sorted(blurbs.BLURBS.items()):
    linked = {m.group(1) for m in re.finditer(r"\[\[([^\]|]+)", para)}
    plain = re.sub(r"\[\[.+?\]\]", " ", para)
    seen = set()
    for word in sorted(names | set(ALIAS), key=len, reverse=True):
        target = ALIAS.get(word, word)
        if target == entry or target in linked or word in seen:
            continue
        # A word inside the entry's own name is not a reference to something
        # else. "The Hercules Cluster is a globular cluster" is not the page
        # mentioning the constellation Hercules, and linking it would send a
        # reader to a different object with a similar name.
        if word in entry:
            continue
        if word in SKIP or target in SKIP:
            continue
        if re.search(r"(?<![\w'-])" + re.escape(word) + r"(?![\w-])", plain):
            hits.append((entry, word, target))
            seen.add(word)

for entry, word, target in hits:
    form = f"[[{target}|{word}]]" if word != target else f"[[{word}]]"
    print(f"{entry:22} {word:20} -> {form}")
print(f"\n{len(hits)} unlinked mentions")
