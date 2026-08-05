"""Planet portraits, drawn as a lit sphere in coloured '#'.

Every other picture on this site is made of characters, so a photograph
would have been the one thing on the page that was not -- and it would have
arrived with a credit line, a licence file, a build script that hits the
network, and megabytes of binaries in a repo whose whole claim is that it
bundles no third-party assets (LICENSES.md has had two dependencies removed
for exactly that reason). Tracing a NASA image into ASCII would not have
helped: that makes it a derivative work and hands the licence question
straight back.

So this is computed, not drawn, which also means it is not a picture of a
planet in general but of that planet tonight. The crescent comes from the
real phase angle (objects.planet_facts' "illuminated"), so Venus is a thin
sliver near inferior conjunction and a small full disc on the far side of
the Sun, and Saturn's rings open and close with the tilt we actually see.

Shading is Lambert: brightness is the surface normal dotted with the
direction of the Sun. That gets the terminator for free and, more
importantly, gets it *curved* -- a crescent's inner edge is an ellipse, not
a straight line, and a hard left/right split reads as a pac-man rather than
a sphere. It also darkens the limb of a full planet, so an outer planet at
99.9% lit still looks round instead of like a flat coin.

Colour is the site's own 256-colour ANSI, so the same string works in a
terminal, in the browser through ansi_to_html, and in the PNG export.
"""
import math

# The canvas. Wide enough to read, narrow enough to sit in the facts column
# without the wrapping that column does for text (art cannot reflow).
#
# Fixed rows, not fixed radius: a wide-open ring system needs more vertical
# room than a bare globe, so the globe is scaled to fit the box rather than
# the box growing to fit the globe. That is what keeps Saturn, Uranus and
# Neptune the same height as the rest instead of sitting shorter.
# A ringed planet spends most of its width on the rings, so at the old 39x15
# Saturn's globe came out a third smaller than Jupiter's next to it. Widening
# the canvas buys the globe back without touching the ring geometry, which is
# measured rather than chosen.
COLS = 45
ROWS = 17

# A character cell is taller than it is wide, so x has to be stretched or
# every planet comes out an egg standing on end. This is the ratio the art
# is drawn for, and OBJECT_CSS pins .obj-art's line-height to match it --
# monospace glyphs are ~0.6em wide, so line-height 1.2em gives exactly 2.0.
# The two numbers have to move together; a stylesheet that sets its own
# line-height here would squash every planet back into an ellipse.
CELL = 2.0


class Palette:
    """Three tones, brightest to darkest, plus optional ring colours.

    Two of these do the real work (the lit face and the shadowed side, which
    is what makes it read as a sphere); the third is a highlight where the
    Sun is nearly overhead, and it is what stops a full disc looking flat.
    """

    def __init__(self, hi, base, shadow, ring=None, ring_dim=None, bands=None,
                 spot=None, cap=None):
        self.hi, self.base, self.shadow = hi, base, shadow
        self.ring, self.ring_dim = ring, ring_dim
        self.bands = bands          # stripes by latitude, north pole first
        self.spot = spot            # (colour, lat, lon-ish, rlat, rlon)
        self.cap = cap              # colour poleward of CAP_LAT


