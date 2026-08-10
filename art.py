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
    # Deep sky. Off the name rather than off the facts, unlike everything
    # above: none of these changes, and a galaxy looks the same tonight as it
    # did in 1781. Most of the catalogue gets nothing back -- see DSO_ART.
    if kind in DSO_KINDS:
        return dso_art(name)
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


# What object_facts calls the four deep-sky categories (api._KIND_WORD has the
# same four). Named here rather than tested inline so that adding a fifth is
# one edit and not a hunt.
DSO_KINDS = ("galaxy", "cluster", "nebula", "planetary nebula")


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


# --------------------------------------------------------------- deep sky
# The same problem the Galaxy above has, 120 times over: there is no view of
# M57 that is not somebody's photograph, and tracing one by hand makes it a
# derivative work (see the module docstring, and build_dsoinfo.py's reasons
# for typing 55 sizes rather than importing a catalogue).
#
# So these are models too, and only for the objects whose shape a handful of
# measured numbers actually determines. A planetary nebula is a shell of gas
# and the ring is limb brightening -- the line of sight through a thin shell
# is longest at the edge -- so drawing the path length through a shell gives
# the ring for free rather than by drawing a ring. A spiral is an exponential
# disc with a logarithmic spiral in it, which is what milkyway_art already
# draws. A globular is a King profile. Those come out as pictures of the
# physics, in the same way the planets are pictures of Lambert's law.
#
# Where the shape is irregular -- the Orion Nebula, the Veil, the North
# America -- there is no small set of numbers that produces it, and the only
# way to draw it is to copy one. Those get nothing, which is the same answer
# a single-star asterism gets.
#
# Every parameter here is either read from dsoinfo.json (the measured extent)
# or a published measured fact typed in below (position angle, concentration
# class). Nothing is chosen to look nice except the tone ramps.

DSO_COLS = 45
DSO_ROWS = 17

# Tone ramps, brightest first, matching sky.DSO_GLYPH's colour per category so
# the portrait and the glyph the chart marks it with are recognisably the same
# object: green galaxy, gold cluster, cyan planetary.
# Clusters of both kinds are gold, matching the glyph the charts mark them
# with. This is the one place here where the drawing keeps a convention instead
# of following the physics, and it is a deliberate choice rather than an
# oversight: a globular photographs white and an open cluster blue-white, and
# both of those were tried. At eleven pixels on a black plate the white came out
# as grey mush with no colour to it at all, while the gold reads instantly and
# agrees with the mark on the chart underneath. A drawing nobody can see the
# shape of is not more honest for having the right hue.
CLU_RAMP = ((0.66, "\033[38;5;229m"), (0.30, "\033[38;5;221m"),
            (0.0, "\033[38;5;136m"))

# What the photographs show, kept for the record and for anyone who wants to
# see the comparison again: an old population with no dust in it is white, and
# a young one is blue-white.
CLU_RAMP_WHITE = ((0.66, "\033[38;5;255m"), (0.30, "\033[38;5;252m"),
                  (0.0, "\033[38;5;103m"))
OPEN_RAMP_BLUE = ((0.66, "\033[38;5;255m"), (0.30, "\033[38;5;189m"),
                  (0.0, "\033[38;5;110m"))
PLN_RAMP = ((0.66, "\033[38;5;51m"), (0.30, "\033[38;5;44m"),
            (0.0, "\033[38;5;30m"))

# The other palette a planetary nebula comes in, and the reason it needs one:
# these things glow in two lines at once. Doubly ionised oxygen is blue-green
# and hydrogen alpha is red, and which one you see where depends on how far out
# you are looking -- the inner shell, close to the hot star, is oxygen; the
# outer shell and the lobes beyond it are hydrogen. So on this ramp the bright
# middle is blue-white and it goes pink and then deep red outward, which is not
# a decoration but the order the lines actually come in.
#
# The Dumbbell is the obvious case: a red object in every photograph ever taken
# of it, with a blue-white middle. Drawn in the chart's cyan it was wrong.
PLN_RAMP_HA = ((0.66, "\033[38;5;159m"), (0.30, "\033[38;5;211m"),
               (0.0, "\033[38;5;125m"))

# Two objects where the colour follows the radius and not the brightness, so
# these ramps are read against distance from the middle rather than against the
# tone. In a shell the two are not the same thing at all: brightness peaks at
# the ring, where the line of sight is longest, so the middle and the outside
# are both faint while being completely different colours.
#
# The Ring Nebula, from the middle out: blue where doubly ionised oxygen fills
# the cavity, teal and white through the shell itself, orange in the outer halo
# where hydrogen and nitrogen take over.
PLN_RAMP_RING = ((0.55, "\033[38;5;33m"), (0.18, "\033[38;5;80m"),
                 (0.0, "\033[38;5;173m"))

# The Crab, same idea and different physics. The blue-teal middle is not a
# spectral line at all -- it is synchrotron light from electrons spiralling in
# the pulsar's magnetic field, which is why it is smooth where the rest is
# filaments. The yellow and orange outside it are those filaments.
PLN_RAMP_CRAB = ((0.55, "\033[38;5;80m"), (0.25, "\033[38;5;228m"),
                 (0.0, "\033[38;5;172m"))

# The Pleiades' own colours. Its members are hot B stars and the dust around
# them scatters their light, so the stars and the cloud really are both blue --
# it is the one object here whose colour is measured rather than a convention.
# The figure is blue too, not the indigo the constellation lines use
# (sky.C.DIM), so the shape reads as belonging to the cluster rather than as a
# piece of Taurus that happens to cross it.
NEB_BLUE = ((0.66, "\033[38;5;117m"), (0.30, "\033[38;5;74m"),
            (0.0, "\033[38;5;25m"))
FIGURE_C = "\033[38;5;68m"

# Nebulosity stops well short of solid. It is the background of its own
# picture -- the stars are the subject -- and a cloud allowed the top of the
# ramp draws over them.
CLOUD_TONES = " ..::"

# The web over a modelled cluster, and the one dim thing in a gold drawing.
MESH_C = "\033[38;5;94m"

# Single braille dots, for stippling a cloud that would otherwise come out as
# flat bands of one character.
SPARKLE_DOTS = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)

# Spikes on the brightest members: a dash in each of the four neighbouring
# cells, laid against the star rather than centred in its own cell, so a
# character-wide star reads as three cells across.
#
# Every photograph of the Pleiades has these, and they are an artefact of the
# telescope rather than anything in the sky -- but so is the reason the cluster
# looks like six bright stars and not a thousand faint ones, and drawing the
# brightest members as bigger is the only way a character grid can say which
# ones the eye actually goes to.
SPIKES = ((0, -1, 0x24), (0, 1, 0x09), (-1, 0, 0x12), (1, 0, 0x12))

