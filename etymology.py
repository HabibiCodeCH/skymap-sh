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

    # ------------------------------------------------------- the 57 figures
    # Two kinds of name in one list, and they behave differently.
    #
    # The asterisms are mostly English and mostly recent: a ladle, a teapot,
    # a kite. There is no descent to trace, so the row says what the words
    # mean and the paragraph carries whatever history there is.
    #
    # The constellations are Latin, usually translating a Greek name that
    # was itself translating a Babylonian one, and the row stops at the
    # Latin. Where that chain is the interesting part it gets a figure
    # instead of a sentence, because a list of four languages is a picture
    # and not a paragraph.
    #
    # `story` is deliberately absent throughout: the origin is written into
    # the blurb, and an entry carrying both prints the same words twice.
    "Big Dipper": {
        "from": "American English",
        "reading": "the Big Dipper",
        "literal": "the big ladle",
    },
    "Little Dipper": {
        "from": "American English",
        "reading": "the Little Dipper",
        "literal": "the little ladle",
    },
    "Cassiopeia's W": {
        "from": "English, after the Greek",
        "reading": "Kassiopeia  ·  Κασσιόπεια",
        "literal": "unknown",
        "unsure": "The queen's name has no agreed derivation. Greek and "
                  "Egyptian origins have both been argued and neither is "
                  "settled.",
    },
    "Northern Cross": {
        "from": "English",
        "reading": "the Northern Cross",
        "literal": "the cross in the north",
    },
    "Summer Triangle": {
        "from": "English",
        "reading": "the Summer Triangle",
        "literal": "the summer triangle",
        "unsure": "Who named it is not settled. Oswald Thomas used "
                  "Sommerdreieck in the 1920s and Patrick Moore is usually "
                  "credited with the English name in the 1950s.",
    },
    "Lyra": {
        "from": "Latin, from Greek",
        "reading": "Lyra  ·  λύρα",
        "literal": "the lyre",
    },
    "Aquila": {
        "from": "Latin",
        "reading": "Aquila",
        "literal": "the eagle",
    },
    "Keystone": {
        "from": "English",
        "reading": "the Keystone",
        "literal": "the wedge at the top of an arch",
    },
    "Corona Borealis": {
        "from": "Latin",
        "reading": "Corona Borealis",
        "literal": "the northern crown",
    },
    "Kite": {
        "from": "English",
        "reading": "the Kite",
        "literal": "a kite",
    },
    "Job's Coffin": {
        "from": "English",
        "reading": "Job's Coffin",
        "literal": "the coffin of Job",
        "unsure": "No origin is recorded. The name turns up in English in the "
                  "1800s already in use, with nothing said about what Job has "
                  "to do with it.",
    },
    "Teapot": {
        "from": "English",
        "reading": "the Teapot",
        "literal": "a teapot",
    },
    "Scorpius": {
        "from": "Latin, from Greek",
        "reading": "Scorpius  ·  Σκορπίος",
        "literal": "the scorpion",
    },
    "Great Square": {
        "from": "English",
        "reading": "the Great Square",
        "literal": "the great square",
    },
    "Andromeda": {
        "from": "Greek",
        "reading": "Andromeda  ·  Ἀνδρομέδα",
        "literal": "ruler of men",
    },
    "Orion": {
        "from": "Greek",
        "reading": "Orion  ·  Ὠρίων",
        "literal": "unknown",
        "unsure": "Derivations from Akkadian Uru-anna, light of heaven, and "
                  "from a Greek word for urine, after the birth story, have "
                  "both been proposed. Neither is established.",
    },
    "Orion's Belt": {
        "from": "English",
        "reading": "Orion's Belt",
        "literal": "the belt of Orion",
    },
    "Hyades V": {
        "from": "English, after the Greek",
        "reading": "Hyades  ·  Ὑάδες",
        "literal": "disputed",
        "unsure": "Read as the rainers, from hyein, to rain, and as the "
                  "piglets, from hys, a pig, which is how Latin took it: "
                  "Suculae, the little pigs.",
    },
    "Auriga": {
        "from": "Latin",
        "reading": "Auriga",
        "literal": "the charioteer",
    },
    "Winter Triangle": {
        "from": "English",
        "reading": "the Winter Triangle",
        "literal": "the winter triangle",
    },
    "Winter Hexagon": {
        "from": "English",
        "reading": "the Winter Hexagon",
        "literal": "the winter hexagon",
    },
    "Sickle": {
        "from": "English",
        "reading": "the Sickle",
        "literal": "a curved reaping blade",
    },
    "Spring Triangle": {
        "from": "English",
        "reading": "the Spring Triangle",
        "literal": "the spring triangle",
    },
    "Great Diamond": {
        "from": "English",
        "reading": "the Great Diamond",
        "literal": "the great diamond",
    },
    "Southern Cross": {
        "from": "Latin",
        "reading": "Crux",
        "literal": "the cross",
    },
    "The Pointers": {
        "from": "English",
        "reading": "the Pointers",
        "literal": "the ones that point",
    },
    "False Cross": {
        "from": "English",
        "reading": "the False Cross",
        "literal": "the false cross",
    },
    "Grus": {
        "from": "Latin",
        "reading": "Grus",
        "literal": "the crane",
    },
    "Canis Major": {
        "from": "Latin",
        "reading": "Canis Maior",
        "literal": "the greater dog",
    },
    "Canis Minor": {
        "from": "Latin",
        "reading": "Canis Minor",
        "literal": "the lesser dog",
    },
    "Gemini": {
        "from": "Latin",
        "reading": "Gemini",
        "literal": "the twins",
    },
    "Virgo": {
        "from": "Latin",
        "reading": "Virgo",
        "literal": "the maiden",
    },
    "Canes Venatici": {
        "from": "Latin",
        "reading": "Canes Venatici",
        "literal": "the hunting dogs",
    },
    "Centaurus": {
        "from": "Latin, from Greek",
        "reading": "Kentauros  ·  Κένταυρος",
        "literal": "the centaur",
        "unsure": "The Greek word itself has no agreed derivation.",
    },
    "Carina": {
        "from": "Latin",
        "reading": "Carina",
        "literal": "the keel",
    },
    "Vela": {
        "from": "Latin",
        "reading": "Vela",
        "literal": "the sails",
    },
    "Puppis": {
        "from": "Latin",
        "reading": "Puppis",
        "literal": "the stern",
    },
    "Aquarius": {
        "from": "Latin",
        "reading": "Aquarius",
        "literal": "the water carrier",
    },
    "Aries": {
        "from": "Latin",
        "reading": "Aries",
        "literal": "the ram",
    },
    "Capricornus": {
        "from": "Latin",
        "reading": "Capricornus",
        "literal": "goat horned",
    },
    "Cepheus": {
        "from": "Greek",
        "reading": "Kepheus  ·  Κηφεύς",
        "literal": "unknown",
        "unsure": "The king's name has no agreed derivation.",
    },
    "Cetus": {
        "from": "Latin, from Greek",
        "reading": "ketos  ·  κῆτος",
        "literal": "sea monster",
    },
    "Columba": {
        "from": "Latin",
        "reading": "Columba",
        "literal": "the dove",
    },
    "Corvus": {
        "from": "Latin",
        "reading": "Corvus",
        "literal": "the crow",
    },
    "Draco": {
        "from": "Latin, from Greek",
        "reading": "drakon  ·  δράκων",
        "literal": "the one that stares",
    },
    "Eridanus": {
        "from": "Greek",
        "reading": "Eridanos  ·  Ἠριδανός",
        "literal": "a river, otherwise unknown",
        "unsure": "The Greeks identified the river with the Po and sometimes "
                  "the Nile, but the name is older than either and has no "
                  "settled derivation.",
    },
    "Hydra": {
        "from": "Greek",
        "reading": "hydra  ·  ὕδρα",
        "literal": "water snake",
    },
    "Hydrus": {
        "from": "Latin, from Greek",
        "reading": "Hydrus",
        "literal": "the male water snake",
    },
    "Lepus": {
        "from": "Latin",
        "reading": "Lepus",
        "literal": "the hare",
    },
    "Libra": {
        "from": "Latin",
        "reading": "Libra",
        "literal": "the scales",
    },
    "Ophiuchus": {
        "from": "Greek",
        "reading": "Ophiouchos  ·  Ὀφιοῦχος",
        "literal": "serpent bearer",
    },
    "Pavo": {
        "from": "Latin",
        "reading": "Pavo",
        "literal": "the peacock",
    },
    "Perseus": {
        "from": "Greek",
        "reading": "Perseus  ·  Περσεύς",
        "literal": "unknown",
        "unsure": "Usually linked to perthein, to destroy, which does not "
                  "account for the whole name and is not agreed.",
    },
    "Phoenix": {
        "from": "Latin, from Greek",
        "reading": "phoinix  ·  φοῖνιξ",
        "literal": "the phoenix, and also purple red",
    },
    "Piscis Austrinus": {
        "from": "Latin",
        "reading": "Piscis Austrinus",
        "literal": "the southern fish",
    },
    "Serpens": {
        "from": "Latin",
        "reading": "Serpens",
        "literal": "the serpent",
    },
    "Triangulum Australe": {
        "from": "Latin",
        "reading": "Triangulum Australe",
        "literal": "the southern triangle",
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
    # A cluster and not a descent, which is the whole claim. Latin did not
    # take this from Greek: three languages inherited one phrase separately,
    # and a top-to-bottom figure would say the opposite on its face.
    #
    # The weekday branch that used to hang here went for the same reason it
    # went from Mars. dies Iovis into jeudi, and the Germanic swap that made
    # it Thursday, are the name of the DAY descending, not the planet's.
    "Jupiter": ("cluster",
                "*dyeus pater", '"sky father", reconstructed',
                [("Latin",    "Iuppiter",    "",          "and so Jupiter"),
                 ("Greek",    "Zeu pater",   "\u0396\u03b5\u1fe6 \u03c0\u03ac\u03c4\u03b5\u03c1",
                  "vocative, in Homer"),
                 ("Sanskrit", "Dyaus Pitar",
                  "\u0926\u094d\u092f\u094c\u0937\u094d\u092a\u093f\u0924\u0943",
                  "in the Rigveda")]),
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
        # "and Saturday" came off here for the same reason the weekday
        # branches came off Mars and Jupiter: that is the name of the DAY
        # descending, not the planet's. The row itself stays, because
        # "Saturn" on it is the planet's English name and the end of the
        # line this figure is drawing.
        ("English", "now", "Saturn", None),
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

    # -------------------------------------------------------- the 57 figures
    # Ten of the 57 earn one. The other 47 are a Latin word for an animal,
    # and a two-row figure saying Latin, then English, is a box drawn around
    # nothing. What earns a figure here is a name that moved: a meaning lost
    # (Libra, Aries), a figure that survived intact for 3,000 years
    # (Capricornus), a shape every tradition named for itself (the Big
    # Dipper, Orion's Belt), or one constellation becoming three (Argo).
    "Libra": ("descent", [
        ("Babylon", "", "Zibanitu, the scales", None),
        ("break", "", "the scales are dropped, and the stars become the "
                      "scorpion's claws", None),
        ("Greece", "2nd c.", "Chelai, the claws", "Χηλαί"),
        ("Rome", "1st c. BC", "Libra, weighed again", None),
        ("English", "now", "Libra, with the claws left in the star names",
         None),
    ]),
    "Scorpius": ("descent", [
        ("Babylon", "", "Girtab, the scorpion", None),
        ("Greece", "", "Skorpios", "Σκορπίος"),
        ("break", "1st c. BC", "the claws are cut off to make Libra", None),
        ("Rome", "", "Scorpius, without them", None),
        ("English", "now", "Scorpius", None),
    ]),
    # The one that did not change. Every other figure on this page lost
    # something on the way; the goat-fish came 3,000 years intact, which is
    # why it is drawn as a descent with no break in it.
    "Capricornus": ("descent", [
        ("Babylon", "", "Suhurmashu, the goat-fish", None),
        ("Greece", "", "Aigokeros, goat-horned", "Αἰγόκερως"),
        ("Rome", "", "Capricornus, the same word again", None),
        ("English", "now", "Capricorn, still half fish", None),
    ]),
    "Aquarius": ("descent", [
        ("Babylon", "", "Gula, the great one, pouring a stream", None),
        ("Greece", "", "Hydrokhoos, the water pourer", "Ὑδροχόος"),
        ("Rome", "", "Aquarius, the same job in Latin", None),
        ("English", "now", "Aquarius", None),
    ]),
    "Aries": ("descent", [
        ("Babylon", "", "Luhunga, the hired man", None),
        ("break", "", "the farm worker becomes a ram", None),
        ("Greece", "", "Krios, the ram", "Κριός"),
        ("Rome", "", "Aries", None),
        ("English", "now", "Aries", None),
    ]),
    "Southern Cross": ("descent", [
        ("Greece", "Ptolemy, 150", "part of Centaurus, unnamed", None),
        ("Portuguese", "1500s", "Crusero, steered by on the way south", None),
        ("Latin", "c.1600", "Crux, given its own place on a chart", None),
        ("English", "now", "the Southern Cross", None),
    ]),
    "Big Dipper": ("converge", [
        ("Greek", "Arktos, the bear"),
        ("Latin", "Plaustrum, the wagon"),
        ("English", "the Plough"),
        ("American English", "the Big Dipper"),
        ("Sanskrit", "Saptarishi, seven sages"),
        ("Chinese", "Beidou, the northern ladle"),
    ], "no shared root and no shared picture: the same seven stars are a "
       "bear, a cart, a plough, a ladle and seven sages, depending on who "
       "is looking"),
    "Orion's Belt": ("converge", [
        ("Arabic", "an-Nizam, the string of pearls"),
        ("Spanish", "las Tres Marias"),
        ("English", "the Three Kings"),
        ("Swedish", "Friggerock, Frigg's distaff"),
        ("Chinese", "Shen, the three stars"),
    ], "three in a row is a picture every tradition drew for itself, and "
       "hardly any of them drew a belt"),
}

