#!/usr/bin/env python3
"""
Where each object's name came from.

The third block on /{object}/history, after what it is called and what
happened to it. Names are the most durable thing on this site: an altitude
is redrawn every five minutes, a blurb can be rewritten, and an etymology
was fixed in the ninth century.

Hand-written here, like blurbs.py and facts.py, for the same reason and one
more. The reason: there is nowhere permissive to take this from -- Wikipedia
is CC BY-SA and close paraphrase of it is still derivative. The extra one:
the standard free source, R. H. Allen's *Star Names* of 1899, is public
domain and unreliable. Kunitzsch, the authority on Arabic star names, judged
it "generally unreliable with regard to star names and their derivations",
and rewording an 1899 guess into fresh prose removes the one signal a reader
had that it was a guess.

So: where scholarship genuinely disagrees, `unsure` says so on the page
rather than the entry picking a side quietly. Nobody being certain is
itself the interesting answer, and it is the honest one.

    from      the language it came out of
    reading   the original script, then a transliteration
    literal   what the words mean, in as few words as possible
    story     one or two sentences -- what happened to it on the way here
    unsure    names the disagreement, or absent

Original scripts sit at the end of `reading` and never in a column anything
has to line up after: a non-Latin run falls back to a proportional face and
smears a monospace grid. The transliteration is always present, so the line
still reads when a font comes up short.
"""

