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
               lit_from_left=False, scale=1.0):
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
    #
    # scale shrinks the planet inside that box without changing the box. An
    # object page wants the disc edge to edge, because the drawing is the
    # subject there. In the day panel's deck it sits next to a meteor shower
    # that leaves a row of margin all round, and a planet touching all four
    # sides read as a different size of picture rather than as a bigger
    # object -- so the deck asks for a little less.
    R = min((COLS / 2.0 - 0.5) / ex, (half_rows * CELL) / ey) * scale

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
    # The one drawing here that is not of a body: an asterism has no disc, so
    # what gets drawn is its shape. Same slot on the page as the planets, for
    # the same reason -- the picture is what the reader is going outside to
    # find, and the chart below shows where it is tonight.
    if kind == "asterism":
        return asterism_art(name)
    # Two more that are not bodies. A radiant is a point in empty sky, so what
    # gets drawn is the shower coming out of it; the Galaxy has no disc to
    # light either, and the only view of it worth having is from outside.
    if kind == "radiant":
        return shower_art(name)
    if kind == "milkyway":
        return milkyway_art()
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


# ------------------------------------------------------------- asterisms
# The shapes people actually point at. An asterism has no disc to light, so
# unlike the planets above there is nothing to shade -- what there is, is a
# shape, and the shape is the whole reason the thing has a name. The Plough
# is seven stars and six lines; drawn on its own it is recognisable, and on
# the horizon chart it is buried in two hundred other stars at whatever angle
# tonight happens to hold it.
#
# Same source as the chart's own figures: asterisms.json for the chains,
# stars.json for where the stars are. Nothing is hand-drawn, so a correction
# to either file corrects the portrait too.

# Its own box, wider and shorter than the planets'. A planet is a disc and
# wants a square-ish frame; an asterism is usually a long shape (the Plough
# is 25 deg by 10) and reads better given room to lie down in.
AST_COLS = 52
AST_ROWS = 15

# Sub-pixels per cell, as the braille block lays them out: 2 across, 4 down.
# The lines are drawn into this finer grid and only become characters at the
# end, which is what stops a diagonal turning into a staircase of hyphens.
AST_SUBX, AST_SUBY = 2, 4

# Two, because one of these really is two stars: The Pointers is Rigil
# Kentaurus and Hadar and the line between them, which is the whole content
# of the name -- it points at the Southern Cross. Drawn, it is a pair and a
# bar, which is exactly what you are being told to look for.
#
# A single star has nothing to connect and no shape to show, so it is the one
# case that returns nothing and lets the page carry on without a picture.
AST_MIN_STARS = 2


def _emit(grid, tint):
    """A character grid and its colours, as ANSI lines with the blank rows off.

    Trimmed on the grid rather than on the finished strings: once the ANSI is
    in, "is this row blank" needs a regex, and art.py cannot import the one in
    api.py -- api imports art, not the other way round.

    A colour is written only where it changes, which is what keeps a drawing
    this dense down to a sane number of bytes.
    """
    import sky
    rows = [r for r, row in enumerate(grid) if any(ch != " " for ch in row)]
    if not rows:
        return []
    out = []
    for r in range(rows[0], rows[-1] + 1):
        line, last = [], None
        for c in range(len(grid[r])):
            col = tint[r][c]
            if col != last:
                line.append(sky.C.OFF if col is None else col)
                last = col
            line.append(grid[r][c])
        out.append("".join(line).rstrip() + sky.C.OFF)
    return out


def _seeded(seed):
    """A tiny deterministic generator, so a drawing is the same every render.

    Not `random`: this has to give the same picture in the terminal, in the
    browser and in the PNG export, and on a process that has seeded the global
    generator for something else entirely. Seeded off the subject's own name,
    so two showers scatter differently and one shower never does.
    """
    x = 0
    for ch in seed:
        x = (x * 131 + ord(ch)) & 0xFFFFFFFF

    def nxt():
        nonlocal x
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        return x / 0x7FFFFFFF
    return nxt