# How hard a member's halo is compressed against its brightness. Flux runs
# over a factor of eleven from Alcyone to Celaeno, and at the fourth root of
# that every sister still gets a halo while Alcyone's stays the largest.
GLOW_COMPRESS = 0.28

# Galaxies get milkyway_art's own palette instead, because it is the physical
# one and because the two drawings are of the same kind of thing: the bulge is
# old stars and yellow, the arms are young stars and blue. A galaxy portrait in
# the chart's green would agree with the glyph and disagree with the Galaxy
# plate two pages over, and of those two the physics is the one worth keeping.
GAL_RAMP = ((0.66, MW_CORE), (0.30, MW_MAJOR), (0.0, MW_HALO))

# The green one the chart marks a galaxy with, kept for comparison.
GAL_RAMP_CHART = ((0.66, "\033[38;5;157m"), (0.30, "\033[38;5;120m"),
                  (0.0, "\033[38;5;65m"))

# For the galaxies that are not yellow-and-blue. A spiral seen close to face on
# is mostly the light of its whole disc at once rather than of its arms, and
# what that adds up to is white: a cream core, grey-white arms, a blue-grey
# haze at the edge. The Whirlpool is the one everybody has seen, and drawn in
# the Galaxy's own palette it came out far too yellow.
GAL_RAMP_WHITE = ((0.66, "\033[38;5;230m"), (0.30, "\033[38;5;253m"),
                  (0.0, "\033[38;5;109m"))

# Brightness to characters. One character per cell, chosen from a ramp, which
# is how the planets above are shaded and for the same reason: these are
# smooth extended things, and a nebula wants a tone rather than a dot.
#
# The braille scatter the asterisms and the meteor showers use is the wrong
# tool here. It draws points and lines beautifully and a smooth gradient not
# at all: dithering eight dots per cell against a random threshold turns a
# fading edge into static, and the first attempt at the Ring Nebula came out
# as a speckled disc with no ring in it.
DSO_TONES = {
    # Sparse to solid. Two entries at each of the low steps, so the faint
    # outskirts get a wider band of the range than the bright middle -- most
    # of one of these objects is faint, and a linear ramp spends its whole
    # ladder on the core.
    "ascii": " ...::+*#",
    "blocks": " ░░▒▒▒▓▓█",
    "braille": " ⠄⠄⠆⠇⡇⡧⡷⣿",
}
DSO_STYLE = "ascii"

# Below this nothing is drawn at all. It is what gives the drawing an edge:
# an exponential disc never actually reaches zero, and without a cut every
# galaxy fills its whole frame with a haze.
DSO_FLOOR = 0.10

# How hard the tones are stretched: the asinh stretch astronomical images are
# displayed with, for the same reason they use it. A galaxy's core is hundreds
# of times its disc and a King core thousands of times its envelope, so a ramp
# linear in brightness spends eight of its nine steps on the middle cell and
# draws everything else as the faintest dot. Lower is a harder stretch.
#
# Per model, because the dynamic range is a property of the object rather than
# of the drawing. A shell has almost none -- the hole in the Ring Nebula is
# about half as bright as its rim -- and stretching that hard fills the hole
# in, which is the same mistake the dithered first pass made from the other
# direction.
DSO_STRETCH = {"shell": 0.7, "bipolar": 0.7, "eyes": 0.7, "ansae": 0.7,
               "spiral": 0.03, "elliptical": 0.03, "lens": 0.03,
               "globular": 0.03}
DSO_STRETCH_DEFAULT = 0.03

# Where a globular starts resolving into stars, as a fraction of the
# drawn radius. Inside this it is a smear at any aperture, and that is
# what makes one look like a globular rather than like a swarm.
GLOB_RESOLVED_IN = 0.22

# The tones a resolved star may be drawn over: the faint ones only.
GLOB_OVER = " .:"


def _ramp_colour(ramp, b):
    for t, col in ramp:
        if b >= t:
            return col
    return ramp[-1][1]


def _deproject(pa):
    """Screen (x right, y up) -> (u along the major axis, v across it).

    Position angle is measured from north through east, and east is to the
    left here as in every other drawing on the site, so the major axis points
    at (-sin pa, cos pa) on screen.
    """
    s, c = math.sin(math.radians(pa)), math.cos(math.radians(pa))
    return lambda x, y: (-x * s + y * c, x * c + y * s)


def _ellipse_box(q, pa, reach=1.0):
    """Screen half-width and half-height of an ellipse with semi-axes (1, q)
    turned by pa. Same job _extent does for the ring systems: the box decides
    the scale, so a galaxy lying diagonally is drawn as large as one lying
    flat instead of being sized off its major axis and clipped."""
    s, c = math.sin(math.radians(pa)), math.cos(math.radians(pa))
    return reach * math.hypot(s, q * c), reach * math.hypot(c, q * s)


def _radial_tint(q, pa):
    """1 in the middle, 0 at the edge, for colouring by radius.

    Needed because in a shell the colour and the brightness run on different
    axes: the tone peaks at the ring, where the sight line through the gas is
    longest, so the cavity and the outer halo are equally faint while being
    completely different colours. Keyed off brightness they come out the same,
    and the Ring Nebula loses the blue middle that is the whole of what it
    looks like.
    """
    uv = _deproject(pa)

    def hue(x, y):
        u, v = uv(x, y)
        return max(0.0, 1.0 - math.hypot(u, v / q))
    return hue