ETYMOLOGY = {

    # ------------------------------------------------------- solar system
    # The five naked-eye planets are one Babylonian list translated four
    # times: Babylon named them for gods, Greek astronomers took the
    # assignments over in the Hellenistic period, Rome translated the Greek
    # gods into Latin ones, and Germanic peoples translated the Latin ones
    # again for the weekdays. Almost every planet name on Earth is somewhere
    # on that chain.
    "Sun": {
        "from": "Old English",
        "reading": "sunne",
        "literal": "the sun",
        "story": "From the same root as Latin sol and Greek helios, and one "
                 "of the oldest words that can be reconstructed. Germanic "
                 "made it feminine, which is why German still has die Sonne "
                 "against a masculine Mond.",
    },
    "Moon": {
        "from": "Old English",
        "reading": "mona",
        "literal": "the measurer",
        "story": "The same root as month and as measure. The moon is the "
                 "thing you count with, and the merge is near-universal: "
                 "Finnish kuu, Turkish ay, Hebrew yareach and Chinese yue "
                 "all mean both the moon and the month, in four unrelated "
                 "families.",
    },
    "Mercury": {
        "from": "Latin",
        "reading": "Mercurius",
        "literal": "of merchandise",
        "story": "From merx, goods for sale: the god of trade, matched to "
                 "Babylonian Nabu, the scribe. The metal is named after the "
                 "planet rather than the other way round, which is why "
                 "Swahili calls it Zebaki, from the Arabic for quicksilver.",
    },
    "Venus": {
        "from": "Latin",
        "reading": "Venus",
        "literal": "desire, charm",
        "story": "The same root as venerate, and as venom, which began as a "
                 "love potion. Venus carries two names in almost every "
                 "tradition, because the morning star and the evening star "
                 "were taken for two objects for a very long time: Greek had "
                 "Phosphoros and Hesperos, Czech has Jitrenka and Vecernice.",
    },
    "Mars": {
        "from": "Latin",
        "reading": "Mars, older Mavors",
        "literal": "unknown",
        "story": "The god of war, matched to Babylonian Nergal, god of "
                 "plague. The Greeks had called the planet Pyroeis, the "
                 "fiery one, for its colour, and half the world's names for "
                 "it still describe the colour rather than the god.",
        "unsure": "The root of Mars itself is not known. An Etruscan origin "
                  "is often proposed and cannot be shown.",
    },
    "Jupiter": {
        "from": "Latin",
        "reading": "Iuppiter",
        "literal": "sky father",
        "story": "The oldest name in the sky. It is the same phrase as Greek "
                 "Zeus pater and Sanskrit Dyaus Pitar, all three descended "
                 "from one reconstructed form, and it is why Thursday and "
                 "jeudi are the same day named twice: once by translating "
                 "the god into Thor, once by keeping him.",
    },
    "Saturn": {
        "from": "Latin",
        "reading": "Saturnus",
        "literal": "unknown",
        "story": "The Romans linked it to serere, to sow, which is folk "
                 "etymology. Persian still calls the planet Keyvan, straight "
                 "from Babylonian Kajamanu, the steady one, a name for its slowness that has been in use for about 2,500 years.",
        "unsure": "Probably Etruscan, from Satre, but the Roman derivation "
                  "from sowing is a guess made after the fact.",
    },
    "Uranus": {
        "from": "Greek",
        "reading": "Ouranos",
        "literal": "sky",
        "story": "The only planet with a Greek rather than a Roman name, and "
                 "the only one whose naming was an argument. Herschel wanted "
                 "Georgium Sidus for the king; Bode proposed Uranus in 1782 "
                 "and it took most of a century to settle.",
    },
    "Neptune": {
        "from": "Latin",
        "reading": "Neptunus",
        "literal": "unknown, god of water",
        "story": "Chosen in 1846 within weeks of the discovery, over Le "
                 "Verrier's own preference, which was to name it after "
                 "himself.",
        "unsure": "The root is disputed. A link to Vedic Apam Napat, child "
                  "of the waters, is a serious proposal and not settled.",
    },

    # ------------------------------------------------------------- stars
    # Roughly two thirds of the named stars carry Arabic names, and they are
    # one story told many times: Ptolemy's Greek positional descriptions were
    # translated into Arabic, clipped into single words, then transliterated
    # by medieval Latin scribes who did not read Arabic. The errors froze.
    "Betelgeuse": {
        "from": "Arabic",
        "reading": "Yad al-Jawza'  ·  يد الجوزاء",
        "literal": "hand of Jawza",
    },
    "Rigel": {
        "from": "Arabic",
        "reading": "Rijl al-Jawza'  ·  رجل الجوزاء",
        "literal": "foot of Jawza",
        "story": "The same figure as Betelgeuse, at the other end. Orion's "
                 "two brightest stars are the hand and the foot of one body "
                 "that Arab astronomers saw where the Greeks saw a hunter.",
    },
    "Aldebaran": {
        "from": "Arabic",
        "reading": "al-Dabaran  ·  الدبران",
        "literal": "the follower",
    },
    "Vega": {
        "from": "Arabic",
        "reading": "al-Waqi'  ·  الواقع",
        "literal": "the falling one",
        "story": "From an-nasr al-waqi', the falling eagle. Altair is "
                 "at-ta'ir, the flying one, so two thirds of the Summer "
                 "Triangle is a pair of birds.",
    },
    "Altair": {
        "from": "Arabic",
        "reading": "al-Ta'ir  ·  الطائر",
        "literal": "the flying one",
    },
    "Deneb": {
        "from": "Arabic",
        "reading": "dhanab  ·  ذنب",
        "literal": "tail",
    },
    "Algol": {
        "from": "Arabic",
        "reading": "al-Ghul  ·  الغول",
        "literal": "the ghoul",
    },
    "Sirius": {
        "from": "Greek",
        "reading": "Seirios  ·  Σείριος",
        "literal": "scorching",
        "story": "Its rising with the Sun opened the hottest weeks of the "
                 "Mediterranean year, which is where dog days comes from: the constellation is the Great Dog and the star is its "
                 "brightest.",
    },
    "Arcturus": {
        "from": "Greek",
        "reading": "Arktouros  ·  Ἀρκτοῦρος",
        "literal": "bear guard",
    },
    "Antares": {
        "from": "Greek",
        "reading": "Antares  ·  Ἀντάρης",
        "literal": "rival of Ares",
    },
    "Procyon": {
        "from": "Greek",
        "reading": "Prokyon  ·  Προκύων",
        "literal": "before the dog",
        "story": "It rises shortly before Sirius. Another name that is a "
                 "piece of practical instruction rather than a description.",
    },
    "Polaris": {
        "from": "Latin",
        "reading": "stella polaris",
        "literal": "the pole star",
        "story": "A recent name for a temporary job. Precession moves the "
                 "pole about a degree every 72 years, so Thuban held the "
                 "post 4,700 years ago and Vega will hold it in 12,000.",
    },
    "Regulus": {
        "from": "Latin",
        "reading": "Regulus",
        "literal": "little king",
        "story": "Coined by Copernicus, calquing older names that all say "
                 "the same thing: Greek Basiliskos, Arabic Qalb al-Asad, "
                 "the lion's heart, and Babylonian Sharru, the king.",
    },
    "Capella": {
        "from": "Latin",
        "reading": "capella",
        "literal": "little she-goat",
    },

    # ---------------------------------------------------------- deep sky
    "Pleiades": {
        "from": "Greek",
        "reading": "Pleiades  ·  Πλειάδες",
        "literal": "disputed",
        "story": "The best-named object in the sky, because almost every "
                 "tradition named it separately: Subaru in Japanese, "
                 "gathered together; Krittika in Sanskrit, the first of the "
                 "27 nakshatras; Matariki in Maori, which opens the year; "
                 "al-Thurayya in Arabic, the abundant one. What they share "
                 "is the count: nearly everyone says seven, and six is all "
                 "most people can see.",
        "unsure": "The Greek name has been derived from plein, to sail, "
                  "from pleios, full, and from the mother Pleione. None is "
                  "settled.",
    },
    "Andromeda Galaxy": {
        "from": "Greek",
        "reading": "Andromeda  ·  Ἀνδρομέδα",
        "literal": "ruler of men",
    },
    "Crab Nebula": {
        "from": "English",
        "reading": "Crab Nebula",
        "literal": "a crab",
    },
    "Milky Way": {
        "from": "Greek, through Latin",
        "reading": "galaxias kyklos  ·  γαλαξίας κύκλος",
        "literal": "milky circle",
        "story": "Calqued into Latin as via lactea and then into every "
                 "European language, while galaxias itself gave the word "
                 "galaxy. Elsewhere it is usually a river or a road: Chinese "
                 "yinhe, the silver river, and Sanskrit Akashaganga, the "
                 "Ganges of the sky.",
    },
}