# 256-colour indices. Picked so each planet is recognisable at a glance from
# its dominant tone alone: Mars red, Venus cream, Uranus cyan, Neptune blue.
# Bands are (lit, shadowed) pairs, one per stripe from north pole to south.
# Two colours per band rather than one band colour and one shared shadow:
# a single dark tone across the terminator flattens a banded planet into a
# solid black bite, and the belts are the thing worth keeping. Darkening each
# stripe on its own keeps Jupiter striped all the way round.
PALETTES = {
    # No cap on the bodies with nothing else drawn on them. On a banded
    # planet the pole tip is one more feature among belts that already show
    # which way the axis leans; on a plain disc it is a lone white blob with
    # no context, and it reads as a smudge rather than as a pole. Mars's
    # caps really are white, but at 34 columns that is not the impression a
    # single bright cell gives.
    "Sun":     Palette(227, 220, 214),
    "Mercury": Palette(251, 245, 238),
    "Venus":   Palette(230, 223, 137),
    "Mars":    Palette(209, 166, 52),
    "Jupiter": Palette(223, 180, 94,
                       bands=((101, 58), (180, 94), (223, 137), (173, 95),
                              (216, 130), (173, 95), (223, 137), (180, 94),
                              (101, 58)),
                       spot=(160, -22.0, 0.34, 11.0, 0.30), cap=101),
    "Saturn":  Palette(223, 179, 94, ring=187, ring_dim=137,
                       bands=((101, 58), (179, 94), (223, 137), (186, 101),
                              (223, 137), (179, 94), (101, 58)), cap=66),
    "Uranus":  Palette(159, 116, 66, ring=109, ring_dim=66,
                       bands=((116, 66), (122, 72), (159, 109), (122, 72),
                              (116, 66)), cap=195),
    "Neptune": Palette(111, 32, 17, ring=61, ring_dim=24,
                       bands=((25, 17), (32, 18), (39, 24), (32, 18),
                              (25, 17)), cap=117),
    "Moon":    Palette(255, 250, 240),
}

# Poleward of this the cap colour takes over. It is what makes the axis
# visible on a planet with no other markings: the bright patch sits wherever
# the pole actually points, so Uranus's lands near the middle of the disc
# (we are looking down its pole) while Mars's sit at opposite limbs.
CAP_LAT = 72.0

# Rings, in planet radii. Saturn's are the ones anyone has seen; Uranus and
# Neptune really do have them, far fainter and much narrower, so they are
# drawn dimmer and tighter rather than pretending they look like Saturn's.
RINGS = {
    "Saturn":  (1.20, 2.00),
    "Uranus":  (1.55, 1.90),
    "Neptune": (1.50, 1.80),
}

def _extent(name, s, theta):
    """Half-width and half-height of the whole drawing, in planet radii.

    A ring is a circle seen at an angle, so on screen it is an ellipse with
    semi-axes (outer, outer*s) turned by theta. Its bounding box is what
    decides how big the globe can be, and for Uranus -- rings nearly face-on
    and steeply turned -- that box is almost square where Saturn's is a wide
    slot. Sizing off it is why all three end up the same height.
    """
    if name not in RINGS:
        return 1.0, 1.0
    a = RINGS[name][1]
    b = a * s
    ct, st = abs(math.cos(theta)), abs(math.sin(theta))
    return (math.hypot(a * ct, b * st), math.hypot(a * st, b * ct))


def _lambert(x, y, light):
    """Brightness 0..1 of the point (x, y) on a unit sphere, or None if the
    point is off the disc. light is the unit vector towards the Sun."""
    r2 = x * x + y * y
    if r2 > 1.0:
        return None
    z = math.sqrt(max(0.0, 1.0 - r2))
    b = x * light[0] + y * light[1] + z * light[2]
    return max(0.0, b)


def _latitude(x, y, z, pole):
    """Planetographic latitude of a point on the disc, in degrees.

    The whole tilt story is this one dot product. The pole is a real
    direction in space projected onto the screen, so the parallels of
    latitude come out tipped by the pole's position angle and foreshortened
    by how far it leans towards us -- straight belts on Jupiter, bullseyes
    on Uranus -- without any of that being drawn by hand.
    """
    d = x * pole[0] + y * pole[1] + z * pole[2]
    return math.degrees(math.asin(max(-1.0, min(1.0, d))))


def _tone(pal, bright, lat):
    """A brightness and a latitude to one of the palette's colours."""
    if pal.cap and abs(lat) >= CAP_LAT and bright > 0.12:
        return pal.cap
    if pal.bands:
        # Stripes by real latitude, north first. Colour comes from where the
        # point is on the planet; brightness only picks which of that
        # stripe's two tones to use, so a banded planet stays banded across
        # the terminator instead of ending in one flat dark bite.
        i = int((90.0 - lat) / 180.0 * len(pal.bands))
        lit, dark = pal.bands[min(max(i, 0), len(pal.bands) - 1)]
        return lit if bright >= 0.34 else dark
    if bright < 0.30:
        return pal.shadow
    if bright > 0.86:
        return pal.hi
    return pal.base


