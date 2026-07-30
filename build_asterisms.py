#!/usr/bin/env python3
"""
Hand-authored asterism line lists, resolved against Yale BSC5.

Everything here is written from published star designations (Bayer letter +
constellation). No third-party line file is used, so nothing in the output
carries the GPL that Stellarium's skyculture data does.

Each entry: name, then one or more polylines. A polyline is an ordered list of
"<bayer> <Con>" tokens; consecutive tokens are joined by a segment.
"""
import json, re

GREEK = {"alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","zeta":"ζ",
         "eta":"η","theta":"θ","iota":"ι","kappa":"κ","lambda":"λ","mu":"μ",
         "nu":"ν","xi":"ξ","omicron":"ο","pi":"π","rho":"ρ","sigma":"σ",
         "tau":"τ","upsilon":"υ","phi":"φ","chi":"χ","psi":"ψ","omega":"ω"}

A = [
 # --- circumpolar / northern
 ("Big Dipper",      [["eta UMa","zeta UMa","epsilon UMa","delta UMa","gamma UMa",
                       "beta UMa","alpha UMa","delta UMa"]]),
 ("Little Dipper",   [["alpha UMi","delta UMi","epsilon UMi","zeta UMi","beta UMi",
                       "gamma UMi","eta UMi","zeta UMi"]]),
 ("Cassiopeia's W",  [["epsilon Cas","delta Cas","gamma Cas","alpha Cas","beta Cas"]]),
 # --- summer
 ("Northern Cross",  [["alpha Cyg","gamma Cyg","eta Cyg","beta Cyg"],
                      ["delta Cyg","gamma Cyg","epsilon Cyg"]]),
 ("Summer Triangle", [["alpha Lyr","alpha Cyg","alpha Aql","alpha Lyr"]]),
 ("Lyra",            [["alpha Lyr","zeta Lyr","delta Lyr","gamma Lyr","beta Lyr",
                       "zeta Lyr"]]),
 ("Aquila",          [["zeta Aql","gamma Aql","alpha Aql","beta Aql"],
                      ["gamma Aql","delta Aql","lambda Aql"]]),
 ("Keystone",        [["zeta Her","epsilon Her","pi Her","eta Her","zeta Her"]]),
 ("Corona Borealis", [["theta CrB","beta CrB","alpha CrB","gamma CrB","delta CrB",
                       "epsilon CrB","iota CrB"]]),
 ("Kite",            [["alpha Boo","eta Boo","gamma Boo","beta Boo","delta Boo",
                       "epsilon Boo","alpha Boo"]]),
 ("Job's Coffin",    [["alpha Del","beta Del","gamma Del","delta Del","alpha Del"]]),
 ("Teapot",          [["gamma Sgr","delta Sgr","epsilon Sgr","zeta Sgr","phi Sgr",
                       "lambda Sgr","delta Sgr"],
                      ["phi Sgr","sigma Sgr","tau Sgr","zeta Sgr"]]),
 ("Scorpius",        [["beta Sco","delta Sco","pi Sco","rho Sco"],
                      ["delta Sco","alpha Sco","epsilon Sco","mu Sco","zeta Sco",
                       "eta Sco","theta Sco","iota Sco","kappa Sco","lambda Sco"]]),
 # --- autumn
 ("Great Square",    [["alpha Peg","beta Peg","alpha And","gamma Peg","alpha Peg"]]),
 ("Andromeda",       [["alpha And","delta And","beta And","gamma And"]]),
 # --- winter
 ("Orion",           [["alpha Ori","zeta Ori","kappa Ori"],
                      ["gamma Ori","delta Ori","beta Ori"],
                      ["zeta Ori","epsilon Ori","delta Ori"],
                      ["alpha Ori","gamma Ori"]]),
 ("Orion's Belt",    [["zeta Ori","epsilon Ori","delta Ori"]]),
 ("Hyades V",        [["epsilon Tau","delta Tau","gamma Tau"],
                      ["gamma Tau","theta Tau","alpha Tau"]]),
 ("Auriga",          [["alpha Aur","beta Aur","theta Aur","iota Aur","eta Aur",
                       "alpha Aur"]]),
 ("Winter Triangle", [["alpha Ori","alpha CMa","alpha CMi","alpha Ori"]]),
 ("Winter Hexagon",  [["beta Ori","alpha Tau","alpha Aur","beta Gem","alpha CMi",
                       "alpha CMa","beta Ori"]]),
 # --- spring
 ("Sickle",          [["epsilon Leo","mu Leo","zeta Leo","gamma Leo","eta Leo",
                       "alpha Leo"]]),
 ("Spring Triangle", [["alpha Boo","alpha Vir","alpha Leo","alpha Boo"]]),
 ("Great Diamond",   [["alpha Boo","alpha Vir","beta Leo","alpha CVn","alpha Boo"]]),
 # --- southern
 ("Southern Cross",  [["alpha Cru","gamma Cru"], ["beta Cru","delta Cru"]]),
 ("The Pointers",    [["alpha Cen","beta Cen"]]),
 ("False Cross",     [["epsilon Car","delta Vel"], ["iota Car","kappa Vel"]]),
 ("Grus",            [["gamma Gru","lambda Gru","alpha Gru","beta Gru","epsilon Gru",
                       "zeta Gru"]]),
]

stars = json.load(open("stars.json"))
index = {}
for s in stars:
    if s.get("b") and s.get("c"):
        base = re.sub(r"[^α-ω]", "", s["b"])      # drop superscripts
        if base:
            index.setdefault((base, s["c"]), s)             # brightest wins (sorted)

def resolve(tok):
    letter, con = tok.split()
    return index.get((GREEK[letter], con))

out, missing = [], []
for name, polys in A:
    lines, used = [], set()
    for poly in polys:
        seq = []
        for tok in poly:
            st = resolve(tok)
            if st is None:
                missing.append((name, tok)); continue
            seq.append(st["hr"]); used.add(st["hr"])
        if len(seq) > 1:
            lines.append(seq)
    if not lines:
        continue
    mags = [s["m"] for s in stars if s["hr"] in used]
    out.append(dict(name=name, lines=lines, ast=True,
                    lead=round(min(mags), 2), faint=round(max(mags), 2)))

json.dump(out, open("asterisms.json", "w"), separators=(",", ":"))
print(f"{len(out)} asterisms, {sum(len(l) for a in out for l in a['lines'])} vertices")
if missing:
    print("UNRESOLVED:", missing)
for a in out:
    print(f"  {a['name']:18} lines={len(a['lines'])} mag {a['lead']}..{a['faint']}")