def _field(cols, rows, hx, hy, fn, ramp, style=None,
           stretch=None, chars=None, hue=None):
    """A brightness function, sampled onto a character grid.

    fn(u, v) -> 0..1 in units of the object's own major-axis half-length, with
    the frame scaled so (hx, hy) just fits. Each cell is sampled at the eight
    sub-pixel positions and averaged, which is what keeps a curved edge from
    stepping: a cell half inside the shell comes out half as bright rather
    than in or out.

    Nothing random, so there is no seed: the same numbers give the same
    picture in the terminal, in the browser and in the PNG export.
    """
    # chars overrides the ramp for a layer that must stay a background: a
    # ladder that stops short of the solid end can never take the eye off
    # what is drawn on top of it.
    tones = chars or DSO_TONES[style or DSO_STYLE]
    stretch = stretch or DSO_STRETCH_DEFAULT
    W, H = cols * SUBX, rows * SUBY
    scale = min((cols - 2) * SUBX / 2 / hx, (rows - 2) * SUBY / 2 / hy)
    cells = [[0.0] * cols for _ in range(rows)]
    peak = 0.0
    for r in range(rows):
        for c in range(cols):
            tot = 0.0
            for sy in range(SUBY):
                for sx in range(SUBX):
                    px, py = c * SUBX + sx, r * SUBY + sy
                    tot += fn((px + 0.5 - W / 2) / scale,
                              (H / 2 - py - 0.5) / scale)
            cells[r][c] = tot / (SUBX * SUBY)
            peak = max(peak, cells[r][c])
    if peak <= 0.0:
        return ([[" "] * cols for _ in range(rows)],
                [[None] * cols for _ in range(rows)])

    # Scaled to the drawing's own brightest cell, not to an absolute number.
    # These profiles differ by orders of magnitude between a galaxy's core and
    # its outskirts, and one fixed scale for all of them leaves the faint ones
    # as a smudge; this is a picture of relative brightness, which is what the
    # eye at an eyepiece sees too.
    grid = [[" "] * cols for _ in range(rows)]
    tint = [[None] * cols for _ in range(rows)]
    top = math.asinh(1.0 / stretch)
    for r in range(rows):
        for c in range(cols):
            b = math.asinh(cells[r][c] / peak / stretch) / top
            if b <= DSO_FLOOR:
                continue
            step = (b - DSO_FLOOR) / (1.0 - DSO_FLOOR) * (len(tones) - 1)
            grid[r][c] = tones[min(len(tones) - 1, int(step) + 1)]
            if hue is None:
                tint[r][c] = _ramp_colour(ramp, b)
            else:
                # At the cell's middle rather than averaged: colour has no
                # business being blended between two of three tones, and a
                # boundary that lands mid-cell reads better hard than mixed.
                tint[r][c] = _ramp_colour(
                    ramp, hue(((c + 0.5) * SUBX - W / 2) / scale,
                              (H / 2 - (r + 0.5) * SUBY) / scale))
    return grid, tint


# ---- the shapes ---------------------------------------------------------

def _shell_path(p, inner):
    """How much shell a line of sight at impact parameter p goes through.

    A hollow sphere of outer radius 1 and inner radius `inner`. This is the
    whole reason a planetary nebula looks like a ring: nothing is dark in the
    middle, there is simply less gas along that line.
    """
    if p >= 1.0:
        return 0.0
    out = math.sqrt(1.0 - p * p)
    return out - (math.sqrt(inner * inner - p * p) if p < inner else 0.0)


def _shell_fn(q, pa, inner, gamma=1.0):
    uv, peak = _deproject(pa), math.sqrt(1.0 - inner * inner)

    def fn(x, y):
        u, v = uv(x, y)
        return (_shell_path(math.hypot(u, v / q), inner) / peak) ** gamma
    return fn


def _bipolar_fn(q, pa, sep, lobe, inner, gamma=1.0):
    """Two shells on a common axis: the shape a bipolar planetary has, and
    the shape M27 and M76 are named for."""
    uv = _deproject(pa)
    peak = math.sqrt(1.0 - inner * inner)

    def fn(x, y):
        u, v = uv(x, y)
        b = 0.0
        for off in (-sep, sep):
            p = math.hypot((u - off) / lobe, v / (lobe * q))
            b += _shell_path(p, inner) / peak
        return min(1.0, b) ** gamma
    return fn


def _eyes_fn(q, pa, inner, eye_u, eye_v, eye_r, gamma=1.0):
    """A shell with two darker patches in it, which is what earned M97 the
    name Owl. The patches are cavities, so they are drawn by taking gas away
    rather than by drawing eyes."""
    uv, base = _deproject(pa), _shell_fn(q, pa, inner, gamma)

    def fn(x, y):
        b = base(x, y)
        if b <= 0.0:
            return 0.0
        u, v = uv(x, y)
        for off in (-eye_u, eye_u):
            if math.hypot(u - off, v - eye_v) < eye_r:
                # Darker, not empty. A cavity has less gas along the line of
                # sight, not none, and drawn as a hole it reads as damage to
                # the picture rather than as structure in the object.
                return b * 0.45
        return b
    return fn


def _ansae_fn(q, pa, inner, knot_u, knot_r, gamma=1.0):
    """A shell with a knot on each end of the major axis. NGC 7009 is called
    the Saturn Nebula because those two knots look like a ring seen edge-on;
    they are real ejecta, not a drawing conceit."""
    uv, base = _deproject(pa), _shell_fn(q, pa, inner, gamma)

    def fn(x, y):
        b = base(x, y)
        u, v = uv(x, y)
        for off in (-knot_u, knot_u):
            d = math.hypot(u - off, v) / knot_r
            if d < 1.0:
                b = max(b, 0.85 * (1.0 - d * d))
        return b
    return fn


def _spiral_fn(q, pa, arms, pitch, h, bulge, bulge_amp, sharp=2.0):
    """An exponential disc with a logarithmic spiral in it.

    The same arm law milkyway_art uses, seen from here instead of from above:
    the sky-plane point is deprojected onto the disc, so the arms come out as
    the ellipses a tilted spiral actually shows rather than as circles.
    """
    uv, k = _deproject(pa), math.tan(math.radians(pitch))

    def fn(x, y):
        u, v = uv(x, y)
        w = v / q
        r = math.hypot(u, w)
        if r > 1.0:
            return 0.0
        arm = (0.5 + 0.5 * math.cos(arms * (math.atan2(w, u)
                                            - math.log(max(r, 0.03)) / k)))
        return (math.exp(-r / h) * (0.34 + 0.66 * arm ** sharp)
                + bulge_amp * math.exp(-r / bulge))
    return fn


def _elliptical_fn(q, pa, re):
    """de Vaucouleurs: the profile an elliptical galaxy has, which is why one
    reads as a smooth gradient with no edge while a spiral reads as arms."""
    uv = _deproject(pa)

    def fn(x, y):
        u, v = uv(x, y)
        r = math.hypot(u, v / q)
        if r > 1.0:
            return 0.0
        return math.exp(-7.67 * ((r / re) ** 0.25 - 1.0))
    return fn


def _lens_fn(pa, disc_q, disc_h, bulge_q, bulge_re, lane_v, lane_w):
    """A thin disc, a fat bulge, and a dust lane across the disc. The lane is
    the whole of why M104 is called the Sombrero, and it is dust in front of
    the disc, so it is drawn by subtracting light rather than adding dark."""
    uv = _deproject(pa)

    def fn(x, y):
        u, v = uv(x, y)
        rd = math.hypot(u, v / disc_q)
        rb = math.hypot(u, v / bulge_q)
        b = 0.0
        if rd <= 1.0:
            b += math.exp(-rd / disc_h)
        if rb <= 1.0:
            b += 0.85 * math.exp(-7.67 * ((rb / bulge_re) ** 0.25 - 1.0))
        if abs(v - lane_v) < lane_w and rd <= 1.0:
            b *= 0.02
        return b
    return fn