def _ring_hit(x, y, name, s, theta):
    """Is this cell on the ring, and does the ring pass in front here?

    The ring is a circle in the planet's equatorial plane, so on screen it is
    an ellipse squashed by s = |sin(opening)| and turned by theta. Rotating
    the point into the ring's own frame is what lets Saturn lie flat and
    Uranus stand up, from the same code and the same real pole directions.

    On the near half of the ellipse the ring passes in front of the globe;
    on the far half the globe hides it. That crossing is the single detail
    that makes a ringed planet read as a ball with a ring around it rather
    than a disc with a line drawn through it.
    """
    if name not in RINGS:
        return None
    inner, outer = RINGS[name]
    u = x * math.cos(theta) + y * math.sin(theta)
    v = -x * math.sin(theta) + y * math.cos(theta)
    d = math.hypot(u, v / max(s, 0.06))
    if not (inner <= d <= outer):
        return None
    return "front" if v > 0 else "back"


# The Moon is drawn at its real phase, because that is the one body whose
# phase anybody watches and the page already reports it. Everything else is
# drawn at a fixed one: from Earth the outer planets are never more than a
# few percent off full, so a truthful Jupiter is a flat coin, and Venus's
# real crescent swings from sliver to disc over months in a way that makes
# the page look broken rather than informative. This is the light source in
# a portrait, not a measurement.
STYLE_ILLUMINATED = 0.76