def _blit(dots, cols, rows, rank):
    """Sub-pixel dots to a braille character grid.

    `dots` is {(x, y): colour}. Where several dots land in one cell their bits
    are merged and the highest-ranked colour wins it, which is what stops a
    trail crossing another trail from taking the brighter one's colour.
    """
    import sky
    grid = [[" "] * cols for _ in range(rows)]
    tint = [[None] * cols for _ in range(rows)]
    cells = {}
    for (x, y), col in dots.items():
        key = (x // SUBX, y // SUBY)
        bits, old = cells.get(key, (0, None))
        cells[key] = (bits | sky.BRAILLE_DOTS[(x % SUBX, y % SUBY)],
                      col if rank(col) >= rank(old) else old)
    for (c, r), (bits, col) in cells.items():
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = chr(sky.BRAILLE_BASE + bits)
            tint[r][c] = col
    return grid, tint


# Sub-pixels per character cell, as the braille block lays them out. Same
# numbers AST_SUBX/AST_SUBY carry for the asterisms; named once more here
# because the two drawings below are not asterisms and reading
# AST_SUBX in a meteor shower would be a lie about where the number comes from.
SUBX, SUBY = 2, 4


def _ast_entry(name):
    """The asterism's record and the star table, or (None, None)."""
    import sky
    key = (name or "").strip().lower()
    for con in sky._load("asterisms.json"):
        if con["name"].lower() == key:
            return con, {t["hr"]: t for t in sky._load("stars.json")}
    return None, None


def _ast_project(stars):
    """Gnomonic projection about the shape's own centroid, in degrees.

    Gnomonic because it is the one projection that maps a great circle to a
    straight line, and the lines between these stars *are* great-circle
    segments -- so a straight line drawn on this plane is the line you would
    see, not an approximation of it. Over the 10-40 deg an asterism spans the
    scale distortion is a few percent at the edges, which is invisible at a
    resolution of 104 by 60 dots.

    North is up and east is left, which is how a star atlas is drawn and how
    sky.py's own zenith inset is drawn: you are looking up at this, not down
    at a map.
    """
    D = math.pi / 180.0
    vx = vy = vz = 0.0
    for st in stars:
        ra, dec = st["ra"] * 15 * D, st["de"] * D
        vx += math.cos(dec) * math.cos(ra)
        vy += math.cos(dec) * math.sin(ra)
        vz += math.sin(dec)
    ra0 = math.atan2(vy, vx)
    dec0 = math.atan2(vz, math.hypot(vx, vy))
    sin0, cos0 = math.sin(dec0), math.cos(dec0)

    out = {}
    for st in stars:
        ra, dec = st["ra"] * 15 * D, st["de"] * D
        dra = ra - ra0
        cosc = (sin0 * math.sin(dec)
                + cos0 * math.cos(dec) * math.cos(dra))
        if cosc <= 0.01:            # more than ~89 deg away; nothing real is
            continue                # but the divide below would explode
        x = math.cos(dec) * math.sin(dra) / cosc
        y = (cos0 * math.sin(dec)
             - sin0 * math.cos(dec) * math.cos(dra)) / cosc
        out[st["hr"]] = (-math.degrees(x), math.degrees(y))   # east to the left
    return out


def _ast_line(dots, a, b, w, h):
    """One segment into the sub-pixel bitmap, by even sampling.

    Sampled rather than Bresenham'd: the endpoints are floats and the step is
    already sub-pixel, so walking the longer axis in half-dot increments lays
    down a continuous run without any of the integer-rounding bookkeeping.
    """
    (x0, y0), (x1, y1) = a, b
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    for i in range(steps + 1):
        t = i / steps
        x, y = int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))
        if 0 <= x < w and 0 <= y < h:
            dots.add((x, y))


