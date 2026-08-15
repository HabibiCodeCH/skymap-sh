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
        "The Sun is a middling yellow star of a kind there are billions of, "
        "and the only one close enough to show a disc. Its light takes eight "
        "minutes and twenty seconds to reach here, so the Sun you see setting "
        "set eight minutes ago. Never look at it through binoculars or a "
        "telescope without a proper solar filter."),

    "Moon": (
        "the only other world anyone has stood on",
        "The Moon is a quarter of Earth's width and drifts about four "
        "centimetres further away each year. It keeps one face turned towards "
        "us, so every photograph ever taken from Earth shows the same side. "
        "The best time to look is not the full Moon, which is flat and "
        "glaring, but a few days either side of half, when shadows along the "
        "terminator throw the craters into relief."),

    "Mercury": (
        "the closest planet to the Sun, and the hardest to see",
        "Mercury never strays more than 28 degrees from the [[Sun]], which means it is only ever visible in twilight, low down, for a few weeks at a time. Copernicus is said to have died without ever seeing it. It has no atmosphere to speak of and a day two-thirds as long as its year."),

    "Venus": (
        "the brightest thing in the sky after the Sun and Moon",
        "Venus is bright enough to cast a shadow on a dark night and is routinely reported as an aircraft or a UFO. It shows phases like the [[Moon]], which is what Galileo saw in 1610 and what settled the argument about whether everything orbits the Earth. Under the cloud it is 460 degrees and dry."),

    "Mars": (
        "the red planet, and the only one whose surface we can see",
        "Mars is half Earth's width, cold, and rusty enough to look orange to "
        "the naked eye. Every 26 months Earth catches up with it and it comes "
        "close enough for a small telescope to show dark markings and a polar "
        "cap. In between it shrinks to a featureless dot."),

    "Jupiter": (
        "the largest planet, and the easiest thing to point a telescope at",
        "Jupiter is two and a half times as massive as every other planet in the solar system put together. Its four big moons are visible with binoculars and change position from one night to the next, which is what Galileo noticed in 1610 and why they carry his name. The Great Red Spot is a storm wider than Earth, though it has been shrinking for a century. Its name is the oldest of any god in the sky. Jupiter, the Greek \"Zeus pater\" and the Sanskrit \"Dyaus Pitar\" are the same phrase, all three descended from one reconstructed form."),

    "Saturn": (
        "the one with the rings",
        "Saturn is the sight that makes people buy a telescope. The rings are "
        "visible in almost anything with lenses, though how open they look "
        "changes over its 29-year orbit: edge-on and nearly invisible in 2025, "
        "wide open again by the early 2030s. They are mostly water ice, and "
        "in places only ten metres thick."),

    "Uranus": (
        "the first planet nobody knew was there",
        "Uranus sits at the very edge of naked-eye visibility, which is why it "
        "went uncatalogued until Herschel found it in 1781. It is tipped on "
        "its side, so each pole spends 42 years in sunlight and 42 in "
        "darkness. In a telescope it is a small blue-green disc and nothing "
        "more."),

    "Neptune": (
        "the planet found with mathematics before anyone looked",
        "Neptune was predicted from wobbles in the orbit of [[Uranus]] and found within a degree of where the arithmetic said it would be. It is never visible to the naked eye. Its winds are the fastest in the solar system, over 2,000 kilometres an hour, on a world that receives one nine-hundredth of our sunlight."),

    # ---------------------------------------------------------------- stars
    "Sirius": (
        "the brightest star in the night sky",
        "Sirius is bright mostly because it is close: at 8.6 light years it is one of the nearest stars, and only twice the [[Sun]]'s width. Low in the sky it flashes red and green as the atmosphere splits its light, which gets it reported as something else more often than any other star. It has a white dwarf companion the size of Earth."),

    "Betelgeuse": (
        "a red supergiant near the end of its life",
        "Betelgeuse is so large that, if it replaced the [[Sun]], its surface would reach past the orbit of [[Mars]]. It will explode as a supernova at some point in the next hundred thousand years, and when it does it will be bright enough to read by. It is also the most famous typo in the sky. The initial \"ya\" was read as \"ba\" by medieval monks who could not read Arabic properly (the two letters look alike), giving Bat al-Jawza', which means nothing in any language, and then Bedalgeuze in the Alfonsine Tables of about 1250."),

    "Rigel": (
        "a blue supergiant, and the brightest star in Orion",
        "Rigel outshines [[Betelgeuse]] despite being the beta star of [[Orion]], because it is genuinely luminous rather than merely close: around 120,000 times the [[Sun]]'s output, from 860 light years away. Blue-white stars burn like this for only a few million years."),

    "Vega": (
        "the star that defined the brightness scale",
        "Vega was the zero point every other star's magnitude was measured "
        "against, which is why its magnitude is almost exactly 0. It was the "
        "pole star 12,000 years ago and will be again in another 12,000, as "
        "Earth's axis wobbles. It spins so fast it is visibly flattened."),

    "Polaris": (
        "the north star, currently",
        "Polaris sits within a degree of the celestial pole, so it barely "
        "moves while everything else wheels around it. That is temporary: "
        "precession swings the pole through a 26,000-year circle, and Polaris "
        "has only held the job for about a thousand years. It is a Cepheid "
        "variable, and a triple star."),

    "Arcturus": (
        "an orange giant, and the brightest star north of the equator",
        "Arcturus is an old star that has already left the main sequence and swollen to 25 times the [[Sun]]'s width. It is moving through the galaxy at a steep angle to everything around it, which suggests it arrived with a small galaxy the [[Milky Way]] absorbed long ago. Its name means the bear guard, and it follows the Great Bear around the pole. One of the very few star names that has come down unchanged from Greek without passing through Arabic on the way."),

    "Antares": (
        "the heart of the scorpion, and a rival to Mars",
        "The name means \"rival of [[Mars]]\", which is what it looks like: a red supergiant sitting on the ecliptic sky, close enough in colour to be mistaken for the planet. You can tell them apart only by watching which one is moving. It is roughly 700 times the [[Sun]]'s width. Like [[Betelgeuse]] it will end as a supernova. Named for its colour."),

    "Altair": (
        "the flying eagle, and one half of a Chinese love story",
        "From an-nasr at-ta'ir \u0627\u0644\u0646\u0633\u0631 \u0627\u0644\u0637\u0627\u0626\u0631 "
        "the flying eagle, against [[Vega]]'s falling one. In Chinese the "
        "same star is the Cowherd, kept apart from the Weaver Girl by the "
        "[[Milky Way]] and allowed across it one night a year."),

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

    # -------------------------------------------------------------- deep sky
    "Andromeda Galaxy": (
        "the furthest thing you can see without a telescope",
        "[[Andromeda]] is 2.5 million light years away. It spans six times the width of the full [[Moon]], though only the bright core shows without optics. It is heading towards us and will merge with the [[Milky Way]] in about four billion years. Named for the constellation it sits in. Al-Sufi recorded it in 964 as a little cloud, which is the oldest surviving description of anything outside our own galaxy, written a thousand years before anyone knew what it was."),

    "Orion Nebula": (
        "a star nursery visible to the naked eye",
        "The middle \"star\" of [[Orion]]'s sword is not a star: it is a cloud of gas 24 light years across with new stars forming inside it. Four of them, the Trapezium, are what light the whole thing up. Binoculars show the shape; a small telescope shows the wisps."),

    "Hercules Cluster": (
        "half a million stars in a ball",
        "A globular cluster, one of about 150 orbiting the [[Milky Way]], it is amongst the oldest things in the galaxy at roughly 11.6 billion years. Through binoculars, it is a fuzzy dot. With a telescope, the edges break into individual stars. A radio message was aimed at it in 1974. It should arrive in 25,000 years."),

    "Pleiades": (
        "the seven sisters, though most people count six",
        "The Pleiades are young stars, around 100 million years old, still loosely travelling together. Six are easy to the naked eye and the seventh is a common eyesight test; binoculars show dozens. They span four [[Moon]]-widths, which is why a telescope is the wrong instrument for them."),

    "Whirlpool Galaxy": (
        "the first galaxy anyone recognised as a spiral",
        "Lord Rosse drew its spiral arms in 1845, having seen it through the "
        "largest telescope in the world, a six-foot mirror at Birr Castle. "
        "He had sketched the [[Crab Nebula]] the year before. Nobody knew "
        "what he was looking at: another eighty years passed before spirals "
        "were shown to be galaxies of their own rather than clouds inside "
        "our own. The small companion on the end of an arm, NGC 5195, is not "
        "parked there but passing behind, and its pull is what draws the "
        "arms so sharply."),

    "Ring Nebula": (
        "a dying star seen down the barrel",
        "It is a shell of gas thrown off by a star like the [[Sun]] as it collapsed, lit from inside by the white dwarf left behind. It is small, about one arcminute, so it needs magnification rather than aperture. This is roughly what the Sun will do in five billion years."),

    "Dumbbell Nebula": (
        "the brightest planetary nebula in the sky",
        "The same kind of object as the [[Ring Nebula]], the Dumbbell Nebula is eight times larger and much easier to see: binoculars from a dark site will show it. The name \"planetary nebula\" is a historical mistake: they looked like planetary discs in early telescopes but have nothing to do with planets."),

    "Lagoon Nebula": (
        "a naked-eye nebula from a dark sky",
        "It sits in the densest part of the [[Milky Way]] towards the galactic "
        "centre, and from somewhere properly dark it is visible without "
        "optics as a brighter patch in the band. The dark lane that gives it "
        "its name splits it in two."),

    "Sombrero Galaxy": (
        "a galaxy seen almost exactly edge-on",
        "It is tilted six degrees from edge-on, so its dust lane cuts across the bright bulge as a hard dark line. It has an unusually large population of globular clusters, nearly 2,000 of them, and a black hole a billion times the [[Sun]]'s mass."),

    "Crab Nebula": (
        "the wreckage of a star that exploded in 1054",
        "Chinese and Japanese astronomers recorded a new star in Taurus in July 1054, bright enough to see in daylight for three weeks. What is left of this supernova is the Crab Nebula. It still expanding at 1,500 kilometres a second, with a neutron star at the centre spinning 30 times a second. Its name comes from a sketch Lord Rosse made in 1844 through the telescope at Birr Castle. The drawing looks like a crab and, even if the later photographs do not, the name survived."),

    "Triangulum Galaxy": (
        "the third galaxy in our local group, and a test of dark skies",
        "It is large and diffuse, which makes it a poor target for a "
        "telescope and a good one for binoculars. Under genuinely dark skies "
        "some people can see it with the naked eye, which makes it a "
        "reasonable contender for the furthest thing visible unaided."),

    "Double Cluster": (
        "two open clusters side by side",
        "The two clusters sit close enough together to share one field of view and were catalogued as a pair by Hipparchus. Both are young, around 12 million years, and actually physically associated rather than a line-of-sight coincidence."),

    "Milky Way": (
        "the galaxy we are inside, seen edge on",
        "The band is the disc of our own galaxy viewed from within it, a "
        "hundred thousand light years across and a few hundred billion stars, "
        "with us about halfway out from the middle. It is brightest and "
        "widest towards [[Teapot|Sagittarius]], because that is the direction of the "
        "centre. Roughly a third of the world now lives under skies too "
        "bright to see it at all."),

    # --------------------------------------------------------- meteor showers
    "Perseids": (
        "the most reliable shower of the year",
        "Earth passes through the dust of comet Swift-Tuttle every August, "
        "and the Perseids arrive in warm weather at a comfortable hour, which "
        "is why they are the shower most people have seen. Around 100 an hour "
        "at the peak from a dark site. You do not need to look at the radiant: "
        "meteors appear all over the sky."),

    "Geminids": (
        "the best shower of the year, if you can stand the cold",
        "The Geminids are the most intense meteor shower at 150 per hour. Their radiant is high in the middle of the night in December. They come from an asteroid rather than a comet, which is unusual, and the meteors are slow and often bright."),

    "Quadrantids": (
        "a sharp peak most people miss",
        "The Quadrantids can match the [[Geminids]], but the peak lasts only a few hours instead of a day or two, so the date matters more than usual and it is easy to be on the wrong side of the planet for it. Named after a constellation that no longer exists."),

    "Lyrids": (
        "the oldest recorded shower",
        "Chinese records describe Lyrid meteors falling \"like rain\" in 687 "
        "BC, which makes this the longest continuously observed shower. Normal "
        "years give about 18 an hour, but it has produced sudden outbursts "
        "several times without warning."),

    # -------------------------------------------------------------- asterisms
    "Big Dipper": (
        "seven stars that point at the pole",
        "It is not a constellation, but a part of Ursa Major, and probably the most widely recognised shape in the northern sky. The two stars at the end of the bowl point at [[Polaris]]. The middle star of the handle, [[Mizar]], has a companion visible to good eyesight, which was used as a vision test for centuries."),

    "Orion's Belt": (
        "three stars in a row, and the easiest signpost in the sky",
        "[[Alnitak]], [[Alnilam]] and [[Mintaka]] are nearly evenly spaced and nearly equally bright, which is why no other pattern gets confused with them. Follow the line down and left to [[Sirius]], up and right to [[Aldebaran]]. The sword hangs below the belt, with the [[Orion Nebula]] in the middle of it."),

    "Summer Triangle": (
        "three bright stars in three constellations",
        "[[Vega]], [[Deneb]] and [[Altair]] are the first stars out on a summer evening and span most of the sky overhead. The [[Milky Way]] runs straight through the middle of the triangle, so from a dark site the shape frames the best part of the band."),

    "Southern Cross": (
        "the smallest constellation, and the southern signpost",
        "Crux has no pole star to point at, so the long axis of the cross is "
        "extended four and a half times to find where the south celestial pole "
        "is. It appears on five national flags. The Coalsack, a dark nebula, "
        "sits beside it as an obvious hole in the [[Milky Way]]."),

    "Little Dipper": (
        "the pole star, and six fainter ones behind it",
        "Ursa Minor is drawn as a smaller ladle than the [[Big Dipper]], and "
        "only two of its stars are easy: [[Polaris]] at the tip of the handle "
        "and [[Kochab]] in the bowl. The rest are faint enough that counting all "
        "seven is a fair test of how dark a sky is. The Greeks called it "
        "Kynosoura, the dog's tail, which is where the word cynosure comes "
        "from: the thing everyone steers by."),

    "Cassiopeia's W": (
        "five bright stars in a W, opposite the Big Dipper",
        "The W sits on the far side of [[Polaris]] from the [[Big Dipper]], so "
        "from northern latitudes one of the two is always up and whichever is "
        "higher points down at the pole. Cassiopeia was a queen punished for "
        "boasting, tied to her chair and turned around the pole, which is why "
        "the W spends half of each night upside down. Tycho's supernova of "
        "1572 went off in this figure and was bright enough to see in "
        "daylight."),

    "Northern Cross": (
        "the bright bones of Cygnus, the swan",
        "[[Deneb]] is the top of the cross and [[Albireo]] the foot, a double star "
        "that splits into gold and blue in almost any telescope. The whole "
        "figure lies along the [[Milky Way]], in the richest star fields in "
        "the northern sky. On autumn evenings it stands upright over the "
        "western horizon."),

    "Keystone": (
        "four faint stars in Hercules, and the way to find M13",
        "A keystone is the wedge at the top of an arch, which is roughly what "
        "these four make. Nothing in it is bright, but it is worth finding: a "
        "third of the way down the western side sits the [[Hercules Cluster]], "
        "half a million stars in a ball. Hercules is a large constellation "
        "with no bright star in it at all."),

    "Corona Borealis": (
        "a small arc of seven stars, and one of the neatest shapes in the sky",
        "The northern crown is a half circle between [[Kite|Bootes]] and "
        "[[Keystone|Hercules]], with "
        "[[Alphecca]] the only bright star in it. Arabic astronomers called it "
        "al-Fakka, the broken dish, because the circle does not close. It also "
        "holds T Coronae Borealis, which flares to naked-eye brightness every "
        "80 years or so: it last did it in 1946 and has been expected again "
        "for the past few years."),

    "Kite": (
        "the shape of Bootes, hanging under Arcturus",
        "[[Arcturus]] is the knot at the bottom and the rest of Bootes fans "
        "out above it, a long narrow kite standing on its point. The way in is "
        "the handle of the [[Big Dipper]]: follow its curve away from the bowl "
        "and it lands on Arcturus. Bootes is the herdsman or the ploughman, "
        "walking behind the bear, though once the kite has been pointed out it "
        "is hard to see the herdsman again."),

    "Job's Coffin": (
        "four stars in Delphinus, in a box the size of a thumbnail",
        "Delphinus is small, faint and unmistakable: four stars in a lozenge "
        "with a fifth trailing off as a tail. Where the name Job's Coffin came "
        "from is not known, and it turns up in English in the 1800s with no "
        "explanation attached. The two brightest stars carry a joke instead of "
        "a history: [[Sualocin]] and [[Rotanev]] is Nicolaus Venator backwards, an "
        "assistant at Palermo who slipped his own name into the catalogue in "
        "1814."),

    "Teapot": (
        "eight stars in Sagittarius that look like a teapot and nothing like "
        "an archer",
        "The archer is meant to be a centaur drawing a bow. What the bright "
        "stars actually make is a teapot, with a lid, a handle and a spout. "
        "Steam appears to rise from the spout because the [[Milky Way]] is at "
        "its thickest here: the centre of the galaxy is a few degrees off, "
        "behind 25,000 light years of dust. The name is 20th century and has "
        "more or less replaced the archer in practice."),

    "Great Square": (
        "four stars marking the body of Pegasus, and an empty patch of sky",
        "The square is large, obvious and nearly empty. Counting the stars you "
        "can see inside it is a standard way to judge how dark a sky is, and "
        "in a town the answer is usually none. The north-east corner is not in "
        "Pegasus at all: [[Alpheratz]] was shared with Andromeda for centuries and "
        "went to [[Andromeda]] when the borders were fixed in 1930, so the "
        "square of Pegasus has one corner in another constellation."),

    "Hyades V": (
        "the V of the bull's face, and the nearest open cluster",
        "The V is the Hyades, about 150 light years away and the closest open "
        "cluster to us, with [[Aldebaran]] in front of it by chance rather "
        "than belonging to it. Its stars share one motion across the sky, "
        "which is how the distance was first measured, and that measurement "
        "was an early rung of the ladder everything further out is judged "
        "against. The Greek name has never been settled: the rainers, from a "
        "verb meaning to rain, or the piglets, which is what the Romans took "
        "it for when they called them Suculae."),

    "Winter Triangle": (
        "three of the brightest stars in the sky, in an almost equal triangle",
        "[[Sirius]], [[Procyon]] and [[Betelgeuse]] are amongst the brightest "
        "stars in the sky, and together they draw a close to perfect "
        "equilateral triangle. The name is modern and the shape useful "
        "because all three are bright enough to survive city lights. "
        "Betelgeuse is the odd corner: red, variable, and several hundred "
        "times the [[Sun]]'s width."),

    "Winter Hexagon": (
        "six bright stars around Orion, and most of the winter sky at once",
        "[[Sirius]], [[Procyon]], [[Pollux]], [[Capella]], [[Aldebaran]] and "
        "[[Rigel]] make a rough ring with [[Betelgeuse]] inside it. It spans "
        "six constellations and about a quarter of the sky, which is what "
        "makes it worth knowing: find two corners and the rest of winter is "
        "fixed. Also called the Winter Circle."),

    "Sickle": (
        "a backwards question mark that makes the head of Leo",
        "[[Regulus]] is the dot at the bottom of the question mark and the "
        "curve above it is the lion's mane. Regulus sits almost exactly on the "
        "ecliptic, so the Moon and the planets pass close to it several times "
        "a year. The Leonid meteors radiate from inside the Sickle every "
        "November, and roughly every 33 years that shower has produced storms "
        "of thousands an hour."),

    "Spring Triangle": (
        "three bright stars that carry the spring sky",
        "[[Arcturus]], [[Spica]] and [[Regulus]] are what is left when the "
        "winter stars have gone and the summer ones have not arrived. The way "
        "in is the handle of the [[Big Dipper]]: arc to Arcturus, then carry "
        "the same curve on to Spica. Some versions use [[Denebola]], in the "
        "tail of [[Sickle|Leo]], in place of Regulus."),

    "Great Diamond": (
        "the Spring Triangle with a fourth corner added",
        "[[Arcturus]], [[Spica]] and [[Denebola]] with [[Cor Caroli]] at the "
        "northern point make a kite about 50 degrees across, also called the "
        "Diamond of [[Virgo]]. The Virgo cluster of galaxies sits inside it, "
        "towards the Denebola end. Cor Caroli means the heart of Charles: it "
        "was named in the 1600s for an English king, and is one of very few "
        "stars named after a real person."),

    "The Pointers": (
        "the two stars that point at the Southern Cross",
        "Alpha and Beta Centauri sit east of the cross, and a line drawn "
        "through them runs into it. That matters because there are two crosses "
        "in this part of the sky and only one of them is the "
        "[[Southern Cross]]. Alpha Centauri is the nearest star system to us "
        "at 4.3 light "
        "years, and almost any telescope splits it into two suns. In the "
        "northern hemisphere the same name is used for the two stars at the "
        "end of the [[Big Dipper]] bowl, which point at [[Polaris]]."),

    "False Cross": (
        "four stars that get mistaken for the Southern Cross",
        "It is bigger than the real cross, fainter, and has nothing pointing "
        "at it, and it has been steered by in error often enough to earn the "
        "name. The [[Southern Cross]] has a fifth star inside the shape and "
        "the [[Milky Way]] running through it; the False Cross sits off to one "
        "side of the band. Two of its stars are in [[Carina]] and two in "
        "[[Vela]], both pieces of the same broken-up ship."),

    # ------------------------------------------------- constellation figures
    # The 57 drawn figures include real constellations as well as asterisms.
    # These are the constellations: what the shape is, what is in it worth
    # looking at, and where the name came from, in that order.
    "Lyra": (
        "a small parallelogram hanging from Vega",
        "[[Vega]] is the fifth brightest star in the sky and everything else "
        "in Lyra is faint, so the constellation is really one bright star with "
        "a small parallelogram under it. The [[Ring Nebula]] sits between the "
        "two lower corners. The lyre is Orpheus's, but older Greek and Arabic "
        "lists drew a bird here instead, which is where Vega's name comes "
        "from: the falling eagle."),

    "Aquila": (
        "the eagle, with Altair at its neck",
        "[[Altair]] has fainter stars on both sides, which is the quickest "
        "way to identify it: three stars in a short line with the middle "
        "one bright. Altair is one of the fastest spinning stars anyone has "
        "measured, turning once in about nine hours and visibly flattened by "
        "it. The figure has been an eagle for as long as there are records, in "
        "Babylonian lists as well as Greek ones."),

    "Scorpius": (
        "one of the few constellations that looks like what it is called",
        "A curved line of stars with [[Antares]] red in the middle and a real "
        "hook of a tail, low in the south from Europe and overhead in the "
        "tropics. It has been a scorpion for at least 3,000 years: the "
        "Babylonians drew the same animal in the same stars. Its claws were "
        "taken away to make [[Libra]], and the two brightest stars of Libra "
        "are still named the northern and southern claw."),

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
        "the best-drawn figure in the sky",
        "A rectangle of four bright stars with a belt of three across the "
        "middle and a sword hanging off it, and no other constellation is as "
        "hard to mistake. [[Betelgeuse]] at one shoulder is red and [[Rigel]] "
        "at the opposite foot is blue-white, which makes it the easiest colour "
        "comparison in the sky. Babylonian lists call the same figure the True "
        "Shepherd of Anu, and where the Greek name Orion came from is not "
        "known."),

    "Auriga": (
        "a pentagon of stars with Capella at the top",
        "A rough pentagon at the top of which sits [[Capella]], the sixth "
        "brightest star in the sky. It is nearly overhead on winter evenings "
        "from northern latitudes. Just below it is a small triangle of faint "
        "stars called the Kids, which is what Capella hints at: the little "
        "she-goat. Auriga is the charioteer, and the goats are what he is "
        "carrying."),

    "Grus": (
        "the crane, and the best of the southern bird figures",
        "Grus sits below [[Piscis Austrinus]] and is unusually well shaped for "
        "a modern constellation: two second magnitude stars and a long neck of "
        "fainter ones. It is one of twelve figures that came out of a single "
        "voyage. Keyser and de Houtman logged the southern stars on a Dutch "
        "trading run in the 1590s and Bayer put them on a chart in 1603, "
        "because nobody who drew star maps had ever seen that part of the sky "
        "before."),

    "Canis Major": (
        "the dog behind Orion, carrying the brightest star in the sky",
        "[[Sirius]] is bright enough that the rest of the figure barely "
        "registers, but there is a dog there, with a triangle for the "
        "hindquarters and [[Mirzam]] in front of it as the announcer. Sirius "
        "rising just before the Sun marked the Nile flood for the Egyptians, "
        "and it is where the dog days of summer come from. M41, an open "
        "cluster visible without help from a dark site, sits four degrees "
        "below Sirius."),

    "Canis Minor": (
        "two stars, and one of them is Procyon",
        "[[Procyon]] and [[Gomeisa]] are essentially the whole constellation, "
        "which makes it one of the emptiest anybody bothers to name. Procyon "
        "means before the dog: from mid-northern latitudes it rises about "
        "half an hour ahead of [[Sirius]], so the name is a piece of practical "
        "advice about what is coming next."),

    "Gemini": (
        "two lines of stars ending in two bright ones",
        "[[Castor]] and [[Pollux]] are the heads, and two roughly parallel "
        "lines of fainter stars run down to the feet at the edge of the "
        "[[Milky Way]]. Pollux is the brighter of the two despite being "
        "lettered Beta, and whether Bayer got it wrong or Castor has faded "
        "since is not settled. Castor is not one star but six, three pairs "
        "orbiting each other. The Babylonians drew the Great Twins in the same "
        "stars."),

    "Virgo": (
        "the second largest constellation, and nearly all of it faint",
        "In Virgo, only [[Spica]] is bright; the rest is a wide shape of "
        "second and third magnitude stars. Spica means the ear of wheat, and "
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
        "a large southern constellation holding the nearest stars to us",
        "Alpha Centauri is 4.3 light years away and splits into two suns in "
        "almost any telescope; a third star, Proxima, is closer still and far "
        "too faint to see. Centaurus also has [[Omega Centauri]], the largest "
        "globular cluster in the sky and an obvious smudge to the naked eye. "
        "The [[Southern Cross]] used to be part of this figure, between the "
        "centaur's front legs."),

    "Carina": (
        "the keel of a ship that was broken up",
        "Argo Navis was the largest constellation ever drawn, and Lacaille cut "
        "it into pieces in the 1750s: the keel, the stern and the sails. "
        "Carina kept [[Canopus]], the second brightest star in the sky, and "
        "the [[Carina Nebula]], which is larger and brighter than the "
        "[[Orion Nebula]] and less famous only because it is too far south "
        "for most "
        "people to see. Eta Carinae inside it came close to exploding in 1843 "
        "and is still there."),

    "Vela": (
        "the sails, one third of a broken-up ship",
        "Vela has no alpha or beta star. When Argo Navis was cut up the Bayer "
        "letters went with the pieces, and those two stayed with [[Carina]], "
        "so Vela starts at gamma. Gamma Velorum is the brightest Wolf-Rayet "
        "star in the sky, a hot star throwing its outer layers off. The Vela "
        "supernova remnant, from an explosion around 11,000 years ago, covers "
        "a large part of the constellation."),

    "Puppis": (
        "the stern, and the third piece of the ship",
        "Puppis is the part of Argo Navis people forget, but the [[Milky Way]] "
        "runs the length of it and it carries several open clusters bright "
        "enough to see without help. Zeta Puppis is one of the hottest and "
        "most luminous stars that can be seen with the naked eye anywhere. "
        "Like [[Vela]] it has no alpha or beta: both went to [[Carina]] when "
        "the ship was divided."),

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
        "the goat-fish, and the faintest constellation in the zodiac",
        "A wide, dim triangle of stars where the figure is stranger than "
        "anything you can see: a goat in front and a fish behind. That is not "
        "a Greek invention. It is the goat-fish of the Babylonian star lists, "
        "and it has come down about 3,000 years without being tidied up. Alpha "
        "Capricorni is a naked-eye double, two unrelated stars a long way "
        "apart that happen to line up."),

    "Cepheus": (
        "a house with a steep roof, near the pole",
        "Cepheus is faint but easy once seen: five stars in the outline of a "
        "child's drawing of a house, with the roof pointing at [[Polaris]]. "
        "Delta Cephei is the star the distance scale of the universe rests on. "
        "Its brightness cycles every 5.4 days, and in 1912 Henrietta Leavitt "
        "showed that for stars like it the length of the cycle gives away the "
        "real brightness, which turns how bright it looks into how far away it "
        "is. Mu Cephei nearby is the [[Garnet Star]], one of the reddest visible "
        "to the naked eye."),

    "Cetus": (
        "a large sea monster, and a star that disappears",
        "Cetus is big, faint and low from northern latitudes, and the reason "
        "to find it is [[Mira]], the first variable star anybody identified. "
        "Mira runs from third magnitude down to tenth and back over about 332 "
        "days, so for months at a time it is not there; Fabricius saw it "
        "appear in 1596 and it took decades to accept that it was coming back "
        "on a schedule. The name is Greek for a sea monster, and it has "
        "drifted since: the same word gives cetacean, and Cetus is now usually "
        "drawn as a whale."),

    "Columba": (
        "the dove, just south of the bright winter stars",
        "Columba is small and moderately faint, under [[Lepus]] and "
        "[[Canis Major]]. Plancius made it in 1592 out of unassigned stars "
        "beside the "
        "ship Argo, and the pairing is deliberate: this is Noah's dove, "
        "released from the ark. Mu Columbae, one of its fainter stars, is a "
        "runaway thrown out of the [[Orion]] region about two and a half "
        "million years ago, one of three now flying apart in three "
        "directions."),

    "Corvus": (
        "four stars in a small crooked sail, west of Spica",
        "Corvus is compact and obvious in a part of the sky where everything "
        "else is faint, which makes it a useful signpost: its eastern edge "
        "points down at [[Spica]]. The Babylonians drew a raven here too, so "
        "this small figure has kept the same bird for about 3,000 years. In "
        "the Greek story the crow was sent for water, came back late with an "
        "excuse, and was thrown into the sky beside the cup and the water "
        "snake, which are the constellations either side of it."),

    "Draco": (
        "a long dragon winding between the two dippers",
        "Draco has no bright star but it is long, curling up between the "
        "[[Big Dipper]] and the [[Little Dipper]] and round to a small head "
        "near [[Vega]]. [[Thuban]], in the tail, was the pole star when the "
        "Egyptian pyramids were built: the pole travels a 26,000 year circle "
        "and it was Thuban's turn around 3000 BC. The Greek word behind the "
        "name comes from a verb meaning to watch, so the dragon is the one "
        "that stares."),

    "Eridanus": (
        "a river of faint stars running from Orion to the far south",
        "Eridanus starts beside [[Rigel]] and meanders further south than any "
        "other constellation, ending at [[Achernar]], which never rises for "
        "most of Europe. Achernar is Arabic for the end of the river, which is "
        "exactly where it sits. Epsilon Eridani, part way along, is one of the "
        "nearest stars known to have a planet, at 10.5 light years."),

    "Hydra": (
        "the largest constellation, and one bright star",
        "Hydra stretches a quarter of the way round the sky and takes over six "
        "hours to rise completely, from a small head south of Cancer to a tail "
        "beyond [[Spica]]. The only star that stands out is [[Alphard]], and "
        "the name says why: the solitary one, sitting in an empty patch with "
        "nothing near it. Everything else in the figure is third magnitude or "
        "fainter."),

    "Hydrus": (
        "the little water snake, and not the big one",
        "Hydrus is a thin triangle of third magnitude stars between the two "
        "Magellanic Clouds, close enough to the south pole that it never sets "
        "from most of the southern hemisphere. It is one of the twelve "
        "constellations Keyser and de Houtman brought back from the 1590s "
        "voyage. The name is a nuisance: [[Hydra]] is the ancient water snake "
        "in the north and Hydrus the modern one in the south, and one letter "
        "separates them."),

    "Lepus": (
        "a hare crouched under Orion's feet",
        "Lepus is a compact figure of moderately bright stars directly below "
        "[[Orion]], and it goes unnoticed because of what is around it. The "
        "story is that the hare is being run down by [[Canis Major]] at the "
        "hunter's feet. R Leporis, called Hind's Crimson Star, is here: a "
        "carbon star red enough that the colour is obvious in binoculars."),

    "Libra": (
        "the scales, made out of the scorpion's claws",
        "Libra is dim, and the giveaway is the names of its two brightest "
        "stars: [[Zubenelgenubi]] and [[Zubeneschamali]], the southern claw and the "
        "northern claw. They are the claws of [[Scorpius]], which is what "
        "these stars were to the Greeks. The Babylonians had weighed them as "
        "scales before that and the Romans went back to the scales, so the "
        "name was lost and recovered, and the older one is still sitting in "
        "the star names."),

    "Ophiuchus": (
        "a large figure holding a snake, and the thirteenth zodiac "
        "constellation",
        "The Sun spends about three weeks a year in Ophiuchus, longer than it "
        "spends in [[Scorpius]], which is the fact behind every few years of "
        "headlines about a new star sign. Astrology has used twelve equal "
        "signs for 2,000 years and the constellations have never been equal in "
        "size, so nothing about this is new. Barnard's Star is here, the "
        "fastest moving star in the sky: it crosses a Moon's width of sky "
        "every 180 years."),

    "Pavo": (
        "the peacock, deep in the southern sky",
        "Pavo is faint apart from its brightest star, which is simply called "
        "[[Peacock]]. That name is recent and administrative: a British air "
        "almanac in the 1930s needed every navigational star to have a name "
        "and gave one to the few that had none. It is another of the twelve "
        "figures from the Dutch voyage of the 1590s. NGC 6752 sits here, one "
        "of the closest globular clusters to us."),

    "Perseus": (
        "the hero, in a rich part of the Milky Way",
        "Perseus is a long curve of stars between [[Cassiopeia's W]] and "
        "[[Capella]], lying in the [[Milky Way]], which is why the "
        "[[Double Cluster]] is on its edge. [[Algol]] is the head of the "
        "Medusa he is "
        "carrying, and it fades by more than a magnitude every 2.87 days. The "
        "[[Perseids]] radiate from this figure every August."),

    "Phoenix": (
        "a southern bird next to the end of the river",
        "Phoenix is a modest figure below [[Achernar]] with one second "
        "magnitude star, [[Ankaa]]. The bird that burns and comes back is a very "
        "old story, but the constellation is not: nothing was drawn here until "
        "Keyser and de Houtman logged these stars in the 1590s and Bayer "
        "printed them in 1603."),

    "Piscis Austrinus": (
        "one bright star, and almost nothing else",
        "[[Fomalhaut]] sits alone in a wide empty stretch of autumn sky, which "
        "is why it gets called the loneliest star, and the rest of the "
        "southern fish is faint. The name means the mouth of the fish, which "
        "is where it sits in the figure. Fomalhaut has a ring of dust around "
        "it and what was announced in 2008 as one of the first planets ever "
        "photographed, later re-read as an expanding cloud of debris from a "
        "collision."),

    "Serpens": (
        "the only constellation in two pieces",
        "Serpens is a snake cut in half by [[Ophiuchus]], who is holding it: "
        "the head is west of him and the tail east, and the two halves are "
        "counted as one constellation with a gap in the middle. Nothing else "
        "in the sky is arranged that way. The [[Eagle Nebula]] is in the tail, "
        "which is where the Pillars of Creation photograph was taken."),

    "Triangulum Australe": (
        "three stars, and a plainer name than most",
        "A small, neat triangle of second and third magnitude stars below "
        "[[The Pointers]], and easier to pick out than the northern "
        "Triangulum it is named after. It was drawn from the observations "
        "Keyser and de Houtman brought home from the Dutch voyage to the "
        "East Indies in the 1590s, the same batch of measurements that "
        "produced [[Grus]], [[Pavo]] and [[Phoenix]]. "
        "[[NGC6025|NGC 6025]], an open cluster, sits at the northern "
        "corner."),
}