def _king_fn(rc):
    """A King profile: flat core, falling envelope, cut off at the tidal
    radius. rc is the core radius as a fraction of that cutoff, and it is
    what the Shapley-Sawyer concentration class measures -- which is the
    difference between M15's needle-sharp middle and M4's loose sprawl."""
    floor = 1.0 / (1.0 + 1.0 / (rc * rc))

    def fn(x, y):
        r = math.hypot(x, y)
        if r > 1.0:
            return 0.0
        return ((1.0 / (1.0 + (r / rc) ** 2) - floor) / (1.0 - floor)) ** 0.8
    return fn


# ---- clusters drawn as stars -------------------------------------------
# A globular's core is a smear and its outskirts are stars, so the profile
# above is the right drawing for one. An open cluster is the opposite: it is
# stars all the way in, which is what "open" means, and a dithered blob would
# be a picture of the wrong thing.

def _open_stars(seed, n, spread, conc=0.65, cx=0.0, cy=0.0):
    """n member positions and relative brightnesses, seeded off the name.

    The brightness draw is weighted, because a cluster's luminosity function
    is: two or three members carry the eye and the rest are faint. Drawn
    evenly it reads as gravel.
    """
    rnd = _seeded(seed)
    out = []
    for _ in range(n):
        r = spread * rnd() ** conc
        a = rnd() * 2 * math.pi
        out.append((cx + r * math.cos(a), cy + r * math.sin(a), rnd() ** 2.2))
    return out


def _mesh(stars, keep, place, W, H, limit=None):
    """Braille links between the brightest members, as sub-pixel dots.

    A modelled open cluster is a scatter, and a scatter of dots is the one
    thing on this site that reads as an accident rather than as an object.
    Joining the brightest few gives it an outline -- which is what the eye
    does at the eyepiece anyway, and what the asterism portraits are built
    on.

    Each of the brightest few joined to its nearest neighbour among them, and
    nothing else. Not a spanning tree: a tree has to reach every star it was
    given, so one outlying member drags a line right across the plate, and
    that single straggle undoes the shape the rest of the web builds. Local
    links can simply stop, which is what leaves it a cluster with an outline
    rather than a diagram of one.
    """
    bright = sorted(stars, key=lambda s: -s[2])[:keep]
    dots, seen = set(), set()
    for i, a in enumerate(bright):
        rest = [(math.hypot(a[0] - b[0], a[1] - b[1]), j, b)
                for j, b in enumerate(bright) if j != i]
        if not rest:
            break
        rest.sort()
        for d, j, b in rest[:2]:
            if limit and d > limit:
                break
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            _ast_line(dots, place(a[0], a[1]), place(b[0], b[1]), W, H)
    return dots


