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
        "Mercury never strays more than 28 degrees from the Sun, which means "
        "it is only ever visible in twilight, low down, for a few weeks at a "
        "time. Copernicus is said to have died without ever seeing it. It has "
        "no atmosphere to speak of and a day two-thirds as long as its year."),

    "Venus": (
        "the brightest thing in the sky after the Sun and Moon",
        "Venus is bright enough to cast a shadow on a dark night and is "
        "routinely reported as an aircraft or a UFO. It shows phases like the "
        "Moon, which is what Galileo saw in 1610 and what settled the "
        "argument about whether everything orbits the Earth. Under the cloud "
        "it is 460 degrees and dry."),

    "Mars": (
        "the red planet, and the only one whose surface we can see",
        "Mars is half Earth's width, cold, and rusty enough to look orange to "
        "the naked eye. Every 26 months Earth catches up with it and it comes "
        "close enough for a small telescope to show dark markings and a polar "
        "cap. In between it shrinks to a featureless dot."),

    "Jupiter": (
        "the largest planet, and the easiest thing to point a telescope at",
        "Jupiter is twice the mass of everything else orbiting the Sun put "
        "together. Its four big moons are visible in binoculars and shift "
        "position from one night to the next, which is what Galileo noticed "
        "in 1610 and why they carry his name. The Great Red Spot is a storm "
        "wider than Earth."),

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
        "Neptune was predicted from wobbles in the orbit of Uranus and found "
        "within a degree of where the arithmetic said it would be. It is never "
        "visible to the naked eye. Its winds are the fastest in the solar "
        "system, over 2,000 kilometres an hour, on a world that receives one "
        "nine-hundredth of our sunlight."),

    # ---------------------------------------------------------------- stars
    "Sirius": (
        "the brightest star in the night sky",
        "Sirius is bright mostly because it is close: at 8.6 light years it is "
        "one of the nearest stars, and only twice the Sun's width. Low in the "
        "sky it flashes red and green as the atmosphere splits its light, "
        "which gets it reported as something else more often than any other "
        "star. It has a white dwarf companion the size of Earth."),

    "Betelgeuse": (
        "a red supergiant near the end of its life",
        "Betelgeuse is so large that, if it replaced the Sun, its surface would reach past the orbit of Mars. It will explode as a supernova at some point in the next hundred thousand years, and when it does it will be bright enough to read by. It is also the most famous typo in the sky. The initial \"ya\" was read as \"ba\" by medieval monks who could not read Arabic properly (the two letters look alike), giving Bat al-Jawza', which means nothing in any language, and then Bedalgeuze in the Alfonsine Tables of about 1250."),

    "Rigel": (
        "a blue supergiant, and the brightest star in Orion",
        "Rigel outshines Betelgeuse despite being the beta star of Orion, "
        "because it is genuinely luminous rather than merely close: around "
        "120,000 times the Sun's output, from 860 light years away. Blue-white "
        "stars burn like this for only a few million years."),

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
        "Arcturus is an old star that has already left the main sequence and swollen to 25 times the Sun's width. It is moving through the galaxy at a steep angle to everything around it, which suggests it arrived with a small galaxy the Milky Way absorbed long ago. Its name means the bear guard, and it follows the Great Bear around the pole. One of the very few star names that has come down unchanged from Greek without passing through Arabic on the way."),

    "Antares": (
        "the heart of the scorpion, and a rival to Mars",
        "The name means \"rival of Mars\", which is what it looks like: a red supergiant sitting on the ecliptic sky, close enough in colour to be mistaken for the planet. You can tell them apart only by watching which one is moving. It is roughly 700 times the Sun's width. Like Betelgeuse it will end as a supernova. Named for its colour."),

    "Altair": (
        "the flying eagle, and one half of a Chinese love story",
        "From an-nasr at-ta'ir \u0627\u0644\u0646\u0633\u0631 \u0627\u0644\u0637\u0627\u0626\u0631 "
        "the flying eagle, against [[Vega]]'s falling one. In Chinese the "
        "same star is the Cowherd, kept apart from the Weaver Girl by the "
        "Milky Way and allowed across it one night a year."),

    "Aldebaran": (
        "the eye of the bull, and not part of the cluster behind it",
        "Aldebaran appears to sit in the Hyades cluster but is less than "
        "half as far away, in front of it by chance. It is an orange "
        "giant 44 times the Sun's width. Pioneer 10 is heading "
        "roughly in its direction and will pass it in about two "
        "million years. Its name is really an instruction for finding "
        "it: It follows the Pleiades across the sky all night."),

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
        "Deneb is faint compared to Sirius, but vastly brighter in reality: somewhere around 200,000 times the Sun's output, seen from a distance of approximately 2,600 light years. If it sat where Sirius does it would cast shadows at noon. Its name (the tail) is the most productive root in the sky. The same word gives Denebola, the lion's tail, Deneb Algedi, the goat's tail, and Deneb Kaitos, the sea monster's tail."),

    # -------------------------------------------------------------- deep sky
    "Andromeda Galaxy": (
        "the furthest thing you can see without a telescope",
        "Andromeda is 2.5 million light years away. It spans six times the width of the full Moon, though only the bright core shows without optics. It is heading towards us and will merge with the Milky Way in about four billion years. Named for the constellation it sits in. Al-Sufi recorded it in 964 as a little cloud, which is the oldest surviving description of anything outside our own galaxy, written a thousand years before anyone knew what it was."),

    "Orion Nebula": (
        "a star nursery visible to the naked eye",
        "The middle \"star\" of Orion's sword is not a star: it is a cloud of "
        "gas 24 light years across with new stars forming inside it. Four of "
        "them, the Trapezium, are what light the whole thing up. Binoculars "
        "show the shape; a small telescope shows the wisps."),

    "Hercules Cluster": (
        "half a million stars in a ball",
        "It is a globular cluster, one of about 150 orbiting the Milky Way, "
        "and among the oldest things in it at roughly 11.6 billion years. In "
        "binoculars it is a fuzzy dot; in a telescope the edges break into "
        "individual stars. A radio message was aimed at it in 1974, which will "
        "arrive in 25,000 years."),

    "Pleiades": (
        "the seven sisters, though most people count six",
        "The Pleiades are young stars, around 100 million years old, still "
        "loosely travelling together. Six are easy to the naked eye and the "
        "seventh is a common eyesight test; binoculars show dozens. They span "
        "four Moon-widths, which is why a telescope is the wrong instrument "
        "for them."),

    "Whirlpool Galaxy": (
        "the first galaxy anyone recognised as a spiral",
        "Lord Rosse sketched its spiral arms in 1845 through a "
        "six-foot telescope, decades before anyone knew what a galaxy was. "
        "The smaller galaxy at the end of one arm is passing through, and the "
        "collision is what makes the arms so pronounced."),

    "Ring Nebula": (
        "a dying star seen down the barrel",
        "It is a shell of gas thrown off by a star like the Sun as it "
        "collapsed, lit from inside by the white dwarf left behind. It is "
        "small, about one arcminute, so it needs magnification rather than "
        "aperture. This is roughly what the Sun will do in five billion "
        "years."),

    "Dumbbell Nebula": (
        "the brightest planetary nebula in the sky",
        "It is the same kind of object as the Ring Nebula but eight times larger "
        "and much easier: binoculars from a dark site will show it. The name "
        "\"planetary nebula\" is a historical mistake: they looked like "
        "planetary discs in early telescopes and have nothing to do with "
        "planets."),

    "Lagoon Nebula": (
        "a naked-eye nebula from a dark sky",
        "It sits in the densest part of the Milky Way towards the galactic "
        "centre, and from somewhere properly dark it is visible without "
        "optics as a brighter patch in the band. The dark lane that gives it "
        "its name splits it in two."),

    "Sombrero Galaxy": (
        "a galaxy seen almost exactly edge-on",
        "It is tilted six degrees from edge-on, so its dust lane cuts across "
        "the bright bulge as a hard dark line. It has an unusually large "
        "population of globular clusters, nearly 2,000 of them, and a black "
        "hole a billion times the Sun's mass."),

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
        "The Geminids outperform the Perseids at up to 150 an hour, and the "
        "radiant is high in the middle of the night in December. They come "
        "from an asteroid rather than a comet, which is unusual, and the "
        "meteors are slow and often bright."),

    "Quadrantids": (
        "a sharp peak most people miss",
        "The Quadrantids can match the Geminids, but the peak lasts only a few "
        "hours instead of a day or two, so the date matters more than usual "
        "and it is easy to be on the wrong side of the planet for it. Named "
        "after a constellation that no longer exists."),

    "Lyrids": (
        "the oldest recorded shower",
        "Chinese records describe Lyrid meteors falling \"like rain\" in 687 "
        "BC, which makes this the longest continuously observed shower. Normal "
        "years give about 18 an hour, but it has produced sudden outbursts "
        "several times without warning."),

    # -------------------------------------------------------------- asterisms
    "Big Dipper": (
        "seven stars that point at the pole",
        "It is not a constellation, but a part of Ursa Major, and probably the most widely recognised shape in the northern sky. The two stars at the end of the bowl point at Polaris. The middle star of the handle, Mizar, has a companion visible to good eyesight, which was used as a vision test for centuries."),

    "Orion's Belt": (
        "three stars in a row, and the easiest signpost in the sky",
        "Alnitak, Alnilam and Mintaka are nearly evenly spaced and nearly "
        "equally bright, which is why no other pattern gets confused with "
        "them. Follow the line down and left to Sirius, up and right to "
        "Aldebaran. The sword hangs below the belt, with the Orion Nebula in "
        "the middle of it."),

    "Summer Triangle": (
        "three bright stars in three constellations",
        "Vega, Deneb and Altair are the first stars out on a summer evening "
        "and span most of the sky overhead. The Milky Way runs straight "
        "through the middle of the triangle, so from a dark site the shape "
        "frames the best part of the band."),

    "Southern Cross": (
        "the smallest constellation, and the southern signpost",
        "Crux has no pole star to point at, so the long axis of the cross is "
        "extended four and a half times to find where the south celestial pole "
        "is. It appears on five national flags. The Coalsack, a dark nebula, "
        "sits beside it as an obvious hole in the Milky Way."),
}