def planet_art(name, illuminated=1.0, pole_b=26.0, pole_pa=90.0,
               lit_from_left=False):
    """One planet, as a list of ANSI-coloured lines.

    illuminated is the fraction of the disc lit (0..1). lit_from_left says
    which limb the Sun is on -- a waxing and a waning Moon show mirrored
    crescents, and getting that backwards is the kind of error someone who
    actually looks up would spot immediately.

    pole_b and pole_pa come from objects.pole_geometry: which parallel faces
    us, and where the north pole points on the sky. They tip the whole
    planet -- belts, poles and rings together, because the rings sit in the
    equatorial plane and all three are the same axis seen from here.
    """
    pal = PALETTES.get(name)
    if pal is None:
        return []
    k = min(1.0, max(0.0, illuminated))
    # Phase angle back out of the illuminated fraction: k = (1 + cos a) / 2.
    a = math.acos(min(1.0, max(-1.0, 2.0 * k - 1.0)))
    lx = -math.sin(a) if lit_from_left else math.sin(a)
    light = (lx, 0.0, math.cos(a))

    s = abs(math.sin(math.radians(pole_b)))
    # The ring's long axis lies 90 degrees from the pole, and the pole's
    # angle is measured from north while the screen measures from horizontal.
    theta = math.radians(90.0 - ((pole_pa + 90.0) % 180.0))
    # The pole as a direction in the drawing: screen x runs right, y runs
    # down, z comes towards the reader. North on the sky is up, hence -cos.
    pb, ppa = math.radians(pole_b), math.radians(pole_pa)
    pole = (math.cos(pb) * math.sin(ppa),
            -math.cos(pb) * math.cos(ppa),
            math.sin(pb))
    # Where each pole lands on the disc, marked explicitly rather than left
    # to the latitude test above.
    #
    # With the pole near the limb -- which is most planets, since we orbit
    # in nearly the same plane -- the cap is a sliver right at the edge, and
    # the one cell it would occupy sits a rounding error outside the circle
    # and never gets drawn. The result was a lone '#' dead centre at the top
    # of every planet, which is exactly what a planet with no tilt looks
    # like. Pinning the tips at the projected pole puts them where the axis
    # actually points: three cells off centre for the Sun, most of a radius
    # for Mars.
    tips = []
    if pal.cap:
        for sign in (1.0, -1.0):
            tx = sign * pole[0] * 0.93
            ty = sign * pole[1] * 0.93
            tips.append((tx, ty))

    half_rows = ROWS // 2
    ex, ey = _extent(name, s, theta)
    # Whichever edge it hits first decides the scale, so nothing is clipped
    # and every planet fills the same box.
    R = min((COLS / 2.0 - 0.5) / ex, (half_rows * CELL) / ey)

    lines = []
    for row in range(-half_rows, half_rows + 1):
        y = row * CELL / R
        out, run_colour, run = [], None, []

        def flush():
            if run:
                out.append(f"\033[38;5;{run_colour}m{''.join(run)}\033[0m")
                run.clear()

        for col in range(-(COLS // 2), COLS // 2 + 1):
            x = col / R
            ring = _ring_hit(x, y, name, s, theta)
            bright = _lambert(x, y, light)
            colour, ch = None, " "
            if ring == "front" or (ring and bright is None):
                # A ring is lit by the same Sun, so the shadowed side of the
                # rings dims with the planet rather than staying bright.
                side = 1.0 if x * light[0] >= 0 else 0.45
                colour = pal.ring if side > 0.5 else pal.ring_dim
                ch = "="
            elif bright is not None:
                z = math.sqrt(max(0.0, 1.0 - x * x - y * y))
                lat = _latitude(x, y, z, pole)
                colour, ch = _tone(pal, bright, lat), "#"
                # The pole tips, drawn a little wider than one cell so they
                # read at this size. Only on the lit side: a pole in shadow
                # is not visible from here and should not glow.
                for tx, ty in tips:
                    if bright > 0.12 and abs(x - tx) < 1.6 / R \
                            and abs(y - ty) < 1.1 * CELL / R:
                        colour = pal.cap
                if pal.spot:
                    # Sits at a latitude on the planet, not at a place on
                    # the picture, so it tips with everything else. The
                    # second coordinate is how far round the visible face it
                    # sits, which is as much longitude as a drawing needs.
                    sc, slat, su, dlat, du = pal.spot
                    across = x * math.cos(theta) + y * math.sin(theta)
                    dy_ = (lat - slat) / dlat
                    dx_ = (across - su) / du
                    if dx_ * dx_ + dy_ * dy_ <= 1.0 and bright > 0.10:
                        colour = sc
            if colour is None:
                flush()
                run_colour = None
                out.append(" ")
                continue
            if colour != run_colour:
                flush()
                run_colour = colour
            run.append(ch)
        flush()
        # Not rstripped: every line keeps its full COLS width, so the box is
        # the same size for every body and a small disc stays centred in it
        # rather than sliding left as its own content shrinks. Blank rows
        # are kept for the same reason vertically -- the fact table below
        # starts on the same line whichever object you are looking at.
        lines.append("".join(out))
    return lines


# --- stars --------------------------------------------------------------------
# The same lit sphere as the Sun, because that is what a star is, with the two
# things that actually differ between them: colour and size. Both are real
# properties the page already reports, so a red supergiant is drawn big and
# red and a white dwarf small and white, and Sirius sits between them.
#
# Colour by Harvard class, matching _CLASS_COLOUR's words in objects.py so the
# picture agrees with the sentence next to it.
STAR_COLOURS = {
    "O": (33, 27, 18),        # blue
    "B": (153, 111, 67),      # blue-white
    "A": (255, 254, 250),     # white
    "F": (230, 229, 187),     # yellow-white
    "G": (227, 220, 214),     # yellow, the Sun's own
    "K": (215, 208, 130),     # orange
    "M": (203, 196, 88),      # red
    "C": (167, 160, 52),      # deep red
    "S": (167, 160, 52),
    "R": (167, 160, 52),
    "N": (167, 160, 52),
    "W": (45, 39, 24),        # blue
}

# How much of the canvas a star fills, by luminosity class. A supergiant is
# hundreds of times the width of a main-sequence star, which no drawing can
# show honestly; these are ordered, not to scale, so the sequence reads
# correctly even though the ratios do not.
STAR_SIZES = {
    "supergiant": 1.00, "bright giant": 0.88, "giant": 0.76,
    "subgiant": 0.62, "main-sequence star": 0.52,
    "subdwarf": 0.42, "white dwarf": 0.30,
}
DEFAULT_STAR_SIZE = 0.52


def star_art(harvard="G", luminosity="main-sequence star"):
    """A star, coloured by spectral class and sized by luminosity class.

    Lit from straight ahead rather than from the side: a star is its own
    light source, so a crescent would be wrong in a way the planets' is not.
    """
    hi, base, shadow = STAR_COLOURS.get((harvard or "G")[:1].upper(),
                                        STAR_COLOURS["G"])
    pal = Palette(hi, base, shadow)
    scale = STAR_SIZES.get(luminosity, DEFAULT_STAR_SIZE)

    half_rows = ROWS // 2
    R = min((COLS / 2.0 - 0.5), half_rows * CELL) * scale
    lines = []
    for row in range(-half_rows, half_rows + 1):
        y = row * CELL / R if R else 99.0
        out, run_colour, run = [], None, []

        def flush():
            if run:
                out.append(f"\033[38;5;{run_colour}m{''.join(run)}\033[0m")
                run.clear()

        for col in range(-(COLS // 2), COLS // 2 + 1):
            x = col / R if R else 99.0
            r2 = x * x + y * y
            if r2 > 1.0:
                flush()
                run_colour = None
                out.append(" ")
                continue
            # Limb darkening only, which is what gives a self-luminous disc
            # its roundness. The Sun really does dim towards its edge.
            edge = 1.0 - r2
            colour = hi if edge > 0.55 else (base if edge > 0.12 else shadow)
            if colour != run_colour:
                flush()
                run_colour = colour
            run.append("#")
        flush()
        lines.append("".join(out))
    return lines


def star_art_for(spectral_type, description=None):
    """A star from its catalogue spectral type, e.g. "M1-2Ia-Iab".

    The luminosity is read from the words objects.describe_spectrum already
    produced rather than parsed again here, so the drawing and the sentence
    beside it can never disagree about whether something is a giant.
    """
    if not spectral_type:
        return []
    harvard = spectral_type[:1].upper()
    # Some entries are prefixed ("gK5", "sgB2"); the class letter is the
    # first character that is actually one.
    for ch in spectral_type:
        if ch.upper() in STAR_COLOURS:
            harvard = ch.upper()
            break
    lum = None
    if description:
        # Longest first: "giant" is a substring of both "supergiant" and
        # "bright giant", and testing it first would call every supergiant
        # an ordinary one.
        for word in sorted(STAR_SIZES, key=len, reverse=True):
            if word in description:
                lum = word
                break
    return star_art(harvard, lum or "main-sequence star")


def art_for(facts):
    """The drawing for an object page, as a list of ANSI lines, or [].

    Driven off the facts the page already computed rather than off the name,
    so the picture is of this object at this moment: the Moon at tonight's
    phase, Saturn with its rings as open as they currently are.
    """
    name, kind = facts.get("object"), facts.get("kind")
    if kind == "star":
        st = facts.get("star") or {}
        return star_art_for(st.get("spectral_type"), st.get("description"))
    if name not in PALETTES:
        return []
    pole_b, pole_pa = facts.get("pole_b", 0.0), facts.get("pole_pa", 90.0)
    if kind == "moon":
        # The one body drawn at its real phase, because it is the one whose
        # phase anybody watches and the page already reports it.
        return planet_art(name, illuminated=facts.get("illuminated", 1.0),
                          pole_b=pole_b, pole_pa=pole_pa,
                          lit_from_left=bool(facts.get("waning")))
    return planet_art(name, illuminated=STYLE_ILLUMINATED,
                      pole_b=pole_b, pole_pa=pole_pa)


def has_art(name):
    return name in PALETTES
