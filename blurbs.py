#!/usr/bin/env python3
"""
What each object is, in a sentence and a paragraph.

The top of an object page, above anything that depends on where you are or
what time it is. Two reasons it exists.

A search engine sees a different page every time it crawls: the altitude
moves, the rise time moves, the chart is redrawn. There is nothing stable
for it to decide what /Venus is about. This is the stable half.

And someone arriving from a shared link needs to know what they are looking
at before an azimuth means anything. "13 degrees above the horizon in the
WSW" is the answer to a question they have not asked yet.

Hand-written, roughly forty of them: the Sun, the Moon, the planets, the
deep-sky objects people have heard of, the brightest stars, the meteor
showers and a few asterisms. Everything else falls back to a generated line
from its own catalogue data and stays out of the sitemap -- a page that can
only say "a magnitude 9.5 galaxy in Virgo" is a page nobody searched for.

House style, following the summary sentences under the charts: plain
statements with the numbers inside them. No "did you know", no "stunning",
nothing that reads as though it is selling the sky.

    GLOSS  one line, completes "X is ..." -- runs next to the title
    BLURB  two or three sentences, the paragraph under it
"""

# Keyed on the canonical object name that objects.resolve_name() returns.
BLURBS = {

    # ---------------------------------------------------------- solar system
    "Sun": (
        "the star we orbit",
        "The Sun is a middling yellow star of a kind there are billions of, and "
        "the only one close enough to us to show a visible disc rather than a "
        "point of light. Its light takes eight minutes and twenty seconds to "
        "cross the distance, so the Sun you watch setting actually set eight "
        "minutes before you saw it. Never look at it through binoculars or a "
        "telescope without a proper solar filter fitted at the front. The "
        "damage is instant and permanent. Its name comes from the same root as "
        "Latin sol and Greek helios, and is one of the oldest words that can be "
        "reconstructed. Germanic made it feminine, which is why German still "
        "has die Sonne against a masculine Mond."),

    "Moon": (
        "the only other world anyone has stood on",
        "The Moon is a quarter of the Earth's width, and it is drifting about four centimetres further away every year. That is slow, but it has an end point: in roughly 600 million years the Moon will be too small in our sky to cover the Sun, and total solar eclipses will stop happening altogether. It turns on its own axis in exactly the time it takes to go round us, so the same face is always pointed our way. The best time to look at it is not when it is full, which is flat and glaring, but a few days either side of half, when the sunlight is arriving at a low angle along the line dividing day from night and every crater throws a long shadow. Its name comes from the same root as month and as measure. The moon is the thing you count with, and the same overlap turns up almost everywhere: Finnish kuu, Turkish ay, Hebrew ירח yareach and Chinese 月 yuè all mean both the moon and the month, in four unrelated language families."),

    "Mercury": (
        "the closest planet to the Sun, and the hardest one to see",
        "Mercury never appears more than 28 degrees away from the [[Sun]] in our sky, so it is only ever visible low down in twilight, for a few weeks at a time, before it is lost in the glare again. Copernicus is said to have died without ever having seen it. It has almost no atmosphere, and its spin and its orbit are so nearly matched that the time from one sunrise to the next lasts two of its years. Its name comes from merx, \"goods for sale\": the god of trade, matched to Babylonian Nabu, the scribe. The metal is named after the planet rather than the other way round, which is why Swahili calls it Zebaki, from the Arabic الزئبق, \"quicksilver\"."),

    "Venus": (
        "the brightest thing in the sky after the Sun and Moon",
        "Venus is bright enough to cast a shadow on a dark night and is routinely reported as an aircraft or a UFO. It shows phases like the [[Moon]], which is what Galileo observed in 1610 and what settled the argument about whether everything orbits the Earth. Under its clouds, its surface is 460 degrees and dry. Its name comes from the same root as venerate and venom (which was first a love potion). Venus is never up all night: it is a morning star or an evening star and never both at once, which is why so many traditions gave it two names. Greek had Phosphoros and Hesperos, and Czech still has Jitrenka and Vecernice."),

    "Mars": (
        "the red planet, and the only one whose surface we can make out",
        "Mars is half the width of the Earth, cold, and rusty enough that it looks orange to the naked eye. Because it is further from the Sun than we are, it goes round more slowly, and every 26 months the Earth catches it up and passes it. Around those dates it comes close enough for even a small telescope to show dark markings and a white polar cap. For the two years in between it shrinks back to a featureless dot. Mars is the god of war, matched to Babylonian Nergal, god of plague. The Greeks had called the planet Πυρόεις, \"the fiery one\", for its colour, and half the world's names for it still describe the colour rather than the god."),

    "Jupiter": (
        "the largest planet, and the easiest thing to point a telescope at",
        "Jupiter is two and a half times as massive as every other planet in the solar system put together. Its four big moons are visible with binoculars and change position from one night to the next, which is what Galileo noticed in 1610 and why they carry his name. The Great Red Spot is a storm wider than Earth, though it has been shrinking for a century. Its name is the oldest of any god in the sky. Jupiter, the Greek \"Zeus pater\" and the Sanskrit \"Dyaus Pitar\" are the same phrase, all three descended from one reconstructed form."),

    "Saturn": (
        "the planet with the rings",
        "Saturn is probably the most famous planet in the solar system, known "
        "for its rings, which show up in almost anything with lenses in it, "
        "though how open they look changes over the planet's 29-year orbit as "
        "we see them from different angles: they were edge-on and nearly "
        "invisible in 2025, and will be wide open again by the early 2030s. "
        "They are mostly made up of water ice, are two hundred and seventy "
        "thousand kilometres across, and in places are only about ten metres "
        "thick. The origin of its name is uncertain: the Romans connected it to "
        "the Latin serere, \"to sow\", which suited a god of agriculture but was "
        "worked out long after the name was already in use. Persian still calls "
        "it Keyvan کیوان, taken straight from the Babylonian Kajamanu, \"the "
        "steady one\" for how slowly it moves, a name that has been in use for "
        "about 2,500 years."),

    "Uranus": (
        "the first planet that nobody knew was there",
        "Uranus sits right at the edge of what the naked eye can pick up, which "
        "is why it was never catalogued as a planet until William Herschel "
        "found it with a telescope in 1781. Everything closer in had been known "
        "since prehistory. It is also tipped right over onto its side, so "
        "instead of spinning like a top it rolls, and each of its poles spends "
        "42 years in continuous sunlight followed by 42 in darkness. In a "
        "telescope it is a small blue-green disc and nothing more. It is the "
        "only planet with a Greek name rather than a Roman one, and the only "
        "one whose naming turned into a long argument. Herschel wanted to call "
        "it Georgium Sidus, \"George's Star\", after the British king who granted "
        "him a pension for the discovery. A German astronomer, Johann Bode, "
        "proposed Uranus instead in 1782, reasoning that since [[Saturn]] was "
        "the father of [[Jupiter]] in the old stories, the planet beyond Saturn "
        "should be Saturn's own father. It took most of a century before "
        "everyone was using it."),

    "Neptune": (
        "the planet that was found with mathematics before anyone looked",
        "Neptune is never visible to the naked eye, and it was found by arithmetic before anybody looked for it. [[Uranus]] was not moving quite as the calculations said it should, and the discrepancy suggested something further out was pulling on it. Two mathematicians worked out where that something had to be, and in 1846 a telescope was pointed at the predicted spot and found the planet within a degree of it. Its winds are the fastest in the solar system, over 2,000 kilometres an hour, on a world that receives one nine-hundredth of the sunlight we get. The name is the Latin Neptunus, \"the god of water\", and it was chosen within weeks of the discovery, over Le Verrier's own preference, which was to name it after himself."),
    "Sirius": (
        "the brightest star in the night sky",
        "Sirius is bright mainly because it is close: at 8.6 light years it is "
        "one of our nearest neighbours, and it is only about twice the width of "
        "the [[Sun]]. When it is low in the sky it flashes red and green as our "
        "atmosphere bends and splits its light, and it gets reported as an "
        "aircraft or something stranger more often than any other star. It has "
        "a companion, a white dwarf about the size of the Earth, the leftover "
        "core of a star that has stopped burning and is now cooling slowly, "
        "still hot enough to shine but far too small to be seen without a "
        "telescope. The name is the Greek Σείριος, \"scorching\", because its "
        "rising with the Sun announced the hottest weeks of the Mediterranean "
        "year. This is also where dog days comes from: Sirius sits in "
        "[[Canis Major]], the great dog, and it is its brightest star."),

    "Betelgeuse": (
        "a red supergiant near the end of its life",
        "Betelgeuse is so large that, if it replaced the [[Sun]], its surface "
        "would reach past the orbit of [[Mars]]. It will explode as a supernova "
        "at some point in the next hundred thousand years, and when it does it "
        "will be bright enough to read by. It is also the most famous typo in "
        "the sky. The Arabic name was يد الجوزاء, Yad al-Jawza', \"the hand of "
        "Jawza\", and the initial ي, \"ya\", was read as ب, \"ba\", by medieval "
        "scribes who could not read Arabic and were working from letters that "
        "differ only in where the dot sits. That gave بط الجوزاء, Bat "
        "al-Jawza', which means nothing in any language, and then Bedalgeuze in "
        "the Alfonsine Tables of about 1250."),

    "Rigel": (
        "a blue supergiant, and the brightest star in Orion",
        "Rigel outshines [[Betelgeuse]] even though Betelgeuse was given the "
        "first Greek letter of the constellation and Rigel only the second. The "
        "difference is that Rigel is genuinely luminous rather than merely "
        "nearby: it puts out something like 120,000 times as much light as the "
        "[[Sun]], from 860 light years away. Stars this hot and this blue burn "
        "through their fuel in a few million years, which by the standards of "
        "the Sun is almost no time at all. Its name has the same origin as "
        "Betelgeuse's: Rijl al-Jawza' رجل الجوزاء, \"the foot of Jawza\", against "
        "Betelgeuse's \"hand of Jawza\". [[Orion]]'s two brightest stars are the "
        "hand and the foot of one body that Arab astronomers saw where the "
        "Greeks saw a hunter."),

    "Vega": (
        "the star that the whole brightness scale was measured against",
        "When astronomers set up the modern scale for how bright a star "
        "appears, they needed a fixed point to measure everything else against, "
        "and Vega was chosen. That is why its own brightness comes out at "
        "almost exactly zero. It was the pole star about 12,000 years ago and "
        "will be again in another 12,000, because the Earth's axis slowly "
        "traces a circle rather than pointing in a fixed direction. Vega spins "
        "so fast that it is visibly flattened, bulging at its equator. Its name "
        "comes from an-nasr al-waqi' النسر الواقع, the falling eagle. "
        "[[Altair]] is at-ta'ir الطائر, the flying one, so two thirds of the "
        "[[Summer Triangle]] is made up of a pair of birds."),

    "Polaris": (
        "the north star, for the time being",
        "Polaris sits within one degree of the point in the sky that the Earth's axis points at, so as the sky turns through the night it barely moves while everything else wheels around it. That is a temporary arrangement. The axis slowly traces out a circle taking about 26,000 years, which shifts the pole roughly a degree every 72 years, so the job passes from one star to another: [[Thuban]] held it 4,700 years ago, [[Vega]] will hold it in 12,000, and Polaris has had it for only about a thousand years. It is not one star either: it is three, and the brightest of them swells and shrinks on a four-day cycle."),

    "Arcturus": (
        "an orange giant, and the brightest star north of the equator",
        "Arcturus is an old star that has already left the main sequence and "
        "swollen to 25 times the [[Sun]]'s width. It is moving through the "
        "galaxy at a steep angle to everything around it, which suggests it "
        "arrived with a small galaxy the [[Milky Way]] absorbed long ago. Its "
        "name is the Greek Ἀρκτοῦρος, \"the bear guard\", and it earns it by "
        "following the Great Bear around the pole. It is one of the very few "
        "star names to have come down unchanged from Greek without passing "
        "through Arabic on the way."),

    "Antares": (
        "the heart of the scorpion, and a rival to Mars",
        "The name is the Greek Ἀντάρης, \"rival of Ares\", Ares being the god the "
        "Romans called [[Mars]], and that is exactly what the star looks like: "
        "a red supergiant sitting on the ecliptic, close enough in colour to be "
        "mistaken for the planet. You can tell the two apart only by watching "
        "which one moves against the stars over a few nights. Antares is "
        "roughly 700 times the width of the [[Sun]], and like [[Betelgeuse]] it "
        "will end as a supernova."),

    "Altair": (
        "the flying eagle, and one half of a Chinese love story",
        "Altair takes its name from an-nasr at-ta'ir النسر الطائر, \"the flying "
        "eagle\", set against [[Vega]]'s falling one. In Chinese the same star "
        "is the Cowherd, kept apart from the Weaver Girl by the [[Milky Way]] "
        "and allowed across it one night a year."),

    "Aldebaran": (
        "the eye of the bull, and not part of the cluster behind it",
        "Aldebaran appears to sit in the Hyades cluster but is less than half as far away, in front of it by chance. It is an orange giant 44 times the [[Sun]]'s width. Pioneer 10 is heading roughly in its direction and will pass it in about two million years. Its name is really an instruction for finding it: It follows the [[Pleiades]] across the sky all night."),

    "Algol": (
        "the demon star, and the first variable anyone explained",
        "Every 2.87 days, Algol fades by more than a magnitude for about "
        "ten hours, because a dimmer companion passes in front of it. "
        "The pattern is regular enough that ancient names for it "
        "across several cultures suggest people noticed long before "
        "John Goodricke worked out why in 1783. You can watch a "
        "minimum happen with no equipment at all. The head of the "
        "ghoul or the severed head of Medusa, its name carries a dark "
        "meaning. Fitting for a darkening star."),

    "Capella": (
        "the sixth brightest star, and actually four",
        "Capella looks like one star but is in fact a four-star system: two yellow giants orbiting each other in 104 days, and a distant pair of red dwarfs. It is far enough north to be circumpolar from most of Europe and North America, so it never sets. Its name comes from the goat Amalthea, who suckled the infant Zeus. One of the few bright stars whose name is an animal."),

    "Deneb": (
        "one of the most luminous stars we can see",
        "Deneb is faint compared to [[Sirius]], but vastly brighter in reality: somewhere around 200,000 times the [[Sun]]'s output, seen from a distance of approximately 2,600 light years. If it sat where Sirius does it would cast shadows at noon. Its name (the tail) is the most productive root in the sky. The same word gives [[Denebola]], the lion's tail, [[Deneb Algedi]], the goat's tail, and Deneb Kaitos, the sea monster's tail."),

    # The rest of the first-magnitude stars. Ten of the twenty-two had
    # a paragraph and twelve did not, with no principle behind the split:
    # the missing ones included the second brightest star in the sky, the
    # nearest system to the Sun, and two of the four in the Southern
    # Cross. Pages linked from the copy were arriving at a chart and no
    # words.
    "Canopus": (
        "the second brightest star in the night sky",
        "Canopus is the second brightest star in the night sky, behind only [[Sirius]]. It sits so far south that it never clears the horizon above about 37 degrees north. It is a supergiant 313 light years away, nearly forty times further than Sirius, so it is genuinely one of the most luminous stars in our part of the galaxy. Spacecraft have navigated by it since the 1960s: it is brilliant, nowhere near the ecliptic, and there is nothing else nearby to mistake it for. It belongs to [[Carina]], the keel of the ship, and where its name came from has never been settled. It may be the Egyptian port of Κάνωπος, at the western mouth of the Nile, whose burial jars are still called canopic. It may equally be Κάνωπος, the helmsman who steered Menelaus home from Troy and died of a snakebite on the Egyptian shore. The two cannot be separated, because the port may be named after the helmsman, or the helmsman invented to explain the port."),

    "Rigil Kentaurus": (
        "the nearest star system to the Sun",
        "Rigil Kentaurus is the brightest of the three stars that make up the closest system to our own, 4.4 light years away, and it is very nearly a twin of the [[Sun]] in size, colour and temperature. Almost any telescope splits it into two stars orbiting each other over eighty years. The third, Proxima Centauri, is a small red star that is closer still and far too faint to see without a telescope, and it has a planet in the zone where liquid water could exist. The name is the Arabic Rijl Qanturis رجل قنطورس, \"the foot of the centaur\", built on the same word as [[Rigel]]. With [[Hadar]] it forms [[The Pointers]], which aim at the [[Southern Cross]]."),

    "Procyon": (
        "the eighth brightest star, and it announces Sirius",
        "Procyon is close rather than powerful: at 11.4 light years it is one of our nearest neighbours, and it would be unremarkable at any real distance. Its name is the Greek Προκύων, \"before the dog\", and it is practical advice rather than description, because from the middle northern latitudes it climbs over the horizon about half an hour ahead of [[Sirius]], the dog star. Like Sirius it has a white dwarf companion, the cooling core of a star that has stopped burning, invisible without a good telescope. It is the brighter of the two stars that make up [[Canis Minor]]."),

    "Achernar": (
        "the end of the river, and the flattest star we know of",
        "Achernar sits at the southern tip of [[Eridanus]], and its name is the Arabic آخر النهر, \"the end of the river\", which is exactly where it is. It spins so fast, at something like 250 kilometres a second at its equator, that it is not round: it bulges outward, making it the most distorted star known. At 144 light years it is bright because it is hot and large rather than because it is near, and it never rises above about 33 degrees north."),

    "Hadar": (
        "the second star of the Pointers, and a giant a long way off",
        "Hadar is the fainter of [[The Pointers]], the two stars that aim at the [[Southern Cross]], and it looks like a near neighbour of [[Rigil Kentaurus]] beside it while actually lying more than a hundred times further away, at 525 light years. It is three hot blue stars rather than one, and the pair at the centre swing around each other every 357 days. Its Arabic name هدار is not settled, and it also answers to Agena, from the Latin genu, \"knee\", which is where it sits in the figure of [[Centaurus]]."),

    "Spica": (
        "the ear of wheat, and two stars almost touching",
        "Spica is the only bright star in [[Virgo]], and it is Latin for \"the ear of wheat\" the maiden is holding, which is the harvest image the whole constellation is built on. It is not one star but two, so close together that they orbit in four days and their mutual gravity pulls each into an egg shape, which is why the brightness rises and falls slightly as they turn. It lies almost exactly on the line the Sun, Moon and planets follow, so the Moon covers it from time to time. The way to find it is to follow the curve of the [[Big Dipper]] handle to [[Arcturus]] and carry on the same arc."),

    "Pollux": (
        "the nearest giant star to us, with a planet going round it",
        "Pollux is one of the two heads of [[Gemini]], the twins, and at 34 light years it is the closest giant star to the Sun: a star that has finished burning hydrogen in its core, swollen up and turned orange. A planet several times the mass of [[Jupiter]] orbits it. It is brighter than [[Castor]] beside it, and the labelling never caught up: Castor was lettered Alpha Geminorum and Pollux only Beta, though the letters were meant to run from the brightest star down."),

    "Fomalhaut": (
        "one bright star alone in an empty patch of autumn sky",
        "Fomalhaut is sometimes called the loneliest star, because there is nothing else bright anywhere near it. Its name is the Arabic فم الحوت, \"the mouth of the fish\", which is where it sits in [[Piscis Austrinus]]. At 25 light years it is a close neighbour, and it is ringed by a broad belt of dust and debris. In 2008 astronomers announced they had photographed a planet inside that ring, which would have been among the first ever seen directly; further observations showed it was not a planet but an expanding cloud of rubble, most likely from a collision between two large bodies."),

    "Mimosa": (
        "the second star of the Southern Cross, and one of the hottest you can "
        "see",
        "Mimosa is the bright star at the eastern arm of the [[Southern Cross]], 353 light years away, and its surface is around 27,000 degrees, roughly five times as hot as the [[Sun]]. That heat is why it looks distinctly blue-white. It pulses very slightly, several times a day, as the star swells and settles. Nobody knows why it is named after a flower."),

    "Acrux": (
        "the foot of the Southern Cross, and a name that was manufactured",
        "Acrux is the brightest star of the [[Southern Cross]] and marks its foot, the end that is extended to find the south pole of the sky. A small telescope splits it into two blue stars of almost equal brightness, and there is a third further out. The name is not old and not from any language: it is the letter A, for the first star of the constellation, stuck on the front of Crux. Several southern stars were named this way in the twentieth century when navigators needed something pronounceable."),

    "Regulus": (
        "the little king, and a star spun into an egg",
        "Regulus is the dot at the foot of the [[Sickle]] and the brightest star in the lion. It sits almost exactly on the line the Sun, Moon and planets follow across the sky, closer to it than any other bright star, so the Moon passes over it and hides it several times in the years when their paths line up. It spins once every sixteen hours, fast enough that it is not round but flattened into an egg, wider across the equator than from pole to pole and noticeably cooler and dimmer around its own middle. At 78 light years it is four stars rather than one. Copernicus coined its name, translating older ones that all said the same thing word for word: Greek Βασιλίσκος, Basiliskos, \"little king\", Arabic قلب الأسد, Qalb al-Asad, \"the lion's heart\", and Babylonian Sharru, \"the king\"."),

    "Adhara": (
        "the brightest star in the sky, five million years ago",
        "Adhara sits below [[Sirius]] in [[Canis Major]] and is a good deal further away, 431 light years, which makes it far more luminous than it looks. Its name is the Arabic العذارى, \"the maidens\". About 4.7 million years ago it passed within 34 light years of us and shone at magnitude -3.99, brighter than [[Jupiter]] ever gets and brighter than any star has been in human history or is due to be again. It is also the brightest source of ultraviolet light in our sky, bright enough that it still has an effect on the thin gas drifting through the space around the solar system, hundreds of light years away."),

    # -------------------------------------------------------------- deep sky
    "Andromeda Galaxy": (
        "the furthest thing you can see without a telescope",
        "[[Andromeda]] is 2.5 million light years away. It spans six times the width of the full [[Moon]], though only the bright core shows without optics. It is heading towards us and will merge with the [[Milky Way]] in about four billion years. Named for the constellation it sits in. Al-Sufi recorded it in 964 as a little cloud, which is the oldest surviving description of anything outside our own galaxy, written a thousand years before anyone knew what it was."),

    "Orion Nebula": (
        "a place where stars are being made, visible to the naked eye",
        "The middle point of light in [[Orion]]'s sword is not a star at all. It is the Orion Nebula, a cloud of gas and dust 24 light years across with new stars condensing inside it, and it is the nearest such place to us. Four of those new stars, close together at the centre and known as the Trapezium, are what light the whole cloud up. Binoculars show its shape clearly and a small telescope starts to show the wisps and folds in it."),

    "Hercules Cluster": (
        "half a million stars in a ball",
        "The Hercules Cluster is a globular cluster, one of about 150 orbiting "
        "the [[Milky Way]]. It is amongst the oldest things in the galaxy at "
        "roughly 11.6 billion years. Through binoculars, it is a fuzzy dot. "
        "With a telescope, the edges break into individual stars. A radio "
        "message was aimed at it in 1974. It should arrive in 25,000 years."),

    "Pleiades": (
        "the seven sisters, though most people count six",
        "The Pleiades are a group of young stars, around 100 million years old, that formed together and are still loosely travelling together through the galaxy. Six of them are easy to see with the naked eye and picking out the seventh is a traditional test of eyesight; binoculars show dozens more. The group covers about four times the width of the full [[Moon]], which is why a telescope is the wrong instrument for them: it magnifies so much that you end up inside the cluster without ever seeing its shape. It is the best-named object in the sky, because almost every tradition named it separately: Japanese 昴, Subaru, \"gathered together\"; Sanskrit कृत्तिका, Krittika, the first of the 27 nakshatras; Maori Matariki, which opens the year; and Arabic الثريا, al-Thurayya, \"the abundant one\". What they share is the count: nearly everyone says seven, and six is all most people can see."),

    "Whirlpool Galaxy": (
        "the first galaxy anyone recognised as a spiral",
        "Lord Rosse drew the Whirlpool's spiral arms in 1845, having seen it "
        "through the largest telescope in the world, a six-foot mirror at Birr "
        "Castle. He had sketched the [[Crab Nebula]] the year before. Nobody "
        "knew what he was looking at: another eighty years passed before "
        "spirals were shown to be galaxies of their own rather than clouds "
        "inside our own. The small companion on the end of an arm, NGC 5195, is "
        "not parked there but passing behind, and its pull is what draws the "
        "arms so sharply."),

    "Ring Nebula": (
        "a dying star seen straight down the barrel",
        "When a star about the size of the [[Sun]] runs out of fuel it swells "
        "up and then sheds its outer layers into space, leaving its exposed "
        "core behind. The Ring Nebula is one of those shed shells, seen from a "
        "direction that makes it look like a smoke ring, and it is lit from "
        "inside by the small hot core at its centre. It is only about one "
        "arcminute across, roughly a thirtieth of the width of the full Moon, "
        "so what it needs is magnification rather than a large telescope. This "
        "is approximately what the Sun will do in five billion years."),

    "Dumbbell Nebula": (
        "the brightest planetary nebula in the sky",
        "The same kind of object as the [[Ring Nebula]], the Dumbbell Nebula is eight times larger and much easier to see: binoculars from a dark site will show it. The name \"planetary nebula\" is a historical mistake: they looked like planetary discs in early telescopes but have nothing to do with planets."),

    "Lagoon Nebula": (
        "a naked-eye nebula from a dark sky",
        "The Lagoon Nebula sits in the densest part of the [[Milky Way]] "
        "towards the galactic centre, and from somewhere properly dark it is "
        "visible without optics as a brighter patch in the band. The dark lane "
        "that gives it its name splits it in two."),

    "Sombrero Galaxy": (
        "a galaxy seen almost exactly edge-on",
        "The Sombrero Galaxy is a spiral seen from the side, tilted only six "
        "degrees off edge-on, so it looks like a bright line with a bulge (the "
        "galaxy core) in the middle rather than a spiral. A band of dust runs "
        "along the line and cuts across the bulge as a dark stripe, which gives "
        "it its name: it makes it look like a hat with a flat brim and rounded "
        "crown. Around it are nearly 2,000 globular clusters, dense balls of "
        "very old stars, against about 150 for our own galaxy. At the centre is "
        "a black hole around a billion times the mass of the [[Sun]]."),

    "Crab Nebula": (
        "the wreckage of a star that exploded in 1054",
        "Chinese and Japanese astronomers recorded a new star in Taurus in July 1054, bright enough to see in daylight for three weeks. What is left of this supernova is the Crab Nebula. It still expanding at 1,500 kilometres a second, with a neutron star at the centre spinning 30 times a second. Its name comes from a sketch Lord Rosse made in 1844 through the telescope at Birr Castle. The drawing looks like a crab and, even if the later photographs do not, the name survived."),

    "Triangulum Galaxy": (
        "the third galaxy in our local group, and a test of dark skies",
        "The Triangulum Galaxy is large and diffuse, which makes it a poor "
        "target for a telescope and a good one for binoculars. Under genuinely "
        "dark skies some people can see it with the naked eye, which makes it a "
        "reasonable contender for the furthest thing visible unaided."),

    "Double Cluster": (
        "two open clusters side by side",
        "The Double Cluster is two groups of stars that sit close enough "
        "together to share one field of view. They were catalogued as a pair by "
        "Hipparchus. Both are young, around 12 million years, and actually "
        "physically associated rather than a line-of-sight coincidence."),

    "Milky Way": (
        "the galaxy we live in, seen edge on from the inside",
        "The Milky Way is the band of light across the sky, and it is our own "
        "galaxy seen from a position inside it. It is a flattened disc about a "
        "hundred thousand light years across containing a few hundred billion "
        "stars, and we sit roughly halfway out from the middle, so looking "
        "along the plane of the disc means looking through the greatest depth "
        "of stars, and that is the band. It is brightest and widest towards "
        "[[Teapot|Sagittarius]], because that is the direction of the centre. "
        "Roughly a third of the people alive now live under skies too bright to "
        "show it at all."),
    "Perseids": (
        "the most reliable meteor shower of the year",
        "The Perseids are the meteor shower most people have seen, because they come in August, in warm weather, at a reasonable hour of the evening. A meteor shower happens when the Earth crosses the trail of grit a comet has left strung out along its orbit, and the grains burn up in our atmosphere as they hit it. The trail we cross in August was left by the comet Swift-Tuttle. From a dark site you can expect around a hundred meteors an hour at the peak, and there is no need to face the point they seem to come from, because they appear all over the sky."),

    "Geminids": (
        "the best shower of the year, if you can stand the cold",
        "The Geminids are the most intense meteor shower at 150 per hour. Their radiant is high in the middle of the night in December. They come from an asteroid rather than a comet, which is unusual, and the meteors are slow and often bright."),

    "Quadrantids": (
        "a sharp peak that most people miss",
        "The Quadrantids can be as rich as the [[Geminids]], but they are much harder to catch. Most showers spread their best hours over a night or two; this one packs almost everything into about six hours, so the timing matters far more than usual and half the world is in daylight when it happens. The name comes from Quadrans Muralis, \"the wall-mounted quadrant\", a constellation drawn around an astronomer's measuring instrument and dropped when the modern list of 88 was fixed. No other shower is named after something that no longer exists."),

    "Lyrids": (
        "the oldest recorded shower",
        "Chinese records describe Lyrid meteors falling \"like rain\" in 687 "
        "BC, which makes this the longest continuously observed shower. Normal "
        "years give about 18 an hour, but it has produced sudden outbursts "
        "several times without warning."),

    # -------------------------------------------------------------- asterisms
    "Big Dipper": (
        "seven stars that point at the pole",
        "The Big Dipper is not a constellation, but a part of Ursa Major, and "
        "probably the most widely recognised shape in the northern sky. The two "
        "stars at the end of the bowl point at [[Polaris]]. The middle star of "
        "the handle, [[Mizar]], has a companion visible to good eyesight, which "
        "was used as a vision test for centuries."),

    "Orion's Belt": (
        "three stars in a row, and the best signpost in the sky",
        "Orion's Belt is three stars, [[Alnitak]], [[Alnilam]] and [[Mintaka]], almost evenly spaced and almost equally bright, which is why no other pattern in the sky gets confused with them. They are also the most useful three stars to know, because the line they make points at other things: extend it down and to the left and it reaches [[Sirius]], the brightest star in the sky, and up and to the right it reaches [[Aldebaran]], the orange eye of Taurus, the bull. Hanging below the belt is [[Orion]]'s sword, and the middle of the sword is not a star but the [[Orion Nebula]], a cloud of gas where new stars are being formed."),

    "Summer Triangle": (
        "three bright stars in three different constellations",
        "The Summer Triangle is made up of [[Vega]], [[Deneb]] and [[Altair]]. "
        "They are the first stars to come out on a summer evening, and they are "
        "spread far enough apart to span most of the sky overhead. Each one "
        "belongs to a different constellation, Vega to [[Lyra]], Deneb to "
        "[[Northern Cross|Cygnus]] and Altair to [[Aquila]], which is why the "
        "triangle is not a constellation itself but a shape drawn across three "
        "of them. The [[Milky Way]] runs straight through the middle of it, so "
        "from a dark site the triangle frames the best part of the whole band."),

    "Southern Cross": (
        "the smallest constellation, and the signpost of the southern sky",
        "The Southern Cross might be the most important constellation in its "
        "hemisphere. Indeed, the southern half of the sky has no bright star "
        "anywhere near its pole, so there is nothing there to steer by "
        "directly. What people do instead is take the long axis of the cross "
        "and extend it about four and a half times its own length, which lands "
        "close to the pole. The cross is small, bright and unmistakable, and it "
        "appears on the national flags of Australia, Brazil, New Zealand, Papua "
        "New Guinea and Samoa. Beside it lies the Coalsack, a cloud of dust "
        "dense enough to block the light of everything behind it, which shows "
        "up as an obvious hole in the [[Milky Way]]."),

    "Little Dipper": (
        "the pole star, with six fainter stars trailing behind it",
        "The Little Dipper is the constellation Ursa Minor, drawn as a smaller version of the [[Big Dipper]] beside it. Only two of its stars are easy to see: [[Polaris]] at the very tip of the handle, and [[Kochab]] in the bowl. The other five are faint enough that being able to count all seven is a fair test of how dark your sky is. The Greeks called this figure Κυνόσουρα, \"the dog's tail\", and because the star at the end of it was what everyone steered by, the word came into English as cynosure: whatever a room full of people cannot take their eyes off."),

    "Cassiopeia's W": (
        "five bright stars in the shape of a W, opposite the Big Dipper",
        "The W sits on the far side of [[Polaris]], the pole star, from the "
        "[[Big Dipper]], which means that from northern latitudes one of the "
        "two is always above the horizon, and whichever of them is higher at "
        "the time will point you towards the pole. The W is the queen "
        "Cassiopeia, who in the Greek story boasted that she was more beautiful "
        "than the sea nymphs and was punished by being tied to a chair and set "
        "turning around the pole forever, so that for half of every night she "
        "hangs upside down. In 1572 a star that nobody had ever recorded "
        "appeared inside this figure and became bright enough to be seen in "
        "daylight. It faded over the following year. That was a supernova, an "
        "exploding star, and the careful measurements the Danish astronomer "
        "Tycho Brahe made of it helped prove that the sky beyond the planets "
        "was not the changeless place everyone had assumed."),

    "Northern Cross": (
        "the bright stars of Cygnus, the swan, in the shape of a cross",
        "The Northern Cross is the brightest part of Cygnus, the swan, and it lies along the [[Milky Way]] in the richest star fields the northern sky has. [[Deneb]] marks the top of the cross and [[Albireo]] the foot. Albireo is worth a telescope of any size, because what looks like a single star separates into two, one gold and one blue, sitting close together. Read as the swan instead, the same stars are a bird flying down the length of the Milky Way with its wings spread, and on autumn evenings the cross stands upright over the western horizon."),

    "Keystone": (
        "four faint stars in Hercules, and the way to find the cluster M13",
        "A keystone is the wedge-shaped block at the top of a stone arch, which is roughly the shape these four stars make. None of them is bright, but the pattern is worth learning, because a third of the way down its western side sits the [[Hercules Cluster]], a ball of several hundred thousand stars bound together by gravity. The constellation these four belong to is Hercules, which is large, contains no bright star at all, and is very hard to find any other way."),

    "Corona Borealis": (
        "a small arc of seven stars, and one of the tidiest shapes in the sky",
        "The northern crown is a neat half circle of seven stars lying between "
        "[[Kite|Bootes]] and [[Keystone|Hercules]], of which only [[Alphecca]] "
        "is truly bright. Medieval Arabic astronomers called it al-Fakka الفكة, "
        "\"the broken dish\", because the circle is open rather than closed. It "
        "also holds a star called T Coronae Borealis, which spends decades too "
        "faint to see and then suddenly flares up to naked-eye brightness for a "
        "few nights. It has done this roughly every eighty years, most recently "
        "in 1946, and astronomers have been expecting the next one for the past "
        "few years."),

    "Kite": (
        "the shape of Bootes, hanging below Arcturus",
        "The Kite is a long narrow diamond standing on its point, and [[Arcturus]], the fourth brightest star in the night sky, is the knot at its bottom corner. The easiest way to find it is to take the curve of the [[Big Dipper]] handle and carry it on past the end: it lands on Arcturus. The stars belong to Bootes, Greek Βοώτης, \"the ox-driver\", drawn as a herdsman walking behind the oxen, which are the stars of the Dipper read as a plough rather than a bear. Once somebody has pointed out the kite, it becomes rather hard to see the herdsman again."),

    "Job's Coffin": (
        "four stars in Delphinus, filling a box the size of a thumbnail",
        "Job's Coffin is a tight lozenge of four stars with a fifth trailing off to make a tail, and it is faint but quite unmistakable. It is the whole of Delphinus, the dolphin, one of the smallest constellations in the sky. Where the name Job's Coffin came from, nobody knows: it turns up in English in the 1800s already in use, with nothing said about what the biblical Job has to do with it. The two brightest stars carry a joke rather than a history. They are called [[Sualocin]] and [[Rotanev]], which is Nicolaus Venator spelled backwards, the Latinised name of an assistant at the Palermo observatory who slipped himself into the star catalogue his employer published in 1814."),

    "Teapot": (
        "eight stars in Sagittarius that look like a teapot and nothing like an "
        "archer",
        "The constellation here is Sagittarius, drawn since antiquity as a "
        "centaur pulling back a bow. What the bright stars actually make is a "
        "teapot, complete with a lid, a handle and a spout, and the modern name "
        "has more or less replaced the archer in practice. Steam appears to "
        "rise from the spout, and that is the [[Milky Way]] at its thickest: "
        "looking this way means looking towards the centre of our own galaxy, "
        "which lies a few degrees off the end of the spout behind about 25,000 "
        "light years of dust."),

    "Great Square": (
        "four stars marking the body of Pegasus, around an empty patch of sky",
        "The Great Square is large, obvious, and almost completely empty inside. Counting how many stars you can see within it is a standard rough test of how dark your sky is, and in a town the honest answer is usually none at all. The square is the body of Pegasus, the winged horse, except that one of its four corners is not in Pegasus at all. [[Alpheratz]], the north-eastern one, was claimed by both Pegasus and [[Andromeda]] for centuries, until the International Astronomical Union drew fixed borders around all 88 constellations in 1930 and put the star in Andromeda."),

    "Hyades V": (
        "the V of the bull's face, and the nearest star cluster to us",
        "The Hyades are the nearest star cluster to us, 150 light years away, and they make the V of stars that forms the face of Taurus, the bull. [[Aldebaran]] sits at one end of the V but is not part of it: it lies less than half as far away, in front of the group by chance. Because the cluster's stars all move together, astronomers could measure its distance directly, and that measurement anchored the scale of everything beyond it. The Greek name is disputed: ὕειν, \"to rain\", because the group rises before dawn as the wet season begins, or ὗς, \"pig\", which the Romans took literally and called them the Suculae, \"the little pigs\"."),

    "Winter Triangle": (
        "three of the brightest stars in the sky, in an almost equal triangle",
        "The Winter Triangle joins [[Sirius]], [[Procyon]] and [[Betelgeuse]], "
        "which are amongst the brightest stars in the sky, and together they "
        "draw a close to perfect equilateral triangle. The name is modern and "
        "the shape useful because all three are bright enough to survive city "
        "lights. Betelgeuse is the odd corner: red, variable, and several "
        "hundred times the [[Sun]]'s width."),

    "Winter Hexagon": (
        "six bright stars around Orion, and most of the winter sky at once",
        "[[Sirius]], [[Procyon]], [[Pollux]], [[Capella]], [[Aldebaran]] and "
        "[[Rigel]] make a rough ring with [[Betelgeuse]] inside it. It spans "
        "six constellations and about a quarter of the sky, which is what "
        "makes it worth knowing: find two corners and the rest of winter is "
        "fixed. Also called the Winter Circle."),

    "Sickle": (
        "a backwards question mark that forms the head of Leo",
        "The Sickle is a curve of six stars shaped like a backwards question "
        "mark, and it makes the head and mane of Leo, the lion. [[Regulus]] is "
        "the dot at the foot of that question mark. It sits almost exactly on "
        "the ecliptic, the line the Sun, Moon and planets all follow across the "
        "sky, so the Moon passes close to it several times a year and the "
        "planets do so every so often. Every November the Leonid meteors appear "
        "to stream out of a point inside the Sickle. They are dust shed by the "
        "comet Tempel-Tuttle, which comes back round every 33 years, and when "
        "the Earth crosses the trail shortly after the comet has passed the "
        "shower can turn into a storm of thousands an hour."),

    "Spring Triangle": (
        "three bright stars that carry the spring sky",
        "The Spring Triangle, made up of [[Arcturus]], [[Spica]] and "
        "[[Regulus]], is what is left once the winter constellations have set "
        "and the summer ones have not yet risen. The way to find it is the "
        "handle of the [[Big Dipper]]: follow its curve away from the bowl and "
        "it takes you to Arcturus, and carrying the same curve onwards takes "
        "you to Spica. Some versions of the triangle use [[Denebola]], in the "
        "tail of [[Sickle|Leo]], in place of Regulus."),

    "Great Diamond": (
        "the Spring Triangle with a fourth corner added to it",
        "The Great Diamond is made up of [[Arcturus]], [[Spica]] and "
        "[[Denebola]], with [[Cor Caroli]] added at the northern point, and it "
        "makes a kite-shaped figure about fifty degrees across, also known as "
        "the Diamond of [[Virgo]]. Inside it, towards the Denebola end, lies "
        "the Virgo cluster, a swarm of over a thousand galaxies bound together "
        "by gravity about 55 million light years away, none of them visible "
        "without a telescope. The name Cor Caroli is Latin for \"the heart of "
        "Charles\". It was given in the 1600s in honour of an English king, "
        "which makes it one of the very few stars in the sky named after a real "
        "person rather than a god or a description."),

    "The Pointers": (
        "the two stars that point at the Southern Cross",
        "[[Rigil Kentaurus|Alpha Centauri]] and [[Hadar|Beta Centauri]] sit to "
        "the east of the cross, and a line drawn through them runs straight "
        "into it. That matters more than it sounds, because there are two "
        "cross-shaped patterns in this part of the sky and only one of them is "
        "the [[Southern Cross]]. The pointers settle it. Alpha Centauri is also "
        "the nearest star system to our own, at 4.3 light years, and almost any "
        "telescope will separate it into two stars orbiting each other. "
        "Confusingly, in the northern hemisphere the same name is used for the "
        "two stars at the end of the [[Big Dipper]] bowl, which point at "
        "[[Polaris]]."),

    "False Cross": (
        "four stars that are regularly mistaken for the Southern Cross",
        "The False Cross is larger than the real cross, fainter, and has "
        "nothing pointing at it. Sailors have steered by it in error often "
        "enough for the mistake to be built into its name. There are two ways "
        "to tell them apart. The [[Southern Cross]] has a fifth star sitting "
        "inside the shape and lies squarely across the bright band of the "
        "[[Milky Way]], while the False Cross stands off to one side of the "
        "band with nothing inside it. Two of its four stars belong to "
        "[[Carina]] and two to [[Vela]]."),
    "Lyra": (
        "a small parallelogram of stars hanging below Vega",
        "Lyra is one brilliant star with a small lopsided rectangle underneath it. The star is [[Vega]], the fifth brightest in the night sky, and everything else in the constellation is faint. Between the two lower corners of the rectangle sits the [[Ring Nebula]], the glowing shell of gas thrown off by a dying star. The lyre belongs to Orpheus, but older Greek and Arabic lists drew a swooping bird in these stars instead, which is where the name Vega comes from: it is worn down from النسر الواقع, an-nasr al-waqi', \"the falling eagle\"."),

    "Aquila": (
        "the eagle, with Altair at its neck",
        "Aquila is Latin for \"the eagle\". Its brightest star, [[Altair]], has "
        "fainter stars on both sides, which is the quickest way to identify it: "
        "three stars in a short line with the middle one bright. Altair is one "
        "of the fastest spinning stars anyone has measured, turning once in "
        "about nine hours and visibly flattened by it. The figure has been an "
        "eagle for as long as there are records, in Babylonian lists as well as "
        "Greek ones."),

    "Scorpius": (
        "one of the few constellations that looks like the thing it is named "
        "after",
        "Scorpius is a curving line of stars with red [[Antares]] in the middle "
        "and a genuine hook of a tail at the end, low in the south from Europe "
        "and passing overhead in the tropics. It has been a scorpion for at "
        "least three thousand years: the Babylonians drew the same animal in "
        "the same stars, and the Greeks and Romans took it over unchanged. The "
        "one thing that did change is the claws. They were cut off and made "
        "into a separate constellation, [[Libra]], which is why the two "
        "brightest stars of Libra are still named the northern claw and the "
        "southern claw."),

    "Andromeda": (
        "a chain of stars running off the Great Square, with a galaxy on it",
        "Andromeda begins at the corner it shares with the [[Great Square]] "
        "and runs in two long lines towards [[Perseus]]. Halfway along, turn "
        "at [[Mirach]] and go up two faint stars to reach the "
        "[[Andromeda Galaxy]], the furthest thing most people can see "
        "without help. In the story she is chained to a rock as a sacrifice, "
        "and everyone else in it is a constellation around her: her mother "
        "[[Cassiopeia's W|Cassiopeia]], her father [[Cepheus]], the sea "
        "monster [[Cetus]] and her rescuer Perseus."),

    "Orion": (
        "the most clearly drawn figure in the sky",
        "Orion is a rectangle of four bright stars with a belt of three across the middle and a sword hanging down from it, and it is the easiest constellation in the sky to identify. [[Betelgeuse]] at one shoulder is distinctly red and [[Rigel]] at the opposite foot is blue-white, which makes them the clearest demonstration anywhere that stars come in different colours. The Babylonians drew the same figure and called it the True Shepherd of Anu. Where the Greek name Ὠρίων came from, nobody knows."),

    "Auriga": (
        "a pentagon of stars with Capella at the top",
        "A rough pentagon at the top of which sits [[Capella]], the sixth "
        "brightest star in the sky. It is nearly overhead on winter evenings "
        "from northern latitudes. Just below it is a small triangle of faint "
        "stars called the Kids, which is what Capella hints at: the little "
        "she-goat. Auriga is the charioteer, and the goats are what he is "
        "carrying."),

    "Grus": (
        "the crane, and the best shaped of the southern bird constellations",
        "Grus sits below [[Piscis Austrinus]] and is unusually well formed for a constellation invented in modern times, with two reasonably bright stars and a long neck of fainter ones. It is one of twelve that all came from a single sea voyage. In the 1590s two Dutch navigators, Pieter Keyser and Frederick de Houtman, sailed to the East Indies and spent the voyage measuring the positions of southern stars that no European chart had ever covered. Their measurements reached the German astronomer Johann Bayer, who printed the new figures in his star atlas in 1603, and they have been on the charts ever since."),

    "Canis Major": (
        "the dog behind Orion, and it carries the brightest star in the sky",
        "Canis Major is the greater dog, and [[Sirius]] is so much brighter "
        "than everything around it that the rest of the figure barely "
        "registers, but there is a dog there, with a triangle of stars for the "
        "hindquarters and [[Mirzam]] standing in front of it. In ancient Egypt, "
        "Sirius disappeared into the Sun's glare for about seventy days each "
        "year, and the morning it first rose again just before dawn arrived "
        "within days of the Nile beginning to flood, so the two events were "
        "read together. The Romans called the hot weeks that followed the dog "
        "days, which is a phrase we still use. Four degrees below Sirius is "
        "M41, a loose group of a hundred or so stars that were born together "
        "and are still travelling together, and it is just visible to the naked "
        "eye from a dark place."),

    "Canis Minor": (
        "a constellation of two stars, one of which is Procyon",
        "Canis Minor contains only two stars, [[Procyon]] and [[Gomeisa]], "
        "which makes this one of the emptiest named patterns in the night sky. "
        "The name Procyon is Greek, Προκύων, for \"before the dog\": seen from "
        "middle northern latitudes, Procyon climbs over the horizon about half "
        "an hour ahead of [[Sirius]], the dog star, so when you see it you know "
        "what is coming next."),

    "Gemini": (
        "two lines of stars, each ending in a bright one",
        "Gemini is Latin for \"the twins\", and [[Castor]] and [[Pollux]] make up "
        "their heads. Two roughly parallel lines of fainter stars run down from "
        "them to the feet, which rest at the edge of the [[Milky Way]]. There "
        "is an oddity in the labelling. Astronomers letter the stars of a "
        "constellation in Greek, in order of brightness, so Alpha should be the "
        "brightest, but here Beta Geminorum, which is Pollux, clearly outshines "
        "Alpha Geminorum, which is Castor. Whether the labelling was simply "
        "wrong when it was done in 1603 or Castor has genuinely faded since is "
        "not settled. Castor is also not one star. It is six, arranged as three "
        "pairs orbiting one another. The Babylonians drew the Great Twins in "
        "these same stars long before the Greeks did."),

    "Virgo": (
        "the second largest constellation, and nearly all of it faint",
        "In Virgo, only [[Spica]] is bright; the rest is a wide shape of second "
        "and third magnitude stars. Spica is Latin for \"the ear of wheat\", and "
        "the figure has been referencing the harvest for a long time: the "
        "Babylonians called the same stars the Furrow. The bowl of the shape "
        "holds the Virgo cluster, over a thousand galaxies around 55 million "
        "light years away, none of them visible without a telescope."),

    "Canes Venatici": (
        "two faint stars, and some of the best galaxies in the sky",
        "The Hunting Dogs. Only two of its stars can be seen without a "
        "telescope, and only [[Cor Caroli]] is bright enough to pick out. "
        "Hevelius named it in the 1680s to fill a blank patch of sky under "
        "the handle of the [[Big Dipper]], which is how most of the small "
        "modern constellations came about: somebody found a gap between the "
        "old figures and put a name on it. What makes this one worth finding "
        "is the [[Whirlpool Galaxy]], the first galaxy anyone saw a spiral "
        "in, drawn by Lord Rosse in 1845."),

    "Centaurus": (
        "a large southern constellation that holds the nearest stars to the Sun",
        "[[Rigil Kentaurus|Alpha Centauri]] is the closest star system to our "
        "own, at 4.3 light years, and almost any telescope will show that it is "
        "not one star but two orbiting each other. A third and much fainter "
        "member of the same system, Proxima Centauri, is nearer still and "
        "cannot be seen without a telescope. Centaurus also contains "
        "[[Omega Centauri]], the largest globular cluster in the sky, which is "
        "a ball of several million old stars held together by their own "
        "gravity, and from a dark site it is an obvious fuzzy patch to the "
        "naked eye. The [[Southern Cross]] used to be part of this "
        "constellation, drawn between the centaur's front legs, before it was "
        "separated off as a figure of its own."),

    "Carina": (
        "the keel of a ship that was broken up into three constellations",
        "For centuries the southern sky held a single enormous constellation "
        "called Argo Navis, the ship of the Greek hero Jason. It was by far the "
        "largest ever drawn, and in the 1750s a French astronomer named "
        "Nicolas-Louis de Lacaille, who spent two years at the Cape of Good "
        "Hope cataloguing stars no European chart had covered properly, decided "
        "it was unwieldy and divided it into three: the keel, the stern and the "
        "sails. Carina is the keel, and it kept the best of the ship. "
        "[[Canopus]] is here, the second brightest star in the night sky, and "
        "so is the [[Carina Nebula]], a cloud of gas and dust where new stars "
        "are forming that is both bigger and brighter than the more famous "
        "[[Orion Nebula]], and less known only because it never rises for most "
        "of the people who write about the sky. Inside that cloud sits Eta "
        "Carinae, a star so massive and unstable that in 1843 it flared up to "
        "become the second brightest star in the sky, threw off a cloud of its "
        "own material, and survived."),

    "Vela": (
        "the sails of a ship, and one of three constellations cut from one",
        "For centuries the southern sky held one enormous constellation, Argo "
        "Navis, the ship of the Greek hero Jason. In the 1750s a French "
        "astronomer, Nicolas-Louis de Lacaille, divided it into the keel, the "
        "stern and the sails, and Vela is the sails. The split left a visible "
        "mark. Astronomers label the stars of a constellation with Greek "
        "letters running roughly brightest first, so Alpha is normally the "
        "brightest star in the figure, but Vela has no Alpha and no Beta at all "
        "and its brightest star is Gamma. Lacaille kept the ship's original "
        "lettering rather than starting each piece again, so Alpha and Beta "
        "went to [[Carina]] and stayed there. [[Puppis]] carries the same gap, "
        "and no other constellation in the sky does. Gamma Velorum itself is "
        "the nearest example of a Wolf-Rayet star, one that has already blown "
        "its outer layers off into space and is burning its exposed core, far "
        "hotter than an ordinary star and still shedding what is left of "
        "itself. Spread across a large part of the constellation is the Vela "
        "supernova remnant, the wreckage of a star that exploded around eleven "
        "thousand years ago."),

    "Puppis": (
        "the stern of the ship, and the third piece of Argo Navis",
        "For centuries the southern sky held one enormous constellation, Argo Navis, the ship of the Greek hero Jason. In the 1750s a French astronomer, Nicolas-Louis de Lacaille, divided it into the keel, the stern and the sails, and Puppis is the stern. It is the piece people forget, but the [[Milky Way]] runs the whole length of it and it holds several clusters of young stars bright enough to see without a telescope. Its brightest star, Zeta Puppis, is one of the hottest and most luminous stars that can be seen anywhere with the naked eye. Lacaille kept the ship's original lettering rather than starting each piece again, so Puppis has no star lettered Alpha or Beta: those went to [[Carina]] and stayed there. [[Vela]] carries the same gap, and no other constellation in the sky does."),

    "Aquarius": (
        "a large, faint zodiac constellation with a stream of water in it",
        "No star in Aquarius is particularly bright. What identifies it is a "
        "small Y of four stars called the Water Jar, and a ragged line of "
        "faint ones "
        "running south from it towards [[Fomalhaut]], which is the water "
        "pouring out. The figure has always been about water: the Babylonians "
        "called it the Great One and drew it pouring a stream."),

    "Aries": (
        "three stars, and the reason the zodiac starts where it does",
        "Aries is [[Hamal]], [[Sheratan]] and one fainter star, and that is "
        "most of it. The Sun used to cross the equator here at the spring "
        "equinox, which is what made this the first zodiac sign, and the "
        "crossing point is "
        "still called the First Point of Aries even though precession moved it "
        "into Pisces about 2,000 years ago. The Babylonians drew a hired farm "
        "worker in these stars before the Greeks made it a ram."),

    "Capricornus": (
        "the goat-fish, and the faintest of the twelve zodiac constellations",
        "The stars of Capricornus make a wide, dim triangle, and the figure drawn on them is far stranger than anything you can actually see: an animal that is a goat at the front and a fish at the back. The Greeks did not invent that. It comes from the star lists of ancient Babylon, where the same creature was drawn in the same stars, and it has been handed down for roughly three thousand years without anybody tidying it into something more sensible. Alpha Capricorni is what astronomers call an optical double: two stars that look like a close pair to the naked eye, and are in fact nowhere near each other, one simply lying far beyond the other along the same line of sight."),

    "Cepheus": (
        "a faint constellation shaped like a house, close to the pole star",
        "Cepheus is not bright, but it is easy to recognise once you have seen "
        "it: five stars in the outline of a child's drawing of a house, with "
        "the point of the roof aimed at [[Polaris]]. One of those five, Delta "
        "Cephei, is the star that the entire measured scale of the universe "
        "rests on. It brightens and fades on a strict cycle of 5.4 days, and in "
        "1912 the American astronomer Henrietta Leavitt showed that for every "
        "star of this type the length of the cycle reveals how much light the "
        "star is genuinely giving off. Compare that with how bright it looks "
        "from here and you have its distance, which for Delta Cephei itself "
        "works out at about 980 light years. It was the first reliable way to "
        "measure anything beyond our own neighbourhood. Nearby is Mu Cephei, "
        "known as the [[Garnet Star]], one of the reddest stars that can be "
        "seen without a telescope."),

    "Cetus": (
        "a large, faint sea monster containing a star that vanishes and returns",
        "Cetus is big, dim, and sits low in the sky from northern latitudes, "
        "and the reason to seek it out is [[Mira]], the first star anyone "
        "recognised as varying in brightness. Over a cycle of about 332 days "
        "Mira fades from being comfortably visible to the naked eye down to a "
        "hundredth of that, far below what any eye can catch, so for months at "
        "a stretch there is simply nothing there. A Dutch pastor and "
        "astronomer, David Fabricius, recorded it appearing in 1596 and assumed "
        "he had seen a new star; it took decades of watching before astronomers "
        "accepted that a single star was doing this over and over on a "
        "schedule. The name is Greek, κῆτος, \"sea monster\", and it has drifted "
        "in meaning since: the same root gives us cetacean, the word for whales "
        "and dolphins, and Cetus is now usually drawn as a whale."),

    "Columba": (
        "the dove, sitting just south of the bright winter stars",
        "Columba is small and none of its stars are bright. It lies below "
        "[[Lepus]] and [[Canis Major]]. A Dutch mapmaker, Petrus Plancius, "
        "assembled it in 1592 out of stars that no existing constellation had "
        "claimed, in the space next to the great ship Argo, and the pairing was "
        "his point: this is the dove that Noah released from the ark to look "
        "for land. One of its fainter stars, Mu Columbae, is what astronomers "
        "call a runaway. It was flung out of the star-forming region around "
        "[[Orion]] roughly two and a half million years ago and is still "
        "travelling, along with two other stars that were thrown out of the "
        "same place at the same time and are now heading in three different "
        "directions."),

    "Corvus": (
        "four stars in a small crooked sail, to the west of Spica",
        "Corvus is compact and easy to pick out because everything around it is "
        "faint, which makes it a useful signpost: the eastern edge of the shape "
        "points down towards [[Spica]]. The Babylonians drew a raven in these "
        "same stars, so this small figure has carried the same bird for close "
        "to three thousand years. In the Greek version the crow was sent to "
        "fetch water, came back late with an invented excuse, and was thrown "
        "into the sky for it, next to Crater, the cup it should have filled, "
        "and [[Hydra]], the water snake it blamed. Both of those are real "
        "constellations, sitting either side of it."),

    "Draco": (
        "a long dragon winding between the two dippers",
        "Draco has no bright star, but it is very long, curling up between the "
        "[[Big Dipper]] and the [[Little Dipper]] and then round to a small "
        "head of four stars near [[Vega]]. [[Thuban]], in the dragon's tail, "
        "was the pole star when the Egyptian pyramids were built. The Earth's "
        "axis does not point in a fixed direction but slowly traces out a "
        "circle over about 26,000 years, so the title of pole star passes from "
        "one star to another, and around 3000 BC it was Thuban's turn. The name "
        "is the Greek δράκων, and it comes in turn from δέρκομαι, \"to watch\" or "
        "\"to stare\", so the dragon is not the one that breathes fire but the "
        "one that keeps its eyes on you."),

    "Eridanus": (
        "a river of faint stars running from Orion down to the far south",
        "Eridanus begins beside [[Rigel]], in the foot of [[Orion]], and winds "
        "further south than any other constellation before it ends at "
        "[[Achernar]], a bright star that never rises at all for most of "
        "Europe. That name is the Arabic آخر النهر, \"the end of the river\", "
        "which is exactly where it sits. Part way along is "
        "[[Ran|Epsilon Eridani]], one of the nearest stars known to have a "
        "planet going round it, at a distance of 10.5 light years."),

    "Hydra": (
        "the largest constellation of all, with only one bright star in it",
        "Hydra stretches a quarter of the way around the sky, from a small head south of the constellation Cancer to a tail that reaches beyond [[Spica]], and it takes more than six hours to rise completely. The only star in it that stands out is [[Alphard]], and its name explains why: it is the Arabic الفرد, \"the solitary one\", and it sits in an empty stretch of sky with nothing near it to compete. Everything else in the figure is faint."),

    "Hydrus": (
        "the little water snake of the south, not to be confused with the big "
        "one",
        "Hydrus is a thin triangle of faint stars lying between the two Magellanic Clouds, which are the small companion galaxies of our own, and it is close enough to the south pole of the sky that it never sets from most of the southern hemisphere. It is another of the twelve constellations drawn from the measurements Pieter Keyser and Frederick de Houtman brought home from the Dutch voyage to the East Indies in the 1590s. The name is an unfortunate choice: [[Hydra]] is the ancient water snake of the northern sky and Hydrus the modern one of the south, and only two letters separate them."),

    "Lepus": (
        "a hare crouched under the feet of Orion",
        "Lepus is a compact figure of moderately bright stars sitting directly below [[Orion]], and it goes unnoticed mostly because of what surrounds it. The traditional picture has the hare being run down by [[Canis Major]], the dog of Orion the hunter, at his feet. It contains one of the reddest stars in the sky, R Leporis, found by the English astronomer John Russell Hind in 1845 and called Hind's Crimson Star ever since. Its outer layers are full of soot, which absorbs the blue light and leaves a red deep enough to be obvious through binoculars."),

    "Libra": (
        "the scales of the zodiac, made out of the scorpion's claws",
        "Libra is dim, and the clue to what happened to it is in the names of its two brightest stars, [[Zubenelgenubi]] and [[Zubeneschamali]], which are the Arabic الزبانى الجنوبي, \"the southern claw\", and الزبانى الشمالي, \"the northern claw\". They are the claws of [[Scorpius]], which is what these stars were to the Greeks. Before the Greeks, the Babylonians had weighed the same stars as a set of scales, and the Romans went back to the scales again, so the name was lost for a few centuries and then recovered. The Greek reading is still sitting inside the star names, which is why they do not match the constellation they are in."),

    "Ophiuchus": (
        "a large figure holding a snake, and the thirteenth zodiac "
        "constellation",
        "Ophiuchus is a large figure holding a snake, and it sits on the band of sky the Sun travels through during the year. That band crosses thirteen constellations rather than the traditional twelve, and Ophiuchus is the one that never made the list, even though the Sun spends about three weeks a year inside it, which is longer than it spends in [[Scorpius]]. It also contains Barnard's Star, which moves across the sky faster than any other star we know: it covers the width of a full Moon every 180 years."),

    "Pavo": (
        "the peacock, deep in the southern sky",
        "Pavo is faint apart from its brightest star, which is simply called [[Peacock]]. That name is recent and thoroughly bureaucratic: in the 1930s the British air almanac needed every star used for navigation to have a name a pilot could say out loud, found that this one had never been given one, and issued it a name. The constellation is another of the twelve drawn from the measurements Pieter Keyser and Frederick de Houtman brought home from the Dutch voyage to the East Indies in the 1590s. It also contains NGC 6752, one of the closest of the great balls of ancient stars that orbit our galaxy."),

    "Perseus": (
        "the hero, lying in a rich stretch of the Milky Way",
        "Perseus is a long curve of stars between [[Cassiopeia's W]] and [[Capella]], and it sits in the [[Milky Way]], which is why the [[Double Cluster]] lies on its edge. [[Algol]] is the head of the Medusa that Perseus is carrying, and it does something you can watch: every 2.87 days it fades by more than half and then recovers, because a dimmer companion star passes in front of it. The [[Perseids]], the most reliable meteor shower of the year, appear to come from a point inside this constellation every August."),

    "Phoenix": (
        "a southern bird constellation, next to the end of the river",
        "Phoenix is a modest figure below [[Achernar]], with one reasonably bright star, [[Ankaa]], and not much else. The bird that burns itself and rises from its own ashes is a very old story, but this constellation is not old at all: there was nothing drawn in this part of the sky until Pieter Keyser and Frederick de Houtman measured these stars on the Dutch voyage to the East Indies in the 1590s, and the German astronomer Johann Bayer printed them in his atlas in 1603. Everything this far south was blank on European charts before that, because no European chart-maker had been there."),

    "Piscis Austrinus": (
        "one bright star, and almost nothing else",
        "Piscis Austrinus is the southern fish, and nearly all of it is faint enough to be a struggle. The exception is [[Fomalhaut]], the one bright star in a wide, empty stretch of autumn sky, which sits at the fish's mouth and is named for it: the Arabic فم الحوت, \"the mouth of the fish\". The figure is old, in the Babylonian lists two thousand years before the Greeks, and it was drawn as a fish drinking the water poured out by [[Aquarius]] above it."),

    "Serpens": (
        "the only constellation that comes in two separate pieces",
        "Serpens is a snake cut in half by the man holding it. [[Ophiuchus]] "
        "stands in the middle of it, so the head lies to the west of him and "
        "the tail to the east, and the two halves are counted as a single "
        "constellation with another one in the gap between them. Nothing else "
        "in the sky is arranged this way. The tail contains the "
        "[[Eagle Nebula]], a cloud of gas and dust with columns of denser "
        "material standing inside it where stars are forming, which is where "
        "the photograph known as the Pillars of Creation was taken."),

    "Triangulum Australe": (
        "three stars, and a plainer name than most",
        "A small, neat triangle of second and third magnitude stars below [[The Pointers]], and easier to pick out than the northern Triangulum it is named after. It was drawn from the measurements Pieter Keyser and Frederick de Houtman brought home from the Dutch voyage to the East Indies in the 1590s, the same batch that produced [[Grus]], [[Pavo]] and [[Phoenix]]. [[NGC6025|NGC 6025]], an open cluster, sits at the northern corner."),
}