def _star_grid(cols, rows, hx, hy, stars, colour, mesh=0, mesh_limit=None):
    """Discrete stars onto a character grid, brightest last.

    colour(b) -> ANSI for a star of relative brightness b. Brightest last for
    the reason the asterism portraits and the horizon chart both settled on:
    where two stars want one cell, the one worth finding should win it.

    mesh joins that many of the brightest with braille, under the stars.
    """
    import sky
    W, H = cols * SUBX, rows * SUBY
    scale = min((cols - 2) * SUBX / 2 / hx, (rows - 2) * SUBY / 2 / hy)
    grid = [[" "] * cols for _ in range(rows)]
    tint = [[None] * cols for _ in range(rows)]

    def place(x, y):
        return W / 2 + x * scale, H / 2 - y * scale

    if mesh:
        cells = {}
        for x, y in _mesh(stars, mesh, place, W, H, mesh_limit):
            key = (x // SUBX, y // SUBY)
            cells[key] = (cells.get(key, 0)
                          | sky.BRAILLE_DOTS[(x % SUBX, y % SUBY)])
        for (c, r), bits in cells.items():
            if 0 <= r < rows and 0 <= c < cols:
                grid[r][c] = chr(sky.BRAILLE_BASE + bits)
                tint[r][c] = MESH_C

    for x, y, b in sorted(stars, key=lambda s: s[2]):
        c = int((W / 2 + x * scale) // SUBX)
        r = int((H / 2 - y * scale) // SUBY)
        if 0 <= r < rows and 0 <= c < cols:
            # Straight to the ladder the charts use, through a magnitude, so a
            # cluster member and a field star of the same brightness are drawn
            # with the same glyph.
            grid[r][c] = sky.glyph_for(5.0 - 4.5 * b)
            tint[r][c] = colour(b)
    return grid, tint


def _real_field(ra_h, dec_deg, radius_deg, limit):
    """The catalogue's own stars inside a circle, gnomonic about its centre.

    The one honest way to draw an open cluster: for the Pleiades, stars.json
    holds nine members brighter than its own 6.5 cutoff, in their real
    positions, and that scatter is the shape people recognise. It is the only
    cluster on the site where this works -- every other sized object has one
    catalogue star inside it, or none.
    """
    out = []
    for x, y, st in _shower_field({"ra": ra_h, "dec": dec_deg}, limit):
        if math.hypot(x, y) <= radius_deg:
            out.append((x, y, st))
    return out


def _real_art(spec, stars, cols, rows, style, seed):
    """An open cluster drawn from its own catalogue stars.

    Three layers, and each is a different kind of claim. The stars are
    measured: real positions, real magnitudes, real colours. The figure is a
    convention the way an asterism's is -- somebody decided which of the
    sisters to join up, and joining them is what makes eight dots read as the
    Pleiades rather than as scattered field stars. The nebulosity is a model:
    the dust is really there and really is lit by these stars, so it is drawn
    as a glow around each member scaled by that member's own brightness, which
    is why it comes out strongest where the bright sisters are. Nothing about
    it is copied off a photograph.
    """
    import sky
    # Framed on the members' own bounding box rather than on the cited centre:
    # the stars bright enough to be in stars.json are not symmetric about it,
    # and centring there left the Pleiades in the middle third of the plate
    # with the rest of it empty.
    xs = [x for x, _y, _st in stars]
    ys = [y for _x, y, _st in stars]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    glow = spec.get("glow")
    # Room for the cloud to fade out in. Without it the glow is cut off square
    # at the outermost star, which is the one thing a cloud must not do.
    pad = 1.06 + (2.4 * glow if glow else 0.0)
    hx = max(1e-6, (max(xs) - min(xs)) / 2) * pad
    hy = max(1e-6, (max(ys) - min(ys)) / 2) * pad
    W, H = cols * SUBX, rows * SUBY
    scale = min((cols - 2) * SUBX / 2 / hx, (rows - 2) * SUBY / 2 / hy)

    def place(x, y):
        return W / 2 + (x - cx) * scale, H / 2 - (y - cy) * scale

    # The cloud first, so everything else sits inside it.
    if glow:
        # A halo per member, and the brightest halo wins rather than the sum.
        # Summed, the dust between the close sisters piles up into one mound
        # brighter than anything around it, the whole frame gets normalised to
        # that mound, and every other star loses its glow -- which is exactly
        # how the first version came out looking like a wash of watercolour.
        #
        # Amplitude compressed hard, because it runs over a factor of eleven
        # between Alcyone and Celaeno: uncompressed, only Alcyone has a halo
        # at all. Compressed, every sister gets one and Alcyone's is still the
        # biggest, which is what the photographs show.
        top = min(st["m"] for _x, _y, st in stars)
        lamps = [(x - cx, y - cy,
                  (10 ** (-0.4 * (st["m"] - top))) ** GLOW_COMPRESS)
                 for x, y, st in stars]

        # Where the wings are cut off. A power law has no edge, so without
        # this the faintest step of the ramp covers the whole plate in an even
        # dusting of full stops -- present everywhere, saying nothing, and the
        # single biggest reason the first version read as watercolour.
        cut = spec.get("haze_cut", 0.10)

        def cloud(u, v):
            # Not a Gaussian: scattered light falls off as a power of the
            # distance, so a halo has a small bright middle and wings that go
            # a long way out. A Gaussian has neither, and draws as a disc.
            return max(0.0, max(a / (1.0 + ((u - px) ** 2 + (v - py) ** 2)
                                     / (glow * glow))
                                for px, py, a in lamps) - cut)
        grid, tint = _field(cols, rows, hx, hy, cloud, NEB_BLUE, style,
                            spec.get("stretch", 0.55), chars=CLOUD_TONES)
    else:
        grid = [[" "] * cols for _ in range(rows)]
        tint = [[None] * cols for _ in range(rows)]

    # Then the figure, in braille, the way the asterism portraits draw theirs.
    named = {st.get("n"): (x, y) for x, y, st in stars if st.get("n")}
    dots = set()
    for chain in spec.get("figure") or ():
        pts = [place(*named[n]) for n in chain if n in named]
        for a, b in zip(pts, pts[1:]):
            _ast_line(dots, a, b, W, H)
    cells = {}
    for x, y in dots:
        key = (x // SUBX, y // SUBY)
        cells[key] = cells.get(key, 0) | sky.BRAILLE_DOTS[(x % SUBX, y % SUBY)]
    for (c, r), bits in cells.items():
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = chr(sky.BRAILLE_BASE + bits)
            tint[r][c] = FIGURE_C

    # A scatter of single braille dots in the blue-white the members are drawn
    # in. Two jobs. The nebulosity is a smooth function, and a smooth function
    # over a coarse grid comes out as flat bands of one character -- a wash,
    # with nothing in it to look at -- so these break it up; dust is not
    # smooth, and this is closer to the object as well as to a picture worth
    # having. And the field around the Pleiades is thick with faint stars that
    # are nowhere near the catalogue's 6.5 cutoff, so open sky here is a
    # statement about the catalogue rather than about the sky.
    #
    # Deliberately braille rather than the star glyphs: at a dot apiece they
    # read as texture, and nothing in the drawing claims a star at a position
    # that has not been measured.
    if spec.get("sparkle"):
        rnd = _seeded(seed + "sparkle")
        for _ in range(spec["sparkle"]):
            c, r = int(rnd() * cols), int(rnd() * rows)
            bit = SPARKLE_DOTS[int(rnd() * len(SPARKLE_DOTS))]
            if 0 <= r < rows and 0 <= c < cols and grid[r][c] in CLOUD_TONES:
                grid[r][c] = chr(sky.BRAILLE_BASE + bit)
                tint[r][c] = NEB_BLUE[0][1]

    # The stars last and brightest last, as everywhere else here: where two
    # want one cell, the one worth finding wins it.
    #
    # boost shifts the magnitudes into the top of the glyph ladder. A cluster
    # portrait is a picture of its own members and nothing else, so the
    # brightest of them should be drawn as the brightest thing the ladder has;
    # left on the absolute scale the Pleiades came out as eight faint dots,
    # because on the sky that is what a mag 4 star is.
    boost = spec.get("boost", 0.0)
    bright = sorted(stars, key=lambda p: p[2]["m"])[:spec.get("spikes", 0)]
    for x, y, _st in bright:
        px, py = place(x, y)
        c0, r0 = int(px // SUBX), int(py // SUBY)
        for dc, dr, bits in SPIKES:
            c, r = c0 + dc, r0 + dr
            if 0 <= r < rows and 0 <= c < cols:
                grid[r][c] = chr(sky.BRAILLE_BASE + bits)
                tint[r][c] = NEB_BLUE[0][1]
    for x, y, st in sorted(stars, key=lambda p: -p[2]["m"]):
        px, py = place(x, y)
        c, r = int(px // SUBX), int(py // SUBY)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = sky.glyph_for(st["m"] - boost)
            tint[r][c] = sky.star_colour(st.get("ci"))
    return _emit(grid, tint)


# ---- the table ----------------------------------------------------------
# Keyed by catalogue id, like dsoinfo.json, because a page can be reached by
# either name ("M57" and "Ring Nebula" are both canonical) and the drawing is
# of the object, not of the name.
#
# Three kinds of number live here and they are not equally trustworthy:
#
#   Measured, and read from dsoinfo.json: the axis ratio. Not typed here at
#   all, except for the few objects dsoinfo does not cover yet.
#
#   Measured, and typed here: the position angle of the major axis (north
#   through east) and the Shapley-Sawyer concentration class. Both are
#   published facts about the object, and both have been checked against a
#   source -- SIMBAD's angular-size record for the position angles, the class
#   from each cluster's own literature. All thirteen classes came back exactly
#   as first typed; nine of the seventeen position angles did not, and M51 was
#   out by 142 degrees. Anything typed from memory here has to be checked the
#   same way before it ships, because a wrong angle on a thin galaxy points it
#   the wrong way against the chart directly underneath it.
#
#   Not measured, and not available: three objects have an axis ratio and no
#   published angle to go with it -- M27, M1 and M97. They are drawn with the
#   major axis up, which is a convention and not a claim; see the entries.
#
#   Not measured at all: how many members an open cluster is drawn with, and
#   the arm count and pitch of a spiral. These are drawing choices. A modelled
#   scatter says "about this rich, over this much sky" and nothing more.
#
# Shapley-Sawyer class -> core radius as a fraction of the drawn radius. The
# class is the published datum and this ladder is the drawing's reading of it,
# which is the right way round: I is a point with a halo and XII is barely a
# cluster at all.
SHAPLEY_RC = {"I": 0.06, "II": 0.09, "III": 0.11, "IV": 0.13, "V": 0.17,
              "VI": 0.21, "VII": 0.25, "VIII": 0.30, "IX": 0.36, "X": 0.42,
              "XI": 0.48, "XII": 0.55}

DSO_ART = {
    # -- planetary nebulae. Shells, so the drawing is a path length.
    "NGC6720": {"model": "shell", "ramp": "pln_ring", "tint": "radial",
                "pa": 60.0, "inner": 0.72},           # M57, the Ring
    # No published angle for the dumbbell axis: SIMBAD carries M27 as round
    # (6.7 by 6.7) so it has no position angle to give, and the 8.0 by 5.7
    # in dsoinfo.json comes from the visual observing guides, which quote
    # an extent and not an orientation. Drawn with the axis up, which is a
    # convention rather than a claim about where it points.
    "NGC6853": {"model": "bipolar", "ramp": "pln_ha", "pa": 0.0,
                "sep": 0.46, "lobe": 0.58, "inner": 0.40},   # M27, Dumbbell
    "NGC7009": {"model": "ansae", "ramp": "pln", "pa": 70.0, "q": 0.74,
                "inner": 0.40, "knot_u": 1.34, "knot_r": 0.22,
                "reach": 1.60},                       # the Saturn Nebula
    "NGC650":  {"model": "bipolar", "ramp": "pln", "pa": 40.0,
                "sep": 0.48, "lobe": 0.55,
                "inner": 0.42},                       # M76, Little Dumbbell
    "NGC3587": {"model": "eyes", "ramp": "pln", "pa": 0.0, "inner": 0.30,
                "eye_u": 0.34, "eye_v": 0.08,
                "eye_r": 0.26},                       # M97, the Owl
    "NGC6543": {"model": "shell", "ramp": "pln", "pa": 10.0, "q": 0.86,
                "inner": 0.45},                       # NGC 6543, Cat's Eye
    # The one drawing here of an object the models do not really fit. A
    # supernova remnant is filaments, not a shell, and no small set of numbers
    # produces filaments -- so this is an honest oval at the measured 6.0x4.0
    # and the prose has to carry the rest. Better than nothing only because
    # the Crab is famous enough that a reader arrives expecting a picture.
    "NGC1952": {"model": "shell", "ramp": "pln_crab", "tint": "radial",
                "pa": 0.0, "inner": 0.10},            # M1, the Crab

    # -- galaxies
    "NGC224":  {"model": "spiral", "ramp": "gal", "pa": 35.0,
                "bulge_amp": 0.55},                   # M31, Andromeda
    "NGC5194": {"model": "spiral", "ramp": "gal_white", "pa": 28.0,
                "pitch": 18.0, "bulge_amp": 0.50},    # M51, the Whirlpool
    "NGC4594": {"model": "lens", "ramp": "gal", "pa": 90.0, "disc_q": 0.20,
                "disc_h": 0.55, "bulge_q": 0.58, "bulge_re": 0.22,
                "lane_v": -0.03, "lane_w": 0.030},    # M104, the Sombrero
    "NGC4486": {"model": "elliptical", "ramp": "gal",
                "pa": 152.0},                         # M87
    # Round, so there is no angle to get wrong: dsoinfo.json has no minor
    # axis for it and SIMBAD gives none either.
    "NGC5457": {"model": "spiral", "ramp": "gal", "pa": 0.0, "arms": 3,
                "pitch": 20.0, "h": 0.38,
                "bulge_amp": 0.40},                   # M101, the Pinwheel
    "NGC598":  {"model": "spiral", "ramp": "gal", "pa": 22.0, "pitch": 22.0,
                "bulge_amp": 0.25},                   # M33, Triangulum
    "NGC3031": {"model": "spiral", "ramp": "gal", "pa": 157.0, "pitch": 13.0,
                "bulge_amp": 0.70},                   # M81, Bode's
    # A starburst irregular seen edge on: no arms to draw and no bulge to draw
    # them round, so the smooth profile is the honest one.
    "NGC3034": {"model": "elliptical", "ramp": "gal", "pa": 66.0,
                "re": 0.50},                          # M82, the Cigar
    "NGC5236": {"model": "spiral", "ramp": "gal", "pa": 45.0, "pitch": 18.0,
                "bulge_amp": 0.50},                   # M83
    "NGC5055": {"model": "spiral", "ramp": "gal", "pa": 102.0, "arms": 5,
                "pitch": 12.0, "bulge_amp": 0.60},    # M63, the Sunflower
    "NGC4826": {"model": "spiral", "ramp": "gal", "pa": 113.0, "pitch": 12.0,
                "bulge_amp": 0.75},                   # M64, the Black Eye
    "NGC3623": {"model": "spiral", "ramp": "gal", "pa": 173.0, "pitch": 10.0,
                "bulge_amp": 0.70},                   # M65
    "NGC3627": {"model": "spiral", "ramp": "gal", "pa": 170.0,
                "bulge_amp": 0.60},                   # M66
    "NGC628":  {"model": "spiral", "ramp": "gal", "pa": 103.0, "pitch": 20.0,
                "bulge_amp": 0.40},                   # M74
    "NGC1068": {"model": "spiral", "ramp": "gal", "pa": 27.0, "pitch": 16.0,
                "bulge_amp": 0.80},                   # M77
    "NGC221":  {"model": "elliptical", "ramp": "gal", "pa": 170.0,
                "re": 0.40},                          # M32
    "NGC205":  {"model": "elliptical", "ramp": "gal", "pa": 170.0,
                "re": 0.45},                          # M110

    # -- globular clusters, by concentration class
    "NGC5139": {"model": "globular", "ramp": "clu",
                "class": "VIII"},                     # Omega Centauri
    "NGC104":  {"model": "globular", "ramp": "clu",
                "class": "III"},                      # 47 Tucanae
    "NGC6205": {"model": "globular", "ramp": "clu",
                "class": "V"},                        # M13, the Hercules
    "NGC7078": {"model": "globular", "ramp": "clu",
                "class": "IV"},                       # M15
    "NGC5904": {"model": "globular", "ramp": "clu", "class": "V"},    # M5
    "NGC6656": {"model": "globular", "ramp": "clu", "class": "VII"},  # M22
    "NGC6121": {"model": "globular", "ramp": "clu", "class": "IX"},   # M4
    "NGC5272": {"model": "globular", "ramp": "clu", "class": "VI"},   # M3
    "NGC6341": {"model": "globular", "ramp": "clu", "class": "IV"},   # M92
    "NGC7089": {"model": "globular", "ramp": "clu", "class": "II"},   # M2
    "NGC6254": {"model": "globular", "ramp": "clu", "class": "VII"},  # M10
    "NGC5024": {"model": "globular", "ramp": "clu", "class": "V"},    # M53
    "NGC6093": {"model": "globular", "ramp": "clu", "class": "II"},   # M80

    # -- open clusters
    # The Pleiades, and no chain between the stars. An asterism is a figure --
    # lines somebody drew between stars that have nothing to do with each
    # other -- and this is the opposite: a real cluster, a thousand stars born
    # together and still travelling together. Drawing the bowl-and-handle over
    # it says the shape is the object, when the object is the swarm and the
    # dust it is lighting.
    # The radius takes in all seven sisters plus Atlas and Pleione, and stops
    # short of the mag 5.4 field star three quarters of a degree south, which
    # is not part of the figure anyone recognises and which set the scale for
    # the whole plate when it was let in. It is a narrow gap to thread -- 0.61
    # for the outermost sister against 0.73 for that star -- so the test names
    # the sisters rather than counting them: 0.60 quietly dropped two.
    "M45":     {"model": "real", "limit": 6.5, "radius": 0.66, "glow": 0.12,
                "stretch": 0.30, "haze_cut": 0.30, "boost": 2.4,
                "sparkle": 26, "spikes": 4},
    "NGC6705": {"model": "open", "ramp": "clu", "n": 70, "spread": 0.95,
                "conc": 0.75, "mesh": 14},            # M11, the Wild Duck
    "NGC869":  {"model": "pair", "ramp": "clu", "with": "NGC884",
                "n": 34, "radius": 0.16, "mesh": 16},  # the Double Cluster
    "NGC2632": {"model": "open", "ramp": "clu", "n": 40, "spread": 0.95,
                "conc": 0.55, "mesh": 12},            # M44, the Beehive
    "NGC6475": {"model": "open", "ramp": "clu", "n": 30, "spread": 0.95,
                "conc": 0.50, "mesh": 10},            # M7, Ptolemy's
    "NGC6405": {"model": "open", "ramp": "clu", "n": 26, "spread": 0.95,
                "conc": 0.55, "mesh": 10},            # M6, the Butterfly
    "NGC2168": {"model": "open", "ramp": "clu", "n": 50, "spread": 0.95,
                "conc": 0.60, "mesh": 12},            # M35
    "NGC2099": {"model": "open", "ramp": "clu", "n": 60, "spread": 0.95,
                "conc": 0.65, "mesh": 12},            # M37
    "NGC1960": {"model": "open", "ramp": "clu", "n": 30, "spread": 0.95,
                "conc": 0.60, "mesh": 10},            # M36
    "NGC1912": {"model": "open", "ramp": "clu", "n": 40, "spread": 0.95,
                "conc": 0.60, "mesh": 11},            # M38
    "NGC7092": {"model": "open", "ramp": "clu", "n": 20, "spread": 0.95,
                "conc": 0.45, "mesh": 8},             # M39
    "NGC2287": {"model": "open", "ramp": "clu", "n": 34, "spread": 0.95,
                "conc": 0.55, "mesh": 10},            # M41
    "NGC2437": {"model": "open", "ramp": "clu", "n": 50, "spread": 0.95,
                "conc": 0.60, "mesh": 12},            # M46
    "NGC2422": {"model": "open", "ramp": "clu", "n": 24, "spread": 0.95,
                "conc": 0.50, "mesh": 9},             # M47
    "NGC7654": {"model": "open", "ramp": "clu", "n": 40, "spread": 0.95,
                "conc": 0.60, "mesh": 11},            # M52
    "NGC2682": {"model": "open", "ramp": "clu", "n": 50, "spread": 0.95,
                "conc": 0.60, "mesh": 12},            # M67
}

_RAMPS = {"gal": GAL_RAMP, "clu": CLU_RAMP, "pln": PLN_RAMP,
          "gal_white": GAL_RAMP_WHITE, "pln_ha": PLN_RAMP_HA,
          "pln_ring": PLN_RAMP_RING, "pln_crab": PLN_RAMP_CRAB,
          # Not used by anything in the table: the alternatives, so a
          # comparison can be drawn without editing the palettes back in.
          "gal_chart": GAL_RAMP_CHART, "clu_white": CLU_RAMP_WHITE,
          "open_blue": OPEN_RAMP_BLUE}


def _dso_entry(name):
    """The catalogue record behind a page name, or None. Brightest wins, the
    same tie-break objects._index uses, so "M31" lands on Andromeda rather
    than on NGC205."""
    import sky
    key = (name or "").strip().lower()
    if not key:
        return None
    best = None
    for o in sky._load("deepsky.json"):
        if key in (o["n"].lower(), o["id"].lower(),
                   (o.get("cn") or "").lower()):
            if best is None or o["m"] < best["m"]:
                best = o
    return best


def dso_art_basis(name):
    """The measured figures a portrait was built from, as clauses, or ().

    For the credit line on the page. Per object rather than one blanket
    sentence, for the reason api.object_sources gives: a globular's drawing
    rests on its concentration class and a galaxy's on its axis ratio and
    angle, and crediting both everywhere credits a number that had nothing to
    do with the page being read.

    Answered off the table rather than by drawing the thing, so asking is
    cheap: object_sources runs on every page and the drawing is not free.
    """
    obj = _dso_entry(name)
    spec = DSO_ART.get(obj["id"]) if obj else None
    if not spec:
        return ()
    if spec["model"] == "real":
        # The one portrait whose stars are real, so this is a source credit
        # and not a note about a model.
        return ("cluster members from the Yale Bright Star Catalogue",)
    if spec["model"] == "globular":
        return ("portrait modelled from the published concentration class",)
    if spec["model"] in ("open", "pair"):
        return ("portrait modelled from the measured extent",)
    bits = []
    if _dso_q(obj, spec) < 0.999:
        bits.append("axis ratio")
    if spec.get("pa"):
        bits.append("position angle")
    if not bits:
        return ("portrait modelled from published dimensions",)
    return (f"portrait modelled from the published {' and '.join(bits)}",)


def _dso_q(obj, spec):
    """The axis ratio: measured where dsoinfo.json has both axes, typed in the
    table where it does not, and round otherwise."""
    import sky
    inf = sky._load("dsoinfo.json").get(obj["id"], {})
    if inf.get("min") and inf.get("maj"):
        return inf["min"] / inf["maj"]
    return spec.get("q", 1.0)


def dso_art(name, cols=DSO_COLS, rows=DSO_ROWS, ramp=None,
            style=None):
    """A deep-sky object's portrait, as ANSI lines, or [].

    [] for anything not in DSO_ART, which is most of the catalogue: an object
    whose shape is not determined by a few measured numbers gets no picture
    rather than an invented one.
    """
    import sky
    obj = _dso_entry(name)
    if obj is None:
        return []
    spec = DSO_ART.get(obj["id"])
    if not spec:
        return []
    model = spec["model"]
    tones = _RAMPS[ramp or spec.get("ramp", "clu")] if model != "real" else None
    seed = obj["id"]
    q, pa = _dso_q(obj, spec), spec.get("pa", 0.0)
    reach = spec.get("reach", 1.0)

    if model == "real":
        inf = sky._load("dsoinfo.json").get(obj["id"], {})
        radius = spec.get("radius") or (inf.get("maj") or 60.0) / 120.0
        stars = _real_field(obj["ra"], obj["de"], radius, spec["limit"])
        if not stars:
            return []
        return _real_art(spec, stars, cols, rows, style, seed)

    if model == "open":
        stars = _open_stars(seed, spec["n"], spec["spread"], spec["conc"])
        grid, tint = _star_grid(cols, rows, 1.0, 1.0, stars,
                                lambda b: _ramp_colour(tones, b),
                                spec.get("mesh", 0), 0.55 * spec["spread"])
        return _emit(grid, tint)

    if model == "pair":
        other = _dso_entry(spec["with"])
        if other is None:
            return []
        # The separation and the angle between them are the catalogue's, so
        # the pair sits the way it sits in the eyepiece.
        dx = -(other["ra"] - obj["ra"]) * 15 * math.cos(math.radians(obj["de"]))
        dy = other["de"] - obj["de"]
        rad = spec["radius"]
        stars = (_open_stars(seed, spec["n"], rad, 0.65, -dx / 2, -dy / 2)
                 + _open_stars(other["id"], spec["n"], rad, 0.65,
                               dx / 2, dy / 2))
        hx = abs(dx) / 2 + rad * 1.25
        hy = abs(dy) / 2 + rad * 1.25
        grid, tint = _star_grid(cols, rows, hx, hy, stars,
                                lambda b: _ramp_colour(tones, b),
                                spec.get("mesh", 0), 0.75 * rad)
        return _emit(grid, tint)

    if model == "shell":
        fn = _shell_fn(q, pa, spec["inner"])
    elif model == "bipolar":
        fn = _bipolar_fn(q, pa, spec["sep"], spec["lobe"], spec["inner"])
        reach = spec.get("reach", spec["sep"] + spec["lobe"])
    elif model == "eyes":
        fn = _eyes_fn(q, pa, spec["inner"], spec["eye_u"], spec["eye_v"],
                      spec["eye_r"])
    elif model == "ansae":
        fn = _ansae_fn(q, pa, spec["inner"], spec["knot_u"], spec["knot_r"])
    elif model == "spiral":
        # Defaults for the numbers most spirals share, so an entry in the table
        # carries only what is different about that galaxy.
        fn = _spiral_fn(q, pa, spec.get("arms", 2), spec.get("pitch", 14.0),
                        spec.get("h", 0.34), spec.get("bulge", 0.06),
                        spec.get("bulge_amp", 0.55))
    elif model == "elliptical":
        fn = _elliptical_fn(q, pa, spec.get("re", 0.42))
    elif model == "lens":
        fn = _lens_fn(pa, spec["disc_q"], spec["disc_h"], spec["bulge_q"],
                      spec["bulge_re"], spec["lane_v"], spec["lane_w"])
        q = max(spec["disc_q"], spec["bulge_q"])
    elif model == "globular":
        rc = spec.get("rc") or SHAPLEY_RC[spec["class"]]
        fn, q, pa = _king_fn(rc), 1.0, 0.0
        # How many members resolve, from the concentration itself rather than
        # typed per cluster: a loose cluster shows more of them, and a tight
        # one is mostly the smear in the middle.
        spec = dict(spec, halo=spec.get("halo", int(26 + 60 * rc)))
    else:
        return []

    hx, hy = _ellipse_box(q, pa, reach)
    grid, tint = _field(cols, rows, hx, hy, fn, tones, style,
                        spec.get("stretch", DSO_STRETCH.get(model)),
                        hue=_radial_tint(q, pa) if spec.get("tint") == "radial"
                        else None)

    # A globular resolves into stars at the edges and not in the middle, which
    # is exactly what an eyepiece shows and what the dithered core cannot say
    # on its own. Drawn over the field, sampled from the same profile, so the
    # ones that appear are where the cluster actually has members.
    if model == "globular" and spec.get("halo"):
        W, H = cols * SUBX, rows * SUBY
        scale = min((cols - 2) * SUBX / 2 / hx, (rows - 2) * SUBY / 2 / hy)
        rnd = _seeded(seed + "halo")
        drawn = 0
        for _ in range(spec["halo"] * 12):
            if drawn >= spec["halo"]:
                break
            r = GLOB_RESOLVED_IN + (0.94 - GLOB_RESOLVED_IN) * rnd()
            if rnd() > fn(r, 0.0) ** 0.45:      # follow the cluster's profile
                continue
            a = rnd() * 2 * math.pi
            b = rnd() ** 2.4
            c = int((W / 2 + r * math.cos(a) * scale) // SUBX)
            row = int((H / 2 - r * math.sin(a) * scale) // SUBY)
            drawn += 1
            if (0 <= row < rows and 0 <= c < cols
                    and grid[row][c] in GLOB_OVER):
                # In the cluster's own brightest tone. The stars that resolve
                # out of a globular first are really its red giants, and
                # drawing them amber was tried and dropped: it turns a gold
                # cluster into two colours arguing with each other.
                grid[row][c] = "•"
                tint[row][c] = _ramp_colour(tones, 0.7 + 0.3 * b)
    return _emit(grid, tint)