FIELD_ORDER = [
    ("from", "From"),
    ("reading", "Reading"),
    ("literal", "Literally"),
]


# ------------------------------------------------------------- the figures
#
# Three shapes, and which one an entry gets is a claim about the name rather
# than a layout preference.
#
#   descent    one line of transmission, and usually something lost on the
#              way. The break marker is the point of the figure: it says
#              where the MEANING went, not merely where the spelling did.
#   branch     a descent that forks, for the planets -- one Babylonian list
#              translated twice into the same week, which is why Thursday
#              and jeudi are the same day named twice.
#   converge   arrows pointing inward, for names with no common ancestor.
#              Drawing the Pleiades as a descent would invent a relationship
#              that does not exist, so the figure refuses to.
#
# Stages carry romanised text only. A non-Latin run inside a box-drawn
# figure falls back to a proportional face and smears every rule around it;
# the original scripts live in `reading`, at the end of a value, where
# nothing has to line up after them.

# A stage is (kind, when, romanised, script). The script is optional and
# always sits on a line of its OWN inside the figure, never beside the
# romanised text: a right-to-left run next to a box-drawing rail reorders
# what a reader sees, and one on a line by itself has nothing to reorder
# with. That is what makes the original scripts safe here after all.
STAGES = {
    "Betelgeuse": ("descent", [
        ("Greek", "Ptolemy, 150", "he tou omou, the one on the shoulder",
         "ἡ τοῦ ὤμου"),
        ("Arabic", "9th c.", "Yad al-Jawza', hand of Jawza", "يد الجوزاء"),
        ("break", "c.1100", "ya read as ba, one dot moved", "ي  ب"),
        ("Arabic", "", "Bat al-Jawza', which means nothing", "بط الجوزاء"),
        ("Latin", "c.1250", "Bedalgeuze, Alfonsine Tables", None),
        ("English", "now", "Betelgeuse", None),
    ]),
    "Rigel": ("descent", [
        ("Greek", "Ptolemy, 150", "the bright one of the left foot", None),
        ("Arabic", "9th c.", "Rijl al-Jawza', foot of Jawza",
         "رجل الجوزاء"),
        ("Latin", "c.1250", "Algebar, then Rigel", None),
        ("English", "now", "Rigel", None),
    ]),
    "Vega": ("descent", [
        ("Arabic", "9th c.", "an-nasr al-waqi', the falling eagle",
         "النسر الواقع"),
        ("break", "medieval", "the bird is dropped, only 'falling' kept",
         None),
        ("Latin", "c.1250", "Vega", None),
        ("English", "now", "Vega", None),
    ]),
    "Algol": ("descent", [
        ("Greek", "", "the Gorgon's head, in Perseus", "Γοργόνειον"),
        ("Arabic", "9th c.", "ra's al-ghul, head of the ghoul",
         "رأس الغول"),
        ("Latin", "medieval", "Algol", None),
        ("English", "now", "Algol, and ghoul, the same word", None),
    ]),
    "Jupiter": ("branch", [
        ("Babylon", "", "Marduk, the city god of Babylon", None),
        ("Greece", "4th c. BC", "Zeus, taking the Babylonian assignment",
         "Ζεύς"),
        ("Rome", "", "Iuppiter, from dyeus phter, sky father", None),
        ("fork", "", "dies Iovis  to  jeudi, giovedi, jueves", None),
        ("North", "c.400", "Thor's day, and so Thursday", None),
    ]),
    "Mars": ("branch", [
        ("Babylon", "", "Nergal, god of plague", None),
        ("Greece", "4th c. BC", "Ares, before that Pyroeis, the fiery one",
         "Ἄρης"),
        ("Rome", "", "Mars", None),
    ]),
    # The weekday branch used to hang here: dies Martis into mardi and
    # martes, and the Germanic swap that made it Tuesday. Both were the name
    # of the DAY descending, not the name of the planet, and no Germanic
    # word for the planet itself is attested at all. Two of five rows about
    # something the page is not about is most of the figure.
    "Saturn": ("descent", [
        ("Babylon", "", "Kajamanu, the steady one", None),
        ("Persia", "", "Keyvan, the same word, still in use", "کیوان"),
        ("Greece", "4th c. BC", "Kronos, before that Phainon, the shining",
         "Κρόνος"),
        ("Rome", "", "Saturnus", None),
        ("English", "now", "Saturn, and Saturday", None),
    ]),
    "Pleiades": ("converge", [
        ("Greek", "Pleiades"),
        ("Arabic", "al-Thurayya"),
        ("Sanskrit", "Krittika"),
        ("Japanese", "Subaru"),
        ("Maori", "Matariki"),
    ], "no shared root: five traditions named it five times, and "
       "four of them counted seven where six are all most people see"),
    "Milky Way": ("converge", [
        ("Greek", "galaxias kyklos, milky circle"),
        ("Latin", "via lactea, the same picture"),
        ("Chinese", "yinhe, the silver river"),
        ("Sanskrit", "Akashaganga, the Ganges of the sky"),
    ], "milk in Europe, a river almost everywhere else"),
}