def asterism_art(name):
    """The asterism's own shape, as a list of ANSI lines, or [].

    Lines in braille and stars as the same glyph ladder the charts use, so
    the portrait and the figure picked out on the horizon chart below it are
    visibly the same object -- which is the point, since the reader has to
    find one from the other.
    """
    import sky
    con, table = _ast_entry(name)
    if not con:
        return []
    chains = [[h for h in poly if h in table] for poly in con["lines"]]
    stars = {h: table[h] for poly in chains for h in poly}
    if len(stars) < AST_MIN_STARS:
        return []

    pos = _ast_project(list(stars.values()))
    if len(pos) < AST_MIN_STARS:
        return []
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)

    # One scale for both axes, and no CELL correction -- which is the
    # opposite of what the planet art above needs, and worth being explicit
    # about because getting it backwards squashes every shape by exactly two.
    #
    # A character cell is 1 unit wide and CELL units tall. Braille puts 2 dots
    # across that width and 4 down that height, so a dot is 0.5 units either
    # way: the sub-pixel grid is already square, and the aspect correction the
    # planets need has been done by the glyph. Divide by CELL here as well and
    # Cassiopeia's W comes out as a shallow V.
    #
    # A margin of one cell all round: a star in the outermost column reads as
    # clipped even when the shape is complete.
    inner_w = (AST_COLS - 2) * AST_SUBX
    inner_h = (AST_ROWS - 2) * AST_SUBY
    scale = min(inner_w / span_x if span_x > 1e-9 else 1e9,
                inner_h / span_y if span_y > 1e-9 else 1e9)
    W, H = AST_COLS * AST_SUBX, AST_ROWS * AST_SUBY
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    def place(hr):
        x, y = pos[hr]
        return (W / 2 + (x - cx) * scale,
                H / 2 - (y - cy) * scale)             # screen y grows downward

    dots = set()
    for poly in chains:
        pts = [place(h) for h in poly if h in pos]
        for a, b in zip(pts, pts[1:]):
            _ast_line(dots, a, b, W, H)

    # Braille first, stars over it. Same order the horizon chart settled on
    # and for the same reason: a line drawn after a star swallows the star,
    # and the stars are the thing being named.
    grid = [[" "] * AST_COLS for _ in range(AST_ROWS)]
    tint = [[None] * AST_COLS for _ in range(AST_ROWS)]
    cells = {}
    for x, y in dots:
        cells.setdefault((x // AST_SUBX, y // AST_SUBY), 0)
        cells[(x // AST_SUBX, y // AST_SUBY)] |= sky.BRAILLE_DOTS[
            (x % AST_SUBX, y % AST_SUBY)]
    for (c, r), bits in cells.items():
        if 0 <= r < AST_ROWS and 0 <= c < AST_COLS:
            grid[r][c] = chr(sky.BRAILLE_BASE + bits)
            tint[r][c] = sky.C.DIM

    # Brightest last, so that where two stars share a cell the one that
    # survives is the one a reader is more likely to be looking for.
    for hr, st in sorted(stars.items(), key=lambda kv: -kv[1]["m"]):
        if hr not in pos:
            continue
        # place() answers in sub-pixels, like everything above it; a star is
        # a whole character and needs the cell that contains that dot.
        x, y = place(hr)
        c, r = int(x // AST_SUBX), int(y // AST_SUBY)
        if 0 <= r < AST_ROWS and 0 <= c < AST_COLS:
            grid[r][c] = sky.glyph_for(st["m"])
            tint[r][c] = sky.star_colour(st.get("ci"))

    return _emit(grid, tint)


# ------------------------------------------------------------ meteor showers
# A radiant is a point in empty sky. There is nothing there to draw -- which
# is exactly the problem, because "the Perseids" is the one event of the year
# a lot of people do go outside for, and its page had no picture at all.
#
# So what gets drawn is the shower: the real stars around the radiant, out of
# the same catalogue the charts use, with meteors coming out of the point.
# That answers the question somebody opening the page actually has, which is
# where to look, and it is the same materials as everything else here.

SHOWER_COLS = 45
SHOWER_ROWS = 15

# How wide a patch of sky, in degrees across. Wide enough that the radiant
# sits among stars a reader could recognise rather than in a random scatter.
SHOWER_SPAN = 46.0

# Faintest star drawn, opened up a step at a time when the patch comes out
# sparse: some radiants genuinely sit in empty sky, and a portrait with four
# stars in it says nothing.
SHOWER_MAGS = (4.2, 4.8, 5.4)
SHOWER_MIN_STARS = 14

# The rate that earns a full box of streaks. The Geminids' 150 an hour is the
# busiest thing in showers.json, so it is the natural top of the scale.
ZHR_FULL = 150
STREAKS_MIN, STREAKS_MAX = 3, 15

METEOR_HEAD = "\033[38;5;255m"    # the meteor itself
METEOR_TRAIL = "\033[38;5;110m"   # the trail behind it
METEOR_FADE = "\033[38;5;61m"     # the last of the trail, going out
RADIANT_C = "\033[38;5;213m"      # orchid: what the events strip already uses

_METEOR_RANK = {None: -1, METEOR_FADE: 0, METEOR_TRAIL: 1, METEOR_HEAD: 2}


def _shower_entry(name):
    """The shower's record, or None. Takes "Perseids", "Perseid", or the
    canonical "Perseids radiant" the object pages resolve to."""
    import sky
    key = (name or "").strip().lower()
    if key.endswith(" radiant"):
        key = key[:-8]
    key = key.rstrip("s")
    for s in sky._load("showers.json"):
        if s["name"].lower().rstrip("s") == key:
            return s
    return None


def _shower_field(sh, limit):
    """Bright stars near the radiant, gnomonic about it, in degrees.

    Same projection as the asterism portraits above, for the same reason: a
    straight line on this plane is a straight line in the sky.
    """
    import sky
    D = math.pi / 180.0
    ra0, dec0 = sh["ra"] * 15 * D, sh["dec"] * D
    sin0, cos0 = math.sin(dec0), math.cos(dec0)
    out = []
    for st in sky._load("stars.json"):
        if st["m"] > limit:
            continue
        ra, dec = st["ra"] * 15 * D, st["de"] * D
        dra = ra - ra0
        cosc = sin0 * math.sin(dec) + cos0 * math.cos(dec) * math.cos(dra)
        if cosc <= 0.2:
            continue
        x = math.degrees(math.cos(dec) * math.sin(dra) / cosc)
        y = math.degrees((cos0 * math.sin(dec)
                          - sin0 * math.cos(dec) * math.cos(dra)) / cosc)
        out.append((-x, y, st))               # east to the left, as always
    return out


def _streak(dots, x0, y0, x1, y1, w, h):
    """One meteor into the sub-pixel bitmap, bright at the head, fading back."""
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 3) + 1
    for i in range(n + 1):
        t = i / n
        x, y = int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))
        if 0 <= x < w and 0 <= y < h:
            col = (METEOR_HEAD if t > 0.78 else
                   METEOR_TRAIL if t > 0.35 else METEOR_FADE)
            if _METEOR_RANK[col] >= _METEOR_RANK.get(dots.get((x, y))):
                dots[(x, y)] = col


def shower_art(name, cols=SHOWER_COLS, rows=SHOWER_ROWS, span=SHOWER_SPAN):
    """A meteor shower's radiant and the sky around it, as ANSI lines, or []."""
    import sky
    sh = _shower_entry(name)
    if not sh:
        return []
    W, H = cols * SUBX, rows * SUBY
    # One scale on both axes and no aspect correction: braille dots are square
    # (see asterism_art above), so a round patch of sky comes out round.
    scale = min((cols - 2) * SUBX / span, (rows - 2) * SUBY / (span * H / W))
    half_x, half_y = (W / 2) / scale, (H / 2) / scale

    stars = []
    for limit in SHOWER_MAGS:
        stars = [(x, y, st) for x, y, st in _shower_field(sh, limit)
                 if abs(x) <= half_x and abs(y) <= half_y]
        if len(stars) >= SHOWER_MIN_STARS:
            break

    rnd = _seeded(sh["name"])
    rx, ry = W / 2, H / 2
    dots = {}
    # How many streaks, from the shower's own rate. Not the rate itself: the
    # published numbers run 5 to 150 an hour, and 150 streaks in a 45-column
    # box is a smear. Compressed, so the ordering survives and both ends stay
    # drawable -- the Draconids get 5 and the Geminids 18, and the Geminids
    # look three times busier rather than thirty.
    n = round(STREAKS_MIN
              + STREAKS_MAX * (min(sh["zhr"], ZHR_FULL) / ZHR_FULL) ** 0.6)
    for i in range(n):
        # Spread evenly round the radiant with a nudge, rather than free
        # random: a genuinely random set of a dozen angles leaves a bald patch
        # every time, and "they come from all round this one point" is the
        # whole of what this drawing has to say.
        ang = (i / n) * 2 * math.pi + (rnd() - 0.5) * (math.pi / n)
        room = min(W, H) * (0.42 + rnd() * 0.5)
        d0 = 5 + rnd() * room * 0.7
        # Perspective, not decoration: a meteor near the radiant is coming
        # almost straight at you and looks short. Further out, longer.
        length = 3 + d0 * 0.6
        _streak(dots, rx + math.cos(ang) * d0, ry + math.sin(ang) * d0,
                rx + math.cos(ang) * (d0 + length),
                ry + math.sin(ang) * (d0 + length), W, H)

    grid, tint = _blit(dots, cols, rows, lambda c: _METEOR_RANK.get(c, -1))

    # Stars over the trails, brightest last -- the same order the asterism
    # portrait and the horizon chart both settled on.
    for x, y, st in sorted(stars, key=lambda p: -p[2]["m"]):
        c, r = int((rx + x * scale) // SUBX), int((ry - y * scale) // SUBY)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = sky.glyph_for(st["m"])
            tint[r][c] = sky.star_colour(st.get("ci"))

    # The radiant last and unconditionally: it is the one thing in the frame
    # that is not a star, and letting a star win the cell hides the subject.
    c, r = int(rx // SUBX), int(ry // SUBY)
    if 0 <= r < rows and 0 <= c < cols:
        grid[r][c], tint[r][c] = "+", RADIANT_C
    return _emit(grid, tint)


# ---------------------------------------------------------------- the Galaxy
# The one drawing here that is not computed from a catalogue.
#
# Everything else on this site is measured: where the stars are, where the
# shadow falls, how open Saturn's rings happen to be tonight. This cannot be.
# There is no photograph of the Milky Way from outside it and there will not
# be one in anyone's lifetime -- the shape is worked out from the inside, from
# arm tracers and maser parallaxes and gas velocities, and what comes out is a
# model. So this is a model, drawn as one, and object_prose says so on the
# page rather than letting the picture imply a photograph.
#
# The structure is the two-armed one the Spitzer star counts settled (Benjamin
# et al. 2005), which is what the familiar NASA/JPL-Caltech rendering shows:
# Scutum-Centaurus and Perseus come off the two ends of the bar and are the
# arms; Norma and Sagittarius-Carina are real but minor. Framed like that
# picture too, with the Sun below the centre.
#
# The one measured number in the frame is the Sun's distance from the centre.

MW_COLS = 36
MW_ROWS = 18

R_SUN_KPC = 8.2          # GRAVITY's 2019 orbit fit puts the black hole at 8.18
MW_R_DISC = 16.0         # where the drawing stops
MW_BAR_HALF = 4.0
MW_BAR_PA = 40.0         # the bar, degrees anticlockwise from the +x axis
MW_SUN_AZ = -90.0        # the Sun below centre, as in that rendering

# name, reference radius (kpc), start azimuth (deg), pitch (deg), turns, major
MW_ARMS = (("Scutum-Centaurus", 4.2, MW_BAR_PA, 13.5, 0.78, True),
           ("Perseus", 4.2, MW_BAR_PA + 180, 13.0, 0.78, True),
           ("Norma", 4.8, MW_BAR_PA + 62, 10.5, 0.55, False),
           ("Sagittarius-Carina", 5.6, MW_BAR_PA + 242, 11.5, 0.55, False))

MW_CORE = "\033[38;5;223m"     # the bulge: old stars, yellow
MW_BAR = "\033[38;5;222m"
MW_MAJOR = "\033[38;5;153m"    # the two arms that are arms
MW_MINOR = "\033[38;5;67m"     # the minor ones
MW_HALO = "\033[38;5;60m"      # the disc they sit in
MW_SUN = "\033[38;5;227m"      # the yellow the charts draw the Sun in

_MW_RANK = {None: -1, MW_HALO: 0, MW_MINOR: 1, MW_MAJOR: 2,
            MW_BAR: 3, MW_CORE: 4}


def milkyway_art(cols=MW_COLS, rows=MW_ROWS, sun=True):
    """The Galaxy from outside, as ANSI lines. North of the plane, looking down.

    Not a picture of the sky: everything else drawn here is what you would see
    from where you are standing, and this is the one view nobody has ever had.
    """
    rnd = _seeded("milky way")
    W, H = cols * SUBX, rows * SUBY
    scale = min(W, H) / 2 / MW_R_DISC
    dots = {}

    def put(x, y, col):
        if x * x + y * y > MW_R_DISC * MW_R_DISC:
            return
        px, py = int(round(W / 2 + x * scale)), int(round(H / 2 - y * scale))
        if 0 <= px < W and 0 <= py < H:
            if _MW_RANK.get(col, -1) >= _MW_RANK.get(dots.get((px, py)), -1):
                dots[(px, py)] = col

    # The disc the arms sit in, thinning outward the way a disc galaxy's light
    # really does. Kept thin: its whole job is to stop the arms floating in
    # black, and any denser it competes with them.
    for _ in range(520):
        r = MW_R_DISC * math.sqrt(rnd())
        a = rnd() * 2 * math.pi
        if rnd() > math.exp(-r / 5.0):
            continue
        put(r * math.cos(a), r * math.sin(a), MW_HALO)

    for _name, r_ref, beta0, pitch, turns, major in MW_ARMS:
        k = math.tan(math.radians(pitch))
        b0 = math.radians(beta0)
        col = MW_MAJOR if major else MW_MINOR
        width = 0.75 if major else 0.40
        steps = 900
        for i in range(steps):
            beta = b0 + (i / steps) * turns * 2 * math.pi
            r = r_ref * math.exp((beta - b0) * k)
            if r > MW_R_DISC:
                break
            cx, cy = r * math.cos(beta), r * math.sin(beta)
            nx, ny = math.cos(beta + math.pi / 2), math.sin(beta + math.pi / 2)
            # The ridge, always drawn. An arm is a continuous thing, and a
            # dotted one reads as noise rather than as an arm -- which is what
            # sank the first two attempts at this.
            put(cx, cy, col)
            # Then the body of the arm around it, widening outward and
            # thinning out as it goes, so an arm fades rather than stopping.
            for _ in range(int((6 if major else 3) * (0.4 + r / MW_R_DISC))):
                if rnd() > max(0.3, 1.15 - (r / MW_R_DISC) ** 2):
                    continue
                off = ((rnd() + rnd() + rnd() - 1.5) / 1.5
                       * width * (0.5 + r / MW_R_DISC))
                put(cx + nx * off, cy + ny * off, col)

    pa = math.radians(MW_BAR_PA)
    for _ in range(420):
        u = (rnd() + rnd() + rnd() - 1.5) / 1.5 * MW_BAR_HALF
        # The bar tapers: fat at the bulge, thin at the ends. Drawn flat and
        # it reads as a cigar laid over the middle rather than as the thing
        # the arms come out of.
        half_w = 1.05 * (1 - (abs(u) / MW_BAR_HALF) ** 2) + 0.18
        v = (rnd() + rnd() + rnd() - 1.5) / 1.5 * half_w
        put(u * math.cos(pa) - v * math.sin(pa),
            u * math.sin(pa) + v * math.cos(pa),
            MW_CORE if u * u + (v * 2.4) ** 2 < 2.0 else MW_BAR)

    grid, tint = _blit(dots, cols, rows, lambda c: _MW_RANK.get(c, -1))

    if sun:
        a = math.radians(MW_SUN_AZ)
        c = int(round(W / 2 + R_SUN_KPC * math.cos(a) * scale)) // SUBX
        r = int(round(H / 2 - R_SUN_KPC * math.sin(a) * scale)) // SUBY
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c], tint[r][c] = "☉", MW_SUN
    return _emit(grid, tint)