# One constellation cut into three, which is a cluster and not a descent for
# the same reason Jupiter is: nothing here descended from anything. Lacaille
# took a figure apart in the 1750s and the pieces are siblings, not
# generations. The three pages share the one figure because the split is the
# only thing any of them has to say about its name.
_ARGO = ("cluster", "Argo Navis", "the ship, taken apart in the 1750s", [
    ("Carina", "the keel", "", "kept alpha"),
    ("Puppis", "the stern", "", "kept zeta"),
    ("Vela", "the sails", "", "kept gamma"),
])
STAGES["Carina"] = _ARGO
STAGES["Puppis"] = _ARGO
STAGES["Vela"] = _ARGO


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


def _cluster_lines(root, root_script, cols):
    """One root, and the names that came down from it side by side.

    The other figures run top to bottom because they describe one name
    travelling. This one describes a name that did not travel: three
    languages inherited it separately from a common ancestor, and drawing
    that as a descent would say Latin got it from Greek, which is exactly
    the thing the figure exists to deny.

    Columns are measured on the Latin lines only. A terminal cannot be
    trusted to give a Devanagari cluster the width it claims, so the script
    row is laid into the same columns and allowed to sit where it lands
    rather than dragging every other row out of true with it.
    """
    w = [max(len(x) for x in (lang, name, gloss) if x) for lang, name, _sc, gloss in cols]
    gap = 4
    mid = [sum(w[:i]) + gap * i + w[i] // 2 for i in range(len(cols))]
    span = mid[-1] - mid[0]
    centre = mid[0] + span // 2

    rail = [" "] * (mid[-1] + 1)
    for i, m in enumerate(mid):
        rail[m] = "┌" if i == 0 else "┐" if i == len(cols) - 1 else "┬"
    for a, b in zip(mid, mid[1:]):
        for x in range(a + 1, b):
            rail[x] = "─"
    if rail[centre] == "─":
        rail[centre] = "┴"

    def row(vals):
        return "".join(v.ljust(w[i] + gap) for i, v in enumerate(vals)).rstrip()

    out = [(" " * max(0, centre - len(root) // 2) + root, False)]
    if root_script:
        # Marked as script only when it actually is one. The flag exists so a
        # browser can isolate a right-to-left run, and setting it on an
        # ordinary Latin gloss asks for isolation nothing needs.
        out.append((" " * max(0, centre - len(root_script) // 2) + root_script,
                    any(ord(ch) > 0x2500 for ch in root_script)))
    out.append((" " * centre + "│", False))
    out.append(("".join(rail).rstrip(), False))
    out.append((row([c[0] for c in cols]), False))
    out.append((row([c[1] for c in cols]), False))
    if any(c[2] for c in cols):
        out.append((row([c[2] or "" for c in cols]), True))
    if any(c[3] for c in cols):
        out.append((row([c[3] or "" for c in cols]), False))
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
    if kind == "cluster":
        return _cluster_lines(spec[1], spec[2], spec[3])
    return _converge_lines(spec[1], spec[2])


def figure_lines(name):
    """The figure as plain lines, for a terminal."""
    return [text for text, _script in figure_rows(name)]


# Names printed inside a figure that are objects with pages of their own.
#
# Listed rather than found at render time. A renderer scanning a figure for
# words it recognises would link "Vela" wherever it fell, and half these
# lines are ordinary words in four languages. The figure's own name is never
# in its list, because a page does not link to itself.
FIGURE_LINKS = {
    "Carina": ("Puppis", "Vela"),
    "Puppis": ("Carina", "Vela"),
    "Vela": ("Carina", "Puppis"),
}


def figure_links(name):
    """Which names inside this figure should be links, if it is drawn as
    markup. A terminal gets the figure with none of them."""
    return FIGURE_LINKS.get(name, ())


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