def _descent_lines(stages, branch=False):
    """A left rail, so the stages read as one descent rather than a stack.

    The break marker is a real row rather than a note on the row after it:
    a reader should be able to see where the meaning was lost without
    reading the words.
    """
    out = []
    last = len(stages) - 1
    for i, stage in enumerate(stages):
        kind, when, text = stage[0], stage[1], stage[2]
        script = stage[3] if len(stage) > 3 else None
        if i == 0:
            rail = "┌"           # top of the rail
        elif i == last:
            rail = "└"           # and the foot of it
        else:
            rail = "├"
        if kind == "break":
            head = f"✕ {when}" if when else "✕"
        elif kind == "fork":
            head = "and sideways, into the week"
        else:
            head = f"{kind} · {when}" if when else kind
        out.append((f"{rail} {head}", False))
        cont = " " if i == last else "│"
        out.append((f"{cont} {text}", False))
        if script:
            # Its own line, flagged so the browser can isolate the run. A
            # right-to-left script sharing a line with a rail character
            # reorders around it; alone, there is nothing to reorder with.
            out.append((f"{cont} {script}", True))
        if i != last:
            out.append(("│", False))
    return out


def _converge_lines(rows, note):
    """Arrows inward, not downward. These names share no ancestor and the
    figure has to say so on its face."""
    wl = max(len(a) for a, _b in rows)
    wv = max(len(b) for _a, b in rows)
    out, n = [], len(rows)
    for i, (lang, name) in enumerate(rows):
        if i == 0:
            j = "┐"
        elif i == n - 1:
            j = "┘"
        elif i == n // 2:
            j = "┼──▶"
        else:
            j = "┤"
        out.append((f"{lang.ljust(wl)}  {name.ljust(wv)}  ─{j}", False))
    out.append(("", False))
    out += [("  " + l, False) for l in _wrap(note, 62)]
    return out


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}" if line else w
    if line:
        out.append(line)
    return out


def figure_rows(name):
    """The figure as (line, is_script) pairs, or empty.

    One figure per name, chosen by what the name actually did. Everything
    except the script lines is box-drawing and ASCII, which both bundled
    fonts carry, so the same figure reaches a terminal and a browser.

    is_script marks a line holding an original script and nothing else. A
    browser isolates those so a right-to-left run cannot reorder around the
    rail beside it; a terminal prints them as they are.
    """
    spec = STAGES.get(name)
    if not spec:
        return []
    kind = spec[0]
    if kind in ("descent", "branch"):
        return _descent_lines(spec[1], branch=(kind == "branch"))
    return _converge_lines(spec[1], spec[2])


def figure_lines(name):
    """The figure as plain lines, for a terminal."""
    return [text for text, _script in figure_rows(name)]


def rows_for(name):
    """The etymology as printable (label, value) rows, or empty."""
    rec = ETYMOLOGY.get(name)
    if not rec:
        return []
    return [(label, rec[key]) for key, label in FIELD_ORDER if rec.get(key)]


def prose_for(name):
    """The story, and the disagreement where there is one."""
    rec = ETYMOLOGY.get(name) or {}
    out = []
    if rec.get("story"):
        out.append(rec["story"])
    if rec.get("unsure"):
        # Marked rather than merged, so a reader can tell a settled reading
        # from a contested one without weighing the prose.
        out.append("Not settled: " + rec["unsure"])
    return out
